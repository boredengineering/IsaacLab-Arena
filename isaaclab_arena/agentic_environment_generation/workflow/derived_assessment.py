# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Retained numeric re-evaluation; no acquisition, model, database, or contract amendment."""

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal

from .contracts import Criterion, FrozenModel, Hash, Identifier, WorkflowContract, contract_digest, parse_contract
from .evidence import CandidateBinding, CriterionEvidence, SceneEvidenceAssessment
from .scene_evidence_artifacts import SceneEvidenceReceipt, assessment_identity, canonical
from .scene_observation import _bound_payload, admit_criterion, evaluate_measurement


class EvidenceChainStepLink(FrozenModel):
    step_index: int
    candidate_id: Hash
    input_digest: Hash | None = None
    output_digest: Hash
    evidence_id: Hash | None = None
    evidence_manifest_digests: tuple[Hash, ...] = ()
    decision_id: str | None = None
    decision_action: str | None = None


class EvidenceChainAuditReport(FrozenModel):
    run_id: Hash
    valid: bool
    steps_verified: int
    candidate_chain: tuple[EvidenceChainStepLink, ...]
    evidence_manifest_digests: tuple[Hash, ...]
    decisions_verified: int
    budget_transactions_verified: int
    chain_digest: Hash
    errors: tuple[str, ...] = ()


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


def reassess_workflow_numeric(
    store_or_criterion: Any,
    operation_id: str | None = None,
    selection: NumericReassessmentSelection | dict[str, Any] | None = None,
    *,
    artifacts: Any = None,
    protect: Any = None,
    candidate: Any = None,
    cohort: Any = None,
    source: Any = None,
    purpose: str = "exploratory",
    validation_contract: Any = None,
) -> NumericReassessmentView | RetainedNumericAssessment:
    """Execute Job J9 (Retained Numeric Reassessment) purely on CPU from retained telemetry manifests.

    Supports both store-backed execution (``reassess_workflow_numeric(store, operation_id, selection,
    artifacts=..., protect=...)``) and direct artifact-backed execution
    (``reassess_workflow_numeric(criterion, candidate=..., cohort=..., artifacts=..., source=..., ...)``).
    Asserts cryptographic hash verification of raw telemetry manifests and zero GPU/LLM invocations.
    """
    if protect is None:
        protect = lambda _value: None  # noqa: E731

    if hasattr(store_or_criterion, "reassess_numeric"):
        if operation_id is None or selection is None or artifacts is None:
            raise ValueError("store-backed reassess_workflow_numeric requires operation_id, selection, and artifacts")
        view = store_or_criterion.reassess_numeric(
            operation_id,
            selection,
            artifacts=artifacts,
            protect=protect,
        )
        assert view.provider_sends == 0, "Retained numeric reassessment must not issue provider/LLM calls"
        assert view.native_releases == 0, "Retained numeric reassessment must not release GPU/Sim workers"
        assert view.original_run_amended is False, "Retained numeric reassessment must not amend original run"
        return view

    if artifacts is None or candidate is None or cohort is None or source is None:
        raise ValueError("direct reassess_workflow_numeric requires criterion, candidate, cohort, artifacts, source")
    # Cryptographically verify raw telemetry manifest digest before evaluating
    artifacts.verified_payload(source, protect=protect)
    assessment = assess_retained_numeric(
        store_or_criterion,
        candidate,
        cohort,
        artifacts,
        source,
        purpose=purpose,
        protect=protect,
        validation_contract=validation_contract,
    )
    reopened = reopen_retained_numeric(
        artifacts,
        assessment.receipt,
        protect=protect,
        validation_contract=validation_contract,
    )
    if reopened != assessment:
        raise ValueError("retained numeric reassessment readback verification failed")
    return assessment


reassessWorkflowNumeric = reassess_workflow_numeric


def verify_run_evidence_chain(
    run_id: str,
    neo4j_store: Any,
    *,
    artifacts: Any = None,
    protect: Any = None,
    strict: bool = True,
) -> EvidenceChainAuditReport:
    """Verify the cryptographic hash chain across candidates, observations, decisions, and budget transactions.

    Asserts that every step's candidate ``input_digest`` (parent digest) -> ``output_digest`` (candidate digest),
    observation ``evidence_manifest_digest`` / ``verified_manifest_digests``, and decision records form an
    unbroken, tamper-evident cryptographic hash chain across the workflow run.
    """
    from .scene_loop import CandidateRecord, Observation, SceneDecision, candidate_record, profile_digest

    if protect is None:
        protect = lambda _value: None  # noqa: E731

    errors: list[str] = []
    scope = getattr(neo4j_store, "scope", {})
    scope_clause = (
        "{deployment_id: $deployment_id, workspace_id: $workspace_id}"
        if "deployment_id" in scope and "workspace_id" in scope
        else ""
    )

    with neo4j_store._transaction() as tx:
        run_row = tx.run(
            f"MATCH (r:ArenaWorkflowRun {scope_clause}) WHERE r.run_id=$run_id RETURN properties(r) AS r",
            **scope,
            run_id=run_id,
        ).single()
        if run_row is None:
            msg = f"Unknown workflow run_id: {run_id}"
            if strict:
                raise ValueError(msg)
            return EvidenceChainAuditReport(
                run_id=run_id if len(run_id) == 64 else hashlib.sha256(run_id.encode("utf-8")).hexdigest(),
                valid=False,
                steps_verified=0,
                candidate_chain=(),
                evidence_manifest_digests=(),
                decisions_verified=0,
                budget_transactions_verified=0,
                chain_digest="0" * 64,
                errors=(msg,),
            )

        run_props = dict(run_row["r"])
        try:
            contract = parse_contract(run_props["contract_json"])
            expected_contract_digest = contract_digest(contract)
            expected_profile_digest = profile_digest(contract)
        except Exception as exc:
            errors.append(f"Invalid retained run contract_json: {exc}")
            expected_contract_digest = None
            expected_profile_digest = None

        cand_rows = list(
            tx.run(
                f"MATCH (r:ArenaWorkflowRun {scope_clause})-[:HAS_SCENE_RECORD]->(c:ArenaWorkflowCandidate {scope_clause}) "
                "WHERE r.run_id=$run_id "
                "OPTIONAL MATCH (c)-[:DERIVED_FROM]->(p:ArenaWorkflowCandidate) "
                "OPTIONAL MATCH (c)-[:ORIGINAL]->(o:ArenaWorkflowCandidate) "
                "RETURN c.record_id AS record_id, c.payload AS payload, "
                "       p.record_id AS parent_edge_id, o.record_id AS original_edge_id",
                **scope,
                run_id=run_id,
            )
        )

        candidates_by_id: dict[str, CandidateRecord] = {}
        parent_edges: dict[str, str | None] = {}
        original_edges: dict[str, str | None] = {}

        for row in cand_rows:
            rec_id = row["record_id"]
            raw_payload = row["payload"]
            parent_edges[rec_id] = row["parent_edge_id"]
            original_edges[rec_id] = row["original_edge_id"]
            try:
                cand = CandidateRecord.model_validate_json(raw_payload)
                rebuilt = candidate_record(
                    run_id,
                    json.loads(cand.scene_json),
                    source_id=cand.source_id,
                    original_id=cand.original_id,
                    parent_id=cand.parent_id,
                )
                if rebuilt != cand or cand.candidate_id != rec_id or cand.run_id != run_id:
                    errors.append(f"Candidate cryptographic digest mismatch for {rec_id}")
                candidates_by_id[rec_id] = cand
            except Exception as exc:
                errors.append(f"Corrupt candidate payload for {rec_id}: {exc}")

        if not candidates_by_id:
            errors.append(f"No ArenaWorkflowCandidate records found for run {run_id}")

        # Verify parent/original lineage and build ordered chain from root(s)
        for cid, cand in candidates_by_id.items():
            if cand.parent_id is None:
                if cand.original_id != cand.candidate_id:
                    errors.append(f"Root candidate {cid} original_id != candidate_id")
                if parent_edges.get(cid) is not None or original_edges.get(cid) is not None:
                    errors.append(f"Root candidate {cid} has unexpected DERIVED_FROM/ORIGINAL edges")
            else:
                if cand.parent_id not in candidates_by_id:
                    errors.append(f"Derived candidate {cid} references missing parent {cand.parent_id}")
                if cand.original_id not in candidates_by_id:
                    errors.append(f"Derived candidate {cid} references missing original {cand.original_id}")
                if parent_edges.get(cid) != cand.parent_id:
                    errors.append(
                        f"Derived candidate {cid} DERIVED_FROM edge ({parent_edges.get(cid)}) != {cand.parent_id}"
                    )
                if original_edges.get(cid) != cand.original_id:
                    errors.append(
                        f"Derived candidate {cid} ORIGINAL edge ({original_edges.get(cid)}) != {cand.original_id}"
                    )

        # Verify run snapshot pointers if present
        for snap_field in ("scene_original", "scene_candidate"):
            if snap_field in run_props and run_props[snap_field] is not None:
                try:
                    snap_cand = CandidateRecord.model_validate_json(run_props[snap_field])
                    if snap_cand.candidate_id not in candidates_by_id:
                        errors.append(f"Run {snap_field} ({snap_cand.candidate_id}) missing from candidate graph")
                    elif candidates_by_id[snap_cand.candidate_id] != snap_cand:
                        errors.append(f"Run {snap_field} payload diverges from candidate graph node")
                except Exception as exc:
                    errors.append(f"Corrupt {snap_field} on ArenaWorkflowRun: {exc}")

        # Query observations (ArenaWorkflowEvidence)
        ev_rows = list(
            tx.run(
                f"MATCH (r:ArenaWorkflowRun {scope_clause})-[:HAS_SCENE_RECORD]->(e:ArenaWorkflowEvidence {scope_clause}) "
                "WHERE r.run_id=$run_id "
                "OPTIONAL MATCH (e)-[:FOR_CANDIDATE]->(c:ArenaWorkflowCandidate) "
                "RETURN e.record_id AS evidence_id, e.payload AS payload, c.record_id AS candidate_id",
                **scope,
                run_id=run_id,
            )
        )

        evidence_by_id: dict[str, tuple[Observation, str | None]] = {}
        evidence_by_candidate: dict[str, list[tuple[str, Observation]]] = {}
        all_manifest_digests: list[str] = []

        for row in ev_rows:
            ev_id = row["evidence_id"]
            cand_id = row["candidate_id"]
            try:
                obs = Observation.model_validate_json(row["payload"])
                if expected_contract_digest is not None and obs.cohort.contract_digest != expected_contract_digest:
                    errors.append(f"Observation {ev_id} contract_digest mismatch")
                if expected_profile_digest is not None and obs.cohort.profile_digest != expected_profile_digest:
                    errors.append(f"Observation {ev_id} profile_digest mismatch")
                if cand_id is not None and cand_id not in candidates_by_id:
                    errors.append(f"Observation {ev_id} FOR_CANDIDATE references unknown candidate {cand_id}")

                verified_set = set(obs.verified_manifest_digests)
                if obs.source_manifest_digest is not None and obs.source_manifest_digest not in verified_set:
                    errors.append(
                        f"Observation {ev_id} source_manifest_digest {obs.source_manifest_digest} not in verified_manifest_digests"
                    )
                for item in obs.evidence:
                    if item.manifest_digest not in verified_set:
                        errors.append(
                            f"Observation {ev_id} criterion {item.criterion_id} manifest_digest {item.manifest_digest} not verified"
                        )
                    if item.manifest_digest not in all_manifest_digests:
                        all_manifest_digests.append(item.manifest_digest)
                for m_digest in obs.verified_manifest_digests:
                    if m_digest not in all_manifest_digests:
                        all_manifest_digests.append(m_digest)

                if artifacts is not None and cand_id in candidates_by_id:
                    cand_obj = candidates_by_id[cand_id]
                    binding = CandidateBinding(
                        candidate_digest=cand_obj.digest,
                        contract_digest=obs.cohort.contract_digest,
                        profile_digest=obs.cohort.profile_digest,
                    )
                    for m_digest in obs.verified_manifest_digests:
                        try:
                            receipt = artifacts.load_receipt(
                                binding,
                                obs.cohort,
                                kind="observation",
                                manifest_digest=m_digest,
                                protect=protect,
                            )
                            artifacts.verified_payload(receipt, protect=protect)
                        except Exception as exc:
                            errors.append(
                                f"Artifact manifest verification failed for observation {ev_id} digest {m_digest}: {exc}"
                            )

                evidence_by_id[ev_id] = (obs, cand_id)
                if cand_id is not None:
                    evidence_by_candidate.setdefault(cand_id, []).append((ev_id, obs))
            except Exception as exc:
                errors.append(f"Corrupt observation payload for {ev_id}: {exc}")

        # Query decisions (ArenaWorkflowDecision)
        dec_rows = list(
            tx.run(
                f"MATCH (r:ArenaWorkflowRun {scope_clause})-[:HAS_DECISION]->(d:ArenaWorkflowDecision {scope_clause}) "
                "WHERE r.run_id=$run_id "
                "RETURN d.decision_id AS decision_id, d.candidate_id AS candidate_id, "
                "       d.evidence_id AS evidence_id, d.payload AS payload, d.record_kind AS record_kind",
                **scope,
                run_id=run_id,
            )
        )

        decisions_by_candidate: dict[str, list[tuple[str, SceneDecision, str | None]]] = {}
        decisions_verified = 0
        for row in dec_rows:
            dec_id = row["decision_id"]
            cand_id = row["candidate_id"]
            ev_id = row["evidence_id"]
            raw_payload = row["payload"]
            if cand_id is None and isinstance(raw_payload, str) and raw_payload.startswith("["):
                # Generation reservation record
                continue
            try:
                dec = SceneDecision.model_validate_json(raw_payload)
                if cand_id not in candidates_by_id:
                    errors.append(f"Decision {dec_id} references unknown candidate {cand_id}")
                if ev_id is not None:
                    if ev_id not in evidence_by_id:
                        errors.append(f"Decision {dec_id} references missing evidence {ev_id}")
                    else:
                        _, ev_cand_id = evidence_by_id[ev_id]
                        if ev_cand_id not in (None, cand_id):
                            errors.append(
                                f"Decision {dec_id} candidate {cand_id} mismatches evidence {ev_id} candidate {ev_cand_id}"
                            )
                if dec.assessment is not None and ev_id is not None:
                    assess_rows = list(
                        tx.run(
                            f"MATCH (a:ArenaCriterionAssessment {scope_clause})-[:ASSESSES]->(e:ArenaWorkflowEvidence {scope_clause}) "
                            "WHERE e.record_id=$ev_id RETURN a.payload AS payload",
                            **scope,
                            ev_id=ev_id,
                        )
                    )
                    if not assess_rows:
                        errors.append(f"Decision {dec_id} assessment missing ArenaCriterionAssessment node for {ev_id}")
                    else:
                        stored_assess = SceneEvidenceAssessment.model_validate_json(assess_rows[0]["payload"])
                        if stored_assess != dec.assessment:
                            errors.append(f"Decision {dec_id} assessment diverges from ArenaCriterionAssessment node")
                decisions_verified += 1
                if cand_id is not None:
                    decisions_by_candidate.setdefault(cand_id, []).append((dec_id, dec, ev_id))
            except Exception as exc:
                errors.append(f"Corrupt decision payload for {dec_id}: {exc}")

        # Query BudgetTransactions if present
        budget_tx_rows = list(
            tx.run(
                f"MATCH (b:ExecutionBudget {scope_clause})-[:HAS_TRANSACTION]->(t:BudgetTransaction {scope_clause}) "
                "WHERE b.run_id=$run_id "
                "RETURN t.transaction_id AS tx_id, t.version_watermark AS wm, "
                "       t.error_before AS eb, t.error_after AS ea, t.delta_error AS de, "
                "       t.candidate_id AS cid "
                "ORDER BY t.version_watermark ASC",
                **scope,
                run_id=run_id,
            )
        )
        budget_tx_verified = 0
        prev_wm = 0
        for row in budget_tx_rows:
            wm = int(row["wm"] or 0)
            if wm < prev_wm:
                errors.append(f"BudgetTransaction {row['tx_id']} non-monotonic watermark {wm} < {prev_wm}")
            prev_wm = wm
            eb = float(row["eb"] or 0.0)
            ea = float(row["ea"] or 0.0)
            de = float(row["de"] or 0.0)
            if abs(round(eb - ea, 8) - round(de, 8)) > 1e-6:
                errors.append(f"BudgetTransaction {row['tx_id']} delta_error mismatch: {eb} - {ea} != {de}")
            cid = row["cid"]
            if cid is not None and cid not in candidates_by_id:
                errors.append(f"BudgetTransaction {row['tx_id']} references unknown candidate {cid}")
            budget_tx_verified += 1

    # Order candidates topologically from root to leaf
    ordered_candidates: list[CandidateRecord] = []
    visited: set[str] = set()
    roots = sorted(
        [c for c in candidates_by_id.values() if c.parent_id is None],
        key=lambda c: c.candidate_id,
    )
    children_map: dict[str, list[CandidateRecord]] = {}
    for c in candidates_by_id.values():
        if c.parent_id is not None:
            children_map.setdefault(c.parent_id, []).append(c)
    for k in children_map:
        children_map[k].sort(key=lambda c: c.candidate_id)

    queue = list(roots)
    while queue:
        curr = queue.pop(0)
        if curr.candidate_id in visited:
            errors.append(f"Cycle detected in candidate lineage at {curr.candidate_id}")
            break
        visited.add(curr.candidate_id)
        ordered_candidates.append(curr)
        queue.extend(children_map.get(curr.candidate_id, []))

    for cid, c in sorted(candidates_by_id.items()):
        if cid not in visited:
            ordered_candidates.append(c)

    step_links: list[EvidenceChainStepLink] = []
    for idx, cand in enumerate(ordered_candidates):
        parent_cand = candidates_by_id.get(cand.parent_id) if cand.parent_id else None
        input_digest = parent_cand.digest if parent_cand is not None else None
        cand_ev_list = evidence_by_candidate.get(cand.candidate_id, [])
        ev_id = cand_ev_list[-1][0] if cand_ev_list else None
        ev_digests: list[str] = []
        for _, obs in cand_ev_list:
            for d in obs.verified_manifest_digests:
                if d not in ev_digests:
                    ev_digests.append(d)
        cand_dec_list = decisions_by_candidate.get(cand.candidate_id, [])
        dec_id = cand_dec_list[-1][0] if cand_dec_list else None
        dec_action = cand_dec_list[-1][1].action if cand_dec_list else None
        if ev_id is None and cand_dec_list and cand_dec_list[-1][2] is not None:
            ev_id = cand_dec_list[-1][2]
            if ev_id in evidence_by_id:
                for d in evidence_by_id[ev_id][0].verified_manifest_digests:
                    if d not in ev_digests:
                        ev_digests.append(d)

        step_links.append(
            EvidenceChainStepLink(
                step_index=idx,
                candidate_id=cand.candidate_id,
                input_digest=input_digest,
                output_digest=cand.digest,
                evidence_id=ev_id,
                evidence_manifest_digests=tuple(ev_digests),
                decision_id=dec_id,
                decision_action=dec_action,
            )
        )

    chain_payload = [link.model_dump(mode="json") for link in step_links]
    chain_digest = hashlib.sha256(canonical(chain_payload)).hexdigest()
    is_valid = len(errors) == 0

    if strict and not is_valid:
        raise ValueError("Evidence chain verification failed: " + "; ".join(errors))

    return EvidenceChainAuditReport(
        run_id=run_id,
        valid=is_valid,
        steps_verified=len(step_links),
        candidate_chain=tuple(step_links),
        evidence_manifest_digests=tuple(all_manifest_digests),
        decisions_verified=decisions_verified,
        budget_transactions_verified=budget_tx_verified,
        chain_digest=chain_digest,
        errors=tuple(errors),
    )

