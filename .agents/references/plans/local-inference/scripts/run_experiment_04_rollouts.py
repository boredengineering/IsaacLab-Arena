#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Experiment 04 Closed-Loop Neural Policy Evaluation Runner.

Executes closed-loop sensorimotor rollouts across multi-domain articulated benchmarks:
  - Scenario D1-C: Sequential Microwave Open & Stow (Type A: Placed Articulated Prop)
  - Scenario D2-A: Kitchen Base Cabinet Drawer Stow (Type B: Intrinsic Prismatic Sub-Prim)
  - Scenario D2-B: Sequential Counter Drawer Open, Stow & Close (Type B: Reversible Prismatic)
  - Scenario D2-C: Commercial Beverage Display Refrigerator Door Open & Beer Stow (Type B: Revolute)
  - Scenario D2-C-MED: Medical Utility Cabinet Dual Door Open & Saline Stow (Type B: Dual Revolute)

Supports Foundation Policy Backends:
  - gr00t:  isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy (ZeroMQ, Port 5556)
  - openpi: isaaclab_arena_openpi.policy.pi0_remote_policy.Pi0RemotePolicy (WebSocket, Port 8008)
  - oracle: isaaclab_arena.policy.zero_action_policy.ZeroActionPolicy (PhysX Solvability Baseline)

Conforms to Section 12, 13.3, 13.4, and 14 of experiment_04.md.
"""

import argparse
import datetime
import json
import os
import socket
import subprocess
import sys
import time


def get_arena_container_name() -> str:
    """Dynamically discover running IsaacLab-Arena Docker container."""
    res = subprocess.run(
        ["docker", "ps", "--filter", "name=isaaclab_arena", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    names = [n.strip() for n in res.stdout.strip().splitlines() if n.strip()]
    if names:
        return names[0]
    return "isaaclab_arena-latest-isaaclab-arena-private"


def probe_policy_endpoint(host: str, port: int, timeout: float = 2.0) -> bool:
    """Non-blocking TCP probe to verify if policy server is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


EXP04_SCENARIOS = {
    "D1-C": {
        "id": "D1-C",
        "name": "Sequential Microwave Open & Stow",
        "domain": "Office Breakroom",
        "ontology": "Type A (Placed Prop)",
        "spec_yaml": "generated_envs/exp04_d1c_microwave/latest/exp04_d1c_microwave.yaml",
        "primary_fixture": "office_table_background",
        "articulated_prim": "microwave",
        "manipuland": "tomato_soup_can",
        "subtasks": ["OpenDoorTask", "PickAndPlaceTask"],
        "default_steps": 1000,
    },
    "D2-A": {
        "id": "D2-A",
        "name": "Prismatic Kitchen Base Cabinet Drawer Stow",
        "domain": "Residential / Kitchen",
        "ontology": "Type B (Intrinsic Prismatic Sub-Prim)",
        "spec_yaml": "generated_envs/exp04_d2a_cabinet/latest/exp04_d2a_cabinet.yaml",
        "primary_fixture": "kitchen_base_cabinet",
        "articulated_prim": "top_drawer",
        "manipuland": "tomato_soup_can",
        "subtasks": ["OpenDrawerTask", "PickAndPlaceTask"],
        "default_steps": 1000,
    },
    "D2-B": {
        "id": "D2-B",
        "name": "Sequential Counter Drawer Open, Stow & Close",
        "domain": "Residential / Breakroom Counter",
        "ontology": "Type B (Intrinsic Reversible Prismatic)",
        "spec_yaml": "generated_envs/exp04_d2b_counter/latest/exp04_d2b_counter.yaml",
        "primary_fixture": "sm_fixture_counter_a01_01",
        "articulated_prim": "storage_drawer",
        "manipuland": "tomato_soup_can",
        "subtasks": ["OpenDrawerTask", "PickAndPlaceTask", "CloseDrawerTask"],
        "default_steps": 1200,
    },
    "D2-C": {
        "id": "D2-C",
        "name": "Commercial Beverage Display Refrigerator Door Open & Beer Stow",
        "domain": "Commercial / Facility / Breakroom",
        "ontology": "Type B (Intrinsic Revolute Sub-Prim)",
        "spec_yaml": "generated_envs/exp04_d2c_fridge/latest/exp04_d2c_fridge.yaml",
        "primary_fixture": "facilityEquipment_beverageFridge_display_a01",
        "articulated_prim": "fridge_door",
        "manipuland": "beer_bottle",
        "subtasks": ["OpenDoorTask", "PickAndPlaceTask"],
        "default_steps": 1000,
    },
    "D2-C-MED": {
        "id": "D2-C-MED",
        "name": "Medical Utility Cabinet Dual Door Open & Saline Stow",
        "domain": "Healthcare / Clinic",
        "ontology": "Type B (Intrinsic Dual Revolute)",
        "spec_yaml": "generated_envs/exp04_d2c_medical/latest/exp04_d2c_medical.yaml",
        "primary_fixture": "cart_medical_utility_a03",
        "articulated_prim": "left_door",
        "manipuland": "screw_top_jar",
        "subtasks": ["OpenDoorTask", "OpenDoorTask", "PickAndPlaceTask"],
        "default_steps": 1200,
    },
}


def extract_snapshots_from_videos(output_dir: str) -> list[str]:
    """Extract initial, mid-point, and final frame PNG snapshots from recorded MP4s."""
    extracted = []
    for root, _, files in os.walk(output_dir):
        for f in files:
            if f.endswith(".mp4"):
                mp4_path = os.path.join(root, f)
                base_name = os.path.splitext(f)[0]
                init_png = os.path.join(root, f"{base_name}_t0.png")
                mid_png = os.path.join(root, f"{base_name}_mid.png")
                final_png = os.path.join(root, f"{base_name}_tfinal.png")
                subprocess.run(
                    ["ffmpeg", "-y", "-ss", "00:00:00.000", "-i", mp4_path, "-vframes", "1", "-q:v", "2", init_png],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                subprocess.run(
                    ["ffmpeg", "-y", "-ss", "00:00:05.000", "-i", mp4_path, "-vframes", "1", "-q:v", "2", mid_png],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                subprocess.run(
                    ["ffmpeg", "-y", "-sseof", "-0.2", "-i", mp4_path, "-vframes", "1", "-q:v", "2", final_png],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                for p in [init_png, mid_png, final_png]:
                    if os.path.exists(p) and p not in extracted:
                        extracted.append(p)
    return extracted


def log_rollout_to_ledger(ledger_path: str, record: dict) -> None:
    """Append structured evaluation record to rsi_interaction_ledger.jsonl."""
    os.makedirs(os.path.dirname(os.path.abspath(ledger_path)), exist_ok=True)
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def run_single_seed_rollout(
    scenario_cfg: dict,
    seed: int,
    base_output_dir: str,
    policy_type: str = "gr00t",
    port: int = 5556,
    num_steps: int = 1000,
    model_comb: str = "comb_2a",
    ledger_path: str = None,
    dry_run: bool = False,
) -> dict:
    """Execute a single-seed closed-loop rollout for a scenario."""
    scenario_id = scenario_cfg["id"]
    spec_yaml = scenario_cfg["spec_yaml"]
    out_dir = os.path.join(base_output_dir, f"scenario_{scenario_id.lower()}", policy_type, f"seed_{seed}")
    os.makedirs(out_dir, exist_ok=True)

    container = get_arena_container_name()

    print("\n" + "=" * 80)
    print(f"▶ EXECUTING EXP 04 ROLLOUT: Scenario {scenario_id} ({scenario_cfg['name']}) | Seed {seed}")
    print(f"  Ontology:      {scenario_cfg['ontology']}")
    print(f"  Policy Type:   {policy_type.upper()} (Port {port})")
    print(f"  Model Pipeline:{model_comb}")
    print(f"  Spec YAML:     {spec_yaml}")
    print(f"  Output Dir:    {out_dir}")
    print(f"  Steps Horizon: {num_steps}")
    print("=" * 80)

    base_cmd = [
        "docker", "exec", container,
        "/isaac-sim/python.sh", "isaaclab_arena/evaluation/policy_runner.py",
        "--env_graph_spec_yaml", spec_yaml,
        "--headless",
        "--num_envs", "1",
        "--num_episodes", "1",
        "--seed", str(seed),
        "--num_steps", str(num_steps),
        "--enable_cameras",
        "--record_viewport_video",
        "--record_camera_video",
        "--output_base_dir", out_dir
    ]

    if policy_type == "gr00t":
        policy_args = [
            "--policy_type", "isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy",
            "--policy_config_yaml_path", "isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml",
            "--remote_host", "127.0.0.1",
            "--remote_port", str(port)
        ]
    elif policy_type == "openpi":
        policy_args = [
            "--policy_type", "isaaclab_arena_openpi.policy.pi0_remote_policy.Pi0RemotePolicy",
            "--remote_host", "127.0.0.1",
            "--remote_port", str(port),
            "--openpi_embodiment_adapter", "droid",
            "--policy_variant", "pi05"
        ]
    elif policy_type == "oracle":
        policy_args = [
            "--policy_type", "isaaclab_arena.policy.zero_action_policy.ZeroActionPolicy"
        ]
    else:
        raise ValueError(f"Unsupported policy_type: {policy_type}")

    cmd = base_cmd + policy_args
    full_cmd_str = " ".join(cmd)

    if dry_run:
        print(f"[DRY-RUN] Command: {full_cmd_str}")
        return {
            "scenario": scenario_id,
            "scenario_name": scenario_cfg["name"],
            "domain": scenario_cfg["domain"],
            "ontology": scenario_cfg["ontology"],
            "model_comb": model_comb,
            "seed": seed,
            "policy_type": policy_type,
            "policy_port": port,
            "spec_yaml": spec_yaml,
            "exit_code": 0,
            "elapsed_seconds": 0.0,
            "episode_length_steps": 0,
            "progress_score": 0.0,
            "all_complete": False,
            "objectives": {},
            "events_count": 0,
            "snapshots": [],
        }

    t0 = time.time()
    proc = subprocess.run(full_cmd_str, shell=True)
    elapsed = time.time() - t0

    # Locate generated episode_results_rank0.jsonl
    results_jsonl = None
    progress_score = 0.0
    ep_length = 0
    all_complete = False
    events = []
    objectives = {}

    for root, _, files in os.walk(out_dir):
        if "episode_results_rank0.jsonl" in files:
            results_jsonl = os.path.join(root, "episode_results_rank0.jsonl")
            break

    if results_jsonl and os.path.exists(results_jsonl):
        try:
            with open(results_jsonl, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line.strip())
                        ep_length = data.get("episode_length", 0)
                        prog = data.get("progress", {})
                        progress_score = prog.get("overall_score", 0.0)
                        all_complete = prog.get("all_complete", data.get("success", False))
                        objectives = prog.get("objectives", {})
                        events = prog.get("events", [])
        except Exception as e:
            print(f"[WARN] Failed parsing {results_jsonl}: {e}")

    snapshots = extract_snapshots_from_videos(out_dir)

    result_summary = {
        "scenario": scenario_id,
        "scenario_name": scenario_cfg["name"],
        "domain": scenario_cfg["domain"],
        "ontology": scenario_cfg["ontology"],
        "model_comb": model_comb,
        "seed": seed,
        "policy_type": policy_type,
        "policy_port": port,
        "spec_yaml": spec_yaml,
        "exit_code": proc.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "episode_length_steps": ep_length,
        "progress_score": progress_score,
        "all_complete": all_complete,
        "objectives": objectives,
        "events_count": len(events),
        "snapshots": snapshots,
    }

    if ledger_path:
        ledger_record = {
            "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "cycle_index": seed,
            "scenario": scenario_id,
            "phase": f"EXP04_ROLLOUT_{policy_type.upper()}",
            "model_metadata": {
                "model_combination": model_comb,
                "policy_type": policy_type,
                "policy_port": port,
                "embodiment": "oxe_droid",
                "controller": "droid_rel_joint_pos",
                "latency_sec": round(elapsed, 2),
            },
            "physical_grounding_evidence": {
                "seed": seed,
                "exit_code": proc.returncode,
                "episode_length_steps": ep_length,
                "progress_score": progress_score,
                "task_success": all_complete,
                "objectives": objectives,
                "snapshots": snapshots,
            },
            "active_inference_state": {
                "bethe_free_energy": 0.0 if all_complete else (0.2 if progress_score > 0.5 else 1.0),
                "delta_free_energy": 0.0,
                "posterior_entropy": 0.0,
                "converged": all_complete,
            },
        }
        log_rollout_to_ledger(ledger_path, ledger_record)

    return result_summary


# ==============================================================================
# Master Candidate Model Combinations Catalog (§13.3 & §13.4, Exactly 14 Models)
# ==============================================================================
CANDIDATE_COMBINATIONS = {
    # Phase 1: 72B Anchor Suite (vLLM on GPU 0 - Active Resident)
    "comb_2a": {"name": "Qwen-72B + Analytical Oracle (V0)", "suite": "Phase 1 (72B Anchor)"},
    "comb_2b": {"name": "Qwen-72B + General VLM Critic (V1)", "suite": "Phase 1 (72B Anchor)"},
    "comb_2c": {"name": "Qwen-72B + Physical AI Critic (V2)", "suite": "Phase 1 (72B Anchor)"},
    "comb_2d": {"name": "Qwen-72B + Metric Depth Critic (V3)", "suite": "Phase 1 (72B Anchor)"},
    # Phase 2: 32B Multi-Residency Super-Pod
    "comb_1a": {"name": "Coder-32B + Analytical Oracle (V0)", "suite": "Phase 2 (32B Super-Pod)"},
    "comb_1b": {"name": "Coder-32B + Physical AI Critic (V2)", "suite": "Phase 2 (32B Super-Pod)"},
    "comb_1c": {"name": "Coder-32B + General VLM Critic (V1)", "suite": "Phase 2 (32B Super-Pod)"},
    "comb_1d": {"name": "Coder-32B + Metric Depth Critic (V3)", "suite": "Phase 2 (32B Super-Pod)"},
    "comb_4a": {"name": "DeepSeek-R1-32B + Analytical Oracle (V0)", "suite": "Phase 2 (32B Super-Pod)"},
    "comb_4b": {"name": "DeepSeek-R1-32B + Physical AI Critic (V2)", "suite": "Phase 2 (32B Super-Pod)"},
    "comb_5a": {"name": "QwQ-32B + Analytical Oracle (V0)", "suite": "Phase 2 (32B Super-Pod)"},
    "comb_5b": {"name": "QwQ-32B + Physical AI Critic (V2)", "suite": "Phase 2 (32B Super-Pod)"},
    # Phase 3: Frontier MoE Suite
    "comb_8a": {"name": "GLM-5.3 (744B) + Analytical Oracle (V0)", "suite": "Phase 3 (Colibrì MoE)"},
    "comb_8b": {"name": "GLM-5.3 (744B) + Physical AI Critic (V2)", "suite": "Phase 3 (Colibrì MoE)"},
}


def main():
    parser = argparse.ArgumentParser(description="Experiment 04 Closed-Loop Neural Rollout Runner")
    parser.add_argument(
        "--scenario",
        type=str,
        default="all",
        choices=["D1-C", "D2-A", "D2-B", "D2-C", "D2-C-MED", "all"],
        help="Scenario ID to evaluate (default: all)"
    )
    parser.add_argument(
        "--policy-type",
        type=str,
        default="dual",
        choices=["gr00t", "openpi", "oracle", "dual"],
        help="Policy backend architecture (gr00t: ZeroMQ, openpi: WebSocket, oracle: PhysX zero-action, dual: GR00T + OpenPI)"
    )
    parser.add_argument("--policy-port", type=int, default=None, help="Policy server port override")
    parser.add_argument("--num-seeds", type=int, default=10, help="Number of seeds to evaluate (default: 10)")
    parser.add_argument("--start-seed", type=int, default=0, help="Initial seed index (default: 0)")
    parser.add_argument("--num-steps", type=int, default=None, help="Maximum rollout steps per seed (default: per scenario config)")
    parser.add_argument(
        "--model-comb",
        type=str,
        default="all",
        help="Model combination tag ('all', 'phase1', 'phase2', 'phase3', comma-separated list, or specific ID like comb_2a)"
    )
    parser.add_argument("--output-dir", type=str, default="artifacts/experiments/exp04_rollouts", help="Base output directory")
    parser.add_argument("--ledger", type=str, default="artifacts/experiments/exp04_rollouts/rsi_interaction_ledger.jsonl", help="Ledger path")
    parser.add_argument("--dry-run", action="store_true", help="Print command invocations without launching physics")
    args = parser.parse_args()

    # Import backend management helpers for dynamic policy lifecycle
    backends_script_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../skills/arena-local-inference-experiments/scripts")
    )
    if backends_script_dir not in sys.path:
        sys.path.insert(0, backends_script_dir)
    try:
        from manage_backends import start_policy_server, stop_container
    except ImportError:
        start_policy_server = None
        stop_container = None

    # Resolve model combinations
    if args.model_comb == "all":
        combs_to_run = list(CANDIDATE_COMBINATIONS.keys())
    elif args.model_comb in ["phase1", "stage1"]:
        combs_to_run = [k for k, v in CANDIDATE_COMBINATIONS.items() if "Phase 1" in v["suite"]]
    elif args.model_comb in ["phase2", "stage2"]:
        combs_to_run = [k for k, v in CANDIDATE_COMBINATIONS.items() if "Phase 2" in v["suite"]]
    elif args.model_comb in ["phase3", "stage3"]:
        combs_to_run = [k for k, v in CANDIDATE_COMBINATIONS.items() if "Phase 3" in v["suite"]]
    elif "," in args.model_comb:
        combs_to_run = [c.strip() for c in args.model_comb.split(",") if c.strip()]
    else:
        combs_to_run = [args.model_comb]

    # Determine scenarios
    if args.scenario == "all":
        selected_scenarios = [EXP04_SCENARIOS[k] for k in ["D1-C", "D2-A", "D2-B", "D2-C"]]
    else:
        selected_scenarios = [EXP04_SCENARIOS[args.scenario]]

    # Determine policies to run
    if args.policy_type == "dual":
        policy_types = ["gr00t", "openpi"]
    else:
        policy_types = [args.policy_type]

    total_matrix_cells = len(combs_to_run) * len(selected_scenarios) * len(policy_types)
    print("\n" + "=" * 105)
    print("🚀 EXPERIMENT 04: FULL PIPELINED BENCHMARK SWEEP (Stage 4B / §13.6.8)")
    print(f"   Model Combinations: {len(combs_to_run)} ({', '.join(combs_to_run)})")
    print(f"   Scenarios:          {len(selected_scenarios)} ({', '.join(s['id'] for s in selected_scenarios)})")
    print(f"   Policy Backends:    {', '.join(p.upper() for p in policy_types)}")
    print(f"   Seeds per Cell:     {args.num_seeds} (Horizon: {args.num_steps or 'per-scenario default'})")
    print(f"   Total Evaluation:   {total_matrix_cells} scenario-policy blocks ({total_matrix_cells * args.num_seeds} episodes)")
    print("=" * 105)

    all_summaries = []

    for p_type in policy_types:
        port = args.policy_port
        if port is None:
            port = 5556 if p_type == "gr00t" else (8008 if p_type == "openpi" else 0)

        # Lifecycle management: Ensure target policy is active on GPU 1
        if not args.dry_run and p_type in ["gr00t", "openpi"]:
            if not probe_policy_endpoint("127.0.0.1", port):
                if start_policy_server is not None:
                    print(f"\n[ORCHESTRATOR] Policy server for {p_type.upper()} on port {port} is offline. Starting on GPU 1...")
                    start_policy_server(p_type)
                    # Wait for port to become ready
                    for attempt in range(40):
                        time.sleep(2)
                        if probe_policy_endpoint("127.0.0.1", port):
                            print(f"[ORCHESTRATOR] {p_type.upper()} policy server is ONLINE on port {port}.")
                            break
                    else:
                        print(f"[ERROR] Failed to start {p_type.upper()} policy server on port {port} within 80s.", file=sys.stderr)
                        sys.exit(1)
                else:
                    print(f"[ERROR] {p_type.upper()} policy server offline on port {port} and manage_backends not found.", file=sys.stderr)
                    sys.exit(1)

        for comb_id in combs_to_run:
            comb_info = CANDIDATE_COMBINATIONS.get(comb_id, {"name": comb_id, "suite": "Custom"})
            print(f"\n{'#' * 90}")
            print(f"🔬 BENCHMARKING COMBINATION: {comb_id} ({comb_info['name']}) [{comb_info['suite']}]")
            print(f"   Active Policy Backend:   {p_type.upper()} on Port {port}")
            print(f"{'#' * 90}")

            for scen in selected_scenarios:
                scen_steps = args.num_steps or scen["default_steps"]
                print("\n" + "-" * 85)
                print(f"🏁 RUNNING BENCHMARK BATCH: Scenario {scen['id']} ({scen['name']})")
                print(f"   Ontology:  {scen['ontology']}")
                print(f"   Policy:    {p_type.upper()} on Port {port}")
                print(f"   Pipeline:  {comb_id}")
                print(f"   Seeds:     {args.start_seed} through {args.start_seed + args.num_seeds - 1}")
                print("-" * 85)

                scen_summaries = []
                for seed in range(args.start_seed, args.start_seed + args.num_seeds):
                    res = run_single_seed_rollout(
                        scenario_cfg=scen,
                        seed=seed,
                        base_output_dir=args.output_dir,
                        policy_type=p_type,
                        port=port,
                        num_steps=scen_steps,
                        model_comb=comb_id,
                        ledger_path=args.ledger,
                        dry_run=args.dry_run,
                    )
                    scen_summaries.append(res)
                    all_summaries.append(res)

                # Compute scenario aggregate metrics
                num_seeds = len(scen_summaries)
                completions = sum(1 for s in scen_summaries if s["all_complete"])
                cr_chained = (completions / num_seeds) * 100.0 if num_seeds > 0 else 0.0
                avg_progress = (sum(s["progress_score"] for s in scen_summaries) / num_seeds) if num_seeds > 0 else 0.0
                zero_action_ok = sum(1 for s in scen_summaries if s["exit_code"] == 0)

                print("\n" + "." * 75)
                print(f"📊 SCENARIO {scen['id']} BATCH SUMMARY ({comb_id} | {p_type.upper()}):")
                print(f"   Chained Completion Rate (CR_chained): {cr_chained:.1f}% ({completions}/{num_seeds})")
                print(f"   Average Progress Score:              {avg_progress:.2f}")
                print(f"   Execution Stability Rate:            {(zero_action_ok / num_seeds) * 100:.1f}%")
                print("." * 75)

    # Print final consolidated table
    print("\n" + "=" * 115)
    print("📋 EXPERIMENT 04 NEURAL POLICY MASTER BENCHMARK MATRIX")
    print(f"   Total Evaluated Episodes: {len(all_summaries)}")
    print("=" * 115)
    print(f"{'Comb':<9} | {'Scen':<6} | {'Ontology':<22} | {'Policy':<8} | {'Seed':<5} | {'Score':<6} | {'Complete':<9} | {'Elapsed':<8}")
    print("-" * 115)
    for s in all_summaries:
        complete_str = "SUCCESS" if s["all_complete"] else "PARTIAL"
        print(
            f"{s.get('model_comb', 'N/A'):<9} | {s['scenario']:<6} | {s['ontology'][:22]:<22} | {s['policy_type']:<8} | "
            f"{s['seed']:<5} | {s['progress_score']:<6.2f} | {complete_str:<9} | {s['elapsed_seconds']}s"
        )
    print("=" * 115)

    # Save summary JSON
    summary_path = os.path.join(args.output_dir, f"exp04_master_benchmark_matrix.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(all_summaries, f, indent=2)
    print(f"\n✓ Saved consolidated master evaluation matrix -> {summary_path}\n")


if __name__ == "__main__":
    main()
