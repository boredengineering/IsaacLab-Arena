# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Fixed policy_runner bridge inside Build's owner-watched GPU process lifecycle."""

import argparse
import importlib
import json
import os
import re
import sys
import traceback
from pathlib import Path

from .build_worker import private_channel
from .evaluation_artifacts import MAX_RECEIPT_BYTES, collect_result
from .evaluation_profiles import FIXED, PROFILES, compatible_spec

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def run_evaluation(inputs, output_root, *, on_completed):
    """Run the native policy harness with explicit local-only telemetry and lineage policy."""
    from isaaclab_arena.agentic_environment_generation.workbench.document_yaml import parse_yaml
    from isaaclab_arena.agentic_environment_generation.workbench.documents import canonical_digest

    fields = {
        "yaml_text",
        "document_id",
        "input_hash",
        "canonical_hash",
        "request_sha256",
        "profile",
        "language_instruction",
        *FIXED,
    }
    if type(inputs) is dict and inputs.get("profile") == "gr00t-droid":
        if "expected_server_info" not in inputs:
            raise ValueError("policy_metadata_unavailable")
        fields.add("expected_server_info")
    if type(inputs) is dict and {"remote_host", "remote_port"} & inputs.keys():
        fields.update(("remote_host", "remote_port"))
    if (
        type(inputs) is not dict
        or set(inputs) != fields
        or any(type(inputs[k]) is not type(v) or inputs[k] != v for k, v in FIXED.items())
    ):
        raise ValueError("Invalid frozen evaluation inputs")
    if inputs["profile"] not in {p["id"] for p in PROFILES}:
        raise ValueError("Invalid evaluation profile")
    host = inputs.get("remote_host", "127.0.0.1")
    port = inputs.get("remote_port", 5555 if inputs["profile"] == "gr00t-droid" else 8000)
    if host != "127.0.0.1" or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid frozen evaluation endpoint")
    if inputs["profile"] == "openpi-droid" and port != 8000:
        raise ValueError("Invalid frozen evaluation endpoint")
    for key in ("input_hash", "canonical_hash", "request_sha256"):
        if type(inputs[key]) is not str or not re.fullmatch(r"[a-f0-9]{64}", inputs[key]):
            raise ValueError("Invalid evaluation hash")
    if inputs["document_id"] is not None and (
        type(inputs["document_id"]) is not str or not re.fullmatch(r"[a-f0-9]{32}", inputs["document_id"])
    ):
        raise ValueError("Invalid evaluation document")
    instruction = inputs["language_instruction"]
    if instruction is not None and (
        type(instruction) is not str or not instruction.strip() or len(instruction.encode()) > 4000
    ):
        raise ValueError("Invalid evaluation instruction")
    text = inputs["yaml_text"]
    if type(text) is not str or len(text.encode()) > 256 * 1024:
        raise ValueError("Invalid evaluation YAML")
    spec = parse_yaml(text)
    if type(spec) is not dict or "external_yaml" in spec or canonical_digest(spec) != inputs["canonical_hash"]:
        raise ValueError("Frozen evaluation scene mismatch")
    env_name = compatible_spec(spec)
    verified_info = None
    if inputs["profile"] == "gr00t-droid":
        from isaaclab_arena.agentic_environment_generation.policy_contract import validate_server_info

        from .policy_readiness import probe_gr00t
        from .readiness import READINESS_CODES

        try:
            pinned = validate_server_info(inputs["expected_server_info"])
        except ValueError:
            raise ValueError("policy_metadata_unavailable") from None
        proof = probe_gr00t({key: pinned[key] for key in ("checkpoint_sha256", "config_sha256")}, port=port)
        for key in ("policy_protocol", "policy_model", "policy_transport"):
            if proof[key]["status"] != "passed":
                code = proof[key]["code"]
                raise ValueError(code if code in READINESS_CODES else "policy_metadata_unavailable")
        verified_info = validate_server_info(proof["server_info"])
        if verified_info != pinned:
            raise ValueError("policy_instance_mismatch")
    root = Path(output_root).absolute()
    path = root / "environment.yaml"
    with path.open("x", encoding="utf-8") as source:
        source.write(text)
    argv = [
        "policy_runner",
        "--headless",
        "--enable_cameras",
        "--num_envs",
        "1",
        "--num_steps",
        "1000",
        "--env_graph_spec_yaml",
        str(path),
        "--output_base_dir",
        str(root / "output"),
        "--remote_host",
        host,
        "--remote_port",
        str(port),
    ]
    if inputs["profile"] == "gr00t-droid":
        argv += [
            "--policy_type",
            "isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy",
            "--policy_config_yaml_path",
            "isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml",
        ]
    else:
        argv += [
            "--policy_type",
            "isaaclab_arena_openpi.policy.pi0_remote_policy.Pi0RemotePolicy",
            "--policy_variant",
            "pi05",
            "--openpi_embodiment_adapter",
            "droid",
        ]
    if instruction is not None:
        argv += [f"--language_instruction={instruction}"]
    received = False

    def completed(evidence):
        nonlocal received
        if received:
            raise ValueError("Duplicate evaluation completion")
        received = True
        on_completed(collect_result(inputs, root, evidence))

    previous_argv, previous_cwd = sys.argv, Path.cwd()
    try:
        os.chdir(REPOSITORY_ROOT)  # GR00T's checked-in YAML includes repository-relative joint configs.
        sys.argv = argv
        runner = importlib.import_module("isaaclab_arena.evaluation.policy_runner")
        original_factory = None
        if verified_info is not None:
            from dataclasses import replace

            from isaaclab_arena.evaluation.policy_runner_cli import policy_cfg_from_cli

            original_factory = runner.build_policy_from_cli

            def verified_factory(policy_type, args_cli):
                config = policy_cfg_from_cli(policy_type, args_cli)
                return policy_type(replace(config, expected_server_info=dict(verified_info)))

            runner.build_policy_from_cli = verified_factory
        try:
            outcome = runner.main(
                on_evaluation_completed=completed,
                publish_to_graph=False,
                telemetry_env_name=env_name,
                update_lineage=False,
            )
        finally:
            if original_factory is not None:
                runner.build_policy_from_cli = original_factory
        if outcome not in (None, 0) or not received:
            raise ValueError("Evaluation did not complete")
    finally:
        sys.argv = previous_argv
        os.chdir(previous_cwd)


def main():
    """Receive private output ownership separately from frozen public job inputs."""
    from .snapshot_process import watch_parent

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-fd", type=int, required=True)
    args = parser.parse_args()
    watch_parent(args.owner_fd)
    with private_channel() as channel:

        def send(message):
            encoded = json.dumps(message, allow_nan=False, separators=(",", ":")) + "\n"
            if len(encoded.encode()) > MAX_RECEIPT_BYTES:
                raise ValueError("Evaluation receipt exceeds bounds")
            channel.write(encoded)
            channel.flush()

        try:
            line = sys.stdin.buffer.readline(2 * 1024 * 1024 + 1)
            if len(line) > 2 * 1024 * 1024 or not line.endswith(b"\n"):
                raise ValueError("Invalid evaluation envelope")
            envelope = json.loads(line)
            if type(envelope) is not dict or set(envelope) != {"inputs", "output_root"}:
                raise ValueError("Invalid evaluation envelope")
            send({"stage": "evaluating_policy"})
            run_evaluation(
                envelope["inputs"],
                envelope["output_root"],
                on_completed=lambda result: send({"result": result}),
            )
            return 0
        except Exception:
            traceback.print_exc(file=sys.stderr)
            send({"error": "Evaluation failed; check private runtime logs"})
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
