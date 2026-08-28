# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Serializes evaluation rollout telemetry into W3C PROV-O RDF lineage graphs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

import rdflib
from rdflib import Literal, Namespace, RDF, XSD

ARENA = Namespace("https://isaac-sim.github.io/arena/schema#")
PROV = Namespace("http://www.w3.org/ns/prov#")
INSTANCES = Namespace("https://isaac-sim.github.io/arena/instances/")


def record_eval_telemetry_to_prov(
    output_dir: str | Path,
    env_name: str,
    metrics: dict[str, Any],
    policy_name: str | None = None,
    task_success: bool | float | None = None,
) -> Path:
    """Serialize evaluation metrics and execution context into a PROV-O Turtle graph.

    Args:
        output_dir: Directory where the evaluation artifacts are stored.
        env_name: Name of the evaluated environment graph.
        metrics: Dictionary of metric summaries (latency, steps, success rate, etc.).
        policy_name: Optional identifier or checkpoint path for the evaluated policy.
        task_success: Optional explicit task success boolean or score (0.0 - 1.0).

    Returns:
        Path to the written ``eval_telemetry.ttl`` file.
    """
    out_path = Path(output_dir) / "eval_telemetry.ttl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    g = rdflib.Graph()
    g.bind("arena", ARENA)
    g.bind("prov", PROV)
    g.bind("", INSTANCES)

    timestamp_str = datetime.now(timezone.utc).isoformat()
    run_id = f"eval_run_{int(datetime.now(timezone.utc).timestamp())}"
    eval_uri = INSTANCES[run_id]
    activity_uri = INSTANCES[f"activity_{run_id}"]
    scene_uri = INSTANCES[env_name]

    # Activity: Evaluation Execution
    g.add((activity_uri, RDF.type, PROV.Activity))
    g.add((activity_uri, PROV.endedAtTime, Literal(timestamp_str, datatype=XSD.dateTime)))
    g.add((activity_uri, PROV.used, scene_uri))

    if policy_name:
        policy_uri = INSTANCES[f"policy_{policy_name.replace('/', '_').replace('.', '_')}"]
        g.add((policy_uri, RDF.type, PROV.Entity))
        g.add((policy_uri, ARENA.modelWeightsPath, Literal(policy_name, datatype=XSD.string)))
        g.add((activity_uri, PROV.used, policy_uri))

    # Entity: EvaluationRun
    g.add((eval_uri, RDF.type, ARENA.EvaluationRun))
    g.add((eval_uri, RDF.type, PROV.Entity))
    g.add((eval_uri, PROV.wasGeneratedBy, activity_uri))
    g.add((eval_uri, ARENA.evaluatedGraph, scene_uri))

    if task_success is not None:
        if isinstance(task_success, bool):
            g.add((eval_uri, ARENA.taskSuccess, Literal(task_success, datatype=XSD.boolean)))
        else:
            g.add((eval_uri, ARENA.taskSuccess, Literal(float(task_success), datatype=XSD.float)))

    # Add numeric metrics directly
    for k, v in metrics.items():
        if isinstance(v, (int, float)):
            pred_name = f"metric_{k}"
            g.add((eval_uri, ARENA[pred_name], Literal(v, datatype=XSD.float if isinstance(v, float) else XSD.integer)))

    # Save metrics JSON payload
    g.add((eval_uri, ARENA.metricsPayload, Literal(json.dumps(metrics), datatype=XSD.string)))

    g.serialize(destination=str(out_path), format="turtle")
    return out_path
