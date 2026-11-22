"""Local review of isolated run copies in the real PaperLab UI.

Builds runs/pilot-review/ from COPIES of each run (one paper per part, new
IDs), then serves the unchanged upstream backend + built frontend on loopback.
The public reading routes are not authenticated: do not expose this server.

* the server never sees an LLM key: META_API_KEY is forced empty and the
  config is a copy with no .env beside it, so no job can spend money;
* a non-default admin password is required (PAPERLAB_ADMIN_PASSWORD);
* only run copies are served: never the EJEE source DB/uploads, never the
  archive, never the run folders themselves.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent


def build(review, runs):
    if any(run == review.resolve() or run.is_relative_to(review.resolve()) for run in runs):
        raise ValueError("Review output cannot also be a source")
    # The backend binds its paths at import, so build at the final path.
    if review.exists():
        shutil.rmtree(review)
    _build_into(review, runs)
    import database
    database.DB_PATH = review / "paperlab.db"


def _build_into(review, runs):
    (review / "Outputs").mkdir(parents=True)
    (review / "data").mkdir()
    shutil.copy(REPO / "config.yaml", review / "config.yaml")
    db = review / "paperlab.db"
    os.environ.update(PHYSICS_ARCHIVE_DB=str(db), PHYSICS_OUTPUT_BASE=str(review / "Outputs"),
                      DATA_ROOT=str(review / "data"), PIPELINE_CONFIG=str(review / "config.yaml"))
    sys.path.insert(0, str(REPO))
    import database
    database.init_db(db)
    database.init_topics(db)
    dest = sqlite3.connect(db)
    for run in runs:
        src = sqlite3.connect((run / "paperlab.db").resolve().as_uri() + "?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        for paper in src.execute("SELECT * FROM papers"):
            cols = [k for k in paper.keys() if k != "id"]
            vals = [paper[k] for k in cols]
            # The UI lists only finished papers: show every pilot part, but say
            # in its title what still needs review (review copy only).
            import json
            held = [r for r in (json.loads(f.read_text(encoding="utf-8")) for f in (run / "review_required").glob("*.json"))
                    if not r.get("approved")] if (run / "review_required").is_dir() else []
            progress = json.loads((run / "progress.json").read_text(encoding="utf-8"))
            failed = [n for n, r in progress["questions"].items() if not r.get("ok")]
            notes = []
            if failed:
                notes.append(f"{len(failed)} not extracted: Q{', Q'.join(failed)}")
            if held:
                notes.append(f"{sum(len(h.get('figures', {})) or 1 for h in held)} figure(s) held for review")
            # Unique per (book, part): distinct runs are all named part-001.
            tag = f"{run.parent.name}__{run.name}" if run.parent.name != "pilot" else run.name
            # A non-standard run folder (e.g. an A/B re-run of the same part)
            # is labelled so two copies of one part can be told apart.
            variant = "" if re.fullmatch(r"part-\d+", run.name) or run.parent.name == "pilot" else run.name
            for i, k in enumerate(cols):
                if k == "paper_name":
                    if variant:
                        notes.insert(0, f"run {variant}")
                    if notes:
                        vals[i] = f"{vals[i]} [review: {'; '.join(notes)}]"
                if k == "status":
                    vals[i] = "done"
                if k == "pdf_hash" and vals[i]:
                    # Review copy only: re-runs of one part share the source
                    # PDF hash, which the schema requires to be unique.
                    vals[i] = f"review-{tag}-{vals[i]}"
            folder = review / "data" / tag
            if (run / "sources").is_dir():
                shutil.copytree(run / "sources", folder, ignore=shutil.ignore_patterns("inspection"))
                for i, k in enumerate(cols):
                    if k in ("question_pdf_path", "solution_pdf_path") and vals[i]:
                        vals[i] = str(folder / Path(vals[i]).name)
            else:  # custom_importer workspaces have no mapped source PDFs
                for i, k in enumerate(cols):
                    if k in ("question_pdf_path", "solution_pdf_path"):
                        vals[i] = None
            new_pid = dest.execute(f"INSERT INTO papers ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals).lastrowid
            qmap = {}
            for q in src.execute("SELECT * FROM questions WHERE paper_id=?", (paper["id"],)):
                target = review / "Outputs" / str(new_pid) / q["question_number"]
                shutil.copytree(Path(q["latex_folder"]), target)
                qcols = [k for k in q.keys() if k != "id"]
                qvals = [new_pid if k == "paper_id" else str(target) if k == "latex_folder" else q[k] for k in qcols]
                qmap[q["id"]] = dest.execute(f"INSERT INTO questions ({','.join(qcols)}) VALUES ({','.join('?' * len(qcols))})", qvals).lastrowid
            for link in src.execute("SELECT question_id,topic_code,rank,src FROM question_topics"):
                if link["question_id"] in qmap:
                    dest.execute("INSERT INTO question_topics (question_id,topic_code,rank,src) VALUES (?,?,?,?)",
                                 (qmap[link["question_id"]], link["topic_code"], link["rank"], link["src"]))
            for u in src.execute("SELECT phase,input,cache_read,output,reasoning,ts FROM token_usage WHERE paper_id=?", (paper["id"],)):
                dest.execute("INSERT INTO token_usage (paper_id,phase,input,cache_read,output,reasoning,ts) VALUES (?,?,?,?,?,?,?)",
                             (new_pid, *tuple(u)))
            print(f"  {run.name}: paper {new_pid} '{paper['paper_name']}', {len(qmap)} questions", flush=True)
        src.close()
    dest.commit()
    assert dest.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    dest.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", type=int, default=8020)
    p.add_argument("--no-build", action="store_true")
    p.add_argument("--sources", nargs="+", default=None, metavar="DIR",
                   help="run folders or glob patterns (default: newest version of every runs/pilot/* part)")
    args = p.parse_args()
    password = os.environ.get("PAPERLAB_ADMIN_PASSWORD", "")
    if len(password) < 12 or password == "admin":
        raise SystemExit("Set a strong PAPERLAB_ADMIN_PASSWORD (12+ chars) before serving.")
    if not (REPO / "frontend" / "build" / "index.html").is_file():
        raise SystemExit("frontend/build missing: run npm ci && npm run build in frontend/")
    review = ROOT / "runs" / "pilot-review"
    os.environ["META_API_KEY"] = ""  # never loadable: config copy has no .env beside it
    if not args.no_build:
        import glob as _glob
        import re
        if args.sources:
            hits = []
            for pat in args.sources:
                hits += [Path(x) for x in _glob.glob(pat, recursive=True)]
            runs = sorted({d.resolve() for d in hits if d.is_dir() and (d / "paperlab.db").is_file()})
            if not runs:
                raise SystemExit(f"No usable run folders matched: {args.sources}")
        else:
            runs = sorted(d for d in (ROOT / "runs" / "pilot").glob("*")
                          if d.is_dir() and (d / "paperlab.db").is_file())
            # Prefer a re-run (name-v2) over the first attempt of the same part.
            latest = {}
            for d in runs:  # keep only the newest version (-vN) of each part
                base, ver = re.match(r"(.*?)(?:-v(\d+))?$", d.name).groups()
                if base not in latest or int(ver or 1) > latest[base][0]:
                    latest[base] = (int(ver or 1), d)
            runs = sorted(d for _, d in latest.values())
        if not runs:
            p.error("No staged pilots found. Pass --sources with one or more EJEE run folders.")
        if any(not (run / "progress.json").is_file() for run in runs):
            p.error("Each --sources directory must be an EJEE run with a progress.json")
        print(f"Building review copy from {len(runs)} run(s): {[d.name for d in runs]}", flush=True)
        build(review, runs)
    elif not all((review / name).is_file() for name in ("paperlab.db", "config.yaml")):
        p.error("No saved review copy. Start once with --sources before using --no-build.")
    os.environ.update(PHYSICS_ARCHIVE_DB=str(review / "paperlab.db"),
                      PHYSICS_OUTPUT_BASE=str(review / "Outputs"),
                      DATA_ROOT=str(review / "data"),
                      PIPELINE_CONFIG=str(review / "config.yaml"),
                      LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import config
    assert not config.LLM_API_KEY, "LLM key must not be visible to the review server"
    import uvicorn
    print(f"Review UI on http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run("backend.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
