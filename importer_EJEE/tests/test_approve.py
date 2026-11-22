import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importer  # noqa: E402


def make_run(tmp_path):
    run = tmp_path / "run"
    q = run / "Outputs" / "1" / "4"
    (q / "figures").mkdir(parents=True)
    (q / "question.tex").write_text("Q [UNREADABLE] \\includegraphics{figures/qfig1.png}", encoding="utf-8")
    (q / "solution.tex").write_text("no_solution_found", encoding="utf-8")
    (q / "figures" / "qfig1.png").write_bytes(b"png-bytes")
    (run / "review_required").mkdir()
    (run / "review_required" / "4.json").write_text(json.dumps(
        {"question": "4", "approved": False, "unreadable": ["question: unreadable content requires review"],
         "figures": {"qfig1.png": "edge still cuts content"}}), encoding="utf-8")
    (run / "manifest.json").write_text(json.dumps({"paper_id": 1, "items": [{"number": "4"}]}), encoding="utf-8")
    return run, q


def test_approval_requires_reviewer_and_binds_to_file_hashes(tmp_path):
    run, q = make_run(tmp_path)
    with pytest.raises(ValueError):
        importer.approve({}, run, "", "")
    with pytest.raises(ValueError, match="not in this run"):
        importer.approve({}, run, "visit", "unknown question", ["../wrong"])
    importer.approve({}, run, "visit", "held figures checked in review UI")
    record = json.loads((run / "review_required" / "4.json").read_text(encoding="utf-8"))
    assert record["approved"] and record["approval"]["by"] == "visit"
    assert set(record["approval"]["hashes"]) == {"question.tex", "solution.tex", "figures/qfig1.png"}
    approvals = json.loads((run / "crop_approvals.json").read_text(encoding="utf-8"))
    assert approvals["4/qfig1.png"] == importer.sha(q / "figures" / "qfig1.png")
    assert record["approval"]["hashes"] == importer._question_files(run, {"paper_id": 1}, "4")
    (q / "figures" / "qfig1.png").write_bytes(b"changed")      # any later edit
    assert record["approval"]["hashes"] != importer._question_files(run, {"paper_id": 1}, "4")
