# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure structural XY repair receipts, never placement or runtime evidence."""
import hashlib
import json
from dataclasses import dataclass, field
from math import hypot, isfinite
from typing import Annotated, Literal

from pydantic import Field

from .contracts import (
    Amount,
    Count,
    FrozenModel,
    Hash,
    Identifier,
    SchemaPath,
    WorkflowContract,
    canonical_json,
    contract_digest,
    parse_contract,
)

__all__ = [
    "SceneRepairReceipt",
    "PermittedSceneRepairReceipt",
    "validate_scene_repair",
    "validate_permitted_scene_repair",
    "ResolvedRepairSelection",
    "resolve_repair_selection",
    "validate_selected_scene_repair",
    "project_scene_repair_candidate",
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


DEFAULT_ALLOWED_SECTORS = (
    "center",
    "front_center",
    "front_left",
    "front_right",
    "left_edge",
    "right_edge",
    "back_left",
    "back_right",
)


def _find_object_index(spec: dict, subject_id: str) -> int | None:
    for idx, obj in enumerate(spec.get("objects") or ()):
        if isinstance(obj, dict) and obj.get("id") == subject_id:
            return idx
    return None


def _is_object_frozen(contract: WorkflowContract, obj_idx: int | None) -> bool:
    if obj_idx is None:
        return True
    obj_prefix = f"/objects/{obj_idx}"
    for p in contract.preserved:
        if p.schema_path == obj_prefix or p.schema_path.startswith(obj_prefix + "/params"):
            return True
    return False


def repair_permission_envelope(contract, original, current, *, effective_subjects):
    """Describe the original-centered XY/sector/yaw permission envelope without granting execution.

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
    supported = {f"/relations/{index}/params/{axis}" for axis in ("x", "y", "yaw", "surface_sector")}
    if any(r.coordinate_frame != "env_local" or r.schema_path not in supported for r in rules):
        raise ValueError("repair_unsupported_path_or_frame")
    if current.scene_json != original.scene_json:
        validate_permitted_scene_repair(contract, baseline, selected)
    for rule in contract.preserved:
        _preserved_subtree(baseline, rule.schema_path, rule.subject_id)

    allowed_axes_set = {path.rsplit("/", 1)[1] for path in paths}

    def placement(record, value):
        params = value["relations"][index]["params"]
        info = dict(
            candidate_id=record.candidate_id,
            digest=record.digest,
            xy_m=[_number(params[axis], "repair_invalid_coordinate") for axis in ("x", "y")],
        )
        if "yaw" in allowed_axes_set and "yaw" in params:
            info["yaw_rad"] = _number(params["yaw"], "repair_invalid_coordinate")
        if "surface_sector" in allowed_axes_set and "surface_sector" in params:
            if not isinstance(params["surface_sector"], str):
                raise ValueError("repair_invalid_coordinate")
            info["surface_sector"] = params["surface_sector"]
        return info

    original_placement = placement(original, baseline)
    metric_rules = [r for r in rules if r.schema_path.rsplit("/", 1)[1] in ("x", "y")]
    radius_m = min((r.max_total_displacement_m for r in metric_rules), default=min(r.max_total_displacement_m for r in rules))
    envelope = dict(
        codec="scene-repair-permissions-v1",
        contract_digest=contract_digest(contract),
        subject_id=subject,
        original=original_placement,
        current=placement(current, selected),
        coordinate_frame="env_local",
        mapping="direct-root-translation-v1",
        allowed_paths=paths,
        allowed_axes=sorted(allowed_axes_set),
        admissible_disk=dict(
            center_xy_m=original_placement["xy_m"],
            radius_m=radius_m,
            interpretation="distance_from_original_not_total_path_length",
        ),
        preserved=[r.model_dump(mode="json") for r in contract.preserved],
        preserve_all_other_fields=True,
        forbidden_changes=["task", "physics", "z", "topology"],
        requires_fresh_native_evidence=True,
    )
    if "surface_sector" in allowed_axes_set:
        sector_rules = [r for r in rules if r.schema_path.endswith("/surface_sector")]
        sectors = sector_rules[0].allowed_sectors if sector_rules and sector_rules[0].allowed_sectors else DEFAULT_ALLOWED_SECTORS
        envelope["allowed_sectors"] = list(sectors)
    if "yaw" in allowed_axes_set:
        yaw_rules = [r for r in rules if r.schema_path.endswith("/yaw")]
        yaw_bound = (
            yaw_rules[0].max_angular_displacement_rad
            if yaw_rules and yaw_rules[0].max_angular_displacement_rad is not None
            else (yaw_rules[0].max_total_displacement_m if yaw_rules else 3.141593)
        )
        envelope["max_angular_displacement_rad"] = float(yaw_bound)
    return json.loads(_scene_json(envelope))


def validate_permitted_scene_repair(
    contract: WorkflowContract, original: dict, candidate: dict
) -> PermittedSceneRepairReceipt:
    """Check a frozen contract's scalar XY/yaw/sector repair without applying it or doing IO.

    Supports exact x/y/yaw/surface_sector leaves on one existing non-anchor target in
    env_local frame, plus optional synchronized /objects/{i}/params/initial_pose updates
    when the target object subtree is not frozen by contract.preserved.
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
    subject = rules[0].subject_id
    original_json = _scene_json(original)
    candidate_json = _scene_json(candidate)
    index, _ = _target_relation(original, subject)
    params = original["relations"][index]["params"]
    allowed_axes = set()
    for rule in rules:
        if rule.coordinate_frame != "env_local":
            raise ValueError("repair_unsupported_frame")
        if rule.schema_path not in {
            f"/relations/{index}/params/x",
            f"/relations/{index}/params/y",
            f"/relations/{index}/params/yaw",
            f"/relations/{index}/params/surface_sector",
        }:
            raise ValueError("repair_unsupported_path")
        allowed_axes.add(rule.schema_path.rsplit("/", 1)[1])

    permitted_param_keys = {"x", "y", "z", "relation_loss_weight"} | (allowed_axes & {"yaw", "surface_sector"})
    if set(params) - permitted_param_keys:
        raise ValueError("repair_unsupported_parameters")
    cand_params = candidate.get("relations", [{}])[index].get("params", {}) if index < len(candidate.get("relations", [])) else {}
    if isinstance(cand_params, dict) and (set(cand_params) - permitted_param_keys):
        raise ValueError("repair_unsupported_parameters")

    for rule in contract.preserved:
        _preserved_subtree(original, rule.schema_path, rule.subject_id)

    # Validate discrete surface_sector and angular yaw bounds if enabled
    if "surface_sector" in allowed_axes:
        new_sec = cand_params.get("surface_sector")
        if not isinstance(new_sec, str):
            raise ValueError("repair_invalid_coordinate")
        sec_rules = [r for r in rules if r.schema_path.endswith("/surface_sector")]
        valid_sectors = sec_rules[0].allowed_sectors if sec_rules and sec_rules[0].allowed_sectors else DEFAULT_ALLOWED_SECTORS
        if new_sec not in valid_sectors:
            raise ValueError("repair_forbidden_sector")

    if "yaw" in allowed_axes:
        old_yaw = _number(params.get("yaw", 0.0), "repair_invalid_coordinates")
        new_yaw = _number(cand_params.get("yaw", 0.0), "repair_invalid_coordinates")
        yaw_rules = [r for r in rules if r.schema_path.endswith("/yaw")]
        yaw_bound = (
            yaw_rules[0].max_angular_displacement_rad
            if yaw_rules and yaw_rules[0].max_angular_displacement_rad is not None
            else (yaw_rules[0].max_total_displacement_m if yaw_rules else 3.141593)
        )
        if abs(new_yaw - old_yaw) > float(yaw_bound):
            raise ValueError("repair_displacement_exceeded")

    # Mask ONLY authorized leaves (and synchronized initial_pose when object is not frozen).
    masked = json.loads(candidate_json)
    xy_only_candidate = json.loads(candidate_json)
    try:
        for axis in allowed_axes:
            if axis in params:
                masked["relations"][index]["params"][axis] = params[axis]
            else:
                masked["relations"][index]["params"].pop(axis, None)
            if axis in ("yaw", "surface_sector"):
                if axis in params:
                    xy_only_candidate["relations"][index]["params"][axis] = params[axis]
                else:
                    xy_only_candidate["relations"][index]["params"].pop(axis, None)
    except (KeyError, IndexError, TypeError):
        raise ValueError("repair_forbidden_edit") from None

    obj_idx = _find_object_index(original, subject)
    if obj_idx is not None and not _is_object_frozen(contract, obj_idx):
        cand_obj = masked["objects"][obj_idx]
        orig_obj = original["objects"][obj_idx]
        cand_pose = cand_obj.get("params", {}).get("initial_pose", {})
        if isinstance(cand_pose, dict) and "position_xyz" in cand_pose:
            pos_xyz = cand_pose["position_xyz"]
            if (
                isinstance(pos_xyz, list)
                and len(pos_xyz) >= 2
                and _number(pos_xyz[0], "repair_invalid_coordinates") == _number(cand_params["x"], "repair_invalid_coordinates")
                and _number(pos_xyz[1], "repair_invalid_coordinates") == _number(cand_params["y"], "repair_invalid_coordinates")
            ):
                orig_obj_copy = json.loads(_scene_json(orig_obj))
                masked["objects"][obj_idx] = orig_obj_copy
                xy_only_candidate["objects"][obj_idx] = json.loads(_scene_json(orig_obj))

    if _scene_json(masked) != original_json:
        raise ValueError("repair_forbidden_edit")

    metric_rules = [r for r in rules if r.schema_path.rsplit("/", 1)[1] in ("x", "y")]
    max_xy = min((r.max_total_displacement_m for r in metric_rules), default=min(r.max_total_displacement_m for r in rules))
    _, old_xy = _target_relation(original, subject)
    _, new_xy = _target_relation(candidate, subject)
    distance = hypot(new_xy[0] - old_xy[0], new_xy[1] - old_xy[1])
    non_xy_changed = any(cand_params.get(a) != params.get(a) for a in (allowed_axes & {"yaw", "surface_sector"}))
    if distance == 0 and non_xy_changed:
        bound = _number(max_xy, "repair_invalid_bound")
        if bound < 0:
            raise ValueError("repair_invalid_bound")
        delta = SceneRepairReceipt(subject, index, old_xy, new_xy, 0.0, bound)
    else:
        delta = validate_scene_repair(
            original,
            xy_only_candidate,
            target_id=subject,
            max_xy_displacement_m=max_xy,
        )
    return PermittedSceneRepairReceipt(
        contract_digest(contract),
        hashlib.sha256(_scene_json(original).encode("utf-8")).hexdigest(),
        hashlib.sha256(_scene_json(candidate).encode("utf-8")).hexdigest(),
        delta,
    )



class ResolvedRepairSelection(FrozenModel):
    """Exact original-centered scalar grammar; weighted placement is not a pose assignment."""

    codec: Literal["scalar-xy-selection-v1"]
    run_id: Identifier
    contract_digest: Hash
    original_candidate_id: Hash
    original_scene_digest: Hash
    target_subject: Identifier
    relation_index: Count
    schema_paths: Annotated[tuple[SchemaPath, ...], Field(min_length=1, max_length=2)]
    coordinate_frame: Literal["env_local"]
    units: Literal["m"]
    original_xy_m: tuple[
        Annotated[float, Field(strict=True, allow_inf_nan=False)],
        Annotated[float, Field(strict=True, allow_inf_nan=False)],
    ]
    max_displacement_m: Amount
    placement_semantics: Literal["weighted-at-position-root-xy-v1"]
    relation_loss_weight: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
    applies_changes: Literal[False] = False
    establishes_physical_effect: Literal[False] = False
    requires_measured_displacement: Literal[True] = True

    def digest(self):
        return hashlib.sha256(_scene_json(self.model_dump(mode="json")).encode()).hexdigest()


def resolve_repair_selection(contract, original):
    """Bind frozen permissions to a unique active scalar relation before any effect.

    The caller supplies its retained original CandidateRecord, not a revision.
    Provenance and release authority remain the owner's responsibility. A generated
    scene must match the selected exact-pointer grammar or is refused, not rewritten.
    """
    from .scene_loop import CandidateRecord

    contract = parse_contract(canonical_json(contract))
    original = CandidateRecord.model_validate_json(original.model_dump_json())
    scene = json.loads(original.scene_json)
    raw = _scene_json(scene)
    if (
        original.parent_id is not None
        or original.original_id != original.candidate_id
        or raw != original.scene_json
        or hashlib.sha256(raw.encode()).hexdigest() != original.digest
    ):
        raise ValueError("repair_original_binding_required")
    rules = contract.allowed_interventions
    if not rules or len({r.subject_id for r in rules}) != 1:
        raise ValueError("repair_missing_or_unsupported_permissions")
    subject = rules[0].subject_id
    if contract.action_policy is not None and contract.action_policy.target_subject not in (None, subject):
        raise ValueError("repair_policy_target_mismatch")
    index, xy = _target_relation(scene, subject)
    params = scene["relations"][index]["params"]
    if set(params) - {"x", "y", "z", "relation_loss_weight"}:
        raise ValueError("repair_unsupported_parameters")
    weight = _number(params.get("relation_loss_weight", 1.0), "repair_unsupported_weight")
    if weight <= 0:
        raise ValueError("repair_unsupported_weight")
    paths = tuple(r.schema_path for r in rules)
    if len(set(paths)) != len(paths) or any(
        r.coordinate_frame != "env_local"
        or r.schema_path not in {f"/relations/{index}/params/x", f"/relations/{index}/params/y"}
        for r in rules
    ):
        raise ValueError("repair_unsupported_path_or_frame")
    for rule in contract.preserved:
        _preserved_subtree(scene, rule.schema_path, rule.subject_id)
    return ResolvedRepairSelection(
        codec="scalar-xy-selection-v1",
        run_id=original.run_id,
        contract_digest=contract_digest(contract),
        original_candidate_id=original.candidate_id,
        original_scene_digest=original.digest,
        target_subject=subject,
        relation_index=index,
        schema_paths=paths,
        coordinate_frame="env_local",
        units="m",
        original_xy_m=xy,
        max_displacement_m=min(r.max_total_displacement_m for r in rules),
        placement_semantics="weighted-at-position-root-xy-v1",
        relation_loss_weight=weight,
    )


def validate_selected_scene_repair(contract, selection, original, candidate):
    """Consume the exact resolved selection and preserve every unauthorized field."""
    selection = ResolvedRepairSelection.model_validate(selection.model_dump(mode="python"))
    expected = resolve_repair_selection(contract, original)
    if selection != expected:
        raise ValueError("repair_original_selection_mismatch")
    return validate_permitted_scene_repair(contract, json.loads(original.scene_json), candidate)


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


def project_scene_repair_candidate(
    original: dict,
    target_id: str,
    preferred_sector: str | None = None,
) -> dict:
    """Project target object to nearest safe interior point on support surface."""
    from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
        project_pose_to_safe_support_surface,
    )
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    spec = ArenaEnvGraphSpec.from_dict(original)
    safe_xyz, sector = project_pose_to_safe_support_surface(spec, target_id, preferred_sector=preferred_sector)
    candidate = json.loads(json.dumps(original))
    for obj in candidate.get("objects", []):
        if obj.get("id") == target_id:
            if "params" not in obj:
                obj["params"] = {}
            if "initial_pose" not in obj["params"]:
                obj["params"]["initial_pose"] = {}
            obj["params"]["initial_pose"]["position_xyz"] = safe_xyz
    for rel in candidate.get("relations", []):
        if rel.get("subject") == target_id:
            if "params" in rel:
                rel["params"]["x"] = safe_xyz[0]
                rel["params"]["y"] = safe_xyz[1]
                if len(safe_xyz) > 2:
                    rel["params"]["z"] = safe_xyz[2]
                if sector:
                    rel["params"]["surface_sector"] = sector
    return candidate
