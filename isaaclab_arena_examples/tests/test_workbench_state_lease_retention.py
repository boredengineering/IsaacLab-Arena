# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Retained cleanup obligations outlive the launcher's lease context."""

import pytest

from isaaclab_arena_examples.agentic_environment_generation.web_api.runtime import StateLease


def test_retained_lease_outlives_outer_context(tmp_path):
    with StateLease(tmp_path) as lease:
        first = lease.retain()
        second = lease.retain()
    with pytest.raises(RuntimeError, match="already owns"):
        with StateLease(tmp_path):
            pass
    first.release()
    first.release()
    with pytest.raises(RuntimeError, match="already owns"):
        with StateLease(tmp_path):
            pass
    second.release()
    with StateLease(tmp_path):
        pass


def test_borrowed_lease_wrong_directory_rejected_before_journal(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import application

    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    # Sentinels must never reach a Journal constructor, much less dirty reset.
    for directory in (first, second):
        (directory / "journal.sqlite3").write_bytes(directory.name.encode())

    def forbidden(*args, **kwargs):
        pytest.fail("Mismatched lease reached journal construction")

    monkeypatch.setattr(application, "Journal", forbidden)
    with StateLease(first) as lease:
        before = {(p.parent.name, p.name): p.read_bytes() for d in (first, second) for p in d.iterdir()}
        with pytest.raises(ValueError, match="lease"):
            application.create_app(second, _state_lease=lease)
        assert {(p.parent.name, p.name): p.read_bytes() for d in (first, second) for p in d.iterdir()} == before


def test_closed_borrowed_lease_rejected_before_startup(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    with StateLease(tmp_path) as lease:
        pass
    with pytest.raises(ValueError, match="lease"):
        create_app(tmp_path, _state_lease=lease)


def test_borrowed_lease_closed_between_construction_and_entry(tmp_path):
    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    with StateLease(tmp_path) as lease:
        app = create_app(tmp_path, _state_lease=lease)
    with pytest.raises(ValueError, match="lease"):
        with TestClient(app, base_url="http://127.0.0.1:3000"):
            pytest.fail("Expired borrowed lease reached lifespan")
    assert not (tmp_path / "journal.sqlite3").exists()


def test_matching_borrowed_path_stays_bound_across_cwd_change(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    monkeypatch.chdir(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    directory = tmp_path / "state"
    with StateLease(directory) as lease:
        app = create_app("state", _state_lease=lease)
        monkeypatch.chdir(elsewhere)
        with TestClient(app, base_url="http://127.0.0.1:3000"):
            actual = app.state.journal.db.execute("PRAGMA database_list").fetchone()[2]
            assert actual == str(directory / "journal.sqlite3")
            assert app.state._cleanup.journal_path == directory / "journal.sqlite3"
    assert not (elsewhere / "state").exists()


def test_state_symlink_is_not_normalized_into_permission(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    directory = tmp_path / "state"
    directory.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError, match="[Ss]ymlink"):
        create_app(alias)
