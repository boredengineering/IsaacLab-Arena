# IsaacLab-Arena: Agentic Environment Generation & Neo4j LPG Cheat Sheet

Quick reference guide for launching containers, running test suites, syncing Labeled Property Graphs (LPG), inspecting scene graphs via CLI, running end-to-end LLM environment generation, and executing zero-action simulation rollouts in IsaacLab-Arena.

---

## 1. Docker Container Management

### Neo4j Graph Database Container
```bash
# Start existing Neo4j container
docker start neo4j-arena

# Create and start a fresh Neo4j container (if not already created)
docker run -d --name neo4j-arena \
  -p 7475:7474 -p 7688:7687 \
  -e NEO4J_AUTH=neo4j/isaaclab_arena_password \
  neo4j:5.26-community
```

### IsaacLab-Arena Container
```bash
# Start existing IsaacLab-Arena simulation container
docker start isaaclab_arena-latest

# Check container status
docker ps -a --filter "name=neo4j-arena|isaaclab_arena-latest"
```

---

## 2. Test Suite & Validation Commands

### Neo4j LPG Synchronization & Cypher Queries Only
```bash
docker exec isaaclab_arena-latest /isaac-sim/python.sh -m pytest \
  isaaclab_arena/tests/test_neo4j_lpg_sync.py -v
```

### Robot-Relative Multi-Camera Framing Tests
```bash
docker exec isaaclab_arena-latest /isaac-sim/python.sh -m pytest \
  isaaclab_arena/tests/test_robot_relative_camera.py -v
```

### Full Semantic & Graph Pipeline Test Suite
Runs W3C SHACL validation, RDF lowering, W3C PROV-O serialization, Neo4j LPG sync, and agent mock tests:
```bash
docker exec isaaclab_arena-latest /isaac-sim/python.sh -m pytest \
  isaaclab_arena/tests/test_rdf_validation.py \
  isaaclab_arena/tests/test_rdf_lowering.py \
  isaaclab_arena/tests/test_telemetry_to_prov.py \
  isaaclab_arena/tests/test_neo4j_lpg_sync.py \
  isaaclab_arena/tests/test_robot_relative_camera.py \
  isaaclab_arena/tests/test_environment_generation_agent.py -v
```

---

## 3. CLI Graph Inspection (`inspect_lpg.py`)

### List All Environments Synced in Neo4j
```bash
docker exec isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/inspect_lpg.py --list
```

### Inspect a Specific Environment Graph
Inspects node entities, labels, and spatial relation properties (`surface_anchor`, `nominal_height`, `clearance_radius`):
```bash
docker exec isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/inspect_lpg.py \
  --env_name test_g1_shelf_pnp_lpg
```

---

## 4. End-to-End LLM Generation Runner

Generate an environment specification from natural language, validate constraints, and sync to Neo4j:
```bash
docker exec -it isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --api_key "<YOUR_API_KEY>" \
  --base_url "https://generativelanguage.googleapis.com/v1beta/openai/" \
  --model "gemini-3.6-flash" \
  --prompt "Unitree G1 humanoid pick up brown box from the wireshelving in galileo room and place it into the blue sorting bin" \
  --out_dir /workspaces/isaaclab_arena/generated_envs/g1_box_pnp
```

### Key CLI Flags:
* `--mode resolve`: Validates relations, grounds prim paths, and syncs to Neo4j.
* `--mode preview`: Generates and prints JSON-LD / Pydantic graph specification.
* `--mode run`: Generates, compiles, and launches the interactive Isaac Sim physics viewport.

---

## 5. Simulation Verification & Zero-Action Policy Rollouts

### Step 3: Interactive 3D Simulation Verification (`--mode build --viz kit`)

Launch Isaac Sim with the interactive GUI on your host display (`num_steps=1200`). This physically validates:
* **Telescopic Placement**: The shelf spawns inside the Galileo room and the brown box rests securely on `shelf_tier_2`.
* **Robot Standoff**: The G1 humanoid spawns 0.85 m in front of the shelving unit facing the box.
* **Grounded Viewport Camera**: The camera centers directly on the robot/shelf interaction zone (no black screens).

```bash
# Allow local docker containers to connect to host X11 display
xhost +local:root
```

Run this inside the devcontainer

```bash
# Run interactive simulation
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

---

### Step 4: Closed-Loop Rollout & PROV-O Telemetry Export

Run the zero-action physics check and generate the W3C PROV-O telemetry file (`eval_telemetry.ttl`):

```bash
docker exec -it isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/g1_box_pnp/pick_brown_box_from_wireshelving_into_bin.yaml \
  --policy_type isaaclab_arena.policy.zero_action_policy.ZeroActionPolicy \
  --num_steps 200 \
  --num_envs 1 \
  --enable_cameras \
  --record_viewport_video \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/g1_pnp_test
```

---

## 6. Interactive Neo4j Web Browser

* **Web UI URL**: [http://localhost:7475](http://localhost:7475) (or `http://localhost:7474` if standard port)
* **Bolt URL**: `bolt://localhost:7688` (host) / `bolt://172.17.0.2:7687` (internal container)
* **Username**: `neo4j`
* **Password**: `isaaclab_arena_password`

### Useful Cypher Visualizer Queries

#### View Entire Environment Scene Graph
```cypher
MATCH (n)-[r]->(m) 
RETURN n, r, m
```

#### View Spatial Relations and Continuous Metric Properties
```cypher
MATCH (s)-[r:PLACED_ON|INSIDE|STANDS_NEAR]->(t)
RETURN s, r, t
```

#### Query Reachability from Unitree G1 to Pick & Place Targets
```cypher
MATCH (emb:Embodiment)-[:STANDS_NEAR]->(fixture:Fixture)<-[:PLACED_ON]-(target:RigidObject)
RETURN emb, fixture, target
```

#### Check Grounding & Floor Containment
```cypher
MATCH (e:EnvironmentGraph)-[:HAS_TERRAIN]->(terrain:Fixture)
MATCH (obj:RigidObject)-[:PLACED_ON]->(shelf:Fixture)
RETURN e, terrain, shelf, obj
```

---

## 7. Default Connection Settings & Environment Variables

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `NEO4J_URI` | `bolt://172.17.0.2:7687` (internal) / `bolt://localhost:7688` (host) | Bolt protocol connection endpoint |
| `NEO4J_USER` | `neo4j` | Database administrator username |
| `NEO4J_PASSWORD` | `isaaclab_arena_password` | Database administrator password |
