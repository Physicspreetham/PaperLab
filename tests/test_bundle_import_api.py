"""Exercise the public upload contract with real, isolated bundles and archives."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from threading import Event
import zipfile

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from backend import deps
from backend.main import _FrontendFiles, app
from backend.routers import bundles
import database
import directory_manager
from paperlab_bundle import build_bundle, merge_bundle
from paperlab_bundle.publication import Publication


URL = "/api/bundles/import"
MIME = {"Content-Type": "application/octet-stream"}
PASSWORD = "strong archive password ü"


@pytest.fixture
def archive(tmp_path, monkeypatch):
    db = tmp_path / "archive & review.db"
    outputs = tmp_path / "configured-media"
    database.init_db(db)
    database.init_topics(db)
    monkeypatch.setattr(database, "DB_PATH", db)
    monkeypatch.setattr(directory_manager, "OUTPUT_BASE", outputs)
    monkeypatch.setattr(directory_manager, "DATA_ROOT", tmp_path / "archive-data")
    monkeypatch.setenv("PHYSICS_OUTPUT_BASE", str(outputs))
    monkeypatch.setenv("PAPERLAB_ADMIN_PASSWORD", PASSWORD)
    return db, outputs


def bundle_file(root, *, tagged=True, extra=None, question=None, invalid_media=False, second_paper=None):
    root.mkdir()
    stage = root / "workspace.db"
    database.init_db(stage)
    database.init_topics(stage)
    qdir = root / "Outputs" / "1" / "1"
    figures = qdir / "figures"
    figures.mkdir(parents=True)
    Image.new("RGB", (12, 12), color="red").save(figures / "qfig1.png")
    if invalid_media:
        (figures / "qfig1.png").write_bytes(b"not a PNG")
    (qdir / "question.tex").write_text(
        question or "Find $v_0$.\n\n" + r"\includegraphics{figures/qfig1.png}", encoding="utf-8")
    (qdir / "solution.tex").write_text(r"\textbf{Answer: 1) 2}", encoding="utf-8")
    with closing(sqlite3.connect(stage)) as c, c:
        c.execute("INSERT INTO papers (paper_name, source_institute, pdf_hash, status) "
                  "VALUES ('Mechanics — Part 1', 'Mechanics', 'test-paper', 'done')")
        c.execute("INSERT INTO questions (paper_id, question_number, latex_folder, status, qtype, difficulty) "
                  "VALUES (1, '1', ?, 'done', 'num', 'Medium')", (str(qdir),))
        if tagged:
            code = c.execute("SELECT code FROM topics WHERE level='subtopic' LIMIT 1").fetchone()[0]
            c.execute("INSERT INTO question_topics (question_id, topic_code, rank, src) "
                      "VALUES (1, ?, 0, 'human')", (code,))
        if second_paper:
            c.execute("INSERT INTO papers (paper_name,source_institute,pdf_hash,status) VALUES (?,?,?,'done')",
                      (second_paper, "Mechanics", "second-test-paper"))
            c.execute("INSERT INTO questions (paper_id,question_number,latex_folder,qtype) VALUES (2,'1',?,'num')",
                      (str(qdir),))
            if tagged:
                c.execute("INSERT INTO question_topics (question_id,topic_code,rank,src) VALUES (2,?,0,'human')", (code,))
    return Path(build_bundle(stage, root / "part.plbundle", extra=extra)["path"])


def login(client, password=PASSWORD):
    response = client.post("/api/auth/login", json={"password": password})
    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    if client.base_url.scheme == "https":
        assert "Secure" in cookie


def post(client, bundle, query="", **kwargs):
    with bundle.open("rb") as f:
        return client.post(URL + query, content=f, headers=kwargs.pop("headers", MIME), **kwargs)


def counts(db):
    with closing(sqlite3.connect(db)) as c:
        return tuple(c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                     for table in ("papers", "questions", "question_topics"))


def replace_bundle(original, output, update):
    with zipfile.ZipFile(original) as z:
        files = {name: z.read(name) for name in z.namelist()}
    manifest = json.loads(files.pop("bundle.json"))
    update(manifest, files)
    manifest["files"] = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("bundle.json", json.dumps(manifest, ensure_ascii=True))
        for name, data in files.items():
            z.writestr(name, data)
    return output


def test_archivist_preview_publish_and_duplicate(archive, tmp_path):
    db, outputs = archive
    bundle = bundle_file(tmp_path / "fixture")
    with TestClient(app, base_url="https://paperlab.test") as client:
        assert post(client, bundle, "?dry_run=false").status_code == 401
        assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        login(client)
        preview = post(client, bundle, headers={**MIME, "Origin": "https://paperlab.test"})
        assert preview.status_code == 200, preview.text
        assert preview.json() == {"dry_run": True, "mergeable": True, "papers": [
            {"name": "Mechanics — Part 1", "questions": 1}]}
        assert counts(db) == (0, 0, 0) and not outputs.exists()
        assert not list(db.parent.glob("*.bak"))

        published = post(client, bundle, "?dry_run=false")
        assert published.status_code == 201, published.text
        receipt = published.json()
        pid = receipt["papers"][0]["archive_paper"]
        backup_name = receipt["backup"]
        assert Path(backup_name).name == backup_name
        assert str(tmp_path) not in published.text and published.headers["cache-control"] == "no-store"
        assert counts(db.parent / backup_name) == (0, 0, 0)
        assert counts(db) == (1, 1, 1)
        qdir = outputs / str(pid) / "1"
        assert "$v_0$" in (qdir / "question.tex").read_text(encoding="utf-8")
        assert client.get(f"/api/papers/{pid}/questions/1/figures/qfig1.png").status_code == 200
        assert client.get(f"/api/papers/{pid}").json()["status"] == "done"
        with closing(sqlite3.connect(db)) as c:
            assert c.execute("SELECT src, rank FROM question_topics").fetchone() == ("human", 0)
            assert c.execute("SELECT difficulty FROM questions").fetchone() == ("Medium",)
        assert receipt["already_imported"] is False
        retry = post(client, bundle, "?dry_run=false")
        assert retry.status_code == 200 and retry.json() == {**receipt, "already_imported": True}
        repacked = replace_bundle(bundle, tmp_path / "repacked.plbundle", lambda m, _: m.update(created="another date"))
        assert post(client, repacked, "?dry_run=false").status_code == 409
        assert not (outputs / ".bundle-pending").exists()
        assert len(list(db.parent.glob("*.bak"))) == 1
        assert counts(db) == (1, 1, 1)
        assert client.post("/api/auth/logout").status_code == 204
        assert post(client, bundle).status_code == 401
    # A new server session reads the original receipt from the archive.
    with TestClient(app, base_url="https://paperlab.test") as client:
        login(client)
        assert post(client, bundle, "?dry_run=false").json()["papers"] == receipt["papers"]


def test_transport_content_type_and_default_password_before_upload(archive, monkeypatch):
    with TestClient(app, base_url="http://paperlab.test") as external:
        login(external)
        assert external.post(URL, content=b"x", headers=MIME).status_code == 403
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 1234)) as local:
        login(local)
        assert local.post(URL, content=b"x", headers={**MIME, "Origin": "https://elsewhere.test"}).status_code == 403
        assert local.post(URL, json={"bundle": "wrong"}).status_code == 415
        assert local.post(URL, content=b"x", headers={**MIME, "Content-Encoding": "gzip"}).status_code == 415
        assert local.post(URL, content=b"", headers=MIME).status_code == 400
        assert local.post(URL, content=b"not a bundle", headers=MIME).status_code == 422
        monkeypatch.setenv("PAPERLAB_ADMIN_PASSWORD", "admin")
        assert local.post(URL, content=b"x", headers=MIME).status_code == 503


def test_stream_and_zip_limits_and_busy_slot(archive, tmp_path, monkeypatch):
    db, outputs = archive
    bundle = bundle_file(tmp_path / "fixture")
    with TestClient(app, base_url="https://paperlab.test") as client:
        login(client)
        with monkeypatch.context() as m:
            m.setattr(bundles, "MAX_BODY", 4)
            assert client.post(URL, content=b"12345", headers=MIME).status_code == 413
            assert client.post(URL, content=iter([b"123", b"45"]), headers=MIME).status_code == 413
        with monkeypatch.context() as m:
            m.setattr(bundles, "BUNDLE_LIMITS", replace(bundles.BUNDLE_LIMITS, expanded_bytes=32))
            assert post(client, bundle, "?dry_run=false").status_code == 413
        with monkeypatch.context() as m:
            m.setattr(bundles, "BUNDLE_LIMITS", replace(bundles.BUNDLE_LIMITS, members=2))
            assert post(client, bundle, "?dry_run=false").status_code == 413
        assert bundles._slot.acquire(blocking=False)
        try:
            busy = post(client, bundle)
            assert busy.status_code == 429 and busy.headers.get("Retry-After")
        finally:
            bundles._slot.release()
        assert counts(db) == (0, 0, 0) and not outputs.exists()
        assert post(client, bundle).status_code == 200


def test_review_gate_untagged_traversal_and_incompatible_media(archive, tmp_path):
    db, outputs = archive
    review = bundle_file(tmp_path / "review", extra={1: {"reviews": {"1": {"reason": "check diagram"}}}})
    no_tags = bundle_file(tmp_path / "no-tags", tagged=False)
    bad_tex = bundle_file(tmp_path / "bad-tex", question=r"Find $x$.\includegraphics{../other.png}")
    bad_fig = bundle_file(tmp_path / "bad-fig", invalid_media=True)
    illegal = io.BytesIO()
    with zipfile.ZipFile(illegal, "w") as z:
        z.writestr("../bad.tex", "no")
    with TestClient(app, base_url="https://paperlab.test") as client:
        login(client)
        assert post(client, review).status_code == 422
        assert "human review" in post(client, review, "?dry_run=false").text
        assert post(client, no_tags, "?dry_run=false").status_code == 422
        assert post(client, bad_tex, "?dry_run=false").status_code == 422
        assert "media does not match" in post(client, bad_fig, "?dry_run=false").text
        assert client.post(URL + "?dry_run=false", content=illegal.getvalue(), headers=MIME).status_code == 422
        assert counts(db) == (0, 0, 0) and not outputs.exists()
        assert post(client, no_tags, "?dry_run=false&allow_untagged=true").status_code == 201
        assert counts(db) == (1, 1, 0)


def test_session_expires_on_the_server(archive, monkeypatch):
    time = [1.0]
    monkeypatch.setattr(deps, "monotonic", lambda: time[0])
    with TestClient(app, base_url="https://paperlab.test") as client:
        login(client)
        assert client.get("/api/auth/me").json()["authed"]
        time[0] += deps.SESSION_MAX_AGE
        assert not client.get("/api/auth/me").json()["authed"]


def test_preview_and_publish_reject_invalid_metadata_and_inside_duplicates(archive, tmp_path):
    db, outputs = archive
    bundle = bundle_file(tmp_path / "plain")

    def bad_db(_, files):
        path = tmp_path / "mutated.db"
        path.write_bytes(files["paperlab.db"])
        with closing(sqlite3.connect(path)) as c, c:
            c.execute("UPDATE papers SET source_institute=?", (b"opaque bytes",))
        files["paperlab.db"] = path.read_bytes()

    variants = [
        (replace_bundle(bundle, tmp_path / "blob.plbundle", bad_db), "source_institute", 422),
        (replace_bundle(bundle, tmp_path / "mismatch.plbundle", lambda m, _: m["papers"][0].update(name="Other")),
         "does not match", 422),
        (replace_bundle(bundle, tmp_path / "receipt.plbundle", lambda m, _: m.update(producer={"note": "\ud800"})),
         "UTF-8 JSON", 422),
        (bundle_file(tmp_path / "same-title", second_paper="Mechanics — Part 1"), "duplicate papers", 409),
        (bundle_file(tmp_path / "raw-tex", question="Find value_name."), "unescaped text underscores", 422),
        (bundle_file(tmp_path / "starred", question=r"\includegraphics*{figures/qfig1.png}"),
         "Unsupported figure command", 422),
    ]
    with TestClient(app, base_url="https://paperlab.test") as client:
        login(client)
        for item, error, code in variants:
            for query in ("", "?dry_run=false"):
                result = post(client, item, query)
                assert result.status_code == code and error in result.text, result.text
    assert counts(db) == (0, 0, 0) and not outputs.exists()
    assert not list(db.parent.glob("*.bak"))


def test_approval_is_bound_to_all_files_and_its_own_question(archive, tmp_path):
    bundle = bundle_file(tmp_path / "fixture", extra={1: {"reviews": {"1": {"reason": "edge"}}}})

    def approve(manifest, files):
        prefix = "Outputs/1/1/"
        hashes = {n[len(prefix):]: hashlib.sha256(v).hexdigest() for n, v in files.items() if n.startswith(prefix)}
        manifest["approvals"]["1:1"] = {"paper": 1, "question": "1", "hashes": hashes,
                                        "by": "reviewer", "at": "now", "note": "compared"}

    cleared = replace_bundle(bundle, tmp_path / "cleared.plbundle", approve)
    added = replace_bundle(cleared, tmp_path / "added.plbundle",
                           lambda _, f: f.update({"Outputs/1/1/figures/qfig2.png": f["Outputs/1/1/figures/qfig1.png"]}))
    other = replace_bundle(cleared, tmp_path / "other.plbundle", lambda m, _: m["approvals"]["1:1"].update(question="2"))
    with TestClient(app, base_url="https://paperlab.test") as client:
        login(client)
        assert post(client, added, "?dry_run=false").status_code == 422
        assert post(client, other, "?dry_run=false").status_code == 422
        assert post(client, cleared).status_code == 200
        assert post(client, cleared, "?dry_run=false").status_code == 201


def test_two_paper_publish_is_hidden_until_commit_and_rolls_back(archive, tmp_path, monkeypatch):
    db, outputs = archive
    bundle = bundle_file(tmp_path / "pair", second_paper="Mechanics — Part 2")
    installed, release = Event(), Event()
    real_install = Publication.install

    def install_then_fail(self, digest, ids):
        real_install(self, digest, ids)
        installed.set()
        if not release.wait(timeout=10):
            raise OSError("test timed out")
        raise OSError("second-paper publication failure")

    with TestClient(app, base_url="https://paperlab.test") as client:
        login(client)
        with monkeypatch.context() as m, ThreadPoolExecutor(max_workers=1) as pool:
            m.setattr(Publication, "install", install_then_fail)
            pending = pool.submit(post, client, bundle, "?dry_run=false")
            try:
                assert installed.wait(timeout=10)
                assert (outputs / "1/1/figures/qfig1.png").is_file()
                assert (outputs / "2/1/figures/qfig1.png").is_file()
                assert client.get("/api/papers/1/questions/1/figures/qfig1.png").status_code == 404
                assert client.get("/api/papers/2/questions/1/render").status_code == 404
                assert post(client, bundle, "?dry_run=false").status_code == 429
            finally:
                release.set()
            assert pending.result(timeout=10).status_code == 500
        assert counts(db) == (0, 0, 0) and not list(outputs.iterdir())
        assert post(client, bundle, "?dry_run=false").status_code == 201
        assert counts(db) == (2, 2, 2)


def test_startup_recovers_interrupted_media_and_log_failure_is_not_rejection(archive, tmp_path):
    db, outputs = archive
    bundle = bundle_file(tmp_path / "pair")
    pending = Publication(db, outputs)
    (pending.stage(1) / "marker").touch()
    pending.install("a" * 64, [1])  # simulates a process death before SQLite commits
    assert (outputs / "1/marker").exists()
    (db.parent / f"{db.stem}.bundle-merges.jsonl").mkdir()  # receipt log is deliberately unwritable
    with TestClient(app, base_url="https://paperlab.test") as client:
        assert not (outputs / "1").exists()
        login(client)
        result = post(client, bundle, "?dry_run=false")
        assert result.status_code == 201 and result.json()["warnings"], result.text
        assert counts(db) == (1, 1, 1)
        assert post(client, bundle, "?dry_run=false").json()["already_imported"]


def test_sqlite_deduplicates_parallel_publishers_without_the_api_slot(archive, tmp_path):
    db, outputs = archive
    bundle = bundle_file(tmp_path / "fixture")
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(merge_bundle, bundle, db, outputs, idempotent=True) for _ in range(2)]
        receipts = [j.result(timeout=15) for j in jobs]
    assert sum(bool(r.get("already_imported")) for r in receipts) == 1
    assert receipts[0]["papers"] == receipts[1]["papers"]
    assert counts(db) == (1, 1, 1) and len(list(db.parent.glob("*.bak"))) == 1


def test_frontend_refresh_serves_shell_without_swallowing_api_or_asset_404s(tmp_path):
    from fastapi import FastAPI

    (tmp_path / "index.html").write_text("<title>PaperLab</title>", encoding="utf-8")
    site = FastAPI()
    site.mount("/", _FrontendFiles(directory=tmp_path, html=True))
    with TestClient(site) as client:
        for path in ("/archive", "/archive/1", "/search/1/2"):
            result = client.get(path, headers={"Accept": "text/html"})
            assert result.status_code == 200 and "PaperLab" in result.text
        for path in ("/api/missing", "/_app/immutable/missing.js", "/fonts/missing.woff2"):
            assert client.get(path, headers={"Accept": "text/html"}).status_code == 404
