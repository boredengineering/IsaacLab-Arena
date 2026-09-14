# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Isolated SQLite/filesystem and explicit fake-driver contracts, never live Cypher."""

import importlib
import json
import socket
from copy import deepcopy

import pytest

from isaaclab_arena.tests.test_workbench_research_graph_transport import ready_driver, transport
from isaaclab_arena_examples.tests.test_workbench_research_store import candidate

TARGET = {"profile_id": "graph", "revision": "a" * 64, "scope_ownership": "cooperative_immutable"}


def module():
    return importlib.import_module("isaaclab_arena.agentic_environment_generation.workbench.research_retrieval")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*a, **kw):
        pytest.fail("No actual sockets permitted")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture
def env(tmp_path, monkeypatch):
    from isaaclab_arena.environment_spec.arena_env_graph_types import AssetRegistry, TaskRegistry

    monkeypatch.setattr(AssetRegistry, "is_registered", lambda *a: True)
    monkeypatch.setattr(TaskRegistry, "is_registered", lambda *a: True)
    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
    from isaaclab_arena.agentic_environment_generation.workbench.research_publication import PublicationAttempts
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    journal = Journal(tmp_path / "journal.sqlite3")
    journal.begin_run()
    store = ResearchStore.create(journal, tmp_path / "store", "store", protect_public=lambda v: None)
    attempts = PublicationAttempts(journal, store.registry, initialize=True, protect_public=lambda v: None)
    driver = ready_driver()
    driver.evaluations = []
    original_session = driver.session

    def session(**kw):
        assert kw["database"] == "research"
        s = original_session(**kw)
        original_run = s.run

        def run(query, **params):
            if str(query).startswith("// managed evaluation"):
                assert 0 < query.timeout <= 5
                driver.calls.append((str(query), params))
                rows = driver.evaluations(params) if callable(driver.evaluations) else driver.evaluations
                return deepcopy(rows)
            return original_run(query, **params)

        s.run = run
        return s

    driver.session = session

    def add(family="family", effect="effect", target=None, verified=True, source_change=None):
        import hashlib
        import yaml

        def simplify(receipt):
            data = yaml.safe_load(receipt["yaml_text"])
            data["relations"] = []
            if source_change:
                source_change(data)
            receipt["yaml_text"] = yaml.safe_dump(data)
            receipt["validation"]["source_hash"] = hashlib.sha256(receipt["yaml_text"].encode()).hexdigest()

        args, _ = candidate(journal, key=effect, receipt_change=simplify)
        commit = store.persist_candidate(
            family, effect, **args, publication_request={"effect_id": effect, "target_profile": target or TARGET}
        )
        files = store.read_version(commit["reservation"]["reservation_id"])
        projection = json.loads(files["projection.json"])
        spec = ArenaEnvGraphSpec.from_dict(Documents(".").validate(files["environment.yaml"].decode())["spec"])
        if verified:
            intent = store.registry.get_publication_intent(effect)
            grant = dict(
                grant_id="grant-" + effect,
                request_id="request-" + effect,
                effect_id=effect,
                target_profile=intent["target_profile"],
                payload_sha256=intent["payload_sha256"],
                capability="graph_write",
                expires_at=10**12,
            )
            accepted = attempts.claim(effect, grant["request_id"], grant)
            attempts.release(effect, accepted["attempt_id"], accepted["generation"], grant_metadata=grant)
            receipt = dict(
                schema_version=1,
                status="verified",
                effect_id=effect,
                target_profile=intent["target_profile"],
                payload_sha256=intent["payload_sha256"],
                transport=transport().publish_once(
                    driver, "research", projection, spec=spec, effect_id=effect, immutable_scope_attested=True
                ),
            )
            assert attempts.complete_verified(
                effect, accepted["attempt_id"], accepted["generation"], receipt=receipt, comparator=lambda *a: True
            )
        driver.calls.clear()
        return projection

    yield store, attempts, driver, add
    store.close()
    journal.close()


def provider(env, **kw):
    return module().ManagedSelectionProvider(
        [(env[0], env[1])], database="research", authorized_targets={"graph": TARGET}, **kw
    )


def test_verified_source_is_structural_without_convergence(env):
    projection = env[3]()
    rows = provider(env)(env[2], min_success_rate=0, min_episodes=1)
    assert len(rows) == 1
    row = rows[0]
    spec = json.loads(row["_canonical_proof"]["spec_json"])
    assert row["task_description"] == spec["task"]["description"]
    assert row["objects"] == [o["registry_name"] for o in spec["objects"]]
    assert row["best_success_rate"] is row["episodes"] is row["evaluation_id"] is None
    assert row["graph_version"] == projection["canonical_identity"]["sha256"]
    assert all("MERGE" not in q and "CREATE" not in q for q, _ in env[2].calls)
    assert all(s.options["default_access_mode"] == "READ" for s in env[2].sessions[1:])


@pytest.mark.parametrize(
    "expected",
    [
        "structural",
        "measured",
        "controller",
        "empty",
        "structural-six",
        "invalid-run",
        "invalid-trial-policy",
        "invalid-env-name",
        "invalid-env-version",
        "invalid-run-policy",
    ],
)
def test_real_provider_integrates_with_strict_snapshot_adapter(env, expected):
    from isaaclab_arena.agentic_environment_generation import graph_rag
    from isaaclab_arena.agentic_environment_generation.prior_receipt import validate_prior_snapshot

    projection = env[3](verified=expected != "empty")
    if expected == "structural-six":
        for i in range(5):
            env[3](
                family=f"f{i}",
                effect=f"e{i}",
                source_change=lambda data, i=i: data["task"].update(description=f"Task {i}"),
            )
    driver = env[2]
    if expected == "measured":
        driver.evaluations = [evaluation()]
    elif expected == "controller" or expected.startswith("invalid-"):
        driver.evaluations = [controller_evaluation(projection)]
        control = provider(env)(driver, min_success_rate=0, min_episodes=1)[0]
        assert control["checkpoint_identity"] == "checkpoint-a"
        if expected.startswith("invalid-"):
            evaluation_row = driver.evaluations[0]
            target, field = {
                "invalid-run": (evaluation_row["controllers"][0], "run_id"),
                "invalid-trial-policy": (evaluation_row["controllers"][0], "trial_policy_identity"),
                "invalid-env-name": (evaluation_row, "env_name"),
                "invalid-env-version": (evaluation_row, "env_version"),
                "invalid-run-policy": (evaluation_row, "policy_identity"),
            }[expected]
            target[field] = None
    original_session = driver.session

    def session(**kwargs):
        result = original_session(**kwargs)
        original_run = result.run

        def run(query, **params):
            if str(query) in (graph_rag._SNAPSHOT_EVALUATED_QUERY, graph_rag._SNAPSHOT_STRUCTURAL_QUERY):
                assert "HAS_REVISION" in str(query)
                driver.calls.append((str(query), params))
                return []  # Explicitly no legacy fixtures in this combined-provider test.
            return original_run(query, **params)

        result.run = run

        class ContextSession:
            def __getattr__(self, name):
                return getattr(result, name)

            def __enter__(self):
                return result

            def __exit__(self, *exc):
                result.close()

        return ContextSession()

    driver.session = session
    instance = provider(env)
    callback_calls = []
    callback_rows = []

    class ObservedProvider:
        database = "research"

        def __call__(self, supplied_driver, **kwargs):
            import time

            assert supplied_driver is driver
            assert kwargs["limit"] == 32
            assert time.monotonic() < kwargs["deadline_monotonic"] <= time.monotonic() + 180
            callback_calls.append(kwargs)
            rows = instance(supplied_driver, **kwargs)
            callback_rows.extend(deepcopy(rows))
            if expected == "structural-six":
                assert len(rows) == 6
            return rows

    snapshot = graph_rag.GraphRAGRetriever(driver).retrieve_prior_snapshot(
        "Arrange objects", limit=5, database="research", managed_selection_provider=ObservedProvider()
    )
    assert len(callback_calls) == 1
    status = "measured" if expected == "controller" else expected.removesuffix("-six")
    if expected.startswith("invalid-"):
        status = "unavailable"
        assert snapshot["warnings"] == ["invalid_record"]
        assert snapshot["priors"] == [] and snapshot["exact_context"] == ""
    assert snapshot["status"] == status, snapshot["warnings"]
    assert validate_prior_snapshot(snapshot, prompt="Arrange objects") == snapshot
    assert "_canonical_proof" not in json.dumps(snapshot)
    assert all("MERGE" not in query and "CREATE" not in query for query, _ in driver.calls)
    if expected == "structural-six":
        assert len(snapshot["priors"]) == 5
    elif status in ("measured", "structural"):
        assert len(snapshot["priors"]) == 1
        assert snapshot["priors"][0]["graph_version"] == projection["canonical_identity"]["sha256"]
        assert snapshot["priors"][0]["evaluation_id"] == ("run-a" if status == "measured" else None)
    if expected == "controller":
        legacy = legacy_snapshot(legacy_controller_record(callback_rows[0], driver.evaluations[0]))
        for field in ("status", "priors", "exact_context", "context_sha256", "effective_settings", "warnings"):
            assert legacy[field] == snapshot[field]


def test_duplicate_canonical_scopes_choose_lexical_family_not_latest(env):
    first = env[3]("aaa", "effect-a")
    env[3]("zzz", "effect-z")
    rows = provider(env)(env[2], min_success_rate=0, min_episodes=1)
    assert len(rows) == 1
    effects = [p["effect_id"] for q, p in env[2].calls if q.startswith("// effect")]
    assert effects and set(effects) == {"effect-a"}
    pinned = provider(env, pinned_scopes={first["canonical_identity"]["sha256"]: "0" * 64})
    with pytest.raises(ValueError):
        pinned(env[2], min_success_rate=0, min_episodes=1)


@pytest.mark.parametrize(
    "change",
    [
        {"limit": 0},
        {"limit": 33},
        {"min_episodes": True},
        {"min_success_rate": float("nan")},
        {"fixture": 5},
        {"deadline_monotonic": True},
        {"deadline_monotonic": float("inf")},
        {"deadline_monotonic": float("nan")},
    ],
)
def test_invalid_bounds_open_no_sessions(env, change):
    with pytest.raises(ValueError):
        provider(env)(env[2], **{**dict(min_success_rate=0, min_episodes=1), **change})
    assert not env[2].sessions


def evaluation(**changes):
    return {
        **dict(
            evaluation_id="run-a",
            best_success_rate=0.8,
            episodes=10,
            policy_identity="policy-a",
            env_name=None,
            env_version=None,
            policies=["policy-a"],
            policy_links=1,
            policy_labels=[["Policy"]],
            trial_links=0,
            controllers=[],
            graph_links=1,
            run_ids=1,
        ),
        **changes,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"policy_labels": [["Wrong"]]},
        {"policy_links": 2, "policy_labels": [["Policy"], ["Wrong"]]},
        {"policy_links": 2, "policies": ["policy-a", "policy-a"], "policy_labels": [["Policy"], ["Policy"]]},
        {"trial_links": 1, "controllers": []},
        {"trial_links": 2},
    ],
)
def test_unfiltered_provenance_counts_and_endpoint_labels(env, change):
    env[3]()
    env[2].evaluations = [evaluation(**change)]
    with pytest.raises(ValueError):
        provider(env)(env[2], min_success_rate=0, min_episodes=1)


def test_provenance_query_does_not_filter_malformed_edges():
    query = module()._EVALUATION_QUERY
    assert "(p:Policy)" not in query
    assert "(t:DCRGControllerTrial)" not in query
    assert "(v:DCRGControllerVariant)" not in query
    assert "AS trial_links" in query
    assert "AS evaluation_links" in query
    assert "AS controller_links" in query
    assert "labels(p)" in query and "labels(t)" in query and "labels(v)" in query
    assert "apoc" not in query.lower()


def test_exact_measured_run_and_query_provenance(env):
    p = env[3]()
    env[2].evaluations = [evaluation()]
    row = provider(env)(env[2], min_success_rate=0.5, min_episodes=4)[0]
    assert (row["evaluation_id"], row["best_success_rate"], row["episodes"], row["policy_identity"]) == (
        "run-a",
        0.8,
        10,
        "policy-a",
    )
    query, params = next((q, p) for q, p in env[2].calls if q.startswith("// managed evaluation"))
    assert params["name"] == p["canonical_identity"]["name"]
    assert "ev.success_rate > $min_success_rate" in query
    assert "LIMIT 1" in query and "sum(" not in query.lower()
    assert "HAS_REIFIER" not in query and "CONTAINS_OBJECT" not in query


@pytest.mark.parametrize(
    "change",
    [
        {"best_success_rate": float("nan")},
        {"episodes": 1000001},
        {"policies": ["a", "b"]},
        {"graph_links": 2},
        {"run_ids": 2},
        {"policy_identity": "wrong"},
    ],
)
def test_invalid_same_run_evidence_rejected(env, change):
    env[3]()
    env[2].evaluations = [evaluation(**change)]
    with pytest.raises(ValueError):
        provider(env)(env[2], min_success_rate=0.5, min_episodes=4)


def test_scoped_filters_are_not_optional_matches(env):
    env[3]()
    assert provider(env)(env[2], min_success_rate=0, min_episodes=1, embodiment="not-the-robot") == []


@pytest.mark.parametrize("target", ["legacy", {**TARGET, "revision": "b" * 64}])
def test_unknown_target_skipped_without_readback(env, target):
    env[3](target=target)
    env[2].calls.clear()
    assert provider(env)(env[2], min_success_rate=0, min_episodes=1) == []
    assert not env[2].calls


def test_unverified_and_uncommitted_are_not_evidence(env):
    env[3](verified=False)
    assert provider(env)(env[2], min_success_rate=0, min_episodes=1) == []
    assert not env[2].calls


def test_missing_effect_readback_is_unavailable_not_empty(env):
    env[3]()
    env[2].nodes = {k: n for k, n in env[2].nodes.items() if "ArenaPublicationEffect" not in n["labels"]}
    with pytest.raises(ValueError, match="readback"):
        provider(env)(env[2], min_success_rate=0, min_episodes=1)


def test_failed_readback_and_missing_tables_never_initialize(env):
    env[3]()
    env[2].constraints = []
    with pytest.raises(Exception):
        provider(env)(env[2], min_success_rate=0, min_episodes=1)
    env[1].journal.db.execute("DROP TABLE publication_states")
    with pytest.raises(ValueError):
        provider(env)(env[2], min_success_rate=0, min_episodes=1)
    assert env[1].journal.db.execute("SELECT 1 FROM sqlite_master WHERE name='publication_states'").fetchone() is None


def test_foreign_journal_rejected(env):
    from types import SimpleNamespace

    bad = SimpleNamespace(journal=object(), registry=env[0].registry)
    with pytest.raises(ValueError, match="Foreign"):
        module().ManagedSelectionProvider([(env[0], bad)], database="research", authorized_targets={"graph": TARGET})


def test_managed_full_limit_retains_sixth_candidate(env):
    for i in range(6):
        env[3](
            family=f"f{i}", effect=f"e{i}", source_change=lambda data, i=i: data["task"].update(description=f"Task {i}")
        )
    rows = provider(env)(env[2], min_success_rate=0, min_episodes=1, limit=32)
    assert len(rows) == 6
    assert len(provider(env)(env[2], min_success_rate=0, min_episodes=1)) == 5
    measured_name = rows[0]["name"]
    env[2].evaluations = lambda params: [evaluation()] if params["name"] == measured_name else []
    mixed = provider(env)(env[2], min_success_rate=0, min_episodes=1, limit=32)
    assert len(mixed) == 6
    assert sum(row["evaluation_id"] is not None for row in mixed) == 1


@pytest.mark.parametrize("stage", ["expired", "prepare", "readback", "evaluation", "validation", "copy"])
def test_cooperative_deadline_never_returns_empty_or_stale_rows(env, monkeypatch, stage):
    import time

    env[3]()
    instance = provider(env)
    now = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    if stage == "expired":
        now[0] = 102.0
    else:
        target, attr = {
            "prepare": (instance, "_prepare"),
            "readback": (module().transport, "reconcile_once"),
            "evaluation": (module(), "_evaluation"),
            "validation": (module(), "validate_prior"),
            "copy": (module(), "deepcopy"),
        }[stage]
        original = getattr(target, attr)

        def expire(*args, **kwargs):
            result = original(*args, **kwargs)
            now[0] = 102.0
            return result

        monkeypatch.setattr(target, attr, expire)
    with pytest.raises(ValueError, match="retrieval_failed"):
        instance(env[2], min_success_rate=0, min_episodes=1, deadline_monotonic=101.0)
    if stage in ("expired", "prepare"):
        assert not env[2].calls
    assert all(s.closed for s in env[2].sessions)


def test_budget_counts_before_filtering(env):
    env[3](effect="a", verified=False)
    env[3](effect="b", verified=False)
    with pytest.raises(ValueError, match="bounds_exceeded"):
        provider(env, candidate_budget=1)(env[2], min_success_rate=0, min_episodes=1)
    assert not env[2].calls


def test_canonical_collision_fails_before_membership(env, monkeypatch):
    env[3]("aaa", "a")
    env[3]("bbb", "b")
    instance = provider(env)
    original = instance._prepare

    def collide(*args):
        result = original(*args)
        if result["effect"] == "b":
            root = next(n for n in result["projection"]["nodes"] if n["labels"] == ["EnvironmentGraph"])
            root["properties"]["spec_json"] += " "
        return result

    monkeypatch.setattr(instance, "_prepare", collide)
    with pytest.raises(ValueError, match="collision"):
        instance(env[2], min_success_rate=0, min_episodes=1)
    assert not env[2].calls


def test_readback_global_support_reifiers_are_not_authored(env):
    env[3]()
    env[2].nodes["global-support"] = dict(
        eid="global-support",
        labels=["ReifiedRelation"],
        properties=dict(env_name="global", relation_type="SUPPORT", kinematic_manifold="made-up"),
    )
    row = provider(env)(env[2], min_success_rate=0, min_episodes=1)[0]
    assert row["relations"] == []


@pytest.mark.parametrize("name", ["", " ", 0, False, "x" * 4097])
def test_present_policy_name_is_validated_before_fallback(env, name):
    env[3]()
    env[2].evaluations = [evaluation(policies=[name], policy_identity=None)]
    with pytest.raises(ValueError):
        provider(env)(env[2], min_success_rate=0, min_episodes=1)


def test_policy_null_must_not_disappear_in_collect(env):
    env[3]()
    env[2].evaluations = [evaluation(policies=[], policy_links=1)]
    with pytest.raises(ValueError):
        provider(env)(env[2], min_success_rate=0, min_episodes=1)


def test_unsupported_task_authored_reifier_spec_json(env):
    def change(data):
        data["task"] = {"description": "Open door", "subtasks": [{"kind": "OpenDoorTask", "params": {}}]}
        data["reified_relations"] = [
            dict(
                reifier_id="authored",
                source_id=data["objects"][0]["id"],
                target_id=data["background"]["id"],
                relation_type="AUTHORED",
                kinematic_manifold="planar",
                surface_anchor="top",
            )
        ]

    p = env[3](source_change=change)
    assert p["dcrg_mapping"]["status"] == "unsupported"
    row = provider(env)(env[2], min_success_rate=0, min_episodes=1)[0]
    assert row["name"].startswith("workbench__")
    assert row["relations"] == [dict(relation_type="AUTHORED", manifold="planar", anchor="top")]
    assert row["evaluation_id"] is None


def controller_evaluation(projection):
    """Build complete same-run writer facts before independently corrupting them."""
    identity = projection["canonical_identity"]
    return evaluation(
        env_name=identity["name"],
        env_version=identity["sha256"],
        trial_links=1,
        controllers=[
            dict(
                trial_id="run-a",
                run_id="run-a",
                trial_policy_identity="policy-a",
                variant_id="v",
                id="v",
                policy_identity="policy-a",
                checkpoint_identity="checkpoint-a",
                env_name=identity["name"],
                env_version=identity["sha256"],
                trial_labels=["DCRGControllerTrial"],
                controller_labels=["DCRGControllerVariant"],
                evaluation_labels=[["EvaluationRun"]],
                evaluation_links=1,
                controller_links=1,
            )
        ],
    )


def checked_controller_control(env):
    control = controller_evaluation(env[3]())
    env[2].evaluations = [deepcopy(control)]
    row = provider(env)(env[2], min_success_rate=0, min_episodes=1)[0]
    assert (row["checkpoint_identity"], row["evaluation_id"], row["best_success_rate"], row["episodes"]) == (
        "checkpoint-a",
        "run-a",
        0.8,
        10,
    )
    return control, row


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"trial_labels": ["Wrong"]},
        {"controller_labels": ["Wrong"]},
        {"evaluation_labels": [["Wrong"]]},
        {"evaluation_links": 2},
        {"controller_links": 2},
        {"controller_links": 0},
        {"trial_id": "other-run"},
        {"checkpoint_identity": None},
        {"checkpoint_identity": ""},
        {"checkpoint_identity": "   "},
        {"id": 1},
        {"variant_id": 1},
    ],
)
def test_checkpoint_from_exact_controller(env, change):
    control, _ = checked_controller_control(env)
    control["controllers"][0].update(change)
    env[2].evaluations = [control]
    if change:
        with pytest.raises(ValueError):
            provider(env)(env[2], min_success_rate=0, min_episodes=1)
    else:
        row = provider(env)(env[2], min_success_rate=0, min_episodes=1)[0]
        assert (row["checkpoint_identity"], row["evaluation_id"], row["best_success_rate"], row["episodes"]) == (
            "checkpoint-a",
            "run-a",
            0.8,
            10,
        )


def legacy_controller_record(row, ev):
    """Translate raw facts, not validator results, into the legacy query projection."""
    trial = ev["controllers"][0]
    return {
        **row,
        **{field: ev.get(field) for field in ("evaluation_id", "best_success_rate", "episodes")},
        "policy_identity": ev["policies"][0],
        "checkpoint_identity": trial.get("checkpoint_identity"),
        "_graph_links": ev["graph_links"],
        "_run_ids": ev["run_ids"],
        "_run_policy": ev.get("policy_identity"),
        "_run_env_name": ev.get("env_name"),
        "_run_env_version": ev.get("env_version"),
        "_policies": [{"valid_label": True, "identity": name} for name in ev["policies"]],
        "_controllers": [{
            "valid_label": True,
            **{
                field: trial.get(field)
                for field in (
                    "trial_id",
                    "run_id",
                    "env_name",
                    "env_version",
                    "variant_id",
                    "evaluation_links",
                    "evaluation_labels",
                )
            },
            "policy_identity": trial.get("trial_policy_identity"),
            "variants": [{
                "valid_label": True,
                "identity": trial.get("checkpoint_identity"),
                "id": trial.get("id"),
                "policy_identity": trial.get("policy_identity"),
            }],
        }],
    }


def legacy_snapshot(row):
    from isaaclab_arena.agentic_environment_generation import graph_rag
    from isaaclab_arena.agentic_environment_generation.prior_receipt import validate_prior_snapshot
    from isaaclab_arena.tests.test_graph_rag_snapshot import Driver

    snapshot = graph_rag.GraphRAGRetriever(Driver([row])).retrieve_prior_snapshot(
        "Arrange objects", limit=5, database="research"
    )
    assert validate_prior_snapshot(snapshot, prompt="Arrange objects") == snapshot
    return snapshot


@pytest.mark.parametrize(
    "owner,field",
    [
        ("trial", field)
        for field in (
            "trial_id",
            "run_id",
            "trial_policy_identity",
            "env_name",
            "env_version",
            "variant_id",
            "id",
            "policy_identity",
        )
    ]
    + [("evaluation", field) for field in ("evaluation_id", "env_name", "env_version", "policy_identity")],
)
@pytest.mark.parametrize(
    "mutation",
    [
        "absent",
        None,
        "",
        "   ",
        0,
        False,
        [],
        {},
        "other",
        "x" * 4097,
    ],
    ids=["absent", "null", "empty", "blank", "integer", "boolean", "list", "map", "wrong", "oversize"],
)
def test_controller_binding_matches_legacy_from_valid_control(env, owner, field, mutation):
    from isaaclab_arena.agentic_environment_generation.prior_receipt import SnapshotRejected

    control, row = checked_controller_control(env)
    assert legacy_snapshot(legacy_controller_record(row, control))["status"] == "measured"
    target = control["controllers"][0] if owner == "trial" else control
    if mutation == "absent":
        target.pop(field)
    else:
        target[field] = mutation
    assert legacy_snapshot(legacy_controller_record(row, control))["status"] == "unavailable"
    env[2].evaluations = [control]
    with pytest.raises(SnapshotRejected):
        provider(env)(env[2], min_success_rate=0, min_episodes=1)


def test_managed_query_projects_trial_bindings_separately():
    query = module()._EVALUATION_QUERY
    assert "run_id:t.run_id" in query
    assert "trial_policy_identity:t.policy_identity" in query
    assert "policy_identity:v.policy_identity" in query


@pytest.mark.parametrize(
    "mutation",
    ["absent", None, "", "   ", 0, False, [], {}, "x" * 4097],
    ids=["absent", "null", "empty", "blank", "integer", "boolean", "list", "map", "oversize"],
)
def test_checkpoint_text_matches_legacy_from_valid_control(env, mutation):
    from isaaclab_arena.agentic_environment_generation.prior_receipt import SnapshotRejected

    control, row = checked_controller_control(env)
    assert legacy_snapshot(legacy_controller_record(row, control))["status"] == "measured"
    trial = control["controllers"][0]
    if mutation == "absent":
        trial.pop("checkpoint_identity")
    else:
        trial["checkpoint_identity"] = mutation
    assert legacy_snapshot(legacy_controller_record(row, control))["status"] == "unavailable"
    env[2].evaluations = [control]
    with pytest.raises(SnapshotRejected):
        provider(env)(env[2], min_success_rate=0, min_episodes=1)


def test_controller_without_policy_endpoint_uses_bound_run_policy(env):
    control, row = checked_controller_control(env)
    control.update(policies=[], policy_links=0, policy_labels=[])
    env[2].evaluations = [control]
    assert provider(env)(env[2], min_success_rate=0, min_episodes=1) == [row]


def test_measured_run_without_policy_or_controller_keeps_unknown_null(env):
    env[3]()
    env[2].evaluations = [evaluation(policies=[], policy_links=0, policy_labels=[], policy_identity=None)]
    row = provider(env)(env[2], min_success_rate=0, min_episodes=1)[0]
    assert row["evaluation_id"] == "run-a"
    assert row["policy_identity"] is row["checkpoint_identity"] is None


@pytest.mark.parametrize("field", ["env_name", "env_version", "policy_identity"])
@pytest.mark.parametrize("absent", [False, True])
def test_absent_optional_run_provenance_without_controller(env, field, absent):
    env[3]()
    control = evaluation()
    env[2].evaluations = [deepcopy(control)]
    assert provider(env)(env[2], min_success_rate=0, min_episodes=1)[0]["evaluation_id"] == "run-a"
    if absent:
        control.pop(field)
    else:
        control[field] = None
    env[2].evaluations = [control]
    row = provider(env)(env[2], min_success_rate=0, min_episodes=1)[0]
    assert row["policy_identity"] == "policy-a"
    assert row["checkpoint_identity"] is None


@pytest.mark.parametrize("pins", [{"bad": "a" * 64}, {"a" * 64: "bad"}, ["bad"]])
def test_pin_format_is_not_repaired(env, pins):
    with pytest.raises(ValueError):
        provider(env, pinned_scopes=pins)


def test_receipt_generation_must_match_durable_record(env):
    env[3]()
    db = env[1].journal.db
    state = json.loads(db.execute("SELECT body FROM publication_states").fetchone()[0])
    state["generation"] += 1
    db.execute("UPDATE publication_states SET body=?", (json.dumps(state),))
    with pytest.raises(ValueError, match="receipt"):
        provider(env)(env[2], min_success_rate=0, min_episodes=1)
