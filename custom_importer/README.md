# Custom importer (manual path)

For books or papers that are **not** in EJEE: a person or an external agent
(Codex, Claude Code, …) transcribes and crops, and this tool stages the work
into a temp workspace via PaperLab's **own native savers and validators**.
Nothing touches the real archive until an explicit `merge`. Give agents
[SKILL.md](SKILL.md): it covers source planning, transcription, exact crops,
and the review handoff. For source data already mapped in EJEE, use the
[EJEE importer](../importer_EJEE/README.md) instead.

Follow the [main installation guide](../README.md#2-install-and-configure).
From the checkout root, use that Python 3.12 environment (`.venv/bin/python`
on macOS/Linux, `.\.venv\Scripts\python.exe` in PowerShell). Store work in a
separate directory. Run one writer per workspace. Only the optional
`classify` command uses PaperLab's paid model.

## Flow

```
source pages ──(transcribe + crop)──► submit ──► workspace (temp DB + Outputs)
                                                      │ check / fix / classify
                                                      ▼
                                            export ──► .plbundle ──► merge ──► archive
```

One PaperLab paper per textbook part: `<Book> — Part N`, 15 question items
in source order, except the last part. Keep a shared passage together as
one item. The custom tool does not split the source automatically. Start
local numbering at 1 per part; record printed labels, edition and page
references in `source_ref`.

## CLI (run from the repo root; every command prints JSON)

```bash
python -m custom_importer init --workspace work/irodov
python -m custom_importer new-paper --workspace work/irodov \
    --name "Irodov - Problems in General Physics — Part 3" \
    --source "Irodov - Problems in General Physics"
# -> {"paper_id": 1}

python -m custom_importer crop --image page7.png --box 120,340,610,420 \
    --out figs/p3_q4_qfig1.png        # --box x,y,width,height (pixels; --grid for 0-1000)
# -> {"clean": true/false, "edges": {...}, "options": {"expand": [...], "shrink": [...]}}
# "clean": true AND visually complete = accept. Use an option verbatim for the retry.

python -m custom_importer submit --workspace work/irodov --json items.jsonl
# one object per line: paper_id, number, qtype, answer_key?, source_ref?, review_note?,
# question_tex, solution_tex, figures {"qfig1.png": path, "sfig1.png": path}
python -m custom_importer remove --workspace work/irodov --paper 1 --number 4

python -m custom_importer check --workspace work/irodov        # must say "ready": true
python -m custom_importer classify --workspace work/irodov    # optional PaperLab Node 3 (needs META_API_KEY, costs API calls)
python -m custom_importer summary --workspace work/irodov

python -m custom_importer export --workspace work/irodov --out irodov-p3.plbundle --paper 1
python -m paperlab_bundle inspect irodov-p3.plbundle
python -m paperlab_bundle merge irodov-p3.plbundle --target-db physics_archive.db --dry-run --require-reviewed
```

Omit `--paper 1` to export all workspace papers. Optional `--source-file`
on `new-paper` attaches an authorized original PDF or image (repeatable).
Use `--allow-untagged` on the bundle merge only if you intentionally want
to defer tagging to PaperLab. Remove `--dry-run` after review and approval.

Same Python API exists too: `from custom_importer import Workspace, merge`
(`ws = Workspace.open("work/irodov")`; `ws.new_paper(...)`, `ws.submit(...)`,
`ws.check(...)`, `ws.classify(...)`, see docstrings). One workspace per process.

## What `submit` enforces (before anything is stored)

Saving goes through native `submit_question`/`submit_solution`: LaTeX syntax,
figure existence and side rules (`qfig*` in question, `sfig*` in solution),
valid `qtype`. On top of that:

- Answer line `\textbf{Answer: N) ...}`, `Solution for N` heading, every figure
  referenced, subscript repair inside `equation`/`align`, bare-name fixes.
- Missing solution must be exactly `no_solution_found`; a key with no worked
  solution uses `No worked solution supplied in source.`
- Resubmitting the same number **replaces** it, including its figure set.
  Previous files are backed up in the workspace's `revisions/` directory.
- Reports have `"ok"` and `"errors"`; fix reported issues and resubmit.
- `[UNREADABLE]` is preserved for review and blocks `check`; never replace
  it with a guess. Use `review_note` for a real source defect or conflict
  that should accompany an otherwise valid item into the bundle.

## Merge rules

Prefer **export → inspect → dry-run → merge** with the exact same file.
`export` refuses while `check` has problems. For review policy, target paths,
duplicate detection, backups and receipts, see the
[bundle guide](../paperlab_bundle/README.md). `custom_importer merge` remains
a convenience wrapper; only that wrapper also writes the receipt to
`workspace.json`. To publish to a deployed host without shell access, use
the [archivist upload API](../paperlab_bundle/README.md#upload-to-a-deployed-server).

## Transcription essentials (full rules in SKILL.md)

Copy exactly what's printed/handwritten; never solve, correct physics, or
invent answers. Leave out headers/footers/printed labels/stars/key badges.
Math in `$...$` (all paired), options as `\enumerate` items, sub-parts as
`\textbf{(a)}` paragraphs, figures as
`\includegraphics[width=\linewidth]{figures/qfig1.png}`. Classify `qtype` by
required response format (`nni` vs `int` vs `num`, `par-*` for passages),
never by the answer value.

Run the no-key regression suite with `python scripts/test_backend.py -q`.
