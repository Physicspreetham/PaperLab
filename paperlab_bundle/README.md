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

## Upload to a deployed server

Use this when you have the archivist password but no shell access to the
archive host. Only upload bundles you trust and are authorized to publish.
The server merges into its configured archive and media directory; clients
cannot choose server paths. No extraction, tagging, or paid API calls run.

| Request | Result |
|---|---|
| `POST /api/auth/login`, JSON `{"password": "…"}` | `204` and an HttpOnly session cookie (`Secure` over HTTPS). Wrong password returns `401`. |
| `POST /api/bundles/import`, raw `.plbundle` bytes, `Content-Type: application/octet-stream` | `200` preview by default; returns `dry_run`, `mergeable`, and paper names and question counts. |
| `POST /api/bundles/import?dry_run=false`, same bytes | First publish returns `201` with `already_imported: false`, `papers` with `archive_paper` IDs, `merged_at`, the backup filename, and `warnings`. A retry after commit returns `200` and the original receipt with `already_imported: true`; it does not publish again. |
| `POST /api/auth/logout` | `204`; invalidates the session. |

The two import requests need the cookie, **not** a copy of the password.
HTTP is allowed only for local loopback development; use a trusted HTTPS
certificate for remote hosts. Unapproved review holds and stale approvals
always block remote imports. Append `allow_untagged=true` only if you want
untagged questions to go to the Tagging Inbox; unknown topic codes still
block. A clean preview doesn't reserve IDs or override later checks.
Upload validates the saved TeX with the native syntax and figure checks
without rewriting any files. Recorded approvals must match the exact
question and all its current TeX and figures; this does not authenticate
the reviewer. If validation fails, fix the staged files and re-export.

If a publish response is lost, retry with the **exact same bytes**, not a
new export. The server fingerprints the file and stores its receipt in
the same database transaction as the papers, so a restart or double-click
cannot add another copy. An in-progress request returns `429`; honor
`Retry-After`. A different bundle with any overlapping paper is rejected
as a whole (`409`). Retrying an old receipt never restores papers that
were deliberately deleted.

Example with Python 3.12 and `httpx` (`python -m pip install httpx` for a
standalone client). The password is prompted for, never passed in a command
argument or written to disk. Save this as a script, set `server` and `bundle`,
then run it; only typing `PUBLISH` makes a change.

```python
from getpass import getpass
from pathlib import Path
import httpx

server = "https://paperlab.example.org"
bundle = Path("part-1.plbundle")

with httpx.Client(base_url=server, timeout=httpx.Timeout(600, connect=10)) as client:
    client.post("/api/auth/login", json={"password": getpass("Archivist password: ")}).raise_for_status()
    try:
        def send(dry_run):
            with bundle.open("rb") as source:
                response = client.post(
                    "/api/bundles/import", params={"dry_run": str(dry_run).lower()},
                    headers={"Content-Type": "application/octet-stream",
                             "Content-Length": str(bundle.stat().st_size)},
                    content=iter(lambda: source.read(1024 * 1024), b""),
                )
            if response.is_error:
                print(response.status_code, response.text)
            response.raise_for_status()
            return response.json()

        print(send(dry_run=True))
        if input("Type PUBLISH to merge this bundle: ") == "PUBLISH":
            print(send(dry_run=False))
    finally:
        client.post("/api/auth/logout")
```

Transport limits: 64 MiB compressed, 256 MiB expanded, 4,096 ZIP entries,
2 MiB manifest, 32 MiB SQLite payload, and 512 KiB per TeX file. Use an
ordinary PaperLab ZIP, not an encrypted or ZIP64 archive. Figures must
be readable PNG or JPEG (up to 3 MiB and 8 megapixels each); original
sources may also be WebP or PDF. Uploads must finish within 120 seconds;
the server handles one upload or merge at a time. Split a larger export by
paper. Merge time depends on archive size; the upload deadline is not a
merge deadline.

The server must already have an archive. For a brand-new PaperLab install,
initialize the default syllabus with `python -c "import database;
database.init_topics()"` in the server environment before importing tagged
papers. Do not re-seed an existing customized syllabus just to import a bundle.

| Status | What to do |
|---|---|
| `401` / `403` | Log in again; use HTTPS and same-origin requests. |
| `408` / `413` / `415` | Retry a slow transfer, split a large bundle, or correct the raw upload format. |
| `409` | A preview found a previously published paper, a different bundle overlaps existing papers, or the target has an occupied output directory. |
| `422` | Inspect the bundle locally and correct the reported validation, topic, or review issue. |
| `429` / `503` | Respect `Retry-After` for a busy server. If the message says setup is incomplete, ask the operator to initialize the archive or set a non-default password. |

For proxy and deployment settings see [Hosting on a server](../README.md#hosting-on-a-server).

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
stages media on the target volume, then commits the paper rows and receipt
together. Public routes will not serve staged media before the commit.
After a process interruption, API startup or the next real CLI merge
recovers journaled media; it does not delete other paper folders. Don't
manually edit or remove `.bundle-pending` while a publish is in progress.

Keep enough space for both the incoming content and a full SQLite backup
per publish, and set a backup retention policy. For host crashes or power
loss, keep a separate DB-and-Outputs backup as well. Stop other archive
writers during local maintenance. The canonical receipt is in SQLite;
the optional `*.bundle-merges.jsonl` copy failing to write does not undo
the import.

Run `python scripts/test_backend.py -q` for offline coverage of both
producers, round-trip merge, duplicate and checksum rejection, WAL-aware
dry run, review policy, and rollback after a copy failure.
