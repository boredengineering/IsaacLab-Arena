# Agent-Generated Environments (`generated_envs/`)

This directory contains **environment specifications (`ArenaEnvGraphSpec` YAMLs)** synthesized automatically by IsaacLab-Arena's **Active Bayesian Inference Agent** from natural language prompts.

---

## 1. Overview & Directory Organization

Whenever you resolve a prompt, the runner saves the generated scene graph specification into an isolated subfolder:

```text
generated_envs/
├── README.md                             # This guide
├── droid_apple_bowl/                     # Generated task folder
│   └── droid_pick_apple_to_bowl.yaml     # ArenaEnvGraphSpec definition
├── droid_mustard_bin/
│   └── droid_pick_mustard_into_bin.yaml
├── droid_rubiks_blue_bin/
│   └── droid_pick_rubiks_cube_to_blue_bin.yaml
└── g1_box_pnp/
    └── g1_pick_and_place_brown_box.yaml
```

---

## 2. Step 1: Configure Inference Credentials

Set your API key and base URL before running the generation agent:

### Option A: OpenRouter (Claude Sonnet 4.5, Gemini 3.7, GPT-4o)
```bash
export OPENROUTER_API_KEY="your-openrouter-key"
export OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
```

### Option B: OpenAI / Azure / NVIDIA Endpoints
```bash
export OPENAI_API_KEY="your-openai-key"
# Optional: export OPENAI_BASE_URL="https://api.openai.com/v1"
```

---

## 3. Step 2: Generate an Environment (`--mode resolve`)

Use [`environment_generation_runner.py`](../isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py) to parse natural language instructions into a grounded physical scene graph:

```bash
docker exec -it \
  -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --model "anthropic/claude-sonnet-4.5" \
  --prompt "Droid stands in front of the table, picks up the red apple from the maple table and places it in the wooden bowl." \
  --out_dir /workspaces/isaaclab_arena/generated_envs/droid_apple_bowl
```

### What Happens During Generation:
1. **Semantic Prior Synthesis**: The LLM infers embodiments, background fixtures, objects, and relational constraints (`on`, `inside`, `next_to`).
2. **Dual-Oracle Verification**:
   * **W3C SHACL Semantic Oracle**: Verifies schema ontology and entity typing.
   * **Spatial Geometric & Reachability Oracle**: Checks for table overhangs ($<5\,\text{cm}$) and robot arm kinematic reach ($r \le 0.85\,\text{m}$).
3. **Continuous Factor Graph Relaxation (Dynamic LBP)**: Damped gradient energy minimization computes equilibrium initial poses with non-overlap clearance.
4. **Active Bayesian Self-Healing**: If any constraint fails, the agent generates structured prediction error feedback and heals the graph automatically.
5. **Observability Telemetry**: A summary card is printed and metrics are synced to Neo4j.

**Sample Telemetry Card**:
```text
======================================================================
  🤖 Active Bayesian Inference & Graph Generation Telemetry
======================================================================
• Model:               anthropic/claude-sonnet-4.5
• Convergence Status:  🟢 Converged (Variational Free Energy ≈ 0)
• Total LLM Calls:     1
• Repair Iterations:   0
• Token Consumption:   7,184 tokens (6,236 prompt, 948 completion)
• Wall-Clock Latency:  19.93s (avg 19.93s / call)
• Physical Invariants: SHACL-star: ✅ Passed | Spatial Geometry: ✅ Passed
======================================================================
```

---

## 4. Step 3: Iteratively Refine or Edit an Existing Environment

If you are disappointed with a generated scene or want to modify specific assets, poses, or tasks, you have **four mechanisms** to continue from an existing environment:

### Method 1: Conversational Agent Refinement (`--base_spec` & `--feedback`)
Feed natural language critique directly into the Active Inference agent to modify the existing graph without starting over from scratch:

```bash
docker exec -it \
  -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --model "anthropic/claude-sonnet-4.5" \
  --base_spec /workspaces/isaaclab_arena/generated_envs/droid_rubiks_blue_bin/droid_pick_rubiks_cube_to_blue_bin.yaml \
  --feedback "Replace the blue bin with a wooden bowl and place a banana next to the rubiks cube." \
  --out_dir /workspaces/isaaclab_arena/generated_envs/droid_rubiks_banana_bowl
```
The agent loads the base spec, interprets your modification request against the registered asset vocabulary, re-runs the SHACL and Spatial Geometric oracles, relaxes the factor graph, and syncs the updated graph to Neo4j.

### Method 2: Direct Declarative YAML Editing
Edit the generated YAML file directly in any editor:
* **Swap Objects**: Change `registry_name` (e.g. from `blue_sorting_bin` to `wooden_bowl_hot3d_robolab`).
* **Adjust Coordinates**: Modify `initial_pose.position_xyz` (e.g. change $[0.0, 0.25, 0.75]$).
* **Edit Relations**: Add/tweak `surface_anchor`, `nominal_height`, or containment relations.
* **Tweak Tasks**: Update `task.params.destination_location` or thresholds.

Once edited, test immediately with `--mode build`:
```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode build \
  --headless \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_rubiks_blue_bin/droid_pick_rubiks_cube_to_blue_bin.yaml
```

### Method 3: Programmatic Python API
Load and mutate the environment graph programmatically:
```python
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec, AssetSpec, SpatialRelationSpec

# Load existing spec
spec = ArenaEnvGraphSpec.from_yaml("generated_envs/droid_rubiks_blue_bin/droid_pick_rubiks_cube_to_blue_bin.yaml")

# Add a new object and support relation
spec.objects.append(AssetSpec(id="apple", registry_name="apple_01_objaverse_robolab", role="object"))
spec.relations.append(SpatialRelationSpec(kind="on", subject="apple", reference="maple_table", params={"surface_anchor": "table_top"}))

# Save updated spec
spec.write_yaml("generated_envs/droid_rubiks_blue_bin/droid_pick_rubiks_cube_apple.yaml")
```

---

## 5. Step 4: Test and Validate the Environment

### A. Fast Headless Rollout (Zero-Action Physics Settling)
Verify in headless mode that all assets assemble and settle under gravity without collision or drops:

```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode build \
  --headless \
  --num_envs 1 \
  --num_steps 60 \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_apple_bowl/droid_pick_apple_to_bowl.yaml
```

### B. Interactive 3D Simulation Viewport (`--viz kit`)
Open the interactive Isaac Sim GUI to watch the robot and scene assemble on your display:

```bash
# 1. Enable X11 display forwarding on the host
xhost +local:root

# 2. Launch interactive viewport
docker exec -it \
  -e DISPLAY="$DISPLAY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode build \
  --viz kit \
  --num_envs 1 \
  --num_steps 1200 \
  --enable_cameras \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_apple_bowl/droid_pick_apple_to_bowl.yaml
```

### C. Policy Evaluation with Metrics & HTML Dashboard
Run formal policy evaluations using [`policy_runner.py`](../isaaclab_arena/evaluation/policy_runner.py) to capture performance metrics and generate reports in [`eval_output/`](../eval_output/):

```bash
docker exec -it \
  -e DISPLAY="$DISPLAY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --policy_type isaaclab_arena.policy.zero_action_policy.ZeroActionPolicy \
  --num_steps 300 \
  --num_envs 1 \
  --enable_cameras \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_apple_bowl/droid_pick_apple_to_bowl.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/droid_apple_test
```

---

## 5. Step 4: Inspect the Knowledge Graph in Neo4j

Every generated environment is synced to Neo4j as a Labeled Property Graph (LPG) with RDF 1.2 reified factor nodes.

1. Open **[http://localhost:7475](http://localhost:7475)** in your web browser.
   * **Username**: `neo4j`
   * **Password**: `isaaclab_arena_password`

2. Run any of the following Cypher queries:

### 1. Visualize Complete Environment Scene Graph
```cypher
MATCH (e:EnvironmentGraph {name: "droid_pick_apple_to_bowl"})-[r1]->(n)
OPTIONAL MATCH (n)-[r2]->(m)
RETURN e, r1, n, r2, m
```

### 2. View Generation Telemetry Properties
```cypher
MATCH (e:EnvironmentGraph)
RETURN e.name AS Environment, 
       e.model_used AS Model, 
       e.llm_call_count AS LLMCalls, 
       e.repair_iterations AS RepairIterations, 
       e.total_tokens AS TotalTokens, 
       e.generation_time_s AS GenerationTimeSec,
       e.converged AS Converged
ORDER BY e.updated_at DESC
```

### 3. Trace Physical Factor Nodes & Kinematic Manifolds
```cypher
MATCH (e:EnvironmentGraph {name: "droid_pick_apple_to_bowl"})-[:HAS_REIFIER]->(rf:ReifiedRelation)
MATCH (rf)-[:REIFIES_SUBJECT]->(s)
MATCH (rf)-[:REIFIES_OBJECT]->(t)
RETURN s.id AS Subject, rf.relation_type AS Relation, t.id AS Target, 
       rf.surface_anchor AS Anchor, rf.required_headroom AS Headroom, 
       rf.prior_entropy AS PriorEntropy, rf.kinematic_manifold AS Manifold
```

---

## 6. Supported Assets & Vocabulary

When constructing prompts, the agent selects from the registered vocabulary in the asset catalogue:

* **Embodiments**: `droid_abs_joint_pos` (*DROID Franka Panda*), `g1` (*Unitree G1 Bipedal Humanoid*), `franka` (*Franka Emika*).
* **Backgrounds & Fixtures**: `maple_table_robolab` (*RoboLab Maple Table*), `office_table`, `wireshelving_a01_vomp_robolab`.
* **Graspable Objects**:
  * *Fruits & Food*: `apple_01_objaverse_robolab`, `banana_01_fruits_veggies_robolab`, `avocado01_fruits_veggies_robolab`, `tomato_soup_can_ycb_robolab`, `mustard_ycb_robolab`.
  * *Everyday Items*: `rubiks_cube_hot3d_robolab`, `mug_ycb_robolab`, `marker_hot3d_robolab`.
* **Receptacles & Containers**: `wooden_bowl_hot3d_robolab`, `bowl_ycb_robolab`, `grey_bin_robolab`, `blue_sorting_bin`, `plasticpail_a02_vomp_robolab`.
