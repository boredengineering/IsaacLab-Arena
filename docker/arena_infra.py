#!/usr/bin/env python3
# Copyright (c) 2026, Isaac Lab-Arena Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Host and devcontainer infrastructure orchestrator for Isaac Lab-Arena.

Manages container lifecycles and endpoint readiness for:
- neo4j-arena: Neo4j 5.26 LPG Experience Graph (7688 Bolt, 7475 HTTP)
- arena-vllm-spec: Qwen2.5-Coder-32B-Instruct-AWQ on GPU 0 (8000 HTTP)
- arena-vllm-visual: Qwen2.5-VL-7B-Instruct on GPU 1 (8001 HTTP)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any

from isaaclab_arena.orchestration.infra_manager import InfraManager


SERVICES: dict[str, dict[str, Any]] = {
    "neo4j": {
        "container_name": "neo4j-arena",
        "image": "neo4j:5.26-community",
        "ports": ["7688:7687", "7475:7474"],
        "envs": ["NEO4J_AUTH=neo4j/isaaclab_arena_password"],
        "default_device": None,
        "run_args": ["neo4j"],
    },
    "llm": {
        "container_name": "arena-vllm-spec",
        "image": "vllm/vllm-openai:latest",
        "ports": ["8000:8000"],
        "envs": [],
        "default_device": "0",
        "run_args": [
            "vllm", "serve", "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ",
            "--port", "8000",
            "--max-model-len", "16384",
            "--gpu-memory-utilization", "0.90",
        ],
    },
    "vlm": {
        "container_name": "arena-vllm-visual",
        "image": "vllm/vllm-openai:latest",
        "ports": ["8001:8000"],
        "envs": [],
        "default_device": "1",
        "run_args": [
            "vllm", "serve", "Qwen/Qwen2.5-VL-7B-Instruct",
            "--port", "8000",
            "--max-model-len", "8192",
            "--gpu-memory-utilization", "0.85",
        ],
    },
}


def _get_docker_container_status(container_name: str) -> tuple[str, str]:
    """Inspect Docker container state and status string."""
    try:
        proc = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}|{{.State.Running}}", container_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return "not_found", "Container not created"
        parts = proc.stdout.strip().split("|")
        status = parts[0]
        return status, f"Container {status}"
    except Exception as exc:
        return "error", str(exc)


def cmd_status(args: argparse.Namespace) -> int:
    """Print status of all infrastructure containers and their endpoints."""
    mgr = InfraManager()
    probes = mgr.probe_all_endpoints(timeout=2.0)

    print("\n" + "=" * 80)
    print("  🏗️  Isaac Lab-Arena Infrastructure Status")
    print("=" * 80)
    print(f"{'SERVICE':<22} | {'CONTAINER':<20} | {'DOCKER':<10} | {'HEALTH':<12} | {'INFO / LATENCY'}")
    print("-" * 80)

    for key, cfg in SERVICES.items():
        cname = cfg["container_name"]
        dstatus, _ = _get_docker_container_status(cname)
        probe = probes.get(key, {})
        h_str = "✅ Ready" if probe.get("ok") else "❌ Unhealthy"
        lat = f"{probe.get('latency_s')}s" if probe.get("ok") else probe.get("info", "")[:35]
        s_name = probe.get("service", key)
        print(f"{s_name:<22} | {cname:<20} | {dstatus:<10} | {h_str:<12} | {lat}")

    print("=" * 80 + "\n")
    return 0 if all(p.get("ok") for p in probes.values()) else 1


def cmd_up(args: argparse.Namespace) -> int:
    """Start or create infrastructure containers and wait for readiness."""
    if shutil.which("docker") is None:
        print("[ERROR] 'docker' binary not found. Cannot launch infrastructure from this environment.", file=sys.stderr)
        return 2

    dev_spec = getattr(args, "device_spec", "0")
    dev_vlm = getattr(args, "device_vlm", "1")

    device_overrides = {
        "llm": dev_spec,
        "vlm": dev_vlm,
    }

    for key, cfg in SERVICES.items():
        cname = cfg["container_name"]
        dstatus, _ = _get_docker_container_status(cname)

        if dstatus == "running":
            print(f"[arena_infra] Container '{cname}' is already running.", flush=True)
            continue
        elif dstatus in ("exited", "created", "paused", "stopped"):
            print(f"[arena_infra] Starting stopped container '{cname}'...", flush=True)
            subprocess.run(["docker", "start", cname], check=True)
        else:
            # Container does not exist, provision new one
            print(f"[arena_infra] Provisioning new container '{cname}'...", flush=True)
            run_cmd = ["docker", "run", "-d", "--name", cname, "--restart", "unless-stopped"]
            for port in cfg["ports"]:
                run_cmd.extend(["-p", port])
            for env in cfg["envs"]:
                run_cmd.extend(["-e", env])

            dev = device_overrides.get(key, cfg["default_device"])
            if dev is not None:
                run_cmd.extend(["--gpus", f'"device={dev}"'])

            run_cmd.append(cfg["image"])
            run_cmd.extend(cfg["run_args"])
            subprocess.run(run_cmd, check=True)

    if getattr(args, "wait", True) or getattr(args, "verify", False):
        return cmd_wait(args)
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    """Stop infrastructure containers."""
    for key, cfg in SERVICES.items():
        cname = cfg["container_name"]
        dstatus, _ = _get_docker_container_status(cname)
        if dstatus == "running":
            print(f"[arena_infra] Stopping container '{cname}'...", flush=True)
            subprocess.run(["docker", "stop", cname], check=False)
        else:
            print(f"[arena_infra] Container '{cname}' is not running ({dstatus}).", flush=True)
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    """Restart infrastructure containers and wait for readiness."""
    cmd_down(args)
    return cmd_up(args)


def cmd_wait(args: argparse.Namespace) -> int:
    """Wait for all service endpoints to pass health checks."""
    timeout_s = getattr(args, "timeout", 120.0)
    mgr = InfraManager()
    deadline = time.time() + timeout_s

    print(f"[arena_infra] Waiting for infrastructure readiness (timeout={timeout_s}s)...", flush=True)
    while time.time() < deadline:
        probes = mgr.probe_all_endpoints(timeout=2.0)
        all_ok = all(p["ok"] for p in probes.values())
        if all_ok:
            print("[arena_infra] ✅ All services ready and responding!", flush=True)
            return cmd_status(args)
        time.sleep(2.0)

    print(f"\n[ERROR][arena_infra] Timed out waiting for services to become ready.", file=sys.stderr)
    cmd_status(args)
    return 1


def main() -> int:
    """CLI Entrypoint for arena_infra."""
    parser = argparse.ArgumentParser(description="Isaac Lab-Arena Infrastructure Orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = subparsers.add_parser("status", help="Display health status of containers and endpoints")

    # up
    p_up = subparsers.add_parser("up", help="Start stopped containers and wait for readiness")
    p_up.add_argument("--device-spec", default="0", help="GPU device ID for Spec LLM (default: 0)")
    p_up.add_argument("--device-vlm", default="1", help="GPU device ID for Visual VLM (default: 1)")
    p_up.add_argument("--timeout", type=float, default=120.0, help="Readiness timeout in seconds")
    p_up.add_argument("--verify", action="store_true", default=True, help="Verify health after startup")

    # down
    p_down = subparsers.add_parser("down", help="Stop infrastructure containers")

    # restart
    p_restart = subparsers.add_parser("restart", help="Restart infrastructure containers")
    p_restart.add_argument("--device-spec", default="0", help="GPU device ID for Spec LLM (default: 0)")
    p_restart.add_argument("--device-vlm", default="1", help="GPU device ID for Visual VLM (default: 1)")
    p_restart.add_argument("--timeout", type=float, default=120.0, help="Readiness timeout in seconds")

    # wait
    p_wait = subparsers.add_parser("wait", help="Wait for endpoints to respond")
    p_wait.add_argument("--timeout", type=float, default=120.0, help="Timeout in seconds")

    # verify
    p_verify = subparsers.add_parser("verify", help="Run end-to-end service probes")

    args = parser.parse_args()

    if args.command == "status":
        return cmd_status(args)
    elif args.command == "up":
        return cmd_up(args)
    elif args.command == "down":
        return cmd_down(args)
    elif args.command == "restart":
        return cmd_restart(args)
    elif args.command == "wait":
        return cmd_wait(args)
    elif args.command == "verify":
        return cmd_status(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
