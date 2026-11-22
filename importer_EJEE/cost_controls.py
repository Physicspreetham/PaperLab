"""Round-trip savers for mapped extraction (no change to validation or pixels).

* ``submit_pair``: one model call saves question then solution through the
  SAME native validators/savers. A question failure never saves a solution;
  each half reports its own verdict, so a failed half is resubmitted.
* ``prune_previews``: when a figure is re-cropped, only the newest preview of
  that filename keeps its image. Older previews become a short text note.
  Source page images and all text/tool history are never touched.
  OPT-IN only (config ``prune_previews: true``): rewriting earlier messages
  invalidates the provider prompt cache from that point, which measured
  costlier than keeping the cached old previews.
"""
from __future__ import annotations

import re

PREVIEW_CAPTION = re.compile(r"^\[Crop preview: (?P<name>[^\]]+)\]$")


def make_submit_pair():
    from langchain_core.tools import tool

    @tool
    def submit_pair(paper_id: int, question_number: str, question_latex: str,
                    solution_latex: str, qtype: str = "unknown") -> str:
        """Save the CURRENT item's question and complete solution in ONE call.

        Runs the native submit_question validator/save first, then the native
        submit_solution validator/save. If the question is NOT SAVED the
        solution is not attempted. Fix only what is reported and call
        submit_pair again with BOTH fields. Use solution_latex exactly
        "no_solution_found" only when the source has no solution and no key.

        Args:
            paper_id: Fixed paper ID from metadata.
            question_number: Fixed question_number from metadata (string).
            question_latex: Full question.tex content.
            solution_latex: Full solution.tex content (Answer line first).
            qtype: Native qtype code.
        """
        raise RuntimeError("submit_pair is executed by the importer loop")

    return submit_pair


_INVOKE = re.compile(r'<(?P<ns>[A-Za-z_]+):invoke\s+name="(?:[\w-]+\.)?(?P<name>[\w-]+)"\s*>(?P<body>.*?)</(?P=ns):invoke>', re.S)
_PARAM = r'<{ns}:parameter\s+name="(?P<key>[\w-]+)"\s*>(?P<value>.*?)</{ns}:parameter>'


def recover_text_tool_calls(text, allowed):
    """Parse tool calls a model wrote as TEXT markup instead of structured calls.

    Only exact ``<ns:invoke name="...">`` / ``<ns:parameter name="...">``
    markup is recognised, only allowed tool names are returned, and values are
    passed through unchanged to the SAME native validators. Returns a list of
    {"name", "args"}; empty when nothing matches.
    """
    calls = []
    for match in _INVOKE.finditer(text or ""):
        name = match.group("name")
        if name not in allowed:
            continue
        args = {}
        for p in re.finditer(_PARAM.format(ns=re.escape(match.group("ns"))), match.group("body"), re.S):
            value = p.group("value")
            args[p.group("key")] = int(value) if p.group("key") in ("paper_id", "page_number", "x", "y", "width", "height") and value.strip().lstrip("-").isdigit() else value
        calls.append({"name": name, "args": args})
    return calls


def prune_previews(messages):
    """Strip image blocks from all but the latest preview of each figure."""
    latest = {}
    for index, message in enumerate(messages):
        name = _preview_name(message)
        if name:
            latest[name] = index
    pruned = 0
    for index, message in enumerate(messages):
        name = _preview_name(message)
        if name and latest[name] != index and any(_is_image(b) for b in message.content):
            message.content = [
                {"type": "text", "text": f"[Older preview of {name} removed; newest preview kept below.]"}
            ]
            pruned += 1
    return pruned


def _preview_name(message):
    content = getattr(message, "content", None)
    if getattr(message, "type", None) != "human" or not isinstance(content, list) or not content:
        return None
    first = content[0]
    if isinstance(first, dict) and first.get("type") == "text":
        match = PREVIEW_CAPTION.match(first.get("text", ""))
        if match:
            return match.group("name")
    return None


def _is_image(block):
    return isinstance(block, dict) and block.get("type") == "image_url"
