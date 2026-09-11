# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""SQLite transactions are the authority for job snapshots and replayable events."""

import json
import os
import sqlite3
import stat
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ReplayGap(ValueError):
    """The requested cursor cannot be replayed; fetch a fresh snapshot."""


class Journal:
    """Persist immutable job inputs and commit every transition with its event."""

    def __init__(self, path: Path):
        path = Path(path)
        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            if candidate.is_symlink():
                raise RuntimeError("Journal files must be owned regular files, not symlinks")
            if candidate.exists():
                info = candidate.stat()
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
                    raise RuntimeError("Journal files must be owned regular files")
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL, body TEXT NOT NULL,
                UNIQUE(workspace_id, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                created_at REAL NOT NULL, body TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
            INSERT OR IGNORE INTO metadata VALUES ('pruned_through', 0);
            INSERT OR IGNORE INTO metadata VALUES ('clean_shutdown', 1);
            INSERT OR IGNORE INTO metadata VALUES ('queue_paused', 0);
            CREATE TABLE IF NOT EXISTS workers (
                job_id TEXT PRIMARY KEY, pid INTEGER NOT NULL, identity TEXT NOT NULL, cleaned INTEGER NOT NULL
            );
        """)

    @contextmanager
    def _transaction(self):
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def close(self):
        """Close this journal connection."""
        with self._lock:
            self.db.close()

    def _event(self, db, job, kind):
        event = {
            "schema_version": 1,
            "workspace_id": job["workspace_id"],
            "job_id": job["id"],
            "kind": kind,
            "job": job,
        }
        cursor = db.execute(
            "INSERT INTO events(job_id, created_at, body) VALUES (?, ?, ?)",
            (job["id"], time.time(), _json(event)),
        )
        return cursor.lastrowid

    def submit(self, session_id, workspace_id, kind, key, inputs, *, max_pending=32):
        """Accept once per operator/workspace/key, rejecting changed immutable inputs."""
        fingerprint = _json({"kind": kind, "inputs": inputs})
        with self._transaction() as db:
            existing = db.execute(
                "SELECT fingerprint, body FROM jobs WHERE workspace_id=? AND idempotency_key=?",
                (workspace_id, key),
            ).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ValueError("Idempotency key already bound to different inputs")
                return json.loads(existing["body"])
            count = db.execute("""SELECT COUNT(*) FROM jobs WHERE json_extract(body, '$.status')
                IN ('queued', 'running', 'cancel_requested')""").fetchone()[0]
            if count >= max_pending:
                raise ValueError("Diagnostic queue capacity reached")
            now = time.time()
            job = {
                "id": uuid.uuid4().hex,
                "workspace_id": workspace_id,
                "kind": kind,
                "status": "queued",
                "stage": "queued",
                "created_at": now,
                "updated_at": now,
                "inputs": json.loads(_json(inputs)),
                "result": None,
                "error": None,
                "created_by_session_id": session_id,
            }
            db.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?)", (job["id"], workspace_id, key, fingerprint, _json(job))
            )
            self._event(db, job, "queued")
            return job

    def get_job(self, job_id):
        """Read a job or raise KeyError for an unknown identifier."""
        with self._lock:
            row = self.db.execute("SELECT body FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            return json.loads(row["body"])

    def transition(self, job_id, status, stage, kind, *, result=None, error=None):
        """Atomically update job state and append the corresponding durable event."""
        with self._transaction() as db:
            return self._transition(db, job_id, status, stage, kind, result=result, error=error)

    def _transition(self, db, job_id, status, stage, kind, *, result=None, error=None):
        job = self.get_job(job_id)
        job.update(status=status, stage=stage, updated_at=time.time(), result=result, error=error)
        db.execute("UPDATE jobs SET body=? WHERE id=?", (_json(job), job_id))
        self._event(db, job, kind)
        return job

    def begin_run(self):
        """Recover interrupted work conservatively and return the durable queue pause state."""
        with self._transaction() as db:
            clean = db.execute("SELECT value FROM metadata WHERE key='clean_shutdown'").fetchone()[0]
            if not clean:
                db.execute("UPDATE metadata SET value=1 WHERE key='queue_paused'")
            active = db.execute("""SELECT id FROM jobs WHERE json_extract(body, '$.status')
                IN ('running', 'cancel_requested')""").fetchall()
            for row in active:
                self._transition(
                    db,
                    row[0],
                    "indeterminate",
                    "interrupted",
                    "indeterminate",
                    error="API restarted without a verified worker outcome; never automatically replayed",
                )
                db.execute("UPDATE metadata SET value=1 WHERE key='queue_paused'")
            db.execute("UPDATE metadata SET value=0 WHERE key='clean_shutdown'")
            return bool(db.execute("SELECT value FROM metadata WHERE key='queue_paused'").fetchone()[0])

    def record_worker(self, job_id, pid, identity):
        """Persist process-start identity before authorizing diagnostic execution."""
        with self._transaction() as db:
            db.execute("INSERT INTO workers VALUES (?, ?, ?, 0)", (job_id, pid, _json(identity)))

    def pending_workers(self):
        """Return identities whose process exit has not yet been acknowledged."""
        with self._lock:
            return [
                {"job_id": row[0], "pid": row[1], "identity": json.loads(row[2])}
                for row in self.db.execute("SELECT job_id, pid, identity FROM workers WHERE cleaned=0")
            ]

    def worker_cleaned(self, job_id):
        """Record verified exit without inventing an execution result."""
        with self._transaction() as db:
            db.execute("UPDATE workers SET cleaned=1 WHERE job_id=?", (job_id,))

    def resume_queue(self):
        """Persist the operator's explicit authorization to dispatch queued work."""
        with self._transaction() as db:
            db.execute("UPDATE metadata SET value=0 WHERE key='queue_paused'")

    def finish_run(self):
        """Mark clean shutdown only after owned worker cleanup has been acknowledged."""
        with self._transaction() as db:
            db.execute("UPDATE metadata SET value=1 WHERE key='clean_shutdown'")

    def snapshot(self):
        """Return all operator jobs and a cursor from the same database transaction."""
        with self._transaction() as db:
            jobs = [json.loads(row[0]) for row in db.execute("SELECT body FROM jobs ORDER BY rowid")]
            cursor = self._cursor(db)
            return {"jobs": jobs, "event_cursor": cursor}

    def events_after(self, cursor, limit=128, *, max_lag=None):
        """Read a bounded ordered replay page."""
        with self._transaction() as db:
            floor = db.execute("SELECT value FROM metadata WHERE key='pruned_through'").fetchone()[0]
            ceiling = self._cursor(db)
            if cursor < floor or cursor > ceiling or (max_lag is not None and ceiling - cursor > max_lag):
                raise ReplayGap("Event cursor unavailable; resynchronize snapshot")
            return [
                dict(json.loads(row["body"]), id=row["id"])
                for row in db.execute("SELECT id, body FROM events WHERE id>? ORDER BY id LIMIT ?", (cursor, limit))
            ]

    @staticmethod
    def _cursor(db):
        row = db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
        return row[0] if row else 0

    def prune_events(self, *, now=None):
        """Prune only an expired prefix, retaining at least seven days and all active jobs."""
        cutoff = (time.time() if now is None else now) - 7 * 86400
        with self._transaction() as db:
            protected = db.execute(
                """SELECT MIN(events.id) FROM events JOIN jobs ON jobs.id=events.job_id
                WHERE events.created_at>=? OR json_extract(jobs.body, '$.status')
                IN ('queued', 'running', 'cancel_requested')""",
                (cutoff,),
            ).fetchone()[0]
            through = self._cursor(db) if protected is None else protected - 1
            db.execute("DELETE FROM events WHERE id<=?", (through,))
            db.execute("UPDATE metadata SET value=MAX(value, ?) WHERE key='pruned_through'", (through,))
