# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Trusted opt-in managed selection; no discovery, driver ownership or write authority.

The caller supplies an already graph_read-authorized driver and its frozen public
profile mapping/database. Empty means no eligible candidates; exceptions mean
unavailable/invalid evidence, never an empty eligible graph. SnapshotRejected
carries receipt-safe warning codes; cleanup failures veto retrieval, while other
errors map to retrieval_failed.
Internal _canonical_proof is for parent dedup ONLY and must be stripped before
strict receipt validation. Membership ordering is lexical, explicitly NOT latest.
Evaluation evidence remains mutable: immutable publication readback is not an
atomic database snapshot. Deadlines are cooperative boundaries, not cancellation
of transport or filesystem operations already in progress.
"""

import hashlib
import json
import math
import time
from copy import deepcopy
from itertools import islice

from isaaclab_arena.agentic_environment_generation.graph_cleanup import close_graph_resources
from isaaclab_arena.agentic_environment_generation.prior_receipt import SnapshotRejected, validate_prior

from . import research_graph_transport as transport
from .research_projection import bounded_neo4j_value, project_scene
from .research_registry import checked_identifier, digest
from .research_source import verify_frozen_spec

# Independent bounded subqueries avoid multiplying policy/controller/graph links.
_EVALUATION_QUERY = """// managed evaluation
MATCH (e:EnvironmentGraph {name: $name, spec_sha256: $sha256, spec_json: $spec_json})
MATCH (ev:EvaluationRun)
WHERE EXISTS { MATCH (ev)-[:EVALUATED_GRAPH]->(e) }
  AND ev.success_rate > $min_success_rate AND ev.num_episodes >= $min_episodes
WITH ev ORDER BY ev.success_rate DESC, ev.num_episodes DESC, ev.id ASC LIMIT 1
CALL { WITH ev MATCH (ev)-[r:EVALUATED_GRAPH]->() WITH r LIMIT 2 RETURN count(r) AS graph_links }
CALL { WITH ev MATCH (other:EvaluationRun {id: ev.id}) WITH other LIMIT 2 RETURN count(other) AS run_ids }
CALL { WITH ev MATCH (ev)-[r:USED_POLICY]->(p)
       WITH r, p LIMIT 2
       RETURN collect(p.name) AS policies, count(r) AS policy_links, collect(labels(p)) AS policy_labels }
CALL { WITH ev MATCH (t)-[r:BASED_ON_EVALUATION]->(ev)
       WITH r LIMIT 2 RETURN count(r) AS trial_links }
CALL { WITH ev MATCH (t)-[:BASED_ON_EVALUATION]->(ev)
       WITH t LIMIT 2
       CALL { WITH t MATCH (t)-[r:BASED_ON_EVALUATION]->(target)
              WITH r, target LIMIT 2
              RETURN count(r) AS evaluation_links, collect(labels(target)) AS evaluation_labels }
       CALL { WITH t MATCH (t)-[r:TRIAL_CONTROLLER]->(v)
              WITH r LIMIT 2 RETURN count(r) AS controller_links }
       OPTIONAL MATCH (t)-[:TRIAL_CONTROLLER]->(v)
       WITH t, v, evaluation_links, evaluation_labels, controller_links LIMIT 2
       RETURN collect({checkpoint_identity:v.checkpoint_identity, policy_identity:v.policy_identity,
                       trial_id:t.id, run_id:t.run_id, trial_policy_identity:t.policy_identity,
                       variant_id:t.variant_id, id:v.id,
                       trial_labels:labels(t), controller_labels:labels(v),
                       evaluation_links:evaluation_links, evaluation_labels:evaluation_labels,
                       controller_links:controller_links,
                       env_name:t.env_name, env_version:t.version}) AS controllers }
RETURN ev.id AS evaluation_id, ev.success_rate AS best_success_rate, ev.num_episodes AS episodes,
       ev.policy_identity AS policy_identity, ev.env_name AS env_name, ev.env_version AS env_version,
       policies, policy_links, policy_labels, trial_links, controllers, graph_links, run_ids LIMIT 2
"""


def _check_deadline(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise SnapshotRejected("retrieval_failed")


def _evaluation(driver, database, row, proof, min_success_rate, min_episodes, deadline_monotonic=None):
    from neo4j import Query

    _check_deadline(deadline_monotonic)
    session = driver.session(database=database, default_access_mode="READ", fetch_size=2)
    try:
        _check_deadline(deadline_monotonic)
        timeout = 5.0 if deadline_monotonic is None else min(5.0, deadline_monotonic - time.monotonic())
        if timeout <= 0:
            raise SnapshotRejected("retrieval_failed")
        records = list(
            islice(
                session.run(
                    Query(_EVALUATION_QUERY, timeout=timeout),
                    **proof,
                    min_success_rate=min_success_rate,
                    min_episodes=min_episodes,
                ),
                2,
            )
        )
    finally:
        close_graph_resources(session)
    _check_deadline(deadline_monotonic)
    if len(records) > 1:
        raise SnapshotRejected("invalid_record")
    if not records:
        return
    ev = dict(records[0])
    bounded_neo4j_value(ev, max_bytes=32768)
    if (
        type(ev["graph_links"]) is not int
        or ev["graph_links"] != 1
        or type(ev["run_ids"]) is not int
        or ev["run_ids"] != 1
        or type(ev["policies"]) is not list
        or len(ev["policies"]) > 1
        or type(ev["policy_links"]) is not int
        or ev["policy_links"] != len(ev["policies"])
        or type(ev["policy_labels"]) is not list
        or len(ev["policy_labels"]) != ev["policy_links"]
        or any(type(labels) is not list or "Policy" not in labels for labels in ev["policy_labels"])
        or type(ev["controllers"]) is not list
        or len(ev["controllers"]) > 1
        or type(ev["trial_links"]) is not int
        or ev["trial_links"] != len(ev["controllers"])
        or ev.get("env_name") not in (None, row["name"])
        or ev.get("env_version") not in (None, row["graph_version"])
    ):
        raise SnapshotRejected("invalid_record")
    from isaaclab_arena.agentic_environment_generation.prior_receipt import bounded_text

    for value in ev["policies"]:
        bounded_text(value, nullable=False)
    run_policy = ev.get("policy_identity")
    if run_policy is not None:
        bounded_text(run_policy, nullable=False)
    policy = ev["policies"][0] if ev["policies"] else None
    if run_policy is not None and policy is not None and run_policy != policy:
        raise SnapshotRejected("invalid_record")
    if policy is None:
        policy = run_policy
    checkpoint = None
    if ev["controllers"]:
        # Controller-backed evidence requires the run's own facts, not policy fallback.
        for field in ("evaluation_id", "env_name", "env_version", "policy_identity"):
            bounded_text(ev.get(field), nullable=False)
        controller = ev["controllers"][0]
        if (
            type(controller) is not dict
            or type(controller.get("trial_labels")) is not list
            or "DCRGControllerTrial" not in controller["trial_labels"]
            or type(controller.get("controller_labels")) is not list
            or "DCRGControllerVariant" not in controller["controller_labels"]
            or type(controller.get("evaluation_links")) is not int
            or controller["evaluation_links"] != 1
            or type(controller.get("controller_links")) is not int
            or controller["controller_links"] != 1
            or type(controller.get("evaluation_labels")) is not list
            or len(controller["evaluation_labels"]) != 1
            or type(controller["evaluation_labels"][0]) is not list
            or "EvaluationRun" not in controller["evaluation_labels"][0]
            or controller.get("trial_id") != ev["evaluation_id"]
            or controller.get("run_id") != ev["evaluation_id"]
            or controller.get("trial_policy_identity") != policy
            or controller.get("policy_identity") != policy
            or not controller.get("id")
            or controller.get("variant_id") != controller["id"]
            or controller.get("env_name") != row["name"]
            or controller.get("env_version") != row["graph_version"]
            or run_policy != policy
            or ev["env_name"] != controller.get("env_name")
            or ev["env_version"] != controller.get("env_version")
        ):
            raise SnapshotRejected("invalid_record")
        for field in (
            "trial_id",
            "run_id",
            "trial_policy_identity",
            "env_name",
            "env_version",
            "id",
            "variant_id",
            "policy_identity",
            "checkpoint_identity",
        ):
            bounded_text(controller.get(field), nullable=False)
        checkpoint = controller["checkpoint_identity"]
    row.update({key: ev[key] for key in ("evaluation_id", "best_success_rate", "episodes")})
    row.update(policy_identity=policy, checkpoint_identity=checkpoint)


class ManagedSelectionProvider:
    """Select from <=16 explicit (ResearchStore, PublicationAttempts) pairs.

    authorized_targets maps profile_id to exact {profile_id, revision,
    scope_ownership}. It is copied at construction, never discovered. Optional
    pinned_scopes maps full canonical SHA to an exact scope ID. candidate_budget
    caps all local reservations BEFORE eligibility/filtering/ranking (maximum 32).
    Direct calls default to five; limit=32 returns the full bounded candidate set
    for adapter-owned global ranking. deadline_monotonic is an optional shared
    monotonic deadline, checked before and after blocking/local work.
    """

    def __init__(self, stores, *, database, authorized_targets, pinned_scopes=None, candidate_budget=32):
        if type(stores) not in (list, tuple) or not 1 <= len(stores) <= 16:
            raise ValueError("Explicit bounded stores required")
        checked_identifier(database)
        if type(candidate_budget) is not int or not 1 <= candidate_budget <= 32:
            raise ValueError("Invalid candidate budget")
        if type(authorized_targets) is not dict or not 1 <= len(authorized_targets) <= 16:
            raise ValueError("Explicit frozen targets required")
        for key, target in authorized_targets.items():
            if (
                type(target) is not dict
                or set(target) != {"profile_id", "revision", "scope_ownership"}
                or target["profile_id"] != key
                or target["scope_ownership"] != "cooperative_immutable"
            ):
                raise ValueError("Invalid frozen target")
            for value in target.values():
                checked_identifier(value)
        self._stores = tuple(stores)
        ids = []
        for store, attempts in self._stores:
            if (
                attempts.journal is not store.registry.journal
                or attempts.registry.journal is not store.registry.journal
                or attempts.registry.registry_id != store.registry.registry_id
            ):
                raise ValueError("Foreign publication journal/registry")
            ids.append(store.store_id)
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate explicit store ID")
        self.database = database
        self._targets = deepcopy(authorized_targets)
        pins = {} if pinned_scopes is None else pinned_scopes
        if (
            type(pins) is not dict
            or len(pins) > 32
            or any(
                type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
                for pair in pins.items()
                for value in pair
            )
        ):
            raise ValueError("Invalid bounded canonical/scope pin")
        self._pins = deepcopy(pins)
        self._budget = candidate_budget

    def _prepare(self, store, attempts, reservation_id, deadline_monotonic=None):
        _check_deadline(deadline_monotonic)
        registry = store.registry
        reservation = store.get_reservation(reservation_id)
        _check_deadline(deadline_monotonic)
        commit = registry.get_commit(reservation_id)
        _check_deadline(deadline_monotonic)
        if commit is None or commit["publication_intent_id"] is None:
            return None
        effect = commit["publication_intent_id"]
        intent = registry.get_publication_intent(effect)
        _check_deadline(deadline_monotonic)
        if intent is None:
            raise ValueError("Missing committed publication intent")
        target = intent["target_profile"]
        if type(target) is not dict or target != self._targets.get(target.get("profile_id")):
            return None
        state = attempts.get_state(effect)
        _check_deadline(deadline_monotonic)
        if state["state"] != "verified":
            return None
        request = reservation["publication_request"]
        expected_intent = dict(
            **request,
            payload=intent["payload"],
            payload_sha256=digest(intent["payload"]),
            schema_version=1,
            registry_id=registry.registry_id,
            reservation_id=reservation_id,
            state="pending",
        )
        if commit["reservation"] != reservation or intent != expected_intent:
            raise ValueError("Immutable intent conflict")
        _check_deadline(deadline_monotonic)
        files = store.read_version(reservation_id)
        _check_deadline(deadline_monotonic)
        if json.loads(files["source.json"]) != reservation:
            raise ValueError("Immutable source conflict")
        _check_deadline(deadline_monotonic)
        spec = verify_frozen_spec(reservation["source"], files)
        _check_deadline(deadline_monotonic)
        projection = project_scene(
            spec,
            store_id=store.store_id,
            revision_id=reservation["revision_id"],
            family=reservation["family"],
            version=f"v{reservation['version']}",
        )
        _check_deadline(deadline_monotonic)
        descriptor = dict(
            artifact="projection.json",
            artifact_sha256=hashlib.sha256(files["projection.json"]).hexdigest(),
            projection_digest=projection["digest"],
            scope_id=projection["scope_id"],
        )
        if json.loads(files["projection.json"]) != projection or descriptor != intent["payload"]:
            raise ValueError("Immutable descriptor/projection conflict")
        evidence = dict(
            status="verified",
            database=self.database,
            effect_id=effect,
            scope_id=projection["scope_id"],
            projection_digest=projection["digest"],
            canonical_identity=projection["canonical_identity"],
            verification_boundary=dict(
                method="operator_attested_immutable_scope_v1",
                operator_attested=True,
                declaration=transport.IMMUTABLE_SCOPE_DECLARATION,
                database_snapshot=False,
            ),
        )
        receipt = dict(
            schema_version=1,
            status="verified",
            effect_id=effect,
            target_profile=target,
            payload_sha256=intent["payload_sha256"],
            transport=evidence,
        )
        with attempts.journal._lock:
            _check_deadline(deadline_monotonic)
            record = attempts.journal.db.execute(
                "SELECT body FROM publication_receipts WHERE effect_id=?", (effect,)
            ).fetchone()
        _check_deadline(deadline_monotonic)
        durable = json.loads(record[0]) if record is not None else {}
        if (
            durable.get("receipt") != receipt
            or durable.get("attempt_id") != state["attempt_id"]
            or durable.get("generation") != state["generation"]
            or state["receipt"] != receipt
            or state["effect_id"] != effect
            or state["target_profile"] != target
            or state["payload_sha256"] != intent["payload_sha256"]
        ):
            raise ValueError("Durable verified receipt conflict")
        return dict(projection=projection, spec=spec, effect=effect, evidence=evidence)

    def __call__(
        self, driver, *, min_success_rate, min_episodes, embodiment=None, fixture=None, limit=5, deadline_monotonic=None
    ):
        if (
            type(limit) is not int
            or not 1 <= limit <= 32
            or type(min_success_rate) not in (int, float)
            or not 0 <= min_success_rate <= 1
            or type(min_episodes) is not int
            or not 1 <= min_episodes <= 1000000
            or any(v is not None and (type(v) is not str or len(v) > 4096) for v in (embodiment, fixture))
            or (
                deadline_monotonic is not None
                and (
                    type(deadline_monotonic) not in (int, float)
                    or not 0 <= deadline_monotonic <= 1e15
                    or not math.isfinite(deadline_monotonic)
                )
            )
        ):
            raise SnapshotRejected("invalid_request")
        _check_deadline(deadline_monotonic)
        candidates = []
        count = 0
        for store, attempts in sorted(self._stores, key=lambda pair: pair[0].store_id):
            _check_deadline(deadline_monotonic)
            with attempts.journal._lock:
                _check_deadline(deadline_monotonic)
                attempts._check(attempts.journal.db)
                records = attempts.journal.db.execute(
                    "SELECT reservation_id FROM research_reservations WHERE store_id=? ORDER BY family, "
                    "json_extract(body,'$.revision_id') LIMIT ?",
                    (store.store_id, self._budget + 1),
                ).fetchall()
            _check_deadline(deadline_monotonic)
            count += len(records)
            if count > self._budget:
                raise SnapshotRejected("bounds_exceeded")
            for record in records:
                _check_deadline(deadline_monotonic)
                prepared = self._prepare(store, attempts, record[0], deadline_monotonic)
                _check_deadline(deadline_monotonic)
                if prepared is not None:
                    candidates.append(prepared)
        groups, hashes, names = {}, {}, {}
        for candidate in candidates:
            _check_deadline(deadline_monotonic)
            projection = candidate["projection"]
            root = next(n["properties"] for n in projection["nodes"] if n["labels"] == ["EnvironmentGraph"])
            sha, payload, name = root["spec_sha256"], root["spec_json"], root["name"]
            if (
                hashlib.sha256(payload.encode()).hexdigest() != sha
                or (sha in hashes and hashes[sha] != payload)
                or (name in names and names[name] != (sha, payload))
            ):
                raise ValueError("Canonical identity collision")
            hashes[sha], names[name] = payload, (sha, payload)
            groups.setdefault((sha, payload), []).append(candidate)
        selected = []
        for (sha, _), group in sorted(groups.items()):
            _check_deadline(deadline_monotonic)
            group.sort(
                key=lambda c: tuple(c["projection"]["scope"][k] for k in ("store_id", "family", "revision_id"))
                + (c["projection"]["scope_id"],)
            )
            if sha in self._pins:
                group = [c for c in group if c["projection"]["scope_id"] == self._pins[sha]]
                if not group:
                    raise ValueError("Pinned scope unavailable")
            selected.append(group[0])
        if set(self._pins) - set(hashes):
            raise ValueError("Pinned canonical identity unavailable")
        rows = []
        for candidate in selected:
            _check_deadline(deadline_monotonic)
            projection = candidate["projection"]
            actual = transport.reconcile_once(
                driver,
                self.database,
                projection,
                spec=candidate["spec"],
                effect_id=candidate["effect"],
                immutable_scope_attested=True,
            )
            _check_deadline(deadline_monotonic)
            if actual != candidate["evidence"]:
                raise ValueError("Managed readback unavailable")
            root = next(n["properties"] for n in projection["nodes"] if n["labels"] == ["EnvironmentGraph"])
            data = json.loads(root["spec_json"])
            row = dict(
                name=root["name"],
                task_description=data["task"]["description"],
                task_composition=data["task"]["composition"],
                embodiment=data["embodiment"]["registry_name"],
                background=data["background"]["registry_name"],
                objects=[o["registry_name"] for o in data["objects"]],
                relations=[
                    dict(
                        relation_type=r["relation_type"],
                        manifold=r.get("kinematic_manifold"),
                        anchor=r.get("surface_anchor"),
                    )
                    for r in data.get("reified_relations", [])
                ],
                best_success_rate=None,
                episodes=None,
                evaluation_id=None,
                policy_identity=None,
                checkpoint_identity=None,
                graph_version=root["spec_sha256"],
            )
            if (embodiment and embodiment not in row["embodiment"]) or (fixture and fixture not in row["background"]):
                continue
            proof = dict(name=root["name"], sha256=root["spec_sha256"], spec_json=root["spec_json"])
            _check_deadline(deadline_monotonic)
            _evaluation(driver, self.database, row, proof, min_success_rate, min_episodes, deadline_monotonic)
            _check_deadline(deadline_monotonic)
            evidence = "measured" if row["evaluation_id"] is not None else "unevaluated"
            validate_prior(
                {
                    **{k: v for k, v in row.items() if k != "best_success_rate"},
                    "success_rate": row["best_success_rate"],
                    "evidence": evidence,
                },
                evidence,
                min_success_rate,
                min_episodes,
            )
            row["_canonical_proof"] = proof
            _check_deadline(deadline_monotonic)
            rows.append(row)
        measured = [row for row in rows if row["evaluation_id"] is not None]
        if measured:
            structural = [row for row in rows if row["evaluation_id"] is None]
            rows = sorted(
                measured, key=lambda r: (-r["best_success_rate"], -r["episodes"], r["evaluation_id"], r["name"])
            )
            if limit == 32:
                rows.extend(structural)  # Adapter owns global measured-first selection.
        _check_deadline(deadline_monotonic)
        result = deepcopy(rows[:limit])
        _check_deadline(deadline_monotonic)
        return result
