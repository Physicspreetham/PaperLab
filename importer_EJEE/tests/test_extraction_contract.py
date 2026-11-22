import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extraction_contract import build_prompt, section
from bootstrap import REPO


def test_paper_workflow_is_removed_but_crop_standards_retained():
    native = (REPO / "prompts" / "extractor_prompt.md").read_text(encoding="utf-8")
    prompt = build_prompt({})
    assert "# REPEATED QUESTION NUMBERS" not in prompt
    assert "# EXECUTION WORKFLOW" not in prompt
    assert "get_page_text" not in prompt or "Do not call get_page_text" in prompt
    assert "the final answers are on page 1" not in prompt.lower()
    assert "Pixels second, physics first." not in prompt
    assert section(native, "FIGURE STANDARD (applies to EVERY figure, no exceptions)") in prompt
    assert section(native, "CROP PROCEDURE (think first, then act)") in prompt
    assert "par-mtx" in prompt and "par-mix" in prompt and "mtx" in prompt
    assert "UNREADABLE" in prompt
    assert "EVERY supplied image" in prompt


def test_raster_mode_explicitly_overrides_native_expansion():
    prompt = build_prompt({"raster_exact_crop": True})
    assert prompt.endswith("Mechanical edge-clear feedback is NOT visual approval.")
    assert "NO automatic expansion" in prompt
    assert "assisted_crop" not in prompt
    assert "3 unsuccessful" not in prompt
    assert "mode: snap" not in prompt
    assert "mode: vector" not in prompt
    assert "first crop" in prompt
    assert "Every printed diagram" in prompt
