DCRG: evidence-driven environment refinement
============================================================

DCRG is the experimental controller that evaluates an environment, proposes a
bounded change, and accepts or rejects the candidate using new rollout evidence.
It is **not a replacement for Graph-RAG**. Graph-RAG retrieves previous experience;
DCRG decides what experiment to run next and records what happened.

This page is the canonical implementation architecture. The older DCRG design
under ``.agents/references/agentic_env_generation/`` is historical research context,
not an executable specification or a claim that C1 is solved.

For commands, artifact layout, recovery, and the measured pilot outcome, see
:doc:`../example_workflows/agentic_env_gen/dcrg`.

.. warning::

   The current optimizer is seeded, annealed gradient-noise Adam. It is not a
   calibrated Langevin sampler, loopy belief propagation, or Bethe free-energy
   inference. A low geometric objective does not establish task success.

Responsibilities and boundaries
-------------------------------

The existing generation pipeline remains responsible for translating a prompt
into ``ArenaEnvGraphSpec``. DCRG operates on a frozen specification and policy
configuration after that translation.

.. code-block:: text

   prompt -> environment_generation_agent -> ArenaEnvGraphSpec
                                                  |
                   Graph-RAG supplies priors       v
                   (read-only retrieval)     DCRG controller
                                                  |
                   +------------------------------+------------------+
                   |                              |                  |
                   v                              v                  v
            policy_runner                 bounded proposer     durable state
         observations/actions             geometry oracle      and manifest
                   |                              ^                  |
                   v                              |                  |
         episode JSON + reach trace ----> validated evidence --------+
                   |                              |
                   v                              v
         immutable graph/run records     candidate -> validation
                   |                              |
                   +----> Graph-RAG               v
                                            new rollout
                                                  |
                                           accept / reject

There are four distinct concepts:

* **Scene graph:** objects, robot, support relations, and task semantics.
* **Spatial factor graph:** a numerical representation used to propose geometry.
* **Experience graph:** Neo4j records of immutable specifications, runs, and feedback.
* **Execution state machine:** the bounded evaluate/propose/accept loop.

A database relationship is not an optimizer step. Adding a cycle to Neo4j does
not make a policy learn. Immutable version lineage can remain acyclic even while
an external controller repeatedly reads evidence and runs new experiments.

Module ownership
----------------

Modules below are relative to ``isaaclab_arena/``. The DCRG package is wired to the CLI and has been exercised against the local
simulator and Neo4j. The C1 pilot did not achieve a successful grasp or placement.

.. list-table::
   :header-rows: 1
   :widths: 34 40 26

   * - Module
     - Owns
     - Must not own
   * - ``agentic_environment_generation/graph_rag.py``
     - Prior retrieval and measured DCRG refinement-history traversal
     - Simulation or automatic scene mutation
   * - ``agentic_environment_generation/dcrg/loop.py``
     - Budget, resume state, candidate acceptance and immutable snapshots
     - Simulator internals or SQL/Cypher construction
   * - ``agentic_environment_generation/dcrg/evaluation.py``
     - Policy-runner subprocess, timeout, manifests and episode validation
     - Changing task thresholds or interpreting energy as success
   * - ``agentic_environment_generation/dcrg/graph.py``
     - Version/run registration and proposal lineage
     - Inventing missing measurements or overwriting old evidence
   * - ``agentic_environment_generation/lpg_neo4j_sync.py``
     - Legacy graph serialization and targeted recurrent feedback I/O
     - Selecting a new pose
   * - ``agentic_environment_generation/spatial_geometric_oracle.py``
     - Frame-aware geometry validation and bounded XY proposals
     - Promoting a proposal without an evaluation
   * - ``relations/spatial_factor_graph.py``
     - Numerical optimization, fixed variables, bounds and objective consistency
     - Database access or task-success classification
   * - ``evaluation/policy_runner.py``
     - Simulator lifecycle, policy execution and raw evidence capture
     - Choosing which candidate should replace the baseline

Data contracts
--------------

Controller-assisted transfer experiments
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Same-scene controller interventions are distinct from environment refinement.
``dcrg/controller_graph.py`` registers a frozen controller contract, including
checkpoint weight fingerprints, controller and base-policy source fingerprints,
base configuration, hand frame, and privileged-state label. Its composite policy
identity changes when the controller contract changes; the environment version
does not change. These trials must not be represented as apple XY proposals.

.. code-block:: text

   DCRGControllerTrial --TRIAL_CONTROLLER---------> DCRGControllerVariant
                       --IN_CONTROLLER_EXPERIMENT-> DCRGControllerExperiment
                       --BASED_ON_EVALUATION------> EvaluationRun
                                                    | EVALUATED_GRAPH
                                                    v
                                               EnvironmentGraph

``GraphRAGRetriever.retrieve_controller_trials`` retrieves these trial records,
including zero-success trials and their exact episode counts. The original
``retrieve_refinement_history`` remains the environment-lineage API. Neither
method autonomously chooses controller parameters; the current assistance
experiment is agent-selected, not an automated controller-search optimizer.

The opt-in ``Gr00tAssistedPolicy`` in ``isaaclab_arena_gr00t/policy/`` wraps the
existing remote chunk scheduler. It supports observe-only diagnostics, a bounded
world-Z joint-space residual, a bounded hand-command gate, and their combination.
It is restricted to the existing single-environment, left-hand G1 joint-control
contract. The original policy, other arm, WBC command tail, scene physics and task
predicates remain unchanged. Configurations require ``privileged_state: true``:
object-relative control reads simulator state, not a model-predicted depth map.

The target frame is explicitly a middle-finger link origin, not a calibrated grasp
centre. Limits constrain the residual and its duration; they are not collision
guarantees. Infeasible residuals fall back to the base command and record their
reason, including any resulting residual-slew discontinuity. The gate captures
the initial post-settle finger vector, triggers on command deviation from that
vector, and restores policy authority by its deadline. Command deviation is not
itself a calibrated measurement of finger closure.

Immutable environment
^^^^^^^^^^^^^^^^^^^^^

An environment version is identified by a digest of its canonical specification,
not by a mutable ``latest`` pointer. Preserve the original specification, policy
configuration digest, asset identities, task predicates, and allowed interventions.
A candidate gets a new identity; it never overwrites its parent.

For the initial C1 experiment, only explicitly authorized apple XY movement is
permitted. Table pose, robot pose, camera, apple Z, plate pose, rotations, friction,
object scale, and success thresholds remain fixed. An anchored target remains
fixed unless its movement is explicitly authorized for that experiment.

Evaluation evidence
^^^^^^^^^^^^^^^^^^^

A completed episode is keyed by simulation seed, environment ID, and episode
index. Record the actual policy checkpoint identity separately from the policy
configuration's ``checkpoint_uri`` label.

* ``success`` is the task's boolean result, supported by completed lift and place
  predicates. It is not inferred from ``overall_score``.
* Sustained lift uses the completed lift predicate, including its consecutive-step
  requirement. Peak height is a separate diagnostic.
* Reach residuals name one pinned robot body and an explicit coordinate frame.
  Missing or nonfinite values remain unknown rather than becoming zero.
  They are link-origin-to-object-origin offsets, not automatically calibrated
  grasp-center errors. A finger-base link can legitimately remain above an object
  during a successful grasp. Compare the same frame with successful reference
  trajectories before interpreting a nonzero offset as a required correction.
* Generic contact-sensor force is not automatically hand-object grip force.
* Every rate retains its denominator and source artifact paths.
* An aborted simulator launch produces a failed run manifest, not failed episodes.

Simulation and placement seeds do not seed the remote GR00T diffusion process.
The current server's ``reset`` method does not apply a seed. Until that contract
is extended and tested, report remote diffusion reproducibility as uncontrolled.

Graph identity
^^^^^^^^^^^^^^

Feedback targets one existing ``EvaluationRun`` and one relation on one immutable
``EnvironmentGraph`` version. It must not broadcast an apple residual to unrelated
plate/table relations. Canonical run metrics and feedback metrics must agree.

.. code-block:: text

   EvaluationRun --EVALUATED_GRAPH--> EnvironmentGraph(version)
   EvaluationRun --USED_POLICY-----> Policy(actual identity)
   EnvironmentGraph --HAS_REIFIER-> ReifiedRelation
   ReifiedRelation --REIFIES_SUBJECT/OBJECT--> scene entities
   EvaluationRun --FEEDBACK_MUTATION--------> ReifiedRelation
   ReifiedRelation --PROPOSES_RELAXATION----> candidate EnvironmentGraph
   parent EnvironmentGraph --EVOLVES_TO-----> candidate EnvironmentGraph

Proposal provenance and proposal outcome are separate. A proposed or rejected
candidate must not be retrieved as a verified success. Graph writes require exact
target read-back; absent targets are errors, not successful no-ops.

Execution and acceptance
------------------------

The controller follows this sequence:

#. Validate the frozen experiment contract and available evidence.
#. Evaluate the baseline with the requested seeds and completed-episode budget.
#. Persist episode evidence and graph identities.
#. Generate a bounded proposal from the exact parent run's feedback.
#. Reject changes outside the intervention contract before using the GPU.
#. Evaluate the candidate using the same simulation/placement seed set.
#. Accept or reject using task success first and sustained lift second; retain
   rejected results as evidence.
#. Stop on the experiment budget, absence of a valid proposal, or the specified
   success milestone. Persist failure state for interruption/restart diagnosis.

A minimum C1 milestone is a genuine lift-and-place completion on at least two
independent simulation seeds with video/trace evidence. This is not a statistical
reliability claim. A stronger claim requires a separately budgeted held-out test.
The archived C1 prompt specifies the right hand, whereas the historical v32
baseline traces the left hand. Report these as different contracts until the
required arm is resolved explicitly.

Repository cleanup and merge strategy
------------------------------------------------------------

The implementation should converge on one subsystem rather than a parallel set
of generation frameworks:

.. code-block:: text

   agentic_environment_generation/
       graph_rag.py                 existing retrieval boundary
       spatial_geometric_oracle.py  shared scene geometry boundary
       lpg_neo4j_sync.py             existing graph compatibility boundary
       dcrg/                        bounded refinement subsystem
           loop.py                  state machine
           evaluation.py            simulator adapter and evidence validation
           graph.py                 immutable experiment persistence
   isaaclab_arena_examples/agentic_environment_generation/
       dcrg_runner.py               one thin CLI
   docs/pages/concepts/dcrg.rst      this canonical architecture

The new modules are consolidated under ``dcrg/``; the temporary flat modules were
removed and imports/tests updated. Shared geometry and the existing Graph-RAG
retriever remain outside this package because other generation workflows use them.

Keep responsibilities separated across repository locations:

* ``docs/``: current architecture, supported commands, and known limitations.
* ``.agents/skills/``: reproducible operational procedures, not research claims.
* ``.agents/references/``: dated hypotheses and historical implementation plans,
  with a pointer to this page instead of copied current instructions.
* ``generated_envs/``: immutable specifications and explicit lineage.
* ``eval_output/``: run manifests and measured results. Models and datasets remain
  outside Git; do not commit raw multi-megabyte traces by default.

Merge gates
-----------

* Numerical regressions: fixed infeasible graphs, best-state consistency,
  deterministic seeds, finite inputs and bounds.
* Geometry regressions: G1 root-is-pelvis convention, support geometry, unchanged
  input, preserved anchors/rotations/Z, and rejected unconverged proposals.
* Evidence regressions: asynchronous environments, missing data, real C1 sequence
  events, duplicate episodes and score/success disagreement.
* Graph integration: exact-version registration, idempotence, conflicting-identity
  rejection, feedback read-back and proposal disposition.
* State-machine integration: bounded execution, durable resume, no duplicate run
  on resume, and explicit rejection of regressions.
* Simulator verification: real baseline and candidate artifacts, not only mocked
  callbacks or successful graph writes.

Do not describe the subsystem as production-ready while any of these gates is
unverified. Cross-object transfer scores, learned posterior calibration, and
policy/controller adaptation are separate research extensions, not prerequisites
for a correct C1 feedback loop.
