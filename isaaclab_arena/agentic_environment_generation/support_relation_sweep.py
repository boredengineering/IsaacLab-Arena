# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Generates a family of scene variants that differ only in one support relation.

The question this exists to answer is whether a policy's competence depends on where a support
surface sits relative to the robot. Answering it requires scenes that differ in *that relation and
nothing else* -- same fixture, same laterality, same prompt, same scales, same friction. A float
bolted onto one environment class would produce such scenes for exactly one environment; a
relational edit produces them for any scene the graph can express.

One intervention, three physical realisations:

* ``anchor``   -- re-select the ``surface_sector`` naming a different declared deck on the same
  fixture. Physically and visually correct, but only available where the fixture declares decks.
* ``fixture``  -- translate the whole support fixture in Z. Always available; a table's legs will
  float above the floor.
* ``platform`` -- translate the embodiment in Z instead. Equivalent in the relation, and plausible
  if the robot is understood to stand on a platform.

The realisation is recorded on each variant, because it is a plausibility choice rather than a
semantic one and a later reader needs to know which was used.

A requested offset that no realisation can support is **skipped with a reason**, never emitted.
Setting ``nominal_height`` alone would move the placement target without putting a surface under
it, so the object would spawn in mid-air and fall -- measuring gravity rather than reach.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from isaaclab_arena.agentic_environment_generation.policy_capability_graph import (
    frame_height,
    resolve_manifold_for_offset,
)

# A declared deck counts as satisfying a requested offset when it lands within this distance.
ANCHOR_MATCH_TOLERANCE_M = 0.08


@dataclass
class SweepVariant:
    """One emitted scene variant, or one refusal, with the reasoning attached."""

    requested_offset_m: float
    realization: str
    spec_dict: dict[str, Any] | None
    achieved_offset_m: float | None = None
    anchor_name: str | None = None
    manifold: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def emitted(self) -> bool:
        """Whether a usable variant was produced for this offset."""
        return self.spec_dict is not None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable summary, excluding the spec body."""
        return {
            "requested_offset_m": round(self.requested_offset_m, 4),
            "achieved_offset_m": round(self.achieved_offset_m, 4) if self.achieved_offset_m is not None else None,
            "realization": self.realization,
            "anchor_name": self.anchor_name,
            "manifold": self.manifold,
            "emitted": self.emitted,
            "notes": list(self.notes),
        }


def _on_relation_dict(spec_dict: dict[str, Any], subject_id: str) -> dict[str, Any] | None:
    """Return the mutable ``on`` relation dict for ``subject_id``."""
    for relation in spec_dict.get("relations", []) or []:
        if relation.get("kind") == "on" and relation.get("subject") == subject_id:
            return relation
    return None


def _manipuland_id(spec_dict: dict[str, Any]) -> str | None:
    """Return the first object that is not receptacle-shaped, matching the capability graph."""
    from isaaclab_arena.agentic_environment_generation.policy_capability_graph import _RECEPTACLE_TOKENS

    for obj in spec_dict.get("objects", []) or []:
        name = f"{obj.get('id', '')} {obj.get('registry_name', '')}".lower()
        if not any(token in name for token in _RECEPTACLE_TOKENS):
            return obj.get("id")
    return None


def _initial_pose(node: dict[str, Any]) -> dict[str, Any]:
    """Return the node's mutable ``initial_pose`` dict, creating it if absent."""
    params = node.setdefault("params", {})
    pose = params.setdefault("initial_pose", {})
    pose.setdefault("position_xyz", [0.0, 0.0, 0.0])
    pose.setdefault("rotation_xyzw", [0.0, 0.0, 0.0, 1.0])
    return pose


def _declared_decks(fixture_registry_name: str) -> dict[str, float]:
    """Return ``{sector_name: deck_z}`` for a fixture's declared, non-inherited decks."""
    try:
        from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
            FIXTURE_SECTOR_BOUNDS,
        )
    except ImportError:
        return {}

    fixture_lower = (fixture_registry_name or "").lower()
    for fixture_key, sectors in FIXTURE_SECTOR_BOUNDS.items():
        if fixture_key in fixture_lower:
            # A deck z of exactly 0.0 means "inherit the fixture surface", which cannot be
            # positioned deliberately, so it is not a sweep target.
            return {name: float(b[4]) for name, b in sectors.items() if b[4] != 0.0}
    return {}


def _record_on_reified(spec_dict: dict[str, Any], subject_id: str, note: str, manifold: str | None) -> None:
    """Annotate the subject's reified PLACED_ON relation so the sweep is reconstructable."""
    for relation in spec_dict.get("reified_relations") or []:
        if relation.get("source_id") == subject_id and "PLACED_ON" in (relation.get("relation_type") or ""):
            sources = relation.setdefault("evidence_sources", [])
            if note not in sources:
                sources.append(note)
            if manifold:
                relation["kinematic_manifold"] = manifold


def generate_support_height_sweep_dicts(
    base_spec_dict: dict[str, Any],
    offsets_m: Sequence[float],
    realization: str = "auto",
    embodiment_frame: str = "pelvis",
    env_name_suffix: str = "support_sweep",
) -> list[SweepVariant]:
    """Emit one scene-dict variant per requested support-relation offset.

    Operates on plain dicts so it can run without the simulator; see
    ``generate_support_height_sweep`` for the typed-spec wrapper.

    Args:
        base_spec_dict: The scene to derive from, as ``ArenaEnvGraphSpec.to_dict()`` output.
        offsets_m: Requested support heights relative to ``embodiment_frame``.
        realization: ``anchor``, ``fixture``, ``platform``, or ``auto`` (anchor when a declared deck
            is within tolerance, fixture translation otherwise).
        embodiment_frame: Frame the offsets are measured against.
        env_name_suffix: Appended to ``env_name`` so variants do not collide with the base scene.

    Returns:
        One ``SweepVariant`` per requested offset, in order. A variant whose offset cannot be
        physically supported carries ``spec_dict=None`` and an explanatory note rather than an
        unsupported scene.
    """
    assert realization in ("anchor", "fixture", "platform", "auto"), f"unknown realization {realization!r}"

    manipuland = _manipuland_id(base_spec_dict)
    embodiment = base_spec_dict.get("embodiment")
    background = base_spec_dict.get("background")
    variants: list[SweepVariant] = []

    if manipuland is None or embodiment is None:
        return [
            SweepVariant(
                requested_offset_m=offset,
                realization=realization,
                spec_dict=None,
                notes=["spec declares no manipuland or no embodiment; nothing to relate"],
            )
            for offset in offsets_m
        ]

    base_relation = _on_relation_dict(base_spec_dict, manipuland)
    fixture_id = (base_relation or {}).get("reference")
    fixture_node = background if (background or {}).get("id") == fixture_id else None
    if fixture_node is None:
        fixture_node = next((o for o in base_spec_dict.get("objects", []) if o.get("id") == fixture_id), None)

    fixture_registry = (fixture_node or {}).get("registry_name", "")
    fixture_pos = ((fixture_node or {}).get("params", {}).get("initial_pose", {}) or {}).get(
        "position_xyz", [0.0, 0.0, 0.0]
    )
    base_pos = (embodiment.get("params", {}).get("initial_pose", {}) or {}).get("position_xyz", [0.0, 0.0, 0.0])
    base_frame_z = frame_height(list(base_pos), embodiment_frame)
    decks = _declared_decks(fixture_registry)
    base_params = (base_relation or {}).get("params", {}) or {}
    base_sector = base_params.get("surface_sector") or base_params.get("surface_anchor")

    for offset in offsets_m:
        target_surface_z = base_frame_z + offset
        chosen = realization
        notes: list[str] = []

        best_anchor: str | None = None
        if realization in ("anchor", "auto") and decks:
            best_anchor = _closest_deck(decks, target_surface_z, fixture_pos[2], base_sector)
            gap = abs(decks[best_anchor] + fixture_pos[2] - target_surface_z)
            if gap > ANCHOR_MATCH_TOLERANCE_M:
                notes.append(
                    f"nearest declared deck '{best_anchor}' is {gap:.3f} m from the requested offset "
                    f"(tolerance {ANCHOR_MATCH_TOLERANCE_M:.2f} m)"
                )
                best_anchor = None

        if realization == "auto":
            chosen = "anchor" if best_anchor else "fixture"
        if realization == "anchor" and best_anchor is None:
            variants.append(
                SweepVariant(
                    requested_offset_m=offset,
                    realization="anchor",
                    spec_dict=None,
                    notes=notes
                    + [
                        "refusing to emit: no declared deck at this offset, so an anchor re-selection "
                        "cannot put a real surface here"
                    ],
                )
            )
            continue

        variant = copy.deepcopy(base_spec_dict)
        variant["env_name"] = f"{base_spec_dict.get('env_name', 'scene')}_{env_name_suffix}"
        relation = _on_relation_dict(variant, manipuland)
        if relation is None:
            variants.append(
                SweepVariant(
                    requested_offset_m=offset,
                    realization=chosen,
                    spec_dict=None,
                    notes=["spec declares no 'on' relation for the manipuland; nothing to sweep"],
                )
            )
            continue

        achieved: float
        anchor_used: str | None = None
        if chosen == "anchor":
            relation.setdefault("params", {})["surface_sector"] = best_anchor
            anchor_used = best_anchor
            achieved = decks[best_anchor] + fixture_pos[2] - base_frame_z
            notes.append(f"selected declared deck '{best_anchor}' at z={decks[best_anchor]:+.3f}")
        elif chosen == "fixture":
            if fixture_node is None:
                variants.append(
                    SweepVariant(
                        requested_offset_m=offset,
                        realization=chosen,
                        spec_dict=None,
                        notes=["support fixture not found in the spec; cannot translate it"],
                    )
                )
                continue
            # Resolve the fixture in the *variant* so the edit is not applied to the base spec.
            variant_fixture = (
                variant["background"]
                if (variant.get("background") or {}).get("id") == fixture_id
                else next(o for o in variant["objects"] if o.get("id") == fixture_id)
            )
            current_surface_z = _current_surface_z(relation, decks, fixture_pos)
            if current_surface_z is None:
                variants.append(
                    SweepVariant(
                        requested_offset_m=offset,
                        realization=chosen,
                        spec_dict=None,
                        notes=notes
                        + [
                            "refusing to emit: the base spec's support height is undetermined, so a "
                            "translation delta cannot be computed without guessing"
                        ],
                    )
                )
                continue
            delta = target_surface_z - current_surface_z
            pose = _initial_pose(variant_fixture)
            pose["position_xyz"] = list(pose["position_xyz"])
            pose["position_xyz"][2] = float(pose["position_xyz"][2]) + delta
            achieved = offset
            notes.append(f"translated fixture '{fixture_id}' by {delta:+.3f} m in Z")
        else:  # platform
            current_surface_z = _current_surface_z(relation, decks, fixture_pos)
            if current_surface_z is None:
                variants.append(
                    SweepVariant(
                        requested_offset_m=offset,
                        realization=chosen,
                        spec_dict=None,
                        notes=notes + ["refusing to emit: base support height undetermined"],
                    )
                )
                continue
            # Moving the robot down raises the support relative to it, hence the sign.
            delta = (current_surface_z - offset) - base_frame_z
            pose = _initial_pose(variant["embodiment"])
            pose["position_xyz"] = list(pose["position_xyz"])
            pose["position_xyz"][2] = float(pose["position_xyz"][2]) + delta
            achieved = offset
            notes.append(
                f"translated embodiment by {delta:+.3f} m in Z; a platform must be added under it "
                f"for the scene to be physically plausible"
            )

        manifold = resolve_manifold_for_offset(achieved)
        _record_on_reified(
            variant,
            manipuland,
            f"support_relation_sweep:{chosen}:offset={achieved:+.3f}",
            manifold,
        )
        variants.append(
            SweepVariant(
                requested_offset_m=offset,
                realization=chosen,
                spec_dict=variant,
                achieved_offset_m=achieved,
                anchor_name=anchor_used,
                manifold=manifold,
                notes=notes,
            )
        )

    return variants


def _sector_family(sector_name: str | None) -> str:
    """Return a sector name with its trailing index stripped, e.g. ``shelf_tier_1`` -> ``shelf_tier``."""
    if not sector_name:
        return ""
    return sector_name.rstrip("_0123456789")


def _closest_deck(
    decks: dict[str, float],
    target_surface_z: float,
    fixture_z: float,
    base_sector: str | None,
) -> str:
    """Return the declared deck nearest ``target_surface_z``, preferring the base spec's family.

    Several sectors on one fixture commonly share a deck height while differing in their lateral
    bounds -- ``galileo_locomanip`` declares ``front_center``, ``front_left``, ``front_right`` and
    ``shelf_tier_1`` all at the same z. Picking arbitrarily among them would change the lateral
    sector as a side effect of a height sweep, confounding the very contrast the sweep exists to
    isolate. Ties therefore resolve toward the family already declared in the base spec, then
    alphabetically for determinism.
    """
    family = _sector_family(base_sector)

    def sort_key(name: str) -> tuple[float, int, str]:
        distance = abs(decks[name] + fixture_z - target_surface_z)
        same_family = 0 if (family and _sector_family(name) == family) else 1
        # Round the distance so heights that are equal in practice compare as ties.
        return (round(distance, 6), same_family, name)

    return min(decks, key=sort_key)


def _current_surface_z(
    relation: dict[str, Any], decks: dict[str, float], fixture_pos: Sequence[float]
) -> float | None:
    """Return the base spec's support surface z, or None when the spec does not determine it."""
    params = relation.get("params", {}) or {}
    if params.get("nominal_height") is not None:
        return float(params["nominal_height"])
    sector = params.get("surface_sector") or params.get("surface_anchor")
    if sector and sector in decks:
        return decks[sector] + float(fixture_pos[2])
    return None


def generate_support_height_sweep(
    base_spec: Any,
    offsets_m: Sequence[float],
    realization: str = "auto",
    embodiment_frame: str = "pelvis",
) -> list[tuple[SweepVariant, Any]]:
    """Typed wrapper: emit ``(variant, ArenaEnvGraphSpec)`` pairs for each supported offset.

    Refused offsets are returned with a ``None`` spec so the caller can report them rather than
    silently getting a shorter list than it asked for.
    """
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    variants = generate_support_height_sweep_dicts(
        base_spec.to_dict(), offsets_m, realization=realization, embodiment_frame=embodiment_frame
    )
    return [(v, ArenaEnvGraphSpec.from_dict(v.spec_dict) if v.emitted else None) for v in variants]


def main() -> int:
    """CLI entry point: write the sweep as versioned environment snapshots."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base_spec", required=True, help="Graph spec YAML to derive variants from.")
    parser.add_argument(
        "--offsets",
        type=float,
        nargs="+",
        default=None,
        help="Support offsets relative to --frame, in metres. Mutually exclusive with --anchors.",
    )
    parser.add_argument(
        "--anchors",
        nargs="+",
        default=None,
        help="Declared sector names to sweep instead of numeric offsets (e.g. shelf_tier_1 ...).",
    )
    parser.add_argument("--realization", choices=("anchor", "fixture", "platform", "auto"), default="auto")
    parser.add_argument("--frame", choices=("pelvis", "shoulder", "base"), default="pelvis")
    parser.add_argument("--policy_config", default=None, help="Policy config YAML to snapshot alongside.")
    parser.add_argument("--dry_run", action="store_true", help="Report the plan without writing versions.")
    args = parser.parse_args()

    from isaaclab_arena.agentic_environment_generation.policy_capability_graph import frame_height as _fh
    from isaaclab_arena.agentic_environment_generation.version_manager import EnvironmentVersionManager
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    base = ArenaEnvGraphSpec.from_yaml(Path(args.base_spec))
    spec_dict = base.to_dict()

    offsets = args.offsets
    if args.anchors:
        # Translate anchor names into the offsets they represent, so both routes share one code path.
        manipuland = _manipuland_id(spec_dict)
        relation = _on_relation_dict(spec_dict, manipuland) if manipuland else None
        fixture_id = (relation or {}).get("reference")
        fixture = (
            spec_dict["background"]
            if (spec_dict.get("background") or {}).get("id") == fixture_id
            else next((o for o in spec_dict.get("objects", []) if o.get("id") == fixture_id), None)
        )
        decks = _declared_decks((fixture or {}).get("registry_name", ""))
        base_pos = (spec_dict["embodiment"].get("params", {}).get("initial_pose", {}) or {}).get(
            "position_xyz", [0.0, 0.0, 0.0]
        )
        frame_z = _fh(list(base_pos), args.frame)
        fixture_z = ((fixture or {}).get("params", {}).get("initial_pose", {}) or {}).get(
            "position_xyz", [0.0, 0.0, 0.0]
        )[2]
        missing = [a for a in args.anchors if a not in decks]
        assert not missing, f"fixture declares no deck named {missing}; known: {sorted(decks)}"
        offsets = [decks[a] + fixture_z - frame_z for a in args.anchors]
        print(f"[sweep] anchors {args.anchors} -> offsets {[round(o, 4) for o in offsets]} rel {args.frame}")

    assert offsets, "provide --offsets or --anchors"

    variants = generate_support_height_sweep_dicts(
        spec_dict, offsets, realization=args.realization, embodiment_frame=args.frame
    )

    for variant in variants:
        status = "OK  " if variant.emitted else "SKIP"
        print(
            f"[sweep] {status} offset={variant.requested_offset_m:+.3f} "
            f"realization={variant.realization} manifold={variant.manifold} "
            f"{'; '.join(variant.notes)}"
        )

    emitted = [v for v in variants if v.emitted]
    if args.dry_run or not emitted:
        print(f"[sweep] {len(emitted)}/{len(variants)} variants supported; nothing written (dry run).")
        return 0

    manager = EnvironmentVersionManager(f"{base.env_name}_support_sweep")
    for variant in emitted:
        spec = ArenaEnvGraphSpec.from_dict(variant.spec_dict)
        version, _dir = manager.create_version(
            spec_source=spec,
            policy_config_source=args.policy_config,
            trigger="support_relation_sweep",
            remediations=[
                f"support offset {variant.achieved_offset_m:+.3f} m rel {args.frame} "
                f"via {variant.realization}"
                + (f" (anchor {variant.anchor_name})" if variant.anchor_name else "")
            ],
            diagnostics=variant.notes,
        )
        print(f"[sweep] wrote v{version}: offset={variant.achieved_offset_m:+.3f} manifold={variant.manifold}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
