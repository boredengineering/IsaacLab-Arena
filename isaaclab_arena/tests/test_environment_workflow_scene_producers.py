# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Synthetic inputs only: these tests establish no native physical or model claims."""

import pytest

from isaaclab_arena.tests._workflow_scene_fixture import artifacts, composed_fixture, criterion, identities, sample


def test_shared_synthetic_fixture_has_one_pure_owner():
    for helper in (artifacts, composed_fixture, criterion, identities, sample):
        assert helper.__module__ == "isaaclab_arena.tests._workflow_scene_fixture"


def test_legacy_foreground_source_excludes_opt_in_split_composition():
    import ast
    from pathlib import Path

    source = (
        Path(__file__).parents[2] / "isaaclab_arena_examples/agentic_environment_generation/foreground_scene_ports.py"
    ).read_text()
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
            imports.extend(alias.name for alias in node.names)
    assert not any("split_scene_ports" in name for name in imports), "V2 must remain an explicit opt-in import"
    assert not any(
        isinstance(node, ast.ClassDef) and node.name == "ForegroundSplitScenePorts" for node in ast.walk(tree)
    ), "V2 composition must not live in the legacy module"


@pytest.mark.parametrize("speed,verdict", [(0.009, "established"), (0.01, "established"), (0.011, "violated")])
def test_numeric_limits_use_retained_samples(tmp_path, speed, verdict):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import evaluate_measurement

    area, store = artifacts(tmp_path)
    candidate, cohort = identities()
    try:
        receipt = store.write(
            candidate,
            cohort,
            {
                "kind": "observation",
                "provenance": "synthetic",
                "samples": [sample(i, speed) for i in range(3)],
                "frames": [],
            },
            protect=lambda value: None,
        )
        evidence = evaluate_measurement(criterion(), candidate, cohort, store, receipt, protect=lambda value: None)
        assert evidence.verdict == verdict
        assert "synthetic_inputs_no_native_physical_claim" in evidence.limitations
        assert evidence.manifest_digest == receipt.manifest_digest
    finally:
        area.close()


def test_exact_scene_receipt_loader_reopens_and_rejects_wrong_bindings(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import SceneEvidenceArtifacts

    area, store = artifacts(tmp_path)
    candidate, cohort = identities()
    payload = {"kind": "observation", "samples": [sample(0)], "frames": []}
    try:
        receipt = store.write(candidate, cohort, payload, protect=lambda value: None)
        reopened = SceneEvidenceArtifacts(area).load_receipt(
            candidate, cohort, kind="observation", manifest_digest=receipt.manifest_digest, protect=lambda value: None
        )
        assert reopened == receipt
        assert store.verified_payload(reopened, protect=lambda value: None) == payload
        for changed_candidate, changed_cohort, digest in (
            (candidate.model_copy(update={"candidate_digest": "d" * 64}), cohort, receipt.manifest_digest),
            (candidate, cohort.model_copy(update={"reset_id": "wrong"}), receipt.manifest_digest),
            (candidate, cohort, "0" * 64),
        ):
            with pytest.raises(ValueError):
                store.load_receipt(
                    changed_candidate,
                    changed_cohort,
                    kind="observation",
                    manifest_digest=digest,
                    protect=lambda value: None,
                )
        with pytest.raises(ValueError):
            store.load_receipt(
                candidate,
                cohort,
                kind="../observation",
                manifest_digest=receipt.manifest_digest,
                protect=lambda value: None,
            )
        (tmp_path / "artifacts" / receipt.relative_directory / "evidence.json").write_text("{}")
        with pytest.raises(ValueError):
            store.load_receipt(
                candidate,
                cohort,
                kind="observation",
                manifest_digest=receipt.manifest_digest,
                protect=lambda value: None,
            )
    finally:
        area.close()


def split_fixture(tmp_path, *, effective=True):
    import json

    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
    from isaaclab_arena.agentic_environment_generation.workflow.evidence import CandidateBinding, EvidenceCohort
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        ScenePortProfile,
        identity,
        profile_digest,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import ObservationRecorder
    from isaaclab_arena.agentic_environment_generation.workflow.split_scene_ports import SplitScenePorts

    f = composed_fixture(tmp_path)
    raw = f.contract.model_dump(mode="python")
    for c in raw["criteria"]:
        c["observation_window"] = dict(start_step=4, end_step=6)
    contract = type(f.contract).model_validate(raw)
    profile = ScenePortProfile(
        codec_version=2,
        port_id="split-retained",
        assurance="synthetic",
        owned_worker=True,
        producer_ids=f.profile.producer_ids,
        capture=dict(
            runtime_allowance_seconds=10,
            steps=6,
            observations=1,
            realizations=1,
            model_calls=0,
            model_tokens=0,
            cost_ceiling_usd=0,
        ),
        assess=dict(runtime_allowance_seconds=10, model_calls=1, model_tokens=100, cost_ceiling_usd=0),
        repair=f.profile.repair,
    )

    def capture_stage(intent, candidate, original, contract):
        f.events.append("capture-stage")
        tag = identity(intent.intent_id, candidate.candidate_id)
        cohort = EvidenceCohort(
            realization_id=tag,
            reset_id=identity(tag, "reset"),
            environment_id="env0",
            window_id=identity(tag, "window"),
            frame_id="world",
            contract_digest=contract_digest(contract),
            profile_digest=profile_digest(contract),
        )
        binding = CandidateBinding(
            candidate_digest=candidate.digest,
            contract_digest=cohort.contract_digest,
            profile_digest=cohort.profile_digest,
        )
        source = candidate if effective else f.original
        position = json.loads(source.scene_json)["relations"][5]["params"]

        def state(env, step):
            value = sample(step)
            value["subjects"] = {f.subject: value["subjects"].pop("cup")}
            value["subjects"][f.subject]["position_w"] = [10 + position["x"], position["y"], position["z"]]
            return value

        recorder = ObservationRecorder(state, provenance="synthetic")
        for step in range(4, 7):
            recorder(None, step)
            recorder.add_frame(camera="wrist", step=step, subject_ids=(f.subject,), image_bytes=b"synthetic-image")
        return f.evidence_store.write(binding, cohort, recorder.payload(), protect=f.ports.protect)

    def fresh():
        return SplitScenePorts(
            profile=profile,
            artifacts=f.evidence_store,
            protect=f.ports.protect,
            authorize=f.ports._authorize,
            ready=f.ports._ready,
            capture_stage=capture_stage,
            capture_start_step=4,
            capture_steps=2,
            capture_timeout_seconds=5,
            refine=f.refine,
            visual=f.visual,
            model_ceiling=f.ceiling,
            output_root=tmp_path / "split",
            direct_root_subjects=(f.subject,),
            displacement_tolerance_m=0.001,
            check_active=lambda: None,
        )

    f.split_contract, f.split_profile, f.capture_stage, f.fresh_split = (contract, profile, capture_stage, fresh)
    return f


def test_split_capture_reopens_numeric_then_assesses_exact_cohort(tmp_path):
    import json

    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import SceneIntent, identity

    f = split_fixture(tmp_path)
    fresh, contract, profile = f.fresh_split, f.split_contract, f.split_profile
    try:
        ports = fresh()
        intent = SceneIntent(
            codec_version=2,
            intent_id=identity("capture"),
            candidate_id=f.original.candidate_id,
            action="capture",
            status="released",
            released_at=1,
            reservation=profile.capture,
        )
        pending = ports.execute(intent, f.original, f.original, contract)
        assert f.events == ["capture-stage"]
        captured = ports.verify_observation(pending, contract, f.original)
        assert [e.criterion_id for e in captured.evidence] == ["speed"]
        assert captured.static_failure is None
        assess = SceneIntent(
            codec_version=2,
            intent_id=identity("assess"),
            candidate_id=f.original.candidate_id,
            action="assess",
            status="released",
            released_at=1,
            reservation=profile.assess,
            observation_id=identity(intent.intent_id, "observation"),
            observation_digest=identity(captured.model_dump(mode="json")),
        )
        ports = fresh()  # no producer cache and no simulator needed for assessment
        with pytest.raises(ValueError, match="retained capture"):
            ports.execute(
                assess,
                f.original,
                f.original,
                contract,
                retained_observation=captured.model_copy(update={"verified_manifest_digests": ("a" * 64,)}),
            )
        assert f.events == ["capture-stage"]
        pending = ports.execute(assess, f.original, f.original, contract, retained_observation=captured)
        assessed = ports.verify_observation(pending, contract, f.original)
        assert assessed.cohort == captured.cohort
        assert [e.criterion_id for e in assessed.evidence] == ["speed", "visible"]
        assert f.events == ["capture-stage", "visual"]
        assert assessed.evidence[0] == captured.evidence[0]
        restored = fresh()
        restored.restore_observations(
            [
                dict(
                    candidate_id=f.original.candidate_id,
                    candidate=f.original.model_dump_json(),
                    payload=assessed.model_dump_json(),
                )
            ],
            contract,
        )
        assert restored.verify_observation(assessed, contract, f.original) == assessed
        assert f.events == ["capture-stage", "visual"]
        receipt = restored._retained[assessed.cohort.realization_id][1]
        (tmp_path / "artifacts" / receipt.relative_directory / "evidence.json").write_text(json.dumps({}))
        with pytest.raises(ValueError):
            restored.verify_observation(assessed, contract, f.original)
    finally:
        f.area.close()


@pytest.mark.parametrize(
    "case,expected",
    [
        ("valid", "established"),
        ("zero", "violated"),
        ("wrong-filter", "inconclusive"),
        ("wrong-source", "inconclusive"),
        ("wrong-destination", "inconclusive"),
        ("missing", "inconclusive"),
        ("short", "inconclusive"),
        ("wrong-frame", "inconclusive"),
        ("fast", "violated"),
    ],
)
def test_support_is_not_stability(tmp_path, case, expected):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import evaluate_measurement

    area, store = artifacts(tmp_path)
    candidate, cohort = identities()
    samples = [sample(i) for i in range(3)]
    for s in samples:
        s["subjects"]["table"] = {"position_w": [10.0, 0.0, 0.9], "prim_path": "/table"}
        s["subjects"]["cup"]["prim_path"] = "/cup"
        s["contacts"] = [{
            "subject": "cup",
            "destination": "table",
            "filter_paths": ["/table"],
            "destination_path": "/table",
            "sensor_path": "/cup",
            "force_w": [0.0, 0.0, 2.0],
        }]
        if case == "zero":
            s["contacts"][0]["force_w"] = [0.0, 0.0, 0.0]
        if case == "wrong-filter":
            s["contacts"][0]["filter_paths"] = ["/floor"]
        if case == "wrong-source":
            s["contacts"][0]["sensor_path"] = "/other"
        if case == "wrong-destination":
            s["subjects"]["table"]["prim_path"] = "/other"
        if case == "missing":
            s.pop("contacts")
        if case == "wrong-frame":
            s["frame"] = "local"
        if case == "fast":
            s["subjects"]["cup"]["angular_velocity_w"] = [0.0, 0.0, 0.05]
    if case == "short":
        samples.pop()
    req = criterion(
        "scene.filtered-support",
        subjects=("cup", "table"),
        rubric="filtered contact with settled proximity",
        limit={"operator": "ge", "value": 1.0, "unit": "N"},
    )
    try:
        receipt = store.write(
            candidate,
            cohort,
            {"kind": "observation", "provenance": "synthetic", "samples": samples, "frames": []},
            protect=lambda value: None,
        )
        result = evaluate_measurement(req, candidate, cohort, store, receipt, protect=lambda value: None)
        assert result.verdict == expected
        if case == "missing":
            assert (
                evaluate_measurement(criterion(), candidate, cohort, store, receipt, protect=lambda value: None).verdict
                == "established"
            )
    finally:
        area.close()


def test_artifacts_exact_retry_protection_tamper_and_cohort_exclusion(tmp_path):
    import json

    area, store = artifacts(tmp_path)
    candidate, cohort = identities()
    payload = {"kind": "observation", "samples": [{"step": 0}], "limitations": ["synthetic only"]}
    try:
        receipt = store.write(candidate, cohort, payload, protect=lambda value: value)
        assert store.verified_payload(receipt, protect=lambda value: value) == payload
        assert store.write(candidate, cohort, payload, protect=lambda value: value) == receipt
        with pytest.raises(ValueError):
            store.write(
                candidate.model_copy(update={"candidate_digest": "d" * 64}),
                cohort,
                payload,
                protect=lambda value: value,
            )

        def mutate(value):
            value["payload"]["samples"] = []

        with pytest.raises(ValueError, match="protection"):
            store.verified_payload(receipt, protect=mutate)
        target = tmp_path / "artifacts" / receipt.relative_directory / "evidence.json"
        target.write_text(json.dumps({"tampered": True}))
        with pytest.raises(ValueError):
            store.verified_payload(receipt, protect=lambda value: value)
    finally:
        area.close()


@pytest.mark.parametrize("change", [None, "aggregate", "rubric", "camera", "window", "digest", "criterion", "cohort"])
def test_visual_answer_bound_to_exact_retained_images(tmp_path, change):
    import json

    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import (
        ObservationRecorder,
        evaluate_visual_answer,
        retain_visual_answer,
        visual_request,
    )

    area, store = artifacts(tmp_path)
    candidate, cohort = identities()
    req = criterion(
        "scene.visible",
        kind="visual",
        required_modalities=("rgb",),
        coordinate_frames=("wrist",),
        rubric="subject visible in every retained frame",
        limit={"operator": "eq", "value": 1.0, "unit": "boolean"},
    )
    recorder = ObservationRecorder(lambda env, step: sample(step), provenance="synthetic")
    for i in range(3):
        recorder(None, i)
        recorder.add_frame(camera="wrist", step=i, subject_ids=("cup",), image_bytes=b"synthetic-png" + bytes([i]))
    try:
        observation = store.write(candidate, cohort, recorder.payload(), protect=lambda value: None)
        request = visual_request(req, candidate, cohort, store, observation, protect=lambda value: None)
        raw = dict(request, answers=[{"frame_digest": f["sha256"], "visible": True} for f in request["frames"]])
        if change == "aggregate":
            raw = {"status": "satisfactory"}
        if change == "rubric":
            raw["rubric"] = "support established"
        if change == "camera":
            raw["frames"][0]["camera"] = "other"
        if change == "window":
            raw["step_window"] = [0, 1]
        if change == "digest":
            raw["answers"][0]["frame_digest"] = "f" * 64
        if change == "criterion":
            raw["criterion_id"] = "other"
        if change == "cohort":
            raw["cohort"]["reset_id"] = "other"
        answer = retain_visual_answer(
            req, candidate, cohort, store, observation, json.dumps(raw).encode(), protect=lambda value: None
        )
        if change:
            with pytest.raises(ValueError):
                evaluate_visual_answer(req, candidate, cohort, store, observation, answer, protect=lambda value: None)
        else:
            result = evaluate_visual_answer(
                req, candidate, cohort, store, observation, answer, protect=lambda value: None
            )
            assert result.verdict == "established"
            assert "visual_visibility_only_not_support_causality_or_policy_success" in result.limitations
    finally:
        area.close()


@pytest.mark.parametrize("moved,expected", [(False, False), (True, True), ("world-static", False)])
def test_effective_displacement_explicit_origin_mapping(tmp_path, moved, expected):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import effective_displacement

    area, store = artifacts(tmp_path)
    candidate, cohort = identities()
    try:
        before = store.write(
            candidate,
            cohort,
            {"kind": "observation", "provenance": "synthetic", "samples": [sample(0)], "frames": []},
            protect=lambda value: None,
        )
        after_sample = sample(0)
        after_sample["origin_w"] = [20.0, 0.0, 0.0]
        after_sample["subjects"]["cup"]["position_w"] = [20.1 if moved else 20.0, 0.0, 1.0]
        if moved == "world-static":
            after_sample["subjects"]["cup"]["position_w"] = [10.0, 0.0, 1.0]
        after = store.write(
            candidate.model_copy(update={"candidate_digest": "d" * 64}),
            cohort.model_copy(update={"realization_id": "r2", "reset_id": "reset2"}),
            {"kind": "observation", "provenance": "synthetic", "samples": [after_sample], "frames": []},
            protect=lambda value: None,
        )
        result = effective_displacement(
            store,
            before,
            after,
            subject="cup",
            step=0,
            target_local=[-10.0 if moved == "world-static" else 0.1, 0.0, 1.0],
            mapping="direct-root-translation-v1",
            tolerance_m=0.001,
            protect=lambda value: None,
        )
        assert result["effective"] is expected
        assert result["target_world"] == [10.0 if moved == "world-static" else 20.1, 0.0, 1.0]
        with pytest.raises(ValueError):
            effective_displacement(
                store,
                before,
                after,
                subject="cup",
                step=0,
                target_local=[0.1, 0.0, 1.0],
                mapping="assumed",
                tolerance_m=0.001,
                protect=lambda value: None,
            )
    finally:
        area.close()


@pytest.fixture
def cpu_native_sampler():
    """Real CPU Warp/ProxyArray conversion; synthetic scene, no simulator startup."""
    from types import SimpleNamespace

    import torch
    import warp as wp

    # Disable CUDA initialization, not the isolated runner's denial boundaries.
    wp.config.enable_cuda = False
    from isaaclab.utils.warp import ProxyArray

    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import make_native_sampler
    from isaaclab_arena.tasks.predicates.object_settling import ObjectInitialRestPoseRecorder

    def array(shape):
        return ProxyArray(wp.zeros(shape, dtype=wp.vec3f, device="cpu"))

    class Scene(dict):
        env_origins = torch.zeros((1, 3))

    scene = Scene()
    for name in ("cup", "table"):
        scene[name] = SimpleNamespace(
            cfg=SimpleNamespace(prim_path="/World/" + name),
            data=SimpleNamespace(root_pos_w=array((1,)), root_lin_vel_w=array((1,)), root_ang_vel_w=array((1,))),
        )
    scene["contact"] = SimpleNamespace(
        cfg=SimpleNamespace(prim_path="/World/cup", filter_prim_paths_expr=["/World/table"]),
        data=SimpleNamespace(force_matrix_w=array((1, 1, 1))),
    )
    env = SimpleNamespace(
        num_envs=1, scene=scene, object_initial_rest_pose_recorder=ObjectInitialRestPoseRecorder(1, "cpu")
    )
    req = criterion(
        "scene.filtered-support",
        subjects=("cup", "table"),
        rubric="filtered contact with settled proximity",
        limit={"operator": "ge", "value": 1.0, "unit": "N"},
    )
    sampler = make_native_sampler(
        (req,), subject_names={"cup": "cup", "table": "table"}, contact_sensors={req.subjects: "contact"}
    )
    return SimpleNamespace(env=env, sampler=sampler, array=array)


@pytest.mark.parametrize("values", [[0.0, 0.0, 0.0], [1.0, -2.0, 3.0]])
def test_native_sampler_cpu_proxy_contact_vector(cpu_native_sampler, values):
    import torch

    f = cpu_native_sampler
    force = f.env.scene["contact"].data.force_matrix_w
    assert force.shape == (1, 1, 1)
    assert tuple(force.torch.shape) == (1, 1, 1, 3)
    force.torch[0, 0, 0] = torch.tensor(values)
    result = f.sampler(f.env, 0)
    force.torch.zero_()  # The retained vector is detached from the native buffer.
    assert result["contacts"] == [{
        "subject": "cup",
        "destination": "table",
        "filter_paths": ["/World/table"],
        "destination_path": "/World/table",
        "sensor_path": "/World/cup",
        "force_w": values,
    }]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_native_sampler_cpu_proxy_contact_rejects_nonfinite(cpu_native_sampler, value):
    f = cpu_native_sampler
    f.env.scene["contact"].data.force_matrix_w.torch[0, 0, 0, 1] = value
    with pytest.raises(ValueError, match="nonfinite"):
        f.sampler(f.env, 0)


@pytest.mark.parametrize("shape", [(2, 1, 1), (1, 2, 1), (1, 1, 2), (1, 1), (1, 0, 1)])
def test_native_sampler_cpu_proxy_contact_rejects_non_singleton_axes(cpu_native_sampler, shape):
    f = cpu_native_sampler
    f.env.scene["contact"].data.force_matrix_w = f.array(shape)
    with pytest.raises(ValueError, match="unsupported native contact filter"):
        f.sampler(f.env, 0)


@pytest.mark.parametrize("fault", ["wrong-filter", "extra-filter", "source", "regex", "multi-env"])
def test_native_sampler_cpu_proxy_contact_requires_exact_binding(cpu_native_sampler, fault):
    f = cpu_native_sampler
    sensor = f.env.scene["contact"]
    if fault == "wrong-filter":
        sensor.cfg.filter_prim_paths_expr = ["/World/floor"]
    elif fault == "extra-filter":
        sensor.cfg.filter_prim_paths_expr.append("/World/floor")
    elif fault == "source":
        sensor.cfg.prim_path = "/World/other"
    elif fault == "regex":
        f.env.scene["table"].cfg.prim_path = "/World/table*"
        sensor.cfg.filter_prim_paths_expr = ["/World/table*"]
    else:
        f.env.num_envs = 2
    with pytest.raises(ValueError, match="native contact filter|source mismatch|single environment"):
        f.sampler(f.env, 0)


def test_native_sampler_cpu_proxy_root_getters_use_scalar_view(cpu_native_sampler):
    import torch

    from isaaclab_arena.tasks.predicates.predicate_utils import (
        get_root_ang_vel_w,
        get_root_lin_vel_w,
        get_root_pos_w,
    )

    f = cpu_native_sampler
    data = f.env.scene["cup"].data
    for index, (field, getter) in enumerate((
        ("root_pos_w", get_root_pos_w),
        ("root_lin_vel_w", get_root_lin_vel_w),
        ("root_ang_vel_w", get_root_ang_vel_w),
    )):
        proxy = getattr(data, field)
        values = [1.0 + index, 2.0 + index, 3.0 + index]
        proxy.torch[0] = torch.tensor(values)
        assert proxy.shape == (1,)
        converted = getter(f.env, "cup")
        assert tuple(converted.shape) == (1, 3)
        assert converted.tolist() == [values]
    result = f.sampler(f.env, 0)["subjects"]["cup"]
    assert result["position_w"] == [1.0, 2.0, 3.0]
    assert result["linear_velocity_w"] == [2.0, 3.0, 4.0]
    assert result["angular_velocity_w"] == [3.0, 4.0, 5.0]


def test_native_sampler_lazy_admission_before_import(monkeypatch):
    import builtins

    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import make_native_sampler

    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert not name.startswith(("isaaclab.", "torch", "warp")), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    assert callable(make_native_sampler((criterion(),), subject_names={"cup": "cup"}))
    for change in (
        {"evaluator_version": "2"},
        {"evidence_producer": "policy.success"},
        {"rubric": "support"},
        {"coordinate_frames": ("env-local",)},
    ):
        with pytest.raises(ValueError):
            make_native_sampler((criterion(**change),), subject_names={"cup": "cup"})


@pytest.mark.parametrize(
    "fault", ["missing", "boolean", "nonfinite", "stale", "cohort", "duplicate-step", "out-of-frame"]
)
def test_measurement_negative_inputs(tmp_path, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import evaluate_measurement

    area, store = artifacts(tmp_path)
    candidate, cohort = identities()
    samples = [sample(i) for i in range(3)]
    if fault == "missing":
        samples[1]["subjects"]["cup"].pop("linear_velocity_w")
    if fault == "boolean":
        samples[1]["subjects"]["cup"]["linear_velocity_w"][0] = True
    if fault == "nonfinite":
        samples[1]["subjects"]["cup"]["linear_velocity_w"][0] = float("nan")
    if fault == "duplicate-step":
        samples[1]["step"] = 0
    if fault == "out-of-frame":
        samples[1]["frame"] = "camera"
    try:
        payload = {"kind": "observation", "provenance": "synthetic", "samples": samples, "frames": []}
        if fault == "nonfinite":
            with pytest.raises(ValueError):
                store.write(candidate, cohort, payload, protect=lambda value: None)
            return
        receipt = store.write(candidate, cohort, payload, protect=lambda value: None)
        if fault in ("stale", "cohort"):
            if fault == "stale":
                candidate = candidate.model_copy(update={"candidate_digest": "f" * 64})
            else:
                cohort = cohort.model_copy(update={"reset_id": "reset2"})
            with pytest.raises(ValueError, match="stale or cross-cohort"):
                evaluate_measurement(criterion(), candidate, cohort, store, receipt, protect=lambda value: None)
        else:
            assert (
                evaluate_measurement(criterion(), candidate, cohort, store, receipt, protect=lambda value: None).verdict
                == "inconclusive"
            )
    finally:
        area.close()


def test_artifact_readback_resync_current_protection_and_no_manifest_cycle(tmp_path, monkeypatch):
    import os

    from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import canonical

    area, store = artifacts(tmp_path)
    candidate, cohort = identities()
    payload = {"kind": "observation", "samples": []}
    try:
        receipt = store.write(candidate, cohort, payload, protect=lambda value: None)
        calls = []
        real = os.fsync
        monkeypatch.setattr(os, "fsync", lambda fd: (calls.append(fd), real(fd))[1])
        assert store.verified_payload(receipt, protect=lambda value: None) == payload
        assert len(calls) >= 5  # files, manifest, target and parents, not directory-only

        def reject(value):
            raise RuntimeError("current policy rejection")

        with pytest.raises(RuntimeError, match="current policy"):
            store.verified_payload(receipt, protect=reject)
        assert (
            receipt.manifest_digest.encode()
            not in (tmp_path / "artifacts" / receipt.relative_directory / "evidence.json").read_bytes()
        )
        with pytest.raises(ValueError):
            canonical({"blob": "x" * (2 * 1024 * 1024)})
    finally:
        area.close()


@pytest.mark.parametrize(
    "linear,angular,expected", [(0.009, 0.049, "established"), (0.01, 0.0, "violated"), (0.0, 0.05, "violated")]
)
def test_settling_samples_do_not_require_or_establish_support(tmp_path, linear, angular, expected):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import evaluate_measurement

    area, store = artifacts(tmp_path)
    candidate, cohort = identities()
    values = [sample(i, linear) for i in range(3)]
    for value in values:
        value["subjects"]["cup"]["angular_velocity_w"] = [angular, 0.0, 0.0]
    req = criterion(
        "scene.settled",
        rubric="linear and angular speeds below settling thresholds",
        limit={"operator": "eq", "value": 1.0, "unit": "boolean"},
    )
    try:
        receipt = store.write(
            candidate,
            cohort,
            {"kind": "observation", "provenance": "synthetic", "samples": values, "frames": []},
            protect=lambda value: None,
        )
        result = evaluate_measurement(req, candidate, cohort, store, receipt, protect=lambda value: None)
        assert result.verdict == expected
        assert "settling_does_not_establish_support" in result.limitations
    finally:
        area.close()


def test_finite_components_with_overflowing_norm_are_inconclusive(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import evaluate_measurement

    area, store = artifacts(tmp_path)
    candidate, cohort = identities()
    values = [sample(i) for i in range(3)]
    values[0]["subjects"]["cup"]["linear_velocity_w"] = [1.79e308] * 3
    try:
        receipt = store.write(
            candidate,
            cohort,
            {"kind": "observation", "provenance": "synthetic", "samples": values},
            protect=lambda value: None,
        )
        assert (
            evaluate_measurement(criterion(), candidate, cohort, store, receipt, protect=lambda value: None).verdict
            == "inconclusive"
        )
    finally:
        area.close()


def test_protection_cannot_return_a_replacement(tmp_path):
    area, store = artifacts(tmp_path)
    candidate, cohort = identities()
    try:
        with pytest.raises(ValueError, match="protection"):
            store.write(candidate, cohort, {"kind": "observation", "samples": []}, protect=lambda value: {})
    finally:
        area.close()


@pytest.mark.parametrize("flags", [(True, False), (False, True), (True, True), (False, False)])
@pytest.mark.parametrize("end_step", [1, 2, 3])
def test_capture_samples_every_nonterminal_step(tmp_path, flags, end_step):
    from isaaclab_arena.agentic_environment_generation.trajectory_capture import capture_trajectory

    class Flag:
        def __init__(self, value):
            self.value = value

        def any(self):
            return self.value

    class Env:
        state = 0

        def reset(self):
            return {"camera_obs": {}}, {}

        def step(self, action):
            self.state += 1
            end = flags if self.state == end_step else (False, False)
            if any(end):
                self.state = 999  # returned native observations have autoreset
            return {"camera_obs": {}}, 0, Flag(end[0]), Flag(end[1]), {}

    class Policy:
        def reset(self):
            pass

        def get_action(self, *args):
            return 0

    samples = []
    result = capture_trajectory(
        Env(),
        Policy(),
        out_dir=tmp_path,
        num_steps=3,
        frame_interval=2,
        camera_names=[],
        save_frame=lambda *args: None,
        sample_state=lambda env, step: samples.append((step, env.state)),
    )
    assert samples == [(i, i) for i in range(end_step if any(flags) else 4)]
    assert set(result) == {"frames", "executed_steps", "stop_reason", "terminal_image_unavailable"}


def test_repair_radius_is_original_not_previous_revision(tmp_path):
    import copy

    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import candidate_record, repaired_candidate
    from isaaclab_arena.tests.test_environment_workflow_repairs import scene
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import scene_contract

    contract = scene_contract()
    original = candidate_record("run", scene(), source_id="generation")
    positive = copy.deepcopy(scene())
    positive["relations"][2]["params"]["x"] = 0.1
    parent = repaired_candidate(contract, original, original, positive, source_id="revision1")
    negative = copy.deepcopy(scene())
    negative["relations"][2]["params"]["x"] = -0.1
    child = repaired_candidate(contract, original, parent, negative, source_id="revision2")
    assert child.parent_id == parent.candidate_id
    assert child.original_id == original.candidate_id
    with pytest.raises(ValueError, match="repair_no_op"):
        repaired_candidate(contract, original, parent, positive, source_id="same-as-parent")


def test_restore_repeated_candidate_requires_durable_selection(tmp_path):
    import json
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        SceneIntent,
        identity,
        repaired_candidate,
    )

    f = composed_fixture(tmp_path)
    rows = []
    try:
        for tag in ("selected", "older"):
            intent = SceneIntent(
                intent_id=identity(tag),
                candidate_id=f.original.candidate_id,
                action="observe",
                status="released",
                released_at=1.0,
                reservation=f.profile.observe,
            )
            result = f.ports.execute(intent, f.original, f.original, f.contract)
            rows.append(
                dict(
                    evidence_id=identity(intent.intent_id, "observation"),
                    candidate_id=f.original.candidate_id,
                    candidate=f.original.model_dump_json(),
                    payload=result.model_dump_json(),
                )
            )
        expected = f.ports._retained[next(iter(f.ports._retained))][1].cohort
        f.ports._latest.clear()
        f.ports._retained.clear()
        with pytest.raises(ValueError, match="selection"):
            f.ports.restore_observations(rows, f.contract)
        records: dict = dict(
            evidence=rows,
            evidence_selections=[],
            selected_evidence_id=rows[0]["evidence_id"],
            scene=SimpleNamespace(candidate=f.original),
        )
        effects = list(f.events)
        f.ports.restore_observations(records, f.contract)
        assert f.ports._latest[f.original.candidate_id].cohort == expected
        assert f.events == effects
        # Missing selected bytes must never fall back to another complete cohort.
        records["selected_evidence_id"] = "a" * 64
        with pytest.raises(ValueError, match="selection"):
            f.ports.restore_observations(records, f.contract)
        # A fresh child needs the parent cohort selected by its repair decision.
        proposed = json.loads(f.original.scene_json)
        proposed["relations"][5]["params"]["x"] += 0.03
        child = repaired_candidate(f.contract, f.original, f.original, proposed, source_id=identity("repair"))
        records.update(
            scene=SimpleNamespace(candidate=child),
            selected_evidence_id=None,
            evidence_selections=[
                dict(
                    candidate_id=f.original.candidate_id, intent_id=child.source_id, evidence_id=rows[0]["evidence_id"]
                )
            ],
        )
        f.ports._latest.clear()
        f.ports._retained.clear()
        f.ports.restore_observations(records, f.contract)
        assert f.ports._latest[f.original.candidate_id].cohort == expected
        assert child.candidate_id not in f.ports._latest
        records["evidence_selections"] = []
        with pytest.raises(ValueError, match="selection"):
            f.ports.restore_observations(records, f.contract)
        records.update(scene=SimpleNamespace(candidate=f.original), selected_evidence_id=rows[0]["evidence_id"])
        receipt = f.ports._retained[expected.realization_id][1]
        (tmp_path / "artifacts" / receipt.relative_directory / "evidence.json").write_text("{}")
        with pytest.raises(ValueError):
            f.ports.restore_observations(records, f.contract)
        assert f.events == effects
    finally:
        f.area.close()


@pytest.mark.parametrize("protected", [False, True])
def test_role_ceilings_and_repair_return_protection(tmp_path, protected):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import SceneIntent, identity

    f = composed_fixture(tmp_path, role_ceilings=True)
    try:
        observed = []
        visual, refine = f.ports._visual, f.ports._refine

        def assess(**kwargs):
            observed.append(kwargs["allowance"]._bound["model"])
            return visual(**kwargs)

        def repair(**kwargs):
            observed.append(kwargs["allowance"]._bound["model"])
            return refine(**kwargs)

        f.ports._visual, f.ports._refine = assess, repair

        def intent(action):
            return SceneIntent(
                intent_id=identity(action),
                candidate_id=f.original.candidate_id,
                action=action,
                status="released",
                reservation=getattr(f.profile, action),
                released_at=1.0,
            )

        f.ports.execute(intent("observe"), f.original, f.original, f.contract)
        if protected:

            def reject(value):
                if isinstance(value, dict) and "relations" in value:
                    raise ValueError("private candidate refused")

            f.ports.protect = reject
            with pytest.raises(ValueError, match="private candidate refused"):
                f.ports.execute(intent("repair"), f.original, f.original, f.contract)
        else:
            f.ports.execute(intent("repair"), f.original, f.original, f.contract)
        assert observed == ["assessment", "generation"]
    finally:
        f.area.close()


@pytest.mark.parametrize("effective,expected", [(True, "accept"), (False, "stop")])
def test_concrete_ports_retained_capture_assessor_repair_tracer(tmp_path, effective, expected):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        SceneIntent,
        assess_and_route,
        identity,
        repaired_candidate,
    )

    f = composed_fixture(tmp_path, effective=effective)
    try:
        assert f.events == []  # no model/runtime construction at composition
        f.ports.validate_candidate(__import__("json").loads(f.original.scene_json))

        def intent(action, candidate, index):
            return SceneIntent(
                intent_id=identity(index),
                candidate_id=candidate.candidate_id,
                action=action,
                status="released",
                reservation=getattr(f.profile, action),
                released_at=1.0,
            )

        assert f.ports.require_bounded_capability("principal", f.contract, f.profile.observe) is True
        first = f.ports.execute(intent("observe", f.original, 1), f.original, f.original, f.contract)
        first = f.ports.verify_observation(first, f.contract, f.original)
        decision = assess_and_route(f.contract, f.original, first)
        assert decision.action == "repair"
        proposal = f.ports.execute(intent("repair", f.original, 2), f.original, f.original, f.contract)
        f.ports.validate_candidate(proposal)
        child = repaired_candidate(f.contract, f.original, f.original, proposal, source_id="repair")
        second = f.ports.execute(intent("observe", child, 3), child, f.original, f.contract)
        second = f.ports.verify_observation(second, f.contract, child)
        decision = assess_and_route(f.contract, child, second)
        assert decision.action == expected
        if not effective:
            assert decision.reason == "ineffective_edit"
        assert first.cohort != second.cohort
        assert f.events == ["capture", "closed", "visual", "refine", "capture", "closed", "visual"]
        assert all("synthetic_inputs_no_native_physical_claim" in e.limitations for e in second.evidence)
        with pytest.raises(ValueError):
            f.ports.verify_observation(first, f.contract, child)
    finally:
        f.area.close()


def test_malformed_visual_answer_retained_static_stop(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        SceneIntent,
        assess_and_route,
        identity,
    )

    f = composed_fixture(tmp_path)
    try:

        def malformed(**kwargs):
            kwargs["allowance"].charge()
            return b'{"status":"satisfactory"}'

        f.ports._visual = malformed
        intent = SceneIntent(
            intent_id=identity("malformed"),
            candidate_id=f.original.candidate_id,
            action="observe",
            status="released",
            reservation=f.profile.observe,
            released_at=1.0,
        )
        result = f.ports.execute(intent, f.original, f.original, f.contract)
        checked = f.ports.verify_observation(result, f.contract, f.original)
        decision = assess_and_route(f.contract, f.original, checked)
        assert (decision.action, decision.reason) == ("stop", "invalid_visual_answer")
        _, observation, answer = f.ports._retained[result.cohort.realization_id]
        assert (
            f.evidence_store.verified_payload(answer, protect=lambda value: None)["raw_response"]
            == '{"status":"satisfactory"}'
        )
        assert f.evidence_store.verified_payload(observation, protect=lambda value: None)["frames"]
    finally:
        f.area.close()


@pytest.mark.parametrize(
    "fault",
    ["producer", "rubric", "window", "multi-visual", "model-calls", "tokens", "cost", "capture", "runtime", "mapping"],
)
def test_ports_refuse_unadmitted_profiles_without_effects(tmp_path, fault):
    from dataclasses import replace

    f = composed_fixture(tmp_path)
    try:
        raw = f.contract.model_dump(mode="python")
        if fault == "producer":
            raw["criteria"][0]["evidence_producer"] = "unsupported"
        elif fault == "rubric":
            raw["criteria"][0]["rubric"] = "arbitrary rubric"
        elif fault == "window":
            raw["criteria"][0]["observation_window"]["end_step"] = 1
        elif fault == "multi-visual":
            raw["criteria"] += (dict(raw["criteria"][1], criterion_id="second-visual"),)
        elif fault == "model-calls":
            f.ports.model_ceiling = replace(f.ceiling, max_calls=2)
        elif fault == "tokens":
            f.ports.model_ceiling = replace(f.ceiling, max_tokens=101)
        elif fault == "cost":
            f.ports.model_ceiling = replace(f.ceiling, max_cost_usd="0.01")
        elif fault == "capture":
            f.ports.capture_steps = 3
        elif fault == "runtime":
            f.ports.capture_timeout_seconds = 11.0
        elif fault == "mapping":
            f.ports.direct_root_subjects = frozenset()
        with pytest.raises(ValueError):
            f.ports.require_bounded_capability("principal", type(f.contract).model_validate(raw), f.profile.observe)
        assert f.events == []
    finally:
        f.area.close()


@pytest.mark.parametrize("fault", ["numeric-bytes", "visual-bytes", "manifest-digest", "complementary-cohort"])
def test_concrete_verify_reopens_every_manifest(tmp_path, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import SceneIntent, identity

    f = composed_fixture(tmp_path)
    try:
        intent = SceneIntent(
            intent_id=identity("verify"),
            candidate_id=f.original.candidate_id,
            action="observe",
            status="released",
            reservation=f.profile.observe,
            released_at=1.0,
        )
        output = f.ports.execute(intent, f.original, f.original, f.contract)
        _, observation, answer = f.ports._retained[output.cohort.realization_id]
        if fault in ("numeric-bytes", "visual-bytes"):
            target = observation if fault == "numeric-bytes" else answer
            (tmp_path / "artifacts" / target.relative_directory / "evidence.json").write_text("{}")
        elif fault == "manifest-digest":
            output = output.model_copy(update={"verified_manifest_digests": ("a" * 64,)})
        else:
            evidence = list(output.evidence)
            evidence[1] = evidence[1].model_copy(
                update={"verdict": "established", "cohort": output.cohort.model_copy(update={"reset_id": "another"})}
            )
            output = output.model_copy(update={"evidence": tuple(evidence)})
        with pytest.raises(ValueError):
            f.ports.verify_observation(output, f.contract, f.original)
        with pytest.raises(ValueError, match="released"):
            f.ports.execute(intent, f.original, f.original, f.contract)
    finally:
        f.area.close()


@pytest.mark.parametrize("action", ["observe", "repair"])
def test_cancel_during_model_return_cannot_adopt(tmp_path, action):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import SceneIntent, identity

    f = composed_fixture(tmp_path)
    try:

        def intent(kind):
            return SceneIntent(
                intent_id=identity(kind),
                candidate_id=f.original.candidate_id,
                action=kind,
                status="released",
                reservation=getattr(f.profile, kind),
                released_at=1.0,
            )

        if action == "repair":
            f.ports.execute(intent("observe"), f.original, f.original, f.contract)
        original_callback = f.ports._visual if action == "observe" else f.ports._refine

        def cancelled():
            raise ValueError("cancelled")

        def callback(**kwargs):
            result = original_callback(**kwargs)
            f.ports.check_active = cancelled
            return result

        if action == "observe":
            f.ports._visual = callback
        else:
            f.ports._refine = callback
        with pytest.raises(ValueError, match="cancelled"):
            f.ports.execute(intent(action), f.original, f.original, f.contract)
    finally:
        f.area.close()


@pytest.mark.parametrize("mode", ["accept", "uncertain", "released", "cancelled"])
def test_workflow_service_consumes_concrete_ports(tmp_path, mode):
    """Synthetic store seam only; real service, schema, capture, producer and assessor."""
    import json
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        SceneDecision,
        SceneIntent,
        SceneSnapshot,
        assess_and_route,
        identity,
        repaired_candidate,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    f = composed_fixture(tmp_path)

    class Store:
        def __init__(self):
            self.run = SimpleNamespace(state="running", version=1, contract_json=canonical_json(f.contract))
            self.candidate = f.original
            self.decision = SceneDecision(action="observe", reason="initial")
            self.intent = self.next_intent("observe")
            self.results = []

        def next_intent(self, action):
            return SceneIntent(
                intent_id=identity(self.run.version),
                candidate_id=self.candidate.candidate_id,
                action=action,
                status="reserved",
                reservation=getattr(f.profile, action),
            )

        def scene_snapshot(self, run_id):
            return SceneSnapshot(self.run, f.original, self.candidate, self.decision, self.intent, f.profile)

        def release_scene(self, run_id, intent_id, auth, *, readiness):
            self.intent = self.intent.model_copy(update={"status": "released", "released_at": 1.0})
            return True

        def check_scene_release(self, run_id, intent_id, auth, *, readiness):
            assert self.intent.intent_id == intent_id and self.intent.status == "released"
            return self.intent

        def get_run(self, run_id):
            return self.run

        def mark_scene_unknown(self, run_id, intent_id):
            self.run.state = "reconciliation_required"

        def finish_scene(self, run_id, intent_id, version, result):
            assert len(self.results) < 3  # this synthetic store is not budget/persistence proof
            self.results.append(result)
            self.run.version += 1
            if result.observation:
                self.decision = assess_and_route(f.contract, self.candidate, result.observation)
            else:
                self.candidate = repaired_candidate(
                    f.contract, f.original, self.candidate, json.loads(result.candidate_json), source_id=intent_id
                )
                self.decision = SceneDecision(action="observe", reason="fresh_child")
            if self.decision.action in ("accept", "stop"):
                self.run.state = "accepted" if self.decision.action == "accept" else "stopped"
                self.intent = None
            else:
                self.intent = self.next_intent(self.decision.action)

    try:
        store = Store()
        if mode == "released":
            store.intent = store.intent.model_copy(update={"status": "released", "released_at": 1.0})
        elif mode == "cancelled":
            store.run.state = "cancelled"
        elif mode == "uncertain":

            def uncertain(**kwargs):
                f.events.append("uncertain_capture")
                raise RuntimeError("controlled capture failure after release")

            f.ports._capture = uncertain
        service = WorkflowService(
            store, SimpleNamespace(require_read=lambda principal: None), None, validate_support=f.ports.admit
        )
        final = service.run_scene("principal", "run", ports=f.ports)
        if mode != "accept":
            assert final.run.state == ("cancelled" if mode == "cancelled" else "reconciliation_required")
            if mode == "uncertain":
                assert "uncertain_capture" in f.events
            assert store.results == []
            before = list(f.events)
            service.run_scene("principal", "run", ports=f.ports)
            assert f.events == before
            assert "visual" not in f.events and "refine" not in f.events
            return
        assert final.run.state == "accepted"
        assert [bool(r.observation) for r in store.results] == [True, False, True]
        assert final.candidate.parent_id == f.original.candidate_id
        before = list(f.events)
        assert service.run_scene("principal", "run", ports=f.ports).run.state == "accepted"
        assert f.events == before  # terminal read dispatches no checks/effects
    finally:
        f.area.close()


@pytest.mark.parametrize("effective", [True, False])
def test_split_absolute_displacement_and_fresh_lineage_restore(tmp_path, effective):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        SceneIntent,
        identity,
        repaired_candidate,
    )

    f = split_fixture(tmp_path, effective=effective)
    ports, contract, profile = f.fresh_split(), f.split_contract, f.split_profile

    def run(action, candidate, captured=None):
        intent = SceneIntent(
            codec_version=2,
            intent_id=identity(action, candidate.candidate_id),
            candidate_id=candidate.candidate_id,
            action=action,
            status="released",
            released_at=1,
            reservation=getattr(profile, action),
            observation_id=(identity(candidate.candidate_id, "observation") if captured else None),
            observation_digest=(identity(captured.model_dump(mode="json")) if captured else None),
        )
        args = {} if captured is None else dict(retained_observation=captured)
        return ports.execute(intent, candidate, f.original, contract, **args)

    try:
        baseline = ports.verify_observation(run("capture", f.original), contract, f.original)
        baseline = ports.verify_observation(run("assess", f.original, baseline), contract, f.original)
        proposed = run("repair", f.original)
        child = repaired_candidate(contract, f.original, f.original, proposed, source_id=identity("repair"))
        captured = ports.verify_observation(run("capture", child), contract, child)
        assert captured.static_failure == (None if effective else "ineffective_edit")
        if effective:
            captured = ports.verify_observation(run("assess", child, captured), contract, child)
            assert all(e.verdict == "established" for e in captured.evidence)
        events = list(f.events)
        restored = f.fresh_split()
        restored.restore_observations(
            [
                dict(candidate_id=c.candidate_id, candidate=c.model_dump_json(), payload=o.model_dump_json())
                for c, o in ((child, captured), (f.original, baseline))
            ],
            contract,
        )
        assert restored.verify_observation(captured, contract, child) == captured
        assert f.events == events
    finally:
        f.area.close()


def test_split_native_admission_requires_real_frozen_producer(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import (
        NativeCaptureProducer,
        NativeCaptureSettings,
    )

    f = split_fixture(tmp_path)
    try:
        ports = f.fresh_split()
        ports.profile = ports.profile.model_copy(update={"assurance": "native-unverified"})
        with pytest.raises(ValueError, match="frozen native producer"):
            ports.admit(f.split_contract)
        criteria = f.split_contract.criteria[:1]
        execution = f.split_contract.execution
        settings = NativeCaptureSettings(
            runtime_profile_id="native-runtime",
            capture_profile_id="native-capture",
            seed=execution.seed,
            timestep_seconds=execution.timestep_seconds,
            decimation=execution.decimation,
            settle_steps=4,
            settle_consecutive_steps=1,
            settle_angular_rad_per_s=0.01,
            window=dict(start_step=4, end_step=6),
            subjects=(dict(subject_id=f.subject, scene_name=f.subject, prim_path="/World/subject"),),
            criteria=criteria,
            max_runtime_seconds=5,
        )
        ports.native_producer = NativeCaptureProducer(
            settings=settings, artifacts=f.evidence_store, protect=ports.protect, output_root=tmp_path / "native"
        )
        with pytest.raises(ValueError, match="binding"):
            ports.admit(f.split_contract)
        contract = f.split_contract.model_copy(
            update={
                "criteria": criteria,
                "execution": execution.model_copy(
                    update={"runtime": settings.runtime_reference(), "capture": settings.capture_reference()}
                ),
            }
        )
        assert ports.admit(contract) == criteria
        ports.capture_start_step = 3
        with pytest.raises(ValueError, match="window"):
            ports.admit(contract)
        assert not f.events
    finally:
        f.area.close()


def test_native_gpu_lease_requires_exact_verified_cleanup_before_unlock(tmp_path):
    import fcntl
    import os
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow import native_resources

    path = tmp_path / "common-gpu.lock"
    lease = native_resources.NativeGpuLease(path)
    fence = SimpleNamespace(run_id="run", attempt_id="capture")
    registration = SimpleNamespace(fence=fence, registration_id="owned-child")
    cleanup = SimpleNamespace(registration=registration, observation="owned_process_group_stopped")
    lease.acquire(fence)
    competitor = os.open(path, os.O_RDWR)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="cleanup"):
            lease.release(registration, cleanup, verify_cleanup=lambda *_: False)
        with pytest.raises(BlockingIOError):
            fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        wrong = SimpleNamespace(fence=SimpleNamespace(run_id="other", attempt_id="capture"))
        with pytest.raises(ValueError, match="binding"):
            lease.release(wrong, cleanup, verify_cleanup=lambda *_: True)
        lease.release(registration, cleanup, verify_cleanup=lambda *_: True)
        fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not lease.held
    finally:
        os.close(competitor)


def test_owned_split_stage_gpu_contention_cleanup_and_numeric_routing(tmp_path):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.native_resources import NativeGpuLease
    from isaaclab_arena.agentic_environment_generation.workflow.split_scene_ports import OwnedSceneStageAdapter

    events = []
    allowed = [False]
    verified = [False]
    gpu = NativeGpuLease(tmp_path / "gpu.lock")
    competitor = NativeGpuLease(tmp_path / "gpu.lock")

    class Worker:
        def __init__(self, kind):
            self.kind = kind

        def prepare(self, fence, contract, *, timeout_s):
            events.append(self.kind + "-prepare")
            return SimpleNamespace(registration=SimpleNamespace(fence=fence, registration_id=fence.attempt_id))

        def stop_owned(self, prepared, *, timeout_s):
            events.append(self.kind + "-stop")
            return SimpleNamespace(registration=prepared.registration)

        def cleanup_verified(self, registration, cleanup):
            return verified[0] and cleanup.registration == registration

        def send_capture(self, prepared, intent, candidate, original, contract, *, protect):
            events.append("native-capture")

        def receive_capture(self, prepared, *, protect):
            return "controlled receipt seam"

        def send_evaluate(self, prepared, intent, candidate, original, contract, *, retained_observation, protect):
            self.observation = retained_observation

        def receive_evaluate(self, prepared, *, protect):
            events.append("numeric-evaluate")
            return self.observation

        def send(self, *args, **kwargs):
            events.append("model-send")

        def receive(self, *args, **kwargs):
            events.append("model-receive")

    adapter = OwnedSceneStageAdapter(
        native_worker=Worker("native"),
        model_worker=Worker("model"),
        numeric_worker=Worker("numeric"),
        gpu_lease=gpu,
        authorize_native=lambda intent, contract: allowed[0],
    )
    contract = SimpleNamespace(criteria=[criterion()])

    def intent(action):
        return SimpleNamespace(action=action, worker_fence=SimpleNamespace(attempt_id=action), intent_id=action)

    capture, assess = intent("capture"), intent("assess")
    with pytest.raises(ValueError, match="native authorization"):
        adapter.prepare_stage(capture, contract, timeout_s=1)
    assert not gpu.held and not events
    allowed[0] = True
    competitor.acquire(capture.worker_fence)
    with pytest.raises(BlockingIOError):
        adapter.prepare_stage(capture, contract, timeout_s=1)
    assert not gpu.held and not events
    competitor.release(
        SimpleNamespace(fence=capture.worker_fence),
        SimpleNamespace(registration=SimpleNamespace(fence=capture.worker_fence)),
        verify_cleanup=lambda *_: True,
    )
    prepared = adapter.prepare_stage(capture, contract, timeout_s=1)
    assert gpu.held and events == ["native-prepare"]
    with pytest.raises(ValueError, match="GPU"):
        adapter.prepare_stage(assess, contract, timeout_s=1)
    assert events == ["native-prepare"]
    cleanup = adapter.stop_owned(prepared, timeout_s=1)
    with pytest.raises(ValueError, match="cleanup"):
        adapter.release_native_resource(prepared.registration, cleanup)
    assert gpu.held
    with pytest.raises(BlockingIOError):
        competitor.acquire(capture.worker_fence)
    verified[0] = True
    assert adapter.release_native_resource(prepared.registration, cleanup) is True
    assert not gpu.held
    prepared = adapter.prepare_stage(assess, contract, timeout_s=1)
    adapter.send_evaluate(prepared, assess, None, None, contract, retained_observation="exact", protect=lambda _: None)
    result = adapter.receive_evaluate(prepared, protect=lambda _: None)
    assert result == "exact"
    assert events == ["native-prepare", "native-stop", "numeric-prepare", "numeric-evaluate"]
    with pytest.raises(ValueError, match="model"):
        adapter.send(prepared, b"forbidden", timeout_s=1)


@pytest.mark.parametrize("numeric_only", [False, True])
@pytest.mark.parametrize("expired", [False, True])
def test_foreground_split_service_keeps_owner_and_cleans_before_model(tmp_path, numeric_only, expired):
    import json
    import time
    from contextlib import nullcontext
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.agentic_environment_generation.workflow.native_resources import NativeGpuLease
    from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence, OwnerView
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        SceneDecision,
        SceneIntent,
        SceneSnapshot,
        identity,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import visual_request
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.agentic_environment_generation.workflow.split_scene_ports import OwnedSceneStageAdapter
    from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease
    from isaaclab_arena_examples.agentic_environment_generation.foreground_split_scene_ports import (
        ForegroundSplitScenePorts,
    )

    f = split_fixture(tmp_path)
    contract, profile = f.split_contract, f.split_profile
    contract = contract.model_copy(update={"criteria": contract.criteria[:1] if numeric_only else contract.criteria})
    profile = profile.model_copy(
        update={
            "assess": profile.assess.model_copy(
                update={"model_calls": 0 if numeric_only else 1, "model_tokens": 0 if numeric_only else 100}
            )
        }
    )
    gpu = NativeGpuLease(tmp_path / "gpu.lock")
    events = []

    class Worker:
        def __init__(self, kind):
            self.kind, self.cleanups = kind, {}

        def prepare(self, fence, contract, *, timeout_s):
            assert self.kind == "native" or not gpu.held
            assert self.kind == "native" or "ack-capture" in events
            events.append(self.kind + "-prepare")
            return SimpleNamespace(
                registration=WorkerRegistration(
                    registration_id=self.kind,
                    fence=fence,
                    host="synthetic",
                    boot="synthetic",
                    pid=1,
                    pgid=1,
                    sid=1,
                    start_ticks=1,
                )
            )

        def stop_owned(self, prepared, *, timeout_s):
            events.append(self.kind + "-stop")
            evidence = CleanupEvidence(
                registration=prepared.registration,
                evidence_ref=self.kind,
                observation="owned_process_group_stopped",
                remote_effects="unknown",
            )
            self.cleanups[self.kind] = evidence
            return evidence

        def cleanup_verified(self, registration, cleanup):
            return cleanup == self.cleanups.get(self.kind) and cleanup.registration == registration

        def send_capture(self, prepared, intent, candidate, original, contract, *, protect, deadline):
            assert (
                gpu.held and time.time() < deadline <= intent.released_at + intent.reservation.runtime_allowance_seconds
            )
            self.capture_args = intent, candidate, original, contract

        def receive_capture(self, prepared, *, protect):
            assert not ports._interlock._is_owned(), "capture receive must not block local stop"
            return f.capture_stage(*self.capture_args)

        def send_evaluate(
            self, prepared, intent, candidate, original, contract, *, retained_observation, protect, deadline
        ):
            assert time.time() < deadline <= intent.released_at + intent.reservation.runtime_allowance_seconds
            self.evaluate_args = candidate, contract, retained_observation

        def receive_evaluate(self, prepared, *, protect):
            assert not ports._interlock._is_owned(), "evaluator receive must not block local stop"
            candidate, contract, retained_observation = self.evaluate_args
            events.append("numeric-evaluate")
            assert not gpu.held
            # Synthetic owned evaluator seam; real immutable numeric evaluators.
            evaluator = f.fresh_split()
            evaluator.profile = profile
            return evaluator.verify_observation(retained_observation, contract, candidate)

        def send(self, prepared, raw, *, timeout_s):
            assert not gpu.held and "ack-capture" in events
            packet = json.loads(raw)
            assert packet["inputs"]["scene_action"] == "assess"
            assert packet["workflow_execution"]["registration"] == prepared.registration.model_dump(mode="json")
            events.append("model-send")

        def receive(self, prepared, *, protect):
            observation = store.captured
            receipt = f.evidence_store.load_receipt(
                ports._retained[observation.cohort.realization_id][1].candidate,
                observation.cohort,
                kind="observation",
                manifest_digest=observation.verified_manifest_digests[0],
                protect=protect,
            )
            request = visual_request(
                contract.criteria[1], receipt.candidate, receipt.cohort, f.evidence_store, receipt, protect=protect
            )
            raw = json.dumps(
                dict(request, answers=[dict(frame_digest=x["sha256"], visible=True) for x in request["frames"]])
            )
            return SimpleNamespace(output={"raw_response": raw})

    adapter = OwnedSceneStageAdapter(
        native_worker=Worker("native"),
        model_worker=Worker("model"),
        numeric_worker=Worker("numeric"),
        gpu_lease=gpu,
        authorize_native=lambda intent, contract: True,
    )
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    lease = ForegroundOwnerLease(
        private, run_id="run", principal="principal", cleanup_verified=adapter.cleanup_verified
    )

    class Store:
        def __init__(self):
            self.run = SimpleNamespace(state="running", version=1, contract_json=canonical_json(contract))
            self.owner = OwnerView(owner_id=lease.owner_id, owner_epoch=1, dirty=True)
            self.intents, self.captured = {}, None
            self.next("capture")

        def next(self, action):
            self.intent = SceneIntent(
                codec_version=2,
                intent_id=identity(action),
                candidate_id=f.original.candidate_id,
                action=action,
                status="reserved",
                reservation=getattr(profile, action),
                observation_id=(identity("capture", "observation") if action == "assess" else None),
                observation_digest=(identity(self.captured.model_dump(mode="json")) if action == "assess" else None),
            )
            self.update()

        def update(self, **changes):
            self.intent = self.intent.model_copy(update=changes)
            self.intents[self.intent.intent_id] = self.intent

        def get_run(self, run_id):
            return self.run

        def get_owner(self):
            return self.owner

        def get_scene_intent(self, run_id, intent_id):
            return self.intents[intent_id]

        def get_scene_capture(self, run_id, intent_id):
            return self.captured

        def get_generation_attempt(self, run_id):
            return SimpleNamespace(
                admitted_at=time.time() - (contract.budget.total_deadline_seconds + 1 if expired else 0)
            )

        def scene_snapshot(self, run_id):
            return SceneSnapshot(
                self.run,
                f.original,
                f.original,
                SceneDecision(action=self.intent.action, reason="test"),
                self.intent,
                profile,
            )

        def claim_scene_worker(self, run_id, intent_id, owner_id, owner_epoch):
            fence = AttemptFence(
                run_id=run_id,
                intent_id=intent_id,
                attempt_id=self.intent.action,
                generation=1,
                owner_id=owner_id,
                owner_epoch=owner_epoch,
            )
            self.update(worker_fence=fence)
            return fence

        def register_scene_worker(self, fence, registration):
            self.update(worker_registration=registration)

        def release_scene(self, *args, **kwargs):
            self.update(status="released", released_at=time.time())
            return True

        def check_scene_release(self, *args, **kwargs):
            return self.intent

        def acknowledge_scene_cleanup(self, fence, cleanup):
            self.update(worker_cleanup=cleanup)
            events.append("ack-" + self.intent.action)

        def mark_scene_unknown(self, *args):
            self.run.state = "reconciliation_required"

        def finish_scene(self, run_id, intent_id, version, result):
            assert self.intent.worker_cleanup is not None and not gpu.held
            self.update(status="produced")
            if self.intent.action == "capture":
                self.captured = result.observation
                self.next("assess")
            else:
                assert result.observation.evidence[0] == self.captured.evidence[0]
                assert all(e.verdict == "established" for e in result.observation.evidence)
                self.run.state = "accepted"

    store = Store()
    authority = SimpleNamespace(
        store=store,
        require_read=lambda *_: None,
        require_scene_execute=lambda *args, **kwargs: "auth",
        release_guard=lambda *args, **kwargs: nullcontext(),
        require_workflow_model_bounds=lambda *_: {
            role: f.ceiling.per_call_bound for role in ("generation", "assessment")
        },
        private_model_config=lambda *args, **kwargs: {},
        private_model_deadline=lambda *args, **kwargs: time.time() + 60,
        clock=time.time,
    )
    try:
        ports = ForegroundSplitScenePorts(
            store=store,
            authority=authority,
            lease=lease,
            worker=adapter,
            principal="principal",
            run_id="run",
            catalogue_sha256="a" * 64,
            artifact_root=tmp_path / "artifacts",
            ready=lambda _: "ready",
            profile=profile,
            artifacts=f.evidence_store,
            protect=lambda _: None,
            model_ceilings={role: f.ceiling for role in ("generation", "assessment")},
            capture_start_step=4,
            capture_steps=2,
            capture_timeout_seconds=5,
            output_root=tmp_path / "capture",
            direct_root_subjects=(f.subject,),
            displacement_tolerance_m=0.001,
        )
        service = WorkflowService(store, authority, None, validate_support=ports.admit)
        result = service.run_scene("principal", "run", ports=ports)
        if expired:
            assert result.run.state == "reconciliation_required"
            assert f.events == []  # No native dispatch or subsequent model process.
            assert events == ["native-prepare", "native-stop", "ack-capture"]
            assert not gpu.held
            lease.require_held("run", "principal")
            return
        assert result.run.state == "accepted", events
        assert f.events == ["capture-stage"]
        assert not gpu.held
        lease.require_held("run", "principal")  # GPU release never releases workflow ownership.
        assert "numeric-evaluate" in events if numeric_only else "model-send" in events
        assert ("model-prepare" in events) is not numeric_only
    finally:
        ports.stop_local()
        prepared = ports.prepared_workers[-1]
        lease.release_after_cleanup(prepared.registration, ports._cleanups[prepared.registration.fence.intent_id])
        f.area.close()
