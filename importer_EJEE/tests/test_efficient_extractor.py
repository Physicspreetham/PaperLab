from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from efficient_extractor import build_tools,prune_old_preview


def fixture_tools(tmp_path,monkeypatch,question_result='saved',solution_result='saved'):
    calls=[]
    def native(side,result):
        def invoke(args):calls.append((side,args));return result
        return SimpleNamespace(invoke=invoke)
    native_tools=SimpleNamespace(submit_question=native('question',question_result),submit_solution=native('solution',solution_result),assisted_crop='native-assisted',exact_crop='native-exact')
    source=tmp_path/'source.png';im=Image.new('RGB',(500,300),'white');ImageDraw.Draw(im).rectangle((100,100,200,200),fill='blue');im.save(source)
    manifest={'paper_id':7,'question_pdf':'mapped-q.pdf','solution_pdf':'mapped-s.pdf'}
    item={'number':'3','question_pages':[2],'solution_pages':[4],'question_rows':[{'asset_evidence':{'body_png':str(source)}}]}
    folder=tmp_path/'question';folder.mkdir()
    monkeypatch.setitem(sys.modules,'directory_manager',SimpleNamespace(ensure_question_dir=lambda *args:folder))
    tools=build_tools(native_tools,manifest,item,tool_decorator=lambda fn:fn)
    return tools,calls,folder


def test_paired_save_reuses_both_native_validators_in_order(tmp_path,monkeypatch):
    (_,_,pair),calls,_=fixture_tools(tmp_path,monkeypatch)
    assert pair(7,'3','Question','Solution','scq')=='saved'
    assert [c[0] for c in calls]==['question','solution']
    assert calls[0][1]['latex_content']=='Question' and calls[1][1]['latex_content']=='Solution'


def test_failed_question_never_saves_solution_and_solution_error_is_not_success(tmp_path,monkeypatch):
    (_,_,pair),calls,_=fixture_tools(tmp_path,monkeypatch,question_result='NOT SAVED: bad syntax')
    assert pair(7,'3','bad','solution').startswith('QUESTION NOT SAVED')
    assert len(calls)==1
    with pytest.raises(ValueError):pair(99,'3','q','s')


def test_native_solution_failure_requires_repair(tmp_path,monkeypatch):
    (_,_,pair),calls,_=fixture_tools(tmp_path,monkeypatch,solution_result='NOT SAVED: answer key')
    assert pair(7,'3','q','s').startswith('SOLUTION NOT SAVED')
    assert len(calls)==2


def test_original_crop_tools_are_retained_without_duplicate_page_fetch(tmp_path,monkeypatch):
    tools,_,_=fixture_tools(tmp_path,monkeypatch)
    assert tools[:2]==['native-assisted','native-exact']
    assert tools[2].__name__=='submit_pair'


def test_preview_pruning_keeps_source_images_other_figures_and_correction_text():
    old=[{'type':'text','text':'qfig1.png: correct top edge'},{'type':'image_url','image_url':'old-preview'}]
    assert prune_old_preview(old,'qfig1.png')==old[:1]
    assert prune_old_preview(old,'qfig2.png')==old
    source=[{'type':'text','text':'QUESTION page 1, source resource'},{'type':'image_url','image_url':'original'}]
    assert prune_old_preview(source,'qfig1.png')==source
    assert len(old)==2  # history input is not mutated
