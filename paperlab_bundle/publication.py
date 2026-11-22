"""SQLite publication receipts and recoverable media moves on the same volume."""
from __future__ import annotations

from contextlib import closing, suppress
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid

_NAME = re.compile(r"[0-9a-f]{32}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_OWNER = ".bundle-owner"
_JOURNAL = "publication.json"


def saved_receipt(db, digest):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bundle_imports'").fetchone():
        return None
    row = db.execute("SELECT receipt FROM bundle_imports WHERE sha256=?", (digest,)).fetchone()
    return json.loads(row[0]) if row else None


def record_receipt(db, digest, serialized):
    db.execute("CREATE TABLE IF NOT EXISTS bundle_imports (sha256 TEXT PRIMARY KEY, receipt TEXT NOT NULL)")
    db.execute("INSERT INTO bundle_imports (sha256, receipt) VALUES (?, ?)", (digest, serialized))


def _pending_root(target, outputs):
    # Only recover work belonging to this database, even if Outputs is shared.
    name = hashlib.sha256(os.fsencode(os.path.normcase(str(target.resolve())))).hexdigest()
    return outputs / ".bundle-pending" / name


def _prune(root):
    for folder in (root, root.parent):
        with suppress(OSError):
            folder.rmdir()


def _owner_is(folder, name):
    if not folder.is_dir() or folder.is_symlink():
        return False
    marker = folder / _OWNER
    if not marker.is_file() or marker.is_symlink():
        return False
    try:
        return marker.read_text(encoding="ascii") == name
    except (FileNotFoundError, UnicodeError):
        return False


def recover_locked(db, target, outputs):
    """With the SQLite writer lock held, recover only our own marked folders."""
    root = _pending_root(target, outputs)
    if not root.is_dir() or root.is_symlink() or root.parent.is_symlink():
        return
    for job in sorted(root.iterdir()):
        if not _NAME.fullmatch(job.name) or job.is_symlink() or not job.is_dir():
            continue
        journal = job / _JOURNAL
        if journal.is_file():
            try:
                info = json.loads(journal.read_text(encoding="utf-8"))
                sha, ids = info["sha256"], info["papers"]
                if not _SHA.fullmatch(sha) or not isinstance(ids, list) or not all(
                    type(pid) is int and pid > 0 for pid in ids
                ):
                    raise ValueError("invalid import journal")
            except FileNotFoundError:
                continue  # the committed publisher finished cleanup first
            except (ValueError, TypeError, KeyError) as exc:
                raise OSError(f"Cannot recover bundle publication {job.name}; inspect its journal") from exc
            committed = saved_receipt(db, sha) is not None
            for pid in ids:
                final = outputs / str(pid)
                if not _owner_is(final, job.name):
                    continue
                if committed:
                    (final / _OWNER).unlink(missing_ok=True)
                elif db.execute("SELECT 1 FROM papers WHERE id=?", (pid,)).fetchone():
                    raise OSError(f"Bundle recovery found an occupied paper directory: {pid}")
                else:
                    shutil.rmtree(final)
        # With no written journal, the process had not started moving media.
        with suppress(FileNotFoundError):
            shutil.rmtree(job)
    _prune(root)


def recover_publications(target, outputs):
    target, outputs = Path(target).resolve(), Path(outputs).resolve()
    if not _pending_root(target, outputs).is_dir():
        return
    with closing(sqlite3.connect(target, timeout=30)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        recover_locked(db, target, outputs)


class Publication:
    def __init__(self, target, outputs):
        self.outputs = outputs
        self.root = _pending_root(target, outputs)
        if self.root.is_symlink() or self.root.parent.is_symlink():
            raise OSError("Bundle staging directories must not be links")
        self.job = self.root / uuid.uuid4().hex
        self.job.mkdir(parents=True)
        self.installed = []

    def stage(self, paper_id):
        folder = self.job / str(paper_id)
        folder.mkdir()
        (folder / _OWNER).write_text(self.job.name, encoding="ascii")
        return folder

    def install(self, digest, ids):
        # Every move is on the same filesystem. The journal must precede
        # the first move so a process restart can undo or finish all moves.
        pending = self.job / f"{_JOURNAL}.tmp"
        with pending.open("w", encoding="utf-8") as stream:
            json.dump({"sha256": digest, "papers": ids}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(self.job / _JOURNAL)
        for pid in ids:
            dest = self.outputs / str(pid)
            if dest.exists() or dest.is_symlink():
                raise FileExistsError(f"Output for paper {pid} already exists")
            (self.job / str(pid)).rename(dest)
            self.installed.append(dest)

    def finish(self, *, committed):
        for dest in self.installed:
            with suppress(FileNotFoundError):
                if _owner_is(dest, self.job.name):
                    if committed:
                        (dest / _OWNER).unlink(missing_ok=True)
                    else:
                        shutil.rmtree(dest)
        with suppress(FileNotFoundError):
            shutil.rmtree(self.job)
        _prune(self.root)
