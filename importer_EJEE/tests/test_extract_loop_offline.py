"""Run the REAL extract_item loop with a scripted model (no API, no cost).

Covers: direct exact_crop, append-only previews, submit_pair failure isolation
(a rejected question never saves a solution), native savers, the answer-key
completion check for a standalone card, and the 20-call default ceiling.
"""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]

CODE = r'''
import json, tempfile, sys
from pathlib import Path
sys.path.insert(0, str(Path("importer_EJEE").resolve()))
from bootstrap import activate, ROOT
(ROOT / "runs").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=ROOT / "runs", ignore_cleanup_errors=True) as tmp:
    run = Path(tmp); activate(run)
    import database, llm, directory_manager
    from importer import extract_item, sha
    from langchain_core.messages import AIMessage
    from PIL import Image, ImageDraw
    database.init_db(); database.init_topics()
    with database.get_connection() as c:
        c.execute("INSERT INTO papers (question_pdf_path, pdf_hash) VALUES ('q.pdf','offline')")
        pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    body = run / "body.png"
    im = Image.new("RGB", (400, 300), "white"); ImageDraw.Draw(im).rectangle((100, 80, 300, 220), outline="black", width=3)
    im.save(body)
    row = {"id": 7, "title": "Card · Q1", "answer": "(B)", "question": None, "solution": None,
           "qtype": "Single correct", "asset_evidence": {"body_png": str(body), "body_sha256": sha(body)}}
    item = {"number": "1", "group": "res:7", "groups": ["res:7"], "merged": False, "kind": "card",
            "question_rows": [row], "solution_rows": [], "question_pages": [1], "solution_pages": [],
            "resource_crops": [], "resource_transcripts": []}
    manifest = {"paper_id": pid, "question_pdf": "q.pdf", "solution_pdf": None, "items": [item]}
    crop = {"pdf_path": "q.pdf", "page_number": 1, "paper_id": pid, "question_number": "1",
            "output_filename": "qfig1.png", "x": 200, "y": 200, "width": 600, "height": 600}
    good_q = "A block is shown. \\includegraphics[width=\\linewidth]{figures/qfig1.png}\n\n\\begin{enumerate}\n\\item 1\n\\item 2\n\\end{enumerate}"
    good_s = "\\textbf{Answer: 1) B}\n\nNo worked solution supplied in source."
    pair = lambda q: {"paper_id": pid, "question_number": "1", "question_latex": q, "solution_latex": good_s, "qtype": "scq"}
    script = [
        [("exact_crop", crop)],
        [("exact_crop", {**crop, "x": 150, "y": 150, "width": 700, "height": 700})],
        [("submit_pair", pair("\\begin{enumerate} \\item broken"))],
        [("submit_pair", pair(good_q))],
    ]
    seen = []
    class Fake:
        def bind_tools(self, *a, **k): return self
    def invoke(_llm, messages):
        seen.append([m for m in messages])
        calls = script[len(seen) - 1]
        if isinstance(calls, str):   # provider wrote the call as text markup
            return AIMessage(content=calls, usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
        return AIMessage(content="", tool_calls=[{"name": n, "args": a, "id": f"c{len(seen)}{i}", "type": "tool_call"} for i, (n, a) in enumerate(calls)],
                         usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    llm.get_llm = lambda: Fake(); llm.invoke_with_retry = invoke
    cfg = {"raster_exact_crop": True}
    result = extract_item(manifest, item, cfg, run)
    assert result["ok"] and result["turns"] == 4, result
    tool_msgs = [m.content for m in seen[3] if m.type == "tool"]
    assert any("question: NOT SAVED" in t and "solution: not attempted" in t for t in tool_msgs), tool_msgs
    previews = [m for m in seen[2] if m.type == "human" and isinstance(m.content, list)
                and m.content and str(m.content[0].get("text", "")).startswith("[Crop preview: qfig1.png]")]
    # Append-only by default: older previews stay untouched so the provider's
    # prompt cache prefix is never invalidated (pruning is opt-in).
    assert len(previews) == 2 and all(m.content[1]["type"] == "image_url" for m in previews)
    olds = [m for m in seen[2] if m.type == "human" and isinstance(m.content, list)
            and "Older preview of qfig1.png" in str(m.content[0].get("text", ""))]
    assert not olds
    sources = [m for m in seen[2] if m.type == "human" and isinstance(m.content, list)
               and str(m.content[0].get("text", "")).startswith("QUESTION page 1")]
    assert sources and sources[0].content[1]["type"] == "image_url", "source page image must stay"
    folder = directory_manager.get_question_dir(pid, "1")
    assert (folder / "solution.tex").read_text(encoding="utf-8").startswith("\\textbf{Answer: 1) B}")
    with Image.open(folder / "figures" / "qfig1.png") as f:
        assert f.size == (280, 210)
    # Edge gate: a crop that CUTS the drawing is sent back at most twice, then
    # the question completes with the figure held for review (blocks merge).
    seen.clear()
    cut = {**crop, "x": 300, "y": 200, "width": 300, "height": 500}   # slices through the rectangle
    item3 = {**item, "number": "3"}; manifest["items"].append(item3)
    pair3 = {**pair(good_q.replace("qfig1", "qfig1")), "question_number": "3",
             "solution_latex": good_s.replace("1) B", "3) B")}
    script[:] = [[("exact_crop", {**cut, "question_number": "3"})]] + [[("submit_pair", pair3)]] * 3
    r3 = extract_item(manifest, item3, cfg, run)
    assert r3["ok"] and r3["turns"] == 4 and r3["figures_held_for_review"] == ["qfig1.png"], r3
    gate_msgs = [m.content for m in seen[2] if m.type == "human" and isinstance(m.content, str)
                 and "cut through content" in m.content]
    assert gate_msgs, "model must be told which edge cuts content"
    review = json.loads((run / "review_required" / "3.json").read_text(encoding="utf-8"))
    assert review["approved"] is False and "qfig1.png" in review["figures"]
    # Crop limit: the figure is frozen for review instead of failing the question.
    seen.clear()
    item4 = {**item, "number": "4"}; manifest["items"].append(item4)
    pair4 = {**pair3, "question_number": "4", "solution_latex": good_s.replace("1) B", "4) B")}
    script[:] = [[("exact_crop", {**crop, "question_number": "4"})]] * 9 + [[("submit_pair", pair4)]]
    r4 = extract_item(manifest, item4, cfg, run)
    assert r4["ok"] and "qfig1.png" in r4["figures_held_for_review"], r4
    assert any("FROZEN" in m.content for m in seen[-1] if m.type == "tool")
    # Turn reserve: endless figure polishing cannot starve the transcription.
    seen.clear()
    item5 = {**item, "number": "5"}; manifest["items"].append(item5)
    pair5 = {**pair3, "question_number": "5", "solution_latex": good_s.replace("1) B", "5) B")}
    names = ["qfig1.png", "qfig2.png", "qfig3.png"]
    polish = [[("exact_crop", {**crop, "question_number": "5", "output_filename": names[i % 3]})] for i in range(17)]
    q5 = good_q + "\n\n\\includegraphics[width=\\linewidth]{figures/qfig2.png}\n\n\\includegraphics[width=\\linewidth]{figures/qfig3.png}"
    script[:] = polish + [[("submit_pair", {**pair5, "question_latex": q5})]] * 3
    r5 = extract_item(manifest, item5, cfg, run)
    assert r5["ok"] and r5["turns"] <= 20, r5
    closing = [m for m in seen[16] if m.type == "human" and isinstance(m.content, str) and "Cropping is now closed" in m.content]
    assert len(closing) == 1, "the save-now notice is sent exactly once"
    assert any("Cropping is closed" in m.content for m in seen[17] if m.type == "tool")
    # Text-form tool call (seen live on APhO Q4) is recovered, not looped on.
    seen.clear()
    item6 = {**item, "number": "6"}; manifest["items"].append(item6)
    q6 = good_q.replace("\\includegraphics[width=\\linewidth]{figures/qfig1.png}", "")
    markup = ('<atem:function_calls><atem:invoke name="default.submit_pair">'
              f'<atem:parameter name="paper_id">{pid}</atem:parameter>'
              '<atem:parameter name="question_number">6</atem:parameter>'
              f'<atem:parameter name="question_latex">{q6}</atem:parameter>'
              '<atem:parameter name="qtype">scq</atem:parameter>'
              '<atem:parameter name="solution_latex">' + good_s.replace("1) B", "6) B") + '</atem:parameter>'
              '</atem:invoke></atem:function_calls>')
    script[:] = [markup]
    r6 = extract_item(manifest, item6, cfg, run)
    assert r6["ok"] and r6["turns"] == 1, r6
    # Ceiling: a model that never saves stops at the default 20 calls.
    seen.clear(); script[:] = [[("exact_crop", crop)]] * 40
    item2 = {**item, "number": "2"}; manifest["items"].append(item2)
    try:
        extract_item(manifest, item2, cfg, run)
        raise AssertionError("expected turn limit")
    except Exception as exc:
        assert "turn limit" in str(exc) or "crop" in str(exc).lower(), exc
    assert len(seen) <= 20
    import gc; gc.collect()
print("offline loop passed")
'''


def test_real_extract_loop_with_scripted_model():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    compat = ROOT / "runs" / "benchmark-compat"
    if compat.is_dir():
        env["PYTHONPATH"] = str(compat)
    result = subprocess.run([sys.executable, "-c", CODE], cwd=ROOT.parent, env=env,
                            capture_output=True, text=True, timeout=120)
    if "Application Control policy" in result.stderr:
        pytest.skip("Windows policy blocks an optional native dependency")
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    assert "offline loop passed" in result.stdout
