"""Isolated worker using the existing importer and current PaperLab Node 3."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import traceback

from bootstrap import activate
from importer import load_config, prepare, extract, figures, pack, classify, verify, dump


def lock_worker(run):
    lock = (run / 'worker.lock').open('a+b')
    lock.seek(0)
    if lock.read(1) == b'': lock.write(b'0'); lock.flush()
    lock.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise RuntimeError('Another importer worker is already using this chapter. Retry when it has stopped.')
    return lock


def seed_current_topics(cfg, run):
    """Classify against the active app's taxonomy, including human revisions."""
    with sqlite3.connect(Path(cfg['target_db']).resolve().as_uri() + '?mode=ro', uri=True) as src:
        src.row_factory = sqlite3.Row
        rows = [dict(r) for r in src.execute('SELECT * FROM topics ORDER BY rowid')]
    snapshot = run / 'target_topics.json'
    previous = json.loads(snapshot.read_text(encoding='utf-8')) if snapshot.exists() else None
    if previous == rows: return
    with sqlite3.connect(run / 'paperlab.db') as dest:
        dest.execute('DELETE FROM question_topics')
        if dest.execute("SELECT 1 FROM sqlite_master WHERE name='topic_classifications'").fetchone():
            dest.execute('DELETE FROM topic_classifications')
        dest.execute('UPDATE questions SET difficulty=NULL, topic_suggestion=NULL')
        dest.execute('DELETE FROM topics')
        cols = [r[1] for r in dest.execute('PRAGMA table_info(topics)')]
        for row in rows:
            dest.execute('INSERT INTO topics ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')', [row[k] for k in cols])
    progress_path = run / 'progress.json'
    progress = json.loads(progress_path.read_text(encoding='utf-8')); progress['node3'] = {}
    dump(progress_path, progress); dump(snapshot, rows)


def main():
    cfg, run = load_config(sys.argv[1])
    # A failed competing lock must not overwrite the first worker's phase file.
    lock = lock_worker(run)
    try:
        activate(run)
        phases = [] if (run/'manifest.json').exists() else [('preparing',prepare)]
        phases += [('converting',extract), ('diagrams',figures), ('formatting',pack),
                   ('syllabus',seed_current_topics), ('classifying',classify), ('verifying',verify)]
        for phase,fn in phases:
            dump(run/'phase.json', {'phase':phase})
            fn(cfg,run)
        dump(run/'phase.json', {'phase':'publishing'})
    except BaseException as exc:
        dump(run/'phase.json', {'phase':'failed', 'error':f'{type(exc).__name__}: {exc}'})
        raise
    finally:
        lock.close()


if __name__ == '__main__': main()
