import json
from pathlib import Path
import shutil
import sqlite3
import sys

import pytest

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(APP))
from importer_EJEE import app_service as service
from importer_EJEE.publish import publish_chapter


def fixture_target(tmp_path):
    target=tmp_path/'target.db'
    with sqlite3.connect(APP/'importer_EJEE/sample_data/paperlab.db') as src, sqlite3.connect(target) as dst:
        src.backup(dst)
        dst.execute('PRAGMA foreign_keys=ON')
        dst.execute('DELETE FROM papers WHERE id=2')
    return target


def isolated_run(tmp_path):
    run=tmp_path/'run';run.mkdir()
    sample=APP/'importer_EJEE/sample_data'
    with sqlite3.connect(sample/'paperlab.db') as src, sqlite3.connect(run/'paperlab.db') as dst:src.backup(dst)
    # Source fixture paper 2 is a small real two-question chapter with solutions.
    manifest={'paper_id':2,'items':[{'number':'1'},{'number':'2'}],'solution_pdf':True}
    (run/'manifest.json').write_text(json.dumps(manifest))
    (run/'verification.json').write_text(json.dumps({'ok':True}))
    (run/'config.json').write_text(json.dumps({'source_key':'test-morin-2','book_source':'Morin','chapter':'2'}))
    with sqlite3.connect(run/'paperlab.db') as c:
        c.row_factory=sqlite3.Row
        topics=[dict(r) for r in c.execute('SELECT * FROM topics ORDER BY rowid')]
    (run/'target_topics.json').write_text(json.dumps(topics))
    shutil.copytree(sample/'Outputs'/'2',run/'Outputs'/'2')
    shutil.copytree(sample/'data'/'sources'/'2',run/'sources')
    return run


def test_catalogue_uses_book_group_chapters_and_reads_source_only(tmp_path,monkeypatch):
    monkeypatch.setattr(service,'WEB',tmp_path/'jobs')
    sample=APP/'importer_EJEE/sample_data'
    source=tmp_path/'ejee.db';shutil.copy2(sample/'ejee_sample.db',source)
    before=source.read_bytes()
    service.configure(source,sample/'source_assets')
    result=service.catalogue(fixture_target(tmp_path))
    morin=next(b for b in result['books'] if b['id']=='morin')
    assert [(c['id'],c['questions']) for c in morin['chapters']]==[('1',18),('2',2)]
    assert next(b for b in result['books'] if b['id']=='hibbeler-dynamics')['chapters'][0]['questions']==2
    assert source.read_bytes()==before
    with service.source_connection(source) as c:
        with pytest.raises(sqlite3.OperationalError):c.execute('DELETE FROM resources')


def test_verified_publish_preserves_topics_usage_and_is_idempotent(tmp_path):
    target=fixture_target(tmp_path);run=isolated_run(tmp_path)
    out=tmp_path/'Outputs';data=tmp_path/'data'
    first=publish_chapter(run,target,out,data)
    second=publish_chapter(run,target,out,data)
    assert first['paper_id']==second['paper_id']==4 and second['already_imported']
    with sqlite3.connect(target) as c:
        assert c.execute('SELECT count(*) FROM papers').fetchone()[0]==3
        assert c.execute('SELECT count(*) FROM questions WHERE paper_id=4').fetchone()[0]==2
        assert c.execute('SELECT count(*) FROM token_usage WHERE paper_id=4').fetchone()[0]==8
        assert c.execute('SELECT count(*) FROM question_topics t JOIN questions q ON t.question_id=q.id WHERE q.paper_id=4').fetchone()[0]==2
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
    assert (out/'4'/'1'/'question.tex').is_file()
    assert (data/'archive/ejee/4/questions.pdf').is_file()


def test_publish_copies_original_ejee_metadata_with_new_question_ids(tmp_path):
    from importer_EJEE.source_tagging import ensure_table
    target=fixture_target(tmp_path);run=isolated_run(tmp_path)
    metadata={'resources':[{'id':42,'tags':'Thermal Physics','difficulty':'Olympiad','ancestry':[]}]}
    with sqlite3.connect(run/'paperlab.db') as c:
        ensure_table(c)
        qid=c.execute('SELECT id FROM questions WHERE paper_id=2 ORDER BY id LIMIT 1').fetchone()[0]
        c.execute('INSERT INTO ejee_source_tags VALUES (?,?)',(qid,json.dumps(metadata)))
    result=publish_chapter(run,target,tmp_path/'Outputs',tmp_path/'data')
    with sqlite3.connect(target) as c:
        saved=c.execute('SELECT t.metadata FROM ejee_source_tags t JOIN questions q ON q.id=t.question_id WHERE q.paper_id=?',(result['paper_id'],)).fetchone()
        assert json.loads(saved[0])==metadata
        assert not c.execute('PRAGMA foreign_key_check').fetchall()


def test_publish_append_preserves_existing_question_ids_and_order(tmp_path, monkeypatch):
    from importer_EJEE import library_store

    target = fixture_target(tmp_path)
    run = isolated_run(tmp_path)
    out, data = tmp_path / 'Outputs', tmp_path / 'data'
    with sqlite3.connect(run / 'paperlab.db') as c:
        c.execute("UPDATE papers SET exam_type='EJEE collection' WHERE id=2")
    pid = publish_chapter(run, target, out, data)['paper_id']
    with sqlite3.connect(target) as c:
        existing = c.execute('SELECT id,question_number FROM questions WHERE paper_id=? ORDER BY id', (pid,)).fetchall()
    original = (out / str(pid) / '1' / 'question.tex').read_bytes()
    cfg = {'source_key':'append-test', 'book_source':'New source', 'chapter':'selection', 'append_paper_id':pid}
    (run / 'config.json').write_text(json.dumps(cfg))
    manifest = json.loads((run / 'manifest.json').read_text())
    for index, item in enumerate(manifest['items']):
        item['question_rows'] = [{'id':index + 100, 'grp':None, 'source':'New source'}]
    (run / 'manifest.json').write_text(json.dumps(manifest))

    collision = out / str(pid) / '4'
    collision.mkdir()
    with pytest.raises(ValueError, match='Output folder already exists'):
        publish_chapter(run, target, out, data)
    assert not (out / str(pid) / '3').exists()
    with sqlite3.connect(target) as c:
        assert c.execute('SELECT id,question_number FROM questions WHERE paper_id=? ORDER BY id', (pid,)).fetchall() == existing
    collision.rmdir()

    assert publish_chapter(run, target, out, data)['paper_id'] == pid
    assert publish_chapter(run, target, out, data)['already_imported']
    with sqlite3.connect(target) as c:
        rows = c.execute('SELECT id,question_number FROM questions WHERE paper_id=? ORDER BY id', (pid,)).fetchall()
        assert rows[:2] == existing
        assert [number for _, number in rows] == ['1', '2', '3', '4']
        assert c.execute('SELECT COUNT(*) FROM token_usage WHERE paper_id=?', (pid,)).fetchone()[0] == 16
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
    assert (out / str(pid) / '1' / 'question.tex').read_bytes() == original
    monkeypatch.setattr(library_store, 'store', lambda: {'db':target, 'outputs':out, 'data':data})
    assert library_store.questions(pid, '3')['questions'][0]['source'] == 'New source'


def test_publish_rejects_stale_syllabus_without_partial_paper(tmp_path):
    target=fixture_target(tmp_path);run=isolated_run(tmp_path)
    with sqlite3.connect(target) as c:c.execute("UPDATE topics SET rev=rev+1 WHERE code=(SELECT code FROM topics LIMIT 1)")
    with pytest.raises(ValueError,match='syllabus changed'):
        publish_chapter(run,target,tmp_path/'Outputs',tmp_path/'data')
    with sqlite3.connect(target) as c:assert c.execute('SELECT count(*) FROM papers').fetchone()[0]==2


def test_failed_file_copy_rolls_back_database(tmp_path,monkeypatch):
    target=fixture_target(tmp_path);run=isolated_run(tmp_path)
    def broken(*args,**kwargs):raise OSError('Simulated disk failure')
    monkeypatch.setattr(shutil,'copytree',broken)
    with pytest.raises(OSError,match='disk failure'):publish_chapter(run,target,tmp_path/'Outputs',tmp_path/'data')
    with sqlite3.connect(target) as c:
        assert c.execute('SELECT count(*) FROM papers').fetchone()[0]==2
        assert c.execute('SELECT count(*) FROM ejee_imports').fetchone()[0]==0


def test_invalid_job_path_and_missing_source_are_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(service,'WEB',tmp_path/'jobs')
    with pytest.raises(ValueError):service.get_job('../outside')
    with pytest.raises(ValueError):service.configure(tmp_path/'missing.db',tmp_path)


def make_job(web, job_id, status='failed', **state):
    folder = web / job_id
    service.write_json(folder / 'state.json', {'id': job_id, 'source_key': 'k', 'book': 'b', 'chapter': 'c', 'total': 3,
        'status': status, 'phase': 'converting', 'target_db': 'T', 'paper_id': None, 'error': None, **state})
    return folder


def test_job_questions_report_each_outcome_and_auto_accepted_crops(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'WEB', tmp_path)
    jid = 'a' * 32
    folder = make_job(tmp_path, jid)
    items = [{'number': str(n), 'group': f'g{n}', 'question_rows': [{'title': f'Q{n}'}]} for n in (1, 2, 3, 4)]
    service.write_json(folder / 'manifest.json', {'items': items})
    service.write_json(folder / 'progress.json', {'questions': {'1': {'ok': True, 'turns': 3},
        '2': {'ok': False, 'needs_review': True, 'error': 'crop'}, '3': {'ok': False, 'error': 'boom'}}})
    service.write_json(folder / 'auto_crop_reviews.json', [{'group': 'g1', 'filename': 'qfig1.png'}])
    rows = service.job_questions(jid)
    assert [r['status'] for r in rows] == ['done', 'review', 'failed', 'pending']
    assert rows[0]['auto_accepted'] == ['qfig1.png'] and rows[0]['label'] == 'Q1'
    state = service.get_job(jid)
    assert state['auto_accepted_crops'] == 1 and state['tagging_mode'] == 'source' and not state['can_cancel']


def test_only_stopped_jobs_can_be_removed_and_other_databases_are_protected(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'WEB', tmp_path)
    failed, done = 'b' * 32, 'c' * 32
    make_job(tmp_path, failed); make_job(tmp_path, done, status='done', phase='done')
    with pytest.raises(ValueError, match='another'):service.delete_job(failed, 'OTHER')
    with pytest.raises(ValueError, match='Only stopped'):service.delete_job(done, 'T')
    assert service.delete_job(failed, 'T') == {'removed': failed}
    assert not (tmp_path / failed).exists() and (tmp_path / done).exists()
    with pytest.raises(ValueError, match='not running'):service.cancel_job(done, 'T')


def test_collection_title_rename_validates_and_keeps_content(tmp_path, monkeypatch):
    from importer_EJEE import library_store as library
    target = fixture_target(tmp_path)
    with sqlite3.connect(target) as c:
        c.execute("UPDATE papers SET exam_type='EJEE collection' WHERE id IN (1,3)")
        names = dict(c.execute('SELECT id,paper_name FROM papers WHERE id IN (1,3)'))
    monkeypatch.setattr(library, 'store', lambda: {'db': target, 'outputs': tmp_path, 'data': tmp_path})
    assert library.rename(1, '  Electrostatics   set  ') == {'id': 1, 'title': 'Electrostatics set'}
    with pytest.raises(ValueError, match='already uses'):library.rename(3, 'Electrostatics set')
    with pytest.raises(ValueError):library.rename(1, '   ')
    with pytest.raises(ValueError):library.rename(1, 'x' * 181)
    with pytest.raises(FileNotFoundError):library.rename(999, 'Missing')
    with sqlite3.connect(target) as c:
        assert c.execute('SELECT paper_name FROM papers WHERE id=3').fetchone()[0] == names[3]


def test_published_figure_can_be_recropped_from_archived_source_and_restored(tmp_path, monkeypatch):
    import hashlib
    from io import BytesIO
    from PIL import Image, ImageDraw
    from importer_EJEE import library_store as library, collection_figures as figures
    monkeypatch.setattr(library, 'store', lambda: {'db': tmp_path/'x.db', 'outputs': tmp_path/'Outputs', 'data': tmp_path/'data'})
    source = Image.new('RGB', (400, 200), 'white')
    draw = ImageDraw.Draw(source)
    draw.rectangle((100, 40, 250, 160), outline='black', width=3)
    draw.line((250, 100, 380, 100), fill='black', width=3)  # lead the first crop cut off
    archive = tmp_path/'data'/'archive'/'ejee'/'7'; archive.mkdir(parents=True)
    buf = BytesIO(); source.save(buf, format='PNG'); (archive/'10-body.png').write_bytes(buf.getvalue())
    folder = tmp_path/'Outputs'/'7'/'3'/'figures'; folder.mkdir(parents=True)
    source.crop((90, 30, 260, 170)).save(folder/'qfig1.png')
    service.write_json(folder/'_import_provenance.json', {'qfig1.png': {
        'source_body': r'C:\runs\x\sources\10-body.png', 'source_sha256': hashlib.sha256(buf.getvalue()).hexdigest(),
        'requested_source_pixel_box': [90, 30, 260, 170], 'source_pixel_box': [100, 40, 251, 161],
        'edge_warnings': ['right'], 'confirmed_edge_warnings': ['right']}})
    row = figures.list_figures(7, '3')[0]
    assert row['name'] == 'qfig1.png' and row['needs_check'] and not row['edited']
    assert figures.source_image(7, '3', 'qfig1.png') == buf.getvalue()
    png, edges = figures.edit_figure(7, '3', 'qfig1.png', (.2, .15, 1.0, .9), 0, False)
    assert Image.open(folder/'qfig1.png').size == (170, 140)
    with pytest.raises(ValueError, match='reaches the crop edge'):
        figures.edit_figure(7, '3', 'qfig1.png', (.2, .15, .75, .9), 0, True)
    figures.edit_figure(7, '3', 'qfig1.png', (.2, .15, .99, .9), 0, True)
    assert Image.open(folder/'qfig1.png').width > 170 and (folder/'_originals'/'qfig1.png').is_file()
    assert figures.list_figures(7, '3')[0]['edited']
    figures.restore_original(7, '3', 'qfig1.png')
    assert Image.open(folder/'qfig1.png').size == (170, 140)
    with pytest.raises(ValueError):figures.edit_figure(7, '3', 'qfig1.png', (.5, .1, .4, .9), 0, False)
    with pytest.raises(ValueError):figures.list_figures(7, '../x')
