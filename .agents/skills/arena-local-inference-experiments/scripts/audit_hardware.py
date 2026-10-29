#!/usr/bin/env python3
"""
Hardware & Microservice Health Auditor for Local Dual-Blackwell Arena Workstation.
Checks GPU VRAM usage, display status, Docker containers, and active inference endpoints.
"""

import json
import shutil
import socket
import subprocess
import sys
import urllib.request

ENDPOINTS = [
    {"name": "Cognitive Spec LLM (Port 8000)", "url": "http://127.0.0.1:8000/v1/models", "optional": False, "type": "http"},
    {"name": "Visual Scene Critic VLM (Port 8001)", "url": "http://127.0.0.1:8001/v1/models", "optional": True, "type": "http"},
    {"name": "Neo4j LPG Web (Port 7475)", "url": "http://127.0.0.1:7475", "optional": True, "type": "http"},
    {"name": "Neo4j Bolt RPC (Port 7688)", "host": "127.0.0.1", "port": 7688, "optional": True, "type": "socket"},
    {"name": "GR00T Policy Server (Port 5556)", "host": "127.0.0.1", "port": 5556, "optional": True, "type": "socket"},
    {"name": "OpenPI Policy Server (Port 8008)", "host": "127.0.0.1", "port": 8008, "optional": True, "type": "socket"},
]

def check_gpus():
    print("=================================================================")
    print("[1/4] GPU Hardware & VRAM Status (Dual Blackwell)")
    print("=================================================================")
    cmd = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.used,memory.free,memory.total,utilization.gpu,temperature.gpu,display_active",
        "--format=csv,noheader"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        lines = res.stdout.strip().split("\n")
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            idx, name, used, free, total, util, temp, disp = parts
            print(f"GPU {idx}: {name}")
            print(f"       VRAM: {used} / {total} (Free: {free}) | Util: {util} | Temp: {temp}C | Display: {disp}")
    except Exception as e:
        print(f"Error querying nvidia-smi: {e}", file=sys.stderr)

    # Check for active compute processes
    try:
        res = subprocess.run(["nvidia-smi", "-q", "-d", "PIDS"], capture_output=True, text=True, check=True)
        if "Processes                                          : None" in res.stdout:
            print("  -> Active Compute Processes: NONE (Clean state)")
        else:
            print("  -> Active Compute Processes detected:")
            for line in res.stdout.split("\n"):
                if "Process ID" in line or "Name" in line or "Used GPU Memory" in line:
                    print(f"     {line.strip()}")
    except Exception as e:
        pass

def check_docker():
    print("\n=================================================================")
    print("[2/4] Active Docker Containers")
    print("=================================================================")
    cmd = ["docker", "ps", "--format", "table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(res.stdout.strip())
    except Exception as e:
        print(f"Error querying docker: {e}", file=sys.stderr)

def check_endpoints():
    print("\n=================================================================")
    print("[3/4] Inference, Policy & Database Endpoints Readiness")
    print("=================================================================")
    for ep in ENDPOINTS:
        flag = "(Optional)" if ep["optional"] else "(Required when running Spec Gen)"
        if ep["type"] == "http":
            try:
                req = urllib.request.Request(ep["url"], headers={"User-Agent": "Arena-Auditor"})
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    status = resp.status
                    if status == 200:
                        print(f"  [ONLINE]  {ep['name']} -> HTTP {status}")
                    else:
                        print(f"  [WARN]    {ep['name']} -> HTTP {status}")
            except Exception:
                print(f"  [OFFLINE] {ep['name']} {flag}")
        elif ep["type"] == "socket":
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.5)
                res = s.connect_ex((ep["host"], ep["port"]))
                s.close()
                if res == 0:
                    print(f"  [ONLINE]  {ep['name']} -> Socket Port {ep['port']} OPEN")
                else:
                    print(f"  [OFFLINE] {ep['name']} {flag}")
            except Exception:
                print(f"  [OFFLINE] {ep['name']} {flag}")

def check_disk():
    print("\n=================================================================")
    print("[4/4] Fast Storage / NVMe Headroom")
    print("=================================================================")
    total, used, free = shutil.disk_usage("/")
    print(f"  Root / NVMe: Total={total/(1024**3):.1f} GB | Used={used/(1024**3):.1f} GB | Free={free/(1024**3):.1f} GB")

if __name__ == "__main__":
    check_gpus()
    check_docker()
    check_endpoints()
    check_disk()
    print("=================================================================\n")
