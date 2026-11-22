"""End-to-end custom importer test in an isolated process (no API calls)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

CODE = r'''
import json, sqlite3, sys, tempfile, gc
from pathlib import Path
from PIL import Image, ImageDraw
tmp = Path(tempfile.mkdtemp())
archive = tmp / "archive" / "physics_archive.db"
archive.parent.mkdir()
import os
os.environ["PAPERLAB_ARCHIVE_DB"] = str(archive)
sys.path.insert(0, ".")
from custom_importer import Workspace, merge
# The archive must refuse to be a workspace.
try:
    Workspace.open(archive.parent); raise AssertionError("archive accepted as workspace")
except ValueError:
    pass
ws = Workspace.open(tmp / "ws")
pid = ws.new_paper("Test Book \u2014 Part 1", "Test Book", source_files=[])
assert ws.new_paper("Test Book \u2014 Part 1", "Test Book") == pid          # idempotent, no duplicate
fig = tmp / "diagram.jpg"
im = Image.new("RGB", (200, 120), "white"); ImageDraw.Draw(im).rectangle((20, 20, 180, 100), outline="black", width=3); im.save(fig)
good_q = "A block rests on an incline.\n\n\\includegraphics[width=\\linewidth]{figures/qfig1.png}\n\n\\begin{enumerate}\n\\item 1 N\n\\item 2 N\n\\end{enumerate}"
good_s = ("\\textbf{Answer: 1) B}\n\n\\underline{\\textbf{Solution for 1}}\n\n"
          "Resolve forces: \\begin{equation}a_1 = g\\sin\\theta\\end{equation}")
r = ws.submit(pid, "1", good_q, good_s, "scq", {"qfig1.png": str(fig)}, answer_key="B")
assert r["ok"], r
saved = (tmp / "ws" / "Outputs" / str(pid) / "1" / "solution.tex").read_text(encoding="utf-8")
assert "a_1 = g" in saved, saved                     # subscript survives native save (guard)
assert (tmp / "ws" / "Outputs" / str(pid) / "1" / "figures" / "qfig1.png").is_file()
# Missing Answer line while a key exists -> not ok, reported.
bad = ws.submit(pid, "2", "Find $x$.", "Some working without the answer line.", "num", answer_key="4")
assert not bad["ok"] and bad["errors"], bad
# Wrong figure name -> rejected before saving.
assert not ws.submit(pid, "3", "Q", "no_solution_found", "unknown", {"figure.png": str(fig)})["ok"]
# Question-only item is fine.
assert ws.submit(pid, "3", "Prove that $E = mc^2$.", "no_solution_found", "unknown")["ok"]
problems = ws.check()
assert any("Q2" in p for p in problems), problems   # the bad item blocks merge
try:
    merge(tmp / "ws", archive, allow_untagged=True); raise AssertionError("merged with problems")
except (ValueError, FileNotFoundError):
    pass
ws.remove(pid, "2")
assert ws.check() == [], ws.check()
assert any("no topic tags" in p for p in ws.check(require_topics=True))
import database
database.init_db(str(archive))                      # an existing (empty) archive
plan = merge(tmp / "ws", archive, allow_untagged=True, dry_run=True)
assert plan["dry_run"] and plan["papers"][0]["questions"] == 2
receipt = merge(tmp / "ws", archive, allow_untagged=True)
new_pid = receipt["papers"][0]["archive_paper"]
with sqlite3.connect(archive) as c:
    assert c.execute("select paper_name, source_institute, status from papers where id=?", (new_pid,)).fetchone() == ("Test Book \u2014 Part 1", "Test Book", "done")
    assert c.execute("select count(*) from questions where paper_id=?", (new_pid,)).fetchone()[0] == 2
    folder = Path(c.execute("select latex_folder from questions where paper_id=? and question_number='1'", (new_pid,)).fetchone()[0])
assert (folder / "figures" / "qfig1.png").is_file() and archive.parent.resolve() in folder.parents
assert list(archive.parent.glob("*.pre-bundle-merge-*.bak"))       # backup taken
try:
    merge(tmp / "ws", archive, allow_untagged=True); raise AssertionError("duplicate merge accepted")
except ValueError as exc:
    assert "already has" in str(exc)
# Rollback: a pre-existing target folder makes the merge fail; nothing is left behind.
ws.new_paper("Test Book \u2014 Part 2", "Test Book")
pid2 = [p["paper_id"] for p in ws.summary()["papers"] if p["name"].endswith("Part 2")][0]
assert ws.submit(pid2, "1", "Q two", "no_solution_found", "unknown")["ok"]
with sqlite3.connect(archive) as c:
    next_id = c.execute("select max(id) from papers").fetchone()[0] + 1
blocker = archive.parent / "Outputs" / str(next_id) / "1"
blocker.mkdir(parents=True)
try:
    merge(tmp / "ws", archive, papers=[pid2], allow_untagged=True); raise AssertionError("expected failure")
except ValueError:
    pass
with sqlite3.connect(archive) as c:
    assert c.execute("select count(*) from papers where paper_name like '%Part 2'").fetchone()[0] == 0
gc.collect()
print("custom importer passed")
'''


def test_custom_importer_end_to_end():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    compat = REPO / "importer_EJEE" / "runs" / "benchmark-compat"
    if compat.is_dir():
        env["PYTHONPATH"] = str(compat)
    r = subprocess.run([sys.executable, "-c", CODE], cwd=REPO, env=env, capture_output=True, text=True, timeout=180)
    if "Application Control policy" in r.stderr:
        pytest.skip("Windows policy blocks an optional native dependency")
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert "custom importer passed" in r.stdout
