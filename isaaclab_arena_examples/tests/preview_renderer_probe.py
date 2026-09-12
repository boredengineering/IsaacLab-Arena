# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit GPU probe: zero policy steps, owned worker, global lease, bounded RPCs.

Run in the non-root Isaac runtime. This is deliberately not a pytest test: GPU
work is opt-in. Receipts contain USD target paths and camera bounds for inspection;
PNG validity alone is not a visual correctness assertion.
"""

import argparse
import json
import time
from pathlib import Path

from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_process import SnapshotProcess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--variants", type=int, default=2, choices=(1, 2))
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    fixture = Path(__file__).parents[2] / "isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml"
    process = SnapshotProcess(root)
    try:
        variants = [
            ("isometric", {"view": "isometric", "resolution": 512}),
            (
                "front",
                {
                    "view": "front",
                    "resolution": 1024,
                    "asset_views": {"maple_table_robolab_table": "top", "droid_abs_joint_pos": "side"},
                },
            ),
        ]
        for name, options in variants[: args.variants]:
            request = {
                "yaml_text": fixture.read_text(),
                "output_dir": str(root / "renders" / name),
                "num_envs": 1,
                "num_steps": 0,
                "env_spacing": 3.0,
                "options": options,
                "renderer_version": "renderer-verification-v2",
            }
            response = process.request(request, time.monotonic() + 360, lambda s: print(s, flush=True))
            (root / f"{name}.json").write_text(json.dumps(response, indent=2))
            print(
                json.dumps({
                    "variant": name,
                    "ok": response.get("ok"),
                    "paths": response.get("paths"),
                    "scene": response.get("scene"),
                    "errors": response.get("errors"),
                    "timings": response.get("timings"),
                }),
                flush=True,
            )
    finally:
        process.close()
        print("Owned worker closed; GPU lease released.", flush=True)


if __name__ == "__main__":
    main()
