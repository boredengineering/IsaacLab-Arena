---
name: arena-session-startup
description: Bring up and query Arena's knowledge systems before proposing or running any experiment — the policy capability graph, the Neo4j graph-RAG experience memory, and the cost-0.05 preflight oracles. Use at the start of any debugging, evaluation, training or diagnosis task on a policy or environment, and before recommending a measurement.
---

# Arena session startup

Arena carries two knowledge systems that rank diagnostics and hold prior outcomes. **Both were
ignored for an entire session (2026-09-06/07), which cost ~4 GPU-hours and three 20-episode
evaluations to re-establish results already recorded in them.** Query them first.

## 1. Capability graph — always available, no deps

Pure Python: no torch, no GPU, no simulator, no database. There is never a reason not to run this.

```bash
python - <<'PY'
from isaaclab_arena.agentic_environment_generation import policy_capability_graph as g
caps  = g.DiagnosticCapabilities(has_policy_weights=True, has_rollout_artifacts=True,
                                 has_gpu=True, has_reference_dataset=True)
state = g.PolicyDiagnosticState()      # pass applied_techniques=[...] as they accumulate
for t in g.plan_diagnostic_sequence(state, caps, max_techniques=5):
    print(f"{t.technique_id:38s} cost={t.cost:<5} discriminates={t.discriminates}")
PY
```

`select_next_diagnostic` ranks by **information gain per unit cost**. The cheap tier is 0.05:

| technique | rollout? | GPU? | discriminates |
| :--- | :--- | :--- | :--- |
| `pre_flight_geometry_oracle` | no | no | `kinematic_unreachable`, `spawn_interpenetration`, `vision_geometry_ood` |
| `depth_fingerprint_preflight` | no | no | `vision_geometry_ood`, `vertical_reach_ood` |
| `success_progress_consistency_check` | yes | no | `harness_false_success`, `horizon_truncation` |
| `stale_frame_assertion` | yes | no | `harness_stale_observation` |

`reference_scene_control_run` costs **0.7** -- fourteen times the cheap tier. Run the cheap four
first. Registries also carry remediations with `arena:invalidatedBy`, so a fix that would break a
stated invariant is representable and permanently ranked last rather than silently chosen.

`KinematicManifold` records which regions of reach space a corpus covers. **A manifold mismatch is
categorical: no policy-config patch closes it.** Check it before proposing any method work.

## 2. Graph-RAG experience memory — needs Neo4j, on a non-default port

Neo4j-backed, ranked by measured evaluation outcome. As of 2026-09-07 it holds **85
EvaluationRun nodes, 653 episodes**, 25 `EnvironmentGraph` and 4 `Policy` nodes.

```bash
docker start neo4j-arena          # often Exited; check `docker ps -a`
# It publishes 7475/7689, NOT the defaults -- 7474/7687 are held by other processes here.
docker exec isaaclab_arena-latest bash -lc \
  'cd /workspaces/isaaclab_arena && NEO4J_URI=bolt://localhost:7689 /isaac-sim/python.sh -c "
from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver
d=get_neo4j_driver()
with d.session() as s:
    for r in s.run(\"MATCH (n) UNWIND labels(n) AS l RETURN l, count(*) AS c ORDER BY c DESC\"):
        print(r[\"l\"], r[\"c\"])
d.close()"'
```

Query from `isaaclab_arena-latest` (host-networked, has `neo4j` and `pydantic`); the VS Code
devcontainer has neither.

**Pair every rate with its episode count.** `graph_rag.py`'s own comment warns that independent
maxima "would pair the best rate with an unrelated run's episode count and report, say, '1.0 over
4 episodes' when the 1.0 came from a single-episode run." The 1.0s in this database are mostly
`num_episodes: 1` -- very likely `harness_false_success`.

## 3. Close the loop

The evidence loop has been observed **open at both ends**: runs write `rerender_summary.json`
while the self-healing path reads `eval_telemetry.ttl`, so no measurement can correct a prior.
After any evaluation, write outcomes back via `policy_diagnostics_sync.py` and
`lpg_neo4j_sync.py`. An unrecorded run is a run the next session will repeat.

## Checklist

1. `plan_diagnostic_sequence` -- what is cheapest and most informative *now*?
2. Run the no-rollout preflights (`pre_flight_geometry_oracle`, `depth_fingerprint_preflight`).
3. Start Neo4j; ask what the recorded history already says about this policy/environment.
4. Only then propose training or a method change.
5. Write results back.

## Related modules

`spatial_geometric_oracle.py` (implements the geometry oracle), `depth_spatial_auditor.py`,
`policy_activation_probe.py`, `eval_self_healing.py`, `corpus_embedding_bank.py`,
`graph_rag.py`, `lpg_neo4j_sync.py`, `policy_diagnostics_sync.py`, `rdf_lowering.py`,
`rdf_validation.py`.
