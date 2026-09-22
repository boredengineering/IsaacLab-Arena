Native capture and task-bound policy adapters
============================================

Scope
-----

These Plan 03 adapters extend the existing workflow service and Neo4j intent
ledger. They do not provide a second controller or a SQLite fallback. The installed
GraphQL launcher remains query-only: it must not be presented as a native ``run``
command. Native startup, policy service/checkpoint verification, and an operator's
execution authorization are separate composition requirements.

The isolated tests use CPU tensors, synthetic simulator/provider seams and a
disposable Neo4j database. They establish software contracts, not PhysX
calibration, successful manipulation, or live A2 acceptance. Retained native
producer payloads deliberately say ``native-unverified``.

Native mechanics
----------------

``workflow.native_realization.build_native_environment`` reuses
``ArenaEnvGraphSpec.to_arena_env`` and ``ArenaEnvBuilder.make_registered`` with
``ArenaEnvBuilderCfg``. It returns the gym wrapper; runtime state belongs to
``env.unwrapped``. Kit must already be initialized in the authorized child.
Required cameras must be enabled in both Kit and graph conversion. An explicit
false graph override conflicts with a camera-requiring profile; the candidate is
not silently rewritten.

By default, ``initialize_and_settle`` resets once, constructs a measured DROID
posture hold, and consumes the entire frozen settle allocation. Supplying
``initialized_observation`` explicitly skips that reset and uses the same hold,
charging and rejection logic for the caller's freshly reset cohort. The caller
owns observation freshness and reset identity; this seam does not attest them or
implement the policy prerequisite producer. For every selected subject,
the final consecutive window must satisfy unrounded linear speed strictly below
``1e-3 m/s`` and the selected angular-speed threshold. Equality, nonfinite or
missing measurements, termination and truncation reject settling. Every control
step is charged before execution. No physics parameter is tuned to force a pass.

DROID absolute arm commands are obtained by inverting the actual configured
position action terms in their selected joint ordering; a zero vector is not a
hold. The binary gripper retains the nearest configured open/closed endpoint;
an intermediate posture is not continuous-position control.

``workflow.native_capture.NativeCaptureSettings`` freezes runtime/capture profile
references, seeds, settings, subject/contact mappings, absolute window, criteria,
image transform and ceilings. Both references bind the same canonical settings
SHA. Its evaluator-v1 constants are explicitly pinned, not newly calibrated.
The current support predicate is filtered contact plus proximity, not generic
load-bearing certification.

``NativeCaptureProducer`` is invoked inside the released registered child. It
builds, settles and captures the same reset cohort, retains synchronized samples
and bounded evaluator PNGs, closes the environment, and returns an immutable
receipt. ``capture_trajectory`` accepts ``initial_observation``, ``step_offset``
and ``reset_policy`` so the post-settle window is never relabelled as reset step
zero. Legacy calls retain their reset behavior and result shape. Terminal-step
images remain unavailable rather than being replaced with autoreset images.

The selected RGB transform is evaluator-only; policy observations are not resized.
The current evidence format allows at most 16 frames and 128 KiB per PNG, with a
separate whole-payload ceiling. Literal contact-path correspondence and one
environment are required. Arbitrary templated contact expansion, depth capture,
other hold embodiments and effective placement calibration are not established.
Measured subjects currently bind spawnable graph objects through their effective
``instance_name`` and prim path. Swapped identities and runtime-name collisions
reject before construction. Background subassets and arbitrary object references
need a separate mapping adapter; a matching label alone is not evidence identity.

Owned split-stage integration
-----------------------------

V1 synthetic combined observation remains supported. V2 separately retains
capture and assessment intents, each with its own registration and cleanup.
Capture reserves realization/settle/capture steps but no model budget; assessment
reserves its own model allowance without charging capture again.

The required order is:

#. Reserve, claim, prepare, register and release capture.
#. Retain capture bytes; stop the exact owned child and acknowledge cleanup.
#. Release the shared GPU slot using the supervisor's exact cleanup witness.
#. Verify the immutable capture and atomically adopt it with the next assessment
   reservation.
#. Prepare assessment only now, using the digest-pinned retained capture.

The GPU flock uses the same explicitly supplied host-backed path as the renderer,
normally ``/eval/.arena-workbench-gpu.lock``. It is not the workflow-scope lease.
``NativeGpuLease`` never unlocks on an ordinary context-manager exit or on a
caller-provided cleanup boolean. Unknown cleanup blocks handoff; a warm legacy
renderer still holding the common lock remains contention.

``SplitScenePorts`` reopens exact observation/answer manifests and re-evaluates
numeric and visual evidence. Assessment never invokes capture. The owned adapter
routes numeric-only assessment to a numeric evaluator, not an idle model child.
``ForegroundSplitScenePorts`` reuses existing guarded model dispatch and scope
ownership. A native authorization callback is required separately from the
existing model grants; ``allow_runtime`` alone is not execution authority.

Permitted visibility repair receives the original/current candidate identities,
selected feedback, exact allowed XY paths, preserved fields, and an
original-centered admissible disk. The radius does not shrink by distance already
travelled. The existing full-candidate guard remains authoritative and fresh
capture is required after a repair. Z, task, physics and topology changes are not
permitted by this repair capability.

Policy evaluation
-----------------

``workflow.policy_contracts`` holds runtime-independent frozen policy/task pins,
completed episode records and aggregation. ``workflow.policy_evaluation`` bridges
those contracts to the existing ``rollout_policy`` and ``TaskBase`` methods.
Task success is supplied by the selected task evaluator, never inferred merely
from termination or a visual verdict.

The current policy criterion adapter supports one required completed-episode task
success-rate criterion: producer ``task-evaluator``, evaluator ``v1``, rubric
``completed episode task success rate``, frame ``episode``, subject ``task``,
and a ``ge`` limit in ``fraction`` units. Its window is ``0`` through the frozen
policy-step ceiling. The minimum successful episode count must equal the ceiling
of the requested fraction times the complete trial size. Arbitrary policy rubrics
and multiple independent policy obligations remain unsupported rather than being
silently mapped to the same success flag. One retained trial is limited to 512
episodes so writer-admitted receipts remain within the bounded readback format.

The managed runner accepts an initialized cohort and rechecks prerequisites after
every autoreset before another action. Deadline/pin guards run before inference
and again before advancing physics; time spent in inference or verification is
not free. The caller still owns a hard watchdog for hung native/network calls.
Direct rollout does not invoke the legacy CLI's graph synchronization, version
ledger or report server.

``policy_episode_records.decode_episode_records`` consumes the actual retained
Arena core episode JSONL bytes, exact recorder job name, observed initial episode
index, and prepared reset identities. It preserves the raw digest and denominator;
foreign seed/instruction/index, duplicate JSON fields, nonfinite values and
ambiguous reset identities are rejected. Empty or incomplete trials remain
unknown, not a zero-denominator success. This decoder is an integrity check, not
an independent attestation of the recorder or served checkpoint.

A request requiring policy evaluation must remain nonterminal after scene
prerequisites pass. Overall acceptance requires the frozen policy aggregation;
failure or incomplete coverage must not erase independently retained scene facts
or leave the workflow accepted. Scene-only requests retain their terminal path.
A supported task/embodiment adapter, verified served instance, immutable receipts
and owned policy execution are required before enabling that outcome in a launcher.

A2 reference acceptance
-----------------------

The reference instruction is:

    Grasp the yellow banana from the right side of the table and set it onto the
    white ceramic plate on the left.

It binds ``droid_abs_joint_pos``, ``banana_ycb_robolab`` and
``plate_large_vomp_robolab``. These identifiers belong to a profile, not a
coordinator branch. Freeze the selected checkpoint/configuration, serializer,
modalities, task definition, lift/dwell/destination predicates, seeds and budgets
before a separately authorized pilot. A peak lift or destination proximity alone
is not the complete PickAndPlace operational sequence. No live A2 success is
established by the synthetic fixtures.

Offline verification
--------------------

From the repository root, using the already admitted cached runtime and manifest::

    python3 scripts/run-functional-checks.py backend \
      isaaclab_arena/tests/test_trajectory_assessment.py \
      --runtime-image sha256:e20b3cc8258b793aaf1fe47c130f54e677fa9c0a6427991cfc1045b743162da5 \
      --provision-manifest outputs/workflow/plan03-implementation/graphql-dependency-probe/run/provision-manifest.json

Use the same pair for ``test_environment_workflow_scene_producers.py`` and the
``isaaclab_arena_examples/tests/test_workbench_evaluation_harness.py`` regression.
``test_environment_workflow_scene_engines.py`` must run as a singleton under its
existing admitted SDK test profile. The durable integration command is::

    python3 scripts/run-workflow-neo4j-checks.py workflow

These commands do not authorize installation, image pulls, native GPU execution,
provider billing, shared-service changes or research-database access. Recheck
source hashes, JUnit results and exact owned-resource cleanup after the final
edits. Separate synthetic component passes are not a GraphQL-submitted live run.
