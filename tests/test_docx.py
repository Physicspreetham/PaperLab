from __future__ import annotations

import io
from xml.etree import ElementTree as ET
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import database
import directory_manager
from backend.docx import InvalidSheet, build_pandoc_input
from backend.main import app
from backend.routers import export

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "m": "http://schemas.openxmlformats.org/officeDocument/2006/math"}


def sheet(contents: str) -> str:
    return f'<div xmlns="http://www.w3.org/1999/xhtml">{contents}</div>'


@pytest.fixture
def figure(tmp_db, tmp_outputs, dummy_pdf):
    pid = database.register_paper(dummy_pdf)
    database.set_paper_status(pid, "done")
    with database.get_connection() as db:
        db.execute("INSERT INTO questions (paper_id, question_number) VALUES (?, '1')", (pid,))
    folder = directory_manager.ensure_question_dir(pid, "1") / "figures"
    path = folder / "qfig1.png"
    Image.new("RGB", (32, 16), "white").save(path)
    return path, f"/api/papers/{pid}/questions/1/figures/{path.name}"


def test_word_download_has_editable_equations_key_and_figure(figure):
    _, ref = figure
    doc = sheet(
        r'<h2>Mechanics</h2><ol start="7"><li>Find <span class="math inline">x = \frac{v}{2}</span>.</li></ol>'
        f'<figure><img data-figure="{ref}" width="32" /></figure>'
        '<table class="pl-key-table"><tbody><tr><td>Q7</td><td>B</td></tr></tbody></table>'
        '<h3 data-solutions="1">Solutions</h3><p>Worked solution.</p>'
    )
    response = TestClient(app).post("/api/export/docx", json={"title": "Mechanics (answers)", "sheet": doc})
    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == 'attachment; filename="Mechanics_answers.docx"'
    assert response.headers["content-type"] == export.DOCX_MIME
    assert response.headers["cache-control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        body = ET.fromstring(archive.read("word/document.xml"))
        equation = body.find(".//m:oMath", NS)
        assert equation is not None and equation.find(".//m:f", NS) is not None
        x = next(run for run in equation.findall(".//m:r", NS) if run.findtext("m:t", namespaces=NS) == "x")
        plain = x.find("m:rPr/m:sty[@m:val='p']", NS)
        assert plain is None  # keep the equation font's italic variables
        assert body.find(".//w:br[@w:type='page']", NS) is not None
        texts = [node.text for node in body.findall(".//w:t", NS)]
        assert "7." in texts and "Q7" in texts and "B" in texts
        assert body.find(".//w:sectPr/w:pgSz[@w:w='11906']", NS) is not None
        assert any(name.startswith("word/media/") and name.endswith(".png") for name in archive.namelist())
        relationships = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        assert all(rel.get("TargetMode") != "External" for rel in relationships)


@pytest.mark.parametrize("contents", [
    '<script>not document content</script>',
    '<img data-figure="https://example.invalid/demo.png" width="10" />',
    '<img src="not-an-archive-reference.png" width="10" />',
    '<span class="math inline"><strong>x</strong></span>',
    '<p><!-- not serialized by the client -->Hello</p>',
])
def test_only_supported_sheet_markup_is_accepted(tmp_db, contents):
    with pytest.raises(InvalidSheet):
        build_pandoc_input(sheet(contents))


def test_conversion_receives_only_rebuilt_markup(tmp_db):
    result = build_pandoc_input(sheet(
        '<p style="color:red" class="draft" data-unused="ignore">A &amp; B</p>'
    )).decode()
    assert "<p>A &amp; B</p>" in result
    assert "color" not in result and "data-unused" not in result


def test_missing_figure_fails_instead_of_downloading_partial_sheet(figure):
    path, ref = figure
    path.unlink()
    response = TestClient(app).post("/api/export/docx", json={
        "title": "Missing figure",
        "sheet": sheet(f'<p>Question</p><img data-figure="{ref}" width="32" />'),
    })
    assert response.status_code == 409
    assert "missing" in response.json()["detail"]


def test_number_is_retained_for_a_figure_only_question(figure):
    _, ref = figure
    contents = sheet(f'<ol start="4"><li><figure><img data-figure="{ref}" width="32" /></figure></li></ol>')
    response = TestClient(app).post("/api/export/docx", json={"title": "Figure question", "sheet": contents})
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        body = ET.fromstring(archive.read("word/document.xml"))
        assert "4." in [tag.text for tag in body.findall(".//w:t", NS)]
        assert body.find(".//w:drawing", NS) is not None


def test_repeated_figures_count_towards_output_limit(figure, monkeypatch):
    path, ref = figure
    monkeypatch.setattr("backend.docx._MAX_MEDIA", path.stat().st_size)
    with pytest.raises(InvalidSheet, match="too large") as invalid:
        build_pandoc_input(sheet(f'<img data-figure="{ref}" width="32" />' * 2))
    assert invalid.value.status == 413


def test_body_limit_checks_actual_bytes_and_conversions_do_not_queue(monkeypatch):
    monkeypatch.setattr(export, "MAX_BODY", 64)
    client = TestClient(app)
    endpoint = "/api/export/docx"
    headers = {"Content-Type": "application/json"}
    oversized = client.post(endpoint, content=b" " * 65, headers={**headers, "Content-Length": "2"})
    assert oversized.status_code == 413
    with export._slot:
        busy = client.post(endpoint, content=b"{}", headers=headers)
    assert busy.status_code == 429 and busy.headers["retry-after"] == "5"
    assert client.post(endpoint, content=b"{", headers=headers).status_code == 422
    assert client.post("/api/export/pdf", json={}).status_code in {404, 405}
