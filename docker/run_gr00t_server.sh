#!/usr/bin/env bash
# ==============================================================================
# Build (if needed) and run the NVIDIA Isaac-GR00T policy server in Docker.
# ==============================================================================
#
# Usage:
#   ./docker/run_gr00t_server.sh [options]
#
# Examples:
#   ./docker/run_gr00t_server.sh -m nvidia/GR00T-N1.6-DROID -e OXE_DROID
#   ./docker/run_gr00t_server.sh -m nvidia/GR00T-N1.6-3B -e NEW_EMBODIMENT -p 5556
#   ./docker/run_gr00t_server.sh -d       # Run detached in background
#   ./docker/run_gr00t_server.sh -k       # Stop running server
#   ./docker/run_gr00t_server.sh -r       # Force image rebuild
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${WORKSPACE_DIR}" ]; then
  curr="${SCRIPT_DIR}"
  while [ "${curr}" != "/" ]; do
    if [ -d "${curr}/.git" ] || [ -d "${curr}/.agents" ]; then
      WORKSPACE_DIR="${curr}"
      break
    fi
    curr="$(dirname "${curr}")"
  done
fi
WORKSPACE_DIR="${WORKSPACE_DIR:-${SCRIPT_DIR}/..}"

IMAGE_NAME="gr00t-dev"
IMAGE_TAG="latest"
CONTAINER_NAME="gr00t-server"

MODEL_PATH="nvidia/GR00T-N1.6-DROID"
EMBODIMENT_TAG="OXE_DROID"
PORT="5556"
DEVICE="cuda"
DETACHED=false
FORCE_REBUILD=false
STOP_ONLY=false
MODALITY_CONFIG=""
SDPA_MODE=""
EXTRA_ARGS=()

print_help() {
    echo "Helper script to build and run the NVIDIA Isaac-GR00T inference server in Docker."
    echo ""
    echo "Usage:"
    echo "  $(basename "$0") [options] [-- extra uv/python args]"
    echo ""
    echo "Options:"
    echo "  -m <model_path>           HuggingFace model ID or local checkpoint path (default: ${MODEL_PATH})"
    echo "  -e <embodiment_tag>       Embodiment tag (e.g. OXE_DROID, NEW_EMBODIMENT, GR1) (default: ${EMBODIMENT_TAG})"
    echo "  -c <modality_config_path> Optional path to modality config python script"
    echo "  -p <port>                 ZeroMQ port to serve on (default: ${PORT})"
    echo "  -d                        Run container in background (detached mode)"
    echo "  -k                        Stop and remove running ${CONTAINER_NAME} container"
    echo "  -r                        Force rebuild of the ${IMAGE_NAME}:${IMAGE_TAG} image"
    echo "  -s                        Enable PyTorch SDPA math fallback (GR00T_DIT_SDPA_MODE=math)"
    echo "  -h                        Show this help and exit"
}

while getopts ":m:e:c:p:dkrsh" opt; do
    case "$opt" in
        m) MODEL_PATH="$OPTARG" ;;
        e) EMBODIMENT_TAG="$OPTARG" ;;
        c) MODALITY_CONFIG="$OPTARG" ;;
        p) PORT="$OPTARG" ;;
        d) DETACHED=true ;;
        k) STOP_ONLY=true ;;
        r) FORCE_REBUILD=true ;;
        s) SDPA_MODE="math" ;;
        h) print_help; exit 0 ;;
        \?) echo "Unknown option: -$OPTARG" >&2; print_help; exit 1 ;;
        :) echo "Option -$OPTARG requires an argument." >&2; exit 1 ;;
    esac
done
shift $((OPTIND-1))
EXTRA_ARGS=("$@")

# Stop handler
if [ "$STOP_ONLY" = true ]; then
    if docker ps -q --filter "name=^${CONTAINER_NAME}$" | grep -q .; then
        echo "Stopping ${CONTAINER_NAME}..."
        docker stop "${CONTAINER_NAME}" >/dev/null
    fi
    if docker ps -a -q --filter "name=^${CONTAINER_NAME}$" | grep -q .; then
        echo "Removing ${CONTAINER_NAME}..."
        docker rm "${CONTAINER_NAME}" >/dev/null
    fi
    echo "✓ ${CONTAINER_NAME} stopped."
    exit 0
fi

# Rebuild or build image if missing
GR00T_SUBMODULE="${WORKSPACE_DIR}/submodules/Isaac-GR00T"
if [ ! -d "${GR00T_SUBMODULE}" ]; then
    echo "❌ Error: Submodule not found at ${GR00T_SUBMODULE}. Run: git submodule update --init --recursive" >&2
    exit 1
fi

if [ "$FORCE_REBUILD" = true ] || [ -z "$(docker images -q "${IMAGE_NAME}:${IMAGE_TAG}" 2>/dev/null)" ]; then
    echo "🔨 Building Docker image ${IMAGE_NAME}:${IMAGE_TAG}..."
    docker build \
        -t "${IMAGE_NAME}:${IMAGE_TAG}" \
        --file "${GR00T_SUBMODULE}/docker/Dockerfile" \
        "${GR00T_SUBMODULE}"
else
    echo "Docker image ${IMAGE_NAME}:${IMAGE_TAG} already exists. (Use -r to force rebuild)"
fi

# Remove any previously exited/stale container
if docker ps -a -q --filter "name=^${CONTAINER_NAME}$" | grep -q .; then
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
fi

# Prepare mounts
MODELS_DIR="${MODELS_DIR:-$HOME/models}"
HF_CACHE_DIR="${HF_CACHE_DIR:-$HOME/.cache/huggingface}"
mkdir -p "${MODELS_DIR}" "${HF_CACHE_DIR}"

DOCKER_ENV=(
    "--env" "HF_HOME=/root/.cache/huggingface"
)

if [ -n "${HF_TOKEN:-}" ]; then
    DOCKER_ENV+=("--env" "HF_TOKEN=${HF_TOKEN}")
fi

if [ -n "${SDPA_MODE}" ]; then
    DOCKER_ENV+=("--env" "GR00T_DIT_SDPA_MODE=${SDPA_MODE}")
fi

DOCKER_VOLUMES=(
    "-v" "${WORKSPACE_DIR}:/workspaces/isaaclab_arena"
    "-v" "${GR00T_SUBMODULE}:/workspace/gr00t"
    "-v" "${MODELS_DIR}:/workspace/pretrained_ckpts"
    "-v" "${MODELS_DIR}:/models"
    "-v" "${HF_CACHE_DIR}:/root/.cache/huggingface"
)

CMD_ARGS=(
    "--model-path" "${MODEL_PATH}"
    "--embodiment-tag" "${EMBODIMENT_TAG}"
    "--device" "${DEVICE}"
    "--host" "127.0.0.1"
    "--port" "${PORT}"
)

if [ -n "${MODALITY_CONFIG}" ]; then
    if [[ "${MODALITY_CONFIG}" = /* ]]; then
        CONTAINER_MODALITY_PATH="${MODALITY_CONFIG}"
    else
        CONTAINER_MODALITY_PATH="/workspaces/isaaclab_arena/${MODALITY_CONFIG}"
    fi
    CMD_ARGS+=("--modality-config-path" "${CONTAINER_MODALITY_PATH}")
fi

RUN_MODE="-it"
if [ "$DETACHED" = true ]; then
    RUN_MODE="-d"
fi

echo "🚀 Launching ${CONTAINER_NAME} on port ${PORT} (Model: ${MODEL_PATH}, Embodiment: ${EMBODIMENT_TAG})..."

docker run ${RUN_MODE} \
    --name "${CONTAINER_NAME}" \
    --gpus all \
    --network host \
    --ipc host \
    "${DOCKER_ENV[@]}" \
    "${DOCKER_VOLUMES[@]}" \
    "${IMAGE_NAME}:${IMAGE_TAG}" \
    uv run python gr00t/eval/run_gr00t_server.py \
        "${CMD_ARGS[@]}" \
        "${EXTRA_ARGS[@]}"

if [ "$DETACHED" = true ]; then
    echo "✓ ${CONTAINER_NAME} is running in background on port ${PORT}."
    echo "  - View logs:   docker logs -f ${CONTAINER_NAME}"
    echo "  - Stop server: ./docker/run_gr00t_server.sh -k"
fi
