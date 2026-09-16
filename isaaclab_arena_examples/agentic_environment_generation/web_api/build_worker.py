# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Fixed build bridge; simulator imports occur only inside the owned worker."""

import argparse
import json
import os
import re
import sys
import tempfile
import traceback
from contextlib import contextmanager, redirect_stdout
from pathlib import Path


def run_build(inputs, *, on_completed):
    """Report the fixed rollout through a trusted hook before simulator shutdown."""
    from isaaclab_arena.agentic_environment_generation.workbench.document_yaml import parse_yaml
    from isaaclab_arena.agentic_environment_generation.workbench.documents import canonical_digest

    fixed = {"headless": True, "num_envs": 1, "num_steps": 20, "policy": "zero_action"}
    fields = {"yaml_text", "document_id", "input_hash", "canonical_hash", "request_sha256", *fixed}
    if (
        type(inputs) is not dict
        or set(inputs) != fields
        or any(type(inputs[key]) is not type(value) or inputs[key] != value for key, value in fixed.items())
    ):
        raise ValueError("Invalid frozen build inputs")
    for key in ("input_hash", "canonical_hash", "request_sha256"):
        if type(inputs[key]) is not str or not re.fullmatch(r"[a-f0-9]{64}", inputs[key]):
            raise ValueError("Invalid frozen build hash")
    text = inputs["yaml_text"]
    if type(text) is not str or len(text.encode("utf-8")) > 256 * 1024:
        raise ValueError("Invalid frozen build YAML")
    raw = parse_yaml(text)
    if type(raw) is not dict or "external_yaml" in raw or canonical_digest(raw) != inputs["canonical_hash"]:
        raise ValueError("Frozen build scene mismatch")

    from isaaclab_arena_examples.agentic_environment_generation import environment_generation_runner as runner

    def completed():
        on_completed(
            {
                "schema_version": 1,
                "input_hash": inputs["input_hash"],
                "canonical_hash": inputs["canonical_hash"],
                "headless": True,
                "num_envs": 1,
                "num_steps": 20,
                "policy": "zero_action",
                "completed": True,
            }
        )

    with tempfile.TemporaryDirectory(prefix="arena-build-") as directory:
        path = Path(directory) / "environment.yaml"
        path.write_text(inputs["yaml_text"], encoding="utf-8")
        previous = sys.argv
        sys.argv = [
            "environment_generation_runner",
            "--mode",
            "build",
            "--headless",
            "--num_envs",
            "1",
            "--num_steps",
            "20",
            "--env_graph_spec_yaml",
            str(path),
        ]
        try:
            if runner.main(on_build_completed=completed) != 0:
                raise ValueError("Build did not complete")
        finally:
            sys.argv = previous


@contextmanager
def private_channel():
    """Separate protocol output from both native-fd and Python simulator logs."""
    sys.stdout.flush()
    descriptor = os.dup(1)
    try:
        os.dup2(2, 1)
        with os.fdopen(os.dup(descriptor), "w", encoding="utf-8") as channel, redirect_stdout(sys.stderr):
            yield channel
    finally:
        sys.stdout.flush()
        os.dup2(descriptor, 1)
        os.close(descriptor)


def main():
    """Serve the supervisor's bounded envelope in an owner-watched process group."""
    from .snapshot_process import watch_parent

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-fd", type=int, required=True)
    args = parser.parse_args()
    watch_parent(args.owner_fd)
    with private_channel() as channel:

        def send(message):
            channel.write(json.dumps(message, allow_nan=False) + "\n")
            channel.flush()

        try:
            line = sys.stdin.buffer.readline(2 * 1024 * 1024 + 1)
            if len(line) > 2 * 1024 * 1024 or not line.endswith(b"\n"):
                raise ValueError("Invalid build envelope")
            envelope = json.loads(line)
            if type(envelope) is not dict or set(envelope) != {"inputs"}:
                raise ValueError("Invalid build envelope")
            send({"stage": "building_environment"})
            run_build(envelope["inputs"], on_completed=lambda result: send({"result": result}))
            return 0
        except Exception:
            traceback.print_exc(file=sys.stderr)
            send({"error": "Build failed; check private runtime logs"})
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
