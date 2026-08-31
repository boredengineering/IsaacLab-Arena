# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Continuous Spatial Factor Graph & Dynamic Loopy Belief Propagation (LBP) Relaxation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import numpy as np
import torch


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

    def add_variable(
        self,
        name: str,
        initial_pose: list[float] | tuple[float, ...],
        is_fixed: bool = False,
        bounds: tuple[float, float, float, float] | None = None,
    ) -> None:
        """Register an entity pose as a continuous variable node."""
        init_tensor = torch.tensor(initial_pose, dtype=torch.float32, device=self.device)
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
        fid = factor_id or f"psi_support_{child_name}_on_{parent_name}"
        self.factors.append({
            "id": fid,
            "type": "support",
            "child": child_name,
            "parent": parent_name,
            "bounds": torch.tensor(surface_bounds, dtype=torch.float32, device=self.device),
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
        fid = factor_id or f"psi_facing_{subject_name}_to_{target_name}"
        self.factors.append({
            "id": fid,
            "type": "facing",
            "subject": subject_name,
            "target": target_name,
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

            if ftype == "support":
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
        """Perform continuous Loopy Belief Propagation relaxation via damped gradient energy minimization."""
        optim_vars = [v.mu for v in self.variables.values() if not v.is_fixed]
        if not optim_vars:
            _, factor_energies = self.compute_energies()
            return FactorGraphRelaxationResult(
                converged=True,
                iterations=0,
                total_energy=0.0,
                poses={name: v.mu.detach().cpu().tolist() for name, v in self.variables.items()},
                factor_energies=factor_energies,
                conflicting_factors=[],
            )

        optimizer = torch.optim.Adam(optim_vars, lr=lr, betas=(momentum, 0.999))
        best_energy = float("inf")
        best_poses = {name: v.mu.detach().cpu().clone() for name, v in self.variables.items()}
        final_factor_energies: dict[str, float] = {}

        for step in range(max_iters):
            optimizer.zero_grad()
            total_energy, factor_energies = self.compute_energies()
            final_factor_energies = factor_energies

            energy_val = float(total_energy.detach().cpu().item())
            if energy_val < best_energy:
                best_energy = energy_val
                best_poses = {name: v.mu.detach().cpu().clone() for name, v in self.variables.items()}

            if energy_val < energy_tol:
                break

            total_energy.backward()
            optimizer.step()

        formatted_poses: dict[str, list[float]] = {}
        for name, pose_tensor in best_poses.items():
            arr = pose_tensor.numpy().tolist()
            if len(arr) == 3:
                arr.append(0.0)
            elif len(arr) >= 4:
                arr[3] = float(np.degrees(arr[3]))
            formatted_poses[name] = [float(round(val, 4)) for val in arr]

        conflicts = [fid for fid, fe in final_factor_energies.items() if fe > 0.05]
        converged = best_energy < 0.1

        return FactorGraphRelaxationResult(
            converged=converged,
            iterations=step + 1,
            total_energy=float(round(best_energy, 4)),
            poses=formatted_poses,
            factor_energies=final_factor_energies,
            conflicting_factors=conflicts,
        )
