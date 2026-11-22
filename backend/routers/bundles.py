"""Archivist-only import of a checked, portable PaperLab bundle."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore
from urllib.parse import urlsplit
import zipfile
import zlib

from anyio import open_file
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from app.auth import uses_default_password
from backend.deps import require_admin
from backend.routers.search import bump_search_version
import database
import directory_manager
from paperlab_bundle.bundle import BundleConflict, BundleError, BundleLimitError, UploadLimits, merge_bundle

router = APIRouter()
_log = logging.getLogger(__name__)
_slot = BoundedSemaphore(1)
MAX_BODY = 64 * 1024 * 1024
UPLOAD_SECONDS = 120
BUNDLE_LIMITS = UploadLimits()
_MIME = "application/octet-stream"
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
_NO_STORE = {"Cache-Control": "no-store"}


def _origin(url):
    parts = urlsplit(url)
    return parts.scheme, parts.hostname, parts.port or {"https": 443, "http": 80}.get(parts.scheme)


def _check_transport(request):
    # Uvicorn trusts forwarded scheme only from a configured proxy peer.
    if request.url.scheme != "https" and not (
        request.url.hostname in _LOOPBACK and request.client and request.client.host in _LOOPBACK
    ):
        raise HTTPException(403, "Bundle import requires HTTPS (except on loopback).")
    origin = request.headers.get("origin")
    if origin is not None:
        try:
            same_origin = _origin(origin) == _origin(str(request.url))
        except ValueError:
            same_origin = False
        if not same_origin:
            raise HTTPException(403, "Cross-origin bundle uploads are not allowed.")


def _check_headers(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != _MIME:
        raise HTTPException(415, "Send the raw .plbundle bytes as application/octet-stream.")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise HTTPException(415, "Do not apply HTTP content encoding to the bundle.")
    length = request.headers.get("content-length")
    if length is not None:
        if not re.fullmatch(r"[0-9]{1,20}", length) or int(length) == 0:
            raise HTTPException(400, "Expected a nonempty bundle.")
        if int(length) > MAX_BODY:
            raise HTTPException(413, "Bundle upload exceeds 64 MiB; split the bundle.")
        return int(length)
    return None


async def _stage(request, path, length):
    size = 0
    async with await open_file(path, "xb") as file:
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY:
                raise HTTPException(413, "Bundle upload exceeds 64 MiB; split the bundle.")
            if chunk:
                await file.write(chunk)
    if not size or (length is not None and length != size):
        raise HTTPException(400, "The bundle upload was empty or incomplete.")


def _merge(path, target, dry_run, allow_untagged):
    return merge_bundle(path, target, directory_manager.OUTPUT_BASE, dry_run=dry_run,
                        allow_untagged=allow_untagged, reviews="block", upload_limits=BUNDLE_LIMITS,
                        idempotent=True)


@router.post(
    "/import",
    dependencies=[Depends(require_admin)],
    openapi_extra={"requestBody": {
        "required": True, "content": {_MIME: {"schema": {"type": "string", "format": "binary"}}},
    }},
    responses={200: {"description": "Preview or the receipt of an already-imported bundle"},
               201: {"description": "Papers published to the archive"}},
)
async def import_bundle(request: Request, dry_run: bool = True, allow_untagged: bool = False):
    """Preview a bundle by default. Send `dry_run=false` to publish."""
    _check_transport(request)
    if uses_default_password():
        raise HTTPException(503, "Configure a non-default archivist password before using bundle imports.")
    length = _check_headers(request)
    target = Path(database.DB_PATH)
    if not target.is_file():
        raise HTTPException(503, "The PaperLab archive is not initialized.")
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, "Another bundle import is in progress.", headers={"Retry-After": "5"})
    try:
        with TemporaryDirectory(prefix="paperlab-upload-", ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "upload.plbundle"
            await asyncio.wait_for(_stage(request, path, length), timeout=UPLOAD_SECONDS)
            receipt = await run_in_threadpool(_merge, path, target, dry_run, allow_untagged)
    except asyncio.TimeoutError:
        raise HTTPException(408, "The bundle took too long to upload.") from None
    except ClientDisconnect:
        raise HTTPException(400, "The bundle upload was interrupted.") from None
    except BundleLimitError as exc:
        raise HTTPException(413, str(exc)) from None
    except BundleConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except BundleError as exc:
        raise HTTPException(422, str(exc)) from None
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, OverflowError,
            zipfile.BadZipFile, zlib.error, RecursionError, NotImplementedError):
        raise HTTPException(422, "Invalid PaperLab bundle metadata or contents.") from None
    except sqlite3.Error as exc:
        code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
        if code in (sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_BUSY):
            raise HTTPException(503, "The archive is busy. Retry in a moment.", headers={"Retry-After": "5"}) from None
        if isinstance(exc, sqlite3.IntegrityError) or code in (
            sqlite3.SQLITE_ERROR, sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_MISMATCH,
        ):
            raise HTTPException(422, "Invalid or incompatible PaperLab bundle database.") from None
        _log.exception("PaperLab bundle database operation failed")
        raise HTTPException(500, "Bundle import failed; check the server log.") from None
    except OSError:
        _log.exception("PaperLab bundle storage operation failed")
        raise HTTPException(500, "Bundle import failed; check the server log.") from None
    finally:
        _slot.release()

    # Return a small public-facing receipt, not filesystem paths or the provenance log.
    papers = [{k: p[k] for k in ("name", "questions", "archive_paper") if k in p}
              for p in receipt["papers"]]
    if dry_run:
        return JSONResponse({"dry_run": True, "mergeable": True, "papers": papers}, headers=_NO_STORE)
    replay = receipt.get("already_imported", False)
    if not replay:
        bump_search_version()
    backup = Path(receipt["backup"]).name
    return JSONResponse({"dry_run": False, "merged_at": receipt["merged"], "papers": papers,
                         "already_imported": replay, "backup": backup, "warnings": receipt["warnings"]},
                        status_code=200 if replay else 201, headers=_NO_STORE)
