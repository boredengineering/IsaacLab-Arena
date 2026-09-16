# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""SQLite transactions are the authority for job snapshots and replayable events."""

import hashlib
import json
import os
import re
import sqlite3
import stat
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

MAX_RECEIPT_BYTES = 65536
# Modern validation and graph context share the worker's bounded 2-MiB transport.
# Keep the original immutable table/constraint intact for existing schema-v1 journals.
MAX_MODERN_RECEIPT_BYTES = 2 * 1024 * 1024
JOURNAL_SCHEMA_VERSION = 1


def _receipt_json(receipt, *, max_bytes=MAX_RECEIPT_BYTES):
    """Encode a bounded JSON object, rejecting coercions and non-finite numbers."""

    def validate(value, depth=0):
        if depth > 32:
            raise ValueError("Receipt nesting exceeds limit")
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise ValueError("Receipt keys must be strings")
                validate(item, depth + 1)
        elif type(value) is list:
            for item in value:
                validate(item, depth + 1)
        elif value is not None and type(value) not in (str, bool, int, float):
            raise ValueError("Receipt must contain only JSON values")

    if type(receipt) is not dict:
        raise ValueError("Receipt must be a JSON object")
    validate(receipt)
    body = _json(receipt)
    if len(body.encode("utf-8")) > max_bytes:
        raise ValueError("Receipt exceeds byte limit")
    return body


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
        self._recovery_attempts = {}
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        schema = """
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
            INSERT OR IGNORE INTO metadata VALUES ('attempt_schema_version', 1);
            CREATE TABLE IF NOT EXISTS workers (
                job_id TEXT PRIMARY KEY, pid INTEGER NOT NULL, identity TEXT NOT NULL, cleaned INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attempts (
                attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, generation INTEGER NOT NULL,
                state TEXT NOT NULL, UNIQUE(job_id, generation)
            );
            CREATE TABLE IF NOT EXISTS candidate_receipts (
                attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, generation INTEGER NOT NULL,
                schema_version INTEGER NOT NULL CHECK(schema_version=1),
                body TEXT NOT NULL CHECK(length(CAST(body AS BLOB))<=65536 AND json_valid(body)),
                UNIQUE(job_id, generation)
            );
            CREATE TRIGGER IF NOT EXISTS receipt_no_update BEFORE UPDATE ON candidate_receipts
                BEGIN SELECT RAISE(ABORT, 'candidate receipt is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS receipt_no_delete BEFORE DELETE ON candidate_receipts
                BEGIN SELECT RAISE(ABORT, 'candidate receipt is immutable'); END;
            CREATE TABLE IF NOT EXISTS modern_candidate_receipts (
                attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, generation INTEGER NOT NULL,
                schema_version INTEGER NOT NULL CHECK(schema_version=1),
                body TEXT NOT NULL CHECK(length(CAST(body AS BLOB))<=2097152 AND json_valid(body)),
                UNIQUE(job_id, generation)
            );
            CREATE TRIGGER IF NOT EXISTS modern_receipt_no_update BEFORE UPDATE ON modern_candidate_receipts
                BEGIN SELECT RAISE(ABORT, 'candidate receipt is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS modern_receipt_no_delete BEFORE DELETE ON modern_candidate_receipts
                BEGIN SELECT RAISE(ABORT, 'candidate receipt is immutable'); END;
            CREATE TABLE IF NOT EXISTS workflow_authorizations (
                renewal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id),
                blocked_generation INTEGER NOT NULL,
                idempotency_key TEXT NOT NULL CHECK(length(idempotency_key)<=128),
                fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64),
                schema_version INTEGER NOT NULL CHECK(schema_version=1),
                body TEXT NOT NULL CHECK(length(CAST(body AS BLOB))<=16384 AND json_valid(body)),
                accepted_job TEXT NOT NULL CHECK(length(CAST(accepted_job AS BLOB))<=1048576 AND json_valid(accepted_job)),
                UNIQUE(job_id, idempotency_key), UNIQUE(job_id, blocked_generation)
            );
            CREATE TRIGGER IF NOT EXISTS authorization_no_update BEFORE UPDATE ON workflow_authorizations
                BEGIN SELECT RAISE(ABORT, 'workflow authorization is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS authorization_no_delete BEFORE DELETE ON workflow_authorizations
                BEGIN SELECT RAISE(ABORT, 'workflow authorization is immutable'); END;
            CREATE TABLE IF NOT EXISTS workflow_renewal_rejections (
                job_id TEXT NOT NULL REFERENCES jobs(id),
                idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) BETWEEN 1 AND 128),
                fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64),
                PRIMARY KEY(job_id, idempotency_key)
            );
            CREATE TRIGGER IF NOT EXISTS rejection_no_update BEFORE UPDATE ON workflow_renewal_rejections
                BEGIN SELECT RAISE(ABORT, 'renewal rejection is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS rejection_no_delete BEFORE DELETE ON workflow_renewal_rejections
                BEGIN SELECT RAISE(ABORT, 'renewal rejection is immutable'); END;
            PRAGMA user_version=1;
        """
        try:
            self._check_schema()
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            with self._transaction() as db:
                self._check_schema()
                # executescript implicitly commits: execute complete statements instead
                # so additive initialization and version metadata commit together.
                statement = ""
                for line in schema.splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        db.execute(statement)
                        statement = ""
        except BaseException:
            self.db.close()
            raise

    def _check_schema(self):
        """Accept legacy version zero or this schema; never migrate newer data backward."""
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, JOURNAL_SCHEMA_VERSION):
            raise RuntimeError("Incompatible journal schema version")
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone():
            row = self.db.execute("SELECT value FROM metadata WHERE key='attempt_schema_version'").fetchone()
            if row is not None and row[0] != JOURNAL_SCHEMA_VERSION:
                raise RuntimeError("Incompatible attempt schema version")

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
                IN ('queued', 'running', 'cancel_requested', 'blocked_authorization')""").fetchone()[0]
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
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?)",
                (job["id"], workspace_id, key, fingerprint, _json(job)),
            )
            self._event(db, job, "queued")
            return job

    @staticmethod
    def workflow_operation_id(workspace_id, key, inputs, generation=1):
        """Bind private authority to the canonical request and one attempt generation."""
        frozen = {k: v for k, v in inputs.items() if k != "workflow_authorization"}
        return hashlib.sha256(_json([workspace_id, key, frozen, generation]).encode()).hexdigest()

    def workflow_binding(self, job, *, generation=None, attempt=None):
        """Derive authority from the stored submission, never caller grant metadata."""
        with self._lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
            if row is None:
                raise ValueError("Workflow authorization unavailable")
            durable = json.loads(row["body"])
            if (
                _json({"kind": job["kind"], "inputs": job["inputs"]}) != row["fingerprint"]
                or job["created_by_session_id"] != durable["created_by_session_id"]
                or job["workspace_id"] != row["workspace_id"]
            ):
                raise ValueError("Workflow authorization unavailable")
            current = self.get_attempt(job["id"])
            if generation is None:
                renewal = self.latest_authorization(job["id"])
                generation = renewal["blocked_attempt"]["generation"] + 1 if renewal else 1
                if durable["status"] == "queued":
                    if current is not None and current["generation"] != generation - 1:
                        raise ValueError("Workflow authorization unavailable")
                elif (
                    durable["status"] != "running"
                    or attempt is None
                    or current is None
                    or current["state"] != "claimed"
                    or current["generation"] != generation
                ):
                    raise ValueError("Workflow authorization unavailable")
                if attempt is not None and (
                    current is None
                    or attempt.get("attempt_id") != current["attempt_id"]
                    or attempt.get("generation") != current["generation"]
                    or any(current.get(k) != v for k, v in attempt.items())
                ):
                    raise ValueError("Workflow authorization unavailable")
            return self.workflow_operation_id(
                row["workspace_id"],
                row["idempotency_key"],
                durable["inputs"],
                generation,
            )

    def get_authorization_replay(self, job_id, key, fingerprint):
        """Return the original accepted snapshot without consulting private configuration."""
        with self._lock:
            row = self.db.execute(
                "SELECT fingerprint, accepted_job FROM workflow_authorizations WHERE job_id=? AND idempotency_key=?",
                (job_id, key),
            ).fetchone()
            if row is None:
                return None
            if row["fingerprint"] != fingerprint:
                raise ValueError("Renewal idempotency conflict")
            return json.loads(row["accepted_job"])

    def authorization_disposition(self, job_id, key, fingerprint):
        """Read only the exact requested binding; absence never proves rejection."""
        with self._lock:
            accepted = self.get_authorization_replay(job_id, key, fingerprint)
            row = self.db.execute(
                "SELECT fingerprint FROM workflow_renewal_rejections WHERE job_id=? AND idempotency_key=?",
                (job_id, key),
            ).fetchone()
            if row is not None and row[0] != fingerprint:
                raise ValueError("Renewal idempotency conflict")
            return {
                "schema_version": 1,
                "code": (
                    "renewal_accepted" if accepted is not None else "renewal_rejected" if row else "renewal_unknown"
                ),
                "job_id": job_id,
                "idempotency_key": key,
                "fingerprint": fingerprint,
            }

    def seal_authorization_rejection(self, job_id, key, fingerprint):
        """Seal nonacceptance atomically, or return the already accepted snapshot."""
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", key) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise ValueError("Invalid renewal binding")
        with self._transaction() as db:
            self.get_job(job_id)
            accepted = self.get_authorization_replay(job_id, key, fingerprint)
            if accepted is not None:
                return accepted
            disposition = self.authorization_disposition(job_id, key, fingerprint)
            if disposition["code"] != "renewal_rejected":
                if (
                    db.execute(
                        "SELECT COUNT(*) FROM workflow_renewal_rejections WHERE job_id=?",
                        (job_id,),
                    ).fetchone()[0]
                    >= 128
                ):
                    raise ValueError("Renewal disposition capacity reached")
                db.execute(
                    "INSERT INTO workflow_renewal_rejections VALUES (?,?,?)",
                    (job_id, key, fingerprint),
                )
            return self.authorization_disposition(job_id, key, fingerprint)

    def latest_authorization(self, job_id):
        """Read the latest immutable linked authorization, never altering job inputs."""
        with self._lock:
            row = self.db.execute(
                "SELECT body FROM workflow_authorizations WHERE job_id=? ORDER BY renewal_id DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def renewable_attempt(self, job_id):
        """Require modern blocked work and its current never-released attempt."""
        with self._lock:
            job = self.get_job(job_id)
            attempt = self.get_attempt(job_id)
            if (
                job["kind"] != "generate"
                or job["inputs"].get("operation") not in ("new", "refine")
                or "workflow_authorization" not in job["inputs"]
                or job["status"] != "blocked_authorization"
                or attempt is None
                or attempt["state"] != "blocked_authorization"
            ):
                raise ValueError("Workflow is not renewable")
            return attempt

    def renew_authorization(self, job_id, key, fingerprint, attempt, metadata, *, max_pending=32):
        """Append guarded metadata and CAS the blocked job to queued in one transaction."""
        body = _receipt_json(metadata, max_bytes=16384)
        if not 1 <= len(key) <= 128 or len(fingerprint) != 64:
            raise ValueError("Invalid renewal binding")
        with self._transaction() as db:
            replay = self.get_authorization_replay(job_id, key, fingerprint)
            if replay is not None:
                return replay, False
            if self.authorization_disposition(job_id, key, fingerprint)["code"] == "renewal_rejected":
                raise ValueError("Renewal permanently rejected")
            if self.renewable_attempt(job_id) != attempt:
                raise ValueError("Workflow renewal conflict")
            count = db.execute(
                "SELECT COUNT(*) FROM jobs WHERE json_extract(body, '$.status') "
                "IN ('queued','running','cancel_requested','blocked_authorization')"
            ).fetchone()[0]
            if count > max_pending:
                raise ValueError("Workflow queue capacity reached")
            accepted = self._transition(db, job_id, "queued", "queued", "authorization_renewed")
            accepted_body = _receipt_json(accepted, max_bytes=1048576)
            db.execute(
                "INSERT INTO workflow_authorizations "
                "(job_id,blocked_generation,idempotency_key,fingerprint,schema_version,body,accepted_job) "
                "VALUES (?,?,?,?,1,?,?)",
                (job_id, attempt["generation"], key, fingerprint, body, accepted_body),
            )
            return accepted, True

    def claim_attempt(self, job_id):
        """Claim a queued job once; return its attempt_id/generation, or None."""
        with self._transaction() as db:
            job = self.get_job(job_id)
            if job["status"] != "queued" or self.queue_paused():
                return None
            generation = db.execute(
                "SELECT COALESCE(MAX(generation), 0)+1 FROM attempts WHERE job_id=?",
                (job_id,),
            ).fetchone()[0]
            attempt_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO attempts VALUES (?, ?, ?, 'claimed')",
                (attempt_id, job_id, generation),
            )
            self._transition(db, job_id, "running", "claimed", "attempt_claimed")
            return {"attempt_id": attempt_id, "generation": generation}

    def get_attempt(self, job_id):
        """Read the current durable attempt identity and state, or None."""
        with self._lock:
            row = self.db.execute(
                "SELECT attempt_id, generation, state FROM attempts WHERE job_id=? ORDER BY generation DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            return dict(row) if row else None

    def _attempt_matches(self, db, job_id, attempt_id, generation, expected_state):
        row = db.execute(
            "SELECT attempt_id, generation, state FROM attempts WHERE job_id=? ORDER BY generation DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        return bool(
            row
            and tuple(row) == (attempt_id, generation, expected_state)
            and self.get_job(job_id)["status"] == "running"
        )

    def _change_attempt(self, job_id, attempt_id, generation, expected_state, state, status):
        with self._transaction() as db:
            if not self._attempt_matches(db, job_id, attempt_id, generation, expected_state):
                return False
            db.execute("UPDATE attempts SET state=? WHERE attempt_id=?", (state, attempt_id))
            self._transition(db, job_id, status, state, "attempt_" + state)
            return True

    def release_attempt(self, job_id, attempt_id, generation):
        """CAS claimed to released; only the True winner may start external work."""
        return self._change_attempt(job_id, attempt_id, generation, "claimed", "released", "running")

    def block_attempt_authorization(self, job_id, attempt_id, generation):
        """Pause unreleased work without automatic renewal or requeue."""
        return self._change_attempt(
            job_id,
            attempt_id,
            generation,
            "claimed",
            "blocked_authorization",
            "blocked_authorization",
        )

    def progress_attempt(self, job_id, attempt_id, generation, *, expected_state, stage):
        """Commit progress only while the exact current attempt remains released."""
        if expected_state != "released" or not isinstance(stage, str) or len(stage) > 100:
            return False
        with self._transaction() as db:
            if not self._attempt_matches(db, job_id, attempt_id, generation, expected_state):
                return False
            self._transition(db, job_id, "running", stage, "stage_changed")
            return True

    def record_attempt_diagnostic(self, job_id, attempt_id, generation, *, expected_state, diagnostic, protect_public):
        """Append guarded static evidence only for the exact unfinished generation attempt."""
        from .generation_diagnostics import checked_diagnostic

        value = checked_diagnostic(diagnostic)
        public = {"diagnostic": value, "kind": "generation_diagnostic"}
        body = _json(public)
        protect_public(public)
        if _json(public) != body:
            raise ValueError("Public diagnostic guard must not mutate values")
        if expected_state not in ("claimed", "released"):
            return False
        with self._transaction() as db:
            if not self._attempt_matches(db, job_id, attempt_id, generation, expected_state):
                return False
            job = self.get_job(job_id)
            if job["kind"] != "generate" or self.get_candidate_receipt(job_id, attempt_id, generation) is not None:
                return False
            if "diagnostic" in job:
                return job["diagnostic"] == value
            job["diagnostic"] = value
            job["updated_at"] = time.time()
            db.execute("UPDATE jobs SET body=? WHERE id=?", (_json(job), job_id))
            self._event(db, job, "generation_diagnostic")
            return True

    def cancel_queued(self, job_id):
        """Cancel queued work atomically, including a renewed but unclaimed attempt."""
        with self._transaction() as db:
            job = self.get_job(job_id)
            if job["status"] != "queued":
                return job
            if db.execute("SELECT 1 FROM workers WHERE job_id=? AND cleaned=0", (job_id,)).fetchone():
                return job
            attempt = self.get_attempt(job_id)
            if attempt is not None:
                if attempt["state"] != "blocked_authorization":
                    return job
                db.execute(
                    "UPDATE attempts SET state='cancelled' WHERE attempt_id=?",
                    (attempt["attempt_id"],),
                )
            return self._transition(db, job_id, "cancelled", "cancelled", "cancelled")

    def request_cancel_attempt(self, job_id, attempt_id, generation, *, expected_state):
        """Fence execution immediately, retaining ownership until cleanup acknowledgement."""
        if expected_state not in ("claimed", "released", "candidate_committed"):
            return False
        return self._change_attempt(
            job_id,
            attempt_id,
            generation,
            expected_state,
            "cancel_requested",
            "cancel_requested",
        )

    def cancel_attempt(self, job_id, attempt_id, generation, *, expected_state):
        """Acknowledge cancellation only after all recorded worker ownership is cleaned."""
        with self._transaction() as db:
            attempt = self.get_attempt(job_id)
            if attempt != {
                "attempt_id": attempt_id,
                "generation": generation,
                "state": expected_state,
            }:
                return False
            if db.execute("SELECT 1 FROM workers WHERE job_id=? AND cleaned=0", (job_id,)).fetchone():
                return False
            # Preserve the foundation's no-worker cancellation API.
            if expected_state not in (
                "claimed",
                "released",
                "cancel_requested",
                "blocked_authorization",
            ):
                return False
            if self.get_job(job_id)["status"] not in (
                "running",
                "cancel_requested",
                "blocked_authorization",
            ):
                return False
            db.execute(
                "UPDATE attempts SET state='cancelled' WHERE attempt_id=?",
                (attempt_id,),
            )
            self._transition(db, job_id, "cancelled", "cancelled", "attempt_cancelled")
            return True

    def fail_attempt(self, job_id, attempt_id, generation, *, expected_state):
        """Record a verified failure only for the current unfinished attempt."""
        if expected_state not in ("claimed", "released"):
            return False
        return self._change_attempt(job_id, attempt_id, generation, expected_state, "failed", "failed")

    def get_candidate_receipt(self, job_id, attempt_id, generation):
        """Read an immutable accepted receipt for exactly this attempt, or None."""
        with self._lock:
            row = self.db.execute(
                "SELECT body FROM candidate_receipts WHERE job_id=? AND attempt_id=? AND generation=? "
                "UNION ALL SELECT body FROM modern_candidate_receipts WHERE job_id=? AND attempt_id=? AND generation=?",
                (job_id, attempt_id, generation, job_id, attempt_id, generation),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def mark_attempt_indeterminate(self, job_id, attempt_id, generation, *, expected_state):
        """Fence an unknown outcome without making the attempt replayable."""
        if expected_state not in ("claimed", "released"):
            return False
        return self._change_attempt(
            job_id,
            attempt_id,
            generation,
            expected_state,
            "indeterminate",
            "indeterminate",
        )

    def queue_paused(self):
        """Read durable dispatch pause state without changing legacy snapshot shape."""
        with self._lock:
            return bool(self.db.execute("SELECT value FROM metadata WHERE key='queue_paused'").fetchone()[0])

    def commit_candidate(self, job_id, attempt_id, generation, *, receipt):
        """Accept a receipt atomically; identical retries succeed without a new event.

        Caller MUST run protect_public before passing a receipt: JSON validation is
        not secret detection. Never pass credentials, raw provider responses or
        exception text. Only JSON objects up to MAX_RECEIPT_BYTES and depth 32 are
        accepted. This records a candidate, NOT a publication or filesystem grant.
        """
        modern = self.get_job(job_id)["inputs"].get("operation") in ("new", "refine")
        body = _receipt_json(receipt, max_bytes=MAX_MODERN_RECEIPT_BYTES if modern else MAX_RECEIPT_BYTES)
        with self._transaction() as db:
            existing = self.get_candidate_receipt(job_id, attempt_id, generation)
            if existing is not None:
                if _json(existing) != body:
                    raise ValueError("Candidate receipt conflict")
                return True
            if not self._attempt_matches(db, job_id, attempt_id, generation, "released"):
                return False
            db.execute(
                "INSERT INTO "
                + ("modern_candidate_receipts" if modern else "candidate_receipts")
                + " VALUES (?, ?, ?, 1, ?)",
                (attempt_id, job_id, generation, body),
            )
            db.execute(
                "UPDATE attempts SET state='candidate_committed' WHERE attempt_id=?",
                (attempt_id,),
            )
            self._transition(db, job_id, "running", "candidate_committed", "candidate_committed")
            return True

    def complete_attempt(self, job_id, attempt_id, generation, *, expected_state):
        """Adopt the accepted receipt as result; never authorize external publication."""
        if expected_state != "candidate_committed":
            return False
        with self._transaction() as db:
            if not self._attempt_matches(db, job_id, attempt_id, generation, expected_state):
                return False
            receipt = self.get_candidate_receipt(job_id, attempt_id, generation)
            if receipt is None:
                return False
            db.execute(
                "UPDATE attempts SET state='completed' WHERE attempt_id=?",
                (attempt_id,),
            )
            self._transition(
                db,
                job_id,
                "succeeded",
                "completed",
                "attempt_completed",
                result=receipt,
            )
            return True

    def get_submission(self, workspace_id, key):
        """Recover a workspace-wide idempotency binding without authorizing new work."""
        with self._lock:
            row = self.db.execute(
                "SELECT body FROM jobs WHERE workspace_id=? AND idempotency_key=?",
                (workspace_id, key),
            ).fetchone()
            return json.loads(row["body"]) if row else None

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
            if db.execute("SELECT 1 FROM attempts WHERE job_id=?", (job_id,)).fetchone():
                raise ValueError("Use attempt identity and CAS for attempt-managed jobs")
            return self._transition(db, job_id, status, stage, kind, result=result, error=error)

    def _transition(self, db, job_id, status, stage, kind, *, result=None, error=None):
        job = self.get_job(job_id)
        attempt = self.get_attempt(job_id)
        if attempt is not None:
            execution = job.get(
                "execution",
                {
                    "released": False,
                    "candidate_accepted": False,
                    "outcome": "not_released",
                },
            )
            if kind == "attempt_claimed":
                execution = {
                    "released": False,
                    "candidate_accepted": False,
                    "outcome": "not_released",
                }
            elif kind == "attempt_released":
                execution.update(released=True, outcome="unknown")
            receipt = self.get_candidate_receipt(job_id, attempt["attempt_id"], attempt["generation"])
            if receipt is not None:
                execution.update(released=True, candidate_accepted=True, outcome="candidate_accepted")
                result = receipt
            job["execution"] = execution
        job.update(
            status=status,
            stage=stage,
            updated_at=time.time(),
            result=result,
            error=error,
        )
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
                attempt = db.execute(
                    "SELECT attempt_id, generation, state FROM attempts WHERE job_id=? ORDER BY generation DESC"
                    " LIMIT 1",
                    (row[0],),
                ).fetchone()
                if attempt:
                    receipt = self.get_candidate_receipt(row[0], attempt[0], attempt[1])
                    if (
                        attempt[2] in ("candidate_committed", "cancel_requested")
                        and db.execute(
                            "SELECT 1 FROM workers WHERE job_id=? AND cleaned=0",
                            (row[0],),
                        ).fetchone()
                    ):
                        self._recovery_attempts[row[0]] = dict(attempt)
                        continue
                    if receipt is not None and attempt[2] == "candidate_committed":
                        db.execute(
                            "UPDATE attempts SET state='completed' WHERE attempt_id=?",
                            (attempt[0],),
                        )
                        self._transition(
                            db,
                            row[0],
                            "succeeded",
                            "completed",
                            "candidate_adopted",
                            result=receipt,
                        )
                        continue
                    if attempt[2] == "cancel_requested":
                        db.execute(
                            "UPDATE attempts SET state='cancelled' WHERE attempt_id=?",
                            (attempt[0],),
                        )
                        self._transition(db, row[0], "cancelled", "cancelled", "attempt_cancelled")
                        continue
                    db.execute(
                        "UPDATE attempts SET state='indeterminate' WHERE attempt_id=?",
                        (attempt[0],),
                    )
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
            db.execute(
                "INSERT INTO workers VALUES (?, ?, ?, 0)",
                (job_id, pid, _json(identity)),
            )

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
        attempt = self._recovery_attempts.pop(job_id, None)
        if attempt:
            state = attempt.pop("state")
            if state == "candidate_committed":
                self.complete_attempt(job_id, **attempt, expected_state=state)
            elif state == "cancel_requested":
                self.cancel_attempt(job_id, **attempt, expected_state=state)

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
                for row in db.execute(
                    "SELECT id, body FROM events WHERE id>? ORDER BY id LIMIT ?",
                    (cursor, limit),
                )
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
            db.execute(
                "UPDATE metadata SET value=MAX(value, ?) WHERE key='pruned_through'",
                (through,),
            )
