# Container resource limits

`resource_limits.py` is a Python 3 standard-library helper. It reads only
`docker info --format '{{.MemTotal}}'` from the selected Docker daemon, not the
editor's cgroup or a potentially different client's `/proc/meminfo`. Discovery
failure stops launch; there is no unlimited fallback or user-supplied capacity.

| Role | Memory cap | PID cap |
| --- | --- | --- |
| Editor | min(8 GiB, 10% daemon RAM) | 512 |
| Arena | min(56 GiB, 60% daemon RAM) | 2048 |
| Frontend | min(4 GiB, 5% daemon RAM) | 256 |

Integer arithmetic rounds down to bytes. Memory-plus-swap equals memory for
all three roles, so they cannot add swap above their memory allowance. The sum
for **one container of each role** is at most 75% of daemon RAM. This reserves
at least 25% for other host activity; it is not a guarantee that unrelated
services, concurrent clones, build processes, or host-network/shared-IPC
resources fit in the remainder. GR00T and Neo4j are not changed by this policy.
Docker must support memory, swap and PID cgroup controls. Daemon RAM changes
require fresh preflight and an explicitly approved container reconfiguration.

## Editor

The existing Dockerfile/runArgs devcontainer keeps explicit 8 GiB memory and
swap flags. `initializeCommand` validates the actual flags against the current
budget before any directory-creation fallback. The default therefore requires
at least 80 GiB daemon RAM. On smaller machines lower **both** numeric memory
flags in `.devcontainer/devcontainer.json` to the helper's `EDITOR_MEMORY_BYTES`
(or lower); the preflight validates that choice. PID limits must remain positive
and at most 512.

This deliberate bounded default avoids switching the editor to Compose or
rewriting its configuration from an initialization hook. A generated `--env-file`
sets container environment, not Docker resource options; a child initialization
command cannot export values into the already-running Dev Containers client's
`${localEnv:...}` substitutions. No generated configuration or extra host package
is required. The preflight requires the already-supported Python 3 and Docker CLI.
It does not update an existing container on attach.

## Arena and Compose

`run_docker.sh` computes fresh budgets before its existing build/removal logic
and passes memory, memory-swap and PID flags when creating an Arena container.
Inherited budget variables are overwritten. Attaching to an existing container
does not change that container's resources.

Compose has no host-command preflight hook. Its resource fields deliberately
require a value rather than silently defaulting to unlimited. For direct Compose
use, refresh exports **in the same shell immediately before the invocation**.
For example, this only validates configuration (it starts nothing):

```bash
RESOURCE_ENV=$(python3 docker/resource_limits.py) &&
  eval "$RESOURCE_ENV" &&
  docker compose --env-file /dev/null -f docker/docker-compose.sim.yml config --quiet
```

Keep the assignment separate from `eval`: `eval "$(failing-command)"` can conceal
a failed preflight. Do not hand-set resource variables or reuse exports after
changing Docker context/host capacity. Direct Docker/Compose use or edited
configuration can bypass this policy; it is not a daemon-global admission system.
The Workbench launcher overwrites its Compose environment with
`resource_environment()` for configuration, build and startup; both frontend
modes inherit the base Compose resource limits. Non-creating `ps` and `stop`
commands instead use a numeric interpolation-only value, so capacity discovery
cannot block observation or cleanup. That value never changes container limits.
Explicit stop and startup rollback attempt API shutdown even if frontend stop
fails.

## Host-only verification

```bash
python3 -m unittest discover -s docker -p test_resource_limits.py -v
bash -n docker/run_docker.sh
python3 docker/resource_limits.py --check-editor
```

The tests import no Arena/simulation packages. Compose config tests use a
nonexistent daemon socket and a sanitized environment, never create containers,
and are skipped if the Docker CLI is absent. No live update/recreate is performed
by the helper or tests.
