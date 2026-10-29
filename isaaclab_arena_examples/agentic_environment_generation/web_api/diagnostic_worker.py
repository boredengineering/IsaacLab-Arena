# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Test-only bounded worker; emits real sleep-step boundaries, never robotics results."""

import argparse
import ctypes
import json
import os
import signal
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument("--delay", type=float, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args()
    if not (1 <= args.steps <= 10 and 0.1 <= args.delay <= 5):
        parser.error("Diagnostic bounds exceeded")
    # Linux PR_SET_PDEATHSIG closes the orphan window, including the pre-prctl parent-death race.
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        parser.exit(1, "Unable to establish parent-death safety\n")
    if os.getppid() != args.parent_pid:
        parser.exit(1, "Supervisor exited before worker initialization\n")
    if sys.stdin.buffer.readline(16) != b"go\n":
        parser.exit(1, "No durable execution authorization\n")

    def emit(stage):
        print(json.dumps({"stage": stage}), flush=True)

    emit("diagnostic_ready")
    for step in range(1, args.steps + 1):
        emit(f"diagnostic_step_{step}_started")
        time.sleep(args.delay)
        emit(f"diagnostic_step_{step}_completed")
    print(json.dumps({"result": {"diagnostic": True, "completed_steps": args.steps}}), flush=True)


if __name__ == "__main__":
    main()
