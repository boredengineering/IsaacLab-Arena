# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for PROV-O telemetry serialization."""

from __future__ import annotations

from pathlib import Path
import rdflib
import pytest

from isaaclab_arena.evaluation.telemetry_to_prov import record_eval_telemetry_to_prov


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

    # Parse and query with rdflib
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
