"""Bounded Word export for the public Paper Builder."""
from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from threading import BoundedSemaphore

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.docx import InvalidSheet, PandocUnavailable, render_docx

router = APIRouter()
_log = logging.getLogger(__name__)
_slot = BoundedSemaphore(1)
MAX_BODY = 2 * 1024 * 1024
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class DocxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(max_length=160)
    sheet: str = Field(min_length=1, max_length=MAX_BODY)


async def _request_body(request: Request) -> bytearray:
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_BODY:
            raise HTTPException(413, "This sheet is too large for one Word export. Split the draft or use Print / PDF.")
        data.extend(chunk)
    return data


@router.post("/docx")
async def export_docx(request: Request) -> Response:
    # Limit before body parsing or queuing work. One conversion per API process;
    # print remains entirely in the browser and never waits for this slot.
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, "Word export is busy. Try again in a moment.", headers={"Retry-After": "5"})
    try:
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(415, "Word export expects a JSON sheet.")
        try:
            raw = await asyncio.wait_for(_request_body(request), timeout=10)
            draft = DocxRequest.model_validate_json(raw)
            del raw
        except asyncio.TimeoutError:
            raise HTTPException(408, "The sheet took too long to upload. Try again.") from None
        except ValidationError:
            raise HTTPException(422, "The Word sheet format is invalid.") from None

        try:
            data = await run_in_threadpool(render_docx, draft.sheet)
        except InvalidSheet as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except PandocUnavailable as exc:
            _log.warning("Word export unavailable: %s", exc)
            raise HTTPException(503, "Word export is unavailable. You can still use Print / PDF.") from None
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Word export took too long. Split the draft or use Print / PDF.") from None
        except (subprocess.CalledProcessError, OSError):
            _log.exception("Word conversion failed")
            raise HTTPException(500, "Could not create the Word document. Try again or use Print / PDF.") from None

        filename = re.sub(r"[^A-Za-z0-9._-]+", "_", draft.title).strip("._")[:120].rstrip(".") or "paper"
        return Response(data, media_type=DOCX_MIME, headers={
            "Content-Disposition": f'attachment; filename="{filename}.docx"',
            "Cache-Control": "no-store",
        })
    finally:
        _slot.release()
