# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Deterministic analytical swept-volume and surface-sector clearance solver (Pass 3c).

Computes 2D/3D revolute annular wedges (W_revolute), prismatic linear stroke OBB corridors
(V_prismatic), discrete surface sector admissibility masks, cavity headroom, and dual-door
non-collision invariants prior to physics simulation launch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RevoluteSweptManifold:
    """Analytical 2D/3D swept annular sector for a revolute hinge door."""

    hinge_xy: tuple[float, float]
    inner_radius_m: float
    outer_radius_m: float
    angle_start_rad: float
    angle_end_rad: float
    z_min_m: float = 0.0
    z_max_m: float = 0.50


@dataclass(frozen=True)
class PrismaticStrokeCorridor:
    """Oriented 3D bounding box (OBB) prism for a linear sliding drawer or rack."""

    center_xy: tuple[float, float]
    yaw_rad: float
    half_extents_xy: tuple[float, float]
    stroke_length_m: float
    slide_dir_xy: tuple[float, float]
    z_min_m: float = 0.0
    z_max_m: float = 0.90


@dataclass(frozen=True)
class SurfaceSectorSpec:
    """Discrete planar surface sector on a grounded supporting fixture deck."""

    name: str
    center_xy: tuple[float, float]
    yaw_rad: float
    half_extents_xy: tuple[float, float]
    deck_z_m: float


def normalize_angle(angle_rad: float) -> float:
    """Normalize an angle in radians to the interval [-pi, pi]."""
    return math.atan2(math.sin(angle_rad), math.cos(angle_rad))


def _angle_in_sweep(angle: float, start: float, end: float) -> bool:
    """Return True if angle lies within the counter-clockwise sweep from start to end."""
    a = normalize_angle(angle)
    s = normalize_angle(start)
    e = normalize_angle(end)
    if s > e:
        s, e = e, s
    span = e - s
    if span > math.pi:
        return a >= e or a <= s
    return s <= a <= e


def check_2d_obb_clearance(
    pos_a: tuple[float, float] | list[float],
    yaw_a: float,
    half_extents_a: tuple[float, float],
    pos_b: tuple[float, float] | list[float],
    yaw_b: float,
    half_extents_b: tuple[float, float],
    margin: float = 0.05,
) -> tuple[bool, float, str]:
    """Compute 2D Separating Axis Theorem (SAT) clearance between two oriented bounding boxes.

    Args:
        pos_a: World (x, y) center of OBB A.
        yaw_a: Yaw orientation of OBB A in radians.
        half_extents_a: (half_length_x, half_width_y) of OBB A in its local frame.
        pos_b: World (x, y) center of OBB B.
        yaw_b: Yaw orientation of OBB B in radians.
        half_extents_b: (half_length_x, half_width_y) of OBB B in its local frame.
        margin: Minimum required clearance in meters.

    Returns:
        Tuple of (is_clear, clearance_beyond_margin, diagnostic_message).
    """
    dx = float(pos_b[0]) - float(pos_a[0])
    dy = float(pos_b[1]) - float(pos_a[1])

    cos_a, sin_a = math.cos(yaw_a), math.sin(yaw_a)
    ax1 = (cos_a, sin_a)
    ax2 = (-sin_a, cos_a)

    cos_b, sin_b = math.cos(yaw_b), math.sin(yaw_b)
    bx1 = (cos_b, sin_b)
    bx2 = (-sin_b, cos_b)

    axes = [ax1, ax2, bx1, bx2]
    clearances: list[float] = []

    for ux, uy in axes:
        dist = abs(dx * ux + dy * uy)
        ra = half_extents_a[0] * abs(ax1[0] * ux + ax1[1] * uy) + half_extents_a[1] * abs(ax2[0] * ux + ax2[1] * uy)
        rb = half_extents_b[0] * abs(bx1[0] * ux + bx1[1] * uy) + half_extents_b[1] * abs(bx2[0] * ux + bx2[1] * uy)
        clearances.append(dist - (ra + rb + margin))

    best_clearance = max(clearances)
    if best_clearance >= 0.0:
        return True, best_clearance + margin, "2D OBB SAT clearance verified."
    return (
        False,
        best_clearance,
        f"2D OBB footprints violate margin {margin:.2f}m (deficit: {-best_clearance:.3f}m).",
    )


def compute_revolute_swept_manifold(
    base_pos: tuple[float, float] | list[float],
    base_yaw_rad: float,
    hinge_offset_local: tuple[float, float] = (-0.10, -0.15),
    door_radius_m: float = 0.35,
    swing_span_rad: tuple[float, float] = (0.0, math.pi / 2.0),
    inner_radius_m: float = 0.0,
    z_bounds_m: tuple[float, float] = (0.531, 0.881),
    rotate_hinge_offset: bool = False,
) -> RevoluteSweptManifold:
    """Construct the world-frame 2D/3D annular swept manifold W_revolute for a revolute door.

    Args:
        base_pos: World (x, y[, z]) origin of the articulated prop or parent fixture.
        base_yaw_rad: World yaw angle of the articulated prop in radians.
        hinge_offset_local: Hinge pivot (hx, hy) offset from base_pos.
        door_radius_m: Outer radius of the revolving door leaf in meters.
        swing_span_rad: Angular sweep interval (theta_min, theta_max) in radians.
        inner_radius_m: Inner radius of the swept annular wedge in meters.
        z_bounds_m: Vertical [z_min, z_max] span of the door leaf in world coordinates.
        rotate_hinge_offset: Whether to rotate hinge_offset_local by base_yaw_rad.

    Returns:
        A RevoluteSweptManifold instance in world coordinates.
    """
    assert door_radius_m > 0.0, f"door_radius_m must be positive, got {door_radius_m}"
    assert inner_radius_m >= 0.0, f"inner_radius_m must be non-negative, got {inner_radius_m}"

    if rotate_hinge_offset:
        cos_y = math.cos(base_yaw_rad)
        sin_y = math.sin(base_yaw_rad)
        hx_w = float(base_pos[0]) + hinge_offset_local[0] * cos_y - hinge_offset_local[1] * sin_y
        hy_w = float(base_pos[1]) + hinge_offset_local[0] * sin_y + hinge_offset_local[1] * cos_y
    else:
        hx_w = float(base_pos[0]) + hinge_offset_local[0]
        hy_w = float(base_pos[1]) + hinge_offset_local[1]

    start_w = base_yaw_rad + swing_span_rad[0]
    end_w = base_yaw_rad + swing_span_rad[1]

    return RevoluteSweptManifold(
        hinge_xy=(hx_w, hy_w),
        inner_radius_m=inner_radius_m,
        outer_radius_m=door_radius_m,
        angle_start_rad=start_w,
        angle_end_rad=end_w,
        z_min_m=z_bounds_m[0],
        z_max_m=z_bounds_m[1],
    )


def point_to_revolute_manifold_distance(
    point_xy: tuple[float, float] | list[float],
    manifold: RevoluteSweptManifold,
) -> float:
    """Compute exact 2D Euclidean distance from a point to a RevoluteSweptManifold wedge."""
    px, py = float(point_xy[0]), float(point_xy[1])
    hx, hy = manifold.hinge_xy
    dx, dy = px - hx, py - hy
    r = math.hypot(dx, dy)
    theta = math.atan2(dy, dx)

    in_angle = _angle_in_sweep(theta, manifold.angle_start_rad, manifold.angle_end_rad)
    if in_angle:
        if manifold.inner_radius_m <= r <= manifold.outer_radius_m:
            return 0.0
        if r < manifold.inner_radius_m:
            return manifold.inner_radius_m - r
        return r - manifold.outer_radius_m

    # Distance to the two radial boundary segments of the wedge
    min_dist = float("inf")
    for edge_angle in (manifold.angle_start_rad, manifold.angle_end_rad):
        ux, uy = math.cos(edge_angle), math.sin(edge_angle)
        proj = dx * ux + dy * uy
        clamped = max(manifold.inner_radius_m, min(manifold.outer_radius_m, proj))
        cx, cy = hx + clamped * ux, hy + clamped * uy
        min_dist = min(min_dist, math.hypot(px - cx, py - cy))
    return min_dist


def check_revolute_manifold_clearance(
    manifold: RevoluteSweptManifold,
    prop_xy: tuple[float, float] | list[float],
    prop_radius_m: float = 0.05,
    margin_m: float = 0.15,
) -> tuple[bool, float, str]:
    """Verify that a staged manipuland or obstacle clears a revolute door swept arc.

    Args:
        manifold: World-frame RevoluteSweptManifold.
        prop_xy: World (x, y) coordinates of the manipuland center.
        prop_radius_m: Bounding cylinder radius of the manipuland in meters.
        margin_m: Required safety clearance margin beyond the door radius (default 0.15m).

    Returns:
        Tuple of (is_clear, measured_clearance_m, diagnostic_message).
    """
    hx, hy = manifold.hinge_xy
    px, py = float(prop_xy[0]), float(prop_xy[1])
    dist_to_hinge = math.hypot(px - hx, py - hy)
    radial_clearance = dist_to_hinge - (manifold.outer_radius_m + prop_radius_m)

    wedge_dist = point_to_revolute_manifold_distance((px, py), manifold) - prop_radius_m
    in_front_halfplane = px >= hx - 0.05
    effective_clearance = max(radial_clearance, wedge_dist)

    if in_front_halfplane and radial_clearance < margin_m:
        return (
            False,
            radial_clearance,
            (
                f"Revolute door swept arc (R={manifold.outer_radius_m:.2f}m) collides with object at "
                f"({px:.2f}, {py:.2f}). Clearance {radial_clearance:.3f}m < required {margin_m:.2f}m."
            ),
        )
    return True, effective_clearance, "Revolute swept arc clearance verified."


def compute_prismatic_stroke_corridor(
    fixture_pos: tuple[float, float] | list[float],
    fixture_yaw_rad: float,
    slide_axis_local: tuple[float, float] = (1.0, 0.0),
    stroke_length_m: float = 0.35,
    drawer_width_m: float = 0.40,
    drawer_depth_m: float = 0.0,
    drawer_height_m: float = 0.15,
    drawer_offset_local: tuple[float, float, float] = (0.0, 0.0, 0.70),
) -> PrismaticStrokeCorridor:
    """Compute the 3D OBB prismatic stroke corridor V_prismatic for an intrinsic sliding drawer.

    Args:
        fixture_pos: World (x, y[, z]) base origin of the parent grounded fixture.
        fixture_yaw_rad: World yaw orientation of the parent fixture in radians.
        slide_axis_local: Unit 2D slide direction (ux, uy) in fixture local coordinates.
        stroke_length_m: Maximum linear pull-out stroke L_stroke in meters.
        drawer_width_m: Width of the drawer face perpendicular to the slide axis in meters.
        drawer_depth_m: Additional outward protrusion depth of the closed drawer face in meters.
        drawer_height_m: Vertical height of the drawer box in meters.
        drawer_offset_local: Local (ox, oy, oz) offset of the drawer aperture face in fixture frame.

    Returns:
        A PrismaticStrokeCorridor representing the swept OBB volume in world space.
    """
    assert stroke_length_m > 0.0, f"stroke_length_m must be positive, got {stroke_length_m}"
    assert drawer_width_m > 0.0 and drawer_depth_m >= 0.0, "Drawer dimensions must be non-negative."

    norm = math.hypot(slide_axis_local[0], slide_axis_local[1])
    assert norm > 1e-6, "slide_axis_local must be non-zero."
    lx, ly = slide_axis_local[0] / norm, slide_axis_local[1] / norm

    cos_f = math.cos(fixture_yaw_rad)
    sin_f = math.sin(fixture_yaw_rad)

    # World slide unit vector
    ux_w = lx * cos_f - ly * sin_f
    uy_w = lx * sin_f + ly * cos_f
    corridor_yaw = math.atan2(uy_w, ux_w)

    # Closed drawer center in world XY
    closed_x = float(fixture_pos[0]) + drawer_offset_local[0] * cos_f - drawer_offset_local[1] * sin_f
    closed_y = float(fixture_pos[1]) + drawer_offset_local[0] * sin_f + drawer_offset_local[1] * cos_f

    # Swept OBB center is shifted by +L_stroke / 2 along the world slide direction (experiment_04.md §3.2)
    center_x = closed_x + 0.5 * stroke_length_m * ux_w
    center_y = closed_y + 0.5 * stroke_length_m * uy_w

    half_length = 0.5 * (drawer_depth_m + stroke_length_m)
    half_width = 0.5 * drawer_width_m

    base_z = float(fixture_pos[2]) if len(fixture_pos) > 2 else 0.0
    z_min = base_z + drawer_offset_local[2] - 0.5 * drawer_height_m
    z_max = base_z + drawer_offset_local[2] + 0.5 * drawer_height_m

    return PrismaticStrokeCorridor(
        center_xy=(center_x, center_y),
        yaw_rad=corridor_yaw,
        half_extents_xy=(half_length, half_width),
        stroke_length_m=stroke_length_m,
        slide_dir_xy=(ux_w, uy_w),
        z_min_m=z_min,
        z_max_m=z_max,
    )


def check_pedestal_prismatic_clearance(
    robot_pos_xy: tuple[float, float] | list[float],
    robot_yaw_rad: float,
    corridor: PrismaticStrokeCorridor,
    pedestal_half_extents: tuple[float, float] = (0.20, 0.20),
    margin_m: float = 0.05,
) -> tuple[bool, float, str]:
    """Verify that the robot pedestal maintains >= 0.05m 2D SAT clearance from V_prismatic.

    Args:
        robot_pos_xy: World (x, y) center of the robot pedestal base.
        robot_yaw_rad: World yaw orientation of the robot pedestal in radians.
        corridor: PrismaticStrokeCorridor for the sliding drawer.
        pedestal_half_extents: (half_x, half_y) footprint of the robot pedestal (default 0.40x0.40m).
        margin_m: Required SAT clearance margin in meters (default 0.05m).

    Returns:
        Tuple of (is_clear, clearance_m, diagnostic_message).
    """
    ok, clearance, _ = check_2d_obb_clearance(
        pos_a=(float(robot_pos_xy[0]), float(robot_pos_xy[1])),
        yaw_a=robot_yaw_rad,
        half_extents_a=pedestal_half_extents,
        pos_b=corridor.center_xy,
        yaw_b=corridor.yaw_rad,
        half_extents_b=corridor.half_extents_xy,
        margin=margin_m,
    )
    if ok:
        return True, clearance, f"Pedestal SAT clearance from prismatic corridor verified ({clearance:.3f}m >= {margin_m:.2f}m)."
    return (
        False,
        clearance,
        (
            f"Robot pedestal at ({robot_pos_xy[0]:.2f}, {robot_pos_xy[1]:.2f}) intersects prismatic stroke "
            f"corridor (deficit: {-clearance:.3f}m < required {margin_m:.2f}m)."
        ),
    )


def check_object_prismatic_clearance(
    prop_xy: tuple[float, float] | list[float],
    corridor: PrismaticStrokeCorridor,
    prop_half_extents: tuple[float, float] = (0.04, 0.04),
    prop_yaw_rad: float = 0.0,
    margin_m: float = 0.10,
) -> tuple[bool, float, str]:
    """Verify that a non-stowed staged manipuland clears the prismatic stroke corridor V_prismatic."""
    ok, clearance, _ = check_2d_obb_clearance(
        pos_a=(float(prop_xy[0]), float(prop_xy[1])),
        yaw_a=prop_yaw_rad,
        half_extents_a=prop_half_extents,
        pos_b=corridor.center_xy,
        yaw_b=corridor.yaw_rad,
        half_extents_b=corridor.half_extents_xy,
        margin=margin_m,
    )
    if ok:
        return True, clearance, f"Object clearance from prismatic corridor verified ({clearance:.3f}m >= {margin_m:.2f}m)."
    return (
        False,
        clearance,
        (
            f"Staged object at ({prop_xy[0]:.2f}, {prop_xy[1]:.2f}) obstructs prismatic stroke corridor "
            f"(deficit: {-clearance:.3f}m < required {margin_m:.2f}m)."
        ),
    )


def partition_fixture_surface_sectors(
    fixture_pos_xy: tuple[float, float] | list[float],
    fixture_yaw_rad: float,
    footprint_half_extents: tuple[float, float] = (0.60, 0.40),
    deck_z_m: float = 0.531,
) -> dict[str, SurfaceSectorSpec]:
    """Partition a fixture's top surface deck into canonical discrete surface sectors.

    The sectors are defined in the world approach frame where 'front' corresponds to the -X
    robot-facing edge and 'left'/'right' correspond to +Y / -Y lateral quadrants.

    Args:
        fixture_pos_xy: World (x, y) center of the supporting fixture.
        fixture_yaw_rad: World yaw rotation of the fixture in radians.
        footprint_half_extents: Local (half_x, half_y) extents of the fixture deck.
        deck_z_m: Physical height Z_deck of the top surface in meters.

    Returns:
        Dictionary mapping sector name ('front_left', 'front_right', 'back_left', 'back_right',
        'front_center', 'center') to SurfaceSectorSpec.
    """
    cos_y = abs(math.cos(fixture_yaw_rad))
    sin_y = abs(math.sin(fixture_yaw_rad))
    world_hx = footprint_half_extents[0] * cos_y + footprint_half_extents[1] * sin_y
    world_hy = footprint_half_extents[0] * sin_y + footprint_half_extents[1] * cos_y

    fx, fy = float(fixture_pos_xy[0]), float(fixture_pos_xy[1])
    qx = 0.45 * world_hx
    qy = 0.45 * world_hy
    sub_hx = 0.40 * world_hx
    sub_hy = 0.40 * world_hy

    return {
        "front_left": SurfaceSectorSpec("front_left", (fx - qx, fy + qy), 0.0, (sub_hx, sub_hy), deck_z_m),
        "front_right": SurfaceSectorSpec("front_right", (fx - qx, fy - qy), 0.0, (sub_hx, sub_hy), deck_z_m),
        "back_left": SurfaceSectorSpec("back_left", (fx + qx, fy + qy), 0.0, (sub_hx, sub_hy), deck_z_m),
        "back_right": SurfaceSectorSpec("back_right", (fx + qx, fy - qy), 0.0, (sub_hx, sub_hy), deck_z_m),
        "front_center": SurfaceSectorSpec("front_center", (fx - qx, fy), 0.0, (sub_hx, 0.35 * world_hy), deck_z_m),
        "center": SurfaceSectorSpec("center", (fx, fy), 0.0, (0.35 * world_hx, 0.35 * world_hy), deck_z_m),
    }


def evaluate_sector_admissibility(
    sectors: dict[str, SurfaceSectorSpec],
    revolute_manifold: RevoluteSweptManifold | None = None,
    prismatic_corridor: PrismaticStrokeCorridor | None = None,
    margin_m: float = 0.10,
) -> dict[str, bool]:
    """Evaluate which surface sectors are admissible (collision-free) against active motion manifolds."""
    admissibility: dict[str, bool] = {}
    for name, sec in sectors.items():
        admissible = True
        if revolute_manifold is not None:
            ok, _, _ = check_revolute_manifold_clearance(
                revolute_manifold,
                sec.center_xy,
                prop_radius_m=min(sec.half_extents_xy) * 0.5,
                margin_m=margin_m,
            )
            if not ok:
                admissible = False
        if admissible and prismatic_corridor is not None:
            ok, _, _ = check_object_prismatic_clearance(
                sec.center_xy,
                prismatic_corridor,
                prop_half_extents=(sec.half_extents_xy[0] * 0.5, sec.half_extents_xy[1] * 0.5),
                margin_m=margin_m,
            )
            if not ok:
                admissible = False
        admissibility[name] = admissible
    return admissibility


def check_cavity_containment_and_headroom(
    object_dims_xyz: tuple[float, float, float],
    cavity_dims_xyz: tuple[float, float, float],
    min_headroom_m: float = 0.02,
    max_volume_ratio: float = 0.40,
) -> tuple[bool, dict[str, float], str]:
    """Verify stowed object containment, volume ratio, and vertical overhead headroom (D2-B / D2-C).

    Args:
        object_dims_xyz: (width, depth, height) bounding dimensions of the manipuland in meters.
        cavity_dims_xyz: (width, depth, height) interior dimensions of the drawer/cabinet cavity.
        min_headroom_m: Minimum vertical clearance (H_cavity - H_obj) to prevent jamming (default 0.02m).
        max_volume_ratio: Maximum allowable Vol(obj) / Vol(cavity) ratio (default 0.40).

    Returns:
        Tuple of (is_valid, metrics_dict, diagnostic_message).
    """
    ow, od, oh = object_dims_xyz
    cw, cd, ch = cavity_dims_xyz
    assert cw > 0 and cd > 0 and ch > 0, "Cavity dimensions must be positive."

    obj_vol = ow * od * oh
    cav_vol = cw * cd * ch
    vol_ratio = obj_vol / cav_vol
    headroom_z = ch - oh
    fits_xy = (ow <= cw and od <= cd) or (od <= cw and ow <= cd)

    metrics = {
        "object_volume_m3": round(obj_vol, 6),
        "cavity_volume_m3": round(cav_vol, 6),
        "volume_ratio": round(vol_ratio, 4),
        "headroom_z_m": round(headroom_z, 4),
    }

    if not fits_xy:
        return (
            False,
            metrics,
            f"Object footprint ({ow:.3f}x{od:.3f}m) exceeds cavity planar aperture ({cw:.3f}x{cd:.3f}m).",
        )
    if headroom_z + 1e-6 < min_headroom_m:
        return (
            False,
            metrics,
            f"Stowed vertical headroom {headroom_z:.3f}m < required {min_headroom_m:.3f}m; risks jamming on closure.",
        )
    if vol_ratio > max_volume_ratio:
        return (
            False,
            metrics,
            f"Object-to-cavity volume ratio {vol_ratio:.2f} exceeds maximum {max_volume_ratio:.2f}.",
        )
    return True, metrics, f"Cavity containment verified (headroom={headroom_z:.3f}m, vol_ratio={vol_ratio:.2f})."


def check_dual_revolute_clearance(
    left_manifold: RevoluteSweptManifold,
    right_manifold: RevoluteSweptManifold,
    robot_pos_xy: tuple[float, float] | list[float],
    pedestal_radius_m: float = 0.25,
    min_seam_clearance_m: float = 0.05,
) -> tuple[bool, dict[str, Any], str]:
    """Verify that dual counter-rotating cabinet doors (D2-C) do not collide or hit the robot pedestal."""
    lx, ly = left_manifold.hinge_xy
    rx, ry = right_manifold.hinge_xy
    hinge_span = math.hypot(rx - lx, ry - ly)

    # At full open (90 deg outward), leaf tips project outward from their respective hinges.
    # For non-interfering counter-rotating doors meeting at a center seam, hinge_span >= R_left + R_right - seam_tol.
    min_required_span = left_manifold.outer_radius_m + right_manifold.outer_radius_m - 0.02
    doors_clear_each_other = hinge_span >= min_required_span

    # Check robot pedestal distance to both swept manifolds
    dist_left = point_to_revolute_manifold_distance(robot_pos_xy, left_manifold) - pedestal_radius_m
    dist_right = point_to_revolute_manifold_distance(robot_pos_xy, right_manifold) - pedestal_radius_m
    min_pedestal_clearance = min(dist_left, dist_right)

    metrics = {
        "hinge_span_m": round(hinge_span, 4),
        "left_radius_m": left_manifold.outer_radius_m,
        "right_radius_m": right_manifold.outer_radius_m,
        "min_pedestal_clearance_m": round(min_pedestal_clearance, 4),
    }

    if not doors_clear_each_other:
        return (
            False,
            metrics,
            (
                f"Dual counter-rotating doors overlap: hinge span {hinge_span:.3f}m < combined leaf radii "
                f"{left_manifold.outer_radius_m + right_manifold.outer_radius_m:.3f}m."
            ),
        )
    if min_pedestal_clearance < min_seam_clearance_m:
        return (
            False,
            metrics,
            (
                f"Dual door swept arcs violate robot pedestal clearance ({min_pedestal_clearance:.3f}m "
                f"< required {min_seam_clearance_m:.2f}m)."
            ),
        )
    return (
        True,
        metrics,
        f"Dual revolute doors verified clear (hinge_span={hinge_span:.2f}m, pedestal_clearance={min_pedestal_clearance:.2f}m).",
    )
