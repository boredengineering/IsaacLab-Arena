# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Owned generation subprocess: parent-death safety and a bounded JSON receipt stream."""

import argparse
import contextlib
import ctypes
import json
import logging
import os
import signal
import sys

from .provider_security import reject_secret


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args()
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != args.parent_pid:
        return 1
    line = sys.stdin.buffer.readline(512 * 1024 + 1)
    if len(line) > 512 * 1024 or not line.endswith(b"\n"):
        return 1
    channel = sys.stdout
    api_key = None

    def send(message):
        reject_secret(message, api_key)
        channel.write(json.dumps(message, allow_nan=False) + "\n")
        channel.flush()

    previous_logging_level = logging.root.manager.disable
    logging.disable(sys.maxsize)
    try:
        envelope = json.loads(line)
        if set(envelope) != {"inputs", "config"} or not envelope["config"]:
            raise ValueError("Invalid private generation envelope")
        config = envelope["config"]
        api_key = config.get("api_key")
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            from .generation import generate

            result = generate(envelope["inputs"], lambda stage: send({"stage": stage}), config=config)
        reject_secret(result, config.get("api_key"))
        send({"result": result})
        return 0
    except Exception:
        send({"error": "Generation failed: check server model configuration, endpoint access, and draft validity"})
        return 1
    finally:
        logging.disable(previous_logging_level)


if __name__ == "__main__":
    raise SystemExit(main())
