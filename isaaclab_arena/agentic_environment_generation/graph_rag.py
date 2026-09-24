# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Graph-RAG experience memory retriever for IsaacLab-Arena environment generation."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from itertools import islice
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import neo4j

from isaaclab_arena.agentic_environment_generation.graph_cleanup import GraphCleanupError, graph_session
from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver
from isaaclab_arena.agentic_environment_generation.prior_receipt import SnapshotRejected as _SnapshotRejected
from isaaclab_arena.agentic_environment_generation.prior_receipt import (
    bounded_text,
    effective_settings,
    empty_snapshot,
    format_prior_context,
)
from isaaclab_arena.agentic_environment_generation.prior_receipt import keyword_filters as _keyword_filters
from isaaclab_arena.agentic_environment_generation.prior_receipt import validate_prior, validate_prior_snapshot

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
WHERE NOT EXISTS { MATCH (e)-[:HAS_REVISION]->(:WorkbenchRevision) }
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
  AND NOT EXISTS { MATCH (e)-[:HAS_REVISION]->(:WorkbenchRevision) }
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


# Snapshot-only projections follow the writers in lpg_neo4j_sync.py and dcrg/graph.py.
# Checkpoint identity exists on DCRGControllerVariant, not on generic Policy nodes.
_SNAPSHOT_EVALUATED_QUERY = _EVALUATED_PRIORS_QUERY.replace(
    "RETURN e.name AS name,",
    """CALL { WITH best_ev MATCH (best_ev)-[r:EVALUATED_GRAPH]->()
       WITH r LIMIT 2 RETURN count(r) AS _graph_links }
CALL { WITH best_ev MATCH (other:EvaluationRun {id: best_ev.id})
       WITH other LIMIT 2 RETURN count(other) AS _run_ids }
CALL { WITH best_ev MATCH (best_ev)-[r:USED_POLICY]->(policy)
       WITH r, policy LIMIT 2
       RETURN collect({valid_label: policy:Policy, identity: policy.name}) AS _policies }
CALL { WITH best_ev MATCH (trial)-[r:BASED_ON_EVALUATION]->(best_ev)
       WITH r, trial LIMIT 2
       CALL { WITH trial MATCH (trial)-[r:BASED_ON_EVALUATION]->(target)
              WITH r, target LIMIT 2
              RETURN count(r) AS evaluation_links, collect(labels(target)) AS evaluation_labels }
       CALL { WITH trial MATCH (trial)-[r:TRIAL_CONTROLLER]->(variant)
              WITH r, variant LIMIT 2
              RETURN collect({valid_label: variant:DCRGControllerVariant,
                              identity: variant.checkpoint_identity, id: variant.id,
                              policy_identity: variant.policy_identity}) AS variants }
       RETURN collect({valid_label: trial:DCRGControllerTrial, variants: variants,
                       trial_id: trial.id, run_id: trial.run_id, env_name: trial.env_name,
                       env_version: trial.version, variant_id: trial.variant_id,
                       policy_identity: trial.policy_identity, evaluation_links: evaluation_links,
                       evaluation_labels: evaluation_labels}) AS _controllers }
RETURN best_ev.id AS evaluation_id, e.version AS graph_version,
       best_ev.policy_identity AS _run_policy, best_ev.env_name AS _run_env_name,
       best_ev.env_version AS _run_env_version,
       _graph_links, _run_ids, _policies, _controllers,
       elementId(e) AS _physical_root_id, elementId(best_ev) AS _physical_run_id,
       CASE WHEN e.spec_json IS NOT NULL AND e.version IS NOT NULL THEN
         {name: e.name, sha256: e.version, spec_json: e.spec_json} ELSE null END AS _canonical_proof,
       coalesce(head(_policies).identity, best_ev.policy_identity) AS policy_identity,
       head(head(_controllers).variants).identity AS checkpoint_identity,
       e.name AS name,""",
)


_SNAPSHOT_STRUCTURAL_QUERY = _STRUCTURAL_PRIORS_QUERY.replace(
    "RETURN e.name AS name,",
    """RETURN null AS evaluation_id, e.version AS graph_version,
       elementId(e) AS _physical_root_id, null AS _physical_run_id,
       CASE WHEN e.spec_json IS NOT NULL AND e.version IS NOT NULL THEN
         {name: e.name, sha256: e.version, spec_json: e.spec_json} ELSE null END AS _canonical_proof,
       null AS policy_identity, null AS checkpoint_identity, e.name AS name,""",
)
# Keep an overflow sentinel: clipping to the accepted bound would hide evidence loss.
_SNAPSHOT_EVALUATED_QUERY = _SNAPSHOT_EVALUATED_QUERY.replace(
    "       objects,\n       relations,", "       objects[..33] AS objects,\n       relations[..33] AS relations,"
).replace("e.task_description AS task_description", "left(e.task_description, 4097) AS task_description")
_SNAPSHOT_STRUCTURAL_QUERY = _SNAPSHOT_STRUCTURAL_QUERY.replace(
    "       objects,\n       relations,", "       objects[..33] AS objects,\n       relations[..33] AS relations,"
).replace("e.task_description AS task_description", "left(e.task_description, 4097) AS task_description")


def _snapshot_text(value):
    bounded_text(value)
    return value


def _validate_legacy_provenance(record):
    """Require bounded independent relationship evidence, including wrong labels."""
    for field in ("_graph_links", "_run_ids"):
        if type(record.get(field)) is not int or record[field] != 1:
            raise _SnapshotRejected("invalid_record")
    policies, controllers = record.get("_policies"), record.get("_controllers")
    if type(policies) is not list or len(policies) > 1 or type(controllers) is not list or len(controllers) > 1:
        raise _SnapshotRejected("invalid_record")
    policy = None
    if policies:
        p = policies[0]
        if type(p) is not dict or set(p) != {"valid_label", "identity"} or p["valid_label"] is not True:
            raise _SnapshotRejected("invalid_record")
        policy = p["identity"]
        bounded_text(policy, nullable=False)
    run_policy = record.get("_run_policy")
    if run_policy is not None:
        bounded_text(run_policy, nullable=False)
        if policy is not None and run_policy != policy:
            raise _SnapshotRejected("invalid_record")
        policy = run_policy
    if record.get("_run_env_name") not in (None, record.get("name")) or record.get("_run_env_version") not in (
        None,
        record.get("graph_version"),
    ):
        raise _SnapshotRejected("invalid_record")
    checkpoint = None
    if controllers:
        c = controllers[0]
        if type(c) is not dict or c.get("valid_label") is not True:
            raise _SnapshotRejected("invalid_record")
        for field in ("trial_id", "run_id", "env_name", "env_version", "variant_id", "policy_identity"):
            bounded_text(c.get(field), nullable=False)
        if (
            type(c.get("evaluation_links")) is not int
            or c["evaluation_links"] != 1
            or type(c.get("evaluation_labels")) is not list
            or len(c["evaluation_labels"]) != 1
            or type(c["evaluation_labels"][0]) is not list
            or "EvaluationRun" not in c["evaluation_labels"][0]
            or c["trial_id"] != record.get("evaluation_id")
            or c["run_id"] != record.get("evaluation_id")
            or c["env_name"] != record.get("name")
            or c["env_version"] != record.get("graph_version")
            or c["policy_identity"] != policy
            or run_policy != policy
            or record.get("_run_env_name") != c["env_name"]
            or record.get("_run_env_version") != c["env_version"]
        ):
            raise _SnapshotRejected("invalid_record")
        variants = c.get("variants")
        if type(variants) is not list or len(variants) != 1:
            raise _SnapshotRejected("invalid_record")
        v = variants[0]
        if type(v) is not dict or v.get("valid_label") is not True:
            raise _SnapshotRejected("invalid_record")
        for field in ("identity", "id", "policy_identity"):
            bounded_text(v.get(field), nullable=False)
        if v["id"] != c["variant_id"] or v["policy_identity"] != policy:
            raise _SnapshotRejected("invalid_record")
        checkpoint = v["identity"]
    if policy != record.get("policy_identity") or checkpoint != record.get("checkpoint_identity"):
        raise _SnapshotRejected("invalid_record")


def _deduplicate_candidates(records, priors, *, rank=True):
    """Deduplicate verified identities; mixed rank is rate, episodes, name, version, run.

    All identity ties retain source order (legacy first), never incidental payload
    fields. With no managed candidates preserve the legacy database ordering.
    """
    candidates = []
    proofs = {}
    runs = {}
    physical_runs = {}
    for index, (record, prior) in enumerate(zip(records, priors, strict=True)):
        proof = record.get("_canonical_proof")
        key = ("unproven", index)
        if proof is not None:
            if type(proof) is not dict or set(proof) != {"name", "sha256", "spec_json"}:
                raise _SnapshotRejected("invalid_record")
            name, digest, payload = (proof[k] for k in ("name", "sha256", "spec_json"))
            if (
                type(payload) is not str
                or len(payload) > 65536
                or type(digest) is not str
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or name != prior["name"]
                or digest != prior["graph_version"]
            ):
                raise _SnapshotRejected("invalid_record")
            try:
                decoded = json.loads(payload)
                canonical = json.dumps(decoded, sort_keys=True, separators=(",", ":"), allow_nan=False)
            except (ValueError, TypeError):
                raise _SnapshotRejected("invalid_record") from None
            if (
                type(decoded) is not dict
                or canonical != payload
                or hashlib.sha256(payload.encode()).hexdigest() != digest
            ):
                raise _SnapshotRejected("invalid_record")
            key = ("canonical", name, digest, payload)
            projection = {
                k: v
                for k, v in prior.items()
                if k
                not in (
                    "success_rate",
                    "episodes",
                    "evaluation_id",
                    "policy_identity",
                    "checkpoint_identity",
                    "evidence",
                )
            }
            if key in proofs and proofs[key] != projection:
                raise _SnapshotRejected("invalid_record")
            proofs[key] = projection
        elif record.get("_physical_root_id") is not None:
            root = _snapshot_text(record.get("_physical_root_id"))
            run = _snapshot_text(record.get("_physical_run_id"))
            key = ("physical", root, run)
        run_key = (key, prior["evaluation_id"])
        if run_key in runs and runs[run_key] != prior:
            raise _SnapshotRejected("invalid_record")
        runs[run_key] = prior
        physical_run = _snapshot_text(record.get("_physical_run_id"))
        if physical_run is not None:
            physical_root = _snapshot_text(record.get("_physical_root_id"))
            identity = (physical_root, prior)
            if physical_run in physical_runs:
                if physical_runs[physical_run] != identity:
                    raise _SnapshotRejected("invalid_record")
                continue
            physical_runs[physical_run] = identity
        candidates.append((key, prior))
    if rank:
        candidates.sort(
            key=lambda item: (
                -(item[1]["success_rate"] or 0),
                -(item[1]["episodes"] or 0),
                item[1]["name"],
                item[1]["graph_version"] or "",
                item[1]["evaluation_id"] or "",
            )
        )
    chosen = {}
    for key, prior in candidates:
        chosen.setdefault(key, prior)
    return list(chosen.values())


def _checked_snapshot_rows(rows, before_read):
    """Iterate snapshot rows only while the selected read authority remains valid."""
    if before_read is None:
        yield from rows
        return
    iterator = iter(rows)
    while True:
        before_read()
        try:
            row = next(iterator)
        except StopIteration:
            return
        before_read()
        yield row


def _snapshot_prior(record: Any, evidence: str, min_success_rate: float, min_episodes: int) -> dict[str, Any]:
    """Project only schema-backed fields, rejecting lossy or malformed evidence."""
    prior: dict[str, Any] = {
        field: _snapshot_text(record.get(field))
        for field in (
            "name",
            "task_description",
            "task_composition",
            "embodiment",
            "background",
            "evaluation_id",
            "graph_version",
            "policy_identity",
            "checkpoint_identity",
        )
    }
    for field in ("objects", "relations"):
        values = record.get(field)
        if type(values) is not list:
            raise _SnapshotRejected("invalid_record")
        if len(values) > 32:
            raise _SnapshotRejected("bounds_exceeded")
        # Cypher collect can contain the OPTIONAL MATCH all-null relation placeholder.
        # Only that exact placeholder is omitted; never coerce malformed evidence.
        prior[field] = (
            [value for value in values if value is not None]
            if field == "objects"
            else [value for value in values if value != {"relation_type": None, "manifold": None, "anchor": None}]
        )
    prior.update(success_rate=record.get("best_success_rate"), episodes=record.get("episodes"), evidence=evidence)
    return validate_prior(prior, evidence, min_success_rate, min_episodes)


def _row_to_prior(record: Any, evidence: str) -> dict[str, Any]:
    """Convert one Cypher record into a prior, dropping null relation placeholders."""
    relations = [r for r in record["relations"] or [] if r and r.get("relation_type")]
    return {
        "name": record["name"],
        "task_description": record["task_description"],
        "task_composition": record["task_composition"],
        "embodiment": record["embodiment"],
        "background": record["background"],
        "objects": [o for o in record["objects"] or [] if o],
        "relations": relations,
        "success_rate": record["best_success_rate"],
        "episodes": record["episodes"],
        "evidence": evidence,
    }


class GraphRAGRetriever:
    """Retrieves prior environment subgraphs from the Neo4j LPG as few-shot generative priors."""

    def __init__(self, driver: neo4j.Driver | None = None):
        self._driver = driver
        self._snapshot_driver = driver

    def retrieve_prior_snapshot(
        self,
        prompt: str,
        limit: int = 2,
        min_success_rate: float = 0.0,
        min_episodes: int = 1,
        *,
        managed_selection_provider=None,
        database: str | None = None,
        before_read=None,
    ) -> dict[str, Any]:
        """Return bounded provenance and the exact context for explicit-driver retrieval.

        The managed callback is a trusted computing boundary: it validates its own
        publication and evaluation readback, declares its authorized ``.database``,
        and cooperates with the deadline. Metadata is not a sandbox or proof of
        callback behavior. Legacy rows receive identical validation with or without it.

        Args:
            prompt: Generation prompt used only to derive keyword filters.
            limit: Maximum priors, from one to five.
            min_success_rate: Exclusive success-rate lower bound, from zero to one.
            min_episodes: Minimum completed episodes, from one to one million.
            managed_selection_provider: Trusted readback callback; receives only the explicitly injected driver.
            database: Explicit authorized database, required for combined managed retrieval.
            before_read: Optional trusted authority check before session/query/cursor IO; cleanup is never gated.

        Returns:
            JSON-safe status, derived_filters, priors, exact_context, context_sha256,
            and safe warning codes. Unconfigured retrieval never discovers credentials.
        """
        valid = (
            type(prompt) is str
            and len(prompt) <= 16384
            and type(limit) is int
            and 1 <= limit <= 5
            and type(min_success_rate) in (int, float)
            and 0 <= min_success_rate <= 1
            and type(min_episodes) is int
            and 1 <= min_episodes <= 1000000
            and (
                database is None
                or (type(database) is str and 0 < len(database) <= 128 and database.strip() == database)
            )
            and (
                managed_selection_provider is None
                or (database is not None and getattr(managed_selection_provider, "database", None) == database)
            )
        )
        emb_filter, fixture_filter = _keyword_filters(prompt) if valid else ("", "")
        receipt = empty_snapshot(prompt if valid else "")
        if valid:
            receipt["effective_settings"] = effective_settings(limit, min_success_rate, min_episodes)
        started = time.monotonic()
        deadline = started + 180.0

        def query_timeout():
            if before_read is not None:
                before_read()
            remaining = deadline - time.monotonic()
            if not 0 < remaining <= 180.0:
                raise _SnapshotRejected("retrieval_failed")
            return min(5.0, remaining)

        def finish():
            if self._snapshot_driver is not None and valid:
                elapsed = time.monotonic() - started
                if not 0 <= elapsed < 180.0:
                    settings = receipt["effective_settings"]
                    receipt.update(empty_snapshot(prompt, warning="retrieval_failed"))
                    receipt["effective_settings"] = settings
                    # Retrieval started, but no bounded measurement can be recorded.
                    # Never clip elapsed time or claim that retrieval did not start.
                    receipt["timing"] = {"source": "unavailable", "elapsed_seconds": None}
                else:
                    receipt["timing"] = {"source": "local_monotonic", "elapsed_seconds": elapsed}
            return validate_prior_snapshot(receipt, prompt=prompt if valid else "")

        if not valid:
            receipt["warnings"] = ["invalid_request"]
            return finish()
        if self._snapshot_driver is None:
            return finish()
        try:
            from neo4j import Query

            params = dict(
                emb_filter=emb_filter,
                fixture_filter=fixture_filter,
                limit=limit,
                min_success_rate=min_success_rate,
                min_episodes=min_episodes,
            )
            candidate_limit = 100 if managed_selection_provider is not None else limit
            params["limit"] = candidate_limit + 1 if managed_selection_provider is not None else limit
            evidence = "measured"
            managed = []
            if managed_selection_provider is not None:
                query_timeout()
                managed = list(
                    islice(
                        managed_selection_provider(
                            self._snapshot_driver,
                            min_success_rate=min_success_rate,
                            min_episodes=min_episodes,
                            embodiment=emb_filter or None,
                            fixture=fixture_filter or None,
                            limit=32,
                            deadline_monotonic=deadline,
                        ),
                        33,
                    )
                )
                if len(managed) > 32:
                    raise _SnapshotRejected("bounds_exceeded")
                query_timeout()
                managed_priors = []
                for record in managed:
                    managed_priors.append(
                        _snapshot_prior(
                            record,
                            "measured" if record.get("best_success_rate") is not None else "unevaluated",
                            min_success_rate,
                            min_episodes,
                        )
                    )
                    if (emb_filter and emb_filter not in (record.get("embodiment") or "")) or (
                        fixture_filter and fixture_filter not in (record.get("background") or "")
                    ):
                        raise _SnapshotRejected("invalid_record")
                _deduplicate_candidates(managed, managed_priors)
            session_options = dict(default_access_mode="READ", fetch_size=6)
            if database is not None:
                session_options["database"] = database
            query_timeout()
            with graph_session(self._snapshot_driver.session(**session_options)) as session:
                records = list(
                    islice(
                        _checked_snapshot_rows(
                            session.run(Query(_SNAPSHOT_EVALUATED_QUERY, timeout=query_timeout()), **params),
                            before_read,
                        ),
                        candidate_limit + 1,
                    )
                )
                query_timeout()
                if len(records) > candidate_limit:
                    raise _SnapshotRejected("bounds_exceeded")
                for record in records:
                    _validate_legacy_provenance(record)
                records += [r for r in managed if r.get("best_success_rate") is not None]
                if not records:
                    evidence = "unevaluated"
                    records = list(
                        islice(
                            _checked_snapshot_rows(
                                session.run(Query(_SNAPSHOT_STRUCTURAL_QUERY, timeout=query_timeout()), **params),
                                before_read,
                            ),
                            candidate_limit + 1,
                        )
                    )
                    if len(records) > candidate_limit:
                        raise _SnapshotRejected("bounds_exceeded")
                    query_timeout()
                    records += managed
            priors = [_snapshot_prior(record, evidence, min_success_rate, min_episodes) for record in records]
            priors = _deduplicate_candidates(records, priors, rank=bool(managed))[:limit]
            context = format_prior_context(priors)
            if len(context.encode("utf-8")) > 32768 or len(json.dumps(priors, allow_nan=False)) > 65536:
                raise _SnapshotRejected("bounds_exceeded")
        except GraphCleanupError:
            raise
        except _SnapshotRejected as exc:
            receipt["warnings"] = [exc.args[0]]
            return finish()
        except (TypeError, KeyError, AttributeError):
            receipt["warnings"] = ["invalid_record"]
            return finish()
        except Exception:
            receipt["warnings"] = ["retrieval_failed"]
            return finish()
        receipt.update(
            status=(("measured" if evidence == "measured" else "structural") if priors else "empty"),
            priors=priors,
            exact_context=context,
            context_sha256=hashlib.sha256(context.encode("utf-8")).hexdigest(),
            warnings=[],
        )
        return finish()

    def get_driver(self) -> neo4j.Driver:
        if self._driver is None:
            self._driver = get_neo4j_driver()
        return self._driver

    def retrieve_prior_subgraphs(
        self, prompt: str, limit: int = 2, min_success_rate: float = 0.0, min_episodes: int = 1
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
            with graph_session(driver.session()) as session:
                records = list(session.run(_EVALUATED_PRIORS_QUERY, **params))
                if records:
                    return [_row_to_prior(r, "measured") for r in records]

                structural = {k: v for k, v in params.items() if k not in ("min_success_rate", "min_episodes")}
                records = list(session.run(_STRUCTURAL_PRIORS_QUERY, **structural))
                return [_row_to_prior(r, "unevaluated") for r in records]
        except GraphCleanupError:
            raise
        except Exception:
            # Generation must not depend on the experience memory being reachable, but a silent
            # miss is indistinguishable from an empty graph, so say which happened.
            logger.warning("Graph-RAG unavailable; continuing without priors.")
            return []

    def format_priors_as_context(self, priors: list[dict[str, Any]]) -> str:
        """Format retrieved subgraphs into a prompt context block."""
        return format_prior_context(priors, structural_outcome="never evaluated")

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
        self, source_env_name: str, checkpoint_identity: str, experiment_id: str | None = None, limit: int = 20
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
                {**_episode_metrics(episodes), "policy_identity": variant["policy_identity"]},
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
