# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Registry and schema reads are authenticated and never submit work."""

import hashlib
import json
import socket

from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app
from isaaclab_arena_examples.tests.test_workbench_editor import ORIGIN, login


def test_schema_and_catalogue_are_actual_read_only_metadata(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import EnvironmentGenerationAgent

    def denied(*args, **kwargs):
        raise AssertionError("Metadata access started external work")

    monkeypatch.setattr(EnvironmentGenerationAgent, "__init__", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as peer:
        for path in ("schema", "catalogues"):
            assert peer.get("/api/editor/" + path).status_code == 401
        login(peer)
        schema = peer.get("/api/editor/schema")
        assert schema.status_code == 200, schema.text
        assert "env_name" in schema.json()["schema"]["properties"]
        catalogue = peer.get("/api/editor/catalogues")
        assert catalogue.status_code == 200, catalogue.text
        data = catalogue.json()
        assert data["read_only"] is True
        assert any(obj["name"] == "banana_ycb_robolab" for obj in data["catalogues"]["assets"]["objects"])
        assert any(task["name"] == "PickAndPlaceTask" for task in data["catalogues"]["tasks"]["tasks"])
        canonical = json.dumps(data["catalogues"], sort_keys=True, separators=(",", ":"), allow_nan=False)
        assert data["catalogue_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
        assert peer.get("/api/editor/catalogues").json() == data
        assert peer.get("/api/jobs").json()["jobs"] == []
