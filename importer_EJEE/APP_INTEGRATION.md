# EJEE import in the local PaperLab app

The standalone importer is available through **EJEE Import** in the archivist sidebar and a link on Intake & Pipeline. **EJEE collections** is a separate reader/library, outside the ordinary question-paper Archive.

## Workflow

1. Log in as archivist and open `/ejee`.
2. The source defaults to the existing local EJEE database and uploads folder. Source settings allow connecting another compatible EJEE database/image folder; the source is opened read-only.
3. Filter by sources (multiple allowed), the actual EJEE module/chapter/week/subtopic hierarchy, Model/question type (`qtype`), level, section, exam, year, status, favourites, altered flag, or text. These are EJEE database fields; Model does not mean the AI model. Source selection is independent of textbook numbering adapters.
4. Preview existing question images and tick individual questions, or eligible questions on the current page. Selections persist across filters/pages and may combine sources/topics. Review/remove items in the selection basket, give it a collection name, and process only those selected questions. There is no chapter-wise requirement. Missing/unsafe images or invalid body crop bounds require correction in EJEE before processing.
5. Import in the background. The existing conversion engine handles mapped question/solution images and diagrams; the current app's actual Node 3 runs freshly against the separate library's syllabus snapshot. No old EJEE classifications are copied.
6. Completed, verified collections appear under `/ejee/library`. Questions, solutions, figures, original per-question source, difficulty and fresh topic paths can be read there. Imported figure URLs use their own endpoint and cannot resolve into the ordinary Archive.

Selective import needs **no textbook chapter mapping**. Optional complete-chapter import remains under a collapsed panel for the configured Morin/Hibbeler adapters. The teaching taxonomy is used to find questions, never to guess printed textbook chapter order.

## Exact selection and provenance

The browser submits explicit resource IDs with a source-configuration token. The server revalidates them, freezes every original resource column and node ancestry, and attaches solutions by the exact `(source, grp)` pair, even if the solution has different filter tags. Independent NULL-group questions stay independent; NULL part is treated as a question with its original value retained. Continuation cards deduplicate to one logical question; ambiguous shared groups are rejected before AI calls. Solution/concept cards cannot be submitted as question anchors.

`selection.json` retains selected/included resource IDs and a content fingerprint; the config records the submitted filters and collection name. Explicit IDs are authoritative when a basket combines several filter searches. Only frozen items become lossless image canvases and enter extraction. Collection question IDs are local sequential numbers, while source labels/IDs remain in the published provenance manifest. Mixed-source collections retain each question's original source. A repeated identical selection (regardless of click order/name) reuses its active/published result.

## Separate storage

Default local layout:

```text
C:/QP/PaperLab/data/ejee_library/
    paperlab.db                  # imported textbooks only
    Outputs/<paper>/<question>/  # question.tex, solution.tex, figures/
    data/archive/ejee/<paper>/   # source canvases and provenance
```

The normal `physics_archive.db`, normal `Outputs/`, normal Archive, question-paper jobs and ordinary usage ledger are not merged with this collection. The separate library copies the syllabus only when first created; it does not copy regular questions/papers. `PAPERLAB_EJEE_LIBRARY_ROOT` can select another dedicated folder; aliases of the normal database/output/source folders are rejected.

Worker manifests, configs, logs and durable progress stay under `importer_EJEE/runs/web/`, which is gitignored. Each chapter converts in its own process using the importer runtime and the current local app checkout. Source credentials are inherited in memory, never sent to the browser or written to job configuration.

The converter keeps unfinished output isolated. The publisher checks question counts and syllabus consistency, allocates new native IDs, copies files into the dedicated library, and commits native question/topic/classification/usage records transactionally. Failures do not leave a partial chapter in the reader. Existing files are never overwritten or deleted to recover from a failed publish.

## Resume, duplicates and usage

- Repeated clicks return the same active job. Completed chapter/source-group sets return the existing chapter instead of paying to convert again.
- A small sample and a full chapter have different group identities, so importing a sample does not silently mark a larger chapter complete.
- Failed/interrupted jobs can resume from saved conversions/classifications. A per-worker file lock prevents concurrent reuse of the same run.
- If the syllabus changes during a run, publishing stops; resuming refreshes classification against the new snapshot without repeating extraction.
- The import page reports separate estimated usage, including failed/in-progress calls retained in worker databases. Completed calls move with the chapter into the dedicated native token ledger and are not counted twice.

## Validation

- 29 importer and app integration tests passed, covering the earlier integration plus exact filter semantics, descendant taxonomy selection, selected-only snapshots, source-safe solution joins, NULL roles/groups, continuation deduplication, literal search, asset validation and selective-job access/storage/duplicates.
- The frontend production build passed.
- A real question/solution from **100 Solved Problems on Motion in a Plane (Jitender Singh)**, which has no textbook adapter, passed selection → prepare → native extraction → diagrams → formatting → fresh local Node 3 → verification → isolated publish. The target contained exactly one question under the supplied collection name, with six recorded API calls and approximately **$0.004807** estimated cost. Artifacts are local in `runs/selection-flow-test/`; no live collection or regular Archive question was created by this check. The browser verified source + chapter + subtopic + Single correct filters, two checkboxes, image preview and an enabled “Process 2 selected questions” button.
- An actual two-question Hibbeler sample was converted in a separate test run, classified using the current app Node 3, verified and published into a dedicated textbook database. The ordinary test paper database remained empty. This did not import a full chapter or write sample questions into the user's normal Archive.
- The live main app discovered 14 Morin chapters and 11 Hibbeler chapters from the real EJEE source. Its ordinary Archive still contained the same 13 papers; the new live textbook library started empty for the user to select imports.

This integration belongs to the local app and its configured `origin` repository. The older author-review fork/pull request is not updated for these app-specific changes.
