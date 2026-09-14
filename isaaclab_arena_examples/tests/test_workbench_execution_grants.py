# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Memory-only operation grants, using static fake secrets and an injected clock."""

import json

import pytest

SECRET = "dummy-execution-secret-123456"
PROFILE = {
    "model": "test-model",
    "endpoint": "https://example.invalid",
    "principal": "test-user",
    "credential_generation": "gen-1",
}


def store(**kwargs):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants

    return ExecutionGrants(clock=lambda: 100, **kwargs)


def issue(grants, **kwargs):
    args = dict(
        owner_id="owner",
        operation_id="operation",
        capability="model",
        profile=PROFILE,
        credentials={"api_key": SECRET, "options": {"values": [1]}},
        expires_at=200,
    )
    return grants.issue(**(args | kwargs))


@pytest.mark.parametrize(
    "owner, operation, capability",
    [
        ("foreign", "operation", "model"),
        ("owner", "foreign", "model"),
        ("owner", "operation", "retrieval_read"),
        ("owner", "operation", "unknown"),
    ],
)
def test_exact_binding_never_falls_back(owner, operation, capability):
    grants = store()
    public = issue(grants)
    with pytest.raises(ValueError, match="Execution grant unavailable"):
        grants.resolve(owner, public["grant_id"], operation, capability)
    with pytest.raises(ValueError, match="Execution grant unavailable"):
        grants.resolve("owner", "unknown", "operation", "model")


@pytest.mark.parametrize("capability", ["model", "retrieval_read", "publication_write", "reconciliation_read"])
def test_supported_capabilities(capability):
    grants = store()
    public = issue(grants, capability=capability)
    assert grants.resolve("owner", public["grant_id"], "operation", capability)


@pytest.mark.parametrize(
    "changes",
    [
        {"expires_at": float("nan")},
        {"expires_at": float("inf")},
        {"expires_at": -float("inf")},
        {"expires_at": True},
        {"expires_at": 100},
        {"expires_at": 7301},
        {"capability": "unknown"},
        {"capability": []},
        {"owner_id": ""},
        {"operation_id": "x" * 257},
        {"profile": {"bad": object()}},
        {"profile": {1: "bad"}},
        {"credentials": {"key": float("nan")}},
        {"credentials": {"key": "x" * 65537}},
        {"profile": {"many": [0] * 4097}},
    ],
)
def test_reject_invalid_or_unbounded_input(changes):
    with pytest.raises(ValueError):
        issue(store(), **changes)


def test_capacity_is_finite_and_expired_entries_free_space():
    grants = store(capacity=1)
    public = issue(grants)
    with pytest.raises(ValueError, match="capacity"):
        issue(grants)
    assert grants.resolve("owner", public["grant_id"], "operation", "model")
    grants.clock = lambda: 200
    issue(grants, expires_at=201)
    for capacity in (0, -1, True, 1.5, 129):
        with pytest.raises(ValueError):
            store(capacity=capacity)


def test_json_depth_and_cycles_are_rejected():
    deep = {}
    for _ in range(18):
        deep = {"nested": deep}
    cycle = []
    cycle.append(cycle)
    for value in (deep, {"cyclic": cycle}):
        with pytest.raises(ValueError):
            issue(store(), credentials=value)


@pytest.mark.parametrize("value", [SECRET, {"nested": [{"prefix-" + SECRET: "ok"}]}, {"nested": ["prefix/" + SECRET]}])
def test_protect_public_scans_values_and_nested_keys(value):
    grants = store()
    issue(grants)
    with pytest.raises(ValueError) as error:
        grants.protect_public(value)
    assert SECRET not in str(error.value)
    assert grants.protect_public({"safe": ["public"]}) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"profile": {"nested": [{SECRET: "hidden"}]}},
        {"profile": {"model": SECRET}},
        {"profile": {"nested": {"api_key": "not-a-known-secret"}}},
        {"owner_id": SECRET},
        {"operation_id": SECRET},
    ],
)
def test_issue_rejects_secret_material_in_all_public_metadata(changes):
    with pytest.raises(ValueError) as error:
        issue(store(), **changes)
    assert SECRET not in str(error.value)


def test_nested_private_credentials_and_previous_grants_protect_public():
    grants = store()
    issue(grants, credentials={"auth": {"token": SECRET}, "model": "test-model"})
    with pytest.raises(ValueError):
        issue(grants, credentials={"api_key": "second-dummy-secret"}, profile={"principal": SECRET})
    with pytest.raises(ValueError):
        grants.protect_public({SECRET: "safe"})
    deep = {}
    for _ in range(18):
        deep = {"nested": deep}
    with pytest.raises(ValueError):
        grants.protect_public(deep)


def test_bad_clock_fails_closed_on_resolve():
    grants = store()
    public = issue(grants)
    grants.clock = lambda: float("nan")
    with pytest.raises(ValueError):
        grants.resolve("owner", public["grant_id"], "operation", "model")


def test_reference_collision_fails_without_replacing_existing_grant(monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import execution_grants

    grants = store()
    monkeypatch.setattr(execution_grants.secrets, "token_hex", lambda size: "a" * 64)
    public = issue(grants)
    with pytest.raises(ValueError):
        issue(grants, credentials={"api_key": "replacement-secret"})
    assert grants.resolve("owner", public["grant_id"], "operation", "model")["api_key"] == SECRET


@pytest.mark.parametrize("reference", [None, [], {}, 123])
def test_malformed_reference_fails_closed(reference):
    with pytest.raises(ValueError):
        store().resolve("owner", reference, "operation", "model")


def test_lifecycle_replacement_revocation_owner_cleanup_and_exact_expiry():
    grants = store()
    first = issue(grants)
    second = issue(grants)
    assert first["grant_id"] != second["grant_id"]
    grants.revoke(first["grant_id"])
    grants.revoke(first["grant_id"])
    with pytest.raises(ValueError):
        grants.resolve("owner", first["grant_id"], "operation", "model")
    assert grants.resolve("owner", second["grant_id"], "operation", "model")["api_key"] == SECRET
    other = issue(grants, owner_id="other")
    grants.forget_owner("owner")
    with pytest.raises(ValueError):
        grants.resolve("owner", second["grant_id"], "operation", "model")
    grants.clock = lambda: 199.999
    assert grants.resolve("other", other["grant_id"], "operation", "model")
    grants.clock = lambda: 200
    with pytest.raises(ValueError):
        grants.resolve("other", other["grant_id"], "operation", "model")
    grants.purge()
    fresh = issue(grants, expires_at=201)
    grants.clear()
    with pytest.raises(ValueError):
        grants.resolve("owner", fresh["grant_id"], "operation", "model")


def test_issue_resolve_detaches_private_config_and_public_profile():
    grants = store()
    profile = {**PROFILE, "metadata": {"labels": ["original"]}}
    credentials = {"api_key": SECRET, "options": {"values": [1]}}
    public = issue(grants, profile=profile, credentials=credentials)
    assert set(public) == {"grant_id", "owner_id", "operation_id", "capability", "profile", "expires_at"}
    assert SECRET not in json.dumps(public)
    profile["metadata"]["labels"].append("changed")
    credentials["options"]["values"].append(2)
    assert public["profile"]["metadata"]["labels"] == ["original"]
    public["profile"]["model"] = "changed"
    resolved = grants.resolve("owner", public["grant_id"], "operation", "model")
    assert resolved == {"api_key": SECRET, "options": {"values": [1]}}
    resolved["options"]["values"].append(3)
    assert grants.resolve("owner", public["grant_id"], "operation", "model")["options"]["values"] == [1]
