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
import math
import os
import signal
import sys
import time
from decimal import Decimal

from isaaclab_arena.agentic_environment_generation.workbench.generation_diagnostics import GENERATION_STAGES

from .generation_diagnostics import classify_failure
from .graph_access import checked_graph_config
from .provider_security import reject_secret


def workflow_allowance(envelope):
    """Validate trusted private release metadata; no store/OS authenticity is implied.

    Wall time is sampled once into a monotonic deadline, so pipe/startup delay
    consumes the original release window. Optional attested upper bounds are
    charged, never actual usage. Legacy packets remain count-only.
    """
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        AttemptFence,
        GenerationReservation,
        WorkerRegistration,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import (
        CallAllowance,
        checked_workflow_accounting,
    )

    try:
        packet = envelope["workflow_execution"]
        if (
            type(packet) is not dict
            or set(packet)
            != {"version", "fence", "registration", "reservation", "admitted_at", "released_at", "deadline"}
            or type(packet["version"]) is not int
            or packet["version"] != 1
        ):
            raise ValueError
        fence = AttemptFence.model_validate(packet["fence"])
        registration = WorkerRegistration.model_validate(packet["registration"])
        reservation = GenerationReservation.model_validate(packet["reservation"])
        admitted, released, deadline = (packet[k] for k in ("admitted_at", "released_at", "deadline"))
        monotonic, now = time.monotonic(), time.time()
        if (
            registration.fence != fence
            or any(type(v) not in (float, int) or not math.isfinite(v) for v in (admitted, released, deadline))
            or not 0 <= admitted <= released <= now < deadline <= released + reservation.runtime_allowance_seconds
            or reservation.model_calls <= 0
            or envelope.get("graph_config") is not None
            or "managed_context" in envelope
            or envelope["inputs"].get("operation") != "new"
            or set(envelope["inputs"]) != {"operation", "prompt", "retrieval_policy", "execution_catalogue_sha256"}
            or envelope["inputs"]["retrieval_policy"] != "allow_fallback"
            or not isinstance(envelope.get("config"), dict)
        ):
            raise ValueError
        accounting = {}
        if "workflow_accounting" in envelope["config"]:
            config = envelope["config"]
            bound = checked_workflow_accounting(
                config["workflow_accounting"], model=config["model"], endpoint=config["base_url"]
            )
            # Existing frozen reservation wire uses JSON numbers. Interpret its
            # decimal spelling once; all subsequent admission uses integer units.
            accounting = dict(
                max_tokens=reservation.model_tokens,
                cost_ceiling_usd=format(Decimal(str(reservation.cost_ceiling_usd)), "f"),
                per_call_bound=bound,
            )
        return CallAllowance(max_calls=reservation.model_calls, deadline=monotonic + deadline - now, **accounting)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("Invalid workflow execution packet") from None


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
    watchdog = False
    previous_alarm = None

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
        if modern and "workflow_execution" in envelope:
            expected.add("workflow_execution")
        if modern and "managed_context" in envelope:
            expected.add("managed_context")
        if not isinstance(envelope, dict) or set(envelope) != expected or not isinstance(envelope["config"], dict):
            raise ValueError("Invalid private generation envelope")
        config = envelope["config"]
        api_key = config.get("api_key")
        options = {}
        if "workflow_execution" in envelope:
            allowance = workflow_allowance(envelope)
            options["allowance"] = allowance
            remaining = allowance.deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("Invalid workflow execution packet")
            # Kernel timer kills this child even during a stuck provider call.
            # It does not prove group cleanup or undo remote provider effects.
            previous_alarm = signal.signal(signal.SIGALRM, signal.SIG_DFL)
            signal.setitimer(signal.ITIMER_REAL, remaining)
            watchdog = True
        if modern:
            if set(config) - {
                "api_key",
                "model",
                "base_url",
                "provider",
                "trusted_server",
                "inference_profile",
                "workflow_accounting",
            }:
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
        if watchdog:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_alarm)
        logging.disable(previous_logging_level)


if __name__ == "__main__":
    raise SystemExit(main())
