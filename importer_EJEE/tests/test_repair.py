import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importer  # noqa: E402
from crop_quality import edge_diagnosis, edge_steps  # noqa: E402


def page():
    """Caption line above a diagram whose label hangs below it."""
    im = Image.new("RGB", (400, 400), "white")
    d = ImageDraw.Draw(im)
    d.line((60, 70, 300, 70), fill="black", width=4)            # caption / prose line
    d.rectangle((100, 120, 260, 260), outline="black", width=3)  # diagram
    d.rectangle((170, 262, 190, 290), fill="black")              # label under it
    return im


def test_edge_steps_change_one_edge_and_find_lines_inside_the_box():
    im = page()
    box = [50, 60, 320, 280]          # caption inside at top, label cut at bottom
    steps = edge_steps(im, box)
    top_in = steps["top-in"]
    assert top_in[1] > 72 and top_in[0::2] == [50, 320] and top_in[3] == 280   # only the top moved
    assert steps["bottom-out"][3] > 290 and steps["bottom-out"][:3] == [50, 60, 320]
    both = edge_steps(im, top_in)["bottom-out"]
    assert edge_diagnosis(im, both) == {}            # chained: caption gone, label kept, clean


def test_repair_records_reviewed_crop_and_chains_picks(tmp_path, monkeypatch):
    run = tmp_path / "run"
    figs = run / "Outputs" / "1" / "1" / "figures"
    figs.mkdir(parents=True)
    src = tmp_path / "body.png"
    page().save(src)
    (figs / "_import_provenance.json").write_text(json.dumps(
        {"qfig1.png": {"source_body": str(src), "source_pixel_box": [50, 60, 320, 280]}}), encoding="utf-8")
    (run / "manifest.json").write_text(json.dumps(
        {"paper_id": 1, "items": [{"number": "1", "group": "g-1"}]}), encoding="utf-8")
    monkeypatch.setattr(importer, "figures", lambda cfg, run: None)
    with pytest.raises(ValueError):
        importer.repair({}, run, {"1/qfig1.png": ["top-in"]}, by=None)       # reviewer required
    with pytest.raises(ValueError):
        importer.repair({}, run, {"1/qfig1.png": ["left-sideways"]}, by="r")  # unknown option
    importer.repair({}, run, {"1/qfig1.png": ["top-in", "bottom-out"]}, by="reviewer")
    entry = json.loads((run / "reviewed_crops.json").read_text(encoding="utf-8"))[0]
    assert entry["group"] == "g-1" and entry["filename"] == "qfig1.png"
    assert entry["source_body_sha256"] == importer.sha(src)
    assert edge_diagnosis(Image.open(src).convert("RGB"), entry["source_pixel_box"]) == {}
    assert "reviewer" in entry["reason"]
    # Run-level repairs take precedence over the shared config file.
    shared = tmp_path / "shared.json"
    shared.write_text(json.dumps([{**entry, "source_pixel_box": [0, 0, 10, 10]}]), encoding="utf-8")
    monkeypatch.setattr(importer, "ROOT", tmp_path)
    crops = importer.reviewed_crops({"reviewed_crops": "shared.json"}, run)
    assert crops[0]["source_pixel_box"] == entry["source_pixel_box"]
