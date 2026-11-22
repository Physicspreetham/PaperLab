"""Free structural support check: `prepare` Part 1 of every planned book.

No LLM calls. Each book's first part is prepared in a throwaway run under
runs/support-check/ (deleted afterwards unless --keep). Result:
runs/books/support_check.json with ok/error per book.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def check(entry, catalog_cfg, books, scratch):
    run = scratch / entry["slug"]
    run_rel = run.relative_to(ROOT).as_posix()
    cfg = run.parent / f"{entry['slug']}.json"
    cfg.write_text(json.dumps({"source_db": catalog_cfg["source_db"], "asset_root": catalog_cfg["asset_root"],
                               "book_source": entry["source"], "part": 1,
                                "book_plan": str(books / entry["slug"] / "plan.json"),
                               "run_dir": run_rel}), encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "importer.py"), "prepare", "--config", str(cfg)],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    result = {"source": entry["source"], "ok": r.returncode == 0,
              "detail": (r.stdout.strip().splitlines() or [""])[-1] if r.returncode == 0
              else (r.stderr.strip().splitlines() or ["?"])[-1]}
    return result


def main():
    from importer import load_config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=ROOT / "books.json")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    cfg, books = load_config(args.config)
    catalog = json.loads((books / "catalog.json").read_text(encoding="utf-8"))
    planned = [e for e in catalog if e.get("status") == "planned" and e.get("parts")]
    base = (ROOT / "runs").resolve()
    base.mkdir(exist_ok=True)
    if not base.is_relative_to(ROOT):
        parser.error("runs/ must stay inside importer_EJEE")
    scratch = Path(tempfile.mkdtemp(prefix="support-check-", dir=base))
    try:
        with ThreadPoolExecutor(6) as pool:
            results = list(pool.map(lambda e: check(e, cfg, books, scratch), planned))
    finally:
        if args.keep:
            print(f"Staged support checks kept in {scratch}", flush=True)
        else:
            shutil.rmtree(scratch)
    (books / "support_check.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    bad = [r for r in results if not r["ok"]]
    print(f"prepared Part 1 of {len(results) - len(bad)}/{len(results)} books without error", flush=True)
    for r in bad:
        print("FAIL", r["source"], "->", r["detail"], flush=True)
    return int(bool(bad))


if __name__ == "__main__":
    sys.exit(main())
