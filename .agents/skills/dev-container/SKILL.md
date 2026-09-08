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

Never hardcode the name. At the start of a session, resolve the container mounting this clone into `ARENA_CONTAINER` (empty result = none running, so start one below):

```bash
ARENA_CONTAINER=$(docker ps --filter "volume=$(git rev-parse --show-toplevel)" --format '{{.Names}}' | head -1)
```

Run the commands below in that same shell so `$ARENA_CONTAINER` stays set (or substitute the literal name).

## Start or attach

```bash
./docker/run_docker.sh
```

Idempotent: builds the (shared) image if it does not exist, starts this clone's container if it is not running, then attaches. The container name is auto-derived from the clone directory; pass `-s <suffix>` to override it.

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
