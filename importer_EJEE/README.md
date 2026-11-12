# EJEE → PaperLab importer

The local app now also has **EJEE Import** and a separate **EJEE collections** reader. See [APP_INTEGRATION.md](APP_INTEGRATION.md) for the app workflow, dedicated database/folders, selective filters, optional chapter mappings and tests. The standalone instructions below remain useful for isolated demos.

Independent data adapter; no PaperLab source modification. See [PLAN.md](PLAN.md) and [UPSTREAM_ANALYSIS.md](UPSTREAM_ANALYSIS.md).

The demo imports **all 18 questions in David Morin, Introduction to Classical Mechanics, Chapter 1: Strategies for solving problems** into `runs/morin-chapter-01/paperlab.db`. The live EJEE database is opened read-only. Production PaperLab data is never targeted. The reference repo and virtual environment are local dependencies, excluded from version control.

From `C:\QP\PaperLab`:

```powershell
git clone https://github.com/Vivek5170/PaperLab.git importer_EJEE/reference/PaperLab
.venv\Scripts\python.exe -m venv importer_EJEE/.venv
importer_EJEE/.venv/Scripts/python.exe -m pip install -r importer_EJEE/requirements.txt
importer_EJEE/.venv/Scripts/python.exe importer_EJEE/importer.py inspect
importer_EJEE/.venv/Scripts/python.exe importer_EJEE/importer.py prepare
importer_EJEE/.venv/Scripts/python.exe importer_EJEE/importer.py extract
importer_EJEE/.venv/Scripts/python.exe importer_EJEE/importer.py figures
importer_EJEE/.venv/Scripts/python.exe importer_EJEE/importer.py classify
importer_EJEE/.venv/Scripts/python.exe importer_EJEE/importer.py pack
importer_EJEE/.venv/Scripts/python.exe importer_EJEE/importer.py verify
```

`inspect` generates `source_schema.json`, source inventory and **EJEE_COLUMN_MAPPING.md covering every column of every table**. `prepare` snapshots selected rows and generates lossless body PNGs and chapter PDFs. `extract` runs a bounded per-question native tool loop and resumes completed items. `figures` exports accepted crop boxes directly from the original image pixels and records every locator/hash, avoiding upstream's default 600 dpi raster upsampling. `classify` executes upstream Node 3 afresh and resumes already-successful classifications. `verify` writes `verification.json` and exits nonzero on incomplete data.

The existing parent `.env` supplies `META_API_KEY` in memory. No new API key is needed. The runtime reads model/endpoint/prices from the downloaded upstream config. Original EJEE topic and difficulty labels are not passed to Node 3.

To review, install frontend packages in `reference/PaperLab/frontend` with `npm install`, then run `Start-Review.ps1` and open http://127.0.0.1:5183/archive. The API on 8011 and frontend on 5183 are separate from the main desktop app. `serve.py` sets the isolated DB, Outputs and data environment before importing upstream modules. `vite.review.config.mjs` points only this review frontend at its API, without modifying upstream files.

The app supports selective question imports from any eligible source without a chapter adapter. Only the standalone complete-textbook-chapter mode needs an explicit adapter config and validated group/chapter numbering. Unsupported part roles or missing body locators stop preparation rather than silently losing data. Existing diagram coordinates are not assumed from generic print-layout rectangles. The first demo is a review artifact; bulk/production import is a subsequent operation after review.

`pack` preserves printed book labels in TeX/provenance while using chapter-local numeric IDs in PaperLab, so its unchanged reader sorts correctly. It also encodes printed heading stars as math symbols to avoid the native Markdown bridge displaying raw emphasis markers. Every change is recorded in `data_normalizations.json`.

For this demo, seven questions have mapped worked solutions across 13 image parts; eleven exercises have no mapped solution. Those eleven remain explicitly missing, without invented answers. Node 3 ran on all 18. Its valid taxonomy-gap suggestion is retained for the numerical integration problem rather than forcing an unrelated topic.


Question display policy: keep only problem statements, subparts, equations, options and diagrams in question.tex. Omit source question labels, descriptive titles and difficulty stars; retain these in the manifest. This supersedes the earlier demo heading-preservation policy. Cleanup handles titles sharing a line with the first sentence and does not require new API calls. Cost breakdown: COST_ANALYSIS.md.
