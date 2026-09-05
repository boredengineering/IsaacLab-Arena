#!/usr/bin/env bash
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
# Launch a GR00T N1.7 finetune arm for the geometry-conditioning comparison.
#
# One entry point for every arm so the arms differ only in the flags recorded here, rather than in
# whatever each invocation happened to be typed with. Runs identically on one local GPU and on a
# cloud instance with up to eight, since only --nproc-per-node changes.
#
# Arms:
#   baseline        RGB, single frame                     -- the control
#   parallax        RGB, frames [-8, 0]                   -- motion parallax, no new data
#   align           single frame + Spatial Forcing        -- geometry via alignment loss
#   mix             single frame + 3D-Mix gated fusion    -- geometry as fused tokens
#   align_parallax  frames [-8, 0] + Spatial Forcing      -- both
#
# Usage:
#   ./finetune_n17_geometry.sh --arm align --nproc-per-node 8
#   ./finetune_n17_geometry.sh --arm baseline --dry-run

set -euo pipefail

ARM=""
NPROC=1
MAX_STEPS=20000
GLOBAL_BATCH_SIZE=64
LEARNING_RATE=""
BASE_MODEL="${BASE_MODEL:-/models/isaaclab_arena/static_apple_tutorial/gn1x_tuned_static_apple}"
DATASET_PATH="${DATASET_PATH:-/datasets/isaaclab_arena/static_apple_tutorial/lerobot}"
EMBODIMENT_TAG="${EMBODIMENT_TAG:-new_embodiment}"
OUTPUT_ROOT="${OUTPUT_ROOT:-/models/isaaclab_arena/static_apple_tutorial/geometry_arms}"
GR00T_ROOT="${GR00T_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../submodules/Isaac-GR00T" && pwd)}"
MODALITY_DIR="${MODALITY_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../embodiments/g1" && pwd)}"
DRY_RUN=false

usage() {
    sed -n '7,23p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --arm) ARM="$2"; shift 2 ;;
        --nproc-per-node) NPROC="$2"; shift 2 ;;
        --max-steps) MAX_STEPS="$2"; shift 2 ;;
        --global-batch-size) GLOBAL_BATCH_SIZE="$2"; shift 2 ;;
        --learning-rate) LEARNING_RATE="$2"; shift 2 ;;
        --base-model) BASE_MODEL="$2"; shift 2 ;;
        --dataset-path) DATASET_PATH="$2"; shift 2 ;;
        --output-root) OUTPUT_ROOT="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown argument: $1" >&2; usage 1 ;;
    esac
done

[[ -n "$ARM" ]] || { echo "--arm is required" >&2; usage 1; }
if ! [[ "$NPROC" =~ ^[1-8]$ ]]; then
    echo "--nproc-per-node must be 1-8 (got '$NPROC')" >&2
    exit 1
fi

# Per-arm flags. Selecting the modality config by path is what switches the temporal image stack:
# the two config modules both register NEW_EMBODIMENT and are mutually exclusive.
MODALITY_SINGLE="${MODALITY_DIR}/g1_sim_wbc_data_gr00t_n_1_7_config.py"
MODALITY_PARALLAX="${MODALITY_DIR}/g1_sim_wbc_data_gr00t_n_1_7_parallax_config.py"

case "$ARM" in
    baseline)       MODALITY="$MODALITY_SINGLE";   GEOMETRY_MODE=off   ; TUNE_VISUAL=false ;;
    parallax)       MODALITY="$MODALITY_PARALLAX"; GEOMETRY_MODE=off   ; TUNE_VISUAL=false ;;
    align)          MODALITY="$MODALITY_SINGLE";   GEOMETRY_MODE=align ; TUNE_VISUAL=true  ;;
    mix)            MODALITY="$MODALITY_SINGLE";   GEOMETRY_MODE=mix   ; TUNE_VISUAL=true  ;;
    align_parallax) MODALITY="$MODALITY_PARALLAX"; GEOMETRY_MODE=align ; TUNE_VISUAL=true  ;;
    *) echo "Unknown arm: $ARM" >&2; usage 1 ;;
esac

for path in "$BASE_MODEL" "$DATASET_PATH" "$MODALITY" "$GR00T_ROOT/gr00t/experiment/launch_finetune.py"; do
    [[ -e "$path" ]] || { echo "Path does not exist: $path" >&2; exit 1; }
done

# Colour jitter perturbs the very images the geometry encoder reads, so saturation and hue -- which
# have no depth meaning -- are dropped for the geometry arms while brightness and contrast stay.
# The RGB arms keep the full set so they are not quietly given weaker augmentation.
if [[ "$GEOMETRY_MODE" == "off" ]]; then
    COLOR_JITTER=(--color-jitter-params brightness 0.3 contrast 0.4 saturation 0.5 hue 0.08)
else
    COLOR_JITTER=(--color-jitter-params brightness 0.3 contrast 0.4)
fi

OUTPUT_DIR="${OUTPUT_ROOT}/${ARM}"

CMD=(
    torchrun --standalone --nnodes 1 --nproc-per-node "$NPROC"
    "$GR00T_ROOT/gr00t/experiment/launch_finetune.py"
    --base-model-path "$BASE_MODEL"
    --dataset-path "$DATASET_PATH"
    --embodiment-tag "$EMBODIMENT_TAG"
    --modality-config-path "$MODALITY"
    --geometry-mode "$GEOMETRY_MODE"
    --output-dir "$OUTPUT_DIR"
    --num-gpus "$NPROC"
    --global-batch-size "$GLOBAL_BATCH_SIZE"
    --max-steps "$MAX_STEPS"
    --no-tune-llm
    --tune-projector
    --tune-diffusion-model
    "${COLOR_JITTER[@]}"
)
if [[ "$TUNE_VISUAL" == "true" ]]; then
    CMD+=(--tune-visual)
else
    CMD+=(--no-tune-visual)
fi
[[ -n "$LEARNING_RATE" ]] && CMD+=(--learning-rate "$LEARNING_RATE")

echo "[finetune] arm=$ARM geometry_mode=$GEOMETRY_MODE tune_visual=$TUNE_VISUAL gpus=$NPROC"
echo "[finetune] modality=$MODALITY"
echo "[finetune] output=$OUTPUT_DIR"
printf '[finetune] %q ' "${CMD[@]}"; echo

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[finetune] --dry-run set; not launching."
    exit 0
fi

mkdir -p "$OUTPUT_DIR"
cd "$GR00T_ROOT"
exec "${CMD[@]}"
