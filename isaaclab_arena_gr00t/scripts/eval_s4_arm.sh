#!/usr/bin/env bash
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
# Evaluate one geometry arm closed-loop and produce an episode-indexed reach trace.
#
# Exists because the reach numbers in the older plans cannot be re-derived: of thirteen historical
# traces only three carry hand columns and none carries an episode index, so every quoted vertical
# error is a single global minimum over an undifferentiated stream. Encoding the invocation once,
# and checking the trace afterwards, is what stops that recurring.
#
# Two gotchas are encoded here rather than left to be rediscovered:
#   - Every main-parser flag must precede the environment subcommand. Putting --output_base_dir
#     after it exits 2 with no message.
#   - --remote_host/--remote_port are not optional in practice: omitting them defaults to
#     localhost:5555 and fails with ConnectionError.
#
# Usage:
#   ./eval_s4_arm.sh --arm align --episodes 20
#   ./eval_s4_arm.sh --arm baseline --episodes 20 --port 5557
#
# Assumes a GR00T server is already serving the arm's checkpoint on --port. Start one with:
#   ./docker/run_gr00t_server.sh -d -p 5557 \
#     -m /models/isaaclab_arena/static_apple_tutorial/geometry_arms/<arm> -e NEW_EMBODIMENT \
#     -c isaaclab_arena_gr00t/embodiments/g1/g1_sim_wbc_data_gr00t_n_1_7_config.py

set -euo pipefail

ARM=""
EPISODES=20
PORT=5557
HOST=127.0.0.1
ENVIRONMENT="galileo_g1_static_pick_and_place"
EMBODIMENT="g1_wbc_agile_joint"
OUTPUT_ROOT="${OUTPUT_ROOT:-eval_output}"
# Scene keys for the traced bodies, from galileo_g1_static_pick_and_place_environment.py's
# TUNED_PICK_UP_OBJECT_NAME / TUNED_DESTINATION_NAME.
OBJECT="apple_01_objaverse_robolab"
DESTINATION="clay_plates_hot3d_robolab"
ARENA_ROOT="${ARENA_ROOT:-/workspaces/isaaclab_arena}"
POLICY_CONFIG="${POLICY_CONFIG:-isaaclab_arena_gr00t/policy/config/g1_static_apple_gr00t_closedloop_config.yaml}"
HAND_BODY="${HAND_BODY:-left_hand_middle_1_link}"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --arm) ARM="$2"; shift 2 ;;
        --episodes) EPISODES="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --host) HOST="$2"; shift 2 ;;
        --object) OBJECT="$2"; shift 2 ;;
        --destination) DESTINATION="$2"; shift 2 ;;
        --output-root) OUTPUT_ROOT="$2"; shift 2 ;;
        --policy-config) POLICY_CONFIG="$2"; shift 2 ;;
        --hand-body) HAND_BODY="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help) sed -n '7,27p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

[[ -n "$ARM" ]] || { echo "--arm is required" >&2; exit 1; }

EXPERIMENT="${OUTPUT_ROOT}/s4_${ARM}"
TRACE="${EXPERIMENT}/reach_traces/${ARM}.jsonl"
mkdir -p "$(dirname "$TRACE")"

# Flag set verified against isaaclab_arena_gr00t/tests/test_gr00t_remote_closedloop_policy_runner.py,
# which is the only place a working invocation is written down. Notes on the non-obvious ones:
#   --policy_type          the registered name; the CLI also accepts a dotted class path
#   --policy_config_yaml_path  required -- the policy's joint mapping and horizon live here
#   --headless --enable_cameras  a vision policy needs cameras, and the run must not open a GUI
#   --remote_host/--remote_port  contributed by the policy, not by policy_runner_cli, which is why
#                                grepping the CLI for them finds nothing
CMD=(
    /isaac-sim/python.sh "${ARENA_ROOT}/isaaclab_arena/evaluation/policy_runner.py"
    # A dotted import path, not the registered short name. `--policy_type`'s help says
    # "either a registered policy name or a path to a policy class", but `get_policy_cls`
    # asserts `"." in policy_type` and rejects the short name outright. The help is wrong.
    --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy
    --policy_config_yaml_path "$POLICY_CONFIG"
    --remote_host "$HOST"
    --remote_port "$PORT"
    --output_base_dir "$EXPERIMENT"
    --num_episodes "$EPISODES"
    --headless
    --enable_cameras
    --trace_reach "$TRACE"
    --trace_reach_object "$OBJECT"
    --trace_reach_destination "$DESTINATION"
    # Pinned: see policy_runner_cli's note. Unpinned understates lateral error by 3-5 cm.
    --trace_reach_hand_body "$HAND_BODY"
    "$ENVIRONMENT"
    --embodiment "$EMBODIMENT"
)

echo "[s4] arm=$ARM episodes=$EPISODES server=${HOST}:${PORT}"
echo "[s4] trace=$TRACE"
printf '[s4] %q ' "${CMD[@]}"; echo

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[s4] --dry-run set; not launching."
    exit 0
fi

"${CMD[@]}"

# The trace is the deliverable, so its usability is checked here rather than discovered later.
# Ten of the thirteen historical traces are unusable for exactly the reasons tested below, and each
# of those runs looked successful at the time.
echo "[s4] verifying the trace is usable..."
python3 - "$TRACE" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path) as handle:
    rows = [json.loads(line) for line in handle if line.strip()]

assert rows, f"{path} is empty: the rollout wrote no reach rows."

keys = set()
for row in rows:
    keys |= row.keys()

missing = [k for k in ("hand_xy_to_obj", "hand_z_minus_obj") if k not in keys]
assert not missing, (
    f"{path} has {len(rows)} rows but no {missing}. ReachTracer resolves hand bodies by substring"
    " against the robot's body names, and returns an empty mapping when none match -- which omits"
    " the columns silently. Check the embodiment's body naming."
)
assert "episode" in keys, (
    f"{path} carries no episode index, so per-episode statistics cannot be derived from it. This"
    " is the defect that made every historical reach table irreproducible."
)

episodes = sorted({e for row in rows for e in (row.get("episode") or [])})
print(f"[s4] trace OK: {len(rows)} rows, {len(episodes)} episodes, hand columns present")
PY
echo "[s4] done. Compare with:"
echo "  python isaaclab_arena_gr00t/scripts/compare_reach_traces.py \\"
echo "    ${OUTPUT_ROOT}/s4_baseline/reach_traces/baseline.jsonl \\"
echo "    ${OUTPUT_ROOT}/s4_align/reach_traces/align.jsonl"
