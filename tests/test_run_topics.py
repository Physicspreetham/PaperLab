from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import database
import directory_manager
import run_topics
from backend.main import app
from backend.routers.inbox import get_inbox
from run_topics import parse_topics_output


def test_topic_parser_preserves_main_and_supporting_order():
    output = "TOPICS: 42, 17\nDIFFICULTY: Hard\nSUGGESTION: NONE"
    parsed = parse_topics_output(output, 296)
    assert parsed["numbers"] == [42, 17]
    assert parsed["suggestion"] is None
    assert not parsed["errors"]


def test_invalid_main_topic_does_not_promote_a_supporting_topic():
    for invalid in ("999", "PH05", ""):
        output = f"TOPICS: {invalid}, 42\nDIFFICULTY: Medium\nSUGGESTION: NONE"
        parsed = parse_topics_output(output, 296)
        assert parsed["numbers"] == []
        assert parsed["difficulty"] == "Medium"
        assert "invalid main topic" in parsed["suggestion"]
        assert parsed["errors"]


def test_insufficient_evidence_keeps_the_review_suggestion():
    output = "TOPICS: NONE\nDIFFICULTY: NONE\nSUGGESTION: The diagram is needed to identify the circuit."
    parsed = parse_topics_output(output, 296)
    assert parsed["numbers"] == []
    assert parsed["difficulty"] is None
    assert parsed["suggestion"] == "The diagram is needed to identify the circuit."


def test_duplicate_or_excess_tags_are_marked_invalid():
    for tags in ("1, 2, 1", "1, 2, 3, 4"):
        reply = f"TOPICS: {tags}\nDIFFICULTY: Medium\nSUGGESTION: NONE"
        assert parse_topics_output(reply, 296)["errors"]


def test_untagged_question_with_missing_evidence_appears_in_inbox(
    tmp_db, tmp_outputs, dummy_pdf, monkeypatch,
):
    pid = database.register_paper(dummy_pdf)
    conn = database.get_connection()
    try:
        conn.execute("INSERT INTO questions (paper_id, question_number) VALUES (?, '1')", (pid,))
        conn.commit()
    finally:
        conn.close()
    qdir = directory_manager.ensure_question_dir(pid, "1")
    (qdir / "question.tex").write_text("Find the value in the circuit shown.", encoding="utf-8")
    note = "The diagram is needed to identify the circuit."
    reply = SimpleNamespace(content=f"TOPICS: NONE\nDIFFICULTY: NONE\nSUGGESTION: {note}")
    monkeypatch.setattr(run_topics, "get_llm", lambda: None)
    monkeypatch.setattr(run_topics, "invoke_with_retry", lambda *_: reply)

    report = run_topics.classify_question(pid, "1")
    assert report["codes"] == []
    assert not report["errors"]
    item, = get_inbox()["items"]
    assert item["number"] == "1"
    assert item["topics"] == []
    assert item["suggestion"] == note


def test_yaml_mode_promotes_latest_selected_topic_without_changing_model_inputs(
    tmp_db, tmp_outputs, tmp_path, dummy_pdf, monkeypatch,
):
    pid = database.register_paper(dummy_pdf)
    database.set_paper_status(pid, "done")
    with database.get_connection() as conn:
        qid = conn.execute(
            "INSERT INTO questions (paper_id, question_number, difficulty) VALUES (?, '1', 'Easy')",
            (pid,),
        ).lastrowid
    qdir = directory_manager.ensure_question_dir(pid, "1")
    (qdir / "question.tex").write_text("Find the value in the circuit shown.", encoding="utf-8")
    cfg = tmp_path / "primary-mode.yaml"
    monkeypatch.setattr(run_topics.config, "CONFIG_PATH", cfg)
    topic_reference = run_topics.build_topic_reference()
    _, by_number = topic_reference
    by_code = {code: n for n, code in by_number.items()}
    # Gravitation is W-40, after electrostatics (W-37) and fluid statics
    # (W-23), although its model reference number is the smallest.
    electrostatic, fluid, gravity = (by_code[c] for c in ("PH13.02", "PH35.01", "PH12.01"))
    picks = [electrostatic, fluid, gravity]
    raw = f"TOPICS: {electrostatic}, {fluid}, {gravity}\nDIFFICULTY: Medium\nSUGGESTION: NONE"
    calls = []

    def respond(_llm, messages):
        calls.append([m.content for m in messages])
        return SimpleNamespace(content=raw)

    monkeypatch.setattr(run_topics, "get_llm", lambda: None)
    monkeypatch.setattr(run_topics, "invoke_with_retry", respond)

    client = TestClient(app)
    for mode, ranked in ((1, picks), (2, [gravity, electrostatic, fluid])):
        cfg.write_text(f"topics:\n  primary_mode: {mode}\n", encoding="utf-8")
        report = run_topics.classify_question(pid, "1", topic_reference)
        assert not report["errors"]
        assert report["primary_mode"] == mode
        assert report["raw_reply"] == raw
        assert report["model_numbers"] == picks
        assert report["numbers"] == ranked
        assert report["codes"] == [by_number[n] for n in ranked]
        assert database.get_question_links(qid) == [
            (by_number[n], rank, "auto") for rank, n in enumerate(ranked)
        ]
        detail = client.get(f"/api/papers/{pid}/questions/1")
        assert detail.status_code == 200
        assert [t["code"] for t in detail.json()["topics"]] == report["codes"]

        primary, supporting = report["codes"][:2]
        for param, code, count in (
            ("main_topic", primary, 1),
            ("main_topic", supporting, 0),
            ("topic", supporting, 1),
        ):
            search = client.get("/api/search", params={param: code})
            assert search.status_code == 200
            assert search.json()["total"] == count
    assert len(calls) == 2 and calls[0] == calls[1]

    database.set_question_topics(qid, [by_number[fluid]], src="human")
    run_topics.classify_question(pid, "1", topic_reference)
    assert database.get_question_links(qid) == [(by_number[fluid], 0, "human")]
    with database.get_connection() as conn:
        assert conn.execute("SELECT difficulty FROM questions WHERE id=?", (qid,)).fetchone()[0] == "Easy"


def test_teaching_weeks_use_existing_codes_and_keep_model_order_for_uncertainty(tmp_db):
    by_number = run_topics.topic_codes_by_number()
    weeks = run_topics._teaching_weeks()
    assert len(weeks) == 296
    assert weeks.keys() == set(by_number.values())
    assert all(1 <= week <= 58 for week in weeks.values())
    assert {code: weeks[code] for code in (
        "PH40.02", "PH40.05", "PH35.01", "PH23.07", "PH17.06", "PH17.03", "PH20.06", "PH20.01",
    )} == {
        "PH40.02": 4, "PH40.05": 31, "PH35.01": 23, "PH23.07": 33,
        "PH17.06": 42, "PH17.03": 45, "PH20.06": 47, "PH20.01": 50,
    }
    by_code = {code: n for n, code in by_number.items()}
    assert weeks["PH41.06"] == weeks["PH24.06"] == 36
    assert weeks["PH34.01"] == weeks["PH22.05"] == 55
    for codes in (("PH01.01", "PH01.06"), ("PH34.01", "PH22.05")):
        picks = [by_code[code] for code in codes]
        assert run_topics._rank_by_teaching_order(picks, by_number) == picks
    picks = [by_code["PH24.01"], by_code["PH41.06"]]
    assert run_topics._rank_by_teaching_order(picks, by_number) == picks[::-1]
    assert run_topics._rank_by_teaching_order([1, 2], {1: "future-code", 2: "PH34.01"}) == [1, 2]


def test_missing_schedule_stops_before_model_call(tmp_outputs, tmp_path, monkeypatch):
    qdir = directory_manager.ensure_question_dir(1, "1")
    (qdir / "question.tex").write_text("Question.", encoding="utf-8")
    with monkeypatch.context() as m:
        m.setattr(run_topics, "TEACHING_ORDER_FILE", tmp_path / "missing.json")
        m.setattr(run_topics, "_teaching_weeks", run_topics._teaching_weeks.__wrapped__)
        m.setattr(run_topics, "get_llm", lambda: pytest.fail("must not call the model"))
        with pytest.raises(FileNotFoundError):
            run_topics.classify_question(1, "1", primary_mode=2)


def test_refill_publishes_clean_abstention_but_never_partial_malformed_tags(
    tmp_db, tmp_outputs, dummy_pdf, monkeypatch,
):
    pid = database.register_paper(dummy_pdf)
    conn = database.get_connection()
    try:
        qid = conn.execute("INSERT INTO questions (paper_id, question_number) VALUES (?, '1')", (pid,)).lastrowid
        conn.commit()
    finally:
        conn.close()
    database.init_topics()
    database.set_question_topics(qid, ["PH24.08"], src="auto")
    qdir = directory_manager.ensure_question_dir(pid, "1")
    (qdir / "question.tex").write_text("Find the value in the circuit shown.", encoding="utf-8")
    reply = SimpleNamespace(content="TOPICS: 1, 9999\nDIFFICULTY: Medium\nSUGGESTION: NONE")
    monkeypatch.setattr(run_topics, "get_llm", lambda: None)
    monkeypatch.setattr(run_topics, "invoke_with_retry", lambda *_: reply)

    report = run_topics.classify_question(pid, "1", replace_auto=True, primary_mode=2)
    assert report["raw_reply"] == reply.content
    assert report["errors"]
    assert database.get_question_links(qid) == [("PH24.08", 0, "auto")]
    reply.content = "TOPICS: NONE\nDIFFICULTY: NONE\nSUGGESTION: Need the diagram."
    report = run_topics.classify_question(pid, "1", replace_auto=True, primary_mode=2)
    assert report["codes"] == [] and not report["errors"]
    assert database.get_question_links(qid) == []
