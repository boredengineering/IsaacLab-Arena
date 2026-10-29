# Local LLM & VLM Inference Runbook (`dev/0.3.1`)

Operational guide and architectural reference for running self-hosted local Large Language Models (LLMs) and Vision-Language Models (VLMs) with IsaacLab-Arena's `agentic_environment_generation` and self-healing loops on a **Dual-Blackwell Workstation** (**NVIDIA RTX PRO 6000 Blackwell 96 GB** + **NVIDIA GeForce RTX 5090 32 GB**).

---

## 1. Directory Contents

| Path | Description |
| :--- | :--- |
| **[`experiments/experiment_05.md`](experiments/experiment_05.md)** | Active milestone specification: *Closed-Loop VLA Articulation Grounding, OpenPI π₀.₅ Remediation & Scaled Cognitive Scene Decomposition Benchmarks* (where execution paused prior to the `dev/0.3.1` port). |
| **[`scripts/`](scripts/)** | OpenUSD fixture/articulation affordance introspection (`introspect_fixture_affordance.py`, `introspect_usd_affordance.py`), articulation verification (`verify_articulated_spec.py`), and experiment orchestration (`orchestrate_experiment.py`). |
| **[`vllm_patches/`](vllm_patches/)** | Local vLLM Hermes tool-call parser plugin (`hermes_tool_parser.py`). |

---

## 2. Dual-GPU Partitioning Architecture (128 GB Total VRAM)

Rather than tensor-splitting across heterogeneous GPUs, workloads are partitioned by function across the two Blackwell cards:

| Component | Target Device | Default Port | VRAM Budget | Role |
| :--- | :--- | :--- | :--- | :--- |
| **Neo4j 5.26 LPG** | Host CPU / RAM | `7688` (Bolt), `7475` (HTTP) | `0 GB` | Experience graph, reified spatial factors, and PROV-O lineage storage. |
| **Spec Generation LLM** | **GPU 0** (RTX PRO 6000, 96 GB) | `8000` | `~20–63 GB` | `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ` (or `Qwen2.5-72B-Instruct-AWQ`) via vLLM. |
| **Visual Scene Critic VLM** | **GPU 0** (RTX PRO 6000, 96 GB) | `8001` | `~14–27 GB` | `Qwen/Qwen2.5-VL-7B-Instruct` for Step-0 camera inspection. |
| **Isaac Sim / IsaacLab** | **GPU 1** (RTX 5090, 32 GB) | — | `~8–12 GB` | PhysX 5.4 simulation, Vulkan RTX offscreen rendering, and USD stage introspection. |
| **GR00T / OpenPI Policy Server** | **GPU 1** (RTX 5090, 32 GB) | `5556` (ZMQ) / `8000` | `~6–10 GB` | Closed-loop robot policy inference (`GR00T-N1.6-DROID` or OpenPI $\pi_{0.5}$). |

---

## 3. Step-by-Step Local Inference Bring-Up

### Step 1: Start Neo4j Experience Database (Host CPU)
```bash
docker run -d --name arena-envgen-neo4j \
  --restart unless-stopped \
  -p 127.0.0.1:7475:7474 \
  -p 127.0.0.1:7688:7687 \
  -e NEO4J_AUTH=neo4j/arena_local_password \
  --mount source=arena-envgen-neo4j-data,target=/data \
  neo4j:5.26-community
```

### Step 2: Launch Local vLLM Servers on GPU 0 (RTX PRO 6000 Blackwell)

#### Option A: Standard Dual-Service (32k Spec LLM on `:8000` + Visual VLM on `:8001`)
```bash
# 1. Spec Generation LLM (Port 8000, FP8 KV Cache)
docker run -d --name arena-vllm-spec \
  --gpus '"device=0"' \
  --network host \
  --ipc host \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:v0.10.0 \
    --model Qwen/Qwen2.5-Coder-32B-Instruct-AWQ \
    --port 8000 \
    --max-model-len 32768 \
    --kv-cache-dtype fp8 \
    --guided-decoding-backend outlines \
    --gpu-memory-utilization 0.65 \
    --api-key local-arena-token

# 2. Visual Critic VLM (Port 8001)
docker run -d --name arena-vllm-visual \
  --gpus '"device=0"' \
  --network host \
  --ipc host \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:v0.10.0 \
    --model Qwen/Qwen2.5-VL-7B-Instruct \
    --port 8001 \
    --max-model-len 8192 \
    --limit-mm-per-prompt image=4 \
    --gpu-memory-utilization 0.28 \
    --api-key local-arena-token
```

#### Option B: Long-Context 131k Spec LLM via YaRN RoPE Scaling (Port 8000)
> **Important**: `Qwen2.5-Coder-32B` has a base `max_position_embeddings` of `32768`. Exceeding 32k requires passing both `VLLM_ALLOW_LONG_MAX_MODEL_LEN=1` and `--hf-overrides` with YaRN factor `4.0`.

```bash
docker run -d --name arena-vllm-spec-131k \
  --restart unless-stopped \
  --gpus '"device=0"' \
  --network host \
  --ipc host \
  -e VLLM_ALLOW_LONG_MAX_MODEL_LEN=1 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:v0.10.0 \
    --model Qwen/Qwen2.5-Coder-32B-Instruct-AWQ \
    --port 8000 \
    --hf-overrides '{"max_position_embeddings": 131072, "rope_scaling": {"rope_type": "yarn", "factor": 4.0, "original_max_position_embeddings": 32768}}' \
    --max-model-len 131072 \
    --kv-cache-dtype fp8 \
    --guided-decoding-backend outlines \
    --gpu-memory-utilization 0.65 \
    --api-key local-arena-token
```

### Step 3: Verify Local Endpoints
```bash
curl -s http://127.0.0.1:8000/v1/models -H "Authorization: Bearer local-arena-token"
curl -s http://127.0.0.1:8001/v1/models -H "Authorization: Bearer local-arena-token"
```

---

## 4. Running Agentic Environment Generation & Grounded Verification

Inside the Arena simulation container (pinned to GPU 1 via `CUDA_VISIBLE_DEVICES=1`):

### A. Pure-Python Spec Resolution (`--mode resolve`)
```bash
docker exec "$ARENA_CONTAINER" su $(id -un) -c \
  "cd /workspaces/isaaclab_arena && \
   CUDA_VISIBLE_DEVICES=1 /isaac-sim/python.sh \
   isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
   --mode resolve \
   --env_name droid_banana_to_red_bowl \
   --prompt 'Droid picks up the yellow banana from the right side of the packing table and places it into the red bowl on the left.' \
   --base_url http://127.0.0.1:8000/v1 \
   --model Qwen/Qwen2.5-Coder-32B-Instruct-AWQ \
   --temperature 0.0 \
   --api_key local-arena-token"
```

### B. Full Grounded Resolution with 60-Step PhysX Settle & Step-0 VLM Critic (`--mode grounded-resolve`)
```bash
docker exec "$ARENA_CONTAINER" su $(id -un) -c \
  "cd /workspaces/isaaclab_arena && \
   CUDA_VISIBLE_DEVICES=1 \
   LOCAL_VLM_BASE_URL=http://127.0.0.1:8001/v1 \
   LOCAL_VLM_MODEL=Qwen/Qwen2.5-VL-7B-Instruct \
   LOCAL_VLM_API_KEY=local-arena-token \
   /isaac-sim/python.sh \
   isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
   --mode grounded-resolve \
   --env_name droid_banana_to_red_bowl \
   --prompt 'Droid picks up the yellow banana from the right side of the packing table and places it into the red bowl on the left.' \
   --base_url http://127.0.0.1:8000/v1 \
   --model Qwen/Qwen2.5-Coder-32B-Instruct-AWQ \
   --temperature 0.0 \
   --api_key local-arena-token"
```

### C. OpenUSD Affordance Introspection & Articulation Verification
```bash
# Introspect static fixture support patches and Z_base grounding:
docker exec "$ARENA_CONTAINER" su $(id -un) -c \
  "cd /workspaces/isaaclab_arena && \
   /isaac-sim/python.sh scripts/tools/introspect_fixture_affordance.py --help"

# Verify articulated scene clearances and joint limits (Experiment 05):
docker exec "$ARENA_CONTAINER" su $(id -un) -c \
  "cd /workspaces/isaaclab_arena && \
   /isaac-sim/python.sh scripts/tools/verify_articulated_spec.py --help"
```
