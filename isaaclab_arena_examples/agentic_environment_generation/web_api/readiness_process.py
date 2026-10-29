# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded private readiness subprocess, separate from every job/queue owner."""

import json
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path

from .owned_process_group import OwnedProcessGroup
from .provider_security import reject_secret, worker_environment

_PENDING = []
MAX_RECEIPT = 8192


def cleanup_pending():
    """Unknown cleanup must retain the dependency slot, not admit another process."""
    return bool(_PENDING)


def validate_receipt(value):
    """Reject arbitrary worker diagnostics rather than exposing them publicly."""
    if type(value) is not dict or set(value) - {"gpu", "provider"} != {"runtime", "graph", "policy"}:
        raise ValueError("Invalid readiness receipt")
    if "provider" in value:
        from .provider_readiness import PROVIDER_CODES

        if value["provider"] not in ("not_checked", "generation_not_configured", *PROVIDER_CODES):
            raise ValueError("Invalid readiness provider receipt")
    if "gpu" in value:
        from .resource_readiness import RESOURCE_CODES

        if value["gpu"] not in ("not_required", *RESOURCE_CODES):
            raise ValueError("Invalid readiness resource receipt")
    if value["runtime"] not in ("runtime_available", "runtime_unavailable") or value["graph"] not in (
        "not_required",
        "graph_not_configured",
        "graph_retrieval_measured",
        "graph_retrieval_structural",
        "graph_retrieval_empty",
        "graph_retrieval_unavailable",
    ):
        raise ValueError("Invalid readiness receipt")
    if value["policy"] is not None:
        from .policy_readiness import validate_probe_result

        validate_probe_result(value["policy"])
    return value


def run_worker(envelope):
    """Bound input, output, lifetime and cleanup; config travels only on private stdin."""
    data = (json.dumps(envelope, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(data) > 96 * 1024:
        raise ValueError("Readiness input exceeds bound")
    reader, owner = os.pipe()
    process = group = None
    record = None
    try:
        api_key = (envelope.get("provider_config") or {}).get("api_key")
        environment = worker_environment(api_key)
        for name in ("CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES", "ISAAC_PATH", "CARB_APP_PATH", "EXP_PATH"):
            if name in os.environ:
                environment[name] = os.environ[name]
        reject_secret(environment, api_key)
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-m",
                "isaaclab_arena_examples.agentic_environment_generation.web_api.readiness_worker",
                "--owner-fd",
                str(reader),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            cwd=Path(__file__).resolve().parents[3],
            start_new_session=True,
            pass_fds=(reader,),
            bufsize=0,
        )
        # Retain the group object even if its fallible descendant scan raises.
        group = OwnedProcessGroup.__new__(OwnedProcessGroup)
        record = (process, group, owner)
        _PENDING.append(record)
        group.__init__(process.pid)
        os.close(reader)
        reader = None
        output = bytearray()
        sent = 0
        deadline = time.monotonic() + 12
        with selectors.DefaultSelector() as selector:
            for pipe, mode in (
                (process.stdin, selectors.EVENT_WRITE),
                (process.stdout, selectors.EVENT_READ),
            ):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, mode)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Readiness worker timed out")
                for key, _ in selector.select(min(remaining, 0.1)):
                    if key.fileobj is process.stdin:
                        sent += os.write(process.stdin.fileno(), data[sent : sent + 4096])
                        if sent == len(data):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                    else:
                        chunk = os.read(process.stdout.fileno(), MAX_RECEIPT + 1 - len(output))
                        output.extend(chunk)
                        if len(output) > MAX_RECEIPT:
                            raise ValueError("Readiness receipt exceeds bound")
                        if not chunk:
                            selector.unregister(process.stdout)
            if process.wait(timeout=max(0.01, deadline - time.monotonic())) != 0:
                raise ValueError("Readiness worker unavailable")

        def unique_pairs(items):
            value = {}
            for key, item in items:
                if key in value:
                    raise ValueError("Duplicate readiness receipt key")
                value[key] = item
            return value

        return validate_receipt(json.loads(output, object_pairs_hook=unique_pairs))
    finally:
        if reader is not None:
            os.close(reader)
        if process is None:
            os.close(owner)
        else:
            try:
                if group is None:
                    raise RuntimeError("Readiness cleanup identity unavailable")
                group.stop()
                process.wait(timeout=3)
            except BaseException:
                # Retain process/group/watch descriptor and block further checks.
                raise RuntimeError("Readiness cleanup pending") from None
            else:
                for pipe in (process.stdin, process.stdout):
                    if pipe is not None:
                        pipe.close()
                os.close(owner)
                _PENDING.remove(record)
