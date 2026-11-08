"""Audit/reorder existing auto tags without LLM calls. Dry-run by default.

python migrate_teaching_order.py --apply --report tmp/teaching-migration.json
This cannot recover concepts omitted by the old three-tag classifier. Use
run_topics.py --refill afterwards for a full reclassification when desired.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import database
from teaching_order import select_primary, CLASSIFIER_VERSION, load_schedule


def migrate(apply: bool = False) -> dict:
    database.init_db()
    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT q.id,q.paper_id,q.question_number,qt.topic_code,qt.src FROM questions q"
            " JOIN question_topics qt ON qt.question_id=q.id ORDER BY q.id,qt.rank,qt.id").fetchall()
        grouped = {}
        for row in rows:
            grouped.setdefault(row["id"], []).append(dict(row))
        backup = None
        if apply:
            backup = str(database.DB_PATH) + ".before-teaching-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".bak"
            with sqlite3.connect(backup) as destination:
                conn.backup(destination)
    finally:
        conn.close()
    report = {"applied": apply, "backup": backup, "items": [], "human_preserved": 0}
    for qid, links in grouped.items():
        codes = [r["topic_code"] for r in links]
        assignment = select_primary(codes)
        human = any(r["src"] == "human" for r in links)
        item = {"question_id": qid, "paper_id": links[0]["paper_id"],
                "number": links[0]["question_number"], "old_codes": codes,
                "human_preserved": human, **assignment}
        report["items"].append(item)
        if human:
            report["human_preserved"] += 1
        elif apply:
            database.save_topic_classification(qid, assignment,
                {"migration": "Existing tags only; old classifier may have omitted required concepts"}, CLASSIFIER_VERSION)
    schedule = load_schedule()
    report["unmapped_topics"] = {c: t for c, t in schedule["topics"].items()
                                  if t["mapping_status"] != "verified"}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", default="tmp/teaching-migration.json")
    args = parser.parse_args()
    report = migrate(args.apply)
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"applied": report["applied"], "questions": len(report["items"]),
                      "human_preserved": report["human_preserved"],
                      "needs_review": sum(r["status"] == "needs_review" for r in report["items"]),
                      "unmapped_topics": len(report["unmapped_topics"]), "report": str(path),
                      "backup": report["backup"]}))
