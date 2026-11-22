"""PaperLab bundle: one portable temp-DB format + one merger for every importer.

A bundle is a single ``.plbundle`` file (a zip) that any importer produces and
any PaperLab install can merge, on Windows, macOS or Linux::

    bundle.json        format/version, producer, papers, SHA-256 of every file
    paperlab.db        SQLite in PaperLab's own schema, only the bundled papers;
                       latex_folder / PDF paths are RELATIVE ("Outputs/1/3")
    Outputs/<paper>/<question>/question.tex, solution.tex, figures/*.png
    sources/<paper>/*  optional original files (PDF/images)

Portability rules (enforced on write AND read): only relative POSIX paths
with forward slashes, no drive letters, no "..", no backslashes, UTF-8 text.
Reading uses the Python standard library. Creating a new archive uses
PaperLab's database initializer; existing archives are not migrated here.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import logging
import math
import os
import re
import shutil
import sqlite3
import struct
import sys
import tempfile
import time
import unicodedata
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from .publication import Publication, record_receipt, recover_locked, saved_receipt

FORMAT = "paperlab-bundle"
VERSION = 1
TABLES = ("papers", "questions", "question_topics", "token_usage")
SUFFIX = ".plbundle"
_WINDOWS_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", re.I)
_log = logging.getLogger(__name__)


class BundleError(ValueError):
    """A bundle (or merge target) failed validation; nothing was changed."""


class BundleLimitError(BundleError):
    """A transport resource limit was exceeded."""


class BundleConflict(BundleError):
    """The target already has this paper or its destination is occupied."""


@dataclass(frozen=True)
class UploadLimits:
    """Limits for accepting a bundle over HTTP, not for local CLI imports."""

    expanded_bytes: int = 256 * 1024 * 1024
    members: int = 4096
    manifest_bytes: int = 2 * 1024 * 1024
    db_bytes: int = 32 * 1024 * 1024
    tex_bytes: int = 512 * 1024


def _sha(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def prior_chain(out_path: Path) -> list:
    """Previous producer_chain when re-exporting over an existing bundle."""
    try:
        with zipfile.ZipFile(out_path) as z:
            old = json.loads(z.read("bundle.json").decode("utf-8"))
    except Exception:
        return []
    if old.get("format") != FORMAT or int(old.get("version", 0)) != VERSION:
        raise BundleError(f"{out_path} holds a different bundle (format {old.get('format')} v{old.get('version')}); "
                          "export to a new file instead of overwriting")
    chain = old.get("producer_chain") or ([old["producer"]] if old.get("producer") else [])
    return [c for c in chain if isinstance(c, dict)]


def safe_relpath(name: str) -> str:
    """Return ``name`` if it is a safe, portable relative path, else raise."""
    if not isinstance(name, str) or not name:
        raise BundleError(f"unsafe path in bundle: {name!r}")
    for part in name.split("/"):
        _component(part)
    return name


def _component(value) -> str:
    text = str(value)
    if (not text or text.endswith((" ", ".")) or any(ord(c) < 32 or c in '/\\:*?"<>|' for c in text)
            or _WINDOWS_RESERVED.fullmatch(text.split(".", 1)[0])):
        raise BundleError(f"unsafe name {text!r} (paper key / question number / file name)")
    return text


# --------------------------------------------------------------------- write
def build_bundle(src_db, out_path, paper_ids=None, producer=None, extra=None,
                 sources=None) -> dict:
    """Package papers from any PaperLab-schema database into one bundle.

    * ``src_db``: a workspace/run database (never needs to be the archive).
      Question folders are read from ``questions.latex_folder`` (absolute or
      relative to the database's folder).
    * ``paper_ids``: which papers (default: all).
    * ``producer``: {"tool": ..., "version": ..., ...} provenance.
    * ``extra``: per-paper metadata {paper_id: {...}} stored in bundle.json
      (review holds, approvals, source provenance).
    * ``sources``: {paper_id: [file paths]} original files to include.
    Returns the bundle manifest.
    """
    if not isinstance(src_db, (str, os.PathLike)) or not isinstance(out_path, (str, os.PathLike)):
        raise BundleError(f"build_bundle needs path-like src_db/out_path, got {type(src_db).__name__}/{type(out_path).__name__}")
    src_db = Path(src_db).resolve()
    out_path = Path(out_path)
    if out_path.suffix != SUFFIX:
        out_path = out_path.with_suffix(SUFFIX)
    src = sqlite3.connect(src_db.as_uri() + "?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        src.execute("BEGIN")
        ids = list(dict.fromkeys(paper_ids)) if paper_ids is not None else [
            r["id"] for r in src.execute("SELECT id FROM papers ORDER BY id")]
        if not ids:
            raise BundleError("no papers to bundle")
        schema = {r["name"]: r["sql"] for r in src.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table'") if r["name"] in TABLES + ("topics",)}
        missing = [t for t in ("papers", "questions") if t not in schema]
        if missing:
            raise BundleError(f"{src_db} is not a PaperLab database (missing {missing})")
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            db = stage / "paperlab.db"
            with closing(sqlite3.connect(db)) as out:
                papers_meta = _build_payload(src, out, src_db, stage, ids, schema, sources, extra)
            files = {}
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    files[safe_relpath(path.relative_to(stage).as_posix())] = _sha(path)
            _validate_file_names(files)
            chain = (prior_chain(out_path) if producer is not None else []) + ([{**producer, "at": _now()}] if producer else [])
            approvals = {}
            for pid, paper in zip(ids, papers_meta):
                review = ((extra or {}).get(pid, {}).get("reviews", {}) or {})
                holds = []
                for question, record in review.items():
                    approval = (record or {}).get("approval") or {}
                    rid = f"{pid}:{question}"
                    if (record or {}).get("approved") and approval.get("hashes"):
                        approvals[rid] = {**approval, "paper": pid, "question": str(question)}
                    elif record and record.get("reason"):
                        holds.append({"id": rid, "paper": pid, "question": str(question),
                                      "reason": record["reason"]})
                if holds:
                    paper["review_pending"] = (paper.get("review_pending", []) or []) + holds
            manifest = {"format": FORMAT, "version": VERSION, "created": _now(),
                        "producer": chain[-1] if chain else {"tool": "unknown"},
                        "producer_chain": chain,
                        "papers": papers_meta, "files": files, "approvals": approvals}
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=out_path.parent, suffix=".partial", delete=False) as f:
                partial = Path(f.name)
            try:
                with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as z:
                    z.writestr("bundle.json", json.dumps(manifest, indent=1, ensure_ascii=False))
                    for rel in files:
                        z.write(stage / rel, rel)
                os.replace(partial, out_path)  # never leave a half-written bundle
            finally:
                partial.unlink(missing_ok=True)
    finally:
        src.close()
    return {**manifest, "path": str(out_path)}


def _build_payload(src, out, src_db, stage, ids, schema, sources, extra):
    for name in TABLES:
        if name in schema:
            out.execute(schema[name])
    papers_meta = []
    for pid in ids:
        p = src.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
        if p is None:
            raise BundleError(f"paper {pid} not found in {src_db}")
        p = dict(p)
        key = _component(pid)
        pdf_columns = ("question_pdf_path", "solution_pdf_path")
        original = {col: (src_db.parent / p[col]).resolve() for col in pdf_columns if p.get(col)}
        for col in pdf_columns:
            p[col] = None  # re-pointed below if the file is bundled
        _insert_row(out, "papers", p)
        qs = list(src.execute("SELECT * FROM questions WHERE paper_id=? ORDER BY id", (pid,)))
        if not qs:
            raise BundleError(f"paper {pid} ({p.get('paper_name')}) has no questions")
        for row in qs:
            q = dict(row)
            number = _component(q["question_number"])
            folder = src_db.parent / (q["latex_folder"] or "")
            if not (folder / "question.tex").is_file():
                raise BundleError(f"paper {pid} Q{number}: question.tex missing in {folder}")
            rel = f"Outputs/{key}/{number}"
            dest = stage / rel
            dest.mkdir(parents=True)
            for name in ("question.tex", "solution.tex"):
                if (folder / name).is_file():
                    shutil.copyfile(folder / name, dest / name)
            figs = folder / "figures"
            if figs.is_dir():
                (dest / "figures").mkdir()
                for img in sorted(figs.iterdir()):
                    # Underscore files are local sidecars, not figures.
                    if img.is_file() and not img.name.startswith("_"):
                        shutil.copyfile(img, dest / "figures" / _component(img.name))
            q["latex_folder"] = rel
            _insert_row(out, "questions", q)
            if "question_topics" in schema:
                for t in src.execute("SELECT * FROM question_topics WHERE question_id=?", (q["id"],)):
                    _insert_row(out, "question_topics", dict(t))
        if "token_usage" in schema:
            for u in src.execute("SELECT * FROM token_usage WHERE paper_id=?", (pid,)):
                _insert_row(out, "token_usage", dict(u))
        stored, paths = [], {}
        source_files = (sources or {}).get(pid, original.values())
        for f in dict.fromkeys(Path(f).resolve() for f in source_files):
            rel = f"sources/{key}/{_component(f.name)}"
            dest = stage / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                raise BundleError(f"paper {pid}: source names collide: {f.name}")
            shutil.copyfile(f, dest)
            stored.append(rel)
            paths[f] = rel
        pdfs = [rel for f, rel in paths.items() if f.suffix.lower() == ".pdf"]
        for i, col in enumerate(pdf_columns):
            rel = paths.get(original.get(col)) if original else (pdfs[i] if i < len(pdfs) else None)
            out.execute(f"UPDATE papers SET {col}=? WHERE id=?", (rel, pid))
        papers_meta.append({
            **((extra or {}).get(pid, {})),
            "key": key, "name": p.get("paper_name"), "source": p.get("source_institute"),
            "exam_type": p.get("exam_type"), "identity": p.get("pdf_hash"),
            "questions": len(qs), "sources": stored})
    out.commit()
    if out.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise BundleError("staged bundle database failed integrity_check")
    return papers_meta


def _insert_row(db, table, row):
    columns = ",".join('"' + name.replace('"', '""') + '"' for name in row)
    return db.execute(f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' * len(row))})",
                      tuple(row.values()))


# ---------------------------------------------------------------------- read
def _validate_file_names(names):
    seen = {}
    files = set(names)
    for name in names:
        parts = safe_relpath(name).split("/")
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            folded = unicodedata.normalize("NFC", prefix).casefold()
            if seen.setdefault(folded, prefix) != prefix or (i < len(parts) and prefix in files):
                raise BundleError(f"conflicting portable paths in bundle: {name!r}")


_ZIP_END = struct.Struct("<4s4H2IH")
_FIGURE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
_RASTER_EXTENSIONS = _FIGURE_EXTENSIONS | {".webp"}
_FIGURE_BYTES = 3 * 1024 * 1024
_MAX_PIXELS = 8_000_000


def _check_upload_zip_end(path, limits):
    # Bound the central directory before ZipFile allocates a ZipInfo per entry.
    # Bundles created by PaperLab within these limits use normal single-disk ZIP.
    with path.open("rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        stream.seek(max(0, size - (_ZIP_END.size + 20)))
        tail = stream.read()
    end = len(tail) - _ZIP_END.size
    if end < 0 or tail[end:end + 4] != b"PK\x05\x06":
        raise BundleError("invalid ZIP bundle")
    _, disk, cd_disk, local, total, cd_size, _, comment = _ZIP_END.unpack_from(tail, end)
    if disk or cd_disk or local != total or comment:
        raise BundleError("expected a single-disk PaperLab ZIP bundle")
    if total > limits.members or cd_size > limits.members * 512:
        raise BundleLimitError("bundle has too many ZIP entries or too much ZIP metadata")
    # ZipFile can otherwise accept a ZIP64 locator that overrides these bounds.
    if end >= 20 and tail[end - 20:end - 16] == b"PK\x06\x07":
        raise BundleError("ZIP64 is not supported for HTTP uploads; split the bundle")


def _check_upload_members(members, limits):
    if len(members) > limits.members or sum(m.file_size for m in members) > limits.expanded_bytes:
        raise BundleLimitError("expanded bundle exceeds the upload limits")
    for m in members:
        name = safe_relpath(m.filename)
        parts = name.split("/")
        suffix = PurePosixPath(name).suffix.lower()
        # Accept only deflate options, a data descriptor, or the UTF-8 flag.
        if m.flag_bits & ~0x80E or m.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise BundleError("unsupported ZIP member flags or compression")
        if name == "bundle.json":
            ceiling = limits.manifest_bytes
        elif name == "paperlab.db":
            ceiling = limits.db_bytes
        elif len(parts) == 4 and parts[0] == "Outputs" and parts[3] in ("question.tex", "solution.tex"):
            ceiling = limits.tex_bytes
        elif len(parts) == 5 and parts[0] == "Outputs" and parts[3] == "figures" and suffix in _FIGURE_EXTENSIONS:
            ceiling = _FIGURE_BYTES
        elif len(parts) == 3 and parts[0] == "sources" and suffix in _RASTER_EXTENSIONS | {".pdf"}:
            ceiling = limits.expanded_bytes
        else:
            raise BundleError(f"unsupported file in uploaded bundle: {name!r}")
        if m.file_size > ceiling:
            raise BundleLimitError(f"bundle member exceeds the upload limit: {name!r}")


def _check_uploaded_media(file, rel):
    suffix = file.suffix.lower()
    if suffix not in _RASTER_EXTENSIONS | {".pdf"}:
        return
    with file.open("rb") as stream:
        head = stream.read(12)
    ok = {
        ".png": head.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": head.startswith(b"\xff\xd8\xff"),
        ".jpeg": head.startswith(b"\xff\xd8\xff"),
        ".webp": head.startswith(b"RIFF") and head[8:12] == b"WEBP",
        ".pdf": head.startswith(b"%PDF-"),
    }
    if not ok[suffix]:
        raise BundleError(f"media does not match its file type: {file.name!r}")
    if suffix != ".pdf":
        from PIL import Image

        image_format = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}[suffix]
        try:
            with Image.open(file, formats=[image_format]) as image:
                if image.width * image.height > _MAX_PIXELS:
                    raise BundleLimitError(f"image exceeds the pixel limit: {rel!r}")
                image.verify()
            with Image.open(file, formats=[image_format]) as image:
                image.load()
        except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
            raise BundleError(f"unreadable image in bundle: {rel!r}") from exc


def open_bundle(path, dest, *, upload_limits: UploadLimits | None = None) -> dict:
    """Validate and extract a bundle into ``dest``. Returns its manifest."""
    path, dest = Path(path), Path(dest)
    if upload_limits:
        _check_upload_zip_end(path, upload_limits)
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise BundleError("invalid PaperLab ZIP bundle") from exc
    with z:
        if upload_limits:
            _check_upload_members(z.infolist(), upload_limits)
        names = z.namelist()
        if len(names) != len(set(names)):
            raise BundleError("duplicate ZIP entries")
        if "bundle.json" not in names:
            raise BundleError("bundle.json missing")
        manifest = json.loads(z.read("bundle.json").decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise BundleError(f"not a {FORMAT} file")
        try:
            _serialize(manifest)
        except (ValueError, RecursionError) as exc:
            raise BundleError("bundle manifest must contain valid UTF-8 JSON values") from exc
        if manifest.get("version") != VERSION:
            raise BundleError(f"unsupported bundle version {manifest.get('version')!r}; expected {VERSION}")
        expected = manifest.get("files", {})
        if not isinstance(expected, dict) or "paperlab.db" not in expected or "bundle.json" in expected:
            raise BundleError("invalid bundle file manifest")
        _validate_file_names(names)
        if set(names) != {"bundle.json", *expected}:
            raise BundleError("ZIP entries do not match the bundle file manifest")
        if not isinstance(manifest.get("papers"), list) or not manifest["papers"]:
            raise BundleError("bundle must list at least one paper")
        for rel, digest in expected.items():
            rel = safe_relpath(rel)
            target = dest.joinpath(*PurePosixPath(rel).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(rel) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            if _sha(target) != digest:
                raise BundleError(f"checksum mismatch for {rel}: bundle is corrupt or was modified")
            if upload_limits:
                _check_uploaded_media(target, rel)
    return manifest


def _serialize(value):
    # Encoding now ensures a non-finite float or lone surrogate cannot turn
    # a committed upload into a validation failure when writing the receipt.
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


def inspect_bundle(path) -> dict:
    """Validate a bundle without merging. Returns the manifest, hard
    problems (block a merge) and review warnings (advisory: the owner has
    seen the figures in the review UI and merges directly)."""
    with tempfile.TemporaryDirectory() as tmp:
        manifest = open_bundle(path, tmp)
        problems, warnings = _content_problems(Path(tmp), manifest, reviews="warn")
    return {"manifest": manifest, "problems": problems, "warnings": warnings,
            "ok": not problems}


def _open_payload(root):
    db = sqlite3.connect((root / "paperlab.db").as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA trusted_schema=OFF")
    return db


def _validate_uploaded_rows(db):
    from database import DIFFICULTY_VALUES, QTYPE_VALUES

    specs = {
        "papers": (
            {"id", "paper_name", "pdf_hash"},
            {"id", "archive", "q_start", "q_end", "s_start", "s_end", "sol_section_start"},
            {"paper_name", "pdf_hash", "exam_type", "paper_date", "source_institute", "question_pdf_path",
             "solution_pdf_path", "status", "error", "sections"},
        ),
        "questions": (
            {"id", "paper_id", "question_number", "latex_folder", "qtype"},
            {"id", "paper_id"},
            {"question_number", "latex_folder", "qtype", "status", "difficulty", "topic_suggestion"},
        ),
        "question_topics": (
            {"question_id", "topic_code", "rank", "src"},
            {"id", "question_id", "rank"}, {"topic_code", "src"},
        ),
        "token_usage": (
            {"paper_id", "phase", "input", "cache_read", "output", "reasoning"},
            {"id", "paper_id", "input", "cache_read", "output", "reasoning"}, {"phase", "ts"},
        ),
    }
    counts = dict(zip(TABLES, (512, 4096, 65536, 200_000)))
    ids = {"papers": set(), "questions": set()}
    for table, (required, ints, texts) in specs.items():
        cols = {row["name"]: row["hidden"] for row in db.execute(f"PRAGMA main.table_xinfo({table})")}
        if not required <= cols.keys() or any(cols.values()):
            raise BundleError(f"invalid columns in bundle table {table}")
        if db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] > counts[table]:
            raise BundleLimitError(f"too many rows in bundle table {table}")
        # Explicit select lists prevent unrelated source columns being evaluated.
        selected = sorted((ints | texts | ({"elapsed_sec"} if table == "papers" else set())) & cols.keys())
        for n, row in enumerate(db.execute(f"SELECT {','.join(selected)} FROM {table}"), 1):
            def invalid(field):
                raise BundleError(f"invalid {table}.{field} in payload row {n}")

            for field in selected:
                value = row[field]
                if value is None:
                    if field in required:
                        invalid(field)
                    continue
                if field in ints:
                    if type(value) is not int or not 0 <= value <= (1 << 53) - 1:
                        invalid(field)
                    if field in {"id", "paper_id", "question_id"} and value == 0:
                        invalid(field)
                elif field in texts:
                    limit = 65536 if field == "sections" else 8192 if field in {"topic_suggestion", "error"} else 1024
                    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
                        invalid(field)
                    if field in required and not value.strip():
                        invalid(field)
                elif type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                    invalid(field)
            if table in ids:
                if row["id"] in ids[table]:
                    invalid("id")
                ids[table].add(row["id"])
            if table in {"questions", "token_usage"} and row["paper_id"] not in ids["papers"]:
                invalid("paper_id")
            if table == "questions":
                if row["qtype"] not in QTYPE_VALUES:
                    invalid("qtype")
                if "difficulty" in cols and row["difficulty"] not in (None, *DIFFICULTY_VALUES):
                    invalid("difficulty")
                number = row["question_number"]
                if len(number) > 120 or any(c in "#%" for c in number):
                    invalid("question_number")
            if table == "question_topics":
                if row["question_id"] not in ids["questions"]:
                    invalid("question_id")
                if row["src"] not in ("auto", "human"):
                    invalid("src")
            if table == "token_usage" and (row["cache_read"] > row["input"] or
                                            any(row[field] > 1_000_000_000 for field in ("input", "output", "reasoning"))):
                invalid("token counters")


def _review_findings(manifest, question_files):
    approvals = manifest.get("approvals", {})
    if not isinstance(approvals, dict):
        raise BundleError("invalid approval manifest")
    approved, findings = set(), []
    for rid, proof in approvals.items():
        if not isinstance(proof, dict):
            raise BundleError("invalid approval record")
        key = (str(proof.get("paper", "")), str(proof.get("question", "")))
        files = question_files.get(key)
        if (rid == ":".join(key) and files and proof.get("hashes") == files and
                all(isinstance(proof.get(field), str) and proof[field].strip() for field in ("by", "at", "note"))):
            approved.add(key)
        else:
            findings.append(f"stale or mismatched approval {rid!r}; review the complete question again")
    for paper in manifest["papers"]:
        pid = str(paper["key"])
        pending = paper.get("review_pending") or []
        reviews = paper.get("reviews") or {}
        if not isinstance(pending, list) or not isinstance(reviews, dict):
            raise BundleError(f"invalid review records for paper {pid}")
        reported = set()
        for hold in pending:
            if not isinstance(hold, dict):
                findings.append(f"paper {pid}: unrecognized review hold")
                continue
            key = (pid, str(hold.get("question", "")))
            if str(hold.get("paper", "")) != pid or hold.get("id") != ":".join(key) or key not in approved:
                findings.append(f"paper {pid} Q{key[1]}: item(s) still need human review: "
                                f"{str(hold.get('reason', 'unresolved hold'))[:512]}")
                reported.add(key)
        for number, review in reviews.items():
            key = (pid, number)
            if not isinstance(review, dict):
                raise BundleError(f"invalid review record for paper {pid}")
            if (review.get("reason") or review.get("approved")) and key not in approved and key not in reported:
                findings.append(f"paper {pid} Q{number}: item(s) still need human review")
    return findings


def _content_problems(root: Path, manifest: dict, reviews: str = "block", *, uploaded=False) -> tuple:
    """Problems found in an extracted bundle. ``reviews`` controls the gate:

    * ``"block"`` (default): unapproved review items and stale approvals are
      problems that refuse ``inspect``/``merge``.
    * ``"warn"``: the same findings come back under ``warnings`` instead, so
      the caller decides. Used by the importers, whose owners review in the UI
      and merge directly.
    """
    problems, review_notes = [], []
    gate = review_notes if reviews == "warn" else problems
    question_files = {}
    files_by_folder = {}
    for rel, digest in manifest["files"].items():
        parts = rel.split("/")
        if len(parts) >= 4 and parts[0] == "Outputs":
            files_by_folder.setdefault((parts[1], parts[2]), {})["/".join(parts[3:])] = digest
    db = _open_payload(root)
    try:
        if uploaded:
            tables = {r["name"]: r["type"] for r in db.execute("PRAGMA main.table_list")}
            if any(tables.get(name) != "table" for name in TABLES):
                raise BundleError("bundle database must contain the PaperLab payload tables")
            if any(kind in ("virtual", "shadow") for kind in tables.values()):
                raise BundleError("virtual tables are not allowed in uploaded bundles")
            _validate_uploaded_rows(db)
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            problems.append("bundle database integrity_check failed")
        keys = {_component(p["key"]) for p in manifest["papers"]}
        rows = {str(r["id"]) for r in db.execute("SELECT id FROM papers")}
        if keys != rows or len(keys) != len(manifest["papers"]):
            problems.append(f"manifest papers {sorted(keys)} != database papers {sorted(rows)}")
        for p in manifest["papers"]:
            pid = str(p["key"])
            paper = db.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
            if paper is None:
                continue
            count = db.execute("SELECT count(*) FROM questions WHERE paper_id=?", (pid,)).fetchone()[0]
            if not count or type(p["questions"]) is not int or count != p["questions"]:
                problems.append(f"paper {pid}: question count does not match the manifest")
            if any(p.get(key) != paper[column] for key, column in
                   (("name", "paper_name"), ("source", "source_institute"), ("identity", "pdf_hash"), ("exam_type", "exam_type"))):
                problems.append(f"paper {pid}: identity metadata does not match the database")
            for col in ("question_pdf_path", "solution_pdf_path"):
                if rel := paper[col]:
                    parts = safe_relpath(rel).split("/")
                    if len(parts) != 3 or parts[:2] != ["sources", pid] or not (root / rel).is_file():
                        problems.append(f"paper {pid}: missing or invalid {col}")
                    elif uploaded and (root / rel).suffix.lower() != ".pdf":
                        problems.append(f"paper {pid}: {col} must refer to a source PDF")
        for q in db.execute("SELECT paper_id, question_number, latex_folder FROM questions"):
            number = _component(q["question_number"])
            rel = f"Outputs/{_component(q['paper_id'])}/{number}"
            if str(q["paper_id"]) not in rows or q["latex_folder"] != rel or number.casefold() == "_source":
                problems.append(f"paper {q['paper_id']} Q{number}: invalid question folder")
                continue
            folder = root / rel
            qtex = folder / "question.tex"
            if not qtex.is_file() or not qtex.read_text(encoding="utf-8").strip():
                problems.append(f"paper {q['paper_id']} Q{q['question_number']}: empty or missing question.tex")
                continue
            key = (str(q["paper_id"]), number)
            question_files[key] = files_by_folder.get(key, {})
            for filename in ("question.tex", "solution.tex"):
                file = folder / filename
                if not file.is_file():
                    continue
                from app.latex_syntax import analyze, checked_figure_references, normalize_figure_references

                text = file.read_text(encoding="utf-8")
                refs, errors = checked_figure_references(text)
                if uploaded:
                    syntax, text_underscores = analyze(text)
                    errors.extend(syntax)
                    if text_underscores:
                        errors.append("unescaped text underscores; save with the native tools and re-export")
                    if normalize_figure_references(text) != text:
                        errors.append("figure commands must use the canonical figures/NAME form")
                    wrong_prefix = "sfig" if filename == "question.tex" else "qfig"
                    errors.extend(f"figure on the wrong side: {name}" for name in refs if name.startswith(wrong_prefix))
                errors.extend(f"missing figure {name}" for name in refs if not (folder / "figures" / name).is_file())
                problems.extend(f"paper {key[0]} Q{number} {filename}: {e}" for e in errors[:10])
        gate.extend(_review_findings(manifest, question_files))
    finally:
        db.close()
    return (problems, []) if reviews == "block" else (problems, review_notes)


# --------------------------------------------------------------------- merge
def merge_bundle(path, target_db, target_outputs=None, dry_run=False, allow_untagged=False,
                 reviews="warn", *, upload_limits: UploadLimits | None = None, idempotent=False) -> dict:
    """Merge one bundle into a PaperLab archive: all-or-nothing.

    Verification is advisory: review findings come back in ``warnings`` but
    never block. ``reviews="block"`` restores the old hard gate (unapproved
    items and stale approvals refuse the merge). Refuses (BundleError,
    nothing changed) only when the bundle itself fails validation, a paper
    already exists in the target (same identity or name+source), topics are
    missing (unless ``allow_untagged``), a topic code is unknown, or the
    target is not a PaperLab archive. Otherwise: backup -> copy folders ->
    one transaction -> integrity checks; on any failure the copied folders
    are removed and the transaction is rolled back.
    """
    target = Path(target_db).resolve()
    outbase = Path(target_outputs).resolve() if target_outputs else target.parent / "Outputs"
    if reviews not in {"warn", "block"}:
        raise BundleError(f"unknown review policy {reviews!r}")
    if target.exists() and not target.is_file():
        raise BundleError(f"target archive path exists but is not a file: {target}")
    digest = _sha(path)
    if idempotent and not dry_run and target.is_file():
        with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as live:
            previous = saved_receipt(live, digest)
        if previous is not None:
            return {**previous, "already_imported": True}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp) / "payload"
        manifest = open_bundle(path, root, upload_limits=upload_limits)
        problems, warnings = _content_problems(root, manifest, reviews=reviews, uploaded=upload_limits is not None)
        summary = {"target": str(target), "papers": [
            {"name": p["name"], "questions": p["questions"]} for p in manifest["papers"]]}
        with closing(_open_payload(root)) as src:
            fresh = not target.exists()
            if dry_run or fresh:
                shadow = Path(tmp) / "target.db"
                if fresh:
                    _prepare_target(shadow)
                else:
                    # SQLite backup includes committed WAL rows. Do not checkpoint,
                    # migrate, or open the real database for writing during preview.
                    with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as live:
                        with closing(sqlite3.connect(shadow)) as copy:
                            live.backup(copy)
                with closing(sqlite3.connect(shadow)) as check:
                    _commit(root, src, manifest, shadow, outbase, summary, check,
                            problems, warnings, allow_untagged, digest, preview=True)
                if dry_run:
                    return {**summary, "dry_run": True, "mergeable": True, "warnings": warnings}
                target.parent.mkdir(parents=True, exist_ok=True)
                # Do not replace another process's freshly initialized target.
                with target.open("xb") as new_db:
                    try:
                        with shadow.open("rb") as staged:
                            shutil.copyfileobj(staged, new_db)
                    except Exception:
                        new_db.close()
                        target.unlink(missing_ok=True)
                        raise
            try:
                with closing(sqlite3.connect(target, timeout=30)) as live:
                    return _commit(root, src, manifest, target, outbase, summary, live,
                                   problems, warnings, allow_untagged, digest, idempotent=idempotent)
            except Exception:
                if fresh:
                    target.unlink(missing_ok=True)
                raise


def _validate_merge(src, problems, t, target, allow_untagged):
    """Hard checks that DO refuse a merge (duplicates, topics, bad target)."""
    if not allow_untagged:
        has_suggestion = any(col[1] == "topic_suggestion" for col in src.execute("PRAGMA table_info(questions)"))
        no_suggestion = "AND COALESCE(trim(q.topic_suggestion), '') = ''" if has_suggestion else ""
        untagged = list(src.execute("SELECT q.paper_id, q.question_number FROM questions q WHERE NOT EXISTS "
                                    "(SELECT 1 FROM question_topics t WHERE t.question_id=q.id) " + no_suggestion))
        problems.extend(f"paper {q['paper_id']} Q{q['question_number']}: no topic tags "
                        "(tag before export, or merge with allow_untagged)" for q in untagged)
    tables = {r[0] for r in t.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"papers", "questions"} <= tables or not target.stat().st_size:
        # Checked BEFORE any migration so a wrong file is never turned into an archive.
        raise BundleError(f"{target} is not a PaperLab archive (no papers/questions tables)")
    if not set(TABLES + ("topics",)) <= tables:
        raise BundleError("target archive needs a schema upgrade; start the current PaperLab app before merging")
    known_topics = {r[0] for r in t.execute("SELECT code FROM topics")}
    for (code,) in src.execute("SELECT DISTINCT topic_code FROM question_topics"):
        if code not in known_topics:
            problems.append(f"topic code {code!r} does not exist in the target syllabus")
    conflicts, names, identities = [], set(), set()
    for pdf_hash, name, source in src.execute("SELECT pdf_hash, paper_name, source_institute FROM papers"):
        identity = (name, source)
        if identity in names or (pdf_hash is not None and pdf_hash in identities):
            conflicts.append(f"bundle contains duplicate papers named '{name}' ({source})")
        names.add(identity)
        identities.add(pdf_hash)
        dup = t.execute("SELECT id FROM papers WHERE pdf_hash=? OR (paper_name=? AND source_institute IS ?)",
                        (pdf_hash, name, source)).fetchone()
        if dup:
            conflicts.append(f"target already has '{name}' ({source}) as paper {dup[0]}")
    if problems:
        raise BundleError("bundle cannot be merged:\n  " + "\n  ".join(problems[:60]))
    if conflicts:
        raise BundleConflict("bundle cannot be merged:\n  " + "\n  ".join(conflicts[:60]))
    return True


def _prepare_target(target: Path):
    """Seed a new archive using PaperLab's own schema and syllabus."""
    repo = Path(__file__).resolve().parent.parent
    if (repo / "database.py").is_file():
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        import database
        database.init_db(str(target))
        database.init_topics(str(target))


def _commit(root, src, manifest, target, outbase, summary, t, problems, warnings,
            allow_untagged, digest, *, preview=False, idempotent=False):
    """Copy question folders + all rows, atomically: backup -> transaction -> checks.

    ``src`` comes in as a READ-ONLY handle and stays open through this call,
    so Windows can delete the temp extraction dir afterwards without a locked
    file blocking it.
    """
    backup = None
    publication = None
    copies = []
    t.row_factory = sqlite3.Row
    receipt = {"merged": _now(), "target": str(target), "warnings": warnings, "sha256": digest,
               "producer": manifest.get("producer"), "producer_chain": manifest.get("producer_chain", []),
               "papers": []}
    try:
        t.execute("PRAGMA foreign_keys=ON")
        # In rollback-journal mode, dirty-page spilling can take an exclusive
        # lock early and block our own read-only pre-merge backup connection.
        t.execute("PRAGMA cache_spill=OFF")
        t.execute("BEGIN IMMEDIATE")
        if not preview:
            recover_locked(t, target, outbase)
        previous = saved_receipt(t, digest)
        if previous is not None and idempotent and not preview:
            t.rollback()
            return {**previous, "already_imported": True}
        _validate_merge(src, list(problems), t, target, allow_untagged)
        if previous is not None:
            raise BundleConflict("this exact bundle was already imported into the archive")
        if not preview:
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            backup = target.with_name(f"{target.stem}.pre-bundle-merge-{stamp}-{uuid.uuid4().hex[:8]}.bak")
        receipt["backup"] = str(backup) if backup else None
        paper_meta = {str(p["key"]): p for p in manifest["papers"]}
        cols = {name: [r["name"] for r in t.execute(f"PRAGMA table_info({name})") if r["name"] != "id"]
                for name in ("papers", "questions", "question_topics", "token_usage")}
        for p in src.execute("SELECT * FROM papers ORDER BY id"):
            p = dict(p)
            row = {c: p.get(c) for c in cols["papers"]}
            row["status"] = "done"
            if "archive" in row:
                row["archive"] = 1
            t.execute(f"INSERT INTO papers ({','.join(cols['papers'])}) VALUES ({','.join('?' * len(cols['papers']))})",
                      [row[c] for c in cols["papers"]])
            new_pid = t.execute("SELECT last_insert_rowid()").fetchone()[0]
            paper_dir = outbase / str(new_pid)
            if paper_dir.exists() or paper_dir.is_symlink():
                raise BundleConflict(f"target folder already exists for paper {new_pid}")
            media = []
            copies.append((new_pid, media))
            src_dir = root / "sources" / str(p["id"])
            if src_dir.is_dir():
                media.append((src_dir, "_source"))
                for col in ("question_pdf_path", "solution_pdf_path"):
                    if p.get(col):
                        t.execute(f"UPDATE papers SET {col}=? WHERE id=?",
                                  (str(paper_dir / "_source" / PurePosixPath(p[col]).name), new_pid))
            count = 0
            for q in src.execute("SELECT * FROM questions WHERE paper_id=? ORDER BY id", (p["id"],)):
                q = dict(q)
                folder = paper_dir / q["question_number"]
                media.append((root / q["latex_folder"], q["question_number"]))
                qrow = {c: q.get(c) for c in cols["questions"]}
                qrow.update(paper_id=new_pid, latex_folder=str(folder))
                t.execute(f"INSERT INTO questions ({','.join(cols['questions'])}) VALUES ({','.join('?' * len(cols['questions']))})",
                          [qrow[c] for c in cols["questions"]])
                new_qid = t.execute("SELECT last_insert_rowid()").fetchone()[0]
                for link in src.execute("SELECT * FROM question_topics WHERE question_id=?", (q["id"],)):
                    link = dict(link)
                    link["question_id"] = new_qid
                    lc = [c for c in cols["question_topics"] if c in link]
                    t.execute(f"INSERT INTO question_topics ({','.join(lc)}) VALUES ({','.join('?' * len(lc))})",
                              [link[c] for c in lc])
                count += 1
            for u in src.execute("SELECT * FROM token_usage WHERE paper_id=?", (p["id"],)):
                u = dict(u)
                u["paper_id"] = new_pid
                uc = [c for c in cols["token_usage"] if c in u]
                t.execute(f"INSERT INTO token_usage ({','.join(uc)}) VALUES ({','.join('?' * len(uc))})",
                          [u[c] for c in uc])
            if t.execute("SELECT count(*) FROM questions WHERE paper_id=?", (new_pid,)).fetchone()[0] != count:
                raise BundleError(f"question count mismatch for {p['paper_name']}")
            receipt["papers"].append({"bundle_key": p["id"], "archive_paper": new_pid,
                                      "name": p["paper_name"], "questions": count,
                                      "provenance": paper_meta[str(p["id"])]})
        if t.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or t.execute("PRAGMA foreign_key_check").fetchall():
            raise BundleError("target integrity/foreign-key check failed")
        if preview:
            t.rollback()
            return receipt
        payload = _serialize(receipt)
        # All row, folder and receipt checks precede the backup and media copies.
        # The read-only sibling sees the committed pre-merge state.
        with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as live:
            with closing(sqlite3.connect(backup)) as bak:
                live.backup(bak)
        publication = Publication(target, outbase)
        for pid, media in copies:
            staging = publication.stage(pid)
            for source, name in media:
                shutil.copytree(source, staging / name)
        record_receipt(t, digest, payload.decode("utf-8"))
        publication.install(digest, [pid for pid, _ in copies])
        t.commit()
    except BaseException:
        try:
            if publication is not None and t.in_transaction:
                publication.finish(committed=False)
        except OSError:
            _log.exception("Bundle rollback needs media recovery")
        finally:
            t.rollback()
        raise
    log = target.with_name(f"{target.stem}.bundle-merges.jsonl")
    try:
        publication.finish(committed=True)
    except OSError:
        _log.exception("Committed bundle media journal cleanup failed")
        receipt["warnings"] = [*receipt["warnings"], "Import committed; media journal cleanup is pending."]
    try:
        with open(log, "ab") as f:
            f.write(payload + b"\n")
    except OSError:
        _log.exception("Committed bundle receipt log could not be written")
        receipt["warnings"] = [*receipt["warnings"], "Import committed; the optional receipt log could not be written."]
    return {**summary, **receipt}
