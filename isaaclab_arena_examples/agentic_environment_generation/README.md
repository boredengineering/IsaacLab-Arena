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

**Current integration boundary:** the dashboard refines its loaded YAML through
`refine_spec`, which does not retrieve Graph-RAG priors. From-scratch
`generate_spec` retrieves priors; use the CLI path below for that workflow.
Starting Neo4j enables persisted graph inspection but does not automatically make
every dashboard generation graph-backed.

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

## 5. Configure model access

### Temporary dashboard key (recommended for local interactive use)

Use the provider-settings panel beside generation:

1. Choose OpenAI, Gemini, OpenRouter, or NVIDIA. Check the displayed destination
   endpoint; browser-entered keys cannot use a custom URL.
2. Enter a model ID and choose **Key expiration**: 15 minutes, 30 minutes
   (default), 1 hour, or 2 hours. Then read and accept the temporary-use notice.
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
invalidate queued jobs bound to the old reference. There is no unlimited option.
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

With model access configured:

1. Load a valid starting document.
2. Enter a prompt, for example:

   > Keep the DROID robot and maple table. Place the cube and bowl on the table,
   > and make the task pick up the cube and place it in the bowl.

3. Click **Generate spec** and follow the job status.
4. Review the returned YAML and warnings, then click **Apply generated YAML**.
5. Check validation and **Save revision** / export again.

The current dashboard submits the editor YAML as the generation base: this
refines the loaded environment rather than always generating from scratch.
Applying a result changes only the editor draft. Generated drafts are **not
published to Neo4j**, and generation does not run simulation or policy evaluation.

Do not resubmit an expensive job just because a browser connection was lost.
Submitted jobs survive browser refreshes; recover the existing job status first.
An unresolved retry keeps its original credential reference even if you save a
replacement key. If it cannot be accepted, inspect the job journal first, then use
**Discard unresolved request** and acknowledge the warning before starting a new
request. Discard clears this tab's retry information only; it does not cancel or
delete an already-accepted job.

### From-scratch Graph-RAG generation (CLI)

For actual prior retrieval, run the following **inside the non-root Arena shell**
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

## 7. Render and evaluate

Request snapshots explicitly to render the scene and individual assets. Use
camera presets and 512/1024 resolution controls to inspect the result. Automatic
previews are optional and off by default. Edits can make existing images stale;
saved previews with unverified remote asset freshness are labelled historical.
Robot thumbnails show the authored joint pose, not simulated initial joints.

**Schema validity is not physical validity, and a rendered scene is not evidence
of policy success.** Snapshots use one environment and zero action steps. Export
the YAML and follow the separate [GR00T](../../docs/pages/example_workflows/agentic_env_gen/eval_with_gr00t.rst)
or [OpenPI](../../docs/pages/example_workflows/agentic_env_gen/eval_with_openpi.rst)
workflow for actual policy evaluation.

The `/neo4j` page provides read-only queries against a separately configured
Neo4j database. These persisted query results are distinct from the editor's
authored graph. An unavailable database does not disable YAML editing.

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
