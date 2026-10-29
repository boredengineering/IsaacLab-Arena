# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Milestone 1 guardrail tests for execution worker import boundaries, persistent sessions, and repair envelopes."""

from __future__ import annotations

import copy
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest


def _base_scene() -> dict:
    return {
        "env_name": "franka_pick_place_milestone1",
        "embodiment": {"id": "franka_ik", "registry_name": "franka_ik", "params": {}},
        "background": {"id": "maple_table_robolab", "registry_name": "maple_table_robolab", "params": {}},
        "objects": [
            {
                "id": "rubiks_cube_hot3d_robolab",
                "registry_name": "rubiks_cube_hot3d_robolab",
                "params": {"initial_pose": {"position_xyz": [0.50, 0.0, 0.05], "orientation_xyzw": [0.0, 0.0, 0.0, 1.0]}},
            },
            {
                "id": "bowl_ycb_robolab",
                "registry_name": "bowl_ycb_robolab",
                "params": {"initial_pose": {"position_xyz": [0.55, 0.22, 0.05], "orientation_xyzw": [0.0, 0.0, 0.0, 1.0]}},
            },
        ],
        "relations": [
            {"kind": "is_anchor", "subject": "maple_table_robolab", "params": {}},
            {
                "kind": "on",
                "subject": "rubiks_cube_hot3d_robolab",
                "reference": "maple_table_robolab",
                "params": {"surface_anchor": "table_top", "surface_sector": "center"},
            },
            {
                "kind": "at_position",
                "subject": "rubiks_cube_hot3d_robolab",
                "params": {"x": 0.50, "y": 0.0, "yaw": 0.0, "surface_sector": "center"},
            },
            {
                "kind": "on",
                "subject": "bowl_ycb_robolab",
                "reference": "maple_table_robolab",
                "params": {"surface_anchor": "table_top", "surface_sector": "front_left"},
            },
        ],
        "reified_relations": [],
        "task": {
            "composition": "atomic",
            "description": "Franka picks up a cube from the maple table and places it into a bowl.",
            "subtasks": [
                {
                    "kind": "PickAndPlaceTask",
                    "params": {
                        "pick_up_object": "rubiks_cube_hot3d_robolab",
                        "destination_location": "bowl_ycb_robolab",
                        "background_scene": "maple_table_robolab",
                    },
                }
            ],
        },
    }


def test_execution_workers_do_not_import_workflow_modules():
    """Importing execution boundary workers must never load workflow control-plane modules."""
    code = """
import sys
import isaaclab_arena.agentic_environment_generation.execution as ex
from isaaclab_arena.agentic_environment_generation.execution import (
    preflight_oracle,
    spec_synthesis_worker,
    simulation_worker,
    visual_critic_worker,
    refiner_worker,
    policy_rollout_worker,
)
workflow_mods = [m for m in sys.modules if m.startswith("isaaclab_arena.agentic_environment_generation.workflow")]
sim_mods = [m for m in sys.modules if m in ("torch", "isaacsim", "omni") or m.startswith(("isaacsim.", "omni."))]
assert not workflow_mods, f"Execution workers leaked workflow imports: {workflow_mods}"
assert not sim_mods, f"Execution workers eagerly imported simulator/torch at module load: {sim_mods}"
"""
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"Import boundary check failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"


def test_workflow_modules_do_not_import_omniverse_or_pytorch():
    """Importing workflow orchestrator modules must never load Omniverse Kit or PyTorch."""
    code = """
import sys
from isaaclab_arena.agentic_environment_generation.workflow import (
    contracts,
    repairs,
    coordinator,
    scene_loop,
    scene_eligibility,
)
sim_mods = [m for m in sys.modules if m in ("torch", "isaacsim", "omni") or m.startswith(("torch.", "isaacsim.", "omni."))]
assert not sim_mods, f"Workflow modules leaked heavy simulator/torch imports: {sim_mods}"
"""
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"Workflow import boundary check failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"


def test_persistent_simulation_worker_three_sequential_mutations_without_restart(tmp_path: Path):
    """3 sequential in-place mutations execute across two-tier attempt leases with 0 subprocess restarts."""
    from isaaclab_arena.agentic_environment_generation.execution.simulation_worker import (
        DeltaPoseMutation,
        DeltaPoseMutationMap,
        PersistentSimulationSession,
        SimulationWorkerIPCServer,
        SimulationWorkerPort,
    )

    session = PersistentSimulationSession(session_id="test-persistent-sim", num_settle_steps=60)
    port = SimulationWorkerPort(session=session)
    scene = _base_scene()

    mutations_seq = [
        (0.48, -0.12, 0.05, "front_center", 0.15),
        (0.52, -0.18, 0.05, "front_right", 0.30),
        (0.45, -0.15, 0.05, "right_edge", -0.20),
    ]
    digests = []

    for idx, (mx, my, mz, sector, yaw) in enumerate(mutations_seq, start=1):
        prepared = port.prepare(fence=f"fence-{idx}", timeout_s=30.0)
        mut_map = DeltaPoseMutationMap(
            mutations={
                "rubiks_cube_hot3d_robolab": DeltaPoseMutation(
                    subject_id="rubiks_cube_hot3d_robolab",
                    position_xyz=(mx, my, mz),
                    surface_sector=sector,
                    yaw_rad=yaw,
                )
            }
        )
        result = port.send(
            prepared,
            {"spec": scene, "mutation_map": mut_map.to_dict(), "num_settle_steps": 60},
            timeout_s=30.0,
        )
        cleanup = port.stop_owned(prepared, timeout_s=5.0)

        # Verify two-tier lease released without killing the warm session
        assert cleanup.session_alive is True
        assert cleanup.subprocess_restarts == 0
        assert cleanup.attempt_number == idx
        assert session.is_alive is True
        assert result.attempt_number == idx
        assert result.subprocess_restarts == 0
        assert result.settled_ok is True, f"Unexpected settle issues: {result.settle_issues}"
        assert result.drop_detected is False
        assert len(result.evidence_manifest_digest) == 64
        digests.append(result.evidence_manifest_digest)

        # Verify Gap 1 Dual-Coordinate Sync: lowered_spec_dict has updated object initial_pose
        cube_obj = next(o for o in result.lowered_spec_dict["objects"] if o["id"] == "rubiks_cube_hot3d_robolab")
        assert cube_obj["params"]["initial_pose"]["position_xyz"] == [mx, my, mz]

        # Verify non-black rendered PNG frames
        assert "front_camera_rgb" in result.rendered_images
        png_bytes = result.rendered_images["front_camera_rgb"]
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(png_bytes) > 64

    assert len(set(digests)) == 3

    # Also verify IPC Unix domain socket daemon across 3 calls
    sock_path = tmp_path / "sim_worker.sock"
    ipc_server = SimulationWorkerIPCServer(sock_path)
    ipc_server.start()
    try:
        for idx in range(1, 4):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as cli:
                cli.connect(str(sock_path))
                req = {"method": "settle_and_capture", "params": {"spec": scene}}
                cli.sendall((json.dumps(req) + "\n").encode("utf-8"))
                raw_resp = b""
                while True:
                    chunk = cli.recv(65536)
                    if not chunk:
                        break
                    raw_resp += chunk
                    if b"\n" in chunk:
                        break
                resp = json.loads(raw_resp.decode("utf-8"))
                assert resp["ok"] is True
                assert resp["result"]["attempt_number"] == idx
                assert resp["result"]["subprocess_restarts"] == 0
    finally:
        ipc_server.stop()
    assert ipc_server.session.is_alive is False


def test_repair_permission_envelope_accepts_surface_sector_yaw_and_polygon_preprojection():
    """repair_permission_envelope and validate_permitted_scene_repair support sector, yaw, and polygon projection."""
    from isaaclab_arena.agentic_environment_generation.execution.refiner_worker import RefinerWorker
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import WorkflowContract
    from isaaclab_arena.agentic_environment_generation.workflow.repairs import (
        repair_permission_envelope,
        validate_permitted_scene_repair,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import candidate_record
    from isaaclab_arena.tests.test_environment_workflow_contracts import request

    base = _base_scene()
    raw = request()
    raw["source"] = {"kind": "existing", "identity": "raw", "content": json.dumps(base)}
    # Freeze only object identity (/objects/0/id), leaving /objects/0/params/initial_pose eligible for synced updates
    raw["preserved"] = [
        {"subject_id": "rubiks_cube_hot3d_robolab", "schema_path": "/objects/0/id", "mode": "frozen"}
    ]
    raw["allowed_interventions"] = [
        {
            "subject_id": "rubiks_cube_hot3d_robolab",
            "schema_path": "/relations/2/params/x",
            "operation": "replace",
            "coordinate_frame": "env_local",
            "units": "m",
            "max_total_displacement_m": 0.25,
        },
        {
            "subject_id": "rubiks_cube_hot3d_robolab",
            "schema_path": "/relations/2/params/y",
            "operation": "replace",
            "coordinate_frame": "env_local",
            "units": "m",
            "max_total_displacement_m": 0.25,
        },
        {
            "subject_id": "rubiks_cube_hot3d_robolab",
            "schema_path": "/relations/2/params/yaw",
            "operation": "replace",
            "coordinate_frame": "env_local",
            "units": "rad",
            "max_total_displacement_m": 0.25,
            "max_angular_displacement_rad": 1.57,
        },
        {
            "subject_id": "rubiks_cube_hot3d_robolab",
            "schema_path": "/relations/2/params/surface_sector",
            "operation": "replace",
            "coordinate_frame": "env_local",
            "units": "sector",
            "max_total_displacement_m": 0.25,
            "allowed_sectors": ["center", "front_center", "front_left", "front_right", "left_edge", "right_edge"],
        },
    ]
    contract = WorkflowContract.model_validate(raw)
    original_rec = candidate_record("run-1", base, source_id="initial")

    # Use Job J8 RefinerWorker to pre-project onto safe support surface and sync coordinates
    refiner = RefinerWorker(strict_mode=False)
    proposed = copy.deepcopy(base)
    proposed["relations"][2]["params"]["yaw"] = 0.35
    proposed["relations"][2]["params"]["surface_sector"] = "front_right"
    refinement = refiner.refine(
        base,
        proposed,
        target_subject="rubiks_cube_hot3d_robolab",
        feedback="Move rubiks_cube_hot3d_robolab to front_right sector to avoid collision.",
        preferred_sector="front_right",
        max_displacement_m=0.25,
        sync_object_initial_pose=True,
    )

    repaired_spec = refinement.refined_spec_dict
    # Keep bowl_ycb_robolab untouched so only target_subject changed
    repaired_spec["objects"][1] = copy.deepcopy(base["objects"][1])
    repaired_spec["relations"][1]["params"]["surface_sector"] = base["relations"][1]["params"]["surface_sector"]

    receipt = validate_permitted_scene_repair(contract, base, repaired_spec)
    assert receipt.delta.target_id == "rubiks_cube_hot3d_robolab"
    assert 0.0 < receipt.delta.displacement_m <= 0.25

    current_rec = candidate_record(
        "run-1",
        repaired_spec,
        source_id="refiner",
        original_id=original_rec.candidate_id,
        parent_id=original_rec.candidate_id,
    )
    envelope = repair_permission_envelope(
        contract,
        original_rec,
        current_rec,
        effective_subjects=("rubiks_cube_hot3d_robolab",),
    )
    assert "surface_sector" in envelope["allowed_axes"]
    assert "yaw" in envelope["allowed_axes"]
    assert "front_right" in envelope["allowed_sectors"]
    assert envelope["max_angular_displacement_rad"] == pytest.approx(1.57)


def test_local_service_triad_ceilings_and_unblocked_ports():
    """Verify local service triad ceilings (8000, 8001, 7688) and unblocked local execution ports."""
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_execution import _default_local_ports
    from isaaclab_arena_examples.agentic_environment_generation.foreground_scene_ports import (
        build_local_service_triad_ceilings,
    )

    triad = build_local_service_triad_ceilings()
    assert triad["endpoints"]["generation_url"] == "http://localhost:8000/v1"
    assert triad["endpoints"]["assessment_url"] == "http://localhost:8001/v1"
    assert triad["endpoints"]["neo4j_uri"] == "bolt://localhost:7688"
    assert "generation" in triad["model_ceilings"]
    assert "assessment" in triad["model_ceilings"]

    ports = _default_local_ports()
    assert set(ports) == {"spawn_spec", "capture", "catalogue"}
    assert all(callable(v) for v in ports.values())
