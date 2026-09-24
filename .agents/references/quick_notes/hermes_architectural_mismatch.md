# Hermes Architectural Mismatch

We got stuck on the development phase now trying to define the api contracts to talk betweent eh workflow and the Neo4j database. 


The primary issue is the conflation of the asset registration mechanism with the full simulation runtime's import graph. This leads to a combinatorial explosion of dependencies. The registration process's design needs modification.

Your assessment is 100% accurate. What you are witnessing is a textbook case of goal displacement and combinatorial entrapment caused by an agent lacking a macroscopic architectural mental model of the system.

Here is an unvarnished diagnosis of why Hermes is failing to progress toward finalizing the application-owned orchestrator and its graph database integration, and what must be done to break the deadlock.

---

### 1. The Root Cause: An Architectural Mismatch

The architecture you are trying to build consists of two fundamentally distinct layers:

```bash
┌────────────────────────────────────────────────────────────────────────┐
│                      MACRO GOAL: Physical AI Orchestrator              │
│   • Neo4j Custom Graph Database (Scene Graphs, Tasks, Embodiments)     │
│   • Application-Owned Orchestrator (GraphQL Schema, Resolvers, State)  │
│   • World/Asset Catalogue Hashing & Provenance (RDF-star / LPG)        │
└──────────────────────────────────┬─────────────────────────────────────┘
                                    │  Boundary Violation
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   DEEP SIMULATION RUNTIME (Isaac Sim / Lab)             │
│   • Omniverse Kit, PhysX C++ SDK, Carbonite, Warp, USD/Pxr C++ libs    │
│   • Gym Environments (ManagerBasedRLMimicEnv, InteractiveScene)        │
│   • UI / Visualizers (ManagerLiveVisualizer, ImagePlot -> Matplotlib)  │
└────────────────────────────────────────────────────────────────────────┘
```

The orchestrator and static catalogue hasher are supposed to run in lightweight, headless CPU mode to query the graph, validate schemas, and index asset metadata.

However, eager imports in the asset and embodiment libraries pierce this boundary:

* ensure_assets_registered() imports isaaclab_arena.embodiments.
* embodiments/__init__.py imports agibot.py.
* agibot.py imports FrankaMimicEnv from franka.py.
* franka.py imports ManagerBasedRLMimicEnv from isaaclab.envs.
* ManagerBasedRLMimicEnv imports ManagerBasedRLEnv.
* ManagerBasedRLEnv imports ManagerLiveVisualizer from isaaclab.ui.widgets.
* ManagerLiveVisualizer imports matplotlib.cm.
* matplotlib attempts to load native .so binaries (_image, _path, etc.).

---

### 2. Why Hermes Is Incapable of Solving This on Its Own

Hermes does not see this architectural boundary. Instead, it treats the entire system as a linear traceback puzzle:

1. The "Whack-A-Mole" Import Loop:
    * In run 74cbf6: It hit an assertion on openable.py. Hermes patched openable.py to use TYPE_CHECKING.
    * In run 972d7e: It progressed 1 line and hit isaaclab_assets. Hermes patched the harness to admit isaaclab_assets.
    * In run aa54a2: It progressed 1 line and hit isaaclab.ui. Hermes patched the harness for isaaclab.ui.
    * In run ec5f83: It progressed 1 line and hit matplotlib. Hermes patched the harness for matplotlib.
    * In run b6f5fa: Loading matplotlib pushed the native binary .so count past the native_limit=48 ceiling, triggering an immediate AssertionError: S2 native identity count ceiling.
2. The Confinement Sandbox Trap:
    * A single standard scientific stack (numpy + torch + matplotlib + pxr) loads 50 to 75 native shared libraries.
    * Hermes is trying to squeeze the entire monolithic simulation runtime into a 48-binary micro-sandbox by making piecemeal source patches. Every fix simply exposes the next transitive import in Isaac Sim’s 500-package dependency graph.

> workflow_graphql_execution_join_harness.py is over 5,200 lines of extreme micro-confinement (python3 -I -S -B, custom sys.meta_path hooks, SHA-256 binary hashing, inode tracking, and a hard 48-file native binary limit).

3. Loss of the Macro Goal:
   * 100% of its reasoning tokens (at ultra effort, burning 20k–30k thinking tokens per step) are consumed reading tracebacks of Python ExtensionFileLoader failures.
   * It cannot deduce that an environment class (FrankaMimicEnv) has no business being eagerly evaluated during asset metadata registration.

> Hermes has completely lost sight of the Neo4j graph database, the GraphQL resolvers, and the Physical AI state coordinator.


---

### 3. Concrete Recommended Strategy to Finalize the Orchestrator

To stop Hermes from looping indefinitely and get the orchestrator running with your graph database, you should force two decisive interventions:

#### Action A: Decouple Simulation Environments from Metadata Registration

The orchestrator only needs metadata and configurations (*Cfg dataclasses, USD paths, mesh bounds) to hash the catalogue and talk to Neo4j. It does not need runnable Gym environments at startup.

* In isaaclab_arena/embodiments/franka/franka.py (and agibot.py):
Wrap FrankaMimicEnv and any Gym environment classes in lazy/deferred imports, or move them out of the eager __init__.py registration path:

```python
if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedRLMimicEnv
```

Or ensure that ```embodiments/__init__.py``` only registers the embodiment configurations (FrankaCfg, AgibotCfg), deferring the environment class import until the simulation worker actually starts a rollout.

#### Action B: Stop Fighting the Confinement Harness in Application Code

If init-server legitimately requires packages that pull in native libraries:

* Update the harness budget in scripts/workflow_graphql_execution_join_harness.py:

    Increase native_limit for init-server from 48 to 64 (the Plan 04 aggregate budget allows up to 64 identities).

* Or explicitly mock/stub isaaclab.ui in headless mode so matplotlib is never imported in the first place.

#### Action C: Pivot Hermes Promptly Back to the Orchestrator & Graph Database

Direct Hermes to stop micro-patching individual third-party libraries and focus on the macro contract:

STOP debugging individual transitive imports.
1. Decouple FrankaMimicEnv in isaaclab_arena/embodiments/franka/franka.py from eager module evaluation so ManagerBasedRLMimicEnv and matplotlib are not loaded during ensure_assets_registered().
2. Verify that init-server executes ensure_assets_registered() and execution_catalogue_sha256() under the existing 48-native budget.
3. Once the catalogue hash is verified, proceed directly to the GraphQL orchestrator integration with Neo4j.

Would you like me to apply the decoupling in franka.py / embodiments right now so init-server can cleanly finish its static asset catalogue pass and advance to the graph database orchestrator?

---

## Proof of the architectural mismatch

The user's concern about code modification for test passes is valid, as mocking or omitting metadata risks introducing subtle bugs. Examining the "run without limits" attempt confirms the issue isn't simply resource constraints, but rather side effects of imported libraries, specifically subprocess spawning during initialization. Decoupling the execution strategy doesn't eliminate these problems.

Your hesitation is completely justified. In autonomous coding, agents frequently take destructive shortcuts—when a test fails on an import or registry, they often mock out the dictionary, hardcode a dummy hash, or delete assets from the registration list to make the test turn green. That leads to subtle, catastrophic bugs when the orchestrator attempts to look up an asset in Neo4j and gets KeyError
or an invalid schema.

However, there is an essential distinction between skipping metadata (which causes dumb mistakes) and decoupling runtime execution from metadata (which is clean Python architecture).

Here is the exact reality of what just occurred when you told Hermes to "run without limits," and why safe decoupling does not lose a single byte of metadata.

---

### 1. What Happened When Hermes Ran "Without Limits"

In the run that just executed (```arena-s2-init-d1bb90d66a2e4baabb9812424b62a98c```):

1. Hermes updated the harness to remove the 48-binary limit and byte ceilings for init-server.
2. It immediately crashed anyway with a fatal error:

```python
File ".../rsl_rl/runners/on_policy_runner.py", line 17, in <module>
    from rsl_rl.utils.logger import Logger
File ".../rsl_rl/utils/logger.py", line 9, in <module>
    import git
File ".../git/__init__.py", line 298, in <module>
    raise ImportError("Failed to initialize: {0}".format(_exc)) from _exc
ImportError: Failed to initialize: workflow-process denies subprocess
```

Why did this happen?

When GitPython (import git) is imported, it automatically spawns a child process (subprocess.Popen(["git", "version"])) at import time just to check which git binary is on the host. The S2 container security policy strictly denies unauthorized subprocess spawning.

This proves that the issue was never just resource quotas. Third-party simulation and training libraries eagerly execute subprocesses, look for GPU drivers, and allocate CUDA memory the microsecond their files are imported.

---

### 2. The Crucial Difference: Mocking vs. Deferred Decoupling

Action                                                                                                            | What It Does                                                                                                                                                               | Risk to Metadata / Database
-------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------
Mocking / Stubbing (The Bad Way)                                                                                  | Replacing registries with fake dicts, deleting @register_* decorators, or returning a hardcoded dummy hash.                                                                | HIGH RISK. The database gets phantom schemas, missing assets, and breaks the Physical AI orchestrator.
Deferred Decoupling (The Safe Way)                                                                                | Keeping the class, the config dataclass, the @register_* decorator, and all metadata 100% intact, but moving the runtime runner import inside the method that executes it. | ZERO RISK. All metadata (names, schemas, bounds, joints, types) is registered identically.

#### Concrete Example: rsl_rl_action_policy.py

In rsl_rl_action_policy.py:

# Currently at line 15 (eager import that spawns git subprocess):

```python
from rsl_rl.runners import DistillationRunner, OnPolicyRunner  # <-- TRIGGERS SUBPROCESS CRASH


@register_policy
class RslRlActionPolicy(PolicyBase[RslRlActionPolicyCfg]):
    name = "rsl_rl"
    ...
```
Notice what @register_policy actually does:

* It stores RslRlActionPolicy and RslRlActionPolicyCfg in POLICY_REGISTRY["rsl_rl"].
* The GraphQL orchestrator and Neo4j only need to know:
    * Policy name: "rsl_rl"
    * Configuration schema: RslRlActionPolicyCfg (checkpoint path, device)
    * Action and observation space shapes.


Where are DistillationRunner and OnPolicyRunner actually used?
Only on line 112 inside def _load_policy(self, env: gym.Env): when actually loading model weights to step a physics simulation!

If we simply move that single line inside _load_policy():

```python
def _load_policy(self, env: gym.Env) -> None:
    from rsl_rl.runners import DistillationRunner, OnPolicyRunner  # Deferred to runtime execution
```

1. Every single policy and asset remains fully registered.
2. Every configuration schema is fully intact.
3. The static catalogue SHA-256 is 100% authentic and un-mocked.
4. git and subprocess are never called during catalogue hashing or orchestrator schema initialization.

---

### 3. Recommendation

You do not have to compromise between safe execution and full metadata integrity:

* Do NOT allow Hermes to mock out or bypass any registries.
* Do apply deferred imports for executable runners (OnPolicyRunner, ManagerBasedRLMimicEnv) so that metadata inspection does not accidentally trigger heavy runtime side effects (subprocesses, CUDA driver queries, GUI visualizers).

This guarantees that your custom Neo4j graph database and the application-owned orchestrator receive the true, complete metadata vocabulary without getting killed by runtime import side effects.

Would you like me to guide Hermes (or apply the deferred import in rsl_rl_action_policy.py directly) to resolve the Git subprocess crash while keeping the complete registry intact?
