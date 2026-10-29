# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Shared synthetic scene fixtures; no native physical or model claims."""


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


def artifacts(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import SceneEvidenceArtifacts

    area = ArtifactArea.create(tmp_path / "artifacts", store_id="store", registry_id="registry")
    return area, SceneEvidenceArtifacts(area)


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
        envelope = feedback["repair_permissions"]
        assert envelope["codec"] == "scene-repair-permissions-v1"
        assert envelope["original"]["candidate_id"] == original.candidate_id
        assert envelope["current"]["candidate_id"] == parent.candidate_id
        assert envelope["allowed_paths"] == [r.schema_path for r in contract.allowed_interventions]
        assert envelope["allowed_axes"] == ["x", "y"]
        assert envelope["admissible_disk"]["radius_m"] == 0.1
        assert envelope["preserve_all_other_fields"] is True
        assert envelope["forbidden_changes"] == ["task", "physics", "z", "topology"]
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
