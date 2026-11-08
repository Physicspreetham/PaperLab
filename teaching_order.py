"""Deterministic primary assignment using the institution's teaching schedule.

Codes remain identifiers, never chronology. Unmapped concepts and ties require
review; neither model priority nor alphabetical order silently breaks a tie.
"""
from __future__ import annotations

import json
from pathlib import Path

MAPPING_PATH = Path(__file__).with_name("teaching_order.json")
CLASSIFIER_VERSION = "teaching-order-v1"


def load_schedule() -> dict:
    return json.loads(MAPPING_PATH.read_text(encoding="utf-8"))


def select_primary(codes: list[str], schedule: dict | None = None) -> dict:
    schedule = load_schedule() if schedule is None else schedule
    codes = list(dict.fromkeys(codes))
    entries = schedule["topics"]
    missing = [c for c in codes if entries.get(c, {}).get("mapping_status") != "verified"]
    result = {"schedule_version": schedule["version"], "primary": None,
              "supporting": codes, "status": "needs_review", "reason": ""}
    if not codes:
        result["reason"] = "No required concepts identified"
    elif missing:
        result["reason"] = "Unverified teaching order: " + ", ".join(missing)
    else:
        latest = max(entries[c]["teaching_rank"] for c in codes)
        winners = [c for c in codes if entries[c]["teaching_rank"] == latest]
        if len(winners) != 1:
            result["reason"] = "Same teaching slot; review primary: " + ", ".join(winners)
        else:
            result.update(primary=winners[0], supporting=[c for c in codes if c != winners[0]],
                          status="assigned", reason="Latest required concept in teaching schedule")
    return result
