"""CLI for the custom importer. Run from the repo root:

    python -m custom_importer <command> --workspace <folder> [...]

Every command prints JSON. Exit code 0 = success, 1 = problems found.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .workspace import Workspace, crop_figure, export, merge


def _items(path):
    text = Path(path).read_text(encoding="utf-8-sig").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    items = [data] if isinstance(data, dict) else data
    if not isinstance(items, list) or not items or not all(isinstance(item, dict) for item in items):
        raise ValueError("Submit a question object, a nonempty array of objects, or JSONL")
    return items


def main(argv=None):
    try:
        return _main(argv)
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


def _main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m custom_importer", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crop", help="cut a figure from a page image (exact pixels, edge report)")
    c.add_argument("--image", required=True)
    c.add_argument("--box", required=True, help="x,y,width,height (pixels, or 0-1000 grid with --grid)")
    c.add_argument("--out", required=True, help="e.g. figs/q1_qfig1.png")
    c.add_argument("--grid", action="store_true")
    for name in ("init", "new-paper", "submit", "remove", "check", "classify", "summary", "export", "merge"):
        p = sub.add_parser(name)
        p.add_argument("--workspace", required=True, help="temp folder, never the archive")
        if name == "new-paper":
            p.add_argument("--name", required=True, help="paper title, e.g. 'Irodov — Part 3'")
            p.add_argument("--source", required=True, help="book / institute, e.g. 'Irodov - Problems in General Physics'")
            p.add_argument("--exam-type", default="Textbook")
            p.add_argument("--date", default=None)
            p.add_argument("--source-file", action="append", default=[], help="original PDF/image (repeatable)")
        if name == "submit":
            p.add_argument("--json", required=True, help="one object, a JSON list, or JSONL of question items")
        if name == "remove":
            p.add_argument("--paper", type=int, required=True)
            p.add_argument("--number", required=True)
        if name in ("check", "classify"):
            p.add_argument("--paper", type=int, default=None)
        if name == "check":
            p.add_argument("--require-topics", action="store_true")
        if name == "export":
            p.add_argument("--out", required=True, help="bundle file to write, e.g. irodov-part3.plbundle")
            p.add_argument("--paper", type=int, action="append", default=None)
            p.add_argument("--require-topics", action="store_true")
        if name == "merge":
            p.add_argument("--target-db", required=True, help="the real physics_archive.db")
            p.add_argument("--target-outputs", default=None, help="default: <target-db folder>/Outputs")
            p.add_argument("--paper", type=int, action="append", default=None)
            p.add_argument("--allow-untagged", action="store_true")
            p.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "crop":
        out = crop_figure(a.image, [float(v) for v in a.box.split(",")], a.out, a.grid)
        print(json.dumps(out, indent=1))
        return 0 if out["clean"] else 1
    if a.cmd == "export":
        out = export(a.workspace, a.out, a.paper, a.require_topics)
        print(json.dumps({k: v for k, v in out.items() if k != "files"}, indent=1, ensure_ascii=False))
        return 0
    if a.cmd == "merge":
        import sys as _sys
        print("NOTE: merge exports a bundle and applies the universal bundle merger", file=_sys.stderr, flush=True)
        out = merge(a.workspace, a.target_db, a.target_outputs, a.paper, a.allow_untagged, a.dry_run)
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return 0
    ws = Workspace.open(a.workspace)
    if a.cmd == "init":
        out, code = ws.summary(), 0
    elif a.cmd == "new-paper":
        pid = ws.new_paper(a.name, a.source, a.exam_type, a.date, a.source_file)
        out, code = {"paper_id": pid}, 0
    elif a.cmd == "submit":
        reports = []
        for item in _items(a.json):
            reports.append(ws.submit(item["paper_id"], item["number"], item["question_tex"],
                                     item["solution_tex"], item.get("qtype", "unknown"),
                                     item.get("figures"), item.get("answer_key"), item.get("source_ref", ""),
                                     item.get("review_note", "")))
        out, code = reports, 0 if all(r["ok"] for r in reports) else 1
    elif a.cmd == "remove":
        ws.remove(a.paper, a.number)
        out, code = {"removed": [a.paper, a.number]}, 0
    elif a.cmd == "check":
        problems = ws.check(a.paper, a.require_topics)
        out, code = {"ready": not problems, "problems": problems}, 0 if not problems else 1
    elif a.cmd == "classify":
        papers = [a.paper] if a.paper else [p["paper_id"] for p in ws.summary()["papers"]]
        out = {str(p): ws.classify(p) for p in papers}
        code = 0 if all(all(v.values()) for v in out.values()) else 1
    else:
        out, code = ws.summary(), 0
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
