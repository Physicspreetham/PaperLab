"""Guard native figure cleanup: accept only exact-white whitespace removal.

Native cleanup runs on a temporary copy. Any proposed component deletion or
nonwhite pixel loss is rejected. This is intentionally stricter than Node 2.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


def cleanup_figure(path):
    from postprocess_figures import postprocess_file

    path = Path(path)
    with Image.open(path) as image:
        before = image.convert("RGB")
    pixels = np.asarray(before)
    with tempfile.TemporaryDirectory(dir=path.parent) as temp:
        candidate_path = Path(temp) / path.name
        before.save(candidate_path)
        native = postprocess_file(candidate_path)
        # Native trim reports contain numpy scalar coordinates.
        native = json.loads(json.dumps(native, default=lambda value: value.item()))
        with Image.open(candidate_path) as image:
            after = image.convert("RGB")
        result = {
            "file": str(path),
            "native": native,
            "before_size": list(before.size),
            "before_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "changed": False,
        }
        if native["peeps_removed"]:
            return {
                **result,
                "review_required": True,
                "reason": "Native proposed deleting border components; content not inferred.",
            }
        if not native["trimmed"]:
            return {**result, "review_required": False, "reason": "No cleanup needed."}
        trim = native["trimmed"]
        x = int(trim.get("left", 0))
        y = int(trim.get("top", 0))
        width, height = after.size
        expected = pixels[y:y + height, x:x + width]
        if not np.array_equal(expected, np.asarray(after)):
            return {
                **result, "review_required": True,
                "reason": "Candidate differs from an exact source-pixel rectangle.",
            }
        keep = np.zeros(pixels.shape[:2], dtype=bool)
        keep[y:y + height, x:x + width] = True
        if np.any(pixels[~keep] != 255):
            return {
                **result, "review_required": True,
                "reason": "Trim would remove nonwhite pixels, including possible faint content.",
            }
        # The original is replaced only after every preservation check passes.
        candidate_path.replace(path)
        return {
            **result,
            "changed": True,
            "review_required": False,
            "reason": "Native trim accepted: only exactly white pixels removed.",
            "after_size": list(after.size),
            "offset": [x, y],
            "after_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }


def cleanup_run(run):
    """Explicit offline phase, after figures export. Does not invoke the model."""
    import json
    from importer import dump

    run = Path(run)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    report = []
    changes = {}
    for item in manifest["items"]:
        folder = run / "Outputs" / str(manifest["paper_id"]) / str(item["number"])
        for path in sorted((folder / "figures").glob("*.png")):
            if not __import__("re").fullmatch(r"[qs]fig\d+\.png", path.name):
                continue
            record = cleanup_figure(path)
            record["question"] = item["number"]
            report.append(record)
            if record["changed"]:
                changes[(str(item["number"]), path.name)] = record
                sidecar = folder / "figures" / "_import_provenance.json"
                if sidecar.exists():
                    evidence = json.loads(sidecar.read_text(encoding="utf-8"))
                    if path.name in evidence:
                        update_evidence(evidence[path.name], record)
                        dump(sidecar, evidence)
    exports = run / "figure_export.json"
    if exports.exists():
        evidence = json.loads(exports.read_text(encoding="utf-8"))
        for entry in evidence:
            record = changes.get((str(entry["question"]), entry["filename"]))
            if record:
                update_evidence(entry, record)
        dump(exports, evidence)
    # Preserve earlier audit entries when the phase is rerun.
    audit = run / "figure_cleanup.json"
    history = json.loads(audit.read_text(encoding="utf-8")) if audit.exists() else []
    dump(audit, history + report)
    return report


def update_evidence(evidence, record):
    evidence["native_cleanup"] = record
    evidence["sha256"] = record["after_sha256"]
    evidence["size"] = record["after_size"]
    box = evidence.get("source_pixel_box")
    if box:
        x, y = record["offset"]
        width, height = record["after_size"]
        evidence["source_pixel_box"] = [
            box[0] + x, box[1] + y, box[0] + x + width, box[1] + y + height
        ]


if __name__ == "__main__":
    import argparse
    import sys
    from bootstrap import ROOT, REPO

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run = (ROOT / args.run_dir).resolve()
    if ROOT not in run.parents or ROOT / "reference" in run.parents:
        raise ValueError("Cleanup run must be inside importer_EJEE, outside reference")
    sys.path.insert(0, str(REPO))
    records = cleanup_run(run)
    print(
        f"{len(records)} figures: "
        f"{sum(r['changed'] for r in records)} safe native trims; "
        f"{sum(r['review_required'] for r in records)} require review."
    )
