#!/usr/bin/env python3
"""
Workstation Model Backend Manager for Local Arena Experiments.
Controls containerized vLLM endpoints on GPU 0 and GPU 1, Colibrì streaming engines,
and ensures strict memory teardown to prevent VRAM collision.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

COLIBRI_DIR = "/workspaces/colibri"

MODEL_PRESETS = {
    "qwen-coder-32b": {
        "model": "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ",
        "utilization": 0.45,
        "max_len": 16384,
        "port": 8000,
        "device": 0,
    },
    "qwen3-32b-fp8": {
        "model": "Qwen/Qwen3-32B-FP8",
        "utilization": 0.50,
        "max_len": 16384,
        "port": 8000,
        "device": 0,
    },
    "qwq-32b": {
        "model": "Qwen/QwQ-32B-AWQ",
        "utilization": 0.45,
        "max_len": 16384,
        "port": 8000,
        "device": 0,
    },
    "qwen-72b": {
        "model": "Qwen/Qwen2.5-72B-Instruct-AWQ",
        "utilization": 0.55,
        "max_len": 12288,
        "port": 8000,
        "device": 0,
    },
    "deepseek-r1-32b": {
        "model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "utilization": 0.70,
        "max_len": 16384,
        "port": 8000,
        "device": 0,
    },
    "qwen3-30b-moe": {
        "model": "Qwen/Qwen3-30B-A3B-FP8",
        "utilization": 0.50,
        "max_len": 16384,
        "port": 8000,
        "device": 0,
    },
    "qwen-72b-awq": {
        "model": "Qwen/Qwen2.5-72B-Instruct-AWQ",
        "utilization": 0.80,
        "max_len": 8192,
        "port": 8000,
        "device": 0,
    },
    "qwen-vl-7b": {
        "model": "Qwen/Qwen2.5-VL-7B-Instruct",
        "utilization": 0.85,
        "max_len": 4096,
        "port": 8001,
        "device": 0,
    },
    "qwen3-vl-32b": {
        "model": "Qwen/Qwen3-VL-32B-Instruct-FP8",
        "utilization": 0.65,
        "max_len": 8192,
        "port": 8001,
        "device": 0,
    },
    "cosmos-reason": {
        "model": "nvidia/Cosmos-Reason2-2B",
        "utilization": 0.25,
        "max_len": 4096,
        "port": 8001,
        "device": 0,
    },
}

POLICY_PRESETS = {
    "gr00t": {
        "container": "gr00t-server",
        "image": "gr00t-dev:latest",
        "port": 5556,
        "device": 1,
        "protocol": "zeromq"
    },
    "openpi": {
        "container": "openpi-server",
        "image": "isaaclab_arena:openpi_server",
        "port": 8008,
        "device": 1,
        "protocol": "websocket"
    }
}

def stop_container(container_name: str):
    print(f"[STOP] Stopping Docker container {container_name}...")
    subprocess.run(["docker", "stop", container_name], capture_output=True)
    subprocess.run(["docker", "rm", container_name], capture_output=True)
    time.sleep(0.5)

def stop_colibri():
    print(f"[STOP] Stopping Colibrì engine if active...")
    if os.path.isdir(COLIBRI_DIR):
        subprocess.run(["python3", f"{COLIBRI_DIR}/c/coli", "stop"], capture_output=True)
    time.sleep(0.5)

def stop_all():
    print("=================================================================")
    print("[CLEANUP] Stopping all inference and policy backends (Releasing VRAM)...")
    print("=================================================================")
    stop_container("arena-vllm-spec")
    stop_container("arena-vllm-visual")
    stop_container("gr00t-server")
    stop_container("openpi-server")
    stop_colibri()
    print("[CLEANUP COMPLETE] Querying nvidia-smi:")
    res = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader"],
                         capture_output=True, text=True)
    print(res.stdout.strip())

def start_policy_server(policy_key: str, port_override: int = None, device_override: int = None):
    preset = POLICY_PRESETS.get(policy_key)
    if not preset:
        print(f"Unknown policy preset: {policy_key}. Available: {list(POLICY_PRESETS.keys())}", file=sys.stderr)
        sys.exit(1)

    container_name = preset["container"]
    port = port_override or preset["port"]
    device = device_override if device_override is not None else preset["device"]

    stop_container(container_name)

    print(f"[START] Launching {policy_key} policy server in {container_name} on GPU {device} (Port {port})...")
    if policy_key == "gr00t":
        # Resolve true host path for huggingface cache when executing from devcontainer
        host_hf_cache = "/root/.cache/huggingface"
        try:
            with open("/proc/self/mountinfo", "r") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 5 and parts[4] == "/root/.cache/huggingface":
                        host_hf_cache = parts[3]
                        break
        except Exception:
            pass

        # Launch gr00t-dev container or start existing stopped container
        check_existing = subprocess.run(["docker", "ps", "-a", "--filter", f"name=^/{container_name}$", "--format", "{{.Names}}"], capture_output=True, text=True)
        if check_existing.stdout.strip():
            subprocess.run(["docker", "start", container_name], check=True)
        else:
            docker_cmd = [
                "docker", "run", "-d",
                "--name", container_name,
                "--gpus", f'"device={device}"',
                "--network", "host",
                "--ipc", "host",
                "-e", "HF_HUB_OFFLINE=1",
                "-e", "TRANSFORMERS_OFFLINE=1",
                "-v", f"{host_hf_cache}:/root/.cache/huggingface",
                preset["image"],
                "/workspace/gr00t/.venv/bin/python", "/workspace/gr00t/gr00t/eval/run_gr00t_server.py",
                "--model-path", "nvidia/GR00T-N1.7-3B",
                "--embodiment-tag", "oxe_droid_relative_eef_relative_joint",
                "--device", "cuda",
                "--host", "0.0.0.0",
                "--port", str(port)
            ]
            subprocess.run(" ".join(docker_cmd), shell=True, check=True)
    elif policy_key == "openpi":
        repo_root = str(Path(__file__).resolve().parents[4])
        cache_dir = os.environ.get("OPENPI_CACHE_DIR", os.path.join(repo_root, "artifacts/openpi_cache"))
        host_cache_dir = cache_dir
        try:
            with open("/proc/self/mountinfo", "r") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 5 and parts[4] == repo_root:
                        host_cache_dir = cache_dir.replace(repo_root, parts[3])
                        break
        except Exception:
            pass

        local_policy_dir = os.path.join(cache_dir, "openpi-assets-simeval/pi05_droid_jointpos")
        container_policy_dir = "/cache/openpi/openpi-assets-simeval/pi05_droid_jointpos" if os.path.isdir(local_policy_dir) else "gs://openpi-assets-simeval/pi05_droid_jointpos"

        docker_cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--gpus", f'"device={device}"',
            "--network", "host",
            "-e", "OPENPI_DATA_HOME=/cache/openpi",
            "-e", "XLA_PYTHON_CLIENT_MEM_FRACTION=0.5",
            "-v", f"{host_cache_dir}:/cache/openpi",
            preset["image"],
            "uv", "run", "scripts/serve_policy.py",
            "--port", str(port),
            "policy:checkpoint",
            "--policy.config=pi05_droid_jointpos_polaris",
            f"--policy.dir={container_policy_dir}",
        ]
        subprocess.run(" ".join(docker_cmd), shell=True, check=True)

    print(f"Policy server {container_name} started on port {port}.")

def start_vllm(preset_key: str, container_name: str = None):
    preset = MODEL_PRESETS.get(preset_key)
    if not preset:
        print(f"Unknown preset: {preset_key}. Available: {list(MODEL_PRESETS.keys())}", file=sys.stderr)
        sys.exit(1)

    if container_name is None:
        container_name = "arena-vllm-visual" if preset.get("port") == 8001 else "arena-vllm-spec"

    stop_container(container_name)

    print(f"[START] Launching {preset['model']} in {container_name} on GPU {preset['device']} (Port {preset['port']})...")
    docker_cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "--gpus", f'"device={preset["device"]}"',
        "--network", "host",
        "--ipc", "host",
        "-e", "CUDA_DEVICE_ORDER=PCI_BUS_ID",
        "-v", "/root/.cache/huggingface:/root/.cache/huggingface",
        "vllm/vllm-openai:latest",
        "--model", preset["model"],
        "--port", str(preset["port"]),
        "--max-model-len", str(preset["max_len"]),
        "--gpu-memory-utilization", str(preset["utilization"]),
        "--enable-request-id-headers"
    ]

    subprocess.run(" ".join(docker_cmd), shell=True, check=True)
    print(f"Container {container_name} started. Waiting for endpoint readiness on port {preset['port']}...")
    wait_for_endpoint(f"http://127.0.0.1:{preset['port']}/v1/models")

def start_colibri_profile(profile_type: str):
    stop_all()
    print(f"[START] Launching Colibrì profile: {profile_type}...")
    if profile_type in ["glm53", "rtx6000", "workstation"]:
        script = f"{COLIBRI_DIR}/scripts/start_workstation_high_throughput_profile.sh"
    elif profile_type == "flash":
        script = f"{COLIBRI_DIR}/scripts/start_flash_profile.sh"
    else:
        print(f"Unknown profile: {profile_type}. Use 'glm53', 'rtx6000', or 'flash'", file=sys.stderr)
        sys.exit(1)

    subprocess.run(["bash", script], check=True)
    print("Colibrì started.")

def wait_for_endpoint(url: str, timeout_sec: int = 180):
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Backend-Manager"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status == 200:
                    print(f"Endpoint {url} is READY in {time.time() - t0:.1f}s.")
                    return True
        except Exception:
            pass
        time.sleep(2)
    print(f"Timed out waiting for {url}", file=sys.stderr)
    return False

def main():
    parser = argparse.ArgumentParser(description="Manage local workstation inference and policy backends")
    sub = parser.add_subparsers(dest="action", required=True)

    start_p = sub.add_parser("start", help="Start a vLLM preset (Cognitive Spec or Visual Critic)")
    start_p.add_argument("preset", choices=list(MODEL_PRESETS.keys()), help="Model preset to start")
    start_p.add_argument("--container", default=None, help="Container name override")

    start_pol = sub.add_parser("start-policy", help="Start a Policy Server on GPU 1 (GR00T or OpenPI)")
    start_pol.add_argument("policy", choices=list(POLICY_PRESETS.keys()), help="Policy server to start")
    start_pol.add_argument("--port", type=int, default=None, help="Port override")
    start_pol.add_argument("--device", type=int, default=1, help="GPU device ID (default: 1)")

    start_c = sub.add_parser("colibri", help="Start a Colibrì profile")
    start_c.add_argument("profile", choices=["glm53", "rtx6000", "workstation", "flash"], help="Colibrì profile to run")

    sub.add_parser("stop-all", help="Stop all running backends and release VRAM across both GPUs")
    sub.add_parser("status", help="Check status of all endpoints")

    args = parser.parse_args()

    if args.action == "start":
        start_vllm(args.preset, args.container)
    elif args.action == "start-policy":
        start_policy_server(args.policy, args.port, args.device)
    elif args.action == "colibri":
        start_colibri_profile(args.profile)
    elif args.action == "stop-all":
        stop_all()
    elif args.action == "status":
        from audit_hardware import check_endpoints, check_gpus
        check_gpus()
        check_endpoints()
    elif args.action == "colibri":
        start_colibri_profile(args.profile)
    elif args.action == "stop-all":
        stop_all()
    elif args.action == "status":
        from audit_hardware import check_endpoints, check_gpus
        check_gpus()
        check_endpoints()

if __name__ == "__main__":
    main()
