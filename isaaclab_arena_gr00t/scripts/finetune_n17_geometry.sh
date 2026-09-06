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
# Arms (the teacher is per-arm; see --teacher to override):
#   baseline        RGB, single frame                          -- the control
#   parallax        RGB, frames [-8, 0]                        -- motion parallax, no new data
#   align           single frame + SF, DA3METRIC-LARGE         -- metric geometry via alignment
#   align_anyview   single frame + SF, DA3-BASE                -- prices multi-view aggregation
#   align_cheap     single frame + SF, Depth-Anything-V2-Small -- the cheap floor
#   mix             single frame + 3D-Mix gated fusion         -- geometry as fused tokens
#   align_parallax  frames [-8, 0] + SF, DA3METRIC-LARGE       -- both
#
# Usage:
#   ./finetune_n17_geometry.sh --arm align --nproc-per-node 8
#   ./finetune_n17_geometry.sh --arm baseline --dry-run
#   ./finetune_n17_geometry.sh --arm align --align-loss-coeff 1.0 --pe-std 0.5   # a sweep point
#   ./finetune_n17_geometry.sh --arm baseline --tune-visual --reduced-color-jitter  # isolating control

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

# Teachers are cross-task assets, so they sit at the root of the models tree rather than under a
# task. Deliberately NOT $MODELS_DIR: that variable is commonly exported pointing at a task
# subdirectory (e.g. /models/isaaclab_arena/locomanipulation_tutorial), which would silently
# resolve the teacher to a path that does not exist.
TEACHER_ROOT="${GEOMETRY_TEACHER_ROOT:-/models/isaaclab_arena}"
TEACHER=""
ALIGN_SITE="post_vl_self_attention"
ALIGN_LOSS_COEFF=""
PE_STD=""
TUNE_VISUAL_OVERRIDE=""
REDUCED_JITTER_OVERRIDE=""

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
        --teacher) TEACHER="$2"; shift 2 ;;
        --align-site) ALIGN_SITE="$2"; shift 2 ;;
        --align-loss-coeff) ALIGN_LOSS_COEFF="$2"; shift 2 ;;
        --pe-std) PE_STD="$2"; shift 2 ;;
        --tune-visual) TUNE_VISUAL_OVERRIDE=true; shift ;;
        --no-tune-visual) TUNE_VISUAL_OVERRIDE=false; shift ;;
        --reduced-color-jitter) REDUCED_JITTER_OVERRIDE=true; shift ;;
        --full-color-jitter) REDUCED_JITTER_OVERRIDE=false; shift ;;
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

# ARM_TEACHER is the default for the arm; --teacher overrides it. Every geometry arm must name a
# teacher explicitly, because the model-side default is Depth-Anything-V2-Small: an arm that forgets
# to pass one trains against the cheap relative-depth encoder while its logs say "align", which is
# indistinguishable from a real DA3METRIC-LARGE run until the results are compared.
case "$ARM" in
    baseline)       MODALITY="$MODALITY_SINGLE";   GEOMETRY_MODE=off   ; TUNE_VISUAL=false; ARM_TEACHER="" ;;
    parallax)       MODALITY="$MODALITY_PARALLAX"; GEOMETRY_MODE=off   ; TUNE_VISUAL=false; ARM_TEACHER="" ;;
    align)          MODALITY="$MODALITY_SINGLE";   GEOMETRY_MODE=align ; TUNE_VISUAL=true ; ARM_TEACHER="${TEACHER_ROOT}/DA3METRIC-LARGE" ;;
    align_anyview)  MODALITY="$MODALITY_SINGLE";   GEOMETRY_MODE=align ; TUNE_VISUAL=true ; ARM_TEACHER="${TEACHER_ROOT}/DA3-BASE" ;;
    align_cheap)    MODALITY="$MODALITY_SINGLE";   GEOMETRY_MODE=align ; TUNE_VISUAL=true ; ARM_TEACHER="depth-anything/Depth-Anything-V2-Small-hf" ;;
    mix)            MODALITY="$MODALITY_SINGLE";   GEOMETRY_MODE=mix   ; TUNE_VISUAL=true ; ARM_TEACHER="${TEACHER_ROOT}/DA3METRIC-LARGE" ;;
    align_parallax) MODALITY="$MODALITY_PARALLAX"; GEOMETRY_MODE=align ; TUNE_VISUAL=true ; ARM_TEACHER="${TEACHER_ROOT}/DA3METRIC-LARGE" ;;
    *) echo "Unknown arm: $ARM" >&2; usage 1 ;;
esac

[[ -n "$TEACHER" ]] || TEACHER="$ARM_TEACHER"

# Visual tuning is a per-arm default, not a property of the arm, and the two are easy to confuse.
# The geometry arms enable it because the alignment loss acts on the backbone's image tokens; the
# RGB arms do not. That makes `baseline` vs `align` a comparison of *two* changes at once -- the
# geometry loss and whether the visual encoder is trainable -- so it cannot attribute a difference
# to Spatial Forcing. Overriding it is what makes an isolating control possible:
#
#   --arm baseline --tune-visual     the control for `align`: same trainable set, no geometry loss
#   --arm baseline                   the arm as originally defined, for continuity
#
# Recorded in the run line below either way, so a log says which was used.
if [[ -n "$TUNE_VISUAL_OVERRIDE" ]]; then
    TUNE_VISUAL="$TUNE_VISUAL_OVERRIDE"
fi
if [[ "$GEOMETRY_MODE" != "off" ]]; then
    [[ -n "$TEACHER" ]] || { echo "Arm '$ARM' needs a teacher; pass --teacher" >&2; exit 1; }
    # A local directory must exist; a bare HuggingFace id (no slash-prefixed path) is fetched by the
    # loader itself, so only path-shaped values are checked here.
    if [[ "$TEACHER" == /* && ! -d "$TEACHER" ]]; then
        echo "Teacher not found: $TEACHER" >&2
        echo "  fetch it with: hf download <repo> --local-dir $TEACHER" >&2
        exit 1
    fi
fi

for path in "$BASE_MODEL" "$DATASET_PATH" "$MODALITY" "$GR00T_ROOT/gr00t/experiment/launch_finetune.py"; do
    [[ -e "$path" ]] || { echo "Path does not exist: $path" >&2; exit 1; }
done

# Colour jitter perturbs the very images the geometry encoder reads, so saturation and hue -- which
# have no depth meaning -- are dropped for the geometry arms while brightness and contrast stay.
# The RGB arms keep the full set so they are not quietly given weaker augmentation.
#
# That fairness argument holds for each arm on its own, but it makes the arms differ in *two* ways
# at once, and augmentation strength moves success rate by itself. `--reduced-color-jitter` forces
# the geometry arms' weaker set onto an RGB arm, so a control can match `align` on augmentation as
# well as on the trainable set:
#
#   --arm baseline --tune-visual --reduced-color-jitter
#
# is the arm that differs from `align` in the geometry loss and nothing else.
if [[ -n "$REDUCED_JITTER_OVERRIDE" ]]; then
    REDUCED_JITTER="$REDUCED_JITTER_OVERRIDE"
elif [[ "$GEOMETRY_MODE" == "off" ]]; then
    REDUCED_JITTER=false
else
    REDUCED_JITTER=true
fi
if [[ "$REDUCED_JITTER" == "true" ]]; then
    COLOR_JITTER=(--color-jitter-params brightness 0.3 contrast 0.4)
else
    COLOR_JITTER=(--color-jitter-params brightness 0.3 contrast 0.4 saturation 0.5 hue 0.08)
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
if [[ "$GEOMETRY_MODE" != "off" ]]; then
    CMD+=(--geometry-encoder-id "$TEACHER" --geometry-align-site "$ALIGN_SITE")
    [[ -n "$ALIGN_LOSS_COEFF" ]] && CMD+=(--geometry-align-loss-coeff "$ALIGN_LOSS_COEFF")
    [[ -n "$PE_STD" ]] && CMD+=(--geometry-align-position-embedding-std "$PE_STD")
fi

if [[ "$TUNE_VISUAL" == "true" ]]; then
    CMD+=(--tune-visual)
else
    CMD+=(--no-tune-visual)
fi
[[ -n "$LEARNING_RATE" ]] && CMD+=(--learning-rate "$LEARNING_RATE")

echo "[finetune] arm=$ARM geometry_mode=$GEOMETRY_MODE tune_visual=$TUNE_VISUAL reduced_color_jitter=$REDUCED_JITTER gpus=$NPROC"
[[ "$GEOMETRY_MODE" != "off" ]] && echo "[finetune] teacher=$TEACHER align_site=$ALIGN_SITE"
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
