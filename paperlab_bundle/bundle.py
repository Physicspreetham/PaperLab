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
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import unicodedata
import uuid
import zipfile
from pathlib import Path, PurePosixPath

FORMAT = "paperlab-bundle"
VERSION = 1
TABLES = ("papers", "questions", "question_topics", "token_usage")
SUFFIX = ".plbundle"
_WINDOWS_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", re.I)


class BundleError(ValueError):
    """A bundle (or merge target) failed validation; nothing was changed."""


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


def open_bundle(path, dest) -> dict:
    """Validate and extract a bundle into ``dest``. Returns its manifest."""
    path, dest = Path(path), Path(dest)
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise BundleError(f"{path} is not a PaperLab bundle: {exc}")
    with z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise BundleError("duplicate ZIP entries")
        if "bundle.json" not in names:
            raise BundleError("bundle.json missing")
        manifest = json.loads(z.read("bundle.json").decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise BundleError(f"not a {FORMAT} file")
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
    return manifest


def inspect_bundle(path) -> dict:
    """Validate a bundle without merging. Returns the manifest, hard
    problems (block a merge) and review warnings (advisory: the owner has
    seen the figures in the review UI and merges directly)."""
    with tempfile.TemporaryDirectory() as tmp:
        manifest = open_bundle(path, tmp)
        problems, warnings = _content_problems(Path(tmp), manifest, reviews="warn")
    return {"manifest": manifest, "problems": problems, "warnings": warnings,
            "ok": not problems}


def _content_problems(root: Path, manifest: dict, reviews: str = "block") -> tuple:
    """Problems found in an extracted bundle. ``reviews`` controls the gate:

    * ``"block"`` (default): unapproved review items and stale approvals are
      problems that refuse ``inspect``/``merge``.
    * ``"warn"``: the same findings come back under ``warnings`` instead, so
      the caller decides. Used by the importers, whose owners review in the UI
      and merge directly.
    """
    problems, review_notes = [], []
    gate = review_notes if reviews == "warn" else problems
    approvals = manifest.get("approvals", {})
    db = sqlite3.connect((root / "paperlab.db").as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
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
            if not count or count != p["questions"]:
                problems.append(f"paper {pid}: question count does not match the manifest")
            for col in ("question_pdf_path", "solution_pdf_path"):
                if rel := paper[col]:
                    parts = safe_relpath(rel).split("/")
                    if len(parts) != 3 or parts[:2] != ["sources", pid] or not (root / rel).is_file():
                        problems.append(f"paper {pid}: missing or invalid {col}")
        for q in db.execute("SELECT paper_id, question_number, latex_folder FROM questions"):
            number = _component(q["question_number"])
            rel = f"Outputs/{_component(q['paper_id'])}/{number}"
            if str(q["paper_id"]) not in rows or q["latex_folder"] != rel:
                problems.append(f"paper {q['paper_id']} Q{number}: invalid question folder")
                continue
            folder = root / rel
            qtex = folder / "question.tex"
            if not qtex.is_file() or not qtex.read_text(encoding="utf-8").strip():
                problems.append(f"paper {q['paper_id']} Q{q['question_number']}: empty or missing question.tex")
                continue
            text = qtex.read_text(encoding="utf-8") + (
                (folder / "solution.tex").read_text(encoding="utf-8") if (folder / "solution.tex").is_file() else "")
            for ref in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{figures/([^}]+)\}", text):
                if not (folder / "figures" / _component(ref)).is_file():
                    problems.append(f"paper {q['paper_id']} Q{q['question_number']}: missing figure {ref}")
        for p in manifest["papers"]:
            pending = [h for h in (p.get("review_pending") or []) if isinstance(h, dict)]
            holds = [h for h in pending if not approvals.get(h.get("id", ""))]
            if holds:
                gate.append(f"paper {p['key']} ({p.get('name')}): {len(holds)} item(s) still need human review: "
                            + "; ".join(h.get("reason", h.get("id", "?")) for h in holds[:5]))
            stale = []
            # Covers holds AND approved-clean items: any approval whose files
            # changed after review is stale, even if nothing else is pending.
            for rid, proof in approvals.items():
                if str(proof.get("paper", p["key"])) != str(p["key"]):
                    continue
                qn = _component(proof.get("question", ""))
                current = {}
                for name in proof.get("hashes", {}):
                    file = root / "Outputs" / str(p["key"]) / qn / safe_relpath(name)
                    if file.is_file():
                        current[name] = _sha(file)
                if current != {k: v for k, v in proof.get("hashes", {}).items()}:
                    stale.append(rid)
            if stale:
                gate.append(f"paper {p['key']}: {len(stale)} approval(s) stale (files changed after review): "
                            + ", ".join(stale[:5]))
    finally:
        db.close()
    return (problems, []) if reviews == "block" else (problems, review_notes)


# --------------------------------------------------------------------- merge
def merge_bundle(path, target_db, target_outputs=None, dry_run=False, allow_untagged=False,
                 reviews="warn") -> dict:
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
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "payload"
        manifest = open_bundle(path, root)
        problems, warnings = _content_problems(root, manifest, reviews=reviews)
        summary = {"target": str(target), "papers": [
            {"name": p["name"], "questions": p["questions"]} for p in manifest["papers"]]}
        with closing(sqlite3.connect((root / "paperlab.db").as_uri() + "?mode=ro", uri=True)) as src:
            src.row_factory = sqlite3.Row
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
                            problems, warnings, allow_untagged, preview=True)
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
                                   problems, warnings, allow_untagged)
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
    for pdf_hash, name, source in src.execute("SELECT pdf_hash, paper_name, source_institute FROM papers"):
        dup = t.execute("SELECT id FROM papers WHERE pdf_hash=? OR (paper_name=? AND source_institute IS ?)",
                        (pdf_hash, name, source)).fetchone()
        if dup:
            problems.append(f"target already has '{name}' ({source}) as paper {dup[0]}")
    if problems:
        raise BundleError("bundle cannot be merged:\n  " + "\n  ".join(problems[:60]))
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


def _commit(root, src, manifest, target, outbase, summary, t, problems, warnings, allow_untagged, preview=False):
    """Copy question folders + all rows, atomically: backup -> transaction -> checks.

    ``src`` comes in as a READ-ONLY handle and stays open through this call,
    so Windows can delete the temp extraction dir afterwards without a locked
    file blocking it.
    """
    backup = None
    copied = []
    t.row_factory = sqlite3.Row
    receipt = {"merged": _now(), "target": str(target), "warnings": warnings,
               "producer": manifest.get("producer"), "producer_chain": manifest.get("producer_chain", []),
               "papers": []}
    try:
        t.execute("PRAGMA foreign_keys=ON")
        t.execute("BEGIN IMMEDIATE")
        _validate_merge(src, list(problems), t, target, allow_untagged)
        if not preview:
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            backup = target.with_name(f"{target.stem}.pre-bundle-merge-{stamp}-{uuid.uuid4().hex[:8]}.bak")
            # Snapshot the pre-merge state while this transaction excludes other writers.
            with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as live:
                with closing(sqlite3.connect(backup)) as bak:
                    live.backup(bak)
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
                raise BundleError(f"target folder already exists: {paper_dir}")
            if not preview:
                paper_dir.mkdir(parents=True)
                copied.append(paper_dir)
            src_dir = root / "sources" / str(p["id"])
            if src_dir.is_dir():
                if not preview:
                    shutil.copytree(src_dir, paper_dir / "_source")
                for col in ("question_pdf_path", "solution_pdf_path"):
                    if p.get(col):
                        t.execute(f"UPDATE papers SET {col}=? WHERE id=?",
                                  (str(paper_dir / "_source" / PurePosixPath(p[col]).name), new_pid))
            count = 0
            for q in src.execute("SELECT * FROM questions WHERE paper_id=? ORDER BY id", (p["id"],)):
                q = dict(q)
                folder = paper_dir / q["question_number"]
                if not preview:
                    shutil.copytree(root / q["latex_folder"], folder)
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
        t.commit()
    except Exception:
        t.rollback()
        for folder in copied:
            shutil.rmtree(folder, ignore_errors=True)
        raise
    log = target.with_name(f"{target.stem}.bundle-merges.jsonl")
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    except OSError as exc:
        receipt["warnings"] = [*warnings, f"Merge committed, but could not write {log}: {exc}"]
    return {**summary, **receipt}
