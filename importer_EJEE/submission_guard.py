"""Evidence-bound native-save repair. Never infer mathematics from saved TeX.

Only added underscore escapes in matching, ordered display environments may
be reverted, and only when the submitted character was a mathematical
subscript. Literal text arguments, labels, comments and code are protected.
"""
from __future__ import annotations

import hashlib
import re

MATH_ENV = re.compile(
    r"\\begin\{(equation\*?|align\*?|gather\*?|eqnarray\*?|multline\*?)\}"
    r".*?\\end\{\1\}", re.DOTALL
)
LITERAL_ARG = re.compile(
    r"\\(?:text[a-zA-Z]*|mbox|operatorname\*?|label|ref|eqref|url|path)"
    r"\s*\{"
)


def normalize_figure_references(text):
    """Canonicalize ONLY bare generated figure names before native validation.

    Native validation subsequently enforces existence and side ownership.
    Arbitrary paths, unknown files and already-canonical paths are untouched.
    """
    return re.sub(
        r"(\\includegraphics(?:\[[^\]]*\])?\{)([qs]fig\d+\.png)(\})",
        r"\1figures/\2\3", text,
    )


def protected_positions(text):
    positions = set()
    for match in LITERAL_ARG.finditer(text):
        depth = 1
        end = match.end()
        while end < len(text) and depth:
            if text[end] == "\\":
                end += 2
                continue
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
            end += 1
        positions.update(range(match.start(), end))
    for match in re.finditer(r"(?<!\\)%[^\n]*", text):
        positions.update(range(match.start(), match.end()))
    return positions


def restore_save_added_subscripts(submitted, saved):
    """Return (repaired, audit). Unknown/native structural changes fail closed."""
    def environments(text):
        ignored = set()
        for match in re.finditer(
            r"\\begin\{(verbatim|lstlisting|minted)\}.*?\\end\{\1\}"
            r"|\\verb\*?(?P<delimiter>[^a-zA-Z\s]).*?(?P=delimiter)"
            r"|(?<!\\)%[^\n]*", text, re.DOTALL
        ):
            ignored.update(range(match.start(), match.end()))
        return [match for match in MATH_ENV.finditer(text)
                if match.start() not in ignored]

    originals = environments(submitted)
    stored = environments(saved)
    if len(originals) != len(stored):
        return saved, []
    replacements = []
    for before, after in zip(originals, stored):
        original, actual = before.group(), after.group()
        if original == actual:
            continue
        # Verify the ENTIRE environment differs only by the native escaping.
        if re.sub(r"(?<!\\)_", r"\\_", original) != actual:
            continue
        if re.search(r"\\(?:verb|begin\{(?:verbatim|lstlisting|minted))", original):
            continue
        protected = protected_positions(original)
        desired = []
        count = 0
        for index, char in enumerate(original):
            if char == "_" and (index == 0 or original[index - 1] != "\\"):
                subscript = (
                    index not in protected
                    and index > 0
                    and bool(re.match(r"[A-Za-z0-9)}\]]", original[index - 1]))
                    and bool(re.match(r"[A-Za-z0-9{\\]", original[index + 1:index + 2]))
                )
                if subscript:
                    count += 1
                else:
                    desired.append("\\")
            desired.append(char)
        repaired = "".join(desired)
        if count:
            replacements.append((after.start(), after.end(), repaired, count))
    output = saved
    for start, end, value, _ in reversed(replacements):
        output = output[:start] + value + output[end:]
    audit = [
        {
            "kind": "restore_native_save_added_subscript_escapes",
            "subscripts": sum(record[3] for record in replacements),
            "before_sha256": hashlib.sha256(saved.encode()).hexdigest(),
            "after_sha256": hashlib.sha256(output.encode()).hexdigest(),
            "evidence": "exact submitted display environments; native escape-only difference",
        }
    ] if replacements else []
    return output, audit


def guard_saved_submission(pid, number, side, submitted):
    import directory_manager
    from tools_extractor import verify_latex_syntax

    folder = directory_manager.get_question_dir(pid, number)
    path = folder / f"{side}.tex"
    saved = path.read_text(encoding="utf-8")
    repaired, audit = restore_save_added_subscripts(submitted, saved)
    if not audit:
        return
    verdict = verify_latex_syntax.invoke({"latex_string": repaired})
    if verdict != "Valid":
        raise ValueError(f"Importer subscript repair rejected: {verdict}")
    # Changes are atomically written and evidence is kept beside the question.
    import json
    audit_path = folder / "_submission_repairs.json"
    history = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else []
    history.extend({**record, "side": side} for record in audit)
    from importer import dump
    dump(audit_path, history)
    temp = path.with_suffix(".tex.tmp")
    temp.write_text(repaired, encoding="utf-8")
    temp.replace(path)
