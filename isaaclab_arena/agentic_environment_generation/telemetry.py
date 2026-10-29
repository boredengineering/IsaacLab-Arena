# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Transparent, tier-aware Active Bayesian Inference telemetry and summary reporting."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ActiveInferenceTelemetry:
    """Telemetry, iteration tracking, token metrics, and critic tier statuses for graph generation."""

    model: str = ""
    total_llm_calls: int = 0
    repair_iterations: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_s: float = 0.0
    converged: bool = True
    shacl_passed: bool = True
    geometry_passed: bool = True
    stagnation_detected: bool = False
    traces: list[str] = field(default_factory=list)
    shacl_status: str = "Passed"
    spatial_geometry_status: str = "Passed"
    visual_critic_tier: str = "tier_3_geometric_oracle"
    visual_critic_status: str = "Bypassed (No Frames - Tier 3 Fallback)"
    physics_preflight_status: str = "Heuristic Only (Pure Python)"
    factor_relaxation_status: str = "Converged"
    factor_relaxation_residual: float = 0.0
    verification_grade: str = "PROVISIONAL: Unverified Settle"

    def render_summary_card(self) -> str:
        """Render an ANSI / plain-text telemetry summary card with explicit critic tier transparency."""
        status_symbol = "🟢 Converged (Variational Free Energy ≈ 0)" if self.converged else "🟡 Fallback Applied"
        shacl_sym = "✅ Passed" if self.shacl_passed else "❌ Violation"
        geom_sym = "✅ Passed" if self.geometry_passed else "❌ Violation"
        total_calls = int(self.total_llm_calls) if isinstance(self.total_llm_calls, (int, float)) else 0
        repair_iters = int(self.repair_iterations) if isinstance(self.repair_iterations, (int, float)) else 0
        tot_tok = int(self.total_tokens) if isinstance(self.total_tokens, (int, float)) else 0
        p_tok = int(self.prompt_tokens) if isinstance(self.prompt_tokens, (int, float)) else 0
        c_tok = int(self.completion_tokens) if isinstance(self.completion_tokens, (int, float)) else 0
        dur_s = float(self.duration_s) if isinstance(self.duration_s, (int, float)) else 0.0
        avg_latency = (dur_s / total_calls) if total_calls > 0 else 0.0
        res_val = (
            float(self.factor_relaxation_residual)
            if isinstance(self.factor_relaxation_residual, (int, float))
            else 0.0
        )

        lines = [
            "======================================================================",
            "  🤖 Active Bayesian Inference & Graph Generation Telemetry",
            "======================================================================",
            f"• Model:               {self.model}",
            f"• Convergence Status:  {status_symbol}",
            f"• Total LLM Calls:     {total_calls}",
            f"• Repair Iterations:   {repair_iters}",
            f"• Token Consumption:   {tot_tok:,} tokens ({p_tok:,} prompt, {c_tok:,} completion)",
            f"• Wall-Clock Latency:  {dur_s:.2f}s (avg {avg_latency:.2f}s / call)",
            f"• Physical Invariants: SHACL-star: {shacl_sym} | Spatial Geometry: {geom_sym}",
            "----------------------------------------------------------------------",
            f"• Semantic Invariants (SHACL):      {self.shacl_status}",
            f"• Spatial Clearance & Containment:  {self.spatial_geometry_status}",
            f"• Factor Graph Relaxation:          {self.factor_relaxation_status} (residual={res_val:.4f})",
            f"• Visual Scene Critic:              {self.visual_critic_status} [{self.visual_critic_tier}]",
            f"• Physical Preflight:               {self.physics_preflight_status}",
            f"• Verification Grade:               {self.verification_grade}",
            "======================================================================",
        ]
        return "\n".join(lines)
