"""Archivist-only EJEE database import UI endpoints."""
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import config
import database
import directory_manager
from backend.deps import require_admin
from importer_EJEE import app_service as service
from importer_EJEE import library_store as library
from importer_EJEE import selection

router = APIRouter(dependencies=[Depends(require_admin)])
library_router = APIRouter()


def environment():
    return {'META_API_KEY': config.LLM_API_KEY or '', 'LLM_MODEL': config.LLM_MODEL,
            'LLM_BASE_URL': config.LLM_BASE_URL,
            'LLM_REASONING_EFFORT': config.LLM_REASONING_EFFORT or '',
            'LLM_USE_RESPONSES_API': str(config.LLM_USE_RESPONSES_API).lower()}


class SourceBody(BaseModel):
    source_db: str = Field(min_length=1, max_length=4096)
    asset_root: str = Field(min_length=1, max_length=4096)


class ImportBody(BaseModel):
    book_id: str
    chapters: list[str] = Field(min_length=1, max_length=20)


class SearchBody(BaseModel):
    filters: dict = Field(default_factory=dict)
    offset: int = Field(default=0,ge=0)
    limit: int = Field(default=30,ge=1,le=100)


class SelectionBody(BaseModel):
    name: str = Field(min_length=1,max_length=180)
    resource_ids: list[int] = Field(min_length=1,max_length=selection.MAX_SELECTION)
    source_token: str = Field(pattern=r'^[a-f0-9]{64}$')
    filters: dict = Field(default_factory=dict)


@router.get('/filters')
def filters():
    try:return selection.facets()
    except (ValueError,OSError,service.sqlite3.Error) as exc:fail(exc)


@router.post('/questions/search')
def search_questions(body: SearchBody):
    try:return selection.search(body.filters,body.offset,body.limit)
    except (ValueError,OSError,service.sqlite3.Error) as exc:fail(exc)


@router.get('/questions/{resource_id}/preview')
def question_preview(resource_id: int,size: Literal['thumbnail','full']='full',source_token: str|None=None):
    try:return Response(selection.preview(resource_id,size,source_token),media_type='image/png')
    except (ValueError,OSError,service.sqlite3.Error) as exc:fail(exc)


@router.get('/questions/{resource_id}')
def question_details(resource_id: int,source_token: str|None=None):
    try:return selection.details(resource_id,source_token)
    except (ValueError,OSError,service.sqlite3.Error) as exc:fail(exc)


@router.post('/selections',status_code=202)
def import_selection(body: SelectionBody):
    if not config.LLM_API_KEY or 'paste-your-key' in config.LLM_API_KEY:
        raise HTTPException(400,'Configure the PaperLab Meta API key before importing.')
    try:
        target=library.store()
        return service.start_selection(body.name,body.resource_ids,body.source_token,body.filters,
            target['db'],target['outputs'],target['data'],environment())
    except (ValueError,OSError,service.sqlite3.Error) as exc:fail(exc)


def fail(exc):
    raise HTTPException(404 if isinstance(exc, FileNotFoundError) else 400, str(exc)) from exc


@router.get('/catalogue')
def catalogue():
    try:
        result = service.catalogue(library.store()['db'])
        result['ai_ready'] = bool(config.LLM_API_KEY and 'paste-your-key' not in config.LLM_API_KEY)
        return result
    except (ValueError, OSError, service.sqlite3.Error) as exc:
        fail(exc)


@router.put('/source')
def set_source(body: SourceBody):
    try:
        service.configure(body.source_db, body.asset_root)
        return catalogue()
    except (ValueError, OSError, service.sqlite3.Error) as exc:
        fail(exc)


@router.get('/jobs')
def jobs():
    return [j for j in service.list_jobs() if j['target_db'] == str(library.store()['db'])]


@router.post('/jobs', status_code=202)
def start(body: ImportBody):
    if not config.LLM_API_KEY or 'paste-your-key' in config.LLM_API_KEY:
        raise HTTPException(400, 'Configure the existing PaperLab Meta API key before starting an import.')
    try:
        target=library.store()
        return {'jobs': service.start_jobs(body.book_id, body.chapters, target['db'],
                target['outputs'], target['data'], environment())}
    except (ValueError, OSError, service.sqlite3.Error) as exc:
        fail(exc)


@router.post('/jobs/{job_id}/resume', status_code=202)
def resume(job_id: str):
    if not config.LLM_API_KEY:
        raise HTTPException(400, 'Configure the PaperLab Meta API key before resuming.')
    try:
        return service.resume_job(job_id, library.store()['db'], environment())
    except (ValueError, OSError) as exc:
        fail(exc)


@router.get('/usage')
def usage():
    result=library.usage()
    # Failed/in-progress conversions have real usage too, kept in their
    # resumable worker DB until publishing. Do not count completed jobs twice.
    pending=sum(j.get('estimated_cost_usd',0) for j in jobs() if j['status']!='done')
    result.update(unpublished_usd=pending,total_usd=result['total_usd']+pending)
    return result


@router.get('/usage/selection')
def selection_usage():
    from importer_EJEE.usage_ledger import selection_usage
    return selection_usage()


@library_router.get('/papers')
def library_papers():
    return library.papers()


@library_router.get('/papers/{paper_id}/questions')
def library_questions(paper_id: int):
    try:return library.questions(paper_id)
    except (ValueError,OSError) as exc:fail(exc)


@library_router.get('/papers/{paper_id}')
def library_paper(paper_id: int):
    try:return library.metadata(paper_id)
    except (ValueError,OSError) as exc:fail(exc)


@library_router.get('/papers/{paper_id}/questions/{qn}')
def library_question(paper_id: int,qn: str):
    try:
        items=library.questions(paper_id,qn)['questions']
        if not items:raise FileNotFoundError('Imported EJEE question not found')
        return items[0]
    except (ValueError,OSError) as exc:fail(exc)


@library_router.get('/papers/{paper_id}/questions/{qn}/figures/{name}')
def library_figure(paper_id: int,qn: str,name: str):
    import re
    if qn in ('.','..') or not re.fullmatch(r'[A-Za-z0-9_.-]+',qn) or not re.fullmatch(r'[qs]fig\d+\.png',name):
        raise HTTPException(400,'Invalid figure path')
    root=library.store()['outputs']
    path=(root/str(paper_id)/qn/'figures'/name).resolve()
    if root not in path.parents or not path.is_file():raise HTTPException(404,'Figure not found')
    return FileResponse(path)
