"""Model Paper builder API: exam patterns + random question picking.

Ported from the EJEE app (server/modelpapers.js). Stateless apart from one small
table that remembers which questions earlier model papers already used, so
"skip questions already used" works across papers. The paper itself (its
sections and questions) lives in the browser, like the Paper Builder drafts.

Section -> question mapping: each pattern section type maps to PaperLab question
types (backend.patterns.QTYPES). A passage (paragraph / table set) is ONE block
that covers several generated numbers, so passage sections pick whole blocks.
"""
from __future__ import annotations

import random
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

import database
import directory_manager
from backend import patterns as P

router = APIRouter()

DEFAULT_WEIGHT = {"Easy": 1, "Medium": 3, "Hard": 6, "Olympiad": 1}
_RANGE = re.compile(r"(\d{1,3})-(\d{1,3})_paragraph$")
_KEY = re.compile(r"Answer\s*:\s*\S", re.I)


# ---------------------------------------------------------------- models

class Options(BaseModel):
    topics: list[str] = Field(default_factory=list)      # topic codes (chapters or subtopics); empty = whole syllabus
    exams: list[str] = Field(default_factory=list)       # papers.exam_type filter
    institutes: list[str] = Field(default_factory=list)  # papers.source_institute filter (raw names)
    difficulty: dict[str, float] = Field(default_factory=dict)
    exclude_used: bool = True
    require_key: bool = True


class PreviewBody(BaseModel):
    pattern: dict
    options: Options = Field(default_factory=Options)


class SectionAsk(BaseModel):
    id: str
    count: int | None = None   # units to draw (default: whatever the section still needs)


class TakenItem(BaseModel):
    paperId: int
    number: str


class GenerateBody(BaseModel):
    pattern: dict
    options: Options = Field(default_factory=Options)
    sections: list[SectionAsk] = Field(default_factory=list)   # empty = every section
    taken: list[TakenItem] = Field(default_factory=list)       # already in the paper (never picked again)
    record: bool = True                                         # remember picks as "used"


# ---------------------------------------------------------------- helpers

def _pattern(raw: dict) -> dict:
    """Re-describe a (possibly user-edited) pattern: instructions follow the marks."""
    secs = raw.get("sections") if isinstance(raw, dict) else None
    if not secs or not isinstance(secs, list):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "pattern has no sections")
    clean = []
    for s in secs:
        if s.get("type") not in P.QTYPES and s.get("type") != "paragraph":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown section type {s.get('type')!r}")
        keep = {k: s[k] for k in ("type", "n", "c", "neg", "partial", "sets", "per", "groups", "digits", "max",
                                  "rows", "perRow", "negRow", "multi") if k in s and s[k] is not None}
        keep["n"], keep["c"], keep["neg"] = int(keep["n"]), int(keep.get("c", 0)), int(keep.get("neg", 0))
        # describe() writes the computed maximum into every section; only matrix
        # sections have a real explicit maximum, the rest follow n x marks.
        if keep.get("type") != "matrix":
            keep.pop("max", None)
        clean.append(keep)
    base = {k: raw[k] for k in ("id", "year", "paper", "verified", "family", "exam", "sectionNames") if k in raw}
    base["sections"] = clean
    if raw.get("minutes"):
        base["minutes"] = int(raw["minutes"])
    return P.describe(base)


def _weights(options: Options) -> dict[str, float]:
    w = dict(DEFAULT_WEIGHT)
    for k, v in (options.difficulty or {}).items():
        try:
            w[k] = max(0.0, float(v))
        except (TypeError, ValueError):
            pass
    return w


def _ensure_used_table(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS model_paper_uses ("
        " paper_id INTEGER NOT NULL, question_number TEXT NOT NULL,"
        " ts TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (paper_id, question_number))"
    )


def _topic_maps(conn) -> tuple[dict[str, str | None], dict[str, str]]:
    """(parent by code, chapter code by topic code)."""
    rows = conn.execute("SELECT code, parent, level FROM topics").fetchall()
    parent = {r["code"]: r["parent"] for r in rows}
    level = {r["code"]: r["level"] for r in rows}
    chapter: dict[str, str] = {}
    for code in parent:
        cur, hops = code, 0
        while cur and level.get(cur) != "chapter" and hops < 8:
            cur, hops = parent.get(cur), hops + 1
        chapter[code] = cur if cur and level.get(cur) == "chapter" else code
    return parent, chapter


def _subtree(parent: dict[str, str | None], roots: list[str]) -> set[str]:
    kids: dict[str, list[str]] = {}
    for c, p in parent.items():
        if p:
            kids.setdefault(p, []).append(c)
    out, stack = set(), [r for r in roots if r in parent]
    while stack:
        c = stack.pop()
        if c in out:
            continue
        out.add(c)
        stack.extend(kids.get(c, []))
    return out


_KEY_CACHE: dict[tuple[int, str], tuple[float, bool]] = {}


def _has_key(paper_id: int, number: str) -> bool:
    """True when the question's solution.tex carries a filed answer."""
    try:
        path = directory_manager.get_question_dir(paper_id, number) / "solution.tex"
        mtime = path.stat().st_mtime
    except (OSError, ValueError):
        return False
    hit = _KEY_CACHE.get((paper_id, number))
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        ok = bool(_KEY.search(path.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        ok = False
    _KEY_CACHE[(paper_id, number)] = (mtime, ok)
    return ok


def _span(number: str, qtype: str) -> int:
    """How many generated numbers one block covers (passage range, else 1)."""
    m = _RANGE.search(str(number))
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a < b <= a + 12:
            return b - a + 1
    return 1


class Pool:
    """Candidate questions for the whole request, loaded once."""

    def __init__(self, conn, options: Options):
        self.conn, self.options = conn, options
        self.parent, self.chapter = _topic_maps(conn)
        self.weights = _weights(options)
        _ensure_used_table(conn)
        self.used = (
            {(r[0], str(r[1])) for r in conn.execute("SELECT paper_id, question_number FROM model_paper_uses")}
            if options.exclude_used else set()
        )
        self.scope = _subtree(self.parent, options.topics) if options.topics else None
        self._rows: list[dict] | None = None

    def rows(self) -> list[dict]:
        if self._rows is not None:
            return self._rows
        o = self.options
        where, args = ["p.status = 'done'"], []
        if o.exams:
            where.append(f"p.exam_type IN ({','.join('?' * len(o.exams))})")
            args += o.exams
        if o.institutes:
            where.append(f"p.source_institute IN ({','.join('?' * len(o.institutes))})")
            args += o.institutes
        rows = [dict(r) for r in self.conn.execute(
            "SELECT q.id, q.paper_id AS paperId, q.question_number AS number, q.qtype, q.difficulty"
            " FROM questions q JOIN papers p ON p.id = q.paper_id WHERE " + " AND ".join(where), args)]
        ids = [r["id"] for r in rows]
        topics: dict[int, list[str]] = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for r in self.conn.execute(
                    f"SELECT question_id, topic_code FROM question_topics WHERE question_id IN ({','.join('?' * len(chunk))})"
                    " ORDER BY rank", chunk):
                topics.setdefault(r["question_id"], []).append(r["topic_code"])
        out = []
        for r in rows:
            tcodes = topics.get(r["id"], [])
            if self.scope is not None and (not tcodes or tcodes[0] not in self.scope):
                continue
            r["topics"] = tcodes
            r["chapter"] = self.chapter.get(tcodes[0], "") if tcodes else ""
            r["count"] = _span(r["number"], r["qtype"])
            out.append(r)
        self._rows = out
        return out

    def weight(self, r: dict) -> float:
        return self.weights.get(r["difficulty"], 1.0) if r.get("difficulty") else 1.0

    def for_section(self, sec: dict, taken: set[tuple[int, str]]) -> list[dict]:
        """Rows that could fill this section: first label set that has questions."""
        free = [r for r in self.rows()
                if (r["paperId"], str(r["number"])) not in taken
                and (r["paperId"], str(r["number"])) not in self.used]
        for labels in P.qtype_sets(sec):
            hit = [r for r in free if r["qtype"] in labels and self.weight(r) > 0]
            if self.options.require_key:
                hit = [r for r in hit if _has_key(r["paperId"], r["number"])]
            if hit:
                return hit
        return []


def _pick(pool: Pool, rows: list[dict], k: int, spread: dict) -> list[dict]:
    """Weighted random pick of k rows, spread over chapters and topics."""
    left, out = list(rows), []
    while len(out) < k and left:
        ws = [pool.weight(r) / (1 + 1.2 * spread["chap"].get(r["chapter"], 0)
                                + 2.5 * spread["topic"].get((r["topics"] or [""])[0], 0)) for r in left]
        r = random.choices(left, weights=ws, k=1)[0]
        left.remove(r)
        out.append(r)
        spread["chap"][r["chapter"]] = spread["chap"].get(r["chapter"], 0) + 1
        top = (r["topics"] or [""])[0]
        spread["topic"][top] = spread["topic"].get(top, 0) + 1
    return out


def _choose(pool: Pool, sec: dict, taken: set, spread: dict, units: int) -> tuple[list[dict], int, str]:
    rows = pool.for_section(sec, taken)
    if sec["type"] in P.GROUPED and (sec.get("per") or sec.get("groups")):
        sizes = (sec.get("groups") or [sec["per"]] * sec["sets"])[:units] if units else []
        chosen: list[dict] = []
        loose = 0
        for g in sizes:
            fit = [r for r in rows if r["count"] == g and r not in chosen]
            got = _pick(pool, fit, 1, spread) or []
            if not got:
                rest = [r for r in rows if r not in chosen]
                got = _pick(pool, rest, 1, spread)
                loose += len(got)
            chosen += got
        note = ""
        if len(chosen) < len(sizes):
            note = f"only {len(chosen)} suitable block{'s' if len(chosen) != 1 else ''} found"
        elif loose:
            note = f"{loose} block{'s' if loose != 1 else ''} do not match the expected passage size"
        return chosen, len(rows), note
    got = _pick(pool, rows, units, spread)
    note = f"only {len(got)} suitable question{'s' if len(got) != 1 else ''} found" if len(got) < units else ""
    return got, len(rows), note


def _item(r: dict) -> dict:
    return {"paperId": r["paperId"], "number": r["number"], "qtype": r["qtype"],
            "difficulty": r["difficulty"], "count": r["count"], "chapter": r["chapter"]}


# ---------------------------------------------------------------- routes

@router.get("/patterns")
def list_patterns() -> dict:
    return {"patterns": P.ALL}


@router.post("/describe")
def describe_pattern(body: dict) -> dict:
    """Instructions/marks for an edited pattern (marks corrected by the user)."""
    return _pattern(body.get("pattern", body))


@router.post("/preview")
def preview(body: PreviewBody) -> dict:
    pat = _pattern(body.pattern)
    conn = database.get_connection()
    try:
        pool = Pool(conn, body.options)
        return {
            "usedCount": len(pool.used),
            "sections": [{"id": s["id"], "wanted": s["units"], "available": len(pool.for_section(s, set()))}
                         for s in pat["sections"]],
        }
    finally:
        conn.close()


@router.post("/generate")
def generate(body: GenerateBody) -> dict:
    pat = _pattern(body.pattern)
    conn = database.get_connection()
    try:
        pool = Pool(conn, body.options)
        taken = {(t.paperId, str(t.number)) for t in body.taken}
        # chapter/topic spread starts from what the paper already holds
        spread: dict = {"chap": {}, "topic": {}}
        by_key = {(r["paperId"], str(r["number"])): r for r in pool.rows()}
        for key in taken:
            r = by_key.get(key)
            if r:
                spread["chap"][r["chapter"]] = spread["chap"].get(r["chapter"], 0) + 1
                top = (r["topics"] or [""])[0]
                spread["topic"][top] = spread["topic"].get(top, 0) + 1
        asks = body.sections or [SectionAsk(id=s["id"]) for s in pat["sections"]]
        out = []
        for ask in asks:
            sec = next((s for s in pat["sections"] if s["id"] == ask.id), None)
            if not sec:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown section {ask.id}")
            units = ask.count if ask.count is not None else sec["units"]
            got, available, note = _choose(pool, sec, taken, spread, max(0, units))
            for r in got:
                taken.add((r["paperId"], str(r["number"])))
            out.append({"id": sec["id"], "wanted": units, "items": [_item(r) for r in got],
                        "available": available, "note": note})
        if body.record:
            _ensure_used_table(conn)
            conn.executemany(
                "INSERT OR IGNORE INTO model_paper_uses (paper_id, question_number) VALUES (?, ?)",
                [(i["paperId"], str(i["number"])) for s in out for i in s["items"]])
            conn.commit()
        return {"sections": out}
    finally:
        conn.close()


class ReleaseBody(BaseModel):
    items: list[TakenItem] = Field(default_factory=list)


@router.post("/release")
def release(body: ReleaseBody) -> dict:
    """Questions that left the paper (swapped, removed, redrawn) are no longer 'used'."""
    conn = database.get_connection()
    try:
        _ensure_used_table(conn)
        conn.executemany("DELETE FROM model_paper_uses WHERE paper_id = ? AND question_number = ?",
                         [(i.paperId, str(i.number)) for i in body.items])
        conn.commit()
        return {"released": len(body.items)}
    finally:
        conn.close()


@router.delete("/used")
def forget_used() -> dict:
    """Forget which questions earlier model papers used."""
    conn = database.get_connection()
    try:
        _ensure_used_table(conn)
        n = conn.execute("SELECT COUNT(*) FROM model_paper_uses").fetchone()[0]
        conn.execute("DELETE FROM model_paper_uses")
        conn.commit()
        return {"cleared": n}
    finally:
        conn.close()
