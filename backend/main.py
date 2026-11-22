"""PaperLab API: FastAPI app wiring the routers to the existing code."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException

import config  # noqa: F401  (pins env first, same as every entry point)
import database
import directory_manager
from app.pairing import reconcile_missing_sources
from app.runs import reset_stuck_running_once
from backend.routers import auth, bundles, export, figures, inbox, jobs, papers, search, stats, tex, topics, uploads
from paperlab_bundle.publication import recover_publications

app = FastAPI(title="PaperLab API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.on_event("startup")
def _startup() -> None:
    database.init_db()
    recover_publications(database.DB_PATH, directory_manager.OUTPUT_BASE)
    reset_stuck_running_once()
    reconcile_missing_sources()


@app.get("/api/health")
def health():
    return {"ok": True}


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(bundles.router, prefix="/api/bundles", tags=["bundles"])
# Figures BEFORE papers: its static GET /trash must win over the papers
# router's file-serving GET figures/{name}.
app.include_router(figures.router, prefix="/api/papers/{paper_id}/questions/{qn}/figures",
                   tags=["figures"])
app.include_router(papers.router, prefix="/api/papers", tags=["papers"])
app.include_router(tex.router, prefix="/api/papers", tags=["tex"])
app.include_router(inbox.router, prefix="/api/inbox", tags=["inbox"])
app.include_router(topics.router, prefix="/api/topics", tags=["topics"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(figures.router, prefix="/api/papers/{paper_id}/questions/{qn}/figures",
                   tags=["figures"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
app.include_router(uploads.router, prefix="/api/uploads", tags=["uploads"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(export.router, prefix="/api/export", tags=["export"])

_FRONTEND_BUILD = Path(__file__).parent.parent / "frontend" / "build"


class _FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            first = path.replace("\\", "/").split("/", 1)[0]
            navigation = "text/html" in Headers(scope=scope).get("accept", "").lower()
            if (exc.status_code != 404 or not navigation or scope["method"] not in ("GET", "HEAD")
                    or first not in {"archive", "builder", "cart", "inbox", "intake", "lab", "ledger",
                                     "mock", "search", "syllabus"}):
                raise
            return await super().get_response("index.html", scope)


if (_FRONTEND_BUILD / "index.html").is_file():
    # Production: serve the Svelte static build; /api routes take precedence.
    app.mount("/", _FrontendFiles(directory=_FRONTEND_BUILD, html=True), name="site")
