"""Lightweight TeX syntax checks and conservative save-time normalization.

This is not a compiler. It distinguishes the syntax PaperLab handles from
opaque identifiers, comments and literal code so repairs do not change them.
"""
from __future__ import annotations

import re

DISPLAY_ENVS = frozenset({"equation", "align", "alignat", "flalign", "gather", "eqnarray", "multline", "displaymath"})
_MATH_ENVS = DISPLAY_ENVS | {"math"}
_PAIR = {r"\[": r"\]", r"\(": r"\)"}
_TEXT = r"text(?:normal|rm|sf|tt|up|it|sl|sc|bf|md)?|mbox"
_OPAQUE = r"label|ref|eqref|pageref|url|path"
_GRAPHIC = r"\\includegraphics(?P<options>\s*\[[^\]]*\])?\s*\{(?P<figure_path>[^{}\n]*)\}"
_TOKENS = re.compile(
    r"(?P<code>\\begin\s*\{(?P<code_env>verbatim\*?|lstlisting|minted)\}[\s\S]*?"
    r"\\end\s*\{(?P=code_env)\}|\\verb(?P<verb_star>\*?)(?P<separator>[^a-zA-Z\s])[^\n]*?(?P=separator))"
    r"|(?P<comment>%[^\n]*)"
    r"|(?P<graphic>" + _GRAPHIC + r")"
    r"|(?P<bad_graphic>\\includegraphics(?![a-zA-Z]))"
    r"|(?P<environment>\\(?P<operation>begin|end)\s*\{(?P<env>[^{}\n]+)\})"
    r"|(?P<group>\\(?P<argument>" + _TEXT + "|" + _OPAQUE + r")\s*\{)"
    r"|(?P<delimiter>\\[()[\]]|\$\$?)"
    r"|\\(?:[a-zA-Z]+|[\s\S])"
    r"|(?P<brace>[{}])|(?P<underscore>_)"
)
_TEXT_ARG = re.compile(rf"(?:{_TEXT})\Z")
_BARE_FIGURE = re.compile(r"[qs]fig\d+\.png\Z")
LOCAL_FIGURE = re.compile(r"figures/([\w.-]+)\Z")


def analyze(tex: str, *, protected: list[tuple[int, int]] | None = None) -> tuple[list[str], list[int]]:
    """Return syntax errors and offsets of unambiguous text underscores."""
    errors, escape = [], []
    environments: list[str] = []
    # A scope ends at a delimiter, the end of a math environment, or at
    # the closing brace of a text/identifier argument.
    scopes: list[tuple[str | int, str, int]] = []
    depth = 0
    for match in _TOKENS.finditer(tex):
        kind = match.lastgroup
        closer, mode, start = scopes[-1] if scopes else (None, "text", 0)
        if protected is not None and kind == "code":
            protected.append(match.span())
        if kind == "group":
            depth += 1  # opening brace is part of the token
            inner = "text" if mode != "opaque" and _TEXT_ARG.fullmatch(match["argument"]) else "opaque"
            scopes.append((depth, inner, match.start()))
        elif kind == "brace":
            if match[0] == "{":
                depth += 1
            elif depth == 0:
                errors.append(f"Unmatched closing brace '}}' at position {match.start()}")
            else:
                if closer == depth:
                    scopes.pop()
                depth -= 1
        elif mode == "opaque":
            continue
        elif kind == "environment":
            env = match["env"]
            if match["operation"] == "begin":
                environments.append(env)
                if env.rstrip("*") in _MATH_ENVS:
                    scopes.append((f"end:{env}", "math", match.start()))
            elif not environments:
                errors.append(f"Stray \\end{{{env}}} with no open environment")
            elif environments[-1] != env:
                errors.append(f"Mismatched environment: expected \\end{{{environments[-1]}}} but found \\end{{{env}}}")
            else:
                environments.pop()
                if closer == f"end:{env}":
                    scopes.pop()
                    if protected is not None:
                        protected.append((start, match.end()))
        elif kind == "delimiter":
            token = match[0]
            if closer == token:
                scopes.pop()
                if protected is not None:
                    protected.append((start, match.end()))
            elif closer == "$" and token == "$$":
                # Two adjacent inline spans: $x$$y$.
                continue
            elif mode != "math" and (token in ("$", "$$") or token in _PAIR):
                scopes.append((_PAIR.get(token, token), "math", match.start()))
            else:
                errors.append(f"Unpaired {token} math delimiter at position {match.start()}")
        elif kind == "underscore" and mode == "text":
            escape.append(match.start())

    if depth:
        errors.append(f"Unmatched opening brace '{{': {depth} unclosed")
    errors.extend(f"Unclosed \\begin{{{env}}}" for env in reversed(environments))
    opening = {closer: opener for opener, closer in _PAIR.items()}
    errors.extend(f"Unpaired {opening.get(closer, closer)} math delimiter; check the start and end of each formula"
                  for closer, mode, _ in reversed(scopes)
                  if mode == "math" and closer in ("$", "$$", *_PAIR.values()))
    return errors, escape


def escape_text_underscores(tex: str) -> str:
    """Escape prose underscores, preserving subscripts and literal arguments."""
    _, offsets = analyze(tex)
    out, start = [], 0
    for i in offsets:
        out.extend((tex[start:i], r"\_"))
        start = i + 1
    return "".join(out) + tex[start:]


def prose_chunks(tex: str):
    """Yield (is_editable, text) chunks without treating literal code as prose."""
    start = 0
    for match in _TOKENS.finditer(tex):
        if match.lastgroup in ("code", "comment"):
            yield True, tex[start:match.start()]
            yield False, match[0]
            start = match.end()
    yield True, tex[start:]


def figure_commands(tex: str):
    """Yield actual includegraphics commands, excluding comments and code."""
    return (m for m in _TOKENS.finditer(tex) if m.lastgroup == "graphic")


def checked_figure_references(tex):
    """Require the local paths used by both the native savers and the reader."""
    errors = []
    paths = []
    for token in _TOKENS.finditer(tex):
        if token.lastgroup == "bad_graphic":
            errors.append("Unsupported figure command: use \\includegraphics{figures/NAME.png} without a star or nested path")
        elif token.lastgroup == "graphic":
            ref = token["figure_path"]
            name = LOCAL_FIGURE.fullmatch(ref)
            if not name or name[1] in {".", ".."}:
                errors.append(f"invalid figure path: {ref!r} -- use figures/NAME.png")
            else:
                paths.append(name[1])
    return list(dict.fromkeys(paths)), errors


def normalize_figure_references(tex: str) -> str:
    """Canonicalize whitespace and generated bare PNG names, never external paths."""
    out, start = [], 0
    for match in figure_commands(tex):
        name = match["figure_path"].strip()
        if _BARE_FIGURE.fullmatch(name):
            name = f"figures/{name}"
        if not LOCAL_FIGURE.fullmatch(name):
            continue
        options = (match["options"] or "").strip()
        out.extend((tex[start:match.start()], f"\\includegraphics{options}{{{name}}}"))
        start = match.end()
    return "".join(out) + tex[start:]
