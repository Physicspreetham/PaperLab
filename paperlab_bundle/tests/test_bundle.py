"""Universal bundle: portability, tamper/traversal safety and merge guarantees."""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

REPO = Path(__file__).resolve().parents[2]

CODE = r'''
import hashlib, json, shutil, sqlite3, sys, tempfile, zipfile, gc
from pathlib import Path
sys.path.insert(0, ".")

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
import database
from paperlab_bundle import BundleError, build_bundle, inspect_bundle, merge_bundle
tmp = Path(tempfile.mkdtemp())

def make_src(name, topic=True, figure=True):
    """A tiny PaperLab-schema workspace with absolute latex folders (like real runs)."""
    root = tmp / name; root.mkdir()
    db = root / "paperlab.db"; database.init_db(str(db)); database.init_topics(str(db))
    c = sqlite3.connect(db)
    c.execute("INSERT INTO papers (paper_name, exam_type, source_institute, pdf_hash, status) VALUES (?,?,?,?,?)",
              (f"{name} \u2014 Part 1", "Textbook", name, f"custom|{name}", "done"))
    code = c.execute("SELECT code FROM topics WHERE level NOT IN ('subject','chapter') LIMIT 1").fetchone()[0]
    for n in ("1", "2"):
        q = root / "Outputs" / "1" / n; (q / "figures").mkdir(parents=True)
        ref = "\n\n\\includegraphics[width=\\linewidth]{figures/qfig1.png}" if figure else ""
        (q / "question.tex").write_text(f"Question {n} $v_0$ = 2 m/s.{ref}", encoding="utf-8")
        (q / "solution.tex").write_text(f"\\textbf{{Answer: {n}) 2}}\n\n\\underline{{\\textbf{{Solution for {n}}}}}\n\nWorking.", encoding="utf-8")
        if figure: (q / "figures" / "qfig1.png").write_bytes(b"\x89PNG fake " + n.encode())
        (q / "figures" / "_import_provenance.json").write_text("{}")      # local sidecar: must not travel
        c.execute("INSERT INTO questions (paper_id, question_number, latex_folder, qtype) VALUES (1,?,?, 'num')", (n, str(q)))
        if topic:
            c.execute("INSERT INTO question_topics (question_id, topic_code, rank, src) VALUES (?,?,0,'auto')",
                      (c.execute("select last_insert_rowid()").fetchone()[0], code))
    c.execute("INSERT INTO token_usage (paper_id, phase, input, cache_read, output, reasoning) VALUES (1,'extractor',100,10,20,0)")
    c.commit(); c.close()
    pdf = root / "questions.pdf"; pdf.write_bytes(b"%PDF-1.4 fake")
    return db, pdf

db, pdf = make_src("Book A")
b = build_bundle(db, tmp / "a", producer={"tool": "test"}, sources={1: [pdf]})["path"]
path = Path(b); assert path.suffix == ".plbundle" and path.is_file()
names = zipfile.ZipFile(path).namelist()
assert all("\\" not in n and not n.startswith("/") and ":" not in n for n in names), names
assert not any("_import_provenance" in n for n in names)               # sidecars stay local
assert "sources/1/questions.pdf" in names
inner = sqlite3.connect(":memory:")
with zipfile.ZipFile(path) as z: Path(tmp / "peek.db").write_bytes(z.read("paperlab.db"))
peek = sqlite3.connect(tmp / "peek.db")
assert {r[0] for r in peek.execute("select latex_folder from questions")} == {"Outputs/1/1", "Outputs/1/2"}
assert peek.execute("select question_pdf_path from papers").fetchone()[0] == "sources/1/questions.pdf"
peek.close()
assert inspect_bundle(path)["ok"]

# Tampering: change one byte of a figure -> checksum refusal.
bad = tmp / "tampered.plbundle"
with zipfile.ZipFile(path) as zin, zipfile.ZipFile(bad, "w") as zout:
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename.endswith("qfig1.png"): data = data + b"x"
        zout.writestr(item, data)
try: inspect_bundle(bad); raise AssertionError("tampered bundle accepted")
except BundleError as e: assert "checksum" in str(e)

# Path traversal / Windows paths are refused before anything is written.
for evil in ("../escape.txt", "Outputs\\1\\x.tex", "C:/x.tex", "/abs.tex"):
    ev = tmp / "evil.plbundle"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(ev, "w") as zout:
        for item in zin.infolist(): zout.writestr(item, zin.read(item.filename))
        zout.writestr(evil, "x")
    try: inspect_bundle(ev); raise AssertionError(f"accepted {evil}")
    except BundleError: pass
    assert not (tmp / "escape.txt").exists()

# Merge into a real (fresh) archive.
arch = tmp / "server" / "physics_archive.db"; arch.parent.mkdir(); database.init_db(str(arch)); database.init_topics(str(arch))
empty = tmp / "notarchive.db"; conn = sqlite3.connect(empty); conn.close(); del conn; gc.collect()
size = empty.stat().st_size
unclosed = sqlite3.connect(empty)
try: merge_bundle(path, empty); raise AssertionError("merged into a non-archive")
except BundleError as e: assert "not a PaperLab archive" in str(e)
except AssertionError: raise
except Exception as e: assert False, f"merging into a non-archive must refuse cleanly, got {type(e).__name__}: {e}"
finally: unclosed.close(); del unclosed; gc.collect()
assert empty.stat().st_size == size
gc.collect()
before = arch.stat().st_mtime_ns, _sha(arch)
dry = merge_bundle(path, arch, dry_run=True)
assert dry["dry_run"] and dry["mergeable"] and dry["papers"][0]["questions"] == 2
gc.collect()
assert (arch.stat().st_mtime_ns, _sha(arch)) == before, "dry run changed the archive"
assert not list(arch.parent.glob("*.pre-bundle-merge-*.bak")) and not (arch.parent / "physics_archive.bundle-merges.jsonl").exists()
r = merge_bundle(path, arch)
pid = r["papers"][0]["archive_paper"]
a = sqlite3.connect(arch)
row = a.execute("select paper_name, status, question_pdf_path from papers where id=?", (pid,)).fetchone()
assert row[0] == "Book A \u2014 Part 1" and row[1] == "done" and Path(row[2]).is_file()
folders = [Path(f) for (f,) in a.execute("select latex_folder from questions where paper_id=?", (pid,))]
assert len(folders) == 2 and all(f.is_absolute() and (f / "figures" / "qfig1.png").is_file() for f in folders)
assert a.execute("select count(*) from question_topics qt join questions q on q.id=qt.question_id where q.paper_id=?", (pid,)).fetchone()[0] == 2
assert a.execute("select count(*) from token_usage where paper_id=?", (pid,)).fetchone()[0] == 1
a.close()
assert list(arch.parent.glob("*.pre-bundle-merge-*.bak")) and (arch.parent / "physics_archive.bundle-merges.jsonl").is_file()
try: merge_bundle(path, arch); raise AssertionError("duplicate merged")
except BundleError as e: assert "already has" in str(e)

# Untagged questions need an explicit opt-in.
db2, _ = make_src("Book B", topic=False, figure=False)
b2 = build_bundle(db2, tmp / "b")["path"]
try: merge_bundle(b2, arch); raise AssertionError("untagged merged")
except BundleError as e: assert "no topic tags" in str(e)
assert merge_bundle(b2, arch, allow_untagged=True)["papers"][0]["questions"] == 2

# Unapproved review items travel in the manifest as warnings, not blocks.
db3, _ = make_src("Book C")
b3 = build_bundle(db3, tmp / "c",
    extra={1: {"reviews": {"2": {"reason": "Q2 qfig1.png edge cuts content"}}}})["path"]
r3 = merge_bundle(str(b3), str(arch))
assert any("need human review" in w for w in r3["warnings"]), r3
try:
    merge_bundle(str(b3), str(arch), reviews="block")
    raise AssertionError("review-pending merged under reviews=block")
except BundleError as e:
    assert "need human review" in str(e), f"wrong refusal: {e}"

# Unknown topic code (syllabus mismatch) is refused, not silently dropped.
db4, _ = make_src("Book D")
c = sqlite3.connect(db4); c.execute("update question_topics set topic_code='ZZ99.99'"); c.commit(); c.close()
b4 = build_bundle(db4, str(tmp / "d.plbundle"))["path"]
try: merge_bundle(str(b4), str(arch)); raise AssertionError("unknown topic merged")
except BundleError as e: assert "ZZ99.99" in str(e)

# Review gate: unapproved holds travel in one manifest; approvals lift their warnings.
got0 = inspect_bundle(str(b))
assert got0["ok"] is True and not got0["warnings"], (got0["problems"], got0["warnings"])
db6, pdf6 = make_src("Book F")
import hashlib as _hashlib
q1dir = tmp / "Book F" / "Outputs" / "1" / "1"
h1 = _hashlib.sha256((q1dir / "question.tex").read_bytes()).hexdigest()
h2 = _hashlib.sha256((q1dir / "solution.tex").read_bytes()).hexdigest()
assert h1 and h2 and q1dir.is_dir()
reviews = {
    "1": {"approved": True, "approval": {"by": "rev", "at": "t", "note": "eyes on",
                                         "hashes": {"question.tex": h1, "solution.tex": h2}}},
    "2": {"reason": "edge cuts content, needs human"},
}
assert set(reviews) == {"1", "2"} and len(h1) == 64 and len(h2) == 64
bf = build_bundle(db6, str(tmp / "f.plbundle"), extra={1: {"reviews": reviews}})["path"]
assert isinstance(bf, str) and bf.endswith(".plbundle"), (type(bf), repr(bf)[:200])
got = inspect_bundle(bf)
assert [p["question"] for p in got["manifest"]["papers"][0].get("review_pending", [])] == ["2"]
assert got["ok"] is True and any("need human review" in w for w in got["warnings"]), (got["problems"], got["warnings"])
strict_target = tmp / "strict" / "archive.db"
for dry in (True, False):
    try:
        merge_bundle(bf, strict_target, dry_run=dry, reviews="block")
        raise AssertionError("strict review ignored")
    except BundleError as e:
        assert "need human review" in str(e)
    assert not strict_target.parent.exists()
try:
    merge_bundle(bf, arch, reviews="block")
    raise AssertionError("review-pending merged under reviews=block")
except BundleError as e:
    assert "need human review" in str(e)
# Change an approved file after review -> approval goes stale, flagged in warnings.
(tmp / "Book F" / "Outputs" / "1" / "1" / "question.tex").write_text("Question 1 changed $v_0$.", encoding="utf-8")
assert any("stale" in w for w in inspect_bundle(build_bundle(db6, str(tmp / "f2.plbundle"), extra={1: {"reviews": reviews}})["path"])["warnings"])
try:
    merge_bundle(str(tmp / "f2.plbundle"), arch, reviews="block")
    raise AssertionError("stale approval merged under reviews=block")
except BundleError as e:
    assert "stale" in str(e)
# producer_chain accumulates across export passes over the same file.
chain0 = inspect_bundle(str(tmp / "a.plbundle"))["manifest"].get("producer_chain", [])
build_bundle(db, str(tmp / "a.plbundle"), producer={"tool": "test", "stage": "merge-check"})
chain1 = inspect_bundle(str(tmp / "a.plbundle"))["manifest"]["producer_chain"]
assert len(chain1) == len(chain0) + 1 and chain1[-1]["stage"] == "merge-check"
# Rollback: an existing target folder fails the merge and leaves nothing behind.
db5, _ = make_src("Book E")
a = sqlite3.connect(arch); next_id = a.execute("select max(id) from papers").fetchone()[0] + 1; a.close()
(arch.parent / "Outputs" / str(next_id)).mkdir(parents=True)
for dry in (True, False):
    try: merge_bundle(build_bundle(db5, tmp / "e")["path"], arch, dry_run=dry); raise AssertionError("expected failure")
    except BundleError as e: assert "folder already exists" in str(e)
a = sqlite3.connect(arch)
assert a.execute("select count(*) from papers where paper_name like 'Book E%'").fetchone()[0] == 0
a.close(); gc.collect()

# Dry-run must see the committed WAL, not only the main database.
wal_target = tmp / "WAL & #snapshot.db"
database.init_db(wal_target)
database.init_topics(wal_target)
wal = sqlite3.connect(wal_target)
wal.execute("PRAGMA wal_autocheckpoint=0")
wal.execute("INSERT INTO papers(paper_name,source_institute,pdf_hash) VALUES ('Book A — Part 1','Book A','custom|Book A')")
wal.commit()
wal_file = Path(str(wal_target) + "-wal")
before = tuple(_sha(p) for p in (wal_target, wal_file))
try:
    merge_bundle(path, wal_target, dry_run=True)
    raise AssertionError("dry-run missed a duplicate in the WAL")
except BundleError as e:
    assert "already has" in str(e), e
assert before == tuple(_sha(p) for p in (wal_target, wal_file))
wal.close()

# Media-copy failure partway through must clean both the DB and partial files.
db7, _ = make_src("Book G")
archive7 = tmp / "copy-failure" / "archive.db"
database.init_db(archive7)
database.init_topics(archive7)
b7 = build_bundle(db7, tmp / "g")["path"]
copytree = shutil.copytree
def broken_copy(src, dst, *args, **kwargs):
    Path(dst).mkdir(parents=True)
    (Path(dst) / "partial").touch()
    raise OSError("simulated disk failure")
try:
    shutil.copytree = broken_copy
    try: merge_bundle(b7, archive7); raise AssertionError("partial copy committed")
    except OSError as e: assert "simulated disk failure" in str(e)
finally:
    shutil.copytree = copytree
assert not list((archive7.parent / "Outputs").iterdir())
c = sqlite3.connect(archive7)
assert not c.execute("SELECT * FROM papers").fetchall()
c.close()
print("bundle passed")
'''


def test_bundle_end_to_end():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    compat = REPO / "importer_EJEE" / "runs" / "benchmark-compat"
    if compat.is_dir():
        env["PYTHONPATH"] = str(compat)
    r = subprocess.run([sys.executable, "-c", CODE], cwd=REPO, env=env, capture_output=True, text=True, timeout=180)
    if "Application Control policy" in r.stderr:
        pytest.skip("Windows policy blocks an optional native dependency")
    assert r.returncode == 0, f"rc={r.returncode} STDOUT:\n" + r.stdout + "\nSTDERR:\n" + r.stderr
    assert "bundle passed" in r.stdout
