# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Small explicit scene producers; no simulator/model construction or policy claims.

The application supplies frozen criteria and trusted capture callbacks. Retained
bytes prove integrity, not authenticity of a caller's measurement source.
"""

import base64
import hashlib
import json
import math
from types import MappingProxyType

from .contracts import Criterion
from .evidence import CriterionEvidence
from .scene_evidence_artifacts import canonical

# producer -> (kind, modality, units, comparison, exact supported rubric)
PRODUCER_REGISTRY = MappingProxyType({
    "scene.linear-speed": ("runtime", "state", "m_per_s", "le", "maximum linear speed"),
    "scene.settled": ("runtime", "state", "boolean", "eq", "linear and angular speeds below settling thresholds"),
    "scene.filtered-support": ("runtime", "state", "N", "ge", "filtered contact with settled proximity"),
    "scene.visible": ("visual", "rgb", "boolean", "eq", "subject visible in every retained frame"),
})
EVALUATOR_VERSION = "1"
MAX_SAMPLES = 256
SUPPORT_THRESHOLDS = MappingProxyType({"linear_m_per_s": 0.01, "angular_rad_per_s": 0.05, "xy_m": 0.05})


def admit_criterion(criterion):
    """Reject unsupported semantics before any native/model callback is invoked."""
    criterion = Criterion.model_validate(criterion.model_dump(mode="python"))
    profile = PRODUCER_REGISTRY.get(criterion.evidence_producer)
    if profile is None or criterion.evaluator_version != EVALUATOR_VERSION:
        raise ValueError("unsupported producer/version")
    kind, modality, unit, operator, rubric = profile
    if (
        criterion.kind,
        criterion.required_modalities,
        criterion.limit.unit,
        criterion.limit.operator,
        criterion.rubric,
    ) != (kind, (modality,), unit, operator, rubric):
        raise ValueError("unsupported criterion semantics")
    if (
        criterion.limit.value < 0
        or criterion.observation_window.end_step - criterion.observation_window.start_step >= MAX_SAMPLES
    ):
        raise ValueError("unsupported threshold/window")
    count = 2 if criterion.evidence_producer == "scene.filtered-support" else 1
    if criterion.evidence_producer == "scene.settled" and criterion.limit.value != 1:
        raise ValueError("unsupported settling threshold")
    if criterion.kind == "visual":
        if criterion.limit.value != 1 or not 1 <= len(criterion.coordinate_frames) <= 4:
            raise ValueError("unsupported visual profile")
    elif criterion.coordinate_frames != ("world",):
        raise ValueError("unsupported frame")
    if len(criterion.subjects) != count or len(set(criterion.subjects)) != count:
        raise ValueError("unsupported frame/subjects")
    return criterion


def _vector(value):
    if (
        type(value) is not list
        or len(value) != 3
        or any(type(x) not in (int, float) or not math.isfinite(x) for x in value)
    ):
        raise ValueError("missing/nonfinite vector")
    return value


def _bound_payload(candidate, cohort, artifacts, receipt, protect):
    if receipt.candidate != candidate or receipt.cohort != cohort:
        raise ValueError("stale or cross-cohort evidence")
    payload = artifacts.verified_payload(receipt, protect=protect)
    if payload.get("kind") != "observation" or payload.get("provenance") not in ("synthetic", "native-unverified"):
        raise ValueError("unsupported observation provenance")
    return payload


def _norm(value):
    result = math.hypot(*_vector(value))
    if not math.isfinite(result):
        raise ValueError("nonfinite derived measurement")
    return result


def _evidence(criterion, candidate, cohort, receipt, verdict, limitations):
    digest = hashlib.sha256(canonical(criterion.model_dump(mode="json"))).hexdigest()
    return CriterionEvidence(
        criterion_id=criterion.criterion_id,
        criterion_digest=digest,
        producer_id=criterion.evidence_producer,
        observed_coordinate_frames=criterion.coordinate_frames,
        observed_step_window=(criterion.observation_window.start_step, criterion.observation_window.end_step),
        subject_ids=criterion.subjects,
        modality="visual" if criterion.kind == "visual" else "measured",
        evaluator_version=criterion.evaluator_version,
        rubric_id=digest,
        candidate_digest=candidate.candidate_digest,
        cohort=cohort,
        manifest_digest=receipt.manifest_digest,
        verdict=verdict,
        limitations=tuple(limitations),
    )


def _window(criterion, cohort, payload):
    samples = payload.get("samples")
    start, end = criterion.observation_window.start_step, criterion.observation_window.end_step
    if type(samples) is not list or not 1 <= len(samples) <= MAX_SAMPLES:
        raise ValueError("insufficient_window")
    steps = [s.get("step") for s in samples]
    if any(type(s) is not int for s in steps) or steps != list(range(start, end + 1)):
        raise ValueError("insufficient_window")
    if cohort.frame_id != "world" or any(s.get("frame") != "world" for s in samples):
        raise ValueError("wrong_frame")
    return samples


def evaluate_measurement(criterion, candidate, cohort, artifacts, receipt, *, protect):
    """Evaluate frozen numeric limits from verified retained raw samples only."""
    criterion = admit_criterion(criterion)
    if criterion.kind == "visual":
        raise ValueError("visual producer is not a measurement")
    payload = _bound_payload(candidate, cohort, artifacts, receipt, protect)
    limitations = [
        (
            "synthetic_inputs_no_native_physical_claim"
            if payload["provenance"] == "synthetic"
            else "native_sampler_not_independently_validated"
        ),
        "not_policy_success_or_causality",
    ]
    try:
        samples = _window(criterion, cohort, payload)
        if criterion.evidence_producer == "scene.filtered-support":
            limitations.append("filtered_contact_proximity_not_load_bearing_certification")
            # Evaluate every sample even after a failure: missing coverage is not a measured violation.
            passes = [_support(s, criterion) for s in samples]
            verdict = "established" if all(passes) else "violated"
        elif criterion.evidence_producer == "scene.settled":
            limitations.append("settling_does_not_establish_support")
            values = [s["subjects"][criterion.subjects[0]] for s in samples]
            linear = [_norm(v["linear_velocity_w"]) for v in values]
            angular = [_norm(v["angular_velocity_w"]) for v in values]
            settled = (
                max(linear) < SUPPORT_THRESHOLDS["linear_m_per_s"]
                and max(angular) < SUPPORT_THRESHOLDS["angular_rad_per_s"]
            )
            verdict = "established" if settled else "violated"
        else:
            speeds = [_norm(s["subjects"][criterion.subjects[0]]["linear_velocity_w"]) for s in samples]
            verdict = "established" if max(speeds) <= criterion.limit.value else "violated"
    except (KeyError, TypeError, ValueError, OverflowError):
        verdict = "inconclusive"
        limitations.append("missing_invalid_or_insufficient_measurement")
    return _evidence(criterion, candidate, cohort, receipt, verdict, limitations)


class ObservationRecorder:
    """Trusted capture callback with detached samples and bounded exact image bytes."""

    def __init__(self, sample_state, *, provenance):
        if provenance not in ("synthetic", "native-unverified"):
            raise ValueError("unsupported provenance")
        self.sample_state = sample_state
        self.provenance = provenance
        self.samples = []
        self.frames = []

    def __call__(self, env, step):
        if type(step) is not int or step < 0 or len(self.samples) >= MAX_SAMPLES:
            raise ValueError("sample bound")
        value = json.loads(canonical(self.sample_state(env, step)))
        if value.get("step") != step or (self.samples and step <= self.samples[-1]["step"]):
            raise ValueError("sample step mismatch")
        canonical(self.payload() | {"samples": self.samples + [value]})
        self.samples.append(value)

    def add_frame(self, *, camera, step, subject_ids, image_bytes):
        """Retain supplied PNG bytes, without asserting they are native camera output."""
        if type(image_bytes) is not bytes or not 1 <= len(image_bytes) <= 128 * 1024 or len(self.frames) >= 16:
            raise ValueError("image bound")
        if type(step) is not int or step not in [s["step"] for s in self.samples]:
            raise ValueError("frame outside retained samples")
        if any((f["camera"], f["step"]) == (camera, step) for f in self.frames):
            raise ValueError("duplicate frame")
        frame = {
            "camera": camera,
            "step": step,
            "subjects": list(subject_ids),
            "encoding": "base64",
            "sha256": hashlib.sha256(image_bytes).hexdigest(),
            "bytes": base64.b64encode(image_bytes).decode("ascii"),
        }
        canonical(self.payload() | {"frames": self.frames + [frame]})
        self.frames.append(frame)

    def payload(self):
        return json.loads(
            canonical(
                {"kind": "observation", "provenance": self.provenance, "samples": self.samples, "frames": self.frames}
            )
        )


def visual_request(criterion, candidate, cohort, artifacts, observation, *, protect):
    """Build exact per-frame visibility rubric coverage; performs no model call."""
    criterion = admit_criterion(criterion)
    if criterion.kind != "visual":
        raise ValueError("visual visibility only")
    payload = _bound_payload(candidate, cohort, artifacts, observation, protect)
    _window(criterion, cohort, payload)
    frames = payload.get("frames")
    if type(frames) is not list or not 1 <= len(frames) <= 16:
        raise ValueError("missing bounded frames")
    start, end = criterion.observation_window.start_step, criterion.observation_window.end_step
    expected = {(camera, step) for camera in criterion.coordinate_frames for step in range(start, end + 1)}
    if {(f["camera"], f["step"]) for f in frames} != expected or len(frames) != len(expected):
        raise ValueError("camera/window coverage mismatch")
    identities = []
    for frame in frames:
        raw = base64.b64decode(frame["bytes"], validate=True)
        if (
            frame["encoding"] != "base64"
            or not 1 <= len(raw) <= 128 * 1024
            or hashlib.sha256(raw).hexdigest() != frame["sha256"]
            or frame["subjects"] != list(criterion.subjects)
        ):
            raise ValueError("image binding mismatch")
        identities.append({k: frame[k] for k in ("camera", "step", "subjects", "sha256")})
    return {
        "criterion_id": criterion.criterion_id,
        "criterion_digest": hashlib.sha256(canonical(criterion.model_dump(mode="json"))).hexdigest(),
        "rubric": criterion.rubric,
        "candidate": candidate.model_dump(mode="json"),
        "cohort": cohort.model_dump(mode="json"),
        "observation_manifest_digest": observation.manifest_digest,
        "step_window": [start, end],
        "frames": identities,
    }


def retain_visual_answer(criterion, candidate, cohort, artifacts, observation, raw_response, *, protect):
    """Keep exact raw UTF-8 response bytes, including rejected answers, without transport."""
    request = visual_request(criterion, candidate, cohort, artifacts, observation, protect=protect)
    if type(raw_response) is not bytes or not 1 <= len(raw_response) <= 65536:
        raise ValueError("response byte bound")
    text = raw_response.decode("utf-8")
    return artifacts.write(
        candidate,
        cohort,
        {
            "kind": "visual-answer",
            "request": request,
            "raw_response": text,
            "response_sha256": hashlib.sha256(raw_response).hexdigest(),
        },
        protect=protect,
    )


def evaluate_visual_answer(criterion, candidate, cohort, artifacts, observation, answer, *, protect):
    """Derive visibility from bound per-frame answers, never aggregate satisfaction."""
    request = visual_request(criterion, candidate, cohort, artifacts, observation, protect=protect)
    if answer.candidate != candidate or answer.cohort != cohort:
        raise ValueError("answer cohort mismatch")
    payload = artifacts.verified_payload(answer, protect=protect)
    if payload["kind"] != "visual-answer" or canonical(payload["request"]) != canonical(request):
        raise ValueError("answer request mismatch")
    raw = payload["raw_response"].encode("utf-8")
    if hashlib.sha256(raw).hexdigest() != payload["response_sha256"]:
        raise ValueError("raw response mismatch")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate answer field")
            value[key] = item
        return value

    response = json.loads(raw, object_pairs_hook=unique)
    answers = response.pop("answers", None)
    if canonical(response) != canonical(request) or type(answers) is not list or len(answers) != len(request["frames"]):
        raise ValueError("exact criterion/rubric/coverage required")
    for item, frame in zip(answers, request["frames"]):
        if (
            set(item) != {"frame_digest", "visible"}
            or item["frame_digest"] != frame["sha256"]
            or type(item["visible"]) is not bool
        ):
            raise ValueError("per-frame answer binding required")
    source = artifacts.verified_payload(observation, protect=protect)
    limitations = ["visual_visibility_only_not_support_causality_or_policy_success"]
    if source["provenance"] == "synthetic":
        limitations.append("synthetic_inputs_no_native_physical_claim")
    return _evidence(
        criterion,
        candidate,
        cohort,
        answer,
        "established" if all(a["visible"] for a in answers) else "violated",
        limitations,
    )


def effective_displacement(artifacts, before, after, *, subject, step, target_local, mapping, tolerance_m, protect):
    """Check a realized translation, not repair success, using explicit origin mapping.

    AtPositionLossStrategy consumes solver positions directly. write_layout_to_sim
    adds env_origins after layout_pose_to_scene_writes. This profile applies ONLY
    where that asset mapping is an identity root translation; the caller must
    establish that mapping, not infer it from an AtPosition relation's existence.
    """
    if (
        mapping != "direct-root-translation-v1"
        or type(tolerance_m) not in (int, float)
        or not math.isfinite(tolerance_m)
        or tolerance_m <= 0
    ):
        raise ValueError("explicit mapping and positive finite tolerance required")
    if (
        before.candidate.candidate_digest == after.candidate.candidate_digest
        or before.cohort.realization_id == after.cohort.realization_id
        or before.candidate.contract_digest != after.candidate.contract_digest
        or before.candidate.profile_digest != after.candidate.profile_digest
    ):
        raise ValueError("fresh candidate/realization with frozen contract/profile required")
    target_local = _vector(target_local)
    positions = []
    origins = []
    world_positions = []
    for receipt in (before, after):
        payload = _bound_payload(receipt.candidate, receipt.cohort, artifacts, receipt, protect)
        samples = [s for s in payload["samples"] if type(s["step"]) is int and s["step"] == step]
        if len(samples) != 1 or samples[0]["frame"] != "world" or receipt.cohort.frame_id != "world":
            raise ValueError("exact world sample required")
        origin = _vector(samples[0]["origin_w"])
        world = _vector(samples[0]["subjects"][subject]["position_w"])
        origins.append(origin)
        world_positions.append(world)
        positions.append([p - o for p, o in zip(world, origin)])
    displacement = math.dist(*positions)
    world_displacement = math.dist(*world_positions)
    error = math.dist(positions[1], target_local)
    if not all(math.isfinite(value) for value in (displacement, world_displacement, error)):
        raise ValueError("nonfinite derived displacement")
    return {
        "effective": displacement > tolerance_m and world_displacement > tolerance_m and error <= tolerance_m,
        "displacement_m": displacement,
        "world_displacement_m": world_displacement,
        "target_error_m": error,
        "target_world": [p + o for p, o in zip(target_local, origins[1])],
        "mapping": mapping,
        "before_manifest_digest": before.manifest_digest,
        "after_manifest_digest": after.manifest_digest,
        "limitations": ["translation_only_not_support_or_repair_success", "source_authenticity_not_established"],
    }


def make_native_sampler(criteria, *, subject_names, contact_sensors=None):
    """Create a lazy callback for an already initialized single Arena environment.

    Reuses native pose/velocity, settling and destination predicates. Diagnostic
    predicate booleans are retained but NEVER consumed as measurement proof.
    No SimulationApp, env, policy or model is constructed. Native execution still
    requires separate runtime/profile validation; this slice tests synthetic inputs.
    """
    criteria = tuple(admit_criterion(c) for c in criteria)
    subjects = {s for c in criteria for s in c.subjects}
    if (
        not criteria
        or set(subject_names) != subjects
        or any(type(n) is not str or not n for n in subject_names.values())
    ):
        raise ValueError("exact subject scene-name mapping required")
    names = dict(subject_names)
    sensors = dict(contact_sensors or {})
    for c in criteria:
        if c.evidence_producer == "scene.filtered-support" and c.subjects not in sensors:
            raise ValueError("explicit support sensor binding required")

    def sample_state(env, step):
        import warp as wp
        from isaaclab.managers import SceneEntityCfg

        from isaaclab_arena.tasks.predicates.object_settling import objects_settled
        from isaaclab_arena.tasks.predicates.predicate_utils import (
            get_env,
            get_root_ang_vel_w,
            get_root_lin_vel_w,
            get_root_pos_w,
        )
        from isaaclab_arena.tasks.predicates.spatial import object_on_destination

        native = get_env(env)
        if native.num_envs != 1:
            raise ValueError("single environment native profile required")

        def vector(tensor):
            return tensor[0].detach().cpu().tolist()

        result = {
            "step": step,
            "frame": "world",
            "origin_w": vector(native.scene.env_origins),
            "subjects": {},
            "contacts": [],
            "diagnostic_predicates": {},
        }
        for subject, name in names.items():
            result["subjects"][subject] = {
                "prim_path": native.scene[name].cfg.prim_path,
                "position_w": vector(get_root_pos_w(native, name)),
                "linear_velocity_w": vector(get_root_lin_vel_w(native, name)),
                "angular_velocity_w": vector(get_root_ang_vel_w(native, name)),
            }
        result["diagnostic_predicates"]["objects_settled"] = bool(
            objects_settled(
                native,
                list(names.values()),
                lin_vel_threshold=SUPPORT_THRESHOLDS["linear_m_per_s"],
                ang_vel_threshold=SUPPORT_THRESHOLDS["angular_rad_per_s"],
                env_id=0,
            ).item()
        )
        for c in criteria:
            if c.evidence_producer != "scene.filtered-support":
                continue
            subject, destination = c.subjects
            sensor_name = sensors[c.subjects]
            sensor = native.scene[sensor_name]
            force = sensor.data.force_matrix_w
            destination_path = native.scene[names[destination]].cfg.prim_path
            filters = list(sensor.cfg.filter_prim_paths_expr)
            if sensor.cfg.prim_path != native.scene[names[subject]].cfg.prim_path:
                raise ValueError("support sensor source mismatch")
            # Exact literal binding only; regex expansion/multiple filtered bodies is unsupported.
            if (
                filters != [destination_path]
                or any(ch in destination_path for ch in "{}*[]")
                or tuple(force.shape) != (1, 1, 1, 3)
            ):
                raise ValueError("unsupported native contact filter")
            result["contacts"].append({
                "subject": subject,
                "destination": destination,
                "filter_paths": filters,
                "destination_path": destination_path,
                "sensor_path": sensor.cfg.prim_path,
                "force_w": wp.to_torch(force)[0, 0, 0].detach().cpu().tolist(),
            })
            result["diagnostic_predicates"][c.criterion_id] = bool(
                object_on_destination(
                    native,
                    object_cfg=SceneEntityCfg(names[subject]),
                    contact_sensor_cfg=SceneEntityCfg(sensor_name),
                    force_threshold=c.limit.value,
                    velocity_threshold=SUPPORT_THRESHOLDS["linear_m_per_s"],
                    destination_cfg=SceneEntityCfg(names[destination]),
                    max_xy_separation=SUPPORT_THRESHOLDS["xy_m"],
                )[0].item()
            )
        return result

    return sample_state


def _support(sample, criterion):
    subject, destination = criterion.subjects
    obj, target = sample["subjects"][subject], sample["subjects"][destination]
    contacts = [c for c in sample["contacts"] if (c["subject"], c["destination"]) == (subject, destination)]
    if len(contacts) != 1 or contacts[0]["filter_paths"] != [contacts[0]["destination_path"]]:
        raise ValueError("unverified contact filter")
    if not contacts[0]["destination_path"]:
        raise ValueError("missing destination path")
    if contacts[0]["sensor_path"] != obj["prim_path"] or contacts[0]["destination_path"] != target["prim_path"]:
        raise ValueError("contact endpoints differ from measured subjects")
    force = _norm(contacts[0]["force_w"])
    linear = _norm(obj["linear_velocity_w"])
    angular = _norm(obj["angular_velocity_w"])
    a, b = _vector(obj["position_w"]), _vector(target["position_w"])
    distance = math.hypot(a[0] - b[0], a[1] - b[1])
    return (
        force >= criterion.limit.value
        and force > 0
        and linear < SUPPORT_THRESHOLDS["linear_m_per_s"]
        and angular < SUPPORT_THRESHOLDS["angular_rad_per_s"]
        and distance < SUPPORT_THRESHOLDS["xy_m"]
    )
