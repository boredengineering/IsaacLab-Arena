# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Private, bounded worker-context dependency reads; never create research work."""

import argparse
import json
import sys

from . import graph_access
from .build_worker import private_channel


def run_checks(envelope):
    """Use the generation worker's actual retriever, projecting no graph content."""
    if type(envelope) is not dict or set(envelope) - {
        "resource_config",
        "check_provider",
        "provider_config",
        "gr00t_port",
    } != {
        "workflow",
        "prompt",
        "graph_config",
        "expectations",
    }:
        raise ValueError("Invalid readiness envelope")
    workflow = envelope["workflow"]
    if workflow not in ("agentic_generation", "graph_generation", "a2_gr00t", "build"):
        raise ValueError("Invalid readiness workflow")
    if "gr00t_port" in envelope and workflow != "a2_gr00t":
        raise ValueError("Invalid readiness endpoint scope")
    if workflow == "a2_gr00t":
        from .policy_endpoint import LEGACY_GR00T_PORT, validate_gr00t_port

        port = validate_gr00t_port(envelope.get("gr00t_port", LEGACY_GR00T_PORT))
    prompt = envelope["prompt"]
    if (
        type(prompt) is not str
        or not prompt.strip()
        or len(prompt) > 16000
        or len(prompt.encode()) > 64000
    ):
        raise ValueError("Invalid readiness prompt")
    result = {"runtime": "runtime_available", "graph": "not_required", "policy": None}
    opted_in = envelope.get("check_provider", False)
    if type(opted_in) is not bool or (
        not opted_in and envelope.get("provider_config") is not None
    ):
        raise ValueError("Invalid provider read authorization")
    if "check_provider" in envelope:
        from .provider_readiness import probe_provider

        result["provider"] = (
            probe_provider(envelope.get("provider_config"))
            if opted_in
            else "not_checked"
        )
    if "resource_config" in envelope:
        from .resource_readiness import probe_gpu

        result["gpu"] = (
            probe_gpu(envelope["resource_config"])
            if workflow in ("agentic_generation", "build", "a2_gr00t")
            else "not_required"
        )
    if workflow in ("agentic_generation", "build", "a2_gr00t"):
        import importlib.util

        if importlib.util.find_spec("isaacsim") is None:
            result["runtime"] = "runtime_unavailable"
    if workflow in ("agentic_generation", "graph_generation", "a2_gr00t"):
        config = envelope["graph_config"]
        if config is None:
            result["graph"] = "graph_not_configured"
        else:
            graph_access.checked_graph_config(config)
            try:
                snapshot = graph_access.retrieve_snapshot(prompt, config)
                result["graph"] = {
                    "measured": "graph_retrieval_measured",
                    "structural": "graph_retrieval_structural",
                    "empty": "graph_retrieval_empty",
                }.get(snapshot.get("status"), "graph_retrieval_unavailable")
            except Exception:
                result["graph"] = "graph_retrieval_unavailable"
    if workflow == "a2_gr00t":
        from .policy_readiness import probe_gr00t

        result["policy"] = probe_gr00t(envelope["expectations"], port=port)
    return result


def main():
    """Read one private envelope and emit one bounded, static result."""
    from .snapshot_process import watch_parent

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-fd", type=int, required=True)
    args = parser.parse_args()
    watch_parent(args.owner_fd)
    with private_channel() as channel:
        try:
            line = sys.stdin.buffer.readline(96 * 1024 + 1)
            if len(line) > 96 * 1024 or not line.endswith(b"\n"):
                raise ValueError("Invalid readiness envelope")
            result = run_checks(json.loads(line))
            encoded = json.dumps(result, allow_nan=False, separators=(",", ":")) + "\n"
            if len(encoded.encode()) > 8192:
                raise ValueError("Invalid readiness receipt")
            channel.write(encoded)
            channel.flush()
            return 0
        except Exception:
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
