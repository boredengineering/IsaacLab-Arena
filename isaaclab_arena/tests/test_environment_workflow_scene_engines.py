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
                receipt,
                prompt="table",
                contract_digest="a" * 64,
                run_id="run1",
                protect=lambda v: None,
            )
            == snapshot
        )
        with pytest.raises(ValueError, match="binding"):
            artifacts.verified_snapshot(
                receipt,
                prompt="different",
                contract_digest="a" * 64,
                run_id="run1",
                protect=lambda v: None,
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
            version=1,
            attested=True,
            model=model,
            endpoint=endpoint,
            max_tokens=10000,
            max_cost_usd="0",
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
                "choices": [{
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }],
            },
        )

    monkeypatch.setattr(transport_type, "handle_request", response)
    return calls, data


def model_tools(tmp_path, *, max_calls=6, request_envelopes=None):
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
    options = {} if request_envelopes is None else {"request_envelopes": request_envelopes}
    return (
        BoundedSceneModels(config=config, approved_roles=roles, allowance=allowance, **options),
        allowance,
    )


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
    feedback = {
        "decision": "repair",
        "criterion_id": "visible",
        "retained_manifest": "b" * 64,
    }
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
            f.contract,
            f.original,
            parent,
            effective_subjects=f.ports.direct_root_subjects,
        )
        assert permissions["admissible_disk"]["radius_m"] == 0.1
        assert permissions["current"]["xy_m"] != permissions["admissible_disk"]["center_xy_m"]
        feedback = {
            "assessment": {"failed_ids": ["visible"]},
            "repair_permissions": permissions,
        }
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
            f.contract,
            f.original,
            parent,
            result.spec.model_dump(mode="json"),
            source_id="refiner",
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
            "table",
            "a" * 64,
            "run",
            empty_snapshot("table", status="not_requested", warning=None),
            protect=protect,
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


def test_assess_sends_retained_image_bytes_and_exact_request(tmp_path, monkeypatch, enveloped=False):
    import base64

    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import (
        ObservationRecorder,
        visual_request,
    )
    from isaaclab_arena.tests._workflow_scene_fixture import artifacts, criterion, identities, sample

    tools, allowance = model_tools(tmp_path, request_envelopes=role_envelopes() if enveloped else None)
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
    image = png_image() if enveloped else b"\x89PNG\r\n\x1a\nsynthetic-image-not-native"
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


def test_authorized_callback_retained_once_then_exact_context(tmp_path, monkeypatch, enveloped=False):
    from isaaclab_arena.agentic_environment_generation import environment_generation_agent as agent
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts

    tools, allowance = model_tools(tmp_path, request_envelopes=role_envelopes() if enveloped else None)
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
        receipt = artifacts.capture(
            "table",
            "a" * 64,
            "run1",
            authorized_retriever=retrieve,
            protect=lambda v: None,
        )
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
    snapshot = empty_snapshot(
        "table",
        status=status,
        warning="unconfigured" if status == "unavailable" else None,
    )
    try:
        receipt = store.write("table", "a" * 64, "run1", snapshot, protect=lambda v: None)
        assert (
            store.verified_snapshot(
                receipt,
                prompt="table",
                contract_digest="a" * 64,
                run_id="run1",
                protect=lambda v: None,
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


def envelope_values(**changes):
    config = configuration()
    return (
        dict(
            version=1,
            model=config["model"],
            endpoint=config["base_url"],
            accounting=config["workflow_accounting"],
            max_text_bytes=100000,
            max_schema_bytes=100000,
            max_request_bytes=300000,
            output_parameter="max_completion_tokens",
            max_output_tokens=64,
            image_formats=["png"],
            max_images=2,
            max_image_bytes=4096,
            max_image_width=8,
            max_image_height=8,
            image_detail="auto",
            permitted_fields=[
                "model",
                "messages",
                "max_completion_tokens",
                "store",
                "response_format",
            ],
            route_policy="direct-chat-completions-v1",
        )
        | changes
    )


def test_envelope_actual_refinement_ping_and_independent_output_ceiling(tmp_path, monkeypatch):
    import inspect

    from openai import OpenAI

    from isaaclab_arena.agentic_environment_generation import environment_generation_agent as agent
    from isaaclab_arena.agentic_environment_generation.workflow import scene_engines
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    # Retain actual installed SDK interception semantics in this isolated test's output.
    print("SDK BUILD REQUEST SOURCE", inspect.getsource(OpenAI._build_request))
    print("SDK REQUEST SOURCE", inspect.getsource(OpenAI.request))
    assert hasattr(scene_engines, "RequestEnvelope"), "opt-in request envelope missing"
    envelope = scene_engines.RequestEnvelope(**envelope_values())
    tools, allowance = model_tools(tmp_path, request_envelopes={"generation": envelope, "assessment": envelope})
    calls, data = sdk(monkeypatch)
    result = tools.refine(
        base_spec=ArenaEnvGraphSpec.model_validate(data),
        feedback={"retained": "exact-scene-feedback"},
        protect=lambda _: None,
        asset_catalog=agent.build_asset_catalogue(),
        relation_catalog=agent.build_relation_catalogue(),
        task_catalog=agent.build_task_catalogue(),
    )
    assert result.spec.model_dump(mode="json") == data
    assert len(calls) == allowance.attempted_calls == 2
    assert calls[0]["max_completion_tokens"] == 8
    assert calls[1]["max_completion_tokens"] == 64
    assert "exact-scene-feedback" in calls[1]["messages"][1]["content"]
    assert "json_schema" in calls[1]["response_format"]


@pytest.mark.parametrize("limit", ["max_text_bytes", "max_schema_bytes", "max_request_bytes"])
def test_envelope_limits_full_sdk_request_before_transport(monkeypatch, limit):
    import inspect
    import time

    from openai import OpenAI

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import CallAllowance, bounded_client
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    print("SDK SEND SOURCE", inspect.getsource(OpenAI._send_request))
    config = configuration()
    envelope = RequestEnvelope(**envelope_values(**{limit: 1}))
    allowance = CallAllowance(
        max_calls=2,
        deadline=time.monotonic() + 30,
        max_tokens=20000,
        cost_ceiling_usd="0",
        per_call_bound=config["workflow_accounting"],
    )
    calls, _ = sdk(monkeypatch)
    with bounded_client(config, allowance=allowance, request_envelope=envelope) as client:
        with pytest.raises(Exception, match="envelope"):
            client.chat.completions.create(
                model=config["model"],
                messages=[{"role": "user", "content": "aggregate input"}],
                max_completion_tokens=32,
                store=False,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "result",
                        "strict": True,
                        "schema": {"type": "object"},
                    },
                },
            )
    assert calls == []


def envelope_allowance(config):
    import time

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import CallAllowance

    return CallAllowance(
        max_calls=10,
        deadline=time.monotonic() + 30,
        max_tokens=100000,
        cost_ceiling_usd="0",
        per_call_bound=config["workflow_accounting"],
    )


@pytest.mark.parametrize(
    "change",
    [
        {"max_completion_tokens": 65},
        {"max_completion_tokens": True},
        {"max_completion_tokens": None},
        {"max_tokens": 1},
        {"stream": True},
        {"stream": False},
        {"n": 2},
        {"n": 1},
        {"tools": []},
        {"tool_choice": "none"},
        {"audio": {"voice": "alloy", "format": "wav"}},
        {"reasoning_effort": "high"},
        {"service_tier": "priority"},
        {"store": True},
        {"extra_body": {"provider": {"allow_fallbacks": True}}},
        {"extra_body": {}},
        {"extra_headers": {"x-provider-route": "elsewhere"}},
        {"extra_query": {"route": "elsewhere"}},
        {"messages": [{"role": "tool", "content": "tool result", "tool_call_id": "id"}]},
        {"messages": [{"role": "user", "content": "a", "name": "extra"}]},
        {
            "messages": [{
                "role": "user",
                "content": [{"type": "input_audio", "input_audio": {}}],
            }]
        },
        {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "x", "schema": {}, "extra": 1},
            }
        },
    ],
)
def test_envelope_closed_request_policy(monkeypatch, change):
    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import bounded_client
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    config = configuration()
    calls, _ = sdk(monkeypatch)
    kwargs = (
        dict(
            model=config["model"],
            messages=[{"role": "user", "content": "ok"}],
            max_completion_tokens=32,
            store=False,
        )
        | change
    )
    with bounded_client(
        config,
        allowance=envelope_allowance(config),
        request_envelope=RequestEnvelope(**envelope_values()),
    ) as client:
        with pytest.raises(Exception, match="envelope"):
            client.chat.completions.create(**kwargs)
    assert calls == []


@pytest.mark.parametrize("mutation", ["body", "header", "url", "query", "method"])
def test_envelope_validates_after_sdk_prepare_hook(monkeypatch, mutation):
    import inspect

    from openai import OpenAI

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import bounded_client
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    print("SDK AUTH SEND SOURCE", inspect.getsource(OpenAI._send_with_auth_retry))
    config = configuration()
    calls, _ = sdk(monkeypatch)
    with bounded_client(
        config,
        allowance=envelope_allowance(config),
        request_envelope=RequestEnvelope(**envelope_values()),
    ) as client:

        def mutate(request):
            print("SDK HEADER NAMES", list(request.headers))
            if mutation == "header":
                request.headers["x-provider-route"] = "elsewhere"
            elif mutation == "url":
                request.url = request.url.copy_with(path="/v1/responses")
            elif mutation == "query":
                request.url = request.url.copy_with(query=b"route=elsewhere")
            elif mutation == "method":
                request.method = "PUT"
            else:
                request._content = request.content.replace(b'"max_completion_tokens":32', b'"max_completion_tokens":99')
                request._content = request._content.replace(
                    b'"max_completion_tokens": 32', b'"max_completion_tokens": 99'
                )

        monkeypatch.setattr(client, "_prepare_request", mutate)
        with pytest.raises(Exception, match="envelope"):
            client.chat.completions.create(
                model=config["model"],
                messages=[{"role": "user", "content": "ok"}],
                max_completion_tokens=32,
                store=False,
            )
    assert calls == []


def png_image(width=2, height=3):
    import struct
    import zlib

    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\0\xff\0" * width) * height))
        + chunk(b"IEND", b"")
    )


def role_envelopes(**changes):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    return {role: RequestEnvelope(**envelope_values(**changes)) for role in ("generation", "assessment")}


def test_enveloped_actual_assessment_retained_png(tmp_path, monkeypatch):
    test_assess_sends_retained_image_bytes_and_exact_request(tmp_path, monkeypatch, enveloped=True)


@pytest.mark.parametrize("case", ["width", "height", "bytes", "count"])
def test_enveloped_actual_assessment_png_overflow_sends_only_ping(tmp_path, monkeypatch, case):
    import base64

    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import (
        ObservationRecorder,
        visual_request,
    )
    from isaaclab_arena.tests._workflow_scene_fixture import artifacts, criterion, identities, sample

    image = png_image(9 if case == "width" else 2, 9 if case == "height" else 3)
    changes = {"max_image_bytes": len(image) - 1} if case == "bytes" else {}
    tools, allowance = model_tools(tmp_path, request_envelopes=role_envelopes(**changes))
    calls, _ = sdk(monkeypatch)
    area, store = artifacts(tmp_path)
    candidate, cohort = identities()
    cameras = ("front", "left", "right") if case == "count" else ("front",)
    visual = criterion(
        "scene.visible",
        kind="visual",
        required_modalities=("rgb",),
        coordinate_frames=cameras,
        observation_window={"start_step": 0, "end_step": 0},
        rubric="subject visible in every retained frame",
        limit={"operator": "eq", "value": 1, "unit": "boolean"},
    )
    recorder = ObservationRecorder(lambda env, step: sample(step), provenance="synthetic")
    recorder(None, 0)
    for camera in cameras:
        recorder.add_frame(camera=camera, step=0, subject_ids=("cup",), image_bytes=image)
    try:
        receipt = store.write(candidate, cohort, recorder.payload(), protect=lambda _: None)
        request = visual_request(visual, candidate, cohort, store, receipt, protect=lambda _: None)
        payload = store.verified_payload(receipt, protect=lambda _: None)
        assert len(request["frames"]) == len(cameras)
        assert all(base64.b64decode(frame["bytes"], validate=True) == image for frame in payload["frames"])
        reason = {
            "width": "PNG dimensions/format",
            "height": "PNG dimensions/format",
            "bytes": "image bytes",
            "count": "aggregate image count",
        }[case]
        with pytest.raises(ValueError, match="request envelope " + reason) as error:
            tools.assess(
                criterion=visual,
                candidate=candidate,
                cohort=cohort,
                artifacts=store,
                observation=receipt,
                protect=lambda _: None,
            )
        assert configuration()["api_key"] not in str(error.value)
        # The real constructor ping is admitted separately. Rejected multimodal
        # assessment reaches neither allowance.charge nor synthetic HTTP transport.
        assert len(calls) == allowance.attempted_calls == 1
        assert allowance.charged_tokens == configuration()["workflow_accounting"]["max_tokens"]
        assert calls[0]["max_completion_tokens"] == 8
        assert "response_format" not in calls[0]
        assert all(type(message["content"]) is str for message in calls[0]["messages"])
    finally:
        area.close()


def test_enveloped_actual_generation_retained_prior(tmp_path, monkeypatch):
    test_authorized_callback_retained_once_then_exact_context(tmp_path, monkeypatch, enveloped=True)


@pytest.mark.parametrize(
    "case",
    [
        "count",
        "aggregate-count",
        "width",
        "height",
        "bytes",
        "remote",
        "jpeg",
        "detail",
        "extra",
        "bad-base64",
        "bad-signature",
        "truncated",
        "trailing",
        "animated",
        "bad-crc",
    ],
)
def test_envelope_rejects_unbounded_inline_images(monkeypatch, case):
    import base64

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import bounded_client
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    config = configuration()
    values = envelope_values()
    image = png_image(9 if case == "width" else 2, 9 if case == "height" else 3)
    if case == "bytes":
        values["max_image_bytes"] = len(image) - 1
    if case == "bad-signature":
        image = b"not-png"
    if case == "truncated":
        image = image[:-4]
    if case == "trailing":
        image += b"extra"
    if case == "animated":
        image = image[:37] + b"acTL" + image[41:]
    if case == "bad-crc":
        image = image[:29] + b"xxxx" + image[33:]
    image_url = {"url": "data:image/png;base64," + base64.b64encode(image).decode("ascii")}
    if case == "remote":
        image_url["url"] = "https://example.invalid/image.png"
    if case == "jpeg":
        image_url["url"] = image_url["url"].replace("image/png", "image/jpeg")
    if case == "detail":
        image_url["detail"] = "high"
    if case == "extra":
        image_url["frames"] = 100
    if case == "bad-base64":
        image_url["url"] += "?"
    parts = [{"type": "image_url", "image_url": image_url}] * (3 if case == "count" else 1)
    messages = [{"role": "user", "content": parts}] * (3 if case == "aggregate-count" else 1)
    calls, _ = sdk(monkeypatch)
    with bounded_client(
        config,
        allowance=envelope_allowance(config),
        request_envelope=RequestEnvelope(**values),
    ) as client:
        with pytest.raises(Exception, match="envelope"):
            client.chat.completions.create(
                model=config["model"],
                messages=messages,
                max_completion_tokens=32,
                store=False,
            )
    assert calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"version": 2},
        {"max_text_bytes": True},
        {"max_text_bytes": 0},
        {"max_schema_bytes": -1},
        {"max_request_bytes": 0},
        {"max_output_tokens": 0},
        {"max_images": -1},
        {"max_image_bytes": 0},
        {"max_image_width": 0},
        {"max_image_height": True},
        {"image_formats": ["jpeg"]},
        {"image_formats": [["png"]]},
        {"image_detail": "unbounded"},
        {"permitted_fields": ["model", "messages", "max_completion_tokens", "tools"]},
        {
            "permitted_fields": [
                "model",
                "messages",
                "max_tokens",
                "max_completion_tokens",
            ]
        },
        {"permitted_fields": ["model", "messages"]},
        {"output_parameter": "reasoning_tokens"},
        {"route_policy": "provider-default-fallbacks"},
    ],
)
def test_envelope_rejects_unsupported_contract(change):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    with pytest.raises(ValueError, match="envelope"):
        RequestEnvelope(**envelope_values(**change))


@pytest.mark.parametrize("change", ["model", "endpoint", "attestation", "roles"])
def test_envelope_binding_change_denied_before_model(tmp_path, monkeypatch, change):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import BoundedSceneModels

    config = configuration()
    envelopes = role_envelopes()
    roles = {role: {"model": config["model"], "endpoint": config["base_url"]} for role in envelopes}
    if change == "model":
        config["model"] = "different"
    if change == "endpoint":
        config["base_url"] += "/"
    if change == "attestation":
        config["workflow_accounting"]["max_cost_usd"] = "0.0"
    if change == "roles":
        del envelopes["assessment"]
    calls, _ = sdk(monkeypatch)
    with pytest.raises(ValueError):
        BoundedSceneModels(
            config=config,
            approved_roles=roles,
            allowance=envelope_allowance(config),
            request_envelopes=envelopes,
        )
    assert calls == []


def test_envelope_freezes_configuration_and_detaches_actual_arguments(tmp_path, monkeypatch):
    from dataclasses import FrozenInstanceError

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import bounded_client
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    values = envelope_values()
    envelope = RequestEnvelope(**values)
    values["accounting"]["max_tokens"] = 1
    values["image_formats"].append("jpeg")
    values["permitted_fields"].append("tools")
    assert envelope.accounting["max_tokens"] == 10000
    assert envelope.image_formats == ("png",)
    assert "tools" not in envelope.permitted_fields
    with pytest.raises(TypeError):
        envelope.accounting["max_tokens"] = 2
    with pytest.raises(FrozenInstanceError):
        envelope.max_output_tokens = 2
    config = configuration()
    allowance = envelope_allowance(config)
    messages = [{"role": "user", "content": "original"}]
    schema = {
        "type": "json_schema",
        "json_schema": {"name": "result", "strict": True, "schema": {"type": "object"}},
    }
    charge = allowance.charge

    def mutate_caller():
        messages[0]["content"] = "changed" * 100000
        schema["json_schema"]["schema"]["description"] = "changed" * 100000
        charge()

    monkeypatch.setattr(allowance, "charge", mutate_caller)
    calls, _ = sdk(monkeypatch)
    with bounded_client(config, allowance=allowance, request_envelope=envelope) as client:
        client.chat.completions.create(
            model=config["model"],
            messages=messages,
            max_completion_tokens=32,
            store=False,
            response_format=schema,
        )
    assert calls[0]["messages"][0]["content"] == "original"
    assert "description" not in calls[0]["response_format"]["json_schema"]["schema"]


@pytest.mark.parametrize("mutation", ["duplicate-json", "stream-bytes", "oversized-header"])
def test_envelope_freezes_final_http_serialization(monkeypatch, mutation):
    import inspect

    from openai import DefaultHttpxClient

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import bounded_client
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    print(
        "HTTPX HOOK SOURCE",
        inspect.getsource(DefaultHttpxClient._send_handling_redirects),
    )
    config = configuration()
    calls, _ = sdk(monkeypatch)
    with bounded_client(
        config,
        allowance=envelope_allowance(config),
        request_envelope=RequestEnvelope(**envelope_values()),
    ) as client:

        def mutate(request):
            if mutation == "duplicate-json":
                request._content = request.content[:-1] + b',"max_completion_tokens":32}'
                request.headers["content-length"] = str(len(request.content))
            elif mutation == "stream-bytes":
                request.stream = type(request.stream)(b'{"model":"other","messages":[]}')
            else:
                request.headers["user-agent"] = "x" * 300000

        monkeypatch.setattr(client, "_prepare_request", mutate)
        with pytest.raises(Exception, match="envelope"):
            client.chat.completions.create(
                model=config["model"],
                messages=[{"role": "user", "content": "ok"}],
                max_completion_tokens=32,
                store=False,
            )
    assert calls == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://openrouter.ai/api/v1",
        "http://api.openai.com/v1",
        "https://api.openai.com/v1?route=x",
    ],
)
def test_envelope_direct_route_excludes_unverified_gateways(endpoint):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    values = envelope_values(endpoint=endpoint)
    values["accounting"]["endpoint"] = endpoint
    with pytest.raises(ValueError, match="envelope"):
        RequestEnvelope(**values)


@pytest.mark.parametrize("operation", ["generate", "refine"])
@pytest.mark.parametrize("limit", ["max_text_bytes", "max_schema_bytes"])
def test_actual_scene_serialization_overflow_sends_only_admitted_ping(tmp_path, monkeypatch, operation, limit):
    from isaaclab_arena.agentic_environment_generation import environment_generation_agent as agent
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    calls, data = sdk(monkeypatch)
    catalogues = dict(
        asset_catalog=agent.build_asset_catalogue(),
        relation_catalog=agent.build_relation_catalogue(),
        task_catalog=agent.build_task_catalogue(),
    )
    with ArtifactArea.create(tmp_path / "overflow", store_id="store", registry_id="registry") as area:
        priors = RetainedPriorArtifacts(area)
        receipt = priors.write(
            "table",
            "a" * 64,
            "run",
            structural_snapshot("table"),
            protect=lambda _: None,
        )

        def invoke(tools):
            if operation == "generate":
                return tools.generate(
                    prompt="table",
                    contract_digest="a" * 64,
                    run_id="run",
                    priors=priors,
                    prior=receipt,
                    require_prior=True,
                    protect=lambda _: None,
                    **catalogues,
                )
            return tools.refine(
                base_spec=ArenaEnvGraphSpec.model_validate(data),
                feedback={"retained_feedback": "exact failed criterion"},
                protect=lambda _: None,
                **catalogues,
            )

        good, _ = model_tools(tmp_path, request_envelopes=role_envelopes())
        assert invoke(good).spec is not None
        assert len(calls) == 2
        body = calls[1]
        size = (
            sum(len(m["content"].encode()) for m in body["messages"])
            if limit == "max_text_bytes"
            else len(json.dumps(body["response_format"], ensure_ascii=True).encode())
        )
        # Every real catalogue/prior/base/feedback/schema is present in this request.
        assert size > 64
        calls.clear()
        denied, allowance = model_tools(tmp_path, request_envelopes=role_envelopes(**{limit: size - 1}))
        with pytest.raises(Exception, match="envelope"):
            invoke(denied)
        assert len(calls) == allowance.attempted_calls == 1  # only constructor ping, zero rejected completion sends
        assert "response_format" not in calls[0]


def test_envelope_inclusive_boundaries_on_actual_sdk_bytes(monkeypatch):
    import base64

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import bounded_client
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    config = configuration()
    image = png_image(8, 8)
    part = {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64," + base64.b64encode(image).decode()},
    }
    messages = [
        {"role": "system", "content": "abc"},
        {"role": "user", "content": [{"type": "text", "text": "def"}, part, part]},
    ]
    schema = {
        "type": "json_schema",
        "json_schema": {"name": "result", "strict": True, "schema": {"type": "object"}},
    }
    values = envelope_values(
        max_text_bytes=6,
        max_schema_bytes=len(json.dumps(schema, ensure_ascii=True).encode()),
        max_image_bytes=len(image),
    )
    kwargs = dict(
        model=config["model"],
        messages=messages,
        max_completion_tokens=64,
        store=False,
        response_format=schema,
    )
    calls, _ = sdk(monkeypatch)
    sizes = []
    with bounded_client(
        config,
        allowance=envelope_allowance(config),
        request_envelope=RequestEnvelope(**values),
    ) as client:

        def observe(request):
            sizes.append(
                len(request.content)
                + len(request.method.encode())
                + len(str(request.url).encode())
                + 5
                + sum(len(k) + len(v) + 4 for k, v in request.headers.raw)
            )

        monkeypatch.setattr(client, "_prepare_request", observe)
        client.chat.completions.create(**kwargs)
    values["max_request_bytes"] = sizes[0]
    with bounded_client(
        config,
        allowance=envelope_allowance(config),
        request_envelope=RequestEnvelope(**values),
    ) as client:
        client.chat.completions.create(**kwargs)
    assert len(calls) == 2
    for key in (
        "max_request_bytes",
        "max_text_bytes",
        "max_schema_bytes",
        "max_image_bytes",
        "max_images",
        "max_output_tokens",
    ):
        smaller = values | {key: values[key] - 1}
        with bounded_client(
            config,
            allowance=envelope_allowance(config),
            request_envelope=RequestEnvelope(**smaller),
        ) as client:
            with pytest.raises(Exception, match="envelope"):
                client.chat.completions.create(**kwargs)
        assert len(calls) == 2


def test_envelope_sdk_bypasses_have_no_transport(monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import bounded_client
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    config = configuration()
    calls, _ = sdk(monkeypatch)
    with bounded_client(
        config,
        allowance=envelope_allowance(config),
        request_envelope=RequestEnvelope(**envelope_values()),
    ) as client:
        with pytest.raises(ValueError, match="envelope"):
            client.post(
                "/chat/completions",
                cast_to=dict,
                body={
                    "model": config["model"],
                    "messages": [],
                    "max_completion_tokens": 1,
                },
            )
    assert calls == []


@pytest.mark.parametrize("alias", ["copy", "with_options"])
@pytest.mark.parametrize("transport_mode", ["replacement", "same", "default"])
def test_envelope_rejects_public_client_cloning(monkeypatch, alias, transport_mode):
    import inspect

    from openai import DefaultHttpxClient, OpenAI

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import bounded_client
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    print("SDK COPY SOURCE", inspect.getsource(OpenAI.copy))
    config = configuration()
    allowance = envelope_allowance(config)
    calls, _ = sdk(monkeypatch)
    with DefaultHttpxClient(trust_env=False, follow_redirects=False) as replacement:
        with bounded_client(
            config,
            allowance=allowance,
            request_envelope=RequestEnvelope(**envelope_values()),
        ) as client:
            options = {}
            if transport_mode != "default":
                options["http_client"] = replacement if transport_mode == "replacement" else client._client
            try:
                clone = getattr(client, alias)(**options)
            except ValueError as exc:
                assert str(exc) == "request envelope client cloning is unsupported"
                assert config["api_key"] not in str(exc)
            else:
                # RED witness: an ordinary public replacement-transport clone inherited
                # credentials, bypassed the ceiling, and sent without charging the owner.
                if transport_mode == "replacement":
                    with clone:
                        assert clone.api_key == config["api_key"]
                        clone.chat.completions.create(
                            model=config["model"],
                            messages=[{"role": "user", "content": "synthetic clone witness"}],
                            max_completion_tokens=65,
                            store=False,
                        )
                    assert len(calls) == 1 and allowance.attempted_calls == 0
                    print("CLONE ESCAPE WITNESS", alias, "synthetic sends=1 charges=0 inherited-key=True output=65>64")
                pytest.fail("request envelope must reject public client cloning at creation")
    assert calls == [] and allowance.attempted_calls == 0


@pytest.mark.parametrize("alias", ["copy", "with_options"])
@pytest.mark.parametrize("transport_mode", ["replacement", "same", "default"])
def test_absent_envelope_preserves_public_client_cloning(monkeypatch, alias, transport_mode):
    from openai import DefaultHttpxClient

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import bounded_client

    config = configuration()
    allowance = envelope_allowance(config)
    calls, _ = sdk(monkeypatch)
    with DefaultHttpxClient(trust_env=False, follow_redirects=False) as replacement:
        with bounded_client(config, allowance=allowance) as client:
            options = {}
            if transport_mode != "default":
                options["http_client"] = replacement if transport_mode == "replacement" else client._client
            with getattr(client, alias)(**options) as clone:
                assert clone is not client and clone.api_key == config["api_key"]
                clone.chat.completions.create(
                    model=config["model"],
                    messages=[{"role": "user", "content": "legacy clone"}],
                    max_completion_tokens=65,
                    store=False,
                )
    # Preserve legacy behavior, not a claim that old derived clients were guarded.
    assert len(calls) == 1 and allowance.attempted_calls == 0


def test_envelope_actual_sdk_httpx_auth_resend_is_one_charge_one_send(monkeypatch):
    import importlib

    from openai import OpenAIError

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import bounded_client
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    config = configuration()
    allowance = envelope_allowance(config)
    calls, _ = sdk(monkeypatch)
    attempts = []
    with bounded_client(
        config,
        allowance=allowance,
        request_envelope=RequestEnvelope(**envelope_values()),
    ) as client:
        httpx = importlib.import_module(type(client._client._transport).__module__.split(".")[0])

        class ResendAuth(httpx.Auth):
            def auth_flow(self, request):
                attempts.append("first")
                response = yield request
                assert response.status_code == 200
                attempts.append("resend")
                yield request

        # Exercise actual HTTPX auth iteration reached through the installed SDK,
        # not a direct call to the hook or a second chat.completions.create.
        monkeypatch.setattr(client._client, "_auth", ResendAuth())
        assert client.max_retries == 0
        with pytest.raises(OpenAIError, match="request envelope rejected before transport") as error:
            client.chat.completions.create(
                model=config["model"],
                messages=[{"role": "user", "content": "auth resend witness"}],
                max_completion_tokens=32,
                store=False,
            )
        assert config["api_key"] not in str(error.value)
    assert attempts == ["first", "resend"]
    assert len(calls) == allowance.attempted_calls == 1
    assert allowance.charged_tokens == config["workflow_accounting"]["max_tokens"]


def test_envelope_requires_attested_output():
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    with pytest.raises(ValueError, match="envelope"):
        RequestEnvelope(**envelope_values(max_output_tokens=10001))


def test_envelope_requires_exact_contract_type(monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import bounded_client

    config = configuration()
    calls, _ = sdk(monkeypatch)

    class Unchecked:
        def check_binding(self, **kwargs):
            pass

    with pytest.raises(ValueError, match="envelope"):
        with bounded_client(config, allowance=envelope_allowance(config), request_envelope=Unchecked()):
            pass
    assert calls == []


def test_envelope_rechecks_accounting_identity_before_transport(monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import bounded_client
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import RequestEnvelope

    config = configuration()
    allowance = envelope_allowance(config)
    calls, _ = sdk(monkeypatch)
    with bounded_client(
        config,
        allowance=allowance,
        request_envelope=RequestEnvelope(**envelope_values()),
    ) as client:

        def change_attestation(request):
            allowance._bound["max_cost_usd"] = "0.0"

        monkeypatch.setattr(client, "_prepare_request", change_attestation)
        with pytest.raises(Exception, match="envelope"):
            client.chat.completions.create(
                model=config["model"],
                messages=[{"role": "user", "content": "ok"}],
                max_completion_tokens=32,
                store=False,
            )
    assert calls == []


def test_prior_corruption_and_changed_retry_are_not_repaired(tmp_path):
    from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts

    area = ArtifactArea.create(tmp_path / "priors", store_id="store", registry_id="registry")
    store = RetainedPriorArtifacts(area)
    try:
        receipt = store.write(
            "table",
            "a" * 64,
            "run1",
            structural_snapshot("table"),
            protect=lambda v: None,
        )
        with pytest.raises(Exception):
            store.write(
                "table",
                "a" * 64,
                "run1",
                empty_snapshot("table"),
                protect=lambda v: None,
            )
        (tmp_path / "priors" / receipt.relative_directory / "prior.json").write_bytes(b"{}")
        with pytest.raises(Exception):
            store.verified_snapshot(
                receipt,
                prompt="table",
                contract_digest="a" * 64,
                run_id="run1",
                protect=lambda v: None,
            )
    finally:
        area.close()
