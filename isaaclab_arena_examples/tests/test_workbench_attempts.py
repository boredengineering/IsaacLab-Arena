# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Attempt fencing and durable receipts, without simulation or external jobs."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal


def submit(journal, key="one"):
    return journal.submit("s", "default", "generate", key, {})["id"]


def test_independent_connections_claim_one_winner(tmp_path):
    path = tmp_path / "journal.sqlite3"
    first, second = Journal(path), Journal(path)
    try:
        job_id = submit(first)
        barrier = Barrier(2)

        def claim(journal):
            barrier.wait()
            return journal.claim_attempt(job_id)

        with ThreadPoolExecutor(2) as pool:
            claims = list(pool.map(claim, (first, second)))
        winners = [claim for claim in claims if claim is not None]
        assert len(winners) == 1
        assert winners[0]["generation"] == 1
        assert winners[0]["attempt_id"]
        assert first.get_job(job_id)["stage"] == "claimed"
        assert len(first.events_after(0)) == 2
        assert first.claim_attempt(job_id) is None
    finally:
        first.close()
        second.close()


def test_cancel_fences_release_and_obsolete_callbacks(tmp_path):
    journal = Journal(tmp_path / "journal.sqlite3")
    try:
        job_id = submit(journal)
        identity = journal.claim_attempt(job_id)
        assert not journal.release_attempt(job_id, identity["attempt_id"], 999)
        assert journal.cancel_attempt(job_id, **identity, expected_state="claimed")
        assert not journal.release_attempt(job_id, **identity)
        assert not journal.fail_attempt(job_id, **identity, expected_state="claimed")
        assert journal.get_job(job_id)["status"] == "cancelled"
        with pytest.raises(ValueError, match="attempt"):
            journal.transition(job_id, "running", "starting", "started")
        other = submit(journal, "other")
        current = journal.claim_attempt(other)
        assert journal.release_attempt(other, **current)
        assert not journal.release_attempt(other, **current)
        assert not journal.fail_attempt(other, **identity, expected_state="released")
        assert journal.fail_attempt(other, **current, expected_state="released")
        assert not journal.cancel_attempt(other, **current, expected_state="failed")
    finally:
        journal.close()


def test_receipt_is_bounded_immutable_atomic_and_identity_fenced(tmp_path):
    journal = Journal(tmp_path / "journal.sqlite3")
    try:
        job_id = submit(journal)
        identity = journal.claim_attempt(job_id)
        receipt = {"schema_version": 1, "candidate": {"summary": "safe public result"}}
        assert not journal.commit_candidate(job_id, **identity, receipt=receipt)
        assert journal.release_attempt(job_id, **identity)
        for bad in ({"x": float("nan")}, {"x": b"bytes"}, {"x": "x" * 65536}, {1: "key"}, []):
            with pytest.raises(ValueError):
                journal.commit_candidate(job_id, **identity, receipt=bad)
        journal.db.execute("CREATE TRIGGER fault BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'fault'); END")
        with pytest.raises(sqlite3.IntegrityError, match="fault"):
            journal.commit_candidate(job_id, **identity, receipt=receipt)
        assert journal.get_candidate_receipt(job_id, **identity) is None
        journal.db.execute("DROP TRIGGER fault")
        assert journal.commit_candidate(job_id, **identity, receipt=receipt)
        cursor = journal.snapshot()["event_cursor"]
        assert journal.commit_candidate(job_id, **identity, receipt=receipt)
        assert journal.snapshot()["event_cursor"] == cursor
        with pytest.raises(ValueError, match="conflict"):
            journal.commit_candidate(job_id, **identity, receipt={"candidate": "different"})
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            journal.db.execute("UPDATE candidate_receipts SET body='{}'")
        assert journal.get_candidate_receipt(job_id, **identity) == receipt
        assert not journal.complete_attempt(job_id, identity["attempt_id"], 99, expected_state="candidate_committed")
        assert journal.complete_attempt(job_id, **identity, expected_state="candidate_committed")
        assert not journal.cancel_attempt(job_id, **identity, expected_state="candidate_committed")
        assert journal.get_job(job_id)["status"] == "succeeded"
        assert journal.get_job(job_id)["result"] == receipt
    finally:
        journal.close()


def test_restart_adopts_receipt_but_never_replays_unknown_attempt(tmp_path):
    path = tmp_path / "journal.sqlite3"
    journal = Journal(path)
    journal.begin_run()
    accepted, unknown, claimed = (submit(journal, key) for key in ("accepted", "unknown", "claimed"))
    accepted_id, unknown_id, claimed_id = (journal.claim_attempt(job) for job in (accepted, unknown, claimed))
    assert journal.release_attempt(accepted, **accepted_id)
    assert journal.release_attempt(unknown, **unknown_id)
    receipt = {"candidate": "public"}
    assert journal.commit_candidate(accepted, **accepted_id, receipt=receipt)
    journal.close()
    journal = Journal(path)
    try:
        assert journal.begin_run()
        assert journal.get_job(accepted)["status"] == "succeeded"
        assert journal.get_candidate_receipt(accepted, **accepted_id) == receipt
        for job, identity in ((unknown, unknown_id), (claimed, claimed_id)):
            assert journal.get_job(job)["status"] == "indeterminate"
            assert journal.claim_attempt(job) is None
            assert not journal.release_attempt(job, **identity)
            assert not journal.commit_candidate(job, **identity, receipt=receipt)
        assert journal.queue_paused()
        queued = submit(journal, "queued")
        assert journal.claim_attempt(queued) is None
        journal.resume_queue()
        assert not journal.queue_paused()
        identity = journal.claim_attempt(queued)
        assert journal.mark_attempt_indeterminate(queued, **identity, expected_state="claimed")
        assert not journal.fail_attempt(queued, **identity, expected_state="claimed")
    finally:
        journal.close()


@pytest.mark.parametrize("version", [2, 99])
def test_incompatible_version_refused_without_migration_and_connection_closed(tmp_path, monkeypatch, version):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version={version}")
    opened = []
    connect = sqlite3.connect

    def tracked(*args, **kwargs):
        connection = connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked)
    with pytest.raises(RuntimeError, match="schema"):
        Journal(path)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")
    with connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == version
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []


def test_additive_schema_metadata_and_idempotent_close(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
        db.execute("INSERT INTO metadata VALUES ('pruned_through', 42)")
    journal = Journal(path)
    assert journal.db.execute("PRAGMA user_version").fetchone()[0] == 1
    assert journal.db.execute("SELECT value FROM metadata WHERE key='attempt_schema_version'").fetchone()[0] == 1
    assert journal.db.execute("SELECT value FROM metadata WHERE key='pruned_through'").fetchone()[0] == 42
    journal.db.execute("UPDATE metadata SET value=2 WHERE key='attempt_schema_version'")
    journal.close()
    journal.close()
    with pytest.raises(RuntimeError, match="schema"):
        Journal(path)


def test_attempt_identity_can_be_recovered_after_close(tmp_path):
    path = tmp_path / "journal.sqlite3"
    journal = Journal(path)
    job_id = submit(journal)
    assert journal.get_attempt(job_id) is None
    identity = journal.claim_attempt(job_id)
    journal.close()
    journal = Journal(path)
    try:
        assert journal.get_attempt(job_id) == {**identity, "state": "claimed"}
        assert journal.release_attempt(job_id, **identity)
        assert journal.get_attempt(job_id) == {**identity, "state": "released"}
    finally:
        journal.close()
