"""Builds the pandoc reference.pptx used by the Paper Builder PowerPoint export.

Starts from pandoc's own default template and restyles the theme to match the
PaperLab slide look: warm cream background, deep green titles with a gold
rule, brown body text, green bars top and bottom, serif (Georgia) headings.
"""
from __future__ import annotations

import functools
import io
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

GREEN, GOLD, CREAM, BROWN, SAND = "0B4F3A", "B8863B", "FBF8F2", "4A3B2E", "F1EADB"
HEAD_FONT, BODY_FONT = "Georgia", "Calibri"

_CLR = (
    f'<a:clrScheme name="PaperLab"><a:dk1><a:srgbClr val="{BROWN}"/></a:dk1>'
    f'<a:lt1><a:srgbClr val="{CREAM}"/></a:lt1><a:dk2><a:srgbClr val="{GREEN}"/></a:dk2>'
    f'<a:lt2><a:srgbClr val="{SAND}"/></a:lt2><a:accent1><a:srgbClr val="{GREEN}"/></a:accent1>'
    f'<a:accent2><a:srgbClr val="{GOLD}"/></a:accent2><a:accent3><a:srgbClr val="1F6F8B"/></a:accent3>'
    '<a:accent4><a:srgbClr val="8B2E2E"/></a:accent4><a:accent5><a:srgbClr val="6B4E9B"/></a:accent5>'
    '<a:accent6><a:srgbClr val="C47F17"/></a:accent6><a:hlink><a:srgbClr val="1F6F8B"/></a:hlink>'
    '<a:folHlink><a:srgbClr val="6B4E9B"/></a:folHlink></a:clrScheme>'
)


def _rect(sid: int, name: str, x: int, y: int, w: int, h: int, color: str) -> str:
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{name}"/><p:cNvSpPr/><p:nvPr userDrawn="1"/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
        '<a:ln><a:noFill/></a:ln></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody></p:sp>'
    )


def _restyle(name: str, data: bytes) -> bytes:
    if name == "ppt/theme/theme1.xml":
        x = data.decode("utf-8")
        x = re.sub(r"<a:clrScheme.*?</a:clrScheme>", _CLR, x, flags=re.S)
        x = re.sub(r"(<a:majorFont><a:latin typeface=\")[^\"]*", rf"\g<1>{HEAD_FONT}", x)
        x = re.sub(r"(<a:minorFont><a:latin typeface=\")[^\"]*", rf"\g<1>{BODY_FONT}", x)
        return x.encode("utf-8")
    if name == "ppt/slideMasters/slideMaster1.xml":
        x = data.decode("utf-8")
        deco = (
            _rect(20, "Top bar", 0, 0, 9144000, 91440, GREEN)
            + _rect(21, "Bottom bar", 0, 5052060, 9144000, 91440, GREEN)
            + _rect(22, "Title rule", 457200, 1080000, 1371600, 22860, GOLD)
        )
        x = x.replace("<p:sp>", deco + "<p:sp>", 1)
        # Title: left aligned, bold green serif. Body: 16pt, brown.
        x = x.replace('<p:titleStyle><a:lvl1pPr algn="ctr"', '<p:titleStyle><a:lvl1pPr algn="l"', 1)
        x = x.replace('<a:defRPr sz="3300" kern="1200"><a:solidFill><a:schemeClr val="tx1"/>',
                      '<a:defRPr sz="2600" b="1" kern="1200"><a:solidFill><a:schemeClr val="tx2"/>', 1)
        x = x.replace('<a:defRPr sz="2400" kern="1200">', '<a:defRPr sz="1600" kern="1200">', 1)
        return x.encode("utf-8")
    if name == "ppt/slideLayouts/slideLayout8.xml":
        # "Content with Caption": pandoc uses it for slides with a figure. Keep the
        # text on the left and the figure on the right, clear of the bars and title.
        x = data.decode("utf-8")
        x = x.replace('<a:off x="457201" y="204787"/><a:ext cx="3008313" cy="871538"/>',
                      '<a:off x="457201" y="204787"/><a:ext cx="4100000" cy="871538"/>', 1)
        x = x.replace('<a:off x="3575050" y="204788"/><a:ext cx="5111750" cy="4389835"/>',
                      '<a:off x="4700000" y="1200151"/><a:ext cx="3986800" cy="3394472"/>', 1)
        x = x.replace('<a:off x="457201" y="1076326"/><a:ext cx="3008313" cy="3518297"/>',
                      '<a:off x="457201" y="1200151"/><a:ext cx="4100000" cy="3394472"/>', 1)
        x = x.replace('<a:defRPr sz="1500" b="1"/>', '<a:defRPr sz="2200" b="1"/>', 1)
        i = x.index('idx="2"')
        j = x.index("</p:sp>", i)
        x = x[:i] + re.sub(r'(<a:lvl1pPr[^>]*>.*?<a:defRPr sz=")\d+', r"\g<1>1600", x[i:j], count=1, flags=re.S) + x[j:]
        return x.encode("utf-8")
    return data


@functools.lru_cache(maxsize=1)
def reference_bytes(pandoc_exe: str) -> bytes:
    with tempfile.TemporaryDirectory(prefix="paperlab_pptxref_") as tmp:
        base = Path(tmp) / "base.pptx"
        with open(base, "wb") as fh:
            subprocess.run([pandoc_exe, "--print-default-data-file", "reference.pptx"],
                           stdout=fh, check=True, timeout=60)
        buf = io.BytesIO()
        with zipfile.ZipFile(base) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                zout.writestr(item, _restyle(item.filename, zin.read(item.filename)))
        return buf.getvalue()


def reference_path(pandoc_exe: str, directory: Path) -> Path:
    out = directory / "reference.pptx"
    out.write_bytes(reference_bytes(pandoc_exe))
    return out
