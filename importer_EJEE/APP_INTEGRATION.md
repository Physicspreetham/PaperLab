# EJEE import in the local PaperLab app

The earlier standalone importer is now available through **EJEE Import** in the archivist sidebar and a link on Intake & Pipeline. **Imported textbooks** is a separate reader/library, not part of the ordinary question-paper Archive.

## Workflow

1. Log in as archivist and open `/ejee`.
2. The source defaults to the existing local EJEE database and uploads folder. Source settings allow connecting another compatible EJEE database/image folder; the source is opened read-only.
3. Choose a supported textbook and one or more chapters. The UI shows question and mapped-solution counts, excluded numbering groups and already-imported chapters.
4. Import in the background. The existing conversion engine handles mapped question/solution images and diagrams; the current app's actual Node 3 runs freshly against the textbook library's syllabus snapshot. No old EJEE classifications are copied.
5. Completed, verified chapters appear under `/ejee/library`. Questions, solutions, figures, difficulty and topic paths can be read there. Imported figure URLs use their own endpoint and cannot resolve into the ordinary Archive.

Morin Classical Mechanics and Hibbeler Dynamics chapter numbering are configured initially. Other sources are listed as requiring a mapping, rather than guessed into the wrong chapters. Server-owned `book_adapters.json` can add explicit source/regex adapters. The app never guesses textbook chapter order from the teaching-topic hierarchy.

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

- 22 importer and app integration tests passed, including read-only source access, access control, storage separation, clean-install syllabus initialization, chapter catalogue/mapping, duplicate submission, transaction rollback, stale syllabus handling, scoped figures and rendering compatibility.
- The frontend production build passed.
- An actual two-question Hibbeler sample was converted in a separate test run, classified using the current app Node 3, verified and published into a dedicated textbook database. The ordinary test paper database remained empty. This did not import a full chapter or write sample questions into the user's normal Archive.
- The live main app discovered 14 Morin chapters and 11 Hibbeler chapters from the real EJEE source. Its ordinary Archive still contained the same 13 papers; the new live textbook library started empty for the user to select imports.

This integration belongs to the local app and its configured `origin` repository. The older author-review fork/pull request is not updated for these app-specific changes.
