"""Importer-specific prompt/tool descriptions without editing upstream files."""
from __future__ import annotations

import re

from bootstrap import ROOT, REPO


def section(text, heading):
    match = re.search(r"^# " + re.escape(heading) + r"\s*$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"Upstream extraction prompt section missing: {heading}")
    next_heading = re.search(r"^# ", text[match.end():], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.start():end].strip()


def _optional_section(text, heading):
    try:
        return section(text, heading)
    except ValueError:
        return ""


def _replace_line(text, pattern, replacement):
    """Replace a whole line literally (no backslash-escape interpretation)."""
    new, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"Upstream prompt line missing: {pattern}")
    return new


def build_prompt(cfg):
    raster = cfg.get("raster_exact_crop", False)
    native = (REPO / "prompts" / "extractor_prompt.md").read_text(encoding="utf-8")
    core = section(native, "CORE DIRECTIVES (NON-NEGOTIABLE)")
    # Key-sheet/paper workflow does not apply to mapped source images.
    core = "\n".join(line for line in core.splitlines() if not line.startswith("4. "))
    core = re.sub(r"^5\. ", "4. ", core, flags=re.MULTILINE)  # keep the list numbered 1..4
    adapter = (ROOT / "prompts" / "mapped_extractor.md").read_text(encoding="utf-8")
    if raster:
        core = _replace_line(
            core, r"^4\. .*",
            "4. **Figure Completeness:** Every diagram, graph, circuit, plot "
            "or ray picture belonging to the CURRENT question/solution must "
            "be cropped to the FIGURE STANDARD and referenced in the correct "
            "TeX file. Use exact_crop directly; qfigN.png for question pages "
            "and sfigN.png for solution pages. Never omit a repeated printed "
            "solution diagram merely because it resembles a question diagram. "
            r"Reference as \includegraphics[width=\linewidth]{figures/qfig1.png} "
            r"or \includegraphics[width=\linewidth]{figures/sfig1.png}.",
        )
        adapter = _replace_line(
            adapter, r"^Crop only actual diagrams,.*",
            "Crop only actual diagrams, never full question/solution bodies. "
            "Use exact_crop directly from the first attempt. Coordinates are "
            "integer x,y,width,height on the CURRENT body image's 0-1000 grid. "
            "Use stable qfigN.png/sfigN.png names, independent per side. "
            "Inspect every preview against the source. Keep all printed "
            "solution text as TeX. Every crop must be referenced, including "
            "diagrams reprinted on solution pages. Follow HANDWRITTEN CONTENT: "
            "transcribe separate working as TeX and keep labels, arrows and "
            "annotations of a drawing inside its crop. No dummy crops.",
        )
    types = section(native, "QUESTION TYPES (read the SECTION header first, not the question alone)")
    start = types.index("Codes for")
    end = types.index("\nA group (")
    # Keep upstream's format-not-answer rule(s) that follow the group line.
    tail = types[end:].split("\n")[2:]
    types = "# NATIVE QUESTION TYPE CODES\n" + types[start:end] + (
        "\n" + "\n".join(tail) if tail else "")
    prompt = "\n\n".join(part for part in [
        "You transcribe already-mapped EJEE textbook question/solution images. "
        "The CURRENT ITEM metadata supplies fixed identity and allowed pages. "
        "Only that item is in scope; images are already supplied.",
        core,
        "# TRANSCRIPTION NOTES\n"
        "Never wrap mathematics in backticks. Flag unreadable symbols rather "
        "than infer them from physics. Put actual answer options in enumerate "
        "with bare item content, never duplicated A)/B) labels. Native saves "
        "are structural validation, not a full TeX compile or fidelity check.",
        types,
        _optional_section(native, "HANDWRITTEN CONTENT"),
        section(native, "FIGURE STANDARD (applies to EVERY figure, no exceptions)"),
        (
            "# DIRECT RASTER CROP PROCEDURE\n"
            "1. Locate the full diagram on the supplied CURRENT source image. "
            "Compute x=1000*left/image_width, y=1000*top/image_height, "
            "width=1000*(right-left)/image_width, height=1000*(bottom-top)/image_height. "
            "These are sizes, not right/bottom corners. Account for the aspect ratio.\n"
            "2. Call exact_crop immediately. The rectangle is saved from "
            "original pixels with NO automatic expansion or resampling. "
            "Reuse the SAME filename for corrections.\n"
            "3. Compare every preview edge against the full source. Include "
            "entire labels, unit parentheses and tick values below/beside axes. "
            "Leave a small clear margin. Exclude neighbouring prose/graphs.\n"
            "4. For clipped content move the relevant edge outward; for foreign "
            "content move it into the empty gap. Do not chase source damage: "
            "call get_page_image with a zoom region if corrections stall; "
            "compare a legible close-up of the source to the crop. Its optional "
            "region uses GLOBAL coordinates; subsequent crops also stay GLOBAL. Never invent "
            "missing marks or claim a source is damaged without inspecting it.\n"
            "5. Crop attempts are bounded per filename. If a clean complete "
            "rectangle is impossible (figures touching, source clipped), keep "
            "the best crop referenced and SAVE the transcription anyway: the "
            "importer holds that figure for human review. Never leave the "
            "question unsaved because of a figure.\n"
            "6. Keep question and solution diagrams separate. Every printed "
            "diagram on either side is required, even if duplicated in the other."
            if raster else section(native, "CROP PROCEDURE (think first, then act)")
        ),
        "# COMPLETE SOLUTION\n"
        "Transcribe every mapped continuation in order, every sentence, equation, "
        "unit, sign, condition and printed conclusion. Never solve or correct "
        "the source. Retain inline mathematics in its sentence and keep each "
        "derivation step with its lead-in/tail. Use blank lines between logical "
        "steps, not around isolated units, subscripts or sentence fragments. "
        "Begin with the Answer line, a blank line, the underlined Solution-for "
        "heading, a blank line, then the entire printed explanation. The "
        "adapter below defines keys/missing solutions and linked source groups.",
        adapter,
    ] if part)
    if cfg.get("paired_submit", cfg.get("raster_exact_crop", False)):
        prompt += (
            "\n\n# SAVING (overrides submit_question/submit_solution wording above)\n"
            "Save with ONE submit_pair call holding both question_latex and "
            "solution_latex. It runs the native question validator/save, then "
            "the native solution validator/save. All rules for submit_question "
            "and submit_solution apply unchanged to each field. If either half "
            "reports NOT SAVED, fix only the reported problems and call "
            "submit_pair again with BOTH fields. All source pages are already "
            "supplied; do not re-request them unless zooming to inspect."
        )
    if cfg.get("raster_exact_crop", False):
        prompt += (
            "\n\n# EJEE RASTER EXACT MODE\n"
            "exact_crop crops the supplied source pixels with NO automatic "
            "expansion. There is no prerequisite: use it for the first crop "
            "and any bounded refinements. You may crop several DIFFERENT figures "
            "in one turn (one call per filename). Replies may list measured "
            "options taken from blank lines in the source; your NEXT exact_crop "
            "for that figure must use one of them VERBATIM. PER-EDGE OPTIONS "
            "change one edge: '<edge>-out' keeps content that edge cut (label, "
            "tick, curve, axis), '<edge>-in' drops a neighbouring line or figure "
            "on that side. Prefer them when edges need different fixes (e.g. "
            "top-in for a caption above, bottom-out for a cut label). MEASURED "
            "OPTIONS 'expand'/'shrink' move every touching edge at once. Do not "
            "nudge edges in small steps. Inspect all labels and tick numbers. "
            "Mechanical edge-clear feedback is NOT visual approval."
        )
    return prompt


DESCRIPTIONS = {
    "get_page_image": (
        "Inspect a mapped source PDF page again. Use only the current item's "
        "allowed PDF path/page. The initial question and all solution images "
        "are already supplied, so do not browse/index the paper."
    ),
    "assisted_crop": (
        "First-stage figure crop using native snapping/stroke assistance. "
        "Integer x,y,width,height on the 0-1000 page grid, not corner coordinates. "
        "Use current mapped pages/ID and stable qfigN.png or sfigN.png names. "
        "Reply contains final box and preview; automatic expansion can include "
        "nearby text. Verify every edge against the source. After 3 unsuccessful "
        "attempts on the SAME filename, use exact_crop rather than repeat guesses."
    ),
    "submit_question": (
        "Validate and save ONLY the current mapped statement, equations, subparts, "
        "options and qfig references under the fixed paper_id/question_number. "
        "Use native qtype codes from the image/adapter. Do not include textbook "
        r"title/printed numbering. Figures must use \includegraphics[width=\linewidth]{figures/qfig1.png}. "
        "Resubmit same ID after NOT SAVED. Saving is "
        "not a fidelity or full compilation check."
    ),
    "submit_solution": (
        "Validate and save the COMPLETE current mapped printed solution with "
        "sfig references only. Call submit_question first. First line is "
        r"\textbf{Answer: <fixed ID>)} followed by a source-supported key/formula; "
        "plain text only inside bold braces. Blank line, "
        r"\underline{\textbf{Solution for <fixed ID>}}, "
        "blank line, then all solution parts in order. "
        r"Figures use \includegraphics[width=\linewidth]{figures/sfig1.png}. "
        "If no printed conclusion exists, say Not explicitly stated in source. "
        "If no mapped solution/key exists, pass no_solution_found. Never solve, "
        "convert units or fabricate a conclusion."
    ),
}


def bind_descriptions(tools, cfg):
    """Copy descriptions only: retain schemas, functions and injection behavior."""
    output = []
    for tool in tools:
        if cfg.get("raster_exact_crop", False) and tool.name == "assisted_crop":
            continue
        description = DESCRIPTIONS.get(tool.name)
        if tool.name == "get_page_image" and cfg.get("raster_exact_crop", False):
            description = (
                "Inspect the CURRENT mapped source body, optionally zooming "
                "x,y,width,height on its GLOBAL 0-1000 grid. Does not create a "
                "figure or consume a crop retry. Use a close-up to check tiny "
                "labels, empty gaps, or suspected source damage. All subsequent "
                "exact_crop coordinates still refer to the FULL source body."
            )
        if tool.name == "exact_crop":
            description = (
                ("Direct raster crop available on the FIRST attempt, with no "
                 "prerequisite. " if cfg.get("raster_exact_crop", False) else
                 "Exact fallback after 3 native assisted_crop attempts for the SAME filename. ")
                + "Integer x,y,width,height on the 0-1000 grid, "
                "stable current-item qfigN/sfigN name. "
                + (
                    "EJEE RASTER MODE: no snapping, resampling, ink deletion or "
                    "automatic edge expansion. The requested rectangle is saved."
                    if cfg.get("raster_exact_crop", False) else
                    "Native mode may auto-expand ink-touching edges; read the "
                    "returned final box and inspect its preview."
                )
                + " Preserve every label, axis unit and tick number with margin."
            )
        output.append(tool.model_copy(update={"description": description}) if description else tool)
    return output


def page_geometry(manifest, item):
    """Describe the actual coordinate frame without guessing diagram bounds."""
    from PIL import Image

    pages = []
    for side in ("question", "solution"):
        for row, page in zip(item[f"{side}_rows"], item[f"{side}_pages"], strict=True):
            with Image.open(row["asset_evidence"]["body_png"]) as image:
                width, height = image.size
            pages.append({
                "side": side, "pdf_path": manifest[f"{side}_pdf"],
                "page_number": page,
                "pixel_width": width, "pixel_height": height,
                "coordinate_frame": "full supplied body image; 0-1000 separately on each axis",
            })
    return pages
