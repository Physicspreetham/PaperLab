"""Merging EJEE collections: ordering, dedupe, provenance, originals untouched. Isolated library."""
import json

import pytest

from importer_EJEE import library_store, merge_collections


def _ancestry(chapter_pos, topic_pos):
    return [{'id': 100 + topic_pos, 'position': topic_pos, 'level': 'topic', 'name': f't{topic_pos}'},
            {'id': 10 + chapter_pos, 'position': chapter_pos, 'level': 'chapter', 'name': f'c{chapter_pos}'}]


def _collection(pid, items, root):
    """items: [(number, source, title, chapter_pos, topic_pos, source_key)]"""
    from importer_EJEE.source_tagging import ensure_table
    c = library_store.connect()
    ensure_table(c)
    c.execute("INSERT INTO papers (id,paper_name,exam_type,source_institute,status,pdf_hash,archive) VALUES (?,?,?,?,?,?,?)",
              (pid, f'col{pid}', 'EJEE collection', 'Mixed', 'done', f'h{pid}', 1))
    arc = root / 'data' / 'archive' / 'ejee' / str(pid)
    arc.mkdir(parents=True)
    (arc / 'img-body.png').write_bytes(b'png')
    manifest_items = []
    for number, source, title, chapter_pos, topic_pos, key in items:
        qid = c.execute("INSERT INTO questions (paper_id,question_number,latex_folder,status) VALUES (?,?,?,?)",
                        (pid, number, str(root / 'Outputs' / str(pid) / number), 'draft')).lastrowid
        c.execute("INSERT INTO ejee_source_tags VALUES (?,?)",
                  (qid, json.dumps({'resources': [{'id': qid, 'ancestry': _ancestry(chapter_pos, topic_pos)}]})))
        folder = root / 'Outputs' / str(pid) / number
        folder.mkdir(parents=True)
        (folder / 'question.tex').write_text(f'Q {pid}-{number}', encoding='utf-8')
        manifest_items.append({'number': number, 'source_key': key, 'source_number': title,
                               'question_rows': [{'source': source, 'title': title}], 'solution_rows': []})
    (arc / 'import-manifest.json').write_text(json.dumps({'items': manifest_items}), encoding='utf-8')
    c.commit()
    c.close()


@pytest.fixture
def library(tmp_db, tmp_path, monkeypatch):
    monkeypatch.setenv('PAPERLAB_EJEE_LIBRARY_ROOT', str(tmp_path / 'textbooks'))
    monkeypatch.setattr(library_store, '_ready', set())
    return library_store.store()['root']


def test_merge_orders_by_syllabus_then_source_and_keeps_originals(library):
    _collection(1, [('1', 'B book', 'Q1', 2, 1, 'k-b1'), ('2', 'A book', 'Q2', 1, 2, 'k-a2')], library)
    _collection(2, [('1', 'A book', 'Q10', 1, 1, 'k-a10'), ('2', 'A book', 'Q9', 1, 1, 'k-a9'),
                    ('3', 'B book', 'Q1', 2, 1, 'k-b1')], library)  # k-b1 duplicates collection 1
    result = merge_collections.merge([1, 2], 'merged')
    assert result['questions'] == 4 and result['skipped_duplicates'] == 1
    pid = result['paper_id']
    served = library_store.questions(pid)
    assert served['paper']['title'] == 'merged'
    # chapter 1/topic 1 (A book: Q9 then Q10), chapter 1/topic 2, then chapter 2.
    texts = [(library / 'Outputs' / str(pid) / q['number'] / 'question.tex').read_text(encoding='utf-8')
             for q in served['questions']]
    assert texts == ['Q 2-2', 'Q 2-1', 'Q 1-2', 'Q 1-1']
    # Originals are untouched.
    assert len(library_store.questions(1)['questions']) == 2
    assert len(library_store.questions(2)['questions']) == 3
    # Provenance numbers were remapped to the new numbering.
    manifest = json.loads((library / 'data' / 'archive' / 'ejee' / str(pid) / 'import-manifest.json')
                          .read_text(encoding='utf-8'))
    assert sorted(item['number'] for item in manifest['items']) == ['3', '4']


def test_merge_rejects_missing_or_single_collection(library):
    _collection(1, [('1', 'A', 'Q1', 1, 1, 'k1')], library)
    with pytest.raises(ValueError):
        merge_collections.merge([1], 'x')
    with pytest.raises(ValueError):
        merge_collections.merge([1, 99], 'x')


def test_delete_questions_trashes_folder_and_frees_the_question_for_reimport(library):
    _collection(1, [('1', 'A', 'Q1', 1, 1, 'k1'), ('2', 'A', 'Q2', 1, 1, 'k2'), ('3', 'A', 'Q3', 1, 1, 'k3')], library)
    assert merge_collections.delete_questions(1, ['2'])['deleted'] == 1
    assert [q['number'] for q in library_store.questions(1)['questions']] == ['1', '3']
    assert not (library / 'Outputs' / '1' / '2').exists()
    assert any(library.glob('trash/1-2-*/question.tex'))  # recoverable
    manifest = json.loads((library / 'data' / 'archive' / 'ejee' / '1' / 'import-manifest.json').read_text(encoding='utf-8'))
    assert [item['source_key'] for item in manifest['items']] == ['k1', 'k3']
    c = library_store.connect()
    assert c.execute('SELECT count(*) FROM ejee_source_tags').fetchone()[0] == 2
    c.close()
    with pytest.raises(FileNotFoundError):
        merge_collections.delete_questions(1, ['2'])
    with pytest.raises(ValueError):  # never empty a collection
        merge_collections.delete_questions(1, ['1', '3'])


def test_split_collection_moves_questions_into_a_new_collection(library):
    _collection(1, [(str(i), 'A', f'Q{i}', 1, i, f'k{i}') for i in range(1, 6)], library)
    result = merge_collections.split_collection(1, ['4', '5'], 'second half')
    assert result['questions'] == 2
    assert [q['number'] for q in library_store.questions(1)['questions']] == ['1', '2', '3']
    moved = library_store.questions(result['paper_id'])
    assert moved['paper']['title'] == 'second half' and [q['number'] for q in moved['questions']] == ['1', '2']
    assert (library / 'Outputs' / str(result['paper_id']) / '1' / 'question.tex').read_text(encoding='utf-8') == 'Q 1-4'


def test_merge_and_replace_can_remove_originals_into_trash(library):
    _collection(1, [('1', 'A', 'Q1', 1, 1, 'k1')], library)
    _collection(2, [('1', 'A', 'Q2', 1, 2, 'k2')], library)
    kept = merge_collections.merge_and_replace([1, 2], 'both')
    assert kept['questions'] == 2 and len(library_store.papers()) == 3  # originals kept by default
    result = merge_collections.merge_and_replace([1, 2], 'both again', remove_originals=True)
    assert result['removed'] == [1, 2]
    assert sorted(p['title'] for p in library_store.papers()) == ['both', 'both again']
    assert not (library / 'Outputs' / '1').exists() and any(library.glob('trash/collection-1-outputs-*/1/question.tex'))
    # Merged collections stay complete after the originals are gone.
    assert [q['number'] for q in library_store.questions(result['paper_id'])['questions']] == ['1', '2']
    c = library_store.connect()
    assert c.execute('SELECT count(*) FROM ejee_source_tags').fetchone()[0] == 4  # 2 + 2 in the merged copies
    c.close()


def test_delete_collection_moves_files_to_trash_and_drops_rows(library):
    _collection(1, [('1', 'A', 'Q1', 1, 1, 'k1')], library)
    _collection(2, [('1', 'A', 'Q2', 1, 2, 'k2')], library)
    merge_collections.delete_collections([1])
    assert [p['id'] for p in library_store.papers()] == [2]
    assert not (library / 'Outputs' / '1').exists() and any(library.glob('trash/collection-1-outputs-*/1/question.tex'))
    assert len(library_store.questions(2)['questions']) == 1
    with pytest.raises(FileNotFoundError):
        merge_collections.delete_collections([1])
