# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Retained numeric re-evaluation; no acquisition, model, database, or contract amendment."""

from dataclasses import dataclass
from typing import Literal

from .contracts import Criterion, FrozenModel, Hash, Identifier, WorkflowContract, contract_digest
from .evidence import CriterionEvidence
from .scene_evidence_artifacts import SceneEvidenceReceipt, assessment_identity, canonical
from .scene_observation import _bound_payload, admit_criterion, evaluate_measurement


class NumericReassessmentSelection(FrozenModel):
    codec: Literal["retained-numeric-selection-v1"]
    run_id: Hash
    evidence_id: Hash
    candidate_id: Hash
    source_manifest_digest: Hash
    criterion: Criterion
    purpose: Literal["exploratory", "validation"]
    validation_contract_digest: Hash | None


class NumericReassessmentView(FrozenModel):
    codec: Literal["retained-numeric-result-v1"] = "retained-numeric-result-v1"
    operation_id: Identifier
    selection_digest: Hash
    run_id: Hash
    evidence_id: Hash
    candidate_id: Hash
    source_manifest_digest: Hash
    purpose: Literal["exploratory", "validation"]
    criterion: Criterion
    validation_contract_digest: Hash | None
    disposition: Literal["produced", "refused"]
    reason: str | None
    assessment_id: Hash | None
    manifest_digest: Hash | None
    evidence: CriterionEvidence | None
    original_run_version: int
    provider_sends: Literal[0] = 0
    native_releases: Literal[0] = 0
    original_run_amended: Literal[False] = False


@dataclass(frozen=True)
class RetainedNumericAssessment:
    receipt: SceneEvidenceReceipt
    evidence: CriterionEvidence
    purpose: str


def _payload(criterion, candidate, cohort, artifacts, source, *, purpose, validation_contract, protect):
    criterion = admit_criterion(criterion)
    if criterion.evaluator_version != "numeric-v2" or purpose not in ("exploratory", "validation"):
        raise ValueError("unsupported retained numeric assessment selection")
    selected_contract = None
    if purpose == "validation":
        if validation_contract is None:
            raise ValueError("validation requires the preselected immutable contract")
        contract = WorkflowContract.model_validate_json(validation_contract.model_dump_json())
        selected_contract = contract_digest(contract)
        if selected_contract != candidate.contract_digest or not any(
            canonical(c.model_dump(mode="json")) == canonical(criterion.model_dump(mode="json"))
            for c in contract.criteria
        ):
            raise ValueError("criterion was not preselected in the source contract")
    elif validation_contract is not None:
        raise ValueError("exploratory assessment cannot claim preselected validation")
    acquired = _bound_payload(candidate, cohort, artifacts, source, protect)
    if acquired.get("codec") != "observation-v2":
        raise ValueError("retained numeric-v2 requires explicit source coverage; legacy receipts remain legacy")
    result = evaluate_measurement(criterion, candidate, cohort, artifacts, source, protect=protect)
    selection = dict(
        criterion=criterion.model_dump(mode="json"),
        purpose=purpose,
        validation_contract_digest=selected_contract,
        source_acquisition_id=acquired["acquisition"]["acquisition_id"],
    )
    return dict(
        kind="numeric-assessment",
        codec="retained-numeric-v1",
        source_manifest_digest=source.manifest_digest,
        assessment_id=assessment_identity("numeric-assessment", source.manifest_digest, selection),
        selection=selection,
        result=result.model_dump(mode="json"),
    )


def _result(payload, receipt):
    source_result = CriterionEvidence.model_validate_json(canonical(payload["result"]))
    result = source_result.model_copy(
        update={
            "manifest_digest": receipt.manifest_digest,
            "assessment_id": payload["assessment_id"],
        }
    )
    return RetainedNumericAssessment(receipt, result, payload["selection"]["purpose"])


def assess_retained_numeric(
    criterion, candidate, cohort, artifacts, source, *, purpose, protect, validation_contract=None
):
    """Retain a separately identified assessment without changing original evidence or intent."""
    payload = _payload(
        criterion,
        candidate,
        cohort,
        artifacts,
        source,
        purpose=purpose,
        validation_contract=validation_contract,
        protect=protect,
    )
    return _result(payload, artifacts.write(candidate, cohort, payload, protect=protect))


def reopen_retained_numeric(artifacts, receipt, *, protect, validation_contract=None):
    """Verify exact child/source bytes and recompute, without another acquisition or child write."""
    payload = artifacts.verified_payload(receipt, protect=protect)
    if payload.get("kind") != "numeric-assessment" or payload.get("codec") != "retained-numeric-v1":
        raise ValueError("unsupported retained numeric codec")
    criterion = Criterion.model_validate(payload["selection"]["criterion"])
    source = artifacts.load_receipt(
        receipt.candidate,
        receipt.cohort,
        kind="observation",
        manifest_digest=payload["source_manifest_digest"],
        protect=protect,
    )
    expected = _payload(
        criterion,
        receipt.candidate,
        receipt.cohort,
        artifacts,
        source,
        purpose=payload["selection"]["purpose"],
        validation_contract=validation_contract,
        protect=protect,
    )
    if canonical(expected) != canonical(payload):
        raise ValueError("retained assessment semantics or ancestry mismatch")
    return _result(payload, receipt)
