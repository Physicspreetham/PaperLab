"""PowerPoint export: one slide per entry, themed, with native equations."""
import io
import shutil
import zipfile

import pytest

from backend.routers.export import Slide, slides_to_pptx

pytestmark = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")


def _deck(slides):
    data = slides_to_pptx("Practice", "Question paper", slides)
    return zipfile.ZipFile(io.BytesIO(data))


def test_one_slide_per_entry_plus_title_slide():
    z = _deck([
        Slide(title="Question 1", html="<p><strong>1.</strong> Find <span class=\"math inline\">\\frac{1}{2}</span></p>"),
        Slide(title="Question 1 (cont.)", html="<p>A) one</p><p>B) two</p>"),
    ])
    names = [n for n in z.namelist() if n.startswith("ppt/slides/slide")]
    assert len(names) == 3  # title slide + 2
    texts = {n: z.read(n).decode("utf-8") for n in names}
    assert any("Question 1 (cont.)" in t for t in texts.values())
    assert any("a14:m" in t for t in texts.values())  # native, editable equation


def test_theme_colours_and_fonts_applied():
    z = _deck([Slide(title="Question 1", html="<p>x</p>")])
    theme = z.read("ppt/theme/theme1.xml").decode("utf-8")
    assert "0B4F3A" in theme and "B8863B" in theme and "Georgia" in theme
