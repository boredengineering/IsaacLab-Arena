# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Real scene model entrypoints and SDK with synthetic HTTP; no native claims."""

import json

import pytest


def test_retained_prior_exact_readback_and_binding(tmp_path):
    from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts

    area = ArtifactArea.create(tmp_path / "priors", store_id="store", registry_id="registry")
    try:
        artifacts = RetainedPriorArtifacts(area)
        snapshot = empty_snapshot("table", status="not_requested", warning=None)
        receipt = artifacts.write("table", "a" * 64, "run1", snapshot, protect=lambda v: None)
        assert (
            artifacts.verified_snapshot(
                receipt, prompt="table", contract_digest="a" * 64, run_id="run1", protect=lambda v: None
            )
            == snapshot
        )
        with pytest.raises(ValueError, match="binding"):
            artifacts.verified_snapshot(
                receipt, prompt="different", contract_digest="a" * 64, run_id="run1", protect=lambda v: None
            )
    finally:
        area.close()


def configuration():
    from isaaclab_arena.agentic_environment_generation.inference_profiles import (
        frozen_builtin_profile,
        resolve_inference_profile,
    )

    model, endpoint = "gpt-6-astra", "https://api.openai.com/v1"
    return dict(
        api_key="synthetic-unit-key",
        model=model,
        base_url=endpoint,
        inference_profile=frozen_builtin_profile(resolve_inference_profile(model, endpoint)),
        workflow_accounting=dict(
            version=1, attested=True, model=model, endpoint=endpoint, max_tokens=10000, max_cost_usd="0"
        ),
    )


def sdk(monkeypatch, before=None, *, completion=None, status=200):
    import importlib

    import openai._base_client
    from openai import DefaultHttpxClient

    from isaaclab_arena.agentic_environment_generation.spec_wire_adapter import SpecWireAdapter
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena.tests.utils.agentic_environment_generation import minimal_spec_dict

    monkeypatch.setattr(openai._base_client, "get_platform", lambda: "Linux")
    with DefaultHttpxClient(trust_env=False) as client:
        transport_type = type(client._transport)
    httpx = importlib.import_module(transport_type.__module__.split(".")[0])
    data = ArenaEnvGraphSpec.model_validate(minimal_spec_dict()).model_dump(mode="json")
    wire = SpecWireAdapter().encode(data)
    calls = []

    def response(transport, request):
        if before:
            before()
        body = json.loads(request.content)
        calls.append(body)
        content = (json.dumps(wire) if completion is None else completion) if "response_format" in body else "pong"
        return httpx.Response(
            status,
            request=request,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}
                ],
            },
        )

    monkeypatch.setattr(transport_type, "handle_request", response)
    return calls, data


def model_tools(tmp_path, *, max_calls=6):
    import time

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import CallAllowance
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import BoundedSceneModels

    config = configuration()
    allowance = CallAllowance(
        max_calls=max_calls,
        deadline=time.monotonic() + 30,
        max_tokens=60000,
        cost_ceiling_usd="0",
        per_call_bound=config["workflow_accounting"],
    )
    roles = {role: {"model": config["model"], "endpoint": config["base_url"]} for role in ("generation", "assessment")}
    return BoundedSceneModels(config=config, approved_roles=roles, allowance=allowance), allowance


def test_generate_actual_entrypoint_retains_before_ping(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
        build_asset_catalogue,
        build_relation_catalogue,
        build_task_catalogue,
    )
    from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts

    tools, allowance = model_tools(tmp_path)
    area = ArtifactArea.create(tmp_path / "priors", store_id="store", registry_id="registry")
    artifacts = RetainedPriorArtifacts(area)
    snapshot = empty_snapshot("table", status="not_requested", warning=None)
    receipt = artifacts.write("table", "a" * 64, "run1", snapshot, protect=lambda v: None)
    reads = []
    original = artifacts.verified_snapshot

    def read(*args, **kwargs):
        result = original(*args, **kwargs)
        reads.append(result)
        return result

    monkeypatch.setattr(artifacts, "verified_snapshot", read)

    def before():
        assert reads == [snapshot]
        assert allowance.attempted_calls >= 1

    calls, data = sdk(monkeypatch, before)
    try:
        result = tools.generate(
            prompt="table",
            contract_digest="a" * 64,
            run_id="run1",
            priors=artifacts,
            prior=receipt,
            require_prior=False,
            protect=lambda v: None,
            asset_catalog=build_asset_catalogue(),
            relation_catalog=build_relation_catalogue(),
            task_catalog=build_task_catalogue(),
        )
        assert result.spec.model_dump(mode="json") == data
        assert result.warnings and result.publication == "not_published"
        assert len(calls) == allowance.attempted_calls == 2
        assert calls[1]["response_format"]["json_schema"]["name"] == "ArenaEnvGraphSpec"
    finally:
        area.close()


def test_refine_actual_method_exact_base_feedback_shared_budget(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
        build_asset_catalogue,
        build_relation_catalogue,
        build_task_catalogue,
    )
    from isaaclab_arena.agentic_environment_generation.spec_wire_adapter import SpecWireAdapter
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    tools, allowance = model_tools(tmp_path, max_calls=2)
    calls, data = sdk(monkeypatch)
    base_spec = ArenaEnvGraphSpec.model_validate(data)
    feedback = {"decision": "repair", "criterion_id": "visible", "retained_manifest": "b" * 64}
    kwargs = dict(
        base_spec=base_spec,
        feedback=feedback,
        protect=lambda v: None,
        asset_catalog=build_asset_catalogue(),
        relation_catalog=build_relation_catalogue(),
        task_catalog=build_task_catalogue(),
    )
    result = tools.refine(**kwargs)
    assert result.spec.model_dump(mode="json") == data
    assert base_spec.model_dump(mode="json") == data
    assert allowance.attempted_calls == len(calls) == 2
    message = calls[1]["messages"][1]["content"]
    assert json.dumps(SpecWireAdapter().encode(data), indent=2) in message
    assert json.dumps(feedback, sort_keys=True, separators=(",", ":")) in message
    with pytest.raises(Exception, match="budget exhausted"):
        tools.refine(**kwargs)
    assert len(calls) == 2


def test_refine_receives_original_centered_permissions_and_returns_guarded_child(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
        build_asset_catalogue,
        build_relation_catalogue,
        build_task_catalogue,
    )
    from isaaclab_arena.agentic_environment_generation.spec_wire_adapter import SpecWireAdapter
    from isaaclab_arena.agentic_environment_generation.workflow.repairs import repair_permission_envelope
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import candidate_record, repaired_candidate
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena.tests._workflow_scene_fixture import composed_fixture

    f = composed_fixture(tmp_path)
    try:
        f.original = candidate_record(
            f.original.run_id,
            ArenaEnvGraphSpec.model_validate(json.loads(f.original.scene_json)).model_dump(mode="json"),
            source_id="generation",
        )
        parent_spec = json.loads(f.original.scene_json)
        parent_spec["relations"][5]["params"]["x"] += 0.08
        parent = repaired_candidate(f.contract, f.original, f.original, parent_spec, source_id="parent")
        proposed = json.loads(parent.scene_json)
        proposed["relations"][5]["params"]["x"] -= 0.12
        wire = SpecWireAdapter().encode(ArenaEnvGraphSpec.model_validate(proposed).model_dump(mode="json"))
        calls, _ = sdk(monkeypatch, completion=json.dumps(wire))
        tools, allowance = model_tools(tmp_path, max_calls=2)
        permissions = repair_permission_envelope(
            f.contract, f.original, parent, effective_subjects=f.ports.direct_root_subjects
        )
        assert permissions["admissible_disk"]["radius_m"] == 0.1
        assert permissions["current"]["xy_m"] != permissions["admissible_disk"]["center_xy_m"]
        feedback = {"assessment": {"failed_ids": ["visible"]}, "repair_permissions": permissions}
        result = tools.refine(
            base_spec=ArenaEnvGraphSpec.model_validate(parent_spec),
            feedback=feedback,
            protect=lambda _: None,
            asset_catalog=build_asset_catalogue(),
            relation_catalog=build_relation_catalogue(),
            task_catalog=build_task_catalogue(),
        )
        assert allowance.attempted_calls == len(calls) == 2
        message = calls[1]["messages"][1]["content"]
        assert json.dumps(feedback, sort_keys=True, separators=(",", ":")) in message
        # The model sees the whole original-centered disk, not a shrinking path budget.
        assert isinstance(result.spec, ArenaEnvGraphSpec)
        child = repaired_candidate(
            f.contract, f.original, parent, result.spec.model_dump(mode="json"), source_id="refiner"
        )
        assert child.parent_id == parent.candidate_id
    finally:
        f.area.close()


@pytest.mark.parametrize("operation", ["generate", "refine"])
def test_model_proposal_is_screened_before_return(tmp_path, monkeypatch, operation):
    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
        build_asset_catalogue,
        build_relation_catalogue,
        build_task_catalogue,
    )
    from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    tools, allowance = model_tools(tmp_path)
    calls, data = sdk(monkeypatch)
    seen = []

    def protect(value):
        if "spec" in value:
            seen.append(value)
            raise ValueError("protected model output")

    catalogues = dict(
        asset_catalog=build_asset_catalogue(),
        relation_catalog=build_relation_catalogue(),
        task_catalog=build_task_catalogue(),
    )
    with ArtifactArea.create(tmp_path / "screened-prior", store_id="store", registry_id="registry") as area:
        priors = RetainedPriorArtifacts(area)
        receipt = priors.write(
            "table", "a" * 64, "run", empty_snapshot("table", status="not_requested", warning=None), protect=protect
        )
        with pytest.raises(ValueError, match="protected model output"):
            if operation == "generate":
                tools.generate(
                    prompt="table",
                    contract_digest="a" * 64,
                    run_id="run",
                    priors=priors,
                    prior=receipt,
                    require_prior=False,
                    protect=protect,
                    **catalogues,
                )
            else:
                tools.refine(
                    base_spec=ArenaEnvGraphSpec.model_validate(data),
                    feedback={"decision": "repair"},
                    protect=protect,
                    **catalogues,
                )
    assert len(calls) == allowance.attempted_calls == 2
    assert seen and set(seen[0]) == {"spec", "warnings", "traces", "publication"}


def test_assess_sends_retained_image_bytes_and_exact_request(tmp_path, monkeypatch):
    import base64

    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import (
        ObservationRecorder,
        visual_request,
    )
    from isaaclab_arena.tests._workflow_scene_fixture import artifacts, criterion, identities, sample

    tools, allowance = model_tools(tmp_path)
    calls, _ = sdk(monkeypatch)
    area, store = artifacts(tmp_path)
    candidate, cohort = identities()
    visual = criterion(
        "scene.visible",
        kind="visual",
        required_modalities=("rgb",),
        coordinate_frames=("front",),
        observation_window={"start_step": 0, "end_step": 0},
        rubric="subject visible in every retained frame",
        limit={"operator": "eq", "value": 1, "unit": "boolean"},
    )
    recorder = ObservationRecorder(lambda env, step: sample(step), provenance="synthetic")
    recorder(None, 0)
    image = b"\x89PNG\r\n\x1a\nsynthetic-image-not-native"
    recorder.add_frame(camera="front", step=0, subject_ids=("cup",), image_bytes=image)
    try:
        receipt = store.write(candidate, cohort, recorder.payload(), protect=lambda v: None)
        request = visual_request(visual, candidate, cohort, store, receipt, protect=lambda v: None)
        result = tools.assess(
            criterion=visual,
            candidate=candidate,
            cohort=cohort,
            artifacts=store,
            observation=receipt,
            protect=lambda v: None,
        )
        assert type(result) is str and "embodiment" in result  # raw synthetic response, not a verdict
        content = calls[1]["messages"][0]["content"]
        assert json.dumps(request, sort_keys=True, separators=(",", ":")) in content[0]["text"]
        assert base64.b64decode(content[1]["image_url"]["url"].split(",")[1]) == image
        assert len(calls) == allowance.attempted_calls == 2
    finally:
        area.close()


def structural_snapshot(prompt):
    import hashlib

    from isaaclab_arena.agentic_environment_generation.prior_receipt import (
        TEXT_FIELDS,
        empty_snapshot,
        format_prior_context,
        validate_prior_snapshot,
    )

    prior = dict.fromkeys(TEXT_FIELDS)
    prior.update(
        name="retained-table-pattern",
        objects=["cup"],
        relations=[],
        evidence="unevaluated",
        success_rate=None,
        episodes=None,
    )
    snapshot = empty_snapshot(prompt, status="structural", warning=None)
    snapshot.update(priors=[prior], timing={"source": "local_monotonic", "elapsed_seconds": 0.01})
    snapshot["exact_context"] = format_prior_context(snapshot["priors"])
    snapshot["context_sha256"] = hashlib.sha256(snapshot["exact_context"].encode()).hexdigest()
    return validate_prior_snapshot(snapshot, prompt=prompt)


def test_authorized_callback_retained_once_then_exact_context(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation import environment_generation_agent as agent
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts

    tools, allowance = model_tools(tmp_path)
    calls, _ = sdk(monkeypatch)
    area = ArtifactArea.create(tmp_path / "priors", store_id="store", registry_id="registry")
    artifacts = RetainedPriorArtifacts(area)
    snapshot = structural_snapshot("table")
    retrievals = []

    def retrieve(prompt):
        retrievals.append(prompt)
        assert allowance.attempted_calls == 0
        return snapshot

    def forbidden(*args, **kwargs):
        raise AssertionError("native/fallback helper must not run for model proposal")

    monkeypatch.setattr(agent, "_ensure_reified_relations_and_grounding", forbidden)
    monkeypatch.setattr(agent, "_deterministic_affordance_fallback", forbidden)
    try:
        receipt = artifacts.capture("table", "a" * 64, "run1", authorized_retriever=retrieve, protect=lambda v: None)
        result = tools.generate(
            prompt="table",
            contract_digest="a" * 64,
            run_id="run1",
            priors=artifacts,
            prior=receipt,
            require_prior=True,
            protect=lambda v: None,
            asset_catalog=agent.build_asset_catalogue(),
            relation_catalog=agent.build_relation_catalogue(),
            task_catalog=agent.build_task_catalogue(),
        )
        assert result.spec and retrievals == ["table"]
        assert calls[1]["messages"][1]["content"].count(snapshot["exact_context"]) == 1
        assert len(calls) == allowance.attempted_calls == 2
    finally:
        area.close()


@pytest.mark.parametrize("status", ["unavailable", "not_requested"])
def test_required_prior_missing_zero_model(tmp_path, monkeypatch, status):
    from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts

    tools, allowance = model_tools(tmp_path)
    calls, _ = sdk(monkeypatch)
    area = ArtifactArea.create(tmp_path / "priors", store_id="store", registry_id="registry")
    store = RetainedPriorArtifacts(area)
    snapshot = empty_snapshot("table", status=status, warning="unconfigured" if status == "unavailable" else None)
    try:
        receipt = store.write("table", "a" * 64, "run1", snapshot, protect=lambda v: None)
        assert (
            store.verified_snapshot(
                receipt, prompt="table", contract_digest="a" * 64, run_id="run1", protect=lambda v: None
            )["status"]
            == status
        )
        with pytest.raises(ValueError, match="required prior unavailable"):
            tools.generate(
                prompt="table",
                contract_digest="a" * 64,
                run_id="run1",
                priors=store,
                prior=receipt,
                require_prior=True,
                protect=lambda v: None,
                asset_catalog=object(),
                relation_catalog=object(),
                task_catalog=object(),
            )
        assert calls == [] and allowance.attempted_calls == 0
    finally:
        area.close()


@pytest.mark.parametrize("completion,status", [("not-json", 200), ("{}", 200), (None, 503)])
def test_model_errors_do_not_fallback_or_retry(tmp_path, monkeypatch, completion, status):
    from isaaclab_arena.agentic_environment_generation import environment_generation_agent as agent
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    tools, allowance = model_tools(tmp_path)
    calls, data = sdk(monkeypatch, completion=completion, status=status)
    with pytest.raises(Exception):
        tools.refine(
            base_spec=ArenaEnvGraphSpec.model_validate(data),
            feedback={"retained": "bad-scene"},
            protect=lambda v: None,
            asset_catalog=agent.build_asset_catalogue(),
            relation_catalog=agent.build_relation_catalogue(),
            task_catalog=agent.build_task_catalogue(),
        )
    assert allowance.attempted_calls == len(calls) == (1 if status == 503 else 2)


@pytest.mark.parametrize("case", ["count-only", "mismatched-attestation", "role", "profile", "deadline"])
def test_configuration_denies_before_model(tmp_path, monkeypatch, case):
    import time

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import CallAllowance
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import BoundedSceneModels

    config = configuration()
    roles = {"generation": {"model": config["model"], "endpoint": config["base_url"]}}
    kwargs = dict(
        max_calls=2,
        deadline=time.monotonic() + 30,
        max_tokens=20000,
        cost_ceiling_usd="0",
        per_call_bound=config["workflow_accounting"],
    )
    if case == "count-only":
        kwargs = dict(max_calls=2, deadline=time.monotonic() + 30)
    if case == "deadline":
        kwargs["deadline"] = float("inf")
    allowance = CallAllowance(**kwargs)
    if case == "mismatched-attestation":
        config["workflow_accounting"]["max_tokens"] += 1
    if case == "role":
        roles["generation"]["model"] = "different"
    if case == "profile":
        config["inference_profile"]["model"] = "different"
    with pytest.raises(ValueError):
        BoundedSceneModels(config=config, approved_roles=roles, allowance=allowance)
    assert allowance.attempted_calls == 0


def test_prior_corruption_and_changed_retry_are_not_repaired(tmp_path):
    from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts

    area = ArtifactArea.create(tmp_path / "priors", store_id="store", registry_id="registry")
    store = RetainedPriorArtifacts(area)
    try:
        receipt = store.write("table", "a" * 64, "run1", structural_snapshot("table"), protect=lambda v: None)
        with pytest.raises(Exception):
            store.write("table", "a" * 64, "run1", empty_snapshot("table"), protect=lambda v: None)
        (tmp_path / "priors" / receipt.relative_directory / "prior.json").write_bytes(b"{}")
        with pytest.raises(Exception):
            store.verified_snapshot(
                receipt, prompt="table", contract_digest="a" * 64, run_id="run1", protect=lambda v: None
            )
    finally:
        area.close()
