# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Editor publication capability reflects this app's admission gate only."""

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app
from isaaclab_arena_examples.tests.test_workbench_editor import ORIGIN, login


@pytest.mark.parametrize("admitting", [None, False, True, "true", 1])
def test_publication_capability_uses_strict_actual_app_admission(tmp_path, admitting):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/editor").status_code == 401
        login(client)
        if admitting is None:
            del app.state.publication_admitting
        else:
            app.state.publication_admitting = admitting
        # Profile presence / connectivity are not execution authority.
        app.state.publication_profiles = {"configured": {}}
        app.state.neo4j_available = True
        result = client.get("/api/editor")
        assert result.status_code == 200
        assert result.json()["capabilities"]["publication_execution"] is (admitting is True)
        app.state.publication_profiles = {}
        app.state.neo4j_available = False
        assert client.get("/api/editor").json()["capabilities"]["publication_execution"] is (admitting is True)
        assert client.get("/api/jobs").json()["jobs"] == []
