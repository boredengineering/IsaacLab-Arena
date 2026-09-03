# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Projects the policy diagnostics knowledge base onto the RDF-star and Neo4j LPG graphs.

``policy_capability_graph`` holds the registries as Python values so they stay cheap to import.
This module writes them into the two graph representations the pipeline already maintains, so
that a policy's training invariants, the shifts a scene induces against them, the evidence
gathered, and the technique chosen next are all queryable next to the scene structure.

The registries are static, so ``emit_technique_catalogue_rdf`` is idempotent and safe to run on
every evaluation; the per-run parts hang off an ``arena:EvaluationRun`` node.
"""

from __future__ import annotations

from typing import Any, Optional
import rdflib
from rdflib import Literal, Namespace, RDF, RDFS, XSD

from isaaclab_arena.agentic_environment_generation.policy_capability_graph import (
    DIAGNOSTIC_TECHNIQUES,
    FAILURE_MODES,
    REMEDIATION_TECHNIQUES,
    SIM_TO_REAL_INVARIANTS,
    DistributionShift,
    PolicyDiagnosticState,
    PolicyProfile,
)

ARENA = Namespace("https://isaac-sim.github.io/arena/schema#")
PROV = Namespace("http://www.w3.org/ns/prov#")
INSTANCES = Namespace("https://isaac-sim.github.io/arena/instances/")

SPARQL_BLOCKING_SHIFTS = """
PREFIX arena: <https://isaac-sim.github.io/arena/schema#>
SELECT ?axis ?sigma ?mode ?remediation ?efficacy
WHERE {
    ?shift a arena:DistributionShift ;
           arena:shiftAxis ?axis ;
           arena:shiftSigma ?sigma ;
           arena:withinTolerance false ;
           arena:manifestsAs ?mode .
    OPTIONAL {
        ?remediation a arena:RemediationTechnique ;
                     arena:resolves ?mode ;
                     arena:expectedEfficacy ?efficacy .
        FILTER NOT EXISTS { ?remediation arena:invalidatedBy ?forbidden . }
    }
}
ORDER BY DESC(?sigma)
"""
"""Every out-of-tolerance shift with the failure mode it implies and the admissible fixes for it."""

SPARQL_TECHNIQUES_FOR_MODE = """
PREFIX arena: <https://isaac-sim.github.io/arena/schema#>
SELECT ?technique ?cost ?metric
WHERE {
    ?technique a arena:DiagnosticTechnique ;
               arena:discriminates ?mode ;
               arena:techniqueCost ?cost ;
               arena:probeMetric ?metric .
}
ORDER BY ?cost
"""
"""Diagnostic techniques able to separate a given failure mode, cheapest first."""


def _bind_prefixes(graph: rdflib.Graph) -> None:
    """Bind the arena, prov, and instance prefixes on ``graph``."""
    graph.bind("arena", ARENA)
    graph.bind("prov", PROV)
    graph.bind("", INSTANCES)


def emit_technique_catalogue_rdf(graph: rdflib.Graph | None = None) -> rdflib.Graph:
    """Emit the static failure-mode, diagnostic, and remediation registries as RDF.

    Args:
        graph: Graph to add to; a new one is created when omitted.

    Returns:
        The graph, with the catalogue merged in.
    """
    graph = graph if graph is not None else rdflib.Graph()
    _bind_prefixes(graph)

    for name, description in SIM_TO_REAL_INVARIANTS.items():
        uri = INSTANCES[f"invariant_{name}"]
        graph.add((uri, RDF.type, ARENA.SimToRealInvariant))
        graph.add((uri, RDFS.comment, Literal(description, datatype=XSD.string)))

    for mode in FAILURE_MODES.values():
        uri = INSTANCES[f"failure_{mode.mode_id}"]
        graph.add((uri, RDF.type, ARENA.FailureMode))
        graph.add((uri, RDFS.label, Literal(mode.label, datatype=XSD.string)))
        graph.add((uri, RDFS.comment, Literal(mode.description, datatype=XSD.string)))
        graph.add((uri, ARENA.failureLayer, Literal(mode.layer, datatype=XSD.string)))
        graph.add((uri, ARENA.priorBelief, Literal(mode.prior, datatype=XSD.float)))
        for excluded in mode.excludes:
            graph.add((uri, ARENA.excludes, INSTANCES[f"failure_{excluded}"]))

    for technique in DIAGNOSTIC_TECHNIQUES.values():
        uri = INSTANCES[f"diagnostic_{technique.technique_id}"]
        graph.add((uri, RDF.type, ARENA.DiagnosticTechnique))
        if technique.is_activation_probe:
            graph.add((uri, RDF.type, ARENA.ActivationProbe))
        graph.add((uri, RDFS.label, Literal(technique.label, datatype=XSD.string)))
        graph.add((uri, RDFS.comment, Literal(technique.description, datatype=XSD.string)))
        graph.add((uri, ARENA.probeMetric, Literal(technique.metric, datatype=XSD.string)))
        graph.add((uri, ARENA.techniqueCost, Literal(technique.cost, datatype=XSD.float)))
        graph.add((uri, ARENA.requiresPolicyWeights, Literal(technique.requires_policy_weights, datatype=XSD.boolean)))
        graph.add((uri, ARENA.requiresRollout, Literal(technique.requires_rollout, datatype=XSD.boolean)))
        graph.add((uri, ARENA.requiresGpu, Literal(technique.requires_gpu, datatype=XSD.boolean)))
        graph.add((
            uri,
            ARENA.requiresReferenceDataset,
            Literal(technique.requires_reference_dataset, datatype=XSD.boolean),
        ))
        if technique.probes_module:
            graph.add((uri, ARENA.probesModule, Literal(technique.probes_module, datatype=XSD.string)))
        for mode_id in technique.discriminates:
            graph.add((uri, ARENA.discriminates, INSTANCES[f"failure_{mode_id}"]))

    for remediation in REMEDIATION_TECHNIQUES.values():
        uri = INSTANCES[f"remediation_{remediation.technique_id}"]
        graph.add((uri, RDF.type, ARENA.RemediationTechnique))
        graph.add((uri, RDFS.label, Literal(remediation.label, datatype=XSD.string)))
        graph.add((uri, RDFS.comment, Literal(remediation.description, datatype=XSD.string)))
        graph.add((uri, ARENA.expectedEfficacy, Literal(remediation.expected_efficacy, datatype=XSD.float)))
        graph.add((uri, ARENA.techniqueCost, Literal(remediation.cost, datatype=XSD.float)))
        for mode_id in remediation.resolves:
            graph.add((uri, ARENA.resolves, INSTANCES[f"failure_{mode_id}"]))
        for invariant_name in remediation.invalidated_by:
            graph.add((uri, ARENA.invalidatedBy, INSTANCES[f"invariant_{invariant_name}"]))

    return graph


def emit_policy_profile_rdf(profile: PolicyProfile, graph: rdflib.Graph | None = None) -> rdflib.Graph:
    """Emit a policy, its architecture, its corpus, and the invariants that corpus established."""
    graph = graph if graph is not None else rdflib.Graph()
    _bind_prefixes(graph)

    policy_uri = INSTANCES[f"policy_{profile.policy_id}"]
    arch_uri = INSTANCES[f"architecture_{profile.policy_id}"]
    corpus_uri = INSTANCES[f"corpus_{profile.corpus_id}"]

    graph.add((policy_uri, RDF.type, ARENA.Policy))
    graph.add((policy_uri, ARENA.checkpointUri, Literal(profile.checkpoint_uri, datatype=XSD.string)))
    graph.add((policy_uri, ARENA.policyKind, Literal(profile.policy_kind, datatype=XSD.string)))
    graph.add((policy_uri, ARENA.controllerBinding, Literal(profile.controller_binding, datatype=XSD.string)))
    if profile.language_instruction:
        graph.add((policy_uri, ARENA.languageInstruction, Literal(profile.language_instruction, datatype=XSD.string)))
    graph.add((policy_uri, ARENA.hasArchitecture, arch_uri))
    graph.add((policy_uri, ARENA.wasTrainedOn, corpus_uri))

    graph.add((arch_uri, RDF.type, ARENA.PolicyArchitecture))
    graph.add((arch_uri, ARENA.actionDim, Literal(profile.action_dim, datatype=XSD.integer)))
    graph.add((arch_uri, ARENA.actionChunkLength, Literal(profile.action_chunk_length, datatype=XSD.integer)))
    graph.add((arch_uri, ARENA.numDenoisingSteps, Literal(profile.num_denoising_steps, datatype=XSD.integer)))
    if profile.vision_backbone:
        graph.add((arch_uri, ARENA.visionBackbone, Literal(profile.vision_backbone, datatype=XSD.string)))
    if profile.action_head_kind:
        graph.add((arch_uri, ARENA.actionHeadKind, Literal(profile.action_head_kind, datatype=XSD.string)))

    graph.add((corpus_uri, RDF.type, ARENA.DemonstrationCorpus))
    graph.add((corpus_uri, ARENA.demoCount, Literal(profile.demo_count, datatype=XSD.integer)))
    graph.add((corpus_uri, ARENA.referenceScene, INSTANCES[profile.reference_scene]))

    for invariant in profile.invariants:
        inv_uri = INSTANCES[f"invariant_{profile.corpus_id}_{invariant.axis}"]
        graph.add((inv_uri, RDF.type, ARENA.TrainingInvariant))
        graph.add((inv_uri, ARENA.invariantAxis, Literal(invariant.axis, datatype=XSD.string)))
        graph.add((inv_uri, RDFS.comment, Literal(invariant.description, datatype=XSD.string)))
        if invariant.value is not None:
            graph.add((inv_uri, ARENA.invariantValue, Literal(invariant.value, datatype=XSD.string)))
        if invariant.numeric_value is not None:
            graph.add((inv_uri, ARENA.invariantNumericValue, Literal(invariant.numeric_value, datatype=XSD.float)))
        if invariant.tolerance is not None:
            graph.add((inv_uri, ARENA.invariantTolerance, Literal(invariant.tolerance, datatype=XSD.float)))
        if invariant.unit:
            graph.add((inv_uri, ARENA.invariantUnit, Literal(invariant.unit, datatype=XSD.string)))
        graph.add((corpus_uri, ARENA.establishesInvariant, inv_uri))

    return graph


def emit_distribution_shifts_rdf(
    env_name: str,
    profile: PolicyProfile,
    shifts: list[DistributionShift],
    graph: rdflib.Graph | None = None,
) -> rdflib.Graph:
    """Emit reified shift measurements linking an environment graph to a policy's invariants.

    Out-of-tolerance shifts additionally assert ``arena:violatesInvariant`` from the scene to the
    invariant, which is the edge a SPARQL or Cypher query follows to ask "why should this policy be
    expected to fail here".
    """
    graph = graph if graph is not None else rdflib.Graph()
    _bind_prefixes(graph)

    scene_uri = INSTANCES[env_name]
    policy_uri = INSTANCES[f"policy_{profile.policy_id}"]

    for index, shift in enumerate(shifts):
        shift_uri = INSTANCES[f"shift_{env_name}_{profile.policy_id}_{shift.axis}_{index}"]
        inv_uri = INSTANCES[f"invariant_{profile.corpus_id}_{shift.axis}"]

        graph.add((shift_uri, RDF.type, ARENA.DistributionShift))
        graph.add((shift_uri, ARENA.shiftInGraph, scene_uri))
        graph.add((shift_uri, ARENA.shiftForPolicy, policy_uri))
        graph.add((shift_uri, ARENA.shiftOfInvariant, inv_uri))
        graph.add((shift_uri, ARENA.shiftAxis, Literal(shift.axis, datatype=XSD.string)))
        graph.add((shift_uri, ARENA.shiftMagnitude, Literal(shift.magnitude, datatype=XSD.float)))
        graph.add((shift_uri, ARENA.shiftSigma, Literal(shift.sigma, datatype=XSD.float)))
        graph.add((shift_uri, ARENA.withinTolerance, Literal(shift.within_tolerance, datatype=XSD.boolean)))
        graph.add((shift_uri, RDFS.comment, Literal(shift.evidence, datatype=XSD.string)))
        for mode_id in shift.manifests_as:
            graph.add((shift_uri, ARENA.manifestsAs, INSTANCES[f"failure_{mode_id}"]))
        if not shift.within_tolerance:
            graph.add((scene_uri, ARENA.violatesInvariant, inv_uri))

    return graph


def emit_diagnostic_state_rdf(
    eval_run_id: str,
    env_name: str,
    profile: PolicyProfile,
    state: PolicyDiagnosticState,
    next_technique_id: str | None = None,
    remediation_id: str | None = None,
    graph: rdflib.Graph | None = None,
) -> rdflib.Graph:
    """Emit an evaluation run's posterior beliefs, evidence, and selected next steps."""
    graph = graph if graph is not None else rdflib.Graph()
    _bind_prefixes(graph)

    run_uri = INSTANCES[eval_run_id]
    graph.add((run_uri, RDF.type, ARENA.EvaluationRun))
    graph.add((run_uri, ARENA.evaluatedGraph, INSTANCES[env_name]))
    graph.add((run_uri, ARENA.evaluatedPolicy, INSTANCES[f"policy_{profile.policy_id}"]))

    for technique_id in state.applied_techniques:
        graph.add((run_uri, ARENA.appliedTechnique, INSTANCES[f"diagnostic_{technique_id}"]))

    for mode_id, belief in state.beliefs.items():
        mode_uri = INSTANCES[f"failure_{mode_id}"]
        belief_uri = INSTANCES[f"belief_{eval_run_id}_{mode_id}"]
        graph.add((belief_uri, RDF.type, ARENA.ProbeObservation))
        graph.add((belief_uri, ARENA.observedDuring, run_uri))
        graph.add((belief_uri, ARENA.observationMetric, Literal(f"posterior_belief::{mode_id}", datatype=XSD.string)))
        graph.add((belief_uri, ARENA.observationValue, Literal(belief, datatype=XSD.float)))
        graph.add((mode_uri, ARENA.posteriorBelief, Literal(belief, datatype=XSD.float)))

    for index, observation in enumerate(state.observations):
        obs_uri = INSTANCES[f"observation_{eval_run_id}_{index}"]
        graph.add((obs_uri, RDF.type, ARENA.ProbeObservation))
        graph.add((obs_uri, ARENA.observedDuring, run_uri))
        graph.add((obs_uri, ARENA.producedByTechnique, INSTANCES[f"diagnostic_{observation.technique_id}"]))
        graph.add((obs_uri, ARENA.observationMetric, Literal(observation.metric, datatype=XSD.string)))
        graph.add((obs_uri, ARENA.observationValue, Literal(observation.value, datatype=XSD.float)))
        graph.add((obs_uri, ARENA.likelihoodRatio, Literal(observation.likelihood_ratio, datatype=XSD.float)))
        if observation.reference is not None:
            graph.add((obs_uri, ARENA.observationReference, Literal(observation.reference, datatype=XSD.float)))
        if observation.note:
            graph.add((obs_uri, RDFS.comment, Literal(observation.note, datatype=XSD.string)))
        for mode_id in observation.supports:
            graph.add((obs_uri, ARENA.supports, INSTANCES[f"failure_{mode_id}"]))
        for mode_id in observation.refutes:
            graph.add((obs_uri, ARENA.refutes, INSTANCES[f"failure_{mode_id}"]))

    dominant = state.dominant()
    if dominant:
        graph.add((run_uri, ARENA.attributedToFailureMode, INSTANCES[f"failure_{dominant[0]}"]))
    if next_technique_id:
        graph.add((run_uri, ARENA.nextTechnique, INSTANCES[f"diagnostic_{next_technique_id}"]))
    if remediation_id:
        graph.add((run_uri, ARENA.remediatedBy, INSTANCES[f"remediation_{remediation_id}"]))

    return graph


def emit_policy_diagnostics_ttl(
    out_path: str,
    env_name: str,
    profile: PolicyProfile,
    state: PolicyDiagnosticState,
    eval_run_id: str = "policy_diagnostics_run",
    next_technique_id: str | None = None,
    remediation_id: str | None = None,
) -> str:
    """Serialize the catalogue, profile, shifts, and run state to a single Turtle file.

    Args:
        out_path: Destination ``.ttl`` path.
        env_name: Environment graph being evaluated.
        profile: Profile of the evaluated policy.
        state: Belief state carrying the measured shifts and observations.
        eval_run_id: Node id for the evaluation run.
        next_technique_id: Diagnostic technique the planner selected next, if any.
        remediation_id: Remediation the planner selected, if any.

    Returns:
        The path written.
    """
    graph = rdflib.Graph()
    emit_technique_catalogue_rdf(graph)
    emit_policy_profile_rdf(profile, graph)
    emit_distribution_shifts_rdf(env_name, profile, state.shifts, graph)
    emit_diagnostic_state_rdf(
        eval_run_id=eval_run_id,
        env_name=env_name,
        profile=profile,
        state=state,
        next_technique_id=next_technique_id,
        remediation_id=remediation_id,
        graph=graph,
    )
    graph.serialize(destination=out_path, format="turtle")
    return out_path


# ---------------------------------------------------------------------------
# Neo4j LPG mirror
# ---------------------------------------------------------------------------


def sync_technique_catalogue_to_neo4j(driver: Optional[Any] = None) -> dict[str, Any]:
    """Mirror the static registries into Neo4j as an LPG.

    Catalogue nodes are global rather than per environment, so a Cypher query can compare which
    techniques resolved which failure modes across every environment evaluated so far.
    """
    from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver

    owns_driver = driver is None
    driver = driver or get_neo4j_driver()

    try:
        with driver.session() as session:
            for name, description in SIM_TO_REAL_INVARIANTS.items():
                session.run(
                    """
                    MERGE (i:SimToRealInvariant {name: $name})
                    SET i.description = $description
                    """,
                    name=name,
                    description=description,
                )

            for mode in FAILURE_MODES.values():
                session.run(
                    """
                    MERGE (f:FailureMode {mode_id: $mode_id})
                    SET f.label = $label,
                        f.layer = $layer,
                        f.prior = $prior,
                        f.description = $description
                    """,
                    mode_id=mode.mode_id,
                    label=mode.label,
                    layer=mode.layer,
                    prior=mode.prior,
                    description=mode.description,
                )
                for excluded in mode.excludes:
                    session.run(
                        """
                        MATCH (a:FailureMode {mode_id: $a_id})
                        MERGE (b:FailureMode {mode_id: $b_id})
                        MERGE (a)-[:EXCLUDES]->(b)
                        """,
                        a_id=mode.mode_id,
                        b_id=excluded,
                    )

            for technique in DIAGNOSTIC_TECHNIQUES.values():
                label = (
                    "DiagnosticTechnique:ActivationProbe" if technique.is_activation_probe else "DiagnosticTechnique"
                )
                session.run(
                    f"""
                    MERGE (t:{label} {{technique_id: $technique_id}})
                    SET t.label = $tech_label,
                        t.metric = $metric,
                        t.cost = $cost,
                        t.probes_module = $probes_module,
                        t.requires_policy_weights = $requires_weights,
                        t.requires_rollout = $requires_rollout,
                        t.requires_gpu = $requires_gpu,
                        t.requires_reference_dataset = $requires_dataset,
                        t.description = $description
                    """,
                    technique_id=technique.technique_id,
                    tech_label=technique.label,
                    metric=technique.metric,
                    cost=technique.cost,
                    probes_module=technique.probes_module or "",
                    requires_weights=technique.requires_policy_weights,
                    requires_rollout=technique.requires_rollout,
                    requires_gpu=technique.requires_gpu,
                    requires_dataset=technique.requires_reference_dataset,
                    description=technique.description,
                )
                for mode_id in technique.discriminates:
                    session.run(
                        """
                        MATCH (t:DiagnosticTechnique {technique_id: $technique_id})
                        MERGE (f:FailureMode {mode_id: $mode_id})
                        MERGE (t)-[:DISCRIMINATES]->(f)
                        """,
                        technique_id=technique.technique_id,
                        mode_id=mode_id,
                    )

            for remediation in REMEDIATION_TECHNIQUES.values():
                session.run(
                    """
                    MERGE (r:RemediationTechnique {technique_id: $technique_id})
                    SET r.label = $rem_label,
                        r.expected_efficacy = $efficacy,
                        r.effort = $effort,
                        r.cost = $cost,
                        r.description = $description,
                        r.is_admissible = $is_admissible
                    """,
                    technique_id=remediation.technique_id,
                    rem_label=remediation.label,
                    efficacy=remediation.expected_efficacy,
                    effort=remediation.effort,
                    cost=remediation.cost,
                    description=remediation.description,
                    is_admissible=not remediation.invalidated_by,
                )
                for mode_id in remediation.resolves:
                    session.run(
                        """
                        MATCH (r:RemediationTechnique {technique_id: $technique_id})
                        MERGE (f:FailureMode {mode_id: $mode_id})
                        MERGE (r)-[:RESOLVES]->(f)
                        """,
                        technique_id=remediation.technique_id,
                        mode_id=mode_id,
                    )
                for invariant_name in remediation.invalidated_by:
                    session.run(
                        """
                        MATCH (r:RemediationTechnique {technique_id: $technique_id})
                        MERGE (i:SimToRealInvariant {name: $name})
                        MERGE (r)-[:INVALIDATED_BY]->(i)
                        """,
                        technique_id=remediation.technique_id,
                        name=invariant_name,
                    )

            return {
                "failure_modes": len(FAILURE_MODES),
                "diagnostic_techniques": len(DIAGNOSTIC_TECHNIQUES),
                "remediation_techniques": len(REMEDIATION_TECHNIQUES),
                "sim_to_real_invariants": len(SIM_TO_REAL_INVARIANTS),
            }
    finally:
        if owns_driver:
            driver.close()


def sync_policy_diagnostics_to_neo4j(
    env_name: str,
    profile: PolicyProfile,
    state: PolicyDiagnosticState,
    eval_run_id: str = "policy_diagnostics_run",
    next_technique_id: str | None = None,
    remediation_id: str | None = None,
    driver: Optional[Any] = None,
) -> dict[str, Any]:
    """Mirror a policy, its corpus invariants, and one run's shifts and beliefs into Neo4j.

    Args:
        env_name: Environment graph node the shifts were measured against.
        profile: Profile of the evaluated policy.
        state: Belief state carrying measured shifts and observations.
        eval_run_id: Node id for the evaluation run.
        next_technique_id: Diagnostic technique the planner selected next, if any.
        remediation_id: Remediation the planner selected, if any.
        driver: Optional active Neo4j driver.

    Returns:
        Counts of the nodes and edges written for this run.
    """
    from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver

    owns_driver = driver is None
    driver = driver or get_neo4j_driver()

    try:
        sync_technique_catalogue_to_neo4j(driver=driver)
        with driver.session() as session:
            session.run(
                """
                MERGE (p:Policy {name: $policy_id})
                SET p.checkpoint_uri = $checkpoint_uri,
                    p.policy_kind = $policy_kind,
                    p.controller_binding = $controller_binding,
                    p.action_dim = $action_dim,
                    p.action_chunk_length = $action_chunk_length,
                    p.vision_backbone = $vision_backbone,
                    p.action_head_kind = $action_head_kind,
                    p.language_instruction = $language_instruction
                MERGE (c:DemonstrationCorpus {corpus_id: $corpus_id})
                SET c.demo_count = $demo_count,
                    c.reference_scene = $reference_scene
                MERGE (p)-[:WAS_TRAINED_ON]->(c)
                """,
                policy_id=profile.policy_id,
                checkpoint_uri=profile.checkpoint_uri,
                policy_kind=profile.policy_kind,
                controller_binding=profile.controller_binding,
                action_dim=profile.action_dim,
                action_chunk_length=profile.action_chunk_length,
                vision_backbone=profile.vision_backbone,
                action_head_kind=profile.action_head_kind,
                language_instruction=profile.language_instruction,
                corpus_id=profile.corpus_id,
                demo_count=profile.demo_count,
                reference_scene=profile.reference_scene,
            )

            for invariant in profile.invariants:
                session.run(
                    """
                    MATCH (c:DemonstrationCorpus {corpus_id: $corpus_id})
                    MERGE (i:TrainingInvariant {corpus_id: $corpus_id, axis: $axis})
                    SET i.description = $description,
                        i.value = $value,
                        i.numeric_value = $numeric_value,
                        i.tolerance = $tolerance,
                        i.unit = $unit
                    MERGE (c)-[:ESTABLISHES_INVARIANT]->(i)
                    """,
                    corpus_id=profile.corpus_id,
                    axis=invariant.axis,
                    description=invariant.description,
                    value=invariant.value or "",
                    numeric_value=invariant.numeric_value if invariant.numeric_value is not None else 0.0,
                    tolerance=invariant.tolerance if invariant.tolerance is not None else 0.0,
                    unit=invariant.unit,
                )

            for index, shift in enumerate(state.shifts):
                session.run(
                    """
                    MERGE (s:DistributionShift {shift_id: $shift_id})
                    SET s.axis = $axis,
                        s.magnitude = $magnitude,
                        s.sigma = $sigma,
                        s.within_tolerance = $within_tolerance,
                        s.scene_value = $scene_value,
                        s.corpus_value = $corpus_value,
                        s.evidence = $evidence
                    WITH s
                    MATCH (p:Policy {name: $policy_id})
                    MERGE (s)-[:SHIFT_FOR_POLICY]->(p)
                    WITH s
                    OPTIONAL MATCH (e:EnvironmentGraph {name: $env_name})
                    FOREACH (_ IN CASE WHEN e IS NOT NULL THEN [1] ELSE [] END |
                        MERGE (s)-[:SHIFT_IN_GRAPH]->(e)
                    )
                    WITH s
                    OPTIONAL MATCH (i:TrainingInvariant {corpus_id: $corpus_id, axis: $axis})
                    FOREACH (_ IN CASE WHEN i IS NOT NULL THEN [1] ELSE [] END |
                        MERGE (s)-[:SHIFT_OF_INVARIANT]->(i)
                    )
                    """,
                    shift_id=f"{env_name}::{profile.policy_id}::{shift.axis}::{index}",
                    axis=shift.axis,
                    magnitude=shift.magnitude,
                    sigma=shift.sigma,
                    within_tolerance=shift.within_tolerance,
                    scene_value=shift.scene_value,
                    corpus_value=shift.corpus_value,
                    evidence=shift.evidence,
                    policy_id=profile.policy_id,
                    env_name=env_name,
                    corpus_id=profile.corpus_id,
                )
                for mode_id in shift.manifests_as:
                    session.run(
                        """
                        MATCH (s:DistributionShift {shift_id: $shift_id})
                        MERGE (f:FailureMode {mode_id: $mode_id})
                        MERGE (s)-[:MANIFESTS_AS]->(f)
                        """,
                        shift_id=f"{env_name}::{profile.policy_id}::{shift.axis}::{index}",
                        mode_id=mode_id,
                    )
                # The load-bearing edge: an out-of-tolerance shift marks the scene as violating a
                # property the policy depends on, joining scene structure to model competence.
                if not shift.within_tolerance:
                    session.run(
                        """
                        MATCH (e:EnvironmentGraph {name: $env_name}),
                              (i:TrainingInvariant {corpus_id: $corpus_id, axis: $axis})
                        MERGE (e)-[v:VIOLATES_INVARIANT]->(i)
                        SET v.sigma = $sigma,
                            v.magnitude = $magnitude
                        """,
                        env_name=env_name,
                        corpus_id=profile.corpus_id,
                        axis=shift.axis,
                        sigma=shift.sigma,
                        magnitude=shift.magnitude,
                    )

            session.run(
                """
                MERGE (ev:EvaluationRun {id: $eval_run_id})
                SET ev.posterior_beliefs = $beliefs
                WITH ev
                MATCH (p:Policy {name: $policy_id})
                MERGE (ev)-[:EVALUATED_POLICY]->(p)
                WITH ev
                OPTIONAL MATCH (e:EnvironmentGraph {name: $env_name})
                FOREACH (_ IN CASE WHEN e IS NOT NULL THEN [1] ELSE [] END |
                    MERGE (ev)-[:EVALUATED_GRAPH]->(e)
                )
                """,
                eval_run_id=eval_run_id,
                beliefs=str({mode_id: round(belief, 4) for mode_id, belief in state.ranked()}),
                policy_id=profile.policy_id,
                env_name=env_name,
            )

            for technique_id in state.applied_techniques:
                session.run(
                    """
                    MATCH (ev:EvaluationRun {id: $eval_run_id})
                    MERGE (t:DiagnosticTechnique {technique_id: $technique_id})
                    MERGE (ev)-[:APPLIED_TECHNIQUE]->(t)
                    """,
                    eval_run_id=eval_run_id,
                    technique_id=technique_id,
                )

            for index, observation in enumerate(state.observations):
                session.run(
                    """
                    MATCH (ev:EvaluationRun {id: $eval_run_id})
                    MERGE (o:ProbeObservation {observation_id: $observation_id})
                    SET o.metric = $metric,
                        o.value = $value,
                        o.reference = $reference,
                        o.likelihood_ratio = $likelihood_ratio,
                        o.note = $note
                    MERGE (o)-[:OBSERVED_DURING]->(ev)
                    WITH o
                    MERGE (t:DiagnosticTechnique {technique_id: $technique_id})
                    MERGE (o)-[:PRODUCED_BY_TECHNIQUE]->(t)
                    """,
                    eval_run_id=eval_run_id,
                    observation_id=f"{eval_run_id}::{index}",
                    metric=observation.metric,
                    value=observation.value,
                    reference=observation.reference if observation.reference is not None else 0.0,
                    likelihood_ratio=observation.likelihood_ratio,
                    note=observation.note,
                    technique_id=observation.technique_id,
                )
                for mode_id, edge in (
                    *((m, "SUPPORTS") for m in observation.supports),
                    *((m, "REFUTES") for m in observation.refutes),
                ):
                    session.run(
                        f"""
                        MATCH (o:ProbeObservation {{observation_id: $observation_id}})
                        MERGE (f:FailureMode {{mode_id: $mode_id}})
                        MERGE (o)-[:{edge}]->(f)
                        """,
                        observation_id=f"{eval_run_id}::{index}",
                        mode_id=mode_id,
                    )

            dominant = state.dominant()
            if dominant:
                session.run(
                    """
                    MATCH (ev:EvaluationRun {id: $eval_run_id})
                    MERGE (f:FailureMode {mode_id: $mode_id})
                    MERGE (ev)-[a:ATTRIBUTED_TO_FAILURE_MODE]->(f)
                    SET a.posterior_belief = $belief
                    """,
                    eval_run_id=eval_run_id,
                    mode_id=dominant[0],
                    belief=dominant[1],
                )
            if next_technique_id:
                session.run(
                    """
                    MATCH (ev:EvaluationRun {id: $eval_run_id})
                    MERGE (t:DiagnosticTechnique {technique_id: $technique_id})
                    MERGE (ev)-[:NEXT_TECHNIQUE]->(t)
                    """,
                    eval_run_id=eval_run_id,
                    technique_id=next_technique_id,
                )
            if remediation_id:
                session.run(
                    """
                    MATCH (ev:EvaluationRun {id: $eval_run_id})
                    MERGE (r:RemediationTechnique {technique_id: $technique_id})
                    MERGE (ev)-[:REMEDIATED_BY]->(r)
                    """,
                    eval_run_id=eval_run_id,
                    technique_id=remediation_id,
                )

            return {
                "eval_run_id": eval_run_id,
                "env_name": env_name,
                "policy_id": profile.policy_id,
                "shifts": len(state.shifts),
                "observations": len(state.observations),
                "dominant_failure_mode": dominant[0] if dominant else None,
            }
    finally:
        if owns_driver:
            driver.close()


def query_blocking_shifts(graph: rdflib.Graph) -> list[dict[str, Any]]:
    """Return the out-of-tolerance shifts in ``graph`` with their admissible remediations."""
    return [
        {
            "axis": str(row.axis),
            "sigma": float(row.sigma),
            "failure_mode": str(row.mode).rsplit("failure_", 1)[-1],
            "remediation": str(row.remediation).rsplit("remediation_", 1)[-1] if row.remediation else None,
            "expected_efficacy": float(row.efficacy) if row.efficacy is not None else None,
        }
        for row in graph.query(SPARQL_BLOCKING_SHIFTS)
    ]
