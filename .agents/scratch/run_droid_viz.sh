#!/usr/bin/env bash
# Run from the editor/host terminal; discover this clone's simulator by its host mount.
set -euo pipefail
HOST_REPO=${HOST_REPO:-/home/tarfy/Documents/GitHub/BoredEngineer/IsaacLab-Arena}
ARENA_CONTAINER=${ARENA_CONTAINER:-$(docker ps --filter "volume=$HOST_REPO" --filter ancestor=isaaclab_arena:latest --format '{{.Names}}')}
: "${ARENA_CONTAINER:?No running simulator found for this clone}"
[[ "$ARENA_CONTAINER" != *$'\n'* ]] || { printf 'Multiple simulator containers matched; set ARENA_CONTAINER explicitly.\n' >&2; exit 1; }
: "${DISPLAY:?Set DISPLAY to the verified desktop display}"
docker exec -u ubuntu:1234 "$ARENA_CONTAINER" mkdir -p \
    /tmp/arena-droid-assets-20260909 /tmp/arena-droid-kit-20260909
exec docker exec -u ubuntu:1234 \
    -e DISPLAY="$DISPLAY" -e HOME=/home/ubuntu \
    -e TMPDIR=/tmp/arena-droid-assets-20260909 \
    -e OMNICLIENT_HUB_MODE=disabled -e PYTHONUNBUFFERED=1 \
    -w /workspaces/isaaclab_arena \
    "$ARENA_CONTAINER" /isaac-sim/python.sh \
    isaaclab_arena/evaluation/policy_runner.py \
    --viz kit \
    --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
    --policy_config_yaml_path /workspaces/isaaclab_arena/generated_envs/droid_apple_to_wooden_bowl/latest/policy_config.yaml \
    --remote_host 127.0.0.1 --remote_port 5559 \
    --num_steps 2000 --num_envs 1 --enable_cameras \
    --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_apple_to_wooden_bowl/latest/droid_apple_to_wooden_bowl.yaml \
    --output_base_dir /workspaces/isaaclab_arena/eval_output/droid_apple_to_wooden_bowl/viz_run \
    --kit_args '--portable --portable-root /tmp/arena-droid-kit-20260909'
