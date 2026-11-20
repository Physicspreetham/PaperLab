"""Dedicated textbook database and files; never rebind the app's global DB."""
import os
import json
from pathlib import Path
import sqlite3
from threading import RLock

_lock = RLock()
_ready = set()


def store():
    import database
    import directory_manager
    root = Path(os.environ.get('PAPERLAB_EJEE_LIBRARY_ROOT', Path(directory_manager.DATA_ROOT)/'ejee_library')).resolve()
    db = root/'paperlab.db'
    if db == Path(database.DB_PATH).resolve(): raise ValueError('The textbook library must use a separate database.')
    if (root/'Outputs').resolve()==Path(directory_manager.OUTPUT_BASE).resolve() or (root/'data').resolve()==Path(directory_manager.DATA_ROOT).resolve():
        raise ValueError('Textbook output/source folders must be separate from ordinary question-paper folders.')
    with _lock:
        if str(db) not in _ready or not db.exists():
            database.init_db(db)
            with sqlite3.connect(database.DB_PATH) as source, sqlite3.connect(db) as dest:
                source.row_factory=sqlite3.Row
                if not dest.execute('SELECT 1 FROM topics LIMIT 1').fetchone():
                    for row in source.execute('SELECT * FROM topics ORDER BY rowid'):
                        columns=list(row.keys())
                        dest.execute('INSERT INTO topics ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',list(row))
            # A clean install may not have opened its syllabus yet. Seed only
            # this collection in that case; never populate the regular archive.
            database.init_topics(db)
            _ready.add(str(db))
    return {'root':root,'db':db,'outputs':root/'Outputs','data':root/'data'}


def connect():
    c=sqlite3.connect(store()['db'],timeout=30);c.row_factory=sqlite3.Row
    return c


def _order_file():
    return store()['root'] / 'collection_order.json'


def saved_order():
    path = _order_file()
    try:
        value = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []
    except (OSError, ValueError):
        return []
    return [i for i in value if isinstance(i, int)]


def papers():
    with connect() as c:
        rows = [dict(r) for r in c.execute('SELECT p.id,p.paper_name title,p.source_institute book,p.status,count(q.id) questions FROM papers p LEFT JOIN questions q ON q.paper_id=p.id GROUP BY p.id ORDER BY p.source_institute,p.id')]
    rank = {pid: i for i, pid in enumerate(saved_order())}
    # Stable: collections never ordered by hand keep their default place, after the ordered ones.
    rows.sort(key=lambda r: rank.get(r['id'], len(rank)))
    return rows


def set_order(ids):
    """Persist the manual display order of collections (any unknown id is rejected)."""
    if not isinstance(ids, list) or len(set(ids)) != len(ids) or any(type(i) is not int for i in ids):
        raise ValueError('Invalid collection order.')
    with connect() as c:
        known = {r[0] for r in c.execute('SELECT id FROM papers')}
    if not set(ids) <= known:
        raise ValueError('The order refers to a collection that no longer exists.')
    path = _order_file()
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(ids), encoding='utf-8')
    tmp.replace(path)
    return {'ids': ids}


def rename(paper_id, title):
    """Change a collection's display title only; content and provenance are untouched."""
    title = ' '.join(str(title or '').split())
    if not title or len(title) > 180:
        raise ValueError('Enter a collection title of 1 to 180 characters.')
    with connect() as c:
        row = c.execute("SELECT id FROM papers WHERE id=? AND exam_type='EJEE collection'", (paper_id,)).fetchone()
        if not row:
            raise FileNotFoundError('Imported EJEE collection not found')
        clash = c.execute("SELECT 1 FROM papers WHERE exam_type='EJEE collection' AND paper_name=? AND id<>?",
                          (title, paper_id)).fetchone()
        if clash:
            raise ValueError('Another EJEE collection already uses this title.')
        c.execute('UPDATE papers SET paper_name=? WHERE id=?', (title, paper_id))
    return {'id': paper_id, 'title': title}


_imported_cache = {'stamp': None, 'index': {}}


def imported_index():
    """selection_key -> {paper_id,title} for every question already in a collection."""
    from importer_EJEE.publish import collection_manifests, question_keys
    root = store()['data'] / 'archive' / 'ejee'
    folders = sorted(p for p in root.glob('*') if p.is_dir() and p.name.isdigit()) if root.is_dir() else []
    files = [f for folder in folders for f in (folder / 'import-manifest.json', *(folder / 'batches').glob('*/import-manifest.json')) if f.is_file()]
    stamp = tuple((str(f), f.stat().st_mtime_ns) for f in files)
    if _imported_cache['stamp'] == stamp:
        return _imported_cache['index']
    with connect() as c:
        titles = {r['id']: r['paper_name'] for r in c.execute("SELECT id,paper_name FROM papers WHERE status='done'")}
    index = {}
    for folder in folders:
        paper_id = int(folder.name)
        if paper_id not in titles:
            continue
        for manifest in collection_manifests(folder):
            for key in question_keys(manifest['items']):
                index.setdefault(key, {'paper_id': paper_id, 'title': titles[paper_id]})
    _imported_cache.update(stamp=stamp, index=index)
    return index


def metadata(paper_id):
    with connect() as c:
        row=c.execute('SELECT id,paper_name title,source_institute institute,exam_type exam,status FROM papers WHERE id=?',(paper_id,)).fetchone()
        if not row:raise FileNotFoundError('Imported EJEE collection not found')
        return dict(row)


def order_keys(paper_id):
    """Per question: its EJEE chapter and syllabus position below the chapter.

    `sort` lists node positions root->leaf under the chapter (week, topic, subtopic),
    which is the order of the subtopic codes in the EJEE app. Questions without
    preserved EJEE tags (AI-reclassified imports) are simply absent.
    """
    with connect() as c:
        if not c.execute('SELECT 1 FROM papers WHERE id=?', (paper_id,)).fetchone():
            raise FileNotFoundError('Imported EJEE collection not found')
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='ejee_source_tags'").fetchone():
            return {}
        rows = c.execute('SELECT q.question_number number, t.metadata FROM questions q '
                         'JOIN ejee_source_tags t ON t.question_id=q.id WHERE q.paper_id=?', (paper_id,)).fetchall()
    result = {}
    for row in rows:
        try:
            resources = json.loads(row['metadata']).get('resources', [])
        except ValueError:
            continue
        lineage = next((r['ancestry'] for r in resources if r.get('ancestry')), None)
        if not lineage:
            continue
        path = list(reversed(lineage))  # stored leaf -> root
        at = next((i for i, n in enumerate(path) if n.get('level') == 'chapter'), None)
        chapter = path[at] if at is not None else None
        below = path[at + 1:] if at is not None else path
        result[row['number']] = {
            'chapter_id': chapter['id'] if chapter else None,
            'chapter_name': chapter['name'] if chapter else None,
            'sort': [n.get('position') or 0 for n in below],
            'leaf': {'id': path[-1]['id'], 'name': path[-1]['name']}}
    return result


def questions(paper_id,number=None):
    from backend.segments import tex_segments
    from directory_manager import SOLUTION_PLACEHOLDER
    from importer_EJEE.publish import collection_manifests
    with connect() as c:
        paper=c.execute('SELECT * FROM papers WHERE id=?',(paper_id,)).fetchone()
        if not paper:raise FileNotFoundError('Imported EJEE collection not found')
        manifests = collection_manifests(store()['data']/'archive'/'ejee'/str(paper_id))
        provenance = {item['number']: item for manifest in manifests for item in manifest['items']}
        key_only = {item['number'] for manifest in manifests
                    if manifest.get('config', {}).get('content_mode') == 'key'
                    for item in manifest['items']}
        rows=c.execute('SELECT * FROM questions WHERE paper_id=?'+(' AND question_number=?' if number is not None else ''),
                       (paper_id,number) if number is not None else (paper_id,)).fetchall()
        topics={r['code']:dict(r) for r in c.execute('SELECT * FROM topics')}
        result=[]
        for row in sorted(rows,key=lambda r:(0,int(r['question_number'])) if r['question_number'].isdigit() else (1,r['question_number'])):
            folder=store()['outputs']/str(paper_id)/row['question_number']
            entry={'number':row['question_number'],'qtype':row['qtype'],'difficulty':row['difficulty'], 'suggestion':row['topic_suggestion'],'topics':[]}
            original=provenance.get(row['question_number'],{}).get('question_rows',[])
            entry['source']=original[0]['source'] if original else paper['source_institute']
            entry['key_only'] = row['question_number'] in key_only
            for code,rank in c.execute('SELECT topic_code,rank FROM question_topics WHERE question_id=? ORDER BY rank',(row['id'],)):
                parts=[];seen=set();cur=code
                while cur in topics and cur not in seen:
                    seen.add(cur);parts.append(topics[cur]['name']);cur=topics[cur]['parent']
                entry['topics'].append({'code':code,'path':' › '.join(reversed(parts))})
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='ejee_source_tags'").fetchone():
                saved = c.execute('SELECT metadata FROM ejee_source_tags WHERE question_id=?', (row['id'],)).fetchone()
                if saved:
                    entry['tagging_mode'] = 'source'
                    entry['source_metadata'] = json.loads(saved['metadata'])
                    resources = entry['source_metadata']['resources']
                    entry['difficulty'] = next((r['difficulty'] for r in resources if r.get('difficulty')), None)
                    entry['source_tags'] = list(dict.fromkeys(r['tags'] for r in resources if r.get('tags')))
                    for resource in resources:
                        lineage = resource.get('ancestry', [])
                        if lineage:
                            topic = {'code': 'EJEE-' + str(lineage[0]['id']),
                                     'path': ' › '.join(n['name'] for n in reversed(lineage))}
                            if topic not in entry['topics']: entry['topics'].append(topic)
            for side in ('question','solution'):
                path=folder/f'{side}.tex'
                text=path.read_text(encoding='utf-8') if path.exists() else 'Content missing.'
                if side == 'solution' and entry['key_only'] and text.strip() == SOLUTION_PLACEHOLDER:
                    text = 'No explicit answer key was available in the source.'
                def scoped(value):
                    if isinstance(value,str) and value.startswith('/api/papers/'):
                        return value.replace('/api/papers/','/api/ejee/library/papers/',1)
                    if isinstance(value,list):return [scoped(v) for v in value]
                    if isinstance(value,dict):return {k:scoped(v) for k,v in value.items()}
                    return value
                entry[side]=scoped(tex_segments(text,folder,paper_id,row['question_number']))
            result.append(entry)
        return {'paper':{'id':paper['id'],'title':paper['paper_name'],'book':paper['source_institute'],
                        'can_append':bool(manifests) and paper['status']=='done'
                        and paper['exam_type']=='EJEE collection'},'questions':result}


def usage():
    import config
    with connect() as c:
        rows=[dict(r) for r in c.execute('SELECT phase,count(*) calls,coalesce(sum(input),0) input,coalesce(sum(cache_read),0) cached,coalesce(sum(output),0) output,coalesce(sum(reasoning),0) reasoning FROM token_usage GROUP BY phase')]
    for r in rows:
        r['cost_usd']=((r['input']-r['cached'])*config.PRICING['input_per_mtok']+r['cached']*config.PRICING['cache_read_per_mtok']+r['output']*config.PRICING['output_per_mtok'])/1e6
    return {'phases':rows,'total_usd':sum(r['cost_usd'] for r in rows),'separate_library':True}
