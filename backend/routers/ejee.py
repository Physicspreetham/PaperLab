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


class ReviewCropBody(BaseModel):
    left: float
    top: float
    right: float
    bottom: float
    rotate: float = 0
    confirm_edges: bool = False


@router.get('/collections/{paper_id}/questions/{number}/figures')
def collection_figures(paper_id: int, number: str):
    from importer_EJEE import collection_figures as figures
    try:
        return figures.list_figures(paper_id, number)
    except (ValueError, OSError) as exc:
        fail(exc)


@router.get('/collections/{paper_id}/questions/{number}/figures/{name}/source')
def collection_figure_source(paper_id: int, number: str, name: str):
    from importer_EJEE import collection_figures as figures
    try:
        return Response(figures.source_image(paper_id, number, name), media_type='image/png')
    except (ValueError, OSError) as exc:
        fail(exc)


@router.post('/collections/{paper_id}/questions/{number}/figures/{name}/restore')
def collection_figure_restore(paper_id: int, number: str, name: str):
    from importer_EJEE import collection_figures as figures
    try:
        return figures.restore_original(paper_id, number, name)
    except (ValueError, OSError) as exc:
        fail(exc)


@router.post('/collections/{paper_id}/questions/{number}/figures/{name}/{action}')
def collection_figure_edit(paper_id: int, number: str, name: str,
                           action: Literal['preview', 'save'], body: ReviewCropBody):
    from importer_EJEE import collection_figures as figures
    try:
        image, edges = figures.edit_figure(paper_id, number, name, (body.left, body.top, body.right, body.bottom),
                                           body.rotate, action == 'save', body.confirm_edges)
        if action == 'preview':
            return Response(image, media_type='image/png', headers={'X-Crop-Edge-Warnings': ','.join(edges)})
        return Response(status_code=204)
    except (ValueError, OSError) as exc:
        fail(exc)


@router.get('/jobs/{job_id}/crop-review')
def job_crop_review(job_id: str):
    from importer_EJEE.crop_review import review_figures
    try:
        _, figures = review_figures(job_id)
        return [{k:row[k] for k in ('number','name','page','side','box','saved')} for row in figures.values()]
    except (ValueError, OSError) as exc:
        fail(exc)


@router.get('/jobs/{job_id}/crop-review/{number}/{name}/{page}')
def job_crop_source(job_id: str, number: str, name: str, page: int):
    from importer_EJEE.crop_review import review_figures, review_image
    try:
        run, figures = review_figures(job_id)
        row = figures.get((number, name, page))
        if not row:
            raise FileNotFoundError('Crop review figure not found.')
        return Response(review_image(run, row), media_type='image/png')
    except (ValueError, OSError) as exc:
        fail(exc)


@router.post('/jobs/{job_id}/crop-review/{number}/{name}/{page}/{action}')
def job_crop_edit(job_id: str, number: str, name: str, page: int,
                  action: Literal['preview', 'save'], body: ReviewCropBody):
    from importer_EJEE.crop_review import edit_crop
    try:
        image, edges = edit_crop(job_id, number, name, page,
                                (body.left, body.top, body.right, body.bottom),
                                body.rotate, action == 'save', body.confirm_edges)
        if action == 'preview':
            return Response(image, media_type='image/png', headers={'X-Crop-Edge-Warnings': ','.join(edges)})
        return Response(status_code=204)
    except (ValueError, OSError) as exc:
        fail(exc)


class OrderBody(BaseModel):
    ids: list[int] = Field(max_length=2000)


class TitleBody(BaseModel):
    title: str = Field(min_length=1, max_length=180)


class MergeBody(BaseModel):
    ids: list[int] = Field(min_length=2, max_length=50)
    title: str = Field(min_length=1, max_length=180)
    remove_originals: bool = False


class SourceBody(BaseModel):
    source_db: str = Field(min_length=1, max_length=4096)
    asset_root: str = Field(min_length=1, max_length=4096)


class ImportBody(BaseModel):
    book_id: str
    chapters: list[str] = Field(min_length=1, max_length=20)


class SearchBody(BaseModel):
    filters: dict = Field(default_factory=dict)
    node_ids: list[int] = Field(default_factory=list)
    offset: int = Field(default=0,ge=0)
    limit: int = Field(default=30,ge=1,le=100)


class SelectionQuestions(BaseModel):
    resource_ids: list[int] = Field(min_length=1,max_length=selection.MAX_SELECTION)
    source_token: str = Field(pattern=r'^[a-f0-9]{64}$')
    filters: dict = Field(default_factory=dict)
    tagging_mode: Literal['source', 'paperlab'] = 'source'
    content_mode: Literal['key', 'full'] = 'full'


class SelectionBody(SelectionQuestions):
    name: str = Field(min_length=1,max_length=180)


@router.get('/filters')
def filters():
    try:return selection.facets()
    except (ValueError,OSError,service.sqlite3.Error) as exc:fail(exc)


@router.post('/questions/search')
def search_questions(body: SearchBody):
    try:
        filters = {**body.filters, 'node_ids': body.node_ids} if body.node_ids else body.filters
        result = selection.search(filters,body.offset,body.limit)
        imported = library.imported_index()
        for item in result['items']:
            item['imported_in'] = imported.get(item['selection_key'])
        return {**result, 'applied_node_ids': filters.get('node_ids', [])}
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
    return queue_selection(body, name=body.name)


@router.post('/collections/{paper_id}/questions', status_code=202)
def append_selection(paper_id: int, body: SelectionQuestions):
    return queue_selection(body, append_paper_id=paper_id)


def queue_selection(body: SelectionQuestions, name='', append_paper_id=None):
    if not config.LLM_API_KEY or 'paste-your-key' in config.LLM_API_KEY:
        raise HTTPException(400,'Configure the PaperLab Meta API key before importing.')
    try:
        target=library.store()
        return service.start_selection(name,body.resource_ids,body.source_token,body.filters,
            target['db'],target['outputs'],target['data'],environment(),tagging_mode=body.tagging_mode,
            append_paper_id=append_paper_id, content_mode=body.content_mode)
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


@router.post('/jobs/{job_id}/cancel')
def cancel(job_id: str):
    try:
        return service.cancel_job(job_id, library.store()['db'])
    except (ValueError, OSError) as exc:
        fail(exc)


@router.delete('/jobs/{job_id}')
def remove(job_id: str):
    try:
        return service.delete_job(job_id, library.store()['db'])
    except (ValueError, OSError) as exc:
        fail(exc)


@router.get('/jobs/{job_id}/questions')
def job_questions(job_id: str):
    try:
        return service.job_questions(job_id)
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


@library_router.patch('/papers/{paper_id}', dependencies=[Depends(require_admin)])
def rename_paper(paper_id: int, body: TitleBody):
    try:
        return library.rename(paper_id, body.title)
    except (ValueError, OSError) as exc:
        fail(exc)


@library_router.post('/papers/merge', dependencies=[Depends(require_admin)])
def merge_papers(body: MergeBody):
    """Merge collections into one new collection titled `title` (originals kept unless asked)."""
    from importer_EJEE import merge_collections
    try:
        return merge_collections.merge_and_replace(body.ids, body.title.strip(), body.remove_originals)
    except (ValueError, OSError) as exc:
        fail(exc)


@library_router.delete('/papers/{paper_id}', dependencies=[Depends(require_admin)])
def delete_paper(paper_id: int):
    """Delete a whole collection (its folders are kept in the library trash)."""
    from importer_EJEE import merge_collections
    try:
        return merge_collections.delete_collections([paper_id])
    except (ValueError, OSError) as exc:
        fail(exc)


@library_router.put('/papers/order', dependencies=[Depends(require_admin)])
def order_papers(body: OrderBody):
    try:
        return library.set_order(body.ids)
    except (ValueError, OSError) as exc:
        fail(exc)


@library_router.get('/papers/{paper_id}/order')
def paper_order(paper_id: int):
    try:return library.order_keys(paper_id)
    except (ValueError,OSError) as exc:fail(exc)


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


@library_router.delete('/papers/{paper_id}/questions/{qn}', dependencies=[Depends(require_admin)])
def delete_library_question(paper_id: int, qn: str):
    """Remove one question from a collection (its folder is kept in the library trash)."""
    from importer_EJEE import merge_collections
    try:
        return merge_collections.delete_questions(paper_id, [qn])
    except (ValueError, OSError) as exc:
        fail(exc)


@library_router.get('/papers/{paper_id}/questions/{qn}/figures/{name}')
def library_figure(paper_id: int,qn: str,name: str):
    import re
    if qn in ('.','..') or not re.fullmatch(r'[A-Za-z0-9_.-]+',qn) or not re.fullmatch(r'[qs]fig\d+\.png',name):
        raise HTTPException(400,'Invalid figure path')
    root=library.store()['outputs']
    path=(root/str(paper_id)/qn/'figures'/name).resolve()
    if root not in path.parents or not path.is_file():raise HTTPException(404,'Figure not found')
    return FileResponse(path)
