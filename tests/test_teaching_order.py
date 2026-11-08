import json

import database
import run_topics
from teaching_order import select_primary


def test_mirror_wins_over_vectors():
    result = select_primary(["PH01.03", "PH29.02"])
    assert result["primary"] == "PH29.02"
    assert result["supporting"] == ["PH01.03"]


def test_real_schedule_overrides_code_order():
    assert select_primary(["PH12.01", "PH13.01"])["primary"] == "PH12.01"
    assert select_primary(["PH01.07", "PH01.01"])["primary"] == "PH01.01"
    assert select_primary(["PH15.05", "PH15.08"])["primary"] == "PH15.05"


def test_latest_within_chapter():
    assert select_primary(["PH29.01", "PH29.02"])["primary"] == "PH29.02"


def test_ties_unknowns_and_empty_require_review():
    for codes in [[], ["PH01.04", "PH01.05"], ["PH34.01", "PH29.02"], ["new-code"]]:
        result = select_primary(codes)
        assert result["status"] == "needs_review"
        assert result["primary"] is None


def test_json_evidence_and_no_three_topic_truncation():
    parsed = run_topics.parse_topics_output(json.dumps({
        "required_topics": [{"number": i, "evidence": "Specific solution step"} for i in range(1, 6)],
        "difficulty": "Hard"}), 296)
    assert parsed["numbers"] == [1, 2, 3, 4, 5]
    assert not parsed["errors"]
    assert len(parsed["evidence"]) == 5
    assert run_topics.parse_topics_output('{"required_topics":[{"number":1}]}', 296)["errors"]


def test_atomic_assignment_review_and_human_protection(tmp_db):
    database.init_topics()
    conn = database.get_connection()
    with conn:
        pid = conn.execute("INSERT INTO papers(paper_name) VALUES ('test')").lastrowid
        qid = conn.execute("INSERT INTO questions(paper_id,question_number) VALUES (?,'1')", (pid,)).lastrowid
    conn.close()
    assignment = select_primary(["PH01.03", "PH29.02"])
    database.save_topic_classification(qid, assignment, {}, "test")
    assert [r[0] for r in database.get_question_links(qid)] == ["PH29.02", "PH01.03"]
    database.save_topic_classification(qid, select_primary(["PH34.01"]), {}, "test")
    assert database.get_question_links(qid) == []
    database.set_question_topics(qid, ["PH01.01"], src="human")
    database.save_topic_classification(qid, assignment, {}, "test")
    assert [r[0] for r in database.get_question_links(qid)] == ["PH01.01"]


def test_model_pool_filters_primary_not_supporting(tmp_db):
    from backend.routers.model_papers import Pool, Options
    database.init_topics()
    conn = database.get_connection()
    with conn:
        pid = conn.execute("INSERT INTO papers(paper_name,status) VALUES ('test','done')").lastrowid
        qid = conn.execute("INSERT INTO questions(paper_id,question_number,qtype) VALUES (?,'1','scq')", (pid,)).lastrowid
    conn.close()
    database.set_question_topics(qid, ["PH29.02", "PH01.03"], src="auto")
    conn = database.get_connection()
    try:
        assert Pool(conn, Options(topics=["PH01"])).rows() == []
        assert len(Pool(conn, Options(topics=["PH29"])).rows()) == 1
    finally:
        conn.close()


def test_migration_backup_and_review_audit(tmp_db):
    from migrate_teaching_order import migrate
    database.init_topics()
    conn = database.get_connection()
    with conn:
        pid = conn.execute("INSERT INTO papers(paper_name) VALUES ('test')").lastrowid
        ids = [conn.execute("INSERT INTO questions(paper_id,question_number) VALUES (?,?)", (pid, str(i))).lastrowid for i in range(3)]
    conn.close()
    database.set_question_topics(ids[0], ["PH01.03", "PH29.02"], src="auto")
    database.set_question_topics(ids[1], ["PH34.01"], src="auto")
    database.set_question_topics(ids[2], ["PH01.03"], src="human")
    preview = migrate()
    assert preview["backup"] is None
    assert database.get_question_links(ids[0])[0][0] == "PH01.03"
    result = migrate(True)
    from pathlib import Path
    assert Path(result["backup"]).is_file()
    assert database.get_question_links(ids[0])[0][0] == "PH29.02"
    assert database.get_question_links(ids[1]) == []
    assert database.get_question_links(ids[2])[0][0] == "PH01.03"
