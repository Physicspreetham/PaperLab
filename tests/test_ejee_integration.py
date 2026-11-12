"""App imports must stay out of the regular question-paper database/files."""
from pathlib import Path
import json
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import config
import database
import directory_manager
from backend.deps import require_admin
from backend.routers import ejee
from importer_EJEE import app_service, library_store


@pytest.fixture
def ejee_app(tmp_db,tmp_path,monkeypatch):
    monkeypatch.setenv('PAPERLAB_EJEE_LIBRARY_ROOT',str(tmp_path/'textbooks'))
    monkeypatch.setattr(library_store,'_ready',set())
    monkeypatch.setattr(app_service,'ROOT',tmp_path/'importer')
    monkeypatch.setattr(app_service,'WEB',tmp_path/'importer'/'jobs')
    monkeypatch.setattr(app_service,'_live',{})
    monkeypatch.setattr(config,'LLM_API_KEY','test-key-not-used')
    app=FastAPI()
    app.include_router(ejee.router,prefix='/api/ejee')
    app.include_router(ejee.library_router,prefix='/api/ejee/library')
    return app


def test_import_endpoints_require_archivist_access(ejee_app):
    client=TestClient(ejee_app)
    assert client.get('/api/ejee/catalogue').status_code==401
    assert client.post('/api/ejee/jobs',json={'book_id':'morin','chapters':['1']}).status_code==401
    assert client.put('/api/ejee/source',json={'source_db':'x','asset_root':'y'}).status_code==401
    assert client.get('/api/ejee/filters').status_code==401
    assert client.post('/api/ejee/questions/search',json={}).status_code==401
    assert client.get('/api/ejee/questions/67760/preview').status_code==401
    assert client.get('/api/ejee/usage/selection').status_code==401


def test_empty_regular_database_still_gets_separate_textbook_syllabus(ejee_app,tmp_db):
    target=library_store.store()
    with sqlite3.connect(target['db']) as c:
        assert c.execute('SELECT count(*) FROM topics').fetchone()[0]>0
        assert c.execute('SELECT count(*) FROM papers').fetchone()[0]==0
    with sqlite3.connect(tmp_db) as c:
        assert c.execute('SELECT count(*) FROM topics').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM papers').fetchone()[0]==0


def test_book_import_job_targets_separate_database_and_folder(ejee_app,tmp_db,tmp_path,monkeypatch):
    ejee_app.dependency_overrides[require_admin]=lambda:True
    fixture=Path(__file__).resolve().parents[1]/'importer_EJEE/sample_data'
    captured=[]
    def launch(job_id,environment):
        captured.append(job_id);app_service._live[job_id]=object()
    monkeypatch.setattr(app_service,'launch',launch)
    client=TestClient(ejee_app)
    result=client.put('/api/ejee/source',json={'source_db':str(fixture/'ejee_sample.db'),'asset_root':str(fixture/'source_assets')})
    assert result.status_code==200
    assert result.json()['books'][0]['source'].startswith('David Morin')
    first=client.post('/api/ejee/jobs',json={'book_id':'morin','chapters':['2']})
    assert first.status_code==202
    job=first.json()['jobs'][0]
    target=library_store.store()
    assert Path(job['target_db'])==target['db']!=tmp_db
    assert Path(job['target_outputs'])==target['outputs']
    assert target['root'] in target['outputs'].parents
    assert target['root'] in target['db'].parents
    # Repeating a click returns the existing job; it cannot charge twice.
    second=client.post('/api/ejee/jobs',json={'book_id':'morin','chapters':['2']})
    assert second.json()['jobs'][0]['id']==job['id'] and len(captured)==1
    with sqlite3.connect(tmp_db) as c:
        assert c.execute('SELECT count(*) FROM papers').fetchone()[0]==0
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='ejee_imports'").fetchone()
    assert client.get('/api/ejee/library/papers').json()==[]
    assert client.get('/api/ejee/usage').json()['total_usd']==0


def test_imported_figure_paths_do_not_read_normal_archive(ejee_app,tmp_path):
    target=library_store.store()
    # IDs may overlap, but the figure endpoint is restricted to textbook files.
    fig=target['outputs']/'1'/'1'/'figures'/'qfig1.png';fig.parent.mkdir(parents=True)
    fig.write_bytes(b'textbook figure')
    client=TestClient(ejee_app)
    assert client.get('/api/ejee/library/papers/1/questions/1/figures/qfig1.png').content==b'textbook figure'
    assert client.get('/api/ejee/library/papers/1/questions/1/figures/secret.txt').status_code==400
    assert client.get('/api/ejee/library/papers/999/questions').status_code==404


def test_selective_import_freezes_only_selection_in_separate_store(ejee_app,tmp_db,monkeypatch):
    ejee_app.dependency_overrides[require_admin]=lambda:True
    sample=Path(__file__).resolve().parents[1]/'importer_EJEE/sample_data'
    client=TestClient(ejee_app);captured=[]
    monkeypatch.setattr(app_service,'launch',lambda jid,env:captured.append(jid))
    assert client.put('/api/ejee/source',json={'source_db':str(sample/'ejee_sample.db'),'asset_root':str(sample/'source_assets')}).status_code==200
    facets=client.get('/api/ejee/filters').json()
    cards=client.post('/api/ejee/questions/search',json={'filters':{'qtype':'Subjective'},'limit':2}).json()
    assert len(cards['items'])==2 and cards['items'][0]['ready']
    assert client.get('/api/ejee/questions/67760/preview').headers['content-type']=='image/png'
    body={'name':'My selected problems','resource_ids':[67760,67763],'source_token':facets['source_token']}
    first=client.post('/api/ejee/selections',json=body)
    assert first.status_code==202,first.text
    job=first.json();folder=app_service.WEB/job['id']
    cfg=json.loads((folder/'config.json').read_text())
    frozen=json.loads((folder/'selection.json').read_text())
    assert cfg['collection_name']=='My selected problems' and cfg['group_pattern']==''
    assert len(frozen['items'])==job['total']==2
    assert [r['id'] for item in frozen['items'] for r in item['question_rows']]==[67760,67763]
    assert Path(job['target_db'])==library_store.store()['db']!=tmp_db
    assert client.post('/api/ejee/selections',json=body).json()['id']==job['id']
    assert len(captured)==1
    assert client.post('/api/ejee/selections',json={**body,'source_token':'0'*64}).status_code==400
    with sqlite3.connect(tmp_db) as c:assert c.execute('SELECT count(*) FROM papers').fetchone()[0]==0


def test_selection_ledger_counts_published_once_and_failed_worker_usage(ejee_app,tmp_db,monkeypatch):
    ejee_app.dependency_overrides[require_admin]=lambda:True
    target=library_store.store()
    with sqlite3.connect(target['db']) as c:
        c.execute("INSERT INTO papers(id,paper_name,exam_type,status) VALUES(1,'Selected problems','EJEE collection','done')")
        c.execute("INSERT INTO papers(id,paper_name,exam_type,status) VALUES(2,'Whole chapter','Textbook','done')")
        c.execute("INSERT INTO token_usage(paper_id,phase,input,cache_read,output,reasoning) VALUES(1,'extractor',1000,200,100,50)")
        c.execute("INSERT INTO token_usage(paper_id,phase,input,output) VALUES(1,'topics',500,50)")
        c.execute("INSERT INTO token_usage(paper_id,phase,input,output) VALUES(2,'extractor',999999,999999)")
        c.execute('CREATE TABLE ejee_imports(source_key TEXT,paper_id INTEGER)')
        c.execute("INSERT INTO ejee_imports VALUES('published-key',1)")
    job={'id':'a'*32,'kind':'selection','target_db':str(target['db']),'source_key':'new-key','chapter':'Interrupted import','book':'Source','total':1,'status':'failed'}
    worker=app_service.WEB/job['id']/'paperlab.db';worker.parent.mkdir(parents=True)
    database.init_db(worker)
    with sqlite3.connect(worker) as c:
        c.execute("INSERT INTO papers(id) VALUES(1)")
        c.execute("INSERT INTO token_usage(paper_id,phase,input,output) VALUES(1,'extractor',100,10)")
    monkeypatch.setattr(app_service,'list_jobs',lambda:[job,{**job,'id':'b'*32,'source_key':'published-key'}])
    result=TestClient(ejee_app).get('/api/ejee/usage/selection').json()
    assert result['collections']==2 and result['totals']['calls']==3
    assert result['totals']['input']==1600 and result['totals']['cached']==200
    assert result['totals']['output']==160 and result['totals']['reasoning']==50
    expected=(1400*config.PRICING['input_per_mtok']+200*config.PRICING['cache_read_per_mtok']+160*config.PRICING['output_per_mtok'])/1e6
    assert result['totals']['cost_usd']==pytest.approx(expected)
    assert {r['status'] for r in result['rows']}=={'done','failed'}
    with sqlite3.connect(tmp_db) as c:assert c.execute('SELECT count(*) FROM token_usage').fetchone()[0]==0


def test_ejee_cart_details_stay_scoped_with_overlapping_paper_ids(ejee_app,tmp_db):
    target=library_store.store()
    with sqlite3.connect(target['db']) as c:
        c.execute("INSERT INTO papers(id,paper_name,source_institute) VALUES(1,'Selected EJEE','Book')")
        c.execute("INSERT INTO questions(paper_id,question_number) VALUES(1,'1')")
    folder=target['outputs']/'1'/'1';folder.mkdir(parents=True)
    (folder/'question.tex').write_text('EJEE statement')
    (folder/'solution.tex').write_text('EJEE solution')
    with sqlite3.connect(tmp_db) as c:c.execute("INSERT INTO papers(id,paper_name) VALUES(1,'Ordinary paper')")
    client=TestClient(ejee_app)
    assert client.get('/api/ejee/library/papers/1').json()['title']=='Selected EJEE'
    single=client.get('/api/ejee/library/papers/1/questions/1')
    assert single.status_code==200 and 'EJEE statement' in single.text
    assert client.get('/api/ejee/library/papers/1/questions/2').status_code==404
