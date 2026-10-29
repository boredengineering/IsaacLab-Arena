#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Experiment 05: Live OpenPI π₀.₅ Remediation & Articulation Acceptance Test (§15.6).

Evaluates Scenario D1-C under remediated DROID home manifold, optimized workspace
standoff, and tuned contact physics against the four empirical acceptance gates:
  1. Initial step drift: Franka EE displacement (steps 0 -> 50) < 0.05 m (confirms zero flail).
  2. Handle approach & grasp proximity: d_min to handle prim.
  3. Door angular displacement: microwave door rotation Delta theta >= 45 deg (0.785 rad).
  4. Subtask 0 exit & task progression: transition to PickAndPlaceTask.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import time
from typing import Any

import numpy as np
import yaml


def get_arena_container_name() -> str:
    """Discover running IsaacLab-Arena Docker container."""
    res = subprocess.run(
        ["docker", "ps", "--filter", "name=isaaclab_arena", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    names = [
        n.strip()
        for n in res.stdout.strip().splitlines()
        if n.strip() and "vllm" not in n and "openpi" not in n and "gr00t" not in n
    ]
    assert names, "No active IsaacLab Arena devcontainer found"
    return names[0]


def get_current_user() -> str:
    """Get current host user name for docker su execution."""
    res = subprocess.run(["id", "-un"], capture_output=True, text=True, check=True)
    return res.stdout.strip()


def run_single_remediation_seed(
    spec_yaml: str,
    seed: int,
    base_output_dir: str,
    port: int = 8008,
    num_steps: int = 1000,
) -> dict[str, Any]:
    """Execute a single-seed rollout and evaluate Section 15.6 acceptance criteria."""
    out_dir = os.path.join(base_output_dir, f"seed_{seed}")
    os.makedirs(out_dir, exist_ok=True)
    trace_path = os.path.join(out_dir, "reach_trace.jsonl")

    container = get_arena_container_name()
    user = get_current_user()

    print("\n" + "=" * 90)
    print(f"▶ EXECUTING EXP 05 OPENPI REMEDIATION VALIDATION: Seed {seed}")
    print(f"  Spec:        {spec_yaml}")
    print(f"  Policy:      OpenPI pi0.5 (Port {port})")
    print(f"  Steps:       {num_steps}")
    print(f"  Output Dir:  {out_dir}")
    print("=" * 90)

    cmd_inner = (
        f"cd /workspaces/isaaclab_arena && /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py "
        f"--env_graph_spec_yaml {spec_yaml} "
        f"--headless "
        f"--num_envs 1 "
        f"--num_episodes 1 "
        f"--seed {seed} "
        f"--num_steps {num_steps} "
        f"--enable_cameras "
        f"--record_viewport_video "
        f"--record_camera_video "
        f"--output_base_dir {out_dir} "
        f"--policy_type isaaclab_arena_openpi.policy.pi0_remote_policy.Pi0RemotePolicy "
        f"--remote_host 127.0.0.1 "
        f"--remote_port {port} "
        f"--openpi_embodiment_adapter droid "
        f"--policy_variant pi05 "
        f"--trace_reach {trace_path} "
        f"--trace_reach_object tomato_soup_can"
    )

    full_cmd = ["docker", "exec", container, "su", user, "-c", cmd_inner]

    t0 = time.time()
    proc = subprocess.run(full_cmd)
    elapsed = time.time() - t0

    # Locate episode results and HDF5 dataset
    res_files = glob.glob(os.path.join(out_dir, "**/episode_results_rank0.jsonl"), recursive=True)
    h5_files = glob.glob(os.path.join(out_dir, "**/dataset_*_rank0.hdf5"), recursive=True)

    task_success = False
    progress_score = 0.0
    events: list[Any] = []
    if res_files:
        with open(res_files[0], encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    task_success = data.get("success", False)
                    prog = data.get("progress", {})
                    progress_score = prog.get("overall_score", 0.0)
                    events = prog.get("events", [])
                except Exception:
                    pass

    # Extract max door rotation from HDF5
    max_door_rot = 0.0
    max_can_vel = 0.0
    if h5_files:
        try:
            import h5py

            with h5py.File(h5_files[0], "r") as h:
                if "data" in h and len(h["data"]) > 0:
                    demo_key = list(h["data"].keys())[0]
                    demo = h["data"][demo_key]
                    if "revolute_joint_state_subtask_0" in demo:
                        joint_arr = demo["revolute_joint_state_subtask_0"][:]
                        max_door_rot = float(np.max(np.abs(joint_arr)))
                    if "object_linear_velocity_subtask_1" in demo:
                        vel_arr = demo["object_linear_velocity_subtask_1"][:]
                        max_can_vel = float(np.max(np.linalg.norm(vel_arr, axis=-1)))
        except Exception as e:
            print(f"[Warning] Failed to read HDF5: {e}")

    # Extract expected initial object Z from spec_yaml
    expected_can_z = 0.531
    try:
        with open(spec_yaml, "r", encoding="utf-8") as f:
            ydata = yaml.safe_load(f)
            for o in ydata.get("objects", []):
                if o.get("id") == "tomato_soup_can":
                    p = o.get("params", {}).get("initial_pose", {}).get("position_xyz")
                    if p and len(p) > 2:
                        expected_can_z = float(p[2])
    except Exception:
        pass

    # Process reach trace to compute:
    # 1. EE drift during steps 0 -> 50
    # 2. Min distance to microwave handle (nominal [-0.102, -0.296, 0.535])
    # 3. Min distance to tomato soup can
    # 4. Max lift height
    # 5. Step 0 object grounding Z and early settling velocity
    handle_pos_w = np.array([-0.1020, -0.2961, 0.5349])
    d_min_handle = 999.0
    d_min_can = 999.0
    max_lift = 0.0
    ee_drift_0_50 = 0.0
    hand_positions: list[np.ndarray] = []
    step_0_obj_z = None
    step_0_speed = 0.0
    max_early_speed = 0.0

    if os.path.exists(trace_path):
        with open(trace_path, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    st = row.get("step")
                    oz = row.get("obj_z")
                    sp = row.get("speed")
                    if st == 0 and oz and len(oz) > 0:
                        step_0_obj_z = float(oz[0])
                    if st == 0 and sp and len(sp) > 0:
                        step_0_speed = float(sp[0])
                    if st is not None and st <= 50 and sp and len(sp) > 0:
                        if float(sp[0]) > max_early_speed:
                            max_early_speed = float(sp[0])

                    hand_pos = row.get("hand_pos_w")
                    if hand_pos and len(hand_pos) > 0:
                        hp = np.array(hand_pos[0])
                        hand_positions.append(hp)
                        d_handle = float(np.linalg.norm(hp - handle_pos_w))
                        if d_handle < d_min_handle:
                            d_min_handle = d_handle

                    hand_dist = row.get("hand_dist_to_obj")
                    if hand_dist and len(hand_dist) > 0:
                        d_c = hand_dist[0]
                        if d_c < d_min_can:
                            d_min_can = d_c

                    lift = row.get("lift")
                    if lift and len(lift) > 0 and lift[0] is not None:
                        if lift[0] > max_lift:
                            max_lift = lift[0]
                except Exception:
                    pass

    if len(hand_positions) >= 50:
        ee_drift_0_50 = float(np.linalg.norm(hand_positions[49] - hand_positions[0]))
    elif len(hand_positions) > 1:
        ee_drift_0_50 = float(np.linalg.norm(hand_positions[-1] - hand_positions[0]))

    # Gate evaluations
    gate_1_zero_flail = ee_drift_0_50 < 0.05
    gate_2_handle_approach = d_min_handle < 0.15
    gate_3_door_rotation = max_door_rot >= 0.785398  # >= 45 deg
    gate_4_subtask_exit = progress_score >= 0.33
    z_drift = abs(step_0_obj_z - expected_can_z) if step_0_obj_z is not None else 999.0
    gate_5_settled_grounding = (step_0_obj_z is not None) and (z_drift < 0.05) and (max_early_speed < 0.50)

    return {
        "seed": seed,
        "spec_yaml": spec_yaml,
        "exit_code": proc.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "task_success": task_success,
        "progress_score": progress_score,
        "events": events,
        "ee_drift_0_50_m": round(ee_drift_0_50, 4),
        "step_0_obj_z": round(step_0_obj_z, 4) if step_0_obj_z is not None else None,
        "obj_z_drift_m": round(z_drift, 4) if step_0_obj_z is not None else None,
        "d_min_handle_m": round(d_min_handle, 4) if d_min_handle < 900.0 else None,
        "d_min_can_m": round(d_min_can, 4) if d_min_can < 900.0 else None,
        "max_door_rot_rad": round(max_door_rot, 4),
        "max_door_rot_deg": round(float(np.degrees(max_door_rot)), 2),
        "max_can_vel_mps": round(max_can_vel, 4),
        "max_can_lift_m": round(max_lift, 4),
        "gates": {
            "gate_1_zero_flail (<0.05m)": gate_1_zero_flail,
            "gate_2_handle_approach (<0.15m)": gate_2_handle_approach,
            "gate_3_door_rotation (>=45deg)": gate_3_door_rotation,
            "gate_4_subtask_exit (progress>=0.33)": gate_4_subtask_exit,
            "gate_5_settled_grounding (z_drift<0.05m, early_speed<0.5m/s)": gate_5_settled_grounding,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Experiment 05 OpenPI Remediation Validation Test")
    parser.add_argument(
        "--spec-yaml",
        type=str,
        default="generated_envs/exp04_d1c_microwave/remediated/exp04_d1c_microwave_remediated.yaml",
        help="Path to remediated spec YAML",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts/experiments/exp05_openpi_remediated",
        help="Base output directory",
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2], help="Evaluation seeds")
    parser.add_argument("--num-steps", type=int, default=1000, help="Steps horizon per episode")
    parser.add_argument("--port", type=int, default=8008, help="OpenPI WebSocket server port")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    all_results = []

    print("\n" + "=" * 100)
    print("🔬 EXPERIMENT 05: OPENPI π₀.₅ REMEDIATION & ARTICULATION ACCEPTANCE TEST")
    print(f"   Spec:       {args.spec_yaml}")
    print(f"   Policy:     OpenPI pi0.5 (Port {args.port})")
    print(f"   Seeds:      {args.seeds}")
    print(f"   Horizon:    {args.num_steps} steps")
    print(f"   Output Dir: {args.output_dir}")
    print("=" * 100)

    for seed in args.seeds:
        res = run_single_remediation_seed(
            spec_yaml=args.spec_yaml,
            seed=seed,
            base_output_dir=args.output_dir,
            port=args.port,
            num_steps=args.num_steps,
        )
        all_results.append(res)
        report_path = os.path.join(args.output_dir, "exp05_openpi_remediation_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2)

    # Print summary comparative table
    print("\n" + "=" * 120)
    print("📋 EXPERIMENT 05 ACCEPTANCE GATE SUMMARY REPORT")
    print("=" * 120)
    header = (
        f"{'Seed':<5} | {'EE Drift 0->50 (m)':<20} | {'d_min_handle (m)':<18} | "
        f"{'Door Rot (deg)':<15} | {'Max Lift (m)':<13} | {'Progress':<10} | {'Flail Gate':<10}"
    )
    print(header)
    print("-" * 120)
    for r in all_results:
        g1 = "PASS" if r["gates"]["gate_1_zero_flail (<0.05m)"] else "FAIL"
        d_h_str = f"{r['d_min_handle_m']:.4f}" if r["d_min_handle_m"] is not None else "N/A"
        print(
            f"{r['seed']:<5} | {r['ee_drift_0_50_m']:<20.4f} | {d_h_str:<18} | "
            f"{r['max_door_rot_deg']:<15.2f} | {r['max_can_lift_m']:<13.4f} | "
            f"{r['progress_score']:<10.2f} | {g1:<10}"
        )
    print("=" * 120)


if __name__ == "__main__":
    main()
