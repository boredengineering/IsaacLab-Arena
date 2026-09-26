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
import operator
from types import MappingProxyType

from .contracts import Criterion
from .evidence import CriterionEvidence
from .observation_schedule import CollectionFailure
from .observation_schedule import compile_acquisition as _compile_acquisition
from .observation_schedule import criterion_coverage, select_frames, select_samples, validate_collection, validate_png
from .scene_evidence_artifacts import _protected, assessment_identity, canonical
from .ternary_evidence import validate_ternary_response

# (producer, evaluator) -> (kind, modality, units, comparison, exact supported rubric)
PRODUCER_REGISTRY = MappingProxyType({
    ("scene.linear-speed", "1"): ("runtime", "state", "m_per_s", "le", "maximum linear speed"),
    ("scene.settled", "1"): (
        "runtime",
        "state",
        "boolean",
        "eq",
        "linear and angular speeds below settling thresholds",
    ),
    ("scene.filtered-support", "1"): ("runtime", "state", "N", "ge", "filtered contact with settled proximity"),
    ("scene.visible", "1"): ("visual", "rgb", "boolean", "eq", "subject visible in every retained frame"),
    ("scene.linear-speed", "numeric-v2"): (
        "runtime",
        "state",
        "m_per_s",
        ("lt", "le", "eq", "ge", "gt"),
        "selected velocity norm",
    ),
    ("scene.settled", "numeric-v2"): ("runtime", "state", "boolean", ("eq",), "selected stationary limits"),
    ("scene.xy-target-error", "numeric-v2"): ("geometry", "state", "m", ("lt", "le"), "selected world XY target error"),
    ("scene.visible", "full-scene-ternary-v1"): ("visual", "rgb", "boolean", ("eq",), "selected per-frame visibility"),
})
EVALUATOR_VERSION = "1"
MAX_SAMPLES = 256
SUPPORT_THRESHOLDS = MappingProxyType({"linear_m_per_s": 0.01, "angular_rad_per_s": 0.05, "xy_m": 0.05})


def compile_acquisition(plan, criteria, *, candidate, cohort):
    """Compile explicit acquisition through the existing producer facade."""
    return _compile_acquisition(plan, criteria, candidate=candidate, cohort=cohort)


def admit_criterion(criterion):
    """Reject unsupported semantics before any native/model callback is invoked."""
    criterion = Criterion.model_validate(criterion.model_dump(mode="python"))
    if criterion.evaluator_version == "full-scene-ternary-v1":
        profile = PRODUCER_REGISTRY.get((criterion.evidence_producer, criterion.evaluator_version))
        parameters = criterion.parameters
        if profile is None or parameters is None or parameters.metric != "visibility":
            raise ValueError("unsupported full-scene visual capability")
        kind, modality, unit, operators, rubric = profile
        if (
            (criterion.kind, criterion.required_modalities, criterion.limit.unit, criterion.rubric)
            != (kind, (modality,), unit, rubric)
            or criterion.limit.operator not in operators
            or criterion.limit.value != 1
            or not 1 <= len(criterion.subjects) <= 16
            or len(set(criterion.subjects)) != len(criterion.subjects)
            or set(criterion.coordinate_frames) != {image.camera for image in parameters.images}
            or len(set(criterion.coordinate_frames)) != len(criterion.coordinate_frames)
        ):
            raise ValueError("unsupported full-scene visual semantics")
        return criterion
    if criterion.evaluator_version == "numeric-v2":
        profile = PRODUCER_REGISTRY.get((criterion.evidence_producer, criterion.evaluator_version))
        if profile is None or criterion.parameters is None:
            raise ValueError("unsupported parameterized producer/version")
        kind, modality, unit, operators, rubric = profile
        if (
            (criterion.kind, criterion.required_modalities, criterion.limit.unit, criterion.rubric)
            != (kind, (modality,), unit, rubric)
            or criterion.limit.operator not in operators
            or criterion.limit.value < 0
            or criterion.coordinate_frames != ("world",)
            or not 1 <= len(criterion.subjects) <= 16
            or len(set(criterion.subjects)) != len(criterion.subjects)
            or criterion.parameters.metric
            != {
                "scene.linear-speed": "linear_speed",
                "scene.settled": "stationary",
                "scene.xy-target-error": "xy_target_error",
            }.get(criterion.evidence_producer)
            or (criterion.evidence_producer == "scene.settled" and criterion.limit.value != 1)
        ):
            raise ValueError("unsupported parameterized criterion semantics")
        return criterion
    if criterion.evaluator_version == "visibility-v2":
        if (
            criterion.evidence_producer != "scene.visible"
            or criterion.kind != "visual"
            or criterion.required_modalities != ("rgb",)
            or criterion.limit.unit != "boolean"
            or criterion.limit.operator != "eq"
            or criterion.limit.value != 1
            or criterion.observation_window.start_step != criterion.observation_window.end_step
            or not 1 <= len(criterion.subjects) <= 16
            or len(set(criterion.subjects)) != len(criterion.subjects)
            or not 1 <= len(criterion.coordinate_frames) <= 4
            or len(set(criterion.coordinate_frames)) != len(criterion.coordinate_frames)
        ):
            raise ValueError("Unsupported retained visibility criterion")
        return criterion
    profile = PRODUCER_REGISTRY.get((criterion.evidence_producer, criterion.evaluator_version))
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
    if payload.get("codec") == "observation-v2":
        validate_collection(payload, candidate=candidate, cohort=cohort)
    return payload


def _norm(value):
    result = math.hypot(*_vector(value))
    if not math.isfinite(result):
        raise ValueError("nonfinite derived measurement")
    return result


def _evidence(criterion, candidate, cohort, receipt, verdict, limitations, *, assessment_id=None, conflict=None):
    digest = hashlib.sha256(canonical(criterion.model_dump(mode="json"))).hexdigest()
    selected = (
        {}
        if criterion.parameters is None
        else dict(
            coverage=criterion_coverage(criterion),
            assessment_id=assessment_id,
            conflict=False if conflict is None else conflict,
        )
    )
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
        **selected,
    )


def _window(criterion, cohort, payload):
    if criterion.parameters is not None:
        if criterion.parameters.metric == "visibility":
            return select_frames(criterion, payload, cohort)
        return select_samples(criterion, payload, cohort)
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
    if criterion.evaluator_version == "numeric-v2":
        samples = _window(criterion, cohort, payload)
        parameters = criterion.parameters
        assert parameters is not None
        subject_passes = []
        for subject in criterion.subjects:
            values = []
            for sample in samples:
                measured = sample["subjects"][subject]
                if parameters.metric == "stationary":
                    passed = _compare_limit(_norm(measured["linear_velocity_w"]), parameters.linear_limit)
                    passed = _compare_limit(_norm(measured["angular_velocity_w"]), parameters.angular_limit) and passed
                elif parameters.metric == "xy_target_error":
                    position = _vector(measured["position_w"])
                    error = _norm(
                        [position[0] - parameters.target_xy_m[0], position[1] - parameters.target_xy_m[1], 0.0]
                    )
                    passed = _compare_limit(error, criterion.limit)
                else:
                    passed = _compare_limit(_norm(measured["linear_velocity_w"]), criterion.limit)
                values.append(passed)
            subject_passes.append((all if parameters.temporal_aggregation == "all" else any)(values))
        passed = (all if parameters.subject_aggregation == "all" else any)(subject_passes)
        return _evidence(criterion, candidate, cohort, receipt, "established" if passed else "violated", limitations)
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


def _compare_limit(value, limit):
    return {"lt": operator.lt, "le": operator.le, "eq": operator.eq, "ge": operator.ge, "gt": operator.gt}[
        limit.operator
    ](value, limit.value)


class ObservationRecorder:
    """Trusted capture callback with detached samples and bounded exact image bytes."""

    def __init__(self, sample_state, *, provenance, acquisition=None):
        if provenance not in ("synthetic", "native-unverified"):
            raise ValueError("unsupported provenance")
        self.sample_state = sample_state
        self.provenance = provenance
        self.samples = []
        self.frames = []
        self.acquisition = acquisition
        self._last_step = -1
        self._collection = {"status": "incomplete"}

    def __call__(self, env, step):
        if self.acquisition is not None:
            if type(step) is not int or not 0 <= step <= self.acquisition.plan.horizon_steps or step <= self._last_step:
                raise CollectionFailure(reason="duplicate_or_invalid_step")
            self._last_step = step
            if step not in self.acquisition.state_steps:
                return
        if type(step) is not int or step < 0 or len(self.samples) >= MAX_SAMPLES:
            raise ValueError("sample bound")
        try:
            value = json.loads(canonical(self.sample_state(env, step)))
        except (ValueError, TypeError) as error:
            if self.acquisition is not None:
                raise CollectionFailure(reason="invalid_numeric_sample") from error
            raise
        if value.get("step") != step or (self.samples and step <= self.samples[-1]["step"]):
            raise ValueError("sample step mismatch")
        if self.acquisition is not None:
            if type(value["step"]) is not int or value.get("frame") != self.acquisition.plan.reference_frame:
                raise CollectionFailure(reason="sample_clock_or_frame_mismatch")
            value.update(self.acquisition.observation_identity(step))
            if "measured_clocks" in value:
                import math

                clocks = value["measured_clocks"]
                measured = clocks.get("simulation_time_seconds")
                if (
                    clocks.get("control_step") != step
                    or clocks.get("reset_count") != 1
                    or type(measured) not in (int, float)
                    or not math.isfinite(measured)
                    or not math.isclose(measured, value["time_seconds"], abs_tol=1e-7, rel_tol=1e-7)
                ):
                    raise CollectionFailure(reason="measured_acquisition_clock_mismatch")
                value["time_seconds"] = measured
        canonical(self.payload() | {"samples": self.samples + [value]})
        self.samples.append(value)

    def add_frame(self, *, camera, step, subject_ids, image_bytes, sensor_update_step=None, sensor_sequence=None):
        """Retain supplied PNG bytes, without asserting they are native camera output."""
        if type(image_bytes) is not bytes or not 1 <= len(image_bytes) <= 128 * 1024 or len(self.frames) >= 16:
            raise ValueError("image bound")
        if self.acquisition is None and (type(step) is not int or step not in [s["step"] for s in self.samples]):
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
        if self.acquisition is not None:
            validate_png(image_bytes)
            frame.update(self.acquisition.observation_identity(step, camera=camera))
            if (
                type(sensor_update_step) is not int
                or sensor_update_step != step
                or type(sensor_sequence) is not int
                or sensor_sequence < 0
                or tuple(subject_ids) != self.acquisition.plan.subjects
            ):
                raise CollectionFailure(reason="sensor_time_or_subject_coverage")
            frame.update(sensor_update_step=sensor_update_step, sensor_sequence=sensor_sequence)
        canonical(self.payload() | {"frames": self.frames + [frame]})
        self.frames.append(frame)

    def payload(self):
        if self.acquisition is not None:
            return json.loads(
                canonical(
                    dict(
                        kind="observation",
                        codec="observation-v2",
                        provenance=self.provenance,
                        acquisition=self.acquisition.metadata(),
                        collection=self._collection,
                        samples=self.samples,
                        frames=self.frames,
                    )
                )
            )
        return json.loads(
            canonical(
                {"kind": "observation", "provenance": self.provenance, "samples": self.samples, "frames": self.frames}
            )
        )

    def complete(self, *, executed_steps, reset_count, terminated, truncated):
        """Finalize valid collection, not a scientific passing result."""
        if self.acquisition is None:
            raise ValueError("explicit acquisition required for collection completion")
        status = dict(
            status="complete",
            executed_steps=executed_steps,
            reset_count=reset_count,
            terminated=terminated,
            truncated=truncated,
        )
        payload = self.payload() | {"collection": status}
        validate_collection(payload, candidate=self.acquisition.candidate, cohort=self.acquisition.cohort)
        self._collection = status
        return payload


def visual_request(criterion, candidate, cohort, artifacts, observation, *, protect):
    """Build exact per-frame visibility rubric coverage; performs no model call."""
    criterion = admit_criterion(criterion)
    if criterion.kind != "visual":
        raise ValueError("visual visibility only")
    payload = _bound_payload(candidate, cohort, artifacts, observation, protect)
    if criterion.evaluator_version == "full-scene-ternary-v1":
        frames = _window(criterion, cohort, payload)
        if any(not set(criterion.subjects) <= set(frame["subjects"]) for frame in frames):
            raise ValueError("visual subject coverage mismatch")
        parameters = criterion.parameters
        request = dict(
            answer_schema="full-scene-ternary-v1",
            criterion_id=criterion.criterion_id,
            criterion=criterion.model_dump(mode="json"),
            criterion_digest=hashlib.sha256(canonical(criterion.model_dump(mode="json"))).hexdigest(),
            rubric=criterion.rubric,
            candidate=candidate.model_dump(mode="json"),
            cohort=cohort.model_dump(mode="json"),
            observation_manifest_digest=observation.manifest_digest,
            acquisition_id=payload["acquisition"]["acquisition_id"],
            step_window=[criterion.observation_window.start_step, criterion.observation_window.end_step],
            aggregation=dict(
                temporal=parameters.temporal_aggregation,
                camera=parameters.camera_aggregation,
                subject=parameters.subject_aggregation,
            ),
            frames=[
                {
                    key: frame[key]
                    for key in ("observation_id", "camera", "step", "clock", "time_seconds", "modality", "sha256")
                }
                | {"subjects": list(criterion.subjects)}
                for frame in frames
            ],
        )
        request["request_sha256"] = hashlib.sha256(canonical(request)).hexdigest()
        return request
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
    request = {
        "criterion_id": criterion.criterion_id,
        "criterion_digest": hashlib.sha256(canonical(criterion.model_dump(mode="json"))).hexdigest(),
        "rubric": criterion.rubric,
        "candidate": candidate.model_dump(mode="json"),
        "cohort": cohort.model_dump(mode="json"),
        "observation_manifest_digest": observation.manifest_digest,
        "step_window": [start, end],
        "frames": identities,
    }
    if criterion.evaluator_version == "visibility-v2":
        if [f["camera"] for f in identities] != list(criterion.coordinate_frames):
            raise ValueError("Retained camera order differs")
        request["answer_schema"] = "visibility-v2"
        request["request_sha256"] = hashlib.sha256(canonical(request)).hexdigest()
    return request


def validate_visibility_response(raw, request):
    """Validate complete per-subject coverage without turning uncertainty into success."""

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate visibility answer key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    if (
        type(value) is not dict
        or set(value) != {"request_sha256", "answers"}
        or value["request_sha256"] != request["request_sha256"]
        or type(value["answers"]) is not list
        or len(value["answers"]) != len(request["frames"])
    ):
        raise ValueError("Visibility request identity or frame coverage differs")
    verdicts = []
    for answer, frame in zip(value["answers"], request["frames"]):
        if (
            type(answer) is not dict
            or set(answer) != {"camera", "frame_digest", "subjects"}
            or answer["camera"] != frame["camera"]
            or answer["frame_digest"] != frame["sha256"]
            or type(answer["subjects"]) is not list
            or len(answer["subjects"]) != len(frame["subjects"])
        ):
            raise ValueError("Visibility frame or subject coverage differs")
        for subject, expected in zip(answer["subjects"], frame["subjects"]):
            if (
                type(subject) is not dict
                or set(subject) != {"subject", "verdict", "reason"}
                or subject["subject"] != expected
                or subject["verdict"] not in ("visible", "not_visible", "uncertain")
                or type(subject["reason"]) is not str
                or not 1 <= len(subject["reason"].strip()) <= 2048
            ):
                raise ValueError("Invalid per-subject visibility answer")
            verdicts.append(subject["verdict"])
    return dict(
        **value,
        verdict="not_visible" if "not_visible" in verdicts else "uncertain" if "uncertain" in verdicts else "visible",
        limitations=[
            "retained_images_not_fresh_capture",
            "visibility_only_not_scene_acceptance",
            "names_metadata_and_subject_tags_are_not_visual_proof",
        ],
    )


def retain_visual_answer(criterion, candidate, cohort, artifacts, observation, raw_response, *, protect):
    """Keep exact raw UTF-8 response bytes, including rejected answers, without transport."""
    request = visual_request(criterion, candidate, cohort, artifacts, observation, protect=protect)
    if type(raw_response) is not bytes or not 1 <= len(raw_response) <= 65536:
        raise ValueError("response byte bound")
    if criterion.evaluator_version == "full-scene-ternary-v1":
        # Screen readable content as well as the exact encoded bytes. Decoding
        # for screening never replaces the retained response or establishes truth.
        _protected({"raw_response_for_screening": raw_response.decode("utf-8", errors="replace")}, protect)
        digest = hashlib.sha256(raw_response).hexdigest()
        selection = dict(request_sha256=request["request_sha256"], response_sha256=digest)
        return artifacts.write(
            candidate,
            cohort,
            dict(
                kind="visual-answer",
                codec="full-scene-answer-v1",
                request=request,
                source_manifest_digest=observation.manifest_digest,
                assessment_id=assessment_identity("visual-answer", observation.manifest_digest, selection),
                raw_response=dict(encoding="base64", bytes=base64.b64encode(raw_response).decode("ascii")),
                response_sha256=digest,
            ),
            protect=protect,
        )
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
    if criterion.evaluator_version == "full-scene-ternary-v1":
        if payload.get("codec") != "full-scene-answer-v1" or payload["raw_response"]["encoding"] != "base64":
            raise ValueError("versioned raw response retention required")
        raw = base64.b64decode(payload["raw_response"]["bytes"], validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        expected = assessment_identity(
            "visual-answer",
            observation.manifest_digest,
            dict(
                request_sha256=request["request_sha256"],
                response_sha256=digest,
            ),
        )
        if (
            payload["assessment_id"] != expected
            or payload["source_manifest_digest"] != observation.manifest_digest
            or digest != payload["response_sha256"]
        ):
            raise ValueError("derived answer/source identity mismatch")
        checked = validate_ternary_response(raw, request)
        return _evidence(
            criterion,
            candidate,
            cohort,
            answer,
            {"true": "established", "false": "violated", "unknown": "inconclusive"}[checked["truth"]],
            checked["limitations"],
            assessment_id=expected,
            conflict=checked["conflict"],
        )
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


def effective_displacement(
    artifacts, before, after, *, subject, step, target_local, mapping, tolerance_m, protect, hypothesis=None
):
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
    acquisitions, selected_samples = [], []
    for receipt in (before, after):
        payload = _bound_payload(receipt.candidate, receipt.cohort, artifacts, receipt, protect)
        acquisitions.append(payload.get("acquisition") if payload.get("codec") == "observation-v2" else None)
        samples = [s for s in payload["samples"] if type(s["step"]) is int and s["step"] == step]
        if len(samples) != 1 or samples[0]["frame"] != "world" or receipt.cohort.frame_id != "world":
            raise ValueError("exact world sample required")
        origin = _vector(samples[0]["origin_w"])
        world = _vector(samples[0]["subjects"][subject]["position_w"])
        origins.append(origin)
        world_positions.append(world)
        positions.append([p - o for p, o in zip(world, origin)])
        selected_samples.append(samples[0])
    displacement = math.dist(*positions)
    world_displacement = math.dist(*world_positions)
    error = math.dist(positions[1], target_local)
    if not all(math.isfinite(value) for value in (displacement, world_displacement, error)):
        raise ValueError("nonfinite derived displacement")
    if any(acquisitions):
        from .scene_eligibility import RootXYHypothesis

        if not all(acquisitions) or hypothesis is None:
            raise ValueError("versioned displacement requires a bound hypothesis and compatible acquisitions")
        h = RootXYHypothesis.model_validate_json(canonical(hypothesis.model_dump(mode="json")))
        if (
            any(a["plan"]["displacement_step"] != step for a in acquisitions)
            or tolerance_m != h.displacement_tolerance_m
            or h.step != step
            or h.target_subject != subject
            or h.source_acquisition_id != acquisitions[0]["acquisition_id"]
            or h.before_world_xy_m != tuple(world_positions[0][:2])
            or h.proposed_authored_xy_m != tuple(target_local[:2])
            or origins[0] != origins[1]
            or before.cohort.reset_id == after.cohort.reset_id
            or acquisitions[0]["plan"]["control_dt_seconds"] != acquisitions[1]["plan"]["control_dt_seconds"]
        ):
            raise ValueError("selected displacement sample, hypothesis or matched clock/origin mismatch")
        premise = artifacts.load_receipt(
            before.candidate,
            before.cohort,
            kind="diagnostic",
            assessment_id=h.diagnostic_assessment_id,
            manifest_digest=h.diagnostic_manifest_digest,
            protect=protect,
        )
        facts = artifacts.verified_payload(premise, protect=protect)
        if (
            facts["source_manifest_digest"] != before.manifest_digest
            or facts["facts"]["observation_id"] != selected_samples[0]["observation_id"]
            or facts["facts"]["repair_selection_digest"] != h.repair_selection_digest
            or facts["facts"]["position_world_m"] != world_positions[0]
        ):
            raise ValueError("displacement hypothesis diagnostic ancestry mismatch")
        actual_delta = [a - b for a, b in zip(world_positions[1], world_positions[0])]
        predicted_delta = [*h.predicted_delta_world_xy_m, 0.0]
        delta_error = _norm([a - b for a, b in zip(actual_delta, predicted_delta)])
        return dict(
            codec="measured-displacement-v2",
            effective=world_displacement > tolerance_m and delta_error <= tolerance_m,
            subject=subject,
            clock="control_step",
            step=step,
            hypothesis_digest=h.digest(),
            before_acquisition_id=acquisitions[0]["acquisition_id"],
            after_acquisition_id=acquisitions[1]["acquisition_id"],
            before_observation_id=selected_samples[0]["observation_id"],
            after_observation_id=selected_samples[1]["observation_id"],
            before_manifest_digest=before.manifest_digest,
            after_manifest_digest=after.manifest_digest,
            actual_delta_world_m=actual_delta,
            predicted_delta_world_m=predicted_delta,
            delta_error_m=delta_error,
            authored_target_error_m=error,
            tolerance_m=tolerance_m,
            causal_status="unproven",
            goal_assessment_required=True,
            limitations=[
                "weighted_constraint_not_guaranteed_pose_assignment",
                "matched_declared_clock_not_calibration",
                "displacement_is_not_goal_satisfaction_or_causal_proof",
            ],
        )
    if hypothesis is not None:
        raise ValueError("legacy displacement does not consume versioned hypotheses")
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


def make_native_sampler(criteria, *, subject_names, contact_sensors=None, acquisition=None):
    """Create a lazy callback for an already initialized single Arena environment.

    Reuses native pose/velocity, settling and destination predicates. Diagnostic
    predicate booleans are retained but NEVER consumed as measurement proof.
    No SimulationApp, env, policy or model is constructed. Native execution still
    requires separate runtime/profile validation; this slice tests synthetic inputs.
    """
    criteria = tuple(admit_criterion(c) for c in criteria)
    subjects = {s for c in criteria for s in c.subjects}
    if acquisition is not None:
        if not subjects <= set(acquisition.subjects) or any(c.parameters is None for c in criteria):
            raise ValueError("explicit acquisition requires supported criterion/subject mappings")
        subjects = set(acquisition.subjects)
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
            if not hasattr(tensor, "detach"):
                tensor = wp.to_torch(tensor)
            if tuple(tensor.shape) != (1, 3):
                raise ValueError("singleton native world vector required")
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
        if acquisition is None:
            result["diagnostic_predicates"]["objects_settled"] = bool(
                objects_settled(
                    native,
                    list(names.values()),
                    lin_vel_threshold=SUPPORT_THRESHOLDS["linear_m_per_s"],
                    ang_vel_threshold=SUPPORT_THRESHOLDS["angular_rad_per_s"],
                    env_id=0,
                ).item()
            )
        else:
            for criterion in criteria:
                parameters = criterion.parameters
                if parameters.metric == "stationary":
                    result["diagnostic_predicates"][criterion.criterion_id] = all(
                        _compare_limit(_norm(result["subjects"][subject]["linear_velocity_w"]), parameters.linear_limit)
                        and _compare_limit(
                            _norm(result["subjects"][subject]["angular_velocity_w"]), parameters.angular_limit
                        )
                        for subject in criterion.subjects
                    )
        for c in criteria:
            if c.evidence_producer != "scene.filtered-support":
                continue
            subject, destination = c.subjects
            sensor_name = sensors[c.subjects]
            sensor = native.scene[sensor_name]
            # ProxyArray.shape excludes the vec3 components; validate the scalar view.
            force = wp.to_torch(sensor.data.force_matrix_w)
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
                "force_w": _vector(force[0, 0, 0].detach().cpu().tolist()),
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
