# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure workflow requests; run only through the offline backend harness."""
import json
import sys

import pytest


def request():
    profile = {"profile_id": "offline", "settings_sha256": "a" * 64}
    return {
        "schema_version": "1",
        "source": {"kind": "new", "prompt": "Create a tabletop scene"},
        "criteria": [{
            "criterion_id": "layout",
            "kind": "structural",
            "evidence_producer": "graph-check-v1",
            "requirement": "required",
            "evaluator_version": "1",
            "required_modalities": ["scene_graph"],
            "coordinate_frames": ["world"],
            "observation_window": {"start_step": 0, "end_step": 0},
            "rubric": "Objects must be present",
            "subjects": ["table"],
            "limit": {"operator": "ge", "value": 1.0, "unit": "count"},
        }],
        "preserved": [
            {"subject_id": "table", "schema_path": "/objects/0/id", "mode": "frozen", "description": "table identity"}
        ],
        "allowed_interventions": [{
            "subject_id": "prop",
            "schema_path": "/relations/0/params/x",
            "operation": "replace",
            "coordinate_frame": "world",
            "units": "m",
            "max_total_displacement_m": 0.2,
            "description": "move props",
        }],
        "execution": {
            "generation_model": {**profile, "billing": "free"},
            "assessment_model": {**profile, "billing": "free"},
            "runtime": profile,
            "database": profile,
            "policy": None,
            "capture": profile,
            "seed": 42,
            "timestep_seconds": 0.01,
            "decimation": 2,
            "dcrg": None,
        },
        "budget": {
            "max_candidates": 2,
            "max_revisions": 1,
            "max_runtime_seconds": 60.0,
            "max_model_calls": 0,
            "max_model_tokens": 0,
            "max_cost_usd": 0.0,
            "max_realizations": 0,
            "max_steps": 0,
            "max_observations": 0,
            "max_policy_episodes": 0,
            "max_policy_steps": 0,
            "per_operation_timeout_seconds": 10.0,
            "total_deadline_seconds": 60.0,
        },
        "effects": {
            "allow_paid_models": False,
            "allow_runtime": False,
            "allow_database_reads": False,
            "allow_publication": False,
        },
    }


def api():
    try:
        import isaaclab_arena.agentic_environment_generation.workflow as workflow

        return workflow
    except ModuleNotFoundError:
        pytest.fail("pure workflow contract API is not implemented")


def test_prompt_only_new_has_immutable_canonical_replay():
    w = api()
    raw = request()
    contract = w.parse_contract(json.dumps(raw))
    assert isinstance(contract, w.WorkflowContract)
    assert contract.source.kind == "new"
    assert contract.source.prompt == raw["source"]["prompt"]
    assert isinstance(contract.criteria, tuple)
    assert isinstance(contract.criteria[0].subjects, tuple)
    assert w.parse_contract(w.canonical_json(contract)) == contract
    assert w.contract_digest(contract) == w.contract_digest(w.parse_contract(json.dumps(raw, sort_keys=True)))
    assert len(w.contract_digest(contract)) == 64
    for obj, field, value in [
        (contract, "schema_version", "2"),
        (contract.criteria[0], "rubric", "changed"),
        (contract.execution.generation_model, "billing", "paid"),
        (contract.allowed_interventions[0], "max_total_displacement_m", 2.0),
        (contract.criteria[0].observation_window, "end_step", 5),
        (contract.budget, "max_candidates", 99),
    ]:
        with pytest.raises((ValueError, TypeError)):
            setattr(obj, field, value)
    raw["criteria"][0]["subjects"].append("chair")
    assert contract.criteria[0].subjects == ("table",)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(criteria=[]),
        lambda r: r["criteria"].append(r["criteria"][0].copy()),
        lambda r: r["criteria"][0].update(kind="policy"),
        lambda r: r["criteria"][0].update(requires_policy=True),
        lambda r: r["budget"].update(max_candidates=True),
        lambda r: r["budget"].update(max_runtime_seconds=True),
        lambda r: r["budget"].update(max_cost_usd=float("inf")),
        lambda r: r["criteria"][0]["limit"].update(value=float("nan")),
        lambda r: r["criteria"][0]["limit"].update(value=True),
        lambda r: r["execution"]["generation_model"].update(billing="paid"),
        lambda r: r["execution"]["assessment_model"].update(billing="paid"),
        lambda r: r["execution"].pop("generation_model"),
        lambda r: r["execution"]["generation_model"].update(api_key="secret"),
        lambda r: r["criteria"][0]["observation_window"].update(start_step=2),
        lambda r: r["criteria"][0].update(required_modalities=[]),
        lambda r: r["criteria"][0].update(coordinate_frames=[]),
        lambda r: r["execution"].update(timestep_seconds=True),
        lambda r: r["execution"].update(decimation=0),
        lambda r: r["execution"].update(seed=True),
        lambda r: r["effects"].update(allow_dcrg=True),
        lambda r: r["execution"].update(dcrg={"profile_id": "dcrg", "settings_sha256": "a" * 64}),
        lambda r: r["budget"].update(total_deadline_seconds=1.0),
        lambda r: r["allowed_interventions"][0].update(schema_path="/objects/*"),
        lambda r: r["allowed_interventions"][0].update(operation="add"),
        lambda r: r["allowed_interventions"][0].update(max_total_displacement_m=True),
        lambda r: r["allowed_interventions"][0].update(max_total_displacement_m=-1),
        lambda r: r["preserved"][0].update(mode="approximate"),
        lambda r: r.update(created_at="today"),
        lambda r: r["effects"].update(allow_publication=True),
        lambda r: r["source"].update(prompt=" "),
        lambda r: r.update(schema_version="2"),
    ],
)
def test_invalid_requests_are_rejected(mutation):
    raw = request()
    mutation(raw)
    with pytest.raises(ValueError):
        api().WorkflowContract.model_validate(raw)


@pytest.mark.parametrize(
    "raw",
    [
        '{"schema_version":"1","schema_version":"1"}',
        '{"extra":{"x":1,"x":1}}',
        '{"extra":NaN}',
        '{"extra":Infinity}',
        '{"extra":-Infinity}',
    ],
)
def test_strict_json_rejects_ambiguous_documents(raw):
    with pytest.raises(ValueError, match="duplicate|nonfinite"):
        api().parse_contract(raw)


def test_existing_source_is_opaque_and_profile_configuration_is_explicit():
    w = api()
    raw = request()
    raw["source"] = {"kind": "existing", "identity": "revision:123", "content": "not a graph spec"}
    raw["criteria"][0]["kind"] = "policy"
    raw["criteria"][0]["required_modalities"] = ["policy_rollout"]
    raw["execution"]["policy"] = {"profile_id": "policy-v1", "settings_sha256": "b" * 64}
    raw["effects"]["allow_runtime"] = True
    raw["budget"].update(
        max_realizations=1, max_steps=10, max_observations=1, max_policy_episodes=1, max_policy_steps=10
    )
    contract = w.parse_contract(json.dumps(raw))
    assert contract.source.content == "not a graph spec"
    assert w.parse_contract(w.canonical_json(contract)) == contract
    assert w.contract_digest(contract) != w.contract_digest(w.parse_contract(json.dumps(request())))


def test_effects_are_declarations_not_execution_grants():
    raw = request()
    raw["effects"]["allow_operational_writes"] = True
    contract = api().WorkflowContract.model_validate(raw)
    assert contract.effects.allow_operational_writes
    assert not contract.effects.allow_database_reads
    assert contract.effects.allow_dcrg is False


@pytest.mark.parametrize(
    "raw", [" " * 2_097_153, b" " * 2_097_153, "[" * 33 + "]" * 33], ids=["text-size", "bytes-size", "depth"]
)
def test_raw_bounds_checked_before_json_parser(raw, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow import contracts

    def forbidden(*args, **kwargs):
        pytest.fail("full JSON parser reached before preflight bounds")

    monkeypatch.setattr(contracts.json, "loads", forbidden)
    with pytest.raises(ValueError, match="size|depth"):
        contracts.parse_contract(raw)


def test_scanner_ignores_brackets_and_escaped_quotes_inside_strings():
    raw = request()
    raw["source"]["prompt"] = "Brackets " + "[" * 100 + ' escaped " slash \\ end'
    contract = api().parse_contract(json.dumps(raw).encode())
    assert contract.source.prompt == raw["source"]["prompt"]


def test_json_exponent_overflow_is_nonfinite_even_in_unknown_fields():
    with pytest.raises(ValueError, match="nonfinite"):
        api().parse_contract('{"unknown":1e9999}')


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r["execution"].update(policy=r["execution"]["runtime"]),
        lambda r: r["budget"].update(max_policy_steps=1),
        lambda r: r["criteria"][0].update(required_modalities=["policy_rollout"]),
        lambda r: r["criteria"][0]["observation_window"].update(end_step=1),
        lambda r: r["effects"].update(allow_publication=0),
        lambda r: r["allowed_interventions"][0].update(schema_path="/objects/0/id"),
        lambda r: r["allowed_interventions"][0].update(schema_path="/objects/0"),
    ],
)
def test_incoherent_semantics_are_rejected(mutation):
    raw = request()
    mutation(raw)
    with pytest.raises(ValueError):
        api().WorkflowContract.model_validate(raw)


@pytest.mark.parametrize(
    "field", ["generation_model", "assessment_model", "capture", "seed", "timestep_seconds", "decimation", "dcrg"]
)
def test_execution_semantics_must_be_explicit(field):
    raw = request()
    raw["execution"].pop(field)
    with pytest.raises(ValueError):
        api().WorkflowContract.model_validate(raw)


@pytest.mark.parametrize("field", ["prompt", "rubric", "content"])
@pytest.mark.parametrize("text", ["\ud800", "\udfff"])
def test_lone_surrogates_rejected_before_acceptance(field, text):
    raw = request()
    if field == "content":
        raw["source"] = {"kind": "existing", "identity": "original", "content": text}
    elif field == "rubric":
        raw["criteria"][0][field] = text
    else:
        raw["source"][field] = text
    w = api()
    with pytest.raises(ValueError):
        w.parse_contract(json.dumps(raw))
    with pytest.raises(ValueError):
        w.WorkflowContract.model_validate(raw)


@pytest.mark.parametrize("field", ["prompt", "rubric", "content"])
def test_unicode_canonical_utf8_replay(field):
    import hashlib

    raw = request()
    text = "Café 桌子 \U0001f600"
    if field == "content":
        raw["source"] = {"kind": "existing", "identity": "original", "content": text}
    elif field == "rubric":
        raw["criteria"][0][field] = text
    else:
        raw["source"][field] = text
    w = api()
    escaped = json.dumps(raw)
    assert "\\ud83d\\ude00" in escaped
    contract = w.parse_contract(escaped)
    encoded = w.canonical_json(contract).encode("utf-8")
    assert text.encode("utf-8") in encoded
    assert w.parse_contract(encoded) == contract
    assert w.contract_digest(contract) == hashlib.sha256(encoded).hexdigest()
    assert w.contract_digest(w.WorkflowContract.model_validate(raw)) == w.contract_digest(contract)


@pytest.mark.parametrize("expansion", ["defaults", "numbers"])
def test_canonical_expansion_respects_replay_byte_ceiling(monkeypatch, expansion):
    from isaaclab_arena.agentic_environment_generation.workflow import contracts

    raw = request()
    raw["source"] = {"kind": "existing", "identity": "original", "content": "é" * 4096}
    if expansion == "numbers":
        raw["effects"].update(allow_dcrg=False, allow_operational_writes=False)
        raw["criteria"][0]["limit"]["value"] = 1
        raw["budget"]["max_runtime_seconds"] = 60
    direct = contracts.WorkflowContract.model_validate(raw)
    canonical = contracts.canonical_json(direct)
    compact = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    compact_size = len(compact.encode("utf-8"))
    canonical_size = len(canonical.encode("utf-8"))
    assert compact_size < canonical_size
    monkeypatch.setattr(contracts, "MAX_CONTRACT_BYTES", canonical_size)
    parsed = contracts.parse_contract(compact)
    assert contracts.parse_contract(contracts.canonical_json(parsed)) == parsed
    monkeypatch.setattr(contracts, "MAX_CONTRACT_BYTES", canonical_size - 1)
    assert compact_size <= contracts.MAX_CONTRACT_BYTES
    with pytest.raises(ValueError, match="size|byte"):
        contracts.parse_contract(compact)
    with pytest.raises(ValueError, match="size|byte"):
        contracts.canonical_json(direct)
    with pytest.raises(ValueError, match="size|byte"):
        contracts.contract_digest(direct)


def test_construction_does_not_import_runtime(monkeypatch):
    import builtins

    original = builtins.__import__
    forbidden = (
        "isaaclab_arena_examples",
        "isaaclab.",
        "isaacsim",
        "omni",
        "pxr",
        "openai",
        "neo4j",
        "torch",
        "fastapi",
        "streamlit",
        "argparse",
        "isaaclab_arena.agentic_environment_generation.env_graph_spec",
    )

    def guarded(name, *args, **kwargs):
        assert not name.startswith(forbidden), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    for name in (
        "isaaclab_arena.agentic_environment_generation.workflow",
        "isaaclab_arena.agentic_environment_generation.workflow.contracts",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)
    w = api()
    before = set(sys.modules)
    w.parse_contract(json.dumps(request()))
    assert not any(name.startswith(forbidden) for name in set(sys.modules) - before)


def test_parameterized_predicate_preserves_legacy_identity_and_refusals():
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import Criterion
    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import admit_criterion

    w = api()
    legacy = w.parse_contract(json.dumps(request()))
    assert w.contract_digest(legacy) == "4b7ac7c1cfbbb3fc8a01d977721b1176a2e54044385b0c2c8eb107097e8c67dc"
    assert "parameters" not in legacy.criteria[0].model_dump(mode="json")
    raw = request()["criteria"][0] | dict(
        criterion_id="speed",
        kind="runtime",
        evidence_producer="scene.linear-speed",
        evaluator_version="numeric-v2",
        required_modalities=["state"],
        subjects=["red_block", "blue_bin"],
        observation_window=dict(start_step=176, end_step=180),
        rubric="selected velocity norm",
        limit=dict(operator="lt", value=0.001, unit="m_per_s"),
        parameters=dict(
            metric="linear_speed",
            reference_frame="world",
            clock="control_step",
            sample_steps=[176, 177, 178, 179, 180],
            temporal_aggregation="all",
            subject_aggregation="all",
            missing_data="reject",
            invalid_data="reject",
        ),
    )
    selected = admit_criterion(Criterion.model_validate(raw))
    assert selected.parameters.sample_steps == (176, 177, 178, 179, 180)
    assert selected.subjects == ("red_block", "blue_bin")
    assert selected.limit.operator == "lt"
    for operator in ("lt", "le", "eq", "ge", "gt"):
        assert admit_criterion(Criterion.model_validate(raw | {"limit": raw["limit"] | {"operator": operator}}))
    for field, value in (("clock", "physics_step"), ("reference_frame", "tool"), ("missing_data", "zero_fill")):
        with pytest.raises(ValueError):
            admit_criterion(Criterion.model_validate(raw | {"parameters": raw["parameters"] | {field: value}}))
    with pytest.raises(ValueError):
        admit_criterion(Criterion.model_validate(raw | {"limit": raw["limit"] | {"unit": "N"}}))
    with pytest.raises(ValueError):
        Criterion.model_validate(raw | {"parameters": raw["parameters"] | {"sample_steps": [176, 176, 180]}})
    old = request()
    old["criteria"][0]["limit"]["operator"] = "lt"
    with pytest.raises(ValueError):
        w.WorkflowContract.model_validate(old)
    old = request()
    old["criteria"][0]["parameters"] = None
    with pytest.raises(ValueError):
        w.WorkflowContract.model_validate(old)
    with pytest.raises(ValueError):
        Criterion.model_validate(old["criteria"][0])
    del old["criteria"][0]["parameters"]
    old["criteria"][0]["limit"]["operator"] = "lt"
    with pytest.raises(ValueError):
        Criterion.model_validate(old["criteria"][0])


def test_schema5_accounting_only_is_explicit_and_projects_distinct_windows():
    from isaaclab_arena.agentic_environment_generation.workflow.evidence_contracts import project_required_criteria
    from isaaclab_arena.tests._workflow_scene_fixture import criterion

    w = api()
    raw = request()
    raw.update(schema_version="5", preserved=[], allowed_interventions=[])
    raw["criteria"] = [
        criterion(
            criterion_id=identifier,
            evaluator_version="numeric-v2",
            rubric="selected velocity norm",
            observation_window=dict(start_step=steps[0], end_step=steps[-1]),
            limit=dict(operator="lt", value=0.001, unit="m_per_s"),
            parameters=dict(
                metric="linear_speed",
                reference_frame="world",
                clock="control_step",
                sample_steps=steps,
                temporal_aggregation="all",
                subject_aggregation="all",
                missing_data="reject",
                invalid_data="reject",
            ),
        ).model_dump(mode="json")
        for identifier, steps in (("history", [176, 177, 178, 179, 180]), ("terminal", [180]))
    ]
    raw["acquisition"] = dict(
        codec="explicit-acquisition-v1",
        adapter="droid-rigid-world-v1",
        clock="control_step",
        reference_frame="world",
        control_dt_seconds=0.02,
        horizon_steps=180,
        subjects=["cup"],
        state_steps=[176, 177, 178, 179, 180],
        images=[],
        renderer_update_steps=[],
        displacement_step=180,
    )
    raw["action_policy"] = dict(
        codec="scene-action-policy-v1",
        on_unknown="stop",
        on_false="stop",
        target_subject=None,
        mechanism=None,
        goal_criterion_id=None,
        prerequisite_criterion_ids=[],
        observation=None,
    )
    raw["budget"].update(
        max_steps=180,
        max_realizations=1,
        max_observations=1,
        max_runtime_seconds=None,
        total_deadline_seconds=None,
        max_model_tokens=None,
        max_cost_usd=None,
        policy=dict(
            codec="experiment-policy-v1",
            runtime="accounting_only",
            deadline="accounting_only",
            model_tokens="accounting_only",
            cost="accounting_only",
        ),
        control=dict(
            codec="renewable-control-v1",
            max_supervision_lease_seconds=60.0,
            heartbeat_seconds=20.0,
            max_credential_lifetime_seconds=300.0,
            client_descriptor_schema="2",
        ),
    )
    raw["effects"]["allow_runtime"] = True
    contract = w.parse_contract(json.dumps(raw))
    assert contract.budget.max_runtime_seconds is contract.budget.total_deadline_seconds is None
    assert contract.budget.experiment_limit_status("runtime", 1000000.0) == "accounted"
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.read_model import inspection_budget

    projected = inspection_budget(
        SimpleNamespace(contract=contract, submission=SimpleNamespace(admitted_at=100.0)),
        [dict(model_calls=1, model_tokens=None, cost_ceiling_usd=None, runtime_allowance_seconds=12.0)],
    )
    assert projected.deadline is None
    assert projected.reserved.runtime_allowance_seconds == 12
    assert projected.remaining.runtime_allowance_seconds is None

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []
    retained = object()
    service = WorkflowService(
        SimpleNamespace(lookup_submission=lambda *args: calls.append("lookup") or retained),
        SimpleNamespace(require_read=lambda principal: calls.append("read")),
        None,
        validate_support=lambda value: pytest.fail("replay reached mutable support"),
    )
    assert service.submit("reader", "replay", contract.model_dump_json()).run is retained
    assert calls == ["read", "lookup"]
    from isaaclab_arena.agentic_environment_generation.workflow.api.schema import frozen_intent

    public = frozen_intent(contract)
    assert public.budget.max_runtime_seconds is None
    assert public.budget.total_deadline_seconds is None
    assert public.budget.policy.runtime == "accounting_only"
    assert public.criteria[0].parameters.metric == "linear_speed"
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import SceneReservation

    allocation = SceneReservation(
        model_calls=0,
        model_tokens=0,
        cost_ceiling_usd=0.0,
        runtime_allowance_seconds=None,
        time_policy="accounting_only",
        realizations=1,
        observations=1,
        steps=180,
    )
    assert allocation.model_dump(mode="json")["runtime_allowance_seconds"] is None
    assert allocation.model_dump(mode="json")["time_policy"] == "accounting_only"
    assert projected.reserved.model_calls == 1
    assert projected.reserved.model_tokens is None
    assert projected.reserved.cost_ceiling_usd is None
    assert projected.policy.model_dump(mode="json") == contract.budget.policy.model_dump(mode="json")
    assert contract.budget.allows_time(100.0, 1000000.0, None)
    assert contract.budget.allows_time(100.0, 1000000.0, 10.0)
    assert not contract.budget.allows_time(100.0, 99.0, 10.0)
    assert contract.budget.allows_resource("cost", None)
    assert contract.budget.allows_resource("runtime", None)
    required = project_required_criteria(contract)
    assert [r.step_window for r in required] == [(176, 180), (180, 180)]
    assert [r.coverage.state_steps for r in required] == [(176, 177, 178, 179, 180), (180,)]
    assert w.parse_contract(w.canonical_json(contract)) == contract
    assert (
        w.contract_digest(w.parse_contract(json.dumps(request())))
        == "4b7ac7c1cfbbb3fc8a01d977721b1176a2e54044385b0c2c8eb107097e8c67dc"
    )
    raw["budget"]["policy"]["runtime"] = "enforced"
    with pytest.raises(ValueError):
        w.WorkflowContract.model_validate(raw)
    raw["budget"]["max_runtime_seconds"] = 10.0
    raw["budget"]["policy"]["runtime"] = "advisory"
    advisory = w.WorkflowContract.model_validate(raw)
    assert advisory.budget.experiment_limit_status("runtime", 20.0) == "advisory_exceeded"
    raw["budget"]["policy"]["runtime"] = "enforced"
    assert w.WorkflowContract.model_validate(raw).budget.experiment_limit_status("runtime", 20.0) == "enforced_exceeded"
    raw["schema_version"] = "1"
    with pytest.raises(ValueError):
        w.WorkflowContract.model_validate(raw)


def test_finite_control_refresh_does_not_renew_workload_or_slide_lease():
    from dataclasses import replace

    from isaaclab_arena.agentic_environment_generation.workflow import control_protocol as control
    from isaaclab_arena.agentic_environment_generation.workflow.api.security import AuthContext
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, AuthorizationSnapshot
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import ControlPolicy
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

    scope = ScopeBinding(
        schema_version=1,
        authority_id="authority",
        operational_schema_version=1,
        artifact_marker_schema=1,
        store_id="store",
        registry_id="registry",
        database="db",
        deployment_id="deployment",
        workspace_id="workspace",
    )
    policy = ControlPolicy(
        codec="renewable-control-v1",
        max_supervision_lease_seconds=60.0,
        heartbeat_seconds=20.0,
        max_credential_lifetime_seconds=300.0,
        client_descriptor_schema="2",
    )
    old = control.PrincipalDescriptor(
        schema_version=2,
        binding=scope,
        instance="instance",
        generation=1,
        credential_revision=1,
        principal="operator",
        context_handle="old-context",
        issued_at=0.0,
        expires_at=100.0,
    )
    current = AuthContext("operator", scope, "instance", 2, 201.0, "current-context")
    fresh = control.PrincipalDescriptor.model_validate(
        old.model_dump(mode="python")
        | dict(
            generation=2,
            credential_revision=2,
            context_handle=current.handle,
            issued_at=101.0,
            expires_at=201.0,
        )
    )

    def recheck(context):
        if context is not current:
            raise PermissionError("expired or revoked context")

    auth = AuthorizationSnapshot(
        database="db",
        deployment_id="deployment",
        workspace_id="workspace",
        principal="operator",
        grant_ref="grant",
        contract_digest="a" * 64,
        expires_at=150.0,
        capabilities=("native_validation",),
    )
    args = dict(policy=policy, now=101.0, recheck=recheck, generation=2, contract_digest="a" * 64)
    assert control.resolve_current_principal(old, fresh, current, action="read", **args) is current
    assert control.resolve_current_principal(old, fresh, current, action="cancel", **args) is current
    with pytest.raises(PermissionError):
        control.resolve_current_principal(old, fresh, current, action="continue", **args)
    assert (
        control.resolve_current_principal(
            old, fresh, current, action="continue", authority=auth, capability="native_validation", **args
        )
        is current
    )
    with pytest.raises(PermissionError):
        control.resolve_current_principal(old, fresh, replace(current, handle="revoked"), action="read", **args)
    with pytest.raises(PermissionError):
        control.resolve_current_principal(
            old,
            fresh,
            current,
            action="continue",
            authority=auth,
            capability="native_validation",
            **(args | {"now": 151.0}),
        )
    fence = AttemptFence(
        run_id="run", intent_id="intent", attempt_id="attempt", generation=1, owner_id="owner", owner_epoch=1
    )
    lease = control.SupervisionLease(
        codec="supervision-lease-v1",
        fence=fence,
        scope_sha256=scope.body_sha256,
        instance="instance",
        principal="operator",
        contract_digest="a" * 64,
        allocation_digest="b" * 64,
        generation=1,
        credential_generation=2,
        credential_expires_at=201.0,
        issued_at=101.0,
        expires_at=111.0,
    )
    cursor = control.SupervisionCursor(
        policy=policy,
        scope=scope,
        instance="instance",
        principal="operator",
        fence=fence,
        contract_digest="a" * 64,
        allocation_digest="b" * 64,
    )
    assert cursor.check(lease, authority=auth, wall_now=101.0, monotonic_now=1001.0) == 1011.0
    assert cursor.check(lease, authority=auth, wall_now=101.0, monotonic_now=1002.0) == 1011.0
    renewed = control.SupervisionLease.model_validate(
        lease.model_dump(mode="python")
        | dict(
            generation=2,
            issued_at=102.0,
            expires_at=121.0,
        )
    )
    assert cursor.check(renewed, authority=auth, wall_now=102.0, monotonic_now=1002.0) == 1021.0
    changed = control.SupervisionLease.model_validate(
        renewed.model_dump(mode="python")
        | dict(
            allocation_digest="c" * 64,
            generation=3,
            issued_at=103.0,
            expires_at=122.0,
        )
    )
    with pytest.raises(PermissionError):
        cursor.check(changed, authority=auth, wall_now=103.0, monotonic_now=1003.0)
    with pytest.raises(TimeoutError):
        cursor.check(renewed, authority=auth, wall_now=122.0, monotonic_now=1022.0)
    clocks = [101.0, 1001.0]
    owned = control.OwnedSupervision(
        policy=policy,
        scope=scope,
        instance="instance",
        principal="operator",
        fence=fence,
        contract_digest="a" * 64,
        allocation_digest="b" * 64,
        wall_clock=lambda: clocks[0],
        monotonic_clock=lambda: clocks[1],
    )
    acknowledgement = owned.accept(lease, auth)
    clocks[1] = 1002.0
    assert owned.accept(lease, auth) == acknowledgement
    assert owned.cursor.monotonic_deadline == 1011.0
    clocks[:] = [102.0, 1002.0]
    assert owned.accept(renewed, auth)["generation"] == 2
    clocks[:] = [122.0, 1022.0]
    with pytest.raises(TimeoutError):
        owned.check_active()
    assert owned.retained_state()["last_acknowledgement"]["generation"] == 2
    with pytest.raises(TimeoutError):
        owned.accept(renewed, auth)
    for value in (None, float("inf"), True):
        with pytest.raises(ValueError):
            control.finite_backend_timeout(value, ceiling=120.0)
        with pytest.raises(ValueError):
            control.legacy_monotonic_deadline(value, wall_now=101.0, monotonic_now=1001.0)
