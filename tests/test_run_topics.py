from types import SimpleNamespace

import database
import directory_manager
import run_topics
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

    report = run_topics.classify_question(pid, "1", replace_auto=True)
    assert report["raw_reply"] == reply.content
    assert report["errors"]
    assert database.get_question_links(qid) == [("PH24.08", 0, "auto")]
    reply.content = "TOPICS: NONE\nDIFFICULTY: NONE\nSUGGESTION: Need the diagram."
    report = run_topics.classify_question(pid, "1", replace_auto=True)
    assert report["codes"] == [] and not report["errors"]
    assert database.get_question_links(qid) == []
