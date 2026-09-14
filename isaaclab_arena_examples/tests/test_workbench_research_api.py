# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Managed research API remains opt-in and does not initialize stores on reads."""

import asyncio
import hashlib
import json
import socket

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
from isaaclab_arena.agentic_environment_generation.workbench.research_registry import ResearchRegistry
from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app
from isaaclab_arena_examples.tests.test_workbench_editor import ORIGIN, login
from isaaclab_arena_examples.tests.test_workbench_research_store import (
    candidate,
    mutate_public_metadata,
    public_callback_target,
)


def publication_profiles():
    return {
        "graph": {
            "connection": {
                "uri": "bolt://private.invalid:7687",
                "user": "operator",
                "password": "private-graph-password",
                "database": "neo4j",
            },
            "immutable_scope": True,
        }
    }


def test_publication_profiles_are_authenticated_bounded_metadata_without_schema(tmp_path, monkeypatch):
    app = create_app(tmp_path, start_paused=True, publication_profiles=publication_profiles())
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/research/publication-profiles").status_code == 401
        login(client)
        auth = app.state.publication_authorization
        monkeypatch.setattr(auth, "issue", lambda *a, **k: pytest.fail("grant issued"))
        before = app.state.journal.db.total_changes
        response = client.get("/api/research/publication-profiles")
        assert response.status_code == 200
        assert response.json() == {"profiles": [{**auth.profile_metadata("graph"), "available": True}]}
        assert set(response.json()["profiles"][0]) == {"profile_id", "revision", "scope_ownership", "available"}
        assert app.state.journal.db.total_changes == before
        assert (
            app.state.journal.db.execute("SELECT 1 FROM sqlite_master WHERE name='research_registry_meta'").fetchone()
            is None
        )
        assert "private.invalid" not in response.text and "private-graph-password" not in response.text
        app.state.publication_profiles["graph"]["immutable_scope"] = False
        assert client.get("/api/research/publication-profiles").json() == {"profiles": []}
        app.state.publication_profiles = {f"graph{i}": publication_profiles()["graph"] for i in range(17)}
        assert client.get("/api/research/publication-profiles").status_code == 409
        app.state.publication_profiles = {}
        assert client.get("/api/research/publication-profiles").json() == {"profiles": []}
        assert client.get("/api/jobs").json()["jobs"] == []


@pytest.fixture
def preparation(tmp_path, monkeypatch, request):
    from isaaclab_arena.agentic_environment_generation.workbench import research_graph_transport
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_scheduler import (
        PublicationScheduler,
    )

    app = create_app(
        tmp_path / "state",
        start_paused=True,
        research_roots={"primary": tmp_path / "managed"},
        publication_profiles=publication_profiles(),
    )
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)

        def unsupported(receipt):
            import yaml

            spec = yaml.safe_load(receipt["yaml_text"])
            spec["task"]["subtasks"][0]["params"].pop("background_scene")
            receipt["yaml_text"] = yaml.safe_dump(spec)
            receipt["validation"]["source_hash"] = hashlib.sha256(receipt["yaml_text"].encode()).hexdigest()

        source, _ = candidate(
            app.state.journal, receipt_change=unsupported if getattr(request, "param", None) == "unsupported" else None
        )
        with ResearchStore.create(
            app.state.journal,
            tmp_path / "managed",
            "primary",
            protect_public=app.state.model_settings.protect_public,
        ):
            pass

        def forbidden(*a, **k):
            pytest.fail("Preparation must not execute or authorize")

        monkeypatch.setattr(socket, "create_connection", forbidden)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
        monkeypatch.setattr(research_graph_transport, "publish_once", forbidden)
        monkeypatch.setattr(research_graph_transport, "reconcile_once", forbidden)
        monkeypatch.setattr(app.state.publication_authorization, "issue", forbidden)
        monkeypatch.setattr(PublicationScheduler, "enqueue", forbidden)
        payload = {
            "idempotency_key": "prepare",
            "family": "a2",
            "source_job_id": source["job_id"],
            "source_attempt_id": source["attempt_id"],
            "source_generation": source["generation"],
            "publication_target": app.state.publication_authorization.profile_metadata("graph"),
        }
        jobs = client.get("/api/jobs").json()["jobs"]
        yield app, client, headers, payload
        assert client.get("/api/jobs").json()["jobs"] == jobs
        assert not app.state.publication_authorization._records


@pytest.mark.parametrize("preparation", ["supported", "unsupported"], indirect=True)
def test_publication_binding_returns_exact_verified_props_read_only(preparation, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_payload import expected_receipt

    app, client, headers, payload = preparation
    base = "/api/research/stores/primary/versions"
    commit = client.post(base, headers=headers, json=payload).json()
    reservation = commit["reservation"]
    url = f"{base}/{reservation['reservation_id']}/publication-binding"
    registry = ResearchRegistry(app.state.journal)
    intent = registry.get_publication_intent(commit["publication_intent_id"])
    with ResearchStore.open(
        app.state.journal,
        app.state.research_roots["primary"],
        "primary",
        protect_public=app.state.model_settings.protect_public,
    ) as store:
        projection = json.loads(store.read_version(reservation["reservation_id"])["projection.json"])
    if projection["dcrg_mapping"]["status"] == "unsupported":
        assert projection["canonical_identity"]["name"] == "workbench__" + projection["canonical_identity"]["sha256"]
    before = app.state.journal.db.total_changes
    schema = app.state.journal.db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    response = client.get(url)
    assert response.status_code == 200, response.text
    expected = expected_receipt(intent, projection, app.state.publication_profiles["graph"]["connection"])
    binding = response.json()
    assert binding["effectId"] == expected["effect_id"] == expected["transport"]["effect_id"]
    assert binding["target"] == expected["target_profile"]
    assert binding["versionRef"]["payload_sha256"] == expected["payload_sha256"]
    for key in ("database", "scope_id", "projection_digest", "canonical_identity"):
        assert binding["versionRef"][key] == expected["transport"][key]
    assert response.json() == {
        "storeId": "primary",
        "effectId": intent["effect_id"],
        "registryId": registry.registry_id,
        "target": payload["publication_target"],
        "versionRef": {
            "reservation_id": reservation["reservation_id"],
            "revision_id": reservation["revision_id"],
            "version": reservation["version"],
            "payload_sha256": intent["payload_sha256"],
            "projection_digest": projection["digest"],
            "scope_id": projection["scope_id"],
            "database": "neo4j",
            "canonical_identity": projection["canonical_identity"],
        },
    }
    assert app.state.journal.db.total_changes == before
    assert app.state.journal.db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == schema
    for private in ("private.invalid", "operator", "private-graph-password", '"uri"', '"password"', '"user"'):
        assert private not in response.text
    assert client.delete("/api/session", headers=headers).status_code == 200
    assert client.get(url).status_code == 401
    login(client)


@pytest.mark.parametrize("change", ["removed", "endpoint", "database", "scope", "password", "secret"])
def test_publication_binding_frozen_profile_and_secret_guards(preparation, change):
    app, client, headers, payload = preparation
    commit = client.post("/api/research/stores/primary/versions", headers=headers, json=payload).json()
    url = f"/api/research/stores/primary/versions/{commit['reservation']['reservation_id']}/publication-binding"
    original = client.get(url).json()
    profile = app.state.publication_profiles["graph"]
    if change == "removed":
        app.state.publication_profiles = {}
    elif change == "endpoint":
        profile["connection"]["uri"] = "bolt://rotated.invalid:7687"
    elif change == "database":
        profile["connection"]["database"] = "other"
    elif change == "scope":
        profile["immutable_scope"] = False
    elif change == "secret":
        app.state.publication_profiles["unrelated"] = {
            "connection": {"password": original["versionRef"]["canonical_identity"]["name"]}
        }
    else:
        profile["connection"]["password"] = "rotated-password"
    before = app.state.journal.db.total_changes
    response = client.get(url)
    assert response.status_code == (200 if change == "password" else 422 if change == "secret" else 409)
    if change == "password":
        assert response.json() == original
    elif change != "secret":
        assert response.json() == {"detail": "Research publication binding unavailable"}
    else:
        assert original["versionRef"]["canonical_identity"]["name"] not in response.text
    assert app.state.journal.db.total_changes == before
    app.state.publication_profiles = publication_profiles()


@pytest.mark.parametrize(
    "change", ["unprepared", "foreign", "missing", "projection", "source", "intent_hash", "intent_profile", "effect"]
)
def test_publication_binding_rejects_unverified_or_wrong_identity(preparation, monkeypatch, change):
    app, client, headers, payload = preparation
    if change == "unprepared":
        payload["publication_target"] = None
    commit = client.post("/api/research/stores/primary/versions", headers=headers, json=payload).json()
    resid = commit["reservation"]["reservation_id"]
    selected = "primary"
    if change == "foreign":
        root = app.state.research_roots["primary"].parent / "other"
        with ResearchStore.create(
            app.state.journal, root, "other", protect_public=app.state.model_settings.protect_public
        ):
            pass
        app.state.research_roots["other"] = root
        selected = "other"
    elif change == "missing":
        resid = "f" * 32
    elif change in {"projection", "source"}:
        name = "projection.json" if change == "projection" else "environment.yaml"
        path = app.state.research_roots["primary"] / commit["relative_directory"] / name
        path.write_bytes(path.read_bytes() + b" ")
    elif change in {"intent_hash", "intent_profile", "effect"}:
        original = ResearchRegistry.get_publication_intent

        def corrupt(self, effect):
            intent = original(self, effect)
            if change == "intent_hash":
                intent["payload_sha256"] = "0" * 64
            elif change == "intent_profile":
                intent["target_profile"]["revision"] = "0" * 64
            else:
                intent["effect_id"] = "wrong"
            return intent

        monkeypatch.setattr(ResearchRegistry, "get_publication_intent", corrupt)
    before = app.state.journal.db.total_changes
    response = client.get(f"/api/research/stores/{selected}/versions/{resid}/publication-binding")
    assert response.status_code == (404 if change == "unprepared" else 409), response.text
    assert app.state.journal.db.total_changes == before


@pytest.mark.parametrize("mode", ["object", "deep", "cycle", "idempotent", "json"])
def test_candidate_reference_rejects_first_callback_mutation(preparation, monkeypatch, mode):
    app, client, _, payload = preparation
    url = f"/api/research/stores/primary/candidates/{payload['source_job_id']}"
    original = client.get(url).json()
    before = app.state.journal.db.total_changes
    durable = list(app.state.journal.db.iterdump())
    guard = app.state.model_settings.protect_public
    changed = []

    def mutate(value):
        guard(value)
        if isinstance(value, dict) and "receipt_sha256" in value and "generation" in value:
            mutate_public_metadata(value, mode)
            changed.append(True)

    with monkeypatch.context() as patch:
        patch.setattr(app.state.model_settings, "protect_public", mutate)
        response = client.get(url)
    assert changed == [True]
    assert response.status_code == 409
    assert response.json() == {"detail": "Managed candidate unavailable"}
    assert "private-callback-marker" not in response.text
    assert client.get(url).json() == original
    assert app.state.journal.db.total_changes == before
    assert list(app.state.journal.db.iterdump()) == durable


@pytest.mark.parametrize("mode", ["object", "deep", "cycle", "idempotent", "json"])
@pytest.mark.parametrize(
    "boundary",
    ["request", "receipt", "approval", "publication-request", "projection", "intent", "projection-publication-request"],
)
@pytest.mark.parametrize("replay", [False, True])
def test_store_callback_corruption_maps_to_static_conflict(preparation, monkeypatch, mode, boundary, replay):
    app, client, headers, payload = preparation
    base = "/api/research/stores/primary/versions"
    response = client.post(base, headers=headers, json=payload)
    assert response.status_code == 201
    original = response.json()
    resid = original["reservation"]["reservation_id"]
    journal = app.state.journal
    registry = ResearchRegistry(journal)
    intent = registry.get_publication_intent(original["publication_intent_id"])
    reference_url = f"/api/research/stores/primary/candidates/{payload['source_job_id']}"
    reference = client.get(reference_url).json()
    root = app.state.research_roots["primary"]
    files = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    durable = list(journal.db.iterdump())
    schema = journal.db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    guard = app.state.model_settings.protect_public
    seen, changed = {}, []

    def mutate(value):
        guard(value)
        target = public_callback_target(value, boundary, seen)
        if target is not None:
            mutate_public_metadata(target, mode)
            changed.append(True)

    with monkeypatch.context() as patch:
        patch.setattr(app.state.model_settings, "protect_public", mutate)
        patch.setattr(ArtifactArea, "stage", lambda *a, **k: pytest.fail("Corrupt artifact staged"))
        patch.setattr(ResearchRegistry, "record_commit", lambda *a, **k: pytest.fail("Corrupt commit written"))
        blocked = payload if replay else {**payload, "idempotency_key": "blocked"}
        response = client.post(base, headers=headers, json=blocked)
    assert changed == [True]
    assert response.status_code == 409
    assert response.json() == {
        "detail": "Research persistence unavailable or conflicting; retain the request for recovery"
    }
    for private in ("private-callback-marker", "private.invalid", "private-graph-password", str(root)):
        assert private not in response.text
    assert registry.get_commit(resid) == original
    assert registry.get_publication_intent(original["publication_intent_id"]) == intent
    assert client.get(reference_url).json() == reference
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == files
    assert journal.db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == schema
    if replay or boundary in {"request", "receipt", "approval", "publication-request"}:
        assert list(journal.db.iterdump()) == durable
    else:
        reservation = registry.get_reservation_for_workflow("primary", "blocked")
        assert reservation is not None
        assert registry.get_commit(reservation["reservation_id"]) is None
        assert registry.get_publication_intent(reservation["publication_request"]["effect_id"]) is None
    assert client.post(base, headers=headers, json=payload).json() == original


@pytest.mark.parametrize(
    "boundary", ["candidate", "request", "receipt", "approval", "publication-request", "projection", "intent"]
)
def test_store_callback_secret_rejection_remains_static_422(preparation, monkeypatch, boundary):
    app, client, headers, payload = preparation
    base = "/api/research/stores/primary/versions"
    original = client.post(base, headers=headers, json=payload).json()
    url = f"/api/research/stores/primary/candidates/{payload['source_job_id']}"
    reference = client.get(url).json()
    durable = list(app.state.journal.db.iterdump())
    guard = app.state.model_settings.protect_public
    seen, rejected = {}, []

    def protect(value):
        target = value if boundary == "candidate" else public_callback_target(value, boundary, seen)
        if target is not None:
            target["private-callback-marker"] = "private-graph-password"
            rejected.append(True)
        guard(value)

    with monkeypatch.context() as patch:
        patch.setattr(app.state.model_settings, "protect_public", protect)
        response = client.get(url) if boundary == "candidate" else client.post(base, headers=headers, json=payload)
    assert rejected == [True]
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request input"}
    assert "private-graph-password" not in response.text
    assert client.get(url).json() == reference
    assert list(app.state.journal.db.iterdump()) == durable
    assert client.post(base, headers=headers, json=payload).json() == original


@pytest.mark.parametrize("field", ["effectId", "target", "versionRef"])
def test_binding_rejects_public_callback_mutation(preparation, monkeypatch, field):
    app, client, headers, payload = preparation
    base = "/api/research/stores/primary/versions"
    commit = client.post(base, headers=headers, json=payload).json()
    url = f"{base}/{commit['reservation']['reservation_id']}/publication-binding"
    original = client.get(url).json()
    guard = app.state.model_settings.protect_public

    def mutate(value):
        guard(value)
        if isinstance(value, dict) and "versionRef" in value:
            if field == "effectId":
                value[field] = "retargeted"
            elif field == "target":
                value[field]["profile_id"] = "retargeted"
            else:
                value[field]["version"] = 999

    with monkeypatch.context() as patch:
        patch.setattr(app.state.model_settings, "protect_public", mutate)
        response = client.get(url)
    assert response.status_code == 409
    assert response.json() == {"detail": "Research public metadata changed"}
    assert client.get(url).json() == original


@pytest.mark.parametrize("endpoint", ["save", "commit", "listing", "profiles", "stores", "identity"])
def test_sibling_public_callback_mutation_preserves_original(preparation, monkeypatch, endpoint):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import research_routes

    app, client, headers, payload = preparation
    base = "/api/research/stores/primary/versions"
    registry = ResearchRegistry(app.state.journal)
    original = None if endpoint in {"save", "identity"} else client.post(base, headers=headers, json=payload).json()
    guard = app.state.model_settings.protect_public
    changed = []

    def mutate(value):
        guard(value)
        if not isinstance(value, dict):
            return
        if endpoint == "identity" and value.get("purpose") == "save_publication_intent":
            value["workflow_id"] = "retargeted"
        elif endpoint in {"save", "commit"} and "manifest" in value and "reservation" in value:
            value["reservation"]["version"] = 999
        elif endpoint == "listing" and "versions" in value:
            value["versions"][0]["version"] = 999
        elif endpoint == "profiles" and "profiles" in value:
            value["profiles"][0]["profile_id"] = "retargeted"
        elif endpoint == "stores" and "stores" in value:
            value["stores"][0]["store_id"] = "retargeted"
        else:
            return
        changed.append(True)

    with monkeypatch.context() as patch:
        patch.setattr(app.state.model_settings, "protect_public", mutate)
        if endpoint in {"save", "identity"}:
            if endpoint == "identity":
                patch.setattr(research_routes, "digest", lambda *a: pytest.fail("Mutated identity hashed"))
            response = client.post(base, headers=headers, json=payload)
        else:
            assert original is not None
            url = {
                "commit": f"{base}/{original['reservation']['reservation_id']}",
                "listing": base + "?family=a2",
                "profiles": "/api/research/publication-profiles",
                "stores": "/api/research/stores",
            }[endpoint]
            response = client.get(url)
    assert changed
    assert response.status_code == 409
    assert response.json() == {"detail": "Research public metadata changed"}
    if endpoint == "identity":
        assert registry.get_reservation_for_workflow("primary", payload["idempotency_key"]) is None
    else:
        reservation = registry.get_reservation_for_workflow("primary", payload["idempotency_key"])
        assert reservation is not None
        durable = registry.get_commit(reservation["reservation_id"])
        assert durable is not None
        assert durable["reservation"]["version"] == 1
        if original is not None:
            assert durable == original
        replay = client.post(base, headers=headers, json=payload)
        assert replay.status_code == 201
        assert replay.json() == durable


def test_binding_rejects_substitution_of_another_prepared_version(preparation, monkeypatch):
    app, client, headers, payload = preparation
    base = "/api/research/stores/primary/versions"
    first = client.post(base, headers=headers, json=payload).json()
    second = client.post(base, headers=headers, json={**payload, "idempotency_key": "second"}).json()
    first_id = first["reservation"]["reservation_id"]
    second_id = second["reservation"]["reservation_id"]
    assert first_id != second_id
    originals = [client.get(f"{base}/{resid}/publication-binding").json() for resid in (first_id, second_id)]
    assert originals[0]["effectId"] != originals[1]["effectId"]
    get_commit = ResearchRegistry.get_commit

    def substitute(self, resid):
        return get_commit(self, second_id if resid == first_id else resid)

    with monkeypatch.context() as patch:
        patch.setattr(ResearchRegistry, "get_commit", substitute)
        response = client.get(f"{base}/{first_id}/publication-binding")
    assert response.status_code == 409
    assert response.json() == {"detail": "Research publication binding unavailable"}
    for resid, original in zip((first_id, second_id), originals):
        assert client.get(f"{base}/{resid}/publication-binding").json() == original


@pytest.mark.parametrize("mode", ["noop", "reorder", "secret"])
def test_public_guard_allows_unchanged_metadata_and_preserves_secret_422(preparation, monkeypatch, mode):
    app, client, headers, payload = preparation
    base = "/api/research/stores/primary/versions"
    commit = client.post(base, headers=headers, json=payload).json()
    url = f"{base}/{commit['reservation']['reservation_id']}/publication-binding"
    expected = client.get(url).json()
    guard = app.state.model_settings.protect_public

    def unchanged(value):
        if mode != "noop":
            guard(value)
        if mode == "reorder" and isinstance(value, dict):
            reordered = dict(reversed(list(value.items())))
            value.clear()
            value.update(reordered)

    with monkeypatch.context() as patch:
        patch.setattr(app.state.model_settings, "protect_public", unchanged)
        if mode == "secret":
            app.state.publication_profiles["unrelated"] = {"connection": {"password": expected["effectId"]}}
        response = client.get(url)
    app.state.publication_profiles.pop("unrelated", None)
    assert response.status_code == (422 if mode == "secret" else 200)
    assert response.json() == ({"detail": "Invalid request input"} if mode == "secret" else expected)


def test_binding_guard_permits_expired_grant_revocation_only(preparation, monkeypatch):
    app, client, headers, payload = preparation
    base = "/api/research/stores/primary/versions"
    commit = client.post(base, headers=headers, json=payload).json()
    url = f"{base}/{commit['reservation']['reservation_id']}/publication-binding"
    expected = client.get(url).json()
    auth = app.state.publication_authorization
    intent = ResearchRegistry(app.state.journal).get_publication_intent(commit["publication_intent_id"])
    session = app.state.sessions.get(client.cookies.get(app.state.cookie_name))
    # Explicit test setup only; the fixture forbids issue/dispatch/graph IO during GET.
    grant = type(auth).issue(auth, session, intent, "expire", "graph_read")
    monkeypatch.setattr(auth, "clock", lambda: grant["expires_at"] + 1)
    revoked = []
    revoke = auth.revoke

    def record_revocation(grant_id):
        revoked.append(grant_id)
        revoke(grant_id)

    monkeypatch.setattr(auth, "revoke", record_revocation)
    monkeypatch.setattr(auth, "resolve", lambda *a, **k: pytest.fail("GET resolved execution authority"))
    monkeypatch.setattr(auth, "bind_attempt", lambda *a, **k: pytest.fail("GET bound worker authority"))
    before = app.state.journal.db.total_changes
    assert grant["grant_id"] in auth._records
    response = client.get(url)
    assert response.status_code == 200
    assert response.json() == expected
    assert revoked == [grant["grant_id"]]
    assert not auth._records
    assert app.state.journal.db.total_changes == before


def test_save_prepares_exact_projection_and_pending_intent(preparation):
    app, client, headers, payload = preparation
    url = "/api/research/stores/primary/versions"
    response = client.post(url, headers=headers, json=payload)
    assert response.status_code == 201, response.text
    commit = response.json()
    effect = commit["publication_intent_id"]
    assert effect and response.headers["x-publication-preparation"] == "prepared-not-published"
    with ResearchStore.open(
        app.state.journal,
        app.state.research_roots["primary"],
        "primary",
        protect_public=app.state.model_settings.protect_public,
    ) as store:
        intent = store.registry.get_publication_intent(effect)
        files = store.read_version(commit["reservation"]["reservation_id"])
        assert intent["state"] == "pending"
        assert intent["target_profile"] == payload["publication_target"]
        assert intent["payload"]["artifact_sha256"] == hashlib.sha256(files["projection.json"]).hexdigest()
        assert json.loads(files["projection.json"])["digest"] == intent["payload"]["projection_digest"]
        assert store.registry.get_commit(commit["reservation"]["reservation_id"]) == commit
    assert client.get(url + "/" + commit["reservation"]["reservation_id"]).json() == commit
    assert client.post(url, headers=headers, json=payload).json() == commit


@pytest.mark.parametrize("state", ["reserved", "committed"])
@pytest.mark.parametrize("profile_id", ["graph", "unrelated"])
@pytest.mark.parametrize(
    "malformed",
    [
        None,
        {"connection": {"password": "private-graph-password"}},
        {"connection": {"uri": "bad-uri", "password": "private-graph-password"}},
    ],
)
def test_accepted_save_replay_ignores_malformed_connections(preparation, monkeypatch, state, profile_id, malformed):
    app, client, headers, payload = preparation
    url = "/api/research/stores/primary/versions"
    if state == "reserved":
        with monkeypatch.context() as crash:

            def interrupted(*a, **k):
                raise OSError("offline interrupted staging")

            crash.setattr(ArtifactArea, "stage", interrupted)
            assert client.post(url, headers=headers, json=payload).status_code == 409
        rows = ResearchRegistry(app.state.journal).list_versions("primary", "a2")
        assert len(rows) == 1 and rows[0]["state"] == "reserved"
        original = None
    else:
        response = client.post(url, headers=headers, json=payload)
        assert response.status_code == 201
        original = response.json()
    app.state.publication_profiles[profile_id] = malformed
    response = client.post(url, headers=headers, json=payload)
    assert response.status_code == 201, response.text
    if original is not None:
        assert response.json() == original
    assert client.post(url, headers=headers, json=payload).json() == response.json()
    assert "private-graph-password" not in response.text
    assert len(ResearchRegistry(app.state.journal).list_versions("primary", "a2")) == 1


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        {},
        {"connection": {"password": "private-graph-password"}},
        {"connection": {"uri": "bad-uri", "password": "private-graph-password"}},
    ],
)
def test_profile_listing_skips_malformed_connections_without_whole_failure(preparation, malformed):
    app, client, _, _ = preparation
    expected = app.state.publication_authorization.profile_metadata("graph")
    app.state.publication_profiles["unrelated"] = malformed
    before = app.state.journal.db.total_changes
    response = client.get("/api/research/publication-profiles")
    assert response.status_code == 200, response.text
    assert response.json() == {"profiles": [{**expected, "available": True}]}
    assert app.state.journal.db.total_changes == before
    assert "private-graph-password" not in response.text


@pytest.mark.parametrize("profile_id", ["graph", "unrelated"])
@pytest.mark.parametrize(
    "connection", [{"password": "private-graph-password"}, {"uri": "bad-uri", "password": "private-graph-password"}]
)
def test_malformed_profile_known_password_never_reflected_or_persisted(preparation, profile_id, connection):
    app, client, headers, payload = preparation
    app.state.publication_profiles[profile_id] = {"connection": connection}
    response = client.post(
        "/api/research/stores/primary/versions",
        headers=headers,
        json={**payload, "idempotency_key": "private-graph-password"},
    )
    assert response.status_code == 422
    assert "private-graph-password" not in response.text
    assert ResearchRegistry(app.state.journal).list_versions("primary", "a2") == []
    assert "private-graph-password" not in "\n".join(app.state.journal.db.iterdump())
    assert not list(app.state.research_roots["primary"].rglob("projection.json"))


def test_prepared_replay_ignores_removed_configuration_and_new_session(preparation):
    app, client, headers, payload = preparation
    url = "/api/research/stores/primary/versions"
    original = client.post(url, headers=headers, json=payload).json()
    app.state.publication_profiles["graph"]["connection"]["password"] = "rotated-private-password"
    assert app.state.publication_authorization.profile_metadata("graph") == payload["publication_target"]
    app.state.publication_profiles["graph"]["connection"]["uri"] = "bolt://changed.invalid:7687"
    assert client.post(url, headers=headers, json=payload).json() == original
    app.state.publication_profiles = {}
    assert client.delete("/api/session", headers=headers).status_code == 200
    headers = login(client)
    replay = client.post(url, headers=headers, json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json() == original
    assert client.post(url, headers=headers, json={**payload, "family": "changed"}).status_code == 409
    assert client.post(url, headers=headers, json={**payload, "publication_target": None}).status_code == 409
    changed = {**payload["publication_target"], "revision": "0" * 64}
    assert client.post(url, headers=headers, json={**payload, "publication_target": changed}).status_code == 409
    assert client.get(url, params={"family": "a2"}).json()["latest_version"] == 1


@pytest.mark.parametrize("change", ["removed", "revision", "scope", "secret"])
def test_preparation_rejects_unavailable_or_changed_target_before_reservation(preparation, change):
    app, client, headers, payload = preparation
    if change == "removed":
        app.state.publication_profiles = {}
    elif change == "revision":
        app.state.publication_profiles["graph"]["connection"]["uri"] = "bolt://different.invalid:7687"
    elif change == "scope":
        app.state.publication_profiles["graph"]["immutable_scope"] = False
    else:
        payload["idempotency_key"] = "private-graph-password"
    response = client.post("/api/research/stores/primary/versions", headers=headers, json=payload)
    assert response.status_code == (422 if change == "secret" else 409)
    registry = ResearchRegistry(app.state.journal)
    assert registry.list_versions("primary", "a2") == []
    assert not list((app.state.research_roots["primary"] / "final").rglob("projection.json"))
    assert "private-graph-password" not in response.text


@pytest.mark.parametrize(
    "target",
    [
        "graph",
        {},
        {"profile_id": "graph"},
        {
            "profile_id": "graph",
            "revision": "a" * 64,
            "scope_ownership": "cooperative_immutable",
            "uri": "bolt://evil",
        },
        {
            "profile_id": "graph",
            "revision": "a" * 64,
            "scope_ownership": "cooperative_immutable",
            "password": "x",
        },
        {
            "profile_id": "graph",
            "revision": "a" * 64,
            "scope_ownership": "cooperative_immutable",
            "command": [],
        },
        {
            "profile_id": "graph",
            "revision": "A" * 64,
            "scope_ownership": "cooperative_immutable",
        },
    ],
)
def test_preparation_strict_target_rejects_private_or_partial_input(preparation, target):
    app, client, headers, payload = preparation
    response = client.post(
        "/api/research/stores/primary/versions",
        headers=headers,
        json={**payload, "publication_target": target},
    )
    assert response.status_code == 422
    assert ResearchRegistry(app.state.journal).list_versions("primary", "a2") == []


def test_preparation_commit_and_outbox_rollback_together_then_recover(preparation, monkeypatch):
    app, client, headers, payload = preparation
    url = "/api/research/stores/primary/versions"
    original = ResearchRegistry._insert_publication_intent

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise ValueError("injected rollback")

    monkeypatch.setattr(ResearchRegistry, "_insert_publication_intent", fail)
    assert client.post(url, headers=headers, json=payload).status_code == 409
    registry = ResearchRegistry(app.state.journal)
    reservation = registry.get_reservation_for_workflow("primary", "prepare")
    assert registry.get_commit(reservation["reservation_id"]) is None
    assert registry.get_publication_intent(reservation["publication_request"]["effect_id"]) is None
    assert registry.latest_version("primary", "a2") is None
    assert list((app.state.research_roots["primary"] / "final").rglob("projection.json"))
    monkeypatch.setattr(ResearchRegistry, "_insert_publication_intent", original)
    app.state.publication_profiles = {}
    response = client.post(url, headers=headers, json=payload)
    assert response.status_code == 201
    assert response.json()["reservation"] == reservation
    assert registry.get_publication_intent(response.json()["publication_intent_id"])["state"] == "pending"


@pytest.mark.parametrize("guard", ["schema", "foreign", "busy"])
def test_preparation_preserves_schema_store_and_busy_guards(preparation, guard):
    from contextlib import nullcontext

    app, client, headers, payload = preparation
    root = app.state.research_roots["primary"]
    with ResearchStore.open(
        app.state.journal,
        root,
        "primary",
        protect_public=app.state.model_settings.protect_public,
    ) as store:
        context = store.area.writer_lock() if guard == "busy" else nullcontext()
        if guard == "schema":
            app.state.journal.db.execute("UPDATE research_registry_meta SET schema_version=999")
        elif guard == "foreign":
            store.registry.register_store("other")
            app.state.research_roots["other"] = root
        with context:
            selected = "other" if guard == "foreign" else "primary"
            response = client.post(
                f"/api/research/stores/{selected}/versions",
                headers=headers,
                json=payload,
            )
            assert response.status_code == (503 if guard == "busy" else 409)
            if guard == "busy":
                assert response.headers["retry-after"] == "1"
        if guard == "schema":
            app.state.journal.db.execute("UPDATE research_registry_meta SET schema_version=1")
        assert store.registry.get_reservation_for_workflow("primary", "prepare") is None
        assert store.registry.list_versions("primary", "a2") == []


def test_workflow_lookup_is_detached_store_scoped_and_read_only(preparation):
    app, client, headers, payload = preparation
    saved = client.post("/api/research/stores/primary/versions", headers=headers, json=payload).json()
    registry = ResearchRegistry(app.state.journal)
    registry.register_store("other")
    before = app.state.journal.db.total_changes
    assert registry.get_reservation_for_workflow("other", "prepare") is None
    copy = registry.get_reservation_for_workflow("primary", "prepare")
    assert copy == saved["reservation"]
    copy["family"] = "changed"
    assert registry.get_reservation_for_workflow("primary", "prepare") == saved["reservation"]
    for store_id, workflow in [("unknown", "prepare"), ("primary", "../bad")]:
        with pytest.raises(ValueError):
            registry.get_reservation_for_workflow(store_id, workflow)
    assert app.state.journal.db.total_changes == before


def test_no_retroactive_preparation_for_unprepared_version(preparation):
    app, client, headers, payload = preparation
    url = "/api/research/stores/primary/versions"
    plain = {**payload, "publication_target": None}
    commit = client.post(url, headers=headers, json=plain).json()
    assert commit["publication_intent_id"] is None
    assert client.post(url, headers=headers, json=payload).status_code == 409
    assert client.post(url, headers=headers, json=plain).json() == commit


def test_no_managed_profile_is_read_only_and_never_initializes_registry(tmp_path):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/research/stores").status_code == 401
        login(client)
        assert client.get("/api/editor").json()["capabilities"]["research_versions"] is False
        response = client.get("/api/research/stores")
        assert response.status_code == 200
        assert response.json() == {"stores": []}
        assert (
            app.state.journal.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_registry_meta'"
            ).fetchone()
            is None
        )
        assert client.get("/api/jobs").json()["jobs"] == []


def test_explicit_save_persists_exact_candidate_and_recovers_same_version(tmp_path):
    root = tmp_path / "managed"
    app = create_app(tmp_path / "state", start_paused=True, research_roots={"primary": root})
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        assert client.get("/api/editor").json()["capabilities"]["research_versions"] is True
        assert not root.exists()
        source, receipt = candidate(app.state.journal)
        with ResearchStore.create(
            app.state.journal,
            root,
            "primary",
            protect_public=app.state.model_settings.protect_public,
        ):
            pass
        payload = {
            "idempotency_key": "save-once",
            "family": "a2",
            "source_job_id": source["job_id"],
            "source_attempt_id": source["attempt_id"],
            "source_generation": source["generation"],
        }
        url = "/api/research/stores/primary/versions"
        response = client.post(url, headers=headers, json=payload)
        assert response.status_code == 201, response.text
        version = response.json()
        assert version["reservation"]["version"] == 1
        assert version["reservation"]["approval"]["principal"] == "single_operator_workspace"
        assert version["publication_intent_id"] is None
        resid = version["reservation"]["reservation_id"]
        assert client.get(f"{url}/{resid}").json() == version
        listing = client.get(url, params={"family": "a2"}).json()
        assert listing["latest_version"] == 1 and listing["next_after_version"] is None
        assert listing["versions"][0]["reservation_id"] == resid
        download = client.get(f"{url}/{resid}/artifacts/environment.yaml")
        assert download.status_code == 200 and download.text == receipt["yaml_text"]
        assert download.headers["content-disposition"].startswith("attachment;")
        reference = client.get(f'/api/research/stores/primary/candidates/{source["job_id"]}').json()
        assert reference["attempt_id"] == source["attempt_id"] and reference["generation"] == source["generation"]
        assert client.post(url, headers=headers, json=payload).json() == version
        assert client.delete("/api/session", headers=headers).status_code == 200
        headers = login(client)
        assert client.post(url, headers=headers, json=payload).json() == version
        assert (
            app.state.journal.get_candidate_receipt(source["job_id"], source["attempt_id"], source["generation"])
            == receipt
        )
        assert client.post(url, headers=headers, json={**payload, "family": "different"}).status_code == 409


def test_uninitialized_configured_profile_is_unavailable_without_creation(tmp_path):
    root = tmp_path / "private-uninitialized-store"
    app = create_app(tmp_path / "state", start_paused=True, research_roots={"primary": root})
    with TestClient(app, base_url=ORIGIN) as client:
        login(client)
        response = client.get("/api/research/stores")
        assert response.status_code == 200
        assert response.json()["stores"] == [{
            "store_id": "primary",
            "available": False,
            "message": "Managed store unavailable",
        }]
        assert str(root) not in response.text
        assert not root.exists()


@pytest.mark.parametrize(
    "path",
    [
        "/api/research/stores/primary/versions?family=a2",
        "/api/research/stores/primary/versions/" + "a" * 32,
        "/api/research/stores/primary/versions/" + "a" * 32 + "/publication-binding",
        "/api/research/stores/primary/versions/" + "a" * 32 + "/artifacts/environment.yaml",
        "/api/research/stores/primary/candidates/" + "a" * 32,
    ],
)
def test_research_reads_require_an_active_session(tmp_path, monkeypatch, path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import research_routes

    monkeypatch.setattr(research_routes, "selected_store", lambda *a: pytest.fail("Unauthenticated store lookup"))
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        assert client.get(path).status_code == 401


def test_persistence_requires_csrf_and_never_initializes_unknown_store(tmp_path):
    app = create_app(tmp_path, start_paused=True)
    payload = {
        "idempotency_key": "save",
        "family": "a2",
        "source_job_id": "a" * 32,
        "source_attempt_id": "b" * 32,
        "source_generation": 1,
    }
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        url = "/api/research/stores/unknown/versions"
        assert client.post(url, json=payload, headers={"Origin": ORIGIN}).status_code == 403
        assert client.post(url, json=payload, headers=headers).status_code == 404
        assert (
            app.state.journal.db.execute("SELECT 1 FROM sqlite_master WHERE name='research_registry_meta'").fetchone()
            is None
        )


def test_cooperating_writer_contention_is_retryable_not_internal_error(tmp_path):
    root = tmp_path / "managed"
    app = create_app(tmp_path / "state", start_paused=True, research_roots={"primary": root})
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        headers = login(client)
        source, _ = candidate(app.state.journal)
        with ResearchStore.create(
            app.state.journal,
            root,
            "primary",
            protect_public=app.state.model_settings.protect_public,
        ) as owner:
            with owner.area.writer_lock():
                listing = client.get("/api/research/stores")
                assert listing.status_code == 200
                assert listing.json()["stores"][0]["message"] == "Managed store busy; retry later"
                response = client.post(
                    "/api/research/stores/primary/versions",
                    headers=headers,
                    json={
                        "idempotency_key": "save",
                        "family": "a2",
                        "source_job_id": source["job_id"],
                        "source_attempt_id": source["attempt_id"],
                        "source_generation": source["generation"],
                    },
                )
                assert response.status_code == 503
                assert response.headers["retry-after"] == "1"
                assert client.get("/api/research/stores/primary/versions?family=a2").status_code == 503
        assert client.get("/api/research/stores").json()["stores"][0]["available"]


def test_profile_read_verifies_the_actual_area_and_registry_binding(tmp_path):
    root = tmp_path / "managed-area"
    app = create_app(tmp_path / "state", start_paused=True, research_roots={"primary": root})
    with TestClient(app, base_url=ORIGIN) as client:
        login(client)
        registry = ResearchRegistry(app.state.journal, initialize=True)
        registry.register_store("primary")
        with ArtifactArea.create(root, store_id="primary", registry_id=registry.registry_id):
            pass
        response = client.get("/api/research/stores")
        assert response.json() == {
            "stores": [{
                "store_id": "primary",
                "available": True,
                "message": "Managed store ready",
            }]
        }
        assert str(root) not in response.text
        assert client.get("/api/jobs").json()["jobs"] == []
