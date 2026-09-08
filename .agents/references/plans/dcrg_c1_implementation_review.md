# DCRG C1 implementation review

Status: historical pre-implementation audit, not a claim of current defects or C1 success.

Current architecture: `docs/pages/concepts/dcrg.rst`. Executable workflow and measured
implementation pilot: `docs/pages/example_workflows/agentic_env_gen/dcrg.rst`.

Scope: `g1_tabletop_apple_to_plate`, scenario C1 in `agentic_env_generation/env_gen_test.md`, and `agentic_env_generation/dcrg_active_inference_paradigm_shift.md`.

## Verified in this review

- Started the existing `isaaclab_arena-latest`, `gr00t-server`, and `neo4j-arena` containers without recreating them.
- Arena imports and a CUDA tensor operation succeeded as the non-root `ubuntu` user inside the simulation container.
- GR00T responded to `PolicyClient.ping()` on 127.0.0.1:5561 and returned video/state/action/language modality configuration. Its configured model is `/models/isaaclab_arena/static_apple_tutorial/geometry_arms/baseline`; do not label it as another checkpoint without provenance verification.
- Neo4j connectivity and read-only queries succeeded on bolt://localhost:7688; HTTP discovery works on port 7475.
- Graph counts at inspection: 103 EvaluationRun nodes, 12 FEEDBACK_MUTATION relationships, one EVOLVES_TO relationship, no PROPOSES_RELAXATION relationship returned by the targeted relationship query.
- The dedicated v32-v35 feedback run nodes have lift rates but null success_rate and num_episodes, while timestamp-based evaluation nodes separately carry success and episode count. These are incomplete, split evidence records.
- `test_spatial_factor_graph.py` and `test_reach_tracer.py`: 12 passed. Pytest reported a cache-directory permission warning; no permissions were changed.
- No new simulation rollout was performed. The simulator container's inherited Docker healthcheck searches for a Kit AppReady log, while its current command is sleep infinity; container startup is not simulation readiness.

## Blocking implementation findings

### 1. Wrong coordinate priors still execute

`spatial_geometric_oracle.py:421` adds 0.75 to low-valued humanoid root Z. The depth preflight also substitutes 0.72 at line 201. This contradicts the measured G1 root-is-pelvis correction in the session memory.

Executed preflight on v32 and v35 reproduces false-height reasoning: pelvis is reported at approximately 0.75 while these specs declare approximately zero. Do not allow this oracle to drive remediation until frame contracts are repaired and tested against measured artifacts.

### 2. Relaxation can solve a different scene

`relax_spec_active_inference` constructs its background variable at a synthetic origin, ignores is_anchor constraints, optimizes the robot and objects, and only constructs support factors for ordinary `on` relations. C1 v32/v35 use anchored objects; v35 also has reified PLACED_ON relations that this path does not lower into support factors.

A no-feedback, zero-temperature in-memory probe of v32 returned converged=True while changing robot XYZ from [-0.46, 0.0, 0.0007] to [-0.5893, -0.0948, -0.0012], apple XYZ from [-0.173, 0.19, 0.0975] to [-0.0665, 0.2965, 0.0975], and plate XYZ from [-0.173, -0.02, 0.078] to [-0.0377, -0.134, 0.078]. Saved specs and the database were not mutated by this probe.

Require an explicit intervention allowlist, bounded trust region, physical support constraints, preserved orientations, and copy-on-write proposals. No feedback must not silently imply a large scene rewrite. Never promote an infeasible proposal.

### 3. Solver convergence is not trustworthy

A fixed variable at Z=1 with a ground factor at Z=0 returned converged=True, total_energy=0, factor energy=300, and no conflicts. Both deterministic and stochastic no-optimizable-variable branches share this problem.

The stochastic implementation adds noise to gradients passed through Adam. This is not the Langevin position update displayed in the plan. It also reports best poses alongside last-iteration factor energies. The code optimizes point poses, not the variational distributions or Bethe beliefs claimed by the plan.

Either implement a mathematically specified seeded sampler with correct updates, or name the current method noisy constrained optimization. Validate finite inputs, sigma, bounds, fixed variables, objective/pose consistency and reproducibility. Stochastic trajectories need not have monotonically decreasing energy.

### 4. The production feedback loop is not wired

Searches of core and example production Python found definitions but no callers for sync_recurrent_feedback_to_neo4j or relax_spec_active_inference. Graph-RAG does not implement the proposed EVOLVES_TO traversal. Existing edges do not establish automated rollout-to-proposal execution.

Add one bounded orchestration path: exact version -> rollout -> validated evidence -> targeted feedback -> proposal -> validation -> candidate rollout -> accept/reject -> durable lineage. Read back writes, record failures, support resume, and enforce iteration/GPU budgets.

### 5. Feedback loses identity and weakens scoring

The recurrent trace writer groups by the first environment's episode and reads index zero from batched arrays. It computes lift rate from peak height alone rather than the sustained-lift gate, and broadcasts identical deltas to every reifier in the environment. Dedicated feedback IDs can create incomplete evaluation nodes. Generic contact_force is not documented here as a verified hand-apple contact channel.

Use a canonical record keyed by run, immutable environment version, policy identity, seed, env_id, episode, body frame, and target relation. Separate task success, sustained lift, peak excursion, and specific contact channels. Preserve counts, uncertainty, source paths and missingness. Never turn missing evidence into zero force or a confident mutation.

## Correct the plan's premise and scope

- Database cycles are not sufficient for learning, nor necessary for closed-loop execution: a controller can operate over an acyclic, time-unrolled provenance history. Keep immutable lineage separate from feedback dependencies.
- A typed deterministic schema does not prevent continuous optimization. Demonstrate the benefit of stochastic search against a deterministic bounded baseline rather than assuming it.
- A measured hand-minus-object residual is not automatically the correct object displacement. The policy responds to changed images, so candidate changes require local response measurements and re-evaluation.
- Retire the v35 table-raising prescription: the later checkpoint records v35 as a regression. Use v32 as a candidate reference to reproduce, not as a universally optimal point.
- Defer cross-object "suprema" work. The stated transfer probabilities and >80% success predictions are not calibrated C1 evidence. A Mahalanobis similarity is not automatically a probability of task success.
- Reconcile scenario semantics: C1 asks for the right arm, but v32 traces pin left_hand_middle_1_link. Decide whether side is binding before counting a completion as C1 success.

## Proposed implementation order and gates

1. Freeze the C1 contract: assets, permitted hand, checkpoint identity, nominal geometry, physics, success predicate, placement seeds and inference seeds. Preserve friction and success thresholds. Separate environment-only transfer from policy/controller adaptation.
2. Add failing regression tests for the reproduced coordinate, anchor and convergence defects; repair these before enabling automatic mutation. Run both numerical and real-spec tests.
3. Repair evidence identity and aggregation; consume honest episode predicates and phase-specific, fixed-frame reach measurements. Join existing split run records only with verified artifact provenance.
4. Implement a bounded, resumable feedback orchestrator with explicit proposal acceptance/rejection and read-back-verified Neo4j lineage. Database outage must be visible; simulations may still finish with durable local evidence awaiting sync.
5. Reproduce v32 on the pinned server with fresh observations and settled geometry. First run diagnostic episodes, then compare controlled candidates with matched seeds. Rank grasp, sustained lift, transport and placement separately.
6. Estimate the local response to permitted small changes before trusting residual-directed updates. Keep table/robot/camera fixed initially. Test deterministic bounded candidates against seeded stochastic search. Do not move a receptacle to manufacture a pass.
7. Promote only a held-out-seed verified pick-and-place. Minimum milestone: genuine completion under the frozen success gate on at least two independent seeds, accompanied by episode counts and video/trace evidence. Robustness requires a separately agreed larger held-out evaluation, not just two lucky trials.
8. If permitted environment changes plateau, report that limit. Consider bounded controller residuals or target demonstrations as a distinct intervention class, not hidden continuation of environment-only transfer.

## Testing additions

- Frame invariance and measured-root regression.
- Anchors and orientations preserved; support geometry enforced even with reified relations.
- Infeasible fixed graphs rejected; seed reproducibility; no factors/no free variables; finite-value checks.
- Multi-environment asynchronous resets; missing hand frame; empty traces; transient lift versus sustained lift; no invalid stage promotion.
- Feedback targets the intended relation and exact version; idempotent writes; missing parent rejected; graph read-back verifies effect.
- End-to-end two-iteration test proves that recorded evidence changes the next permitted proposal and records rejection when the candidate regresses.
- Simulator acceptance checks actual placement, not low surrogate energy, contact-force maxima or graph edge counts.
