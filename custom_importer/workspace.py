"""Custom importer: submit agent-transcribed questions into a TEMP workspace.

An external agent (Codex, Claude Code, ...) reads a book itself and submits
each question/solution/figure here. Everything is saved by PaperLab's OWN
native savers and validators into an isolated workspace database; nothing
touches the real archive until an explicit ``merge``.

Workspace layout (any folder OUTSIDE the archive)::

    <workspace>/paperlab.db       temp database (same schema as the archive)
    <workspace>/Outputs/<paper>/<question>/question.tex, solution.tex, figures/
    <workspace>/sources/<paper>/  optional original files (PDF/images)
    <workspace>/workspace.json    papers, provenance and merge receipts

Only one workspace may be active per Python process (PaperLab modules bind
their database/output paths when first imported).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
IMPORTER = REPO / "importer_EJEE"
FIGURE_NAME = re.compile(r"[qs]fig\d+\.png")
NO_SOLUTION = "no_solution_found"

_ACTIVE: "Workspace | None" = None


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _archive_paths():
    db = Path(os.environ.get("PAPERLAB_ARCHIVE_DB") or os.environ.get("PHYSICS_ARCHIVE_DB")
              or REPO / "physics_archive.db").resolve()
    out = Path(os.environ.get("PHYSICS_OUTPUT_BASE") or db.parent / "Outputs").resolve()
    return db, out


class Workspace:
    """A temp staging area. Create once per process with ``Workspace.open``."""

    def __init__(self, path: Path):
        self.path = path
        self.db = path / "paperlab.db"
        self.outputs = path / "Outputs"
        self.meta_file = path / "workspace.json"

    # ------------------------------------------------------------ lifecycle
    @classmethod
    def open(cls, path) -> "Workspace":
        global _ACTIVE
        path = Path(path).resolve()
        if _ACTIVE is not None:
            if _ACTIVE.path == path:
                return _ACTIVE
            raise RuntimeError(f"Workspace {_ACTIVE.path} is already active in this process; "
                               "use a new process for another workspace")
        archive_db, archive_out = _archive_paths()
        if path == archive_db.parent or path == archive_out or archive_out in path.parents \
                or path in (REPO, REPO / "Outputs"):
            raise ValueError(f"Workspace {path} overlaps the real archive; choose a separate folder")
        ws = cls(path)
        for entry in (ws.db, ws.outputs, ws.meta_file, path / "data", path / "sources"):
            if entry.is_symlink():
                raise ValueError(f"Workspace path must not be a symlink: {entry}")
        for module, attr, expected in (("database", "DB_PATH", ws.db),
                                       ("directory_manager", "OUTPUT_BASE", ws.outputs)):
            if module in sys.modules and Path(getattr(sys.modules[module], attr)).resolve() != expected:
                raise RuntimeError(f"{module} is already bound to a different store; open the workspace in a new process")
        path.mkdir(parents=True, exist_ok=True)
        (path / "Outputs").mkdir(exist_ok=True)
        os.environ["PHYSICS_ARCHIVE_DB"] = str(ws.db)
        os.environ["PHYSICS_OUTPUT_BASE"] = str(ws.outputs)
        os.environ["DATA_ROOT"] = str(path / "data")
        os.environ.setdefault("PIPELINE_CONFIG", str(REPO / "config.yaml"))
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        os.environ["LANGSMITH_TRACING"] = "false"
        for p in (str(REPO), str(IMPORTER)):
            if p not in sys.path:
                sys.path.insert(0, p)
        import config  # bind the workspace before database/tools are imported
        import database
        database.init_db()
        database.init_topics()
        if not ws.meta_file.exists():
            ws._write_meta({"schema": "paperlab-custom-workspace/1", "created": ws._now(),
                            "papers": {}, "merges": []})
        _ACTIVE = ws
        return ws

    @staticmethod
    def _now():
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _meta(self):
        return json.loads(self.meta_file.read_text(encoding="utf-8"))

    def _write_meta(self, meta):
        tmp = self.meta_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.meta_file)

    # --------------------------------------------------------------- papers
    def new_paper(self, name: str, source: str, exam_type: str = "Textbook",
                  paper_date: str | None = None, source_files=(), notes: str = "") -> int:
        """Register one question paper (e.g. 'Irodov — Part 3'). Returns paper_id.

        ``name`` is the title shown in PaperLab; ``source`` the book/institute
        (papers.source_institute). The pair must be unique: re-registering the
        same pair returns the existing id instead of creating a duplicate.
        """
        import database
        name, source = (name or "").strip(), (source or "").strip()
        if not name or not source:
            raise ValueError("new_paper needs a non-empty name and source")
        files = [Path(f) for f in source_files]
        if len({f.name.casefold() for f in files}) != len(files):
            raise ValueError("Source filenames must be distinct")
        for f in files:
            if not f.is_file():
                raise FileNotFoundError(f)
        identity = hashlib.sha256(f"custom|{source}|{name}".encode("utf-8")).hexdigest()
        with database.get_connection() as c:
            row = c.execute("SELECT id FROM papers WHERE pdf_hash=?", (identity,)).fetchone()
            if row:
                return int(row["id"])
            c.execute("INSERT INTO papers (paper_name, exam_type, paper_date, source_institute, pdf_hash, status)"
                      " VALUES (?,?,?,?,?, 'uploaded')", (name, exam_type, paper_date, source, identity))
            pid = int(c.execute("SELECT last_insert_rowid()").fetchone()[0])
        stored = []
        for f in files:
            dest = self.path / "sources" / str(pid) / f.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            stored.append({"file": str(dest), "sha256": _sha(dest)})
        pdfs = [s["file"] for s in stored if s["file"].lower().endswith(".pdf")]
        if pdfs:
            with database.get_connection() as c:
                c.execute("UPDATE papers SET question_pdf_path=?, solution_pdf_path=? WHERE id=?",
                          (pdfs[0], pdfs[1] if len(pdfs) > 1 else None, pid))
        meta = self._meta()
        meta["papers"][str(pid)] = {"name": name, "source": source, "exam_type": exam_type,
                                    "created": self._now(), "source_files": stored, "notes": notes,
                                    "questions": {}}
        self._write_meta(meta)
        return pid

    # -------------------------------------------------------------- submit
    def submit(self, paper_id: int, number: str, question_tex: str, solution_tex: str,
               qtype: str = "unknown", figures: dict | None = None, answer_key: str | None = None,
               source_ref: str = "", review_note: str = "") -> dict:
        """Save ONE question + its solution (+ figures). Returns a report dict.

        * ``number``: the question number shown in the paper ("1", "15a").
        * ``question_tex`` / ``solution_tex``: PaperLab LaTeX. Solutions start
          with ``\\textbf{Answer: <number>) ...}``, then a blank line,
          ``\\underline{\\textbf{Solution for <number>}}``, a blank line and
          the worked solution. Use exactly ``no_solution_found`` when the
          source has neither a solution nor an answer key.
        * ``figures``: {"qfig1.png": "path/to/image", "sfig1.png": ...};
          qfig* are referenced from the question, sfig* from the solution as
          ``\\includegraphics[width=\\linewidth]{figures/qfig1.png}``.
        * ``answer_key``: the source's key, if it has one (enforces that the
          solution opens with the Answer line).

        Resubmitting the same number replaces it. ``ok`` is True only when
        both halves are saved and every completion check passes.
        """
        import directory_manager
        from importer import normalize_rendering, validate_item
        from submission_guard import guard_saved_submission, normalize_figure_references
        import tools_extractor as tools
        number = directory_manager.safe_component(str(number).strip(), "question number")
        self._require_paper(paper_id)
        report = {"paper_id": paper_id, "number": number, "ok": False, "errors": []}
        figures = dict(figures or {})
        for name in figures:
            if not FIGURE_NAME.fullmatch(name):
                report["errors"].append(f"figure name {name!r} must be qfigN.png (question) or sfigN.png (solution)")
        if report["errors"]:
            return report
        from PIL import Image
        from io import BytesIO
        figure_data = {}
        for name, src in figures.items():
            src = Path(src)
            if not src.is_file():
                report["errors"].append(f"figure file not found: {src}")
                continue
            try:
                with Image.open(src) as im:
                    im.load()
                    if (im.format or "").upper() == "PNG":
                        figure_data[name] = src.read_bytes()  # byte-identical: no recompression
                    else:
                        png = BytesIO()
                        im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(png, "PNG")
                        figure_data[name] = png.getvalue()
            except Exception as exc:
                report["errors"].append(f"figure {name} is not a readable image: {exc}")
                continue
        if report["errors"]:
            return report

        def prepare(tex):
            return normalize_figure_references(normalize_rendering(tex.strip(), number))

        qtex = prepare(question_tex)
        stex = prepare(solution_tex) if solution_tex.strip() != NO_SOLUTION else NO_SOLUTION
        has_solution = stex != NO_SOLUTION and stex.splitlines()[-1:] != ["No worked solution supplied in source."]
        qdir = directory_manager.ensure_question_dir(paper_id, number)
        # Back up the previous transcription before the native savers replace it.
        if (qdir / "question.tex").is_file():
            from uuid import uuid4
            backup = self.path / "revisions" / str(paper_id) / number / uuid4().hex
            shutil.copytree(qdir, backup)
        for old in (qdir / "figures").glob("[qs]fig*.png"):
            if old.name not in figures:
                old.unlink()
        figure_hashes = {}
        for name, data in figure_data.items():
            (qdir / "figures" / name).write_bytes(data)
            figure_hashes[name] = hashlib.sha256(data).hexdigest()
        q = str(tools.submit_question.invoke({"paper_id": paper_id, "question_number": number,
                                              "latex_content": qtex, "qtype": qtype}))
        report["question"] = q
        if q == "saved":
            guard_saved_submission(paper_id, number, "question", qtex)
            s = str(tools.submit_solution.invoke({"paper_id": paper_id, "question_number": number,
                                                  "latex_content": stex}))
            report["solution"] = s
            if s == "saved" and has_solution:
                guard_saved_submission(paper_id, number, "solution", stex)
        else:
            report["solution"] = "not attempted (question not saved)"
        if report["question"] != "saved" or report["solution"] != "saved":
            report["errors"] += [x for x in (report["question"], report["solution"]) if x != "saved"]
        else:
            report["errors"] = validate_item(paper_id, number, has_solution, bool(answer_key))
        report["ok"] = not report["errors"]
        meta = self._meta()
        meta["papers"][str(paper_id)]["questions"][number] = {
            "qtype": qtype, "figures": figure_hashes, "answer_key": answer_key,
            "source_ref": source_ref, "review_note": review_note, "has_solution": has_solution,
            "submitted": self._now(), "ok": report["ok"]}
        self._write_meta(meta)
        return report

    def remove(self, paper_id: int, number: str):
        """Delete one submitted question from the workspace (not the archive)."""
        import database
        import directory_manager
        with database.get_connection() as c:
            c.execute("DELETE FROM questions WHERE paper_id=? AND question_number=?", (paper_id, str(number)))
        shutil.rmtree(directory_manager.get_question_dir(paper_id, str(number)), ignore_errors=True)
        meta = self._meta()
        meta["papers"].get(str(paper_id), {}).get("questions", {}).pop(str(number), None)
        self._write_meta(meta)

    def _require_paper(self, paper_id):
        import database
        if database.get_paper(paper_id) is None:
            raise ValueError(f"paper_id {paper_id} is not in this workspace; call new_paper first")

    # --------------------------------------------------------------- checks
    def check(self, paper_id: int | None = None, require_topics: bool = False) -> list[str]:
        """Every problem that would block a merge (empty list = ready)."""
        import database
        from importer import validate_item
        problems = []
        meta = self._meta()
        with database.get_connection() as c:
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                problems.append("workspace database integrity check failed")
            papers = [r["id"] for r in c.execute("SELECT id FROM papers")] if paper_id is None else [paper_id]
            if not papers:
                problems.append("workspace has no papers")
            for pid in papers:
                rows = c.execute("SELECT id, question_number, qtype, topic_suggestion FROM questions WHERE paper_id=?",
                                 (pid,)).fetchall()
                if not rows:
                    problems.append(f"paper {pid}: no questions submitted")
                info = meta["papers"].get(str(pid), {}).get("questions", {})
                for n, record in info.items():
                    if not record.get("ok"):
                        problems.append(f"paper {pid} Q{n}: last submission did not pass validation; fix and resubmit")
                for r in rows:
                    n = r["question_number"]
                    q = info.get(n, {})
                    if r["qtype"] not in database.QTYPE_VALUES:
                        problems.append(f"paper {pid} Q{n}: bad qtype {r['qtype']!r}")
                    for e in validate_item(pid, n, q.get("has_solution", True), bool(q.get("answer_key"))):
                        problems.append(f"paper {pid} Q{n}: {e}")
                    if require_topics and not (r["topic_suggestion"] or "").strip() and not c.execute(
                            "SELECT 1 FROM question_topics WHERE question_id=?", (r["id"],)).fetchone():
                        problems.append(f"paper {pid} Q{n}: no topic tags (run classify, or merge with allow_untagged)")
        return problems

    # ------------------------------------------------------------- topics
    def classify(self, paper_id: int) -> dict:
        """Optional: tag topics/difficulty with PaperLab's own Node 3 (uses the API key)."""
        import config
        import database
        from run_topics import build_topic_reference, classify_question
        reference, mode = build_topic_reference(), config.topic_primary_mode()
        results = {}
        with database.get_connection() as c:
            numbers = [r[0] for r in c.execute("SELECT question_number FROM questions WHERE paper_id=?", (paper_id,))]
        for n in numbers:
            report = classify_question(paper_id, n, reference, primary_mode=mode)
            results[n] = bool(report.get("ok"))
        return results

    def summary(self) -> dict:
        import database
        out = {"workspace": str(self.path), "papers": []}
        with database.get_connection() as c:
            for p in c.execute("SELECT id, paper_name, source_institute FROM papers ORDER BY id"):
                n = c.execute("SELECT count(*) FROM questions WHERE paper_id=?", (p["id"],)).fetchone()[0]
                tagged = c.execute("SELECT count(DISTINCT q.id) FROM questions q JOIN question_topics t ON t.question_id=q.id"
                                   " WHERE q.paper_id=?", (p["id"],)).fetchone()[0]
                out["papers"].append({"paper_id": p["id"], "name": p["paper_name"], "source": p["source_institute"],
                                      "questions": n, "topic_tagged": tagged})
        return out


# ------------------------------------------------------------------- crop
def crop_figure(source, box, out, grid: bool = False) -> dict:
    """Cut a figure from a source page image: exact pixels, no resampling.

    ``box`` is (x, y, width, height) in pixels, or on the 0-1000 grid of the
    page when ``grid=True``. Returns the saved pixel box plus an edge report:
    which edges cut content and measured 'expand'/'shrink' alternatives
    (in the same unit as the input). Nothing is adjusted automatically.
    """
    for p in (str(REPO), str(IMPORTER)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import math
    from PIL import Image
    from crop_quality import describe, edge_diagnosis, gap_suggestions, to_grid
    if Path(source).resolve() == Path(out).resolve():
        raise ValueError("Crop output must not overwrite its source image")
    with Image.open(source) as im:
        im = im.convert("RGB")
        w, h = im.size
        x, y, bw, bh = (float(v) for v in box)
        if grid:
            px = [math.floor(x * w / 1000), math.floor(y * h / 1000),
                  math.ceil((x + bw) * w / 1000), math.ceil((y + bh) * h / 1000)]
        else:
            px = [int(x), int(y), int(x + bw), int(y + bh)]
        if px[0] < 0 or px[1] < 0 or px[2] > w or px[3] > h or px[2] <= px[0] or px[3] <= px[1]:
            raise ValueError(f"box {box} is outside the {w}x{h} image")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        im.crop(px).save(out, "PNG")
        diagnosis = edge_diagnosis(im, px)
        options = gap_suggestions(im, px)
    fmt = (lambda b: to_grid(b, (w, h))) if grid else (lambda b: [b[0], b[1], b[2] - b[0], b[3] - b[1]])
    return {"saved": str(out), "pixel_box": px, "image_size": [w, h],
            "edges": diagnosis, "advice": describe(diagnosis).strip(),
            "options": {k: fmt(v) for k, v in options.items()}, "clean": not diagnosis}


# --------------------------------------------------------- export / merge
def _bundle_tools():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from paperlab_bundle import build_bundle, merge_bundle
    return build_bundle, merge_bundle


def export(workspace, out, papers=None, require_topics=False) -> dict:
    """Write checked workspace papers to ONE portable PaperLab bundle file.

    The bundle (``.plbundle``) can be copied to any machine and merged there
    with ``python -m paperlab_bundle merge``. Refuses while ``check()``
    reports problems for the selected papers.
    """
    build_bundle, _ = _bundle_tools()
    ws = Workspace.open(workspace)
    problems = (ws.check(require_topics=require_topics) if papers is None else
                [problem for pid in dict.fromkeys(papers) for problem in ws.check(pid, require_topics)])
    if problems:
        raise ValueError("Workspace is not ready to export:\n  " + "\n  ".join(problems[:50]))
    meta = ws._meta()
    ids = papers or [int(k) for k in meta["papers"]]
    extra, sources = {}, {}
    for pid in ids:
        info = meta["papers"].get(str(pid), {})
        questions = info.get("questions", {})
        extra[pid] = {"source_refs": {n: q.get("source_ref", "") for n, q in questions.items()},
                      "reviews": {n: {"reason": q["review_note"]} for n, q in questions.items() if q.get("review_note")},
                      "notes": info.get("notes", "")}
        sources[pid] = [f["file"] for f in info.get("source_files", [])]
    return build_bundle(ws.db, out, ids, producer={"tool": "custom_importer", "workspace": ws.path.name},
                        extra=extra, sources=sources)


def merge(workspace, target_db, target_outputs=None, papers=None, allow_untagged=False, dry_run=False) -> dict:
    """Export a bundle and merge it with the universal PaperLab merger.

    Legacy entry point (kept for scripts): export the workspace to a bundle
    with ``export`` and merge it with ``python -m paperlab_bundle merge``.
    """
    import tempfile
    _, merge_bundle = _bundle_tools()
    ws = Workspace.open(workspace)
    target = Path(target_db).resolve()
    if target == ws.db.resolve() or ws.path in target.parents:
        raise ValueError("Target is inside the workspace; point target_db at the real archive")
    outputs = Path(target_outputs).resolve() if target_outputs else target.parent / "Outputs"
    if outputs == ws.path or outputs.is_relative_to(ws.path) or ws.path.is_relative_to(outputs):
        raise ValueError("Target Outputs overlaps the workspace")
    with tempfile.TemporaryDirectory() as tmp:
        bundle = export(workspace, Path(tmp) / "workspace.plbundle", papers)
        receipt = merge_bundle(bundle["path"], target, target_outputs, dry_run, allow_untagged)
    if not dry_run:
        meta = ws._meta()
        meta["merges"].append(receipt)
        ws._write_meta(meta)
    return receipt
