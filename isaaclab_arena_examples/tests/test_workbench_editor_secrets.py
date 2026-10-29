# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Editor secret boundaries use real YAML validation and dummy credentials only."""

import socket

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, generation
from isaaclab_arena_examples.tests.test_workbench_editor import FIXTURE, ORIGIN, login
from isaaclab_arena_examples.tests.test_workbench_model_settings import BODY, KEY


@pytest.fixture(autouse=True)
def no_external_work(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("Unexpected network or provider invocation")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(generation, "configuration", lambda: None)
    monkeypatch.setattr(generation, "generate", denied)


def escaped_key(encoding="hex"):
    if encoding == "folded":
        return '"dummy-private-' + chr(92) + '\n  provider-marker-123456"'
    prefix, width = {"hex": ("x", 2), "unicode": ("u", 4), "long_unicode": ("U", 8)}[encoding]
    return '"' + "".join(f"\\{prefix}{ord(char):0{width}x}" for char in KEY) + '"'


def secret_yaml():
    return FIXTURE.read_text().replace("pick_and_place_maple_table_default", escaped_key())


@pytest.mark.parametrize("route", ["validate", "save", "generate", "snapshots"])
@pytest.mark.parametrize("location", ["value", "dict_key", "error", "syntax_error", "folded_error", "comment"])
def test_editor_rejects_secret_before_diagnostics_or_persistence(tmp_path, route, location):
    text = secret_yaml()
    if location == "dict_key":
        text = FIXTURE.read_text().replace("params: {}", f"params: {{{escaped_key()}: harmless}}", 1)
    elif location == "error":
        text = FIXTURE.read_text() + f"\n{escaped_key()}: unknown\n"
    elif location == "syntax_error":
        text = f"env_name: [{escaped_key()} invalid\n"
    elif location == "folded_error":
        text = f"env_name: [{escaped_key('folded')} invalid\n"
    elif location == "comment":
        text = FIXTURE.read_text() + f"\n# {KEY}\n"
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        status = client.put("/api/model-settings", headers=headers, json=BODY).json()
        body = {"yaml_text": text}
        if route == "generate":
            body = {"base_yaml": text, "prompt": "Move cube", "credential_ref": status["credential_ref"]}
        if route in {"generate", "snapshots"}:
            body["idempotency_key"] = "encoded"
        response = client.post(f"/api/editor/{route}", headers=headers, json=body)
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}
        assert client.get("/api/jobs").json()["jobs"] == []
        assert not (tmp_path / "editor-revisions").exists()
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert KEY.encode() not in path.read_bytes()
            assert escaped_key().encode() not in path.read_bytes()


@pytest.mark.parametrize("route", ["validate", "save", "generate", "snapshots"])
@pytest.mark.parametrize("text", ["env_name: [broken", 'env_name: "\\U00110000"', "a: &x [1]\nb: *x\n"])
def test_secret_guards_preserve_invalid_yaml_diagnostics(tmp_path, route, text):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        client.put("/api/model-settings", headers=headers, json=BODY)
        expected = app.state.documents.validate(text)
        assert not expected["valid"]
        body = {"yaml_text": text}
        if route == "generate":
            body = {"base_yaml": text, "prompt": "Move cube"}
        if route in {"generate", "snapshots"}:
            body["idempotency_key"] = "invalid"
        response = client.post(f"/api/editor/{route}", headers=headers, json=body)
        assert response.status_code == (200 if route == "validate" else 422)
        if route == "validate":
            assert response.json() == expected
        elif route == "save":
            assert response.json() == {"detail": "Invalid environment specification: " + "; ".join(expected["errors"])}
        else:
            assert response.json() == {
                "detail": {"message": "Invalid Arena environment specification", "errors": expected["errors"]}
            }


@pytest.mark.parametrize("replay", [False, True])
def test_complete_generation_metadata_is_guarded_even_on_prior_replay(tmp_path, monkeypatch, replay):
    future_key = "another-dummy-private-key-654321"
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        settings = client.put("/api/model-settings", headers=headers, json={**BODY, "model": future_key}).json()
        body = {"prompt": "Move cube", "idempotency_key": "metadata", "credential_ref": settings["credential_ref"]}
        if replay:
            assert client.post("/api/editor/generate", headers=headers, json=body).status_code == 202
        owner_cookies = dict(client.cookies)
        client.cookies.clear()
        other_headers = login(client)
        assert (
            client.put("/api/model-settings", headers=other_headers, json={**BODY, "api_key": future_key}).status_code
            == 200
        )
        client.cookies.clear()
        client.cookies.update(owner_cookies)
        if replay:
            monkeypatch.setattr(app.state.model_settings, "resolve", lambda *args: pytest.fail("Replay reauthorized"))
        before = app.state.journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        response = client.post("/api/editor/generate", headers=headers, json=body)
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}
        assert app.state.journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == before


def test_snapshot_submission_guards_idempotency_key(tmp_path):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        client.put("/api/model-settings", headers=headers, json=BODY)
        response = client.post(
            "/api/editor/snapshots", headers=headers, json={"yaml_text": FIXTURE.read_text(), "idempotency_key": KEY}
        )
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}
        assert client.get("/api/jobs").json()["jobs"] == []


@pytest.mark.parametrize("route", ["validate", "save", "generate", "snapshots"])
def test_decoded_validation_warnings_are_guarded(tmp_path, monkeypatch, route):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        client.put("/api/model-settings", headers=headers, json=BODY)
        real_validate = app.state.documents.validate

        def warning(*args):
            result = real_validate(*args)
            result["warnings"].append({KEY: "warning"})
            return result

        monkeypatch.setattr(app.state.documents, "validate", warning)
        body = {"yaml_text": FIXTURE.read_text()}
        if route == "generate":
            body = {"base_yaml": FIXTURE.read_text(), "prompt": "Move cube"}
        if route in {"generate", "snapshots"}:
            body["idempotency_key"] = "warning"
        response = client.post(f"/api/editor/{route}", headers=headers, json=body)
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}
        assert client.get("/api/jobs").json()["jobs"] == []
        assert not (tmp_path / "editor-revisions").exists()


@pytest.mark.parametrize("route", ["document", "generate"])
def test_server_loaded_yaml_is_guarded_before_public_response(tmp_path, route):
    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents

    source = tmp_path / "repo/generated_envs/scene.yaml"
    source.parent.mkdir(parents=True)
    source.write_text(secret_yaml())
    app = create_app(tmp_path / "state", start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        app.state.documents = Documents(tmp_path / "state", root=tmp_path / "repo")
        document_id = app.state.documents.index()[0]["id"]
        headers = login(client)
        status = client.put("/api/model-settings", headers=headers, json=BODY).json()
        if route == "document":
            response = client.get(f"/api/editor/documents/{document_id}")
        else:
            response = client.post(
                "/api/editor/generate",
                headers=headers,
                json={
                    "document_id": document_id,
                    "prompt": "Move cube",
                    "idempotency_key": "source",
                    "credential_ref": status["credential_ref"],
                },
            )
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}
        assert client.get("/api/jobs").json()["jobs"] == []


def test_download_rechecks_revision_against_current_credentials(tmp_path):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        revision = client.post("/api/editor/save", headers=headers, json={"yaml_text": secret_yaml()}).json()
        assert client.get(revision["download_url"]).status_code == 200
        client.put("/api/model-settings", headers=headers, json=BODY)
        response = client.get(revision["download_url"])
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}


@pytest.mark.parametrize("encoding", ["hex", "folded"])
def test_save_guards_unused_frozen_include_bytes_before_revision_write(tmp_path, encoding):
    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents

    source = tmp_path / "repo/generated_envs/scene.yaml"
    source.parent.mkdir(parents=True)
    # Double-quoted YAML line continuation decodes without any hex escapes.
    secret = escaped_key(encoding)
    (source.parent / "included.yaml").write_text(
        FIXTURE.read_text().replace("pick_and_place_maple_table_default", secret)
    )
    source.write_text("external_yaml: included.yaml\n")
    state = tmp_path / "state"
    app = create_app(state, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        app.state.documents = Documents(state, root=tmp_path / "repo")
        source_id = next(item["id"] for item in app.state.documents.index() if item["name"] == "scene")
        original = app.state.documents.load(source_id)
        assert app.state.documents.frozen[original["document_id"]]
        assert original["validation"]["valid"]
        assert original["validation"]["spec"]["env_name"] == KEY
        headers = login(client)
        client.put("/api/model-settings", headers=headers, json=BODY)
        response = client.post(
            "/api/editor/save",
            headers=headers,
            json={"yaml_text": FIXTURE.read_text(), "document_id": original["document_id"]},
        )
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}
        assert not (state / "editor-revisions").exists()


@pytest.mark.parametrize("encoding", ["hex", "unicode", "long_unicode", "folded"])
def test_generate_rejects_decoded_secret_before_journaling(tmp_path, encoding):
    text = FIXTURE.read_text().replace("pick_and_place_maple_table_default", escaped_key(encoding))
    assert KEY not in text
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        status = client.put("/api/model-settings", headers=headers, json=BODY).json()
        validation = app.state.documents.validate(text)
        assert validation["valid"]
        assert validation["spec"]["env_name"] == KEY
        response = client.post(
            "/api/editor/generate",
            headers=headers,
            json={
                "prompt": "Move cube",
                "base_yaml": text,
                "idempotency_key": "encoded",
                "credential_ref": status["credential_ref"],
            },
        )
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}
        assert client.get("/api/jobs").json()["jobs"] == []
    assert all(KEY.encode() not in path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
