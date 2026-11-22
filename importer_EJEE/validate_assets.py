"""Decode every planned source image and check its body crop (no LLM).

Writes runs/books/asset_validation.json: per-book counts and every failing
resource with a reason. Read-only against the EJEE database and uploads.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
MIN_SIDE = 16  # px: one-line answer solutions ("19°") are legitimately ~38 px tall


def check(args):
    rid, file_name, meta, asset_root = args
    try:
        base = Path(asset_root).resolve()
        path = (base / file_name).resolve()
        if not path.is_relative_to(base):
            return rid, "asset escapes upload root"
        with Image.open(path) as im:
            im.load()
            w, h = im.size
        m = json.loads(meta or "{}")
        box = m.get("box") or m.get("qbox")
        px = [math.floor(box[0] * w), math.floor(box[1] * h), math.ceil(box[2] * w), math.ceil(box[3] * h)]
        if not (0 <= px[0] < px[2] <= w and 0 <= px[1] < px[3] <= h):
            return rid, "body crop outside image"
        bw, bh = px[2] - px[0], px[3] - px[1]
        if bw < MIN_SIDE or bh < MIN_SIDE:
            return rid, f"body crop too small {bw}x{bh}px"
        return rid, None
    except Exception as exc:  # decode/truncation errors are the point
        return rid, f"{type(exc).__name__}: {exc}"


def main():
    from importer import load_config, source_connect
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=ROOT / "books.json")
    args = parser.parse_args()
    cfg, books = load_config(args.config)
    catalog = json.loads((books / "catalog.json").read_text(encoding="utf-8"))
    with closing(source_connect(cfg["source_db"])) as conn:
        return validate(catalog, books, conn, cfg["asset_root"])


def validate(catalog, books, conn, asset_root):
    report, failures = [], []
    for entry in catalog:
        if entry.get("status") != "planned":
            continue
        plan = json.loads((books / entry["slug"] / "plan.json").read_text(encoding="utf-8"))
        ids = [rid for key in (k for p in plan["parts"] for k in p)
               for rid in plan["items"][key]["question_ids"] + plan["items"][key]["solution_ids"]]
        jobs = []
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            q = f"SELECT id,file_name,print_meta FROM resources WHERE id IN ({','.join('?' * len(chunk))})"
            jobs += [(r[0], r[1], r[2], asset_root) for r in conn.execute(q, chunk)]
        with ThreadPoolExecutor(8) as pool:
            bad = [(rid, why) for rid, why in pool.map(check, jobs) if why]
        bad.extend((rid, "resource missing since planning") for rid in sorted(set(ids) - {job[0] for job in jobs}))
        report.append({"source": entry["source"], "slug": entry["slug"], "images": len(jobs), "failed": len(bad)})
        failures += [{"source": entry["source"], "resource_id": rid, "reason": why} for rid, why in bad]
        print(f"{len(jobs):6} images, {len(bad):3} failed | {entry['source'][:60]}", flush=True)
    out = {"books": report, "failures": failures,
           "total_images": sum(r["images"] for r in report), "total_failed": len(failures)}
    (books / "asset_validation.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"TOTAL images {out['total_images']}, failed {out['total_failed']}", flush=True)
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
