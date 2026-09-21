# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure contract inspection; execution belongs to the examples composition CLI."""

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
    setup = commands.add_parser("setup", help="Create explicit private query configuration state", allow_abbrev=False)
    setup.add_argument("--config", required=True)
    setup.add_argument("--create", action="store_true", required=True)
    setup.add_argument("--credentials-fd", type=int, required=True)
    for name in ("credentials-update", "credentials-remove"):
        credentials = commands.add_parser(name, allow_abbrev=False)
        credentials.add_argument("--config", required=True)
        if name == "credentials-update":
            credentials.add_argument("--credentials-fd", type=int, required=True)
    profiles = commands.add_parser("profiles", help="Query retained profiles over HTTP", allow_abbrev=False)
    profiles.add_argument("--client", required=True)
    for name in ("profile", "status", "submission", "receipt", "runs", "events"):
        query = commands.add_parser(name, allow_abbrev=False)
        query.add_argument("--client", required=True)
        if name in {"profile", "status", "submission", "receipt"}:
            query.add_argument("identifier")
        if name == "profile":
            query.add_argument("--revision", required=True)
        if name == "receipt":
            query.add_argument("--kind", required=True, choices=("SUBMIT", "CANCEL", "RESUME"))
        if name in {"runs", "events"}:
            query.add_argument("--first", required=True, type=int)
            query.add_argument("--after")
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
    if options.command in {"profiles", "profile", "status", "submission", "receipt", "runs", "events"}:
        try:
            from .api.client import query

            result = query(
                options.client,
                options.command,
                **{key: getattr(options, key, None) for key in ("identifier", "revision", "kind", "first", "after")},
            )
        except Exception:
            print("workflow: query unavailable", file=sys.stderr)
            return 2
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    if options.command.startswith("api-"):
        try:
            from .api.instance import instance_id, launch, observe
            from .api.installed_config import load

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
