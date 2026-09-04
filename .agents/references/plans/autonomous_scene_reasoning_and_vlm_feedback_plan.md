# Autonomous Scene Reasoning & Closed-Loop Active Inference Implementation Plan

This document outlines the detailed architectural and technical plan for implementing **Autonomous Scene Reasoning, Semantic Workspace Sectors, Multimodal VLM Closed-Loop Critique, and Graph-RAG Experience Memory** in IsaacLab-Arena.

---

## 1. Executive Summary & System Architecture

The objective is to upgrade IsaacLab-Arena's environment generation from an open-loop symbolic solver into a **fully closed-loop Active Inference Perception-Action Engine**.

```mermaid
graph TD
    UserPrompt["User Prompt / Goal"] --> Agent["Environment Generation Agent<br/>(Active Inference Engine)"]

    subgraph "Phase 1: Generative Specification & Graph-RAG"
        GraphRAG["Graph-RAG Memory<br/>(Neo4j Prior Retrieval)"] -->|Few-Shot Prior Subgraphs| Agent
        Agent -->|Emits Candidate Spec| Spec["ArenaEnvGraphSpec<br/>(Entities, Sectors, Relations)"]
    end

    subgraph "Phase 2: Symbolic & Geometric Grounding"
        Spec --> SHACL["1. SHACL-star Rule Validator"]
        Spec --> SectorOracle["2. Semantic Sector & Reach Oracle"]
        Spec --> FactorGraph["3. Differentiable Spatial Factor Graph<br/>(Continuous LBP Relaxation)"]
        SHACL -->|Semantic Violations| Agent
        SectorOracle -->|Reach / Sector Violations| Agent
        FactorGraph -->|Relaxed Poses (x, y, z, yaw)| Stage["USD Stage Assembly"]
    end

    subgraph "Phase 3: Multimodal Closed-Loop Feedback"
        Stage --> FastPhysX["4. 10-Step PhysX Preflight Critic<br/>(Toppling, Slip, Contact)"]
        Stage --> FastRender["5. TiledCamera Visual Snapshot<br/>(RGB Viewports)"]
        FastRender --> VLMCritic["6. Multimodal VLM Critic<br/>(Occlusion, Clutter, Headroom)"]
        FastPhysX -->|Physics Prediction Error| Agent
        VLMCritic -->|Visual Prediction Error| Agent
    end

    subgraph "Phase 4: Execution & Lineage"
        Stage --> VerifiedEnv["Verified Environment<br/>(YAML, README, Neo4j Lineage)"]
        VerifiedEnv --> PolicyRunner["Evaluation Policy Runner<br/>(Benchmarking Flywheel)"]
    end
```

---

## 2. Component 1: Semantic Workspace Sectors & Dexterity Zones

### 2.1 Problem Statement
Currently, generic support relations (e.g. `on(rubiks_cube, maple_table)`) sample uniformly across the entire $0.90\text{ m} \times 0.60\text{ m}$ table surface. This causes objects to land in far back corners ($X > 0.0$), forcing the robot arm into awkward, over-extended reach postures.

### 2.2 Technical Design
We divide fixture support surfaces into **functional semantic sectors** oriented relative to the robot anchor:

```
                  +Y = +0.30m (Far Left)
        ┌───────────────────┬───────────────────┐
        │  rear_left        │  rear_right       │
        │  (storage/buffer) │  (storage/buffer) │
        ├───────────────────┼───────────────────┤
        │  front_left       │  front_right      │
        │  (staging/drop)   │  (staging/drop)   │
        │         [front_center]                │
        │       (primary pick zone)             │
        └───────────────────┴───────────────────┘
                  -Y = -0.30m (Far Right)
                         ▲
                         │
                 [🤖 Robot Base] (X = -0.55m)
```

#### Sector Definitions (on `maple_table_robolab`):
* `front_center`: $X \in [-0.32, -0.08]\text{ m}, Y \in [-0.12, +0.12]\text{ m}$ *(Primary manipulation sweet-spot)*
* `front_left`: $X \in [-0.32, -0.08]\text{ m}, Y \in [+0.10, +0.26]\text{ m}$ *(Left receptacle / bin staging zone)*
* `front_right`: $X \in [-0.32, -0.08]\text{ m}, Y \in [-0.26, -0.10]\text{ m}$ *(Right receptacle / tool zone)*
* `rear_center`: $X \in [+0.05, +0.35]\text{ m}, Y \in [-0.15, +0.15]\text{ m}$ *(Background storage zone)*

### 2.3 Implementation Details
1. **Schema & Types** (`isaaclab_arena/environment_spec/arena_env_graph_types.py`):
   Add `surface_sector: str | None = None` to `SpatialRelationSpec.params` and `ReifiedSpatialRelationSpec`.
2. **Fixture Sector Map** (`isaaclab_arena/agentic_environment_generation/spatial_geometric_oracle.py`):
   Implement `get_fixture_sector_bounds(fixture_name, sector_name)` returning bounding box $(x_{\min}, x_{\max}, y_{\min}, y_{\max}, z)$.
3. **Factor Graph Integration** (`isaaclab_arena/relations/spatial_factor_graph.py`):
   Update `add_support_factor` to accept sector bounds, keeping objects strictly inside the requested functional quadrant during LBP relaxation.
4. **Active Inference Prompting** (`isaaclab_arena/agentic_environment_generation/spec_inference.py`):
   Update system prompt and JSON schema to encourage the LLM to assign manipulands to `front_center` and receptacles to `front_left` / `front_right`.

---

## 3. Component 2: Visual Active Inference (Multimodal VLM Critic)

### 3.1 Problem Statement
Symbolic and geometric checks cannot detect camera line-of-sight occlusions, lighting contrast issues, or whether a bin is positioned such that its interior is invisible to the robot's overhead camera.

### 3.2 Technical Design
Introduce a `VisualSceneCritic` module that renders a 1-frame multi-camera preview and uses a multimodal LLM (Claude 4.5 Vision or GPT-4o) as an observation critic.

```
[Candidate Scene Spec]
       │
       ▼
[Render Snapshot] ────► `external_camera_rgb` (720x1280) & `wrist_camera_rgb`
       │
       ▼
[Multimodal VLM Call] ─► Evaluates 4 Structured Criteria:
                           1. Object Visibility & Line-of-Sight (0-10)
                           2. Gripper Approach Headroom (0-10)
                           3. Tabletop Realism & Natural Spacing (0-10)
                           4. Container Opening Accessibility (0-10)
       │
       ▼
[Score Evaluation]
       ├── If all scores >= 8.0 ──► ✅ Pass Scene
       └── If any score < 8.0   ──► ❌ Compute Visual Prediction Error & Feed back to Agent
```

### 3.3 Implementation Details
1. **Renderer Module** (`isaaclab_arena/agentic_environment_generation/visual_critic.py`):
   * Implements `capture_scene_preview_images(spec) -> dict[str, Image]` using lightweight headless `TiledCamera` offscreen capture.
2. **Critic Prompt & Rubric** (`visual_critic.py`):
   * Sends side-by-side external and wrist views to `InferenceBackend.multimodal_chat()`.
   * Formats response into structured JSON:
     ```json
     {
       "conforms": false,
       "visibility_score": 6,
       "occlusion_issues": "The rubiks_cube is partially occluded behind the tall bin from the main camera view.",
       "actionable_feedback": "Shift the rubiks_cube 8cm to the right (Y = -0.15) and move the bin to front_left (Y = +0.18)."
     }
     ```
3. **Bayesian Loop Integration** (`isaaclab_arena/agentic_environment_generation/environment_generation_agent.py`):
   * In `generate_spec` and `refine_spec`, if SHACL and Geometry pass, run the `VisualSceneCritic`.
   * If `conforms == False`, inject `actionable_feedback` as a visual prediction error into `repair_with_feedback()`.

---

## 4. Component 3: Graph-RAG Experience Memory (Neo4j Priors)

### 4.1 Problem Statement
Currently, each new prompt generates a scene from scratch without leveraging past verified, high-performing environment subgraphs stored in Neo4j.

### 4.2 Technical Design
Implement a `GraphRAGRetriever` that matches user intent against the Neo4j LPG database and retrieves relevant verified topologies as few-shot priors.

```
[User Prompt: "Franka sorting fruit into a bowl on wireshelving"]
       │
       ▼
[Keyword / Semantic Filter] ─► Extracts Embodiment ("franka"), Fixture ("wireshelving"), Task ("PickAndPlace")
       │
       ▼
[Neo4j Cypher Subgraph Query]
  MATCH (e:EnvironmentGraph)-[:HAS_EMBODIMENT]->(emb:Embodiment)
  MATCH (e)-[:CONTAINS_OBJECT]->(f:Fixture)
  WHERE f.registry_name CONTAINS "wireshelving" AND e.converged = true
  RETURN e, emb, f, e.spec_yaml LIMIT 2
       │
       ▼
[Prior Subgraph Injection] ─► Injected as "Relevant Verified Examples" in LLM System Prompt
       │
       ▼
[First-Pass Convergence] ──► Faster generation, fewer repair iterations, 50% lower token cost
```

### 4.3 Implementation Details
1. **Retriever Module** (`isaaclab_arena/agentic_environment_generation/graph_rag.py`):
   * Queries Neo4j for matching `EnvironmentGraph` nodes filtered by `converged = true` and shared entity registries.
2. **Prompt Context Formatter**:
   * Compacts the retrieved subgraphs into concise factor-graph snippets embedded in `spec_inference.py`.

---

## 5. Component 4: Dynamic PhysX Preflight Critic

### 5.1 Problem Statement
Static bounding-box checks cannot catch dynamic simulation issues such as:
* Spherical/curved objects rolling off due to gravity.
* High contact penetration forces that trigger PhysX explosive instabilities.
* Robot gripper starting in collision with tall receptacles.

### 5.2 Technical Design
Run an ultrafast 10-step zero-action rollout in PhysX memory:
1. Step physics for 10 frames ($0.1\text{ s}$).
2. Track root linear displacement $\Delta \mathbf{p}$ and angular velocity $\boldsymbol{\omega}$ for all objects:
   * If $\|\Delta \mathbf{p}\|_{xy} > 0.05\text{ m}$ (unintended sliding/rolling) $\to$ **Flag unstable placement**.
   * If $\| \mathbf{v}_z \| < -1.5\text{ m/s}$ (object free-falling off table) $\to$ **Flag table boundary violation**.
   * If collision normal impulse $> 100\text{ N}$ $\to$ **Flag penetration jam**.
3. Feed dynamic diagnostics back to Active Inference repair loop.

---

## 6. Implementation Roadmap & Milestones

| Milestone | Phase / Task | Target Deliverables | Complexity |
| :--- | :--- | :--- | :--- |
| **M1** | **Semantic Workspace Sectors** | • Update `arena_env_graph_types.py` with `surface_sector`.<br>• Add sector bounds to `spatial_geometric_oracle.py`.<br>• Sector-bounded support potential in `SpatialFactorGraph`.<br>• Unit tests in `test_spatial_factor_graph.py`. | **Low / Immediate** |
| **M2** | **Graph-RAG Memory (Neo4j)** | • `graph_rag.py` Cypher retriever.<br>• Inject top-2 validated subgraphs into `spec_inference.py`.<br>• Unit tests verifying retrieval against active Neo4j database. | **Medium** |
| **M3** | **Visual VLM Closed-Loop Critic** | • `visual_critic.py` with multi-camera snapshot.<br>• Multimodal VLM rubric prompt & parser.<br>• Integration into `EnvironmentGenerationAgent` repair loop. | **Medium-High** |
| **M4** | **PhysX Preflight Dynamic Critic** | • 10-step headless rollout tensor monitor.<br>• Dynamic instability diagnostics reporter.<br>• Regression test suite for self-healing physics. | **Medium** |

---

## 7. Testing & Verification Strategy

1. **Unit Testing**:
   * `pytest isaaclab_arena/tests/test_spatial_factor_graph.py`: Assert that objects constrained to `front_center` and `front_left` sectors converge strictly within the robot-facing quadrant ($X \in [-0.32, -0.08]$).
2. **Integration Testing**:
   * Run end-to-end generation with `--prompt "Droid robot sorting rubiks cube into vomp bin on maple table"`.
   * Verify that:
     1. Objects spawn in the front sector near the robot.
     2. Visual VLM critic confirms 0 occlusions.
     3. PhysX rollout completes with 0 drift.
     4. Neo4j logs the complete provenance lineage.
