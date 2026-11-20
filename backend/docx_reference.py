"""Builds the pandoc reference.docx used by the Paper Builder Word export.

Start from pandoc's own default template and rewrite its styles so the
exported paper looks like a printed question paper: A4, Times New Roman
13pt, 1.5 line spacing, left-aligned, hanging-indent question numbers, indented options,
centred figures, bordered tables. The Lua filter (pandoc_docx.lua) assigns
the custom styles defined here (QItem, QOpt, QFig, ...).
"""
from __future__ import annotations

import functools
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

FONT = "Times New Roman"
SZ = 26  # half-points -> 13pt (source paper: Times New Roman ~13.2pt)
LINE = 360  # 1.5 line spacing (source paper line pitch is ~22.7pt at 13.2pt)
HANG = 680  # question number column: 34pt, as in the source paper
# Option columns (twips from the left margin) used when 4 short options share a line.
OPT_TABS = (678, 2712, 4746, 6780)

# A4, 0.7in margins -> 9890 twips (6.87in) of text width.
SECT_PR = (
    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
    '<w:pgMar w:top="1008" w:right="1008" w:bottom="1008" w:left="1008" '
    'w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>'
)

_FONTS = f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:eastAsia="{FONT}" w:cs="{FONT}"/>'


def _pstyle(sid: str, name: str, ppr: str, rpr: str = "", based: str = "Normal") -> str:
    return (
        f'<w:style w:type="paragraph" w:customStyle="1" w:styleId="{sid}">'
        f'<w:name w:val="{name}"/><w:basedOn w:val="{based}"/><w:qFormat/>'
        f"<w:pPr>{ppr}</w:pPr>" + (f"<w:rPr>{rpr}</w:rPr>" if rpr else "") + "</w:style>"
    )


def _heading(sid: str, name: str, lvl: int, size: int, before: int, after: int, border: bool) -> str:
    bdr = '<w:pBdr><w:bottom w:val="single" w:sz="8" w:space="2" w:color="000000"/></w:pBdr>' if border else ""
    return (
        f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/>'
        '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
        f'<w:pPr><w:keepNext/><w:keepLines/>{bdr}<w:spacing w:before="{before}" w:after="{after}"/>'
        f'<w:jc w:val="center"/><w:outlineLvl w:val="{lvl}"/></w:pPr>'
        f'<w:rPr>{_FONTS}<w:b/><w:bCs/><w:color w:val="000000"/><w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr>'
        "</w:style>"
    )


_TABS = "<w:tabs>" + "".join(f'<w:tab w:val="left" w:pos="{t}"/>' for t in OPT_TABS) + "</w:tabs>"

CUSTOM_STYLES = "".join(
    [
        # Question stem: bold number in the margin column, text starts at HANG.
        _pstyle("QItem", "QItem", f'<w:spacing w:before="0" w:after="0"/><w:ind w:left="{HANG}" w:hanging="{HANG}"/>'),
        _pstyle("QItemCont", "QItemCont", f'<w:ind w:left="{HANG}"/>'),
        _pstyle("QSub", "QSub", f'<w:spacing w:before="0" w:after="0"/><w:ind w:left="{2*HANG}" w:hanging="{HANG}"/>'),
        _pstyle("QSubCont", "QSubCont", f'<w:ind w:left="{2*HANG}"/>'),
        # Long options: one per line under the stem text.
        _pstyle("QOpt", "QOpt", f'<w:spacing w:before="0" w:after="0"/><w:ind w:left="{HANG}"/>'),
        # Short options: A) B) C) D) share one line, fixed columns like the source.
        _pstyle("QOptRow", "QOptRow", f'{_TABS}<w:spacing w:before="0" w:after="0"/>'),
        # Figures: centred, single-spaced so the picture is not padded.
        _pstyle("QFig", "QFig", '<w:keepLines/><w:spacing w:before="60" w:after="60" w:line="240" w:lineRule="auto"/><w:jc w:val="center"/>'),
        # Paper / section headers.
        _pstyle("DocSub", "DocSub", '<w:spacing w:before="0" w:after="120" w:line="276" w:lineRule="auto"/><w:jc w:val="center"/>', '<w:sz w:val="22"/><w:szCs w:val="22"/>'),
        _pstyle("SecKind", "SecKind", '<w:spacing w:before="0" w:after="60" w:line="276" w:lineRule="auto"/><w:jc w:val="center"/>', "<w:b/><w:bCs/>"),
        # Instruction bullets: small and tight, as in the source header block.
        _pstyle("QBullet", "QBullet", '<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:left="283" w:hanging="283"/>', '<w:sz w:val="19"/><w:szCs w:val="19"/>'),
        # Subtopic title above each group of questions (EJEE assignments).
        _pstyle("TopicHead", "TopicHead", '<w:keepNext/><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="000000"/></w:pBdr><w:spacing w:before="240" w:after="120" w:line="276" w:lineRule="auto"/>', "<w:b/><w:bCs/>"),
        _pstyle("ParaHead", "ParaHead", '<w:keepNext/><w:spacing w:before="120" w:after="0"/>', "<w:b/><w:bCs/>"),
    ]
)

TABLE_STYLE = (
    '<w:style w:type="table" w:default="1" w:styleId="Table"><w:name w:val="Table"/>'
    '<w:basedOn w:val="TableNormal"/><w:qFormat/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/>'
    "<w:tblBorders>"
    + "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="808080"/>' for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
    + '</w:tblBorders><w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="100" w:type="dxa"/>'
    '<w:bottom w:w="40" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>'
)


def _replace_style(xml: str, sid: str, new: str) -> str:
    pat = re.compile(r'<w:style [^>]*w:styleId="%s"[^>]*>[\s\S]*?</w:style>' % re.escape(sid))
    return pat.sub(lambda _m: new, xml, count=1) if pat.search(xml) else xml.replace("</w:styles>", new + "</w:styles>")


def _patch_styles(xml: str) -> str:
    # Document defaults: font, size, justified, tight spacing.
    xml = re.sub(
        r"<w:rPrDefault>[\s\S]*?</w:rPrDefault>",
        f'<w:rPrDefault><w:rPr>{_FONTS}<w:sz w:val="{SZ}"/><w:szCs w:val="{SZ}"/>'
        '<w:lang w:val="en-US" w:eastAsia="en-US" w:bidi="ar-SA"/></w:rPr></w:rPrDefault>',
        xml,
        count=1,
    )
    xml = re.sub(
        r"<w:pPrDefault>[\s\S]*?</w:pPrDefault>",
        f'<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="{LINE}" w:lineRule="auto"/>'
        '</w:pPr></w:pPrDefault>',
        xml,
        count=1,
    )
    # Body styles: no big gaps between paragraphs.
    # BodyText/FirstParagraph carry question text between figure and options:
    # indent it under the stem text (numbers sit in the HANG-wide column).
    for sid, sp in (("BodyText", f'w:before="0" w:after="0"/><w:ind w:left="{HANG}"'), ("Compact", 'w:before="0" w:after="0" w:line="276" w:lineRule="auto"/><w:ind w:left="0"')):
        pat = re.compile(r'(<w:style [^>]*w:styleId="%s"[\s\S]*?)<w:spacing [^>]*/>' % sid)
        xml = pat.sub(lambda m: m.group(1) + f"<w:spacing {sp}/>", xml, count=1)
    xml = _replace_style(xml, "Heading1", _heading("Heading1", "heading 1", 0, 32, 0, 60, False))
    xml = _replace_style(xml, "Heading2", _heading("Heading2", "heading 2", 1, 28, 60, 40, True))
    xml = _replace_style(xml, "Heading3", _heading("Heading3", "heading 3", 2, 26, 200, 40, True))
    xml = _replace_style(xml, "Table", TABLE_STYLE)
    return xml.replace("</w:styles>", CUSTOM_STYLES + "</w:styles>")


def _patch_document(xml: str) -> str:
    # Page size / margins come from the reference's final sectPr.
    return re.sub(r"<w:sectPr>[\s\S]*?</w:sectPr>", SECT_PR, xml, count=1)


def build_reference(pandoc_exe: str, dest: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="paperlab_ref_") as tmp:
        base = Path(tmp) / "base.docx"
        with open(base, "wb") as fh:
            subprocess.run([pandoc_exe, "--print-default-data-file", "reference.docx"],
                           stdout=fh, check=True, timeout=60)
        with zipfile.ZipFile(base) as zin, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/styles.xml":
                    data = _patch_styles(data.decode("utf-8")).encode("utf-8")
                elif item.filename == "word/document.xml":
                    data = _patch_document(data.decode("utf-8")).encode("utf-8")
                zout.writestr(item, data)


@functools.lru_cache(maxsize=1)
def reference_path(pandoc_exe: str) -> str:
    dest = Path(tempfile.gettempdir()) / "paperlab_reference_v5.docx"
    build_reference(pandoc_exe, dest)
    return str(dest)
