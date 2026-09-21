# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure structural XY repair receipts, never placement or runtime evidence."""
import hashlib
import json
from dataclasses import dataclass, field
from math import hypot, isfinite

from .contracts import WorkflowContract, canonical_json, contract_digest, parse_contract

__all__ = [
    "SceneRepairReceipt",
    "PermittedSceneRepairReceipt",
    "validate_scene_repair",
    "validate_permitted_scene_repair",
]


@dataclass(frozen=True, slots=True)
class PermittedSceneRepairReceipt:
    """Contract and canonical scene bindings for a structural proposal only."""

    contract_digest: str
    original_scene_digest: str
    candidate_scene_digest: str
    delta: "SceneRepairReceipt"


def _preserved_subtree(original, path, subject_id):
    """Resolve a frozen existing subtree and its enclosing identity or relation."""
    node = original
    owner = None
    try:
        for token in path.split("/")[1:]:
            token = token.replace("~1", "/").replace("~0", "~")
            if type(node) is list:
                if not token.isascii() or not token.isdecimal() or str(int(token)) != token:
                    raise ValueError("repair_unsupported_preservation")
                node = node[int(token)]
            else:
                node = node[token]
            if type(node) is dict:
                owner = node.get("subject", node.get("id", owner))
    except (KeyError, IndexError, TypeError):
        raise ValueError("repair_unsupported_preservation") from None
    if owner != subject_id:
        raise ValueError("repair_unsupported_preservation")


def repair_permission_envelope(contract, original, current, *, effective_subjects):
    """Describe the original-centered XY permission disk without granting execution.

    Args:
        contract: Frozen intervention and preservation rules.
        original: Retained original candidate, never a previous revision.
        current: Retained candidate whose selected assessment permits repair.
        effective_subjects: Trusted adapter's direct-root mapping capability.

    Returns:
        Bounded public model instructions; the full-candidate guard remains authoritative.
    """
    contract = parse_contract(canonical_json(contract))
    rules = contract.allowed_interventions
    if not rules or len({r.subject_id for r in rules}) != 1:
        raise ValueError("repair_missing_or_unsupported_permissions")
    subject = rules[0].subject_id
    if subject not in effective_subjects:
        raise ValueError("repair_effective_mapping_required")
    if current.run_id != original.run_id or current.original_id != original.candidate_id:
        raise ValueError("repair_lineage_mismatch")
    baseline, selected = json.loads(original.scene_json), json.loads(current.scene_json)
    for record, value in ((original, baseline), (current, selected)):
        if hashlib.sha256(_scene_json(value).encode()).hexdigest() != record.digest:
            raise ValueError("repair_candidate_digest_mismatch")
    index, _ = _target_relation(baseline, subject)
    paths = [r.schema_path for r in rules]
    supported = {f"/relations/{index}/params/{axis}" for axis in ("x", "y")}
    if any(r.coordinate_frame != "env_local" or r.schema_path not in supported for r in rules):
        raise ValueError("repair_unsupported_path_or_frame")
    if current.scene_json != original.scene_json:
        validate_permitted_scene_repair(contract, baseline, selected)
    for rule in contract.preserved:
        _preserved_subtree(baseline, rule.schema_path, rule.subject_id)

    def placement(record, value):
        params = value["relations"][index]["params"]
        return dict(
            candidate_id=record.candidate_id,
            digest=record.digest,
            xy_m=[_number(params[axis], "repair_invalid_coordinate") for axis in ("x", "y")],
        )

    original_placement = placement(original, baseline)
    envelope = dict(
        codec="scene-repair-permissions-v1",
        contract_digest=contract_digest(contract),
        subject_id=subject,
        original=original_placement,
        current=placement(current, selected),
        coordinate_frame="env_local",
        mapping="direct-root-translation-v1",
        allowed_paths=paths,
        allowed_axes=sorted({path.rsplit("/", 1)[1] for path in paths}),
        admissible_disk=dict(
            center_xy_m=original_placement["xy_m"],
            radius_m=min(r.max_total_displacement_m for r in rules),
            interpretation="distance_from_original_not_total_path_length",
        ),
        preserved=[r.model_dump(mode="json") for r in contract.preserved],
        preserve_all_other_fields=True,
        forbidden_changes=["task", "physics", "z", "topology"],
        requires_fresh_native_evidence=True,
    )
    return json.loads(_scene_json(envelope))


def validate_permitted_scene_repair(
    contract: WorkflowContract, original: dict, candidate: dict
) -> PermittedSceneRepairReceipt:
    """Check a frozen contract's scalar XY repair without applying it or doing IO.

    Only exact x/y leaves on one existing non-anchor target are supported, in
    env_local meters. The Euclidean ceiling is conservatively the minimum of
    ALL rules for that target, even if one allowed axis is unchanged. Frozen
    preservation paths must resolve beneath an identity or subject relation.
    No source text is parsed, enriched or rewritten. The caller must retain the
    original baseline; these digests bind supplied bytes, not their provenance.

    Args:
        contract: Frozen intent; no external target or bound overrides.
        original: Retained original baseline, never the previous repair attempt.
        candidate: Proposed scene, left untouched.

    Returns:
        Immutable bindings and delta, not runtime validity or physical success.
    """
    if type(contract) is not WorkflowContract:
        raise ValueError("repair_invalid_contract")
    # Validate Python values before JSON serialization can coerce unsafe copies
    # (notably bool into a float). Then freeze canonical validated values again.
    contract = WorkflowContract.model_validate(contract.model_dump(mode="python"))
    contract = parse_contract(canonical_json(contract))
    rules = contract.allowed_interventions
    if not rules:
        raise ValueError("repair_missing_permissions")
    if len({rule.subject_id for rule in rules}) != 1:
        raise ValueError("repair_unsupported_multiple_targets")
    original_json = _scene_json(original)
    candidate_json = _scene_json(candidate)
    index, _ = _target_relation(original, rules[0].subject_id)
    params = original["relations"][index]["params"]
    if set(params) - {"x", "y", "z", "relation_loss_weight"}:
        raise ValueError("repair_unsupported_parameters")
    allowed_axes = set()
    for rule in rules:
        if rule.coordinate_frame != "env_local":
            raise ValueError("repair_unsupported_frame")
        if rule.schema_path not in {f"/relations/{index}/params/x", f"/relations/{index}/params/y"}:
            raise ValueError("repair_unsupported_path")
        allowed_axes.add(rule.schema_path.rsplit("/", 1)[1])
    for rule in contract.preserved:
        _preserved_subtree(original, rule.schema_path, rule.subject_id)
    # The existing guard masks both axes; additionally mask ONLY authorized
    # leaves here. Canonical comparison preserves numeric representation too.
    masked = json.loads(candidate_json)
    try:
        for axis in allowed_axes:
            masked["relations"][index]["params"][axis] = params[axis]
    except (KeyError, IndexError, TypeError):
        raise ValueError("repair_forbidden_edit") from None
    if _scene_json(masked) != original_json:
        raise ValueError("repair_forbidden_edit")
    delta = validate_scene_repair(
        original,
        candidate,
        target_id=rules[0].subject_id,
        max_xy_displacement_m=min(rule.max_total_displacement_m for rule in rules),
    )
    return PermittedSceneRepairReceipt(
        contract_digest(contract),
        hashlib.sha256(_scene_json(original).encode("utf-8")).hexdigest(),
        hashlib.sha256(_scene_json(candidate).encode("utf-8")).hexdigest(),
        delta,
    )


@dataclass(frozen=True, slots=True)
class SceneRepairReceipt:
    """An immutable proposal delta; fresh runtime evidence is always required."""

    target_id: str
    relation_index: int
    original_xy: tuple[float, float]
    candidate_xy: tuple[float, float]
    displacement_m: float
    max_xy_displacement_m: float
    requires_fresh_runtime_evidence: bool = field(default=True, init=False)
    applies_changes: bool = field(default=False, init=False)


def _number(value, code):
    if type(value) not in (int, float):
        raise ValueError(code)
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise ValueError(code) from None
    if not isfinite(result):
        raise ValueError(code)
    return result


def _scene_json(value):
    """Bound scene input before encoding; not a public general-purpose codec."""
    # contracts.canonical_json currently accepts WorkflowContract only. Keep this
    # scene-specific until the shared canonical codec accepts arbitrary JSON.
    remaining = 1_048_576
    nodes = 0
    active = set()

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes += 1
        remaining -= 1
        if depth > 32 or nodes > 100_000 or remaining < 0:
            raise ValueError("repair_invalid_json")
        kind = type(item)
        if kind is str:
            if len(item) > remaining:
                raise ValueError("repair_invalid_json")
            remaining -= len(item.encode("utf-8"))
        elif kind is int:
            if item.bit_length() > 1024:
                raise ValueError("repair_invalid_json")
        elif kind is float:
            if not isfinite(item):
                raise ValueError("repair_invalid_json")
        elif item is None or kind is bool:
            pass
        elif kind in (dict, list):
            identity = id(item)
            if identity in active:
                raise ValueError("repair_invalid_json")
            active.add(identity)
            if kind is dict:
                for key, child in item.items():
                    if type(key) is not str:
                        raise ValueError("repair_invalid_json")
                    visit(key, depth + 1)
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
            active.remove(identity)
        else:
            raise ValueError("repair_invalid_json")
        if remaining < 0:
            raise ValueError("repair_invalid_json")

    try:
        if type(value) is not dict:
            raise ValueError("repair_invalid_json")
        visit(value, 0)
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > 1_048_576:
            raise ValueError("repair_invalid_json")
        return encoded
    except (UnicodeError, RecursionError, OverflowError):
        raise ValueError("repair_invalid_json") from None


def _target_relation(spec, target_id):
    objects = spec.get("objects")
    relations = spec.get("relations")
    refs = spec.get("object_references") or []
    if type(objects) is not list or type(relations) is not list or type(refs) is not list:
        raise ValueError("repair_unsupported_structure")
    identities = objects + refs + [spec.get("embodiment"), spec.get("background")]
    if any(type(item) is not dict for item in identities + relations):
        raise ValueError("repair_unsupported_structure")
    if (
        sum(item.get("id") == target_id for item in objects) != 1
        or sum(item.get("id") == target_id for item in identities) != 1
    ):
        raise ValueError("repair_target_not_unique")
    if any(relation.get("kind") == "is_anchor" and relation.get("subject") == target_id for relation in relations):
        raise ValueError("repair_unsupported_anchor")
    supports = [
        relation for relation in relations if relation.get("kind") == "on" and relation.get("subject") == target_id
    ]
    if len(supports) != 1:
        raise ValueError("repair_unsupported_on")
    reference = supports[0].get("reference")
    if (
        type(reference) is not str
        or not reference
        or reference == target_id
        or sum(item.get("id") == reference for item in identities) != 1
    ):
        raise ValueError("repair_unsupported_on")
    matches = [
        i
        for i, relation in enumerate(relations)
        if relation.get("kind") == "at_position" and relation.get("subject") == target_id
    ]
    if not matches:
        raise ValueError("repair_unsupported_no_at_position")
    if len(matches) != 1:
        raise ValueError("repair_relation_not_unique")
    index = matches[0]
    params = relations[index].get("params")
    if type(params) is not dict or "x" not in params or "y" not in params:
        raise ValueError("repair_invalid_coordinates")
    xy = (_number(params["x"], "repair_invalid_coordinates"), _number(params["y"], "repair_invalid_coordinates"))
    return index, xy


def validate_scene_repair(
    original: dict, candidate: dict, *, target_id: str, max_xy_displacement_m: float
) -> SceneRepairReceipt:
    """Validate an existing scalar x/y at_position replacement, without IO.

    This narrow profile requires a non-anchor target and exactly one on relation
    referencing a distinct, uniquely resolvable scene identity. It accepts explicit
    finite scalar x/y only, not vector-form or general AtPosition configurations.
    Support geometry and runtime feasibility still require fresh evidence. The
    caller must retain the original baseline; its provenance is not authenticated.

    Args:
        original: Immutable caller-owned baseline, not the previous attempt.
        candidate: Proposed complete dict-shaped Arena scene; never modified.
        target_id: Unique movable object ID (at most 128 UTF-8 bytes).
        max_xy_displacement_m: Nonnegative finite Euclidean limit from original.

    Returns:
        Frozen bounded delta requiring fresh runtime evidence; applies no changes.
    """
    if type(target_id) is not str or not target_id or len(target_id) > 128:
        raise ValueError("repair_invalid_target")
    try:
        if len(target_id.encode("utf-8")) > 128:
            raise ValueError("repair_invalid_target")
    except UnicodeError:
        raise ValueError("repair_invalid_target") from None
    bound = _number(max_xy_displacement_m, "repair_invalid_bound")
    if bound < 0:
        raise ValueError("repair_invalid_bound")
    original_json = _scene_json(original)
    candidate_json = _scene_json(candidate)
    index, old_xy = _target_relation(original, target_id)
    new_index, new_xy = _target_relation(candidate, target_id)
    if new_index != index:
        raise ValueError("repair_forbidden_edit")
    # Round-trip only the bounded validated proposal. Restore the two permitted
    # leaves, then compare canonical bytes (not Python's bool/int equality).
    masked = json.loads(candidate_json)
    for axis in ("x", "y"):
        masked["relations"][index]["params"][axis] = original["relations"][index]["params"][axis]
    if _scene_json(masked) != original_json:
        raise ValueError("repair_forbidden_edit")
    distance = hypot(new_xy[0] - old_xy[0], new_xy[1] - old_xy[1])
    if distance == 0:
        raise ValueError("repair_no_op")
    if not isfinite(distance) or distance > bound:
        raise ValueError("repair_displacement_exceeded")
    return SceneRepairReceipt(target_id, index, old_xy, new_xy, distance, bound)
