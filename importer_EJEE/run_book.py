"""Convert any planned EJEE book, part by part, on demand.

    python run_book.py --book "Hibbeler Dynamics 14e" --parts 1-3
    python run_book.py --book "Hibbeler Dynamics 14e" --parts 2      # resume/retry

Each part runs prepare -> extract -> figures -> pack -> classify -> verify in
runs/books/<book>/part-NNN (isolated; never the archive). Safe to re-run:
finished questions are skipped (not re-billed), failed ones are retried, and
prepared parts are never re-planned. Nothing is merged: after reviewing, use
`importer.py approve` and `importer.py merge` explicitly.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRICE = {"input": 0.10, "cached": 0.002, "output": 0.20}  # USD per million (config.yaml)
# Rupee view of the same bill. Rate dated; override with env USD_INR.
USD_INR = float(os.environ.get("USD_INR", "92.89"))  # 2026-11-22, exchangerate-api.com
GST = 0.18  # Indian GST on imported online services


def parse_parts(text, total):
    parts = set()
    for chunk in text.split(","):
        try:
            bounds = chunk.split("-", 1)
            a, b = int(bounds[0]), int(bounds[-1])
        except ValueError:
            raise SystemExit(f"Invalid part selection {chunk!r}") from None
        if not 1 <= a <= b <= total:
            raise SystemExit(f"Invalid part selection {chunk!r}; expected 1..{total} in ascending order")
        parts.update(range(a, b + 1))
    return sorted(parts)


def phase(name, cfg_path, log):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "importer.py"), name, "--config", str(cfg_path)],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    log.write(f"\n===== {name} (exit {r.returncode})\n{r.stdout}\n{r.stderr}\n")
    log.flush()
    return r.returncode


def cost(run):
    db = run / "paperlab.db"
    if not db.exists():
        return 0.0
    c = sqlite3.connect(db)
    row = c.execute("SELECT sum(input), sum(cache_read), sum(output) FROM token_usage").fetchone()
    c.close()
    inp, cached, out = (v or 0 for v in row)
    return ((inp - cached) * PRICE["input"] + cached * PRICE["cached"] + out * PRICE["output"]) / 1e6


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", required=True, help="exact EJEE resources.source name")
    ap.add_argument("--parts", required=True, help="e.g. 1 or 1-3 or 1,4,7")
    ap.add_argument("--config", type=Path, default=ROOT / "books.json",
                    help="catalog config (default: importer_EJEE/books.json)")
    ap.add_argument("--source-db", type=Path, help="override source DB, relative to the current directory")
    ap.add_argument("--asset-root", type=Path, help="override upload root, relative to the current directory")
    args = ap.parse_args()
    sys.path.insert(0, str(ROOT))
    import book_plan
    from importer import load_config, source_connect
    cfg, out_root = load_config(args.config)
    source_db = str(args.source_db.resolve()) if args.source_db else cfg["source_db"]
    asset_root = str(args.asset_root.resolve()) if args.asset_root else cfg["asset_root"]
    if book_plan.exclusion(args.book):
        raise SystemExit(f"{args.book!r} is excluded: {book_plan.exclusion(args.book)}")
    slug = book_plan.slug(args.book)
    book_dir = out_root / slug
    plan_path = book_dir / "plan.json"
    if not plan_path.exists():
        # Plan just this book (frozen from now on; never renumbered later).
        with closing(source_connect(source_db)) as conn:
            summary = book_plan.plan_book(conn, args.book, asset_root, cfg.get("part_size", 15), book_dir)
        if not summary["ready"]:
            raise SystemExit(f"No importable questions for {args.book!r}: {summary}")
        print(f"Planned {args.book}: {summary['ready']} questions in {summary['parts']} parts "
              f"({summary['blocked']} blocked, listed in plan.json)", flush=True)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    results = []
    for part in parse_parts(args.parts, len(plan["parts"])):
        run = book_dir / f"part-{part:03d}"
        run_rel = run.relative_to(ROOT).as_posix()
        run.mkdir(parents=True, exist_ok=True)
        cfg_path = run.parent / f"part-{part:03d}.json"
        cfg_path.write_text(json.dumps({
            "source_db": source_db, "asset_root": asset_root,
            "book_source": args.book, "part": part, "book_plan": str(plan_path),
            "run_dir": run_rel, "native_figure_cleanup": True}, indent=1), encoding="utf-8")
        with open(run.parent / f"part-{part:03d}.log", "a", encoding="utf-8") as log:
            codes = {}
            if not (run / "manifest.json").exists():
                codes["prepare"] = phase("prepare", cfg_path, log)
                if codes["prepare"]:
                    results.append({"part": part, "codes": codes})
                    continue
            for name in ("extract", "figures", "pack", "classify", "verify"):
                codes[name] = phase(name, cfg_path, log)
                if codes[name] and name in ("extract", "figures", "pack"):
                    break  # resume this stage first; never classify or package a failed extraction
        progress = run / "progress.json"
        q = json.loads(progress.read_text(encoding="utf-8"))["questions"] if progress.is_file() else {}
        held = sorted(f.stem for f in (run / "review_required").glob("*.json")) if (run / "review_required").exists() else []
        usd = cost(run)
        record = {"part": part, "codes": codes, "ok": sum(1 for v in q.values() if v.get("ok")),
                  "questions": len(plan["parts"][part - 1]),
                  "failed": [k for k, v in q.items() if not v.get("ok")], "held_for_review": held,
                  "verified": codes.get("verify") == 0, "usd": round(usd, 4),
                  "inr": round(usd * USD_INR, 2), "inr_with_gst": round(usd * USD_INR * (1 + GST), 2),
                  "usd_inr_rate": USD_INR, "run": str(run)}
        results.append(record)
        print(f"Part {part}: {record['ok']}/{record['questions']} ok, verified={record['verified']}, "
              f"review={held or 'none'}, failed={record['failed'] or 'none'}, ${record['usd']} = Rs {record['inr']} "
              f"(Rs {record['inr_with_gst']} incl. 18% GST)", flush=True)
    (book_dir / "last_run.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0 if all(r.get("verified") for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
