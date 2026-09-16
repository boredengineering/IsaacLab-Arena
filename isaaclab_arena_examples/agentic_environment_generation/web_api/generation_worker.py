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

from isaaclab_arena.agentic_environment_generation.workbench.generation_diagnostics import GENERATION_STAGES

from .generation_diagnostics import classify_failure
from .graph_access import checked_graph_config
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
    graph_password = None
    stage = "worker_starting"

    def send(message):
        reject_secret(message, api_key)
        reject_secret(message, graph_password)
        channel.write(json.dumps(message, allow_nan=False) + "\n")
        channel.flush()

    def progress(value):
        nonlocal stage
        if type(value) is not str or value not in GENERATION_STAGES:
            raise ValueError("Invalid generation stage")
        send({"stage": value})
        stage = value

    previous_logging_level = logging.root.manager.disable
    logging.disable(sys.maxsize)
    try:
        envelope = json.loads(line)
        inputs = envelope.get("inputs") if isinstance(envelope, dict) else None
        modern = isinstance(inputs, dict) and inputs.get("operation") in {"new", "refine"}
        expected = {"inputs", "config", "graph_config"} if modern else {"inputs", "config"}
        if modern and "managed_context" in envelope:
            expected.add("managed_context")
        if not isinstance(envelope, dict) or set(envelope) != expected or not isinstance(envelope["config"], dict):
            raise ValueError("Invalid private generation envelope")
        config = envelope["config"]
        api_key = config.get("api_key")
        options = {}
        if modern:
            if set(config) - {"api_key", "model", "base_url", "provider", "trusted_server"}:
                raise ValueError("Invalid private model configuration fields")
            digest = inputs.get("execution_catalogue_sha256")
            if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Invalid execution catalogue identity")
            graph = envelope["graph_config"]
            graph = checked_graph_config(graph) if graph is not None else None
            graph_password = (graph or {}).get("password")
            options["graph_config"] = graph
            from .managed_retrieval import private_context

            managed = private_context(inputs, envelope)
            if managed is not None:
                options["managed_context"] = managed
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            from .generation import generate

            result = generate(envelope["inputs"], progress, config=config, **options)
        reject_secret(result, config.get("api_key"))
        reject_secret(result, graph_password)
        send({"result": result})
        return 0
    except Exception as exc:
        # Even static markers may collide with a protected credential. Emit nothing.
        with contextlib.suppress(Exception):
            send({"error": classify_failure(exc, stage)})
        return 1
    finally:
        logging.disable(previous_logging_level)


if __name__ == "__main__":
    raise SystemExit(main())
