"""Dedicated textbook database and files; never rebind the app's global DB."""
import os
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


def papers():
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT p.id,p.paper_name title,p.source_institute book,p.status,count(q.id) questions FROM papers p LEFT JOIN questions q ON q.paper_id=p.id GROUP BY p.id ORDER BY p.source_institute,p.id')]


def questions(paper_id):
    from backend.segments import tex_segments
    with connect() as c:
        paper=c.execute('SELECT * FROM papers WHERE id=?',(paper_id,)).fetchone()
        if not paper:raise FileNotFoundError('Imported textbook chapter not found')
        rows=c.execute('SELECT * FROM questions WHERE paper_id=?',(paper_id,)).fetchall()
        topics={r['code']:dict(r) for r in c.execute('SELECT * FROM topics')}
        result=[]
        for row in sorted(rows,key=lambda r:(0,int(r['question_number'])) if r['question_number'].isdigit() else (1,r['question_number'])):
            folder=store()['outputs']/str(paper_id)/row['question_number']
            entry={'number':row['question_number'],'qtype':row['qtype'],'difficulty':row['difficulty'], 'suggestion':row['topic_suggestion'],'topics':[]}
            for code,rank in c.execute('SELECT topic_code,rank FROM question_topics WHERE question_id=? ORDER BY rank',(row['id'],)):
                parts=[];seen=set();cur=code
                while cur in topics and cur not in seen:
                    seen.add(cur);parts.append(topics[cur]['name']);cur=topics[cur]['parent']
                entry['topics'].append({'code':code,'path':' › '.join(reversed(parts))})
            for side in ('question','solution'):
                path=folder/f'{side}.tex'
                text=path.read_text(encoding='utf-8') if path.exists() else 'Content missing.'
                def scoped(value):
                    if isinstance(value,str) and value.startswith('/api/papers/'):
                        return value.replace('/api/papers/','/api/ejee/library/papers/',1)
                    if isinstance(value,list):return [scoped(v) for v in value]
                    if isinstance(value,dict):return {k:scoped(v) for k,v in value.items()}
                    return value
                entry[side]=scoped(tex_segments(text,folder,paper_id,row['question_number']))
            result.append(entry)
        return {'paper':{'id':paper['id'],'title':paper['paper_name'],'book':paper['source_institute']},'questions':result}


def usage():
    import config
    with connect() as c:
        rows=[dict(r) for r in c.execute('SELECT phase,count(*) calls,coalesce(sum(input),0) input,coalesce(sum(cache_read),0) cached,coalesce(sum(output),0) output,coalesce(sum(reasoning),0) reasoning FROM token_usage GROUP BY phase')]
    for r in rows:
        r['cost_usd']=((r['input']-r['cached'])*config.PRICING['input_per_mtok']+r['cached']*config.PRICING['cache_read_per_mtok']+r['output']*config.PRICING['output_per_mtok'])/1e6
    return {'phases':rows,'total_usd':sum(r['cost_usd'] for r in rows),'separate_library':True}
