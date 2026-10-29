# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""SHACL validation helper for RDF-star environment graphs."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid

import pyshacl
from pydantic import BaseModel, ConfigDict, Field
import rdflib

DEFAULT_SHACL_PATH = Path(__file__).parent / "ontology" / "arena_constraints.shacl.ttl"


class SHACLValidationReport(BaseModel):
    """Structured receipt from Job J4 (W3C SHACL Semantic Validator)."""

    model_config = ConfigDict(frozen=True)

    conforms: bool
    violations: list[str] = Field(default_factory=list)
    report_text: str = ""
    triples_count: int = 0


def validate_rdf_environment_graph(
    data_graph: rdflib.Graph,
    shacl_path: Path | str = DEFAULT_SHACL_PATH,
) -> tuple[bool, str]:
    """Validate an RDF-star environment graph against the arena SHACL constraint shapes.

    Args:
        data_graph: An rdflib Graph containing the parsed scene and entities.
        shacl_path: Filesystem path to the SHACL constraint rules (.ttl).

    Returns:
        A tuple ``(conforms, report_text)``. When ``conforms`` is False, ``report_text``
        contains the detailed human-readable validation violations.
    """
    shacl_graph = rdflib.Graph()
    shacl_graph.parse(str(shacl_path), format="turtle")

    conforms, results_graph, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shacl_graph,
        inference="rdfs",
        abort_on_first=False,
        meta_shacl=False,
        advanced=True,
    )
    return bool(conforms), str(results_text)


def _extract_shacl_violations(results_text: str, conforms: bool) -> list[str]:
    """Extract violation messages from pyshacl validation report text."""
    if conforms:
        return []
    violations: list[str] = []
    for line in str(results_text).splitlines():
        stripped = line.strip()
        if stripped.startswith("Message:") or stripped.startswith("Constraint Violation"):
            violations.append(stripped)
    if not violations and str(results_text).strip():
        violations.append(str(results_text).strip())
    return violations


def validate_shacl_report(
    spec_or_graph: Any,
    shacl_path: Path | str = DEFAULT_SHACL_PATH,
) -> SHACLValidationReport:
    """Validate an ArenaEnvGraphSpec, scene dict, or rdflib.Graph and return SHACLValidationReport."""
    if isinstance(spec_or_graph, rdflib.Graph):
        data_graph = spec_or_graph
    else:
        from isaaclab_arena.agentic_environment_generation.execution.spec_synthesis_worker import (
            build_permissive_fallback_spec,
        )
        from isaaclab_arena.agentic_environment_generation.rdf_lowering import spec_to_rdf_graph
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

        if isinstance(spec_or_graph, dict):
            try:
                spec = ArenaEnvGraphSpec.from_dict(spec_or_graph)
            except Exception:
                spec = build_permissive_fallback_spec(
                    env_name=str(spec_or_graph.get("env_name") or spec_or_graph.get("name") or "fallback_env")
                )
        else:
            spec = spec_or_graph
        data_graph = spec_to_rdf_graph(spec)

    conforms, report_text = validate_rdf_environment_graph(data_graph, shacl_path=shacl_path)
    violations = _extract_shacl_violations(report_text, conforms)
    return SHACLValidationReport(
        conforms=bool(conforms),
        violations=violations,
        report_text=str(report_text),
        triples_count=len(data_graph),
    )


class SHACLValidatorWorker:
    """Job J4 WorkerPort-compatible W3C SHACL Semantic Validator."""

    def __init__(self, shacl_path: Path | str = DEFAULT_SHACL_PATH) -> None:
        self.shacl_path = shacl_path

    def validate(self, spec_or_graph: Any) -> SHACLValidationReport:
        """Run SHACL validation and return structured SHACLValidationReport."""
        return validate_shacl_report(spec_or_graph, shacl_path=self.shacl_path)

    def prepare(self, fence: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        """Prepare WorkerPort handle for Job J4."""
        wid = f"shacl-validator-{uuid.uuid4().hex[:8]}"
        handle: dict[str, Any] = {"worker_id": wid, "fence": fence, "request": None}
        return handle, {"worker_id": wid}

    def send(self, handle: dict[str, Any], request: dict[str, Any]) -> None:
        """Accept SHACL validation request payload."""
        handle["request"] = dict(request)

    def receive(self, handle: dict[str, Any], deadline: float | None = None) -> dict[str, Any]:
        """Execute SHACL validation and return serialized SHACLValidationReport."""
        req = handle.get("request") or {}
        target = req.get("spec") or req.get("graph") or req.get("scene") or req
        report = self.validate(target)
        return report.model_dump(mode="json")

    def stop_owned(self, handle: dict[str, Any]) -> dict[str, Any]:
        """Release WorkerPort handle cleanly."""
        handle["request"] = None
        return {"worker_id": handle.get("worker_id", "shacl-validator"), "stopped": True}


PROVENANCE_SHACL_TTL = """
@prefix arena: <https://isaac-sim.github.io/arena/schema#> .
@prefix prov:  <http://www.w3.org/ns/prov#> .
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .

arena:CandidateProvenanceShape a sh:NodeShape ;
    sh:targetClass arena:CandidateRecord ;
    sh:property [
        sh:path arena:candidateId ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:message "ERROR: Every CandidateRecord must declare arena:candidateId." ;
    ] ;
    sh:property [
        sh:path arena:candidateDigest ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:message "ERROR: Every CandidateRecord must declare arena:candidateDigest." ;
    ] ;
    sh:property [
        sh:path prov:wasGeneratedBy ;
        sh:minCount 1 ;
        sh:message "ERROR: Every CandidateRecord must link prov:wasGeneratedBy to an activity." ;
    ] ;
    sh:property [
        sh:path prov:wasAttributedTo ;
        sh:minCount 1 ;
        sh:message "ERROR: Every CandidateRecord must link prov:wasAttributedTo to an agent." ;
    ] .

arena:ObservationProvenanceShape a sh:NodeShape ;
    sh:targetClass arena:ObservationRecord ;
    sh:property [
        sh:path arena:evidenceId ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:message "ERROR: Every ObservationRecord must declare arena:evidenceId." ;
    ] ;
    sh:property [
        sh:path arena:forCandidate ;
        sh:minCount 1 ;
        sh:message "ERROR: Every ObservationRecord must link arena:forCandidate." ;
    ] ;
    sh:property [
        sh:path prov:wasGeneratedBy ;
        sh:minCount 1 ;
        sh:message "ERROR: Every ObservationRecord must link prov:wasGeneratedBy." ;
    ] ;
    sh:property [
        sh:path prov:wasAttributedTo ;
        sh:minCount 1 ;
        sh:message "ERROR: Every ObservationRecord must link prov:wasAttributedTo." ;
    ] .

arena:SceneDecisionProvenanceShape a sh:NodeShape ;
    sh:targetClass arena:SceneDecisionRecord ;
    sh:property [
        sh:path arena:decisionId ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:message "ERROR: Every SceneDecisionRecord must declare arena:decisionId." ;
    ] ;
    sh:property [
        sh:path arena:decisionAction ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:message "ERROR: Every SceneDecisionRecord must declare arena:decisionAction." ;
    ] ;
    sh:property [
        sh:path prov:wasGeneratedBy ;
        sh:minCount 1 ;
        sh:message "ERROR: Every SceneDecisionRecord must link prov:wasGeneratedBy." ;
    ] ;
    sh:property [
        sh:path prov:wasAttributedTo ;
        sh:minCount 1 ;
        sh:message "ERROR: Every SceneDecisionRecord must link prov:wasAttributedTo." ;
    ] .

arena:BudgetTransactionProvenanceShape a sh:NodeShape ;
    sh:targetClass arena:BudgetTransactionRecord ;
    sh:property [
        sh:path arena:transactionId ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:message "ERROR: Every BudgetTransactionRecord must declare arena:transactionId." ;
    ] ;
    sh:property [
        sh:path arena:horizonAfter ;
        sh:minCount 1 ;
        sh:datatype xsd:integer ;
        sh:message "ERROR: Every BudgetTransactionRecord must declare integer arena:horizonAfter." ;
    ] ;
    sh:property [
        sh:path prov:wasAttributedTo ;
        sh:minCount 1 ;
        sh:message "ERROR: Every BudgetTransactionRecord must link prov:wasAttributedTo." ;
    ] .

arena:ReifiedStatementProvenanceShape a sh:NodeShape ;
    sh:targetClass arena:ReifiedProvenanceStatement ;
    sh:property [
        sh:path rdf:subject ;
        sh:minCount 1 ;
        sh:message "ERROR: ReifiedProvenanceStatement missing rdf:subject." ;
    ] ;
    sh:property [
        sh:path rdf:predicate ;
        sh:minCount 1 ;
        sh:message "ERROR: ReifiedProvenanceStatement missing rdf:predicate." ;
    ] ;
    sh:property [
        sh:path rdf:object ;
        sh:minCount 1 ;
        sh:message "ERROR: ReifiedProvenanceStatement missing rdf:object." ;
    ] ;
    sh:property [
        sh:path prov:wasAttributedTo ;
        sh:minCount 1 ;
        sh:message "ERROR: ReifiedProvenanceStatement must declare prov:wasAttributedTo." ;
    ] .
"""


def _safe_token(raw: str, max_len: int = 24) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(raw))
    return cleaned[:max_len] or "item"


def export_run_provenance_rdf_star(
    run_id: str,
    neo4j_store: Any = None,
    *,
    audit_report: Any = None,
    budget_txs: list[dict[str, Any]] | None = None,
) -> str:
    """Serialize a workflow run's execution trace and cryptographic chain as W3C PROV-O Turtle-star.

    Produces reified Turtle-star triples (e.g. ``<<( :budget arena:extendedHorizon H )>> prov:wasAttributedTo ...``)
    linking ``:CandidateRecord``, ``:ObservationRecord``, ``:BudgetTransactionRecord``, and ``:SceneDecisionRecord``
    with ``prov:wasGeneratedBy`` and ``prov:wasAttributedTo``.
    """
    from isaaclab_arena.agentic_environment_generation.workflow.derived_assessment import (
        verify_run_evidence_chain,
    )

    if audit_report is None:
        audit_report = verify_run_evidence_chain(run_id, neo4j_store, strict=True)

    if budget_txs is None:
        budget_txs = []
        if neo4j_store is not None and hasattr(neo4j_store, "list_budget_transactions"):
            try:
                budget_txs = list(neo4j_store.list_budget_transactions(run_id))
            except Exception:
                budget_txs = []

    run_tok = _safe_token(run_id, 16)
    lines: list[str] = [
        "@prefix arena: <https://isaac-sim.github.io/arena/schema#> .",
        "@prefix prov:  <http://www.w3.org/ns/prov#> .",
        "@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix :      <https://isaac-sim.github.io/arena/instances/> .",
        "",
        ":macro_orchestrator a prov:SoftwareAgent, arena:OrchestratorAgent .",
        ":causal_estimator_j7 a prov:SoftwareAgent, arena:CausalEstimatorAgent .",
        "",
        f":run_{run_tok} a prov:Activity, arena:WorkflowRun ;",
        f'    arena:runId "{run_id}"^^xsd:string ;',
        f'    arena:chainDigest "{audit_report.chain_digest}"^^xsd:string ;',
        "    prov:wasAssociatedWith :macro_orchestrator .",
        "",
        ":budget a prov:Entity, arena:ExecutionBudget ;",
        f'    arena:runId "{run_id}"^^xsd:string ;',
        "    prov:wasAttributedTo :macro_orchestrator .",
        "",
    ]

    cand_uri_map: dict[str, str] = {}
    for link in audit_report.candidate_chain:
        cid = link.candidate_id
        cand_tok = f"candidate_{_safe_token(cid, 16)}"
        cand_uri_map[cid] = f":{cand_tok}"
        act_uri = f":step_activity_{run_tok}_{link.step_index}"
        lines.extend([
            f"{act_uri} a prov:Activity, arena:SceneLoopStep ;",
            f"    arena:stepIndex {link.step_index} ;",
            "    prov:wasAssociatedWith :macro_orchestrator .",
            "",
            f":{cand_tok} a prov:Entity, arena:CandidateRecord ;",
            f'    arena:candidateId "{cid}"^^xsd:string ;',
            f'    arena:candidateDigest "{link.output_digest}"^^xsd:string ;',
            f"    prov:wasGeneratedBy {act_uri} ;",
            "    prov:wasAttributedTo :macro_orchestrator .",
            f'<<( :{cand_tok} arena:candidateDigest "{link.output_digest}"^^xsd:string )>> '
            f"prov:wasAttributedTo :macro_orchestrator ; prov:wasGeneratedBy {act_uri} .",
        ])
        if link.input_digest is not None:
            lines.append(f':{cand_tok} arena:inputDigest "{link.input_digest}"^^xsd:string .')
            for prev_link in audit_report.candidate_chain:
                if prev_link.output_digest == link.input_digest and prev_link.candidate_id in cand_uri_map:
                    lines.append(f":{cand_tok} prov:wasDerivedFrom {cand_uri_map[prev_link.candidate_id]} .")
                    break
        lines.append("")

        if link.evidence_id is not None:
            ev_tok = f"observation_{_safe_token(link.evidence_id, 16)}"
            lines.extend([
                f":{ev_tok} a prov:Entity, arena:ObservationRecord ;",
                f'    arena:evidenceId "{link.evidence_id}"^^xsd:string ;',
                f"    arena:forCandidate :{cand_tok} ;",
                f"    prov:wasGeneratedBy {act_uri} ;",
                "    prov:wasAttributedTo :macro_orchestrator .",
            ])
            for m_digest in link.evidence_manifest_digests:
                lines.append(f':{ev_tok} arena:manifestDigest "{m_digest}"^^xsd:string .')
                lines.append(
                    f'<<( :{ev_tok} arena:manifestDigest "{m_digest}"^^xsd:string )>> '
                    f"prov:wasAttributedTo :macro_orchestrator ; prov:wasGeneratedBy {act_uri} ."
                )
            lines.append("")

        if link.decision_id is not None:
            dec_tok = f"decision_{_safe_token(link.decision_id, 16)}"
            action_str = link.decision_action or "observe"
            lines.extend([
                f":{dec_tok} a prov:Entity, arena:SceneDecisionRecord ;",
                f'    arena:decisionId "{link.decision_id}"^^xsd:string ;',
                f'    arena:decisionAction "{action_str}"^^xsd:string ;',
                f"    prov:used :{cand_tok} ;",
                f"    prov:wasGeneratedBy {act_uri} ;",
                "    prov:wasAttributedTo :macro_orchestrator .",
                f'<<( :{dec_tok} arena:decisionAction "{action_str}"^^xsd:string )>> '
                f"prov:wasAttributedTo :macro_orchestrator ; prov:wasGeneratedBy {act_uri} .",
                "",
            ])

    if budget_txs:
        for tx_item in budget_txs:
            tx_id = str(tx_item.get("transaction_id") or uuid.uuid4().hex)
            tx_tok = f"tx_{_safe_token(tx_id, 16)}"
            h_after = int(tx_item.get("horizon_after") or 0)
            de = float(tx_item.get("delta_error") or 0.0)
            lines.extend([
                f":{tx_tok} a prov:Activity, prov:Entity, arena:BudgetTransactionRecord ;",
                f'    arena:transactionId "{tx_id}"^^xsd:string ;',
                f"    arena:horizonAfter {h_after} ;",
                f"    arena:lyapunovDeltaError {de:.6f} ;",
                "    prov:wasAttributedTo :causal_estimator_j7 ;",
                "    prov:wasAssociatedWith :macro_orchestrator .",
                f":budget arena:extendedHorizon {h_after} .",
                f"<<( :budget arena:extendedHorizon {h_after} )>> "
                f"prov:wasAttributedTo :macro_orchestrator ; prov:wasGeneratedBy :{tx_tok} .",
                "",
            ])
    else:
        default_tx_tok = f"tx_init_{run_tok}"
        lines.extend([
            f":{default_tx_tok} a prov:Activity, prov:Entity, arena:BudgetTransactionRecord ;",
            f'    arena:transactionId "init_{run_tok}"^^xsd:string ;',
            "    arena:horizonAfter 1 ;",
            "    arena:lyapunovDeltaError 0.000000 ;",
            "    prov:wasAttributedTo :causal_estimator_j7 ;",
            "    prov:wasAssociatedWith :macro_orchestrator .",
            ":budget arena:extendedHorizon 1 .",
            f"<<( :budget arena:extendedHorizon 1 )>> "
            f"prov:wasAttributedTo :macro_orchestrator ; prov:wasGeneratedBy :{default_tx_tok} .",
            "",
        ])

    return "\n".join(lines)


def parse_turtle_star_to_rdf_graph(turtle_star_text: str) -> rdflib.Graph:
    """Parse a W3C RDF-star / Turtle-star document into an rdflib.Graph with reified statement nodes."""
    import re

    standard_lines: list[str] = []
    reified_blocks: list[str] = []
    reifier_idx = 0

    pattern = re.compile(r"^\s*<<\(\s*(\S+)\s+(\S+)\s+(.+?)\s*\)>>\s*(.+?)\.\s*$")
    pattern_cg = re.compile(r"^\s*<<\s*(\S+)\s+(\S+)\s+(.+?)\s*>>\s*(.+?)\.\s*$")

    for line in turtle_star_text.splitlines():
        m = pattern.match(line) or pattern_cg.match(line)
        if m:
            subj, pred, obj, annotations = m.group(1), m.group(2), m.group(3).strip(), m.group(4).strip()
            reifier_idx += 1
            reifier_node = f":reified_stmt_{reifier_idx}"
            standard_lines.append(f"{subj} {pred} {obj} .")
            reified_blocks.append(
                f"{reifier_node} a arena:ReifiedProvenanceStatement, rdf:Statement ;\n"
                f"    rdf:subject {subj} ;\n"
                f"    rdf:predicate {pred} ;\n"
                f"    rdf:object {obj} ;\n"
                f"    {annotations} ."
            )
        else:
            standard_lines.append(line)

    combined_ttl = "\n".join(standard_lines + [""] + reified_blocks)
    g = rdflib.Graph()
    g.parse(data=combined_ttl, format="turtle")
    return g


def validate_provenance_rdf_star(
    turtle_star_or_graph: str | rdflib.Graph,
    shacl_ttl: str = PROVENANCE_SHACL_TTL,
) -> SHACLValidationReport:
    """Validate a W3C PROV-O RDF-star execution trace against PROV-O and Arena SHACL shapes."""
    if isinstance(turtle_star_or_graph, str):
        data_graph = parse_turtle_star_to_rdf_graph(turtle_star_or_graph)
    else:
        data_graph = turtle_star_or_graph

    shacl_graph = rdflib.Graph()
    shacl_graph.parse(data=shacl_ttl, format="turtle")

    conforms, _results_graph, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shacl_graph,
        inference="rdfs",
        abort_on_first=False,
        meta_shacl=False,
        advanced=True,
    )
    violations = _extract_shacl_violations(str(results_text), bool(conforms))
    return SHACLValidationReport(
        conforms=bool(conforms),
        violations=violations,
        report_text=str(results_text),
        triples_count=len(data_graph),
    )


export_run_provenance_to_rdf_star = export_run_provenance_rdf_star



