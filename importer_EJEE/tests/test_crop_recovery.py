import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importer


def test_crop_export_matches_out_of_order_replies_by_id():
    first = {'id':'first', 'name':'exact_crop', 'args':{'output_filename':'qfig1.png'}}
    second = {'id':'second', 'name':'exact_crop', 'args':{'output_filename':'qfig2.png'}}
    messages = [
        {'type':'ai', 'tool_calls':[first, second]},
        {'type':'tool', 'tool_call_id':'second', 'content':'Saved final box: [20, 20, 30, 30]'},
        {'type':'tool', 'tool_call_id':'second', 'content':'Error: Duplicate late reply'},
        {'type':'tool', 'tool_call_id':'first', 'content':'Saved final box: [10, 10, 30, 30]'},
    ]
    assert importer.accepted_crop_calls(messages) == {
        'qfig1.png':(first, [10, 10, 30, 30]), 'qfig2.png':(second, [20, 20, 30, 30])}


def test_short_mapped_solution_is_accepted_but_placeholder_is_rejected(tmp_path, monkeypatch):
    placeholder = r'\textit{No solution provided.}'
    monkeypatch.setitem(sys.modules, 'directory_manager', SimpleNamespace(
        get_question_dir=lambda *_: tmp_path, SOLUTION_PLACEHOLDER=placeholder))
    (tmp_path / 'question.tex').write_text('Find $x$.')
    solution = tmp_path / 'solution.tex'
    solution.write_text('Answer: 1) 2\n$x=4/2$')
    assert importer.validate_item(1, '1', True) == []
    solution.write_text('Answer: 1) 2\n' + placeholder)
    assert importer.validate_item(1, '1', True)


def test_review_failure_continues_other_questions_and_resume_does_not_charge_again(tmp_path, monkeypatch):
    items = [{'number': str(n), 'group': str(n), 'solution_rows': []} for n in range(1, 4)]
    importer.dump(tmp_path / 'manifest.json', {'paper_id': 1, 'items': items})
    importer.dump(tmp_path / 'progress.json', {'questions': {}})
    monkeypatch.setitem(sys.modules, 'database', SimpleNamespace(set_paper_status=lambda *a, **k: None,
                                                              mark_paper_archived=lambda *a: None))
    monkeypatch.setattr(importer, 'validate_item', lambda *a: [])
    reviews = []
    monkeypatch.setattr(importer, 'reviewed_crops', lambda cfg: reviews)
    calls = []
    def extract_one(manifest, item, cfg, run):
        calls.append(item['number'])
        if item['number'] == '2' and not reviews:
            raise importer.CropReviewRequired('2: crop loop')
        return {'ok': True}
    monkeypatch.setattr(importer, 'extract_item', extract_one)
    with pytest.raises(importer.CropReviewRequired, match='Questions 2'):
        importer.extract({}, tmp_path)
    assert calls == ['1', '2', '3']
    with pytest.raises(importer.CropReviewRequired):
        importer.extract({}, tmp_path)
    assert calls == ['1', '2', '3']
    reviews.append({'group': '2', 'filename': 'sfig1.png', 'source_pixel_box': [1, 2, 3, 4]})
    importer.extract({}, tmp_path)
    assert calls == ['1', '2', '3', '2']


def test_export_collects_all_clipped_figures_before_stopping_publication(tmp_path, monkeypatch):
    source = tmp_path / 'source.png'
    image = Image.new('RGB', (100, 100), 'white')
    ImageDraw.Draw(image).rectangle((10, 10, 90, 90), fill='black')
    image.save(source)
    items = []
    for number in ('1', '2'):
        items.append({'number': number, 'group': number, 'question_pages': [1],
                      'question_rows': [{'asset_evidence': {'body_png': str(source), 'body_sha256': 'hash'}}]})
        importer.dump(tmp_path / 'traces' / f'{number}.json', {'messages': [
            {'type': 'ai', 'tool_calls': [{'name': 'exact_crop', 'args': {
                'output_filename': 'qfig1.png', 'pdf_path': 'q.pdf', 'page_number': 1}}]},
            {'type': 'tool', 'content': 'Saved final box: [200, 200, 500, 500]'}]})
    importer.dump(tmp_path / 'manifest.json', {'paper_id': 1, 'question_pdf': 'q.pdf', 'items': items})
    monkeypatch.setitem(sys.modules, 'directory_manager', SimpleNamespace(get_question_dir=lambda pid, n: tmp_path / n))
    monkeypatch.setattr(importer, 'reviewed_crops', lambda cfg: [])
    monkeypatch.setattr(importer, 'reuse_reviewed', lambda *a: [])
    with pytest.raises(importer.CropReviewRequired, match='1/qfig1.png, 2/qfig1.png'):
        importer.figures({}, tmp_path)
    report = json.loads((tmp_path / 'crop_reviews.json').read_text())
    assert [r['question'] for r in report] == ['1', '2']
    assert not list(tmp_path.glob('*/figures/qfig1.png'))


def test_manual_crop_requires_confirmation_and_retains_warning_on_resume(tmp_path, monkeypatch):
    import hashlib
    from importer_EJEE import crop_review
    from importer_EJEE.raster_figures import has_unconfirmed_edges, render_reviewed_crop

    source = tmp_path / 'source.png'
    image = Image.new('RGB', (100, 100), 'white')
    ImageDraw.Draw(image).rectangle((10, 10, 90, 90), fill='black')
    image.save(source)
    name = 'qfig1.png'
    row = {'group': 'test', 'source': {
        'body_png': str(source), 'body_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    }}
    monkeypatch.setattr(crop_review, 'review_figures', lambda _: (tmp_path, {('12', name, 12): row}))
    args = ('job', '12', name, 12, (0, 0, 1, .8), 0)
    preview, warnings = crop_review.edit_crop(*args, save=False)
    assert warnings == ['bottom']
    assert not (tmp_path / 'manual_crop_reviews.json').exists()
    with pytest.raises(ValueError, match='bottom'):
        crop_review.edit_crop(*args, save=True)
    saved, _ = crop_review.edit_crop(*args, save=True, confirm_edges=True)
    assert saved == preview
    entry, = json.loads((tmp_path / 'manual_crop_reviews.json').read_text())
    _, report = render_reviewed_crop(image, entry)
    assert report['edge_warnings'] == ['bottom']
    assert not has_unconfirmed_edges(report)


def test_unresolvable_crop_is_auto_accepted_with_best_attempt_and_reused(tmp_path):
    from raster_figures import crop_figure, has_unconfirmed_edges
    # Diagram whose arrow runs straight into neighbouring prose: no box ever clears.
    source = Image.new('RGB', (300, 200), 'white')
    draw = ImageDraw.Draw(source)
    draw.ellipse((40, 40, 110, 110), outline='black', width=3)
    draw.line((110, 75, 300, 75), fill='black', width=3)
    attempts = []
    for box in ([30, 30, 200, 120], [30, 30, 260, 120], [30, 30, 150, 120]):
        _, info = crop_figure(source, box, pixel_box=True)
        assert info['edge_warnings']
        attempts.append(info)
    figure, info = importer.auto_accept_crop(tmp_path, 'g', 'qfig1.png', {'body_sha256': 'abc'}, source, attempts)
    assert not has_unconfirmed_edges(info) and info['edge_warnings']
    saved = json.loads((tmp_path / 'auto_crop_reviews.json').read_text())
    assert saved[0]['auto_accepted'] and saved[0]['source_pixel_box'] == min(reversed(attempts), key=lambda a: len(a['edge_warnings']))['requested_source_pixel_box']
    # same filename later: the entry is replaced, not duplicated
    importer.auto_accept_crop(tmp_path, 'g', 'qfig1.png', {'body_sha256': 'abc'}, source, attempts)
    assert len(json.loads((tmp_path / 'auto_crop_reviews.json').read_text())) == 1
    cfg = {'run_dir': tmp_path.relative_to(importer.ROOT).as_posix()} if str(tmp_path).startswith(str(importer.ROOT)) else None
    if cfg:
        assert any(r.get('auto_accepted') for r in importer.reviewed_crops(cfg))
