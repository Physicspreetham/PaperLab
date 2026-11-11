"""App imports must stay out of the regular question-paper database/files."""
from pathlib import Path
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
