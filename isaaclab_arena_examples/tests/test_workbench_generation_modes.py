# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit generation operations never infer a template or contact a provider."""

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, generation
from isaaclab_arena_examples.tests.test_workbench_editor import FIXTURE, ORIGIN, login


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(generation, "configuration", lambda: None)
    monkeypatch.setattr(generation, "generate", lambda *a, **k: pytest.fail("Unexpected inference"))
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as peer:
        headers = login(peer)
        saved = peer.put(
            "/api/model-settings",
            headers=headers,
            json={
                "provider": "openai",
                "model": "test-only-model",
                "api_key": "synthetic-mode-test-secret-12345",
            },
        )
        assert saved.status_code == 200
        yield peer, headers, saved.json()["credential_ref"]


def test_index_advertises_supported_modes_without_starting_work(client):
    peer, _, _ = client
    response = peer.get("/api/editor")
    assert response.status_code == 200
    assert response.json()["capabilities"]["generation_modes"] is True
    assert peer.get("/api/jobs").json()["jobs"] == []


def test_explicit_new_never_loads_the_selected_document(client, monkeypatch):
    peer, headers, reference = client
    monkeypatch.setattr(peer.app.state.documents, "load", lambda *a: pytest.fail("Implicit template load"))
    response = peer.post(
        "/api/editor/generate",
        headers=headers,
        json={
            "operation": "new",
            "prompt": "Droid moves banana onto a large plate",
            "idempotency_key": "new-a2",
            "credential_ref": reference,
            "retrieval_policy": "allow_fallback",
        },
    )
    assert response.status_code == 202, response.text
    inputs = response.json()["inputs"]
    assert inputs["operation"] == "new"
    assert inputs["retrieval_policy"] == "allow_fallback"
    assert inputs["base_yaml"] is None
    assert inputs["document_id"] is None
    assert inputs["input_hash"] is None
    replay = peer.post(
        "/api/editor/generate",
        headers=headers,
        json={
            "operation": "new",
            "prompt": "Droid moves banana onto a large plate",
            "idempotency_key": "new-a2",
            "credential_ref": reference,
            "retrieval_policy": "allow_fallback",
        },
    )
    assert replay.status_code == 202
    assert replay.json()["id"] == response.json()["id"]


@pytest.mark.parametrize(
    "extra", [{"base_yaml": None}, {"base_yaml": ""}, {"document_id": None}, {"document_id": "a" * 32}]
)
def test_new_rejects_any_implicit_base_fields(client, extra):
    peer, headers, reference = client
    response = peer.post(
        "/api/editor/generate",
        headers=headers,
        json={
            "operation": "new",
            "prompt": "A2",
            "idempotency_key": "invalid",
            "credential_ref": reference,
            **extra,
        },
    )
    assert response.status_code == 422
    assert peer.get("/api/jobs").json()["jobs"] == []


def test_refine_requires_a_valid_explicit_base_and_does_not_claim_retrieval(client):
    peer, headers, reference = client
    body = {
        "operation": "refine",
        "prompt": "Keep the objects",
        "idempotency_key": "refine",
        "credential_ref": reference,
    }
    assert peer.post("/api/editor/generate", headers=headers, json=body).status_code == 422
    assert peer.post("/api/editor/generate", headers=headers, json={**body, "base_yaml": "invalid"}).status_code == 422
    response = peer.post("/api/editor/generate", headers=headers, json={**body, "base_yaml": FIXTURE.read_text()})
    assert response.status_code == 202, response.text
    assert response.json()["inputs"]["operation"] == "refine"
    assert response.json()["inputs"]["input_hash"]
    assert (
        peer.post(
            "/api/editor/generate",
            headers=headers,
            json={
                **body,
                "base_yaml": FIXTURE.read_text(),
                "retrieval_policy": "require_service",
                "idempotency_key": "not-supported",
            },
        ).status_code
        == 422
    )
