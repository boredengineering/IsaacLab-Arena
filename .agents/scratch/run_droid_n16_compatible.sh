#!/usr/bin/env bash
# Local, transport-only N1.6-DROID launch; no model or submodule edits.
set -euo pipefail
HOST_REPO=${HOST_REPO:-/home/tarfy/Documents/GitHub/BoredEngineer/IsaacLab-Arena}
HOST_HF_CACHE=${HOST_HF_CACHE:-/root/.cache/huggingface}
SERVER_NAME=${SERVER_NAME:-gr00t-server}
# Refuse to silently destroy an existing container. Stop/rename it explicitly first.
if docker container inspect "$SERVER_NAME" >/dev/null 2>&1; then
    printf '%s\n' "Container $SERVER_NAME already exists; stop/rename it before launching." >&2
    exit 1
fi

docker run -d --name "$SERVER_NAME" --gpus all --network host --ipc host \
    --workdir /workspace/gr00t \
    --env HF_HOME=/cache/huggingface \
    --env HF_HUB_OFFLINE=1 \
    --env GR00T_DIT_SDPA_MODE=math \
    --env PYTHONUNBUFFERED=1 \
    --env HOME=/tmp/gr00t-home \
    --env PYTHONPATH=/workspace/gr00t/.venv/lib/python3.10/site-packages:/workspace/gr00t \
    --mount "type=bind,source=$HOST_HF_CACHE,target=/cache/huggingface,readonly" \
    --mount "type=bind,source=$HOST_REPO,target=/workspaces/isaaclab_arena,readonly" \
    --mount "type=bind,source=$HOST_REPO/submodules/Isaac-GR00T/gr00t/policy/server_client.py,target=/workspace/gr00t/gr00t/policy/server_client.py,readonly" \
    --entrypoint /bin/bash gr00t-dev:latest -c '
        set -euo pipefail
        # The image stores its Python under root-only /root. Relocate just the
        # interpreter, rather than opening root permissions or running inference as root.
        cp -a /root/.local/share/uv/python/cpython-3.10.21-linux-x86_64-gnu /opt/arena-python
        mkdir -p /tmp/gr00t-home
        chown 1000:1000 /tmp/gr00t-home
        exec setpriv --reuid=1000 --regid=1000 --clear-groups \
            /opt/arena-python/bin/python3.10 gr00t/eval/run_gr00t_server.py \
            --model-path nvidia/GR00T-N1.6-DROID \
            --embodiment-tag OXE_DROID --device cuda --host 127.0.0.1 --port 5559
    '
