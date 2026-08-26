#!/usr/bin/env python3
"""Hardware and GPU microarchitecture probe for Physical AI workloads."""
import json
import shutil
import subprocess
import sys

def probe():
    data = {"gpu_detected": False, "blackwell_sm120": False, "vulkan_ready": False}
    if shutil.which("nvidia-smi"):
        try:
            res = subprocess.check_output(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"], text=True)
            data["gpu_detected"] = True
            data["gpu_info"] = [line.strip() for line in res.strip().split("\n") if line.strip()]
            if any("RTX 50" in g or "PRO 6000" in g or "B200" in g or "B100" in g for g in data["gpu_info"]):
                data["blackwell_sm120"] = True
        except Exception as e:
            data["error"] = str(e)
    if shutil.which("vulkaninfo"):
        data["vulkan_ready"] = True
    print(json.dumps(data, indent=2))

if __name__ == "__main__":
    probe()
