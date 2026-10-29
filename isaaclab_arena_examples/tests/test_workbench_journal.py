# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Durable workbench state, without simulator initialization."""

import sqlite3

import pytest


def test_acceptance_is_durable_atomic_and_operator_idempotent(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal

    path = tmp_path / "journal.sqlite3"
    journal = Journal(path)
    inputs = {"steps": 2, "delay_seconds": 0.1}
    job = journal.submit("session-a", "default", "diagnostic", "request-1", inputs)
    assert job["status"] == "queued"
    assert journal.snapshot() == {"jobs": [job], "event_cursor": 1}
    assert journal.events_after(0)[0]["job"] == job
    journal.close()
    journal = Journal(path)
    assert journal.submit("session-b", "default", "diagnostic", "request-1", inputs) == job
    with pytest.raises(ValueError, match="Idempotency"):
        journal.submit("session-b", "default", "diagnostic", "request-1", {**inputs, "steps": 3})
    assert len(journal.snapshot()["jobs"]) == 1
    # A real SQLite trigger fault proves state and event writes roll back together.
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'fault'); END")
    with pytest.raises(sqlite3.IntegrityError, match="fault"):
        journal.transition(job["id"], "running", "starting", "started")
    assert journal.get_job(job["id"]) == job
    assert journal.snapshot()["event_cursor"] == 1
    journal.close()


def test_retention_gap_keeps_active_events_and_monotonic_snapshot_cursor(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal, ReplayGap

    journal = Journal(tmp_path / "journal.sqlite3")
    job = journal.submit("s", "default", "diagnostic", "one", {"steps": 1, "delay_seconds": 0.1})
    journal.prune_events(now=job["created_at"] + 9 * 86400)
    assert len(journal.events_after(0)) == 1  # Never prune active job events.
    terminal = journal.transition(job["id"], "cancelled", "cancelled", "cancelled")
    journal.prune_events(now=terminal["updated_at"] + 6 * 86400)
    assert len(journal.events_after(0)) == 2  # At least seven days.
    journal.prune_events(now=terminal["updated_at"] + 9 * 86400)
    assert journal.snapshot()["event_cursor"] == 2
    assert journal.events_after(2) == []
    with pytest.raises(ReplayGap):
        journal.events_after(0)
    with pytest.raises(ReplayGap):
        journal.events_after(999)
    assert journal.get_job(job["id"]) == terminal
    new = journal.submit("s", "default", "diagnostic", "two", {"steps": 1, "delay_seconds": 0.1})
    assert journal.events_after(2)[0]["id"] == 3
    assert journal.events_after(2)[0]["job"] == new
    journal.close()


def test_unclean_restart_marks_started_work_indeterminate_and_pauses_queue(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal

    path = tmp_path / "restart.sqlite3"
    journal = Journal(path)
    assert journal.begin_run() is False
    active = journal.submit("s", "default", "diagnostic", "active", {"steps": 1, "delay_seconds": 0.1})
    queued = journal.submit("s", "default", "diagnostic", "queued", {"steps": 1, "delay_seconds": 0.1})
    journal.transition(active["id"], "running", "worker_starting", "started")
    journal.close()  # No clean shutdown marker: equivalent journal state to process loss.
    journal = Journal(path)
    assert journal.begin_run() is True
    recovered = journal.get_job(active["id"])
    assert recovered["status"] == "indeterminate"
    assert journal.get_job(queued["id"])["status"] == "queued"
    assert journal.events_after(3)[0]["job"] == recovered
    assert journal.events_after(3)[0]["kind"] == "indeterminate"
    journal.finish_run()
    journal.close()
    journal = Journal(path)
    assert journal.begin_run() is True  # Pause survives even a subsequent clean restart.
    journal.resume_queue()
    journal.finish_run()
    journal.close()
    journal = Journal(path)
    assert journal.begin_run() is False
    assert journal.get_job(active["id"])["status"] == "indeterminate"
    journal.finish_run()
    journal.close()


def test_journal_refuses_symlinks_and_enforces_private_database(tmp_path):
    import stat

    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal

    target = tmp_path / "untouched"
    target.write_text("not a database")
    link = tmp_path / "journal.sqlite3"
    link.symlink_to(target)
    with pytest.raises(RuntimeError, match="regular"):
        Journal(link)
    assert target.read_text() == "not a database"
    link.unlink()
    journal = Journal(link)
    assert stat.S_IMODE(link.stat().st_mode) == 0o600
    journal.close()
