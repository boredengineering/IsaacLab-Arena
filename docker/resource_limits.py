# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Host-side resource budgets shared by the editor, simulator and frontend."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

GIB = 1024**3


def existing_research_budget(capacity, available, retained):
    """Budget existing Neo4j/GR00T while retaining caps and 4 GiB host headroom.

    Args:
        capacity: Fresh Docker daemon RAM capacity in bytes.
        available: Fresh host MemAvailable in bytes, not container free memory.
        retained: Actual positive arena/editor/frontend/helper memory caps.

    Returns:
        Explicit no-swap memory and PID limits for the two existing services.
    """
    if (
        type(capacity) is not int
        or type(available) is not int
        or not 0 < available <= capacity
        or type(retained) is not dict
        or set(retained) != {"arena", "editor", "frontend", "helper"}
        or any(type(value) is not int or value <= 0 for value in retained.values())
    ):
        raise ValueError("Invalid existing-stack resource observations")
    required = 18 * GIB
    reserve = 4 * GIB
    if sum(retained.values()) + required + reserve > capacity or available < required + reserve:
        raise ValueError("Insufficient host headroom for existing research services")
    return {
        "neo4j": {"memory": 2 * GIB, "memory_swap": 2 * GIB, "pids": 256},
        "gr00t": {"memory": 16 * GIB, "memory_swap": 16 * GIB, "pids": 1024},
    }


def resource_environment(capacity=None):
    """Return decimal Compose/shell values reserving at least 25% daemon RAM."""
    if capacity is None:
        capacity = int(
            subprocess.run(
                ["docker", "info", "--format", "{{.MemTotal}}"],
                check=True,
                text=True,
                capture_output=True,
                timeout=15,
            ).stdout.strip()
        )
    # Docker requires at least 6 MiB; never round a small budget up into headroom.
    if type(capacity) is not int or capacity < 120 * 1024**2:
        raise ValueError("Docker host memory must be an integer of at least 120 MiB")
    result = {}
    for role, maximum, percentage, pids in (("EDITOR", 8, 10, 512), ("ARENA", 56, 60, 2048), ("FRONTEND", 4, 5, 256)):
        result[f"{role}_MEMORY_BYTES"] = str(min(maximum * GIB, capacity * percentage // 100))
        result[f"{role}_PIDS_LIMIT"] = str(pids)
    return result


def validate_editor(run_args, capacity=None):
    """Fail closed unless explicit editor flags fit the daemon-derived budget."""
    budget = resource_environment(capacity)
    if any(arg in ("--memory", "--memory-swap", "--pids-limit") or arg.startswith("-m") for arg in run_args):
        raise ValueError("Use only the checked --memory=, --memory-swap= and --pids-limit= flag forms")
    limits = {}
    for flag in ("memory", "memory-swap", "pids-limit"):
        values = [arg.split("=", 1)[1] for arg in run_args if arg.startswith(f"--{flag}=")]
        if len(values) != 1 or not values[0].isascii() or not values[0].isdecimal():
            raise ValueError(f"Editor requires one decimal --{flag}= value")
        limits[flag] = int(values[0])
    if not 6 * 1024**2 <= limits["memory"] <= int(budget["EDITOR_MEMORY_BYTES"]):
        raise ValueError(
            "Editor memory exceeds min(8 GiB, 10% Docker host RAM), or is below 6 MiB; "
            "lower both memory flags in .devcontainer/devcontainer.json for this host"
        )
    if limits["memory-swap"] != limits["memory"] or not 0 < limits["pids-limit"] <= 512:
        raise ValueError("Editor requires equal memory/swap caps and a PID limit in 1..512")


def main():
    """Print fresh numeric shell exports, or validate checked-in editor flags."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-editor", action="store_true")
    args = parser.parse_args()
    if args.check_editor:
        config = Path(__file__).resolve().parent.parent / ".devcontainer/devcontainer.json"
        validate_editor(json.loads(config.read_text())["runArgs"])
    else:
        for key, value in resource_environment().items():
            print(f"export {key}={value}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Resource preflight failed: {error}", file=sys.stderr)
        sys.exit(1)
