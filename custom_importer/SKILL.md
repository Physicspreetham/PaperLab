---
name: paperlab-custom-importer
description: Convert a physics book or question paper into PaperLab yourself (Codex, Claude Code or any agent) by transcribing questions, solutions and figures, submitting them into a TEMP workspace with `python -m custom_importer`, checking them, and merging the workspace into the real PaperLab archive. Use when asked to import, add, transcribe or convert textbook/paper questions into PaperLab without the automatic EJEE pipeline.
---

# PaperLab custom importer

You transcribe; PaperLab's own savers validate and store. Work always goes
into a **temporary workspace**; the real archive changes only at the final
`merge`, after the user agrees.

```
source pages ──(you: read, transcribe, crop)──► submit ──► workspace (temp DB)
                                                              │ check / fix
                                                              ▼
                                                   merge ──► physics_archive.db
```

Run every command from the **repository root** with the project's Python
(`.venv/bin/python` or `.\.venv\Scripts\python.exe`; see the
[installation guide](../README.md#2-install-and-configure)). Every
command prints JSON; exit code 1 means "look at the problems listed".

## 1. Set up

```bash
python -m custom_importer init --workspace work/irodov
python -m custom_importer new-paper --workspace work/irodov \
    --name "Irodov - Problems in General Physics — Part 3" \
    --source "Irodov - Problems in General Physics"
# -> {"paper_id": 1}
```

* **Workspace**: any folder that is NOT the archive or its `Outputs/`
  (refused if it overlaps). One workspace per command/process.
* **Plan before writing.** Record the edition, page ranges, ordered printed
  labels, and corresponding key/solution pages; retain that mapping locally.
  Freeze book parts at **15 question items per paper** (last part may be
  shorter). Count an intact linked passage as one item. Do not renumber an
  exported part when you find a missing or blocked item. Keep a real exam as
  one paper unless asked to split it. Name book parts `<Book> — Part N`.
  `--source` is the book (or institute) name, identical for
  every part. Re-running `new-paper` with the same name+source returns the
  same id (no duplicates).
* **Question numbers** start at `1` per book part. If a passage covers local
  labels 3–5, submit it once as `3-5_paragraph`, resume at 6, and repeat the
  Answer/Solution-for block for each subquestion. Do not cut a passage across
  parts. Put the printed labels, section and source pages in `source_ref`,
  e.g. `Irodov 1.109, question p. 24; solution p. 168`. `--source-file` can
  attach permitted original PDFs/images; never bundle material the owner
  has not authorized for sharing.

## 2. Transcribe (rules learned from the EJEE conversion)

**Transcription, not solving.** Copy exactly what is printed or handwritten:
wording, symbols, signs, values, units, sub/superscripts, option order.
Never solve, correct physics, convert units or invent a missing answer or
step. Illegible text: write `[UNREADABLE]` (the question is then held for
review). Struck-out working is omitted.

Read the complete question and solution pages, not just the OCR layer or a
cutout. If the last line reaches the bottom, check the next source page
before submitting. Keep handwritten working, margin derivations, and inline
corrections in reading order; keep diagram annotations in the crop. For
lookalikes like `$v_S$` versus `$v_5$`, compare clearer glyphs in the same
source. Do not infer a symbol from what the physics “should” say.

Leave out page/card chrome: running headers and footers, the printed problem
number or title, difficulty stars, "KEY (B)" badges, marks/section boxes.
Keep everything that is part of the problem (given data, notes, sub-parts).

LaTeX conventions:

* Math in `$...$`; displays in `$$...$$` or `\begin{equation}`/`align`.
  Pair delimiters, preserve fraction scope, subscripts, precision and units.
  Put numbered displays in `equation` with `\tag{...}`, not `\eqno` or
  `\tag` inside `$$...$$`. No backticks or quotes around math.
* Write the stem on one line per paragraph (don't hard-wrap).
* Options: `\begin{enumerate}` with one `\item` per option, no `A)` labels
  typed (the app adds them).
* Sub-parts: separate paragraphs starting `\textbf{(a)}`, `\textbf{(b)}`.
* Figures: `\includegraphics[width=\linewidth]{figures/qfig1.png}` in the
  question, `figures/sfig1.png` in the solution.

**Solution format** (`solution_tex`):

```latex
\textbf{Answer: 3) B}

\underline{\textbf{Solution for 3}}

<entire worked solution, every step, in source order>
```

* The number after `Answer:` and `Solution for` is the local question number.
* Answer line: copy a supplied key, or an explicit conclusion from the
  matching worked solution. Never promote an intermediate step to an
  answer or reconcile conflicting editions. Preserve conflicting source
  evidence and record a `review_note`. Keep plain text inside the
  bold braces, put any formula after the closing brace:
  `\textbf{Answer: 3)} $v = 2$ m/s`.
* Key but no worked solution: Answer line, then
  `No worked solution supplied in source.`
* No key and no solution: `solution_tex` is exactly `no_solution_found`.
* Printed answer without explicit final value:
  `\textbf{Answer: 3) Not explicitly stated in source.}` then the solution.

**qtype** (classify the required response format, never the answer value):

| code | when |
|---|---|
| `scq` / `msq` | options, one / one-or-more correct (incl. assertion-reason) |
| `nni` | no options; format demands a non-negative whole number |
| `int` | no options; whole number, sign not restricted |
| `num` | no options; general numerical answer (decimals, "correct to 2 decimals") |
| `mtx` | match-the-column with combination options |
| `par-scq` ... `par-mix` | one passage with several sub-questions (`par-mix` if formats differ) |
| `unknown` | proofs, derivations, open written answers, or genuinely unclear |

A computed answer like `7` does not make a question `int`/`nni`.
Read the section instructions/response field if present, even when they are
not included in the transcription.

## 3. Figures

Every diagram, graph, circuit or ray picture of the question or solution must
be cropped: question-side as `qfigN.png`, solution-side as `sfigN.png`
(also when the solution reprints the question's diagram). Crop **original
pixels only**: no redrawing, enhancement, upscaling or re-lettering.

```bash
python -m custom_importer crop --image page7.png --box 120,340,610,420 --out figs/p3_q4_qfig1.png
# --box x,y,width,height in pixels (or on the 0-1000 grid with --grid)
```

The reply lists every edge that **cuts content** and measured `options`:
`expand` (keeps content the edge cut) and `shrink` (drops a neighbouring line
that intrudes). Re-run with one of them verbatim; don't nudge in small steps.
Compare every crop with the **full rendered source page**, not an embedded
image. `"clean": true` is only an edge diagnostic. Require every label,
tick value, unit, arrow, pen mark and curve to be complete; no foreign
text or neighbouring figure; a small white margin. Handwritten labels/arrows
on a drawing stay in the image; separate handwritten working is transcribed.
If a clean rectangle is impossible (figures touching, source clipped), keep
the best faithful crop, add a `review_note`, and show the user what needs
review. Do not redraw, guess, or treat a diagnostic as approval.

## 4. Submit

Write one JSON object per question (a JSON list or JSONL file also works):

```json
{"paper_id": 1, "number": "4", "qtype": "num", "answer_key": "2.5",
 "source_ref": "Irodov 1.109, question p. 24; solution p. 168",
 "question_tex": "A ball ...\n\n\\includegraphics[width=\\linewidth]{figures/qfig1.png}",
 "solution_tex": "\\textbf{Answer: 4) 2.5}\n\n\\underline{\\textbf{Solution for 4}}\n\n...",
 "figures": {"qfig1.png": "figs/p3_q4_qfig1.png"}}
```

(Standard JSON escaping: a LaTeX backslash is `\\`, a line break `\n`.
Writing the file with `json.dump` from Python handles this for you.)

```bash
python -m custom_importer submit --workspace work/irodov --json items.jsonl
```

From Python instead of JSON files:

```python
from custom_importer import Workspace
ws = Workspace.open("work/irodov")
pid = ws.new_paper("Irodov - Problems in General Physics — Part 3", "Irodov - Problems in General Physics")
report = ws.submit(pid, "4", question_tex, solution_tex, qtype="num",
                   figures={"qfig1.png": "figs/p3_q4_qfig1.png"}, answer_key="2.5")
```

Each report has `"ok"` and `"errors"`. Saving uses PaperLab's native
`submit_question`/`submit_solution` (LaTeX syntax, figure existence, side
rules) plus completion checks (Answer line, Solution-for heading, every
figure referenced, key present when `answer_key` is given). Fix what is
reported and **resubmit the same number** (it replaces the old version,
including its figure set; old files are backed up under `revisions/`).
`remove --paper 1 --number 4` deletes one. Before moving on, compare
the saved TeX and every crop against the source, not just the `"ok"` flag.

## 5. Check, tag, merge

```bash
python -m custom_importer check   --workspace work/irodov          # must say "ready": true
python -m custom_importer classify --workspace work/irodov          # optional: PaperLab Node 3 topics
                                                                    #   + difficulty (needs META_API_KEY; costs API calls)
python -m custom_importer summary --workspace work/irodov
python -m custom_importer export --workspace work/irodov --out irodov-part-3.plbundle --paper 1
python -m paperlab_bundle inspect irodov-part-3.plbundle
python -m paperlab_bundle merge irodov-part-3.plbundle --target-db physics_archive.db --dry-run --require-reviewed
```

* **Ask the user before the real merge.** Report the source-to-local count,
  skipped/blocked source items, remaining review notes, and dry-run output.
  After approval, remove `--dry-run` only for the exact bundle and target
  that were approved. If the owner explicitly accepts a source defect,
  report the advisory warning and omit `--require-reviewed` only with
  their approval. Do not suppress `[UNREADABLE]` to make `check` pass.
* Merge refuses when `check` reports anything, when a paper with the same
  name+source already exists in the archive, when the target is not a
  PaperLab archive, or when topics are missing (pass `--allow-untagged` only
  if the user wants to tag later in PaperLab).
* See the [bundle guide](../paperlab_bundle/README.md) for backups, explicit
  target paths and the merge receipt. `--paper ID` on export selects just
  the specified papers. Keep the exact `.plbundle` you previewed.
* After merging, open PaperLab and look at the new papers. Keep the
  workspace until the user is satisfied; it is the record of what was added.

## 6. Don'ts

* Don't write to `physics_archive.db` or its `Outputs/` directly; only `merge`.
* Don't invent, solve or "fix" source content; mark `[UNREADABLE]` and report.
* Don't crop whole pages or text blocks as figures; text is transcribed.
* Don't change PaperLab application code or its math rendering.
* Report source defects you notice (missing text, card starting
  mid-sentence, a figure from another problem) instead of hiding them.
