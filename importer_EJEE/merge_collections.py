"""Merge several published EJEE collections into one new collection.

Source collections are never modified or removed. Questions are copied into a
new collection ordered by syllabus (module, chapter, week, subtopic), then by
source, then by card title, and numbered 1..N in that order. Archived source
images are hard-linked (copied when linking is unavailable) so the diagram
editor keeps working without duplicating hundreds of megabytes.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

from importer_EJEE import library_store as library
from importer_EJEE.publish import _insert, collection_manifests


def _natural(text):
    return [int(p) if p.isdigit() else p.casefold() for p in re.split(r'(\d+)', text or '')]


def _link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _clone_tree(src, dst):
    """Copy a folder tree, hard-linking files (the archive is read-only data)."""
    shutil.copytree(src, dst, copy_function=_link_or_copy)


def _sort_key(item):
    path = tuple((n.get('position') if n.get('position') is not None else 1 << 30, n['id'])
                 for n in reversed(item['ancestry']))
    source = item['source']
    return ((0, path) if path else (1, ()),
            (1, '') if not source else (0, str(source).casefold()),
            _natural(item['title']), item['paper_id'], int(item['number']))


def merge(paper_ids, title, only=None, dedupe=True):
    """Create one new collection from `paper_ids`; returns {paper_id, questions, skipped_duplicates}.

    `only` ({paper_id: set of question numbers}) restricts which questions are copied; it is
    how `split_collection` builds a new collection from part of one.
    """
    paper_ids = list(dict.fromkeys(paper_ids))
    if len(paper_ids) < 2 and not only:
        raise ValueError('Choose at least two collections to merge.')
    if not title.strip():
        raise ValueError('The merged collection needs a title.')
    store = library.store()
    out, archive = store['outputs'], store['data'] / 'archive' / 'ejee'
    c = library.connect()
    c.execute('PRAGMA foreign_keys=ON')
    created = []
    try:
        c.execute('BEGIN IMMEDIATE')
        papers = {}
        for pid in paper_ids:
            row = c.execute("SELECT * FROM papers WHERE id=? AND status='done' AND exam_type='EJEE collection'", (pid,)).fetchone()
            if row is None:
                raise ValueError(f'Collection {pid} is missing or not finished.')
            papers[pid] = dict(row)

        # Gather every question with the provenance needed for ordering and dedupe.
        entries, seen_keys, skipped = [], set(), 0
        for pid in paper_ids:
            provenance = {item['number']: item for m in collection_manifests(archive / str(pid)) for item in m['items']}
            for q in c.execute('SELECT * FROM questions WHERE paper_id=?', (pid,)):
                if only is not None and q['question_number'] not in only.get(pid, ()):
                    continue
                item = provenance.get(q['question_number'])
                meta = c.execute('SELECT metadata FROM ejee_source_tags WHERE question_id=?', (q['id'],)).fetchone()
                resources = json.loads(meta['metadata']).get('resources', []) if meta else []
                ancestry = next((r['ancestry'] for r in resources if r.get('ancestry')), [])
                rows = (item or {}).get('question_rows') or [{}]
                key = (item or {}).get('source_key')
                if key and dedupe and key in seen_keys:
                    skipped += 1
                    continue
                if key:
                    seen_keys.add(key)
                entries.append({'question': dict(q), 'paper_id': pid, 'number': q['question_number'], 'ancestry': ancestry,
                                'source': rows[0].get('source'), 'title': rows[0].get('title') or (item or {}).get('source_number') or ''})
        if not entries:
            raise ValueError('The selected collections contain no questions.')
        entries.sort(key=_sort_key)
        number_map = {(e['paper_id'], e['number']): str(i) for i, e in enumerate(entries, 1)}

        pid = c.execute('SELECT coalesce(max(id),0)+1 FROM papers').fetchone()[0]
        while (out / str(pid)).exists() or (archive / str(pid)).exists():
            pid += 1
        first = papers[paper_ids[0]]
        new_archive = archive / str(pid)
        paper = {k: v for k, v in first.items() if k != 'id'}
        paper.update(paper_name=title.strip(), source_institute='Mixed EJEE sources', status='done', archive=1, error=None,
                     pdf_hash=hashlib.sha256('|'.join([*sorted(str(p['pdf_hash']) for p in papers.values()), f'merged-{pid}']).encode()).hexdigest(),
                     question_pdf_path=str(new_archive / 'questions.pdf'),
                     solution_pdf_path=str(new_archive / 'solutions.pdf') if first.get('solution_pdf_path') else None)
        c.execute('INSERT INTO papers (id,' + ','.join(paper) + ') VALUES (?,' + ','.join('?' for _ in paper) + ')', [pid, *paper.values()])

        # Database rows.
        from importer_EJEE.source_tagging import ensure_table
        ensure_table(c)
        for e in entries:
            old, number = e['question'], number_map[(e['paper_id'], e['number'])]
            row = dict(old)
            row.update(paper_id=pid, question_number=number, latex_folder=str(out / str(pid) / number))
            new_id = _insert(c, 'questions', row)
            tag = c.execute('SELECT metadata FROM ejee_source_tags WHERE question_id=?', (old['id'],)).fetchone()
            if tag:
                c.execute('INSERT INTO ejee_source_tags VALUES (?,?)', (new_id, tag['metadata']))
            for link in c.execute('SELECT * FROM question_topics WHERE question_id=?', (old['id'],)).fetchall():
                value = dict(link); value['question_id'] = new_id; _insert(c, 'question_topics', value)
            for result in c.execute('SELECT * FROM topic_classifications WHERE question_id=?', (old['id'],)).fetchall():
                value = dict(result); value['question_id'] = new_id; _insert(c, 'topic_classifications', value)

        # Files: question folders and archived sources, staged then renamed into place.
        stage_out, stage_arc = out / ('.merge-' + uuid4().hex), archive / ('.merge-' + uuid4().hex)
        stage_out.mkdir(parents=True); stage_arc.mkdir(parents=True)
        created += [stage_out, stage_arc]
        for e in entries:
            src = out / str(e['paper_id']) / e['number']
            if not src.is_dir():
                raise ValueError(f'Collection {e["paper_id"]} question {e["number"]} has no output folder.')
            shutil.copytree(src, stage_out / number_map[(e['paper_id'], e['number'])])
        for i, old_pid in enumerate(paper_ids):
            old_root = archive / str(old_pid)
            folders = [(old_root, stage_arc if i == 0 else stage_arc / 'batches' / f'merged-{old_pid}')]
            folders += [(b, stage_arc / 'batches' / b.name) for b in sorted((old_root / 'batches').glob('*')) if b.is_dir()]
            for src, dst in folders:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.mkdir(exist_ok=True)
                for f in src.iterdir():
                    if f.is_dir():
                        if f.name != 'batches':
                            _clone_tree(f, dst / f.name)
                    elif f.name != 'import-manifest.json':
                        _link_or_copy(f, dst / f.name)
                manifest_path = src / 'import-manifest.json'
                if manifest_path.is_file():
                    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                    manifest['items'] = [dict(item, number=number_map[(old_pid, item['number'])])
                                         for item in manifest['items'] if (old_pid, item['number']) in number_map]
                    (dst / 'import-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        stage_out.rename(out / str(pid)); created = [p for p in created if p != stage_out]; created.append(out / str(pid))
        stage_arc.rename(new_archive); created = [p for p in created if p != stage_arc]; created.append(new_archive)
        c.commit()
        return {'paper_id': pid, 'questions': len(entries), 'skipped_duplicates': skipped}
    except BaseException:
        c.rollback()
        for path in created:  # only folders this run created
            shutil.rmtree(path, ignore_errors=True)
        raise
    finally:
        c.close()


def _trash(path, label):
    """Move a folder aside instead of deleting it, so a mistaken delete is recoverable."""
    if not path.is_dir():
        return None
    dest = library.store()['root'] / 'trash' / label
    dest.parent.mkdir(parents=True, exist_ok=True)
    while dest.exists():
        dest = dest.with_name(dest.name + '_')
    shutil.move(str(path), str(dest))
    return dest


def delete_questions(paper_id, numbers):
    """Remove questions from a collection. Folders go to `<library>/trash/`, and the questions
    are dropped from the import manifests so they can be selected and imported again."""
    numbers = {str(n) for n in numbers}
    if not numbers:
        raise ValueError('Choose at least one question to delete.')
    store = library.store()
    out, archive = store['outputs'], store['data'] / 'archive' / 'ejee' / str(int(paper_id))
    c = library.connect()
    c.execute('PRAGMA foreign_keys=ON')
    try:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM papers WHERE id=? AND status='done' AND exam_type='EJEE collection'", (paper_id,)).fetchone() is None:
            raise FileNotFoundError('Imported EJEE collection not found')
        rows = c.execute('SELECT id,question_number FROM questions WHERE paper_id=?', (paper_id,)).fetchall()
        existing = {r['question_number']: r['id'] for r in rows}
        missing = numbers - set(existing)
        if missing:
            raise FileNotFoundError('Question not found in this collection: ' + ', '.join(sorted(missing, key=_natural)))
        if len(numbers) >= len(existing):
            raise ValueError('A collection must keep at least one question.')
        ids = [existing[n] for n in numbers]
        marks = ','.join('?' for _ in ids)
        for table in ('ejee_source_tags', 'question_topics', 'topic_classifications'):
            c.execute(f'DELETE FROM {table} WHERE question_id IN ({marks})', ids)
        c.execute(f'DELETE FROM questions WHERE id IN ({marks})', ids)
        stamp = uuid4().hex[:8]
        moved = [(out / str(paper_id) / n, f'{paper_id}-{n}-{stamp}') for n in sorted(numbers, key=_natural)]
        # Manifests lose the deleted items (rewritten last, so a failure above leaves them intact).
        for manifest_path in [archive / 'import-manifest.json', *sorted((archive / 'batches').glob('*/import-manifest.json'))]:
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                kept = [item for item in manifest['items'] if item['number'] not in numbers]
                if len(kept) != len(manifest['items']):
                    manifest['items'] = kept
                    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()
    for folder, label in moved:
        _trash(folder, label)
    return {'paper_id': int(paper_id), 'deleted': len(numbers)}


def delete_collections(paper_ids):
    """Remove whole collections. Their folders are moved to `<library>/trash/` (recoverable)."""
    paper_ids = [int(i) for i in dict.fromkeys(paper_ids)]
    store = library.store()
    out, archive = store['outputs'], store['data'] / 'archive' / 'ejee'
    c = library.connect()
    c.execute('PRAGMA foreign_keys=ON')
    try:
        c.execute('BEGIN IMMEDIATE')
        for pid in paper_ids:
            if c.execute("SELECT 1 FROM papers WHERE id=? AND exam_type='EJEE collection'", (pid,)).fetchone() is None:
                raise FileNotFoundError(f'Collection {pid} not found')
        for pid in paper_ids:
            c.execute('DELETE FROM papers WHERE id=?', (pid,))
        for table in ('ejee_source_tags', 'question_topics', 'topic_classifications'):
            c.execute(f'DELETE FROM {table} WHERE question_id NOT IN (SELECT id FROM questions)')
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()
    stamp = uuid4().hex[:8]
    for pid in paper_ids:
        _trash(out / str(pid), f'collection-{pid}-outputs-{stamp}')
        _trash(archive / str(pid), f'collection-{pid}-sources-{stamp}')
    order = library.saved_order()
    kept = [i for i in order if i not in paper_ids]
    if kept != order:
        (store['root'] / 'collection_order.json').write_text(json.dumps(kept), encoding='utf-8')
    return {'deleted': paper_ids}


def merge_and_replace(paper_ids, title, remove_originals=False):
    result = merge(paper_ids, title)
    if remove_originals:
        delete_collections(paper_ids)
        result['removed'] = list(dict.fromkeys(paper_ids))
    return result


def split_collection(paper_id, numbers, title):
    """Move `numbers` out of a collection into a new one titled `title` (renumbered 1..N)."""
    numbers = {str(n) for n in numbers}
    result = merge([paper_id], title, only={paper_id: numbers}, dedupe=False)
    if result['questions'] != len(numbers):
        raise ValueError('Some of the chosen questions could not be copied; nothing was removed from the source.')
    delete_questions(paper_id, numbers)
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--title', required=True)
    parser.add_argument('ids', nargs='+', type=int)
    args = parser.parse_args()
    print(json.dumps(merge(args.ids, args.title)))
