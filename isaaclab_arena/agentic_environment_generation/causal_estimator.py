# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Job J7: Causal Lightcone & Lyapunov Estimator for In-Graph Dynamic Budgeting.

Pure Python/NumPy mathematical core with zero simulator or GPU dependencies.
Evaluates the composite Lyapunov error E(k), trajectory contraction rate
Delta E(k) = E(k-1) - E(k), and causal planning horizon H*(s_k).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal
import uuid

import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class TrajectoryStep(BaseModel):
    """Single trajectory step telemetry snapshot for Lyapunov contraction analysis."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    step_index: int = 0
    lyapunov_error: float = 0.0
    settle_velocity_norm: float = 0.0
    spatial_exclusion_error: float = 0.0
    visual_critic_score: float = 1.0
    min_clearance_m: float = 0.15
    max_contact_force_n: float = 0.0
    topological_collision: bool = False
    candidate_id: str | None = None


class ContractionResult(BaseModel):
    """Result of evaluating Lyapunov contraction across trajectory history."""

    model_config = ConfigDict(frozen=True)

    delta_error: float
    is_contracting: bool
    regime: Literal["converging", "stagnating", "diverging"]
    error_before: float = 0.0
    error_after: float = 0.0


class CausalHorizonReceipt(BaseModel):
    """Cryptographic/structured receipt emitted by Job J7 (Causal Lightcone Estimator)."""

    model_config = ConfigDict(frozen=True)

    horizon_H: int = Field(ge=0)
    delta_E: float
    regime: Literal["converging", "stagnating", "diverging"]
    lyapunov_error: float = Field(ge=0.0)
    causal_status: Literal["in_cone", "narrow_cone", "collapsed"]
    reason: str


def _extract_settle_velocity_norm(settle_telemetry: Any) -> float:
    """Extract scalar settling velocity/displacement norm ||v_settle|| from telemetry."""
    if settle_telemetry is None:
        return 0.0
    if isinstance(settle_telemetry, (int, float)):
        val = float(settle_telemetry)
        return max(0.0, val) if math.isfinite(val) else 1.0
    if isinstance(settle_telemetry, (list, tuple, np.ndarray)):
        arr = np.asarray(settle_telemetry, dtype=float)
        if arr.size == 0 or not np.isfinite(arr).all():
            return 0.0
        return float(np.linalg.norm(arr))
    if isinstance(settle_telemetry, dict):
        for key in ("settle_velocity_norm", "linear_speed", "max_linear_velocity", "velocity_norm"):
            if key in settle_telemetry and settle_telemetry[key] is not None:
                val = float(settle_telemetry[key])
                if math.isfinite(val):
                    drop_penalty = float(settle_telemetry.get("vertical_drop_z", 0.0) or 0.0)
                    return max(0.0, val + max(0.0, drop_penalty))
        if "objects" in settle_telemetry and isinstance(settle_telemetry["objects"], dict):
            norms: list[float] = []
            for obj_metrics in settle_telemetry["objects"].values():
                if isinstance(obj_metrics, dict):
                    speed = float(obj_metrics.get("linear_speed", 0.0) or 0.0)
                    drop = float(obj_metrics.get("vertical_drop_z", 0.0) or 0.0)
                    disp = float(obj_metrics.get("root_displacement", 0.0) or 0.0)
                    norms.append(speed + max(0.0, drop) + 0.5 * max(0.0, disp - 0.05))
            if norms:
                return float(max(norms))
        drop = float(settle_telemetry.get("vertical_drop_z", 0.0) or 0.0)
        disp = float(settle_telemetry.get("root_displacement", 0.0) or 0.0)
        return max(0.0, drop + 0.5 * max(0.0, disp - 0.05))
    return 0.0


def _extract_spatial_exclusion_distance(spatial_violations: Any) -> float:
    """Extract scalar spatial exclusion / penetration distance d_exclusion(x_k)."""
    if spatial_violations is None:
        return 0.0
    if isinstance(spatial_violations, (int, float)):
        val = float(spatial_violations)
        return max(0.0, val) if math.isfinite(val) else 1.0
    if isinstance(spatial_violations, dict):
        for key in ("exclusion_distance", "d_exclusion", "obb_penetration", "residual"):
            if key in spatial_violations and spatial_violations[key] is not None:
                val = float(spatial_violations[key])
                if math.isfinite(val):
                    return max(0.0, val)
        if "violations" in spatial_violations and isinstance(spatial_violations["violations"], (list, tuple)):
            return 0.25 * float(len(spatial_violations["violations"]))
        return 0.0
    if isinstance(spatial_violations, (list, tuple)):
        if not spatial_violations:
            return 0.0
        numeric_items = [float(x) for x in spatial_violations if isinstance(x, (int, float))]
        if len(numeric_items) == len(spatial_violations):
            return float(sum(max(0.0, x) for x in numeric_items))
        return 0.25 * float(len(spatial_violations))
    return 0.0


def compute_lyapunov_error(
    settle_telemetry: Any,
    spatial_violations: Any,
    visual_critic_score: float,
    weights: tuple[float, float, float] = (0.4, 0.4, 0.2),
) -> float:
    """Compute composite Lyapunov error E(k) for scene synthesis trajectory step k.

    Formula:
        E(k) = alpha * ||v_settle|| + beta * d_exclusion(x_k) + gamma * (1 - S_vlm)

    Args:
        settle_telemetry: Scalar velocity norm, velocity vector, or telemetry dict.
        spatial_violations: Scalar penetration/exclusion distance, violation list, or oracle dict.
        visual_critic_score: Step-0 VLM visual critic score S_vlm in [0.0, 1.0].
        weights: Tuple of (alpha, beta, gamma) non-negative weights.

    Returns:
        Non-negative scalar Lyapunov error E(k).
    """
    assert len(weights) == 3, "weights must be a 3-tuple (alpha, beta, gamma)"
    alpha, beta, gamma = float(weights[0]), float(weights[1]), float(weights[2])
    assert alpha >= 0.0 and beta >= 0.0 and gamma >= 0.0, "Lyapunov weights must be non-negative"

    v_settle = _extract_settle_velocity_norm(settle_telemetry)
    d_exclusion = _extract_spatial_exclusion_distance(spatial_violations)
    s_vlm = max(0.0, min(1.0, float(visual_critic_score)))

    error = alpha * v_settle + beta * d_exclusion + gamma * (1.0 - s_vlm)
    return float(max(0.0, round(error, 8)))


def _step_error(step: TrajectoryStep | dict[str, Any] | float | int) -> float:
    """Extract scalar Lyapunov error from a TrajectoryStep, dict, or float."""
    if isinstance(step, TrajectoryStep):
        return float(step.lyapunov_error)
    if isinstance(step, (int, float)):
        return float(step)
    if isinstance(step, dict):
        if "lyapunov_error" in step:
            return float(step["lyapunov_error"])
        if "error" in step:
            return float(step["error"])
        return compute_lyapunov_error(
            step.get("settle_telemetry", step.get("settle_velocity_norm", 0.0)),
            step.get("spatial_violations", step.get("spatial_exclusion_error", 0.0)),
            step.get("visual_critic_score", 1.0),
        )
    raise TypeError(f"Unsupported trajectory step type: {type(step)!r}")


def evaluate_trajectory_contraction(
    history: list[TrajectoryStep | dict[str, Any] | float],
    *,
    stagnation_tol: float = 1e-3,
) -> ContractionResult:
    """Evaluate Lyapunov contraction rate Delta E(k) = E(k-1) - E(k) over trajectory history.

    Args:
        history: Ordered list of TrajectoryStep instances (or dicts/floats) from step 0..k.
        stagnation_tol: Minimum positive error reduction required to classify as converging.

    Returns:
        ContractionResult containing delta_error, is_contracting, and regime.
    """
    if not history:
        return ContractionResult(
            delta_error=0.0,
            is_contracting=True,
            regime="converging",
            error_before=0.0,
            error_after=0.0,
        )

    if len(history) == 1:
        err0 = _step_error(history[0])
        return ContractionResult(
            delta_error=0.0,
            is_contracting=True,
            regime="converging",
            error_before=err0,
            error_after=err0,
        )

    error_before = _step_error(history[-2])
    error_after = _step_error(history[-1])
    delta_error = float(round(error_before - error_after, 8))

    if delta_error > stagnation_tol:
        return ContractionResult(
            delta_error=delta_error,
            is_contracting=True,
            regime="converging",
            error_before=error_before,
            error_after=error_after,
        )
    if abs(delta_error) <= stagnation_tol:
        # Special case: if error is already zero and stays zero, it has converged
        if error_after <= stagnation_tol:
            return ContractionResult(
                delta_error=delta_error,
                is_contracting=True,
                regime="converging",
                error_before=error_before,
                error_after=error_after,
            )
        return ContractionResult(
            delta_error=delta_error,
            is_contracting=False,
            regime="stagnating",
            error_before=error_before,
            error_after=error_after,
        )
    return ContractionResult(
        delta_error=delta_error,
        is_contracting=False,
        regime="diverging",
        error_before=error_before,
        error_after=error_after,
    )


def _infer_spec_clearance_m(scene_spec: Any) -> float | None:
    """Compute minimum pairwise XY object clearance from a scene spec if available."""
    if scene_spec is None:
        return None
    objects = None
    if isinstance(scene_spec, dict):
        objects = scene_spec.get("objects")
    elif hasattr(scene_spec, "objects"):
        objects = getattr(scene_spec, "objects")
    if not objects or not isinstance(objects, (list, tuple)) or len(objects) < 2:
        return None

    positions: list[tuple[float, float]] = []
    for obj in objects:
        params = obj.get("params", {}) if isinstance(obj, dict) else getattr(obj, "params", {}) or {}
        pose = params.get("initial_pose", {}) if isinstance(params, dict) else {}
        xyz = pose.get("position_xyz") if isinstance(pose, dict) else None
        if isinstance(xyz, (list, tuple)) and len(xyz) >= 2:
            positions.append((float(xyz[0]), float(xyz[1])))

    if len(positions) < 2:
        return None

    min_dist = float("inf")
    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            d = math.hypot(positions[i][0] - positions[j][0], positions[i][1] - positions[j][1])
            min_dist = min(min_dist, d)
    return min_dist if math.isfinite(min_dist) else None


def estimate_causal_horizon(
    scene_spec: Any,
    physical_telemetry: dict[str, Any] | None,
    contraction_result: ContractionResult | dict[str, Any],
    *,
    max_ceiling: int | None = None,
    high_contact_force_threshold_n: float = 50.0,
) -> int:
    """Estimate the causal planning horizon H*(s_k) from telemetry and Lyapunov contraction.

    Rules:
        1. If regime == "diverging" or topological collision: return 0 (topological restart / stop).
        2. If clearance < 0.05m or high contact forces (or stagnating regime): return 1
           (narrow lightcone; force 1-step settle + visual audit).
        3. If smooth quasi-static relaxation (delta_error > 0.15 and clearance > 0.10m): return 3
           (deep lightcone; allow multi-step factor graph relaxation).
        4. Otherwise (moderate contraction with safe clearance): return 2.

    Args:
        scene_spec: Candidate ArenaEnvGraphSpec or scene dict.
        physical_telemetry: Telemetry dict with clearance, contact forces, and collision flags.
        contraction_result: ContractionResult (or dict) from evaluate_trajectory_contraction.
        max_ceiling: Optional immutable outer ceiling H_max to clamp the returned horizon.
        high_contact_force_threshold_n: Contact force threshold (N) above which lightcone narrows to 1.

    Returns:
        Integer causal planning horizon H*(s_k) >= 0.
    """
    telemetry = dict(physical_telemetry or {})
    if isinstance(contraction_result, dict):
        contraction = ContractionResult.model_validate(contraction_result)
    else:
        contraction = contraction_result

    topological_collision = bool(
        telemetry.get("topological_collision", False)
        or float(telemetry.get("obb_penetration", 0.0) or 0.0) > 0.02
    )
    if contraction.regime == "diverging" or topological_collision:
        return 0

    spec_clearance = _infer_spec_clearance_m(scene_spec)
    default_clearance = spec_clearance if spec_clearance is not None else 0.15
    clearance_m = float(
        telemetry.get(
            "min_clearance_m",
            telemetry.get("clearance_m", telemetry.get("clearance", default_clearance)),
        )
    )
    contact_force_n = float(
        telemetry.get(
            "max_contact_force_n",
            telemetry.get("contact_force_n", telemetry.get("contact_force", 0.0)),
        )
    )

    if (
        clearance_m < 0.05
        or contact_force_n >= high_contact_force_threshold_n
        or contraction.regime == "stagnating"
    ):
        horizon = 1
    elif contraction.delta_error > 0.15 and clearance_m > 0.10:
        horizon = 3
    else:
        horizon = 2

    if max_ceiling is not None:
        horizon = max(0, min(horizon, int(max_ceiling)))
    return int(horizon)


@dataclass
class _CausalEstimatorHandle:
    """Lightweight handle for WorkerPort protocol compliance on Job J7."""

    worker_id: str
    attempt_token: str | None = None
    request_payload: dict[str, Any] | None = None


class CausalLightconeEstimator:
    """Job J7 WorkerPort-compatible Causal Lightcone & Lyapunov Estimator."""

    def __init__(
        self,
        *,
        weights: tuple[float, float, float] = (0.4, 0.4, 0.2),
        max_ceiling: int | None = None,
    ) -> None:
        self.weights = weights
        self.max_ceiling = max_ceiling

    def evaluate(
        self,
        *,
        scene_spec: Any = None,
        physical_telemetry: dict[str, Any] | None = None,
        spatial_violations: Any = None,
        visual_critic_score: float = 1.0,
        history: list[TrajectoryStep | dict[str, Any] | float] | None = None,
        max_ceiling: int | None = None,
    ) -> CausalHorizonReceipt:
        """Compute Lyapunov error, trajectory contraction, and causal horizon receipt."""
        current_error = compute_lyapunov_error(
            physical_telemetry,
            spatial_violations,
            visual_critic_score,
            weights=self.weights,
        )
        effective_history = list(history or [])
        effective_history.append(
            TrajectoryStep(
                step_index=len(effective_history),
                lyapunov_error=current_error,
                settle_velocity_norm=_extract_settle_velocity_norm(physical_telemetry),
                spatial_exclusion_error=_extract_spatial_exclusion_distance(spatial_violations),
                visual_critic_score=visual_critic_score,
            )
        )
        contraction = evaluate_trajectory_contraction(effective_history)
        ceiling = max_ceiling if max_ceiling is not None else self.max_ceiling
        horizon = estimate_causal_horizon(
            scene_spec,
            physical_telemetry,
            contraction,
            max_ceiling=ceiling,
        )
        if horizon == 0:
            causal_status: Literal["in_cone", "narrow_cone", "collapsed"] = "collapsed"
            reason = (
                f"Causal lightcone collapsed (regime={contraction.regime}, "
                f"delta_E={contraction.delta_error:.4f}, E={current_error:.4f})"
            )
        elif horizon == 1:
            causal_status = "narrow_cone"
            reason = (
                f"Narrow causal lightcone H*=1 (regime={contraction.regime}, "
                f"delta_E={contraction.delta_error:.4f}, E={current_error:.4f})"
            )
        else:
            causal_status = "in_cone"
            reason = (
                f"Trajectory contracting within causal lightcone H*={horizon} "
                f"(delta_E={contraction.delta_error:.4f}, E={current_error:.4f})"
            )
        return CausalHorizonReceipt(
            horizon_H=horizon,
            delta_E=contraction.delta_error,
            regime=contraction.regime,
            lyapunov_error=current_error,
            causal_status=causal_status,
            reason=reason,
        )

    def prepare(self, fence: Any) -> tuple[_CausalEstimatorHandle, dict[str, Any]]:
        """Prepare a WorkerPort handle for Job J7."""
        wid = f"causal-estimator-{uuid.uuid4().hex[:8]}"
        token = getattr(fence, "attempt_token", None)
        handle = _CausalEstimatorHandle(worker_id=wid, attempt_token=token)
        return handle, {"worker_id": wid}

    def send(self, handle: _CausalEstimatorHandle, request: dict[str, Any]) -> None:
        """Accept causal estimation request payload."""
        handle.request_payload = dict(request)

    def receive(self, handle: _CausalEstimatorHandle, deadline: float | None = None) -> dict[str, Any]:
        """Execute causal estimation and return serialized CausalHorizonReceipt."""
        req = handle.request_payload or {}
        receipt = self.evaluate(
            scene_spec=req.get("scene_spec"),
            physical_telemetry=req.get("physical_telemetry"),
            spatial_violations=req.get("spatial_violations"),
            visual_critic_score=float(req.get("visual_critic_score", 1.0)),
            history=req.get("history"),
            max_ceiling=req.get("max_ceiling", self.max_ceiling),
        )
        return receipt.model_dump(mode="json")

    def stop_owned(self, handle: _CausalEstimatorHandle) -> dict[str, Any]:
        """Release WorkerPort handle cleanly."""
        handle.request_payload = None
        return {"worker_id": handle.worker_id, "stopped": True}
