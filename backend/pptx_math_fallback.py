"""Readable fallback for equations on slides.

Pandoc wraps a slide's whole text box in `mc:AlternateContent` with only a
PowerPoint-2010 `Choice` (native editable equations) and no `Fallback`.
Viewers that do not understand it (WPS Office, LibreOffice, Keynote, web
previews) then drop the entire box, so the question text vanishes.

Here every such box gets a `Fallback`: the same shape with each equation
replaced by a plain-text rendering (Unicode super/subscripts, fractions as
a/b, roots, vectors). PowerPoint still uses the native equations.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

_SUP = dict(zip("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ"))
_SUB = dict(zip("0123456789+-=()aeoxhklmnpst", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜ"))
_ACCENT = {"⃗": "⃗", "→": "⃗", "̂": "̂", "^": "̂", "¯": "̄", "̅": "̅", "˙": "̇", "̇": "̇", "~": "̃"}


def _script(text: str, table: dict, marker: str) -> str:
    if text and all(c in table for c in text):
        return "".join(table[c] for c in text)
    return f"{marker}({text})" if len(text) > 1 else f"{marker}{text}"


def _group(text: str) -> str:
    return text if len(text) <= 1 or re.fullmatch(r"[\w.]+", text) else f"({text})"


def _kids(el, name: str) -> str:
    sub = el.find(M + name)
    return "".join(_lin(c) for c in sub) if sub is not None else ""


def _chr(el, tag: str, default: str) -> str:
    pr = el.find(M + tag + "Pr")
    c = pr.find(M + "chr") if pr is not None else None
    return c.get(M + "val", default) if c is not None else default


def _lin(el) -> str:
    tag = el.tag.replace(M, "")
    if tag == "t":
        return el.text or ""
    if tag == "f":
        return f"{_group(_kids(el, 'num'))}/{_group(_kids(el, 'den'))}"
    if tag == "sSup":
        return _kids(el, "e") + _script(_kids(el, "sup"), _SUP, "^")
    if tag == "sSub":
        return _kids(el, "e") + _script(_kids(el, "sub"), _SUB, "_")
    if tag == "sSubSup":
        return _kids(el, "e") + _script(_kids(el, "sub"), _SUB, "_") + _script(_kids(el, "sup"), _SUP, "^")
    if tag == "rad":
        deg = _kids(el, "deg")
        root = {"": "√", "2": "√", "3": "∛", "4": "∜"}.get(deg, f"{deg}√")
        return root + _group(_kids(el, "e"))
    if tag == "d":
        pr = el.find(M + "dPr")
        def attr(n, d):
            c = pr.find(M + n) if pr is not None else None
            return c.get(M + "val", d) if c is not None else d
        parts = [_kids_el(e) for e in el.findall(M + "e")]
        return attr("begChr", "(") + attr("sepChr", ",").join(parts) + attr("endChr", ")")
    if tag == "nary":
        sub, sup = _kids(el, "sub"), _kids(el, "sup")
        out = _chr(el, "nary", "∫")
        if sub:
            out += _script(sub, _SUB, "_")
        if sup:
            out += _script(sup, _SUP, "^")
        return out + _kids(el, "e")
    if tag == "acc":
        return _kids(el, "e") + _ACCENT.get(_chr(el, "acc", "̂"), "̂")
    if tag == "bar":
        return _kids(el, "e") + "̅"
    if tag in ("limLow", "limUpp"):
        return _kids(el, "e") + _script(_kids(el, "lim"), _SUB if tag == "limLow" else _SUP, "_" if tag == "limLow" else "^")
    if tag in ("rPr", "dPr", "naryPr", "accPr", "radPr", "fPr", "ctrlPr", "sSupPr", "sSubPr", "sSubSupPr", "barPr", "boxPr"):
        return ""
    return "".join(_lin(c) for c in el)


def _kids_el(el) -> str:
    return "".join(_lin(c) for c in el)


def omml_to_text(omml_xml: str) -> str:
    try:
        return _kids_el(ET.fromstring(omml_xml)).strip()
    except ET.ParseError:
        return ""


_MATH = re.compile(r"<a14:m>\s*(<m:oMathPara.*?</m:oMathPara>|<m:oMath .*?</m:oMath>)\s*</a14:m>", re.S)
_ALT = re.compile(r"(<mc:AlternateContent[^>]*>\s*<mc:Choice[^>]*>)(.*?)(</mc:Choice>)(\s*</mc:AlternateContent>)", re.S)


def _plain_run(m: re.Match) -> str:
    text = omml_to_text(m.group(1).replace("<m:oMath ", '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" ', 1)
                        if 'xmlns:m=' not in m.group(1)[:200] else m.group(1)) or "…"
    return f'<a:r><a:rPr lang="en-US" i="1"/><a:t>{escape(text)}</a:t></a:r>'


_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_A14 = "http://schemas.microsoft.com/office/drawing/2010/main"


def _wrap_run(m: re.Match) -> str:
    """Equation outside any AlternateContent (pandoc does this inside tables).

    A bare `a14:m` has no namespace declaration, which makes the slide invalid
    XML (PowerPoint offers to "repair" it). Wrap it as PowerPoint itself does.
    """
    return (
        f'<mc:AlternateContent xmlns:mc="{_MC}"><mc:Choice xmlns:a14="{_A14}" Requires="a14">'
        f"{m.group(0)}</mc:Choice><mc:Fallback>{_plain_run(m)}</mc:Fallback></mc:AlternateContent>"
    )


def add_fallback(slide_xml: str) -> str:
    def repl(m: re.Match) -> str:
        body = m.group(2)
        if "<a14:m>" not in body:
            return m.group(0)
        fb = _MATH.sub(_plain_run, body)
        return f"{m.group(1)}{body}{m.group(3)}<mc:Fallback>{fb}</mc:Fallback>{m.group(4)}"

    out, pos = [], 0
    for m in _ALT.finditer(slide_xml):  # shape-level blocks: add a Fallback shape
        out.append(_MATH.sub(_wrap_run, slide_xml[pos:m.start()]))  # anything else: wrap each run
        out.append(repl(m))
        pos = m.end()
    out.append(_MATH.sub(_wrap_run, slide_xml[pos:]))
    return "".join(out)


def add_math_fallbacks(pptx: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(pptx)) as zin:
        items = [(i, zin.read(i.filename)) for i in zin.infolist()]
    if not any(b"a14:m" in data for _, data in items):
        return pptx
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in items:
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", info.filename) and b"a14:m" in data:
                data = add_fallback(data.decode("utf-8")).encode("utf-8")
            zout.writestr(info, data)
    return out.getvalue()
