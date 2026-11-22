"""Whole-database book planning: no LLM, no writes to the EJEE source.

A *book* is one ``resources.source``. Every question-bearing row is turned
into exactly one item:

* grouped rows: one item per ``grp`` (ordered q rows + ordered sol rows);
* ungrouped question cards (``part`` NULL, non-concept type): one item per
  row. Their printed key/solution lives inside the same image (``keys``).

Items are ordered by a natural sort of their source label and cut into
"<book> — Part N" papers of ``part_size`` items. The plan is frozen on disk:
re-planning a live, growing database never renumbers an existing plan; new
rows are reported, not silently inserted into prepared parts.

Every item is validated deterministically (asset present and inside the
upload root, decodable raster, valid body box, unambiguous multi-part
order). Failures are recorded as ``blocked`` with a reason -- never dropped
and never guessed.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

PLAN_SCHEMA = "ejee-book-plan/1"

# Actual exam / mock / institute test papers are out of textbook scope.
# Matched against the exact source name (case-insensitive).
EXCLUDED_SOURCES = [
    (r"^ALLEN( NEW)?$", "institute exam/mock papers"),
    (r"^SRI CHAITANYA$", "institute exam/mock papers"),
    (r"^FIITJEE\b", "institute AITS test papers"),
    (r"Q\.PAP", "single exam question paper"),
    (r"^JEE Advanced \d{4} Paper", "actual JEE Advanced paper (upstream seeds these separately)"),
]
CONCEPT_TYPES = {"concept"}


_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}


def _roman(token):
    total = 0
    for a, b in zip(token, token[1:] + " "):
        value = _ROMAN[a]
        total += -value if b != " " and _ROMAN.get(b, 0) > value else value
    return total


def natural_key(text):
    # "(ix)" is a sub-part number: order (iv) < (v) < ... < (ix) < (x).
    text = re.sub(r"\(([ivxlc]+)\)", lambda m: f"({_roman(m.group(1).lower()):04d})",
                  text or "", flags=re.IGNORECASE)
    return [(0, int(tok), "") if tok.isdigit() else (1, 0, tok.lower())
            for tok in re.findall(r"\d+|\D+", text)]


_SPLIT = re.compile(r"\s*\(\s*part\s*(\d+)\s*/\s*(\d+)\s*\)", re.IGNORECASE)


def merge_split_problems(items):
    """Join complete "(part k/m)" families: one printed problem, k images.

    Only complete, unblocked families with identical prefixes merge; anything
    partial stays separate and is flagged so a reviewer sees it.
    """
    families = {}
    for it in items:
        m = _SPLIT.search(it["label"])
        if m:
            families.setdefault(_SPLIT.sub("", it["label"]).strip(), []).append((int(m[1]), int(m[2]), it))
    drop = set()
    for prefix, members in families.items():
        members.sort(key=lambda x: x[0])
        total = members[0][1]
        complete = [k for k, _, _ in members] == list(range(1, total + 1)) and all(m == total for _, m, _ in members)
        if not complete or any(it["blocked"] for _, _, it in members):
            for _, _, it in members:
                it["blocked"] = it["blocked"] or f"incomplete split family '{prefix}'; needs review"
            continue
        head = members[0][2]
        head.update({
            "key": "merge:" + "+".join(it["key"] for _, _, it in members), "label": prefix,
            "groups": [g for _, _, it in members for g in it["groups"]], "kind": "merged",
            "question_ids": [q for _, _, it in members for q in it["question_ids"]],
            "solution_ids": [s for _, _, it in members for s in it["solution_ids"]],
            "has_key": any(it["has_key"] for _, _, it in members),
        })
        drop.update(id(it) for _, _, it in members[1:])
    return [it for it in items if id(it) not in drop]


def exclusion(source):
    for pattern, reason in EXCLUDED_SOURCES:
        if re.search(pattern, source or "", re.IGNORECASE):
            return reason
    return None


def slug(source):
    text = re.sub(r"[^A-Za-z0-9]+", "-", source or "untitled").strip("-").lower()[:60]
    digest = hashlib.sha1((source or "").encode("utf-8")).hexdigest()[:8]
    return f"{text}-{digest}"


def _part_order(row):
    m = re.search(r"\((\d+)\s*/\s*\d+\)", row["title"] or "")
    return (int(m.group(1)) if m else 1, row["position"] or 0, row["id"])


def _row_problem(row, asset_root):
    """Deterministic reason this row cannot be imported, else None."""
    if not row["file_name"]:
        return "no asset file"
    base = Path(asset_root).resolve()
    path = (base / row["file_name"]).resolve()
    if base not in path.parents:
        return "asset path escapes upload root"
    if not path.is_file():
        return f"missing asset {row['file_name']}"
    if not (row["mime"] or "").startswith("image/"):
        return f"non-raster asset ({row['mime']})"
    try:
        meta = json.loads(row["print_meta"] or "{}")
    except ValueError:
        return "unparseable print_meta"
    box = meta.get("box") or meta.get("qbox")
    if not box or len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
        return "no valid body box"
    return None


def load_book(conn, source, asset_root):
    """Return ordered items for one source (blocked items included)."""
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT id,grp,part,type,title,position,file_name,mime,print_meta,answer "
        "FROM resources WHERE source=? ORDER BY id", (source,))]
    groups, singles, ignored = {}, [], {"concept": 0, "orphan_unknown_part": 0}
    for row in rows:
        if row["type"] in CONCEPT_TYPES:
            ignored["concept"] += 1
            continue
        if row["grp"]:
            groups.setdefault(row["grp"], []).append(row)
        elif row["part"] in (None, "", "q"):
            singles.append(row)
        else:
            ignored["orphan_unknown_part"] += 1
    items = []
    for grp, members in groups.items():
        q = sorted((r for r in members if r["part"] == "q"), key=_part_order)
        s = sorted((r for r in members if r["part"] == "sol"), key=_part_order)
        other = [r for r in members if r["part"] not in ("q", "sol")]
        reason = None
        if other:
            reason = f"unsupported part value(s) {sorted({str(r['part']) for r in other})}"
        elif not q:
            reason = "solution rows without a question row"
        elif len(q) > 1 and not all(re.search(r"\(\d+/\d+\)", r["title"] or "") for r in q):
            reason = "multiple question rows without (n/m) order"
        if reason is None:
            for r in q + s:
                problem = _row_problem(r, asset_root)
                if problem:
                    reason = f"resource {r['id']}: {problem}"
                    break
        label = (q[0]["title"] if q else members[0]["title"]) or grp
        items.append({"key": f"grp:{grp}", "label": label, "groups": [grp], "kind": "grouped",
                      "question_ids": [r["id"] for r in q], "solution_ids": [r["id"] for r in s],
                      "has_key": any(r["answer"] for r in q), "blocked": reason})
    for row in singles:
        reason = _row_problem(row, asset_root)
        items.append({"key": f"res:{row['id']}", "label": row["title"] or f"resource {row['id']}",
                      "groups": [], "kind": "card", "question_ids": [row["id"]], "solution_ids": [],
                      "has_key": bool(row["answer"]), "blocked": reason})
    items = merge_split_problems(items)
    # Order: grp IDs encode chapter/exercise/number (printed labels restart per
    # exercise, e.g. two "Q1"s), so grouped-only books sort by grp. Books that
    # mix grouped items with standalone cards share only the printed label.
    labels = [it["label"] for it in items]
    if singles and groups and len(set(labels)) == len(labels):
        ordering = "label"
        items.sort(key=lambda it: (natural_key(it["label"]), it["key"]))
    else:
        ordering = "grp"
        items.sort(key=lambda it: (natural_key(it["groups"][0] if it["groups"] else it["label"]), it["key"]))
    # A genuine duplicate reuses the same source image; repeated labels do not.
    by_file = {}
    files = {r["id"]: r["file_name"] for r in rows}
    for it in items:
        for rid in it["question_ids"]:
            other = by_file.setdefault(files[rid], it["key"])
            if other != it["key"] and not it["blocked"]:
                it["blocked"] = f"same image file as {other}; needs review"
    ignored["ordering"] = ordering
    return items, ignored


def cut_parts(items, part_size):
    if type(part_size) is not int or part_size < 1:
        raise ValueError("part_size must be a positive integer")
    ready = [it for it in items if not it["blocked"]]
    return [ready[i:i + part_size] for i in range(0, len(ready), part_size)]


def plan_book(conn, source, asset_root, part_size, out_dir):
    """Write (or verify) the frozen plan for one book. Returns a summary."""
    out_dir = Path(out_dir)
    path = out_dir / "plan.json"
    items, ignored = load_book(conn, source, asset_root)
    parts = cut_parts(items, part_size)
    summary = {"source": source, "slug": out_dir.name, "items": len(items),
               "ready": sum(1 for it in items if not it["blocked"]),
               "blocked": sum(1 for it in items if it["blocked"]),
               "parts": len(parts), "ignored": ignored,
               "with_solution": sum(1 for it in items if it["solution_ids"] and not it["blocked"]),
               "key_only": sum(1 for it in items if not it["solution_ids"] and it["has_key"] and not it["blocked"]),
               "no_answer": sum(1 for it in items if not it["solution_ids"] and not it["has_key"] and not it["blocked"])}
    plan = {"schema": PLAN_SCHEMA, "source": source, "part_size": part_size,
            "parts": [[it["key"] for it in part] for part in parts],
            "items": {it["key"]: it for it in items}}
    if path.exists():
        frozen = json.loads(path.read_text(encoding="utf-8"))
        old = [k for part in frozen["parts"] for k in part]
        new = [k for part in plan["parts"] for k in part]
        summary["frozen"] = True
        summary["new_since_plan"] = len(set(new) - set(old))
        summary["vanished_since_plan"] = sorted(set(old) - set(new))[:20]
        return summary
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    summary["frozen"] = False
    return summary


def catalog(source_db, asset_root, out_root, part_size=15):
    conn = sqlite3.connect(Path(source_db).resolve().as_uri() + "?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    sources = [r[0] for r in conn.execute(
        "SELECT source FROM resources GROUP BY source ORDER BY count(*) DESC")]
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    report = []
    for source in sources:
        if source is None:
            report.append({"source": None, "status": "skipped", "reason": "row without source"})
            continue
        reason = exclusion(source)
        if reason:
            report.append({"source": source, "status": "excluded", "reason": reason})
            continue
        summary = plan_book(conn, source, asset_root, part_size, out_root / slug(source))
        summary["status"] = "concept-only" if summary["items"] == 0 else "planned"
        report.append(summary)
    conn.close()
    (out_root / "catalog.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


def part_items(conn, plan, part):
    """Rebuild prepare()-shaped items for one frozen part from resource IDs."""
    conn.row_factory = sqlite3.Row
    if not 1 <= part <= len(plan["parts"]):
        raise ValueError(f"Part {part} outside 1..{len(plan['parts'])}")
    out = []
    for local, key in enumerate(plan["parts"][part - 1], start=1):
        spec = plan["items"][key]
        def fetch(ids):
            rows = []
            for rid in ids:
                row = conn.execute("SELECT * FROM resources WHERE id=?", (rid,)).fetchone()
                if row is None or row["source"] != plan["source"]:
                    raise ValueError(f"Planned resource {rid} vanished or moved; re-plan required")
                rows.append(dict(row))
            return rows
        q, s = fetch(spec["question_ids"]), fetch(spec["solution_ids"])
        out.append({"group": spec["groups"][0] if spec["groups"] else spec["key"],
                    "groups": spec["groups"] or [spec["key"]], "merged": False,  # split families are not passages
                    "number": str(local), "source_number": spec["label"], "plan_key": key,
                    "kind": spec["kind"], "question_rows": q, "solution_rows": s,
                    "question_pages": [], "solution_pages": []})
    return out
