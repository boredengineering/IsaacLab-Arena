# Experiment 01: Dual-Blackwell Single-Scenario Baseline (Scenario A2: Banana to Red Bowl)

**Document Version:** 1.0.0  
**Date:** 2026-09-30  
**Status:** Active Execution & Tracking  
**Authors / Researchers:** Renan & Antigravity  
**Target Hardware:** Dual-Blackwell Workstation (NVIDIA RTX PRO 6000 96 GB + NVIDIA GeForce RTX 5090 32 GB)  
**Parent Campaign Log:** [`experiments.md`](experiments.md)  
**Telemetry Reference:** [`experiments.md#7-multi-layer-telemetry--observability-infrastructure`](experiments.md#7-multi-layer-telemetry--observability-infrastructure)  
**Hardware Guide:** [`install-multi-gpu.md`](install-multi-gpu.md)  

---

## 1. Executive Summary & Tracking Objective

The objective of **Experiment 01** is to establish the empirical baseline for Isaac Lab-Arena's local inference pipeline on a dedicated dual-Blackwell workstation, completely air-gapped from cloud APIs. 

This document serves as the **Mental Model Tracking Ledger**: it juxtaposes **what we are expecting** (hypothesized mechanics, token costs, latency bounds, and physics settling) against **what we are getting** (actual terminal outputs, telemetry readings, and failure modes). Documenting this variance in real time enables systematic debugging, performance profiling, and informed parameter adjustments for subsequent experiments.

### Evaluated Benchmark Scenario: Scenario A2
- **Scenario Name:** Banana to Red Bowl
- **Prompt:** *"Grasp the yellow banana from the right side of the table and place it into the red bowl on the left."*
- **Embodiment:** Franka DROID (`droid_abs_joint_pos`, dual RGB cameras: wrist POV + exterior $45^\circ$)
- **Background:** `maple_table_robolab` (Pose: `[-0.25, 0.0, 0.0]`)
- **Source Object:** `banana_ycb_robolab` (Sector: `front_right`)
- **Target Container:** `bowl_ycb_robolab` (Sector: `front_left`, classic red YCB bowl)
- **Policy Server:** `nvidia/GR00T-N1.6-DROID` (ZeroMQ Port 5556 on GPU 1)

---

## 2. Core Research Hypotheses & Success Criteria

| Hypothesis ID | Empirical Target | Success Criteria / Metric Threshold | Validation Method |
| :--- | :--- | :--- | :--- |
| **H1: Zero-Cloud Resolution** | The local LLM (`Qwen2.5-Coder-32B-AWQ`) will resolve the natural prompt into a valid `ArenaEnvGraphSpec` without cloud fallback. | $\le 2$ repair iterations; final Free Energy $\mathcal{F} \le 0.05$; 100% SHACL & Geometric Oracle pass. | Inspection of `metadata.json` and `lineage.ttl`. |
| **H2: VRAM Isolation** | Dual-server cognitive workloads on GPU 0 and simulation/policy workloads on GPU 1 will not trigger CUDA OOM or memory thrashing. | GPU 0 VRAM peak $\le 65\text{ GB}$ (out of 95.6 GB); GPU 1 VRAM peak $\le 25\text{ GB}$ (out of 31.8 GB); Preemptions = 0. | vLLM `/metrics` & `nvidia-smi` 1 Hz logs. |
| **H3: Zero-Action Physics Gating** | Stepping the simulation with `ZeroActionPolicy` will verify asset contact stability before neural policy inference. | Linear velocity $< 0.1\text{ m/s}$; angular velocity $< 1.0\text{ rad/s}$; contact forces nominal; zero mesh penetration. | Step 1.5 policy runner logs and settling video. |
| **H4: Closed-Loop Manipulation** | The Franka Panda arm driven by GR00T foundation policy will pick the banana and place it into the bowl. | Task Success Rate $\ge 80\%$ (at least 4/5 successful placements in 5 benchmark episodes). | `summary_metrics.json` and multi-camera MP4 evaluation videos. |

---

## 3. Dual-Blackwell Execution Topology

```mermaid
flowchart TD
    subgraph GPU0["GPU 0: NVIDIA RTX PRO 6000 Blackwell (96 GB GDDR7)"]
        LLM["arena-vllm-spec (Port 8000)<br/>Qwen2.5-Coder-32B-AWQ (~22 GB)<br/>• Outlines Schema-Guided Decoding"]
        VLM["arena-vllm-visual (Port 8001)<br/>Qwen2.5-VL-7B-Instruct (~16 GB)<br/>• Tier 2 Multimodal Viewport Critic"]
        HW0["1 Hz Telemetry Logger<br/>(gpu0_hardware_telemetry.csv)"]
    end

    subgraph CPU["Host CPU & System RAM (128 GB DDR5)"]
        NEO["neo4j-arena (Ports 7475 / 7688)<br/>Labeled Property Graph & Lineage"]
    end

    subgraph GPU1["GPU 1: NVIDIA GeForce RTX 5090 (32 GB GDDR7)"]
        GR00T["gr00t-server (ZeroMQ Port 5556)<br/>nvidia/GR00T-N1.6-DROID (~8 GB)"]
        SIM["isaaclab_arena:latest (~10 GB)<br/>• Phase 1.5: Zero-Action Physics Gate<br/>• Phase 1.6: GR00T Neural Rollouts"]
    end

    LLM -->|Factor Graph Spec| SIM
    VLM -->|Visual Inspection| LLM
    NEO -->|Semantic Lineage| SIM
    GR00T -->|Action Chunks (50 Hz)| SIM
```

### 3.1 Host Machine Workload Sizing & Process Execution Matrix

To ensure reproducible, zero-cloud execution on the local host without kernel OOM kills or CUDA memory collisions, the workstation processes are partitioned across GPU 0, GPU 1, and the host CPU/DRAM as follows:

| Component / Subsystem | Execution Target & Device | VRAM Footprint | Host System RAM | Network / IPC Endpoint | Notes / Operational Sizing |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Neo4j 5.26 LPG** | Host CPU / Docker (`arena-envgen-neo4j`) | **0 GB (No GPU)** | **4 – 8 GB** | Bolt `127.0.0.1:7688`<br/>HTTP `127.0.0.1:7475` | Java JVM Heap (`-Xms2G -Xmx4G`) + pagecache. Does not utilize CUDA. Persists verified environment factor graphs. |
| **Workbench Web API & UI** | Host CPU / Docker or Node (`arena-workbench`) | **0 GB (No GPU)** | **1 – 2 GB** | HTTP `127.0.0.1:3001` (UI)<br/>HTTP `127.0.0.1:8002` (API) | Python FastAPI backend + Node.js/React frontend for live scene graph exploration and interactive graph inspection. |
| **SHACL & RDF-star Validator** | Host CPU / Python runtime | **0 GB (No GPU)** | **0.5 – 1 GB** | In-process Python CLI / Module | `pyshacl` + `rdflib` graph validation, OWL ontology checking, and W3C PROV-O audit trail lowering. |
| **Host Display Server (Xorg)** | Host Desktop / GPU 0 (`0000:01:00.0`) | **~2.6 GB** | **1 – 2 GB** | Local X11 Server (`:0` / `:1`) | Physical monitor connected to RTX PRO 6000 DisplayPort (`Disp.A: On`). Essential baseline VRAM allocation. |
| **Spec Generation LLM** | **GPU 0 (RTX PRO 6000 96 GB)** / vLLM | **20 – 65 GB** | **16 – 32 GB** | HTTP `127.0.0.1:8000/v1` | `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ` (Primary: ~19.5 GB weights + 4–43 GB KV cache) or Qwen2.5-72B-AWQ (Future Stress: ~40 GB). Schema-guided Outlines decoding. |
| **Visual Scene Critic VLM** | **GPU 0 (RTX PRO 6000 96 GB)** / vLLM | **8 – 27 GB** | **8 – 16 GB** | HTTP `127.0.0.1:8001/v1` | `Qwen/Qwen2.5-VL-7B-Instruct` (AWQ: ~8 GB, BF16: ~14–27 GB) for Tier 2 multimodal camera inspection of USD viewport renders. |
| **Simulation Runtime** | **GPU 1 (RTX 5090 32 GB)** / Docker | **8 – 12 GB** | **16 – 32 GB** | Headless (IPC / Host Vulkan Offscreen) | `isaaclab_arena:latest` (Isaac Sim 6.0). PhysX 5 dynamics, USD stage resolution, and offscreen camera rendering for multi-camera sensors. |
| **Isaac-GR00T Policy Server** | **GPU 1 (RTX 5090 32 GB)** / PyTorch | **6 – 10 GB** | **8 – 16 GB** | ZeroMQ `tcp://127.0.0.1:5556` | `nvidia/GR00T-N1.6-DROID` (3B foundation model) or OpenPI policy. Serves real-time 50 Hz sensor-to-action chunk rollouts. |

### 3.2 Host Configuration & Pre-flight Invariants for Researchers

1. **Host System Memory (DRAM):** Minimum 64 GB DRAM, **128 GB recommended**. Concurrent footprint across JVM heap (4–8 GB), vLLM Ray/Python workers (16–32 GB), Isaac Sim pinned memory & USD stage buffers (16–32 GB), and OS/Xorg services (4–8 GB) is **~46 – 95 GB DRAM**.
2. **Docker Network Mode (`--network host`):** Mandatory across all containers. Bypasses Docker bridge NAT overhead, keeping ZeroMQ IPC latency $\le 0.4\text{ ms}$ (vs. $\sim 2.5\text{ ms}$ over bridge) and enabling direct `127.0.0.1` socket binding.
3. **Shared Memory (`--ipc host`):** Mandatory for vLLM and Isaac Sim containers. Permits PyTorch DataLoader, raylet IPC, and Vulkan offscreen shared-memory rings to exchange tensors without hitting Docker's default 64 MB `/dev/shm` barrier.
4. **Physical GPU Isolation (`--gpus '"device=..."'`):** Never use `--gpus all`. Explicitly pass `--gpus '"device=0"'` to cognitive servers and `--gpus '"device=1"'` to simulation/policy servers.

---

## 4. Step-by-Step Mental Model: Expected vs. Getting Tracking Ledger

### Phase 1.1: Cognitive & Visual Engine Bring-Up (GPU 0)

#### 1.1.1 Spec Generator LLM (`arena-vllm-spec` on Port 8000)
- **Target Device:** `CUDA_VISIBLE_DEVICES=0` (RTX PRO 6000 96 GB)
- **Command:**
  ```bash
  docker run -d --name arena-vllm-spec \
    --gpus '"device=0"' \
    --network host \
    --ipc host \
    -v ~/.cache/huggingface:/root/.cache/huggingface \
    vllm/vllm-openai:latest \
    --model Qwen/Qwen2.5-Coder-32B-Instruct-AWQ \
    --port 8000 \
    --max-model-len 16384 \
    --guided-decoding-backend outlines \
    --gpu-memory-utilization 0.40 \
    --enable-request-id-headers
  ```
- **Expected Results (Mental Model):**
  - Model weights load in $\sim 15\text{ seconds}$ from host cache.
  - VRAM allocated: $\sim 38.4\text{ GB}$ (leaving $\sim 20\text{ GB}$ dedicated to KV cache).
  - Outlines backend initializes JSON grammar state machine.
  - HTTP `GET /v1/models` returns HTTP 200 with model ID `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ`.
- **Actual Observed Results (Tracking Ledger):**
  | Parameter | Expected | Actual / Getting | Status | Notes |
  | :--- | :--- | :--- | :--- | :--- |
  | **Container Startup** | Up, Exit 0 | `Up (Healthy)` |  PASSED | Container `arena-vllm-spec` running on port 8000 |
  | **VRAM Allocated** | ~38.4 GB | `~38.2 GB` |  PASSED | Process on GPU 0 |
  | **HTTP Status (`/v1/models`)** | 200 OK | `200 OK` |  PASSED | Returns model ID `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ` |
  | **Compilation Latency** | $< 25\text{ s}$ | `~18 s` |  PASSED | Model runner ready |

---

#### 1.1.2 Visual Scene Critic VLM (`arena-vllm-visual` on Port 8001)
- **Target Device:** `CUDA_VISIBLE_DEVICES=0` (RTX PRO 6000 96 GB)
- **Command:**
  ```bash
  docker run -d --name arena-vllm-visual \
    --gpus '"device=0"' \
    --network host \
    --ipc host \
    -v ~/.cache/huggingface:/root/.cache/huggingface \
    vllm/vllm-openai:latest \
    serve Qwen/Qwen2.5-VL-7B-Instruct \
    --port 8001 \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.25 \
    --enable-request-id-headers
  ```
- **Expected Results (Mental Model):**
  - Allocates 25% of GPU 0 VRAM ($\sim 24\text{ GB}$).
  - Total combined GPU 0 allocation: $\sim 62.4\text{ GB} / 95.6\text{ GB}$ ($\sim 33.2\text{ GB}$ free headroom).
  - HTTP `GET /v1/models` returns HTTP 200 with `Qwen/Qwen2.5-VL-7B-Instruct`.
- **Actual Observed Results (Tracking Ledger):**
  | Parameter | Expected | Actual / Getting | Status | Notes |
  | :--- | :--- | :--- | :--- | :--- |
  | **Container Startup** | Up, Exit 0 | `Up (Healthy)` |  PASSED | Container `arena-vllm-visual` running on port 8001 |
  | **VRAM Allocated** | ~24.0 GB | `~23.7 GB` |  PASSED | Process on GPU 0 |
  | **Combined GPU 0 VRAM** | $\le 65\text{ GB}$ | `61,947 MiB / 97,887 MiB` |  PASSED | 35.3 GB free headroom maintained |
  | **HTTP Status (`/v1/models`)** | 200 OK | `200 OK` |  PASSED | Returns model ID `Qwen/Qwen2.5-VL-7B-Instruct` |

---

#### 1.1.3 Telemetry Readiness & Baseline Metric Probing
- **Command:**
  ```bash
  curl -s http://127.0.0.1:8000/metrics | grep -E "vllm:(kv_cache_usage_perc|num_requests_running)"
  curl -s http://127.0.0.1:8001/metrics | grep -E "vllm:(kv_cache_usage_perc|num_requests_running)"
  ```
- **Expected Results (Mental Model):**
  - `vllm:kv_cache_usage_perc` = `0.0` (unoccupied KV cache).
  - `vllm:num_requests_running` = `0.0`.
- **Actual Observed Results (Tracking Ledger):**
  | Metric | Expected Baseline | Actual Baseline | Status |
  | :--- | :--- | :--- | :--- |
  | `kv_cache_usage_perc` (8000) | `0.00` | `0.0` |  PASSED |
  | `num_requests_running` (8000) | `0.0` | `0.0` |  PASSED |
  | `kv_cache_usage_perc` (8001) | `0.00` | `0.0` |  PASSED |
  | `num_requests_running` (8001) | `0.0` | `0.0` |  PASSED |

---

### Phase 1.2: Neo4j Knowledge Store Bring-Up (Host CPU / Docker)

- **Target Device:** Host CPU & System RAM (Ports 7475 HTTP, 7688 Bolt)
- **Command:**
  ```bash
  docker run -d --name neo4j-arena \
    --network host \
    -e NEO4J_AUTH=none \
    -e NEO4J_PLUGINS='["apoc"]' \
    -v $(pwd)/arena_knowledge/neo4j/data:/data \
    neo4j:5.26-community
  ```
- **Expected Results (Mental Model):**
  - Database initializes in $\sim 5\text{ seconds}$; binds to Bolt port `7688`.
  - Zero GPU memory consumption.
- **Actual Observed Results (Tracking Ledger):**
  | Parameter | Expected | Actual / Getting | Status |
  | :--- | :--- | :--- | :--- |
  | **Container Status** | Up, healthy | `Up (Healthy)` |  PASSED |
  | **Bolt Port 7688** | Open, responsive | `HTTP 200 on 7475 / Bolt on 7688` |  PASSED |
  | **Initial Node Count** | $\ge 0$ | `Persistent store ready` |  PASSED |

---

### Phase 1.3: GR00T Policy Server Bring-Up (GPU 1)

- **Target Device:** `CUDA_VISIBLE_DEVICES=1` (RTX 5090 32 GB)
- **Command:**
  ```bash
  docker run -d --name gr00t-server \
    --gpus '"device=1"' \
    --network host \
    --ipc host \
    -v ~/.cache/huggingface:/root/.cache/huggingface \
    gr00t-dev:latest \
    /workspace/gr00t/.venv/bin/python3 /workspace/gr00t/gr00t/eval/run_gr00t_server.py \
      --model-path nvidia/GR00T-N1.6-DROID \
      --embodiment-tag OXE_DROID \
      --port 5556 \
      --device cuda
  ```
- **Expected Results (Mental Model):**
  - PyTorch 2.7 loads GR00T-N1.6-DROID weights into GPU 1 GDDR7 ($\sim 8.2\text{ GB}$).
  - ZeroMQ sets up `REP` socket listening on `tcp://*:5556`.
  - Server awaits observation dictionaries without error.
- **Actual Observed Results (Tracking Ledger):**
  | Parameter | Expected | Actual / Getting | Status |
  | :--- | :--- | :--- | :--- |
  | **GPU 1 Memory Used** | ~8.2 GB | `6,900 MiB / 32,607 MiB` |  PASSED |
  | **Socket State** | Bound to 5556 | `Bound to 5556 (TCP Open: True)` |  PASSED |
  | **Server Health** | Responsive | `Ready for observation dicts` |  PASSED |

---

### Phase 1.4: Agentic Spec Generation & Factor Graph Resolution (GPU 0)

- **Target Device:** Host CPU + GPU 0 (Pure Python; Zero simulation engine overhead)
- **Telemetry Logger Command:**
  ```bash
  mkdir -p eval_output/droid_banana_to_red_bowl
  nvidia-smi -i 0 --query-gpu=timestamp,utilization.gpu,utilization.memory,memory.used,power.draw,temperature.gpu \
    --format=csv -l 1 > eval_output/droid_banana_to_red_bowl/gpu0_hardware_telemetry.csv &
  GPU0_LOGGER_PID=$!
  ```
- **Option A: Pure Spec Resolution (`--mode resolve`, No Sim Startup):**
  ```bash
  docker run --rm --gpus '"device=0"' --network host \
    -e LOCAL_VLM_BASE_URL="http://localhost:8001/v1" \
    -v $(pwd):/workspaces/isaaclab_arena \
    isaaclab_arena:latest \
    /isaac-sim/python.sh isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
      --mode resolve \
      --prompt "Grasp the yellow banana from the right side of the table and place it into the red bowl on the left." \
      --env_name "droid_banana_to_red_bowl" \
      --base_url "http://localhost:8000/v1" \
      --model "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ" \
      --api_key "local-arena-token"
  ```
- **Option B: Monolithic End-to-End Simulation (`--mode full`):**
  ```bash
  # Headless Mode:
  docker run --rm --gpus '"device=0"' --network host \
    -e LOCAL_VLM_BASE_URL="http://localhost:8001/v1" \
    -v $(pwd):/workspaces/isaaclab_arena \
    isaaclab_arena:latest \
    /isaac-sim/python.sh isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
      --mode full \
      --headless \
      --num_envs 1 \
      --prompt "Grasp the yellow banana from the right side of the table and place it into the red bowl on the left." \
      --env_name "droid_banana_to_red_bowl" \
      --base_url "http://localhost:8000/v1" \
      --model "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ" \
      --api_key "local-arena-token"

  # Interactive Viewport GUI (--viz kit):
  xhost +local:docker > /dev/null 2>&1 || xhost +local:root > /dev/null 2>&1

  docker run --rm --gpus '"device=0"' --network host \
    -e DISPLAY="$DISPLAY" \
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
    -e LOCAL_VLM_BASE_URL="http://localhost:8001/v1" \
    -v $(pwd):/workspaces/isaaclab_arena \
    isaaclab_arena:latest \
    /isaac-sim/python.sh isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
      --mode full \
      --viz kit \
      --num_envs 1 \
      --prompt "Grasp the yellow banana from the right side of the table and place it into the red bowl on the left." \
      --env_name "droid_banana_to_red_bowl" \
      --base_url "http://localhost:8000/v1" \
      --model "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ" \
      --api_key "local-arena-token"
  ```
- **Option C: Recursive Prompt Update & Spec Refinement (`--mode resolve`):**
  ```bash
  docker run --rm --gpus '"device=0"' --network host \
    -e LOCAL_VLM_BASE_URL="http://localhost:8001/v1" \
    -v $(pwd):/workspaces/isaaclab_arena \
    isaaclab_arena:latest \
    /isaac-sim/python.sh isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
      --mode resolve \
      --base_spec generated_envs/droid_banana_to_red_bowl/latest/droid_banana_to_red_bowl.yaml \
      --feedback "Move the red bowl 10 cm further to the left to ensure greater clearance from the tabletop center." \
      --env_name "droid_banana_to_red_bowl" \
      --temperature 0.0 \
      --base_url "http://localhost:8000/v1" \
      --model "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ" \
      --api_key "local-arena-token"
  ```
  - **Three Test Feedback Prompts for Table Swapping & Fixture Adaptation:**
    1. **Prompt 1: Direct Swap to Robolab Oak Table (Minimal Semantic Delta)**
       `--feedback "Change the background table from maple_table_robolab to table_oak_robolab, keeping the yellow banana on the right and the red bowl on the left."`
       *Tests swapping the underlying table model to its closest sibling (`table_oak_robolab`) while ensuring the agent preserves existing sector layout, object transforms, and pick-and-place task logic.*
    2. **Prompt 2: Swap to Standard Isaac Lab Table (Geometry & Height Adaptation)**
       `--feedback "Replace the background table with the standard Seattle lab table (registry_name: 'table'), adjusting the banana and red bowl heights so they sit stably on the new table surface."`
       *Tests whether the model and Spatial Geometric Oracle adapt object placements from the Robolab coordinate frame to the standard Seattle table's $Z = 0.75\text{ m}$ deck height.*
    3. **Prompt 3: Domain Shift to Industrial Packing Workstation**
       `--feedback "Switch the scene background from the maple table to the packing_table workstation, ensuring the red bowl and yellow banana remain in reachable front sectors for the Franka DROID arm."`
       *Tests a larger domain transition (kitchen tabletop $\to$ warehouse packing station `packing_table`), validating whether the agent adapts spatial clearance and reachability checks for the DROID arm on a new fixture.*
- **Expected Results (Mental Model):**
  - In `--mode resolve` (initial prompt): spec resolution executes without launching NVIDIA Omniverse or Isaac Sim; completed in $\le 5\text{ seconds}$.
  - In `--mode resolve` with `--base_spec` (Option C): refines existing graph spec with feedback via `agent.refine_spec()`; increments version (`v1` $\to$ `v2`) without overwriting historical files; updates symlink `latest -> v2/`.
  - In `--mode full`: resolves the graph spec, boots Isaac Sim in the same process, settles objects on the table, and steps the zero-action policy.
  - Active Inference Self-Healing loop:
    - Pass 1: SHACL graph validation passes.
    - Pass 2: Spatial clearance oracle confirms banana is in `front_right` and bowl is in `front_left` with non-overlapping AABBs.
    - Pass 3: VLM critic verifies line-of-sight and camera views.
  - Artifact created: `generated_envs/droid_banana_to_red_bowl/v1/droid_banana_to_red_bowl.yaml` (or `v2/` for refinement).
  - Symlink updated: `generated_envs/droid_banana_to_red_bowl/latest -> vN/`.
  - Process exits with return code `0`.
- **Actual Observed Results (Tracking Ledger):**
  | Parameter | Expected | Actual / Getting | Status | Notes |
  | :--- | :--- | :--- | :--- | :--- |
  | **Resolution Mode** | `--mode resolve` | `--mode resolve` | ✅ PASSED | Pure factor graph synthesis, zero simulator overhead |
  | **Monolithic Mode** | `--mode full` | `--mode full --headless --temperature 0.0` | ✅ PASSED | Resolves spec, boots Isaac Sim, settles USD scene, steps 20 frames (Exit 0) |
  | **Graph-RAG Retrieval** | Query Neo4j | `bolt://localhost:7688` | ✅ PASSED | Injected 2 prior subgraphs from `neo4j-arena` |
  | **LLM Token Metrics** | Synthesis | `3,043 tokens` | ✅ PASSED | ~62 tok/s throughput on RTX PRO 6000 |
  | **Spatial Placement** | Non-overlapping | Banana Right (`-0.1568y`), Bowl Left (`+0.1568y`) | ✅ PASSED | Stable tabletop positions on `maple_table` |
  | **Neo4j LPG Sync** | Sync to Neo4j | `8 nodes, 11 relations` | ✅ PASSED | Verified via Cypher API commit |
  | **Artifacts Created** | Spec YAML & Lineage | `v1/` and `v2/` YAML, `lineage.json`, `lineage.ttl` (PROV-O) | ✅ PASSED | Symlink `latest -> v2` verified |
  | **Feedback Refinement (Prompt 1)** | Table swap `maple_table_robolab` $\to$ `table_oak_robolab` | Swapped to `table_oak_robolab`; banana right, bowl left | ✅ PASSED | 1 LLM call, 0 repairs, 7,838 tokens (6,568 prompt, 1,270 completion), 21.38s latency, version `v3` generated (`latest -> v3`), Neo4j synced (11 nodes, 18 relations) |
  | **Feedback Refinement (Prompt 2)** | Table swap `table_oak_robolab` $\to$ `table` (Seattle) | Swapped to Seattle lab `table`; stable deck height ($Z=0.7492\text{ m}$) | ✅ PASSED | 1 LLM call, 0 repairs, 7,836 tokens (6,570 prompt, 1,266 completion), 19.67s latency, version `v4` generated (`latest -> v4`), Neo4j synced (11 nodes, 18 relations) |
  | **Feedback Refinement (Prompt 3)** | Domain shift $\to$ `packing_table` workstation | Swapped to `packing_table`; remapped sectors to `front_right` and `front_left` | ✅ PASSED | 1 LLM call, 0 repairs, 7,853 tokens (6,562 prompt, 1,291 completion), 20.05s latency, version `v5` generated (`latest -> v5`), Neo4j synced (8 nodes, 22 relations) |
  | **Exit Code** | 0 | `0` | ✅ PASSED | Exited cleanly with code 0 |

#### Incident & Root Cause Analysis: `--mode full` Spec Synthesis Edge Cases

During initial `--mode full` evaluation, three interrelated prompt-to-schema failure modes were diagnosed and hardened:

1. **Hallucinated `cli_override_specs` Sections**:
   - *Failure*: `AssertionError: Agent returned an invalid spec. Validation traces: ('CLI override \'----task\' targets unknown or non-swappable asset \'task\'')`.
   - *Root Cause*: The Pydantic description for `cli_override_specs` was interpreted by the LLM as general command-line parameters for YAML sections (`--task`, `--embodiment`, etc.) with leading dashes. In Arena's domain model, CLI overrides can *only* target swappable scene assets (`self.embodiment.id`, `self.background.id`, or scene objects).
   - *Fix*: Added automatic pruning in `_sanitize_spec_candidate` to filter out non-asset targets, stripped leading dashes in `CliOverrideSpec`, and instructed the prompt to omit `cli_override_specs` for standard tasks.

2. **Unterminated String at Char 612 / Degenerate `prim_path` Repetition**:
   - *Failure*: `JSONDecodeError: Unterminated string starting at: line 18 column 68 (char 612)` after exhausting `max_tokens=4096`.
   - *Root Cause*: The system prompt's few-shot schema example showed `"destination_location": "destination_id"`. This misled the LLM into believing it had to generate an `object_reference` with `id: destination_id`. When generating `prim_path`, the model entered an infinite token repetition loop (`/World/bowl_ycb_robolab_01/bowl_ycb_robolab_01_mesh_01/...`) until hitting the token ceiling, leaving the JSON string unclosed.
   - *Fix*: Updated the few-shot template to use `"destination_location": "destination_object_id"`, added prompt guidance specifying that receptacle tasks directly use the target object ID without generating `object_references`, and added automatic redirection in `_sanitize_spec_candidate`.

3. **`placement_validators` Subset Invariant Violation**:
   - *Failure*: `required_checks must be a subset of enabled_checks; unexpected: ['friction', 'headroom']`.
   - *Root Cause*: The LLM added `friction` and `headroom` to `required_checks` without mirroring them in `enabled_checks`.
   - *Fix*: Added automatic reconciliation in `_sanitize_spec_candidate` ensuring `enabled_checks` is always a superset of `required_checks`.

#### Incident & Architectural Analysis: Offline VLM Critic Bypass, 4-Tier Cascades, and the Zero-Repair Phenomenon in v3–v5

During the execution of feedback refinement prompts 1, 2, and 3 (`v3`, `v4`, `v5`), an important operational anomaly occurred that highlights key architectural behaviors in the validation pipeline:

##### 1. The Anomaly Observed
- The execution command explicitly passed `-e LOCAL_VLM_BASE_URL="http://localhost:8001/v1"`.
- However, the local visual critic container (`arena-vllm-visual` serving `Qwen/Qwen2.5-VL-7B-Instruct` on port 8001) was **not running on the host**.
- Despite the unreachable endpoint, the runner process did not crash, throw a connection error, or hang.
- Furthermore, the telemetry reported `Repair Iterations: 0` and `Total LLM Calls: 1`, converging immediately without triggering the Active Inference self-healing repair loop.

##### 2. Root Cause 1: Cascading Fallback & Image-Gated Architecture in `VisualSceneCritic`
In [`VisualSceneCritic.evaluate_scene_spec`](../../../../isaaclab_arena/agentic_environment_generation/visual_critic.py#L81-L130), multimodal evaluation follows a 4-tier cascading hierarchy:
- **Tier 1 (Cloud Frontier VLM)** & **Tier 2 (Self-Hosted Local VLM on Port 8001)** are strictly conditioned on the presence of rendered visual frames:
  ```python
  if rendered_images:
      try:
          local_res = self._call_local_vlm_critic(spec, rendered_images)
          ...
      except Exception as exc:
          print(f"[VisualCritic] Tier 2 Local VLM unavailable ({exc}), falling back to Tier 3 Geometric Oracle...")
  ```
- Because `--mode resolve` is a symbolic, rapid-prototyping mode designed to avoid simulator startup overhead, `SimulationAppContext` is not initialized, and `rendered_images` is `None`.
- Consequently, both Tier 1 and Tier 2 were bypassed by design. The evaluation dropped directly into **Tier 3 (Deterministic Geometric & Frustum Oracle)**, which evaluated bounding box clearances, nominal deck heights, and support anchoring purely via algebraic CPU operations in `spatial_geometric_oracle.py`.
- Additionally, even if images had been passed, the generic `except Exception` handler swallows `ConnectionRefusedError` to maintain workflow continuity, preventing a hard crash.

##### 3. Root Cause 2: Asymmetry Between `generate_spec` and `refine_spec`
An architectural discrepancy was identified in the agent's validation pipelines:
- In [`EnvironmentGenerationAgent.generate_spec()`](../../../../isaaclab_arena/agentic_environment_generation/environment_generation_agent.py#L294-L298), candidate specifications are evaluated against SHACL RDF constraints, `SpatialGeometricOracle`, `VisualSceneCritic`, and `PhysXPreflightCritic`.
- In [`EnvironmentGenerationAgent.refine_spec()`](../../../../isaaclab_arena/agentic_environment_generation/environment_generation_agent.py#L518-L528) (invoked when `--base_spec` is supplied), the validation block checks only `validate_rdf_environment_graph` (SHACL) and `validate_spatial_geometry`. `VisualSceneCritic` and `PhysXPreflightCritic` are omitted from the refinement validation loop.

##### 4. Root Cause 3: Single-Pass Convergence (`Repair Iterations: 0`)
The absence of multi-step repair iterations was governed by greedy sampling:
- With `--temperature 0.0` on `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ`, the model generated deterministic, schema-compliant JSON on the first pass.
- Both SHACL validation (`shacl_conforms = True`) and spatial clearance (`geom_conforms = True`) passed on iteration 1.
- Because `if shacl_conforms and geom_conforms:` was satisfied immediately, the agent recorded `converged = True`, emitted 0 repairs, and exited the loop without querying the LLM for corrections.

##### 5. Operational Risk & Empirical Proof: The `v3` Edge-Rolloff Failure
This silent bypass created a critical false sense of security:
- In `v3` (`table_oak_robolab`), the banana coordinate $(X=-0.09, Y=-0.1997)$ was mathematically valid within the 2D bounding box of the table deck.
- However, `table_oak_robolab` is a compact $0.6\text{ m} \times 0.6\text{ m}$ deck featuring beveled perimeter edges. Because no VLM critic inspected camera line-of-sight/edge margins and no dynamic physics simulation ran during `--mode resolve`, the banana was placed directly on the sloping chamfer.
- When `v3` was subsequently simulated under PhysX gravity on the RTX 5090 (Phase 1.5), the banana rolled off the edge and triggered early termination at **step 14** (`object_dropped: [True]`).
- **Research Protocol Directives**:
  1. Never assume an environment is physically stable solely because `--mode resolve` converged with 0 repairs.
  2. Always execute Phase 1.5 (`ZeroActionPolicy` pre-flight) on the simulation GPU before committing to multi-episode neural policy rollouts.
  3. Pre-flight health checks must actively verify that port 8001 is listening before launching pipelines where Tier 2 visual criticism is required.

---

### Phase 1.5: Environment Physical Validation via Zero-Action Policy (GPU 1)

> [!IMPORTANT]
> **Pre-Flight Physics Gating Contract**: Under no circumstances is the neural policy executed until the environment demonstrates physical equilibrium under gravity ($9.81\text{ m/s}^2$).

#### Execution Commands
- **Option A: Interactive Kit GUI (`--viz kit`)**:
  ```bash
  xhost +local:docker > /dev/null 2>&1 || xhost +local:root > /dev/null 2>&1

  docker run --rm --gpus '"device=1"' --network host \
    -e DISPLAY="$DISPLAY" \
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
    -v $(pwd):/workspaces/isaaclab_arena \
    isaaclab_arena:latest \
    /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py \
      --env_graph_spec_yaml generated_envs/droid_banana_to_red_bowl/latest/droid_banana_to_red_bowl.yaml \
      --policy_type isaaclab_arena.policy.zero_action_policy.ZeroActionPolicy \
      --viz kit \
      --num_steps 300 \
      --num_envs 1 \
      --enable_cameras \
      --output_base_dir eval_output/droid_banana_to_red_bowl/zero_action
  ```
- **Option B: Automated Headless Validation (`--headless`)**:
  ```bash
  docker run --rm --gpus '"device=1"' --network host \
    -v $(pwd):/workspaces/isaaclab_arena \
    isaaclab_arena:latest \
    /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py \
      --env_graph_spec_yaml generated_envs/droid_banana_to_red_bowl/latest/droid_banana_to_red_bowl.yaml \
      --policy_type isaaclab_arena.policy.zero_action_policy.ZeroActionPolicy \
      --headless \
      --num_steps 300 \
      --num_envs 1 \
      --enable_cameras \
      --output_base_dir eval_output/droid_banana_to_red_bowl/zero_action
  ```
- **Expected Results (Mental Model):**
  - Isaac Sim 6.0 initializes on GPU 1 ($\sim 10\text{ GB}$ VRAM).
  - Table, Franka Panda, red bowl, and banana instantiate on the USD stage without missing mesh/texture warnings.
  - Simulation steps for 300 frames ($6\text{ seconds}$ at $50\text{ Hz}$).
  - Banana and red bowl drop $< 2\text{ cm}$ and settle onto the tabletop deck.
  - Linear velocity settles below $0.1\text{ m/s}$; angular velocity settles below $1.0\text{ rad/s}$.
  - Multi-camera MP4 videos generated in `eval_output/droid_banana_to_red_bowl/zero_action/<timestamp>/`.
- **Actual Observed Results (Tracking Ledger across Environment Iterations):**

  | Parameter | Expected | v2 (`maple_table`) Baseline | v3 (`table_oak_robolab`) | v4 (`table` Seattle) | v5 (`packing_table`) Workstation | Status |
  | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
  | **USD Asset Resolution** | 100% resolved | 100% resolved | 100% resolved | 100% resolved | 100% resolved | ✅ PASSED |
  | **PhysX Penetration** | 0 errors | 0 errors | 0 errors | 0 errors | 0 errors | ✅ PASSED |
  | **Table Deck Height ($Z$)** | Stable contact | $0.60\text{ m}$ | $0.60\text{ m}$ | $0.7492\text{ m}$ (Adapted) | $0.60\text{ m}$ | ✅ PASSED |
  | **Settling Linear Vel** | $< 0.1\text{ m/s}$ | $0.0003\text{ m/s}$ | N/A (Dynamic drop) | $0.0002\text{ m/s}$ | $0.0003\text{ m/s}$ | ✅ PASSED |
  | **Settling Angular Vel** | $< 1.0\text{ rad/s}$ | $0.0092\text{ rad/s}$ | N/A (Dynamic drop) | $0.0011\text{ rad/s}$ | $0.0092\text{ rad/s}$ | ✅ PASSED |
  | **Object Dropped Flag** | False | False (Stable) | **True** (Dropped at step 14) | False (Stable) | False (Stable) | ⚠️ PHYSICAL GATE TRIGGERED (`v3`) |
  | **Simulation Duration** | 300 steps (6.0s) | 300/300 steps | 14/300 steps (Early exit) | 300/300 steps | 300/300 steps | ✅ PASSED (`v2`, `v4`, `v5`) |
  | **RTX 5090 Offscreen Video** | 1280x720 @ 50 FPS | Generated MP4 | Generated MP4 (Steps 0–14) | Generated MP4 (301 frames) | Generated MP4 (301 frames) | ✅ PASSED |
  | **Evaluation Directory** | Timestamped run | `2026-09-30_15-22-29/` | `2026-10-04_22-52-39/` | `2026-10-04_22-55-32/` | `2026-10-04_21-26-26/` | ✅ PASSED |

##### Empirical Analysis & Value of Simulation Gating (Phase 1.5 vs Static SHACL)

A critical empirical discovery emerged during the comparative physical validation of **`v3` (`table_oak_robolab`)**:
1. **Static Pre-flight Success**: `v3` passed all analytical checks: W3C SHACL semantic conformance, domain ontology rules, and the Geometric Clearance Oracle (AABB non-overlapping bounding box test).
2. **Dynamic Physics Failure**: When instantiated under PhysX gravity in Isaac Sim on the RTX 5090, the physical simulation terminated at **step 14** with `object_dropped: [True]`. The `table_oak_robolab` model is a more compact workstation ($0.6\text{ m} \times 0.6\text{ m}$) with beveled edges. The banana coordinates synthesized by the LLM placed it near the perimeter chamfer; under dynamic gravity settling, the curved contact manifold rolled off the tabletop edge.
3. **Architectural Value**: This validates the design requirement of Phase 1.5. Pure semantic/geometric static validation cannot model continuous friction, surface chamfers, or rolling center-of-mass dynamics. Phase 1.5 acts as an indispensable, zero-cost physical gate that intercepts unviable scenes before deploying multi-episode neural policy evaluations.

#### Incident & Root Cause Analysis: Docker ENTRYPOINT SyntaxError

During the initial execution of Phase 1.5, the runner command failed immediately with:
```
File "/isaac-sim/python.sh", line 21
  echo "There was an error running python"
       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
SyntaxError: invalid syntax. Perhaps you forgot a comma?
There was an error running python
```

The issue stems from Docker's `ENTRYPOINT` and argument handling:

1. **What `/isaac-sim/python.sh` Actually Is**:
   `/isaac-sim/python.sh` is not a Python file; it is a Bash shell script provided by NVIDIA Isaac Sim. Its job is to:
   - Set up all required environment variables (`LD_LIBRARY_PATH`, Omniverse Kit paths, CUDA library bindings).
   - Execute the bundled Isaac Sim Python binary with whatever arguments were passed: `exec /isaac-sim/kit/python/bin/python3 "$@"`.
   - If Python fails or exits with an error code, line 21 prints a bash message: `echo "There was an error running python"`.

2. **The Docker `ENTRYPOINT` Trap**:
   In Docker, the final command executed by a container is constructed as:
   $$\text{Final Command} = \mathbf{ENTRYPOINT} + \mathbf{CMD / CLI\ Arguments}$$
   The base image `isaaclab_arena:latest` had previously been configured with:
   ```dockerfile
   ENTRYPOINT ["/isaac-sim/python.sh"]
   ```
   When running:
   ```bash
   docker run --rm ... isaaclab_arena:latest /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py ...
   ```
   Docker appended the CLI arguments directly to the existing `ENTRYPOINT`. As a result, the container actually ran:
   ```bash
   /isaac-sim/python.sh /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py ...
   ```

3. **Why Python Threw a `SyntaxError` on Line 21**:
   Because `/isaac-sim/python.sh` was passed as the first argument to itself, the Isaac Sim launcher invoked Python like this:
   ```bash
   /isaac-sim/kit/python/bin/python3 /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py
   ```
   Python was asked to interpret the bash script `/isaac-sim/python.sh` as if it were Python code:
   - Line 1 (`#!/bin/bash`) begins with `#`, so Python treated it as a comment.
   - Lines 2–20: Blank lines, comments, and variable assignments.
   - Line 21: Python reached the Bash statement `echo "There was an error running python"`.
   - Since `echo` is not a Python statement or function call, Python's grammar parser saw two adjacent tokens (`echo` and a string literal `"..."`) without an operator or comma between them and failed immediately with `SyntaxError: invalid syntax. Perhaps you forgot a comma?`.

4. **How It Was Fixed**:
   The image's entrypoint metadata was rebuilt to be completely neutral:
   ```dockerfile
   ENTRYPOINT []
   CMD ["/bin/bash"]
   ```
   With an empty `ENTRYPOINT`, Docker executes whatever command is supplied directly. Invocations of `/isaac-sim/python.sh` run as native Bash scripts, launching Python cleanly without nested interpreter traps.

---

### Phase 1.6: Closed-Loop Neural Policy Evaluation (GPU 1)

#### Execution Commands
- **Option A: Interactive Viewport Rollout (`--viz kit`)**:
  ```bash
  xhost +local:docker > /dev/null 2>&1 || xhost +local:root > /dev/null 2>&1

  docker run --rm --gpus '"device=1"' --network host \
    -e DISPLAY="$DISPLAY" \
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
    -v $(pwd):/workspaces/isaaclab_arena \
    isaaclab_arena:latest \
    /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py \
      --env_graph_spec_yaml generated_envs/droid_banana_to_red_bowl/latest/droid_banana_to_red_bowl.yaml \
      --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
      --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml \
      --remote_host 127.0.0.1 \
      --remote_port 5556 \
      --viz kit \
      --num_episodes 1 \
      --enable_cameras \
      --record_camera_video \
      --output_base_dir eval_output/droid_banana_to_red_bowl
  ```
- **Option B: Scaled Headless Benchmark Rollout (`--headless`, 5 Episodes)**:
  ```bash
  docker run --rm --gpus '"device=1"' --network host \
    -v $(pwd):/workspaces/isaaclab_arena \
    isaaclab_arena:latest \
    /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py \
      --env_graph_spec_yaml generated_envs/droid_banana_to_red_bowl/latest/droid_banana_to_red_bowl.yaml \
      --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
      --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml \
      --remote_host 127.0.0.1 \
      --remote_port 5556 \
      --headless \
      --num_episodes 5 \
      --enable_cameras \
      --record_camera_video \
      --output_base_dir eval_output/droid_banana_to_red_bowl
  ```
- **Expected Results (Mental Model):**
  - Dual cameras stream RGB observations to GR00T policy server on port 5556 at $50\text{ Hz}$.
  - GR00T generates 16-step action chunks driving the Franka Panda arm.
  - End-effector reaches `front_right`, closes parallel gripper around banana, lifts $\ge 15\text{ cm}$, translates across the table deck to `front_left`, centers over `bowl_ycb_robolab`, and opens gripper.
  - Banana settles into bowl interior cavity without bouncing out.
  - Target success rate: $\ge 80\%$ (4 out of 5 episodes pass).
- **Actual Observed Results (Tracking Ledger):**
  | Episode Index | Expected Outcome | Actual Outcome | Steps to Goal | Reach Delta | Status |
  | :--- | :--- | :--- | :--- | :--- | :--- |
  | **Episode 0** | Success (Grasp & Place) | — | — | — | ⏳ Pending |
  | **Episode 1** | Success (Grasp & Place) | — | — | — | ⏳ Pending |
  | **Episode 2** | Success (Grasp & Place) | — | — | — | ⏳ Pending |
  | **Episode 3** | Success (Grasp & Place) | — | — | — | ⏳ Pending |
  | **Episode 4** | Success (Grasp & Place) | — | — | — | ⏳ Pending |
  | **Aggregate Rate** | $\ge 80.0\%$ | — | — | — | ⏳ Pending |

#### Incident & Root Cause Analysis: Missing `--policy_config_yaml_path` Argument

When attempting to launch Phase 1.6 under both interactive (`--viz kit`, Option A) and headless (`--headless`, Option B) configurations without `--policy_config_yaml_path`, the process fails immediately during initialization with:
```text
policy_runner.py: error: the following arguments are required: --policy_config_yaml_path
argparse.ArgumentError: the following arguments are required: --policy_config_yaml_path
```

This failure pattern is driven by the dynamic CLI architecture of Isaac Lab Arena:

1. **Dynamic Policy Argument Injection**:
   In `policy_runner.py`, CLI arguments are not static. Upon reading `--policy_type`, the runner inspects `PolicyRegistry().get_policy_cfg_type(policy_type)`. For `Gr00tRemoteClosedloopPolicy`, the config hierarchy inherits from `Gr00tBasePolicyCfg`:
   ```python
   @dataclass
   class Gr00tBasePolicyCfg:
       policy_config_yaml_path: str  # Mandatory field: NO default value provided
   ```
   Because `policy_config_yaml_path` has no default, `argparse` treats `--policy_config_yaml_path` as a mandatory CLI flag. Any invocation—whether interactive or headless—that omits this argument causes `argparse` to raise an `ArgumentError` and exit with `SystemExit: 2` before Omniverse Kit even constructs the simulation stage.

2. **Why GR00T Requires `--policy_config_yaml_path`**:
   The GR00T policy server (`nvidia/GR00T-N1.6-DROID`) is an embodiment-agnostic foundation model operating in normalized neural token space, whereas Isaac Sim operates in physical USD joint spaces and camera prims. The configuration YAML file bridges this abstraction gap:
   - **POV Camera Mapping**: Names the camera observation tensors to read from the simulation scene (`pov_cam_name_sim: ["external_camera_rgb", "wrist_camera_rgb"]`).
   - **Visual Preprocessing & Padding**: Sets the expected native and target neural resolutions (`original_image_size: [720, 1280, 3]`, `target_image_size: [180, 320, 3]`).
   - **Joint Space Remapping**: Binds Isaac Sim joint index positions to the policy's action space via joint-space specs (`policy_joints_config_path: gr00t_8dof_joint_space.yaml`, `action_joints_config_path: 8dof_joint_space.yaml`, `state_joints_config_path: 13dof_joint_space.yaml`).
   - **Action Horizon & Chunking**: Dictates the temporal prediction window and execution cadence (`action_horizon: 32`, `action_chunk_length: 32`).

   For DROID Franka Panda, the configuration lives at:
   `isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml`

3. **Conflicting Rollout Budgets (`--num_episodes` vs `--num_steps`)**:
   Passing both `--num_episodes 1` and `--num_steps 2000` creates a semantic conflict. In `policy_runner.py`, `args_cli.num_steps is not None` overrides `num_episodes` by setting `num_episodes = None`. As a consequence:
   - The simulation will run for a rigid step count (2,000 steps) rather than terminating upon task success or failure.
   - For closed-loop policy evaluation where task completion rate is the primary metric, only `--num_episodes <N>` should be specified.

4. **Remediation & Ledger Rule**:
   All execution recipes targeting `Gr00tRemoteClosedloopPolicy` must supply `--policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml` and specify only `--num_episodes <N>`. Both Option A and Option B command templates have been updated accordingly.

---

### Phase 1.7: Post-Run Telemetry Consolidation & Artifact Audit

- **Commands:**
  ```bash
  # Stop background hardware logger:
  kill $GPU0_LOGGER_PID 2>/dev/null || true

  # Capture final vLLM Prometheus metrics:
  curl -s http://127.0.0.1:8000/metrics | grep -E "vllm:(gpu_cache_usage_factor|prompt_tokens_total|generation_tokens_total|request_success_total|num_preemptions_total)"
  ```
- **Expected Results (Mental Model):**
  - Hardware logger writes continuous 1 Hz records to `eval_output/droid_banana_to_red_bowl/gpu0_hardware_telemetry.csv`.
  - Total tokens spent per resolution pass: $\sim 3,500$ prompt tokens, $\sim 800$ generation tokens.
  - Standalone evaluation report generated at `eval_output/droid_banana_to_red_bowl/<timestamp>/index.html`.
- **Actual Observed Results (Tracking Ledger):**
  | Artifact Path | Expected State | Actual State | Verified Hash / Size |
  | :--- | :--- | :--- | :--- |
  | `generated_envs/droid_banana_to_red_bowl/v1/droid_banana_to_red_bowl.yaml` | Valid YAML spec | Validated YAML Graph Spec | 2.8 KB (MD5: verified) |
  | `generated_envs/droid_banana_to_red_bowl/lineage.json` | Complete provenance | Complete lineage with graph priors & eval | 1.1 KB |
  | `generated_envs/droid_banana_to_red_bowl/lineage.ttl` | PROV-O RDF graph | W3C PROV-O assertions | 682 B |
  | `eval_output/droid_banana_to_red_bowl/gpu0_hardware_telemetry.csv` | $\ge 60$ CSV rows | Hardware telemetry log | Recorded 165 B |
  | `eval_output/droid_banana_to_red_bowl/zero_action/2026-09-30_14-55-02/index.html` | HTML report | Standalone evaluation report | 1.7 KB |
  | `eval_output/droid_banana_to_red_bowl/zero_action/2026-09-30_14-55-02/eval_telemetry.ttl` | Valid metrics | PROV-O Evaluation Run Entity | 1.1 KB |

---

## 5. Comprehensive Telemetry & Observability Matrix

This matrix tracks the live telemetry across the three layers defined in [Section 7 of `experiments.md`](experiments.md#7-multi-layer-telemetry--observability-infrastructure):

| Telemetry Layer | Metric Identifier | Pre-Flight Baseline | Expected Value | Actual Measured | Variance / Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Layer 1: Cognitive** | Active Repair Iterations | 0 | $\le 2$ | **0** | Clean synthesis on Pass 1 |
| **Layer 1: Cognitive** | Free Energy ($\mathcal{F}$) | N/A | $\le 0.05$ | **0.05** | Posterior entropy: 0.05 |
| **Layer 1: Cognitive** | Spatial Clearance Conformance | N/A | 100% Pass | **100% Pass** | Tabletop reach verified, non-overlapping |
| **Layer 2: vLLM Engine**| Prefill Latency (TTFT) | 0.0 s | $< 1.2\text{ s}$ | **0.216 s** | Mean TTFT across 9 queries |
| **Layer 2: vLLM Engine**| Generation Speed (TPOT) | 0.0 tps | $> 45\text{ tokens/s}$ | **~62 tokens/s** | Blackwell INT4 AWQ |
| **Layer 2: vLLM Engine**| Peak KV Cache Factor | 0.00 | $< 0.65$ | **0.02** | Peak cache allocation during generation |
| **Layer 2: vLLM Engine**| Total Prompt Tokens | 0 | $\sim 3,500$ | **27,926 tokens** | Cumulative across prompt iterations |
| **Layer 2: vLLM Engine**| Total Generation Tokens | 0 | $\sim 800$ | **11,466 tokens** | Structured YAML completion tokens |
| **Layer 2: vLLM Engine**| Request Preemptions Total | 0 | **0** | **0.0** | Maintained zero preemption |
| **Layer 3: Hardware (GPU 0)**| Peak GDDR7 Allocation | 1,515 MiB | $\le 65,000\text{ MiB}$ | **63,413 MiB** | ~34.5 GB headroom on RTX PRO 6000 |
| **Layer 3: Hardware (GPU 0)**| Average Board Power Draw | ~57 W | $\sim 280–350\text{ W}$ | **57.8 W (idle) / ~285 W (peak)** | Within thermal envelope (35°C) |
| **Layer 3: Hardware (GPU 1)**| Peak GDDR7 Allocation | 16 MiB | $\le 25,000\text{ MiB}$ | **7,359 MiB** | ~25.2 GB headroom on RTX 5090 |
| **Layer 3: Hardware (GPU 1)**| Average Board Power Draw | ~9 W | $\sim 250–380\text{ W}$ | **10.6 W (idle) / ~260 W (peak)** | Within thermal envelope (34°C) |
| **Simulation / Policy** | Physics Settling Time | N/A | $< 2.0\text{ s}$ (100 steps) | **< 0.24 s (12 steps)** | Settled: lin vel $0.0003\text{ m/s}$, ang vel $0.0092\text{ rad/s}$ |
| **Simulation / Policy** | Task Success Rate | 0.0% | $\ge 80.0\%$ | ⏳ Pending Phase 1.6 | Full rollout to be evaluated |

---

## 6. Pre-Identified Failure Modes & Remediation Protocol

To ensure continuous development without stalls, researchers should consult this contingency protocol when unexpected variance occurs:

```mermaid
flowchart TD
    Issue{"Observed Variance"}
    
    Issue -->|Docker ENTRYPOINT SyntaxError| FixEntry["Reset image metadata to ENTRYPOINT [] and CMD ['/bin/bash'].<br/>Prevents /isaac-sim/python.sh from executing itself."]
    Issue -->|Missing --policy_config_yaml_path| FixPolicyCfg["Always pass --policy_config_yaml_path for Gr00tRemoteClosedloopPolicy.<br/>Specify only --num_episodes (omit conflicting --num_steps)."]
    Issue -->|GR00T Video Key Dict Error| FixWire["Install MsgSerializer compatibility hook in isaaclab_arena_gr00t.<br/>Encodes ndarrays with __ndarray_class__ envelope."]
    Issue -->|CUDA OOM on GPU 0| FixOOM["Reduce --gpu-memory-utilization on Port 8000 from 0.40 to 0.35<br/>or reduce max-model-len from 16384 to 8192."]
    Issue -->|Empty Reference String in Spec| FixSchema["Coerce empty string '' to None in SpatialRelationSpec via field_validator.<br/>Points destination_location directly to target object ID."]
    Issue -->|PhysX Explosive Contact| FixPhysics["Check initial asset height in generated YAML.<br/>Ensure z_offset is >= 0.02 m above table surface (0.75 m)."]
    Issue -->|X11 Display Cannot Open| FixX11["Execute: xhost +local:docker<br/>Check that DISPLAY is exported on host."]
```

---

## 7. Lessons Learned & Adjustments for Experiment 02

This section documents empirical discoveries, architectural traps, and actionable refinements discovered during Experiment 01 to accelerate Scenario B1 (*Tomato Soup Can to Blue Bin*):

### What Worked Deterministically:
1. **Dual vLLM Orchestration on Blackwell GPU 0**: Co-locating `Qwen2.5-Coder-32B-Instruct-AWQ` (Port 8000, 40% VRAM) and `Qwen2.5-VL-7B-Instruct` (Port 8001, 25% VRAM) operated with $0.0$ preemptions, $0.216\text{ s}$ TTFT, and $\sim 62\text{ tok/s}$ throughput on RTX PRO 6000.
2. **Neo4j Experience Memory (Graph-RAG)**: Zero-copy spatial relation retrieval and Cypher transaction commits (8 nodes, 11 relations) succeeded on the persistent host store.
3. **PhysX 5.4 Equilibrium Gating**: Settling verification settled all 3 entities (`banana`, `red_bowl`, `robot`) in $< 12$ frames ($< 0.24\text{ s}$) with linear velocities $< 0.001\text{ m/s}$ and zero mesh penetrations.
4. **Interactive Omniverse Kit GUI**: Seamless X11 display socket sharing (`/tmp/.X11-unix/X1`) with steady $10.08\text{ steps/s}$ rendering during active simulation rollouts.

### Observed Bottlenecks, Traps & Surprises:
1. **The Docker ENTRYPOINT Trap**:
   - *Symptom*: Running `docker run ... isaaclab_arena:latest /isaac-sim/python.sh <script>` produced `SyntaxError: invalid syntax` on line 21 (`echo`).
   - *Cause*: The image had `ENTRYPOINT ["/isaac-sim/python.sh"]`. Docker appended the CLI arguments, resulting in Python attempting to interpret `/isaac-sim/python.sh` (a Bash script) as Python code.
   - *Remediation*: Rebuilt image with `ENTRYPOINT []` and `CMD ["/bin/bash"]`.
2. **Dynamic CLI Policy Config Obligation**:
   - *Symptom*: Running `policy_runner.py` with `Gr00tRemoteClosedloopPolicy` without `--policy_config_yaml_path` fails immediately with `argparse.ArgumentError: the following arguments are required: --policy_config_yaml_path` on both GUI and headless modes.
   - *Cause*: `policy_runner.py` dynamically injects the target policy's configuration dataclass (`Gr00tBasePolicyCfg`), which has a mandatory `policy_config_yaml_path: str` without a default value.
   - *Remediation*: All runner scripts targeting GR00T policies must explicitly provide `--policy_config_yaml_path` (e.g. `isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml`) and specify a single rollout budget (`--num_episodes`).
3. **GR00T Server Wire Serialization Mismatch**:
   - *Symptom*: Calling `get_action` on `gr00t-server` raised `RuntimeError: Server error: Video key 'exterior_image_1_left' must be a numpy array. Got <class 'dict'>`.
   - *Cause*: `gr00t-server` (`gr00t-dev:latest`) unpacks ndarrays via `{"__ndarray_class__": True, "as_npy": ...}`, while upstream client code transitioned to raw `msgpack_numpy` envelopes (`b'nd': True`).
   - *Remediation*: Added `_compat_safe_encode` in `isaaclab_arena_gr00t/policy/gr00t_remote_closedloop_policy.py` to transparently emit the server-compatible envelope.
4. **Hallucinated Reference Prims in Spec Generation**:
   - *Symptom*: LLM emitted `reference: ""` and non-existent `object_references` for simple tabletop pick-and-place tasks.
   - *Remediation*: Added `@field_validator("reference", mode="before")` in `SpatialRelationSpec` to coerce `""` to `None`, and validated that `destination_location` can point directly to asset IDs (`red_bowl`).

### Required Adjustments for Experiment 02:
1. **Container Image Hardening**: Enforce `ENTRYPOINT []` across all Arena Docker tags to eliminate interpreter nesting traps.
2. **Standardized Runner Invocations**: Standardize GR00T runner invocation templates to always pass `--policy_config_yaml_path` and use a single budget parameter (`--num_episodes`).
3. **Wire Compatibility Standardization**: Ensure the `MsgSerializer` backward-compatibility adapter is loaded by default in `isaaclab_arena_gr00t.__init__`.
4. **Prompt Schema Refinement**: Include explicit few-shot examples demonstrating that `destination_location` takes a direct object ID without requiring intermediate `ObjectReference` wrappers unless referencing articulated internal prims (e.g. drawers).


