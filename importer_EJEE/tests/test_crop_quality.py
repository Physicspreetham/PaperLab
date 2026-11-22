import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crop_quality import edge_margins, approval_errors


def test_edge_detection_includes_faint_labels():
    image = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(image).rectangle((20, 20, 80, 80), outline="black")
    image.putpixel((99, 40), (200, 200, 200))
    assert edge_margins(image)["right"] == 0


def test_whitespace_margin_counts():
    image = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(image).rectangle((10, 20, 80, 90), outline="black")
    assert edge_margins(image) == {"left": 10, "top": 20, "right": 19, "bottom": 9}
    assert edge_margins(Image.new("RGB", (100, 100), "white")) is None


def test_review_requires_matching_current_hash_and_cannot_override_pixel_damage():
    record = {
        "question": "55", "filename": "sfig1.png",
        "source_pixel_identical": True, "hash_matches_provenance": True,
        "review_required": True,
    }
    assert approval_errors([record], {}, {"55/sfig1.png": "current"})
    assert approval_errors([record], {"55/sfig1.png": "old"}, {"55/sfig1.png": "current"})
    assert not approval_errors(
        [record], {"55/sfig1.png": "current"}, {"55/sfig1.png": "current"}
    )
    assert approval_errors(
        [{**record, "source_pixel_identical": False}],
        {"55/sfig1.png": "current"}, {"55/sfig1.png": "current"},
    )
