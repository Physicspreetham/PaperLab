"""Places question figures on pandoc-generated slides.

Pandoc's own figure layouts put the options in the picture's placeholder, so
they overlap it. Instead the slides are generated text-only and the figures
are added here as real pictures: text keeps the left column (stem + options),
figures are scaled to fit the right column (stacked if there are several).
A slide with figures but no text gets the figures centred at full width.
"""
from __future__ import annotations

import base64
import io
import re
import zipfile

from PIL import Image

EMU_PX = 9525  # 96 dpi
MAX_UPSCALE = 2.0
GAP = 91440

# Slide geometry (EMU) shared with pptx_reference.py: 10in x 5.625in.
BODY_X, BODY_Y, BODY_H = 457200, 1200151, 3394472
FULL_W = 8229600
TEXT_W = 4100000
FIG_X, FIG_W = 4700000, 3986800

_IMG_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
_EXT = {"PNG": ("png", "image/png"), "JPEG": ("jpeg", "image/jpeg"), "GIF": ("gif", "image/gif")}


def _decode(uri: str):
    """data: URI -> (bytes, ext, mime, w_px, h_px), or None when unusable."""
    m = re.match(r"data:[^;,]*(;base64)?,(.*)$", uri, re.S)
    if not m:
        return None
    try:
        raw = base64.b64decode(m.group(2)) if m.group(1) else m.group(2).encode("latin-1")
        im = Image.open(io.BytesIO(raw))
        fmt, (w, h) = im.format, im.size
    except Exception:
        return None
    if fmt not in _EXT or w < 1 or h < 1:
        return None
    ext, mime = _EXT[fmt]
    return raw, ext, mime, w, h


def _fit(w_px: int, h_px: int, box_w: int, box_h: int) -> tuple[int, int]:
    nat_w, nat_h = w_px * EMU_PX, h_px * EMU_PX
    scale = min(box_w / nat_w, box_h / nat_h, MAX_UPSCALE)
    return int(nat_w * scale), int(nat_h * scale)


def _pic(shape_id: int, rid: str, x: int, y: int, cx: int, cy: int, name: str) -> str:
    return (
        f'<p:pic><p:nvPicPr><p:cNvPr id="{shape_id}" name="{name}" descr=""/>'
        '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
        f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
    )


def add_figures(pptx: bytes, figures: list[list[str]], first_slide: int = 2) -> bytes:
    """`figures[i]` are data: URIs for content slide i (file slide{first_slide+i})."""
    if not any(figures):
        return pptx
    zin = zipfile.ZipFile(io.BytesIO(pptx))
    files = {n: zin.read(n) for n in zin.namelist()}
    infos = {i.filename: i for i in zin.infolist()}
    order = list(files)
    zin.close()
    exts: dict[str, str] = {}
    serial = 0

    for idx, uris in enumerate(figures):
        decoded = [d for d in (_decode(u) for u in uris) if d]
        if not decoded:
            continue
        n = first_slide + idx
        sname, rname = f"ppt/slides/slide{n}.xml", f"ppt/slides/_rels/slide{n}.xml.rels"
        if sname not in files:
            continue
        xml = files[sname].decode("utf-8")
        rels = files[rname].decode("utf-8")
        has_body = 'idx="1"' in xml
        if has_body:
            xml = re.sub(
                r'(<p:ph idx="1"\s*/></p:nvPr></p:nvSpPr>)<p:spPr\s*/>',
                rf'\1<p:spPr><a:xfrm><a:off x="{BODY_X}" y="{BODY_Y}"/><a:ext cx="{TEXT_W}" cy="{BODY_H}"/></a:xfrm></p:spPr>',
                xml, count=1,
            )
            box_x, box_w = FIG_X, FIG_W
            # Long text in the narrower column: tell PowerPoint to shrink it to fit.
            body_chars = sum(len(t) for t in re.findall(r"<a:t>(.*?)</a:t>", xml)[1:])
            if body_chars > 420:
                scale = 85000 if body_chars <= 650 else 70000
                xml = re.sub(
                    r'(<p:ph idx="1"\s*/>.*?<p:txBody>)<a:bodyPr\s*/>',
                    rf'\g<1><a:bodyPr><a:normAutofit fontScale="{scale}" lnSpcReduction="10000"/></a:bodyPr>',
                    xml, count=1, flags=re.S,
                )
        else:
            box_x, box_w = BODY_X, FULL_W
        slot_h = (BODY_H - GAP * (len(decoded) - 1)) // len(decoded)
        pics, y = [], BODY_Y
        for k, (raw, ext, mime, w, h) in enumerate(decoded):
            serial += 1
            media = f"ppt/media/plfig{serial}.{ext}"
            files[media] = raw
            order.append(media)
            exts[ext] = mime
            rid = f"rIdFig{serial}"
            rels = rels.replace("</Relationships>", f'<Relationship Id="{rid}" Type="{_IMG_TYPE}" Target="../media/plfig{serial}.{ext}"/></Relationships>')
            cx, cy = _fit(w, h, box_w, slot_h)
            x = box_x + (box_w - cx) // 2
            pics.append(_pic(900 + serial, rid, x, y + (slot_h - cy) // 2, cx, cy, f"Figure {k + 1}"))
            y += slot_h + GAP
        xml = xml.replace("</p:spTree>", "".join(pics) + "</p:spTree>", 1)
        files[sname], files[rname] = xml.encode("utf-8"), rels.encode("utf-8")

    ct = files["[Content_Types].xml"].decode("utf-8")
    for ext, mime in exts.items():
        if f'Extension="{ext}"' not in ct:
            ct = ct.replace("<Default ", f'<Default Extension="{ext}" ContentType="{mime}" /><Default ', 1)
    files["[Content_Types].xml"] = ct.encode("utf-8")

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in order:
            zout.writestr(infos[name] if name in infos else name, files[name])
    return out.getvalue()
