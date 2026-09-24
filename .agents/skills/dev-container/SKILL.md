---
name: dev-container
description: Sets up and manages the isaaclab_arena Docker container — the single environment used for Arena's development, testing, training, and evaluation. Use when the user asks to set up the dev environment, bootstrap the project, get started on a fresh clone, start developing, build or rebuild the image, start or attach to the container, or run any command inside it. Also covers ./docker/run_docker.sh flag combinations (-r rebuild, -R rebuild without cache, -d/-m/-e custom dataset/model/eval mounts), docker exec usage, and the /isaac-sim/python.sh aliasing.
allowed-tools: Bash(./docker/run_docker.sh *) Bash(docker exec *) Bash(docker images *) Bash(docker ps *)
---

# Dev Container

Arena package execution uses the simulation container. This checkout also supports a separate
editor/agent devcontainer, a GR00T policy server, and Neo4j. Do not mistake a running editor
container for a working simulator. The current DCRG runtime procedure is documented in
`docs/pages/example_workflows/agentic_env_gen/dcrg.rst`.

Each clone of the repo on the host machine gets its own container, so separate clones can run in parallel. The image (`isaaclab_arena:latest`) is shared, but the container name is `isaaclab_arena-latest` for the folder named `IsaacLab-Arena` and `isaaclab_arena-latest-<suffix>` for folders named `IsaacLab-Arena_<suffix>` (`run_docker.sh` derives the suffix automatically).

## Discover this clone's container (once per session)

Never hardcode the name or take the first volume match. Use `terminal` to list
running **and stopped** candidates, then inspect their mount destinations, mode,
image and command. Inside an editor container, first map this checkout to its
host source path as described below. Select the simulator with the same-clone RW
bind at `/workspaces/isaaclab_arena`, not the editor or read-only policy mount.

```bash
docker ps -a --format '{{.ID}} {{.Names}} {{.Image}} {{.Status}}'
```

Set `ARENA_CONTAINER` to the verified exact ID. An empty running-container list
does not establish that the container is absent or needs rebuilding.

## Start or attach

```bash
./docker/run_docker.sh
```

Use this launcher for initial creation or an intentional recreation. It builds
the shared image if absent and attaches to an existing running container, but
**removes an exited container before recreating it**. It is not a lossless restart
of a stopped container. The name is auto-derived from the clone directory; pass
`-s <suffix>` to override it.

For an existing verified container, prefer `docker start "$ARENA_CONTAINER"`
through `terminal` when startup is authorized. This preserves its image, mounts,
command, model caches and writable layer. Read its exact state back afterward.

## Restore the existing simulator, policy and database stack

- Treat an explicit request to start the existing stack as startup authority;
  do not ask the user to perform the same documented restart manually. Keep a
  genuinely narrower no-shared-service scope separate from stack restoration.
- Inspect only projected state, image, mounts, ports, user, device requests and
  restart policy; never dump `Config.Env` or credentials. Correlate stop times
  with host boot. Exit 137 alone does not prove OOM; check `OOMKilled` and do not
  invent a stop cause when historical Docker events are unavailable.
- Discover GR00T and Neo4j by their existing mounts, images and ports. Follow
  `docs/pages/example_workflows/agentic_env_gen/dcrg.rst` and
  `docs/pages/example_workflows/agentic_env_gen/eval_with_gr00t.rst`; preserve the
  deployed GR00T model/embodiment and Neo4j volumes. Start exact verified IDs
  without rebuilding, replacing data, changing restart policies or replaying jobs.
- A simulator container may intentionally run `sleep infinity`: start a bounded
  non-root headless `AppLauncher`/`SimulationContext` check with real reset/steps
  and clean close, rather than leaving an unrelated simulator workload running.
  Preserve the non-root image group and user-owned caches described below.
- Verify GR00T's actual deployed port using `PolicyClient`'s `ping` endpoint and
  `get_modality_config()`. Modality configs are dataclasses, not Pydantic models;
  report `delta_indices`/`modality_keys`, not `model_dump()` or arbitrary nested
  `vars()` JSON. Ping/schema readiness is not an inference acceptance result.
- Verify Neo4j's mapped HTTP discovery endpoint and Bolt connectivity without
  reading credentials or writing graph data. Do not call a TCP connection an
  authenticated query. Keep shared-service readiness separate from isolated
  S2 initialization evidence and GPU restrictions.
- Leave requested shared services running; close only owned smoke processes.
  Retain results and retry unchanged dependent discovery before proposing any
  alternate discovery semantics. A `no` restart policy explains why a service
  stays down after reboot; changing that policy is a separate persistent change.

## Common flag combinations

| Flag | Purpose |
|---|---|
| `-r` | Force image rebuild |
| `-R` | Force image rebuild **without cache** |
| `-d <path>` | Mount a custom dataset directory |
| `-m <path>` | Mount a custom model directory |
| `-e <path>` | Mount a custom eval directory |

Example with custom mounts:

```bash
./docker/run_docker.sh -d ~/datasets -m ~/models -e ~/eval
```

## Run a command in the already-running container

```bash
docker exec "$ARENA_CONTAINER" su $(id -un) -c \
  "cd /workspaces/isaaclab_arena && <command>"
```

The repo root is mounted at `/workspaces/isaaclab_arena` inside the container.

## Python invocation

Inside the container, `python` is aliased to `/isaac-sim/python.sh`. Both forms work, but **prefer `/isaac-sim/python.sh` explicitly** in `docker exec` invocations from outside the container, where the alias is not active.

## Verify

A container is up and importable when:

```bash
docker exec "$ARENA_CONTAINER" su $(id -un) -c \
  "/isaac-sim/python.sh -c 'import isaaclab_arena; print(isaaclab_arena.__file__)'"
```

prints a path under `/workspaces/isaaclab_arena/`.

## Nested-container discovery and non-root runtime

- Inside an editor devcontainer, `git rev-parse --show-toplevel` is a container path,
  not necessarily the host source path used by Docker. Inspect the editor's mounts to
  obtain the host clone path, then select the simulator mounting that same source.
- Inspect `/isaac-sim` permissions and use the image's read group with the non-root
  user when necessary. An inaccessible directory can make extension discovery report
  `SimulationApp=None` even though the extension is installed.
- Give non-root runs a user-owned `TMPDIR` for public USD downloads. A root-owned
  cached USD may otherwise be reused and fail as an apparently missing rigid body.
- Use Kit's documented `--portable --portable-root <writable-directory>` through
  `--kit_args` for writable runtime caches. If Hub startup fails, the documented
  per-process `OMNICLIENT_HUB_MODE=disabled` setting is an alternative.
- Verify an actual scene launch after imports. A container healthcheck that only
  searches for an old Kit log is not proof of current simulator readiness.
