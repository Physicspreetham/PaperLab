"""Offline crop evidence checks. Flags are review signals, not visual approval."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def edge_margins(image):
    pixels = np.asarray(image.convert("RGB"))
    ink = np.any(pixels < 245, axis=2)
    if not ink.any():
        return None
    ys, xs = np.where(ink)
    return {
        "left": int(xs.min()),
        "top": int(ys.min()),
        "right": int(image.width - 1 - xs.max()),
        "bottom": int(image.height - 1 - ys.max()),
    }


TOUCH_PX = 3


def touching_edges(image):
    margins = edge_margins(image)
    if margins is None:
        return []
    return [edge for edge in ("top", "bottom", "left", "right") if margins[edge] < TOUCH_PX]


def edge_diagnosis(source, box):
    """Per touching edge: does ink continue just OUTSIDE the box in the source?

    Deterministic hint only (never an automatic box change). ``source`` is the
    full body image, ``box`` the pixel box [l, t, r, b] that was cropped.
    """
    crop = source.crop(box)
    width, height = source.size
    l, t, r, b = box
    band_x = max(4, width // 100)
    band_y = max(4, height // 100)
    outside = {
        "top": (l, max(0, t - band_y), r, t),
        "bottom": (l, b, r, min(height, b + band_y)),
        "left": (max(0, l - band_x), t, l, b),
        "right": (r, t, min(width, r + band_x), b),
    }
    result = {}
    for edge in touching_edges(crop):
        strip = outside[edge]
        if strip[2] <= strip[0] or strip[3] <= strip[1]:
            result[edge] = "at the source image border (cannot expand)"
            continue
        pixels = np.asarray(source.crop(strip).convert("RGB"))
        result[edge] = ("ink continues outside" if np.any(pixels < 245, axis=2).any()
                        else "no ink just outside")
    return result


def gap_suggestions(source, box, limit_frac=0.30):
    """Measured alternatives for each touching edge (advisory, never applied).

    For every edge with ink contact, find the nearest fully blank source line
    OUTSIDE the box (expand: keeps cut content) and INSIDE it (shrink: drops an
    intruding line). Returns {"expand": box, "shrink": box} in pixel [l,t,r,b];
    a side that cannot find a blank line within ``limit_frac`` keeps its edge.
    """
    pixels = np.any(np.asarray(source.convert("RGB")) < 245, axis=2)
    height, width = pixels.shape
    l, t, r, b = box
    touching = touching_edges(source.crop(box))
    if not touching:
        return {}

    def blank_row(y, x0, x1):
        return 0 <= y < height and not pixels[y, x0:x1].any()

    def blank_col(x, y0, y1):
        return 0 <= x < width and not pixels[y0:y1, x].any()

    lim_y, lim_x = int(height * limit_frac), int(width * limit_frac)
    pad = 4

    def move(cur, edge, outward):
        l, t, r, b = cur
        if edge == "top":
            ys = range(t - 1, max(-1, t - lim_y), -1) if outward else range(t, min(b, t + lim_y))
            y = next((y for y in ys if blank_row(y, l, r)), None)
            return cur if y is None else [l, max(0, y - pad) if outward else y, r, b]
        if edge == "bottom":
            ys = range(b, min(height, b + lim_y)) if outward else range(b - 1, max(t, b - lim_y), -1)
            y = next((y for y in ys if blank_row(y, l, r)), None)
            return cur if y is None else [l, t, r, min(height, y + pad) if outward else y + 1]
        if edge == "left":
            xs = range(l - 1, max(-1, l - lim_x), -1) if outward else range(l, min(r, l + lim_x))
            x = next((x for x in xs if blank_col(x, t, b)), None)
            return cur if x is None else [max(0, x - pad) if outward else x, t, r, b]
        xs = range(r, min(width, r + lim_x)) if outward else range(r - 1, max(l, r - lim_x), -1)
        x = next((x for x in xs if blank_col(x, t, b)), None)
        return cur if x is None else [l, t, min(width, x + pad) if outward else x + 1, b]

    def settle(outward):
        # One edge at a time, re-checking contact after each move, so a single
        # intruding line is removed by ONE edge instead of shrinking all four.
        cur = [l, t, r, b]
        for _ in range(4):
            edges = touching_edges(source.crop(cur))
            if not edges:
                break
            moved = False
            for edge in ("top", "bottom", "left", "right"):
                if edge in edges:
                    nxt = move(cur, edge, outward)
                    if nxt != cur:
                        cur, moved = nxt, True
                        break
            if not moved:
                break
        return cur

    exp, shr = settle(True), settle(False)
    clamp = lambda v: [max(0, v[0]), max(0, v[1]), min(width, v[2]), min(height, v[3])]
    out = {}
    for name, cand in (("expand", clamp(exp)), ("shrink", clamp(shr))):
        if cand != [l, t, r, b] and cand[2] - cand[0] > 8 and cand[3] - cand[1] > 8:
            out[name] = cand
    return out


def edge_steps(source, box, limit_frac=0.30):
    """Per-edge measured moves to the next fully blank source line.

    For each edge: ``out`` moves outward past ink that touches or lies just
    beyond the edge; ``in`` moves inward past the first band of ink met from
    the edge (e.g. a prose line lying wholly inside the box, which an edge
    check alone cannot see). Each candidate changes ONE edge. Returns
    {"top-in": box, ...} in pixel [l, t, r, b]; advisory only.
    """
    pixels = np.any(np.asarray(source.convert("RGB")) < 245, axis=2)
    height, width = pixels.shape
    l, t, r, b = box
    lim_y, lim_x = int(height * limit_frac), int(width * limit_frac)

    def row_blank(y):
        return not pixels[y, l:r].any()

    def col_blank(x):
        return not pixels[t:b, x].any()

    def inward(positions, blank):
        seen_ink = False
        for p in positions:
            if not blank(p):
                seen_ink = True
            elif seen_ink:
                return p
        return None

    def outward(positions, blank, pad=4):
        # First blank line past the ink, then up to ``pad`` more blank lines
        # of white margin (never into the next ink).
        positions = list(positions)
        for i, p in enumerate(positions):
            if blank(p):
                margin = p
                for q in positions[i + 1:i + 1 + pad]:
                    if not blank(q):
                        break
                    margin = q
                return margin
        return None

    out = {}
    y = inward(range(t, min(b, t + lim_y)), row_blank)
    if y is not None and y > t:
        out["top-in"] = [l, y, r, b]
    y = outward(range(t - 1, max(-1, t - lim_y), -1), row_blank) if not row_blank(t) or (t > 0 and not row_blank(t - 1)) else None
    if y is not None:
        out["top-out"] = [l, max(0, y), r, b]
    y = inward(range(b - 1, max(t, b - lim_y), -1), row_blank)
    if y is not None and y + 1 < b:
        out["bottom-in"] = [l, t, r, y + 1]
    y = outward(range(b, min(height, b + lim_y)), row_blank) if not row_blank(b - 1) or (b < height and not row_blank(b)) else None
    if y is not None:
        out["bottom-out"] = [l, t, r, min(height, y + 1)]
    x = inward(range(l, min(r, l + lim_x)), col_blank)
    if x is not None and x > l:
        out["left-in"] = [x, t, r, b]
    x = outward(range(l - 1, max(-1, l - lim_x), -1), col_blank) if not col_blank(l) or (l > 0 and not col_blank(l - 1)) else None
    if x is not None:
        out["left-out"] = [max(0, x), t, r, b]
    x = inward(range(r - 1, max(l, r - lim_x), -1), col_blank)
    if x is not None and x + 1 < r:
        out["right-in"] = [l, t, x + 1, b]
    x = outward(range(r, min(width, r + lim_x)), col_blank) if not col_blank(r - 1) or (r < width and not col_blank(r)) else None
    if x is not None:
        out["right-out"] = [l, t, min(width, x + 1), b]
    return {k: v for k, v in out.items()
            if v != [l, t, r, b] and v[2] - v[0] > 8 and v[3] - v[1] > 8}


def to_grid(box, size):
    """Pixel [l,t,r,b] -> integer [x,y,width,height] on the 0-1000 grid (covering)."""
    import math
    w, h = size
    x0, y0 = math.floor(box[0] * 1000 / w), math.floor(box[1] * 1000 / h)
    x1, y1 = math.ceil(box[2] * 1000 / w), math.ceil(box[3] * 1000 / h)
    return [x0, y0, min(1000, x1) - x0, min(1000, y1) - y0]


def describe(diagnosis):
    if not diagnosis:
        return " All four edges have a clear margin (this does not prove every label is included)."
    parts = []
    for edge, state in diagnosis.items():
        if state == "ink continues outside":
            advice = ("the box cuts through content: if it belongs to this diagram (label, "
                      "tick, curve, arrow) EXPAND this edge past it; if it is neighbouring "
                      "text or another figure, move this edge INWARD into the blank gap")
        elif state == "no ink just outside":
            advice = "content ends exactly at this edge: expand it slightly for a clear margin"
        else:
            advice = "the source itself ends here; keep it and report source clipping if a label is cut"
        parts.append(f"{edge.upper()}: {state} -> {advice}")
    return (" EDGE CONTACT (must be fixed before completion; reuse the same filename): "
            + "; ".join(parts) + ".")


def approval_errors(records, approvals, current_hashes):
    errors = []
    for crop in records:
        key = f'{crop["question"]}/{crop["filename"]}'
        if not crop["source_pixel_identical"] or not crop["hash_matches_provenance"]:
            errors.append(f"{key}: crop pixels/hash do not match provenance")
        if crop["review_required"] and (
            not current_hashes.get(key) or approvals.get(key) != current_hashes[key]
        ):
            errors.append(
                f"{key}: crop edge review required; approve the reviewed current PNG hash explicitly"
            )
    return errors


def audit_run(run):
    import json
    from importer import dump, sha

    run = Path(run)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    records = []
    for item in manifest["items"]:
        folder = run / "Outputs" / str(manifest["paper_id"]) / str(item["number"]) / "figures"
        sidecar = folder / "_import_provenance.json"
        evidence = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
        for name, source in evidence.items():
            path = folder / name
            with Image.open(path) as image:
                actual = image.convert("RGB")
            with Image.open(source["source_body"]) as image:
                expected = image.convert("RGB").crop(source["source_pixel_box"])
            exact = np.array_equal(np.asarray(actual), np.asarray(expected))
            margins = edge_margins(actual)
            tight = margins is None or min(margins.values()) < 3
            records.append({
                "question": item["number"], "filename": name,
                "source_pixel_identical": exact,
                "hash_matches_provenance": sha(path) == source["sha256"],
                "margins_px": margins,
                "review_required": tight or not exact,
                "note": "Edge checks cannot detect labels omitted entirely outside the crop.",
            })
    dump(run / "crop_quality.json", records)
    return records


if __name__ == "__main__":
    import argparse
    from bootstrap import ROOT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run = (ROOT / args.run_dir).resolve()
    if ROOT not in run.parents or ROOT / "reference" in run.parents:
        raise ValueError("Audit run must be inside importer_EJEE, outside reference")
    records = audit_run(run)
    print(
        f"{len(records)} crops; {sum(r['source_pixel_identical'] for r in records)} "
        f"source-pixel identical; {sum(r['review_required'] for r in records)} edge/evidence flags."
    )
