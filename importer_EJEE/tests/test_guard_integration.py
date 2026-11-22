"""Exercise the real native submission + importer repair without any API."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_native_submission_and_guard_in_isolated_process():
    compat = ROOT / "runs" / "benchmark-compat"
    # A Windows-only local import shim is not a shipped runtime dependency.
    env = dict(os.environ)
    if compat.is_dir():
        env["PYTHONPATH"] = str(compat)
    code = r'''
import tempfile, sys
from pathlib import Path
sys.path.insert(0, str(Path("importer_EJEE").resolve()))
from bootstrap import activate, ROOT
(ROOT / "runs").mkdir(exist_ok=True)
from submission_guard import guard_saved_submission
with tempfile.TemporaryDirectory(dir=ROOT / "runs") as tmp:
    activate(Path(tmp))
    import database, directory_manager
    import tools_extractor as tools
    from extraction_contract import bind_descriptions
    native_tools = [tools.get_page_image, tools.assisted_crop, tools.exact_crop,
                    tools.submit_question, tools.submit_solution]
    adapted = bind_descriptions(native_tools, {})
    for original, copied in zip(native_tools, adapted):
        assert copied.name == original.name
        assert copied.func is original.func
        assert copied.args_schema is original.args_schema
        assert copied.tool_call_schema.model_json_schema()["properties"] == original.tool_call_schema.model_json_schema()["properties"]
        assert copied.description != original.description
    database.init_db()
    with database.get_connection() as conn:
        conn.execute("INSERT INTO papers (question_pdf_path, pdf_hash) VALUES (?,?)",
                     ("test-only.pdf", "guard-integration"))
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    q = (r"Evaluate these cases. \textbf{(a)} $m_1=m_2$."
         "\n\n" + r"\begin{equation}a_1=\frac{m_2}{m_3}+\text{file_name}\end{equation}")
    assert tools.submit_question.invoke(
        {"paper_id":pid, "question_number":"1", "latex_content":q, "qtype":"unknown"}
    ) == "saved"
    folder = directory_manager.get_question_dir(pid, "1")
    saved = (folder/"question.tex").read_text(encoding="utf-8")
    assert r"a_1=\frac{m_2}{m_3}" in saved and r"\text{file\_name}" in saved
    guard_saved_submission(pid, "1", "question", q)
    fixed = (folder/"question.tex").read_text(encoding="utf-8")
    assert fixed == saved  # legacy repair is a no-op after the native fix
    assert not (folder/"_submission_repairs.json").exists()
    s = (r"\textbf{Answer: 1)} $\frac{m_1}{m_2}$" + "\n\n"
         + r"\underline{\textbf{Solution for 1}}" + "\n\n"
         + r"\begin{align}v_1&=v_2\\a_1&=a_2\end{align}")
    assert tools.submit_solution.invoke(
        {"paper_id":pid, "question_number":"1", "latex_content":s}
    ) == "saved"
    guard_saved_submission(pid, "1", "solution", s)
    fixed = (folder/"solution.tex").read_text(encoding="utf-8")
    assert r"v_1&=v_2" in fixed and r"a_1&=a_2" in fixed
    from backend.segments import rich_text
    from app.render import tex_to_markdown
    from urllib.parse import unquote
    assert "v_1" in unquote(rich_text(tex_to_markdown(fixed)))
    from raster_crop import make_exact_crop, make_page_image
    from importer import sha
    from PIL import Image
    source = Path(tmp)/"source.png"
    image = Image.new("RGB", (100,100), "white")
    image.putpixel((40,40), (0,0,0))
    image.save(source)
    manifest = {
        "paper_id":pid, "question_pdf":"mapped-q.pdf", "solution_pdf":None,
        "items":[{
            "number":"1", "question_pages":[1], "solution_pages":[],
            "question_rows":[{"asset_evidence":{
                "body_png":str(source), "body_sha256":sha(source)
            }}], "solution_rows":[]
        }]
    }
    exact = make_exact_crop(manifest, tools)
    call = {
        "name":"exact_crop", "id":"test-crop", "type":"tool_call",
        "args":{"pdf_path":"mapped-q.pdf", "page_number":1,
                "x":200,"y":200,"width":600,"height":600,
                "output_filename":"qfig1.png","paper_id":pid,"question_number":"1"}
    }
    result = exact.invoke(call)
    assert "NO AUTO-EXPANSION" in result.update["messages"][0].content
    assert tools._assist_used(pid, "1", "qfig1.png") == 0
    raster_tools = bind_descriptions(
        [tools.get_page_image, tools.assisted_crop, exact,
         tools.submit_question, tools.submit_solution], {"raster_exact_crop":True}
    )
    assert [t.name for t in raster_tools] == [
        "get_page_image", "exact_crop", "submit_question", "submit_solution"
    ]
    assert "FIRST attempt" in raster_tools[1].description
    assert "tool_call_id" not in raster_tools[1].tool_call_schema.model_json_schema()["properties"]
    inspect = make_page_image(manifest, tools, Path(tmp))
    result = inspect.invoke({
        "name":"get_page_image", "id":"test-inspection", "type":"tool_call",
        "args":{"pdf_path":"mapped-q.pdf","page_number":1,
                "x":200,"y":200,"width":600,"height":600},
    })
    assert "Source inspection only" in result.update["messages"][0].content
    assert "FULL body's" in result.update["messages"][0].content
    assert tools._assist_used(pid, "1", "qfig1.png") == 0
    assert source.is_file()
    with Image.open(folder/"figures"/"qfig1.png") as crop:
        assert crop.size == (60,60)
        assert crop.getpixel((20,20)) == (0,0,0)
    import gc
    gc.collect()
print("native integration passed")
'''
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT.parent, env=env,
        capture_output=True, text=True, timeout=60,
    )
    if "Application Control policy" in result.stderr:
        pytest.skip("Windows policy blocks an optional native dependency")
    assert result.returncode == 0, result.stdout + result.stderr
