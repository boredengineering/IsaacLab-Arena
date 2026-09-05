# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Helpers for pinning a scene to the simulator state stored in a recorded demonstration.

Replaying *actions* from an initial state diverges from the recording, so anything that needs the
rendered frame to correspond to the recorded one has to write the recorded state per frame instead.
These helpers do that bookkeeping and the checks that keep a silent mismatch from passing as a
faithful replay.

Kept out of the Isaac Lab entry-point scripts on purpose: those parse ``sys.argv`` and launch the
simulator at import time, so importing one from another tool hijacks that tool's own arguments.
"""

import numpy as np
import torch
from typing import Any


def read_recorded_states(demo_group: Any) -> dict[str, dict[str, dict[str, np.ndarray]]]:
    """Return the per-frame recorded state arrays for one demo, keyed by asset type and name.

    Args:
        demo_group: The ``data/demo_N`` group of an Isaac Lab HDF5 recording.

    Returns:
        Nested mapping ``{asset_type: {asset_name: {state_name: array of shape (T, D)}}}``.
    """
    states: dict[str, dict[str, dict[str, np.ndarray]]] = {}
    for asset_type in ("articulation", "rigid_object"):
        if asset_type not in demo_group["states"]:
            continue
        states[asset_type] = {}
        for asset_name, asset_group in demo_group["states"][asset_type].items():
            states[asset_type][asset_name] = {name: np.asarray(arr) for name, arr in asset_group.items()}
    return states


def frame_state_for_scene(
    scene_state: dict[str, dict[str, dict[str, torch.Tensor]]],
    recorded: dict[str, dict[str, dict[str, np.ndarray]]],
    frame_index: int,
    device: str,
) -> dict[str, dict[str, dict[str, torch.Tensor]]]:
    """Overlay one recorded frame onto the scene's current state, leaving unrecorded assets alone.

    Starting from the live scene state rather than building a fresh dict means an asset the scene
    has but the recording does not (an invisible support surface, say) keeps its own pose instead of
    raising.

    Args:
        scene_state: Current scene state, as returned by ``InteractiveScene.get_state``.
        recorded: Per-frame recorded arrays from :func:`read_recorded_states`.
        frame_index: Frame to overlay.
        device: Device to place the overlaid tensors on.

    Returns:
        A state dict in the format ``InteractiveScene.reset_to`` expects.
    """
    overlaid = {
        asset_type: {asset_name: dict(entries) for asset_name, entries in assets.items()}
        for asset_type, assets in scene_state.items()
    }
    for asset_type, assets in recorded.items():
        for asset_name, entries in assets.items():
            if asset_type not in overlaid or asset_name not in overlaid[asset_type]:
                continue
            for state_name, array in entries.items():
                if state_name not in overlaid[asset_type][asset_name]:
                    continue
                value = torch.as_tensor(array[frame_index], dtype=torch.float32, device=device)
                overlaid[asset_type][asset_name][state_name] = value.unsqueeze(0)
    return overlaid


def assert_recording_covers_scene(
    scene_state: dict[str, dict[str, dict[str, torch.Tensor]]],
    recorded: dict[str, dict[str, dict[str, np.ndarray]]],
) -> list[str]:
    """Assert the recording drives the robot, and report scene assets it does not drive.

    Args:
        scene_state: Current scene state.
        recorded: Per-frame recorded arrays.

    Returns:
        Names of scene assets left at their live pose because the recording does not contain them.
    """
    recorded_articulations = set(recorded.get("articulation", {}))
    scene_articulations = set(scene_state.get("articulation", {}))
    assert scene_articulations & recorded_articulations, (
        "The recording drives none of the scene's articulations, so playback would render a scene the"
        f" recording never describes. Scene has {sorted(scene_articulations)}, recording has"
        f" {sorted(recorded_articulations)}."
    )
    undriven = []
    for asset_type, assets in scene_state.items():
        for asset_name in assets:
            if asset_name not in recorded.get(asset_type, {}):
                undriven.append(f"{asset_type}/{asset_name}")
    return sorted(undriven)


def state_playback_error(scene, written: dict) -> dict[str, float]:
    """Read the scene state back after a write and return the worst discrepancy per asset.

    A silent mismatch here is the difference between "the recording did not apply" and "the scene
    renders the recorded state differently", which are diagnosed in completely different places.

    Note this cannot detect a joint *ordering* difference between the recording and the current
    build, because it compares what was written against what was read back in the same ordering.
    Compare the articulation's ``joint_names`` against the recording's own ordering for that.

    Args:
        scene: The interactive scene, already advanced with ``sim.forward()``.
        written: The state dict that was handed to ``InteractiveScene.reset_to``.

    Returns:
        Mapping from ``"<asset_type>/<asset>/<state>"`` to the maximum absolute difference.
    """
    realised = scene.get_state(is_relative=True)
    errors = {}
    for asset_type, assets in written.items():
        for asset_name, entries in assets.items():
            for state_name, value in entries.items():
                other = realised.get(asset_type, {}).get(asset_name, {}).get(state_name)
                if other is None:
                    continue
                diff = (value.to(other.device).float() - other.float()).abs().max()
                errors[f"{asset_type}/{asset_name}/{state_name}"] = float(diff)
    return errors
