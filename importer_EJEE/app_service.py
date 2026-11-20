"""App-facing read-only EJEE catalogue and persistent background import jobs.

No AI libraries are imported into the web server. The existing importer runs
in its own Python process and publishes completed, verified chapters only.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
from threading import RLock
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
APP = ROOT.parent
WEB = Path(os.environ.get('PAPERLAB_EJEE_JOBS_ROOT', ROOT / 'runs' / 'web')).resolve()
ADAPTERS = [
    {'id': 'morin', 'source': 'David Morin · Introduction to Classical Mechanics',
     'pattern': r'^morin-(?P<chapter>\d+)\.(?P<number>\d+)$'},
    {'id': 'hibbeler-dynamics', 'source': 'Hibbeler Dynamics 14e',
     'pattern': r'^hb-(?P<chapter>\d+)[–-](?P<number>\d+)$'},
]
MORIN_CHAPTERS = ['Strategies for solving problems', 'Statics', 'Using F = ma', 'Oscillations',
    'Conservation of energy and momentum', 'The Lagrangian method', 'Central forces',
    'Angular momentum, Part I', 'Angular momentum, Part II', 'Accelerating frames of reference',
    'Relativity (Kinematics)', 'Relativity (Dynamics)', '4-vectors', 'General Relativity']
_lock = RLock()
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ejee-import')
_live = {}
_procs = {}
_cancelled = set()
_cost_cache = {}
STATE_KEYS = ('id','source_key','book','chapter','total','status','phase','created_at','target_db','target_outputs','target_data','paper_id','error','kind','content_mode','selected_resource_ids','append_paper_id','skipped','finished_at')


def read_json(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def source_connection(path):
    c = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA query_only=ON')
    c.execute('BEGIN')
    return c


def settings():
    return read_json(WEB / 'settings.json', {
        'source_db': os.environ.get('EJEE_SOURCE_DB', 'C:/EJEE-data/ejee.db'),
        'asset_root': os.environ.get('EJEE_ASSET_ROOT', 'C:/EJEE-data/uploads')})


def configure(source_db, asset_root):
    db, assets = Path(source_db).expanduser().resolve(), Path(asset_root).expanduser().resolve()
    if not db.is_file() or not assets.is_dir():
        raise ValueError('The EJEE database file and image folder must both exist on this computer.')
    c = source_connection(db)
    try:
        cols = {r['name'] for r in c.execute('PRAGMA table_info(resources)')}
        if not {'id', 'source', 'grp', 'part', 'file_name', 'print_meta'} <= cols:
            raise ValueError('This is not a supported EJEE resources database.')
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'nodes', 'resource_crops', 'resource_transcripts'} <= names:
            raise ValueError('EJEE mapping/provenance tables are missing from this database.')
    finally:
        c.close()
    result = {'source_db': str(db), 'asset_root': str(assets)}
    with _lock:
        write_json(WEB / 'settings.json', result)
    return result


def adapters():
    # A server-owned file can add explicit book numbering adapters. Never infer
    # textbook chapter order from the unrelated EJEE teaching taxonomy.
    return read_json(ROOT / 'book_adapters.json', ADAPTERS)


def chapter_key(source, chapter, groups=None):
    return hashlib.sha256(json.dumps([source, str(chapter), sorted(groups or [])], ensure_ascii=False).encode()).hexdigest()


def completed_imports(target_db):
    c = sqlite3.connect(target_db)
    try:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='ejee_imports'").fetchone(): return {}
        return dict(c.execute('SELECT i.source_key,i.paper_id FROM ejee_imports i JOIN papers p ON p.id=i.paper_id'))
    finally:
        c.close()


def catalogue(target_db):
    cfg = settings()
    if not Path(cfg['source_db']).is_file() or not Path(cfg['asset_root']).is_dir():
        return {'settings': cfg, 'books': [], 'unsupported': [], 'connected': False,
                'message': 'Connect the EJEE database and its image folder first.'}
    c = source_connection(cfg['source_db'])
    try:
        inventory = {r[0]: r[1] for r in c.execute('SELECT source,count(*) FROM resources WHERE part=? GROUP BY source', ('q',))}
        imported = completed_imports(target_db)
        books = []
        for adapter in adapters():
            pattern = re.compile(adapter['pattern'])
            chapters, unmatched = {}, 0
            for row in c.execute('SELECT grp,part,count(*) n FROM resources WHERE source=? GROUP BY grp,part', (adapter['source'],)):
                match = pattern.fullmatch(row['grp'] or '')
                if not match:
                    if row['part'] == 'q': unmatched += row['n']
                    continue
                number = match['chapter']
                chapter = chapters.setdefault(number, {'id': number, 'groups': {}, 'question_parts': 0,
                                                       'solution_parts': 0})
                group = chapter['groups'].setdefault(row['grp'], {'q': 0, 'sol': 0})
                if row['part'] in group: group[row['part']] += row['n']
                else: group['unsupported'] = True
            entries = []
            for number, ch in sorted(chapters.items(), key=lambda v: int(v[0])):
                valid_groups = [g for g,parts in ch['groups'].items() if parts['q'] and not parts.get('unsupported')]
                if not valid_groups: continue
                title = ('Chapter ' + number)
                if adapter['id'] == 'morin' and 1 <= int(number) <= len(MORIN_CHAPTERS): title += ': ' + MORIN_CHAPTERS[int(number)-1]
                if adapter['id'] == 'hibbeler-dynamics' and number == '12': title += ': Kinematics of a Particle'
                # A two-question fixture and a full chapter are different
                # inputs; one must not silently block the other as a duplicate.
                key = chapter_key(adapter['source'], number, valid_groups)
                entries.append({'id': number, 'title': title, 'questions': len(valid_groups),
                                'solution_groups': sum(bool(ch['groups'][g]['sol']) for g in valid_groups),
                                'groups': valid_groups, 'source_key': key, 'paper_id': imported.get(key),
                                'excluded_groups': len(ch['groups']) - len(valid_groups)})
            if entries:
                books.append({'id': adapter['id'], 'source': adapter['source'], 'chapters': entries,
                              'excluded_question_parts': unmatched})
        known = {a['source'] for a in adapters()}
        return {'settings': cfg, 'connected': True, 'books': books,
                'unsupported': [{'source': k, 'question_parts': v} for k,v in inventory.items() if k and k not in known]}
    finally:
        c.close()


def worker_python():
    candidates = [ROOT / '.venv' / 'Scripts' / 'python.exe', ROOT / '.venv' / 'bin' / 'python']
    return str(next((p for p in candidates if p.is_file()), Path(sys.executable)))


def _job_cost(db, cacheable):
    """Estimated API cost from a worker DB; finished jobs are cached by file time."""
    if not db.exists():
        return 0.0
    stamp = tuple(p.stat().st_mtime_ns for p in (db, db.with_name(db.name + '-wal')) if p.exists())
    if cacheable and _cost_cache.get(str(db), (None,))[0] == stamp:
        return _cost_cache[str(db)][1]
    import config
    total = 0.0
    try:
        c = source_connection(db)
        try:
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='token_usage'").fetchone():
                for incoming, cached, outgoing in c.execute('SELECT input,cache_read,output FROM token_usage'):
                    total += ((incoming-cached)*config.PRICING['input_per_mtok']
                              + cached*config.PRICING['cache_read_per_mtok']
                              + outgoing*config.PRICING['output_per_mtok'])/1e6
        finally:
            c.close()
    except sqlite3.Error:
        return 0.0  # The worker may still be creating its database on this poll.
    _cost_cache[str(db)] = (stamp, total)
    return total


def get_job(job_id):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id): raise ValueError('Invalid import job')
    state = read_json(WEB / job_id / 'state.json')
    if state is None: raise FileNotFoundError('Import job not found')
    progress = read_json(WEB / job_id / 'progress.json', {'questions': {}, 'node3': {}})
    state['converted'] = sum(bool(v.get('ok')) for v in progress.get('questions', {}).values())
    state['classified'] = sum(bool(v.get('ok')) for v in progress.get('node3', {}).values())
    phase = read_json(WEB / job_id / 'phase.json', {})
    if state['status'] == 'failed':
        state['phase'] = phase.get('phase', 'failed')
    if state['status'] in ('running', 'queued'):
        state['phase'] = phase.get('phase', state.get('phase', 'queued'))
        if job_id not in _live:
            state['status'] = 'interrupted'
            state['error'] = 'The app restarted. Resume this chapter to continue from saved progress.'
    config_json = read_json(WEB / job_id / 'config.json', {})
    state['tagging_mode'] = config_json.get('tagging_mode', 'source')
    state['auto_accepted_crops'] = len(read_json(WEB / job_id / 'auto_crop_reviews.json', []))
    state['can_cancel'] = state['status'] in ('running', 'queued') and job_id in _live
    state['estimated_cost_usd'] = _job_cost(WEB / job_id / 'paperlab.db',
                                            state['status'] in ('done', 'failed', 'interrupted'))
    return state


def cancel_job(job_id, target_db):
    """Stop a queued or running import; saved progress is kept and Resume continues it."""
    with _lock:
        state = get_job(job_id)
        if state['target_db'] != str(target_db): raise ValueError('This job belongs to another PaperLab database.')
        if state['status'] not in ('queued', 'running') or job_id not in _live:
            raise ValueError('This import is not running.')
        future, proc = _live[job_id], _procs.get(job_id)
        _cancelled.add(job_id)
        message = 'Import cancelled. Resume to continue from saved progress.'
        if future.cancel():  # still waiting in the queue
            _cancelled.discard(job_id)
            _live.pop(job_id, None)
            saved = read_json(WEB / job_id / 'state.json')
            saved.update(status='failed', error=message, finished_at=time.time())
            write_json(WEB / job_id / 'state.json', saved)
        elif proc is not None and proc.poll() is None:
            proc.terminate()
        write_json(WEB / job_id / 'phase.json', {'phase': 'failed', 'error': message})
    return get_job(job_id)


def delete_job(job_id, target_db):
    """Remove a stopped job's working folder. Completed imports are never deleted."""
    with _lock:
        state = get_job(job_id)
        if state['target_db'] != str(target_db): raise ValueError('This job belongs to another PaperLab database.')
        if state['status'] not in ('failed', 'interrupted'):
            raise ValueError('Only stopped imports that were not completed can be removed.')
        if job_id in _live and not _live[job_id].done():
            raise ValueError('Cancel this import before removing it.')
        _live.pop(job_id, None)
        shutil.rmtree(WEB / job_id)
    return {'removed': job_id}


def job_questions(job_id):
    """Per-question outcome table for one import job."""
    get_job(job_id)  # validates the id and that the job exists
    folder = WEB / job_id
    manifest = read_json(folder / 'manifest.json')
    if not manifest: return []
    progress = read_json(folder / 'progress.json', {'questions': {}}).get('questions', {})
    auto = {}
    for entry in read_json(folder / 'auto_crop_reviews.json', []):
        auto.setdefault(entry['group'], []).append(entry['filename'])
    rows = []
    for item in manifest['items']:
        saved = progress.get(item['number']) or {}
        status = ('done' if saved.get('ok') else 'review' if saved.get('needs_review')
                  else 'failed' if saved.get('error') else 'pending')
        first = (item.get('question_rows') or [{}])[0]
        rows.append({'number': item['number'], 'label': first.get('title') or item.get('source_number') or item['group'],
                     'status': status, 'error': saved.get('error'), 'turns': saved.get('turns'),
                     'elapsed_sec': saved.get('elapsed_sec'), 'auto_accepted': auto.get(item['group'], [])})
    return rows


def list_jobs():
    with _lock:
        return [get_job(p.parent.name) for p in sorted(WEB.glob('*/state.json'), key=lambda p: p.stat().st_mtime, reverse=True)]


def _run(job_id, environment):
    from importer_EJEE.publish import publish_chapter
    folder = WEB / job_id
    with _lock:
        state = read_json(folder / 'state.json'); state.update(status='running', error=None)
        write_json(folder / 'state.json', state)
    try:
        env = {**os.environ, **environment, 'PAPERLAB_REPO': str(APP), 'PYTHONUNBUFFERED': '1',
               'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8:backslashreplace'}
        _cancelled.discard(job_id)
        with (folder / 'worker.log').open('a', encoding='utf-8') as log:
            proc = subprocess.Popen([worker_python(), str(ROOT / 'web_worker.py'), str(folder / 'config.json')],
                                    cwd=APP, env=env, stdout=log, stderr=log,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            _procs[job_id] = proc
            try:
                returncode = proc.wait()
            finally:
                _procs.pop(job_id, None)
        if job_id in _cancelled:
            _cancelled.discard(job_id)
            raise RuntimeError('Import cancelled. Resume to continue from saved progress.')
        if returncode:
            detail = read_json(folder / 'phase.json', {}).get('error')
            raise RuntimeError(detail or 'Chapter conversion stopped. Resume to retry using the saved progress.')
        published = publish_chapter(folder, state['target_db'], state['target_outputs'], state['target_data'])
        state.update(status='done', phase='done', paper_id=published['paper_id'], error=None)
        try:
            from backend.routers.search import bump_search_version
            bump_search_version()
        except ImportError:
            pass
    except Exception as exc:
        message=str(exc)
        for key,value in environment.items():
            if 'KEY' in key and value:message=message.replace(value,'[credential omitted]')
        state.update(status='failed', error=message)
    with _lock:
        state['finished_at'] = time.time()
        write_json(folder / 'state.json', state)


def launch(job_id, environment):
    _live[job_id] = _pool.submit(_run, job_id, environment)


def start_jobs(book_id, chapters, target_db, target_outputs, target_data, environment):
    if not chapters or len(chapters) > 20: raise ValueError('Select between one and twenty chapters.')
    cat = catalogue(target_db)
    book = next((b for b in cat['books'] if b['id'] == book_id), None)
    if not book: raise ValueError('Choose a supported textbook from the connected EJEE database.')
    selected = [next((c for c in book['chapters'] if c['id'] == str(ch)), None) for ch in dict.fromkeys(chapters)]
    if any(c is None for c in selected): raise ValueError('The selected chapter is not in the connected database.')
    adapter = next(a for a in adapters() if a['id'] == book_id)
    result = []
    with _lock:
        previous = list_jobs()
        for chapter in selected:
            if chapter['paper_id']:
                result.append({'status': 'done', 'paper_id': chapter['paper_id'], 'chapter': chapter['title']}); continue
            existing = next((j for j in previous if j['source_key'] == chapter['source_key'] and j['target_db'] == str(target_db) and j['status'] != 'done'), None)
            if existing:
                result.append(existing); continue
            job_id = uuid4().hex; folder = WEB / job_id
            cfg = {**cat['settings'], 'book_source': book['source'], 'group_pattern': adapter['pattern'],
                   'chapter': chapter['id'], 'chapter_title': chapter['title'], 'groups': chapter['groups'],
                   'run_dir': folder.relative_to(ROOT).as_posix(), 'max_turns_per_question': 36,
                   'target_db': str(target_db), 'source_key': chapter['source_key']}
            write_json(folder / 'config.json', cfg)
            state = {'id': job_id, 'source_key': chapter['source_key'], 'book': book['source'],
                     'chapter': chapter['title'], 'total': chapter['questions'], 'status': 'queued', 'phase': 'queued',
                     'created_at': time.time(), 'target_db': str(target_db), 'target_outputs': str(target_outputs),
                     'target_data': str(target_data), 'paper_id': None, 'error': None}
            write_json(folder / 'state.json', state)
            launch(job_id, environment); result.append(state)
    return result


def resume_job(job_id, target_db, environment):
    with _lock:
        state = get_job(job_id)
        if state['target_db'] != str(target_db): raise ValueError('This job belongs to another PaperLab database.')
        if state['status'] in ('done', 'running', 'queued'): return state
        check_append_queue(state.get('append_paper_id'), target_db)
        state.update(status='queued', error=None)
        write_json(WEB / job_id / 'state.json', state)
        launch(job_id, environment)
        return state


def check_append_queue(paper_id, target_db):
    if paper_id is not None and any(
        job.get('append_paper_id') == paper_id and job['target_db'] == str(target_db)
        and job['status'] in ('queued', 'running') for job in list_jobs()
    ):
        raise ValueError('An addition is already processing for this collection. Wait for it to finish.')


def start_selection(name, resource_ids, source_token, filters, target_db, target_outputs, target_data,
                    environment, tagging_mode='source', append_paper_id=None, content_mode='full'):
    from importer_EJEE import selection
    from importer_EJEE.publish import collection_manifests, question_keys
    name=name.strip()
    if tagging_mode not in ('source', 'paperlab'): raise ValueError('Invalid tagging mode')
    if content_mode not in ('key', 'full'): raise ValueError('Invalid transcription mode')
    if append_paper_id is None and (not name or len(name)>180):
        raise ValueError('Enter a collection name (up to 180 characters).')
    with _lock:
        if selection.source_token()!=source_token:
            raise ValueError('The connected EJEE source changed. Refresh the filters before importing.')
        selected=selection.snapshot(resource_ids)
        identity = 'selection:' + selected['fingerprint']
        skipped = 0
        if append_paper_id is not None:
            with sqlite3.connect(target_db) as c:
                paper = c.execute("SELECT paper_name FROM papers WHERE id=? AND status='done' AND exam_type='EJEE collection'",
                                  (append_paper_id,)).fetchone()
            if not paper:
                raise FileNotFoundError('The destination collection is no longer available.')
            name = paper[0]
            manifests = collection_manifests(Path(target_data) / 'archive' / 'ejee' / str(append_paper_id))
            if not manifests:
                raise ValueError('The destination collection has no import history.')
            existing = question_keys(item for batch in manifests for item in batch['items'])
            items = selected['items']
            selected['items'] = [item for item in items if item['source_key'] not in existing]
            skipped = len(items) - len(selected['items'])
            if not selected['items']:
                return {'status':'done', 'paper_id':append_paper_id, 'already_imported':True, 'skipped':skipped}
            keys = {item['source_key'] for item in selected['items']}
            question_ids = {row['id'] for item in selected['items'] for row in item['question_rows']}
            selected['selected_resource_ids'] = [rid for rid in selected['selected_resource_ids'] if rid in question_ids]
            selected['included_resource_ids'] = [
                row['id'] for item in selected['items'] for side in ('question_rows', 'solution_rows')
                for row in item[side]]
            identity = f'append:{append_paper_id}:' + ','.join(sorted(keys))
        if content_mode == 'key':
            identity += ':key-only'
        key=hashlib.sha256(identity.encode()).hexdigest()
        imported=completed_imports(target_db)
        if key in imported:return {'status':'done','paper_id':imported[key],'already_imported':True}
        existing=next((j for j in list_jobs() if j['source_key']==key and j['target_db']==str(target_db) and j['status']!='done'),None)
        if existing:return existing
        check_append_queue(append_paper_id, target_db)
        sources=list(dict.fromkeys(r['source'] or 'Unspecified source' for item in selected['items'] for r in item['question_rows']))
        job_id=uuid4().hex;folder=WEB/job_id
        write_json(folder/'selection.json',selected)
        cfg={**settings(),'selection_snapshot':str(folder/'selection.json'),'collection_name':name,
             'extractor_mode':'mapped-pair','cost_max_turns_per_question':12,'tagging_mode':tagging_mode,
             'content_mode':content_mode,
             'selection_filters':filters,'book_source':sources[0] if len(sources)==1 else 'Mixed EJEE sources',
             'group_pattern':'','chapter':'selection','chapter_title':name,
             'run_dir':folder.relative_to(ROOT).as_posix(),'max_turns_per_question':36,
             'target_db':str(target_db),'source_key':key}
        if append_paper_id is not None:
            cfg['append_paper_id'] = append_paper_id
        write_json(folder/'config.json',cfg)
        state={'id':job_id,'source_key':key,'book':cfg['book_source'],'chapter':name,'total':len(selected['items']),
               'status':'queued','phase':'queued','created_at':time.time(),'target_db':str(target_db),
               'target_outputs':str(target_outputs),'target_data':str(target_data),'paper_id':None,'error':None,
               'kind':'selection','content_mode':content_mode,'selected_resource_ids':selected['selected_resource_ids']}
        if append_paper_id is not None:
            state.update(append_paper_id=append_paper_id, skipped=skipped)
        write_json(folder/'state.json',state);launch(job_id,environment)
        return state
