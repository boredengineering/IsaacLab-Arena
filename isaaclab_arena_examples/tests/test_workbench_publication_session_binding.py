# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Internal session checks can participate in a publication release transaction."""

from contextlib import closing

import pytest

from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena.agentic_environment_generation.workbench.sessions import Sessions


@pytest.mark.parametrize("expired", [False, True])
def test_internal_session_read_does_not_nest_transactions_or_refresh_expiry(tmp_path, expired):
    clock = [1000.0]
    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        sessions = Sessions(journal, clock=lambda: clock[0], idle_seconds=5, absolute_seconds=10)
        session, _ = sessions.create()
        if expired:
            clock[0] += 6
        changes = journal.db.total_changes
        with journal._transaction():
            result = sessions.get_by_id(session["session_id"])
            assert result == (
                None if expired else {"session_id": session["session_id"], "expires_at": session["expires_at"]}
            )
        assert journal.db.total_changes == changes
