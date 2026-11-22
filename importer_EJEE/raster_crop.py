"""Direct source-pixel crop for EJEE rasters, with no assisted prerequisite.

Native PaperLab tools and their retry gates remain unchanged outside this
importer-only mode. No snapping, vector assistance or expansion is used here.
"""
import math
from pathlib import Path

from PIL import Image


def pixel_box(size, x, y, width, height):
    values = (x, y, width, height)
    if any(isinstance(value, bool) or int(value) != value for value in values):
        raise ValueError("Crop coordinates must be integers")
    x, y, width, height = map(int, values)
    if x < 0 or y < 0 or width < 1 or height < 1:
        raise ValueError("Crop must have positive size and nonnegative origin")
    if x + width > 1000 or y + height > 1000:
        raise ValueError("Crop must fit the 0-1000 grid")
    w, h = size
    return [
        math.floor(x * w / 1000), math.floor(y * h / 1000),
        math.ceil((x + width) * w / 1000),
        math.ceil((y + height) * h / 1000),
    ]


def make_exact_crop(manifest, native):
    from typing import Annotated
    from langchain_core.tools import InjectedToolCallId, tool
    from langgraph.types import Command
    import directory_manager

    @tool
    def exact_crop(
        pdf_path: str, page_number: int, x: int, y: int,
        width: int, height: int, output_filename: str,
        paper_id: int, question_number: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Crop an EJEE source-pixel rectangle with NO automatic edge expansion.

        Available immediately, including the first crop of a new figure.
        Coordinates are integer x,y,width,height on the 0-1000 page grid.
        Use the same filename for refinements. Preview every edge; expand
        deliberately to retain full axis labels and tick values. No snapping,
        resampling, ink deletion or silent box adjustment takes place.
        """
        if paper_id != manifest["paper_id"]:
            raise ValueError("Wrong paper ID")
        filename = directory_manager.safe_component(output_filename, "output_filename")
        item = next(
            (item for item in manifest["items"]
             if str(item["number"]) == str(question_number)), None
        )
        if item is None:
            raise ValueError("Unknown mapped question")
        side = (
            "question" if pdf_path == manifest["question_pdf"]
            else "solution" if pdf_path == manifest.get("solution_pdf") else None
        )
        if side is None or page_number not in item[f"{side}_pages"]:
            raise ValueError("Not a mapped source page")
        import re
        prefix = "qfig" if side == "question" else "sfig"
        if not re.fullmatch(prefix + r"\d+\.png", filename):
            raise ValueError("Wrong-side figure filename")
        pixel_box((1000, 1000), x, y, width, height)
        index = item[f"{side}_pages"].index(page_number)
        evidence = item[f"{side}_rows"][index]["asset_evidence"]
        from importer import sha
        source = Path(evidence["body_png"])
        if sha(source) != evidence["body_sha256"]:
            raise ValueError("Source body hash changed")
        from crop_quality import describe, edge_diagnosis, edge_steps, gap_suggestions, to_grid
        with Image.open(source) as image:
            image = image.convert("RGB")
            box = pixel_box(image.size, x, y, width, height)
            cropped = image.crop(box)
            warning = describe(edge_diagnosis(image, box))
            options = gap_suggestions(image, box)
            if options:
                # Advisory only: measured blank lines in the SOURCE. Nothing
                # is applied; the model must choose and call exact_crop.
                warning += " MEASURED OPTIONS (nearest blank source lines; verify with the preview): " + "; ".join(
                    f"{name} -> x,y,width,height = {to_grid(cand, image.size)}"
                    + (" (keeps content cut by the edge)" if name == "expand"
                       else " (drops a line intruding at the edge)")
                    for name, cand in options.items()) + "."
            touching = edge_diagnosis(image, box)
            if touching:
                # One-edge moves, so a caption above can be dropped while a
                # cut label on another side is kept (combined options can't).
                steps = {k: v for k, v in edge_steps(image, box).items() if k.split("-")[0] in touching}
                if steps:
                    warning += " PER-EDGE OPTIONS (change one edge; chain them on later calls): " + "; ".join(
                        f"{name} -> {to_grid(cand, image.size)}" for name, cand in steps.items()) + "."
        folder = directory_manager.ensure_question_dir(paper_id, question_number)
        destination = folder / "figures" / filename
        cropped.save(destination, format="PNG")
        # Remember the source frame so the completion gate can diagnose edges.
        import json
        sidecar = destination.parent / "_raster_boxes.json"
        boxes = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
        boxes[filename] = {"body_png": str(source), "box": list(box)}
        sidecar.write_text(json.dumps(boxes, indent=1), encoding="utf-8")
        native._record_figure_mode(destination.parent, filename, "exact")
        native.SNAP_LOG.append((paper_id, str(question_number), filename, "exact"))
        return native.image_reply(
            tool_call_id,
            f"Saved source-pixel exact crop. final box: {[x, y, width, height]} "
            f"(boxes are [x, y, width, height]). NO AUTO-EXPANSION. "
            f"Source pixel box: {box}.{warning}",
            f"[Crop preview: {filename}]", destination, native.PAGE_PX,
        )

    return exact_crop


def make_page_image(manifest, native, run):
    """Inspect source pixels/regions at readable scale without saving a figure."""
    from typing import Annotated
    from langchain_core.tools import InjectedToolCallId, tool
    from langgraph.types import Command

    pages = {}
    for item in manifest["items"]:
        for side in ("question", "solution"):
            for row, page in zip(item[f"{side}_rows"], item[f"{side}_pages"], strict=True):
                pages[(manifest[f"{side}_pdf"], page)] = row["asset_evidence"]

    @tool
    def get_page_image(
        pdf_path: str, page_number: int,
        tool_call_id: Annotated[str, InjectedToolCallId],
        x: int = 0, y: int = 0, width: int = 1000, height: int = 1000,
    ) -> Command:
        """Inspect a CURRENT mapped body image or zoom a source region.

        Optional x,y,width,height are on the original body's 0-1000 grid.
        This does not save a qfig/sfig or consume a crop retry. Use it to
        distinguish source damage from a bad crop and locate empty gaps.
        Subsequent exact_crop coordinates still refer to the FULL body,
        never to the zoomed preview.
        """
        from importer import sha
        evidence = pages.get((pdf_path, page_number))
        if evidence is None:
            raise ValueError("Not a mapped source page")
        source = Path(evidence["body_png"])
        if sha(source) != evidence["body_sha256"]:
            raise ValueError("Source body hash changed")
        with Image.open(source) as image:
            image = image.convert("RGB")
            box = pixel_box(image.size, x, y, width, height)
            region = image.crop(box)
            full_size = image.size
        folder = Path(run) / "sources" / "inspection"
        folder.mkdir(parents=True, exist_ok=True)
        # The identity includes source hash and frame: never a stale preview.
        dest = folder / f'{evidence["body_sha256"]}-{x}-{y}-{width}-{height}.png'
        if not dest.exists():
            region.save(dest, format="PNG")
        return native.image_reply(
            tool_call_id,
            f"Source inspection only. Full body dimensions: {full_size}. "
            f"Inspected global box: {[x, y, width, height]}; pixel box: {box}. "
            "All exact_crop coordinates must still use the FULL body's 0-1000 "
            "grid. Inspect whether missing marks exist in the source before "
            "changing crop bounds. No figure was saved.",
            "[Source-region inspection, not a final figure]", dest, native.PAGE_PX,
        )

    return get_page_image
