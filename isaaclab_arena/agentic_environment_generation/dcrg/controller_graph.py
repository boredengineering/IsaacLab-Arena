# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Immutable same-scene controller interventions, separate from XY proposal lineage."""

from __future__ import annotations

import hashlib
import json
import re

from isaaclab_arena.agentic_environment_generation.dcrg.graph import (
    _edge,
    _ensure_schema,
    _json,
    _node,
    _registered_evaluation,
    _registered_graph,
    _text,
    _verified,
)


def _sha256(value, field):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field} must be a full lowercase SHA-256")


def _contract_payload(contract):
    if not isinstance(contract, dict):
        raise ValueError("Controller contract must be a JSON object")
    for field in ("checkpoint_identity", "hand_body", "frame"):
        _text(contract.get(field), field)
    for field in ("checkpoint_weights_sha256", "source_sha256"):
        mapping = contract.get(field)
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError(f"Nonempty {field} mapping is required")
        for name, digest in mapping.items():
            _text(name, field)
            _sha256(digest, field)
    _sha256(contract.get("policy_config_sha256"), "policy_config_sha256")
    if not isinstance(contract.get("controller_config"), dict):
        raise ValueError("controller_config must be a JSON object")
    if contract.get("privilege_mode") != "privileged_state_diagnostic":
        raise ValueError("privilege_mode must explicitly label privileged_state_diagnostic")
    if contract.get("scenario_contract") != "c1_existing_left_hand_baseline":
        raise ValueError("scenario_contract must be c1_existing_left_hand_baseline")
    return _json(contract)


def register_controller_variant(contract: dict, driver) -> dict:
    """Register a frozen controller contract before running its composite policy.

    The caller computes real fingerprints and binds the saved contract/config to the
    evaluation's hashed manifest artifacts. Verification here means graph read-back,
    not inspection of the remote server's weights. Extra JSON fields are preserved
    and included in the digest; timestamps and run-specific data belong in a separate
    run manifest, not this reusable variant contract.

    Args:
        contract: Required fields: checkpoint_identity, checkpoint_weights_sha256
            (nonempty filename-to-SHA256 mapping), controller_config (JSON object),
            source_sha256 (nonempty mapping covering controller and base-policy sources),
            policy_config_sha256 (base policy configuration), hand_body, frame,
            privilege_mode='privileged_state_diagnostic', and
            scenario_contract='c1_existing_left_hand_baseline'. Digests are full
            lowercase SHA-256 strings; labels are explicit nonempty strings.
        driver: Caller-owned Neo4j driver with schema privileges.

    Returns:
        Verified variant_id (canonical SHA-256), checkpoint_identity and policy_identity.
    """
    payload = _contract_payload(contract)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    checkpoint = contract["checkpoint_identity"]
    identity = {
        "variant_id": digest,
        "checkpoint_identity": checkpoint,
        "policy_identity": checkpoint + "#controller:" + digest,
        "verified": True,
    }

    def write(tx):
        _node(
            tx,
            "DCRGControllerVariant",
            {"id": digest},
            {
                "spec_json": payload,
                "checkpoint_identity": checkpoint,
                "policy_identity": identity["policy_identity"],
                "privileged_state": contract["privilege_mode"] == "privileged_state_diagnostic",
            },
        )
        return identity

    _ensure_schema(driver)
    with driver.session() as session:
        return session.execute_write(write)


def _verified_variant(properties):
    contract = json.loads(properties["spec_json"])
    payload = _contract_payload(contract)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    _verified(
        [{"properties": properties}],
        {
            "id": digest,
            "spec_json": payload,
            "checkpoint_identity": contract["checkpoint_identity"],
            "policy_identity": contract["checkpoint_identity"] + "#controller:" + digest,
            "privileged_state": True,
        },
        "controller variant",
    )
    return contract


def attach_controller_evaluation(run_id: str, variant_id: str, experiment_id: str, driver) -> dict:
    """Attach an already registered evaluation to an immutable comparison trial.

    Args:
        run_id: Existing EvaluationRun.id; a run can belong to only one trial/group.
        variant_id: Previously registered canonical controller contract digest.
        experiment_id: Explicit comparison group, never inferred from a checkpoint path.
        driver: Caller-owned Neo4j driver with schema privileges.

    Returns:
        Verified run, variant, experiment, environment and composite policy identities.
    """
    _text(run_id, "run_id")
    _sha256(variant_id, "variant_id")
    _text(experiment_id, "experiment_id")
    variant = ("DCRGControllerVariant", {"id": variant_id})
    trial = ("DCRGControllerTrial", {"id": run_id})
    experiment = ("DCRGControllerExperiment", {"id": experiment_id})

    def write(tx):
        variant_props = _node(tx, *variant)
        contract = _verified_variant(variant_props)
        policy_identity = variant_props["policy_identity"]
        run = _node(tx, "EvaluationRun", {"id": run_id})
        if run.get("policy_identity") != policy_identity:
            raise ValueError("Evaluation composite policy_identity conflict")
        graph = _registered_graph(tx, run["env_name"], run["env_version"])
        evaluation, run = _registered_evaluation(tx, run_id, graph, run["env_version"])
        properties = {
            "run_id": run_id,
            "variant_id": variant_id,
            "experiment_id": experiment_id,
            "env_name": run["env_name"],
            "version": run["env_version"],
            "policy_identity": variant_props["policy_identity"],
        }
        _node(
            tx,
            *experiment,
            {
                "env_name": run["env_name"],
                "version": run["env_version"],
                "checkpoint_identity": contract["checkpoint_identity"],
                "scenario_contract": contract["scenario_contract"],
                "checkpoint_weights_sha256_json": _json(contract["checkpoint_weights_sha256"]),
                "policy_config_sha256": contract["policy_config_sha256"],
                "hand_body": contract["hand_body"],
                "frame": contract["frame"],
            },
        )
        _node(tx, *trial, properties)
        for target, relation in (
            (variant, "TRIAL_CONTROLLER"),
            (evaluation, "BASED_ON_EVALUATION"),
            (experiment, "IN_CONTROLLER_EXPERIMENT"),
        ):
            _edge(tx, trial, target, relation, {})
        return {**properties, "verified": True}

    _ensure_schema(driver)
    with driver.session() as session:
        return session.execute_write(write)
