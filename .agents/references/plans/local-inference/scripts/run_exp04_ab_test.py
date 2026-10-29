#!/usr/bin/env python3
"""Fast 3-Arm Prompt & Articulation Diagnostic A/B Test (§16.5).

Scenario D1-C, OpenPI pi0.5 on Port 8008, 3 Seeds per Arm (0, 1, 2)
"""

import argparse
import glob
import json
import math
import os
import subprocess
import sys
import time
import numpy as np

def get_arena_container_name() -> str:
    res = subprocess.run(
        ["docker", "ps", "--filter", "name=isaaclab_arena", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    names = [n for n in res.stdout.strip().split("\n") if n and "vllm" not in n and "openpi" not in n and "gr00t" not in n]
    assert names, "No active IsaacLab Arena devcontainer found"
    return names[0]

ARMS = {
    "Arm_A": {
        "name": "Arm A (Compound Baseline)",
        "prompt": "Open the microwave door past 75 degrees and stow the Campbell's tomato soup can upright onto the interior turntable.",
        "spec_yaml": "artifacts/experiments/exp04_prompt_ab_test/specs/arm_a.yaml",
        "door_state": "Fully closed (0 deg, reset_openness: 0.0)",
    },
    "Arm_B": {
        "name": "Arm B (Atomic Articulation Only)",
        "prompt": "Grasp the microwave handle and pull the door open.",
        "spec_yaml": "artifacts/experiments/exp04_prompt_ab_test/specs/arm_b.yaml",
        "door_state": "Fully closed (0 deg, reset_openness: 0.0)",
    },
    "Arm_C": {
        "name": "Arm C (Atomic Pick-and-Place with Pre-Opened Door)",
        "prompt": "Pick up the tomato soup can and place it on the turntable inside the microwave.",
        "spec_yaml": "artifacts/experiments/exp04_prompt_ab_test/specs/arm_c.yaml",
        "door_state": "Pre-opened to 85% (reset_openness: 0.85)",
    },
}

def run_single_episode(arm_id: str, seed: int, base_output_dir: str, num_steps: int = 1000) -> dict:
    arm_cfg = ARMS[arm_id]
    out_dir = os.path.join(base_output_dir, arm_id.lower(), f"seed_{seed}")
    os.makedirs(out_dir, exist_ok=True)
    trace_path = os.path.join(out_dir, "reach_trace.jsonl")

    container = get_arena_container_name()

    print("\n" + "=" * 90)
    print(f"▶ EXECUTING 16.5 DIAGNOSTIC: {arm_cfg['name']} | Seed {seed}")
    print(f"  Prompt:     \"{arm_cfg['prompt']}\"")
    print(f"  Door State: {arm_cfg['door_state']}")
    print(f"  Spec:       {arm_cfg['spec_yaml']}")
    print(f"  Output Dir: {out_dir}")
    print("=" * 90)

    cmd = [
        "docker", "exec", container,
        "/isaac-sim/python.sh", "isaaclab_arena/evaluation/policy_runner.py",
        "--env_graph_spec_yaml", arm_cfg["spec_yaml"],
        "--headless",
        "--num_envs", "1",
        "--num_episodes", "1",
        "--seed", str(seed),
        "--num_steps", str(num_steps),
        "--enable_cameras",
        "--record_viewport_video",
        "--record_camera_video",
        "--output_base_dir", out_dir,
        "--policy_type", "isaaclab_arena_openpi.policy.pi0_remote_policy.Pi0RemotePolicy",
        "--remote_host", "127.0.0.1",
        "--remote_port", "8008",
        "--openpi_embodiment_adapter", "droid",
        "--policy_variant", "pi05",
        "--trace_reach", trace_path,
        "--trace_reach_object", "tomato_soup_can",
    ]

    t0 = time.time()
    proc = subprocess.run(" ".join(cmd), shell=True)
    elapsed = time.time() - t0

    # Locate generated episode_results_rank0.jsonl and dataset hdf5
    res_files = glob.glob(os.path.join(out_dir, "**/episode_results_rank0.jsonl"), recursive=True)
    h5_files = glob.glob(os.path.join(out_dir, "**/dataset_*_rank0.hdf5"), recursive=True)

    progress_score = 0.0
    task_success = False
    events = []
    if res_files:
        with open(res_files[0]) as f:
            for line in f:
                try:
                    data = json.loads(line)
                    task_success = data.get("success", False)
                    prog = data.get("progress", {})
                    progress_score = prog.get("overall_score", 0.0)
                    events = prog.get("events", [])
                except Exception:
                    pass

    # Extract HDF5 joint and velocity data
    max_door_rot = 0.0
    max_can_vel = 0.0
    if h5_files:
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

    # Compute handle approach distance (d_min) from reach_trace.jsonl or hand_pos
    # Handle world coordinate in D1-C microwave reference: [-0.1020, -0.2961, 0.5349]
    handle_pos_w = np.array([-0.1020, -0.2961, 0.5349])
    d_min_handle = 999.0
    d_min_can = 999.0
    max_lift = 0.0

    if os.path.exists(trace_path):
        with open(trace_path) as f:
            for line in f:
                try:
                    row = json.loads(line)
                    hand_pos = row.get("hand_pos_w")
                    if hand_pos and len(hand_pos) > 0:
                        hp = np.array(hand_pos[0])
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

    return {
        "arm": arm_id,
        "arm_name": arm_cfg["name"],
        "seed": seed,
        "prompt": arm_cfg["prompt"],
        "door_state": arm_cfg["door_state"],
        "exit_code": proc.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "task_success": task_success,
        "progress_score": progress_score,
        "events": events,
        "d_min_handle_m": round(d_min_handle, 4) if d_min_handle < 900.0 else None,
        "d_min_can_m": round(d_min_can, 4) if d_min_can < 900.0 else None,
        "max_door_rot_rad": round(max_door_rot, 4),
        "max_can_vel_mps": round(max_can_vel, 4),
        "max_can_lift_m": round(max_lift, 4),
    }

def main():
    parser = argparse.ArgumentParser(description="Section 16.5 Prompt & Articulation Diagnostic A/B Test")
    parser.add_argument("--output-dir", type=str, default="artifacts/experiments/exp04_prompt_ab_test", help="Output directory")
    parser.add_argument("--num-steps", type=int, default=1000, help="Steps per episode")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2], help="Seeds to evaluate")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    all_results = []

    print("\n" + "=" * 105)
    print("🔬 EXPERIMENT 04: SECTION 16.5 3-ARM PROMPT & ARTICULATION DIAGNOSTIC A/B TEST")
    print("   Objective: Isolate Prompt Attention Dispersion vs Handle Grasp vs Cavity Stowage")
    print(f"   Policy:    OpenPI pi0.5 (Port 8008, WebSocket)")
    print(f"   Arms:      Arm A (Compound), Arm B (Atomic Articulation), Arm C (Atomic PnP Pre-Opened)")
    print(f"   Seeds:     {args.seeds}")
    print("=" * 105)

    for arm_id in ["Arm_A", "Arm_B", "Arm_C"]:
        for seed in args.seeds:
            res = run_single_episode(arm_id, seed, args.output_dir, num_steps=args.num_steps)
            all_results.append(res)
            # Dump incremental report
            with open(os.path.join(args.output_dir, "exp04_prompt_ab_test_report.json"), "w") as f:
                json.dump(all_results, f, indent=2)

    # Print summary comparative table
    print("\n" + "=" * 115)
    print("📋 SECTION 16.5 DIAGNOSTIC A/B TEST: COMPARATIVE RESULTS MATRIX")
    print("=" * 115)
    print(f"{'Arm':<8} | {'Seed':<5} | {'d_min_handle (m)':<18} | {'Door Max Rot (rad)':<20} | {'d_min_can (m)':<15} | {'Max Lift (m)':<14} | {'Progress':<10} | {'Success':<8}")
    print("-" * 115)
    for r in all_results:
        d_h_str = f"{r['d_min_handle_m']:.4f}" if r['d_min_handle_m'] is not None else "N/A"
        d_c_str = f"{r['d_min_can_m']:.4f}" if r['d_min_can_m'] is not None else "N/A"
        print(
            f"{r['arm']:<8} | {r['seed']:<5} | {d_h_str:<18} | {r['max_door_rot_rad']:<20.4f} | "
            f"{d_c_str:<15} | {r['max_can_lift_m']:<14.4f} | {r['progress_score']:<10.2f} | {str(r['task_success']):<8}"
        )
    print("=" * 115)

if __name__ == "__main__":
    main()
