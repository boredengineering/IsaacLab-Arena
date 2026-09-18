# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Pure scene metadata assessment; never authenticates measurements or reads artifacts.

The caller MUST derive verified_manifest_digests from actual manifest byte readback.
A digest supplied in a receipt is not verification. No physical truth is inferred here.

Use evidence_contracts to project frozen requests without reducing their semantics.
Criterion digests bind requests, not measurement truth or producer provenance.
This pure utility is not production acceptance.
"""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, model_validator


def _unique(values):
    if len(values) != len(set(values)):
        raise ValueError("duplicate identities")
    return values


Identity = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256, pattern=r"^\S+$")]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
Subjects = Annotated[tuple[Identity, ...], Field(min_length=1, max_length=128), AfterValidator(_unique)]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1024, pattern=r"\S")]
Limitations = Annotated[tuple[Text, ...], Field(max_length=128)]
Modality = Literal["structural", "measured", "visual"]
CoordinateFrames = Annotated[tuple[Identity, ...], Field(min_length=1, max_length=256), AfterValidator(_unique)]
Step = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)]


def _ordered_window(window):
    if window[1] < window[0]:
        raise ValueError("observation window end precedes start")
    return window


StepWindow = Annotated[tuple[Step, Step], AfterValidator(_ordered_window)]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", revalidate_instances="always")


class CandidateBinding(Frozen):
    candidate_digest: Digest
    contract_digest: Digest
    profile_digest: Digest


class EvidenceCohort(Frozen):
    realization_id: Identity
    reset_id: Identity
    environment_id: Identity
    window_id: Identity
    frame_id: Identity
    """Common scene coordinate convention, not an individual camera identity."""
    contract_digest: Digest
    profile_digest: Digest


class CriterionRequirement(Frozen):
    criterion_id: Identity
    criterion_digest: Digest
    producer_id: Identity
    coordinate_frames: CoordinateFrames
    step_window: StepWindow
    subject_ids: Subjects
    modality: Modality
    evaluator_version: Identity
    rubric_id: Identity
    state_independent: bool = False
    scope: Literal["scene", "policy"] = "scene"

    @model_validator(mode="after")
    def static_is_structural(self):
        if self.state_independent and self.modality != "structural":
            raise ValueError("state-independent reuse requires structural evidence")
        return self


class CriterionEvidence(Frozen):
    criterion_id: Identity
    criterion_digest: Digest
    producer_id: Identity
    observed_coordinate_frames: CoordinateFrames
    observed_step_window: StepWindow
    subject_ids: Subjects
    modality: Modality
    evaluator_version: Identity
    rubric_id: Identity
    candidate_digest: Digest
    cohort: EvidenceCohort
    manifest_digest: Digest
    verdict: Literal["established", "violated", "inconclusive", "not_run"]
    limitations: Limitations = ()


class SceneEvidenceAssessment(Frozen):
    status: Literal["established", "not_established", "inconclusive"]
    missing_ids: tuple[Identity, ...] = ()
    failed_ids: tuple[Identity, ...] = ()
    """All matching verified failures, including diagnostic historical failures."""
    historical_conflict_ids: tuple[Identity, ...] = ()
    limitations: Limitations = ()


def assess_scene_evidence(
    required: tuple[CriterionRequirement, ...],
    candidate: CandidateBinding,
    evidence: tuple[CriterionEvidence, ...],
    verified_manifest_digests: frozenset[str],
    *,
    selected_cohort: EvidenceCohort,
) -> SceneEvidenceAssessment:
    """Assess one exact scene cohort, never a multi-trial policy success rate.

    Only the explicitly selected cohort establishes state-dependent requirements.
    Matching structural state-independent receipts may be reused from other cohorts.
    Historical failures/conflicts remain diagnostics, not global vetoes; selected
    failures/conflicts block. Caller owns byte verification and selection provenance.
    """
    required = TypeAdapter(
        Annotated[tuple[CriterionRequirement, ...], Field(min_length=1, max_length=128)]
    ).validate_python(required, strict=True)
    candidate = CandidateBinding.model_validate(candidate)
    selected_cohort = EvidenceCohort.model_validate(selected_cohort)
    if (
        selected_cohort.contract_digest != candidate.contract_digest
        or selected_cohort.profile_digest != candidate.profile_digest
    ):
        raise ValueError("selected cohort must match candidate contract/profile binding")
    evidence = TypeAdapter(Annotated[tuple[CriterionEvidence, ...], Field(max_length=4096)]).validate_python(
        evidence, strict=True
    )
    verified_manifest_digests = TypeAdapter(Annotated[frozenset[Digest], Field(max_length=4096)]).validate_python(
        verified_manifest_digests, strict=True
    )
    _unique(tuple(r.criterion_id for r in required))
    requirements = {r.criterion_id: r for r in required}
    groups = {}
    limitations = set()
    failed = set()
    selected_failed = set()
    historical_conflicts = set()
    for record in evidence:
        req = requirements.get(record.criterion_id)
        if req is None:
            continue
        if (
            record.candidate_digest != candidate.candidate_digest
            or record.cohort.contract_digest != candidate.contract_digest
            or record.cohort.profile_digest != candidate.profile_digest
            or record.manifest_digest not in verified_manifest_digests
        ):
            limitations.add("unverified_or_stale_receipt")
            continue
        groups.setdefault((record.criterion_id, record.cohort), set()).add(record)

    passes = {r.criterion_id: set() for r in required}
    ambiguous = False
    for (criterion_id, observed_cohort), records in groups.items():
        req = requirements[criterion_id]
        selected = observed_cohort == selected_cohort
        if len(records) > 1:
            if selected:
                ambiguous = True
                limitations.add("ambiguous_receipts")
            else:
                historical_conflicts.add(criterion_id)
                limitations.add("historical_conflict")
        for record in records:
            matches = (
                set(record.subject_ids) == set(req.subject_ids)
                and record.criterion_digest == req.criterion_digest
                and record.producer_id == req.producer_id
                and set(record.observed_coordinate_frames) == set(req.coordinate_frames)
                and record.observed_step_window == req.step_window
                and record.modality == req.modality
                and record.evaluator_version == req.evaluator_version
                and record.rubric_id == req.rubric_id
            )
            if not matches:
                limitations.add("criterion_identity_mismatch")
                continue
            if req.scope == "policy":
                continue
            if record.verdict == "violated":
                failed.add(criterion_id)
                if selected:
                    selected_failed.add(criterion_id)
                else:
                    limitations.add("historical_failure")
            elif record.verdict == "established" and len(records) == 1 and (selected or req.state_independent):
                passes[criterion_id].add(observed_cohort)

    unsupported = any(r.scope == "policy" for r in required)
    if unsupported:
        limitations.add("unsupported_policy_requirement")
    missing = {r.criterion_id for r in required if not passes[r.criterion_id]}
    status = (
        "not_established"
        if selected_failed
        else ("established" if not missing and not ambiguous and not unsupported else "inconclusive")
    )
    return SceneEvidenceAssessment(
        status=status,
        missing_ids=tuple(r.criterion_id for r in required if r.criterion_id in missing - selected_failed),
        failed_ids=tuple(r.criterion_id for r in required if r.criterion_id in failed),
        historical_conflict_ids=tuple(r.criterion_id for r in required if r.criterion_id in historical_conflicts),
        limitations=tuple(sorted(limitations)),
    )
