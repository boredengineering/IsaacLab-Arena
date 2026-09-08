# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Continuous spatial factor energies and deterministic or stochastic Adam relaxation."""

from __future__ import annotations

import math
import numpy as np
import torch
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VariableNode:
    """A continuous random variable node representing an entity pose in SE(2) x R."""

    name: str
    mu: torch.Tensor  # Shape (3,) or (4,) -> [x, y, z] or [x, y, z, yaw_rad]
    cov: torch.Tensor = field(default_factory=lambda: torch.eye(3))
    is_fixed: bool = False
    bounds: tuple[float, float, float, float] | None = None  # (xmin, xmax, ymin, ymax)


@dataclass
class FactorGraphRelaxationResult:
    """Result of factor graph relaxation including final poses and residual energies."""

    converged: bool
    iterations: int
    total_energy: float
    poses: dict[str, list[float]]  # {node_name: [x, y, z, yaw_deg]}
    factor_energies: dict[str, float]
    conflicting_factors: list[str]


class SpatialFactorGraph:
    """Continuous Factor Graph for resolving coupled spatial constraints and loopy dependencies."""

    def __init__(self, device: str = "cpu"):
        self.device = torch.device(device)
        self.variables: dict[str, VariableNode] = {}
        self.factors: list[dict[str, Any]] = []

    def _finite_tensor(self, values: Any, name: str) -> torch.Tensor:
        """Convert numerical inputs while rejecting nonfinite float32 representations."""
        tensor = torch.tensor(values, dtype=torch.float32, device=self.device)
        assert torch.isfinite(tensor).all(), f"{name} must contain finite float32 values"
        return tensor

    @staticmethod
    def _nonnegative(value: float, name: str) -> None:
        """Validate a finite, nonnegative scalar parameter."""
        assert math.isfinite(value) and value >= 0.0, f"{name} must be finite and nonnegative"

    @staticmethod
    def _validate_relaxation(max_iters: int, lr: float, energy_tol: float) -> None:
        """Validate optimizer controls before any early return or state mutation."""
        assert (
            isinstance(max_iters, int) and not isinstance(max_iters, bool) and max_iters >= 0
        ), "max_iters must be a nonnegative integer"
        assert math.isfinite(lr) and lr > 0.0, "lr must be finite and positive"
        SpatialFactorGraph._nonnegative(energy_tol, "energy_tol")

    def add_variable(
        self,
        name: str,
        initial_pose: list[float] | tuple[float, ...],
        is_fixed: bool = False,
        bounds: tuple[float, float, float, float] | None = None,
    ) -> None:
        """Register an entity pose as a continuous variable node."""
        init_tensor = self._finite_tensor(initial_pose, "initial_pose")
        assert init_tensor.ndim == 1 and init_tensor.numel() in (3, 4), "initial_pose must have 3 or 4 coordinates"
        if bounds is not None:
            bound_tensor = self._finite_tensor(bounds, "bounds")
            assert bound_tensor.shape == (4,), "bounds must be (xmin, xmax, ymin, ymax)"
            assert bounds[0] <= bounds[1] and bounds[2] <= bounds[3], "bounds must be ordered"
        if not is_fixed:
            init_tensor.requires_grad_(True)
        self.variables[name] = VariableNode(
            name=name,
            mu=init_tensor,
            is_fixed=is_fixed,
            bounds=bounds,
        )

    def add_support_factor(
        self,
        child_name: str,
        parent_name: str,
        surface_bounds: list[float] | tuple[float, ...],
        edge_margin: float = 0.05,
        weight: float = 150.0,
        factor_id: str | None = None,
    ) -> str:
        """Add a support containment factor keeping child within parent surface [xmin, xmax, ymin, ymax, z_deck]."""
        self._nonnegative(weight, "weight")
        self._nonnegative(edge_margin, "edge_margin")
        surface = self._finite_tensor(surface_bounds, "surface_bounds")
        assert surface.shape == (5,), "surface_bounds must have 5 coordinates"
        assert surface_bounds[0] + edge_margin <= surface_bounds[1] - edge_margin, "empty support X interval"
        assert surface_bounds[2] + edge_margin <= surface_bounds[3] - edge_margin, "empty support Y interval"
        fid = factor_id or f"psi_support_{child_name}_on_{parent_name}"
        self.factors.append({
            "id": fid,
            "type": "support",
            "child": child_name,
            "parent": parent_name,
            "bounds": surface,
            "margin": float(edge_margin),
            "weight": float(weight),
        })
        return fid

    def add_reachability_factor(
        self,
        robot_name: str,
        target_name: str,
        target_distance: float = 0.65,
        tolerance: float = 0.18,
        weight: float = 80.0,
        factor_id: str | None = None,
    ) -> str:
        """Add a kinematic reachability factor keeping robot base within dexterity envelope of target."""
        self._nonnegative(weight, "weight")
        self._nonnegative(target_distance, "target_distance")
        self._nonnegative(tolerance, "tolerance")
        fid = factor_id or f"psi_reach_{robot_name}_to_{target_name}"
        self.factors.append({
            "id": fid,
            "type": "reach",
            "robot": robot_name,
            "target": target_name,
            "d_opt": float(target_distance),
            "tol": float(tolerance),
            "weight": float(weight),
        })
        return fid

    def add_clearance_factor(
        self,
        entity_a: str,
        entity_b: str,
        min_distance: float = 0.22,
        weight: float = 200.0,
        factor_id: str | None = None,
    ) -> str:
        """Add a collision avoidance factor repelling entity_a and entity_b."""
        self._nonnegative(weight, "weight")
        self._nonnegative(min_distance, "min_distance")
        fid = factor_id or f"psi_clear_{entity_a}_{entity_b}"
        self.factors.append({
            "id": fid,
            "type": "clearance",
            "a": entity_a,
            "b": entity_b,
            "min_dist": float(min_distance),
            "weight": float(weight),
        })
        return fid

    def add_ground_factor(
        self,
        entity_name: str,
        floor_z: float = 0.0,
        weight: float = 300.0,
        factor_id: str | None = None,
    ) -> str:
        """Add a ground snapping factor locking z-elevation to floor terrain."""
        self._nonnegative(weight, "weight")
        assert math.isfinite(floor_z), "floor_z must be finite"
        fid = factor_id or f"psi_ground_{entity_name}"
        self.factors.append({
            "id": fid,
            "type": "ground",
            "entity": entity_name,
            "floor_z": float(floor_z),
            "weight": float(weight),
        })
        return fid

    def add_facing_factor(
        self,
        subject_name: str,
        target_name: str,
        weight: float = 40.0,
        factor_id: str | None = None,
    ) -> str:
        """Add an orientation factor directing subject's forward heading toward target."""
        self._nonnegative(weight, "weight")
        fid = factor_id or f"psi_facing_{subject_name}_to_{target_name}"
        self.factors.append({
            "id": fid,
            "type": "facing",
            "subject": subject_name,
            "target": target_name,
            "weight": float(weight),
        })
        return fid

    def add_empirical_reach_likelihood_factor(
        self,
        robot_name: str,
        target_name: str,
        measured_reach_delta: tuple[float, float, float] | list[float],
        sigma: tuple[float, float, float] | list[float] = (0.015, 0.015, 0.015),
        weight: float = 250.0,
        factor_id: str | None = None,
    ) -> str:
        """Add empirical reach error likelihood factor from simulation telemetry.

        Shifts the target variable node toward the verified reach basin of the policy.
        """
        self._nonnegative(weight, "weight")
        delta_tensor = self._finite_tensor(measured_reach_delta, "measured_reach_delta")
        sigma_tensor = self._finite_tensor(sigma, "sigma")
        assert delta_tensor.shape == (3,), "measured_reach_delta must have 3 coordinates"
        assert sigma_tensor.shape == (3,) and (sigma_tensor > 0).all(), "sigma must have 3 positive coordinates"
        fid = factor_id or f"psi_empirical_reach_{robot_name}_to_{target_name}"
        # Target should shift by measured_reach_delta (hand_pos_minus_obj_pos)
        target_var = self.variables[target_name]
        init_pos = target_var.mu.detach().clone()[:3]
        target_opt = init_pos + delta_tensor
        assert torch.isfinite(target_opt).all(), "empirical optimal position must be finite"

        self.factors.append({
            "id": fid,
            "type": "empirical_reach",
            "robot": robot_name,
            "target": target_name,
            "optimal_pos": target_opt,
            "sigma": sigma_tensor,
            "weight": float(weight),
        })
        return fid

    def compute_energies(self) -> tuple[torch.Tensor, dict[str, float]]:
        """Compute total potential energy and per-factor energy breakdown."""
        total_energy = torch.tensor(0.0, device=self.device)
        factor_energies: dict[str, float] = {}

        for factor in self.factors:
            ftype = factor["type"]
            fid = factor["id"]
            e = torch.tensor(0.0, device=self.device)

            if ftype == "empirical_reach":
                target = self.variables[factor["target"]]
                target_pos_opt = factor["optimal_pos"]
                sigma = factor["sigma"]
                diff = (target.mu[:3] - target_pos_opt[:3]) / sigma
                e = factor["weight"] * torch.sum(diff**2)

            elif ftype == "support":
                child = self.variables[factor["child"]]
                parent = self.variables[factor["parent"]]
                bounds = factor["bounds"]
                margin = factor["margin"]

                rel_x = child.mu[0] - parent.mu[0]
                rel_y = child.mu[1] - parent.mu[1]

                # Support polygon boundary penalties
                min_x = bounds[0] + margin
                max_x = bounds[1] - margin
                min_y = bounds[2] + margin
                max_y = bounds[3] - margin

                x_viol = torch.relu(min_x - rel_x) + torch.relu(rel_x - max_x)
                y_viol = torch.relu(min_y - rel_y) + torch.relu(rel_y - max_y)
                z_target = parent.mu[2] + bounds[4]
                z_viol = torch.abs(child.mu[2] - z_target)

                e = factor["weight"] * (x_viol**2 + y_viol**2 + 5.0 * (z_viol**2))

            elif ftype == "reach":
                robot = self.variables[factor["robot"]]
                target = self.variables[factor["target"]]
                dist_xy = torch.norm(robot.mu[:2] - target.mu[:2])
                reach_viol = torch.relu(torch.abs(dist_xy - factor["d_opt"]) - factor["tol"])
                e = factor["weight"] * (reach_viol**2)

            elif ftype == "clearance":
                a = self.variables[factor["a"]]
                b = self.variables[factor["b"]]
                dist_xy = torch.norm(a.mu[:2] - b.mu[:2])
                col_viol = torch.relu(factor["min_dist"] - dist_xy)
                e = factor["weight"] * (col_viol**2)

            elif ftype == "ground":
                entity = self.variables[factor["entity"]]
                z_viol = torch.abs(entity.mu[2] - factor["floor_z"])
                e = factor["weight"] * (z_viol**2)

            elif ftype == "facing":
                subject = self.variables[factor["subject"]]
                target = self.variables[factor["target"]]
                dx = target.mu[0] - subject.mu[0]
                dy = target.mu[1] - subject.mu[1]
                target_yaw = torch.atan2(dy, dx)
                if subject.mu.shape[0] >= 4:
                    current_yaw = subject.mu[3]
                    yaw_diff = torch.sin(current_yaw - target_yaw)
                    e = factor["weight"] * (yaw_diff**2)

            total_energy = total_energy + e
            factor_energies[fid] = float(e.detach().cpu().item())

        return total_energy, factor_energies

    def relax(
        self,
        max_iters: int = 120,
        lr: float = 0.04,
        momentum: float = 0.5,
        energy_tol: float = 1e-3,
    ) -> FactorGraphRelaxationResult:
        """Minimize factor energy with Adam, projecting free poses onto their XY bounds.

        Args:
            max_iters: Maximum number of updates; zero evaluates the bounded initial state.
            lr: Adam learning rate.
            momentum: Adam's first-moment decay coefficient.
            energy_tol: Early-stop threshold; reported convergence retains energy < 0.1.

        Returns:
            Best evaluated state, restored in the graph, with matching unrounded energies,
            poses rounded to four decimals (yaw in degrees), and actual update count.
            Nonfinite updates or gradients stop optimization and retain the best finite state.
        """
        self._validate_relaxation(max_iters, lr, energy_tol)
        assert math.isfinite(momentum) and 0.0 <= momentum < 1.0, "momentum must be in [0, 1)"
        optim_vars = [v.mu for v in self.variables.values() if not v.is_fixed]
        if not optim_vars:
            return self._current_result(iterations=0)

        optimizer = torch.optim.Adam(optim_vars, lr=lr, betas=(momentum, 0.999))
        return self._relax_adam(optimizer, max_iters, lr, energy_tol)

    def _relax_adam(
        self,
        optimizer: torch.optim.Optimizer,
        max_iters: int,
        lr: float,
        energy_tol: float,
        temperature: float = 0.0,
        cooling_rate: float = 1.0,
        generator: torch.Generator | None = None,
    ) -> FactorGraphRelaxationResult:
        """Minimize energy and restore the best evaluated state, including the last update."""
        self._project_bounds()
        best_energy = float("inf")
        best_poses = {name: v.mu.detach().clone() for name, v in self.variables.items()}
        iterations = 0
        for step in range(max_iters + 1):
            optimizer.zero_grad()
            total_energy, _ = self.compute_energies()
            energy = float(total_energy.detach().cpu().item())
            finite_state = math.isfinite(energy) and all(torch.isfinite(v.mu).all() for v in self.variables.values())
            assert step != 0 or finite_state, "initial poses and energy must be finite"
            if not finite_state:
                break
            if energy < best_energy:
                best_energy = energy
                best_poses = {name: v.mu.detach().clone() for name, v in self.variables.items()}
            if step == max_iters or energy < energy_tol or not total_energy.requires_grad:
                break
            total_energy.backward()
            if temperature > 0.0:
                with torch.no_grad():
                    for v in self.variables.values():
                        if not v.is_fixed and v.mu.grad is not None:
                            noise = torch.randn(v.mu.shape, dtype=v.mu.dtype, device=v.mu.device, generator=generator)
                            v.mu.grad.add_(noise * math.sqrt(2.0 * lr * temperature))
            if any(
                v.mu.grad is not None and not torch.isfinite(v.mu.grad).all()
                for v in self.variables.values()
                if not v.is_fixed
            ):
                break
            optimizer.step()
            self._project_bounds()
            temperature *= cooling_rate
            iterations = step + 1

        with torch.no_grad():
            for name, v in self.variables.items():
                if not v.is_fixed:
                    v.mu.copy_(best_poses[name])
        optimizer.zero_grad()
        return self._current_result(iterations)

    def _project_bounds(self) -> None:
        """Project free XY coordinates without modifying fixed anchors or yaw radians."""
        with torch.no_grad():
            for v in self.variables.values():
                if not v.is_fixed and v.bounds is not None:
                    xmin, xmax, ymin, ymax = v.bounds
                    v.mu[0].clamp_(xmin, xmax)
                    v.mu[1].clamp_(ymin, ymax)

    def _current_result(self, iterations: int) -> FactorGraphRelaxationResult:
        """Report energies and formatted poses from the same graph state."""
        total, energies = self.compute_energies()
        energy = float(total.detach().cpu().item())
        assert math.isfinite(energy) and all(
            torch.isfinite(v.mu).all() for v in self.variables.values()
        ), "result poses and energy must be finite"
        return FactorGraphRelaxationResult(
            converged=energy < 0.1,
            iterations=iterations,
            total_energy=energy,
            poses=self._format_poses({name: v.mu.detach().cpu() for name, v in self.variables.items()}),
            factor_energies=energies,
            conflicting_factors=[fid for fid, value in energies.items() if value > 0.05],
        )

    def _format_poses(self, poses: dict[str, torch.Tensor]) -> dict[str, list[float]]:
        """Format tensor poses to degrees and rounded float coordinates."""
        formatted: dict[str, list[float]] = {}
        for name, pose_tensor in poses.items():
            arr = pose_tensor.numpy().tolist()
            if len(arr) == 3:
                arr.append(0.0)
            elif len(arr) >= 4:
                arr[3] = float(np.degrees(arr[3]))
            formatted[name] = [float(round(val, 4)) for val in arr]
        return formatted

    def relax_stochastic(
        self,
        max_iters: int = 150,
        lr: float = 0.03,
        temperature: float = 0.10,
        cooling_rate: float = 0.98,
        energy_tol: float = 1e-3,
        seed: int | None = None,
    ) -> FactorGraphRelaxationResult:
        """Minimize energy with annealed gradient-noise Adam and XY-bound projection.

        At step t, Adam receives g + sqrt(2 * lr * temperature * cooling_rate**t)
        times independent standard Gaussian noise. This is a heuristic optimizer,
        not Langevin dynamics, belief propagation, or posterior sampling.

        Args:
            max_iters: Maximum number of optimizer updates; zero evaluates the initial state.
            lr: Adam learning rate.
            temperature: Initial gradient-noise scale parameter; zero disables noise.
            cooling_rate: Multiplicative decay of temperature per update.
            energy_tol: Early-stop energy threshold (reported convergence remains energy < 0.1).
            seed: Local generator seed; None uses local nondeterministic seeding. Neither
                choice changes global torch random state.

        Returns:
            Best evaluated state with matching energies and poses formatted in degrees.
        """
        self._validate_relaxation(max_iters, lr, energy_tol)
        self._nonnegative(temperature, "temperature")
        assert math.isfinite(cooling_rate) and 0.0 <= cooling_rate <= 1.0, "cooling_rate must be in [0, 1]"
        assert seed is None or (
            isinstance(seed, int) and not isinstance(seed, bool) and 0 <= seed < 2**64
        ), "seed must be an integer in [0, 2**64) or None"
        optim_vars = [v.mu for v in self.variables.values() if not v.is_fixed]
        if not optim_vars:
            return self._current_result(iterations=0)

        optimizer = torch.optim.Adam(optim_vars, lr=lr)
        generator = torch.Generator(device=self.device)
        if seed is None:
            generator.seed()
        else:
            generator.manual_seed(seed)
        return self._relax_adam(optimizer, max_iters, lr, energy_tol, temperature, cooling_rate, generator)
