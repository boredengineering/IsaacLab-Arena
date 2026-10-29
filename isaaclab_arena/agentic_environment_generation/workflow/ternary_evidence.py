# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Full-scene ternary-v1 decoding, independent of the historical visibility-v2 codec."""

import json
from typing import Annotated, Literal

from pydantic import Field

from .contracts import Amount, Count, FrozenModel, Hash, Identifier
from .evidence import aggregate_truth
from .scene_evidence_artifacts import canonical


class SubjectTruth(FrozenModel):
    subject: Identifier
    truth: Literal["true", "false", "unknown"]
    confidence: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)] | None
    conflict: Annotated[bool, Field(strict=True)]
    reason: Annotated[str, Field(strict=True, min_length=1, max_length=2048, pattern=r"\S")]


class FrameTruth(FrozenModel):
    observation_id: Hash
    camera: Identifier
    step: Count
    clock: Literal["control_step"]
    time_seconds: Amount
    modality: Literal["rgb"]
    frame_digest: Hash
    subjects: Annotated[tuple[SubjectTruth, ...], Field(min_length=1, max_length=16)]


class FullSceneTruth(FrozenModel):
    codec: Literal["full-scene-ternary-v1"]
    request_sha256: Hash
    answers: Annotated[tuple[FrameTruth, ...], Field(min_length=1, max_length=16)]


def validate_ternary_response(raw, request):
    """Decode exact request/frame/time/modality/subject coverage; invalid is not UNKNOWN."""

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate response key")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("nonfinite response value")

    if type(raw) is not bytes or not 1 <= len(raw) <= 65536:
        raise ValueError("bounded raw response required")
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)
        response = FullSceneTruth.model_validate(parsed)
    except (ValueError, TypeError):
        raise ValueError("malformed full-scene ternary response") from None
    if (
        request.get("answer_schema") != response.codec
        or response.request_sha256 != request["request_sha256"]
        or len(response.answers) != len(request["frames"])
    ):
        raise ValueError("full-scene request/coverage mismatch")
    by_subject = {}
    conflict = False
    for answer, frame in zip(response.answers, request["frames"]):
        actual = answer.model_dump(mode="json")
        keys = ("observation_id", "camera", "step", "clock", "time_seconds", "modality")
        if (
            canonical({key: actual[key] for key in keys}) != canonical({key: frame[key] for key in keys})
            or answer.frame_digest != frame["sha256"]
            or tuple(s.subject for s in answer.subjects) != tuple(frame["subjects"])
        ):
            raise ValueError("full-scene frame/time/modality/subject mismatch")
        for subject in answer.subjects:
            by_subject.setdefault(subject.subject, {}).setdefault(answer.camera, []).append(subject.truth)
            conflict = conflict or subject.conflict
    aggregation = request["aggregation"]
    subjects = [
        aggregate_truth(
            [aggregate_truth(values, aggregation["temporal"]) for values in cameras.values()], aggregation["camera"]
        )
        for cameras in by_subject.values()
    ]
    return dict(
        response=response.model_dump(mode="json"),
        truth=aggregate_truth(subjects, aggregation["subject"]),
        conflict=conflict,
        limitations=["visibility_only_not_causal_defect_or_repair_authority", "subject_tags_are_not_visual_proof"],
    )
