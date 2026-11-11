"""Publish a verified isolated chapter atomically into the active app store."""
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4


def _insert(c, table, row):
    cols = {r[1] for r in c.execute('PRAGMA table_info('+table+')')}
    row = {k:v for k,v in row.items() if k in cols and k != 'id'}
    return c.execute('INSERT INTO '+table+' ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')', list(row.values())).lastrowid


def publish_chapter(run, target_db, output_base, data_root):
    run = Path(run).resolve()
    report = json.loads((run/'verification.json').read_text(encoding='utf-8'))
    if not report['ok']: raise ValueError('Chapter verification must pass before publishing.')
    cfg = json.loads((run/'config.json').read_text(encoding='utf-8'))
    manifest = json.loads((run/'manifest.json').read_text(encoding='utf-8'))
    expected = len(manifest['items'])
    out = Path(output_base).resolve(); archive = Path(data_root).resolve()/'archive'/'ejee'
    out.mkdir(parents=True,exist_ok=True); archive.mkdir(parents=True,exist_ok=True)
    c = sqlite3.connect(target_db,timeout=30); c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    # This import registry adds no changes to native PaperLab table contracts.
    c.execute('CREATE TABLE IF NOT EXISTS ejee_imports (source_key TEXT PRIMARY KEY, paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE, source_name TEXT NOT NULL, chapter TEXT NOT NULL, imported_at TEXT DEFAULT CURRENT_TIMESTAMP)')
    c.commit()
    pending_out = out/('.ejee-'+uuid4().hex); pending_sources=archive/('.ejee-'+uuid4().hex)
    moved = []
    try:
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT i.paper_id FROM ejee_imports i JOIN papers p ON p.id=i.paper_id WHERE source_key=?',(cfg['source_key'],)).fetchone()
        if old: c.rollback(); return {'paper_id':old['paper_id'],'already_imported':True}
        with sqlite3.connect((run/'paperlab.db').as_uri()+'?mode=ro',uri=True) as src:
            src.row_factory=sqlite3.Row
            snapshot=json.loads((run/'target_topics.json').read_text(encoding='utf-8'))
            current=[dict(r) for r in c.execute('SELECT * FROM topics ORDER BY rowid')]
            if current != snapshot: raise ValueError('The app syllabus changed during classification. Resume to reclassify against the latest syllabus.')
            questions=src.execute('SELECT * FROM questions WHERE paper_id=?',(manifest['paper_id'],)).fetchall()
            if len(questions)!=expected: raise ValueError('Question count changed after verification.')
            pid=c.execute('SELECT coalesce(max(id),0)+1 FROM papers').fetchone()[0]
            while (out/str(pid)).exists() or (archive/str(pid)).exists(): pid+=1
            paper=dict(src.execute('SELECT * FROM papers WHERE id=?',(manifest['paper_id'],)).fetchone())
            paper.pop('id'); paper['question_pdf_path']=str(archive/str(pid)/'questions.pdf')
            paper['solution_pdf_path']=str(archive/str(pid)/'solutions.pdf') if manifest['solution_pdf'] else None
            paper.update(status='done',archive=1,error=None)
            cols={r[1] for r in c.execute('PRAGMA table_info(papers)')}
            paper={k:v for k,v in paper.items() if k in cols}
            c.execute('INSERT INTO papers (id,'+','.join(paper)+') VALUES ('+','.join('?' for _ in range(len(paper)+1))+')',[pid,*paper.values()])
            for question in questions:
                qid=question['id']; row=dict(question)
                row.update(paper_id=pid,latex_folder=str(out/str(pid)/row['question_number']))
                newqid=_insert(c,'questions',row)
                for link in src.execute('SELECT * FROM question_topics WHERE question_id=?',(qid,)):
                    value=dict(link);value['question_id']=newqid;_insert(c,'question_topics',value)
                if src.execute("SELECT 1 FROM sqlite_master WHERE name='topic_classifications'").fetchone():
                    for result in src.execute('SELECT * FROM topic_classifications WHERE question_id=?',(qid,)):
                        value=dict(result);value['question_id']=newqid;_insert(c,'topic_classifications',value)
            for token in src.execute('SELECT * FROM token_usage WHERE paper_id=?',(manifest['paper_id'],)):
                value=dict(token);value['paper_id']=pid;_insert(c,'token_usage',value)
            shutil.copytree(run/'Outputs'/str(manifest['paper_id']),pending_out)
            shutil.copytree(run/'sources',pending_sources)
            shutil.copy2(run/'manifest.json',pending_sources/'import-manifest.json')
            pending_out.rename(out/str(pid));moved.append((out/str(pid),pending_out))
            pending_sources.rename(archive/str(pid));moved.append((archive/str(pid),pending_sources))
            c.execute('INSERT INTO ejee_imports (source_key,paper_id,source_name,chapter) VALUES (?,?,?,?)',
                      (cfg['source_key'],pid,cfg['book_source'],cfg['chapter']))
            c.commit()
            return {'paper_id':pid,'already_imported':False}
    except BaseException:
        c.rollback()
        # Preserve generated files for recovery. Never delete existing app data.
        for dest,pending in reversed(moved):
            if dest.exists() and not pending.exists(): dest.rename(pending)
        raise
    finally:
        c.close()
