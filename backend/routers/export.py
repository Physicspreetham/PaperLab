"""Paper Builder export: HTML sheet -> Word (.docx) via pandoc, or PDF via a
headless Chrome/Edge (so "Save PDF" never depends on the browser print dialog).

The browser sends the already-paginated preview as HTML with math as
`<span class="math inline|display">tex</span>` (a Lua filter makes it real math) and figures inlined as
data: URIs. Pandoc turns that into a .docx with native (editable) Word
equations. Pandoc is a system binary, probed at runtime like tectonic.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import sys
import subprocess
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.docx_reference import reference_path

router = APIRouter()

LUA_FILTER = Path(__file__).resolve().parent.parent / "pandoc_docx.lua"

MAX_HTML_CHARS = 120_000_000  # figures are inlined as base64
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class DocxRequest(BaseModel):
    html: str = Field(..., max_length=MAX_HTML_CHARS)
    title: str = Field("paper", max_length=200)


def _pandoc() -> str:
    exe = shutil.which("pandoc")
    if not exe:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "pandoc is not installed on the server (https://pandoc.org/installing.html), "
            "then restart the API.",
        )
    return exe


def _safe_name(title: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("._") or "paper"
    return name[:80]


# Equations: same typeface as the paper text, upright (not italic) -- the
# source paper's math is set as plain text.
_MATH_RUN = re.compile(r"<m:r>(<m:rPr>(?:(?!</m:rPr>).)*</m:rPr>|<m:rPr\s*/>)?(?!<w:rPr>)", re.S)
_MATH_FONT = (
    '<w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" '
    'w:cs="Times New Roman" w:eastAsia="Times New Roman"/></w:rPr>'
)


def _upright(rpr: str | None) -> str:
    """m:rPr for a math run, forced to plain (upright, non-italic) style.

    Runs that already carry a style (bold, upright words, script letters)
    are left exactly as they are.
    """
    if not rpr or rpr.replace(" ", "") == "<m:rPr/>":
        return '<m:rPr><m:sty m:val="p"/></m:rPr>'
    if any(t in rpr for t in ("<m:sty", "<m:scr", "<m:nor", "<m:lit")):
        return rpr
    return rpr.replace("<m:rPr>", '<m:rPr><m:sty m:val="p"/>', 1)


# Word draws fractions inside running text noticeably smaller than the text
# around them (numerator/denominator are scaled down). Bump the runs inside
# fractions so option lines like A) v0 mu0 i0 / 16 R lambda pi^2 stay readable.
_FRAC_SZ = 30  # half-points (15pt) for the 13pt body text
_FRAC_TAG = re.compile(r"(</?m:(?:num|den)>)")


def _grow_fractions(xml: str) -> str:
    out, depth = [], 0
    for part in _FRAC_TAG.split(xml):
        if part in ("<m:num>", "<m:den>"):
            depth += 1
        elif part in ("</m:num>", "</m:den>"):
            depth = max(0, depth - 1)
        elif depth:
            part = part.replace(
                'w:eastAsia="Times New Roman"/></w:rPr>',
                f'w:eastAsia="Times New Roman"/><w:sz w:val="{_FRAC_SZ}"/><w:szCs w:val="{_FRAC_SZ}"/></w:rPr>',
            )
        out.append(part)
    return "".join(out)


def _style_math(docx: bytes) -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(docx))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml = data.decode("utf-8")
                xml = _MATH_RUN.sub(lambda m: "<m:r>" + _upright(m.group(1)) + _MATH_FONT, xml)
                xml = _grow_fractions(xml)
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    return buf.getvalue()


def html_to_docx(html: str) -> bytes:
    """Convert builder HTML to .docx bytes (raises HTTPException on failure)."""
    exe = _pandoc()
    with tempfile.TemporaryDirectory(prefix="paperlab_docx_") as tmp:
        out = Path(tmp) / "paper.docx"
        try:
            proc = subprocess.run(
                [exe, "-f", "html", "-t", "docx",
                 "--reference-doc", reference_path(exe),
                 "--lua-filter", str(LUA_FILTER),
                 "-o", str(out)],
                input=html.encode("utf-8"),
                capture_output=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "pandoc timed out")
        if proc.returncode != 0 or not out.is_file():
            msg = proc.stderr.decode("utf-8", "replace").strip()[:500]
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"pandoc failed: {msg}")
        return _style_math(out.read_bytes())


@router.post("/docx")
def export_docx(body: DocxRequest) -> Response:
    data = html_to_docx(body.html)
    fname = _safe_name(body.title) + ".docx"
    return Response(
        content=data,
        media_type=DOCX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ---- PDF (headless Chrome / Edge) ------------------------------------------

DOCX_PDF_MIME = "application/pdf"
MAX_PDF_HTML_CHARS = 150_000_000

# Anything that could make the headless browser read a local file or reach
# the network is refused: the page must be fully self-contained (data: URIs).
_EXTERNAL_REF = re.compile(
    r"""(?:\b(?:src|href|poster|srcset|xlink:href)\s*=\s*["'](?!data:|#|["'])"""
    r"""|url\(\s*["']?(?!data:|#|["')]))""",
    re.I,
)
_FILE_URL = re.compile(r"file:/", re.I)


class PdfRequest(BaseModel):
    html: str = Field(..., max_length=MAX_PDF_HTML_CHARS)
    title: str = Field("paper", max_length=200)


def _find_browser() -> str:
    env = os.environ.get("PAPERLAB_BROWSER")
    cands: list[str] = [env] if env else []
    if sys.platform.startswith("win"):
        roots = [os.environ.get(k, "") for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        for r in filter(None, roots):
            cands += [
                os.path.join(r, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(r, "Microsoft", "Edge", "Application", "msedge.exe"),
            ]
    elif sys.platform == "darwin":
        cands += [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            cands.append(found)
    for c in cands:
        if c and Path(c).is_file():
            return c
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Chrome or Edge was not found on the server. Install one, or set PAPERLAB_BROWSER "
        "to its path, then restart the API.",
    )


def html_to_pdf(html: str) -> bytes:
    if _EXTERNAL_REF.search(html) or _FILE_URL.search(html):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "page references external resources")
    exe = _find_browser()
    with tempfile.TemporaryDirectory(prefix="paperlab_pdf_") as tmp:
        tmpd = Path(tmp)
        src = tmpd / "sheet.html"
        out = tmpd / "sheet.pdf"
        src.write_text(html, encoding="utf-8")
        cmd = [
            exe,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={tmpd / 'profile'}",  # never attach to the user's running browser
            "--host-resolver-rules=MAP * ~NOTFOUND",  # no network at all
            "--no-pdf-header-footer",
            "--print-to-pdf-no-header",
            "--virtual-time-budget=20000",
            f"--print-to-pdf={out}",
            src.as_uri(),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "PDF rendering timed out")
        if not out.is_file() or out.stat().st_size == 0:
            msg = proc.stderr.decode("utf-8", "replace").strip()[-300:]
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"PDF rendering failed: {msg}")
        return out.read_bytes()


@router.post("/pdf")
def export_pdf(body: PdfRequest) -> Response:
    data = html_to_pdf(body.html)
    fname = _safe_name(body.title) + ".pdf"
    return Response(
        content=data,
        media_type=DOCX_PDF_MIME,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
