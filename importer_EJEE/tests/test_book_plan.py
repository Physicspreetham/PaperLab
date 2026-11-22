import json
import sqlite3
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import book_plan  # noqa: E402

META = json.dumps({"box": [0.05, 0.05, 0.95, 0.95]})


def make_db(tmp_path, rows):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    db = tmp_path / "src.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE resources (id INTEGER PRIMARY KEY, source TEXT, grp TEXT, part TEXT,"
              " type TEXT, title TEXT, position INTEGER, file_name TEXT, mime TEXT,"
              " print_meta TEXT, answer TEXT)")
    for i, (source, grp, part, kind, title, answer) in enumerate(rows, start=1):
        name = f"{i}.png"
        Image.new("RGB", (200, 200), "white").save(uploads / name)
        c.execute("INSERT INTO resources VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (i, source, grp, part, kind, title, i, name, "image/png", META, answer))
    c.commit()
    return c, uploads


def test_roman_subparts_sort_numerically():
    labels = ["PE 1.2 (ix)", "PE 1.2 (v)", "PE 1.2 (iv)", "PE 1.2 (x)", "PE 1.10 (i)", "PE 1.2 (i)"]
    assert sorted(labels, key=book_plan.natural_key) == [
        "PE 1.2 (i)", "PE 1.2 (iv)", "PE 1.2 (v)", "PE 1.2 (ix)", "PE 1.2 (x)", "PE 1.10 (i)"]


def test_restarted_labels_are_not_duplicates_and_grp_orders(tmp_path):
    c, up = make_db(tmp_path, [
        ("B", "bk-c2-r1", "q", "objective", "KTG · Q1.", None),
        ("B", "bk-c10-r1", "q", "objective", "KTG · Q1.", None),
        ("B", "bk-c2-r2", "q", "objective", "KTG · Q2.", None),
        ("B", "bk-c2-r2", "sol", "objective", "KTG · Q2.", None),
    ])
    items, ignored = book_plan.load_book(c, "B", up)
    assert [it["key"] for it in items] == ["grp:bk-c2-r1", "grp:bk-c2-r2", "grp:bk-c10-r1"]
    assert not any(it["blocked"] for it in items)
    assert ignored["ordering"] == "grp"


def test_cards_interleave_by_label_and_concepts_are_ignored(tmp_path):
    c, up = make_db(tmp_path, [
        ("I", "ir-1.1", "q", "subjective", "Irodov · 1.1", None),
        ("I", None, None, "objective", "Irodov · 1.2", "(B)"),
        ("I", "ir-1.3", "q", "subjective", "Irodov · 1.3", None),
        ("I", None, None, "concept", "Slide 1", None),
    ])
    items, ignored = book_plan.load_book(c, "I", up)
    assert [it["label"] for it in items] == ["Irodov · 1.1", "Irodov · 1.2", "Irodov · 1.3"]
    assert items[1]["kind"] == "card" and items[1]["has_key"]
    assert ignored["concept"] == 1 and ignored["ordering"] == "label"


def test_split_problem_family_merges_in_part_order(tmp_path):
    c, up = make_db(tmp_path, [
        ("A", "apho-1-2", "q", "olympiad", "APhO 2006 · Q1 Laser (part 2/2)", None),
        ("A", "apho-1-1", "q", "olympiad", "APhO 2006 · Q1 Laser (part 1/2)", None),
        ("A", "apho-2-1", "q", "olympiad", "APhO 2006 · Q2 Spring (part 1/2)", None),
    ])
    items, _ = book_plan.load_book(c, "A", up)
    merged = [it for it in items if it["kind"] == "merged"]
    assert len(merged) == 1 and merged[0]["question_ids"] == [2, 1]
    assert merged[0]["label"] == "APhO 2006 · Q1 Laser"
    incomplete = [it for it in items if "incomplete split family" in (it["blocked"] or "")]
    assert len(incomplete) == 1


def test_genuine_problems_are_blocked_not_dropped(tmp_path):
    c, up = make_db(tmp_path, [
        ("S", "g1", "q", "objective", "Q1", None),
        ("S", "g2", "sol", "objective", "Q2", None),
        ("S", "g3", "q", "objective", "Q3", None),
    ])
    (up / "3.png").unlink()
    items, _ = book_plan.load_book(c, "S", up)
    reasons = {it["key"]: it["blocked"] for it in items}
    assert reasons["grp:g1"] is None
    assert "without a question" in reasons["grp:g2"]
    assert "missing asset" in reasons["grp:g3"]
    parts = book_plan.cut_parts(items, 15)
    assert [[it["key"] for it in p] for p in parts] == [["grp:g1"]]


def test_exam_papers_excluded_textbooks_kept():
    assert book_plan.exclusion("ALLEN") and book_plan.exclusion("FIITJEE AITS 2024")
    assert book_plan.exclusion("JEE Advanced 2021 Paper 1")
    assert not book_plan.exclusion("Hibbeler Dynamics 14e")
    assert not book_plan.exclusion("PYQ+ Mechanics Ch11 Collision")
    assert not book_plan.exclusion("JEE DIGITAL - Rotational Motion")


def test_frozen_plan_is_not_renumbered_when_source_grows(tmp_path):
    c, up = make_db(tmp_path, [("F", f"f-{i}", "q", "objective", f"Q{i}", None) for i in range(1, 5)])
    first = book_plan.plan_book(c, "F", up, 2, tmp_path / "plan")
    plan = json.loads((tmp_path / "plan" / "plan.json").read_text(encoding="utf-8"))
    Image.new("RGB", (200, 200)).save(up / "new.png")
    c.execute("INSERT INTO resources VALUES (99,'F','f-0','q','objective','Q0',0,'new.png','image/png',?,NULL)", (META,))
    again = book_plan.plan_book(c, "F", up, 2, tmp_path / "plan")
    assert first["frozen"] is False and again["frozen"] is True and again["new_since_plan"] == 1
    assert json.loads((tmp_path / "plan" / "plan.json").read_text(encoding="utf-8")) == plan


def test_default_catalog_freezes_fifteen_questions_and_keeps_order(tmp_path):
    c, up = make_db(tmp_path, [
        ("Book", None, None, "objective", f"Q{i}", None) for i in range(1, 33)
    ])
    db = Path(c.execute("PRAGMA database_list").fetchone()[2])
    c.close()
    out = tmp_path / "frozen"
    entry, = book_plan.catalog(db, up, out)
    plan = json.loads((out / entry["slug"] / "plan.json").read_text(encoding="utf-8"))
    assert plan["part_size"] == 15
    assert [len(part) for part in plan["parts"]] == [15, 15, 2]
    assert plan["parts"][1][0] == "res:16" and plan["parts"][2][-1] == "res:32"
