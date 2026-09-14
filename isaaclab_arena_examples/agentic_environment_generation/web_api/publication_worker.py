# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Credential-free bootstrap; one private EOF-terminated envelope, one result, exit."""

import ctypes
import json
import os
import signal
import sys

READY = {"schema_version": 1, "ready": "publication"}
ERROR = {"schema_version": 1, "error": "publication_unknown"}
MAX_ENVELOPE_BYTES = 2 * 1024 * 1024
MAX_RESULT_BYTES = 64 * 1024
MAX_DEPTH = 32


def _write_all(channel, data):
    """Write a complete bounded frame, including positive short-write results."""
    remaining = memoryview(data)
    while remaining:
        count = os.write(channel, remaining)
        if count <= 0:
            raise OSError("Publication channel closed")
        remaining = remaining[count:]


def main(*, driver_factory=None):
    """Run the production protocol; factory injection is trusted code only."""
    try:
        if len(sys.argv) != 3 or sys.argv[1] != "--parent-pid":
            return 1
        parent = int(sys.argv[2])
        if parent <= 1 or ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            return 1
        if os.getppid() != parent:
            return 1
    except BaseException:
        return 1
    channel = os.dup(1)
    # Redirect file descriptors, not just Python streams: SDK/native output is private.
    with open(os.devnull, "wb") as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
    _write_all(channel, json.dumps(READY).encode() + b"\n")
    result = ERROR
    try:
        raw = sys.stdin.buffer.read(MAX_ENVELOPE_BYTES + 1)
        # A file entrypoint avoids web_api.__init__ and its application/Journal imports.
        if not __package__:
            import importlib
            import types

            package = types.ModuleType("_arena_publication_private")
            package.__path__ = [os.path.dirname(os.path.abspath(__file__))]
            sys.modules[package.__name__] = package
            payload = importlib.import_module(package.__name__ + ".publication_payload")
            execute_private_envelope = payload.execute_private_envelope
        else:
            from .publication_payload import execute_private_envelope

        result = execute_private_envelope(raw, driver_factory=driver_factory)
    except BaseException:
        pass
    try:
        data = json.dumps(result, allow_nan=False, separators=(",", ":")).encode() + b"\n"
        if len(data) > MAX_RESULT_BYTES:
            data = json.dumps(ERROR).encode() + b"\n"
        _write_all(channel, data)
    finally:
        os.close(channel)
    return 0 if "receipt" in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
