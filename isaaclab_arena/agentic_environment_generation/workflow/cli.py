# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Initial read-only CLI slice: inspect intent, never release execution or check readiness."""

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


def main(argv=None):
    """Inspect an explicitly supplied request file; planned dependencies are not live checks."""
    parser = _StaticArgumentParser(prog="workflow.cli", description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser(
        "inspect-contract", help="Inspect intent without checking live readiness", allow_abbrev=False
    )
    inspect.add_argument("path", help="Explicit JSON request file")
    try:
        options = parser.parse_args(argv)
    except ValueError:
        print("inspect-contract: invalid arguments", file=sys.stderr)
        return 2
    except SystemExit as error:
        return error.code
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
