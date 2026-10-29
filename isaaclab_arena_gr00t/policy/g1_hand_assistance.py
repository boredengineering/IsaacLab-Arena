# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Opt-in privileged-state G1 assistance; thresholds are experiment hypotheses.

The historical middle-finger link origin is NOT a grasp centre. All distances
are metres and joint residuals radians. This module imports no simulator APIs.
"""

from __future__ import annotations

import json
import math
import torch
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AssistanceCfg:
    """JSON schema; privileged_state must explicitly be true, unknown keys fail."""

    privileged_state: bool
    mode: str = "observe"
    hand: str = "left"
    hand_body: str = "left_hand_middle_1_link"
    object_name: str = "red_apple"
    downward_offset_m: float = 0.01
    residual_joint_bound: float = 0.10
    residual_slew_rad_s: float = 0.5
    residual_norm_bound: float = 0.15
    damping: float = 0.05
    rotation_weight: float = 0.2
    lateral_bound_m: float = 0.003
    max_active_s: float = 1.0
    xy_window_m: float = 0.10
    z_min_m: float = -0.02
    z_max_m: float = 0.15
    lift_stop_m: float = 0.008
    ready_xy_m: float = 0.04
    ready_z_min_m: float = -0.01
    ready_z_max_m: float = 0.04
    ready_dwell_s: float = 0.06
    closure_deviation_rad: float = 0.08
    gate_max_delay_s: float = 0.4
    gate_release_s: float = 0.1
    rgb_checksum: bool = False

    def __post_init__(self):
        assert self.privileged_state is True, "Explicit privileged_state=true acknowledgement required"
        assert self.mode in ("observe", "gate", "offset", "combined")
        assert self.hand == "left", "Only the explicitly validated left-hand mapping is supported"
        assert self.hand_body == "left_hand_middle_1_link", "Target is a finger origin, not a grasp centre"
        assert isinstance(self.object_name, str) and self.object_name
        assert isinstance(self.rgb_checksum, bool)
        for key, value in asdict(self).items():
            if key not in ("privileged_state", "mode", "hand", "hand_body", "object_name", "rgb_checksum"):
                assert type(value) in (int, float) and math.isfinite(value), key
        bounds = {
            "downward_offset_m": 0.03,
            "residual_joint_bound": 0.15,
            "residual_slew_rad_s": 1.0,
            "residual_norm_bound": 0.3,
            "damping": 1.0,
            "rotation_weight": 1.0,
            "lateral_bound_m": 0.01,
            "max_active_s": 2.0,
            "xy_window_m": 0.2,
            "lift_stop_m": 0.008,
            "ready_xy_m": 0.1,
            "ready_dwell_s": 0.3,
            "closure_deviation_rad": 0.5,
            "gate_release_s": 0.2,
        }
        for key, maximum in bounds.items():
            assert 0 < getattr(self, key) <= maximum, key
        assert -0.1 <= self.z_min_m < self.z_max_m <= 0.3
        assert self.z_min_m <= self.ready_z_min_m < self.ready_z_max_m <= self.z_max_m
        assert self.ready_xy_m <= self.xy_window_m
        assert 0.3 <= self.gate_max_delay_s <= 0.5
        assert self.gate_release_s < self.gate_max_delay_s

    @classmethod
    def from_json(cls, path: str) -> AssistanceCfg:
        """Load an explicit JSON file; no implicit configuration is accepted."""
        assert path, "assistance_config_path is required"
        with open(path) as stream:
            return cls(**json.load(stream))


def bounded_residual(
    jacobian: torch.Tensor,
    q_policy: torch.Tensor,
    limits: torch.Tensor,
    previous: torch.Tensor,
    dt: float,
    cfg: AssistanceCfg,
) -> tuple[torch.Tensor, str]:
    """Compute non-accumulating weighted world-frame DLS with intersected bounds.

    Args:
        jacobian: World-frame geometric Jacobian [6, 7] at the finger origin.
        q_policy: Scheduled policy arm targets [7], radians.
        limits: Measured articulation soft position limits [7, 2], radians.
        previous: Previous applied residual [7], radians (only used for slew).
        dt: Policy timestep, seconds.
        cfg: Explicit assistance settings.

    Returns:
        Residual and acceptance/rejection reason. Rejection deliberately returns
        zero even when this requires a slew discontinuity; it never overrides raw
        policy targets merely to repair an infeasible policy command.
    """
    assert jacobian.shape == (6, 7) and q_policy.shape == previous.shape == (7,)
    assert limits.shape == (7, 2) and math.isfinite(dt) and dt > 0
    zero = torch.zeros_like(q_policy)
    if not all(torch.isfinite(x).all() for x in (jacobian, q_policy, limits, previous)):
        return zero, "nonfinite"
    slew = cfg.residual_slew_rad_s * dt
    low = torch.maximum(torch.maximum(limits[:, 0] - q_policy, previous - slew), zero - cfg.residual_joint_bound)
    high = torch.minimum(torch.minimum(limits[:, 1] - q_policy, previous + slew), zero + cfg.residual_joint_bound)
    if torch.any(low > high):
        return zero, "empty_intersection"
    weights = q_policy.new_tensor([1, 1, 1, cfg.rotation_weight, cfg.rotation_weight, cfg.rotation_weight])
    weighted = weights[:, None] * jacobian
    desired = q_policy.new_tensor([0, 0, -cfg.downward_offset_m, 0, 0, 0]) * weights
    try:
        delta = weighted.T @ torch.linalg.solve(
            weighted @ weighted.T + cfg.damping**2 * torch.eye(6, device=q_policy.device, dtype=q_policy.dtype), desired
        )
    except RuntimeError:
        return zero, "solve_failed"
    delta = torch.minimum(torch.maximum(delta, low), high)
    predicted = jacobian @ delta
    if not torch.isfinite(delta).all() or not torch.isfinite(predicted).all():
        return zero, "nonfinite"
    if torch.linalg.vector_norm(delta) > cfg.residual_norm_bound:
        return zero, "norm_bound"
    if not (-cfg.downward_offset_m * 1.05 <= predicted[2] < 0):
        return zero, "not_downward"
    if torch.linalg.vector_norm(predicted[:2]) > cfg.lateral_bound_m:
        return zero, "lateral_bound"
    return delta, "accepted"


ARM_SLOTS = [11, 15, 19, 21, 23, 25, 27]
HAND_SLOTS = [29, 30, 31, 35, 36, 37, 41]


class HandAssistance:
    """Single-environment state, sampled first at the POST-SETTLE policy call."""

    def __init__(self, cfg: AssistanceCfg):
        self.cfg = cfg
        self.epoch = -1
        self.reset()

    def reset(self):
        """Forget all episode baselines, residuals, clocks and gate permissions."""
        self.epoch += 1
        self.step = 0
        self.time = 0.0
        self.open_hand = None
        self.initial_object_z = None
        self.previous = None
        self.active_start = None
        self.offset_stopped = None
        self.gate_start = None
        self.release_start = None
        self.ready_dwell = 0.0
        self.permission = False
        self.timed_out = False
        self.state_rejected = False

    def apply(
        self,
        *,
        raw: torch.Tensor,
        measured: torch.Tensor,
        jacobian: torch.Tensor,
        limits: torch.Tensor,
        hand_pos: torch.Tensor,
        object_pos: torch.Tensor,
        dt: float,
    ) -> tuple[torch.Tensor, dict]:
        """Clone one scheduled 50D action and record active-arm/finger diagnostics.

        Args:
            raw: Scheduled action [1, 50]; never mutated or accumulated into.
            measured: Joint positions in canonical G1 action-name order [43].
            jacobian: World-frame active-arm Jacobian at the finger origin [6, 7].
            limits: Active-arm soft joint limits [7, 2].
            hand_pos: Measured finger origin in world coordinates [3].
            object_pos: Measured object position in world coordinates [3].
            dt: Policy timestep in seconds.

        Returns:
            Independent executed tensor and JSON-serializable diagnostics.
        """
        assert raw.shape == (1, 50) and measured.shape == (43,)
        assert math.isfinite(dt) and dt > 0
        out = raw.clone()
        if self.open_hand is None:
            self.open_hand = measured[HAND_SLOTS].clone()
            self.initial_object_z = float(object_pos[2])
            self.previous = torch.zeros_like(measured[ARM_SLOTS])
        correction = torch.zeros_like(self.previous)
        relative = hand_pos - object_pos
        finite = bool(torch.isfinite(relative).all() and torch.isfinite(measured).all())
        self.state_rejected = self.state_rejected or not finite
        if self.state_rejected:
            self.offset_stopped = "nonfinite_state"
        xy = float(torch.linalg.vector_norm(relative[:2]))
        lift = float(object_pos[2]) - self.initial_object_z
        window = finite and xy <= self.cfg.xy_window_m and self.cfg.z_min_m <= relative[2] <= self.cfg.z_max_m
        if lift >= self.cfg.lift_stop_m:
            self.offset_stopped = "object_lifted"
        if window and self.active_start is None:
            self.active_start = self.time
        if self.active_start is not None and self.time - self.active_start >= self.cfg.max_active_s - 1e-9:
            self.offset_stopped = self.offset_stopped or "active_timeout"
        reason = "disabled"
        if self.cfg.mode in ("offset", "combined"):
            reason = self.offset_stopped or ("outside_window" if not window else "eligible")
            if reason == "eligible":
                correction, reason = bounded_residual(jacobian, raw[0, ARM_SLOTS], limits, self.previous, dt, self.cfg)
            out[0, ARM_SLOTS] += correction
        requested = float(torch.max((raw[0, HAND_SLOTS] - self.open_hand).abs())) >= self.cfg.closure_deviation_rad
        ready = bool(
            finite and xy <= self.cfg.ready_xy_m and self.cfg.ready_z_min_m <= relative[2] <= self.cfg.ready_z_max_m
        )
        self.ready_dwell = self.ready_dwell + dt if ready else 0.0
        authority = 1.0
        if self.cfg.mode in ("gate", "combined") and not self.state_rejected:
            if requested and self.gate_start is None:
                self.gate_start = self.time
            if self.gate_start is not None:
                if self.ready_dwell >= self.cfg.ready_dwell_s - 1e-9:
                    self.permission = True
                deadline = self.gate_start + self.cfg.gate_max_delay_s - self.cfg.gate_release_s
                if self.release_start is None:
                    if self.time >= deadline - 1e-9:
                        self.timed_out = True
                        self.release_start = deadline
                    elif self.permission or lift >= self.cfg.lift_stop_m or not finite:
                        self.release_start = self.time
                authority = (
                    0.0
                    if self.release_start is None
                    else min(1.0, max(0.0, (self.time - self.release_start) / self.cfg.gate_release_s))
                )
                if self.time >= self.gate_start + self.cfg.gate_max_delay_s - 1e-9:
                    authority = 1.0
                if authority < 1.0:
                    out[0, HAND_SLOTS] = self.open_hand + authority * (raw[0, HAND_SLOTS] - self.open_hand)
        trace = {
            "privileged_state": True,
            "state_rejected": self.state_rejected,
            "mode": self.cfg.mode,
            "hand": self.cfg.hand,
            "hand_body": self.cfg.hand_body,
            "object_name": self.cfg.object_name,
            "hand_reference": "finger_origin_not_grasp_centre",
            "epoch": self.epoch,
            "step": self.step,
            "time_s": self.time,
            "hand_world": hand_pos.tolist(),
            "object_world": object_pos.tolist(),
            "initial_open_hand": self.open_hand.tolist(),
            "correction": correction.tolist(),
            "relative_hand_object": relative.tolist(),
            "object_lift_m": lift,
            "in_window": bool(window),
            "residual_reason": reason,
            "predicted_correction_world": (jacobian @ correction).tolist(),
            "residual_slew_discontinuity": bool(
                torch.any((correction - self.previous).abs() > self.cfg.residual_slew_rad_s * dt + 1e-7)
            ),
            "closure_requested": requested,
            "ready": ready,
            "ready_dwell_s": self.ready_dwell,
            "gate_activated": self.gate_start is not None,
            "gate_permission_latched": self.permission,
            "gate_timed_out": self.timed_out,
            "gate_authority": authority,
        }
        for group, slots in (("arm", ARM_SLOTS), ("hand", HAND_SLOTS)):
            trace[f"raw_{group}"] = raw[0, slots].tolist()
            trace[f"executed_{group}"] = out[0, slots].tolist()
            trace[f"measured_{group}"] = measured[slots].tolist()
        self.previous = correction
        self.time += dt
        self.step += 1
        return out, trace
