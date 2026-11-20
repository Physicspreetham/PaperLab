"""Re-crop diagrams of an already published EJEE collection from the original source pixels.

The published figure is a lossless crop of an archived source image
(`data/archive/ejee/<paper>/<resource>-body.png`). Editing re-renders from that
source, so a crop can grow beyond the old PNG, unlike the generic figure tools.
The first original is kept under `figures/_originals/` for undo.
"""
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import re
import shutil

from PIL import Image

from importer_EJEE import library_store as library
from importer_EJEE.raster_figures import render_reviewed_crop

FIGURE = re.compile(r'[qs]fig\d+\.png')


def _folder(paper_id, number):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', number) or number in ('.', '..'):
        raise ValueError('Invalid question number')
    root = library.store()['outputs'].resolve()
    folder = (root / str(int(paper_id)) / number / 'figures').resolve()
    if root not in folder.parents or not folder.is_dir():
        raise FileNotFoundError('Figures not found for this question')
    return folder


def _provenance(folder):
    path = folder / '_import_provenance.json'
    if not path.is_file():
        raise FileNotFoundError('This question has no recorded source crops to edit.')
    return path, json.loads(path.read_text(encoding='utf-8'))


def _archive_source(paper_id, evidence):
    name = PureWindowsPath(evidence.get('source_body', '')).name
    root = (library.store()['data'] / 'archive' / 'ejee' / str(int(paper_id))).resolve()
    if not name or not root.is_dir():
        return None
    for path in (root / name, *(root / 'batches').glob(f'*/{name}')):
        path = path.resolve()
        if path.is_file() and root in path.parents:
            return path
    return None


def _verified_source(paper_id, evidence):
    path = _archive_source(paper_id, evidence)
    if path is None:
        raise FileNotFoundError('The original source image for this diagram is no longer archived.')
    data = path.read_bytes()
    if evidence.get('source_sha256') and hashlib.sha256(data).hexdigest() != evidence['source_sha256']:
        raise ValueError('The archived source image changed since import.')
    return data


def list_figures(paper_id, number):
    folder = _folder(paper_id, number)
    _, provenance = _provenance(folder)
    rows = []
    for name, evidence in sorted(provenance.items()):
        if not FIGURE.fullmatch(name) or not (folder / name).is_file():
            continue
        source = _archive_source(paper_id, evidence)
        if source is None:
            continue
        with Image.open(source) as image:
            width, height = image.size
        left, top, right, bottom = evidence.get('requested_source_pixel_box') or evidence['source_pixel_box']
        confirmed = evidence.get('confirmed_edge_warnings') or []
        rows.append({'name': name, 'side': 'question' if name[0] == 'q' else 'solution',
                     'box': [left * 1000 / width, top * 1000 / height,
                             (right - left) * 1000 / width, (bottom - top) * 1000 / height],
                     'saved': {'rotation': evidence.get('rotation', 0)},
                     'edge_warnings': evidence.get('edge_warnings', []),
                     'needs_check': bool(confirmed) and not evidence.get('manual_edit'),
                     'edited': bool(evidence.get('manual_edit'))})
    return rows


def source_image(paper_id, number, name):
    folder = _folder(paper_id, number)
    _, provenance = _provenance(folder)
    if not FIGURE.fullmatch(name) or name not in provenance:
        raise FileNotFoundError('Figure not found')
    return _verified_source(paper_id, provenance[name])


def edit_figure(paper_id, number, name, bounds, angle, save, confirm_edges=False):
    left, top, right, bottom = bounds
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1 and -180 <= angle <= 180):
        raise ValueError('Set valid crop edges and rotation.')
    with library._lock:
        folder = _folder(paper_id, number)
        path, provenance = _provenance(folder)
        if not FIGURE.fullmatch(name) or name not in provenance:
            raise FileNotFoundError('Figure not found')
        evidence = provenance[name]
        with Image.open(BytesIO(_verified_source(paper_id, evidence))) as image:
            w, h = image.size
            box = [math.floor(left * w), math.floor(top * h), math.ceil(right * w), math.ceil(bottom * h)]
            entry = {'source_pixel_box': box, 'rotation': angle}
            output, report = render_reviewed_crop(image, entry)
        if save:
            if report['edge_warnings'] and not confirm_edges:
                raise ValueError('Image ink reaches the crop edge. Allow clearance on '
                                 + ', '.join(report['edge_warnings']) + '.')
            original = folder / '_originals' / name
            if not original.exists():
                original.parent.mkdir(exist_ok=True)
                shutil.copy2(folder / name, original)
            buffer = BytesIO()
            output.save(buffer, format='PNG')
            (folder / name).write_bytes(buffer.getvalue())
            updated = {**evidence, **report, 'rotation': angle, 'manual_edit': True,
                       'sha256': hashlib.sha256(buffer.getvalue()).hexdigest(),
                       'method': 'manually re-cropped from archived source pixels'}
            updated.pop('confirmed_edge_warnings', None)
            if report['edge_warnings']:
                updated['confirmed_edge_warnings'] = report['edge_warnings']
            provenance[name] = updated
            path.write_text(json.dumps(provenance, indent=2, ensure_ascii=False), encoding='utf-8')
            review = folder / '_raster_review.json'
            if review.is_file():
                reviews = json.loads(review.read_text(encoding='utf-8'))
                if name in reviews:
                    reviews[name] = {**reviews[name], **updated}
                    review.write_text(json.dumps(reviews, indent=2, ensure_ascii=False), encoding='utf-8')
        buffer = BytesIO()
        output.save(buffer, format='PNG')
        return buffer.getvalue(), report['edge_warnings']


def restore_original(paper_id, number, name):
    with library._lock:
        folder = _folder(paper_id, number)
        original = folder / '_originals' / name
        if not FIGURE.fullmatch(name) or not original.is_file():
            raise FileNotFoundError('No original is stored for this figure.')
        shutil.copy2(original, folder / name)
    return {'restored': name}
