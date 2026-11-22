"""EJEE chapter import: read-only source -> mapped image PDFs -> Node 2 -> Node 3.

Usage: python importer.py inspect|prepare|extract|classify|verify --config demo.json
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
from uuid import uuid4

from bootstrap import ROOT, REPO, activate


class CropReviewRequired(RuntimeError):
    """A bounded extraction attempt needs human crop/content review."""


def crop_review_signature(cfg, group):
    crops = [crop for crop in reviewed_crops(cfg) if crop['group'] == group]
    return hashlib.sha256(('source-raster-v8:' + json.dumps(crops, sort_keys=True)).encode()).hexdigest()


AUTO_ACCEPT_AFTER = 3


def auto_accept_crop(run, group, filename, source, image, attempts):
    """Stop a crop loop that cannot reach a clean edge: keep the best attempt.

    Repeated model retries on a diagram that physically abuts prose (e.g. a
    video frame whose arrows run under the statement) never converge and used to
    park the whole import in manual review. The attempt with the fewest
    edge-touching sides is kept, the remaining contact is recorded as confirmed
    (auto_accepted=True keeps it visible/reviewable), and the figure is stored
    as a run-level reviewed crop so figures() and resumes reproduce it exactly.
    """
    from raster_figures import render_reviewed_crop
    index, best = min(enumerate(attempts), key=lambda pair: (len(pair[1]['edge_warnings']), -pair[0]))
    entry = {'group': group, 'filename': filename, 'source_body_sha256': source['body_sha256'],
             'source_pixel_box': best['requested_source_pixel_box'],
             'confirmed_edge_warnings': best['edge_warnings'], 'auto_accepted': True,
             'reason': 'Auto-accepted after ' + str(len(attempts)) + ' crop attempts; source ink still touches '
                       + ', '.join(best['edge_warnings']) + '. Optional manual review.'}
    figure, info = render_reviewed_crop(image, entry)
    path = Path(run) / 'auto_crop_reviews.json'
    records = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []
    same = lambda r: (r['group'], r['filename'], r['source_body_sha256']) == (group, filename, source['body_sha256'])
    dump(path, [r for r in records if not same(r)] + [entry])
    return figure, info


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    try:
        tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
        for attempt in range(6):
            try:
                tmp.replace(path)
                break
            except PermissionError:
                if os.name != 'nt' or attempt == 5:
                    raise
                time.sleep(0.1 * (2 ** attempt))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except PermissionError:
                pass


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def source_connect(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    conn.execute('BEGIN')  # consistent snapshot including the live WAL
    return conn


def load_config(path):
    path = Path(path).resolve()
    cfg = json.loads(path.read_text(encoding='utf-8'))
    for key in ('source_db', 'asset_root', 'original_pdf', 'selection_snapshot'):
        if cfg.get(key) and not Path(cfg[key]).is_absolute():
            cfg[key] = str((path.parent / cfg[key]).resolve())
    run = (ROOT / cfg['run_dir']).resolve()
    if ROOT not in run.parents or REPO == run or ROOT / 'reference' in run.parents or (REPO != ROOT.parent and REPO in run.parents):
        raise ValueError('Invalid run directory')
    return cfg, run


def ident(name):
    return '"' + name.replace('"', '""') + '"'


def inspect_source(cfg, run):
    with source_connect(cfg['source_db']) as c:
        tables = []
        for row in c.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"):
            tables.append({'name': row['name'], 'sql': row['sql'],
                           'count': c.execute('SELECT count(*) FROM ' + ident(row['name'])).fetchone()[0],
                           'columns': [dict(v) for v in c.execute('PRAGMA table_info(' + ident(row['name']) + ')')]})
        dump(run / 'source_schema.json', tables)
        books = [dict(r) for r in c.execute('SELECT source,part,count(*) count FROM resources GROUP BY source,part ORDER BY source,part')]
        dump(run / 'source_inventory.json', books)
    write_mapping(tables, run)
    print(f'Inspected {len(tables)} tables; wrote schema, inventory and column mapping.', flush=True)


RESOURCE_MAP = {
    'id': 'Stable resource provenance; group membership and resume identity.',
    'uid': 'Preserved provenance; not a PaperLab question ID.',
    'grp': 'Exact question–answer join WITH source. Never match by similar titles.',
    'part': 'q -> question pages; sol -> ordered solution pages. Other roles require explicit handling.',
    'source': 'Exact textbook name -> papers.source_institute.',
    'title': 'Source label, original numbering and continuation-order evidence; preserved in manifest.',
    'position': 'Order evidence within a group; numeric continuation titles take precedence.',
    'file_name': 'Primary source asset under uploads; hash and crop losslessly.',
    'file_alt': 'Preserve provenance only; do not silently substitute an altered image.',
    'file_orig': 'Preserved original filename for traceability.',
    'mime': 'Asset validation/provenance; image decoded by Pillow.',
    'print_meta': 'Use box as normalized BODY bounds only; qbox is a fallback. keys/mask/qn are not diagram boxes. Preserve entire JSON.',
    'question': 'Existing transcription as auxiliary evidence only; image remains authoritative.',
    'answer': 'Existing answer evidence, checked against source; never synthesize a new answer.',
    'solution': 'Existing solution evidence; map with group images, never generate a worked solution.',
    'topic_id': 'Retain original node ancestry in provenance ONLY. Never seed PaperLab topics.',
    'difficulty': 'Provenance ONLY; PaperLab Node 3 reclassifies from imported TeX.',
    'tags': 'Provenance ONLY; no automatic topic assignment from EJEE.',
    'qtype': 'Source format evidence for Node 2; never map subjective to numeric automatically.',
    'type': 'Provenance and source format evidence; target schema has no subjective code, use unknown if needed.',
    'src_doc': 'Preserve locator; not a PDF path unless independently resolved.',
    'exam': 'Preserve only: textbooks use exam_type=Textbook, not historical exam labels.',
    'year': 'Preserve only: do not invent paper_date from textbook publication or import year.',
    'shift': 'Preserve only: no shift for chapter papers.',
}


def write_mapping(tables, run):
    used = {'resources', 'nodes', 'resource_crops', 'source_documents', 'resource_transcripts'}
    out = ['# EJEE column disposition', '',
           'Generated from the actual source schema. No source table or row is deleted. “Omitted” means excluded from the target PaperLab database; selected resource rows retain every original column in manifest.json. Student data is not exported.', '',
           'The current database has no tb_chapter table. Textbook chapter numbers are decoded from an explicit configured grp pattern; nodes is the teaching taxonomy and must not be substituted for book chapter order.', '']
    for table in tables:
        name = table['name']
        out += [f'## `{name}` ({table["count"]:,} rows)', '', '| Column | Disposition and reason |', '|---|---|']
        for col in table['columns']:
            field = col['name']
            if name == 'resources':
                desc = RESOURCE_MAP.get(field, 'Preserved in selected resource provenance; omitted from PaperLab because it is EJEE UI/editor state, not archival question content or fresh extraction statistics.')
            elif name == 'nodes':
                desc = 'Preserved in selected resource ancestry. Original teaching classification is provenance only; Node 3 supplies all target classification.'
            elif name == 'resource_crops':
                desc = 'Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records.'
            elif name == 'source_documents':
                desc = 'Preserve selected crop-source linkage and locator/hash. Resolve and validate asset before coordinate reuse.'
            elif name == 'resource_transcripts':
                desc = 'Preserve selected versions and review/hold metadata as evidence; no unreviewed text replaces source pixels.'
            else:
                desc = 'Omitted from target: ' + (
                    'SQLite internal sequence; target generates its own IDs.' if name == 'sqlite_sequence' else
                    'EJEE worksheet composition, not textbook question ownership.' if name in {'papers', 'paper_items'} else
                    'Handwritten annotation state; not printed source content.' if name == 'strokes' else
                    'Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope.')
            out.append(f'| `{field}` | {desc} |')
        out.append('')
    (run / 'EJEE_COLUMN_MAPPING.md').write_text('\n'.join(out), encoding='utf-8')


def part_order(row):
    m = re.search(r'\((\d+)\s*/\s*\d+\)', row['title'] or '')
    return (int(m.group(1)) if m else 1, row['position'], row['id'])


def body_image(row, asset_root):
    from PIL import Image
    path = (Path(asset_root) / row['file_name']).resolve()
    base = Path(asset_root).resolve()
    if base not in path.parents or not path.is_file():
        raise ValueError(f'Missing/unsafe source image for resource {row["id"]}')
    with Image.open(path) as original:
        im = original.convert('RGB')
    meta = json.loads(row.get('print_meta') or '{}')
    box = meta.get('box') or meta.get('qbox')
    if not box or len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
        raise ValueError(f'No valid body box for resource {row["id"]}; explicit adapter required')
    import math
    px = [math.floor(box[0]*im.width), math.floor(box[1]*im.height),
          math.ceil(box[2]*im.width), math.ceil(box[3]*im.height)]
    return im.crop(px), {'path': str(path), 'sha256': sha(path), 'body_box': box, 'body_box_px': px, 'original_size': list(im.size)}


def prepare(cfg, run):
    import fitz
    import database
    if (run / 'manifest.json').exists():
        raise ValueError('Run already prepared; use extract/classify to resume, or choose a new run_dir')
    if cfg.get('selection_snapshot'):
        snapshot = json.loads(Path(cfg['selection_snapshot']).read_text(encoding='utf-8'))
        items = snapshot['items']
        if not items or any(not item['question_rows'] for item in items):
            raise ValueError('Selected question snapshot is empty or invalid')
    else:
        pattern = re.compile(cfg['group_pattern'])
        with source_connect(cfg['source_db']) as c:
            groups = defaultdict(list)
            for row in c.execute('SELECT * FROM resources WHERE source=? ORDER BY position,id', (cfg['book_source'],)):
                row = dict(row)
                m = pattern.fullmatch(row['grp'] or '')
                if m and m['chapter'] == str(cfg['chapter']) and (not cfg.get('groups') or row['grp'] in cfg['groups']):
                    groups[row['grp']].append(row)
            if not groups:
                raise ValueError('No resources match the configured source and chapter')
            nodes = {r['id']: dict(r) for r in c.execute('SELECT * FROM nodes')}
            items = []
            for grp, rows in sorted(groups.items(), key=lambda pair: int(pattern.fullmatch(pair[0])['number'])):
                if any(r['part'] not in ('q', 'sol') for r in rows):
                    raise ValueError(f'Unsupported part in {grp}; explicit adapter required')
                qrows = sorted([r for r in rows if r['part'] == 'q'], key=part_order)
                srows = sorted([r for r in rows if r['part'] == 'sol'], key=part_order)
                if not qrows:
                    raise ValueError(f'Orphan solution group {grp}')
                if len(qrows) > 1 and not all(re.search(r'\(\d+/\d+\)', r['title']) for r in qrows):
                    raise ValueError(f'Ambiguous multiple question rows in {grp}')
                rid = [r['id'] for r in rows]
                placeholders = ','.join('?' for _ in rid)
                crops = [dict(r) for r in c.execute(f'SELECT * FROM resource_crops WHERE resource_id IN ({placeholders})', rid)]
                transcripts = [dict(r) for r in c.execute(f'SELECT * FROM resource_transcripts WHERE resource_id IN ({placeholders})', rid)]
                ancestry = {}
                for r in rows:
                    lineage, n, seen = [], r['topic_id'], set()
                    while n in nodes and n not in seen:
                        seen.add(n); lineage.append(nodes[n]); n = nodes[n]['parent_id']
                    ancestry[str(r['id'])] = lineage
                items.append({'group': grp, 'number': str(int(pattern.fullmatch(grp)['number'])),
                              'source_number': f'{cfg["chapter"]}.{pattern.fullmatch(grp)["number"]}',
                              'question_rows': qrows, 'solution_rows': srows, 'original_ancestry': ancestry,
                              'resource_crops': crops, 'resource_transcripts': transcripts,
                              'question_pages': [], 'solution_pages': []})
    run.mkdir(parents=True, exist_ok=True)
    assets = run / 'sources'; assets.mkdir(exist_ok=True)
    qpdf, spdf = fitz.open(), fitz.open()
    for item in items:
        for side, doc in [('question', qpdf), ('solution', spdf)]:
            for row in item[f'{side}_rows']:
                im, evidence = body_image(row, cfg['asset_root'])
                buffer = io.BytesIO(); im.save(buffer, format='PNG')
                png = assets / f'{row["id"]}-body.png'; png.write_bytes(buffer.getvalue())
                page = doc.new_page(width=im.width * 72 / 200, height=im.height * 72 / 200)
                page.insert_image(page.rect, stream=buffer.getvalue())
                row['asset_evidence'] = {**evidence, 'body_png': str(png), 'body_sha256': sha(png)}
                item[f'{side}_pages'].append(len(doc))
    qpath = assets / 'questions.pdf'; spath = assets / 'solutions.pdf'
    qpdf.save(qpath, deflate=True)
    if len(spdf): spdf.save(spath, deflate=True)
    nq, ns = len(qpdf), len(spdf); qpdf.close(); spdf.close()
    database.init_db(); database.init_topics()
    pid = database.register_paper(str(qpath), str(spath) if ns else None)
    with database.get_connection() as c:
        c.execute('UPDATE papers SET paper_name=?,exam_type=?,source_institute=?,q_start=1,q_end=?,s_start=?,s_end=?,status=? WHERE id=?',
                  (cfg.get('collection_name') or f'{cfg["book_source"]} — Chapter {cfg["chapter"]}: {cfg["chapter_title"]}', 'EJEE collection' if cfg.get('selection_snapshot') else 'Textbook', cfg['book_source'], nq, 1 if ns else None, ns or None, 'uploaded', pid))
    commit = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
    manifest = {'schema': 'ejee-paperlab-import/1', 'paper_id': pid, 'config': cfg,
                'upstream_commit': commit, 'question_pdf': str(qpath), 'solution_pdf': str(spath) if ns else None,
                'question_pdf_sha256': sha(qpath), 'solution_pdf_sha256': sha(spath) if ns else None,
                'items': items}
    dump(run / 'manifest.json', manifest)
    dump(run / 'progress.json', {'questions': {}, 'node3': {}})
    print(f'Prepared paper {pid}: {len(items)} questions, {nq} question pages, {ns} solution pages.', flush=True)


def clean_message(msg):
    content = msg.content
    if isinstance(content, list):
        content = [{**b, 'image_url': '[image omitted from log]'} if isinstance(b, dict) and b.get('type') == 'image_url' else b for b in content]
    return {'type': msg.type, 'content': content, 'tool_calls': getattr(msg, 'tool_calls', None),
            'tool_call_id': getattr(msg, 'tool_call_id', None)}


def source_heading(item):
    title = item['question_rows'][0]['title'].split(' · ', 1)[-1]
    return re.sub(r'\s*\(Exercise\)\s*$', '', title).strip()


def strip_problem_heading(tex, heading):
    """Remove a verified book heading, including inline headings, never the stem."""
    match = re.match(r'^\s*\d+(?:\.\d+)*[.)]?\s+', tex)
    offset = match.end() if match else 0
    rest = tex[offset:]
    normalize = lambda s: s.replace('’', "'").replace('‘', "'").strip()
    end = None
    if rest.startswith('\\textbf{'):
        depth, start = 1, len('\\textbf{')
        for i in range(start, len(rest)):
            if rest[i] == '{': depth += 1
            elif rest[i] == '}': depth -= 1
            if depth == 0:
                label = rest[start:i]
                label = re.sub(r'\$(?:\\ast|\\star|\*|∗|\s)+\$|[∗*]+', '', label)
                if normalize(label) == normalize(heading): end = i + 1
                break
    else:
        if normalize(rest[:len(heading)]) == normalize(heading):
            tail = rest[len(heading):]
            if not tail or tail[0].isspace() or tail[0] in '*∗': end = len(heading)
    if end is None: return tex
    body = rest[end:].lstrip()
    body = re.sub(r'^(?:\$(?:\\ast|\\star|\*|∗|\s)+\$|`?[∗*]+`?)\s*', '', body)
    return body.lstrip() if body.strip() else tex


def normalize_rendering(tex):
    """Keep valid TeX while targeting the unchanged PaperLab/KaTeX bridge."""
    tex = re.sub(r'\\eqno\s*\(([^)\n]+)\)', lambda m: r'\tag{' + m[1] + '}', tex)
    escapes = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}',
               '$': r'\$', '%': r'\%', '#': r'\#', '&': r'\&', '_': r'\_',
               '^': r'\textasciicircum{}', '~': r'\textasciitilde{}'}

    def program(match):
        # The native renderer strips verbatim environments, then Markdown
        # interprets code asterisks as emphasis and collapses line breaks.
        # A math array preserves rows and protects literal monospace text in
        # both KaTeX and LaTeX without requiring a PaperLab source change.
        rows = []
        for line in match[1].strip('\r\n').splitlines():
            code, marker, comment = line.partition('#')
            literal = lambda s: ''.join(escapes.get(ch,ch) for ch in s)
            rows.append(r'\texttt{' + literal(code.rstrip()) + '} & ' +
                        r'\texttt{' + literal(('#' + comment) if marker else '') + '}')
        return '\n\n$$\n' + r'\begin{array}{ll}' + '\n' + (' \\\\\n'.join(rows)) + '\n' + r'\end{array}' + '\n$$\n\n'
    return re.sub(r'\\begin\{verbatim\}\s*\n?(.*?)\\end\{verbatim\}', program, tex, flags=re.DOTALL)


def figure_references(qdir):
    return {name for side in ('question', 'solution')
            if (path := qdir / f'{side}.tex').is_file()
            for name in re.findall(r'\\includegraphics(?:\[[^\]]*\])?\{figures/([^}]+)\}', path.read_text(encoding='utf-8'))}


def validate_item(pid, number, has_solution):
    from raster_figures import has_unconfirmed_edges
    import directory_manager
    qdir = directory_manager.get_question_dir(pid, number)
    errors = []
    refs = set()
    for side, prefix in [('question', 'qfig'), ('solution', 'sfig')]:
        path = qdir / f'{side}.tex'
        if not path.is_file() or not path.read_text(encoding='utf-8').strip():
            errors.append(f'{side}.tex missing'); continue
        text = path.read_text(encoding='utf-8')
        if '[UNREADABLE]' in text: errors.append(f'{side}: unreadable content requires review')
        if side == 'solution' and has_solution:
            _, _, body = text.strip().partition('\n')
            if not body.strip() or body.strip() == directory_manager.SOLUTION_PLACEHOLDER:
                errors.append('Mapped solution was replaced by placeholder/empty text')
        for file in re.findall(r'\\includegraphics(?:\[[^\]]*\])?\{figures/([^}]+)\}', text):
            if not re.fullmatch(prefix + r'\d+\.png', file): errors.append(f'Invalid side/filename: {file}')
            if not (qdir / 'figures' / file).is_file(): errors.append(f'Missing figure {file}')
            refs.add(file)
    for path in (qdir / 'figures').glob('*.png'):
        if path.name not in refs: errors.append(f'Unreferenced figure {path.name}')
    review_path=qdir/'figures'/'_raster_review.json'
    if review_path.exists():
        for filename,review in json.loads(review_path.read_text()).items():
            if filename in refs and has_unconfirmed_edges(review):
                errors.append(filename+': re-crop edge-touching source ink at '+', '.join(review['edge_warnings']))
    return errors


def extract_item(manifest, item, cfg, run):
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from langgraph.types import Command
    import database
    import tools_extractor as tools
    from raster_figures import crop_figure, nearby_clear_cuts, reviewed_source
    from PIL import Image
    from llm import get_llm, invoke_with_retry
    import directory_manager
    pid, number = manifest['paper_id'], item['number']
    key_only = cfg.get('content_mode') == 'key'
    # These canvases are 200 dpi raster sources, unlike upstream vector PDFs.
    # Keep its crop algorithms but do not save a 600 dpi upsample of the pixels.
    tools._SAVE_DPI = 200
    selected = [tools.get_page_image, tools.assisted_crop, tools.exact_crop, tools.submit_question, tools.submit_solution]
    optimized=cfg.get('extractor_mode','mapped-pair')!='legacy-pdf'
    if optimized:
        from efficient_extractor import build_tools, INSTRUCTIONS, PROFILE
        selected=build_tools(tools,manifest,item)
    by_name = {t.name: t for t in selected}
    native = (REPO / 'prompts' / 'extractor_prompt.md').read_text(encoding='utf-8')
    override = (ROOT / 'prompts' / 'mapped_extractor.md').read_text(encoding='utf-8')
    if optimized:override+='\n\n'+INSTRUCTIONS
    if key_only:
        override += (
            '\n\nQUESTIONS + KEY MODE overrides every instruction to transcribe a worked solution. '
            'Transcribe the complete question and its diagrams. In solution_latex supply exactly one '
            'line in the normal Answer format containing only the explicit source answer key. '
            'Use source_answers first. If absent, look for an explicit final answer in the supplied '
            'source text and images. Never derive an answer or include reasoning or solution figures. '
            'If no explicit key exists, submit exactly no_solution_found.'
        )
    allowed = {manifest['question_pdf']: item['question_pages']}
    if manifest['solution_pdf']: allowed[manifest['solution_pdf']] = item['solution_pages']
    source_answers = [r['answer'] for r in item['question_rows'] if r['answer']]
    metadata = {'paper_id': pid, 'question_number': number, 'source_label': item['question_rows'][0]['title'],
                'allowed_pages': allowed, 'has_mapped_solution': bool(item['solution_rows']),
                'source_answers': source_answers,
                'source_question_text': [r['question'] for r in item['question_rows'] if r['question']],
                'source_solution_text': [r['solution'] for r in item['question_rows'] if r['solution']
                                         and not (key_only and source_answers)],
                'source_qtype': [r['qtype'] for r in item['question_rows'] if r['qtype']]}
    metadata['reviewed_diagrams'] = reuse_reviewed(cfg, item, pid, number)
    reviewed_filenames = {diagram['filename'] for diagram in metadata['reviewed_diagrams']}
    messages = [SystemMessage(content=native + '\n\n' + override), HumanMessage(content=json.dumps(metadata, ensure_ascii=False))]
    # Existing resource mapping supplies the images immediately; no searching/indexing calls.
    for side in ['question', 'solution']:
        if side == 'solution' and key_only and metadata['source_answers']:
            continue
        for row, page in zip(item[f'{side}_rows'], item[f'{side}_pages']):
            messages.append(HumanMessage(content=[{'type': 'text', 'text': f'{side.upper()} page {page}, resource {row["id"]}; already body-cropped, no key-sheet assumption.'},
                                                    tools.img_block(row['asset_evidence']['body_png'], tools.PAGE_PX)]))
    llm = get_llm().bind_tools(selected, parallel_tool_calls=False)
    saved = set(); t0 = time.time()
    log = run / 'traces' / f'{number}.json'
    max_turns=min(cfg.get('max_turns_per_question',36),cfg.get('cost_max_turns_per_question',12)) if optimized else cfg.get('max_turns_per_question',36)
    crop_attempts = defaultdict(int)
    attempt_log = defaultdict(list)
    clear_figures = set()
    last_box, same_box = {}, defaultdict(int)
    # Reserve a few extra calls for figure-heavy questions that are making
    # progress. Repeated crops of the same filename do not earn more calls.
    max_extra_turns = 6 if optimized else 0
    calls_made = 0
    for turn in range(max_turns + max_extra_turns):
        extra_turns = min(max_extra_turns, max(0, len(clear_figures) - 2))
        if turn >= max_turns + extra_turns:
            break
        response = invoke_with_retry(llm, messages)
        calls_made += 1
        usage = response.usage_metadata or {}
        database.log_token_usage(pid, 'extractor', input_tokens=usage.get('input_tokens', 0),
                                 cache_read=(usage.get('input_token_details') or {}).get('cache_read', 0),
                                 output_tokens=usage.get('output_tokens', 0),
                                 reasoning_tokens=(usage.get('output_token_details') or {}).get('reasoning', 0))
        messages.append(response)
        previews = []
        for call in response.tool_calls or []:
            args = dict(call['args']); name = call['name']
            if name in ('assisted_crop', 'exact_crop'):
                if args.get('output_filename') in reviewed_filenames:
                    messages.append(ToolMessage(
                        content='The verified source crop already exists. Reference it without recropping.',
                        tool_call_id=call['id']))
                    continue
                key = (args.get('output_filename', ''), args.get('page_number'),
                       tuple(args.get(k) for k in ('x', 'y', 'width', 'height')))
                crop_attempts[key] += 1
                if crop_attempts[key] > 2:
                    dump(log, {'turns': turn+1, 'messages': [clean_message(m) for m in messages]})
                    raise CropReviewRequired(f'{number}/{key}: repeated crop attempts; review the source before retrying')
            try:
                if name not in by_name: raise ValueError('Tool not allowed')
                if name == 'submit_question':
                    args['latex_content'] = strip_problem_heading(args['latex_content'], source_heading(item))
                if name in ('submit_question', 'submit_solution'):
                    if key_only and name == 'submit_solution':
                        args['latex_content'] = key_transcription(args['latex_content'], bool(source_answers))
                    args['latex_content'] = normalize_rendering(args['latex_content'])
                if name=='submit_pair':
                    if key_only:
                        args['solution_latex'] = key_transcription(args['solution_latex'], bool(source_answers))
                    args['question_latex']=normalize_rendering(strip_problem_heading(args['question_latex'],source_heading(item)))
                    args['solution_latex']=normalize_rendering(args['solution_latex'])
                if 'paper_id' in args and args['paper_id'] != pid: raise ValueError('Wrong paper ID')
                if 'question_number' in args and str(args['question_number']) != number: raise ValueError('Wrong question number')
                if 'pdf_path' in args:
                    if args['pdf_path'] not in allowed or args.get('page_number') not in allowed[args['pdf_path']]:
                        raise ValueError('PDF/page is outside this mapped question')
                if name in ('assisted_crop', 'exact_crop'):
                    prefix = 'qfig' if args['pdf_path'] == manifest['question_pdf'] else 'sfig'
                    if key_only and prefix == 'sfig':
                        raise ValueError('Only question diagrams are allowed in Questions + Key mode')
                    if not re.fullmatch(prefix + r'\d+\.png', args.get('output_filename', '')):
                        raise ValueError('Use the correct side and stable qfigN.png/sfigN.png filename')
                if optimized and name in ('assisted_crop', 'exact_crop'):
                    # Both mapped crop tools operate on the original source canvas.
                    # Do not invoke PDF crop heuristics or their conflicting feedback.
                    from raster_figures import clear_crop_edges, crop_figure as probe_crop, snap_to_ink_blobs, snap_within_reach
                    side = 'question' if args['pdf_path'] == manifest['question_pdf'] else 'solution'
                    idx = item[f'{side}_pages'].index(args['page_number'])
                    body = item[f'{side}_rows'][idx]['asset_evidence']['body_png']
                    box = [args[k] for k in ('x', 'y', 'width', 'height')]
                    with Image.open(body) as source:
                        # Prefer whole ink blobs around the model's rough box; they cannot clip a
                        # diagram or brush a neighbouring paragraph. Fall back to edge clearing.
                        x, y, w, h = box
                        rough = [max(0, math.floor(x*source.width/1000)), max(0, math.floor(y*source.height/1000)),
                                 min(source.width, math.ceil((x+w)*source.width/1000)),
                                 min(source.height, math.ceil((y+h)*source.height/1000))]
                        snapped = snap_to_ink_blobs(source, rough) if rough[2] > rough[0] and rough[3] > rough[1] else None
                        if snapped and not snap_within_reach(snapped, rough):
                            snapped = None  # blob bridged into neighbouring text; trust the model's box
                        if snapped and not probe_crop(source, snapped, pixel_box=True)[1]['edge_warnings']:
                            box = [snapped[0]*1000/source.width, snapped[1]*1000/source.height,
                                   (snapped[2]-snapped[0])*1000/source.width, (snapped[3]-snapped[1])*1000/source.height]
                        else:
                            box = clear_crop_edges(source, box)
                    result = 'Saved ' + args['output_filename'] + '. Original source-pixel crop. final box: ' + json.dumps(box)
                elif name in ('get_page_image', 'assisted_crop', 'exact_crop'):
                    result = by_name[name].invoke({'name': name, 'args': args, 'id': call['id'], 'type': 'tool_call'})
                else:
                    result = by_name[name].invoke(args)
                replies = result.update.get('messages', []) if isinstance(result, Command) else [
                    ToolMessage(content=str(result), tool_call_id=call['id'])]
                if name in ('assisted_crop','exact_crop'):
                    reply='\n'.join(m.content for m in replies if isinstance(m,ToolMessage) and isinstance(m.content,str)) or str(result)
                    final=re.search(r'final box: (\[[^\]]+\])',reply)
                    if final and reply.startswith('Saved '):
                        side='question' if args['pdf_path']==manifest['question_pdf'] else 'solution'
                        idx=item[f'{side}_pages'].index(args['page_number'])
                        body=item[f'{side}_rows'][idx]['asset_evidence']['body_png']
                        qdir=directory_manager.get_question_dir(pid,number)
                        dest=qdir/'figures'/args['output_filename']
                        with Image.open(body) as im:
                            preview, review = crop_figure(im, json.loads(final[1]))
                            cuts = nearby_clear_cuts(im, review) if review['edge_warnings'] else {}
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        preview.save(dest,format='PNG')
                        review_path=qdir/'figures'/'_raster_review.json'
                        reviews=json.loads(review_path.read_text()) if review_path.exists() else {}
                        reviews[args['output_filename']]=review
                        auto_note = ''
                        if review['edge_warnings']:
                            attempt_log[args['output_filename']].append(review)
                            if len(attempt_log[args['output_filename']]) >= AUTO_ACCEPT_AFTER:
                                with Image.open(body) as im:
                                    preview, review = auto_accept_crop(run, item['group'], args['output_filename'],
                                        item[f'{side}_rows'][idx]['asset_evidence'], im, attempt_log[args['output_filename']])
                                preview.save(dest, format='PNG')
                                reviews[args['output_filename']] = review
                                reviewed_filenames.add(args['output_filename'])
                                cuts = {}
                                auto_note = ('AUTO-ACCEPTED after repeated attempts: the best crop is kept and flagged for optional review. '
                                             'It is final; do not crop this figure again. Reference it and submit the transcription now.')
                        dump(review_path,reviews)
                        if not review['edge_warnings'] or auto_note:
                            clear_figures.add(args['output_filename'])
                        note=('RE-CROP REQUIRED: source ink touches '+', '.join(review['edge_warnings'])+'. The automatic search found no nearby clear cut on those edges. Inspect the full source image and move the failing edge to a visible blank gap. Keep the complete diagram and exclude prose.' if review['edge_warnings'] else 'Raster edges have clearance. Compare with the full source: exclude statement fragments and include every dimension label. If correct, submit the transcription now.')
                        if review['edge_warnings'] and not auto_note:
                            from raster_figures import figure_candidates
                            with Image.open(body) as im:
                                note += (' Detected ink blocks (x, y, width, height on the 0-1000 scale; a block may be '
                                         'prose, not a diagram): ' + json.dumps(figure_candidates(im)) + '.')
                        if auto_note:
                            note = auto_note
                        if cuts:
                            note += (' Blank cut candidates (absolute normalized x or y, 0–1000): '
                                     + json.dumps(cuts) + '. Choose only a cut that keeps every diagram element. '
                                     'For right/bottom cuts, calculate width/height from the chosen absolute edge.')
                        fingerprint = tuple(round(v) for v in json.loads(final[1]))
                        fname = args['output_filename']
                        same_box[fname] = same_box[fname] + 1 if last_box.get(fname) == fingerprint else 0
                        last_box[fname] = fingerprint
                        if same_box[fname] and not auto_note:
                            if not review['edge_warnings']:
                                clear_figures.add(fname)
                            note = ('NO CHANGE: your adjusted numbers produced exactly the same final box as the previous '
                                    'attempt, so recropping again will not help. ' + (
                                    'This crop has clean edges: accept it, reference it and submit the transcription now.'
                                    if not review['edge_warnings'] else
                                    'Choose a clearly different box (use the detected blocks / blank cuts above) or submit with this crop.'))
                        if optimized:
                            from efficient_extractor import prune_old_preview
                            messages=[m.model_copy(update={'content':prune_old_preview(m.content,args['output_filename'])}) if isinstance(m,HumanMessage) else m for m in messages]
                        previews.append(HumanMessage(content=[{'type':'text','text':args['output_filename']+': '+note},tools.img_block(dest,tools.CROP_PX)]))
                messages.extend(m for m in replies if not isinstance(m, HumanMessage))
                previews.extend(m for m in replies if isinstance(m, HumanMessage) and name not in ('assisted_crop', 'exact_crop'))
                if name in ('submit_question', 'submit_solution') and str(result) == 'saved':
                    saved.add(name)
                if name == 'submit_pair' and str(result) == 'saved':
                    saved.update(('submit_question', 'submit_solution'))
            except Exception as exc:
                messages.append(ToolMessage(content=f'Error: {type(exc).__name__}: {exc}', tool_call_id=call['id']))
        messages.extend(previews)
        dump(log, {'profile':PROFILE if optimized else 'legacy-pdf','turns': turn+1, 'elapsed_sec': time.time()-t0, 'messages': [clean_message(m) for m in messages]})
        if len(saved) == 2:
            qdir = directory_manager.get_question_dir(pid, number)
            referenced = figure_references(qdir)
            for path in (qdir / 'figures').glob('*.png'):
                if re.fullmatch(r'[qs]fig\d+\.png', path.name) and path.name not in referenced and path.name not in reviewed_filenames:
                    retired = run / 'unused_crops' / number / path.name
                    retired.parent.mkdir(parents=True, exist_ok=True)
                    path.replace(retired)
            errors = validate_item(pid, number, bool(item['solution_rows']) and not key_only)
            if not errors: return {'ok': True, 'profile':PROFILE if optimized else 'legacy-pdf','turns': turn+1, 'elapsed_sec': round(time.time()-t0, 2)}
            messages.append(HumanMessage(content='Completion check failed; correct with same IDs: ' + '; '.join(errors)))
        elif not response.tool_calls:
            messages.append(HumanMessage(content='Finish this mapped item with submit_pair.' if optimized else 'Finish this mapped item by calling both submit_question and submit_solution. Do not invent missing solutions.'))
    raise CropReviewRequired(f'{number}: {calls_made}-call cost limit reached; trace and usage saved for crop/content review. No incomplete question is published.')


def extract(cfg, run):
    import database
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    progress = json.loads((run / 'progress.json').read_text(encoding='utf-8'))
    pid = manifest['paper_id']; t0 = time.time()
    database.set_paper_status(pid, 'extracting')
    needs_review = []
    for item in manifest['items']:
        number = item['number']
        signature = crop_review_signature(cfg, item['group'])
        previous = progress['questions'].get(number, {})
        if previous.get('needs_review') and previous.get('review_signature') == signature:
            needs_review.append(number)
            continue
        has_solution = bool(item['solution_rows']) and cfg.get('content_mode') != 'key'
        if progress['questions'].get(number, {}).get('ok') and not validate_item(pid, number, has_solution):
            continue
        print(f'Extracting {number} ({len(item["solution_rows"])} solution parts)', flush=True)
        try:
            progress['questions'][number] = extract_item(manifest, item, cfg, run)
        except CropReviewRequired as exc:
            progress['questions'][number] = {'ok': False, 'needs_review': True,
                'review_signature': signature, 'error': str(exc)}
            needs_review.append(number)
        except Exception as exc:
            progress['questions'][number] = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
            database.set_paper_status(pid, 'failed', progress['questions'][number]['error'], time.time()-t0)
            dump(run / 'progress.json', progress)
            raise
        dump(run / 'progress.json', progress)
        print(f'{number}: {progress["questions"][number]}', flush=True)
    if needs_review:
        message = 'Questions ' + ', '.join(needs_review) + ': crop/content review required. Saved conversions will be reused. Check the source diagrams and update the reviewed crops for these questions before resuming.'
        database.set_paper_status(pid, 'failed', message, time.time()-t0)
        raise CropReviewRequired(message)
    elapsed = sum(r.get('elapsed_sec', 0) for r in progress['questions'].values())
    database.set_paper_status(pid, 'done', elapsed_sec=elapsed)
    database.mark_paper_archived(pid)
    print(f'Extraction complete: {len(manifest["items"])} questions. Run classify next.', flush=True)


def valid_classification(report):
    # Upstream explicitly permits no matching topic with a new-topic suggestion.
    assignment = report.get('assignment') or {}
    reviewed_gap = assignment.get('status') == 'needs_review' and assignment.get('reason')
    return bool(report.get('difficulty') and (report.get('codes') or report.get('suggestion') or reviewed_gap) and not report.get('errors'))


def reviewed_crops(cfg):
    explicit=json.loads((ROOT / cfg['reviewed_crops']).read_text(encoding='utf-8')) if cfg.get('reviewed_crops') else []
    local = ROOT / cfg['run_dir'] / 'manual_crop_reviews.json' if cfg.get('run_dir') else None
    if local and local.is_file():
        manual = json.loads(local.read_text(encoding='utf-8'))
        keys = {(r['group'], r['filename'], r['source_body_sha256']) for r in manual}
        explicit = manual + [r for r in explicit if (r['group'], r['filename'], r['source_body_sha256']) not in keys]
    auto = ROOT / cfg['run_dir'] / 'auto_crop_reviews.json' if cfg.get('run_dir') else None
    if auto and auto.is_file():
        keys = {(r['group'], r['filename'], r['source_body_sha256']) for r in explicit}
        explicit = explicit + [r for r in json.loads(auto.read_text(encoding='utf-8'))
                               if (r['group'], r['filename'], r['source_body_sha256']) not in keys]
    bundled=ROOT/'reviewed_figure_crops.json'
    defaults=json.loads(bundled.read_text(encoding='utf-8')) if bundled.exists() else []
    keys={(r['group'],r['filename'],r['source_body_sha256']) for r in explicit}
    return explicit+[r for r in defaults if (r['group'],r['filename'],r['source_body_sha256']) not in keys]


def key_transcription(value, has_source_answer):
    value = value.strip()
    if value == 'no_solution_found' and not has_source_answer:
        return value
    if (len(value.splitlines()) != 1 or '\\includegraphics' in value
            or not re.fullmatch(r'\\textbf\{Answer:\s*[^\n]+\}', value, re.I)):
        raise ValueError('Submit only the source Answer line or no_solution_found')
    return value


def reuse_reviewed(cfg, item, pid, number):
    """Reuse only reviewed isolated rectangles whose source pixel hash still matches."""
    from PIL import Image
    from raster_figures import has_unconfirmed_edges, render_reviewed_crop
    import directory_manager
    reused = []
    raster_reviews = {}
    for crop in reviewed_crops(cfg):
        if crop['group'] != item['group']: continue
        for side in ('question', 'solution'):
            if side == 'solution' and cfg.get('content_mode') == 'key': continue
            if not crop['filename'].startswith('qfig' if side == 'question' else 'sfig'): continue
            for row,page in zip(item[f'{side}_rows'], item[f'{side}_pages']):
                ev = row['asset_evidence']
                if ev['body_sha256'] != crop['source_body_sha256']: continue
                if sha(ev['body_png']) != crop['source_body_sha256']: raise ValueError('Reviewed diagram source changed')
                with Image.open(ev['body_png']) as im:
                    b = crop['source_pixel_box']
                    if not (0 <= b[0] < b[2] <= im.width and 0 <= b[1] < b[3] <= im.height): raise ValueError('Invalid reviewed diagram bounds')
                    qdir = directory_manager.ensure_question_dir(pid, number)
                    figure,info=render_reviewed_crop(im,crop)
                    if has_unconfirmed_edges(info):raise ValueError('Reviewed diagram still touches its source crop edges')
                    figure.save(qdir / 'figures' / crop['filename'])
                reused.append({'filename': crop['filename'], 'side': side, 'page': page, 'resource_id': row['id'], 'review': crop['reason'],'raster_review':info})
                raster_reviews[crop['filename']] = info
    if raster_reviews:
        review_path = directory_manager.get_question_dir(pid, number) / 'figures' / '_raster_review.json'
        existing = json.loads(review_path.read_text(encoding='utf-8')) if review_path.exists() else {}
        dump(review_path, {**existing, **raster_reviews})
    return reused


def classify(cfg, run):
    # Preserve source classifications by default; AI classification is opt-in.
    import database
    import run_topics as topic_runner
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    progress = json.loads((run / 'progress.json').read_text(encoding='utf-8'))
    if cfg.get('tagging_mode', 'source') == 'source':
        from importer_EJEE.source_tagging import preserve
        from contextlib import closing
        with closing(database.get_connection()) as connection:
            with connection:
                for item in manifest['items']:
                    number = item['number']
                    if not progress['questions'].get(number, {}).get('ok'):
                        raise ValueError('Extraction must finish first')
                    # Use this transaction's connection. get_question_id() opens
                    # another writer via init_db(), deadlocking our own writes.
                    row = connection.execute('SELECT id FROM questions WHERE paper_id=? AND question_number=?',
                                             (manifest['paper_id'], number)).fetchone()
                    if row is None: raise ValueError(f'Question {number} missing from import database')
                    metadata = preserve(connection, row[0], item)
                    progress['node3'][number] = {'ok': True, 'mode': 'source', 'source_metadata': metadata}
        manifest['config']['tagging_mode'] = 'source'
        dump(run / 'manifest.json', manifest)
        dump(run / 'progress.json', progress)
        print('Original EJEE tagging preserved; no classification API calls.', flush=True)
        return
    # Newer PaperLab uses an explicit (code,path) catalogue; older upstream
    # versions construct their numbered reference internally. Never pass
    # display strings where the current classifier expects code/path tuples.
    catalog = topic_runner.build_topic_catalog() if hasattr(topic_runner, 'build_topic_catalog') else None
    incomplete = []
    for item in manifest['items']:
        number = item['number']
        if not progress['questions'].get(number, {}).get('ok'): raise ValueError('Extraction must finish first')
        previous = progress['node3'].get(number, {})
        if number in cfg.get('skip_classification_questions', ()) and not valid_classification(previous):
            progress['node3'][number] = {**previous, 'ok': False, 'skipped': True}
            dump(run / 'progress.json', progress)
            continue
        if valid_classification(previous):
            previous['ok'] = True
            dump(run / 'progress.json', progress)
            continue
        for attempt in range(2):
            report = topic_runner.classify_question(manifest['paper_id'], number, catalog)
            report['ok'] = bool(report.get('ok') and valid_classification(report))
            progress['node3'][number] = report
            dump(run / 'progress.json', progress)
            if report['ok']: break
        print(f'Node 3 {number}: {report}', flush=True)
        if not report['ok']: incomplete.append(number)
        time.sleep(1)
    if incomplete:
        raise RuntimeError('Classification needs review for questions ' + ', '.join(incomplete) +
                           '. Two attempts per question were made; other classifications are saved. Resume retries only incomplete questions.')


def accepted_crop_calls(messages):
    pending, accepted = [], {}
    for message in messages:
        if message['type'] == 'ai':
            pending = list(message.get('tool_calls') or [])
        elif message['type'] == 'tool' and pending:
            reply_id = message.get('tool_call_id')
            # Legacy traces without IDs recorded results in call order.
            index = next((i for i, call in enumerate(pending) if call.get('id') == reply_id), None) if reply_id else 0
            if index is None:
                continue
            call = pending.pop(index)
            text = message['content']
            if call['name'] not in ('assisted_crop', 'exact_crop') or not isinstance(text, str) or not text.startswith('Saved '):
                continue
            match = re.search(r'final box: (\[[^\]]+\])', text)
            if match:
                accepted[call['args']['output_filename']] = (call, json.loads(match[1]))
    return accepted


def figures(cfg, run):
    """Export accepted raster boxes from original pixels, without PDF upsampling."""
    import math
    from PIL import Image
    from raster_figures import crop_figure, has_unconfirmed_edges, render_reviewed_crop
    import directory_manager
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    exported = []
    issues = []
    for item in manifest['items']:
        trace = json.loads((run / 'traces' / f'{item["number"]}.json').read_text(encoding='utf-8'))
        accepted = accepted_crop_calls(trace['messages'])
        qdir = directory_manager.get_question_dir(manifest['paper_id'], item['number'])
        referenced = figure_references(qdir) if (qdir / 'question.tex').is_file() else None
        evidence = {}
        for filename, (call, box) in accepted.items():
            if referenced is not None and filename not in referenced:
                continue
            args = call['args']
            side = 'question' if args['pdf_path'] == manifest['question_pdf'] else 'solution'
            index = item[f'{side}_pages'].index(args['page_number'])
            source = item[f'{side}_rows'][index]['asset_evidence']
            with Image.open(source['body_png']) as im:
                x,y,w,h = box
                # Tool replies round normalized coordinates. Preserve a one-unit
                # safety margin so that rounding cannot remove an accepted label.
                px = [max(0, math.floor((x-1)*im.width/1000)), max(0, math.floor((y-1)*im.height/1000)),
                      min(im.width, math.ceil((x+w+1)*im.width/1000)), min(im.height, math.ceil((y+h+1)*im.height/1000))]
                review = next((r for r in reviewed_crops(cfg) if r['group'] == item['group'] and r['filename'] == filename and r['source_body_sha256'] == source['body_sha256']), None)
                cropped,review_info = render_reviewed_crop(im,review) if review else crop_figure(im,px,pixel_box=True)
                if has_unconfirmed_edges(review_info):
                    issues.append({'question': item['number'], 'filename': filename,
                                   'source_body_sha256': source['body_sha256'],
                                   'source_body': source['body_png'], **review_info})
                    continue
                dest = qdir / 'figures' / filename
                cropped.save(dest, format='PNG')
                evidence[filename] = {'source_body': source['body_png'], 'source_sha256': source['body_sha256'],
                                      'tool_final_box': box, **review_info,'sha256': sha(dest)}
                if review: evidence[filename]['review_override'] = review
        for reused in reuse_reviewed(cfg, item, manifest['paper_id'], item['number']):
            crop = next(r for r in reviewed_crops(cfg) if r['group'] == item['group'] and r['filename'] == reused['filename'])
            source = next(r['asset_evidence'] for r in item[f'{reused["side"]}_rows'] if r['id'] == reused['resource_id'])
            dest = qdir / 'figures' / reused['filename']
            with Image.open(dest) as im: size = list(im.size)
            evidence[reused['filename']] = {**evidence.get(reused['filename'], {}),
                'source_body': source['body_png'], 'source_sha256': source['body_sha256'],
                **reused['raster_review'], 'size': size, 'sha256': sha(dest),
                'method': 'reviewed source-pixel crop reused by exact image hash; trimmed and padded', 'review_override': crop}
        if evidence:
            dump(qdir / 'figures' / '_import_provenance.json', evidence)
            review_path = qdir / 'figures' / '_raster_review.json'
            reviews = json.loads(review_path.read_text(encoding='utf-8')) if review_path.exists() else {}
            dump(review_path, {**reviews, **{name: value for name, value in evidence.items()}})
            exported.extend({'question': item['number'], 'filename': k, **v} for k,v in evidence.items())
    dump(run / 'figure_export.json', exported)
    dump(run / 'crop_reviews.json', issues)
    if issues:
        names = ', '.join(f'{issue["question"]}/{issue["filename"]}' for issue in issues)
        raise CropReviewRequired(f'Crop review required: {names}. All diagrams were checked; details saved in crop_reviews.json. Converted questions are saved. No incomplete collection is published.')
    print(f'Exported {len(exported)} accepted figures from original pixels without upsampling.', flush=True)


def pack(cfg, run):
    """Normalize legacy pilot IDs and renderer-sensitive heading stars in DATA only."""
    import database
    import directory_manager
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    progress = json.loads((run / 'progress.json').read_text(encoding='utf-8'))
    changes = []
    pattern = re.compile(cfg['group_pattern'])
    for item in manifest['items']:
        old = item['number']; new = old if cfg.get('selection_snapshot') else str(int(pattern.fullmatch(item['group'])['number']))
        item.setdefault('source_number', old)
        qdir = directory_manager.get_question_dir(manifest['paper_id'], old)
        if old != new:
            dest = directory_manager.get_question_dir(manifest['paper_id'], new)
            if dest.exists(): raise ValueError(f'Target ID already exists: {new}')
            qdir.rename(dest)
            with database.get_connection() as c:
                c.execute('UPDATE questions SET question_number=?,latex_folder=? WHERE paper_id=? AND question_number=?',
                          (new, str(dest), manifest['paper_id'], old))
            for phase in ('questions', 'node3'):
                if old in progress[phase]: progress[phase][new] = progress[phase].pop(old)
            trace = run / 'traces' / f'{old}.json'
            if trace.exists(): trace.rename(run / 'traces' / f'{new}.json')
            item['extraction_number'] = old
            item['number'] = new
            qdir = dest
            changes.append({'kind': 'local_question_id', 'source_number': old, 'target_number': new,
                            'reason': 'One chapter per paper: local numeric IDs sort correctly in unchanged upstream reader. Printed source labels and tool traces remain verbatim.'})
        for side in ('question', 'solution'):
            path = qdir / f'{side}.tex'
            if not path.exists(): continue
            before = path.read_text(encoding='utf-8')
            # A printed difficulty star inside textbf becomes *** in upstream's
            # Markdown bridge. Move only that symbol outside bold, as math.
            after = normalize_rendering(strip_problem_heading(before, source_heading(item)) if side == 'question' else before)
            if after != before:
                path.write_text(after, encoding='utf-8')
                changes.append({'kind': 'content_and_rendering_normalization', 'question': new, 'side': side,
                                'before_sha256': hashlib.sha256(before.encode()).hexdigest(), 'after_sha256': sha(path),
                                'reason': 'Keep statement-only questions; normalize equation tags and preserve literal code rows for the unchanged native renderer.'})
    dump(run / 'manifest.json', manifest)
    dump(run / 'progress.json', progress)
    previous = json.loads((run / 'data_normalizations.json').read_text(encoding='utf-8')) if (run / 'data_normalizations.json').exists() else []
    dump(run / 'data_normalizations.json', previous + changes)
    print(f'Packed chapter with {len(changes)} recorded data normalizations; no application source edits.', flush=True)


def verify(cfg, run):
    import database
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    progress = json.loads((run / 'progress.json').read_text(encoding='utf-8'))
    errors = []
    pid = manifest['paper_id']
    with database.get_connection() as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': errors.append('DB integrity check failed')
        if c.execute('PRAGMA foreign_key_check').fetchall(): errors.append('Foreign key check failed')
        count = c.execute('SELECT count(*) FROM questions WHERE paper_id=?', (pid,)).fetchone()[0]
        if count != len(manifest['items']): errors.append('Question count mismatch')
        for item in manifest['items']:
            has_solution = bool(item['solution_rows']) and cfg.get('content_mode') != 'key'
            errors.extend(f'{item["number"]}: {e}' for e in validate_item(pid, item['number'], has_solution))
            classification = progress['node3'].get(item['number'], {})
            allowed_skip = item['number'] in cfg.get('skip_classification_questions', ()) and classification.get('skipped')
            if not classification.get('ok') and not allowed_skip: errors.append(f'{item["number"]}: Node 3 incomplete')
            for side in ('question', 'solution'):
                for row in item[f'{side}_rows']:
                    ev = row['asset_evidence']
                    if sha(ev['path']) != ev['sha256']: errors.append(f'Source asset changed: {row["id"]}')
        if c.execute('SELECT count(*) FROM token_usage WHERE input<0 OR output<0 OR cache_read<0 OR cache_read>input').fetchone()[0]:
            errors.append('Invalid token usage counters')
        for key in ('question_pdf', 'solution_pdf'):
            if manifest.get(key) and sha(manifest[key]) != manifest[key+'_sha256']: errors.append(f'{key} changed')
        usage = [dict(r) for r in c.execute('SELECT phase,count(*) calls,sum(input) input,sum(cache_read) cached,sum(output) output,sum(reasoning) reasoning FROM token_usage WHERE paper_id=? GROUP BY phase', (pid,))]
        topics = c.execute('SELECT count(*) FROM question_topics qt JOIN questions q ON q.id=qt.question_id WHERE q.paper_id=? AND qt.src=?', (pid, 'auto')).fetchone()[0]
    report = {'ok': not errors, 'paper_id': pid, 'questions': count, 'auto_topic_links': topics, 'usage': usage,
              'errors': errors, 'upstream_commit': manifest['upstream_commit']}
    dump(run / 'verification.json', report)
    print(json.dumps(report, indent=2), flush=True)
    if errors: raise SystemExit(1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['inspect', 'prepare', 'extract', 'figures', 'classify', 'pack', 'verify'])
    p.add_argument('--config', default=str(ROOT / 'demo.json'))
    args = p.parse_args()
    cfg, run = load_config(args.config)
    activate(run)
    {'inspect': inspect_source, 'prepare': prepare, 'extract': extract, 'figures': figures, 'classify': classify, 'pack': pack, 'verify': verify}[args.phase](cfg, run)


if __name__ == '__main__':
    main()
