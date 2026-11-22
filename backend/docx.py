"""Build inert Pandoc input from a bounded sheet snapshot.

The converter sees only markup generated here and embedded archive raster
figures. Client URLs, markup directives, styles, and filesystem paths never
reach Pandoc. Pass --sandbox as an independent file-access boundary.
"""
from __future__ import annotations

import base64
from functools import lru_cache
import html
from importlib.util import find_spec
import io
import os
from pathlib import Path
import re
import subprocess
import tempfile
from time import monotonic
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from PIL import Image

import database
import directory_manager
from backend.docx_reference import patch_reference

_LUA = Path(__file__).with_name("pandoc_docx.lua").resolve()
_PANDOC_VERSION = b"3.9"  # Also bundled by requirements-word.txt.
_STARTUP_TIMEOUT = 30      # Allow a cold executable launch on macOS.
_CONVERSION_TIMEOUT = 30   # Per-document work after startup.
_NS = "{http://www.w3.org/1999/xhtml}"
_TAGS = set("""
    div header section p span h1 h2 h3 h4 h5 h6 em strong b i u s del sup sub
    blockquote pre code br hr ol ul li dl dt dd figure figcaption img
    table caption colgroup col thead tbody tfoot tr td th
""".split())
_VOID = {"img", "col", "br", "hr"}
_STYLES = {"DocSub", "SecKind", "ParaHead", "TopicHead"}
_FIGURE = re.compile(r"/api/papers/([1-9][0-9]{0,14})/questions/([^/]{1,180})/figures/([^/]{1,180})")
_IMAGE_EXT = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}
_MAX_IMAGES = 160
_MAX_MEDIA = 12 * 1024 * 1024
_MAX_IMAGE = 3 * 1024 * 1024
_MAX_DOCX = 20 * 1024 * 1024
_MAX_PIXELS = 8_000_000


class InvalidSheet(ValueError):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _integer(raw: str | None, low: int, high: int) -> str:
    if raw is None or not re.fullmatch(r"[0-9]{1,4}", raw) or not low <= int(raw) <= high:
        raise InvalidSheet("The sheet contains an unsupported size or number.")
    return str(int(raw))


class _Sheet:
    def __init__(self, conn):
        self.conn = conn
        self.images: dict[tuple[int, str, str], tuple[str, int]] = {}
        self.media_bytes = 0
        self.image_uses = 0
        self.nodes = 0

    def figure(self, ref: str) -> str:
        match = _FIGURE.fullmatch(ref)
        if match is None:
            raise InvalidSheet("Only figures from the PaperLab archive can be exported.")
        pid, qn, name = match.groups()
        key = (int(pid), unquote(qn), unquote(name))
        pid, qn, name = key
        self.image_uses += 1
        if self.image_uses > _MAX_IMAGES:
            raise InvalidSheet("There are too many figures for one Word export. Split the draft or use Print / PDF.", 413)
        if key in self.images:
            url, size = self.images[key]
            self._count_media(size)
            return url
        image_format = _IMAGE_EXT.get(Path(name).suffix.lower())
        if image_format is None or name.startswith(("._", "_trash_")):
            raise InvalidSheet("Word export supports PNG and JPEG archive figures.")
        if not self.conn.execute(
            "SELECT 1 FROM questions q JOIN papers p ON p.id=q.paper_id "
            "WHERE q.paper_id=? AND q.question_number=? AND p.status='done'",
            (pid, qn),
        ).fetchone():
            raise InvalidSheet("A source question is no longer available in the archive.", 409)
        try:
            root = directory_manager.OUTPUT_BASE.resolve()
            folder = directory_manager.get_question_dir(pid, qn) / "figures"
            folder = folder.resolve()
            folder.relative_to(root)
            checked_name = directory_manager.safe_component(name, "figure name")
            path = (folder / checked_name).resolve()
            if path.parent != folder or not path.is_file():
                raise OSError("Not an archive figure")
            with path.open("rb") as src:
                data = src.read(_MAX_IMAGE + 1)
        except (OSError, ValueError, RuntimeError):
            raise InvalidSheet("An archive figure is missing. Reload the preview or use Print / PDF.", 409) from None
        if len(data) > _MAX_IMAGE:
            raise InvalidSheet("The figures are too large for one Word export. Split the draft or use Print / PDF.", 413)
        self._count_media(len(data))
        try:
            with Image.open(io.BytesIO(data), formats=[image_format]) as img:
                if img.width * img.height > _MAX_PIXELS:
                    raise InvalidSheet("An archive figure exceeds the Word export size limit.", 413)
                img.verify()
        except (OSError, SyntaxError, Image.DecompressionBombError):
            raise InvalidSheet("An archive figure could not be read. Reload the preview or use Print / PDF.", 409) from None
        mime = "image/png" if image_format == "PNG" else "image/jpeg"
        url = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
        self.images[key] = (url, len(data))
        return url

    def _count_media(self, size: int) -> None:
        self.media_bytes += size
        if self.media_bytes > _MAX_MEDIA:
            raise InvalidSheet("The figures are too large for one Word export. Split the draft or use Print / PDF.", 413)

    def render(self, node: ET.Element, depth: int = 0) -> str:
        self.nodes += 1
        if depth > 40 or self.nodes > 20_000:
            raise InvalidSheet("This sheet is too complex for one Word export. Split the draft or use Print / PDF.", 413)
        tag = node.tag.removeprefix(_NS)
        if tag not in _TAGS:
            raise InvalidSheet("The sheet contains an unsupported element.")

        # Emit only attributes with explicit semantics below. Never copy an
        # attribute name, URL, or stylistic CSS from the request.
        attrs = {}
        if tag == "img":
            attrs["src"] = self.figure(node.get("data-figure", ""))
            attrs["width"] = _integer(node.get("width"), 1, 600)
            attrs["alt"] = "Archive figure"
        if tag == "ol" and "start" in node.attrib:
            attrs["start"] = _integer(node.get("start"), 1, 9999)
        if tag == "ol" and node.get("type") in {"1", "a", "A", "i", "I"}:
            attrs["type"] = node.get("type")
        if tag in {"td", "th"}:
            for key in ("colspan", "rowspan"):
                if key in node.attrib:
                    attrs[key] = _integer(node.get(key), 1, 40)
        if tag == "col" and "data-width" in node.attrib:
            attrs["style"] = f"width:{_integer(node.get('data-width'), 1, 100)}%"
        if tag == "div" and node.get("custom-style") in _STYLES:
            attrs["custom-style"] = node.get("custom-style")
        if tag == "table" and node.get("class") == "pl-key-table":
            attrs.update({"class": "pl-key-table", "style": "width:100%"})
        if tag == "h3" and node.get("data-solutions") == "1":
            attrs["class"] = "pl-solutions"
        if tag == "span" and node.get("class") in {"math inline", "math display"}:
            if len(node) or len(node.text or "") > 4000 or not (node.text or "").strip():
                raise InvalidSheet("A math expression is empty or too large for Word export.")
            attrs["class"] = node.get("class")
        start = "<" + tag + "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in attrs.items()) + ">"
        if tag in _VOID:
            return start
        parts = [start, html.escape(node.text or "")]
        for child in node:
            parts += [self.render(child, depth + 1), html.escape(child.tail or "")]
        return "".join(parts) + f"</{tag}>"


def build_pandoc_input(sheet: str) -> bytes:
    # Browser serialization needs no comments, DTD or processing instructions.
    if "<!" in sheet or "<?" in sheet:
        raise InvalidSheet("The Word sheet contains unsupported markup.")
    try:
        root = ET.fromstring(sheet)
    except (ET.ParseError, UnicodeError, ValueError):
        raise InvalidSheet("The Word sheet format is invalid.") from None
    if root.tag != _NS + "div" or not len(root):
        raise InvalidSheet("The Word sheet is empty or invalid.")
    conn = database.get_connection()
    try:
        inner = _Sheet(conn).render(root)
    finally:
        conn.close()
    return ('<!doctype html><html><head><meta charset="utf-8"></head><body>'
            + inner + "</body></html>").encode()


class PandocUnavailable(RuntimeError):
    """The configured or bundled converter cannot be used on this server."""


class PandocTimedOut(RuntimeError):
    """A named converter stage exceeded its time budget."""


def _pandoc() -> tuple[Path, bool]:
    """Prefer an explicit operator override, otherwise the pinned wheel."""
    override = os.environ.get("PAPERLAB_PANDOC")
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute() or not path.is_file() or (os.name == "nt" and path.suffix.lower() != ".exe"):
            raise PandocUnavailable("PAPERLAB_PANDOC must name an absolute path to a Pandoc executable")
        return path.resolve(), True
    package = find_spec("pypandoc")
    exe = "pandoc.exe" if os.name == "nt" else "pandoc"
    if package and package.origin:
        bundled = Path(package.origin).resolve().parent / "files" / exe
        if bundled.is_file():
            return bundled, False
    raise PandocUnavailable("Install the Word requirements or configure PAPERLAB_PANDOC (see README.md)")


def _run_pandoc(args: list[str], *, stage: str, timeout: float, **options):
    try:
        if timeout <= 0:
            raise subprocess.TimeoutExpired(args, timeout)
        return subprocess.run(args, timeout=timeout, **options)
    except subprocess.TimeoutExpired as exc:
        raise PandocTimedOut(f"{stage} timed out") from exc


def _verify_pandoc(exe: Path, folder: str, env: dict[str, str], *, timeout: float) -> None:
    # External versions may change the reference template, flags and Lua API.
    try:
        version = _run_pandoc(
            [str(exe), "--version"], cwd=folder, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, stage="version check", timeout=timeout, check=True,
        ).stdout.splitlines()[:1]
    except subprocess.CalledProcessError as exc:
        raise PandocUnavailable(f"PAPERLAB_PANDOC exited with status {exc.returncode} on --version") from exc
    except OSError as exc:
        raise PandocUnavailable(f"Could not run the executable in PAPERLAB_PANDOC: {exc.strerror}") from exc
    if not version or version[0].split()[:2] != [b"pandoc", _PANDOC_VERSION]:
        raise PandocUnavailable(f"PAPERLAB_PANDOC must point to Pandoc {_PANDOC_VERSION.decode()}")


def _pandoc_env(folder: str) -> dict[str, str]:
    env = {"HOME": folder, "TMPDIR": folder, "TEMP": folder, "TMP": folder}
    if os.name == "nt":
        # Keep the converter out of the service account's profile while
        # retaining the system directory needed by Windows processes.
        system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
        if not system_root:
            raise PandocUnavailable("The Windows service environment must define SystemRoot")
        env.update(SystemRoot=system_root, APPDATA=folder, LOCALAPPDATA=folder, USERPROFILE=folder)
    return env


def _pandoc_args(exe: Path, folder: str) -> list[str]:
    # The converter gets no archive paths or API credentials. The workspace,
    # runtime heap and execution time are independently bounded.
    return [str(exe), "+RTS", "-M256m", "-RTS", "--sandbox", "--data-dir", folder]


@lru_cache(maxsize=2)
def _reference_docx(exe: Path, verify_version: bool) -> bytes:
    # Bootstrap once per converter. Cache only a successful, immutable
    # template; each export still gets its own private working directory.
    with tempfile.TemporaryDirectory(prefix="paperlab_pandoc_") as folder:
        env = _pandoc_env(folder)
        deadline = monotonic() + _STARTUP_TIMEOUT
        if verify_version:
            _verify_pandoc(exe, folder, env, timeout=deadline - monotonic())
        defaults = _run_pandoc(
            [*_pandoc_args(exe, folder), "--print-default-data-file=reference.docx"], cwd=folder, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True,
            stage="reference template", timeout=deadline - monotonic(),
        ).stdout
    return patch_reference(defaults)


def render_docx(sheet: str) -> bytes:
    source = build_pandoc_input(sheet)
    exe, verify_version = _pandoc()
    template = _reference_docx(exe, verify_version)
    with tempfile.TemporaryDirectory(prefix="paperlab_word_") as folder:
        workspace = Path(folder)
        reference = workspace / "reference.docx"
        out = workspace / "paper.docx"
        reference.write_bytes(template)
        with (workspace / "conversion.log").open("wb") as warnings:
            _run_pandoc(
                [*_pandoc_args(exe, folder), "-f", "html-raw_html", "-t", "docx", "--reference-doc", str(reference),
                 "--lua-filter", str(_LUA), "-o", str(out)],
                cwd=folder, env=_pandoc_env(folder), input=source, stdout=subprocess.DEVNULL, stderr=warnings,
                check=True, stage="DOCX conversion", timeout=_CONVERSION_TIMEOUT,
            )
        with (workspace / "conversion.log").open("rb") as warnings:
            # Pandoc otherwise silently flattens unsupported math or drops figures.
            if warnings.read(1):
                raise InvalidSheet("Word could not convert part of the sheet without losing content. Use Print / PDF.", 422)
        with out.open("rb") as doc:
            data = doc.read(_MAX_DOCX + 1)
        if not data or len(data) > _MAX_DOCX:
            raise InvalidSheet("The Word file is too large. Split the draft or use Print / PDF.", 413)
        return data
