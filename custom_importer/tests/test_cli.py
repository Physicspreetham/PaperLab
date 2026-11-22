"""Drive the documented CLI exactly as an agent would (no API calls)."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[2]


def run(args, env, ok=(0,)):
    r = subprocess.run([sys.executable, "-m", "custom_importer", *args], cwd=REPO, env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    if "Application Control policy" in r.stderr:
        pytest.skip("Windows policy blocks an optional native dependency")
    assert r.returncode in ok, r.stdout + r.stderr
    return json.loads(r.stdout), r.returncode


def test_documented_cli_flow(tmp_path):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    compat = REPO / "importer_EJEE" / "runs" / "benchmark-compat"
    if compat.is_dir():
        env["PYTHONPATH"] = str(compat)
    archive = tmp_path / "archive" / "physics_archive.db"
    archive.parent.mkdir()
    env["PAPERLAB_ARCHIVE_DB"] = str(archive)
    page = tmp_path / "page.png"
    im = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((100, 100, 200, 200), outline="black", width=2)
    d.line((100, 60, 300, 60), fill="black", width=3)
    im.save(page)
    cut, code = run(["crop", "--image", str(page), "--box", "90,90,60,120", "--out", str(tmp_path / "f.png")], env, ok=(1,))
    assert not cut["clean"] and "right" in cut["edges"] and "expand" in cut["options"]
    fixed, code = run(["crop", "--image", str(page), "--box", ",".join(map(str, cut["options"]["expand"])),
                       "--out", str(tmp_path / "f.png")], env)
    assert fixed["clean"] and code == 0
    ws = str(tmp_path / "ws")
    pid = run(["new-paper", "--workspace", ws, "--name", "Demo Book — Part 1", "--source", "Demo Book"], env)[0]["paper_id"]
    items = tmp_path / "items.jsonl"
    items.write_text("\n".join(json.dumps(x) for x in [
        {"paper_id": pid, "number": "1", "qtype": "num", "answer_key": "2",
         "question_tex": "Find $x$ in the figure.\n\n\\includegraphics[width=\\linewidth]{figures/qfig1.png}",
         "solution_tex": "\\textbf{Answer: 1) 2}\n\n\\underline{\\textbf{Solution for 1}}\n\n$x = 2$.",
         "figures": {"qfig1.png": str(tmp_path / "f.png")},
         "source_ref": "Exercise 4 · Q17", "review_note": "Diagram label clipped in source"},
        {"paper_id": pid, "number": "2", "qtype": "unknown",
         "question_tex": "Prove the identity.", "solution_tex": "no_solution_found"},
    ]), encoding="utf-8")
    reports, code = run(["submit", "--workspace", ws, "--json", str(items)], env)
    assert code == 0 and all(r["ok"] for r in reports)
    assert run(["check", "--workspace", ws], env)[0]["ready"]
    bundle = tmp_path / "part.plbundle"
    manifest, _ = run(["export", "--workspace", ws, "--out", str(bundle)], env)
    assert manifest["papers"][0]["source_refs"]["1"] == "Exercise 4 · Q17"
    assert manifest["papers"][0]["review_pending"][0]["reason"] == "Diagram label clipped in source"
    sqlite3.connect(archive).close()           # an empty, non-PaperLab file is refused
    r = subprocess.run([sys.executable, "-m", "custom_importer", "merge", "--workspace", ws, "--target-db",
                        str(archive), "--allow-untagged", "--dry-run"], cwd=REPO, env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode != 0 and "not a PaperLab archive" in json.loads(r.stdout)["error"]
    subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, '.'); import database; database.init_db(r'{archive}')"],
                   cwd=REPO, env=env, check=True, timeout=120)
    out, _ = run(["merge", "--workspace", ws, "--target-db", str(archive), "--allow-untagged", "--dry-run"], env)
    assert out["dry_run"] and out["papers"][0]["questions"] == 2
