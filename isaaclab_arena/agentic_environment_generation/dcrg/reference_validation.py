# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Numerical replay checks and metadata inspection, never task-success certification."""

import numpy as np
from collections.abc import Mapping
from os import PathLike
from typing import Any


def compare_pose_trajectory(
    reference: Mapping[str, Any],
    actual: Mapping[str, Any],
    position_tolerance_m: float,
    orientation_tolerance_rad: float,
) -> dict[str, Any]:
    """Compare corresponding poses without resampling or coordinate conversion.

    Args:
        reference: Mapping with ``poses`` (N, 7): xyz [m], quaternion; ``timestamps``
            (N,) [s]; explicit ``frame_id`` naming coordinate/body frame; and
            ``quaternion_order`` (``wxyz`` or ``xyzw``). Unit norms must be within
            1e-6; only this numerical roundoff is normalized, never arbitrary scaling.
            Pose/timestamp arrays must have signed/unsigned integer or floating-point
            dtypes (NumPy kinds i/u/f), converted to float64 for comparison. Numeric
            lists are supported; object, string, boolean and complex arrays are not.
        actual: Same schema and frame as reference. Callers must verify source conventions.
        position_tolerance_m: Finite nonnegative maximum Euclidean position error [m].
        orientation_tolerance_rad: Finite nonnegative maximum shortest rotation angle [rad].

    Returns:
        ``passed``, ``valid_input``, ``reason``, ``sample_count`` and maximum position/
        orientation errors. Invalid data yields False flags, zero compared samples
        and None metrics. Matching timestamps must be strictly increasing and exact;
        passing numerical bounds is not retained-grasp or task-success evidence.
    """
    invalid = {
        "passed": False,
        "valid_input": False,
        "reason": None,
        "sample_count": 0,
        "max_position_error_m": None,
        "max_orientation_error_rad": None,
    }
    try:
        for tolerance in (position_tolerance_m, orientation_tolerance_rad):
            if np.iscomplexobj(tolerance):
                raise ValueError("Tolerances must be real-valued")
            if np.ndim(tolerance) != 0 or not np.isfinite(tolerance) or tolerance < 0:
                raise ValueError("Tolerances must be finite nonnegative scalars")
        ref = np.asarray(reference["poses"])
        act = np.asarray(actual["poses"])
        if ref.dtype.kind not in "iuf" or act.dtype.kind not in "iuf":
            raise ValueError("Poses must be real-valued")
        ref = ref.astype(float)
        act = act.astype(float)
        if ref.ndim != 2 or ref.shape[1] != 7 or len(ref) == 0 or ref.shape != act.shape:
            raise ValueError("Poses must have identical nonempty (N, 7) shapes")
        frame = reference["frame_id"]
        if not isinstance(frame, str) or not frame.strip() or frame != actual["frame_id"]:
            raise ValueError("Explicit coordinate/body frames must match")
        order = reference["quaternion_order"]
        if order not in ("wxyz", "xyzw") or order != actual["quaternion_order"]:
            raise ValueError("Explicit quaternion orders must match: wxyz or xyzw")
        times = []
        quaternions = []
        for trajectory, poses in ((reference, ref), (actual, act)):
            if not np.isfinite(poses).all():
                raise ValueError("Poses must be finite")
            with np.errstate(over="ignore", under="ignore"):
                norms = np.hypot.reduce(poses[:, 3:], axis=1)
            if not np.allclose(norms, 1.0, atol=1e-6, rtol=0):
                raise ValueError("Quaternions must be unit length within 1e-6")
            quaternions.append(poses[:, 3:] / norms[:, None])
            timestamps = np.asarray(trajectory["timestamps"])
            if timestamps.dtype.kind not in "iuf":
                raise ValueError("Timestamps must be real-valued")
            timestamps = timestamps.astype(float)
            if timestamps.shape != (len(ref),) or not np.isfinite(timestamps).all():
                raise ValueError("Timestamps must be finite and match pose count")
            if np.any(np.diff(timestamps) <= 0):
                raise ValueError("Timestamps must be strictly increasing")
            times.append(timestamps)
        if not np.array_equal(*times):
            raise ValueError("Timestamps must match exactly; resampling is not implicit")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        invalid["reason"] = str(exc)
        return invalid
    with np.errstate(over="ignore", invalid="ignore"):
        position = np.hypot.reduce(ref[:, :3] - act[:, :3], axis=1)
    if not np.isfinite(position).all():
        invalid["reason"] = "Computed position errors must be finite"
        return invalid
    q_ref, q_act = quaternions
    dot = np.sum(q_ref * q_act, axis=1)
    q_act = q_act * np.where(dot < 0, -1, 1)[:, None]
    # Chord-based angle retains precision near identity; hypot avoids squared-norm underflow.
    chord = np.hypot.reduce(q_ref - q_act, axis=1)
    orientation = 4 * np.arctan2(chord, np.hypot.reduce(q_ref + q_act, axis=1))
    # For sign-aligned unit quaternions, theta = 4 * asin(chord / 2) >= 2 * chord.
    # Enforce this bound because atan2 can underflow before the multiplication by four.
    orientation = np.maximum(orientation, 2 * chord)
    passed = bool(np.all(position <= position_tolerance_m) and np.all(orientation <= orientation_tolerance_rad))
    return {
        "passed": passed,
        "valid_input": True,
        "reason": None if passed else "tolerance_exceeded",
        "sample_count": len(ref),
        "max_position_error_m": float(np.max(position)),
        "max_orientation_error_rad": float(np.max(orientation)),
    }


def inspect_reference_episode(path: str | PathLike[str], episode_name: str) -> dict[str, Any]:
    """Read HDF5 schema and historical metadata without loading dataset payloads.

    Args:
        path: Native HDF5 file opened read-only; h5py is imported only on this call.
        episode_name: Exact child name under ``data`` (for example ``demo_0``).

    Returns:
        Dataset shapes/dtypes/attributes, state presence and unresolved prerequisites.
        Historical labels never certify success, replay, conventions or joint mapping.
        File/schema access errors propagate instead of producing a passing report.
    """
    import h5py

    def attributes(group):
        return {
            key: value.tolist() if isinstance(value, (np.ndarray, np.generic)) else value
            for key, value in group.attrs.items()
        }

    if not isinstance(episode_name, str) or not episode_name or "/" in episode_name:
        raise ValueError("episode_name must be an exact child name under data")
    with h5py.File(path, "r") as file:
        data = file["data"]
        if not isinstance(data, h5py.Group):
            raise ValueError("data must be a group")
        episode = data[episode_name]
        if not isinstance(episode, h5py.Group):
            raise ValueError("episode must be a group")
        datasets = {}

        def visit(name, item):
            if isinstance(item, h5py.Dataset):
                datasets[name] = {
                    "shape": list(item.shape) if item.shape is not None else None,
                    "dtype": str(item.dtype),
                    "attributes": attributes(item),
                }

        episode.visititems(visit)
        attrs = {"file": attributes(file), "data": attributes(data), "episode": attributes(episode)}
    actions = datasets.get("actions", {}).get("shape")
    processed = datasets.get("processed_actions", {}).get("shape")
    state_presence = {}
    for label, prefix in (("trajectory", "states"), ("initial", "initial_state")):
        for kind, category in (("robot", "articulation"), ("object", "rigid_object")):
            state_presence[f"{kind}_{label}"] = any(
                name.startswith(f"{prefix}/{category}/")
                and name.endswith("/root_pose")
                and info["shape"] is not None
                and len(info["shape"]) == 2
                and info["shape"][0] > 0
                and info["shape"][1] == 7
                for name, info in datasets.items()
            )
    sample_count = actions[0] if actions and len(actions) == 2 else None
    issues = [
        "Metadata only: scene provenance, sample alignment, quaternion convention, joint mapping, "
        "bounded replay and independent task/retention success remain unverified"
    ]
    if attrs["episode"].get("num_samples") != sample_count:
        issues.append("num_samples does not match actions")
    for name, info in datasets.items():
        if name == "processed_actions" or name.startswith("states/"):
            shape = info["shape"]
            if not shape or shape[0] != sample_count:
                issues.append(f"Sample count mismatch: {name}")
    issues.extend(f"Missing root-pose data: {name}" for name, present in state_presence.items() if not present)
    return {
        "episode_name": episode_name,
        "datasets": datasets,
        "attributes": attrs,
        "sample_count": sample_count,
        "action_dimension": actions[1] if actions and len(actions) == 2 else None,
        "processed_action_dimension": processed[1] if processed and len(processed) == 2 else None,
        "historical_success": attrs["episode"].get("success"),
        "success_certified": False,
        "replay_validated": False,
        "state_presence": state_presence,
        "timestamp_datasets": [name for name in datasets if name.rsplit("/", 1)[-1] == "timestamps"],
        "quaternion_order": None,
        "runtime_joint_mapping": None,
        "issues": issues,
    }
