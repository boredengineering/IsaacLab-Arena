#!/usr/bin/env python3
"""
Candidate Model Downloader & Smoke Tester for Local Dual-Blackwell Pipeline.
Downloads models to ~/.cache/huggingface/hub and runs an isolated containerized
smoke test via vLLM on GPU 0, ensuring complete VRAM deallocation after each test.
"""

import argparse
import os
import subprocess
import sys
import time

CANDIDATES = [
    {
        "id": "Qwen/Qwen2.5-72B-Instruct-AWQ",
        "name": "Qwen 2.5 72B Instruct AWQ",
        "type": "text",
        "utilization": 0.85,
        "max_len": 2048,
    },
    {
        "id": "Qwen/Qwen3-32B-FP8",
        "name": "Qwen 3 32B FP8",
        "type": "text",
        "utilization": 0.65,
        "max_len": 2048,
    },
    {
        "id": "Qwen/Qwen3-VL-32B-Instruct-FP8",
        "name": "Qwen 3 VL 32B Instruct FP8",
        "type": "vision",
        "utilization": 0.70,
        "max_len": 2048,
    },
    {
        "id": "Qwen/Qwen3-30B-A3B-FP8",
        "name": "Qwen 3 30B A3B FP8 (MoE)",
        "type": "text",
        "utilization": 0.65,
        "max_len": 2048,
    },
    {
        "id": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "name": "DeepSeek R1 Distill Qwen 32B",
        "type": "text",
        "utilization": 0.75,
        "max_len": 2048,
    },
    {
        "id": "Qwen/QwQ-32B-AWQ",
        "name": "QwQ 32B AWQ",
        "type": "text",
        "utilization": 0.65,
        "max_len": 2048,
    },
]

def download_model(model_id: str):
    print(f"\n=======================================================")
    print(f"[DOWNLOAD] Starting download for: {model_id}")
    print(f"=======================================================")
    t0 = time.time()
    from huggingface_hub import snapshot_download
    snapshot_download(
        repo_id=model_id,
        max_workers=8,
        resume_download=True,
    )
    dt = time.time() - t0
    print(f"[DOWNLOAD COMPLETE] {model_id} downloaded in {dt:.1f} s ({dt/60:.2f} min).")

def smoke_test_model(candidate: dict):
    model_id = candidate["id"]
    util = candidate.get("utilization", 0.7)
    max_len = candidate.get("max_len", 2048)
    is_vision = candidate.get("type") == "vision"

    print(f"\n=======================================================")
    print(f"[SMOKE TEST] Launching isolated vLLM smoke test for: {model_id}")
    print(f"=======================================================")

    python_test_code = f"""
import sys, time
from vllm import LLM, SamplingParams

print('[CONTAINER] Initializing LLM engine for {model_id}...')
t0 = time.time()
llm = LLM(
    model='{model_id}',
    gpu_memory_utilization={util},
    max_model_len={max_len},
    trust_remote_code=True
)
print(f'[CONTAINER] Model initialized in {{time.time() - t0:.2f}}s')

sampling_params = SamplingParams(max_tokens=32, temperature=0.0)
prompt = 'Describe a clean robotic tabletop scene in one sentence.'
print(f'[CONTAINER] Submitting prompt: {{prompt}}')
t_gen = time.time()
outputs = llm.generate([prompt], sampling_params)
response = outputs[0].outputs[0].text.strip()
print(f'[CONTAINER] Generated response: {{response}}')
print(f'[CONTAINER] Inference took {{time.time() - t_gen:.2f}}s')
print('[CONTAINER] SMOKE TEST RESULT: PASSED')
"""

    docker_cmd = [
        "docker", "run", "--rm", "--gpus", "all",
        "-e", "CUDA_DEVICE_ORDER=PCI_BUS_ID",
        "-e", "CUDA_VISIBLE_DEVICES=0",
        "-v", "/root/.cache/huggingface:/root/.cache/huggingface",
        "--entrypoint", "python3",
        "vllm/vllm-openai:latest",
        "-c", python_test_code
    ]

    t0 = time.time()
    proc = subprocess.run(docker_cmd, capture_output=True, text=True)
    dt = time.time() - t0

    print("--- Docker Test Output ---")
    print(proc.stdout)
    if proc.returncode != 0:
        print("--- Docker Error Output ---", file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"Smoke test failed for {model_id} with exit code {proc.returncode}")

    print(f"[SMOKE TEST SUCCESS] {model_id} passed smoke test in {dt:.1f} s.")

    # Confirm VRAM release
    time.sleep(2)
    smi = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader"],
                         capture_output=True, text=True)
    print(f"[VRAM AUDIT AFTER TEST]:\n{smi.stdout.strip()}")

def main():
    parser = argparse.ArgumentParser(description="Download and smoke test candidate models")
    parser.add_argument("--model", type=str, default=None, help="Specific model ID to download and test")
    parser.add_argument("--all", action="store_true", help="Download and test all candidates sequentially")
    args = parser.parse_args()

    targets = []
    if args.model:
        targets = [c for c in CANDIDATES if c["id"] == args.model]
        if not targets:
            targets = [{"id": args.model, "name": args.model, "type": "text", "utilization": 0.7, "max_len": 2048}]
    elif args.all:
        targets = CANDIDATES
    else:
        print("Please specify --model <model_id> or --all")
        sys.exit(1)

    for c in targets:
        print(f"\n>>> PROCESSING: {c['id']} ({c['name']})")
        download_model(c["id"])
        smoke_test_model(c)
        print(f">>> FINISHED: {c['id']}\n")

if __name__ == "__main__":
    main()
