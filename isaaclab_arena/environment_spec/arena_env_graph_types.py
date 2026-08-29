# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pydantic schema for :class:`~isaaclab_arena.environment_spec.arena_env_graph_spec.ArenaEnvGraphSpec`."""

from __future__ import annotations

from enum import Enum
from numbers import Real
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from isaaclab_arena.assets.object_type import ObjectType
from isaaclab_arena.assets.registries import AssetRegistry, ObjectRelationLibraryRegistry, TaskRegistry


def _extract_asset_usd_path(asset_cls: type, **params: Any) -> str | None:
    """Return the asset's root USD path or URL, or ``None`` if not extractable."""
    class_usd = getattr(asset_cls, "usd_path", None)
    if isinstance(class_usd, str) and class_usd:
        return class_usd

    # Instantiate when usd_path is set lazily (e.g. Lightwheel backgrounds).
    # TODO(qianl): add support for embodiments, whose robot USD lives in scene_config.robot.spawn.
    try:
        instance = asset_cls(**params)
    except Exception:
        return None

    usd_path = getattr(instance, "usd_path", None)
    return str(usd_path) if usd_path else None


class AssetSpec(BaseModel):
    """One registered asset instance in an environment graph."""

    id: str = Field(
        min_length=1,
        description=(
            "Unique id for this asset instance. Use underscore-connected identifiers "
            "(e.g. 'banana', 'maple_table'). Referenced by relations and task params."
        ),
    )
    registry_name: str = Field(
        min_length=1,
        description="Exact registered asset name from EMBODIMENTS / BACKGROUNDS / OBJECTS.",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional constructor kwargs forwarded to the asset class.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_from_string_or_dict(cls, data: Any) -> Any:
        if isinstance(data, str):
            clean_id = data.split("_")[0] if "_" in data else data
            return {"id": clean_id, "registry_name": data, "params": {}}
        if isinstance(data, dict):
            reg_name = data.get("registry_name") or data.get("name") or data.get("asset_name")
            if reg_name and not data.get("id"):
                clean_id = reg_name.split("_")[0] if "_" in reg_name else reg_name
                data["id"] = clean_id
            if reg_name and not data.get("registry_name"):
                data["registry_name"] = reg_name
        return data

    @field_validator("registry_name")
    @classmethod
    def _validate_registry_name(cls, value: str) -> str:
        registry = AssetRegistry()
        assert registry.is_registered(value), f"Unknown asset registry_name '{value}'"
        return value

    def resolve_usd_path(self) -> str:
        """Return the USD path or URL for this registered asset instance."""
        asset_cls = AssetRegistry().get_asset_by_name(self.registry_name)
        usd_path = _extract_asset_usd_path(asset_cls, **self.params)
        assert usd_path, f"asset {self.registry_name!r} has no usd_path"
        return usd_path


class ObjectReferenceSpec(BaseModel):
    """USD prim reference inside a parent background asset."""

    id: str = Field(min_length=1, description="Unique node id referenced by relations and task params.")
    parent_id: str = Field(min_length=1, description="Id of the parent background asset node.")
    prim_path: str | None = Field(
        default=None,
        description="USD prim path inside the parent background; leave empty until resolved.",
    )
    object_type: ObjectType = Field(
        description=(
            "Physics type for the referenced prim. Use the first matching value:\n"
            "- articulation: door or other articulated prim in open/close door tasks\n"
            "- rigid: manipulable prim in pick-and-place tasks\n"
            "- base: static anchor prim (e.g. table surface) in is_anchor or placement relations"
        ),
    )
    params: dict[str, Any] = Field(default_factory=dict)


class TaskSpec(BaseModel):
    """Atomic registered task leaf referenced by a composite root task."""

    kind: str = Field(
        min_length=1,
        description=(
            "Registered task class name from the TASKS block in the user message "
            "(e.g. 'PickAndPlaceTask', 'OpenDoorTask'). Must match TaskRegistry exactly."
        ),
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Constructor kwargs for the task (listed in TASKS). Each object param must "
            "name exactly one asset or object-reference node id."
        ),
    )

    @field_validator("kind")
    @classmethod
    def _validate_registered_task_type(cls, value: str) -> str:
        assert TaskRegistry().is_registered(value), f"Unknown task kind '{value}'"
        return value


class TaskCompositionType(str, Enum):
    """How atomic subtasks combine in a composite root task."""

    ATOMIC = "atomic"
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


class CompositeTaskSpec(BaseModel):
    """Root task node for an environment graph."""

    composition: TaskCompositionType = Field(
        description="How the subtasks combine: " + ", ".join([f"'{e.value}'" for e in TaskCompositionType])
    )
    description: str = Field(
        min_length=1,
        description="Natural-language summary of the overall task (e.g. 'pick and place all bananas into the bin').",
    )
    subtasks: list[TaskSpec] = Field(
        default_factory=list,
        description="Atomic registered tasks that compose this root task.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_task_structure(cls, data: Any) -> Any:
        if isinstance(data, dict):
            normalized = dict(data)
            # Handle flat or legacy task representations
            if ("task_type" in normalized or "kind" in normalized) and "subtasks" not in normalized:
                task_kind = normalized.get("task_type") or normalized.get("kind")
                task_params = normalized.get("params", {})
                desc = normalized.get("description", f"Execute {task_kind}")
                return {
                    "composition": "atomic",
                    "description": desc,
                    "subtasks": [{"kind": task_kind, "params": task_params}],
                }
            if "subtasks" in normalized:
                if "composition" not in normalized:
                    normalized["composition"] = "atomic" if len(normalized["subtasks"]) == 1 else "sequential"
                if "description" not in normalized or not normalized["description"]:
                    normalized["description"] = "Execute tasks"
            return normalized
        return data

    @model_validator(mode="after")
    def _validate_composition_task_count(self) -> CompositeTaskSpec:
        if self.composition is TaskCompositionType.ATOMIC:
            assert len(self.subtasks) == 1, "composition 'atomic' requires exactly one atomic task"
        else:
            assert (
                len(self.subtasks) >= 2
            ), f"composition '{self.composition.value}' requires at least two atomic tasks, got {len(self.subtasks)}"
        return self


class SpatialRelationSpec(BaseModel):
    """Spatial relation in an environment graph."""

    kind: str = Field(
        min_length=1,
        description=(
            "Relation name from the RELATIONS block in the user message "
            "(e.g. 'on', 'next_to', 'is_anchor'). Must match a registered relation exactly."
        ),
    )
    subject: str = Field(
        min_length=1,
        description=(
            "Node id this relation applies to. For binary relations (e.g. 'on'), it's the "
            "object placed relative to ``reference``. For unary relations (e.g. "
            "'is_anchor', 'position_limits'), it's the anchored or constrained object."
        ),
    )
    reference: str | None = Field(
        default=None,
        description=(
            "Reference node id for binary relations only — e.g. for 'on', the surface "
            "the subject rests on. Must be null for unary relations."
        ),
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional kind-specific parameters; leave empty by default.",
    )

    @model_validator(mode="after")
    def _validate_kind_and_arity(self) -> SpatialRelationSpec:
        registry = ObjectRelationLibraryRegistry()
        assert registry.is_registered(self.kind), f"Unknown relation kind '{self.kind}'"
        relation_cls = registry.get_object_relation_by_name(self.kind)
        if relation_cls.is_unary():
            assert self.reference is None, f"Relation kind '{self.kind}' must not define relation.reference"
        else:
            assert self.reference is not None, f"Relation kind '{self.kind}' requires relation.reference"
        self.params = _normalize_relation_params(self.params)
        return self


def _normalize_relation_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    if "position_xyz" in normalized:
        normalized["position_xyz"] = _convert_to_float_tuple(normalized["position_xyz"], 3, "position_xyz")
    if "rotation_xyzw" in normalized:
        normalized["rotation_xyzw"] = _convert_to_float_tuple(normalized["rotation_xyzw"], 4, "rotation_xyzw")
    return normalized


def _convert_to_float_tuple(value: Any, length: int, field_name: str) -> tuple[float, ...]:
    """Coerce a fixed-length numeric list or tuple (e.g. position or quaternion)."""
    assert isinstance(value, (list, tuple)), f"Field '{field_name}' must be a list or tuple of {length} numbers"
    assert len(value) == length, f"Field '{field_name}' must contain exactly {length} numbers, got {len(value)}"
    assert all(
        isinstance(item, Real) and not isinstance(item, bool) for item in value
    ), f"Field '{field_name}' must contain only numbers"
    return tuple(float(item) for item in value)


class PlacementValidatorSpec(BaseModel):
    """Per-env placement validators.

    Selects which build-time geometric checks gate object placement for this env. Defaults to
    every build-time check.
    """

    enabled_checks: list[str] | None = Field(
        default=None,
        description=(
            "Build-time check names to evaluate during placement; none runs every registered build-time "
            "check. A check not listed here is never run. Built-in names: no_overlap, on_relation, "
            "next_to, not_next_to, face_to; externally-registered validators may add more."
        ),
    )
    required_checks: list[str] | None = Field(
        default=None,
        description=(
            "Enabled checks that must pass for a layout to be valid; none requires every enabled check. "
            "Must be a subset of enabled_checks."
        ),
    )

    @model_validator(mode="after")
    def _validate_required_subset(self) -> PlacementValidatorSpec:
        if self.enabled_checks is not None and self.required_checks is not None:
            extra = set(self.required_checks) - set(self.enabled_checks)
            assert not extra, f"required_checks must be a subset of enabled_checks; unexpected: {sorted(extra)}"
        return self


class CliOverrideSpec(BaseModel):
    """One CLI flag that swaps an asset's registry name, declared in the graph YAML."""

    arg: str = Field(min_length=1)  # flag name without leading dashes; "object" -> --object
    target_node_id: str = Field(min_length=1)  # graph asset id whose registry_name the flag swaps

    @property
    def dest(self) -> str:
        """The argparse attribute name for this flag (dashes become underscores)."""
        return self.arg.replace("-", "_")


class ContinuousIntervalSpec(BaseModel):
    """Bounded continuous interval for domain randomization and tolerance gating."""

    min_val: float = Field(description="Minimum bound of the tolerance interval.")
    max_val: float = Field(description="Maximum bound of the tolerance interval.")
    nominal: float = Field(description="Nominal/mean value for deterministic execution.")

    @model_validator(mode="before")
    @classmethod
    def _coerce_interval(cls, data: Any) -> Any:
        if isinstance(data, dict):
            min_val = data.get("min_val", data.get("min", data.get("lower", -0.05)))
            max_val = data.get("max_val", data.get("max", data.get("upper", 0.05)))
            nominal = data.get("nominal", data.get("mean", (float(min_val) + float(max_val)) / 2.0))
            return {"min_val": float(min_val), "max_val": float(max_val), "nominal": float(nominal)}
        elif isinstance(data, (list, tuple)) and len(data) >= 2:
            min_val = float(data[0])
            max_val = float(data[1])
            nominal = float(data[2]) if len(data) >= 3 else (float(min_val) + float(max_val)) / 2.0
            return {"min_val": min_val, "max_val": max_val, "nominal": nominal}
        return data


class ReifiedRelationSpec(BaseModel):
    """RDF 1.2 Reified Spatial and Functional Invariant Contract."""

    reifier_id: str = Field(
        min_length=1,
        description="Unique RDF 1.2 reifier identifier (e.g. 'reifier_box_shelf').",
    )
    source_id: str = Field(
        min_length=1,
        description="Subject node id in the causal relation.",
    )
    relation_type: str = Field(
        min_length=1,
        description="Type of the reified relation (e.g. 'PLACED_ON', 'STANDS_NEAR', 'RECEPTACLE_FOR', 'OBSERVES').",
    )
    target_id: str = Field(
        min_length=1,
        description="Object node id in the causal relation.",
    )
    surface_anchor: str | None = Field(
        default=None,
        description="Introspected USD geometric patch identifier (e.g. 'shelf_patch_2').",
    )
    contact_normal: tuple[float, float, float] = Field(
        default=(0.0, 0.0, 1.0),
        description="Unit contact normal vector in world space.",
    )
    delta_x: ContinuousIntervalSpec = Field(
        default_factory=lambda: ContinuousIntervalSpec(min_val=-0.05, max_val=0.05, nominal=0.0),
        description="Relative positional offset interval along local X axis.",
    )
    delta_y: ContinuousIntervalSpec = Field(
        default_factory=lambda: ContinuousIntervalSpec(min_val=-0.05, max_val=0.05, nominal=0.0),
        description="Relative positional offset interval along local Y axis.",
    )
    delta_z: ContinuousIntervalSpec = Field(
        default_factory=lambda: ContinuousIntervalSpec(min_val=0.0, max_val=0.03, nominal=0.01),
        description="Vertical clearance offset interval along contact normal.",
    )
    required_headroom: float = Field(
        default=0.35,
        description="Minimum vertical clearance (meters) required above the contact surface.",
    )
    required_friction: float = Field(
        default=0.60,
        description="Minimum static friction coefficient required for stable contact.",
    )
    kinematic_manifold: str = Field(
        default="unitree_g1_bimanual_chest_height",
        description="Embodiment reachability manifold profile identifier.",
    )
    prior_entropy: float = Field(
        default=2.5,
        description="Prior Shannon entropy (nats) representing ungrounded spatial uncertainty.",
    )
    posterior_entropy: float = Field(
        default=0.05,
        description="Posterior Shannon entropy (nats) after geometric affordance conditioning.",
    )
    evidence_sources: list[str] = Field(
        default_factory=list,
        description="Lineage provenance IDs of sensory observations that informed this contract.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_reifier(cls, data: Any) -> Any:
        if isinstance(data, dict):
            normalized = dict(data)
            # Aliases for source_id and target_id
            if "source_id" not in normalized:
                normalized["source_id"] = normalized.get("subject") or normalized.get("source") or ""
            if "target_id" not in normalized:
                normalized["target_id"] = normalized.get("reference") or normalized.get("target") or normalized.get("object") or ""
            if "reifier_id" not in normalized or not normalized["reifier_id"]:
                src = normalized.get("source_id", "src")
                rel = str(normalized.get("relation_type", "rel")).lower()
                tgt = normalized.get("target_id", "tgt")
                normalized["reifier_id"] = f"reifier_{src}_{rel}_{tgt}"
            # Extract nested params if LLM put parameters in a 'params' sub-dict
            if "params" in normalized and isinstance(normalized["params"], dict):
                p = normalized.pop("params")
                for k in ("surface_anchor", "required_headroom", "required_friction", "kinematic_manifold", "contact_normal", "delta_x", "delta_y", "delta_z"):
                    if k in p and k not in normalized:
                        normalized[k] = p[k]
            if normalized.get("required_friction") is None:
                normalized["required_friction"] = 0.60
            if normalized.get("required_headroom") is None:
                normalized["required_headroom"] = 0.35
            return normalized
        return data

