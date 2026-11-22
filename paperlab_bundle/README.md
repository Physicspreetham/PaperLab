# PaperLab bundle

A `.plbundle` is one portable file for transferring staged PaperLab papers
between machines. The [EJEE importer](../importer_EJEE/README.md) and
[custom importer](../custom_importer/README.md) use the same format and
merger. Install PaperLab using the [main guide](../README.md#2-install-and-configure).
Run these commands from the checkout root with that Python environment.
No model key is needed.

## Inspect, preview, publish

```sh
python -m paperlab_bundle inspect part-1.plbundle
python -m paperlab_bundle merge part-1.plbundle --target-db physics_archive.db --dry-run --require-reviewed
python -m paperlab_bundle merge part-1.plbundle --target-db physics_archive.db --require-reviewed
```

1. **Inspect** shows package contents, hard problems, and advisory review
   warnings. Verify that you trust the producer and are allowed to import
   the material. SHA-256 checks detect corruption; they do not authenticate
   the producer or prove transcription quality.
2. **Dry-run** tests against a throwaway SQLite snapshot, including committed
   WAL data, without writing or migrating the target DB or its `Outputs`.
   It checks existing output-folder conflicts too. It is not a reservation
   and does not test write permissions or available disk space.
3. **Merge** publishes the exact file you inspected. Use `--target-outputs`
   if the server does not use `Outputs/` beside its archive DB. A missing DB
   path creates a new archive on real merge; confirm the path before
   approving. For an older existing archive, start the current PaperLab
   version once to apply schema migrations before retrying the merge.

Missing topics block a merge unless `--allow-untagged` is intentional.
Recorded classification abstentions retain their suggestion and go to
PaperLab's Tagging Inbox. Unknown topic codes, duplicates, unsafe paths,
corrupt files and invalid payload references are refused. Review holds
and stale approvals are warnings by default; `--require-reviewed` makes
them blocking on both dry and real runs. It checks **recorded** holds;
it does not replace human review.

## What moves

| Entry | Contents |
|---|---|
| `bundle.json` | Format version, producer chain, paper identities, review records and hash-bound approvals, source references when supplied, and SHA-256 for every payload file |
| `paperlab.db` | Bundled papers, questions, saved tags (including rank and source), difficulty, and token usage |
| `Outputs/<paper>/<question>/` | `question.tex`, `solution.tex`, and figures; local sidecars and revision backups are not transferred |
| `sources/<paper>/` | Optional originals or mapped source PDFs |

All payload paths are portable relative POSIX paths. The merger allocates
new paper/question IDs and rewrites media paths for the destination.
Original numbering and provenance remain in the `.plbundle` and merge
receipt. Keep the exported file.

For an already-staged PaperLab database, the low-level builder is also
available. Prefer the producer's `export`, which applies its own checks
and includes its provenance:

```sh
python -m paperlab_bundle build --db work/book/paperlab.db --paper 1 --out part-1.plbundle
```

## Backups and recovery

Real merge takes a uniquely named `*.pre-bundle-merge-*.bak` SQLite backup,
copies media into new paper directories, then commits rows in one
transaction. On a reported copy or database failure, it rolls back rows and
removes directories it created. Stop other archive writers during
maintenance; keep a full DB-and-Outputs backup as well for host crashes
or power loss. The JSON receipt lists the backup and new IDs and is appended
to `*.bundle-merges.jsonl`. If only writing the receipt log fails after
commit, the command explicitly reports that the import succeeded with a
warning; don't rerun it blindly.

Run `python scripts/test_backend.py -q` for offline coverage of both
producers, round-trip merge, duplicate and checksum rejection, WAL-aware
dry run, review policy, and rollback after a copy failure.
