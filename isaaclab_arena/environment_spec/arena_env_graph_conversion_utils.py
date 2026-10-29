# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from isaaclab_arena.assets.asset import Asset
from isaaclab_arena.assets.object_reference import (
    ObjectReference,
    OpenableObjectReference,
    PressableObjectReference,
    TurnableObjectReference,
)
from isaaclab_arena.assets.object_set import RigidObjectSet
from isaaclab_arena.assets.object_type import ObjectType
from isaaclab_arena.assets.registries import AssetRegistry, ObjectRelationLibraryRegistry
from isaaclab_arena.environment_spec.arena_env_graph_task_conversion_utils import build_task_from_spec
from isaaclab_arena.environment_spec.arena_env_graph_types import ObjectReferenceSpec, SpatialRelationSpec
from isaaclab_arena.relations.object_placer_params import ObjectPlacerParams
from isaaclab_arena.relations.placement_asset import PlaceableAsset
from isaaclab_arena.relations.relation_solver import RelationSolverParams
from isaaclab_arena.utils.physics_backend import PhysicsBackend
from isaaclab_arena.utils.pose import Pose
from isaaclab_arena.utils.usd.helpers import has_light, open_stage

_DEFAULT_DOME_LIGHT_ASSET_NAME = "light"
_DEFAULT_DOME_LIGHT_NODE_ID = "auto_dome_light"
_DEFAULT_DIRECTIONAL_LIGHT_ASSET_NAME = "directional_light"
_DEFAULT_DIRECTIONAL_LIGHT_NODE_ID = "auto_directional_light"
_AFFORDANCE_REFERENCE_CLASSES: dict[str, type[ObjectReference]] = {
    "openable_joint_name": OpenableObjectReference,
    "pressable_joint_name": PressableObjectReference,
    "turnable_joint_name": TurnableObjectReference,
}

if TYPE_CHECKING:
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec


def parse_asset_params(params: dict[str, Any]) -> dict[str, Any]:
    """Convert an asset's serialized initial pose without modifying its graph parameters."""
    parsed = dict(params)
    if isinstance(parsed.get("initial_pose"), dict):
        parsed["initial_pose"] = Pose.from_dict(parsed["initial_pose"])
    return parsed


def build_arena_env_from_graph_spec(graph_spec: ArenaEnvGraphSpec, enable_cameras: bool = False) -> Any:
    """Build an IsaacLabArenaEnvironment from a validated ArenaEnvGraphSpec.

    Args:
        graph_spec: A validated graph spec (asset refs exist, ids unique, etc.).
        enable_cameras: Forwarded to the embodiment so its cameras are added.
    """
    # Lazy import to avoid pxr early import causing unit test failures.
    from isaaclab_arena.environment_spec.env_cfg_override import apply_env_cfg_override
    from isaaclab_arena.environment_spec.placer_params_cfg_override import build_placer_params_from_override
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
    from isaaclab_arena.scene.scene import Scene

    assets_by_node_id = instantiate_assets_from_spec(graph_spec, AssetRegistry(), enable_cameras=enable_cameras)
    _ensure_scene_lighting(graph_spec, assets_by_node_id)
    _attach_spatial_relations_to_assets(graph_spec.relations, assets_by_node_id)
    scene_assets = [asset for node_id, asset in assets_by_node_id.items() if node_id != graph_spec.embodiment.id]
    override = graph_spec.env_cfg_override

    def _env_cfg_callback(env_cfg):
        """Force one RTX re-render after reset and apply optional env_cfg_override."""
        if getattr(env_cfg, "num_rerenders_on_reset", 0) < 1:
            env_cfg.num_rerenders_on_reset = 1
        if override is not None:
            env_cfg = apply_env_cfg_override(env_cfg, override=override)
        return env_cfg

    default_physics_backend = (
        graph_spec.default_physics_backend if graph_spec.default_physics_backend is not None else PhysicsBackend.PHYSX
    )
    if graph_spec.placer_params is not None:
        placer_params = build_placer_params_from_override(graph_spec.placer_params)
    elif graph_spec.placement_validators is not None:
        placer_params = build_checks_for_placer_params(graph_spec)
    else:
        placer_params = build_placer_params_from_override(None)

    return IsaacLabArenaEnvironment(
        name=graph_spec.env_name,
        scene=Scene(assets=scene_assets),
        embodiment=assets_by_node_id[graph_spec.embodiment.id],
        task=build_task_from_spec(graph_spec.task, assets_by_node_id),
        placer_params=placer_params,
        env_cfg_callback=_env_cfg_callback,
        default_physics_backend=default_physics_backend,
    )


def build_checks_for_placer_params(graph_spec: ArenaEnvGraphSpec) -> ObjectPlacerParams:
    """Build placement params defining what checks to run during layout validation for this env."""
    placement_validators = graph_spec.placement_validators
    enabled_checks = placement_validators.enabled_checks if placement_validators is not None else None
    required_checks = placement_validators.required_checks if placement_validators is not None else None

    return ObjectPlacerParams(
        enabled_checks=set(enabled_checks) if enabled_checks is not None else None,
        required_checks=set(required_checks) if required_checks is not None else None,
        solver_params=RelationSolverParams(verbose=False, save_position_history=False),
    )


def _ensure_scene_lighting(graph_spec: ArenaEnvGraphSpec, assets_by_node_id: dict[str, Any]) -> None:
    """Inject default lighting setup, if no lighting already exists.

    Injects:
    - dome light
    - directional light (default turned off). For lighting variations to act on.
    """
    if _scene_already_has_light(graph_spec, assets_by_node_id):
        return

    dome_node_id = _unique_node_id(set(assets_by_node_id), _DEFAULT_DOME_LIGHT_NODE_ID)
    dome_light = AssetRegistry().get_asset_by_name(_DEFAULT_DOME_LIGHT_ASSET_NAME)()
    assets_by_node_id[dome_node_id] = dome_light

    directional_node_id = _unique_node_id(set(assets_by_node_id), _DEFAULT_DIRECTIONAL_LIGHT_NODE_ID)
    directional_light = AssetRegistry().get_asset_by_name(_DEFAULT_DIRECTIONAL_LIGHT_ASSET_NAME)()
    directional_light.off()  # a lighting-direction variation turns it back on at build time
    # Let the direction variation dim this dome when it activates, so shadows show.
    directional_light.set_dome_light(dome_light)
    assets_by_node_id[directional_node_id] = directional_light

    print(
        f"INFO: no light found in scene or background USD(s); injected default light '{dome_node_id}'"
        f" and directional light '{directional_node_id}'"
        " (off unless a lighting-direction variation activates it)."
    )


def _unique_node_id(existing_ids: set[str], base: str) -> str:
    """Return the first non-colliding id from ``base``, ``base_1``, ``base_2``, ... given ``existing_ids``."""
    if base not in existing_ids:
        return base
    suffix = 1
    while f"{base}_{suffix}" in existing_ids:
        suffix += 1
    return f"{base}_{suffix}"


def _scene_already_has_light(graph_spec: ArenaEnvGraphSpec, assets_by_node_id: dict[str, Any]) -> bool:
    """Return whether the scene is already lit, either explicitly or via a baked-in USD light."""
    if any("light" in (getattr(asset, "tags", None) or []) for asset in assets_by_node_id.values()):
        return True
    for asset_spec in [graph_spec.background, *graph_spec.objects]:
        asset = assets_by_node_id[asset_spec.id]
        usd_path = getattr(asset, "usd_path", None)
        if usd_path is not None and getattr(asset, "spawner_cfg", None) is None:
            with open_stage(usd_path) as stage:
                if has_light(stage):
                    return True
    return False


def _prim_path_for_relative(parent_prim_path: str, prim_path: str) -> str:
    """Expand a relative prim suffix to the Isaac Lab runtime prim path."""
    if prim_path.startswith("{ENV_REGEX_NS}/"):
        return prim_path
    stripped = prim_path.lstrip("/")
    if not stripped:
        return parent_prim_path
    return f"{parent_prim_path}/{stripped}"


def _parse_pose_data(pose_data: Any) -> Pose | None:
    """Parse raw dictionary or Pose object into a typed Pose."""
    if isinstance(pose_data, dict):
        pos = tuple(pose_data.get("position_xyz", [0.0, 0.0, 0.0]))
        rot = tuple(pose_data.get("rotation_xyzw", [0.0, 0.0, 0.0, 1.0]))
        return Pose(position_xyz=pos, rotation_xyzw=rot)
    elif isinstance(pose_data, Pose):
        return pose_data
    return None


def _instantiate_object_reference(
    ref: ObjectReferenceSpec,
    parent_asset: Asset,
) -> ObjectReference:
    """Instantiate a plain or affordance-specific object reference."""
    assert ref.prim_path is not None, "Object reference must have a prim path"
    joint_param_names = [name for name in _AFFORDANCE_REFERENCE_CLASSES if name in ref.params]
    assert len(joint_param_names) <= 1, f"Object reference '{ref.id}' cannot expose multiple affordances"

    common_kwargs = {
        "name": ref.id,
        "prim_path": _prim_path_for_relative(parent_asset.get_prim_path(), ref.prim_path),
        "parent_asset": parent_asset,
        **parse_asset_params(ref.params),
    }
    if not joint_param_names:
        return ObjectReference(object_type=ref.object_type, **common_kwargs)

    # Affordance references always set object_type=ARTICULATION; omit the YAML value.
    assert ref.object_type == ObjectType.ARTICULATION, (
        f"Object reference '{ref.id}' sets {joint_param_names[0]}, so it must use"
        f" object_type=articulation, got {ref.object_type}"
    )
    return _AFFORDANCE_REFERENCE_CLASSES[joint_param_names[0]](**common_kwargs)


def instantiate_assets_from_spec(
    graph_spec: ArenaEnvGraphSpec, asset_registry: Any, enable_cameras: bool = False
) -> dict[str, PlaceableAsset]:
    """Return ``{asset.id: live_asset}`` after materializing the typed graph spec."""
    assets_by_node_id: dict[str, PlaceableAsset] = {}

    embodiment_params = parse_asset_params(graph_spec.embodiment.params)
    if enable_cameras:
        embodiment_params.setdefault("enable_cameras", True)
    emb_pose_data = embodiment_params.pop("initial_pose", None)
    if emb_pose_data is not None:
        parsed_emb_pose = _parse_pose_data(emb_pose_data)
        if parsed_emb_pose is not None:
            embodiment_params["initial_pose"] = parsed_emb_pose
    initial_joint_pos = embodiment_params.pop("initial_joint_pos", None)
    finger_friction_params = embodiment_params.pop("finger_contact_friction", None)
    embodiment_instance = asset_registry.get_asset_by_name(graph_spec.embodiment.registry_name)(**embodiment_params)
    if initial_joint_pos is not None and hasattr(embodiment_instance, "set_joint_initial_pos"):
        embodiment_instance.set_joint_initial_pos(initial_joint_pos)
    if finger_friction_params is not None and hasattr(embodiment_instance, "set_finger_contact_friction"):
        embodiment_instance.set_finger_contact_friction(**finger_friction_params)
    assets_by_node_id[graph_spec.embodiment.id] = embodiment_instance

    bg_params = parse_asset_params(graph_spec.background.params)
    assets_by_node_id[graph_spec.background.id] = asset_registry.get_asset_by_name(graph_spec.background.registry_name)(
        **bg_params
    )

    for obj in graph_spec.objects:
        params = parse_asset_params(obj.params)
        params.setdefault("instance_name", obj.id)
        initial_pose_data = params.pop("initial_pose", None)
        asset_instance = asset_registry.get_asset_by_name(obj.registry_name)(**params)
        parsed_obj_pose = _parse_pose_data(initial_pose_data)
        is_anchor_obj = any(r.kind == "is_anchor" and r.subject == obj.id for r in graph_spec.relations)
        has_relations = any(r.subject == obj.id and r.kind != "is_anchor" for r in graph_spec.relations)
        if (
            parsed_obj_pose is not None
            and (is_anchor_obj or not has_relations)
            and hasattr(asset_instance, "set_initial_pose")
        ):
            asset_instance.set_initial_pose(parsed_obj_pose)
        assets_by_node_id[obj.id] = asset_instance

    for object_set in graph_spec.object_sets or []:
        assets_by_node_id[object_set.id] = RigidObjectSet(
            name=object_set.id,
            objects=[asset_registry.get_asset_by_name(registry_name)() for registry_name in object_set.members],
            random_choice=object_set.random_choice,
            **parse_asset_params(object_set.params),
        )

    for ref in graph_spec.object_references or []:
        assets_by_node_id[ref.id] = _instantiate_object_reference(
            ref,
            parent_asset=assets_by_node_id[ref.parent_id],
        )

    return assets_by_node_id


def _attach_spatial_relations_to_assets(
    relations: list[SpatialRelationSpec], assets_by_node_id: dict[str, PlaceableAsset]
) -> None:
    """Attach one Relation per spatial relation to the asset(s) it targets, in place."""
    import inspect

    for relation in relations:
        subject_asset = assets_by_node_id[relation.subject]
        relation_class = ObjectRelationLibraryRegistry().get_object_relation_by_name(relation.kind)
        params = dict(relation.params or {})

        # Unpack vector position parameters (e.g. pos: [x, y, z]) into x, y, z kwargs for AtPosition
        for pos_key in ("pos", "position", "xyz", "position_xyz"):
            if pos_key in params and isinstance(params[pos_key], (list, tuple)) and len(params[pos_key]) >= 3:
                coords = params[pos_key]
                if "x" not in params:
                    params["x"] = float(coords[0])
                if "y" not in params:
                    params["y"] = float(coords[1])
                if "z" not in params:
                    params["z"] = float(coords[2])
                break

        sig = inspect.signature(relation_class.__init__)
        valid_kwargs = {k: v for k, v in params.items() if k in sig.parameters}
        if relation_class.is_unary():
            subject_asset.add_relation(relation_class(**valid_kwargs))
            if relation.kind == "is_anchor" and subject_asset.get_initial_pose() is None:
                subject_asset.set_initial_pose(Pose.identity())
        else:
            reference_asset = assets_by_node_id[relation.reference]
            subject_asset.add_relation(relation_class(reference_asset, **valid_kwargs))
            if "surface_sector" in valid_kwargs or "surface_anchor" in valid_kwargs:
                from isaaclab_arena.relations.relations import RandomAroundSolution, get_relation

                if get_relation(subject_asset, RandomAroundSolution) is None:
                    subject_asset.add_relation(RandomAroundSolution(x_half_m=0.03, y_half_m=0.03))
