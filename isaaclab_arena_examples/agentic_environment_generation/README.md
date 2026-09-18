# Agentic Environment Generation

Use the Arena Workbench to edit environment YAML, inspect its authored graph,
request agent-generated changes, and render scene and asset snapshots. Exported
`ArenaEnvGraphSpec` YAML can then be used by Arena's separate policy evaluation
workflows.

The workbench is experimental. Use a checkout containing `web/arena-workbench/`
and `docker/workbench/`; an upstream release may not contain this interface.

## Which services do I need?

| Service | Minimal editor / snapshots | Full graph-backed workflow | Started by |
| --- | --- | --- | --- |
| Arena runtime (Python API, agent, Isaac Sim workers) | Required | Required | `./docker/run_docker.sh` |
| Workbench frontend | Required for the dashboard | Required for the dashboard, not CLI-only use | `docker/workbench/run_workbench.sh start` |
| Neo4j experience database | Optional | Required | Separate Neo4j startup below |
| Generation LLM endpoint | Only for generation | Required for generation | Hosted API, or an operator-managed local inference server |
| GR00T / OpenPI policy server | Not required | Required only when evaluating the corresponding policy | Separate policy evaluation guide |

For the full setup, start Neo4j and Arena, configure their connection and model
access, then launch the workbench. Neither launcher starts Neo4j or a policy
server. The Python API runs **inside Arena**, not in another API container.

**Current integration boundary:** revised APIs expose prompt-first generation as
well as refinement. `refine_spec` does not retrieve new Graph-RAG priors;
from-scratch generation has its own authorized retrieval path. Managed research
retrieval integration is still under review, not proof of end-to-end P2 parity.
Starting Neo4j does not automatically configure generation or publish drafts.

### Current dashboard readiness

**Workflow readiness** checks one general **generation → inspect → build** path
(`agentic_generation`), not a scenario selection. It inspects the registered model
settings, generation, validation and Build contracts, plus snapshot/preview/artifact
contracts when the editor advertises its snapshot adapter. An explicit **Check
dependencies** observes runtime package availability, graph retrieval and GPU
headroom. It accepts an arbitrary prompt without a base specification, or validates
the current frozen source without imposing a DROID embodiment.

Provider-model metadata reads are **opt-in and off by default**; configured model
settings alone remain `not_checked`. A metadata PASS is availability evidence, not
inference, quota, structured-output or task-success evidence. Checks do not generate,
render, advance simulation, publish, or call policy-server RPCs. Changing the source,
prompt, session, settings or consent retires the result and requires another click.

This is the combined graph-backed path: Neo4j/model access is not needed just to
edit or Build. **Policy evaluation is separate**, with its existing Evaluate
admission and fixed-profile restrictions; GR00T/OpenPI is not required for generation
or Build. Readiness never grants operation authorization. The existing generation,
inspection, Build and Evaluate controls retain their own validation and admission.
Deploy the matching API/worker and frontend together: an older API returning a
different version/workflow is rejected, never retried as a legacy scenario check.
Legacy readiness API identifiers remain supported for explicit existing clients.

### Opt-in managed research preview

**Admin CLI operating requirement:** initialization and backup are offline-only
and require `--attest-quiescent`. Close all journal connections and keep API/workers
offline throughout. The CLI never stops them implicitly. Lock checks reject
attached WAL connections and conflicting rollback transactions, but cannot prove
that every idle connection is absent. The reviewed private-copy preflight does
not rely on SQLite `mode=ro` being physically nonmutating. These preview commands
are not approval for a deployment cutover or proof of power-loss durability.

Generation and **Apply generated YAML** remain draft-only. **Save revision** /
export saves an editor snapshot; the separate **Save Research Version** action
persists an exact accepted candidate as a numbered, immutable research version.
Publication and policy evaluation are separate operations, not consequences of
saving. Managed publication/retrieval/worker integration remains unfinished or
under review; code and synthetic browser tests do not establish live deployment.

The Python API's `research_roots` / repeatable `--research-store ID=ABSOLUTE_PATH`
configuration exposes already initialized roots. The default stays empty and
`research_versions` is advertised only with configured roots. GET discovery does
not initialize or migrate anything. Before enabling a profile, back up and review
the existing P1 journal, then explicitly run `research_admin init-store` against
the supported current schema and a new owner-private local root outside
`generated_envs` / `eval_output`. Incompatible schemas fail closed; there is no
silent P1 migration or claim that legacy writers are safe for managed storage.

Follow the [managed operator runbook](../../docs/pages/example_workflows/agentic_env_gen/workbench.rst#managed-research-preview-operator-onboarding)
for actual initialization, API profile, backup, checkpoint verification/estimate,
and inactive restore-preparation commands. Its paths are operator-replaced
absolute placeholders, not chosen deployment locations. Backups contain private
Sessions-derived journal state. The cooperative local-filesystem deadline is not
a hard I/O deadline or power-loss proof. Prepared restore **never activates** the
API, undoes graph effects, or automatically replays queued work.

For optional managed CLI resolve from a prompt, use the already-running API and
its server-configured model, in the intended non-root Arena shell. This command
authorizes model work; it is not a health check. Replace the path/profile/origin
and retain the exact operation ID before submission:

```bash
/isaac-sim/python.sh isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --prompt "Droid grasps the yellow banana from the maple table and places it onto the large white ceramic plate." \
  --managed_api_socket /REPLACE/private-ipc/api.sock \
  --managed_api_origin http://localhost:3001 \
  --managed_store_id research --managed_family banana_plate \
  --managed_operation_id REPLACE_WITH_RETAINED_OPERATION_ID
```

Do not add `--base_spec` for prompt-first generation or put an API key in argv.
Managed resolve rejects credential/endpoint/sampling overrides; temporary dashboard
keys do not configure this CLI. Recover ambiguous results by rerunning unchanged
with the same operation ID, including from replacement session S2. Exact accepted
lookup precedes fresh model preflight, so changed current model settings do not
silently replace accepted work. A timeout is not cancellation or retry permission.

Retain exact store/family/source/parent identity for research saves; select an
immutable parent explicitly in the UI, never guess from `latest`. The current
managed CLI saves with no parent and verifies commit/artifact readback. It reports
`publication=not_requested`. The old CLI without managed flags is preserved below
and still has its separate publication attempt.

**Remaining acceptance:** approve spend/token/time and retrieval/GPU budgets before
live work, then obtain exact-operation recovery and artifact/runtime evidence on
the reviewed deployment. Publication, retrieval and worker end-to-end proof and
physical evaluation remain separate authorized acceptance, not synthetic-test claims.

## 1. Prepare the runtime

You need Linux, an Isaac Sim-compatible NVIDIA GPU, Docker Engine, Docker Compose,
and NVIDIA Container Toolkit. Follow the [Arena installation guide](../../docs/pages/quickstart/installation.rst)
for the base setup.

From the repository root, in a **host terminal**:

```bash
git submodule update --init --recursive
mkdir -p "$HOME/eval"
./docker/run_docker.sh
```

The script builds or starts this clone's Arena simulation container and attaches
to it. An editor/devcontainer is not a substitute for this runtime. The workbench
requires a writable persistent `/eval` mount and a non-root runtime user with
access to Isaac Sim.

The script manages only this clone's Arena container. It attaches to a running
container, but removes and recreates a matching exited container. Preserve
important data in mounts; container-only changes can be lost. Dataset/model/eval
directories are mounted only if they exist before creation.

If the runtime does not already have the optional web dependencies, install them
**inside the Arena runtime**, as the supported non-root development user:

```bash
cd /workspaces/isaaclab_arena
/isaac-sim/python.sh -m pip install -e '.[web]'
```

Node and npm run in the frontend container; do not install them on the host or
in the simulation runtime for this workflow. A policy server is not required
for YAML editing or snapshots.

## 2. Start and configure Neo4j

### Reuse an existing research database when available

In a **host terminal**, identify the intended database without dumping credentials:

```bash
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
```

If your operator has an existing Arena Neo4j container, start that exact container
with `docker start <existing-container-name>`. Keep its existing data volume,
ports, and credentials. Do not replace it with an empty database or delete its
volume. The database may be shared by other research runs.

### Create a database only for a fresh installation

The following **host Bash** commands create a separate local database using the
Neo4j image version specified in the repository's simulation Compose file.
First confirm that the chosen container/volume names and host ports are unused.
Choose different names for independent clones rather than sharing data accidentally.

```bash
read -r -s -p 'New Neo4j password (at least 8 characters): ' NEO4J_PASSWORD
printf '\n'
export NEO4J_PASSWORD
export NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}"
docker volume create arena-envgen-neo4j-data
docker run -d --name arena-envgen-neo4j \
  --restart unless-stopped \
  -p 127.0.0.1:7475:7474 \
  -p 127.0.0.1:7688:7687 \
  --env NEO4J_AUTH \
  --mount source=arena-envgen-neo4j-data,target=/data \
  neo4j:5.26-community
unset NEO4J_AUTH NEO4J_PASSWORD
```

The password is entered interactively, not stored as a literal shell-history
command. Docker administrators can still inspect container environment variables.
Do not publish credentials or use `NEO4J_AUTH=none`. Initial authentication settings
do not reset the password of an existing database volume.

Check startup and authenticate interactively:

```bash
docker logs --tail 50 arena-envgen-neo4j
docker exec -it --user neo4j arena-envgen-neo4j \
  cypher-shell -a bolt://localhost:7687 -u neo4j
```

At the Cypher prompt, run `RETURN 1 AS ok;`, then `:exit`. If startup is still in
progress, retry after the logs report readiness. Neo4j Browser is available at
**http://localhost:7475**; connect it to **bolt://localhost:7688**.

The repository also contains `docker/docker-compose.sim.yml`. Do not run the
whole Compose stack just to obtain Neo4j: it also defines Arena and GR00T, and its
Neo4j port mappings are not loopback-only. Its default Bolt port is 7687, whereas
the Python graph driver's current fallback is 7688. Set the client URI explicitly
instead of relying on those differing defaults.

### Configure the Arena client, not just the database

The Python process accessing Neo4j needs:

| Variable | Value for the fresh local setup above |
| --- | --- |
| `NEO4J_URI` | `bolt://localhost:7688` |
| `NEO4J_USER` | `neo4j` |
| `NEO4J_PASSWORD` | The password chosen above |

Arena uses host networking, so `localhost:7688` reaches the published host port.
Do not use a transient Docker bridge IP. For a remote database, use its actual
reachable URI and the operator's authentication/TLS configuration.

For **CLI commands in an interactive non-root Arena shell**, configure and verify
the connection in that same shell:

```bash
export NEO4J_URI=bolt://localhost:7688
export NEO4J_USER=neo4j
read -r -s -p 'Neo4j password: ' NEO4J_PASSWORD
printf '\n'
export NEO4J_PASSWORD
/isaac-sim/python.sh -c 'from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver; driver = get_neo4j_driver(); driver.verify_connectivity(); driver.close(); print("Neo4j connection verified")'
```

For the **workbench API**, these variables must instead be in its startup
environment. Neither `run_docker.sh` nor the workbench launcher forwards the
host's `NEO4J_*` variables. Exports in an unrelated interactive container shell
do not configure an API launched later by `docker exec`. An operator must
provision the runtime's inherited environment or an explicit API launch path;
the stock launcher currently has no Neo4j credential-injection option. Merely
starting the database is not a completed dashboard connection setup.

After configuring and launching the API, open `/neo4j` and run `RETURN 1 AS ok`.
This checks the actual dashboard-to-database connection; a successful CLI probe
alone does not. Keep credentials server-side, never in query text or browser YAML.

### Populate and verify experience memory

A new database is empty. Reuse an operator-approved existing database/backup, or
populate it through explicit CLI generation and real evaluation workflows.
The from-scratch CLI below attempts to publish generated specs. Evaluations
provide measured evidence; do not label unevaluated fixtures as successful runs.

In `/neo4j`, inspect what is actually present:

```cypher
MATCH (g:EnvironmentGraph) RETURN count(g) AS environments
```

```cypher
MATCH (e:EvaluationRun) RETURN count(e) AS evaluation_runs
```

Counts establish presence, not eligible priors: retrieval prefers matching
environments with qualifying measured results, then falls back to structurally
converged environments. It can return no priors. Database failures also allow
from-scratch generation to continue without priors, so inspect warnings and
retrieval evidence rather than assuming generation success proves Graph-RAG use.
Dashboard save/export does **not** seed or publish to Neo4j.

## 3. Launch the workbench

In another **host terminal**, from the repository root:

```bash
sh docker/workbench/run_workbench.sh inspect --dev --diagnostics --port 3001
sh docker/workbench/run_workbench.sh status --dev --diagnostics --port 3001
```

If the workbench is not already running:

```bash
sh docker/workbench/run_workbench.sh start --dev --diagnostics --port 3001
```

Open **http://localhost:3001**. Keep using the same hostname while editing:
`localhost` and `127.0.0.1` have separate browser cookies and draft storage.

- Use the same options for `inspect`, `start`, `status`, and `stop`.
- Port 3001 is explicit; the launcher's default is 3000. Choose another unused
  port if needed rather than stopping an unrelated application.
- The launcher discovers this clone's running Arena runtime. If discovery is
  ambiguous, supply `--runtime <exact-container-name>`; `--host-root` and
  `--api-user` are available for ambiguous mount or user discovery.
- The launcher starts only the frontend and Python API, not Arena, Neo4j, or a
  policy server. `--diagnostics` enables optional test-only jobs, not simulation
  or model inference.
- Keep this local-only deployment on loopback. It does not provide multi-user
  authentication or isolation for network exposure.

## 4. Try editing before enabling generation

1. Open the default document in the picker:
   `isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml`.
   It contains a DROID robot, maple table, cube, bowl, and mug.
2. Inspect the YAML, authored graph, assets, and tasks. Select graph nodes to
   inspect their properties.
3. Make a small YAML edit and check the schema diagnostics. Editing and
   validation do not invoke an LLM, publish to Neo4j, or start GPU work.
4. Click **Save revision** and export the flattened YAML. This creates an
   immutable revision without overwriting repository YAML or include files.

Unsaved drafts have per-tab reload recovery, but browser storage is not durable
project storage. Save and export work you want to keep.

### Graph explorer preview

Choose **Try graph explorer**, or append `graphRenderer=explorer` to the workbench
URL. The legacy SVG remains the default until visual acceptance; **Use legacy
graph** switches back without changing YAML or restarting the API.

The explorer offers **Table / 2D / 3D**, with a shared node/relationship inspector,
search and role/type filters. Drag nodes to pin their layout positions; use
**Freeze layout**, **Fit visible**, and **Expand graph** for inspection. Navigation
buttons and coordinate/nudge controls provide keyboard and click-only alternatives.
Layout coordinates do not change object poses. The optional WebGL 3D mode is a
relationship diagram, not a scene preview; Table and 2D remain fallback choices.

On the Neo4j page the outer Table still contains raw query rows, while the graph
explorer's Table lists returned Nodes/Relationships. Selecting or rearranging
entities sends no database-expansion, generation, or simulator request. For
controls, limits, and recovery, see the
[workbench runbook](../../docs/pages/example_workflows/agentic_env_gen/workbench.rst).

## 5. Configure model access

### Temporary dashboard key (recommended for local interactive use)

Use the provider-settings panel beside generation:

1. Choose OpenAI, Gemini, OpenRouter, or NVIDIA. Check the displayed destination
   endpoint; browser-entered keys cannot use a custom URL.
2. Enter a model ID and choose **Key expiration**: 15 minutes, 30 minutes
   (default), 1 hour, 2 hours, or **Never expires**. Then read and accept the temporary-use notice.
   Changing provider, model, expiration, or consent clears the key field.
3. Paste a scoped, budget-limited API key into the dedicated password field,
   never the prompt or YAML editor, then click **Save temporary key**. This sends
   the key to the local API but does **not** contact the provider or run inference.
4. Use **Generate spec** only when ready to send the environment/prompt to that
   provider. A configured status is not proof the key/model is valid.
5. Forget the session key when finished, or end the session.

The API key expires after the selected duration or at session expiry, whichever
comes first; expired entries are removed on access or by periodic memory cleanup.
Changing the dropdown only affects the next save. To change an active key's
deadline, re-enter the key and save again; this replaces its reference and can
invalidate queued jobs bound to the old reference.
**Never expires** disables only the key timer: the key remains in API memory
until the session ends, you forget/replace it, or the API restarts. Explicit
session activity can extend its idle deadline, but not the session's absolute
lifetime; polling alone cannot extend it. The active status shows **No key timer**
and the current session deadline. Longer retention increases exposure; prefer
the default timer when possible and forget the key when finished.
It does not persist the key in SQLite, job inputs, YAML, or exports. The browser
does not save it in local/session storage or the query/mutation cache, and clears
the password field after a submission attempt. Public settings show provider,
model, source, and expiry, not the key or a key suffix. Tabs sharing the same
browser session share these settings; closing a tab is not equivalent to forgetting
the server-side key. An API restart loses temporary keys.

Replacing, forgetting, or expiring a key invalidates queued jobs bound to that
credential reference; they must not silently switch to another key/provider.
Already-authorized generation jobs can finish all model calls within their
existing budget. Forgetting a
key is not provider-side revocation and cannot retract a request already sent.
If a server-environment key exists, forgetting a temporary override restores that
fallback for new requests; check the displayed source before generating again.

**Security limits:** this remains a trusted, single-operator local workbench.
Use loopback HTTP only for local access, and reviewed HTTPS/authentication for
remote deployments. Same-origin malicious JavaScript, browser extensions,
developer tools, or a privileged local process can access secrets in transit or
memory; RAM zeroization is not guaranteed. Do not collect network traces while
entering a real key. Prefer restricted project keys with provider-side spending
limits; revoke them at the provider if exposure is suspected.
Generation sends the prompt, base scene, relevant asset/task catalogues, USD
context, and any graph priors consumed by the selected workflow to the provider.
Review the provider's data-retention policy before using private research data.

### Operator-managed environment configuration

Server configuration remains available for unattended use. These variables must
reach the **Python API process environment inside the Arena runtime**:

| Provider | API key | Optional model and endpoint overrides |
| --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | `OPENAI_MODEL`, `OPENAI_BASE_URL` |
| Gemini | `GEMINI_API_KEY` | `GEMINI_MODEL`, `GEMINI_BASE_URL` |
| OpenRouter | `OPENROUTER_API_KEY` | `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL` |
| NVIDIA | `NV_API_KEY` | `NV_MODEL`, `NV_BASE_URL` |

Configure one provider and select a model available to your account. If multiple
server keys are present, selection follows the table's order. Never put keys in
environment YAML, committed files, or browser fields other than the dedicated
temporary-key control.

**Current setup limitation:** the workbench does not automatically read `.env`
files, and its launcher does not forward host model variables through
`docker exec`. There is one existing provisioning path: `run_docker.sh` forwards
an exported host `NV_API_KEY` when **creating** the Arena container. Attaching to
an existing container does not update its environment. That script does not
forward the other provider keys, model/endpoint overrides, or `NEO4J_*` variables.
The server-environment NVIDIA default endpoint is internal; an arbitrary NVIDIA
API key does not necessarily grant access. The temporary dashboard NVIDIA option
instead targets the public `https://integrate.api.nvidia.com/v1` endpoint.

For other configuration, an operator must provision the runtime container
environment inherited by the API, or provide an explicit credential-injection
launch path. Exports in an unrelated container shell are not enough. Apply API
environment changes through a controlled restart after active jobs finish.

Without either configuration, generation is unavailable; editing and snapshots
remain usable. The verification record below predates temporary dashboard-key
support and does not establish successful live inference with a real key.

## 6. Generate, review, and save

After deploying the revised API, its `generation_modes` capability exposes
**New environment from prompt** and **Refine current environment**. An older
running API omits that capability and retains the legacy refinement UI; loading
a template is not a substitute for upgrading to the prompt-first workflow.

With model access and a run budget configured:

1. Select **New environment from prompt**. No document is required, and an open
   document is not submitted as a base. For A2, enter:

   > Droid grasps the yellow banana from the right side of the maple table and
   > places it onto the large white ceramic plate on the left.

2. Select the retrieval policy. Requiring the service stops generation if
   retrieval is unavailable; an empty successful retrieval can still have no
   eligible priors. Allowing fallback records unavailable retrieval explicitly.
3. Click **Generate spec** once and follow the existing job.
4. Inspect the YAML, warnings and last generation evidence: exact consumed
   context, context/catalogue digests, measured versus structural precedent,
   evaluation/policy identities when known, and retrieval limits/timing.
5. For A2, verify DROID, `banana_ycb_robolab`, `plate_large_vomp_robolab`, and
   banana-to-large-plate task parameters. Banana-to-bowl is not A2. Schema
   validation alone does not prove the requested task or physical success.
6. Explicitly **Apply generated YAML**. A New result detaches old document/include
   context, then validates again. **Save revision** / export remains editor-draft
   persistence, not the numbered research-version/publication workflow.

For refinement, load a valid document and select **Refine current environment**.
It freezes the explicit base and does not retrieve new graph priors. Applying an
old result against changed source identity requires confirmation and detaches
foreign includes, even when raw YAML text matches.

Graph retrieval needs explicit `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD`
in the API's server environment; `NEO4J_DATABASE` defaults to `neo4j`. Provision
secrets privately through the operator-managed configuration described above, never in prompts,
URLs, command arguments or committed files. Query-page connectivity alone does
not prove the generation worker has this authorized profile. The worker receives
only the scoped private configuration; it never discovers default credentials.

Generated drafts are **not published to Neo4j**, and generation does not run
simulation or policy evaluation. This is P1 draft-only functionality, not full
CLI `resolve` parity. Live A2 acceptance has not been established by the synthetic
browser or subprocess tests.

Do not resubmit an expensive job just because a browser connection was lost.
Submitted jobs survive browser refreshes; recover the existing job status first.
An unresolved retry keeps its original credential reference even if you save a
replacement key. If it cannot be accepted, inspect the job journal first, then use
**Discard unresolved request** and acknowledge the warning before starting a new
request. Discard clears this tab's retry information only; it does not cancel or
delete an already-accepted job.

For **blocked authorization**, select the job (including jobs from another tab)
and explicitly reauthorize or cancel. Reauthorization preserves the original
prompt/profile and appends a linked grant. A definitively rejected renewal offers
**Use current credentials** only after its durable rejection is verified; an
ambiguous response keeps the same request ID/reference. Correcting credentials
does not itself submit work. Indeterminate work cannot use this renewal path.
Cancellation distinguishes never-released work, unknown external outcomes and
preserved accepted candidates; cancelling does not prove a provider did no work.

### From-scratch Graph-RAG generation (CLI)

For the CLI's versioned Graph-RAG resolve path, run **inside the non-root Arena shell**
where you verified Neo4j and configured your model credentials. Select a supported
model and endpoint for your provider; the runner accepts `--model` and
`--base_url` overrides. Do not pass a secret through `--api_key` on the command line.
Temporary dashboard keys are not exported to the CLI or its environment.

```bash
/isaac-sim/python.sh isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --prompt "Droid picks up the mustard bottle from the maple table and places it in the grey bin."
```

Do not add `--base_spec` for this from-scratch path. This command makes model
calls, creates versioned YAML/lineage artifacts, and attempts Neo4j publication;
unlike the workbench, it is **not draft-only**. It does not launch a simulation
rollout. Use the output path reported by the runner and verify the resulting
graph in Neo4j: publication failures can be non-fatal. A first run against an
empty database has no prior experience to retrieve.

## 7. Build, render, and evaluate

### Build the current environment

The prototype's **Build environment** action reuses this README's CLI harness;
it does not generate a replacement scene. After applying generated YAML or
loading/editing a document:

1. Validate the current draft, then select **Build environment**.
2. The API freezes that draft and submits one job. Its fixed profile is headless,
   one environment, and **20 zero-action simulation steps**, with no video.
   This advances simulation; it is not a zero-step schema check.
3. Follow progress, refresh status, or cancel through the existing job controls.
   **Job details** shows the frozen inputs and matching completion result.
4. A completed build means the harness completed those steps and its owned worker
   was cleaned up. It does not establish manipulation-task success. Later draft
   edits do not change the submitted job.

Build requires a running Isaac Sim-capable Arena runtime and available GPU lease.
It does not call generation, a remote policy server, or graph publication.
The button is available only when the API advertises its Build adapter and the
current draft is validated; adapter support alone is not GPU readiness.
Focused API/harness-seam and frontend tests pass. A real GPU run of this new web
adapter has not yet been performed.

### Evaluate a policy from the workbench

The production editor now includes **Evaluate policy**, backed by the existing
`policy_runner.py` harness. Start the appropriate server using the
[GR00T](../../docs/pages/example_workflows/agentic_env_gen/eval_with_gr00t.rst)
or [OpenPI](../../docs/pages/example_workflows/agentic_env_gen/eval_with_openpi.rst)
guide first; the workbench does not start or stop policy servers.

1. Apply or load the environment YAML and validate it. This prototype supports
   `droid_abs_joint_pos` with its DROID camera and separate-observation contract;
   it rejects incompatible embodiments rather than remapping actions.
2. Choose **GR00T DROID** (`127.0.0.1:5555`) or **OpenPI DROID**
   (`127.0.0.1:8000`). The profile identifies the client configuration, not a
   verified checkpoint running on that server.
3. Optionally enter a language instruction; leave it empty to use the task
   description. Select **Evaluate policy** to submit the frozen draft/profile.
4. Follow the job's progress or cancellation controls. The fixed profile uses
   one headless environment, enabled cameras and 1000 policy iterations, with
   a 900-second worker deadline. Settling steps are additional; iterations are
   not episodes. Video, variations and distributed execution are not exposed
   by this prototype profile.
5. Inspect the recorded episode count, measured metrics and warnings. A completed
   job is not manipulation success. No completed episodes is reported as no
   completed-episode evidence, with success unknown rather than a fabricated rate.
6. Download the report (`index.html`), episode records
   (`episode_results_rank0.jsonl`), and local telemetry (`eval_telemetry.ttl`)
   when produced. Downloads check the recorded byte size and SHA-256; HTML is
   downloaded as an attachment, not embedded in the API origin. HDF5/video
   downloads are not served by this prototype.

Web evaluation explicitly disables automatic Neo4j telemetry publication and
legacy version-tree lineage writes. It leaves local evaluation outputs intact;
the standalone CLI retains its existing defaults. Missing local telemetry is a
warning, not proof of publication. Actual GPU/policy-server execution has not yet
been verified for this web adapter. Focused tests and scoped independent review
pass, including artifact screening, download reactivation and empty episode files.
The test image lacks `rdflib`, so its mocked telemetry tests do not establish real
Turtle serialization; local TTL remains separately unverified.

### Snapshots

Request snapshots explicitly to render the scene and individual assets. Use
camera presets and 512/1024 resolution controls to inspect the result. Automatic
previews are optional and off by default. Edits can make existing images stale;
saved previews with unverified remote asset freshness are labelled historical.
Robot thumbnails show the authored joint pose, not simulated initial joints.

**Schema validity is not physical validity, and a rendered scene is not evidence
of policy success.** Snapshots use one environment and zero action steps. Use
**Evaluate policy** for the fixed prototype profiles above, or export the YAML
and use the linked CLI guides for other supported evaluation options.

The `/neo4j` page provides read-only queries against a separately configured
Neo4j database. These persisted query results are distinct from the editor's
authored graph. An unavailable database does not disable YAML editing.

### Task-driven trajectory assessment CLI

Inside the non-root simulation runtime, `isaaclab_arena_examples/tools/render_policy_trajectory.py`
captures one supplied task's policy rollout and retains a structured visual assessment.
It executes the configured policy and calls a model; it is not a readiness check.
Supply `--env_graph_spec_yaml` and `--policy_config_yaml_path`, plus the matching
`--policy_type`, `--remote_host` and `--remote_port` for the intended policy service.
The existing legacy policy/port defaults are retained; they do not discover the running service.
`--device` selects the simulator and environment-builder device. The Arena-side policy
device follows it unless explicitly overridden with `--policy_device` (for example,
`--device cuda:1 --policy_device cpu`). This does not select the remote policy server's device.

Use `--model` and optionally `--base_url` to select the assessment model, or use the
existing inference-backend configuration. Do not put credentials in command arguments.
`--camera_names` selects camera observation keys; omission captures available cameras.
`--num_steps` and `--frame_interval` bound the rollout and sampling, with a maximum
of 64 selected images. Captures include the initial observation and sampled observations
before termination, including the final budget step when it does not terminate.
Isaac Lab can auto-reset before returning a terminal step's observations: those frames
are omitted, and unavailable terminal imagery is recorded rather than presented as the
end of the trajectory. This tool does not install a pre-reset recording hook.

Each run needs a new `--out_dir`; omission creates a unique directory under
`eval_output/trajectory_assessments/`. The directory retains `spec.yaml`, PNG frames,
`capture.json` (actual step count and termination reason), and, on valid assessment,
`assessment.json` (model identifier, specification/image digests, observations and feedback).
Both receipts retain `policy_instruction`, the exact return from `policy.set_task_description`.
The environment's instruction is passed first; policy-specific fallback remains in the policy
when that instruction is null. The assessment prompt distinguishes this resolved instruction
from the authored specification, which remains unchanged even if their descriptions differ.
After capture completes, `capture.json` is written before policy/environment teardown.
If either teardown fails, the run fails, the completed capture evidence remains, and no
assessment model is called or `assessment.json` produced. Environment closure is still
attempted after a policy-close failure; there is no automatic retry or resume API.
The reusable implementations live in `isaaclab_arena/agentic_environment_generation/trajectory_capture.py`
and `trajectory_assessment.py`; importing the CLI does not start simulation.

Assessment status is `satisfactory`, `issues_detected`, or `inconclusive`. It is a VLM
observation, not measured task success or physical certification (`task_success` remains
unknown). No captured frames means an inconclusive receipt without a model call.
Malformed model responses fail rather than becoming accepted assessments; captured
evidence remains available. The tool does not automatically refine, publish to Neo4j,
invoke DCRG, or certify a repaired environment.

## Stop and troubleshoot

To stop only the workbench frontend and its owned API supervisor:

```bash
sh docker/workbench/run_workbench.sh stop --dev --diagnostics --port 3001
```

That command leaves Neo4j, Arena, and policy servers alone. If the fresh database
above is exclusively yours and no jobs need it, stop it separately with
`docker stop arena-envgen-neo4j`; later use `docker start arena-envgen-neo4j`.
Do not remove the persistent data volume or stop a shared research database.

- **No running runtime found:** start this clone's Arena container, then repeat
  `inspect`. Do not select an unrelated editor container.
- **Frontend loads but API is disconnected:** check `status`; serving the page
  does not prove the Python API is healthy.
- **Generation unavailable:** check API-process provider configuration, not
  browser settings or a repository `.env` file.
- **Neo4j unavailable:** check database readiness, the actual published Bolt
  port, authentication, and the API process environment. A healthy Neo4j Browser
  or a successful CLI connection does not prove the API has the same credentials.
- **Generation works but no priors appear:** check whether you used the dashboard
  refinement path, whether the database has eligible matching evidence, and
  whether retrieval reported a connection failure.
- **Rendering fails:** inspect the job's errors and check GPU availability,
  simulator permissions, and asset access. Do not kill unrelated GPU jobs.
- **API restart interrupted work:** inspect retained job state. Work without
  completion evidence must not be blindly rerun.
- **Queued work never starts after recovery:** inspect all pending jobs first.
  The current recovery control is under **Jobs & diagnostics**: enable the
  diagnostic controls, then select **Resume queued tests**. Despite that label,
  this resumes the shared queue, including generation and snapshot jobs. Do not
  resume unrelated pending work without its owner's approval.
- **Startup refuses an existing API socket:** do not blindly delete it. An
  unclean container shutdown can leave an owned stale socket. An operator must
  verify ownership, connection refusal, and exclusive lifecycle/state/socket
  locks before recovery. The API's `UnixListener` supports guarded stale-socket
  recovery, but the outer launcher currently refuses the socket before reaching
  that path; a supported launcher recovery command is still needed.

## Live validation record (2026-09-12)

The existing Arena and Neo4j containers were restarted with their data preserved;
this was **not** a fresh image build or a new-database installation test.
The workbench launched on port 3001 after guarded stale-socket recovery.

- Runtime web dependencies, API health, and actual dashboard Neo4j access passed.
- The database contained 28 environment graphs and 154 evaluation records.
  The mustard/table/DROID retrieval probe returned one measured prior,
  `droid_rubiks_cube_to_blue_bin`. This verifies retrieval, not a new policy result.
- 54 editor/query Python tests and 77 frontend tests passed; the TypeScript and
  production frontend build passed, with a large-bundle warning.
- The live Chromium suite reported five passed and one generation test skipped.
  Its render test accepted historical pixels while the new job was still queued;
  that assertion alone is **not** proof of fresh rendering.
- After explicitly resuming the single test job, snapshot job
  `f7f400077a594c41a85397089c7fcbb5` succeeded with no partial errors. All six asset
  images plus the scene decoded at 1024 × 1024. The fresh scene and upright robot
  thumbnail were visually inspected. The scene shows a floating mug: successful
  rendering does not establish physical validity of the default fixture.
- No model API key was present in the runtime. Live generation was intentionally
  left blocked; no inference or policy evaluation was performed.

Follow-up work includes a supported credential/recovery setup, visible shared-queue
state, a render test bound to the newly submitted job's artifacts, and a document
picker that distinguishes environment specs from policy/experiment YAML and
identifies duplicate names by version/path. Existing Neo4j ports in this reused
deployment are not loopback-only; this run did not change their network bindings.

## Temporary-key verification (2026-09-13)

The temporary-key feature is deployed on the local workbench. Verification passed:
245 workbench Python tests (one opt-in GPU test skipped), 122 frontend tests,
the production frontend/documentation builds, and independent security re-review.
The live browser run passed five checks, including saving a dummy key, session
isolation, reload, password clearing, unchanged job history, and **Forget key**;
live inference and GPU tests were deliberately skipped in that run. The dummy
marker was absent from the checked API state/log/revision files after the test.

No real credentials or successful provider inference were used to validate this
feature. An early unit-test transport mock missed the SDK's vendored HTTP client;
dummy-key requests received OpenAI 401 responses. Those tests were corrected to
intercept the actual SDK transport and deny socket connections. A configured
provider status remains distinct from verified model access.

## Further reading

- [Workbench runbook](../../docs/pages/example_workflows/agentic_env_gen/workbench.rst)
  — launch details, recovery, and verification records. Its older statement that
  standalone robot thumbnails are unavailable is superseded by the current renderer.
- [Workbench architecture](../../docs/pages/concepts/agentic_workbench.rst)
  — frontend/API ownership, jobs, storage, preview catalogue, and security boundaries.
- [Generation and evaluation overview](../../docs/pages/example_workflows/agentic_env_gen/index.rst)
  — CLI generation from scratch, building YAML environments, and evaluation.
- [Legacy Streamlit guide](../../docs/pages/example_workflows/agentic_env_gen/gui_runner.rst)
  — the older interface; the workbench does not yet replace every evaluation workflow.
