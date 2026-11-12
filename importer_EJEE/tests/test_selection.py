import json
import io
from pathlib import Path
import shutil
import sqlite3
import sys

import pytest
from PIL import Image

APP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(APP))
from importer_EJEE import app_service as service, selection


@pytest.fixture
def source(tmp_path,monkeypatch):
    sample=APP/'importer_EJEE/sample_data'
    db=tmp_path/'source.db';shutil.copy2(sample/'ejee_sample.db',db)
    monkeypatch.setattr(service,'WEB',tmp_path/'jobs')
    with sqlite3.connect(db) as c:
        c.execute("UPDATE resources SET source='Unmapped source',grp='arbitrary-group',qtype='Numerical',fav=1 WHERE grp='morin-1.1'")
        c.execute("UPDATE resources SET source='Other source',grp='arbitrary-group' WHERE grp='morin-1.2'")
        c.execute("UPDATE resources SET part=NULL,grp=NULL,title='literal 50%_ problem' WHERE id=67766")
    service.configure(db,sample/'source_assets')
    return db


def test_filters_use_real_node_descendants_and_model_not_adapter(source):
    with sqlite3.connect(source) as c:
        parent=c.execute('SELECT parent_id FROM nodes WHERE id=268').fetchone()[0]
    result=selection.search({'source':['Unmapped source'],'node_id':parent,'qtype':'Numerical','fav':True})
    assert [r['id'] for r in result['items']]==[67760]
    assert result['items'][0]['solution_parts']==2
    assert result['items'][0]['ready']
    assert selection.search({'source':['Unmapped source'],'qtype':'Subjective'})['total']==0
    assert 'Numerical' in [v['value'] for v in selection.facets()['qtype']]


def test_snapshot_keeps_only_exact_selected_group_with_own_solutions(source):
    before=source.read_bytes()
    frozen=selection.snapshot([67760,67760])
    assert frozen['included_resource_ids']==[67760,67761,67762]
    assert len(frozen['items'])==1
    assert len(frozen['items'][0]['solution_rows'])==2
    assert frozen['items'][0]['question_rows'][0]['source']=='Unmapped source'
    assert source.read_bytes()==before
    assert selection.preview(67760).startswith(b'\x89PNG')


def test_gallery_metadata_and_full_size_image_remain_read_only_and_source_scoped(source):
    before=source.read_bytes();token=selection.source_token()
    info=selection.details(67760,token)
    assert info['source']=='Unmapped source' and info['solution_parts']==2
    assert info['question_parts'][0]['id']==67760
    assert 'file_name' not in info and 'print_meta' not in info
    full=Image.open(io.BytesIO(selection.preview(67760,'full',token)))
    thumb=Image.open(io.BytesIO(selection.preview(67760,'thumbnail',token)))
    assert thumb.width<=480 and thumb.height<=360
    assert full.width>thumb.width or full.height>thumb.height
    assert source.read_bytes()==before
    with pytest.raises(ValueError,match='source changed'):selection.preview(67760,'full','0'*64)
    with pytest.raises(ValueError,match='source changed'):selection.details(67760,'0'*64)
    with pytest.raises(FileNotFoundError):selection.details(67761,token)


def test_null_group_is_independent_and_like_search_is_literal(source):
    result=selection.search({'q':'50%_'})
    assert [r['id'] for r in result['items']]==[67766]
    item=selection.snapshot([67766])['items'][0]
    assert item['solution_rows']==[]
    assert item['question_rows'][0]['part']=='q'
    assert item['question_rows'][0]['source_part'] is None


def test_identity_is_independent_of_click_order_and_keeps_same_group_sources_apart(source):
    a=selection.snapshot([67760,67763]);b=selection.snapshot([67763,67760])
    assert a['fingerprint']==b['fingerprint']
    assert len(a['items'])==2
    assert {r['source'] for r in a['items'][0]['solution_rows']}=={'Unmapped source'}
    assert {r['source'] for r in a['items'][1]['solution_rows']}=={'Other source'}


def test_continuations_deduplicate_and_ambiguous_mapping_is_rejected(source):
    with sqlite3.connect(source) as c:
        c.execute("UPDATE resources SET source='Unmapped source',grp='arbitrary-group' WHERE id=67763")
    with pytest.raises(ValueError,match='multiple question cards'):selection.snapshot([67760])
    with sqlite3.connect(source) as c:
        c.execute("UPDATE resources SET title='Question (1/2)' WHERE id=67760")
        c.execute("UPDATE resources SET title='Question (2/2)' WHERE id=67763")
    frozen=selection.snapshot([67763,67760])
    assert len(frozen['items'])==1
    assert [r['id'] for r in frozen['items'][0]['question_rows']]==[67760,67763]


def test_invalid_selection_and_unsafe_assets_rejected_before_ai(source):
    with pytest.raises(ValueError):selection.snapshot([67761])
    with pytest.raises(ValueError):selection.snapshot([999999999])
    with sqlite3.connect(source) as c:c.execute("UPDATE resources SET file_name='../outside.png' WHERE id=67760")
    assert not selection.search({'source':'Unmapped source'})['items'][0]['ready']
    with pytest.raises(ValueError,match='unavailable'):selection.snapshot([67760])
