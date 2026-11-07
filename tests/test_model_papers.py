"""Model paper builder: exam patterns, instructions, and the picking pool."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend import patterns as P
from backend.routers import model_papers as M


def test_known_totals_match_official_papers():
    # JEE Advanced 2025 Paper 1 Physics: 4x3 + 3x4 + 6x4 + 3x4 = 60 marks, 16 questions
    p = P.by_id("2025-P1")
    assert (p["questions"], p["total"]) == (16, 60)
    # 2015 Paper 1 has an explicit matrix maximum (2 questions worth 16)
    p15 = P.by_id("2015-P1")
    assert [s["max"] for s in p15["sections"]] == [32, 40, 16]
    assert P.by_id("NEET-2026")["total"] == 180


def test_every_pattern_has_instructions_and_unique_ids():
    ids = [p["id"] for p in P.ALL]
    assert len(ids) == len(set(ids)) == 41
    for p in P.ALL:
        assert p["general"] and p["minutes"] > 0
        for s in p["sections"]:
            assert s["instructions"] and s["heading"].startswith(s["title"])
            assert s["units"] >= 1


def test_marks_follow_edits_and_instructions_follow_marks():
    p = P.by_id("2025-P1")
    edited = {k: v for k, v in p.items()}
    edited["sections"] = [dict(s) for s in p["sections"]]
    edited["sections"][0]["c"] = 4
    out = M._pattern(edited)
    # stale computed `max` from the original must not survive an edit
    assert out["sections"][0]["max"] == 16
    assert any("+4" in line for line in out["sections"][0]["instructions"])
    assert out["total"] == 64


def test_pattern_rejects_garbage():
    with pytest.raises(HTTPException):
        M._pattern({"sections": [{"type": "nonsense", "n": 1, "c": 1}]})
    with pytest.raises(HTTPException):
        M._pattern({})


def test_units_count_passages_not_sub_questions():
    p = P.by_id("2024-P2")
    para = next(s for s in p["sections"] if s["type"] == "paragraph_numeric")
    assert (para["n"], para["units"]) == (4, 2)   # 2 stems x 2 questions
    p11 = P.by_id("2011-P1")
    assert next(s for s in p11["sections"] if s["type"] == "paragraph")["units"] == 2   # groups [3, 2]


def test_span_of_passage_blocks():
    assert M._span("33-34_paragraph", "par-scq") == 2
    assert M._span("B-31-33_paragraph", "par-num") == 3
    assert M._span("7", "scq") == 1
    assert M._span("40-90_paragraph", "par-scq") == 1   # span too large: treated as one


def test_integer_sections_fall_back_to_numerical_questions():
    sets = P.qtype_sets({"type": "integer"})
    assert sets == [["int"], ["num"]]
    assert P.qtype_sets({"type": "paragraph", "multi": True}) == [["par-msq"], ["par-mix"]]
