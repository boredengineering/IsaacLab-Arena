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

Discover the database and its published Bolt port from Docker inspection; do not
trust historical port numbers or node counts. Set `NEO4J_URI` to that verified
endpoint and query through the simulation container's non-root runtime. The
editor container is not the simulation runtime. See
`docs/pages/example_workflows/agentic_env_gen/dcrg.rst` for verified commands and
cache/permission prerequisites.

**Pair every rate with its episode count.** `graph_rag.py`'s own comment warns that independent
maxima "would pair the best rate with an unrelated run's episode count and report, say, '1.0 over
4 episodes' when the 1.0 came from a single-episode run." The 1.0s in this database are mostly
`num_episodes: 1` -- very likely `harness_false_success`.

## 3. Close the loop

### Discovering and selecting DCRG

For refinement or evaluation of an existing environment spec, read
`docs/pages/concepts/dcrg.rst` and
`docs/pages/example_workflows/agentic_env_gen/dcrg.rst`, then use the bounded CLI
`isaaclab_arena_examples/agentic_environment_generation/dcrg_runner.py`.
The implementation is under `isaaclab_arena/agentic_environment_generation/dcrg/`.

Before proposing another experiment, query
`GraphRAGRetriever.retrieve_refinement_history(source_env_name, policy_identity, accepted_only=False)`.
Inspect rejected trials for diagnostic work; use the default accepted-only filter
when looking for accepted refinements. Keep the exact deciding run's counts/rates.
An accepted lift improvement is not automatically a successful pick-and-place.

For same-scene controller assistance, also query
`GraphRAGRetriever.retrieve_controller_trials(source_env_name, checkpoint_identity, experiment_id=None)`.
These records use explicit controller/source/weight fingerprints and composite
policy identities; they are not XY environment proposals. Inspect the actual
controller config, privilege label, per-run counts, and video evidence before
repeating a trial. A height-dwell event can accompany a slip rather than retained
transport. Check whether a gate released on geometry or merely timed out.
See `.agents/references/quick_notes/c1_controller_assistance_results.md` and the
controller-assistance section of the DCRG runbook for the measured comparison.

Identify records by original scenario name, canonical spec SHA-256, exact policy
identity, evaluation ID, and target support reifier. `graph_identity` computes the
immutable graph name and version; do not guess these from `latest` or version-folder
names. Feedback must be fetched for that exact version/run/reifier and body frame.

This is explicit agent guidance and an executable CLI, not automatic LLM routing.
`EnvironmentGenerationAgent` still calls `retrieve_prior_subgraphs` for prompt
generation; it does not automatically call the DCRG history API. A coding agent
must deliberately choose refinement and invoke the documented workflow.

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
