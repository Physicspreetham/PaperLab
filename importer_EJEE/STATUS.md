# Status: EJEE → PaperLab importers

Historical handoff from the November 2026 EJEE pilots. For current setup and
commands, use the [EJEE importer README](README.md). This snapshot preserves
the pilot evidence, changes and costs (USD, INR, INR incl. 18% GST).
Rupee figures use ₹92.89 per USD (22 Nov 2026).

## 1. What exists

| Piece | Folder | Purpose |
|---|---|---|
| EJEE textbook importer | `importer_EJEE/` | Books already in the EJEE database → PaperLab papers named `TBname — Part N`, ~15 questions each. EJEE DB and uploads are read-only. |
| Custom importer | `custom_importer/` | Books not in EJEE: a person or agent transcribes and crops; PaperLab's own savers and validators stage it. |
| Universal bundle + merger | `paperlab_bundle/` | One portable `.plbundle` file (zip: `bundle.json`, `paperlab.db` with relative paths, `Outputs/`, `sources/`, SHA-256 per file). Both importers export it; one merger imports it into any archive on Windows, macOS or Linux. |

Nothing reaches an archive without an explicit merge. EJEE export requires a
passing verification report. The shared bundle merger reports carried review
findings as warnings unless `--require-reviewed` is set.

## 2. Converted and held so far

13 pilot parts, 195 questions, all staged: Physics Galaxy, Hibbeler, Meriam &
Kraige, Irodov, Young & Freedman, APhO, PYQ+, BIIT, Sardana, SBT, JEE Digital,
INSP, Aakash. The owner reviews staged parts before publication.
Per-part costs and notes: [EJEE_SOURCES.md](EJEE_SOURCES.md) §4–5.

Known source problems (EJEE data, left blocked on purpose): Y&F Part 3 Q8 and
APhO Part 1 Q4. APhO Q6 was approved by the user.

Aakash Book Crunch 1, Part 1 was re-run with the cache fix (§4). The user
approved the new run; it is now the official `part-001`, exported as a
bundle with nothing pending. The earlier run is kept outside the repo as a
backup.

## 3. Changes in this round

**Crops**
- `importer.py repair` fixes held or flagged figures with **no AI cost**. It
  draws candidate sheets with measured options: per-edge moves (`top-in`,
  `bottom-out`, …) and combined `expand`/`shrink`. `--pick Q/fig=option --by NAME`
  records the chosen rectangle in the run's `reviewed_crops.json`, bound to the
  source image hash so it survives re-runs. A human must approve the new PNGs.
- Crop replies to the model now also list per-edge options, so one edge can
  drop a caption while another keeps a cut label.
- Pilot review: every figure that touched an edge ("a lil cut" labels) was
  fixed with `repair`: 4 in the first Aakash run, 5 in the re-run.

**Prompts** (read end to end as the model receives them; no contradictions left)
- Core directives numbered 1–4 again.
- An imperfect figure no longer stops the question: the model saves the
  transcription and the importer holds the figure for review.
- Removed references to base-prompt sections that do not exist, and the rule
  that a computed answer decides the question type (type follows the required
  response format).
- Saving instructions defer to the SAVING section.

**Rendering**
- Plain-TeX `\eqno{(1)}` / `\eqno{\text{...(3)}}` showed as red errors in the
  web view. `pack` now converts them to `\tag*{…}` in displays (printed label
  kept exactly) or plain text after prose. `verify` refuses any leftover `\eqno`.
- Fixed `verify`'s `$$ … \tag` check, which paired `$$` wrongly.

**Cost** (details in §4)
- The extraction conversation is append-only by default; pruning old crop
  previews is opt-in (`prune_previews: true`).
- `run_book.py` prints and records each part's cost in USD, INR and INR
  incl. 18% GST (`USD_INR` env var overrides the rate).

**Other**
- `load_config` accepts a UTF-8 BOM (configs saved by Notepad/PowerShell).
- `serve_review.py` can show two runs of the same part side by side.
- Current setup uses the root `requirements.txt`; the old demo and sample
  workflow has been retired. `--config` is required for individual phases.
- Tests: 93 pass (`importer_EJEE`, `custom_importer`, `paperlab_bundle`).

## 4. Cost

Measured on the 13 pilots: about half the extraction money ($0.31 of $0.61)
went on input the provider had seen before but did not serve from cache.
Pruning old previews rewrote earlier messages and broke the cache on every
re-crop. The A/B re-run of Aakash Part 1:

| | Calls | Crops | Extraction cached | Extraction | Total | Total INR | INR incl. GST |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pruning (old) | 119 | 108 | 64% | $0.0747 | $0.0785 | ₹7.29 | ₹8.60 |
| Append-only (now) | 109 | 93 | 73% | $0.0729 | $0.0837 | ₹7.77 | ₹9.17 |

Cache breaks fell from 22 calls to 1, but kept previews made prompts 25%
larger, so extraction is only ~2% cheaper. The total rose because the
unchanged topic-tagging step got a poor cache rate from the provider that run
(96% → 57%). The projections therefore keep the measured pilot rates.

| Scope (Allen excluded) | Questions | USD | INR | INR incl. 18% GST |
|---|---:|---:|---:|---:|
| Textbooks | 39,535 | ~$106 | ₹9,842 | ₹11,614 |
| Everything convertible | 60,409 | ~$150 | ₹13,920 | ₹16,425 |

Per 15-question part incl. GST: ~₹1.7 for key-only cards, ₹3–5 for printed
books, ~₹9 for Aakash, ~₹24 for a photo olympiad. Spent so far ≈ $1.68
(₹156; ₹184 incl. GST). The earlier "~$170" total counted Allen study
material, which is excluded.

What was considered and **not** done, to protect quality: lowering the crop
cap from 8 to 6 attempts, and smaller preview images.

## 5. Rules (unchanged)

Transcribe, never solve; `[UNREADABLE]` instead of guessing. Figures are
original pixels only, cropped with `exact_crop`. Nothing is dropped silently;
holds block EJEE export until a human approves the exact files.
Excluded: Allen (including study material), Sri Chaitanya, FIITJEE and actual
JEE Advanced papers. Olympiads are left out of counts but can be run.

## 6. Not verified / open

- The live paid pilots used the contributor's Windows environment. Current
  offline import and bundle checks run in PaperLab's macOS/Linux/Windows CI
  matrix; macOS and Linux are required, Windows advisory.
- One A/B run is a small sample; provider cache variance is larger than the
  ~2% gain.

## 7. Next

1. EJEE Importer sub-app (`importer_EJEE/app/`, PaperLab theme, Svelte):
   search page with filters and book cards, load 15-question parts into a
   cart (temp DB), export page (convert to LaTeX + crops, rerun, download
   bundle), settings (EJEE DB path, uploads, optional PaperLab DB to merge).
2. Experimental: a PaperLab server accepts a bundle over HTTP with an
   archivist password.
