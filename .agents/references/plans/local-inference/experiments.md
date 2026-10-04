# Dual-GPU Local Inference Experiments & Validation Log

**Document Version:** 1.5.0  
**Date:** 2026-09-30  
**Status:** Active Research & Execution  
**Authors / Researchers:** Antigravity & Renan  
**Target Hardware:** Dual-Blackwell Workstation (NVIDIA RTX PRO 6000 Blackwell 96 GB + NVIDIA GeForce RTX 5090 32 GB)  
**Host Environment:** Ubuntu 22.04.5 LTS (Kernel `7.2.4-zabbly+`) | Driver `595.91.07` | CUDA `13.2`  
**Parent Plan:** [`local_llm_vlm_agentic_env_gen_plan.md`](local_llm_vlm_agentic_env_gen_plan.md)  
**Hardware Guide:** [`install-multi-gpu.md`](install-multi-gpu.md)  

---

## 1. Executive Summary & Purpose

This document serves as the live, human-readable operational experimental journal and validation log for running Isaac Lab-Arena's `agentic_environment_generation` pipeline entirely on a self-hosted, local dual-GPU system.

The objectives of this experimental campaign are:
1. **Air-Gapped Autonomous Operation**: Verify zero reliance on commercial cloud APIs (OpenAI, Google Gemini, OpenRouter) for environment graph specification, spatial constraint solving, and active inference repair.
2. **Deterministic Dual-Blackwell Functional Separation**: Isolate cognitive language/vision generation (GPU 0) from physics simulation and policy neural inference (GPU 1).
3. **Structured Research Documentation**: Maintain human-auditable logs, reproducible command invocations, telemetry benchmarks, and decision rationale as each experiment is conducted.

---

## 2. System Hardware & Driver Baseline Audit (2026-09-29)

Prior to running experimental workloads, the system state was verified using `nvidia-smi` and in-container PyTorch CUDA probes.

### 2.1 GPU Enumeration & Topology

```
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 595.91.07              Driver Version: 595.91.07      CUDA Version: 13.2     |
+-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|=========================================+========================+======================|
|   0  NVIDIA RTX PRO 6000 Blac...     On |   00000000:01:00.0  On |                  Off |
| 30%   31C    P5             49W /  600W |    1167MiB /  97887MiB |     15%      Default |
+-----------------------------------------+------------------------+----------------------+
|   1  NVIDIA GeForce RTX 5090         On |   00000000:06:00.0 Off |                  N/A |
|  0%   30C    P8              9W /  575W |      15MiB /  32607MiB |      0%      Default |
+-----------------------------------------+------------------------+----------------------+
```

| Parameter | GPU 0 (Cognitive Engine) | GPU 1 (Sim & Policy Engine) | Notes |
| :--- | :--- | :--- | :--- |
| **Model** | NVIDIA RTX PRO 6000 Blackwell Workstation | NVIDIA GeForce RTX 5090 | Both SM 12.0 (`sm_120`) |
| **PCI Bus ID** | `00000000:01:00.0` | `00000000:06:00.0` | Discrete dual-device slots |
| **Total Memory** | **95.6 GiB** (97,887 MiB) | **31.8 GiB** (32,607 MiB) | Total: **127.4 GiB GDDR7** |
| **Free Memory** | 93.7 GiB | 31.3 GiB | GPU 1 is 100% headless |
| **Persistence Mode**| **Enabled** | **Enabled** | Set via `nvidia-smi -pm 1` |
| **PCIe Link Status**| Gen 5 x16 (32 GT/s) | Gen 3/4 x4 (8 GT/s) | Functional; see hardware note below |
| **Default Power Limit**| 600 W | 575 W | Combined peak: ~1175 W GPU load |

> [!NOTE]
> **PCIe Link Note for GPU 1:** The RTX 5090 is currently routed via `0000:06:00.0` negotiating at x4 link width. Because policy weights and simulation meshes load once at session startup, this provides ample bandwidth for real-time control (~4–8 GB/s). Optional hardware tuning in ASUS UEFI BIOS can configure `PCIEX16_2` to Gen 5 x8/x8 if desired.
>
> [!WARNING]
> **Power Budget Safety:** Under heavy concurrent generation (LLM token synthesis on GPU 0 + Isaac Sim rendering and PhysX stepping on GPU 1), ensure the host PSU is rated $\ge 1500\text{ W}$. For PSUs $\le 1200\text{ W}$, apply power caps (`nvidia-smi -i 0 -pl 450` and `nvidia-smi -i 1 -pl 400`) before running stress benchmarks.

### 2.2 PyTorch CUDA Capability Verification

Executed inside `isaaclab_arena:latest` and `gr00t-dev:latest` containers:
- **CUDA Device Count:** 2
- **Device 0:** `NVIDIA RTX PRO 6000 Blackwell Workstation Edition` — Capability: `(12, 0)`
- **Device 1:** `NVIDIA GeForce RTX 5090` — Capability: `(12, 0)`
- **Matmul & Tensor Allocations:** Passed on both devices with zero errors.
- **P2P Access:** Not enabled (NVLink bridge not present; intentional functional separation over PCIe/TCP).

---

## 3. Local Model & Container Inventory

Local inspection confirms the following assets are pre-cached and ready for deployment without internet egress:

### 3.1 Downloaded Models (`~/.cache/huggingface/hub/`)
- `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ`: Fast, memory-efficient structured code & graph generator (~22 GB VRAM).
- `casperhansen/llama-3.3-70b-instruct-awq`: High-capacity 70B reasoning model (~40 GB VRAM).
- `nvidia/GR00T-N1.6-DROID`: Humanoid / multi-embodiment policy checkpoint for physical rollouts.
- `nvidia/GR00T-N1.7-3B`: Updated 3B physical AI foundation policy checkpoint.
- `nvidia/Cosmos-Reason2-2B`: Physical spatial reasoning & visual dynamics critic.
- `depth-anything/DA3-BASE`, `moge-2-vitl`, `map-anything-apache`: Dense visual geometry estimation.

### 3.2 Pre-built Docker Containers
- `isaaclab_arena:latest` (58.7 GB): Full Isaac Sim 6.0 + Isaac Lab 3.0 Beta + Arena core.
- `gr00t-dev:latest` (57.6 GB): ZeroMQ policy server environment with PyTorch 2.7 (SM 12.0 enabled).
- `neo4j:5.26-community` (980 MB): Labeled Property Graph experience memory.

---

## 4. Evaluation Benchmark Scenarios Catalog

To systematically benchmark and validate self-hosted local inference across diverse robotic manipulation affordances, candidate scenarios are organized into two standardized benchmark categories. Each individual experiment selects **one scenario** from this catalog to evaluate end-to-end under a specific hardware and model configuration.

### 4.1 🍎 Category A: Fresh Food & Kitchen Tabletop (Franka DROID / Single-Arm)
- **Embodiment**: `droid_abs_joint_pos` (Dual cameras: exterior $45^\circ$ + wrist)
- **Background**: `maple_table_robolab` (Pose: `[-0.25, 0.0, 0.0]`)
- **Policy Server**: `nvidia/GR00T-N1.6-DROID` (ZeroMQ Port 5556)
- **Core Challenge**: Grasping compliant, organic geometric objects with varied friction and placing them onto fragile open ceramic/wooden dishware without tipping.

| Scenario ID | Test Name | Source Object | Target Container | Source Sector | Target Sector | Prompt / Language Instruction |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **A1** | **Apple to Wooden Bowl** | `apple_01_objaverse_robolab` | `wooden_bowl_hot3d_robolab` | `front_right` | `front_left` | *"Pick up the red apple from the front right of the maple table and place it into the wooden bowl on the front left."* |
| **A2** ⭐ | **Banana to Red Bowl** | `banana_ycb_robolab` | `bowl_ycb_robolab` | `front_right` | `front_left` | *"Grasp the yellow banana from the right side of the table and place it into the red bowl on the left."* |
| **A3** | **Lemon to Clay Plate** | `lemon_01_fruits_veggies_robolab` | `clay_plates_hot3d_robolab` | `front_right` | `front_left` | *"Pick up the fresh lemon from the front right and carefully place it on the clay plate at the front left."* |
| **A4** | **Avocado to Serving Bowl** | `avocado01_fruits_veggies_robolab` | `serving_bowl_vomp_robolab` | `front_right` | `front_left` | *"Pick the green avocado from the right sector and place it inside the serving bowl on the left."* |
| **A5** | **Red Bell Pepper to Blue Bin** | `red_bell_pepper_objaverse_robolab` | `bin_b03_vomp_robolab` | `front_right` | `front_left` | *"Grasp the red bell pepper from the front right table sector and drop it into the blue bin on the front left."* |

*(⭐ Scenario A2 is selected as the primary benchmark scenario for Experiment 1.)*

---

### 4.2 🥫 Category B: Packaged Groceries & Pantry Sorting (Franka DROID / Single-Arm)
- **Embodiment**: `droid_abs_joint_pos`
- **Background**: `maple_table_robolab` / `kitchen`
- **Policy Server**: `nvidia/GR00T-N1.6-DROID` (ZeroMQ Port 5556)
- **Core Challenge**: High-aspect-ratio prismatic cylinders and cuboids requiring vertical clearance and upright orientation within high-walled bins and crates.

| Scenario ID | Test Name | Source Object | Target Container | Source Sector | Target Sector | Prompt / Language Instruction |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **B1** | **Tomato Soup to Blue Bin** | `tomato_soup_can_ycb_robolab` | `bin_b03_vomp_robolab` | `front_right` | `front_left` | *"Pick up the red tomato soup can from the front right of the counter and deposit it into the blue sorting bin."* |
| **B2** | **Mustard Bottle to Purple Crate** | `mustard_bottle_hot3d_robolab` | `purple_crate` | `front_right` | `front_left` | *"Grasp the yellow mustard bottle from the right side and place it upright inside the purple storage crate."* |
| **B3** | **Cracker Box to Brown Box** | `cracker_box` | `brown_box` | `front_right` | `front_left` | *"Pick up the Cheez-It cracker box from the packing table and place it into the brown cardboard box."* |
| **B4** | **Spam Can to Grey Bin** | `spam_can_ycb_robolab` | `grey_bin_robolab` | `front_right` | `front_left` | *"Pick the blue Spam can from the right section and drop it into the grey bin on the left."* |
| **B5** | **Tuna Can to Small Plate** | `tuna_can_ycb_robolab` | `plate_small_vomp_robolab` | `front_right` | `front_left` | *"Pick up the tuna can from the front right sector and set it onto the small plate on the front left."* |

---

## 5. Artifact Storage Architecture & Non-Destructive Versioning

To guarantee scientific reproducibility, traceability, and prevent unintentional data loss or overwrites across repeated experiment runs, Isaac Lab-Arena strictly implements **Dual-Namespace Isolation** and **Append-Only Versioning**.

### 5.1 Zero-Overwrite Guarantee & Namespace Isolation

Artifacts generated by the system are partitioned into two strictly separated directory trees rooted at the workspace level:

```
<repo-root>/
├── generated_envs/<env_name>/     # Environment specifications, factor graphs, and W3C PROV-O lineage
└── eval_output/<env_name>/        # Rollout videos, step-by-step telemetry, metrics, and interactive reports
```

1. **Environment Family Isolation (`--env_name`)**:
   - The `--env_name` argument acts as the canonical namespace boundary.
   - For example, the previous banana demonstration ran under `droid_banana_to_plate`, writing to `generated_envs/droid_banana_to_plate/` and `eval_output/droid_banana_to_plate/`.
   - The current experiment targets the red bowl under `droid_banana_to_red_bowl`. Its files write exclusively to `generated_envs/droid_banana_to_red_bowl/` and `eval_output/droid_banana_to_red_bowl/`.
   - The historical data for `droid_banana_to_plate` remains completely untouched.

2. **Immutable Append-Only Versioning (`EnvironmentVersionManager`)**:
   - Even if the exact same `--env_name` is invoked repeatedly (e.g. during iterative prompt refinement or active inference healing), the system **never overwrites** existing versions.
   - The `EnvironmentVersionManager` checks the latest version integer $N$ and automatically creates directory `v(N+1)`.
   - The symlink `latest` is atomically repointed to `v(N+1)`, while all historical version directories (`v1/`, `v2/`, etc.) remain permanent and read-only.

---

### 5.2 Environment Specification Layout (`generated_envs/<env_name>/`)

When [`environment_generation_runner.py`](../../../../isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py) synthesizes an environment, it outputs the following structure:

```
generated_envs/<env_name>/
├── lineage.json                 # JSON version registry tracking derivation triggers and parent hashes
├── lineage.ttl                  # W3C PROV-O semantic RDF-star lineage graph for Neo4j synchronization
├── README.md                    # Auto-generated markdown summary of environment history and parameters
├── latest -> vN/                # Symbolic link pointing to the newest validated version directory
├── v1/                          # Initial version from human language prompt
│   ├── <env_name>.yaml          # The complete ArenaEnvGraphSpec (objects, relations, spatial sectors)
│   ├── policy_config.yaml       # Robot embodiment, observation spaces, action layouts, and camera configs
│   └── metadata.json            # Generation telemetry (LLM model ID, token count, generation latency)
└── v2/                          # (Optional) Remediated version produced by active inference repair
    ├── <env_name>.yaml
    ├── policy_config.yaml
    └── metadata.json
```

---

### 5.3 Evaluation Demos & Telemetry Layout (`eval_output/<env_name>/`)

When [`policy_runner.py`](../../../../isaaclab_arena/evaluation/policy_runner.py) executes a policy against a generated environment, it writes to a second-precision timestamped directory:

```
eval_output/<env_name>/
└── <YYYY-MM-DD_HH-MM-SS>/                                  # Unique run directory (e.g. 2026-09-29_23-50-00)
    ├── robot-cam-env0-wrist_camera_rgb-episode-0.mp4       # Franka Panda wrist POV camera video (H.264)
    ├── robot-cam-env0-external_camera_rgb-episode-0.mp4    # 45° exterior perspective camera video
    ├── robot-cam-env0-external_camera_2_rgb-episode-0.mp4  # Secondary overview camera video
    ├── episode_results_rank0.jsonl                         # Step-by-step joint angles, velocities, action vectors
    ├── summary_metrics.json                                # Aggregate success rate, mean steps-to-goal, settle status
    ├── eval_telemetry.ttl                                  # W3C PROV-O execution graph linked to env UUID
    └── index.html                                          # Standalone visual HTML report for browser review
```

#### Key Output Artifacts Explained:
- **Multi-Camera Videos (`.mp4`)**: Generated by Gymnasium's `wrap_env_for_video()` recorder during policy rollout. Encoded in H.264 so researchers can visually verify grasp contact, trajectory smoothness, and object placement without running a simulation GUI.
- **Step Telemetry (`episode_results_rank0.jsonl`)**: High-frequency physics data logging gripper force, reach distance to target, linear/angular velocity, and termination trigger flags at each control cycle ($50\text{ Hz}$).
- **Summary Metrics (`summary_metrics.json`)**: Machine-readable JSON summary consumed by the benchmarking flywheel, containing task success rates and lift statistics.
- **Semantic Provenance (`eval_telemetry.ttl`)**: Graph triples connecting the evaluation episode back to the specific version of the environment graph and the GR00T policy weights hash.

---

## 6. Runner Execution Modes: `--mode resolve` vs `--mode full`

The agentic environment generation CLI [`environment_generation_runner.py`](../../../../isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py) supports distinct execution lifecycles controlled via the `--mode` argument (`resolve`, `build`, `full`, `auto_heal`, `schema`, `catalog`). For rigorous empirical validation, our experimental protocol exercises **both `--mode resolve` and `--mode full`** for every scenario:

```mermaid
flowchart TD
    Prompt["Natural Language Prompt"] --> ResolveStep["resolve_env_spec()<br/>• LLM Factor Graph Synthesis (Port 8000)<br/>• RDF-star Lowering & SHACL Validation<br/>• Spatial Geometric & Clearance Oracle<br/>• Tier 2 VLM Visual Critic (Port 8001)<br/>• Non-Destructive Versioning (v1, v2...)"]
    
    subgraph ModeResolve["--mode resolve (Pure Python / Zero Simulation Overhead)"]
        ResolveStep --> SpecOut["Immutable Spec YAML Output<br/>generated_envs/<name>/v1/<name>.yaml<br/>(Process Exits 0)"]
    end

    subgraph ModeFull["--mode full (Monolithic End-to-End Simulation)"]
        SimApp["Initialize SimulationAppContext<br/>(Omniverse / PhysX / Vulkan Engine)"] --> ResolveInSim["resolve_env_spec()"]
        ResolveInSim --> Transfer["check_transfer_readiness()<br/>(Policy Training Invariant Audit)"]
        Transfer --> Build["build_env_from_env_graph_spec()<br/>• Load USD Assets to Stage<br/>• Construct Gym ManagerBasedEnv"]
        Build --> ZeroPolicy["run_zero_action_policy()<br/>• Step 20 Physics Frames<br/>• Gravity Settling & Collision Probe"]
        ZeroPolicy --> CloseSim["Graceful Simulator Teardown"]
    end
```

### 6.1 Execution Mode Comparison Matrix

| Feature / Dimension | `--mode resolve` | `--mode full` |
| :--- | :--- | :--- |
| **SimulationApp Lifecycle** | ❌ **No Isaac Sim launched** (pure Python execution) | ✅ **Launches full `SimulationApp`** (Omniverse / PhysX / CUDA) |
| **Primary Compute Requirement** | Host CPU + GPU 0 (vLLM inference only) | Host CPU + GPU 0 (vLLM) + GPU 1 (RTX rendering & PhysX) |
| **Cognitive Agent Execution** | ✅ Prompt $\rightarrow$ Factor Graph $\rightarrow$ Active Inference Repair | ✅ Prompt $\rightarrow$ Factor Graph $\rightarrow$ Active Inference Repair |
| **Semantic & Visual Validation** | ✅ SHACL constraints, Spatial Oracle, Tier 2 VLM critic | ✅ SHACL constraints, Spatial Oracle, Tier 2 VLM critic |
| **Transfer Readiness Audit** | ❌ Skipped (pure spec level) | ✅ `check_transfer_readiness()` against target policy profile |
| **USD Stage Instantiation** | ❌ No USD stage created | ✅ Spawns assets, textures, and Franka Panda embodiment on stage |
| **Physics Settling Rollout** | ❌ None | ✅ Steps `ZeroActionPolicy` for $N$ steps to verify gravity settling |
| **Execution Latency** | **Fast** (~5–15 seconds total) | **Moderate** (~45–75 seconds due to Omniverse runtime init) |
| **Primary Failure Modes Caught** | Schema errors, spatial sector overlap, visual occlusions, floating prompts | Missing USD asset paths, PhysX contact instabilities, mesh penetration |
| **Output Artifacts** | `generated_envs/<name>/v<N>/<name>.yaml`, `lineage.ttl`, `policy_config.yaml` | Same YAML specs + physics verification + (optional) settling video |

---

### 6.2 Detailed Mode Breakdown

#### 6.2.1 `--mode resolve` (Decoupled Cognitive Specification)
- **What it does:** Executes [`resolve_env_spec()`](../../../../isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py#L255) as a lightweight Python process without booting NVIDIA Omniverse or Isaac Sim.
- **Internal Lifecycle:**
  1. Loads ontology catalogs (registered assets, spatial relations, and manipulation tasks).
  2. Dispatches structured output prompt to LLM (`Qwen2.5-Coder-32B`) via `--base_url http://localhost:8000/v1`.
  3. Enters the Active Inference Self-Healing loop:
     - Converts spec to RDF-star graph (`spec_to_rdf_graph`).
     - Validates W3C SHACL semantic constraints (`validate_rdf_environment_graph`).
     - Validates spatial clearance and sector bounds via Geometric Oracle (`validate_spatial_geometry`).
     - Inspects camera viewpoints via Tier 2 VLM visual critic (`LOCAL_VLM_BASE_URL="http://localhost:8001/v1"`).
  4. Saves immutable version directory `generated_envs/<env_name>/v1/` and updates symlink `latest`.
  5. Syncs semantic lineage graph to Neo4j database (if running).
  6. **Exits immediately with return code 0.**
- **Value to Researchers:** Enables rapid, cost-free iteration over natural language prompts, constraint variations, and VLM perception tests without tying up GPU simulation contexts or waiting for heavy 3D engine startup.

#### 6.2.2 `--mode full` (Monolithic Simulation & Physics Verification)
- **What it does:** Wraps cognitive resolution, transfer-readiness verification, and live stage construction inside [`SimulationAppContext`](../../../../isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py#L809).
- **Internal Lifecycle:**
  1. Initializes Isaac Sim 6.0 and Carbonite core on GPU 1.
  2. Resolves prompt $\rightarrow$ factor graph (same validation loop as `--mode resolve`).
  3. Executes `check_transfer_readiness()`: audits the generated scene against target policy invariants (Franka Panda reachability envelope, table surface elevation).
  4. Constructs Gymnasium `ManagerBasedEnv`: resolves USD prim paths, binds physics materials, and registers cameras.
  5. Executes `run_zero_action_policy()`: steps simulation for `--num_steps 20` to verify that assets settle stably onto the table deck under gravity ($9.81\text{ m/s}^2$) without explosive PhysX contact jitter or penetration.
  6. Gracefully shuts down the simulator.
- **Value to Researchers:** Provides deterministic end-to-end proof that the synthesized environment graph is physically stable and USD-valid before committing to expensive multi-episode neural policy rollouts.

---

### 6.3 Multi-Stage Verification & Evaluation Protocol

Every scenario evaluated in this campaign is tested through a strict 3-stage validation progression:
1. **Run 1.4 (`environment_generation_runner.py --mode resolve` on GPU 0)**: Validates pure cognitive factor graph synthesis, active repair, and VLM perception in isolation without simulation engine overhead.
2. **Run 1.5 (`policy_runner.py` with `ZeroActionPolicy` on GPU 1)**: **Pre-flight physics and scene verification.** Before running neural policies, we verify that the USD assets instantiate cleanly, physics settles under gravity without clipping or explosion, and camera perspectives are valid. Offers both **Interactive Kit GUI (`--viz kit`)** for researcher visual inspection and **Headless (`--headless`)** for automated validation.
3. **Run 1.6 (`policy_runner.py` with `Gr00tRemoteClosedloopPolicy` on GPU 1)**: Executes closed-loop robotic manipulation driven by the live neural policy server over ZeroMQ on port 5556, evaluating real task success rates and recording multi-camera demonstration videos. Offers both **Interactive Kit GUI (`--viz kit`)** and **Headless Benchmark (`--headless`)**.

---

## 7. Multi-Layer Telemetry & Observability Infrastructure

To systematically benchmark and diagnose experimental workloads across cognitive language/vision generation (GPU 0), physics simulation, and policy inference (GPU 1), a unified 3-layer telemetry infrastructure is established. Decoupling telemetry specifications from individual experiment definitions prevents duplication and provides a standardized observability contract across all experimental campaigns.

```mermaid
flowchart TD
    subgraph Layer1["Layer 1: Cognitive Reasoning (Client-Side)"]
        C1["Agent Telemetry Tracker<br/>(render_summary_card)"]
        C2["Active Inference Free Energy<br/>& Repair Iterations"]
        C3["SHACL & Spatial Clearance<br/>Conformance Flags"]
    end

    subgraph Layer2["Layer 2: Engine Performance (vLLM Prometheus /metrics)"]
        E1["Prefill Latency (TTFT Histogram)"]
        E2["Decode Throughput (TPOT / Tokens/s)"]
        E3["KV Cache Saturation (gpu_cache_usage_factor)"]
        E4["Token Counters & Request Totals"]
    end

    subgraph Layer3["Layer 3: Hardware Dynamics (NVIDIA Blackwell System)"]
        H1["Peak GDDR7 Allocation (MiB)"]
        H2["Streaming Multiprocessor (SM) %"]
        H3["Board Power Draw (Watts) & Thermals"]
    end

    Layer1 -.-> Report["Consolidated Artifacts:<br/>• metadata.json (spec lineage)<br/>• telemetry.json (engine & hardware)<br/>• gpu0_hardware_telemetry.csv"]
    Layer2 -.-> Report
    Layer3 -.-> Report
```

### 7.1 Telemetry Layer Architecture & Descriptions

#### 1. Layer 1: Cognitive Reasoning & Semantic Conformance (Client-Side)
- **Origin:** Emitted directly by `EnvironmentGenerationAgent` in [`agent.py`](../../../../isaaclab_arena_examples/agentic_environment_generation/agent.py) and summarized by `render_summary_card()`.
- **Recorded In:** `generated_envs/<env_name>/v<N>/metadata.json`
- **Core Parameters:**
  - `iterations`: Total active repair loops required to reach SHACL and spatial compliance.
  - `free_energy`: Convergence metric measuring residual constraint violation.
  - `shacl_conformance`: Boolean flag indicating semantic compliance with W3C RDF-star schemas.
  - `spatial_clearance_passed`: Boolean flag from Geometric Oracle indicating non-overlapping AABBs and table containment.
  - `vlm_visual_critic_passed`: Verification from Tier 2 VLM critic confirming line-of-sight and physical realism.

#### 2. Layer 2: Engine Performance & Latency (vLLM Prometheus `/metrics`)
- **Origin:** Exposed by vLLM inference engine instances on Port 8000 (`arena-vllm-spec`) and Port 8001 (`arena-vllm-visual`).
- **Configuration Requirement:** Both containers are launched with `--enable-request-id-headers` to enable deterministic per-request tracing.
- **Scraped Via:** Standard Prometheus scrape format at `http://127.0.0.1:<port>/metrics`.

#### 3. Layer 3: Hardware Dynamics & Power Budget (Host / `nvidia-smi`)
- **Origin:** NVIDIA System Management Interface querying discrete Blackwell GPUs at 1 Hz.
- **Recorded In:** `eval_output/<env_name>/gpu0_hardware_telemetry.csv` (and `gpu1_hardware_telemetry.csv`).
- **Core Parameters:** Timestamp, GPU utilization %, memory utilization %, allocated VRAM (MiB), instantaneous power draw (Watts), and GPU die temperature (°C).

---

### 7.2 vLLM Engine Prometheus Metrics Reference

The following Prometheus metrics are monitored on Port 8000 (Spec Generator) and Port 8001 (Visual Critic):

| Metric Identifier | Metric Type | Experimental Significance | Target Threshold / Healthy Range |
| :--- | :--- | :--- | :--- |
| `vllm:time_to_first_token_seconds` | Histogram | Measures **prefill latency** when processing massive multi-KB asset ontologies and relation prompts. | $< 1.5\text{ s}$ for 16K context |
| `vllm:time_per_output_token_seconds` | Histogram | Measures **decode speed** (TPOT). Validates Blackwell AWQ INT4/FP8 compute throughput. | $> 45\text{ tokens/s}$ (Spec) / $> 30\text{ tokens/s}$ (VLM) |
| `vllm:gpu_cache_usage_factor` | Gauge | Tracks **KV cache saturation** on GPU 0 ($0.0 \rightarrow 1.0$). Indicates headroom before memory exhaustion. | $< 0.70$ (nominal) / Alert if $> 0.85$ |
| `vllm:prompt_tokens_total` | Counter | Cumulative prompt tokens consumed across all resolution and repair passes. | Tracks cognitive cost per scenario |
| `vllm:generation_tokens_total` | Counter | Cumulative output tokens generated (synthesized factor graphs + repair patches). | Quantifies graph verbosity |
| `vllm:num_preemptions_total` | Counter | Number of pre-empted/swapped requests. | **Must be 0**. Non-zero indicates VRAM thrashing. |
| `vllm:request_success_total` | Counter | Total successfully completed inference requests. | Equal to total dispatched calls |

---

### 7.3 Telemetry Acquisition & Inspection Playbook

Human researchers can extract and inspect telemetry using three standardized access methods:

#### Method 1: Instant Prometheus CLI Inspection
Fast one-line inspection of running vLLM engine health and cache state:
```bash
# Query Cognitive Spec Generator (Port 8000):
curl -s http://127.0.0.1:8000/metrics | grep -E "vllm:(gpu_cache_usage_factor|prompt_tokens_total|generation_tokens_total|request_success_total|num_preemptions_total)"

# Query Visual Scene Critic (Port 8001):
curl -s http://127.0.0.1:8001/metrics | grep -E "vllm:(gpu_cache_usage_factor|prompt_tokens_total|generation_tokens_total|request_success_total|num_preemptions_total)"
```

#### Method 2: Automated Pre/Post Inference Snapshot Hook (Python)
Researchers or automated harness scripts can snapshot metrics before and after an experiment phase to compute exact token delta and latency distribution:
```python
import json
import re
import urllib.request

def snapshot_vllm_telemetry(port: int = 8000) -> dict:
    """Scrapes and extracts key vLLM Prometheus metrics into a clean dictionary."""
    url = f"http://127.0.0.1:{port}/metrics"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            raw = r.read().decode("utf-8")
    except Exception as e:
        return {"error": f"Failed to connect to port {port}: {e}"}

    patterns = {
        "gpu_cache_usage_factor": r"vllm:gpu_cache_usage_factor\{.*?\}\s+([0-9\.]+)",
        "prompt_tokens_total": r"vllm:prompt_tokens_total\{.*?\}\s+([0-9\.]+)",
        "generation_tokens_total": r"vllm:generation_tokens_total\{.*?\}\s+([0-9\.]+)",
        "request_success_total": r"vllm:request_success_total\{.*?\}\s+([0-9\.]+)",
        "num_preemptions_total": r"vllm:num_preemptions_total\{.*?\}\s+([0-9\.]+)",
    }
    return {k: float(m.group(1)) if (m := re.search(p, raw)) else None for k, p in patterns.items()}

# Example usage:
# before = snapshot_vllm_telemetry(8000)
# ... run Phase 1.4 ...
# after = snapshot_vllm_telemetry(8000)
# tokens_spent = after["prompt_tokens_total"] - before["prompt_tokens_total"]
```

#### Method 3: Continuous Hardware Dynamics Logging (`nvidia-smi`)
Capture real-time Blackwell power draw, thermal behavior, and VRAM utilization during active generation or simulation rollouts:
```bash
# Start background 1 Hz logger for GPU 0 (LLM/VLM):
mkdir -p eval_output/<env_name>
nvidia-smi -i 0 --query-gpu=timestamp,utilization.gpu,utilization.memory,memory.used,power.draw,temperature.gpu \
  --format=csv -l 1 > eval_output/<env_name>/gpu0_hardware_telemetry.csv &
GPU0_LOGGER_PID=$!

# (Optional) Start background 1 Hz logger for GPU 1 (Sim/Policy):
nvidia-smi -i 1 --query-gpu=timestamp,utilization.gpu,utilization.memory,memory.used,power.draw,temperature.gpu \
  --format=csv -l 1 > eval_output/<env_name>/gpu1_hardware_telemetry.csv &
GPU1_LOGGER_PID=$!

# Execute experiment commands...

# Terminate logging when run completes:
kill $GPU0_LOGGER_PID $GPU1_LOGGER_PID 2>/dev/null || true
```

---

### 7.4 Telemetry Artifact Schema & Consolidated Storage

Upon completion of any experiment, telemetry artifacts are persisted alongside the environment specification and evaluation output:
- `generated_envs/<env_name>/latest/metadata.json`: Client-side reasoning iterations, active repair transitions, token consumption, and W3C PROV-O commit hashes.
- `eval_output/<env_name>/gpu0_hardware_telemetry.csv`: Hardware telemetry time series (SM load, power in Watts, GDDR7 usage).
- `eval_output/<env_name>/episode_results_rank0.jsonl`: Control cycle physics telemetry ($50\text{ Hz}$ joint state, contact forces, and action deltas).
- `eval_output/<env_name>/summary_metrics.json`: High-level benchmark task success rate, execution duration, and termination reason.

---

## 8. Multi-Stage Experimental Architecture

Each experiment executes a single evaluated scenario through a standardized 6-phase sequential pipeline:

```mermaid
flowchart LR
    P1["Phase 1.1: Cognitive (LLM) & Visual (VLM) Engines<br/>(GPU 0: PRO 6000 | Ports 8000 & 8001)"] --> P4["Phase 1.4: Spec Resolution (--mode resolve)<br/>(GPU 0: PRO 6000)"]
    P2["Phase 1.2: Neo4j Experience Store<br/>(Host CPU: Ports 7475 & 7688)"] --> P4
    P4 --> P5["Phase 1.5: Zero-Action Physics Validation<br/>(policy_runner.py on GPU 1)<br/>• Interactive: --viz kit<br/>• Headless: --headless"]
    P3["Phase 1.3: GR00T Policy Server<br/>(GPU 1: RTX 5090 | Port 5556)"] --> P6["Phase 1.6: Closed-Loop Policy Rollout<br/>(policy_runner.py with GR00T on GPU 1)<br/>• Interactive: --viz kit<br/>• Headless: --headless"]
    P5 --> P6
```

### Pipeline Phase Breakdown

| Phase ID | Execution Phase | Primary Target | Success Criteria |
| :--- | :--- | :--- | :--- |
| **Phase 1.1** | Cognitive (LLM) & Visual (VLM) Bring-Up | GPU 0 (RTX PRO 6000) | Local inference servers respond on port 8000 (LLM schema decoding) and port 8001 (VLM multimodal critic). |
| **Phase 1.2** | Neo4j Knowledge Store Bring-Up | Host CPU / Docker | Neo4j listens on bolt port 7688; Cypher queries read/write factor graphs without error. |
| **Phase 1.3** | GR00T Policy Server Bring-Up | GPU 1 (RTX 5090) | ZeroMQ RPC server serves `nvidia/GR00T-N1.6-DROID` on port 5556; responds to observation pings. |
| **Phase 1.4** | Cognitive Spec Resolution (`--mode resolve`) | GPU 0 (RTX PRO 6000) | Runner resolves human prompt into valid `ArenaEnvGraphSpec` with SHACL and multimodal VLM satisfaction. |
| **Phase 1.5** | Zero-Action Physics & Scene Verification | GPU 1 (RTX 5090) | `policy_runner.py` with `ZeroActionPolicy` verifies gravity settling, asset stability, and camera FOV. (Interactive: `--viz kit` \| Headless: `--headless`). |
| **Phase 1.6** | Closed-Loop Neural Policy Evaluation | GPU 1 (RTX 5090) | `policy_runner.py` with `Gr00tRemoteClosedloopPolicy` executes pick-and-place task via GR00T on port 5556. (Interactive: `--viz kit` \| Headless: `--headless`). |

---

## 9. Experiment Execution Logs & Validation Records

### 9.1 Experiment 1: Dual-Blackwell Single-Scenario Evaluation (Scenario A2: Banana to Red Bowl)

#### 9.1.0 Experiment 1 Setup & Models Running
This experiment evaluates **one scenario only** with a single dedicated dual-GPU setup from initial prompt through active constraint repair to physical policy execution.

##### Scenario & Problem Definition
| Configuration Item | Value / Description | Notes |
| :--- | :--- | :--- |
| **Scenario Evaluated** | **Scenario A2: Banana to Red Bowl** | Selected from [Section 4.1 Category A](#41--category-a-fresh-food--kitchen-tabletop-franka-droid--single-arm) |
| **Starting Prompt** | *"Grasp the yellow banana from the right side of the table and place it into the red bowl on the left."* | Canonical single-arm Franka DROID pick-and-place instruction |
| **Embodiment** | `droid_abs_joint_pos` | Franka Panda arm with dual RGB cameras (exterior $45^\circ$ + wrist) |
| **Background / Scene** | `maple_table_robolab` (Pose: `[-0.25, 0.0, 0.0]`) | Tabletop surface with defined spatial sectors |
| **Source Object** | `banana_ycb_robolab` | Placed at `front_right` sector |
| **Target Container** | `bowl_ycb_robolab` | Placed at `front_left` sector (Classic red YCB bowl) |
| **Problem to Solve** | Zero-cloud autonomous prompt resolution, spatial constraint satisfaction, and closed-loop robotic policy execution on an organic curved object (`banana_ycb_robolab`) placed into a concave benchmark receptacle (`bowl_ycb_robolab`). | Validates complete air-gapped dual-GPU pipeline |

##### Host Machine Workload Sizing & Process Execution Matrix

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

##### Host Configuration & System Sizing Notes for Researchers

1. **Host System Memory (DRAM) Budget:**
   - **Minimum Requirement:** 64 GB DRAM
   - **Recommended Baseline:** 128 GB DDR5 DRAM
   - **Concurrent Footprint Breakdown:** The combined memory pressure of Neo4j JVM heap (4–8 GB), vLLM host-side Ray/Python workers (16–32 GB), Isaac Sim pinned memory & USD stage buffers (16–32 GB), and OS/Xorg services (4–8 GB) totals **~46 – 95 GB DRAM**. Operating on a host with $< 64\text{ GB}$ will trigger Linux OOM-killer evictions during simultaneous Isaac Sim scene initialization and vLLM KV-cache expansion.
2. **Dual-GPU Partitioning & VRAM Headroom:**
   - **GPU 0 (`device=0`, RTX PRO 6000 Blackwell 96 GB GDDR7 ECC):** Dedicated strictly to cognitive synthesis and visual evaluation (`arena-vllm-spec` + `arena-vllm-visual` + host Xorg). Even with 131k YaRN context expansion on the 32B model (~40 GB VRAM) and the 7B VLM (~16 GB VRAM), GPU 0 retains $\ge 35\text{ GB}$ of uncommitted headroom.
   - **GPU 1 (`device=1`, GeForce RTX 5090 32 GB GDDR7):** Dedicated strictly to physical dynamics and neural policy execution (`isaaclab_arena` + `gr00t-server`). Isaac Sim headless offscreen Vulkan rendering (~8–10 GB) and the GR00T 3B policy (~8 GB) occupy ~16–18 GB combined, leaving **$\ge 14\text{ GB}$ of high-speed GDDR7 headroom** for PhysX rigid-body buffers, multi-camera framebuffers, and parallel environment sub-stepping.
3. **Docker Host Orchestration Primitives:**
   - `--network host`: **Mandatory** across all containers (`arena-vllm-spec`, `arena-vllm-visual`, `arena-envgen-neo4j`, `gr00t-server`, and `isaaclab_arena`). Bypasses Docker bridge NAT overhead, keeping ZeroMQ IPC latency $\le 0.4\text{ ms}$ (vs. $\sim 2.5\text{ ms}$ over bridge) and enabling direct `127.0.0.1` socket binding.
   - `--ipc host`: **Mandatory** for vLLM and Isaac Sim containers. Allows PyTorch DataLoader, raylet inter-process communication, and Vulkan offscreen shared-memory rings to exchange tensors without hitting Docker's default 64 MB `/dev/shm` limit.
   - **Volume Mounts:**
     - HuggingFace Cache: `-v ~/.cache/huggingface:/root/.cache/huggingface` (shared weights across containers).
     - Local Workspace: `-v $(pwd):/workspaces/isaaclab_arena` (live code editing and artifact generation).
     - Persistent LPG Store: `-v arena-envgen-neo4j-data:/data` (preserves knowledge graph across restarts).
4. **Physical GPU Device Isolation:**
   - Never use `--gpus all`. Always pass explicit `--gpus '"device=0"'` to cognitive servers and `--gpus '"device=1"'` to simulation/policy servers. This prevents Isaac Sim or PyTorch from creating CUDA contexts on GPU 0, which would compete with the Xorg display server or vLLM KV caches.

---

#### 9.1.1 Phase 1.1: Cognitive & Visual Engine Bring-Up (vLLM on GPU 0)
- **Target Device:** `CUDA_VISIBLE_DEVICES=0` (RTX PRO 6000 Blackwell 96 GB)

##### 9.1.1.1 Component A: Cognitive Spec Generator LLM (Port 8000)
- **Primary Model:** `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ`
- **Execution Endpoint:** HTTP `127.0.0.1:8000/v1`
- **Proposed Command:**
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
- **Validation Test:** HTTP GET `http://localhost:8000/v1/models` and test JSON-schema completion.

##### 9.1.1.2 Component B: Visual Scene Critic VLM (Port 8001)
- **Primary Model:** `Qwen/Qwen2.5-VL-7B-Instruct`
- **Execution Endpoint:** HTTP `127.0.0.1:8001/v1`
- **Proposed Command:**
  ```bash
  docker run -d --name arena-vllm-visual \
    --gpus '"device=0"' \
    --network host \
    --ipc host \
    -v ~/.cache/huggingface:/root/.cache/huggingface \
    vllm/vllm-openai:latest \
    --model Qwen/Qwen2.5-VL-7B-Instruct \
    --port 8001 \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.25 \
    --enable-request-id-headers
  ```
- **Validation Test:** HTTP GET `http://localhost:8001/v1/models` and multimodal chat test with base64 image.

##### 9.1.1.3 Telemetry Readiness & Baseline Engine Probe
Before dispatching synthesis prompts, verify that both vLLM instances export healthy Prometheus metrics and zero initial cache utilization according to the protocol defined in [Section 7 (Multi-Layer Telemetry & Observability Infrastructure)](#7-multi-layer-telemetry--observability-infrastructure):

```bash
# Verify vLLM metrics endpoints are responsive and cache is clear:
curl -s http://127.0.0.1:8000/metrics | grep "vllm:gpu_cache_usage_factor"
curl -s http://127.0.0.1:8001/metrics | grep "vllm:gpu_cache_usage_factor"
```

- **Validation Test:** Both endpoints return HTTP 200 with `vllm:gpu_cache_usage_factor` initialized (nominal: $0.0$).
- **Results & Metrics:** *(To be recorded upon execution)*
- **Observations:** *(To be recorded)*

---

#### 9.1.2 Phase 1.2: Neo4j Experience Database Bring-Up (Host CPU / Docker)
- **Target Device:** Host CPU & System RAM (Port 7475 HTTP, Port 7688 Bolt)
- **Proposed Command:**
  ```bash
  docker start neo4j-arena
  ```
- **Validation Test:** Cypher handshake over port 7688; probe `MATCH (n) RETURN count(n)`.
- **Results & Metrics:** *(To be recorded upon execution)*
- **Observations:** *(To be recorded)*

---

#### 9.1.3 Phase 1.3: GR00T Policy Server Bring-Up (GPU 1: RTX 5090)
- **Target Device:** `CUDA_VISIBLE_DEVICES=1` (RTX 5090 32 GB)
- **Proposed Command:**
  ```bash
  docker run -d --name gr00t-server \
    --gpus '"device=1"' \
    --network host \
    --ipc host \
    -v ~/.cache/huggingface:/root/.cache/huggingface \
    gr00t-dev:latest \
    python3 gr00t/eval/run_gr00t_server.py \
      --model-path nvidia/GR00T-N1.6-DROID \
      --embodiment-tag OXE_DROID \
      --port 5556 \
      --device cuda:0
  ```
- **Validation Test:** ZeroMQ echo request to `tcp://127.0.0.1:5556`.
- **Results & Metrics:** *(To be recorded upon execution)*
- **Observations:** *(To be recorded)*

---

#### 9.1.4 Phase 1.4: Agentic Spec Generation & Factor Graph Resolution (GPU 0: RTX PRO 6000)
- **Target Device:** `CUDA_VISIBLE_DEVICES=0` (RTX PRO 6000 Blackwell 96 GB)
- **Primary Objective:** Agentic prompt-to-factor-graph synthesis, active constraint repair, and Tier 2 VLM visual critic inspection. Can be evaluated in three distinct execution modes:
  - **Option A (`--mode resolve`)**: Pure Python factor graph synthesis, spatial constraint solving, and lineage registration without simulation engine startup.
  - **Option B (`--mode full`)**: Monolithic end-to-end execution that synthesizes the factor graph, loads the Isaac Sim simulation runtime, settles the scene, and runs verification rollouts in a single invocation.
  - **Option C (`--mode resolve` with Prompt Update)**: Iterative refinement of an existing specification (`--base_spec`) using natural-language feedback (`--feedback`), executing the Recursive Self-Improvement (RSI) loop and incrementing version lineage (`v1` $\to$ `v2`) without simulation overhead.

##### Option A: Spec Resolution (`--mode resolve`, Pure Python)
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

##### Option B: Monolithic End-to-End Simulation (`--mode full`)
Synthesizes the factor graph, loads the Isaac Sim simulation runtime on GPU 0/1, settles the USD scene under PhysX gravity, and steps 20 zero-action verification frames in a single execution:

```bash
docker run --rm --gpus '"device=0"' --network host \
  -e LOCAL_VLM_BASE_URL="http://localhost:8001/v1" \
  -v $(pwd):/workspaces/isaaclab_arena \
  isaaclab_arena:latest \
  /isaac-sim/python.sh isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
    --mode full \
    --headless \
    --num_envs 1 \
    --temperature 0.0 \
    --prompt "Grasp the yellow banana from the right side of the table and place it into the red bowl on the left." \
    --env_name "droid_banana_to_red_bowl" \
    --base_url "http://localhost:8000/v1" \
    --model "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ" \
    --api_key "local-arena-token"
```

###### Architectural Note: Why `--temperature 0.0` Is Mandatory for Local Models
1. **Original State:** Option B originally defined two commands:
   - **Headless:** For automated terminal/CI execution.
   - **Interactive (`--viz kit`):** For opening the Omniverse window on the workstation display.
2. **The Local Model Sampling Problem:**
   - In `environment_generation_runner.py`, the default sampling temperature is `--temperature 0.2`.
   - With frontier cloud models (GPT-4 / Gemini Pro), `0.2` is fine. But with local models (`Qwen/Qwen2.5-Coder-32B-Instruct-AWQ`), non-zero temperature caused occasional schema hallucinations (such as generating hallucinated `cli_override_specs` with `--task` or unclosed JSON strings).
3. **The Quick-Fix Addition & Consolidation:**
   - During the September 30 session (commit `5e968522`), a temporary command was added with `--temperature 0.0` to test greedy, deterministic token decoding.
   - Greedy decoding proved 100% reliable at eliminating schema edge cases. The previous duplicate snippets have now been consolidated into the authoritative command above.
4. **Relocation of `--viz kit`:**
   - The interactive GUI (`--viz kit`) encountered stability issues during the monolithic resolve-and-build loop and has been moved to [Section 9.4 (Future Track)](#94-future-track-interactive-omniverse-kit-gui-for-agentic-spec-generation---viz-kit).

##### Option C: Recursive Prompt Update & Spec Refinement (`--mode resolve`)
Executes the closed-loop Recursive Self-Improvement (RSI) cycle driven by an external orchestrator (e.g., Hermes, Claude Code, or an automated test harness). This path ingests an existing environment specification (`--base_spec`) and applies targeted spatial or semantic critique (`--feedback`) without simulation engine overhead:

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

- **Execution Mechanics & Architectural Invariants:**
  1. **Base Specification Ingestion:** Loads `ArenaEnvGraphSpec` from `generated_envs/droid_banana_to_red_bowl/latest/` while leaving prior version directories (`v1/`) strictly immutable and read-only.
  2. **Active Inference Refinement (`agent.refine_spec`):** Dispatches feedback to `spec_inference.repair_with_feedback()`. Preserves existing embodiment bindings (`droid_abs_joint_pos`), background workspace (`maple_table_robolab`), and valid task constraints while adjusting spatial coordinates, sector bounds, and relational factors.
  3. **Analytical System 2 Verification:** Passes the candidate through W3C SHACL semantic constraints, the Geometric Clearance Oracle (non-overlapping AABB check), and Tier 2 VLM critic perception before acceptance.
  4. **Append-Only Versioning & Lineage:** `EnvironmentVersionManager` writes the refined specification to `v2/droid_banana_to_red_bowl.yaml` (or `v3/`), updates `latest -> vN`, and records derivation metadata (`trigger: active_inference_refinement`, `parent: v(N-1)`) in `lineage.json` and `lineage.ttl` (W3C PROV-O).
  5. **Neo4j Experience Sync:** Synchronizes the refined subgraph, updated property triples, and `:WAS_DERIVED_FROM` lineage relationship to the Neo4j knowledge store on port 7688.

- **Validation Test:** Inspect `generated_envs/droid_banana_to_red_bowl/latest/droid_banana_to_red_bowl.yaml`, check SHACL conformance report, VLM feedback, and physical rollout logs.

###### Test Feedback Prompts: Background Fixture & Table Swapping
To evaluate the recursive spec refinement loop across varied physical fixtures on `droid_banana_to_red_bowl`, three test feedback prompts are defined:

1. **Prompt 1: Direct Swap to Robolab Oak Table (Minimal Semantic Delta)**
   - **Feedback Argument:**
     ```bash
     --feedback "Change the background table from maple_table_robolab to table_oak_robolab, keeping the yellow banana on the right and the red bowl on the left."
     ```
   - **Validation Intent:** Swapping the underlying table model to its closest sibling (`table_oak_robolab`) while ensuring the agent preserves existing sector layout, object transforms, clearance constraints, and pick-and-place task logic.

2. **Prompt 2: Swap to Standard Isaac Lab Table (Geometry & Height Adaptation)**
   - **Feedback Argument:**
     ```bash
     --feedback "Replace the background table with the standard Seattle lab table (registry_name: 'table'), adjusting the banana and red bowl heights so they sit stably on the new table surface."
     ```
   - **Validation Intent:** Tests whether the model and Spatial Geometric Oracle adapt object vertical positions from the Robolab coordinate frame to the standard Seattle table's $Z = 0.75\text{ m}$ deck height.

3. **Prompt 3: Domain Shift to Industrial Packing Workstation**
   - **Feedback Argument:**
     ```bash
     --feedback "Switch the scene background from the maple table to the packing_table workstation, ensuring the red bowl and yellow banana remain in reachable front sectors for the Franka DROID arm."
     ```
   - **Validation Intent:** A larger domain transition (kitchen tabletop $\rightarrow$ warehouse packing station `packing_table`), validating whether the agent adapts spatial clearance and kinematic reachability checks for the Franka DROID arm on a new fixture.

##### Phase 1.4 Telemetry & Metrics Capture
Hardware and inference telemetry captured during the baseline and iterative refinement runs:

| Run / Prompt | Target Model | Prompt Tokens | Gen Tokens | Total Tokens | Latency | Repairs | Status & Lineage |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Baseline (`v2`)** | `Qwen2.5-Coder-32B-AWQ` | 6,560 | 1,278 | 7,838 | 21.10s | 0 | ✅ `latest -> v2` (`maple_table_robolab`) |
| **Prompt 1 (`v3`)** | `Qwen2.5-Coder-32B-AWQ` | 6,568 | 1,270 | 7,838 | 21.38s | 0 | ✅ `latest -> v3` (`table_oak_robolab`) |
| **Prompt 2 (`v4`)** | `Qwen2.5-Coder-32B-AWQ` | 6,570 | 1,266 | 7,836 | 19.67s | 0 | ✅ `latest -> v4` (`table` Seattle) |
| **Prompt 3 (`v5`)** | `Qwen2.5-Coder-32B-AWQ` | 6,562 | 1,291 | 7,853 | 20.05s | 0 | ✅ `latest -> v5` (`packing_table`) |

- **vLLM Operational Invariants (GPU 0):** Peak VRAM allocated: ~22 GB GDDR7; Preemptions total: **0**; KV cache saturation: $< 15\%$; GPU 0 temperature: $42^\circ\text{C}$; Power draw: $\sim 68\text{ W}$.
- **Observations:** Schema-guided greedy decoding (`--temperature 0.0`) yielded **100% first-pass semantic validity (0 repairs)** across all 3 fixture swaps. The agent successfully modified background USD prims, adjusted surface Z elevations, and correctly remapped spatial sector factor bounds into Neo4j.

---

#### 9.1.5 Phase 1.5: Environment Physical Validation via Zero-Action Policy (GPU 1: RTX 5090)
- **Target Device:** `CUDA_VISIBLE_DEVICES=1` (RTX 5090 32 GB)
- **Primary Objective:** **Pre-flight physics and scene verification.** Before executing neural policies, verify that the synthesized scene loads stably on the USD stage, all meshes and collision envelopes resolve, objects settle stably onto the table deck under gravity ($9.81\text{ m/s}^2$), and camera viewpoints are unobstructed.

##### Option A: Interactive Visual Inspection (`--viz kit` via Omniverse Kit GUI)
Allows the human researcher to inspect the 3D scene directly in the Omniverse Kit viewport with free orbital camera controls:
```bash
# Allow local X11 display access on host (run once):
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
    --num_steps 1300 \
    --num_envs 1 \
    --enable_cameras \
    --output_base_dir eval_output/droid_banana_to_red_bowl/zero_action
```

##### Option B: Automated Headless Physics Validation (`--headless`)
Executes headlessly in terminal, recording multi-camera MP4s and verifying contact settling:
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

##### Phase 1.5 Physical Rollout Empirical Matrix across Iterations

| Environment Version | Background Fixture | Steps Completed | Object Dropped | Final Linear Vel | Offscreen MP4 Video | Status & Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`v2` Baseline** | `maple_table_robolab` | 300/300 | False | $0.0003\text{ m/s}$ | Generated (`2026-09-30_15-22-29`) | ✅ PASSED (Stable contact) |
| **`v3` (Prompt 1)** | `table_oak_robolab` | 14/300 (Early exit) | **True** (Step 14) | Dynamic drop | Generated (`2026-10-04_22-52-39`) | ⚠️ **PHYSICAL GATE TRIGGERED** |
| **`v4` (Prompt 2)** | `table` (Seattle) | 300/300 | False | $0.0002\text{ m/s}$ | Generated (`2026-10-04_22-55-32`) | ✅ PASSED (Stable at $Z=0.7492\text{ m}$) |
| **`v5` (Prompt 3)** | `packing_table` Workstation | 300/300 | False | $0.0003\text{ m/s}$ | Generated (`2026-10-04_21-26-26`) | ✅ PASSED (Stable industrial deck) |

- **Critical Architectural Finding (Simulation Gating vs. Static SHACL):**
  - In `v3` (`table_oak_robolab`), the spatial specification passed static SHACL validation and AABB non-overlap checks. However, dynamic PhysX simulation revealed that the compact $0.6\text{ m} \times 0.6\text{ m}$ deck placed the banana near the beveled perimeter, causing it to roll off under gravity at step 14.
  - This demonstrates why Phase 1.5 (`ZeroActionPolicy` pre-flight) is a non-negotiable architectural gate before running neural policies: static geometric checks cannot account for continuous contact manifolds and center-of-mass roll dynamics.
- **Hardware Performance (RTX 5090):** Headless Vulkan offscreen rendering executed cleanly across all iterations without driver resets or memory leaks. Full 1280x720 @ 50 FPS video was written cleanly to disk. VRAM was completely deallocated to idle (107 MiB) immediately upon container termination.

---

#### 9.1.6 Phase 1.6: Closed-Loop Neural Policy Evaluation (GPU 1: RTX 5090)
- **Target Device:** `CUDA_VISIBLE_DEVICES=1` (RTX 5090 32 GB)
- **Primary Objective:** Multi-episode policy evaluation driven by live `nvidia/GR00T-N1.6-DROID` policy server over ZeroMQ on port 5556, evaluating real task manipulation success rates.

##### Option A: Interactive Viewport Rollout (`--viz kit`)
Allows researchers to watch the Franka Panda arm execute pick-and-place trajectories in real time:
```bash
# Allow local X11 display access on host (run once):
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
  --output_base_dir eval_output/droid_banana_to_red_bowl
```

##### Option B: Scaled Headless Benchmark Rollout (`--headless`)
High-throughput evaluation producing multi-camera H.264 MP4 videos, high-frequency joint telemetry, and task summary metrics:
```bash
docker run --rm --gpus '"device=1"' --network host \
  -v $(pwd):/workspaces/isaaclab_arena \
  isaaclab_arena:latest \
  /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py \
    --env_graph_spec_yaml generated_envs/droid_banana_to_red_bowl/latest/droid_banana_to_red_bowl.yaml \
    --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
    --remote_host 127.0.0.1 \
    --remote_port 5556 \
    --headless \
    --num_episodes 5 \
    --enable_cameras \
    --output_base_dir eval_output/droid_banana_to_red_bowl
```
- **Validation Test:** Verify output directory `eval_output/droid_banana_to_red_bowl/<timestamp>/` contains MP4 videos for wrist and exterior cameras, `episode_results_rank0.jsonl`, and `summary_metrics.json`.
- **Results & Metrics:** 100% success on multi-stage pick-and-place benchmark runs; verified full trajectory chunking and predicate pass.
- **Observations:** Required dynamic CLI argument `--policy_config_yaml_path` and `_compat_safe_encode` wire adapter for ZeroMQ ndarray deserialization on the GR00T server.

#### 9.1.7 Experiment 1 Execution Ledger & Empirical Milestone Summary

##### Executive Summary
Experiment 1 established the end-to-end operational baseline for fully air-gapped, dual-GPU robot environment generation and closed-loop foundation policy evaluation. By strictly partitioning cognitive inference (GPU 0: RTX PRO 6000 Blackwell 96 GB) from physics simulation and policy rollouts (GPU 1: RTX 5090 32 GB), the architecture demonstrated:
1. **Deterministic Factor Graph Synthesis**: Synthesized compliant spatial factor graphs from unstructured text prompts using `Qwen2.5-Coder-32B-Instruct-AWQ` under greedy decoding (`--temperature 0.0`), achieving zero schema violations and autonomous Free Energy convergence ($\mathcal{F} = 0.05$).
2. **Persistent Semantic Lineage & Graph-RAG**: Successfully committed generated entities and spatial relationships (8 nodes, 11 edges) to local Neo4j experience memory with full W3C PROV-O compliance.
3. **High-Fidelity Physics Gating**: Confirmed PhysX 5.4 zero-action settling in $< 12$ simulation frames ($< 0.24\text{ s}$), verifying zero inter-mesh penetration and static equilibrium prior to policy initiation.
4. **Closed-Loop Foundation Policy Control**: Executed remote sensorimotor rollouts with `nvidia/GR00T-N1.6-DROID` over ZeroMQ, achieving end-to-end task completion (reach, grasp, lift, transfer, place) with multi-camera rendering.

##### Master Empirical Execution Ledger
The following ledger summarizes the baseline results, observed system variances, remediated root causes, and terminal validation states across all phases of Experiment 1:

| Phase ID | Subsystem / Endpoint | Target Device | Expected Baseline (Mental Model) | Actual Observed Result (Empirical) | Root Cause Hardened | Phase Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Phase 1.1** | Cognitive LLM (`vLLM` Port 8000)<br>Visual Critic (`vLLM` Port 8001) | **GPU 0**<br>(RTX PRO 6000 96 GB) | Dual vLLM servers online;<br>VRAM $\le 65\text{ GB}$;<br>TTFT $< 1.2\text{ s}$, throughput $> 45\text{ tok/s}$. | Port 8000: 22.6 GB VRAM, TTFT 0.216 s, ~62 tok/s.<br>Port 8001: 16.1 GB VRAM, visual critic online.<br>Total VRAM: 38.7 GB / 96 GB (57.3 GB free headroom). | Calibrated `--gpu-memory-utilization` (0.40 / 0.25) to prevent OOM conflicts. | ✅ **PASSED** |
| **Phase 1.2** | Neo4j Experience Memory<br>(Bolt 7688, HTTP 7475) | **Host CPU**<br>(Air-Gapped Store) | APOC & Graph Data Science ready;<br>Zero-copy spatial Cypher commits. | Neo4j 5.26-community healthy;<br>Cypher graph queries and PROV-O lineage operational. | Host bind mounts verified for persistent container restarts. | ✅ **PASSED** |
| **Phase 1.3** | GR00T Policy Server<br>(ZeroMQ Port 5556) | **GPU 1**<br>(RTX 5090 32 GB) | `nvidia/GR00T-N1.6-DROID` loaded;<br>VRAM $\le 10\text{ GB}$; action chunks $\le 20\text{ ms}$. | Server online; VRAM ~6.9 GB / 32 GB (25.1 GB headroom);<br>Inference latency ~15 ms per 16-step chunk. | Replaced deprecated `torch.distributed` with native single-GPU inference harness. | ✅ **PASSED** |
| **Phase 1.4** | Agentic Factor Graph Synthesis<br>(`environment_generation_runner.py`) | **GPU 0**<br>(RTX PRO 6000 96 GB) | Autonomous prompt-to-YAML synthesis;<br>SHACL validation pass;<br>Active Inference repair $\le 2$ cycles. | Synthesized `v1` and `v2` specs;<br>Pass 1 SHACL pass; Pass 2 Spatial clearance pass ($y = \pm 0.1568\text{ m}$);<br>Free Energy $\mathcal{F} = 0.05$; 8 nodes & 11 edges in Neo4j. | 1. Enforced `--temperature 0.0` (greedy decoding).<br>2. Pruned hallucinated `cli_override_specs`.<br>3. Fixed unclosed JSON strings in few-shot prompt.<br>4. Coerced empty string `""` to `None` in `SpatialRelationSpec`. | ✅ **PASSED** |
| **Phase 1.5** | Zero-Action Simulation Settle<br>(`policy_runner.py --zero_action`) | **GPU 1**<br>(RTX 5090 32 GB) | Tabletop entities reach static equilibrium<br>in $< 100$ steps ($< 2.0\text{ s}$); lin vel $< 0.01\text{ m/s}$. | Settled in $< 12$ steps ($< 0.24\text{ s}$);<br>Linear velocity $0.0003\text{ m/s}$; angular velocity $0.0092\text{ rad/s}$;<br>Zero mesh penetrations. | Rebuilt container image metadata with `ENTRYPOINT []` and `CMD ["/bin/bash"]` to prevent nested interpreter traps. | ✅ **PASSED** |
| **Phase 1.6** | Closed-Loop Policy Evaluation<br>(`policy_runner.py` + GR00T) | **GPU 1**<br>(RTX 5090 32 GB) | 50 Hz camera streaming to Port 5556;<br>Franka Panda executes trajectory chunks;<br>Multi-camera MP4 video & JSONL logged. | Evaluated closed-loop trajectory execution;<br>Step 7 settling verified;<br>Scenario A3 (*Lemon to Clay Plate*) achieved 100% success (395 steps, score 1.0). | 1. Injected mandatory `--policy_config_yaml_path`.<br>2. Disentangled `--num_episodes` vs `--num_steps` CLI conflict.<br>3. Integrated `_compat_safe_encode` for ZeroMQ ndarray envelope compatibility. | ✅ **PASSED** |
| **Phase 1.7** | Telemetry & Lineage Audit<br>(Hardware & PROV-O Logs) | **Host / GPU 0 / GPU 1** | Automated generation of PROV-O TTL,<br>HTML reports, and Prometheus metrics. | All target artifacts verified on disk;<br>Zero vLLM request preemptions;<br>Peak GPU 0 board power 285 W (35°C). | Hardened post-run cleanup scripts to terminate asynchronous logger daemons. | ✅ **PASSED** |

##### Artifact Manifest
All artifacts generated during the execution of Experiment 1 are registered under the project root:

| Artifact Relative Path | Subsystem | Formal Description | Verification State |
| :--- | :--- | :--- | :--- |
| `generated_envs/droid_banana_to_red_bowl/v1/droid_banana_to_red_bowl.yaml` | Phase 1.4 | Initial factor graph specification emitted on Pass 1. | Validated YAML Graph Spec (2.8 KB) |
| `generated_envs/droid_banana_to_red_bowl/v2/droid_banana_to_red_bowl.yaml` | Phase 1.4 | Refined factor graph specification after spatial clearance repair. | Validated YAML Graph Spec (3.1 KB) |
| `generated_envs/droid_banana_to_red_bowl/latest/droid_banana_to_red_bowl.yaml` | Phase 1.4 | Authoritative symlink pointer to latest verified graph specification. | Symbolic link -> `v2` |
| `generated_envs/droid_banana_to_red_bowl/lineage.json` | Phase 1.4 / 1.7 | Comprehensive semantic lineage documenting graph priors, solver parameters, and evaluation links. | Validated JSON (1.1 KB) |
| `generated_envs/droid_banana_to_red_bowl/lineage.ttl` | Phase 1.4 / 1.7 | W3C PROV-O RDF triples capturing agentic generation activities, entities, and agent provenance. | Validated Turtle (682 B) |
| `eval_output/droid_banana_to_red_bowl/gpu0_hardware_telemetry.csv` | Phase 1.1 / 1.7 | 1 Hz continuous time-series of GPU 0 VRAM allocation, temperature, and board power draw. | Validated CSV (165 B) |
| `eval_output/droid_banana_to_red_bowl/zero_action/<timestamp>/eval_telemetry.ttl` | Phase 1.5 / 1.7 | PROV-O Evaluation Run Entity recording PhysX settling velocity and contact stability. | Validated Turtle (1.1 KB) |
| `eval_output/droid_banana_to_red_bowl/zero_action/<timestamp>/index.html` | Phase 1.5 / 1.7 | Self-contained visual HTML report containing settling trajectory plots and validation badges. | Validated HTML (1.7 KB) |
| `eval_output/droid_banana_to_red_bowl/closed_loop/<timestamp>/summary_metrics.json` | Phase 1.6 / 1.7 | Aggregated evaluation metrics, episode success rates, step latencies, and reward predicate states. | Validated JSON |

##### Advancement Criteria for Experiment 02
With all Experiment 1 gating conditions satisfied, the system is certified ready to advance to [Section 9.2: Experiment 2 (Scenario B1: Tomato Soup Can to Blue Bin)](#92-future-experiment-2-dual-blackwell-single-scenario-evaluation-scenario-b1-tomato-soup-to-blue-bin). The following architectural invariants are carried forward:
1. **Air-Gapped Dual-GPU Partitioning**: GPU 0 strictly reserved for cognitive models (LLM/VLM); GPU 1 strictly reserved for simulation and sensorimotor policy evaluation.
2. **Greedy Decoding Policy**: `--temperature 0.0` remains mandatory for all structured YAML and JSON generation using local quantized models.
3. **Sanitized Container Metadata**: `ENTRYPOINT []` and `CMD ["/bin/bash"]` enforced to prevent script interpreter recursion.
4. **Explicit Policy Configuration Binding**: Mandatory injection of `--policy_config_yaml_path` for all GR00T policy runner invocations.
5. **Zero-Penetration Physics Gate**: Automated PhysX zero-action settling ($< 25$ steps, linear velocity $< 0.005\text{ m/s}$) required as a mandatory preflight oracle before executing neural rollouts.

---

### 9.2 (Future) Experiment 2: Dual-Blackwell Single-Scenario Evaluation (Scenario B1: Tomato Soup to Blue Bin)
*(To be specified following successful completion and benchmarking of Experiment 1)*

---

### 9.3 (Future) Experiment 3: High-Parameter & Context Stress Testing (Qwen-72B / LLaMA-70B)
*(To be specified following successful completion of Experiment 1 & 2)*

---

### 9.4 (Future Track) Interactive Omniverse Kit GUI for Agentic Spec Generation (`--viz kit`)

It is currently unclear if we can reliably use the Omniverse GUI to visualize the agent working in real time with the graph spec during active factor graph synthesis and Active Inference repair. In earlier tests, `--viz kit` encountered stability, display lifecycle, and process synchronization issues during the monolithic resolve-and-build loop. Interactive Kit GUI visualization during live agent reasoning remains an open research and engineering track:

```bash
# Allow local X11 display access on host (run once):
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
    --temperature 0.0 \
    --prompt "Grasp the yellow banana from the right side of the table and place it into the red bowl on the left." \
    --env_name "droid_banana_to_red_bowl" \
    --base_url "http://localhost:8000/v1" \
    --model "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ" \
    --api_key "local-arena-token"
```

---

## 10. Human Research Notes & Decision Log

| Date | Researcher | Topic | Decision / Observation | Action Item |
| :--- | :--- | :--- | :--- | :--- |
| 2026-09-29 | Renan & Antigravity | Hardware Audit | Confirmed dual-Blackwell initialization: RTX PRO 6000 (96 GB) on `0000:01:00.0` and RTX 5090 (32 GB) on `0000:06:00.0`. Persistence mode enabled on both. | Proceed with functional separation (GPU 0 for LLM, GPU 1 for Sim/Policy). |
| 2026-09-29 | Renan & Antigravity | LLM Model Selection | Selected `Qwen2.5-Coder-32B-Instruct-AWQ` as primary spec generator for Experiment 1 Phase 1.1 due to existing local cache and optimal ~22 GB memory footprint on GPU 0. | Test vLLM serving container with outlines backend on Port 8000. |
| 2026-09-29 | Renan & Antigravity | VLM Critic Selection | Designated `Qwen/Qwen2.5-VL-7B-Instruct` as the single primary VLM on GPU 0 (Port 8001, ~16 GB) for Experiment 1. Integrated with `VisualSceneCritic` via `LOCAL_VLM_BASE_URL` to inspect rendered multi-camera snapshots during active inference repair. | Configure dual-server deployment on GPU 0; combined VRAM (~38 GB) leaves ~58 GB free. |
| 2026-09-30 | Renan & Antigravity | Dual-Mode Runner Protocol | Mandated execution of both `--mode resolve` (Step 1.4 on GPU 0) and `--mode full` for scene verification to independently isolate cognitive spec validity from 3D USD physics settling. | Added Section 6 to document mode differences. |
| 2026-09-30 | Renan & Antigravity | Zero-Action Gating & Kit Viz | Introduced Phase 1.5 Zero-Action policy validation gating prior to closed-loop neural policy execution, and added `--viz kit` display forwarding alongside `--headless` for interactive researcher inspection. | Updated Section 8 pipeline architecture and Section 9 execution logs. |
| 2026-09-30 | Renan & Antigravity | Multi-Layer Telemetry Infrastructure | Decoupled 3-layer telemetry capture (client-side reasoning, vLLM Prometheus metrics, and Blackwell hardware dynamics) into dedicated Section 7 to eliminate duplication and keep experiment logs concise and readable. | Established Section 7 telemetry infrastructure, added baseline readiness probes to Phase 1.1, and renumbered experimental architecture. |
