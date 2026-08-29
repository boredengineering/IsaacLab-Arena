# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for PROV-O telemetry serialization and stationarity gating."""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pytest
import rdflib
import torch

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.environment_spec.arena_env_graph_types import (
    AssetSpec,
    CompositeTaskSpec,
    ContinuousIntervalSpec,
    ReifiedRelationSpec,
    TaskCompositionType,
    TaskSpec,
)
from isaaclab_arena.evaluation.telemetry_to_prov import (
    StatisticalStationarityEvaluator,
    VectorizedTelemetryBuffer,
    attribute_simulation_telemetry_to_reifiers,
    record_eval_telemetry_to_prov,
)


def test_record_eval_telemetry_to_prov(tmp_path: Path):
    metrics = {
        "mean_latency_ms": 18.2,
        "completed_steps": 1200,
        "success_rate": 1.0,
    }

    out_file = record_eval_telemetry_to_prov(
        output_dir=tmp_path,
        env_name="galileo_g1_box_pnp_agentic",
        metrics=metrics,
        policy_name="gr00t_checkpoint_20000",
        task_success=True,
    )

    assert out_file.exists()
    assert out_file.name == "eval_telemetry.ttl"

    g = rdflib.Graph()
    g.parse(str(out_file), format="turtle")

    query = """
    PREFIX arena: <https://isaac-sim.github.io/arena/schema#>
    PREFIX prov:  <http://www.w3.org/ns/prov#>
    SELECT ?run ?activity ?success ?latency
    WHERE {
        ?run a arena:EvaluationRun, prov:Entity ;
             prov:wasGeneratedBy ?activity ;
             arena:taskSuccess ?success ;
             arena:metric_mean_latency_ms ?latency .
    }
    """
    rows = list(g.query(query))
    assert len(rows) == 1
    row = rows[0]
    assert str(row.success).lower() == "true"
    assert abs(float(row.latency) - 18.2) < 1e-3


def test_vectorized_telemetry_buffer_stepping():
    """Verify lock-free tensor stepping across vectorized environments."""
    num_envs = 64
    buffer = VectorizedTelemetryBuffer(num_envs=num_envs, buffer_size=100, device="cpu")

    # Step 50 times with random drift and terminal events
    for step in range(50):
        drifts = torch.full((num_envs,), float(step) * 0.001)
        terminals = torch.zeros(num_envs, dtype=torch.bool)
        if step == 25:
            terminals[0] = True
        buffer.record_step_vectorized(drift_mags=drifts, is_terminal=terminals)

    assert buffer.head == 50
    drift_np, _, term_np = buffer.extract_recent_window_numpy(window_size=30)
    assert drift_np.shape == (30, num_envs)
    assert term_np.shape == (30, num_envs)
    assert np.any(term_np[:, 0])


def test_statistical_stationarity_evaluator():
    """Verify that actuator limit-cycle jitter is detected via stationarity testing."""
    t = np.linspace(0, 1, 100)
    # 1. Smooth nominal physical settle
    smooth_jitter = 0.5 * np.exp(-5 * t) + 0.0001 * np.random.randn(100)
    smooth_drift = np.zeros(100)
    fault_smooth = StatisticalStationarityEvaluator.evaluate_stationarity_and_attribute(
        drift_trajectory=smooth_drift,
        jitter_trajectory=smooth_jitter,
        reifier_id="reifier_nominal",
    )
    assert fault_smooth is None, "Smooth settle should pass stationarity test without fault!"

    # 2. High-frequency chattering limit-cycle
    chatter_jitter = 0.5 * np.exp(-5 * t) + 0.05 * np.sin(2 * np.pi * 40 * t)
    fault_chatter = StatisticalStationarityEvaluator.evaluate_stationarity_and_attribute(
        drift_trajectory=smooth_drift,
        jitter_trajectory=chatter_jitter,
        reifier_id="reifier_chatter",
    )
    assert fault_chatter is not None
    assert fault_chatter["is_non_stationary"] is True
    assert fault_chatter["reifier_id"] == "reifier_chatter"


def test_attribute_simulation_telemetry_to_reifiers():
    """Verify that PhysX drift faults are correctly attributed to RDF 1.2 reifier IDs."""
    spec = ArenaEnvGraphSpec(
        env_name="test_fault_attribution",
        embodiment=AssetSpec(id="g1", registry_name="g1_wbc_joint"),
        background=AssetSpec(id="galileo", registry_name="galileo_locomanip"),
        objects=[
            AssetSpec(id="brown_box", registry_name="brown_box"),
        ],
        reified_relations=[
            ReifiedRelationSpec(
                reifier_id="reifier_box_shelf",
                source_id="brown_box",
                relation_type="PLACED_ON",
                target_id="galileo",
            )
        ],
        task=CompositeTaskSpec(
            composition=TaskCompositionType.ATOMIC,
            description="Pick brown box",
            subtasks=[TaskSpec(kind="PickAndPlaceTask", params={"pick_up_object": "brown_box", "destination_location": "galileo"})],
        ),
    )

    telemetry = {
        "object_drift": {"brown_box": 0.082},  # 8.2cm drift > 5cm threshold
        "ik_feasibility": 0.95,
    }

    diagnostics = attribute_simulation_telemetry_to_reifiers(telemetry, spec)
    assert len(diagnostics) == 1
    assert "reifier_box_shelf" in diagnostics[0]
    assert "Excessive settle drift" in diagnostics[0]
