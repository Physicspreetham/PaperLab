import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootstrap import REPO
sys.path.insert(0, str(REPO))
from figure_cleanup import cleanup_figure, update_evidence


def test_trim_preserves_all_content_and_is_idempotent(tmp_path):
    image = Image.new("RGB", (200, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.line((60, 60, 140, 140), fill="black", width=3)
    draw.text((90, 80), "m1", fill="black")
    path = tmp_path / "qfig1.png"
    image.save(path)
    result = cleanup_figure(path)
    import json
    json.dumps(result)
    assert result["changed"] and not result["review_required"]
    original = np.asarray(image)
    after = np.asarray(Image.open(path).convert("RGB"))
    x, y = result["offset"]
    assert np.array_equal(after, original[y:y + after.shape[0], x:x + after.shape[1]])
    assert (after != 255).sum() == (original != 255).sum()
    first = path.read_bytes()
    assert not cleanup_figure(path)["changed"]
    assert path.read_bytes() == first


def test_native_border_component_deletion_is_rejected(tmp_path):
    image = Image.new("RGB", (200, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 50, 150, 150), outline="black", width=3)
    image.putpixel((0, 20), (0, 0, 0))  # could be a legitimate small mark
    path = tmp_path / "sfig1.png"
    image.save(path)
    original = path.read_bytes()
    result = cleanup_figure(path)
    assert not result["changed"] and result["review_required"]
    assert path.read_bytes() == original


def test_faint_labels_outside_dark_bbox_are_not_lost(tmp_path):
    image = Image.new("RGB", (200, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 60, 140, 140), outline="black", width=3)
    draw.text((10, 10), "v0", fill=(200, 200, 200))
    path = tmp_path / "qfig1.png"
    image.save(path)
    original = path.read_bytes()
    result = cleanup_figure(path)
    assert not result["changed"] and result["review_required"]
    assert path.read_bytes() == original


def test_provenance_tracks_source_pixel_trim():
    evidence = {"source_pixel_box": [50, 80, 250, 280], "sha256": "before"}
    record = {
        "offset": [10, 20], "after_size": [100, 120],
        "after_sha256": "after",
    }
    update_evidence(evidence, record)
    assert evidence["source_pixel_box"] == [60, 100, 160, 220]
    assert evidence["sha256"] == "after"
