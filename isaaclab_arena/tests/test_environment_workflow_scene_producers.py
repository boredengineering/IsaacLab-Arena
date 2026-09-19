# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Synthetic inputs only: these tests establish no native physical or model claims."""

import pytest


def identities():
    from isaaclab_arena.agentic_environment_generation.workflow.evidence import CandidateBinding, EvidenceCohort

    candidate = CandidateBinding(candidate_digest="a" * 64, contract_digest="b" * 64, profile_digest="c" * 64)
    cohort = EvidenceCohort(
        realization_id="r1",
        reset_id="reset1",
        environment_id="env0",
        window_id="w1",
        frame_id="world",
        contract_digest="b" * 64,
        profile_digest="c" * 64,
    )
    return candidate, cohort


def criterion(producer="scene.linear-speed", **updates):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import Criterion

    return Criterion(**(
        dict(
            criterion_id="speed",
            kind="runtime",
            evidence_producer=producer,
            requirement="required",
            evaluator_version="1",
            required_modalities=("state",),
            coordinate_frames=("world",),
            observation_window={"start_step": 0, "end_step": 2},
            rubric="maximum linear speed",
            subjects=("cup",),
            limit={"operator": "le", "value": 0.01, "unit": "m_per_s"},
        )
        | updates
    ))


def sample(step, speed=0.0):
    return {
        "step": step,
        "frame": "world",
        "origin_w": [10.0, 0.0, 0.0],
        "subjects": {
            "cup": {
                "position_w": [10.0, 0.0, 1.0],
                "linear_velocity_w": [speed, 0.0, 0.0],
                "angular_velocity_w": [0.0, 0.0, 0.0],
            }
        },
    }


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
            candidate,
            cohort,
            kind="observation",
            manifest_digest=receipt.manifest_digest,
            protect=lambda value: None,
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


def artifacts(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import SceneEvidenceArtifacts

    area = ArtifactArea.create(tmp_path / "artifacts", store_id="store", registry_id="registry")
    return area, SceneEvidenceArtifacts(area)


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


def composed_fixture(tmp_path, *, effective=True, role_ceilings=False):
    """Real schema and retained producers, controlled synthetic runtime/model effects."""
    import json
    import yaml
    from contextlib import contextmanager
    from pathlib import Path
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import ScenePortProfile, candidate_record
    from isaaclab_arena.agentic_environment_generation.workflow.scene_ports import (
        CaptureRuntime,
        ModelCeiling,
        ScenePorts,
    )
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import scene_contract

    scene = yaml.safe_load((Path(__file__).parent / "test_data/pick_and_place_maple_table_env_graph.yaml").read_text())
    # Explicit derived fixture: original authored relation plus unique support.
    subject = "mug_ycb_robolab"
    scene["relations"].append(
        {"kind": "on", "subject": subject, "reference": "maple_table_robolab_table", "params": {}}
    )
    raw = scene_contract().model_dump(mode="python")
    raw["criteria"] = [
        criterion(subjects=(subject,)).model_dump(mode="python"),
        criterion(
            "scene.visible",
            criterion_id="visible",
            subjects=(subject,),
            kind="visual",
            required_modalities=("rgb",),
            coordinate_frames=("wrist",),
            rubric="subject visible in every retained frame",
            limit={"operator": "eq", "value": 1.0, "unit": "boolean"},
        ).model_dump(mode="python"),
    ]
    raw["preserved"] = []
    raw["allowed_interventions"] = [
        dict(
            subject_id=subject,
            schema_path=f"/relations/5/params/{axis}",
            operation="replace",
            coordinate_frame="env_local",
            units="m",
            max_total_displacement_m=0.1,
        )
        for axis in ("x", "y")
    ]
    contract = type(scene_contract()).model_validate(raw)
    common = dict(model_calls=1, model_tokens=100, cost_ceiling_usd=0.0, runtime_allowance_seconds=10.0)
    profile = ScenePortProfile(
        port_id="synthetic-retained",
        assurance="synthetic",
        producer_ids=("scene.linear-speed", "scene.visible"),
        observe=dict(common, observations=1, realizations=1, steps=2),
        repair=dict(common, candidates=1, revisions=1),
    )
    area, evidence_store = artifacts(tmp_path)
    events = []
    original = candidate_record("run", scene, source_id="generation")

    class Flag:
        def any(self):
            return False

    class Env:
        def reset(self):
            return {"camera_obs": {"wrist": b"synthetic-image"}}, {}

        def step(self, action):
            return self.reset()[0], 0, Flag(), Flag(), {}

    class Policy:
        def reset(self):
            pass

        def get_action(self, *args):
            return 0

    @contextmanager
    def capture(*, candidate, contract, cohort):
        events.append("capture")
        position = json.loads(candidate.scene_json)["relations"][5]["params"]

        def state(env, step):
            value = sample(step)
            value["subjects"] = {subject: value["subjects"].pop("cup")}
            value["subjects"][subject]["position_w"] = [
                10 + (position["x"] if effective else 0.65),
                position["y"],
                position["z"],
            ]
            return value

        yield CaptureRuntime(Env(), Policy(), state, lambda image, path: path.write_bytes(image))
        events.append("closed")

    def visual(*, request, frames, allowance):
        events.append("visual")
        allowance.charge()
        assert frames and frames[0]["bytes"]
        visible = request["candidate"]["candidate_digest"] != original.digest
        return json.dumps(
            dict(request, answers=[dict(frame_digest=f["sha256"], visible=visible) for f in request["frames"]])
        ).encode()

    def refine(*, parent, original, feedback, contract, allowance):
        events.append("refine")
        allowance.charge()
        assert parent.candidate_id == original.candidate_id
        assert feedback["assessment"]["failed_ids"] == ["visible"]
        result = json.loads(parent.scene_json)
        result["relations"][5]["params"]["x"] += 0.03
        return result

    ceiling = ModelCeiling(
        max_calls=1,
        max_tokens=100,
        max_cost_usd="0",
        timeout_seconds=5.0,
        per_call_bound=dict(
            version=1,
            attested=True,
            model="synthetic",
            endpoint="synthetic://controlled",
            max_tokens=100,
            max_cost_usd="0",
        ),
    )
    from dataclasses import replace

    role_options = {}
    if role_ceilings:
        role_options["model_ceilings"] = {
            role: replace(ceiling, per_call_bound=dict(ceiling.per_call_bound, model=role))
            for role in ("generation", "assessment")
        }
    ports = ScenePorts(
        **role_options,
        profile=profile,
        artifacts=evidence_store,
        protect=lambda value: None,
        authorize=lambda *args: events.append("authorize"),
        ready=lambda contract: events.append("ready"),
        capture=capture,
        refine=refine,
        visual=visual,
        model_ceiling=None if role_ceilings else ceiling,
        capture_steps=2,
        capture_timeout_seconds=5.0,
        output_root=tmp_path / "capture",
        direct_root_subjects=(subject,),
        displacement_tolerance_m=0.001,
        check_active=lambda: None,
    )
    return SimpleNamespace(**locals())


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
