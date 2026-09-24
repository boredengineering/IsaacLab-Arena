# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Offline inspection and explicit installed HTTP workflow operations."""

import argparse
import json
import os
import stat
import sys

from .contracts import MAX_CONTRACT_BYTES, contract_digest, parse_contract
from .evidence_contracts import project_required_criteria
from .readiness import required_dependencies


class _StaticArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse diagnostics can otherwise echo arbitrary arguments and paths.
        raise ValueError("invalid arguments")


def _read_contract(path):
    # Refuse final symlinks atomically; nonblocking open prevents FIFO hangs.
    # Missing platform support fails closed, never falls back to following links.
    if not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("unsupported file semantics")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_CONTRACT_BYTES:
            raise ValueError("invalid file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return parse_contract(stream.read(MAX_CONTRACT_BYTES + 1))
    finally:
        os.close(fd)


def _add_installed_arguments(commands):
    """Declare installed commands without importing any optional API dependencies."""
    readiness = commands.add_parser("setup-readiness", help="Report offline public setup blockers", allow_abbrev=False)
    readiness.add_argument("--selection", help="Explicit public selection JSON; no credentials or checks")
    setup = commands.add_parser("setup", help="Create explicit private query configuration state", allow_abbrev=False)
    setup.add_argument("--config", required=True)
    setup.add_argument("--create", action="store_true", required=True)
    setup.add_argument("--credentials-fd", type=int, required=True)
    for name in ("credentials-update", "credentials-remove"):
        credentials = commands.add_parser(name, allow_abbrev=False)
        credentials.add_argument("--config", required=True)
        if name == "credentials-update":
            credentials.add_argument("--credentials-fd", type=int, required=True)
    submit = commands.add_parser("submit", help="Submit to the installed execution owner", allow_abbrev=False)
    submit.add_argument("--client", required=True)
    submit.add_argument("--operation-id", required=True)
    submit.add_argument("--contract", required=True)
    cancel = commands.add_parser(
        "cancel", help="Request keyed cancellation through the installed owner", allow_abbrev=False
    )
    cancel.add_argument("identifier")
    resume = commands.add_parser("resume", help="Admit an explicitly reauthorized known-unreleased continuation")
    resume.add_argument("--client", required=True)
    resume.add_argument("--operation-id", required=True)
    resume.add_argument("--expected-version", required=True)
    resume.add_argument("--renew-authorization", action=argparse.BooleanOptionalAction, required=True)
    resume.add_argument("identifier")
    cancel.add_argument("--client", required=True)
    cancel.add_argument("--operation-id", required=True)
    result = commands.add_parser("result", help="Read an exact bounded terminal result over HTTP", allow_abbrev=False)
    result.add_argument("identifier")
    result.add_argument("--client", required=True)
    result.add_argument("--operation-id", required=True)
    result.add_argument("--wait-terminal-seconds", type=int, required=True)
    profiles = commands.add_parser("profiles", help="Query retained profiles over HTTP", allow_abbrev=False)
    profiles.add_argument("--client", required=True)
    for name in (
        "profile",
        "status",
        "submission",
        "receipt",
        "runs",
        "events",
        "prior",
        "artifact",
        "candidate",
        "generation",
        "evidence",
        "artifact-inventory",
        "assessment",
    ):
        query = commands.add_parser(name, allow_abbrev=False)
        query.add_argument("--client", required=True)
        if name in {
            "profile",
            "status",
            "submission",
            "receipt",
            "prior",
            "artifact",
            "candidate",
            "generation",
            "evidence",
            "artifact-inventory",
            "assessment",
        }:
            query.add_argument("identifier")
        if name == "profile":
            query.add_argument("--revision", required=True)
        if name == "receipt":
            query.add_argument("--kind", required=True, choices=("SUBMIT", "CANCEL", "RESUME"))
        if name in {"runs", "events"}:
            query.add_argument("--first", required=True, type=int)
            query.add_argument("--after")
        if name == "artifact":
            query.add_argument("--kind", required=True, choices=("PRIOR", "CANDIDATE", "GENERATION", "EVIDENCE"))
            query.add_argument("--reference-id", required=True)
            query.add_argument(
                "--name",
                required=True,
                choices=("PRIOR_JSON", "CANDIDATE_JSON", "CANDIDATE_YAML", "PROVENANCE_JSON", "EVIDENCE_JSON"),
            )
            query.add_argument("--sha256", required=True)
            query.add_argument("--offset", default="0")
            query.add_argument("--limit", type=int, default=65536)
        if name in {"candidate", "generation", "evidence", "artifact-inventory", "assessment"}:
            query.add_argument("--reference-id", required=True)
        if name == "artifact-inventory":
            query.add_argument("--kind", required=True, choices=("PRIOR", "CANDIDATE", "GENERATION", "EVIDENCE"))
    admin = commands.add_parser("admin", help="Explicit query scope administration", allow_abbrev=False)
    actions = admin.add_subparsers(dest="action", required=True)
    for name in ("initialize-schema", "initialize-scope", "initialize-artifacts", "register-profile"):
        action = actions.add_parser(name, allow_abbrev=False)
        action.add_argument("--config", required=True)
        if name == "initialize-artifacts":
            action.add_argument("--create", action="store_true")
        if name == "register-profile":
            action.add_argument("--registration", required=True)
    for name in ("api-launch", "api-status", "api-stop", "api-reconcile", "api-serve"):
        command = commands.add_parser(name, allow_abbrev=False)
        command.add_argument("--config", required=True)
        command.add_argument("--instance", required=True)
        if name == "api-serve":
            command.add_argument("--lease-fd", required=True, type=int)
            command.add_argument("--gate-fd", required=True, type=int)


def _run_installed(options):
    """Execute only the explicitly selected installed operation with static errors."""
    if options.command == "setup-readiness":
        from .setup_readiness import MAX_SELECTION_BYTES, setup_readiness

        try:
            raw = None
            if options.selection is not None:
                # Same regular-file/no-follow discipline as contract inspection.
                fd = os.open(options.selection, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    metadata = os.fstat(fd)
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_SELECTION_BYTES:
                        raise ValueError("invalid file")
                    with os.fdopen(fd, "rb", closefd=False) as stream:
                        raw = stream.read(MAX_SELECTION_BYTES + 1)
                finally:
                    os.close(fd)
            report = setup_readiness(raw)
        except (OSError, ValueError, RecursionError, AttributeError):
            print("setup-readiness: invalid selection file", file=sys.stderr)
            return 2
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0
    if options.command in {"submit", "cancel", "resume", "result"}:
        try:
            from .api.client import query
            from .api.client import result as read_result
            from .contracts import canonical_json

            code = 0
            if options.command == "submit":
                contract = _read_contract(options.contract)
                result = query(
                    options.client, "submit", identifier=options.operation_id, raw_contract=canonical_json(contract)
                )
                receipt = result["data"].get("submitWorkflow", {})
                if (
                    receipt.get("__typename") != "SubmissionReceipt"
                    or receipt.get("operationId") != options.operation_id
                    or receipt.get("acceptedContractDigest") != contract_digest(contract)
                ):
                    raise ValueError("Submission unavailable")
            elif options.command == "cancel":
                result = query(
                    options.client, "cancel", identifier=options.identifier, operation_id=options.operation_id
                )
                outcome = result["data"].get("cancelWorkflow", {})
                if outcome.get("__typename") != "CancellationResult":
                    raise ValueError("Cancellation unavailable")
                code = 0 if outcome.get("durable") == "recorded" else 2
            elif options.command == "resume":
                result = query(
                    options.client,
                    "resume",
                    identifier=options.identifier,
                    operation_id=options.operation_id,
                    expected_version=options.expected_version,
                    renew_authorization=options.renew_authorization,
                )
                if result["data"].get("resumeWorkflow", {}).get("__typename") != "ResumeReceipt":
                    raise ValueError("Resume unavailable")
            else:
                result = read_result(
                    options.client,
                    options.identifier,
                    operation_id=options.operation_id,
                    wait_terminal_seconds=options.wait_terminal_seconds,
                )
        except Exception:
            print("workflow: command rejected or result unavailable", file=sys.stderr)
            return 2
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return code
    if options.command in {
        "profiles",
        "profile",
        "status",
        "submission",
        "receipt",
        "runs",
        "events",
        "prior",
        "artifact",
        "candidate",
        "generation",
        "evidence",
        "artifact-inventory",
        "assessment",
    }:
        try:
            from .api.client import query

            result = query(
                options.client,
                options.command,
                **{
                    key: getattr(options, key, None)
                    for key in (
                        "identifier",
                        "revision",
                        "kind",
                        "first",
                        "after",
                        "reference_id",
                        "sha256",
                        "offset",
                        "limit",
                    )
                },
                artifact_name=getattr(options, "name", None),
            )
        except Exception:
            print("workflow: query unavailable", file=sys.stderr)
            return 2
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    if options.command.startswith("api-"):
        try:
            from .api.installed_config import load
            from .api.instance import instance_id, launch, observe

            selected = instance_id(options.instance)
            config = load(options.config)
            if options.command == "api-serve":
                from .api.server import serve

                return serve(config, selected, options.lease_fd, options.gate_fd)
            if options.command == "api-launch":
                result, code = launch(config, selected)
            else:
                result, code = observe(
                    config, selected, stop=options.command == "api-stop", reconcile=options.command == "api-reconcile"
                )
        except Exception:
            print("workflow: instance observation incomplete", file=sys.stderr)
            return 2
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return code
    if options.command in {"setup", "admin", "credentials-update", "credentials-remove"}:
        try:
            from .api.installed_config import load, setup

            config = load(options.config)
            if options.command == "setup":
                result = setup(config, options.credentials_fd)
            elif options.command.startswith("credentials-"):
                from .api.installed_config import change_credentials

                result = change_credentials(
                    config,
                    remove=options.command == "credentials-remove",
                    credential_fd=getattr(options, "credentials_fd", None),
                )
            else:
                from .api.installed_composition import administer

                result = administer(
                    config,
                    options.action,
                    create=getattr(options, "create", False),
                    registration_path=getattr(options, "registration", None),
                )
        except Exception:
            print("workflow: operation rejected or incomplete", file=sys.stderr)
            return 2
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    return None


def main(argv=None):
    """Inspect an explicitly supplied request file; planned dependencies are not live checks."""
    parser = _StaticArgumentParser(prog="workflow.cli", description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser(
        "inspect-contract",
        help="Inspect intent without checking live readiness",
        allow_abbrev=False,
    )
    inspect.add_argument("path", help="Explicit JSON request file")
    _add_installed_arguments(commands)
    try:
        options = parser.parse_args(argv)
    except ValueError:
        print("inspect-contract: invalid arguments", file=sys.stderr)
        return 2
    except SystemExit as error:
        return error.code
    installed_result = _run_installed(options)
    if installed_result is not None:
        return installed_result
    try:
        contract = _read_contract(options.path)
        dependencies = required_dependencies(contract)
    except (OSError, ValueError, RecursionError):
        print("inspect-contract: invalid request file", file=sys.stderr)
        return 2
    try:
        project_required_criteria(contract)
        scene_assessment = {"compatible": True, "code": "supported_projection"}
    except ValueError:
        scene_assessment = {"compatible": False, "code": "unsupported_scene_assessment"}
    required = sorted(c.criterion_id for c in contract.criteria if c.requirement == "required")
    advisory = sorted(c.criterion_id for c in contract.criteria if c.requirement == "advisory")
    summary = {
        "schema_version": contract.schema_version,
        "contract_digest": contract_digest(contract),
        "required_criteria": {"ids": required, "count": len(required)},
        "advisory_criteria": {"ids": advisory, "count": len(advisory)},
        "planned_dependencies": sorted(
            ({"category": r.dependency_id, "profile_id": r.profile_id} for r in dependencies),
            key=lambda item: (item["category"], item["profile_id"]),
        ),
        "scene_assessment": scene_assessment,
        "execution_released": False,
        "readiness_checked": False,
    }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
