import re
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from submission_guard import restore_save_added_subscripts, normalize_figure_references
from bootstrap import REPO

sys.path.insert(0, str(REPO))
from app.render import split_tex, tex_to_markdown
from backend.segments import rich_text


def native_escape(tex):
    # Exact native underscore transform; avoids model/network imports.
    spans = re.compile(
        r"\$\$.*?\$\$|\\\[.*?\\\]|(?<!\\)\$(?:[^$\\]|\\.)*?\$", re.DOTALL
    )
    output, position = [], 0
    for match in spans.finditer(tex):
        output.append(re.sub(r"(?<!\\)_", r"\\_", tex[position:match.start()]))
        output.append(match.group())
        position = match.end()
    output.append(re.sub(r"(?<!\\)_", r"\\_", tex[position:]))
    return "".join(output)


@pytest.mark.parametrize("env", [
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "eqnarray", "eqnarray*", "multline", "multline*",
])
def test_restores_only_evidenced_subscripts(env):
    original = (
        r"file_name $x_1$ \[y_2\] "
        + "\\begin{" + env + "}"
        + r"a_1 = \frac{m_2}{m_{3}} + \text{file_name} + \texttt{a\_b}"
        + "\\end{" + env + "}"
    )
    saved = native_escape(original)
    repaired, audit = restore_save_added_subscripts(original, saved)
    assert r"file\_name $x_1$ \[y_2\]" in repaired
    assert r"a_1 = \frac{m_2}{m_{3}}" in repaired
    assert r"\text{file\_name}" in repaired
    assert r"\texttt{a\_b}" in repaired
    assert audit[0]["subscripts"] == 3
    assert restore_save_added_subscripts(original, repaired) == (repaired, [])
    html = rich_text(tex_to_markdown(repaired))
    maths = [unquote(value) for value in re.findall(r'data-tex="([^"]+)"', html)]
    assert any(r"a_1" in value and r"m_{3}" in value for value in maths)
    assert not any(r"a\_1" in value for value in maths)


@pytest.mark.parametrize("original", [
    r"$x_1$ and $$y_2$$ and \(z_3\) and \[w_4\]",
    r"filename_a and ___ and \texttt{code_name}",
    r"\begin{equation} a\_1 = \text{file\_name} \end{equation}",
    r"\begin{verbatim}\begin{equation}x_1\end{equation}\end{verbatim}",
    r"\verb|\begin{equation}x_1\end{equation}|",
    "% " + r"\begin{equation}x_1\end{equation}",
    r"\begin{enumerate}\item $x_1$ \item $\frac{m_2}{m_3}$\end{enumerate}",
    r"\textbf{Answer: 4)} $\frac{m_1}{m_2}$",
    r"\textit{No solution provided.}",
    r"\begin{equation}x = \text{a_b}\end{equation}",
])
def test_other_types_are_unchanged(original):
    saved = native_escape(original)
    assert restore_save_added_subscripts(original, saved) == (saved, [])


def test_does_not_guess_when_math_changed():
    original = r"\begin{equation}a_1 = m_2\end{equation}"
    saved = r"\begin{equation}a\_1 = m\_3\end{equation}"
    assert restore_save_added_subscripts(original, saved) == (saved, [])
    assert restore_save_added_subscripts(original, saved + saved) == (saved + saved, [])


def test_explicit_subpart_labels_survive_renderer():
    text = (
        "Evaluate these cases:\n\n"
        r"\textbf{(a)} $m_1 = m_2$."
        "\n\n" + r"\textbf{(b)} $m_1 \gg m_2$."
    )
    html = rich_text(tex_to_markdown(text))
    assert "<strong>(a)</strong>" in html
    assert "<strong>(b)</strong>" in html
    assert html.count("<p>") == 3


def test_options_and_tables_keep_renderer_behavior(tmp_path):
    samples = [
        r"\begin{enumerate}\item $x_1$ \item $\frac{m_2}{m_3}$\end{enumerate}",
        r"\begin{tabular}{cc}Name & Value \\ A & $x_1$ \\ B & $x_2$\end{tabular}",
        r"\textbf{Answer: 1)} $\frac{m_1}{m_2}$" + "\n\n" + r"\textit{Printed conclusion.}",
    ]
    for text in samples:
        saved = native_escape(text)
        repaired, audit = restore_save_added_subscripts(text, saved)
        assert not audit
        assert split_tex(saved, tmp_path) == split_tex(repaired, tmp_path)


def test_figure_path_fix_is_narrow_and_idempotent():
    text = (
        r"\includegraphics{qfig1.png} "
        r"\includegraphics[width=\linewidth]{sfig2.png} "
        r"\includegraphics{figures/qfig3.png} "
        r"\includegraphics{../qfig1.png} "
        r"\includegraphics{custom.png} "
        r"\texttt{qfig1.png}"
    )
    fixed = normalize_figure_references(text)
    assert r"\includegraphics{figures/qfig1.png}" in fixed
    assert r"\includegraphics[width=\linewidth]{figures/sfig2.png}" in fixed
    for literal in [
        r"\includegraphics{figures/qfig3.png}", r"\includegraphics{../qfig1.png}",
        r"\includegraphics{custom.png}", r"\texttt{qfig1.png}",
    ]:
        assert literal in fixed
    assert normalize_figure_references(fixed) == fixed
