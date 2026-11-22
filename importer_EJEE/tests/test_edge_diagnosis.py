import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crop_quality import describe, edge_diagnosis, touching_edges  # noqa: E402


def page():
    im = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((100, 100, 200, 200), outline="black", width=2)   # the diagram
    d.line((100, 60, 300, 60), fill="black", width=3)              # neighbouring text line
    return im


def test_clear_crop_reports_no_contact():
    assert edge_diagnosis(page(), [90, 90, 210, 210]) == {}
    assert "clear margin" in describe({})


def test_cut_diagram_says_content_continues_outside():
    d = edge_diagnosis(page(), [90, 90, 150, 210])          # right edge cuts the box
    assert d == {"right": "ink continues outside"}
    assert "EXPAND" in describe(d)


def test_foreign_text_line_inside_box_is_contact():
    d = edge_diagnosis(page(), [90, 59, 210, 210])           # top edge on the text line
    assert "top" in d


def test_gap_suggestions_offer_expand_and_shrink_from_source_pixels():
    from crop_quality import gap_suggestions, to_grid
    im = page()
    cut = [90, 90, 150, 210]                       # right edge slices the diagram
    s = gap_suggestions(im, cut)
    assert s["expand"][2] > 200                    # reaches past the diagram's right side
    assert edge_diagnosis(im, s["expand"]) == {}  # and the result is clean
    intruding = [90, 59, 210, 210]                 # top edge sits on the text line
    s = gap_suggestions(im, intruding)
    assert s["shrink"][1] >= 62 and s["shrink"][2] == 210   # drops the line; right edge untouched
    assert edge_diagnosis(im, s["shrink"]) == {}
    assert gap_suggestions(im, [90, 90, 210, 210]) == {}   # clean crops get no advice
    assert to_grid([0, 0, 400, 300], im.size) == [0, 0, 1000, 1000]


def test_content_ending_at_edge_and_image_border():
    im = page()
    assert edge_diagnosis(im, [90, 90, 201, 210]).get("right") == "no ink just outside"
    full = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(full).line((0, 50, 99, 50), fill="black")
    assert edge_diagnosis(full, [0, 40, 100, 60])["left"].startswith("at the source image border")
    assert touching_edges(Image.new("RGB", (10, 10), "white")) == []
