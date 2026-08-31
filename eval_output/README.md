# Policy Evaluation & Rollout Telemetry (`eval_output/`)

This directory is IsaacLab-Arena's central repository for **simulation evaluation runs, policy rollouts, interactive HTML dashboards, recorded videos, and W3C PROV-O semantic telemetry**.

---

## 1. Directory Structure & Naming Conventions

Each evaluation job creates a timestamped run directory (`YYYY-MM-DD_HH-MM-SS`) under its designated task or experiment folder:

```text
eval_output/
├── README.md                             # This documentation
├── <experiment_or_env_name>/             # e.g., droid_apple_test, droid_mustard_test, g1_pnp_test
│   └── 2026-08-31_15-29-21/              # Timestamped rollout run directory
│       ├── index.html                    # Interactive HTML evaluation dashboard & video viewer
│       ├── episode_results_rank0.jsonl   # Per-episode structured metrics and termination records
│       ├── eval_telemetry.ttl            # W3C PROV-O semantic lineage & physical settling scores
│       └── videos/                       # (Optional) Multi-camera MP4 video recordings
│           ├── env0_ep0_wrist_camera.mp4
│           └── env0_ep0_head_camera.mp4
```

---

## 2. Core Artifacts Generated per Run

| Artifact | File Format | Source Module | Purpose |
| :--- | :--- | :--- | :--- |
| **Interactive Dashboard** | `index.html` | [`isaaclab_arena/visualization/report.py`](../isaaclab_arena/visualization/report.py) | Self-contained visual report with summary metrics, embedded video players, and episode inspector. |
| **Raw Episode Records** | `episode_results_rank<N>.jsonl` | [`isaaclab_arena/metrics/episode_recorder.py`](../isaaclab_arena/metrics/episode_recorder.py) | JSON Lines logs of per-episode success, duration, termination reason, and seed parameters across MPI/GPU ranks. |
| **Semantic Telemetry** | `eval_telemetry.ttl` | [`isaaclab_arena/evaluation/telemetry_to_prov.py`](../isaaclab_arena/evaluation/telemetry_to_prov.py) | Machine-readable RDF Turtle graph linking simulation metrics to the scene graph and policy in W3C PROV-O format. |
| **Rollout Videos** | `videos/*.mp4` | [`isaaclab_arena/video/video_recording.py`](../isaaclab_arena/video/video_recording.py) | Synchronized camera streams (wrist, head, third-person) recorded during the policy rollout. |

---

## 3. How to Generate Evaluation Runs

### A. Zero-Action Physics Settling & Object Stationarity Test
Run a 300-step zero-action evaluation to verify that objects spawn without collision and settle stably on support surfaces:

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

### B. Closed-Loop Neural Policy Evaluation (GR00T / OpenPI / Custom)
Evaluate a trained checkpoint across 50 episodes with video recording:

```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --policy_type isaaclab_arena.policy.gr00t_policy.GR00TPolicy \
  --num_episodes 50 \
  --num_envs 4 \
  --record_camera_video \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_apple_bowl/droid_pick_apple_to_bowl.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/droid_apple_gr00t_eval
```

---

## 4. Serving and Visualizing the HTML Dashboard

### Option A: Local Python Web Server (Host Browser)
Serve all evaluation runs across `eval_output/` on port `8080`:

```bash
python3 -m http.server 8080 --directory /workspaces/IsaacLab-Arena/eval_output/
```
Open **[http://localhost:8080](http://localhost:8080)** in your browser and click any timestamped directory to view its `index.html`.

### Option B: Automatic Serving via Policy Runner
Pass `--serve_evaluation_report` to automatically launch an embedded HTTP server upon simulation completion:

```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --policy_type isaaclab_arena.policy.zero_action_policy.ZeroActionPolicy \
  --num_steps 300 \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_mustard_bin/droid_pick_mustard_into_bin.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/droid_mustard_test \
  --serve_evaluation_report \
  --evaluation_report_port 8000
```
Open **[http://localhost:8000](http://localhost:8000)** to view the report immediately.

---

## 5. Semantic Telemetry & Neo4j Feedback (`eval_telemetry.ttl`)

`eval_telemetry.ttl` records physical simulation outcomes in machine-readable **W3C PROV-O RDF Turtle** format, linking evaluation results directly to the scene graph and policy.

### A. View `eval_telemetry.ttl` Locally
You can inspect the raw RDF Turtle graph for any run directly from the command line:

```bash
cat eval_output/droid_mustard_test/2026-08-29_21-47-18/eval_telemetry.ttl
```

**Sample TTL Content**:
```turtle
@prefix : <https://isaac-sim.github.io/arena/instances/> .
@prefix arena: <https://isaac-sim.github.io/arena/schema#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:eval_run_1788040065 a prov:Entity, arena:EvaluationRun ;
    prov:wasGeneratedBy :activity_eval_run_1788040065 ;
    arena:evaluatedGraph :droid_pick_mustard_to_bin ;
    arena:metric_num_episodes 50 ;
    arena:metric_success_rate "0.94"^^xsd:float ;
    arena:metric_object_moved_rate "0.98"^^xsd:float ;
    arena:metricsPayload "{\"num_episodes\": 50, \"success_rate\": 0.94, \"object_moved_rate\": 0.98}"^^xsd:string .

:activity_eval_run_1788040065 a prov:Activity ;
    prov:endedAtTime "2026-08-29T21:47:45.112928+00:00"^^xsd:dateTime ;
    prov:used :droid_pick_mustard_to_bin, :policy_GR00TPolicy .
```

---

### B. View & Query Telemetry in the Neo4j Web Visualizer

All evaluation runs are automatically synced into Neo4j as `(:EvaluationRun)` nodes connected to their respective `(:EnvironmentGraph)` and `(:Policy)` nodes.

1. Open your browser at: **[http://localhost:7475](http://localhost:7475)**
   * **Username**: `neo4j`
   * **Password**: `isaaclab_arena_password`

2. Copy and paste any of the following Cypher queries into the top query bar:

#### 1. Visual Scene Graph with Evaluation Runs & Policies
Visualize all evaluation runs, the environments they tested, and the policies evaluated:
```cypher
MATCH (ev:EvaluationRun)
OPTIONAL MATCH (ev)-[r1:EVALUATED_GRAPH]->(e:EnvironmentGraph)
OPTIONAL MATCH (ev)-[r2:USED_POLICY]->(p:Policy)
RETURN ev, r1, e, r2, p
```

#### 2. Policy Performance Leaderboard
Generate a tabular leaderboard comparing success rates, episode counts, and completion timestamps across policies:
```cypher
MATCH (ev:EvaluationRun)-[:EVALUATED_GRAPH]->(e:EnvironmentGraph)
OPTIONAL MATCH (ev)-[:USED_POLICY]->(p:Policy)
RETURN e.name AS Environment, 
       p.name AS Policy, 
       ev.success_rate AS SuccessRate, 
       ev.num_episodes AS Episodes, 
       ev.ended_at AS CompletedAt
ORDER BY ev.ended_at DESC
```

#### 3. Deep Trace: Evaluation Outcome Down to Reified Factor Nodes
Trace from an evaluation run all the way down to the entity interaction factors (surface anchors, headroom, and kinematic reach manifolds):
```cypher
MATCH (ev:EvaluationRun)-[:EVALUATED_GRAPH]->(e:EnvironmentGraph)
OPTIONAL MATCH (e)-[:HAS_REIFIER]->(rf:ReifiedRelation)
OPTIONAL MATCH (rf)-[:REIFIES_SUBJECT]->(s)
OPTIONAL MATCH (rf)-[:REIFIES_OBJECT]->(t)
RETURN ev, e, rf, s, t
```

---

### C. Active Inference Self-Healing Feedback Loop

```text
  ┌─────────────────────────────────────────────────────────────┐
  │                    Active Inference Loop                    │
  │                                                             │
  │   1. Isaac Sim PhysX Rollout                                │
  │        ↓                                                    │
  │   2. Vectorized Telemetry Buffer (Jitter & Drift Tracking)  │
  │        ↓                                                    │
  │   3. telemetry_to_prov.py (Attribution to Reifier IDs)      │
  │        ↓                                                    │
  │   4. Neo4j LPG Graph (:EvaluationRun -> :ReifiedRelation)   │
  │        ↓                                                    │
  │   5. EnvironmentGenerationAgent (Prior Error Feedback)      │
  │        ↓                                                    │
  │   6. Auto-Healed Environment Spec (YAML)                    │
  └─────────────────────────────────────────────────────────────┘
```

1. **Statistical Stationarity Evaluator**: During the rollout, GPU tensor ring buffers track contact chattering and object drift ($>3\,\text{cm}$).
2. **Reifier Fault Attribution**: If settling fails or objects slip off surfaces, `attribute_simulation_telemetry_to_reifiers()` maps the fault to the specific reifier edge (e.g., `<< :reifier_apple_table | :apple :PLACED_ON :table >>`).
3. **Active Bayesian Prior Update**: On the next environment generation iteration, the agent queries Neo4j for prior failure history on that asset/relation pair and automatically adjusts surface friction, nominal placement heights, or standoff distances.

