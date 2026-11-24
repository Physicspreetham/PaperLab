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


def test_figure_is_a_picture_beside_the_text_not_in_the_text():
    import base64
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, "PNG")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    z = _deck([Slide(title="Question 1", html="<p>stem</p><p>A) one</p>", images=[uri])])
    slide = z.read("ppt/slides/slide2.xml").decode("utf-8")
    assert "<p:pic>" in slide  # placed explicitly, not by pandoc's figure layout
    assert "Question figure" not in slide  # no alt-text caption
    assert 'cx="4100000"' in slide  # text narrowed to the left column
    assert any(n.startswith("ppt/media/plfig") for n in z.namelist())
    assert 'Extension="png"' in z.read("[Content_Types].xml").decode("utf-8")


def _png_uri():
    import base64
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def test_every_slide_is_valid_xml_with_figure_long_text_and_math():
    from xml.etree import ElementTree as ET

    long_text = "word " * 120
    z = _deck([Slide(
        title="Question 45",
        html=rf'<p><strong>45.</strong> {long_text} <span class="math inline">\frac{{a}}{{b}}</span></p><p>A) one</p>',
        images=[_png_uri()],
    )])
    for name in z.namelist():
        if name.endswith(".xml") or name.endswith(".rels"):
            ET.fromstring(z.read(name))  # raises if a post-processing step broke the XML
    slide = z.read("ppt/slides/slide2.xml").decode("utf-8")
    assert 'type="title"' in slide and 'idx="1"' in slide  # placeholders intact
    assert "normAutofit" in slide  # long text beside a figure shrinks to fit


def test_equations_have_a_plain_text_fallback_for_other_viewers():
    z = _deck([Slide(
        title="Question 1",
        html=r'<p>Find <span class="math inline">\frac{mb^2}{4}</span> and <span class="math inline">\sqrt{x}+v_0</span> now</p>',
    )])
    slide = z.read("ppt/slides/slide2.xml").decode("utf-8")
    assert "<mc:Choice" in slide and "<mc:Fallback>" in slide
    fallback = slide.split("<mc:Fallback>")[1]
    assert "Find " in fallback and " now" in fallback  # the surrounding question text survives
    assert "mb²/4" in fallback and "√x+v₀" in fallback
    assert "<a14:m>" not in fallback


def test_omml_to_text():
    from backend.pptx_math_fallback import omml_to_text

    ns = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
    x = f'<m:oMath {ns}><m:sSup><m:e><m:r><m:t>x</m:t></m:r></m:e><m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup></m:oMath>'
    assert omml_to_text(x) == "x²"


def test_equations_inside_a_table_keep_the_slide_valid():
    from xml.etree import ElementTree as ET

    html = (
        '<p><strong>91.</strong> Match.</p><table><thead><tr><th>Column I</th><th>Column II</th></tr></thead>'
        r'<tbody><tr><td>(p) radius <span class="math inline">r_0</span></td>'
        r'<td>(1) <span class="math inline">\frac{1}{2}</span></td></tr></tbody></table>'
    )
    z = _deck([Slide(title="Question 91", html=html)])
    slide = z.read("ppt/slides/slide2.xml").decode("utf-8")
    ET.fromstring(slide)  # was: unbound prefix a14 (PowerPoint wants to repair the file)
    assert "radius" in slide and "<mc:Fallback>" in slide and "r₀" in slide
