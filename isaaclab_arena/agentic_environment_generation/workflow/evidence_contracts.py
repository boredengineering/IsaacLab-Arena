# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure frozen-request projection, not a support registry or native producer claim.

The full criterion digest binds intent, including numeric limits and rubric text.
Only the producer evaluates those limits; a digest is never measurement proof.
"""

import hashlib
import json

from .contracts import WorkflowContract
from .evidence import CriterionRequirement


def project_required_criteria(contract: WorkflowContract) -> tuple[CriterionRequirement, ...]:
    """Project required scene criteria; reject profiles this assessor cannot represent.

    All required criteria share one exact inclusive step window. Frame identities
    are per-criterion exact sets, so cameras need not share the cohort's scene frame.
    Advisory criteria do not participate. Structural reuse is deliberately disabled:
    the frozen contract does not assert state independence.
    """
    contract = WorkflowContract.model_validate(contract.model_dump(mode="python"))
    if sum(criterion.requirement == "required" for criterion in contract.criteria) > 128:
        raise ValueError("unsupported required criterion count")
    requirements = []
    for criterion in contract.criteria:
        if criterion.requirement != "required":
            continue
        profiles = {
            "structural": ("scene_graph", "structural"),
            "geometry": ("state", "measured"),
            "runtime": ("state", "measured"),
            "visual": ("rgb", "visual"),
        }
        profile = profiles.get(criterion.kind)
        if profile is None or criterion.required_modalities != (profile[0],):
            raise ValueError(f"unsupported criterion profile: {criterion.criterion_id}")
        canonical = json.dumps(
            criterion.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        requirements.append(
            CriterionRequirement(
                criterion_id=criterion.criterion_id,
                criterion_digest=digest,
                producer_id=criterion.evidence_producer,
                coordinate_frames=criterion.coordinate_frames,
                step_window=(criterion.observation_window.start_step, criterion.observation_window.end_step),
                subject_ids=criterion.subjects,
                modality=profile[1],
                evaluator_version=criterion.evaluator_version,
                rubric_id=digest,
            )
        )
    if not requirements:
        raise ValueError("at least one required criterion is necessary")
    if len({requirement.step_window for requirement in requirements}) != 1:
        raise ValueError("unsupported differing required observation windows")
    return tuple(requirements)
