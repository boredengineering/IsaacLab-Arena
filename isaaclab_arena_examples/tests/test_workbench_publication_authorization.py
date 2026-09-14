# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Offline publication authority contracts; no graph or model configuration."""

import copy
import hashlib
import json

import pytest

SECRET = "dummy-graph-private-password-123456"


class Sessions:
    def __init__(self):
        self.current = {"session_id": "owner", "expires_at": 1000}

    def get_by_id(self, owner):
        return copy.deepcopy(self.current) if self.current and owner == self.current["session_id"] else None


def setup(**kwargs):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_authorization import (
        PublicationAuthorization,
    )

    sessions = Sessions()
    profiles = {
        "graph": {
            "connection": {
                "uri": "bolt://example.invalid:7687",
                "user": "operator",
                "password": SECRET,
                "database": "research",
            },
            "immutable_scope": True,
        }
    }
    now = [100]
    auth = PublicationAuthorization(sessions, lambda: profiles, clock=lambda: now[0], **kwargs)
    return auth, sessions, profiles, now


def intent(auth):
    payload = {"artifact": "descriptor", "projection_digest": "a" * 64}
    return {
        "effect_id": "effect",
        "target_profile": auth.profile_metadata("graph"),
        "payload": payload,
        "payload_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def issue(auth, sessions, capability="graph_write"):
    return auth.issue(sessions.current, intent(auth), "request", capability)


def resolve(auth, grant, **kwargs):
    return auth.resolve(
        grant,
        **(
            {
                "capability": grant["capability"],
                "effect_id": "effect",
                "request_id": "request",
                "attempt_id": "attempt",
                "generation": 1,
            }
            | kwargs
        ),
    )


def test_issue_exact_metadata_separate_capabilities_and_attempt_binding():
    auth, sessions, profiles, _ = setup()
    frozen = intent(auth)
    write = auth.issue(sessions.current, frozen, "request", "graph_write")
    read = issue(auth, sessions, "graph_read")
    assert set(write) == {
        "grant_id",
        "request_id",
        "effect_id",
        "target_profile",
        "payload_sha256",
        "capability",
        "expires_at",
    }
    assert write["grant_id"] != read["grant_id"]
    assert write["expires_at"] == 280
    assert SECRET not in json.dumps([write, read])
    with pytest.raises(ValueError):
        resolve(auth, write)
    auth.bind_attempt(write, "attempt", 1)
    auth.bind_attempt(read, "attempt", 1)
    frozen["payload"]["artifact"] = "mutation"
    private, approved = resolve(auth, write)
    assert private == profiles["graph"]["connection"]
    assert approved == write
    private["password"] = "mutation"
    approved["target_profile"]["profile_id"] = "mutation"
    assert resolve(auth, write)[0]["password"] == SECRET
    for changes in (
        {"effect_id": "other"},
        {"request_id": "other"},
        {"capability": "graph_read"},
        {"attempt_id": "other"},
        {"generation": 2},
        {"generation": True},
    ):
        with pytest.raises(ValueError):
            resolve(auth, write, **changes)
    for field, value in (
        ("target_profile", "other"),
        ("payload_sha256", "b" * 64),
        ("expires_at", 999),
        ("capability", "graph_read"),
        ("extra", "value"),
    ):
        changed = copy.deepcopy(write)
        changed[field] = value
        with pytest.raises(ValueError):
            resolve(auth, changed)
    with pytest.raises(ValueError):
        auth.bind_attempt(write, "other", 2)
    assert resolve(auth, read)[0]["password"] == SECRET
    assert (
        auth(
            write,
            capability="graph_write",
            effect_id="effect",
            request_id="request",
            attempt_id="attempt",
            generation=1,
        )[1]
        == write
    )


@pytest.mark.parametrize(
    "change",
    ["password", "uri", "user", "database", "scope", "missing", "expired", "revoked", "clear", "forget", "revoke"],
)
def test_original_authority_loss_denies_and_forgets(change):
    auth, sessions, profiles, now = setup()
    grant = issue(auth, sessions)
    auth.bind_attempt(grant, "attempt", 1)
    if change in ("password", "user", "database"):
        profiles["graph"]["connection"][change] = "replacement-private-value"
    elif change == "uri":
        profiles["graph"]["connection"]["uri"] = "bolt://other.invalid:7687"
    elif change == "scope":
        profiles["graph"]["immutable_scope"] = False
    elif change == "missing":
        profiles.clear()
    elif change == "expired":
        now[0] = 280
    elif change == "revoked":
        sessions.current = None
    elif change == "clear":
        auth.clear()
    elif change == "forget":
        auth.forget_owner("owner")
    else:
        auth.revoke(grant["grant_id"])
    with pytest.raises(ValueError, match="Publication authorization unavailable"):
        resolve(auth, grant)
    assert auth._records == {}
    if change in {"password", "missing"}:
        auth.protect_public({"forgotten": SECRET})
    else:
        # Revocation drops the grant, not the operator's still-configured password.
        with pytest.raises(ValueError):
            auth.protect_public({"forgotten": SECRET})


def test_rotation_explicit_reissue_and_independent_read():
    auth, sessions, profiles, _ = setup()
    frozen = intent(auth)
    write = issue(auth, sessions)
    read = issue(auth, sessions, "graph_read")
    auth.bind_attempt(read, "attempt", 1)
    auth.revoke(write["grant_id"])
    assert resolve(auth, read)[0]["password"] == SECRET
    from isaaclab_arena_examples.agentic_environment_generation.web_api.model_settings import ModelSettings

    ModelSettings().forget("owner")
    assert resolve(auth, read)[0]["password"] == SECRET
    profiles["graph"]["connection"]["password"] = "rotated-private-password-789"
    with pytest.raises(ValueError):
        resolve(auth, read)
    fresh = auth.issue(sessions.current, frozen, "request", "graph_write")
    auth.bind_attempt(fresh, "attempt", 1)
    assert resolve(auth, fresh)[0]["password"] == "rotated-private-password-789"
    auth.protect_public({k: profiles["graph"]["connection"][k] for k in ("uri", "user", "database")})
    for value in ({"nested": ["rotated-private-password-789"]}, {"rotated-private-password-789": "key"}):
        with pytest.raises(ValueError, match="Publication authorization unavailable"):
            auth.protect_public(value)


@pytest.mark.parametrize("expiry", [100, 99, True, float("nan"), float("inf"), 10**200])
def test_invalid_session_deadlines_fail_closed(expiry):
    auth, sessions, _, _ = setup()
    sessions.current["expires_at"] = expiry
    with pytest.raises(ValueError, match="Publication authorization unavailable"):
        issue(auth, sessions)


def test_capacity_purge_deadline_and_no_defaults():
    auth, sessions, profiles, now = setup(capacity=2)
    sessions.current["expires_at"] = 150
    assert issue(auth, sessions)["expires_at"] == 150
    issue(auth, sessions, "graph_read")
    with pytest.raises(ValueError):
        issue(auth, sessions)
    now[0] = 150
    auth.purge()
    sessions.current["expires_at"] = 1000
    grant = issue(auth, sessions)
    auth.bind_attempt(grant, "attempt", 1)
    now[0] = float("nan")
    with pytest.raises(ValueError):
        resolve(auth, grant)
    now[0] = 160
    for field in ("uri", "user", "password", "database"):
        connection = profiles["graph"]["connection"]
        saved = connection.pop(field)
        with pytest.raises(ValueError):
            auth.profile_metadata("graph")
        connection[field] = saved


def test_callback_mutation_cannot_rebind_resolve_input():
    auth, sessions, profiles, _ = setup()
    grant = issue(auth, sessions)
    auth.bind_attempt(grant, "attempt", 1)
    supplied = copy.deepcopy(grant)
    supplied["payload_sha256"] = "b" * 64

    def getter():
        supplied["payload_sha256"] = grant["payload_sha256"]
        return profiles

    auth.profiles_getter = getter
    with pytest.raises(ValueError):
        resolve(auth, supplied)


@pytest.mark.parametrize(
    "field,value",
    [
        ("effect_id", "bad/identifier"),
        ("effect_id", "x" * 65),
        ("payload_sha256", "z" * 64),
        ("payload", {"bad": float("nan")}),
        ("payload", {"bad": "x" * 32769}),
        ("target_profile", {"profile_id": "graph", "revision": "b" * 64}),
        ("payload", {"secret": SECRET}),
    ],
)
def test_bad_intents_never_issue_or_leak(field, value):
    auth, sessions, _, _ = setup()
    frozen = intent(auth)
    frozen[field] = value
    with pytest.raises(ValueError) as caught:
        auth.issue(sessions.current, frozen, "request", "graph_write")
    assert str(caught.value) == "Publication authorization unavailable"
    assert SECRET not in str(caught.value)


def test_no_construction_lookup_and_public_guard_freezes_before_callback():
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_authorization import (
        PublicationAuthorization,
    )

    def forbidden():
        raise AssertionError("construction must not lookup")

    PublicationAuthorization(Sessions(), forbidden, clock=forbidden)
    auth, sessions, profiles, _ = setup()
    issue(auth, sessions)
    supplied = {"private": SECRET}

    def getter():
        supplied.clear()
        return profiles

    auth.profiles_getter = getter
    with pytest.raises(ValueError):
        auth.protect_public(supplied)


@pytest.mark.parametrize("role", ["publication_write", "reconciliation_read", "model", "retrieval_read", None, []])
def test_only_core_graph_capabilities(role):
    auth, sessions, _, _ = setup()
    with pytest.raises(ValueError):
        issue(auth, sessions, role)


def test_real_sessions_resolve_inside_existing_journal_transaction(tmp_path):
    from contextlib import closing

    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
    from isaaclab_arena.agentic_environment_generation.workbench.sessions import Sessions as RealSessions

    auth, _, _, _ = setup()
    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        sessions = RealSessions(journal, clock=lambda: 100)
        session, token = sessions.create()
        auth.sessions = sessions
        grant = auth.issue(session, intent(auth), "request", "graph_write")
        auth.bind_attempt(grant, "attempt", 1)
        with journal._transaction():
            assert resolve(auth, grant)[0]["password"] == SECRET
        sessions.revoke(token)
        with journal._transaction():
            with pytest.raises(ValueError):
                resolve(auth, grant)


@pytest.mark.parametrize("revoked", [False, True])
def test_configured_password_is_guarded_without_live_grants(revoked):
    auth, sessions, profiles, _ = setup()
    if revoked:
        auth.revoke(issue(auth, sessions)["grant_id"])
    public = {k: profiles["graph"]["connection"][k] for k in ("uri", "user", "database")}
    assert auth.protect_public(public) is None
    with pytest.raises(ValueError, match="Publication authorization unavailable"):
        auth.protect_public({"unused": SECRET})
    assert auth._records == {}


def test_rotation_guard_checks_frozen_password_once_then_forgets():
    auth, sessions, profiles, _ = setup()
    issue(auth, sessions)
    profiles["graph"]["connection"]["password"] = "replacement-private-password-654321"
    with pytest.raises(ValueError):
        auth.protect_public({"old_inflight_marker": SECRET})
    assert auth._records == {}
    # A revoked secret is not retained as an indefinite global denylist.
    assert auth.protect_public({"old_inflight_marker": SECRET}) is None
    with pytest.raises(ValueError):
        auth.protect_public({"new_marker": profiles["graph"]["connection"]["password"]})


@pytest.mark.parametrize("connection", [{"password": SECRET}, {"uri": "bad-uri", "password": SECRET}])
@pytest.mark.parametrize("profile_id", ["graph", "unrelated"])
def test_public_guard_recovers_password_without_connection_authority(connection, profile_id):
    auth, sessions, profiles, _ = setup()
    frozen = intent(auth)
    profiles[profile_id] = {"connection": connection}
    snapshot = copy.deepcopy(profiles)
    public = {"status": ["accepted"]}
    assert auth.protect_public(public) is None
    assert public == {"status": ["accepted"]}
    for value in ({"nested": [SECRET]}, {SECRET: "key"}):
        original = copy.deepcopy(value)
        with pytest.raises(ValueError, match="^Publication authorization unavailable$"):
            auth.protect_public(value)
        assert value == original
    assert profiles == snapshot
    assert auth._records == {}
    with pytest.raises(ValueError):
        auth.profile_metadata(profile_id)
    if profile_id == "graph":
        with pytest.raises(ValueError):
            auth.issue(sessions.current, frozen, "request", "graph_write")


@pytest.mark.parametrize(
    "profile",
    [
        None,
        [],
        "invalid",
        {},
        {"connection": None},
        {"connection": []},
        {"connection": {}},
        *({"connection": {"password": password}} for password in (None, False, 123, [], {}, "")),
    ],
)
def test_public_guard_inspectable_profiles_without_text_password_have_no_marker(profile):
    auth, _, profiles, _ = setup()
    profiles["graph"] = profile
    snapshot = copy.deepcopy(profiles)
    assert auth.protect_public({"safe": "accepted"}) is None
    assert profiles == snapshot
    with pytest.raises(ValueError):
        auth.profile_metadata("graph")


@pytest.mark.parametrize("password", [" ", "\t\n", " padded-private-password "])
def test_public_guard_preserves_nonempty_password_even_when_blank(password):
    auth, _, profiles, _ = setup()
    profiles["graph"] = {"connection": {"password": password}}
    assert auth.protect_public({"safe": "accepted"}) is None
    with pytest.raises(ValueError):
        auth.protect_public({"text": "prefix" + password + "suffix"})


@pytest.mark.parametrize("bad", [object(), float("nan"), "x" * 65537, [None] * 4097])
def test_public_guard_uninspectable_profile_fails_closed(bad):
    auth, _, profiles, _ = setup()
    profiles["unrelated"] = {"connection": {"password": bad}}
    with pytest.raises(ValueError, match="^Publication authorization unavailable$"):
        auth.protect_public({"safe": "accepted"})


@pytest.mark.parametrize("bad_collection", [None, [], {1: {}}, {"x" * 1048577: {}}, {str(i): {} for i in range(17)}])
def test_public_guard_uninspectable_collection_fails_closed(bad_collection):
    auth, _, _, _ = setup()
    auth.profiles_getter = lambda: bad_collection
    with pytest.raises(ValueError, match="^Publication authorization unavailable$"):
        auth.protect_public({"safe": "accepted"})


@pytest.mark.parametrize("kind", ["cycle", "depth", "getter"])
def test_public_guard_uninspectable_source_purges_frozen_records(kind):
    auth, sessions, profiles, _ = setup()
    issue(auth, sessions)
    if kind == "getter":

        def unavailable():
            raise RuntimeError(SECRET)

        auth.profiles_getter = unavailable
    elif kind == "cycle":
        profiles["graph"]["cycle"] = profiles
    else:
        nested = {}
        for _ in range(17):
            nested = {"nested": nested}
        profiles["graph"] = nested
    with pytest.raises(ValueError, match="^Publication authorization unavailable$"):
        auth.protect_public({"safe": "accepted"})
    assert auth._records == {}


@pytest.mark.parametrize("reject", [False, True])
def test_malformed_profile_scans_frozen_marker_before_purge(reject):
    auth, sessions, profiles, _ = setup()
    issue(auth, sessions)
    profiles["graph"] = None
    if reject:
        with pytest.raises(ValueError):
            auth.protect_public({"old": SECRET})
    else:
        assert auth.protect_public({"safe": "accepted"}) is None
    assert auth._records == {}
    assert auth.protect_public({"forgotten": SECRET}) is None


def test_profile_is_detached_nonsecret_and_explicit():
    auth, _, profiles, _ = setup()
    public = auth.profile_metadata("graph")
    assert set(public) == {"profile_id", "revision", "scope_ownership"}
    assert public["profile_id"] == "graph"
    assert public["scope_ownership"] == "cooperative_immutable"
    assert len(public["revision"]) == 64
    assert SECRET not in json.dumps(public)
    assert "example.invalid" not in json.dumps(public)
    public["profile_id"] = "mutated"
    assert auth.profile_metadata("graph")["profile_id"] == "graph"
    profiles["graph"]["connection"]["password"] = "replacement-private-password-654321"
    assert auth.profile_metadata("graph")["revision"] == public["revision"]
    for boundary in (None, False, 1, "true"):
        profiles["graph"]["immutable_scope"] = boundary
        with pytest.raises(ValueError, match="Publication authorization unavailable"):
            auth.profile_metadata("graph")
    del profiles["graph"]["immutable_scope"]
    with pytest.raises(ValueError):
        auth.profile_metadata("graph")
