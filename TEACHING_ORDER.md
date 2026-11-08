# Teaching-order classification

PaperLab uses `teaching_order.json` (Nucleus 2026–28 schedule, revised 22 June) to choose one primary subtopic from the concepts required by a solution. Existing codes are unchanged. `teaching_rank` is the completion date of the first teaching slot, formatted YYYYMMDD; revision, cumulative tests, and later repeats do not move a topic later.

The classifier receives topic paths and descriptions and returns every required topic with solution evidence. Python chooses the unique latest verified rank. Rank 0 in `question_topics` is primary; later ranks are supporting. Search and model-paper selection use only primary by default. Search offers “Include supporting concepts”. Default topic counts count primary assignments only.

## Mapping review

The schedule sometimes groups several concepts together or does not explicitly cover the full scope of an existing code. Those entries have `mapping_status: needs_review`. Two required topics sharing the latest teaching slot also require review: their relative order is not invented. Review cases retain their candidates and reason in `topic_classifications`, remove auto tags, and appear in the Tagging Inbox. Human tags are preserved, including manual overrides. Topic names/scopes changed in the syllabus should have their schedule mappings rechecked.

To verify a mapping, edit the entry's `taught_from`, `taught_until`, `teaching_rank`, `source_page`, `reason`, and `mapping_status` in `teaching_order.json`. Use the PDF's actual teaching rows. If a code spans several stages, map completion of its full scope, or split the code into narrower concepts after review. Only establish an internal order for a shared slot when supported by an actual teaching sequence; otherwise keep review status. Bump the schedule version when changing the mapping.

## Existing question migration

`python migrate_teaching_order.py` writes a dry-run report to `tmp/teaching-migration.json`.

`python migrate_teaching_order.py --apply` creates a SQLite backup before atomically replacing each question's auto tags. It preserves human choices. The report includes every decision and all unresolved mapping entries. This migration only reorders previously detected concepts; it cannot recover concepts omitted by the old three-topic limit.

A full reclassification can be run with `python run_topics.py --refill` using the application's configured model. This invokes the model and incurs normal usage. Missing solutions go directly to review. The migration itself makes no model calls.

The teaching schedule is an institutional ordering source, not a statement that every listed topic is currently in the official JEE Advanced syllabus. Syllabus eligibility should be managed separately.
