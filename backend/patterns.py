"""Exam patterns for the Model Paper builder (Physics part of each paper).

Ported from the EJEE app (server/patterns.js). JEE Advanced 2009-2025 (Paper 1
and 2) plus the latest JEE Main, BITSAT, NEET, AP/TS EAPCET, KCET and COMEDK
patterns. Section structure and marking schemes were read from the official
papers; `verified` says where each paper's marks come from (the app asks the
user to confirm the ones that are not 'official'). Every number can be edited
per paper after it is created.

A section spec: {type, n, c (marks for a correct answer), neg (negative marks,
positive number), ...extras}
  type: single | multiple | integer | numerical | paragraph | paragraph_numeric
        | matching | matrix | matrix3
  partial: 'tiers' (+3/+2/+1) | 'each' (+1 per correct option) | None
  sets/per/groups: passage groups, e.g. 2 paragraphs x 2 questions
  digits: integer answers 0 to 9
  max: explicit section maximum when it is not n x c (matrix match)
"""
from __future__ import annotations

from typing import Any

# PaperLab question types (questions.qtype) that can fill each section type.
# Each inner list is one acceptable "label set": the first set that has
# questions wins (so integer sections fall back to numerical questions).
QTYPES: dict[str, list[list[str]]] = {
    "single": [["scq"]],
    "multiple": [["msq"]],
    "integer": [["int"], ["num"]],
    "numerical": [["num"], ["int"]],
    "paragraph": [["par-scq"], ["par-mix"]],
    "paragraph_multi": [["par-msq"], ["par-mix"]],
    "paragraph_numeric": [["par-num", "par-int"], ["par-mix"]],
    "matching": [["mtx"]],
    "matrix": [["mtx"]],
    "matrix3": [["mtx"]],
}

# Section types whose questions come as a passage block (one block = several numbers).
GROUPED = {"paragraph", "paragraph_numeric", "matrix3"}

TYPE_NAME = {
    "single": "Single correct",
    "multiple": "One or more correct",
    "integer": "Integer answer",
    "numerical": "Numerical value",
    "paragraph": "Paragraph",
    "paragraph_numeric": "Question stems (numerical)",
    "matching": "Matching list",
    "matrix": "Matrix match",
    "matrix3": "Three-column matching",
}


def _s(type_: str, n: int, c: int, neg: int = 0, **extra: Any) -> dict:
    return {"type": type_, "n": n, "c": c, "neg": neg, **extra}


def _p(year: int, paper: int, verified: str, sections: list[dict]) -> dict:
    return {"id": f"{year}-P{paper}", "year": year, "paper": paper, "verified": verified, "sections": sections}


TIERS = {"partial": "tiers"}
EACH = {"partial": "each"}

PATTERNS: list[dict] = [
    _p(2025, 1, "official", [_s("single", 4, 3, 1), _s("multiple", 3, 4, 2, **TIERS), _s("numerical", 6, 4), _s("matching", 3, 4, 1, sets=3)]),
    _p(2025, 2, "official", [_s("single", 4, 3, 1), _s("multiple", 4, 4, 2, **TIERS), _s("numerical", 8, 4)]),
    _p(2024, 1, "official", [_s("single", 4, 3, 1), _s("multiple", 3, 4, 2, **TIERS), _s("integer", 6, 4), _s("matching", 4, 3, 1, sets=4)]),
    _p(2024, 2, "official", [_s("single", 4, 3, 1), _s("multiple", 3, 4, 2, **TIERS), _s("integer", 6, 4), _s("paragraph_numeric", 4, 3, 0, sets=2, per=2)]),
    _p(2023, 1, "official", [_s("multiple", 3, 4, 2, **TIERS), _s("single", 4, 3, 1), _s("integer", 6, 4), _s("matching", 4, 3, 1, sets=4)]),
    _p(2023, 2, "official", [_s("single", 4, 3, 1), _s("multiple", 3, 4, 2, **TIERS), _s("integer", 6, 4), _s("paragraph_numeric", 4, 3, 0, sets=2, per=2)]),
    _p(2022, 1, "official", [_s("numerical", 8, 3), _s("multiple", 6, 4, 2, **TIERS), _s("matching", 4, 3, 1, sets=4)]),
    _p(2022, 2, "official", [_s("integer", 8, 3, 1, digits=True), _s("multiple", 6, 4, 2, **TIERS), _s("single", 4, 3, 1)]),
    _p(2021, 1, "official", [_s("single", 4, 3, 1), _s("paragraph_numeric", 6, 2, 0, sets=3, per=2), _s("multiple", 6, 4, 2, **TIERS), _s("integer", 3, 4)]),
    _p(2021, 2, "official", [_s("multiple", 6, 4, 2, **TIERS), _s("paragraph_numeric", 6, 2, 0, sets=3, per=2), _s("paragraph", 4, 3, 1, sets=2, per=2), _s("integer", 3, 4)]),
    _p(2020, 1, "official", [_s("single", 6, 3, 1), _s("multiple", 6, 4, 2, **TIERS), _s("numerical", 6, 4)]),
    _p(2020, 2, "official", [_s("integer", 6, 3, 1, digits=True), _s("multiple", 6, 4, 2, **TIERS), _s("numerical", 6, 4)]),
    _p(2019, 1, "official", [_s("single", 4, 3, 1), _s("multiple", 8, 4, 1, **TIERS), _s("numerical", 6, 3)]),
    _p(2019, 2, "official", [_s("multiple", 8, 4, 1, **TIERS), _s("numerical", 6, 3), _s("matching", 4, 3, 1, sets=2, per=2)]),
    _p(2018, 1, "official", [_s("multiple", 6, 4, 2, **TIERS), _s("numerical", 8, 3), _s("paragraph", 4, 3, 1, sets=2, per=2)]),
    _p(2018, 2, "official", [_s("multiple", 6, 4, 2, **TIERS), _s("numerical", 8, 3), _s("matching", 4, 3, 1, sets=4)]),
    _p(2017, 1, "official", [_s("multiple", 7, 4, 2, **EACH), _s("integer", 5, 3, 0, digits=True), _s("matrix3", 6, 3, 1, sets=2, per=3)]),
    _p(2017, 2, "official", [_s("single", 7, 3, 1), _s("multiple", 7, 4, 2, **EACH), _s("paragraph", 4, 3, 0, sets=2, per=2)]),
    _p(2016, 1, "official", [_s("single", 5, 3, 1), _s("multiple", 8, 4, 2, **EACH), _s("integer", 5, 3, 0, digits=True)]),
    _p(2016, 2, "official", [_s("single", 6, 3, 1), _s("multiple", 8, 4, 2, **EACH), _s("paragraph", 4, 3, 0, sets=2, per=2)]),
    _p(2015, 1, "official", [_s("integer", 8, 4, 0, digits=True), _s("multiple", 10, 4, 2), _s("matrix", 2, 8, 0, max=16, rows=4, perRow=2, negRow=1)]),
    _p(2015, 2, "official", [_s("integer", 8, 4, 0, digits=True), _s("multiple", 8, 4, 2), _s("paragraph", 4, 4, 2, sets=2, per=2, multi=True)]),
    _p(2014, 1, "secondary", [_s("multiple", 10, 3), _s("integer", 10, 3, 0, digits=True)]),
    _p(2014, 2, "secondary", [_s("single", 10, 3, 1), _s("paragraph", 6, 3, 1, sets=3, per=2), _s("matching", 4, 3, 1, sets=4)]),
    _p(2013, 1, "quoted", [_s("single", 10, 2), _s("multiple", 5, 4, 1), _s("integer", 5, 4, 1, digits=True)]),
    _p(2013, 2, "quoted", [_s("multiple", 8, 3, 1), _s("paragraph", 8, 3, 1, sets=4, per=2), _s("matching", 4, 3, 1, sets=4)]),
    _p(2012, 1, "confirm", [_s("single", 10, 3, 1), _s("multiple", 5, 4), _s("integer", 5, 4, 0, digits=True)]),
    _p(2012, 2, "confirm", [_s("single", 8, 3, 1), _s("paragraph", 6, 3, 1, sets=3, per=2), _s("multiple", 6, 4, 1)]),
    _p(2011, 1, "confirm", [_s("single", 7, 3, 1), _s("multiple", 4, 4), _s("paragraph", 5, 3, 1, sets=2, groups=[3, 2]), _s("integer", 7, 4, 0, digits=True)]),
    _p(2011, 2, "confirm", [_s("single", 8, 3, 1), _s("multiple", 4, 4), _s("integer", 6, 4, 0, digits=True), _s("matrix", 2, 8, 0, max=16, rows=4, perRow=2)]),
    _p(2010, 1, "confirm", [_s("single", 8, 3, 1), _s("multiple", 5, 3), _s("paragraph", 5, 3, 1, sets=2, groups=[3, 2]), _s("integer", 10, 3, 0, digits=True)]),
    _p(2010, 2, "confirm", [_s("single", 6, 5, 2), _s("integer", 5, 3, 0, digits=True), _s("paragraph", 6, 3, 1, sets=2, per=3), _s("matrix", 2, 8, 0, max=16, rows=4, perRow=2)]),
    _p(2009, 1, "confirm", [_s("single", 8, 3, 1), _s("multiple", 4, 4, 1), _s("paragraph", 6, 4, 1, sets=2, per=3), _s("matrix", 2, 8, 0, max=16, rows=4, perRow=2)]),
    _p(2009, 2, "confirm", [_s("single", 4, 3, 1), _s("multiple", 5, 4, 1), _s("matrix", 2, 8, 0, max=16, rows=4, perRow=2), _s("integer", 8, 4, 0, digits=True)]),
]

# Other competitive exams: latest (2026 session) pattern as published by the exam
# bodies and reported by coaching institutes. verified='published' asks the user to
# confirm against the official bulletin. minutes = the Physics share of the paper.
#   JEE Main     20 MCQ (+4/-1) + 5 numerical (+4/-1)
#   NEET UG      45 MCQ, +4/-1
#   BITSAT       30 MCQ, +3/-1
#   AP/TS EAPCET 40 MCQ, +1, no negative
#   KCET         60 MCQ, +1, no negative
#   COMEDK UGET  60 MCQ, +1, no negative


def _x(family: str, year: int, sections: list[dict], minutes: int, **extra: Any) -> dict:
    pid = "".join(ch for ch in family if ch.isalpha()).upper()
    return {"id": f"{pid}-{year}", "family": family, "exam": family, "year": year, "paper": 1,
            "verified": "published", "sections": sections, "minutes": minutes, **extra}


OTHER: list[dict] = [
    _x("JEE Main", 2026, [_s("single", 20, 4, 1), _s("numerical", 5, 4, 1)], 60, sectionNames=["SECTION A", "SECTION B"]),
    _x("BITSAT", 2026, [_s("single", 30, 3, 1)], 45),
    _x("NEET", 2026, [_s("single", 45, 4, 1)], 60),
    _x("AP EAPCET", 2026, [_s("single", 40, 1)], 45),
    _x("TS EAPCET", 2026, [_s("single", 40, 1)], 45),
    _x("KCET", 2026, [_s("single", 60, 1)], 80),
    _x("COMEDK UGET", 2026, [_s("single", 60, 1)], 60),
]

VERIFIED_NOTE = {
    "published": "Pattern and marking scheme of the latest (2026) notification as published by the exam body and reported by coaching institutes. Please confirm against the official information bulletin.",
    "official": "Section structure and marking scheme read from the official paper.",
    "quoted": "Structure read from the official paper; marking scheme quoted from the official instructions by a published source. Please confirm.",
    "secondary": "Structure read from the official paper; marks from published analyses (the archive copy has no instruction page). Please confirm.",
    "confirm": "Structure read from the official paper; marks and negative marking are from published analyses and memory (the archive copy has no instruction page). Please confirm against the official paper before use.",
}

_WORDS = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE",
          "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN", "SEVENTEEN", "EIGHTEEN", "NINETEEN"]
_TENS = ["", "", "TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY"]


def _words(n: int) -> str:
    if n < len(_WORDS):
        return _WORDS[n]
    if n < 100 and _TENS[n // 10]:
        return _TENS[n // 10] + (f"-{_WORDS[n % 10]}" if n % 10 else "")
    return str(n)


def _word(n: int) -> str:
    return f"{_words(n)} ({n:02d})"


def _max_of(sec: dict) -> int:
    return sec.get("max") or sec["n"] * sec["c"]


def marks_lines(sec: dict) -> list[str]:
    """Marking-scheme wording, as printed on the official instruction pages."""
    t, c, neg = sec["type"], sec["c"], sec["neg"]
    other = f"Negative Marks : −{neg} In all other cases." if neg > 0 else "Zero Marks : 0 In all other cases."
    if t == "multiple":
        lines = ["Answer to each question will be evaluated according to the following marking scheme:",
                 f"Full Marks : +{c} If only (all) the correct option(s) is(are) chosen;"]
        if sec.get("partial") == "tiers":
            lines += [f"Partial Marks : +{c - 1} If all the four options are correct but ONLY three options are chosen;",
                      f"Partial Marks : +{c - 2} If three or more options are correct but ONLY two options are chosen, both of which are correct;",
                      f"Partial Marks : +{c - 3} If two or more options are correct but ONLY one option is chosen and it is a correct option;"]
        elif sec.get("partial") == "each":
            lines.append("Partial Marks : +1 For darkening a bubble corresponding to each correct option, provided NO incorrect option is darkened;")
        lines += ["Zero Marks : 0 If none of the options is chosen (i.e. the question is unanswered);", other]
        if sec.get("partial") == "tiers":
            lines.append("For example, if (A), (B) and (D) are the ONLY three options corresponding to correct answers, choosing ONLY (A), (B) and (D) will get +4 marks; choosing ONLY (A) and (B) will get +2 marks; choosing ONLY (A) will get +1 mark; choosing no option will get 0 marks, and choosing any other option(s) will get −" + str(neg or 2) + " marks.")
        return lines
    if t in ("integer", "numerical"):
        what = "integer" if t == "integer" else "numerical value"
        return ["Answer to each question will be evaluated according to the following marking scheme:",
                f"Full Marks : +{c} If ONLY the correct {what} is entered;",
                *(["Zero Marks : 0 If the question is unanswered;", f"Negative Marks : −{neg} In all other cases."] if neg > 0
                  else ["Zero Marks : 0 In all other cases."])]
    if t == "paragraph_numeric":
        return ["Answer to each question will be evaluated according to the following marking scheme:",
                f"Full Marks : +{c} If ONLY the correct numerical value is entered at the designated place;",
                "Zero Marks : 0 In all other cases."]
    if t == "matrix":
        return ["Marking scheme (for each statement in Column I):",
                f"+{sec.get('perRow', 2)} If only the bubble(s) corresponding to all the correct match(es) is(are) darkened;",
                "0 If none of the bubbles is darkened;",
                f"−{sec['negRow']} In all other cases." if sec.get("negRow") else "No negative marking."]
    return ["Answer to each question will be evaluated according to the following marking scheme:",
            f"Full Marks : +{c} If ONLY the correct option is chosen;",
            "Zero Marks : 0 If none of the options is chosen (i.e. the question is unanswered);", other]


def intro_lines(sec: dict) -> list[str]:
    t, n = sec["type"], sec["n"]
    sets, per = sec.get("sets"), sec.get("per")
    opts = "Each question has FOUR options (A), (B), (C) and (D)."
    if t == "single":
        return [f"This section contains {_word(n)} questions.", f"{opts} ONLY ONE of these four options is the correct answer.", "For each question, choose the option corresponding to the correct answer."]
    if t == "multiple":
        return [f"This section contains {_word(n)} questions.", f"{opts} ONE OR MORE THAN ONE of these four option(s) is(are) correct answer(s).", "For each question, choose the option(s) corresponding to (all) the correct answer(s)."]
    if t == "integer":
        return [f"This section contains {_word(n)} questions.",
                "The answer to each question is a SINGLE DIGIT INTEGER ranging from 0 to 9, BOTH INCLUSIVE." if sec.get("digits") else "The answer to each question is a NON-NEGATIVE INTEGER.",
                "For each question, enter the correct integer corresponding to the answer in the place designated to enter the answer."]
    if t == "numerical":
        return [f"This section contains {_word(n)} questions.", "The answer to each question is a NUMERICAL VALUE.",
                "For each question, enter the correct numerical value of the answer in the place designated to enter the answer. If the numerical value has more than two decimal places, truncate/round-off the value to TWO decimal places."]
    if t == "paragraph":
        head = (f"This section contains {_word(sets)} paragraphs" + (f". Based on each paragraph, there are {_word(per).split(' ')[0]} ({per:02d}) questions" if per else "") + ".") if sets else f"This section contains {_word(n)} questions."
        if sec.get("multi"):
            return [head, f"{opts} ONE OR MORE THAN ONE of these four option(s) is(are) correct answer(s).", "For each question, choose the option(s) corresponding to (all) the correct answer(s)."]
        return [head, f"{opts} ONLY ONE of these four options is the correct answer.", "For each question, choose the option corresponding to the correct answer."]
    if t == "paragraph_numeric":
        return [f"This section contains {_word(sets)} question stems.", f"There are {_word(per)} questions corresponding to each question stem.", "The answer to each question is a NUMERICAL VALUE.",
                "For each question, enter the correct numerical value corresponding to the answer in the designated place. If the numerical value has more than two decimal places, truncate/round-off the value to TWO decimal places."]
    if t == "matching":
        return [f"This section contains {_word(sets or n)} Matching List Sets.", "Each set has ONE Multiple Choice Question.", "Each set has TWO lists: List-I and List-II.",
                "FOUR options are given in each Multiple Choice Question based on List-I and List-II and ONLY ONE of these four options satisfies the condition asked in the Multiple Choice Question."]
    if t == "matrix":
        return [f"This section contains {_word(n)} questions.", "Each question contains statements given in two columns, which have to be matched. The statements in Column I are labelled A, B, C and D, while the statements in Column II are labelled p, q, r, s and t. Any given statement in Column I can have correct matching with ONE OR MORE statement(s) in Column II."]
    if t == "matrix3":
        return [f"This section contains {_word(n)} questions of matching type.", f"This section contains {_word(sets)} tables (each having 3 columns and 4 rows). Based on each table, there are {_word(per).split(' ')[0]} ({per:02d}) questions.", f"{opts} ONLY ONE of these four options is correct.", "For each question, choose the option corresponding to the correct answer."]
    return []


def qtype_sets(sec: dict) -> list[list[str]]:
    """PaperLab qtype label sets that can fill this section."""
    key = sec["type"]
    if key == "paragraph" and sec.get("multi"):
        key = "paragraph_multi"
    return QTYPES[key]


def units_of(sec: dict) -> int:
    """How many blocks fill the section (a passage is one block of several numbers)."""
    if sec["type"] in GROUPED and (sec.get("per") or sec.get("groups")):
        return len(sec.get("groups") or [sec["per"]] * sec["sets"])
    return sec["n"]


def describe(p: dict) -> dict:
    q = 0
    sections = []
    for i, sec in enumerate(p["sections"]):
        mx = _max_of(sec)
        title = (p.get("sectionNames") or [])[i] if p.get("sectionNames") and i < len(p["sectionNames"]) else f"SECTION {i + 1}"
        sections.append({
            **sec, "id": f"S{i + 1}", "title": title, "max": mx, "typeName": TYPE_NAME[sec["type"]],
            "from": q + 1, "to": q + sec["n"], "heading": f"{title} (Maximum Marks: {mx})",
            "instructions": [*intro_lines(sec), *marks_lines(sec)],
            "units": units_of(sec),
        })
        q += sec["n"]
    total = sum(s["max"] for s in sections)
    if p.get("family") and p["family"] != "JEE Advanced":
        return {
            **p, "label": f"{p['family']} {p['year']}", "sections": sections, "questions": q, "total": total,
            "minutes": p.get("minutes") or 60, "note": VERIFIED_NOTE[p["verified"]],
            "general": [
                f"This paper is the Physics part of {p['family']} ({p['year']} pattern), in the same number of questions and marking scheme.",
                "Each section starts with its own instructions and marking scheme. Read them before attempting the section.",
                "Rough work may be done in the space provided or on the blank pages.",
            ],
        }
    modern = p["year"] >= 2013
    return {
        **p, "family": "JEE Advanced", "exam": "JEE Advanced" if modern else "IIT-JEE",
        "label": f"{'JEE Advanced' if modern else 'IIT-JEE'} {p['year']} · Paper {p['paper']}",
        "sections": sections, "questions": q, "total": total, "minutes": 60, "note": VERIFIED_NOTE[p["verified"]],
        "general": [
            f"This paper is the Physics part of {'JEE (Advanced)' if modern else 'IIT-JEE'} {p['year']} Paper {p['paper']}, in the same sections, number of questions and marking scheme.",
            "Each section starts with its own instructions and marking scheme. Read them before attempting the section.",
            "Rough work may be done in the space provided or on the blank pages.",
        ],
    }


ALL: list[dict] = [describe(p) for p in [*PATTERNS, *OTHER]]


def by_id(pattern_id: str) -> dict | None:
    return next((p for p in ALL if p["id"] == pattern_id), None)
