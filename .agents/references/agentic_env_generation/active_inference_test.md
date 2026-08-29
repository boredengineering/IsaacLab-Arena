# Active Bayesian Inference & Semantic Reification Verification Guide

This guide details the step-by-step test tiers for validating RDF-star semantic reification, W3C SHACL-star constraints, active LLM repair loops, Neo4j Labeled Property Graph (LPG) synchronization, and physical simulation rollouts in IsaacLab-Arena.

---

### Prerequisites: Neo4j LPG Container

Ensure the Neo4j graph database container is running before executing LPG synchronization or inspection commands:

```bash
docker start neo4j-arena 2>/dev/null || docker run -d --name neo4j-arena \
  -p 7475:7474 -p 7688:7687 \
  -e NEO4J_AUTH=neo4j/isaaclab_arena_password \
  neo4j:5.26-community
```

---

### Tier 1: Semantic, Graph, & Reification Test Suite

Run the full semantic validation, RDF-star lifting/lowering, active Bayesian repair loop, and Neo4j LPG synchronization tests:

```bash
docker exec isaaclab_arena-latest /isaac-sim/python.sh -m pytest \
  isaaclab_arena/tests/test_rdf_validation.py \
  isaaclab_arena/tests/test_rdf_lowering.py \
  isaaclab_arena/tests/test_telemetry_to_prov.py \
  isaaclab_arena/tests/test_neo4j_lpg_sync.py \
  isaaclab_arena/tests/test_robot_relative_camera.py \
  isaaclab_arena/tests/test_environment_generation_agent.py -v
```

#### What this verifies:
* **W3C SHACL-star physical invariant rules** (mandatory terrain, Pink WBC single-thread check, corridor clearance).
* **Active LLM repair loop on SHACL violation** (`test_active_bayesian_repair_loop_on_shacl_violation`).
* **Neo4j Labeled Property Graph (LPG)** `:ReifiedRelation` factor nodes and continuous intervals.
* **3D Bipedal Capability Manifold** standoff projection conditioned on target elevation $\Delta z$.
* **Lock-free GPU telemetry buffer** and rolling variance stationarity gating.

---

### Tier 2: Neo4j LPG Graph Inspection & Web Visualizer

#### 1. CLI Graph Inspector:

Inspect the synced scene graph, containment hierarchy, and RDF 1.2 reified factor nodes:

```bash
# List all environments in Neo4j
docker exec isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/inspect_lpg.py --list

# Inspect reified relations, anchors, headroom, and entropy for a specific environment
docker exec isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/inspect_lpg.py \
  --env_name test_g1_reified_factor_graph
```

#### 2. Interactive Neo4j Web Browser:

Open your browser at [http://localhost:7475](http://localhost:7475) (or `http://localhost:7474`) with username `neo4j` and password `isaaclab_arena_password`.

**Visualizer Cypher Query**:
```cypher
MATCH (e:EnvironmentGraph)-[:HAS_REIFIER]->(rf:ReifiedRelation)
MATCH (rf)-[:REIFIES_SUBJECT]->(s), (rf)-[:REIFIES_OBJECT]->(t)
RETURN e, rf, s, t
```

---

### Tier 3: End-to-End LLM Prompt Generation

Generate an environment specification from natural language with live LLM active inference, grounding, and Neo4j sync:

Must export the key

```bash
export GEMINI_API_KEY="Magical Key here"
export NV_API_KEY="$GEMINI_API_KEY"
```


```bash
docker exec -it isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --api_key "$NV_API_KEY" \
  --model "gemini-3.6-flash" \
  --prompt "Unitree G1 humanoid pick up brown box from the wireshelving in galileo room and place it into the blue sorting bin" \
  --out_dir /workspaces/isaaclab_arena/generated_envs/g1_box_pnp
```

using open router

```bash
export OPENROUTER_API_KEY="Magical Key here"
export OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
export OPENAI_MODEL="anthropic/claude-3.7-sonnet"   # or "google/gemini-2.5-flash", "openai/gpt-4o"
```

```bash
docker exec -it \
  -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  -e OPENROUTER_BASE_URL="https://openrouter.ai/api/v1" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --api_key "$OPENROUTER_API_KEY" \
  --base_url "https://openrouter.ai/api/v1" \
  --model "google/gemini-3.7-flash" \
  --prompt "Unitree G1 humanoid pick up brown box from the wireshelving in galileo room and place it into the blue sorting bin" \
  --out_dir /workspaces/isaaclab_arena/generated_envs/g1_box_pnp
```      


---

### Tier 4: Interactive 3D Physics Simulation & Zero-Action Policy Rollouts

#### 1. Interactive 3D Physics Viewport (`--viz kit`):

First enable X11 access on the host:

```bash
xhost +local:root
```

Then launch Isaac Sim with the GUI viewport:

```bash
docker exec -it \
  -e DISPLAY="$DISPLAY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode build \
  --viz kit \
  --num_envs 1 \
  --num_steps 1200 \
  --enable_cameras \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/g1_box_pnp/pick_brown_box_from_wireshelving_into_bin.yaml
```

#### 2. Closed-Loop Physics Settle & W3C PROV-O Telemetry Export:

Run the zero-action gravity settling evaluation and verify `eval_telemetry.ttl` export:

```bash
docker exec -it isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --policy_type isaaclab_arena.policy.zero_action_policy.ZeroActionPolicy \
  --num_steps 300 \
  --num_envs 1 \
  --enable_cameras \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/g1_box_pnp/pick_brown_box_from_wireshelving_into_bin.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/g1_pnp_test
```
