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

##### Models & Runtimes Executing in Experiment 1
| System Role | Model / Image | Execution Device | Memory Footprint | Network / Port | Primary Responsibility |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Cognitive Spec Generator (LLM)** | `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ` | GPU 0 (RTX PRO 6000 96 GB) | ~22 GB GDDR7 | HTTP `127.0.0.1:8000` | Zero-cloud schema-guided factor graph synthesis & active repair |
| **Visual Scene Critic (VLM)** | `Qwen/Qwen2.5-VL-7B-Instruct` | GPU 0 (RTX PRO 6000 96 GB) | ~14–16 GB GDDR7 | HTTP `127.0.0.1:8001` | Tier 2 local multimodal inspection of multi-camera USD viewport renders (occlusion, line-of-sight, floating objects) |
| **Knowledge Graph Store** | `neo4j:5.26-community` | Host CPU / System RAM | ~4 GB DRAM | Bolt `127.0.0.1:7688`<br/>HTTP `127.0.0.1:7475` | Labeled Property Graph (LPG) storage for verified environment graphs |
| **Physical Policy Server** | `nvidia/GR00T-N1.6-DROID` (3B) | GPU 1 (RTX 5090 32 GB) | ~8 GB GDDR7 | ZeroMQ `tcp://127.0.0.1:5556` | Real-time sensor-to-action policy rollouts (7-DoF joint position delta) |
| **Simulation Runtime** | `isaaclab_arena:latest` (Isaac Sim 6.0) | GPU 1 (RTX 5090 32 GB) | ~10 GB GDDR7 | Headless (IPC / Host) | PhysX dynamics, USD stage resolution, and camera rendering |

> **GPU 0 VRAM Allocation Summary:**  
> - Spec Generator LLM: ~22 GB GDDR7  
> - Visual Critic VLM: ~16 GB GDDR7  
> - **Total GPU 0 Utilization:** ~38 GB / 96 GB (**~58 GB free headroom** for KV cache and large context batches)

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

##### Phase 1.4 Telemetry & Metrics Capture
Hardware and inference telemetry are captured during this phase using the hooks specified in [Section 7](#7-multi-layer-telemetry--observability-infrastructure):

| Metric Category | Target Indicator | Baseline (Pre) | Peak / Final (Post) | Delta / Total |
| :--- | :--- | :--- | :--- | :--- |
| **Cognitive Agent** | Repair Iterations | 0 | — | — |
| **Cognitive Agent** | Free Energy ($\mathcal{F}$) | Initial | — | Final Conformance |
| **vLLM Spec (8000)** | Prompt Tokens | — | — | — |
| **vLLM Spec (8000)** | Generation Tokens | — | — | — |
| **vLLM Spec (8000)** | KV Cache Saturation | 0.0 | — | Peak Gauge |
| **vLLM Spec (8000)** | Preemptions Total | 0 | 0 | 0 (Must be 0) |
| **vLLM Visual (8001)**| Critic Queries / Requests | — | — | — |
| **Hardware (GPU 0)** | Peak VRAM Allocated | ~38 GB | — | GDDR7 Used |
| **Hardware (GPU 0)** | Average Power Draw | ~49 W | — | Watts |

- **Results & Metrics:** *(To be recorded upon execution)*
- **Observations:** *(To be recorded)*

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
- **Validation Test:** Verify that `banana_ycb_robolab` rests stably in `front_right`, `bowl_ycb_robolab` rests in `front_left`, no explosive contact penetration occurs, and wrist/exterior cameras capture clean visual frames.
- **Results & Metrics:** *(To be recorded upon execution)*
- **Observations:** *(To be recorded)*

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
- **Results & Metrics:** *(To be recorded upon execution)*
- **Observations:** *(To be recorded)*

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
