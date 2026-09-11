# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Opaque durable browser sessions, independent of job ownership."""

import hashlib
import secrets
import time


class Sessions:
    """Store cookie digests; only explicit activity extends the idle deadline."""

    def __init__(self, journal, *, clock=time.time, idle_seconds=86400, absolute_seconds=604800):
        self.journal = journal
        self.clock = clock
        self.idle_seconds = idle_seconds
        self.absolute_seconds = absolute_seconds
        with journal._transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS sessions (
                digest TEXT PRIMARY KEY, session_id TEXT NOT NULL, csrf_token TEXT NOT NULL,
                expires_at REAL NOT NULL, absolute_at REAL NOT NULL
            )""")

    def get(self, token):
        """Validate a cookie without refreshing either deadline."""
        if not token:
            return None
        with self.journal._transaction() as db:
            row = db.execute("SELECT * FROM sessions WHERE digest=?", (self._digest(token),)).fetchone()
            if row is None or self.clock() >= min(row["expires_at"], row["absolute_at"]):
                return None
            return {key: row[key] for key in ("session_id", "csrf_token", "expires_at")}

    @staticmethod
    def _digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def create(self):
        """Create a fresh session and return its public record and opaque cookie."""
        token = secrets.token_urlsafe(32)
        now = self.clock()
        body = {
            "session_id": secrets.token_hex(16),
            "csrf_token": secrets.token_urlsafe(32),
            "expires_at": now + min(self.idle_seconds, self.absolute_seconds),
        }
        with self.journal._transaction() as db:
            db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                (
                    self._digest(token),
                    body["session_id"],
                    body["csrf_token"],
                    body["expires_at"],
                    now + self.absolute_seconds,
                ),
            )
        return body, token

    def activity(self, token):
        """Extend a valid session only as far as its original absolute deadline."""
        with self.journal._transaction() as db:
            db.execute(
                "UPDATE sessions SET expires_at=MIN(absolute_at, ?) WHERE digest=? AND expires_at>?",
                (self.clock() + self.idle_seconds, self._digest(token), self.clock()),
            )
        return self.get(token)

    def revoke(self, token):
        """Revoke this browser credential without touching its jobs."""
        with self.journal._transaction() as db:
            db.execute("DELETE FROM sessions WHERE digest=?", (self._digest(token),))
