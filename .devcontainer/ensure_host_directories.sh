#!/usr/bin/env bash
# ==============================================================================
# Ensure Host Directories for IsaacLab-Arena & Physical AI DevContainer
# ==============================================================================
# This script runs on the HOST (via devcontainer initializeCommand or CLI)
# to guarantee all required persistence directories exist with correct
# user permissions BEFORE Docker volume mounting occurs.
# ==============================================================================

set -euo pipefail

HOST_HOME="${HOME:-/home/$(id -un)}"

echo "🔍 [IsaacLab-Arena] Checking host directories for DevContainer persistence..."

# Core Host Directories & Tutorial Subdirectories
DIRECTORIES=(
    # Core Mounts
    "${HOST_HOME}/datasets"
    "${HOST_HOME}/models"
    "${HOST_HOME}/eval"
    
    # Standard IsaacLab-Arena Workflow Subpaths
    "${HOST_HOME}/datasets/isaaclab_arena/locomanipulation_tutorial"
    "${HOST_HOME}/datasets/isaaclab_arena/sequential_static_manipulation_tutorial"
    "${HOST_HOME}/datasets/isaaclab_arena/static_apple_tutorial"
    "${HOST_HOME}/models/isaaclab_arena/locomanipulation_tutorial"
    "${HOST_HOME}/models/isaaclab_arena/sequential_static_manipulation_tutorial"
    "${HOST_HOME}/models/isaaclab_arena/dexsuite_lift"
    "${HOST_HOME}/models/isaaclab_arena/reinforcement_learning"
    "${HOST_HOME}/models/isaaclab_arena/static_apple_tutorial"
    "${HOST_HOME}/eval/isaaclab_arena/locomanipulation_tutorial"
    "${HOST_HOME}/eval/isaaclab_arena/camera_sensitivity"
    
    # Caches & Hugging Face
    "${HOST_HOME}/.cache/huggingface"
    
    # Cloud Credentials & Tooling Configs
    "${HOST_HOME}/.aws"
    "${HOST_HOME}/.config/gcloud"
    "${HOST_HOME}/.azure"
    "${HOST_HOME}/.config/gh"
    "${HOST_HOME}/.config/osmo"
    "${HOST_HOME}/.cloudxr"
    "${HOST_HOME}/.nvidia-omniverse"
)

CREATED_COUNT=0
EXISTING_COUNT=0

for dir in "${DIRECTORIES[@]}"; do
    if [ ! -d "${dir}" ]; then
        mkdir -p "${dir}"
        echo "  [+] Created:  ${dir}"
        CREATED_COUNT=$((CREATED_COUNT + 1))
    else
        EXISTING_COUNT=$((EXISTING_COUNT + 1))
    fi
    # Touch verification marker for core mounts
    case "${dir}" in
        */datasets/isaaclab_arena/*|*/models/isaaclab_arena/*|*/eval/isaaclab_arena/*)
            touch "${dir}/.mount_verified" 2>/dev/null || true
            ;;
    esac
done

echo "✓ Host directory check complete: ${EXISTING_COUNT} existing, ${CREATED_COUNT} created."
