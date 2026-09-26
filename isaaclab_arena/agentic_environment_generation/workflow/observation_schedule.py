# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure explicit acquisition identities and collection validation, never sensor truth."""

import base64
import hashlib
import io
import math
from dataclasses import dataclass

from .contracts import AcquisitionSchedule, CriterionCoverage
from .evidence import CandidateBinding, EvidenceCohort
from .scene_evidence_artifacts import canonical


class CollectionFailure(ValueError):
    """Invalid acquisition, never a ternary scientific verdict."""

    def __init__(self, category="invalid_collection", reason="invalid_collection"):
        assert category in ("invalid_collection", "unexpected_reset", "unexpected_termination")
        self.category = category
        super().__init__(f"invalid collection: {category}: {reason}")


def criterion_coverage(criterion):
    """Return explicit coverage for a new evaluator, or unchanged legacy semantics."""
    if criterion.parameters is None:
        return None
    if criterion.parameters.metric == "visibility":
        return CriterionCoverage(clock=criterion.parameters.clock, state_steps=(), images=criterion.parameters.images)
    return CriterionCoverage(clock=criterion.parameters.clock, state_steps=criterion.parameters.sample_steps, images=())


@dataclass(frozen=True)
class CompiledAcquisition:
    """Frozen logical observation identities; real sensor timestamps remain mandatory."""

    plan: AcquisitionSchedule
    candidate: CandidateBinding
    cohort: EvidenceCohort

    @property
    def state_steps(self):
        return self.plan.state_steps

    @property
    def collection_steps(self):
        return tuple(sorted(set(self.state_steps) | {image.step for image in self.plan.images}))

    @property
    def renderer_update_steps(self):
        return self.plan.renderer_update_steps

    def phase_for(self, step, settle_steps):
        """Give the settle phase sole ownership of the initialized handoff step."""
        if type(step) is not int or not 0 <= step <= self.plan.horizon_steps:
            raise ValueError("unsupported acquisition step")
        return "settle" if step <= settle_steps else "capture"

    def metadata(self):
        value = dict(
            codec="acquisition-v1",
            plan=self.plan.model_dump(mode="json"),
            candidate=self.candidate.model_dump(mode="json"),
            cohort=self.cohort.model_dump(mode="json"),
        )
        return value | {"acquisition_id": hashlib.sha256(canonical(value)).hexdigest()}

    def observation_identity(self, step, *, camera=None):
        if type(step) is not int or not (
            step in self.state_steps
            if camera is None
            else any(image.step == step and image.camera == camera for image in self.plan.images)
        ):
            raise ValueError("observation outside explicit schedule")
        value = dict(
            acquisition_id=self.metadata()["acquisition_id"],
            step=step,
            clock=self.plan.clock,
            time_seconds=step * self.plan.control_dt_seconds,
            modality="state" if camera is None else "rgb",
            frame=self.plan.reference_frame if camera is None else camera,
        )
        return value | {"observation_id": hashlib.sha256(canonical(value)).hexdigest()}


def compile_acquisition(plan, criteria, *, candidate, cohort):
    """Bind a supported explicit plan to one immutable candidate/reset and its criteria.

    Args:
        plan: Frozen state, image, renderer-update and displacement selections.
        criteria: Supported predicates selecting subsets of this acquisition.
        candidate: Original acquisition binding, not a reassessment's replacement contract.
        cohort: One realization, reset, environment and clock convention.

    Returns:
        Logical identities and independent schedules; no render/update is performed.
    """
    from .scene_observation import admit_criterion

    plan = AcquisitionSchedule.model_validate(plan.model_dump(mode="python"))
    candidate = CandidateBinding.model_validate(candidate)
    cohort = EvidenceCohort.model_validate(cohort)
    if (
        cohort.contract_digest != candidate.contract_digest
        or cohort.profile_digest != candidate.profile_digest
        or cohort.frame_id != plan.reference_frame
    ):
        raise ValueError("acquisition candidate/cohort/frame mismatch")
    for criterion in criteria:
        criterion = admit_criterion(criterion)
        coverage = criterion_coverage(criterion)
        if (
            coverage is None
            or not set(criterion.subjects) <= set(plan.subjects)
            or not set(coverage.state_steps) <= set(plan.state_steps)
            or not set(coverage.images) <= set(plan.images)
        ):
            raise ValueError("insufficient acquisition coverage for selected criterion")
    return CompiledAcquisition(plan, candidate, cohort)


def validate_png(raw):
    """Validate bounded RGB PNG bytes without trusting MIME labels or filenames."""
    from PIL import Image

    if type(raw) is not bytes or not 0 < len(raw) <= 131072 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("unsupported bounded RGB PNG")
    with Image.open(io.BytesIO(raw)) as image:
        if image.format != "PNG" or image.mode != "RGB" or not 0 < max(image.size) <= 128:
            raise ValueError("unsupported RGB image dimensions/mode")
        image.verify()


def _vector(value):
    if (
        type(value) is not list
        or len(value) != 3
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)
        or not math.isfinite(math.hypot(*value))
    ):
        raise CollectionFailure(reason="nonfinite_or_invalid_vector")


def validate_collection(payload, *, candidate, cohort):
    """Refuse invalid collection before scientific grading, independently of truth."""
    if payload.get("codec") != "observation-v2" or payload.get("kind") != "observation":
        raise ValueError("unsupported collection codec")
    try:
        metadata = payload["acquisition"]
        plan = AcquisitionSchedule.model_validate(metadata["plan"])
        compiled = compile_acquisition(plan, (), candidate=candidate, cohort=cohort)
        if canonical(metadata) != canonical(compiled.metadata()):
            raise ValueError("collection ancestry mismatch")
        status = payload["collection"]
        if type(status.get("reset_count")) is int and status["reset_count"] != 1:
            raise CollectionFailure("unexpected_reset")
        if status.get("terminated") is True or status.get("truncated") is True:
            raise CollectionFailure("unexpected_termination")
        expected = dict(
            status="complete", executed_steps=plan.horizon_steps, reset_count=1, terminated=False, truncated=False
        )
        if canonical(status) != canonical(expected):
            raise CollectionFailure(reason="incomplete_or_invalid_status")
        samples, frames = payload["samples"], payload["frames"]
        if type(samples) is not list or type(frames) is not list:
            raise CollectionFailure(reason="invalid_sequence")
        if [s["step"] for s in samples] != list(plan.state_steps) or len(samples) != len(plan.state_steps):
            raise CollectionFailure(reason="incomplete_states")
        for sample in samples:
            identity = compiled.observation_identity(sample["step"])
            if canonical({k: sample.get(k) for k in identity}) != canonical(identity):
                raise CollectionFailure(reason="state_clock_or_identity_mismatch")
            if set(sample["subjects"]) != set(plan.subjects):
                raise CollectionFailure(reason="state_subject_mismatch")
            _vector(sample["origin_w"])
            for subject in sample["subjects"].values():
                for key in ("position_w", "linear_velocity_w", "angular_velocity_w"):
                    _vector(subject[key])
        if len(frames) != len(plan.images):
            raise CollectionFailure(reason="incomplete_images")
        sequences = {}
        for frame, selected in zip(frames, plan.images):
            identity = compiled.observation_identity(selected.step, camera=selected.camera)
            if (
                canonical({k: frame.get(k) for k in identity}) != canonical(identity)
                or frame["camera"] != selected.camera
                or frame["subjects"] != list(plan.subjects)
                or type(frame["sensor_update_step"]) is not int
                or frame["sensor_update_step"] != selected.step
                or type(frame["sensor_sequence"]) is not int
                or frame["sensor_sequence"] <= sequences.get(selected.camera, -1)
                or frame["encoding"] != "base64"
            ):
                raise CollectionFailure(reason="image_coverage_clock_or_freshness_mismatch")
            sequences[selected.camera] = frame["sensor_sequence"]
            raw = base64.b64decode(frame["bytes"], validate=True)
            if hashlib.sha256(raw).hexdigest() != frame["sha256"]:
                raise CollectionFailure(reason="image_digest_mismatch")
            validate_png(raw)
        canonical(payload)
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise CollectionFailure(reason="invalid_structure") from exc
    return compiled


def select_samples(criterion, payload, cohort):
    """Select sparse numeric coverage without relabelling acquisition time or reset."""
    metadata = payload.get("acquisition", {})
    candidate = CandidateBinding.model_validate(metadata.get("candidate", {}))
    compiled = validate_collection(payload, candidate=candidate, cohort=cohort)
    coverage = criterion_coverage(criterion)
    if (
        coverage is None
        or not set(coverage.state_steps) <= set(compiled.state_steps)
        or not set(criterion.subjects) <= set(compiled.plan.subjects)
    ):
        raise ValueError("insufficient collection coverage")
    by_step = {sample["step"]: sample for sample in payload["samples"]}
    return [by_step[step] for step in coverage.state_steps]


def select_frames(criterion, payload, cohort):
    """Select exact camera/time identities, never a Cartesian numeric-window expansion."""
    metadata = payload.get("acquisition", {})
    candidate = CandidateBinding.model_validate(metadata.get("candidate", {}))
    compiled = validate_collection(payload, candidate=candidate, cohort=cohort)
    coverage = criterion_coverage(criterion)
    if coverage is None or not coverage.images or not set(coverage.images) <= set(compiled.plan.images):
        raise ValueError("insufficient image collection coverage")
    frames = {(f["camera"], f["step"], f["modality"]): f for f in payload["frames"]}
    return [frames[(selection.camera, selection.step, selection.modality)] for selection in coverage.images]
