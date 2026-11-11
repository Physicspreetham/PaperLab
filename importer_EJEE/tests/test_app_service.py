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
