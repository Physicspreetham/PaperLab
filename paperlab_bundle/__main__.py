"""PaperLab bundle CLI (Windows, macOS, Linux):

    python -m paperlab_bundle inspect FILE.plbundle
    python -m paperlab_bundle merge   FILE.plbundle --target-db physics_archive.db [--dry-run]
    python -m paperlab_bundle build   --db WORKSPACE.db --out FILE.plbundle [--paper ID ...]

Prints JSON. Exit code 0 = success, 1 = refused (nothing changed).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import zipfile

from .bundle import BundleError, build_bundle, inspect_bundle, merge_bundle


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m paperlab_bundle", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inspect")
    i.add_argument("bundle")
    m = sub.add_parser("merge")
    m.add_argument("bundle")
    m.add_argument("--target-db", required=True)
    m.add_argument("--target-outputs", default=None, help="default: <target-db folder>/Outputs")
    m.add_argument("--dry-run", action="store_true")
    m.add_argument("--allow-untagged", action="store_true")
    m.add_argument("--require-reviewed", action="store_true", help="refuse pending holds or stale approvals")
    b = sub.add_parser("build")
    b.add_argument("--db", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--paper", type=int, action="append", default=None)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "inspect":
            out = inspect_bundle(a.bundle)
            out["manifest"] = {k: v for k, v in out["manifest"].items() if k != "files"}
            code = 0 if out["ok"] else 1
        elif a.cmd == "merge":
            out, code = merge_bundle(a.bundle, a.target_db, a.target_outputs, a.dry_run, a.allow_untagged,
                                     reviews="block" if a.require_reviewed else "warn"), 0
        else:
            out = build_bundle(a.db, a.out, a.paper, producer={"tool": "paperlab_bundle build"})
            out, code = {k: v for k, v in out.items() if k != "files"}, 0
    except (BundleError, OSError, sqlite3.Error, zipfile.BadZipFile, ValueError, KeyError, TypeError) as exc:
        out, code = {"ok": False, "error": str(exc)}, 1
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
