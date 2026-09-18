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
