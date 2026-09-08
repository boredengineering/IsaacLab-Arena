# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Graph-RAG experience memory retriever for IsaacLab-Arena environment generation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import neo4j

from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver

logger = logging.getLogger(__name__)

# Ranked by measured evaluation outcome. Three things here are load-bearing:
#   1. The embodiment/fixture filters sit after their own WITH. A WHERE attached to an OPTIONAL
#      MATCH only decides whether the optional pattern binds, so it would leave every
#      environment in the result instead of filtering any out.
#   2. The WHERE on the EvaluationRun OPTIONAL MATCH is deliberate: it selects which runs
#      qualify, and `WHERE best_ev IS NOT NULL` then drops environments left with none.
#   3. One best run is selected via head(collect(...)) rather than max() per field. Independent
#      maxima would pair the best rate with an unrelated run's episode count and report, say,
#      "1.0 over 4 episodes" when the 1.0 came from a single-episode run.
_EVALUATED_PRIORS_QUERY = """
MATCH (e:EnvironmentGraph)
OPTIONAL MATCH (e)-[:HAS_EMBODIMENT]->(emb:Embodiment)
OPTIONAL MATCH (e)-[:HAS_TERRAIN]->(bg:Fixture)
WITH e, emb, bg
WHERE ($emb_filter = "" OR emb.registry_name CONTAINS $emb_filter)
  AND ($fixture_filter = "" OR bg.registry_name CONTAINS $fixture_filter)
OPTIONAL MATCH (e)-[:CONTAINS_OBJECT]->(obj)
OPTIONAL MATCH (e)-[:HAS_REIFIER]->(rel:ReifiedRelation)
WITH e, emb, bg,
     collect(DISTINCT obj.registry_name) AS objects,
     collect(DISTINCT {
         relation_type: rel.relation_type,
         manifold: rel.kinematic_manifold,
         anchor: rel.surface_anchor
     }) AS relations
OPTIONAL MATCH (ev:EvaluationRun)-[:EVALUATED_GRAPH]->(e)
    WHERE ev.success_rate > $min_success_rate
      AND coalesce(ev.num_episodes, 0) >= $min_episodes
WITH e, emb, bg, objects, relations, ev
    ORDER BY ev.success_rate DESC, ev.num_episodes DESC
WITH e, emb, bg, objects, relations, head(collect(ev)) AS best_ev
WHERE best_ev IS NOT NULL
RETURN e.name AS name,
       e.task_description AS task_description,
       e.task_composition AS task_composition,
       emb.registry_name AS embodiment,
       bg.registry_name AS background,
       objects,
       relations,
       best_ev.success_rate AS best_success_rate,
       best_ev.num_episodes AS episodes
ORDER BY best_success_rate DESC, episodes DESC
LIMIT $limit
"""

# Fallback when nothing has been evaluated above the bar. ``converged`` is a property of the
# *generator* (it reached free energy ~0 without applying a fallback), not of any policy's
# performance, so these are labelled as unevaluated precedent rather than verified priors.
_STRUCTURAL_PRIORS_QUERY = """
MATCH (e:EnvironmentGraph)
WHERE e.converged = true
OPTIONAL MATCH (e)-[:HAS_EMBODIMENT]->(emb:Embodiment)
OPTIONAL MATCH (e)-[:HAS_TERRAIN]->(bg:Fixture)
WITH e, emb, bg
WHERE ($emb_filter = "" OR emb.registry_name CONTAINS $emb_filter)
  AND ($fixture_filter = "" OR bg.registry_name CONTAINS $fixture_filter)
OPTIONAL MATCH (e)-[:CONTAINS_OBJECT]->(obj)
OPTIONAL MATCH (e)-[:HAS_REIFIER]->(rel:ReifiedRelation)
WITH e, emb, bg,
     collect(DISTINCT obj.registry_name) AS objects,
     collect(DISTINCT {
         relation_type: rel.relation_type,
         manifold: rel.kinematic_manifold,
         anchor: rel.surface_anchor
     }) AS relations
RETURN e.name AS name,
       e.task_description AS task_description,
       e.task_composition AS task_composition,
       emb.registry_name AS embodiment,
       bg.registry_name AS background,
       objects,
       relations,
       null AS best_success_rate,
       null AS episodes
ORDER BY e.updated_at DESC
LIMIT $limit
"""


def _keyword_filters(prompt: str) -> tuple[str, str]:
    """Derive embodiment and fixture substring filters from a generation prompt."""
    p = prompt.lower()
    if "g1" in p:
        embodiment = "g1"
    elif "droid" in p:
        embodiment = "droid"
    elif "franka" in p:
        embodiment = "franka"
    else:
        embodiment = ""

    if "shelv" in p or "rack" in p:
        fixture = "wireshelving"
    elif "kitchen" in p or "counter" in p:
        fixture = "kitchen"
    elif "table" in p or "desk" in p:
        fixture = "table"
    else:
        fixture = ""

    return embodiment, fixture


def _row_to_prior(record: Any, evidence: str) -> dict[str, Any]:
    """Convert one Cypher record into a prior, dropping null relation placeholders."""
    relations = [r for r in (record["relations"] or []) if r and r.get("relation_type")]
    return {
        "name": record["name"],
        "task_description": record["task_description"],
        "task_composition": record["task_composition"],
        "embodiment": record["embodiment"],
        "background": record["background"],
        "objects": [o for o in (record["objects"] or []) if o],
        "relations": relations,
        "success_rate": record["best_success_rate"],
        "episodes": record["episodes"],
        "evidence": evidence,
    }


class GraphRAGRetriever:
    """Retrieves prior environment subgraphs from the Neo4j LPG as few-shot generative priors."""

    def __init__(self, driver: neo4j.Driver | None = None):
        self._driver = driver

    def get_driver(self) -> neo4j.Driver:
        if self._driver is None:
            self._driver = get_neo4j_driver()
        return self._driver

    def retrieve_prior_subgraphs(
        self,
        prompt: str,
        limit: int = 2,
        min_success_rate: float = 0.0,
        min_episodes: int = 1,
    ) -> list[dict[str, Any]]:
        """Retrieve prior environment subgraphs, ranked by measured evaluation outcome.

        Environments whose best evaluation run clears both thresholds are preferred and returned
        best-first. When none qualify, falls back to structurally converged environments, which
        carry no performance evidence and are labelled accordingly.

        Args:
            prompt: Generation prompt; keywords select the embodiment and fixture families.
            limit: Maximum number of priors to return.
            min_success_rate: Exclusive lower bound on a run's success rate.
            min_episodes: Minimum episodes behind that rate, so a single lucky episode does not
                outrank a run with real sample size.

        Returns:
            Priors, each tagged with an ``evidence`` field of ``"measured"`` or ``"unevaluated"``.
        """
        emb_filter, fixture_filter = _keyword_filters(prompt)
        params = {
            "emb_filter": emb_filter,
            "fixture_filter": fixture_filter,
            "limit": limit,
            "min_success_rate": min_success_rate,
            "min_episodes": min_episodes,
        }

        try:
            driver = self.get_driver()
            with driver.session() as session:
                records = list(session.run(_EVALUATED_PRIORS_QUERY, **params))
                if records:
                    return [_row_to_prior(r, "measured") for r in records]

                structural = {k: v for k, v in params.items() if k not in ("min_success_rate", "min_episodes")}
                records = list(session.run(_STRUCTURAL_PRIORS_QUERY, **structural))
                return [_row_to_prior(r, "unevaluated") for r in records]
        except Exception as exc:
            # Generation must not depend on the experience memory being reachable, but a silent
            # miss is indistinguishable from an empty graph, so say which happened.
            logger.warning("Graph-RAG retrieval failed (%s: %s); continuing without priors.", type(exc).__name__, exc)
            return []

    def format_priors_as_context(self, priors: list[dict[str, Any]]) -> str:
        """Format retrieved subgraphs into a prompt context block."""
        if not priors:
            return ""

        measured = [p for p in priors if p.get("evidence") == "measured"]
        if measured:
            header = [
                "### Prior Environment Subgraphs (Graph-RAG, ranked by measured success rate):",
                "These structural patterns come from environments that were evaluated and scored above zero.",
            ]
        else:
            header = [
                "### Prior Environment Subgraphs (Graph-RAG, structural precedent only):",
                "No evaluated environment cleared the evidence bar. The patterns below are structurally",
                "valid but carry NO evidence that a policy performs well in them -- reuse their grounding",
                "and relations, not their assumed quality.",
            ]
        lines = [*header, ""]

        for idx, p in enumerate(priors, 1):
            if p.get("evidence") == "measured":
                outcome = f"success_rate={p.get('success_rate')} over {p.get('episodes')} episode(s)"
            else:
                outcome = "never evaluated"
            lines.append(f"Example {idx} ({p.get('name', 'env')}) -- {outcome}:")
            lines.append(f"  - Task: {p.get('task_description')}")
            if p.get("task_composition"):
                lines.append(f"  - Composition: {p.get('task_composition')}")
            lines.append(f"  - Embodiment: {p.get('embodiment')}")
            lines.append(f"  - Background: {p.get('background')}")
            lines.append(f"  - Objects: {', '.join(p.get('objects', []))}")
            for rel in p.get("relations", []):
                lines.append(
                    f"  - Relation: {rel.get('relation_type')}"
                    f" (manifold={rel.get('manifold')}, anchor={rel.get('anchor')})"
                )
            lines.append("")

        return "\n".join(lines)

    def retrieve_refinement_history(
        self,
        source_env_name: str,
        policy_identity: str,
        *,
        limit: int = 5,
        min_episodes: int = 1,
        accepted_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Read bounded DCRG evolutionary paths with the exact deciding run's outcome.

        This is measured refinement history, not proof of generalization. Rejected
        trials are included only when explicitly requested; untested proposals are
        excluded. Database failures propagate rather than looking like empty history.

        Args:
            source_env_name: Original scenario name before immutable version suffixes.
            policy_identity: Exact checkpoint identity used by the deciding evaluation.
            limit: Maximum number of paths, each bounded to five evolution edges.
            min_episodes: Minimum completed episodes on the deciding evaluation.
            accepted_only: Exclude rejected trials by default.

        Returns:
            Version chains, decision status, candidate spec JSON, and matched rates/counts.
        """
        assert source_env_name and policy_identity, "Explicit scenario and policy identities are required"
        assert limit > 0 and min_episodes > 0, "Positive retrieval bounds are required"
        with self.get_driver().session() as session:
            records = session.run(
                """
                MATCH path=(root:EnvironmentGraph)-[:EVOLVES_TO*1..5]->(child:EnvironmentGraph)
                WHERE root.source_env_name = $source_env_name
                WITH path, child, last(relationships(path)).proposal_id AS proposal_id
                MATCH (p:DCRGProposal {id: proposal_id})-[:HAS_DECISION]->(decision:DCRGProposalDecision)
                      -[:BASED_ON_EVALUATION]->(ev:EvaluationRun)-[:USED_POLICY]->(policy:Policy)
                MATCH (ev)-[:EVALUATED_GRAPH]->(child)
                WHERE policy.name = $policy_identity AND ev.num_episodes >= $min_episodes
                  AND (NOT $accepted_only OR decision.status = 'accepted')
                RETURN [n IN nodes(path) | n.version] AS versions,
                       [n IN nodes(path) | n.name] AS environments,
                       p.id AS proposal_id, decision.status AS decision,
                       ev.id AS evaluation_id, ev.success_rate AS success_rate,
                       ev.num_episodes AS num_episodes, policy.name AS policy_identity,
                       child.spec_json AS spec_json
                ORDER BY ev.success_rate DESC, ev.num_episodes DESC, p.id
                LIMIT $limit
                """,
                source_env_name=source_env_name,
                policy_identity=policy_identity,
                min_episodes=min_episodes,
                accepted_only=accepted_only,
                limit=limit,
            )
            return [dict(record) for record in records]

    def retrieve_controller_trials(
        self,
        source_env_name: str,
        checkpoint_identity: str,
        experiment_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Retrieve measured same-scene interventions, including zero-success trials.

        Args:
            source_env_name: Original scenario name, without its immutable version suffix.
            checkpoint_identity: Exact base checkpoint identity, not the composite policy ID.
            experiment_id: Explicit comparison group, or None to inspect all matching groups.
            limit: Maximum number of distinct evaluated trials.

        Returns:
            Per-run contracts, counts, raw-event sustained lifts and hashed artifacts.
            Missing raw events yield unknown lift counts, never inferred success. Counts
            are per run, not additive across aggregate/per-seed records of the same rollout.
            No unevaluated fallback is used; database and evidence failures propagate.
        """
        import json

        from isaaclab_arena.agentic_environment_generation.dcrg.controller_graph import _verified_variant
        from isaaclab_arena.agentic_environment_generation.dcrg.graph import _episode_metrics, _text, _verified

        _text(source_env_name, "source_env_name")
        _text(checkpoint_identity, "checkpoint_identity")
        if experiment_id is not None:
            _text(experiment_id, "experiment_id")
        if type(limit) is not int or limit <= 0:
            raise ValueError("limit must be a positive integer")
        with self.get_driver().session() as session:
            records = list(
                session.run(
                    """
                MATCH (trial:DCRGControllerTrial)-[:TRIAL_CONTROLLER]->(v:DCRGControllerVariant)
                MATCH (trial)-[:IN_CONTROLLER_EXPERIMENT]->(experiment:DCRGControllerExperiment)
                MATCH (trial)-[:BASED_ON_EVALUATION]->(ev:EvaluationRun)-[:EVALUATED_GRAPH]->(e:EnvironmentGraph)
                WHERE e.source_env_name = $source_env_name
                  AND v.checkpoint_identity = $checkpoint_identity
                  AND ($experiment_id IS NULL OR experiment.id = $experiment_id)
                  AND ev.policy_identity = v.policy_identity AND ev.num_episodes > 0
                  AND trial.id = ev.id AND trial.variant_id = v.id
                  AND trial.experiment_id = experiment.id
                  AND ev.env_name = e.name AND ev.env_version = e.version
                  AND trial.env_name = e.name AND trial.version = e.version
                  AND experiment.env_name = e.name AND experiment.version = e.version
                  AND experiment.checkpoint_identity = v.checkpoint_identity
                RETURN DISTINCT properties(v) AS variant, properties(ev) AS evaluation,
                       experiment.id AS experiment_id, e.source_env_name AS source_env_name,
                       e.spec_json AS spec_json
                ORDER BY experiment_id, evaluation.id
                LIMIT $limit
                """,
                    source_env_name=source_env_name,
                    checkpoint_identity=checkpoint_identity,
                    experiment_id=experiment_id,
                    limit=limit,
                )
            )
        trials = []
        for record in records:
            variant = record["variant"]
            evaluation = record["evaluation"]
            contract = _verified_variant(variant)
            episodes = json.loads(evaluation["episode_results_json"])
            _verified(
                [{"properties": evaluation}],
                {
                    **_episode_metrics(episodes),
                    "policy_identity": variant["policy_identity"],
                },
                "controller evaluation",
            )
            events = [episode.get("progress", {}).get("events") for episode in episodes]
            lifts = None
            if all(isinstance(event_list, list) for event_list in events):
                lifts = sum(
                    any(
                        event.get("predicate_name", "").startswith("object_lifted_above_resting_min(")
                        for event in event_list
                    )
                    for event_list in events
                )
            trials.append({
                "run_id": evaluation["id"],
                "variant_id": variant["id"],
                "experiment_id": record["experiment_id"],
                "source_env_name": record["source_env_name"],
                "env_name": evaluation["env_name"],
                "version": evaluation["env_version"],
                "spec_json": record["spec_json"],
                "checkpoint_identity": variant["checkpoint_identity"],
                "policy_identity": evaluation["policy_identity"],
                "contract": contract,
                "controller_config": contract["controller_config"],
                "privilege_mode": contract["privilege_mode"],
                "privileged_state": variant["privileged_state"],
                "num_episodes": evaluation["num_episodes"],
                "num_successes": evaluation["num_successes"],
                "success_rate": evaluation["success_rate"],
                "num_sustained_lifts": lifts,
                "sustained_lift_rate": None if lifts is None else lifts / len(episodes),
                "artifacts": [
                    {"path": path, "sha256": digest}
                    for path, digest in zip(evaluation["artifact_paths"], evaluation["artifact_sha256"], strict=True)
                ],
                "evidence": "measured_controller_trial",
            })
        return trials
