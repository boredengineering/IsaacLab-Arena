Running a bounded DCRG experiment
============================================================

See :doc:`../../concepts/dcrg` for architecture and data contracts. This runbook
covers the executable workflow, not the historical research proposal.

Prerequisites
-------------

Run Arena package code inside the clone's simulation container, as a non-root
user. Discover the container from its repository mount rather than assuming its
name. The local workflow needs the simulator, the matching policy server, and
Neo4j; the editor/agent container is an orchestrator, not the simulator.

Before a rollout:

* Confirm the policy server's actual model path and modality configuration.
  ``checkpoint_uri`` in a client YAML is not proof of what the server loaded.
* Confirm the actual Bolt port. This development deployment uses 7688 and HTTP
  7475; other deployments may use the defaults.
* Run the capability-graph preflights and inspect existing evidence before
  repeating experiments.
* Pin the required arm/hand contract. ``c1_existing_left_hand_baseline`` below is
  explicitly not proof of the original catalog's right-arm C1 request.

Non-root cache pitfalls
^^^^^^^^^^^^^^^^^^^^^^^

An existing root-run container can contain unreadable cached public USD files.
The failure can misleadingly say that the apple has no rigid body even though
the source USD has one. Do not repair that by modifying asset physics.

For the inspected container, ``/isaac-sim`` is group-readable by GID 1234; executing
as ``ubuntu:1234`` permits extension discovery without running as root. Discover
these IDs and permissions for another container rather than copying them blindly.
Use a user-owned temporary asset cache and writable Kit portable root. If the
Omniverse Hub fails to initialize, its documented per-process
``OMNICLIENT_HUB_MODE=disabled`` setting avoids using that cache service.

.. code-block:: bash

   # Inside the simulation container, as its non-root development user.
   mkdir -p /tmp/arena-dcrg-assets /tmp/arena-dcrg-kit
   export TMPDIR=/tmp/arena-dcrg-assets
   export OMNICLIENT_HUB_MODE=disabled

HDF5 recorder output now follows the evaluation run directory, alongside episode
JSON and camera videos, rather than a shared root-owned ``/tmp/isaaclab/logs``.

Launch
------

The example below uses the checkpoint actually served in the local pilot.
Substitute the verified server identity if a different checkpoint is loaded.
The run directory must be dedicated to this experiment; models and raw evaluation
artifacts should remain outside Git.

.. code-block:: bash

   /isaac-sim/python.sh \
     isaaclab_arena_examples/agentic_environment_generation/dcrg_runner.py \
     --base_spec generated_envs/g1_tabletop_apple_to_plate/v32/g1_tabletop_apple_to_plate.yaml \
     --policy_config generated_envs/g1_tabletop_apple_to_plate/v32/policy_config.yaml \
     --policy_identity /models/isaaclab_arena/static_apple_tutorial/geometry_arms/baseline \
     --scenario_contract c1_existing_left_hand_baseline \
     --run_dir /eval/isaaclab_arena/dcrg_c1/run_001 \
     --hand_body left_hand_middle_1_link \
     --remote_port 5561 \
     --neo4j_uri bolt://localhost:7688 \
     --seeds 42 7 \
     --episodes_per_seed 2 \
     --max_candidates 1 \
     --max_displacement_m 0.01 \
     --kit_args '--portable --portable-root /tmp/arena-dcrg-kit'

``--max_candidates`` excludes the baseline. Each evaluated spec runs the requested
number of completed episodes on every seed, sequentially. ``--timeout_s`` bounds
each simulator process, including startup. The initial implementation permits
only bounded apple XY movement; changing physics, task thresholds, robot/camera
pose, plate pose, or object Z fails candidate validation.

The CLI uses deterministic bounded proposals (zero gradient-noise temperature)
for this initial comparison. The underlying numerical solver also supports seeded
noise, but it is not a calibrated stochastic inference method.

Evidence reuse and resume
-------------------------

``--reuse_baseline`` accepts one completed rollout directory per seed. It checks
raw spec and policy-config digests, hand frame, requested seed coverage, and
actual completed episode records before reuse. This is intended for explicitly
verified prior runs, not arbitrary files with a plausible success rate.
Checkpoint identity remains an operator-verified server contract; the remote API
does not expose a model digest or seed its diffusion process.

Re-running the **same command and contract** resumes the run. Completed evidence
and graph outbox events are reused rather than rerun. Changes to the contract
require a different run directory. An interrupted evaluation without a durable
evidence receipt is indeterminate: inspect its files and recover evidence
explicitly instead of blindly retrying or fabricating a result.

Kit arguments are part of the frozen contract because they can change simulator
settings, not just cache paths. Older state files created before a required
contract field was recorded are not silently upgraded. Keep them as historical
evidence; use a new run directory after explicitly validating any reused artifacts.

Artifact layout
---------------

.. code-block:: text

   run_001/
       state.json                      contract, decisions, counters, sync status
       specs/<canonical-sha256>.yaml    immutable source/candidate snapshots
       evaluations/<sha256>/
           spec.yaml
           evidence.json               validated multi-seed receipt
           seed42/
               manifest.json           command, input digests, status/errors
               process.log
               reach.jsonl
               <timestamp>/
                   episode_results_rank0.jsonl
                   *.hdf5
                   robot-cam-*.mp4
           seed7/...

A reused baseline retains references to its original artifact directories rather
than pretending that new episodes were generated. Preserve those source directories
for audit and resume. Raw traces and model/dataset files do not belong in commits.

Graph inspection
----------------

The CLI registers immutable versions, per-seed evaluation records, an aggregate
batch record, exact-relation feedback, and proposal/decision provenance. Aggregate
batch records refer to the same underlying episodes as the per-seed records:
**do not sum both as independent observations**.

The graph stores the full source spec as canonical JSON and materializes the
target/support endpoints needed for feedback. This is not a duplicate full scene
compiler. The existing ``GraphRAGRetriever.retrieve_refinement_history`` reads
bounded evolutionary paths and the exact deciding run's rates/counts. Accepted
trials are returned by default; use ``accepted_only=False`` to inspect rejected
trials. Neither rejected nor untested candidates become successful priors.

.. code-block:: python

   from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever
   from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver

   driver = get_neo4j_driver(uri="bolt://localhost:7688")
   try:
       history = GraphRAGRetriever(driver).retrieve_refinement_history(
           "g1_tabletop_apple_to_plate",
           "/models/isaaclab_arena/static_apple_tutorial/geometry_arms/baseline",
           accepted_only=False,
       )
   finally:
       driver.close()

Interpreting outcomes
------------------------------------------------------------

* ``success``: the frozen task gate reported a completed success on each requested
  distinct seed. This is a trial milestone, not statistical robustness.
* ``exhausted``: the candidate/iteration budget ended without that milestone.
* ``no_proposal``: no distinct, permitted proposal was available.
* ``failed``: infrastructure, evidence validation, or synchronization failed.
  The exception propagates and the state records the failure.

Termination during a neutral settle is a rejected rollout, not an extra policy
episode. The runner must not start another settle after the final requested
episode. The evidence adapter rejects mismatched counts rather than truncating
files until they look correct.

Local pilot result
------------------

The implementation pilot on 2026-09-07 used two episodes each on seeds 42 and 7:

.. list-table::
   :header-rows: 1

   * - Spec
     - Completed episodes
     - Sustained lifts
     - Task successes
   * - v32 baseline (``3442a766d74fdfe1...``)
     - 4
     - 0
     - 0
   * - Bounded candidate (``826df6ebab6011c1...``)
     - 4
     - 0
     - 0

The controller rejected the candidate, retained the baseline, and returned
``exhausted``. Neo4j decision/history read-back agreed, and repeating the same
command left the state file digest unchanged without another rollout.
That pilot resume check preceded the additional Kit-argument contract hardening;
its archived state is preserved rather than rewritten to claim missing provenance.
The actual evidence is under
``/eval/isaaclab_arena/dcrg_c1/20260907/closed_loop/`` in that development workspace;
it is not shipped with the repository.

This verifies the execution and evidence loop, **not C1 success**. The earlier
2 cm pilot that recorded unexpected settle episodes is excluded from this table.
It remains a failed diagnostic artifact, not a scored comparison.

Controller-assistance comparison
------------------------------------------------------------

The separate controller experiment uses the same v32 scene and the step-pinned
``geometry_arms/align/checkpoint-5000`` policy. This checkpoint uses depth-feature
supervision during training, not a runtime depth observation. Assistance accesses
simulator object positions and must be labelled ``privileged_state_diagnostic``.
It is not a claim of vision-only policy transfer.

Select ``isaaclab_arena_gr00t.policy.gr00t_assisted_policy.Gr00tAssistedPolicy``
through the existing policy runner and provide ``--assistance_config_path`` and
``--assistance_trace_path``. The config is JSON, requiring explicit
``privileged_state: true``. Supported modes are ``observe``, ``offset``, ``gate``
and ``combined``. ``observe`` records the same diagnostics without changing any
action. The low-level ``dcrg.evaluation.run_rollout`` accepts
``assistance_config_path`` and fingerprints it in the rollout manifest; the
environment-only ``dcrg_runner.py`` does not perform controller-parameter search.

Register the exact environment with ``register_environment_version``, the
controller contract with ``register_controller_variant``, completed evidence with
``register_evaluation_run`` using the returned composite policy identity, then
link it with ``attach_controller_evaluation``. Inspect records through
``GraphRAGRetriever.retrieve_controller_trials`` rather than the XY lineage API.
The comparison pins checkpoint weight digests, base policy config, scene, and
hand/frame. Preserve the full controller/source contract as an evaluation artifact.

The bounded 2026-09-08 batch completed these trials:

.. list-table::
   :header-rows: 1

   * - Controller
     - Seed
     - Episodes
     - Height-dwell events
     - Placements
   * - Observe-only
     - 42
     - 2
     - 0
     - 0
   * - 0.01 m downward residual
     - 42
     - 2
     - 0
     - 0
   * - 0.4 s maximum finger gate
     - 42
     - 2
     - 1
     - 0
   * - Residual + gate
     - 42
     - 2
     - 0
     - 0
   * - Observe-only
     - 7
     - 2
     - 0
     - 0
   * - 0.4 s maximum finger gate
     - 7
     - 2
     - 0
     - 0

No placement succeeded in the twelve completed episodes. The one height-dwell
event did not establish retained transport: video shows the apple slipping/rolling
away while the hand continues without it. All gate episodes released on timeout,
not geometric readiness. Do not interpret these results as validated grasp-centre
calibration, reliable grasp improvement, or proof of Graph-RAG's efficacy. The
remote policy's diffusion process remains unseeded.

The scene, physics, six-second task horizon, and success predicates were unchanged.
One interrupted setup smoke produced zero episodes and is excluded from scoring.
No candidate was promoted. Raw artifacts and reproducible trial harnesses are in
``/eval/isaaclab_arena/dcrg_c1_assistance/20260908/`` in the development workspace.
The graph experiment is ``c1_align_assistance_20260908``. Exact read-back verified
six trials, four controller variants, all registered artifact/source hashes, an
unchanged identical retry, and rejection of conflicting controller attribution.
