# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Synthetic transaction contracts, not real Neo4j concurrency proofs."""
from dataclasses import FrozenInstanceError

import pytest


def scope_binding_body():
    return dict(
        schema_version=1,
        authority_id="explicit-authority",
        database="literal.db",
        deployment_id="deployment:one",
        workspace_id="workspace.one",
        operational_schema_version=1,
        artifact_marker_schema=1,
        store_id="artifact-store",
        registry_id="artifact-registry",
    )


@pytest.mark.parametrize("field", ["schema_version", "operational_schema_version", "artifact_marker_schema"])
@pytest.mark.parametrize("value", [True, 1.0, "1", 0, 2, None])
def test_scope_binding_versions_are_supported_exact_integers(field, value):
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

    with pytest.raises(ValueError):
        ScopeBinding.model_validate(scope_binding_body() | {field: value})


@pytest.mark.parametrize("field", ["store_id", "registry_id"])
@pytest.mark.parametrize("value", ["with.dot", "with:colon", "../relative", "", "x" * 129, "unicode-α"])
def test_scope_binding_artifact_ids_use_narrow_marker_grammar(field, value):
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

    with pytest.raises(ValueError):
        ScopeBinding.model_validate(scope_binding_body() | {field: value})


@pytest.mark.parametrize("field", ["root", "hostname", "credentials", "password", "driver", "executable", "ready"])
def test_scope_binding_rejects_location_private_or_executable_extras(field):
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

    with pytest.raises(ValueError):
        ScopeBinding.model_validate(scope_binding_body() | {field: "private-sentinel"})


def test_scope_binding_is_frozen_explicit_and_canonical():
    import hashlib

    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
        MAX_BINDING_BYTES,
        ScopeBinding,
        decode_scope_binding,
    )

    raw = scope_binding_body()
    binding = ScopeBinding.model_validate(raw)
    assert binding.database == "literal.db" and binding.workspace_id == "workspace.one"
    assert binding.authority_id != binding.store_id
    assert len(binding.body_json.encode()) < MAX_BINDING_BYTES
    assert binding.body_sha256 == hashlib.sha256(binding.body_json.encode()).hexdigest()
    assert decode_scope_binding(binding.body_json, binding.body_sha256) == binding
    for field in raw:
        with pytest.raises(ValueError):
            ScopeBinding.model_validate({k: v for k, v in raw.items() if k != field})
    with pytest.raises(ValueError):
        binding.authority_id = "changed"


@pytest.mark.parametrize("amounts,limit", [
    ([1.0, 1e-30], 2.0),
    ([1.0, 5e-324], 2.0),
    ([999999999999.0, 1.0, 1e-30], 1e12),
    ([0.9999999999999999] * 1000, 1000.0),
    ([0.0, 0.1, 0.2], 1.0),
])
@pytest.mark.parametrize("hostile_context", [False, True])
def test_inspection_budget_exact_for_admitted_amounts(amounts, limit, hostile_context):
    from decimal import Decimal, ROUND_DOWN, getcontext, localcontext
    from fractions import Fraction

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import GenerationReservation
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import WorkflowContract, contract_digest
    from isaaclab_arena.agentic_environment_generation.workflow.queries import (
        FrozenRunIntentView, FrozenSubmissionInspection, SceneReadScope,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.read_model import inspection_budget
    from isaaclab_arena.tests.test_environment_workflow_service import contract

    raw = contract().model_dump(mode="json")
    raw["budget"].update(max_cost_usd=limit, max_runtime_seconds=limit)
    accepted = WorkflowContract.model_validate(raw)
    scope = SceneReadScope(database="db", deployment_id="d", workspace_id="w")
    submission = FrozenSubmissionInspection(
        scope=scope, kind="SUBMIT", operation_id="key", run_id="a" * 64,
        request_digest="b" * 64, accepted_contract_digest=contract_digest(accepted),
        digest_codec="sha256-canonical-json-utf8-v1", admitted_at=100.0,
        disposition="retained_admission", provenance="legacy_run_record", receipt_version=None, cause_id=None,
    )
    intent = FrozenRunIntentView(
        scope=scope, run_id=submission.run_id, submission=submission, contract=accepted,
        state="cancelled", phase="generation", run_version=2, event_cursor=2,
        intent_projection_revision="d" * 64,
    )
    rows = [GenerationReservation(
        model_calls=1, model_tokens=1000000000,
        cost_ceiling_usd=value, runtime_allowance_seconds=value,
    ).model_dump(mode="json") for value in amounts]
    expected = sum((Fraction(str(value)) for value in amounts), Fraction(0))
    remaining = max(Fraction(0), Fraction(str(limit)) - expected)
    ambient = str(getcontext())
    with localcontext() as context:
        if hostile_context:
            context.prec, context.Emin, context.Emax = 2, -2, 2
            context.rounding = ROUND_DOWN
            for signal in context.traps:
                context.traps[signal] = True
        before = str(context)
        result = inspection_budget(intent, rows)
        after = str(context)
    assert str(getcontext()) == ambient
    for field in ("cost_ceiling_usd", "runtime_allowance_seconds"):
        assert Fraction(getattr(result.reserved, field)) == expected
        assert Fraction(getattr(result.remaining, field)) == remaining
        wire = result.model_dump(mode="json")
        assert type(wire["reserved"][field]) is str
        assert Fraction(wire["reserved"][field]) == expected
    assert after == before
    assert result.reserved.model_tokens == len(rows) * 1000000000
    assert result.reserved.model_calls == len(rows)
    assert result.remaining.model_tokens == 0
    assert result.actual_consumption == "unknown"
    assert result.accounting == "conservative_cumulative_reservations_no_refunds"
    if amounts == [1.0, 1e-30]:
        assert result.reserved.cost_ceiling_usd == Decimal("1.000000000000000000000000000001")
        assert result.model_dump(mode="json")["remaining"]["cost_ceiling_usd"] == "0.999999999999999999999999999999"
    if amounts == [0.0, 0.1, 0.2]:
        assert result.model_dump(mode="json")["reserved"]["cost_ceiling_usd"] == "0.3"


@pytest.mark.parametrize("method", ["get_submission_inspection", "get_run_intent"])
@pytest.mark.parametrize("identity", [" bad", "bad ", "", "../run", "a" * 129, 12, None])
def test_inspection_rejects_literal_identifier_before_driver_io(method, identity):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore

    class NoIO:
        def session(self, **kwargs):
            pytest.fail("malformed literal identifier reached IO")

    store = Neo4jWorkflowStore(NoIO(), database="db", deployment_id="d", workspace_id="w")
    with pytest.raises(ValueError, match="Invalid operation id"):
        getattr(store, method)(identity)


@pytest.mark.parametrize("field", ["run_version", "event_cursor"])
@pytest.mark.parametrize("value", [True, 1.0, -1, 2**63])
def test_intent_counters_reject_non_signed64_scalars(field, value):
    from isaaclab_arena.agentic_environment_generation.workflow.queries import FrozenRunIntentView

    # Isolate scalar validation without requiring an unrelated valid intent tree.
    from pydantic import TypeAdapter

    annotation = FrozenRunIntentView.model_fields[field].rebuild_annotation()
    with pytest.raises(ValueError):
        TypeAdapter(annotation).validate_python(value)
    assert TypeAdapter(annotation).validate_python(2**63 - 1) == 2**63 - 1
    if field == "run_version":
        with pytest.raises(ValueError):
            TypeAdapter(annotation).validate_python(0)
    else:
        assert TypeAdapter(annotation).validate_python(0) == 0


def test_model_profile_contract_preserves_literal_settings_and_freezes_policy():
    try:
        from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    except ImportError:
        pytest.fail("pure model profile registration contract is missing")
    value = profile_registration()
    profile = ProfileRegistration.model_validate(value)
    assert profile.roles == ("assessment_model", "generation_model")
    assert profile.settings.endpoint == "https://api.openai.com/v1/"
    assert profile.revision == 2
    value["settings"]["inference_policy"]["request_policy"]["store"] = False
    assert profile.settings.inference_policy.request_policy.store is None
    with pytest.raises(ValueError):
        profile.settings.inference_policy.request_policy.store = False


@pytest.mark.parametrize("damage", [
    "bool_revision", "zero_revision", "overflow_revision", "policy_bool_revision", "policy_store_zero",
    "duplicate_roles", "empty_roles", "unknown", "private", "executable", "oversize", "policy_binding",
    "user_defined_claim", "policy_unknown", "policy_endpoint",
])
def test_model_profile_structure_is_strict_and_bounded(damage):
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration

    value = profile_registration()
    policy = value["settings"]["inference_policy"]
    if damage in ("bool_revision", "zero_revision", "overflow_revision"):
        value["revision"] = {"bool_revision": True, "zero_revision": 0, "overflow_revision": 2**63}[damage]
    elif damage == "policy_bool_revision":
        policy["revision"] = True
    elif damage == "policy_store_zero":
        policy["request_policy"]["store"] = 0
    elif damage == "duplicate_roles":
        value["roles"] = ["generation_model", "generation_model"]
    elif damage == "empty_roles":
        value["roles"] = []
    elif damage in ("unknown", "private", "executable"):
        value["settings"][{"unknown": "temperature", "private": "api_key", "executable": "factory"}[damage]] = "forbidden"
    elif damage == "oversize":
        policy["documentation_urls"] = ["https://example.invalid/" + "界" * 4000]
    elif damage == "policy_binding":
        value["settings"]["model"] = "another-model"
    elif damage == "user_defined_claim":
        policy["origin"] = "user_defined"
    elif damage == "policy_endpoint":
        policy["endpoint"] = "https://unapproved.invalid"
    else:
        policy["credential"] = "forbidden"
    with pytest.raises(ValueError):
        ProfileRegistration.model_validate(value)


@pytest.mark.parametrize("accounting", [False, True])
def test_public_model_hash_is_legacy_byte_compatible(accounting):
    import hashlib
    import json

    from isaaclab_arena.agentic_environment_generation.workflow import profiles

    assert hasattr(profiles, "public_model_settings_sha256"), "public hash seam is missing"
    raw = profile_registration()["settings"]
    raw["inference_policy"]["documentation_urls"] = ["https://example.invalid/界"]
    if accounting:
        raw["workflow_accounting"] = {
            "version": 1, "attested": True, "model": raw["model"], "endpoint": raw["endpoint"],
            "max_tokens": 700, "max_cost_usd": "0.000000000",
        }
    # Independent legacy payload and encoding fixture (default ensure_ascii=True).
    expected = hashlib.sha256(json.dumps(
        {"version": 1, **raw}, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    settings = profiles.PublicModelSettings.model_validate(raw)
    assert profiles.public_model_settings_sha256(settings) == expected
    for key in ("private-one", "private-two"):
        private = {"api_key": key, **raw}
        selected = {k: v for k, v in private.items() if k != "api_key"}
        assert profiles.public_model_settings_sha256(profiles.PublicModelSettings.model_validate(selected)) == expected
    raw["inference_policy"] = None
    legacy = profiles.PublicModelSettings.model_validate(raw)
    assert profiles.public_model_settings_sha256(legacy) == hashlib.sha256(json.dumps(
        {"version": 1, **raw}, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    with pytest.raises(ValueError):
        profiles.ProfileRegistration.model_validate({**profile_registration(), "settings": raw})


@pytest.mark.parametrize("damage", ["extra", "wrong_endpoint", "bool_tokens", "not_attested"])
def test_public_accounting_uses_existing_strict_attestation(damage):
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import PublicModelSettings

    raw = profile_registration()["settings"]
    attestation = {
        "version": 1, "attested": True, "model": raw["model"], "endpoint": raw["endpoint"],
        "max_tokens": 700, "max_cost_usd": "0",
    }
    raw["workflow_accounting"] = attestation
    assert PublicModelSettings.model_validate(raw).workflow_accounting.max_tokens == 700
    if damage == "extra":
        attestation["api_key"] = "forbidden"
    elif damage == "wrong_endpoint":
        attestation["endpoint"] = "https://api.openai.com/v1"
    elif damage == "bool_tokens":
        attestation["max_tokens"] = True
    else:
        attestation["attested"] = False
    with pytest.raises(ValueError):
        PublicModelSettings.model_validate(raw)


@pytest.mark.parametrize("screen", ["absent", "mutate", "replace", "deny"])
def test_model_profile_registration_protection_precedes_io(screen):
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration

    d = Driver()
    registration = ProfileRegistration.model_validate(profile_registration())

    def protect(value):
        if screen == "mutate":
            value["registration"]["profile_id"] = "redacted"
        if screen == "replace":
            return {}
        if screen == "deny":
            raise ValueError("public-data rejected")

    with pytest.raises(ValueError):
        store(d).register_profile(registration, protect=None if screen == "absent" else protect)
    assert d.calls == []
    assert registration.profile_id == "public-model"


@pytest.mark.parametrize("field,value", [("profile_id", "bad id"), ("profile_id", "x" * 129),
                                         ("revision", True), ("revision", 0), ("revision", 2**63)])
def test_model_profile_lookup_rejects_invalid_identity_before_io(field, value):
    d = Driver()
    args = {"profile_id": "profile", "revision": 1, field: value}
    with pytest.raises(ValueError):
        store(d).get_profile(**args)
    assert d.calls == []


@pytest.mark.parametrize("field", ["database", "deployment_id", "workspace_id"])
def test_model_profile_scope_is_bounded_before_io(field):
    d = Driver()
    s = api().Neo4jWorkflowStore(d, **({"database": "db", "deployment_id": "d", "workspace_id": "w"} |
                                     {field: "x" * 129}))
    with pytest.raises(ValueError):
        s.list_profiles()
    assert d.calls == []


@pytest.mark.parametrize("field,value", [("schema_version", True), ("schema_version", 2),
                                         ("body_sha256", "f" * 64), ("settings_sha256", "f" * 64)])
def test_profile_revision_validates_codec_and_digest_bindings(field, value):
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import (
        ProfileRegistration, ProfileRevision, profile_revision,
    )

    revision = profile_revision(ProfileRegistration.model_validate(profile_registration()))
    raw = revision.model_dump(mode="json") | {field: value}
    with pytest.raises(ValueError):
        ProfileRevision.model_validate(raw)


@pytest.mark.parametrize("operation", ["read", "list"])
@pytest.mark.parametrize("failure", ["transport", "timeout", "query", "unknown"])
def test_profile_query_failures_are_not_retained_corruption(monkeypatch, operation, failure):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    error = {"transport": OSError, "timeout": TimeoutError, "query": ValueError,
             "unknown": api().OutcomeUnknown}[failure]("query boundary failure")
    original = Transaction.run

    def run(self, query, **params):
        if query.startswith("MATCH (p:ArenaWorkflowProfileRevision "):
            raise error
        return original(self, query, **params)

    monkeypatch.setattr(Transaction, "run", run)
    d = Driver([[{"workspace_id": "w"}]])
    screens = []
    service = WorkflowService(store(d), SimpleNamespace(require_read=lambda p: None), None, validate_support=None)
    with pytest.raises(type(error)) as caught:
        if operation == "read":
            service.read_profile("reader", "public-model", 2, protect=screens.append)
        else:
            service.list_profiles("reader", protect=screens.append)
    assert caught.value is error and screens == []
    assert [q for q, _ in d.calls][-2:] == ["tx.close", "session.close"]
    assert not any(q == "commit" for q, _ in d.calls)


def profile_registration():
    return {
        "profile_id": "public-model", "revision": 2, "kind": "model",
        "roles": ["generation_model", "assessment_model"],
        "settings": {
            "model": "gpt-4.1", "endpoint": "https://api.openai.com/v1/", "billing": "free",
            "inference_policy": {
                "id": "openai-gpt-4.1", "revision": 1, "provider": "openai", "model": "gpt-4.1",
                "endpoint": "https://api.openai.com/v1", "origin": "builtin", "support": "documented",
                "verification": "not_checked",
                "documentation_urls": ["https://developers.openai.com/api/docs/models/gpt-4.1"],
                "request_policy": {
                    "api": "chat_completions", "temperature_mode": "configured",
                    "token_limit_parameter": "max_tokens", "structured_output": "json_schema",
                    "multimodal_output": "json_object", "store": None,
                },
            },
        },
    }


def schema_rows():
    return [
        dict(entityType="NODE", type="UNIQUENESS", labelsOrTypes=[label], properties=fields)
        for label, fields in [
            ("ArenaWorkflowControl", ["deployment_id", "workspace_id"]),
            ("ArenaWorkflowRun", ["deployment_id", "workspace_id", "operation_id"]),
            ("ArenaWorkflowRun", ["deployment_id", "workspace_id", "run_id"]),
            ("ArenaWorkflowEvent", ["deployment_id", "workspace_id", "sequence"]),
            ("ArenaWorkflowProfile", ["deployment_id", "workspace_id", "profile_id"]),
            ("ArenaWorkflowProfileRevision", ["deployment_id", "workspace_id", "profile_id", "revision"]),
            ("ArenaCancelReceipt", ["deployment_id", "workspace_id", "kind", "operation_id"]),
            ("ArenaResumeReceipt", ["deployment_id", "workspace_id", "kind", "operation_id"]),
        ]
    ]


def history_index_rows():
    return (
        [
            dict(
                entityType="NODE",
                type="RANGE",
                state="ONLINE",
                owningConstraint="workflow_resume_command",
                labelsOrTypes=["ArenaResumeReceipt"],
                properties=["deployment_id", "workspace_id", "kind", "operation_id"],
            )
        ]
        + [
            dict(
                entityType="NODE",
                type="RANGE",
                state="ONLINE",
                owningConstraint=None,
                labelsOrTypes=[label],
                properties=["deployment_id", "workspace_id", field],
            )
            for label, field in (
                ("ArenaWorkflowCandidate", "record_id"),
                ("ArenaWorkflowEvidence", "record_id"),
                ("ArenaCriterionAssessment", "record_id"),
                ("ArenaWorkflowDecision", "decision_id"),
                ("ArenaWorkflowDecision", "evidence_id"),
                ("ArenaExecutionIntent", "intent_id"),
                ("ArenaExecutionIntent", "run_id"),
                ("ArenaExecutionAttempt", "attempt_id"),
                ("ArenaRetiredWorkflowOwner", "owner_id"),
            )
        ]
        + [
            dict(
                entityType="NODE",
                type="RANGE",
                state="ONLINE",
                owningConstraint=None,
                labelsOrTypes=["ArenaWorkflowCandidate"],
                properties=["deployment_id", "workspace_id", "run_id", "record_id"],
            ),
            dict(
                entityType="NODE",
                type="RANGE",
                state="ONLINE",
                owningConstraint=None,
                labelsOrTypes=["ArenaWorkflowDecision"],
                properties=["deployment_id", "workspace_id", "run_id", "decision_id"],
            ),
            dict(
                entityType="NODE",
                type="RANGE",
                state="ONLINE",
                owningConstraint=None,
                labelsOrTypes=["ArenaWorkflowEvent"],
                properties=[
                    "deployment_id",
                    "workspace_id",
                    "run_id",
                    "kind",
                    "sequence",
                ],
            ),
            dict(
                entityType="NODE",
                type="RANGE",
                state="ONLINE",
                owningConstraint=None,
                labelsOrTypes=["ArenaWorkflowProfileRevision"],
                properties=["deployment_id", "workspace_id"],
            ),
        ]
    )


@pytest.mark.parametrize("damage", ["missing", "populating", "wrong_scope", "unique", "wrong_type", "wrong_entity"])
def test_schema_verification_requires_online_nonunique_profile_scope_index(damage):
    rows = history_index_rows()
    if damage == "missing":
        rows.pop()
    else:
        field, value = {
            "populating": ("state", "POPULATING"), "wrong_scope": ("properties", ["workspace_id"]),
            "unique": ("owningConstraint", "constraint"), "wrong_type": ("type", "TEXT"),
            "wrong_entity": ("entityType", "RELATIONSHIP"),
        }[damage]
        rows[-1][field] = value
    d = Driver([schema_rows(), rows])
    with pytest.raises(api().SchemaMissing):
        store(d).verify_schema()
    assert not any("CREATE" in q or "awaitIndexes" in q for q, _ in d.calls)


@pytest.mark.parametrize("damage", ["missing", "populating", "wrong_scope", "unique"])
def test_schema_verification_requires_online_nonunique_history_indexes(damage):
    rows = history_index_rows()
    if damage == "missing":
        rows.pop(1)
    elif damage == "populating":
        rows[1]["state"] = "POPULATING"
    elif damage == "unique":
        rows[1]["owningConstraint"] = "unwanted-uniqueness"
    else:
        rows[1]["properties"] = ["record_id"]
    d = Driver([schema_rows(), rows])
    with pytest.raises(api().SchemaMissing):
        store(d).verify_schema()
    assert not any("CREATE" in q or "awaitIndexes" in q for q, _ in d.calls)


@pytest.mark.parametrize("label", ["ArenaExecutionAttempt", "ArenaRetiredWorkflowOwner"])
def test_cleanup_lookup_indexes_are_explicit_and_required(label):
    rows = [r for r in history_index_rows() if r["labelsOrTypes"] != [label]]
    with pytest.raises(api().SchemaMissing):
        store(Driver([schema_rows(), rows])).verify_schema()
    assert any(label in ddl and "CREATE INDEX" in ddl for ddl in api().Neo4jWorkflowStore.schema_requirements())


@pytest.mark.parametrize("damage", ["missing", "populating", "wrong_scope"])
def test_resume_schema_requires_explicit_online_exact_receipt_index(damage):
    rows = history_index_rows()
    if damage == "missing":
        rows.pop(0)
    elif damage == "populating":
        rows[0]["state"] = "POPULATING"
    else:
        rows[0]["properties"] = ["deployment_id", "workspace_id", "operation_id"]
    d = Driver([schema_rows(), rows])
    with pytest.raises(api().SchemaMissing, match="resume"):
        store(d).verify_schema()
    assert not any("CREATE" in q or "awaitIndexes" in q for q, _ in d.calls)


@pytest.mark.parametrize(
    "update",
    [
        dict(expectedVersion=True),
        dict(expectedVersion=1.0),
        dict(expectedVersion=0),
        dict(expectedVersion=2**63),
        dict(renewAuthorization=1),
        dict(renewAuthorization="true"),
        dict(runId=" run"),
        dict(runId="run "),
        dict(principal="x"),
        dict(adapter="cli"),
    ],
)
def test_resume_payload_is_strict_before_store_io(update):
    from isaaclab_arena.agentic_environment_generation.workflow.commands import ResumePayload

    payload = dict(runId="run", expectedVersion=2**63 - 1, renewAuthorization=False)
    assert ResumePayload.model_validate(payload).model_dump() == payload
    d = Driver([])
    with pytest.raises(ValueError):
        store(d).admit_resume(
            "literal.Resume:1", dict(payload, **update), selection=None, eligibility=None, protect=lambda v: None
        )
    assert d.calls == []


def test_schema_verification_and_explicit_scope_initialization():
    d = Driver([schema_rows(), history_index_rows(), schema_rows(), history_index_rows(), [{"floor": 0, "ceiling": 0}]])
    s = store(d)
    assert s.verify_schema() is True
    s.initialize_scope()
    queries = [q for q, _ in d.calls]
    assert sum(q.startswith("SHOW CONSTRAINTS") for q in queries) == 2
    assert not any("CREATE CONSTRAINT" in q for q in queries)
    assert any("MERGE (c:ArenaWorkflowControl" in q for q in queries)
    assert all(p == {"database": "explicit-db"} for q, p in d.calls if q == "session")
    assert all(p == {"timeout": 5} for q, p in d.calls if q == "begin")


def test_missing_schema_cannot_initialize():
    d = Driver([[]])
    with pytest.raises(api().SchemaMissing):
        store(d).initialize_scope()
    assert not any("MERGE" in q for q, _ in d.calls)


@pytest.mark.parametrize("failure", ["commit", "tx.close", "session.close"])
def test_cleanup_or_unknown_commit_never_returns_success(failure):
    d = Driver([schema_rows(), history_index_rows()], fail=failure)
    with pytest.raises(api().OutcomeUnknown):
        store(d).verify_schema()
    assert d.calls[-1][0] == "session.close"
    assert sum(q == "begin" for q, _ in d.calls) == 1


def run_row(**changes):
    return dict(
        run_id="run",
        operation_id="op",
        request_json='{"a":1}',
        contract_json='{"accepted":1}',
        version=1,
        state="pending",
        phase="dependency_readiness",
        event_cursor=1,
        **changes,
    )


def test_admission_locks_before_replay_and_capacity_and_retains_contract():
    row = run_row()
    d = Driver([[{"floor": 0, "ceiling": 0}], [], [{"pending": 0}], [{"run": row}]])
    result = store(d).admit("op", row["request_json"], row["contract_json"], 1)
    assert result.operation_id == "op" and result.event_cursor == 1
    with pytest.raises(FrozenInstanceError):
        result.state = "running"
    queries = [(q, p) for q, p in d.calls if "MATCH" in q]
    assert "SET c.revision=c.revision+1" in queries[0][0]
    assert "operation_id" in queries[1][0]
    assert "count" in queries[2][0]
    assert all(p["deployment_id"] == "d" and p["workspace_id"] == "w" for _, p in queries)
    d = Driver([[{"floor": 0, "ceiling": 1}], [{"run": row}]])
    replay = store(d).admit("op", row["request_json"], '{"accepted":2}', 0)
    assert replay == result
    assert not any("count(" in q or "CREATE (r" in q for q, _ in d.calls)


def test_conflict_and_capacity_and_missing_scope():
    row = run_row()
    d = Driver([[{"floor": 0, "ceiling": 1}], [{"run": row}]])
    with pytest.raises(api().SubmissionConflict):
        store(d).admit("op", '{"a":2}', "{}", 1)
    d = Driver([[{"floor": 0, "ceiling": 1}], [], [{"pending": 1}]])
    with pytest.raises(api().CapacityExceeded):
        store(d).admit("other", "{}", "{}", 1)
    d = Driver([[]])
    with pytest.raises(api().ScopeMissing):
        store(d).admit("op", "{}", "{}", 1)
    assert not any("MERGE" in q for q, _ in d.calls)


def test_lookup_and_get_share_canonical_view_and_scope():
    row = run_row()
    d = Driver([[{"floor": 0, "ceiling": 1}], [{"run": row}], [{"floor": 0, "ceiling": 1}], [{"run": row}]])
    s = store(d, "other")
    assert s.lookup_submission("op", row["request_json"]) == s.get_run("run")
    assert all(p["workspace_id"] == "other" for q, p in d.calls if "MATCH" in q)


@pytest.mark.parametrize("raw", ['{ "a":1}', '{"a":NaN}', '{"a":1,"a":1}', "[]"])
def test_noncanonical_request_rejected_without_io(raw):
    d = Driver()
    with pytest.raises(ValueError):
        store(d).admit("op", raw, "{}", 1)
    assert not d.calls


@pytest.mark.parametrize("source", [{}, {"source_id": None}, {"source_id": "retained:Decision-01"}])
def test_event_page_preserves_source_identity_and_frozen_legacy_default(source):
    event = dict(sequence=1, run_id="run", operation_id="op", kind="WorkflowRequested", schema_version=1)
    d = Driver([[{"floor": 0, "ceiling": 1}], [{"event": dict(event, **source)}]])
    retained = store(d).events_after(0).events[0]
    assert hasattr(retained, "source_id"), "event source must be explicit, including unavailable legacy sources"
    assert retained.source_id == source.get("source_id")
    assert retained.schema_version == 1
    with pytest.raises(FrozenInstanceError):
        retained.source_id = "replacement"
    legacy = api().WorkflowEvent(1, "run", "op", "WorkflowRequested", 1)
    assert legacy.source_id is None


def test_snapshot_and_event_page_hold_control_lock_and_bounds():
    row = run_row()
    event = dict(sequence=1, run_id="run", operation_id="op", kind="WorkflowRequested", schema_version=1)
    d = Driver([[{"floor": 0, "ceiling": 1}], [{"run": row}], [{"floor": 0, "ceiling": 1}], [{"event": event}]])
    s = store(d)
    snap = s.snapshot()
    assert snap.cursor == 1 and snap.floor == 0 and snap.runs[0].run_id == "run"
    page = s.events_after(0, limit=1)
    assert page.ceiling == 1 and page.cursor == 1 and page.events[0].sequence == 1
    queries = [(q, p) for q, p in d.calls if "MATCH" in q]
    assert "SET c.revision=c.revision+1" in queries[0][0]
    assert "SET c.revision=c.revision+1" in queries[2][0]
    assert "ORDER BY e.sequence" in queries[3][0] and "LIMIT $limit" in queries[3][0]
    assert queries[3][1]["ceiling"] == 1


@pytest.mark.parametrize("cursor", [-1, 1, 4])
def test_cursor_below_floor_or_above_ceiling_is_rejected(cursor):
    d = Driver([[{"floor": 2, "ceiling": 3}]])
    with pytest.raises(api().ReplayGap):
        store(d).events_after(cursor)
    assert not any("ArenaWorkflowEvent" in q for q, _ in d.calls)


@pytest.mark.parametrize("limit", [0, 1001, True])
def test_page_bound_is_enforced_before_io(limit):
    d = Driver()
    with pytest.raises(ValueError):
        store(d).events_after(0, limit)
    assert not d.calls


def test_lock_uses_constant_write_before_dependent_increment():
    d = Driver([[{"floor": 0, "ceiling": 0}], []])
    store(d).snapshot()
    query = next(q for q, _ in d.calls if "MATCH" in q)
    assert query.index("SET c.lock_anchor=true") < query.index("SET c.revision=c.revision+1")


@pytest.mark.parametrize("field", ["database", "deployment_id", "workspace_id"])
def test_empty_scope_identifiers_rejected_without_io(field):
    d = Driver()
    values = dict(database="db", deployment_id="d", workspace_id="w")
    values[field] = ""
    with pytest.raises(ValueError):
        api().Neo4jWorkflowStore(d, **values)
    assert not d.calls


@pytest.mark.parametrize("operation", ["", None, 1, True, [], "a" * 129, "a/b", " a", "a\n", "é", "-a"])
@pytest.mark.parametrize("method", ["lookup_submission", "admit"])
def test_invalid_operation_rejected_without_io(operation, method):
    d = Driver()
    with pytest.raises(ValueError):
        if method == "admit":
            store(d).admit(operation, "{}", "{}", 1)
        else:
            store(d).lookup_submission(operation, "{}")
    assert not d.calls


@pytest.mark.parametrize("kind", ["candidate", "decision", "assessment", "evidence"])
def test_exact_scene_reads_are_scoped_bounded_and_do_not_write(kind):
    d = Driver([[]])
    assert getattr(store(d), "get_scene_" + kind)("a" * 64) is None
    queries = [(q, p) for q, p in d.calls if q.startswith("MATCH")]
    assert len(queries) == 1
    query, params = queries[0]
    assert query.endswith("LIMIT 2") and "2097152" in query
    assert params == dict(deployment_id="d", workspace_id="w", id="a" * 64)
    assert not any(word in query.split() for word in ("SET", "CREATE", "MERGE", "DELETE"))
    assert d.calls[-2:] == [("tx.close", {}), ("session.close", {})]
    d = Driver([[{}, {}]])
    with pytest.raises(ValueError, match="ambiguous"):
        getattr(store(d), "get_scene_" + kind)("a" * 64)


@pytest.mark.parametrize("kind", ["candidate", "decision", "assessment", "evidence"])
@pytest.mark.parametrize("identity", [None, "", " a", "a/b", "a" * 129])
def test_invalid_historical_identity_never_reaches_store(kind, identity):
    d = Driver()
    with pytest.raises(ValueError):
        getattr(store(d), "get_scene_" + kind)(identity)
    assert not d.calls


@pytest.mark.parametrize("kind", ["candidate", "decision"])
def test_historical_payload_size_guard_rejects_before_parsing(kind):
    from isaaclab_arena.agentic_environment_generation.workflow.queries import (
        HISTORICAL_CANDIDATE_BYTES,
        CorruptSceneRecord,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import CandidateRecord, SceneDecision

    limit = HISTORICAL_CANDIDATE_BYTES if kind == "candidate" else 2 * 1024 * 1024
    model = CandidateRecord if kind == "candidate" else SceneDecision
    # Byte checking is not just the database's character-count CASE guard.
    with pytest.raises(CorruptSceneRecord, match="excessive"):
        api().Neo4jWorkflowStore._historical_payload({"node": {"payload": "é" * (limit // 2 + 1)}}, model)


def api():
    try:
        from isaaclab_arena.agentic_environment_generation.workflow import neo4j_store

        return neo4j_store
    except ModuleNotFoundError:
        pytest.fail("Neo4j workflow store is not implemented")


class Driver:
    def __init__(self, replies=(), fail=None):
        self.replies = list(replies)
        self.calls = []
        self.fail = fail

    def session(self, **kwargs):
        self.calls.append(("session", kwargs))
        return Session(self)


class Session:
    def __init__(self, driver):
        self.d = driver

    def begin_transaction(self, **kwargs):
        self.d.calls.append(("begin", kwargs))
        return Transaction(self.d)

    def close(self):
        self.d.calls.append(("session.close", {}))
        if self.d.fail == "session.close":
            raise RuntimeError("session close failed")


class Transaction:
    def __init__(self, driver):
        self.d = driver

    def run(self, query, **params):
        self.d.calls.append((query, params))
        assert self.d.replies, query
        return self.d.replies.pop(0)

    def commit(self):
        self.d.calls.append(("commit", {}))
        if self.d.fail == "commit":
            raise RuntimeError("commit unknown")

    def close(self):
        self.d.calls.append(("tx.close", {}))
        if self.d.fail == "tx.close":
            raise RuntimeError("transaction close failed")


def store(driver, workspace="w"):
    return api().Neo4jWorkflowStore(driver, database="explicit-db", deployment_id="d", workspace_id=workspace)


@pytest.mark.parametrize("fetch_size", [None, 1])
@pytest.mark.parametrize("failure", [None, "commit", "tx.close", "session.close", "body"])
def test_transaction_fetch_size_opt_in_preserves_lifecycle(fetch_size, failure):
    d = Driver(fail=failure)
    s = store(d)

    def execute():
        options = {} if fetch_size is None else {"fetch_size": fetch_size}
        with s._transaction(**options):
            if failure == "body":
                raise RuntimeError("query failed")

    if failure is None:
        execute()
    else:
        with pytest.raises(RuntimeError if failure == "body" else api().OutcomeUnknown):
            execute()
    assert d.calls[:2] == [
        ("session", dict(database="explicit-db", **({} if fetch_size is None else {"fetch_size": 1}))),
        ("begin", {"timeout": 5}),
    ]
    assert d.calls[-2:] == [("tx.close", {}), ("session.close", {})]
    assert ("commit", {}) in d.calls if failure != "body" else ("commit", {}) not in d.calls


def test_constructor_is_driver_free_and_schema_is_explicit():
    d = Driver()
    s = store(d)
    assert not d.calls
    ddl = s.schema_requirements()
    assert len(ddl) == 21
    assert "ON (n.deployment_id, n.workspace_id, n.run_id, n.decision_id)" in ddl[-4]
    assert "ON (n.deployment_id, n.workspace_id, n.run_id, n.record_id)" in ddl[-3]
    assert "ON (n.deployment_id, n.workspace_id)" in ddl[-2]
    assert "ON (n.deployment_id, n.workspace_id, n.run_id, n.kind, n.sequence)" in ddl[-1]
    assert "IS UNIQUE" not in ddl[-1]
    assert all("CREATE CONSTRAINT" in item for item in ddl[:8])
    assert all("CREATE INDEX" in item and "UNIQUE" not in item for item in ddl[8:])
    assert not d.calls


@pytest.mark.parametrize("failure", [OSError, TimeoutError])
@pytest.mark.parametrize("phase", ["session", "begin_transaction", "run"])
def test_initial_lookup_transport_failure_is_store_unavailable(monkeypatch, failure, phase):
    target = {"session": Driver, "begin_transaction": Session, "run": Transaction}[phase]

    def fail(*args, **kwargs):
        raise failure("private transport detail")

    monkeypatch.setattr(target, phase, fail)
    with pytest.raises(api().StoreUnavailable, match="^workflow store unavailable$"):
        store(Driver()).lookup_submission("op", "{}")


@pytest.mark.parametrize("failure", ["commit", "tx.close", "session.close"])
def test_lookup_unknown_outcomes_are_not_outages(failure):
    d = Driver([[{"floor": 0, "ceiling": 0}], []], fail=failure)
    with pytest.raises(api().OutcomeUnknown):
        store(d).lookup_submission("op", "{}")


@pytest.mark.parametrize("failure", [ValueError, TypeError, RuntimeError])
def test_lookup_programming_errors_propagate(monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure("programming error")

    monkeypatch.setattr(Transaction, "run", fail)
    with pytest.raises(failure, match="programming error"):
        store(Driver()).lookup_submission("op", "{}")


def test_conflict_read_is_not_an_outage():
    d = Driver([[{"floor": 0, "ceiling": 1}], [{"run": run_row()}]])
    with pytest.raises(api().SubmissionConflict):
        store(d).lookup_submission("op", '{"a":2}')


@pytest.mark.parametrize("name", ["ServiceUnavailable", "SessionExpired"])
def test_real_optional_driver_transport_errors_are_classified(monkeypatch, name):
    import importlib

    try:
        exceptions = importlib.import_module("neo4j.exceptions")
    except ModuleNotFoundError as exc:
        assert exc.name == "neo4j"
        assert api()._lookup_transport_errors() == (OSError,)
        return

    def fail(*args, **kwargs):
        raise getattr(exceptions, name)("private detail")

    monkeypatch.setattr(Driver, "session", fail)
    with pytest.raises(api().StoreUnavailable):
        store(Driver()).lookup_submission("op", "{}")


@pytest.mark.parametrize("phase", ["commit", "transaction_close", "session_close"])
def test_lookup_transport_errors_during_commit_or_cleanup_remain_unknown(monkeypatch, phase):
    target, method = {
        "commit": (Transaction, "commit"),
        "transaction_close": (Transaction, "close"),
        "session_close": (Session, "close"),
    }[phase]

    def fail(*args, **kwargs):
        raise OSError("private transport detail")

    monkeypatch.setattr(target, method, fail)
    d = Driver([[{"floor": 0, "ceiling": 0}], []])
    with pytest.raises(api().OutcomeUnknown):
        store(d).lookup_submission("op", "{}")


@pytest.mark.parametrize("operation", ["a", "A0_.:-z", "A" * 128])
def test_valid_operation_ids_reach_lookup_unchanged(operation):
    d = Driver([[{"floor": 0, "ceiling": 0}], []])
    assert store(d).lookup_submission(operation, "{}") is None
    assert [p["identity"] for _, p in d.calls if "identity" in p] == [operation]


def test_paging_cursor_canonical_fullwidth_and_query_binding():
    import importlib.util

    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

    assert importlib.util.find_spec(
        "isaaclab_arena.agentic_environment_generation.workflow.paging"
    ), "cursor codec missing"
    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        CursorBindingMismatch,
        CursorQueryMismatch,
        EventPosition,
        RunPosition,
        decode_cursor,
        encode_cursor,
    )

    binding = ScopeBinding.model_validate(scope_binding_body())
    position = EventPosition(position=str(2**63 - 1), floor="0", ceiling=str(2**63 - 1))
    token = encode_cursor(binding, position)
    assert "=" not in token and len(token) <= 4096
    assert decode_cursor(token, binding, EventPosition) == position
    assert EventPosition.model_validate_json(position.model_dump_json()) == position
    assert type(position.model_dump(mode="json")["position"]) is str
    with pytest.raises(CursorQueryMismatch):
        decode_cursor(token, binding, RunPosition)
    with pytest.raises(CursorBindingMismatch):
        decode_cursor(token, binding.model_copy(update={"authority_id": "another-authority"}), EventPosition)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_query",
        "missing_binding",
        "extra",
        "duplicate",
        "space",
        "padding",
        "empty",
        "oversize",
        "alphabet",
        "utf8",
        "nan",
        "bool_version",
        "float_version",
        "version",
        "numeric",
        "leading_zero",
        "plus",
        "overflow",
        "negative",
        "floor",
        "ceiling",
    ],
)
def test_page_cursor_rejects_noncanonical_and_malformed_values(damage):
    import base64
    import json

    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        CursorVersionMismatch,
        EventPosition,
        MalformedCursor,
        decode_cursor,
        encode_cursor,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

    binding = ScopeBinding.model_validate(scope_binding_body())
    token = encode_cursor(binding, EventPosition(position="2", floor="0", ceiling="3"))
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    body = json.loads(raw)
    if damage.startswith("missing_"):
        del body[damage.removeprefix("missing_")]
    elif damage == "extra":
        body["extra"] = "secret"
    elif damage == "bool_version":
        body["schemaVersion"] = True
    elif damage == "float_version":
        body["schemaVersion"] = 1.0
    elif damage == "version":
        body["schemaVersion"] = 2
    elif damage in ("numeric", "leading_zero", "plus", "overflow", "negative"):
        body["position"] = {
            "numeric": 2,
            "leading_zero": "02",
            "plus": "+2",
            "overflow": str(2**63),
            "negative": "-1",
        }[damage]
    elif damage == "floor":
        body["floor"] = "3"
    elif damage == "ceiling":
        body["ceiling"] = "1"
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    if damage == "duplicate":
        raw = raw[:-1] + b',"position":"2"}'
    elif damage == "space":
        raw = b" " + raw
    elif damage == "utf8":
        raw = b"\xff"
    elif damage == "nan":
        raw = raw.replace(b'"2"', b"NaN")
    token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    if damage == "padding":
        token += "="
    elif damage == "empty":
        token = ""
    elif damage == "oversize":
        token = "x" * 4097
    elif damage == "alphabet":
        token = "%%%"
    with pytest.raises(CursorVersionMismatch if damage == "version" else MalformedCursor):
        decode_cursor(token, binding, EventPosition)


@pytest.mark.parametrize(
    "field", ["authority_id", "database", "deployment_id", "workspace_id", "store_id", "registry_id"]
)
def test_page_cursor_binds_full_operational_identity(field):
    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        CursorBindingMismatch,
        RunPosition,
        decode_cursor,
        encode_cursor,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

    binding = ScopeBinding.model_validate(scope_binding_body())
    token = encode_cursor(binding, RunPosition(position="a" * 64))
    with pytest.raises(CursorBindingMismatch):
        decode_cursor(token, binding.model_copy(update={field: "different"}), RunPosition)


@pytest.mark.parametrize("method", ["list_runs_window", "read_scope_events_window"])
@pytest.mark.parametrize("index_state", ["POPULATING", "FAILED"])
def test_page_offline_index_is_not_an_empty_result_or_lazy_ddl(method, index_state):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore, SchemaMissing
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

    binding = ScopeBinding.model_validate(scope_binding_body())
    replies = [
        [dict(floor=0, ceiling=0)],
        [dict(body=binding.body_json, digest=binding.body_sha256, present=True)],
        [
            dict(
                entityType="NODE",
                type="RANGE",
                state=index_state,
                labelsOrTypes=["ArenaWorkflowRun"],
                properties=["deployment_id", "workspace_id", "run_id"],
                owningConstraint="run",
            )
        ],
    ]
    d = Driver(replies)
    s = Neo4jWorkflowStore(
        d, database=binding.database, deployment_id=binding.deployment_id, workspace_id=binding.workspace_id
    )
    with pytest.raises(SchemaMissing):
        getattr(s, method)(binding)
    queries = [q for q, _ in d.calls]
    assert not any("CREATE " in q or "MERGE " in q or "CALL " in q for q in queries)
    assert not d.replies


def test_candidate_cursor_has_a_fixed_parent_bound_query_family():
    from isaaclab_arena.agentic_environment_generation.workflow import paging
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
        ScopeBinding,
    )

    assert hasattr(paging, "CandidatePosition"), "run-owned candidate cursor missing"
    binding = ScopeBinding.model_validate(scope_binding_body())
    position = paging.CandidatePosition(run_id="a" * 64, position="b" * 64)
    token = paging.encode_cursor(binding, position)
    assert paging.decode_cursor(token, binding, paging.CandidatePosition) == position
    assert len(token) <= 4096
    with pytest.raises(paging.CursorQueryMismatch):
        paging.decode_cursor(token, binding, paging.RunPosition)
    with pytest.raises(paging.CursorBindingMismatch):
        paging.decode_cursor(
            token,
            binding.model_copy(update={"authority_id": "other"}),
            paging.CandidatePosition,
        )
    with pytest.raises(ValueError):
        paging.CandidatePosition(run_id=True, position="b" * 64)


@pytest.mark.parametrize("damage", ["missing", "offline", "unique", "wrong_scope"])
def test_candidate_parent_index_is_online_nonunique_and_admin_only(damage):
    rows = history_index_rows()
    row = next(
        r
        for r in rows
        if r["properties"] == ["deployment_id", "workspace_id", "run_id", "record_id"]
    )
    if damage == "missing":
        rows.remove(row)
    else:
        key, value = {
            "offline": ("state", "POPULATING"),
            "unique": ("owningConstraint", "bad"),
            "wrong_scope": ("properties", ["run_id", "record_id"]),
        }[damage]
        row[key] = value
    d = Driver([schema_rows(), rows])
    with pytest.raises(api().SchemaMissing):
        store(d).verify_schema()
    assert not any("CREATE" in q or "awaitIndexes" in q for q, _ in d.calls)


@pytest.mark.parametrize("keys", [("record_id",), ("run_id", "record_id")])
@pytest.mark.parametrize("damage", ["missing", "offline", "unique", "type"])
def test_candidate_runtime_gate_checks_both_online_nonunique_indexes(keys, damage):
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
        ScopeBinding,
    )

    binding = ScopeBinding.model_validate(scope_binding_body())
    indexes = history_index_rows() + [
        dict(r, type="RANGE", state="ONLINE", owningConstraint="unique")
        for r in schema_rows()
    ]
    target = next(
        r
        for r in indexes
        if r["labelsOrTypes"] == ["ArenaWorkflowCandidate"]
        and r["properties"] == ["deployment_id", "workspace_id", *keys]
    )
    if damage == "missing":
        indexes.remove(target)
    else:
        key, value = {
            "offline": ("state", "POPULATING"),
            "unique": ("owningConstraint", "unexpected"),
            "type": ("type", "TEXT"),
        }[damage]
        target[key] = value
    d = Driver(
        [
            [dict(floor=0, ceiling=0)],
            [dict(body=binding.body_json, digest=binding.body_sha256, present=True)],
            indexes,
        ]
    )
    s = api().Neo4jWorkflowStore(
        d,
        database=binding.database,
        deployment_id=binding.deployment_id,
        workspace_id=binding.workspace_id,
    )
    with pytest.raises(api().SchemaMissing):
        s.list_scene_candidates_window(binding, "a" * 64)
    assert not any("CREATE" in q or "CALL " in q for q, _ in d.calls)
    assert not d.replies


def test_candidate_store_parent_cursor_mismatch_precedes_transaction():
    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        CandidatePosition,
        CursorQueryMismatch,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
        ScopeBinding,
    )

    binding = ScopeBinding.model_validate(scope_binding_body())
    d = Driver([])
    s = api().Neo4jWorkflowStore(
        d,
        database=binding.database,
        deployment_id=binding.deployment_id,
        workspace_id=binding.workspace_id,
    )
    with pytest.raises(CursorQueryMismatch):
        s.list_scene_candidates_window(
            binding,
            "a" * 64,
            after=CandidatePosition(run_id="b" * 64, position="c" * 64),
        )
    assert not d.calls


def test_decision_cursor_binds_parent_and_preserves_general_identifier():
    from isaaclab_arena.agentic_environment_generation.workflow import paging
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

    assert hasattr(paging, "DecisionPosition"), "run-qualified decision cursor missing"
    binding = ScopeBinding.model_validate(scope_binding_body())
    value = paging.DecisionPosition(run_id="a" * 64, position="foreground-initial-generation")
    token = paging.encode_cursor(binding, value)
    assert paging.decode_cursor(token, binding, paging.DecisionPosition) == value
    with pytest.raises(paging.CursorQueryMismatch):
        paging.decode_cursor(token, binding, paging.CandidatePosition)
    with pytest.raises(paging.CursorBindingMismatch):
        paging.decode_cursor(token, binding.model_copy(update={"authority_id": "other"}), paging.DecisionPosition)
    for changes in ({"run_id": True}, {"position": True}, {"position": "bad key"}, {"position": "a" * 129}):
        with pytest.raises(ValueError):
            paging.DecisionPosition.model_validate({**value.model_dump(), **changes})
    with pytest.raises(ValueError):
        value.position = "changed"


@pytest.mark.parametrize("damage", ["missing", "offline", "unique", "wrong_scope"])
def test_decision_parent_index_is_online_nonunique_and_admin_only(damage):
    rows = history_index_rows()
    row = next(r for r in rows if r["properties"] == ["deployment_id", "workspace_id", "run_id", "decision_id"])
    if damage == "missing":
        rows.remove(row)
    else:
        key, value = {
            "offline": ("state", "POPULATING"),
            "unique": ("owningConstraint", "bad"),
            "wrong_scope": ("properties", ["run_id", "decision_id"]),
        }[damage]
        row[key] = value
    d = Driver([schema_rows(), rows])
    with pytest.raises(api().SchemaMissing):
        store(d).verify_schema()
    assert not any("CREATE" in q or "awaitIndexes" in q for q, _ in d.calls)


@pytest.mark.parametrize("keys", [("run_id", "decision_id")])
@pytest.mark.parametrize("damage", ["missing", "offline", "unique", "type"])
def test_decision_runtime_gate_checks_both_online_nonunique_indexes(keys, damage):
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
        ScopeBinding,
    )

    binding = ScopeBinding.model_validate(scope_binding_body())
    indexes = history_index_rows() + [
        dict(r, type="RANGE", state="ONLINE", owningConstraint="unique") for r in schema_rows()
    ]
    target = next(
        r
        for r in indexes
        if r["labelsOrTypes"] == ["ArenaWorkflowDecision"]
        and r["properties"] == ["deployment_id", "workspace_id", *keys]
    )
    if damage == "missing":
        indexes.remove(target)
    else:
        key, value = {
            "offline": ("state", "POPULATING"),
            "unique": ("owningConstraint", "unexpected"),
            "type": ("type", "TEXT"),
        }[damage]
        target[key] = value
    d = Driver(
        [
            [dict(floor=0, ceiling=0)],
            [dict(body=binding.body_json, digest=binding.body_sha256, present=True)],
            indexes,
        ]
    )
    s = api().Neo4jWorkflowStore(
        d,
        database=binding.database,
        deployment_id=binding.deployment_id,
        workspace_id=binding.workspace_id,
    )
    with pytest.raises(api().SchemaMissing):
        s.list_decisions_window(binding, "a" * 64)
    assert not any("CREATE" in q or "CALL " in q for q, _ in d.calls)
    assert not d.replies


def test_decision_store_parent_cursor_mismatch_precedes_transaction():
    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        DecisionPosition,
        CursorQueryMismatch,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
        ScopeBinding,
    )

    binding = ScopeBinding.model_validate(scope_binding_body())
    d = Driver([])
    s = api().Neo4jWorkflowStore(
        d,
        database=binding.database,
        deployment_id=binding.deployment_id,
        workspace_id=binding.workspace_id,
    )
    with pytest.raises(CursorQueryMismatch):
        s.list_decisions_window(
            binding,
            "a" * 64,
            after=DecisionPosition(run_id="b" * 64, position="c" * 64),
        )
    assert not d.calls
