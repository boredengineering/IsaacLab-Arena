# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Separate E1 installed execution bootstrap; source review is not run authority."""

import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import runpy
import selectors
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

if __name__ == "__main__":
    assert sys.flags.isolated == sys.flags.no_site == 1
    sys.path.insert(0, "/source/scripts")

import workflow_process_harness as base
from workflow_graphql_network_harness import executing

SELF = "scripts/workflow_graphql_execution_join_harness.py"
TEST = "isaaclab_arena/tests/test_environment_workflow_graphql_execution_joined_neo4j.py"
FIXTURE = "scripts/workflow_graphql_execution_join_fixture.py"
SPEC = "outputs/workflow/plan04-implementation/installed-execution/join-spec.md"
DESIGN = "outputs/workflow/plan04-implementation/installed-execution/join-design.md"
INVENTORY = "outputs/workflow/plan04-implementation/installed-execution/join-source-files.json"
MODULE = "isaaclab_arena.agentic_environment_generation.workflow.cli"
EXECUTABLE = "/isaac-sim/kit/python/bin/python3"
CONFIGS = tuple(f"/tmp/graphql-execution/{kind}/config/server.json" for kind in ("query", "execution"))
CONFIG = CONFIGS[1]
INSTANCE = "dddddddddddddddddddddddddddddddd"
CLIENT = f"/tmp/graphql-execution/execution/runtime/instances/{INSTANCE}/client.json"
CONTRACT = "/tmp/graphql-execution/execution/config/contract.json"
OPERATION = "e1-submit"
JOIN_CASE = os.environ.get("ARENA_WORKFLOW_JOIN_CASE", "happy")
assert JOIN_CASE in {"happy", "cancel", "resume", "evidence"}
RUN_ID = hashlib.sha256(
    json.dumps(["execution-admission-test", "execution", OPERATION], separators=(",", ":")).encode()
).hexdigest()
ADMIN = [
    ["admin", "initialize-schema", "--config", CONFIG],
    ["admin", "initialize-scope", "--config", CONFIG],
    ["admin", "initialize-artifacts", "--config", CONFIG, "--create"],
    *[
        [
            "admin",
            "register-profile",
            "--config",
            CONFIG,
            "--registration",
            f"/tmp/graphql-execution/execution/config/{role}.json",
        ]
        for role in ("generation", "assessment")
    ],
]
LAUNCH = ["api-launch", "--config", CONFIG, "--instance", INSTANCE]
RESUME_INSTANCE = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
RESUME_CLIENT = f"/tmp/graphql-execution/execution/runtime/instances/{RESUME_INSTANCE}/client.json"
RELAUNCH = ["api-launch", "--config", CONFIG, "--instance", RESUME_INSTANCE]
RECONCILE = ["api-reconcile", "--config", CONFIG, "--instance", INSTANCE]
READBACK = ["p1-readback", "--client", CLIENT]
RESUME = [
    "resume",
    RUN_ID,
    "--client",
    RESUME_CLIENT,
    "--operation-id",
    "p1-resume",
    "--renew-authorization",
    "--expected-version",
    "reserved-version",
]
READ_CLIENT = RESUME_CLIENT if JOIN_CASE == "resume" else CLIENT
READ_INSTANCE = RESUME_INSTANCE if JOIN_CASE == "resume" else INSTANCE
LOST_RESPONSE = ["p1-resume-lost", "--client", RESUME_CLIENT]
CONTROL_CHECK = ["p1-control", "--client", READ_CLIENT]
SUBMIT = ["submit", "--client", CLIENT, "--operation-id", OPERATION, "--contract", CONTRACT]
CANCEL = ["cancel", RUN_ID, "--client", CLIENT, "--operation-id", "p1-cancel"]
RESULT = ["result", RUN_ID, "--client", READ_CLIENT, "--operation-id", OPERATION, "--wait-terminal-seconds", "120"]
STOP = ["api-stop", "--config", CONFIG, "--instance", READ_INSTANCE]
STATUS = ["api-status", "--config", CONFIG, "--instance", READ_INSTANCE]
THREAD_ENV = {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
LAUNCH_ENV = {"HOME": "/tmp", "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
ENV = {**LAUNCH_ENV, **THREAD_ENV, **({"ARENA_WORKFLOW_JOIN_CASE": JOIN_CASE} if JOIN_CASE != "happy" else {})}
COMMANDS = [*ADMIN, LAUNCH, SUBMIT, *([CANCEL] if JOIN_CASE == "cancel" else []), RESULT]
if JOIN_CASE == "resume":
    COMMANDS = [*ADMIN, LAUNCH, SUBMIT, RECONCILE, RELAUNCH, LOST_RESPONSE, RESUME, CONTROL_CHECK, RESULT, READBACK]
if JOIN_CASE == "cancel":
    COMMANDS.append(CONTROL_CHECK)
if JOIN_CASE == "evidence":
    COMMANDS.append(READBACK)
CLIENT_LAUNCHES = 2 + len(COMMANDS) + 2
SOURCE_LIMIT = 384  # Exact static closure plus four generated leaves.
SOURCE_MANIFEST_LIMIT = 65536
ACTIVE = None
PROFILE_CALL_NAMES = frozenset({
    "__init__",
    "launch",
    "render",
    "retrieve_snapshot",
    "driver",
    "query",
    "launch_tiled",
    "capture_launch",
    "Open",
    "OpenMasked",
    "synthetic_response",
    "claim_intent",
})

# Bytes-only candidates, NOT import permissions. First five are the existing
# provisioner's ALLOWED; last three were retained immutable metadata roots.
DEPENDENCY_ROOTS = (
    "/isaac-sim/kit/python/lib/python3.12/site-packages",
    "/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle",
    "/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle",
    "/isaac-sim/extscache/omni.cip.pip-2.0.5+lx64.cp312/pip_prebundle",
    "/isaac-sim/extscache/omni.ai.langchain.core-2.3.1+109.0.0.lx64.cp312/pip_core_prebundle",
    "/isaac-sim/exts/omni.isaac.core_archive/pip_prebundle",
    "/isaac-sim/exts/omni.pip.compute/pip_prebundle",
    "/isaac-sim/exts/omni.pip.cloud/pip_prebundle",
)
DEPENDENCY_TARGETS = {"pyyaml": "yaml", "openai": "openai", "gitpython": "git"}
DEPENDENCY_RECIPES = {
    "/opt/arena-f0/provision-recipe.json": "18ab4e13d3a0a4dc88390d852c632c437fcf980847e19b58d81b7ee74b111753",
    "/opt/arena-f0/graphql-test-v1-recipe.json": "4470dde2d4822e1cd4ecd451dbe534d772aab0037cd49b9c5aec508a51562aaf",
}


def dependency_location_probe(preimport, guard, runner):
    """Locate only fixed immutable dependency bytes; never import or enable them."""
    import sysconfig
    from email.parser import BytesParser

    before_path = list(sys.path)
    before_modules = {name: module for name, module in sys.modules.copy().items()
                      if name.split(".")[0] in DEPENDENCY_TARGETS.values()}
    before_forbidden = dict(guard.forbidden)
    deadline = time.monotonic() + 5
    limits = dict(roots=8, entries_per_root=4096, metadata_files=32,
                  file_bytes=262144, total_bytes=4194304, report_bytes=524288,
                  seconds=5, link_bytes=1024, metadata_field_bytes=131072)
    report: dict = dict(
        schema_version=1, status="failed", scope="fixed immutable bytes only; no dependency imports",
        image=runner.GRAPHQL_IMAGE, image_binding="existing host select_graphql_runtime/owned inspect, not self-discovery",
        provision_manifest_sha256=runner.GRAPHQL_MANIFEST_SHA256,
        not_established=["importability", "dependency closure", "compatibility", "native permission", "new path admission"],
        limits=limits, sys_path=before_path, targets=DEPENDENCY_TARGETS,
        interpreter=sys.executable, python_version=list(sys.version_info[:3]),
        preimport_kernel_denial=preimport["kernel_denial"], roots=[], recipes={},
        files_read=0, metadata_files=0, bytes_read=0, metadata_field_bytes=0,
    )

    def bounded():
        assert time.monotonic() < deadline, "Dependency metadata deadline"

    def point(path, *, listing=False):
        """Open each ancestor NOFOLLOW; links are evidence, never traversed."""
        bounded()
        assert path.startswith("/") and len(path) <= 1024
        parts = path[1:].split("/")
        assert len(parts) <= 24 and all(p not in {"", ".", ".."} for p in parts)
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        row: dict = dict(path=path, state="unread", links=[])
        try:
            assert os.fstatvfs(fd).f_flag & os.ST_RDONLY
            for index, part in enumerate(parts):
                bounded()
                at = "/" + "/".join(parts[:index + 1])
                try:
                    info = os.stat(part, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    return dict(row, state="missing", at=at), None
                if stat.S_ISLNK(info.st_mode):
                    target = os.readlink(part, dir_fd=fd)
                    assert len(os.fsencode(target)) <= limits["link_bytes"]
                    return dict(row, state="symlink_not_followed", at=at,
                                links=[dict(path=at, target=target)]), None
                directory = index < len(parts) - 1 or listing
                if directory and not stat.S_ISDIR(info.st_mode):
                    return dict(row, state="not_directory", at=at), None
                if not directory and not stat.S_ISREG(info.st_mode):
                    return dict(row, state="not_regular", at=at), None
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if directory:
                    flags |= os.O_DIRECTORY
                nxt = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = nxt
                opened = os.fstat(fd)
                assert (opened.st_dev, opened.st_ino, opened.st_mode) == (info.st_dev, info.st_ino, info.st_mode)
                assert os.fstatvfs(fd).f_flag & os.ST_RDONLY
            row.update(physical=path, mode=stat.S_IMODE(opened.st_mode), uid=opened.st_uid,
                       gid=opened.st_gid, device=opened.st_dev, inode=opened.st_ino)
            if listing:
                names = []
                with os.scandir(fd) as entries:
                    for entry in entries:
                        bounded()
                        assert len(names) < limits["entries_per_root"], "Dependency immediate listing ceiling"
                        assert len(os.fsencode(entry.name)) <= 255
                        names.append(entry.name)
                return dict(row, state="directory", immediate_entries=len(names)), sorted(names)
            assert opened.st_nlink == 1 and opened.st_size <= limits["file_bytes"]
            assert report["bytes_read"] + opened.st_size <= limits["total_bytes"]
            with os.fdopen(os.dup(fd), "rb") as stream:
                data = stream.read(limits["file_bytes"] + 1)
            assert len(data) == opened.st_size and len(data) <= limits["file_bytes"]
            after = os.fstat(fd)
            assert (after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (
                opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
            report["files_read"] += 1
            report["bytes_read"] += len(data)
            return dict(row, state="regular", size=len(data), sha256=hashlib.sha256(data).hexdigest()), data
        finally:
            os.close(fd)

    def normalize(name):
        return re.sub(r"[-_.]+", "-", name).lower()

    try:
        assert guard.role == "server" and ACTIVE is guard
        assert sys.flags.isolated == sys.flags.no_site == sys.flags.ignore_environment == 1
        assert os.getuid() == os.getgid() == 1000 and sys.executable == EXECUTABLE
        assert runner.GRAPHQL_IMAGE == "sha256:b94e17024f1e123ac5a42759ab56651a18823fda7c701e765cba31f200154cdd"
        assert runner.GRAPHQL_MANIFEST_SHA256 == "03764536ed54c1f59cbf46305c5bc4ba618e2dc1deeeac7ffdfb21a0dffbf810"
        assert before_path == runner._GRAPHQL_PROBE["PATHS"]
        assert list(DEPENDENCY_ROOTS[:5]) == runner._GRAPHQL_PROBE["ALLOWED"]
        assert sysconfig.get_path("purelib") == sysconfig.get_path("platlib") == DEPENDENCY_ROOTS[0]
        for path, digest in DEPENDENCY_RECIPES.items():
            row, _raw = point(path)
            report["recipes"][path] = row
            assert row["state"] == "regular" and row["sha256"] == digest, "Immutable recipe binding"
        for root in DEPENDENCY_ROOTS:
            identity, names = point(root, listing=True)
            row: dict = dict(path=root, identity=identity, modules={}, distributions=[],
                             on_original_sys_path=root in before_path, metadata_search="unsearched")
            report["roots"].append(row)
            if names is None:
                continue
            for module in DEPENDENCY_TARGETS.values():
                row["modules"][module] = [point(root + "/" + leaf)[0]
                                          for leaf in (module + "/__init__.py", module + ".py")]
            for name in names:
                if not name.endswith(".dist-info"):
                    continue
                distribution = normalize(name[:-10].rsplit("-", 1)[0])
                if distribution not in DEPENDENCY_TARGETS:
                    continue
                assert re.fullmatch(r"[A-Za-z0-9_.+-]{1,200}\.dist-info", name)
                assert report["metadata_files"] < limits["metadata_files"]
                report["metadata_files"] += 1
                metadata, raw = point(root + "/" + name + "/METADATA")
                item = dict(distribution=distribution, metadata=metadata)
                row["distributions"].append(item)
                if raw is None:
                    continue
                headers = BytesParser().parsebytes(raw, headersonly=True)
                assert len(headers.get_all("Name", [])) == len(headers.get_all("Version", [])) == 1
                assert normalize(headers["Name"]) == distribution
                requirements = headers.get_all("Requires-Dist", [])
                assert len(requirements) <= 128 and all(len(x) <= 1024 for x in requirements)
                assert 0 < len(headers["Version"]) <= 128
                requires_python = headers.get("Requires-Python")
                assert requires_python is None or len(requires_python) <= 256
                fields = dict(name=headers["Name"], version=headers["Version"],
                              requires_python=requires_python, requires_dist=requirements)
                field_bytes = len(json.dumps(fields, sort_keys=True).encode())
                assert report["metadata_field_bytes"] + field_bytes <= limits["metadata_field_bytes"]
                report["metadata_field_bytes"] += field_bytes
                item.update(fields)
            row["metadata_search"] = "bounded_immediate_complete"
        bounded()
        assert len(json.dumps(report, sort_keys=True).encode()) <= limits["report_bytes"]
        report["status"] = "completed"
    except (AssertionError, OSError, ValueError) as error:
        # Metadata failures are diagnostic, not a replacement for the original
        # installed startup result. No exception messages/locals are retained.
        report["error_type"] = type(error).__name__
    finally:
        assert sys.path == before_path and guard.forbidden == before_forbidden
        assert before_modules == {name: module for name, module in sys.modules.copy().items()
                                  if name.split(".")[0] in DEPENDENCY_TARGETS.values()}
    # Defensive bounded fallback remains diagnostic and never enables paths.
    if len(json.dumps(report, sort_keys=True).encode()) > limits["report_bytes"]:
        report.update(status="failed", error_type="ReportOverflow", roots=[])
    return report


# Discovery frontier only, NOT import permissions. Second frontier NOT RUN.
# Keep source-grounded native targets separate from transitive import admission.
REGISTRATION_TARGETS = {
    "openai": "openai", "torch": "torch", "usd-core": "pxr", "isaaclab": "isaaclab", "warp-lang": "warp"
}
REGISTRATION_POINTS = (
    "/isaac-sim/python.sh",
    "/isaac-sim/setup_python_env.sh",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/__init__.py",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/setup.py",
    "/workspace/submodules/IsaacLab/source/isaaclab/isaaclab/__init__.py",
    "/workspace/submodules/IsaacLab/source/isaaclab/setup.py",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/envs/__init__.py",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/envs/__init__.pyi",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/envs/manager_based_env.py",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/assets/__init__.py",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/assets/__init__.pyi",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/assets/articulation/__init__.py",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/assets/articulation/__init__.pyi",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/assets/articulation/articulation.py",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/utils/__init__.py",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/utils/__init__.pyi",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/utils/module.py",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/utils/warp/__init__.py",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/utils/warp/__init__.pyi",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/utils/warp/ops.py",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/scene/__init__.py",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/scene/__init__.pyi",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/scene/interactive_scene.py",
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/assets/articulation/base_articulation_data.py",
    "/isaac-sim/kit/python/lib/python3.12/site-packages/warp/config.py",
    "/isaac-sim/kit/python/lib/python3.12/site-packages/warp/_src/__init__.py",
    "/isaac-sim/kit/python/lib/python3.12/site-packages/warp/_src/context.py",
)
REGISTRATION_PINS = {
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/__init__.py": (
        "24e50c4e57b9be1c55aa949f1b8dd416d95e6002e12941abe33a7a6eb16f697b"
    ),
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/setup.py": (
        "e155aff6d90a2d095f5224edb60d27117612accd3b6f21c3a34ea715df94f1c2"
    ),
    "/isaac-sim/kit/python/lib/python3.12/site-packages/openai/__init__.py": (
        "b9d647b12e6a04aa430c89306e83d9e65c7c55237096b609d97e85d64dc1f3e0"
    ),
    "/isaac-sim/kit/python/lib/python3.12/site-packages/openai-3.3.1.dist-info/METADATA": (
        "46e6686dc5fec7ad1e90ea8531b3cf85267f7075813eb72f67ac92083b2da8c7"
    ),
    "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab/utils/warp/__init__.py": (
        "c5bd9c6ab69725f706d7586a2c560fdf9d45c6145f5d387412dd2fbc878d6c7d"
    ),
    "/isaac-sim/kit/python/lib/python3.12/site-packages/warp/__init__.py": (
        "4a272a0c07b087b8f43710ebb061f02b1bc002a1bf4f701c336528c64a6ba2f7"
    ),
}


# SOURCE DESIGN ONLY: fresh independent review of this exception is required
# before the existing metadata invocation. This grants no execution admission.
REGISTRATION_CONTEXT_EXCEPTION = {
    "path": "/isaac-sim/kit/python/lib/python3.12/site-packages/warp/_src/context.py",
    "file_bytes": 476553,
    "report_bytes": 131072,
}


def registration_metadata_point(
    path, runner, report, deadline, *, listing=False
) -> tuple[dict, bytes | list[str] | None]:
    """Observe a fixed candidate without following links or executing its bytes."""
    assert type(path) is str and len(path) <= 1024 and type(listing) is bool
    parts = path[1:].split("/")
    assert path.startswith("/") and len(parts) <= 24 and all(p not in {"", ".", ".."} for p in parts)
    if listing:
        assert path in DEPENDENCY_ROOTS
    elif path not in REGISTRATION_POINTS and path not in DEPENDENCY_RECIPES:
        root = next((p for p in DEPENDENCY_ROOTS if path.startswith(p + "/")), None)
        assert root is not None
        relative = path[len(root) + 1 :]
        leaves = {m + suffix for m in REGISTRATION_TARGETS.values() for suffix in ("/__init__.py", ".py")}
        if relative not in leaves:
            assert re.fullmatch(r"[A-Za-z0-9_.+-]{1,200}\.dist-info/METADATA", relative)
            distribution = re.sub(r"[-_.]+", "-", relative.split("/")[0][:-10].rsplit("-", 1)[0]).lower()
            assert distribution in REGISTRATION_TARGETS
    assert time.monotonic() < deadline, "Registration metadata deadline"
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    row: dict = dict(path=path, state="unread", links=[])
    try:
        assert os.fstatvfs(fd).f_flag & os.ST_RDONLY
        for index, part in enumerate(parts):
            assert time.monotonic() < deadline
            at = "/" + "/".join(parts[: index + 1])
            try:
                info = os.stat(part, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                return dict(row, state="missing", at=at), None
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(part, dir_fd=fd)
                assert len(os.fsencode(target)) <= 1024
                return dict(row, state="symlink_not_followed", at=at, links=[dict(path=at, target=target)]), None
            directory = index < len(parts) - 1 or listing
            if directory and not stat.S_ISDIR(info.st_mode):
                return dict(row, state="not_directory", at=at), None
            if not directory and not stat.S_ISREG(info.st_mode):
                return dict(row, state="not_regular", at=at), None
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if directory:
                flags |= os.O_DIRECTORY
            nxt = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = nxt
            opened = os.fstat(fd)
            assert (opened.st_dev, opened.st_ino, opened.st_mode) == (info.st_dev, info.st_ino, info.st_mode)
            assert os.fstatvfs(fd).f_flag & os.ST_RDONLY
        row.update(
            physical=path,
            mode=stat.S_IMODE(opened.st_mode),
            uid=opened.st_uid,
            gid=opened.st_gid,
            device=opened.st_dev,
            inode=opened.st_ino,
        )
        if listing:
            names = []
            with os.scandir(fd) as entries:
                for entry in entries:
                    assert time.monotonic() < deadline and len(names) < 4096
                    assert len(os.fsencode(entry.name)) <= 255
                    names.append(entry.name)
            return dict(row, state="directory", immediate_entries=len(names)), sorted(names)
        file_limit = 262144
        if path == REGISTRATION_CONTEXT_EXCEPTION["path"]:
            # Exact prior stat observation, not a generic raised ceiling. Every
            # initializer pin must already have passed the unchanged reader.
            assert opened.st_size == REGISTRATION_CONTEXT_EXCEPTION["file_bytes"]
            assert stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1
            assert row["physical"] == path and row["links"] == []
            assert os.fstatvfs(fd).f_flag & os.ST_RDONLY
            assert set(report["pins"]) == set(REGISTRATION_PINS)
            for pinned_path, digest in REGISTRATION_PINS.items():
                pinned = report["pins"][pinned_path]
                assert pinned["path"] == pinned["physical"] == pinned_path
                assert pinned["state"] == "regular" and pinned["links"] == []
                assert pinned["sha256"] == digest
            file_limit = REGISTRATION_CONTEXT_EXCEPTION["file_bytes"]
        if opened.st_size > file_limit:
            report["source_bound_failure"] = dict(
                row, state="source_file_limit_exceeded", size=opened.st_size,
                file_bytes=file_limit, source_evidence=None,
            )
        assert opened.st_nlink == 1 and opened.st_size <= file_limit
        # Both our read and the existing physical verifier's read are charged.
        assert report["bytes_read"] + 2 * opened.st_size <= 4194304
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(file_limit + 1)
        assert len(raw) == opened.st_size
        after = os.fstat(fd)
        assert (after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
        row.update(state="regular", size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        report["bytes_read"] += len(raw)
        # No broad ALLOWED expansion: the no-follow read above precedes reuse of
        # the existing immutable physical verifier for this exact parent only.
        checked, physical = runner._GRAPHQL_PROBE["physical_file"](path, [str(Path(path).parent)])
        report["bytes_read"] += len(checked)
        assert checked == raw and all(row[k] == value for k, value in physical.items())
        assert row["links"] == []
        assert time.monotonic() < deadline
        if path in REGISTRATION_PINS:
            assert row["sha256"] == REGISTRATION_PINS[path], "Registration pinned bytes changed"
        if path == REGISTRATION_CONTEXT_EXCEPTION["path"]:
            report["context_exception_witness"] = dict(row)
        return row, raw
    finally:
        os.close(fd)


def registration_metadata_probe(preimport, guard, runner, report, *, admission=None, trigger=None):
    """Prepare bounded source evidence without enabling package imports."""
    import ast

    def dependency_frontier():
        started = time.monotonic()
        # Only one literal finite metadata page; prior source/native facts stay retained.
        p = "/isaac-sim/kit/python/lib/python3.12/site-packages"
        page = INITIALIZATION_METADATA_PAGE
        paths = initialization_metadata_page_selection(page)["sources"]
        assert trigger == dict(fullname="lazy_loader", origin=p + "/lazy_loader/__init__.py")
        assert guard.initialization_case == "positive" and guard.initialization_role == "init-server"
        assert runner.GRAPHQL_IMAGE == "sha256:b94e17024f1e123ac5a42759ab56651a18823fda7c701e765cba31f200154cdd"
        assert runner.GRAPHQL_MANIFEST_SHA256 == "03764536ed54c1f59cbf46305c5bc4ba618e2dc1deeeac7ffdfb21a0dffbf810"
        budget = admission.budget
        saved = {key: budget[key] for key in ("deadline", "byte_limit", "file_limit", "entries", "entry_limit") if key in budget}
        initial_bytes = budget["bytes"]
        report.update(
            schema_version=1, status="partial", trigger=trigger, role=guard.initialization_role, pid=os.getpid(),
            image=runner.GRAPHQL_IMAGE, provision_manifest_sha256=runner.GRAPHQL_MANIFEST_SHA256,
            expanded_import_admitted=False, package_imports_executed=False,
            complete_dependency_closure=False, requested_manifest=paths,
            selection="one fixed metadata content page; candidate coverage only, no discovery or admission",
            retained_evidence=dict(status="retained-not-current", coverage_joined=False,
                run="arena-s2-init-fda1fe67d99d469997d24745cb648ca6",
                manifest_sha256="0f3b54e9b0361e797226170c505ef5f8b7599dced032d050128866af314231ce"),
            baseline={}, baseline_complete=False, module_origins=[], module_origins_complete=False,
            source_capture_complete=False, imports_complete=False,
            boundary=initialization_metadata_page_state(page, saved.get("byte_limit", 2 * 1024**3)),
            source_manifest_binding="enclosing initialization-init-server.json source_sha256",
            original_refusal_retained=True, cleanup="enclosing role lifecycle; inspection opens close in finally",
            encoded_bytes=None, encoded_bytes_upper_bound=1048576, deadline_exhausted=False, entries=0,
            role_read_limit=saved.get("byte_limit", 2 * 1024**3),
            files=[dict(path=path, status="not_read_pending", imports_complete=False) for path in paths], bytes_read=0,
            limits=dict(seconds=5, file_bytes=262144, total_bytes=4194304, report_bytes=1048576, imports=512),
        )
        # Reserve space for all terminal statuses/counters before accepting any
        # variable data. JSON escaping, not raw UTF-8 length, determines cost.
        encoder = json.JSONEncoder(sort_keys=True)
        encoding_deadline = None

        def size(value):
            count = 0
            for chunk in encoder.iterencode(value):
                if encoding_deadline is not None and time.monotonic() >= encoding_deadline:
                    raise TimeoutError("S2 frontier encoding deadline")
                count += len(chunk.encode("utf-8"))
                if count > 1048576:
                    return count
            return count

        used = size(report)

        def replace(container, key, value):
            nonlocal used
            delta = size(value) - size(container[key])
            if used + delta > 1048576 - 8192:
                return False
            container[key] = value
            used += delta
            return True

        def add(container, key, value):
            nonlocal used
            assert key not in container and type(key) is str
            # Default JSON separators are ': ' and ', '; encode each new key
            # and value once rather than copying/re-encoding growing metadata.
            delta = size(key) + 2 + size(value) + (2 if container else 0)
            if used + delta > 1048576 - 8192:
                return False
            container[key] = value
            used += delta
            return True

        def append(container, value):
            nonlocal used
            delta = size(value) + (2 if container else 0)
            if used + delta > 1048576 - 8192:
                return False
            container.append(value)
            used += delta
            return True

        budget["deadline"] = min(saved["deadline"], started + 5)
        budget["byte_limit"] = min(saved.get("byte_limit", 8 * 1024**3), initial_bytes + 4194304)
        budget["file_limit"] = min(saved.get("file_limit", 2 * 1024**3), 262144)
        budget["entries"] = saved.get("entries", 0)
        budget["entry_limit"] = min(saved.get("entry_limit", 4096), 4096)
        encoding_deadline = budget["deadline"]
        try:
            initialization_metadata_page_capture(admission, report, budget, append, replace, page=page)
            # Selected raw metadata precedes four new helper sources on EP-A only.
            for index, path in enumerate(paths):
                row = report["files"][index]
                if time.monotonic() >= budget["deadline"]:
                    row["status"] = "not_read_deadline"
                    continue
                if used >= 1048576 - 16384:
                    row["status"] = "not_read_encoded_limit"
                    continue
                try:
                    witness, raw = initialization_physical_file(path, budget, source=True)
                    assert type(witness) is dict and type(raw) is bytes
                    observed = dict(path=path, status="read_source_omitted", witness=witness,
                                    imports_complete=False, imports=[],
                                    imports_semantics="syntactic including deferred/conditional; not execution order")
                    if not replace(report["files"], index, observed):
                        row["status"] = "read_encoded_limit"
                        continue
                    row = report["files"][index]
                    text = raw.decode("utf-8", errors="strict")
                    assert text.encode("utf-8") == raw
                    source = dict(format="complete_utf8_source" if path.endswith((".py", ".pyi")) else "complete_utf8_data",
                                  complete_source=True,
                                  bytes=len(raw), sha256=witness["sha256"], text=text)
                    if not add(row, "source_evidence", source):
                        row["status"] = "read_encoded_limit"
                        continue
                    row["status"] = "observed"
                except BaseException as error:
                    row["status"] = ("not_read_missing" if isinstance(error, FileNotFoundError)
                                     else "read_error" if "witness" in row else "not_read_refused")
                    row["error_type"] = type(error).__name__[:128]
                    if isinstance(error, AssertionError) and "witness" not in row:
                        reasons = {"S2 physical link refused": "not_read_link",
                                   "S2 physical hard link refused": "not_read_link",
                                   "S2 physical per-file ceiling": "not_read_oversize",
                                   "S2 physical read ceiling": "not_read_byte_limit"}
                        if len(error.args) == 1 and type(error.args[0]) is str:
                            row["status"] = reasons.get(error.args[0], row["status"])
                    if time.monotonic() >= budget["deadline"]:
                        row["status"] = "read_deadline" if "witness" in row else "not_read_deadline"
            # No repeated broad family/source reconciliation in this residual packet.
            for field, values in (("baseline", admission.baseline), ("module_origins", admission.modules)):
                complete = True
                for key in values if field == "baseline" else range(len(values)):
                    if time.monotonic() >= budget["deadline"]:
                        complete = False
                        break
                    retained = (add(report[field], key, values[key]) if field == "baseline"
                                else append(report[field], values[key]))
                    if not retained:
                        complete = False
                        break
                report[field + "_complete"] = complete
            # Optional AST summaries cannot starve baseline/context publication.
            for row in report["files"]:
                if "source_evidence" not in row or time.monotonic() >= budget["deadline"]:
                    continue
                if not row["path"].endswith((".py", ".pyi")):
                    row["imports_complete"] = True  # Data is deliberately never AST parsed.
                    continue
                try:
                    tree = ast.parse(row["source_evidence"]["text"].encode("utf-8"), filename=row["path"])
                    complete = True
                    parents = {}
                    for node in ast.walk(tree):
                        if time.monotonic() >= budget["deadline"]:
                            complete = False
                            break
                        for child in ast.iter_child_nodes(node):
                            parents[child] = node
                        if isinstance(node, (ast.Import, ast.ImportFrom)):
                            qualification = "eager_syntax"
                            child = node
                            while child in parents:
                                parent = parents[child]
                                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                                    qualification = "deferred"
                                    break
                                if isinstance(parent, ast.If) and child in parent.body and (
                                    isinstance(parent.test, ast.Name) and parent.test.id == "TYPE_CHECKING"
                                    or isinstance(parent.test, ast.Attribute) and parent.test.attr == "TYPE_CHECKING"
                                ):
                                    qualification = "type_only"
                                    break
                                if isinstance(parent, (ast.If, ast.Try, ast.For, ast.While, ast.With, ast.Match)):
                                    qualification = "conditional"
                                child = parent
                            edge = dict(line=node.lineno, end_line=node.end_lineno, col=node.col_offset,
                                        end_col=node.end_col_offset, module=getattr(node, "module", None),
                                        level=getattr(node, "level", 0), names=[x.name for x in node.names],
                                        qualification=qualification)
                            if len(row["imports"]) >= 512 or not append(row["imports"], edge):
                                complete = False
                                break
                    row["imports_complete"] = complete
                except BaseException as error:
                    # Summary failure never invalidates complete captured bytes.
                    row["imports_error_type"] = type(error).__name__[:128]
        finally:
            report["source_capture_complete"] = all("source_evidence" in row for row in report["files"])
            report["imports_complete"] = all(row["imports_complete"] for row in report["files"])
            report["status"] = ("observed" if all(report[field] for field in (
                "source_capture_complete", "imports_complete", "baseline_complete", "module_origins_complete"
            )) and report["boundary"]["status"] == "observed" else "partial")
            report["bytes_read"] = budget["bytes"] - initial_bytes
            for row in report["files"]:
                if row["status"] == "not_read_pending":
                    row["status"] = ("not_read_deadline" if time.monotonic() >= budget["deadline"]
                                     else "not_read_inspection_error")
            report["entries"] = budget["entries"]
            report["deadline_exhausted"] = time.monotonic() >= budget["deadline"]
            # Restore limits only: inspection reads remain charged to the role.
            for key in ("deadline", "byte_limit", "file_limit", "entries", "entry_limit"):
                if key in saved:
                    if key != "entries":
                        budget[key] = saved[key]
                elif key != "entries":
                    budget.pop(key, None)

    if admission is not None:
        dependency_frontier()
        return

    import sysconfig
    from email.parser import BytesParser

    assert type(guard) is JoinGuards and guard is ACTIVE and guard.role in {"server", "model"}
    assert guard.query_only and not guard.scene and not guard.sdk_ready
    assert type(report) is dict and not report
    assert sys.flags.isolated == sys.flags.no_site == sys.flags.ignore_environment == 1
    assert os.getuid() == os.getgid() == 1000 and sys.executable == EXECUTABLE
    assert preimport["before_package_imports"] is True and set(preimport["kernel_denial"]) == {"2", "10"}
    assert all(type(v) is int and v > 0 for v in preimport["kernel_denial"].values())
    assert runner.GRAPHQL_IMAGE == "sha256:b94e17024f1e123ac5a42759ab56651a18823fda7c701e765cba31f200154cdd"
    assert runner.GRAPHQL_MANIFEST_SHA256 == "03764536ed54c1f59cbf46305c5bc4ba618e2dc1deeeac7ffdfb21a0dffbf810"
    before_path, before_finders = list(sys.path), tuple(sys.meta_path)
    before_forbidden, before_allowed = dict(guard.forbidden), dict(guard.allowed)
    before_modules = {n: m for n, m in sys.modules.copy().items() if n.split(".")[0] in REGISTRATION_TARGETS.values()}
    assert not before_modules, "Registration targets already loaded"
    assert before_path == runner._GRAPHQL_PROBE["PATHS"]
    assert list(DEPENDENCY_ROOTS[:5]) == runner._GRAPHQL_PROBE["ALLOWED"]
    assert sysconfig.get_path("purelib") == sysconfig.get_path("platlib") == DEPENDENCY_ROOTS[0]
    source = verify_sources()
    deadline = time.monotonic() + 5
    report.update(
        schema_version=1,
        status="failed",
        role=guard.role,
        scope="fixed candidate metadata/source bytes; no package, shell, setup, pth or native execution",
        expanded_import_admitted=False,
        package_imports_executed=False,
        metadata_probe_executed=True,
        image=runner.GRAPHQL_IMAGE,
        provision_manifest_sha256=runner.GRAPHQL_MANIFEST_SHA256,
        image_binding="host selected/inspected immutable image; not child self-discovery",
        source_sha256=source,
        sys_path=before_path,
        targets=REGISTRATION_TARGETS,
        recipes={},
        pins={},
        roots=[],
        setup_points=[],
        bytes_read=0,
        preimport_kernel_denial=preimport["kernel_denial"],
        limits=dict(
            seconds=5,
            file_bytes=262144,
            total_bytes=4194304,
            entries_per_root=4096,
            metadata_files=32,
            report_bytes=524288,
            exact_file_exception=REGISTRATION_CONTEXT_EXCEPTION,
        ),
        not_established=[
            "complete dependency closure",
            "importability",
            "native safety",
            "extension/shared-library binding",
            "registration success",
            "acquisition authority",
        ],
    )

    def point(path, *, listing=False):
        return registration_metadata_point(path, runner, report, deadline, listing=listing)

    def imports(path, raw):
        if raw is None or not path.endswith((".py", ".pyi")):
            return []
        tree = ast.parse(raw, filename=path)
        edges = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                assert len(edges) < 512
                edges.append(
                    dict(
                        line=node.lineno,
                        module=getattr(node, "module", None),
                        level=getattr(node, "level", 0),
                        names=[x.name for x in node.names],
                    )
                )
        # Includes deferred/conditional imports; never interpreted as execution order.
        return sorted(edges, key=lambda x: x["line"])

    def context_source(path, raw):
        """Select complete AST units; never claim a complete initialization closure."""
        assert path == REGISTRATION_CONTEXT_EXCEPTION["path"]
        assert type(raw) is bytes and len(raw) == REGISTRATION_CONTEXT_EXCEPTION["file_bytes"]
        text = raw.decode("utf-8", errors="strict")
        assert text.encode("utf-8") == raw
        digest = hashlib.sha256(raw).hexdigest()
        witness = report["context_exception_witness"]
        assert witness["path"] == witness["physical"] == path and witness["links"] == []
        assert witness["state"] == "regular" and witness["size"] == len(raw)
        assert witness["sha256"] == digest
        tree = ast.parse(raw, filename=path)
        assert time.monotonic() < deadline
        assert len(tree.body) <= 512

        def unique(body, name, kind):
            matches = [n for n in body if getattr(n, "name", None) == name]
            assert len(matches) == 1 and type(matches[0]) is kind, "Unknown initialization shape"
            return matches[0]

        init = unique(tree.body, "init", ast.FunctionDef)
        runtime = unique(tree.body, "Runtime", ast.ClassDef)
        assert not runtime.bases and not runtime.keywords and not runtime.decorator_list
        constructor = unique(runtime.body, "__init__", ast.FunctionDef)
        assert constructor.args.args and constructor.args.args[0].arg == "self"
        definitions = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        # Complete module-level imports/configuration/control-flow statements.
        # Runtime class-body statements are also visible; other class bodies,
        # unselected definition-time effects and external callees remain omitted.
        selected: list[tuple[str, ast.stmt]] = [("init", init), ("Runtime.__init__", constructor)]
        selected.extend(("module_statement", n) for n in tree.body if not isinstance(n, definitions))
        selected.extend(("Runtime.class_statement", n) for n in runtime.body if not isinstance(n, definitions))
        assert len(selected) <= 512
        seen = {id(n) for _, n in selected}
        helper_count = 0
        index = 0
        while index < len(selected):
            assert time.monotonic() < deadline
            label, node = selected[index]
            index += 1
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                target = None
                if isinstance(call.func, ast.Name):
                    name = call.func.id
                    if any(isinstance(n, definitions) and n.name == name for n in tree.body):
                        # Other constructors require a separately reviewed source
                        # frontier, not automatic inclusion of entire classes.
                        matches = [n for n in tree.body if getattr(n, "name", None) == name]
                        if all(isinstance(n, ast.ClassDef) for n in matches):
                            continue
                        target = unique(tree.body, name, ast.FunctionDef)
                        target_label = name
                elif (label.startswith("Runtime.") and isinstance(call.func, ast.Attribute)
                      and isinstance(call.func.value, ast.Name) and call.func.value.id == "self"):
                    name = call.func.attr
                    if any(isinstance(n, definitions) and n.name == name for n in runtime.body):
                        target = unique(runtime.body, name, ast.FunctionDef)
                        target_label = "Runtime." + name
                if target is not None and id(target) not in seen:
                    helper_count += 1
                    assert helper_count <= 32 and len(selected) < 512, "Initialization selection overflow"
                    selected.append((target_label, target))
                    seen.add(id(target))
        # Byte offsets use Python AST's UTF-8 column convention. Decorators are
        # included from their @ token, with every body through end_col_offset.
        assert b"\r" not in raw, "Unknown source newline shape"
        lines = raw.split(b"\n")
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line) + 1)
        units = []
        for label, node in sorted(selected, key=lambda item: (item[1].lineno, item[1].col_offset)):
            assert time.monotonic() < deadline
            first_line, first_col = node.lineno, node.col_offset
            decorators = getattr(node, "decorator_list", [])
            if decorators:
                first_line, first_col = decorators[0].lineno, decorators[0].col_offset - 1
                assert lines[first_line - 1][first_col:first_col + 1] == b"@"
            start = offsets[first_line - 1] + first_col
            assert type(node.end_lineno) is int and type(node.end_col_offset) is int
            end = offsets[node.end_lineno - 1] + node.end_col_offset
            assert 0 <= start < end <= len(raw)
            segment = raw[start:end]
            assert len(segment) <= REGISTRATION_CONTEXT_EXCEPTION["report_bytes"], "Complete unit oversized"
            unit: dict = dict(
                label=label, kind=type(node).__name__, complete_ast_unit=True,
                start_line=first_line, end_line=node.end_lineno,
                start_col=first_col, end_col=node.end_col_offset,
                start_byte=start, end_byte=end, bytes=len(segment),
                sha256=hashlib.sha256(segment).hexdigest(),
                ast_sha256=hashlib.sha256(ast.dump(node).encode()).hexdigest(),
                source_file_sha256=digest, text=segment.decode("utf-8", errors="strict"),
            )
            assert unit["text"].encode("utf-8") == raw[start:end]
            units.append(unit)
        component = dict(
            format="selective_complete_ast_units_v1", path=path,
            source_file_bytes=len(raw), source_file_sha256=digest,
            complete_source=False, complete_initialization_closure=False,
            selection="init; Runtime.__init__; module/Runtime statements; syntactic local function/self-method calls",
            unresolved="external/indirect calls, other class bodies, unselected definition-time effects; no safety verdict",
            unit_count=len(units), helper_count=helper_count, units=units,
        )
        assert len(json.dumps(component, sort_keys=True).encode()) <= REGISTRATION_CONTEXT_EXCEPTION["report_bytes"]
        assert time.monotonic() < deadline
        return component

    def selected_source(path, raw):
        """Retain only selected immutable UTF-8 bytes, never evaluated source."""
        if raw is None or not path.endswith((".py", ".pyi")):
            return None
        assert path in REGISTRATION_POINTS or path in {
            root + leaf for root in DEPENDENCY_ROOTS for leaf in ("/warp/__init__.py", "/warp.py")
        }
        if path == REGISTRATION_CONTEXT_EXCEPTION["path"]:
            return context_source(path, raw)
        assert type(raw) is bytes and len(raw) <= 262144
        text = raw.decode("utf-8", errors="strict")
        assert text.encode("utf-8") == raw
        return dict(
            format="complete_utf8_source", bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), text=text
        )

    try:
        for path in DEPENDENCY_RECIPES:
            assert time.monotonic() < deadline
            row, raw = point(path)
            report["recipes"][path] = row
            assert raw is not None, "Registration recipe unavailable"
            e1_yaml_pin(path, row)
        for path in REGISTRATION_PINS:
            row, raw = point(path)
            report["pins"][path] = row
            assert raw is not None, "Previously observed registration pin unavailable"
        for path in REGISTRATION_POINTS:
            row, raw = point(path)
            report["setup_points"].append(
                dict(witness=row, imports=imports(path, raw), source_evidence=selected_source(path, raw))
            )
            # Shell is data: record only bounded literal source/source-env lines.
            # Do not derive paths, source it, execute setup.py or process .pth.
            if raw is not None and path.endswith(".sh"):
                assert isinstance(raw, bytes)
                declarations = []
                for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
                    if line.lstrip().startswith(("source ", ". ", "export PYTHONPATH=", "export LD_LIBRARY_PATH=")):
                        assert len(declarations) < 64 and len(line) <= 2048
                        declarations.append(dict(line=number, text=line))
                report["setup_points"][-1]["unresolved_shell_declarations"] = declarations
        fd_rows = []
        for root in DEPENDENCY_ROOTS:
            identity, names = point(root, listing=True)
            row: dict = dict(path=root, identity=identity, modules=[], distributions=[], metadata_search="unsearched")
            report["roots"].append(row)
            if names is None:
                continue
            for module in REGISTRATION_TARGETS.values():
                for leaf in (module + "/__init__.py", module + ".py"):
                    path = root + "/" + leaf
                    witness, raw = point(path)
                    row["modules"].append(
                        dict(
                            module=module, witness=witness, imports=imports(path, raw),
                            source_evidence=selected_source(path, raw) if module == "warp" else None,
                        )
                    )
            assert isinstance(names, list)
            for name in names:
                if not name.endswith(".dist-info"):
                    continue
                distribution = re.sub(r"[-_.]+", "-", name[:-10].rsplit("-", 1)[0]).lower()
                if distribution not in REGISTRATION_TARGETS:
                    continue
                assert len(fd_rows) < 32
                witness, raw = point(root + "/" + name + "/METADATA")
                item: dict = dict(distribution=distribution, witness=witness, declarations_unresolved=True)
                row["distributions"].append(item)
                fd_rows.append(item)
                if raw is not None:
                    assert isinstance(raw, bytes)
                    headers = BytesParser().parsebytes(raw, headersonly=True)
                    assert len(headers.get_all("Name", [])) == len(headers.get_all("Version", [])) == 1
                    assert re.sub(r"[-_.]+", "-", headers["Name"]).lower() == distribution
                    assert 0 < len(headers["Version"]) <= 128
                    requirements = headers.get_all("Requires-Dist", [])
                    assert len(requirements) <= 128 and all(len(x) <= 1024 for x in requirements)
                    requires_python = headers.get_all("Requires-Python", [])
                    assert len(requires_python) <= 1 and all(len(x) <= 256 for x in requires_python)
                    item.update(
                        name=headers["Name"],
                        version=headers["Version"],
                        requires_dist=requirements,
                        requires_python=requires_python,
                    )
            row["metadata_search"] = "bounded_immediate_complete"
        assert time.monotonic() < deadline
        report["status"] = "candidate_discovery_completed_not_import_admitted"
    except (AssertionError, OSError, ValueError, SyntaxError) as error:
        report["error_type"] = type(error).__name__
    finally:
        assert sys.path == before_path and tuple(sys.meta_path) == before_finders
        assert guard.forbidden == before_forbidden and guard.allowed == before_allowed
        after_modules = {
            n: m for n, m in sys.modules.copy().items() if n.split(".")[0] in REGISTRATION_TARGETS.values()
        }
        assert set(before_modules) == set(after_modules)
        assert all(before_modules[name] is after_modules[name] for name in before_modules)
        assert verify_sources() == source
    if len(json.dumps(report, sort_keys=True).encode()) > 524288:
        report.update(status="failed", error_type="ReportOverflow", roots=[], setup_points=[])
    assert len(json.dumps(report, sort_keys=True).encode()) <= 524288
    return report


# The only extra import admission is this package, never its prebundle parent.
E1_YAML_ROOT = "/isaac-sim/exts/omni.pip.compute/pip_prebundle/yaml"
E1_YAML_METADATA = "/isaac-sim/exts/omni.pip.compute/pip_prebundle/pyyaml-6.0.3.dist-info/METADATA"
E1_YAML_PINS = {
    "/isaac-sim/exts/omni.pip.compute/pip_prebundle/yaml/__init__.py": "b19dfcc333d6a75dfd73073901164507252f271b41d3b5f7d85510033a0547a7",
    "/isaac-sim/exts/omni.pip.compute/pip_prebundle/pyyaml-6.0.3.dist-info/METADATA": "03c3b415ed38d09faedc49360e930769b40c58f68585e6de00e2e4916a858d34",
}


def e1_yaml_file(path):
    """Read a bounded fixed-package file with no links, including ancestors."""
    assert type(path) is str and len(path) <= 1024
    assert path in DEPENDENCY_RECIPES or path == E1_YAML_METADATA or path.startswith(E1_YAML_ROOT + "/"), "E1 YAML root"
    parts = path[1:].split("/")
    assert path.startswith("/") and len(parts) <= 24 and all(p not in {"", ".", ".."} for p in parts)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        assert os.fstatvfs(fd).f_flag & os.ST_RDONLY
        for index, part in enumerate(parts):
            info = os.stat(part, dir_fd=fd, follow_symlinks=False)
            directory = index < len(parts) - 1
            assert stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), "E1 YAML nonphysical file"
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if directory:
                flags |= os.O_DIRECTORY
            nxt = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = nxt
            opened = os.fstat(fd)
            assert (opened.st_dev, opened.st_ino, opened.st_mode) == (info.st_dev, info.st_ino, info.st_mode)
            assert os.fstatvfs(fd).f_flag & os.ST_RDONLY
        assert opened.st_nlink == 1 and opened.st_size <= 33554432
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(33554433)
        assert len(raw) == opened.st_size
        after = os.fstat(fd)
        assert (after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
        row = dict(path=path, physical=path, links=[], size=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                   device=opened.st_dev, inode=opened.st_ino, mode=stat.S_IMODE(opened.st_mode),
                   uid=opened.st_uid, gid=opened.st_gid)
        return raw, row
    finally:
        os.close(fd)


def e1_yaml_pin(path, row):
    """Reject a changed fixed recipe, initializer or selected METADATA."""
    pins = {**DEPENDENCY_RECIPES, **E1_YAML_PINS}
    assert path in pins and row["path"] == row["physical"] == path and row["links"] == [], "E1 YAML pin origin"
    assert row["sha256"] == pins[path], "E1 YAML pinned bytes changed"


class E1YamlFinder:
    """Bind only yaml and yaml.* to verified bytes; never modify sys.path."""

    def __init__(self, runner, guard, report):
        self.runner, self.guard, self.report = runner, guard, report
        self.loaders = {}

    def find_spec(self, fullname, path=None, target=None):
        if fullname != "yaml" and not fullname.startswith("yaml."):
            return None
        from importlib.machinery import EXTENSION_SUFFIXES, ExtensionFileLoader, PathFinder

        assert self.guard is ACTIVE and self.guard.role in {"server", "model"}
        assert target is None and fullname not in sys.modules, "E1 YAML shadow/reload"
        assert re.fullmatch(r"yaml(?:\.[A-Za-z_][A-Za-z_0-9]*){0,16}", fullname)
        parent = "/".join([E1_YAML_ROOT, *fullname.split(".")[1:-1]])
        assert path is None if fullname == "yaml" else list(path or ()) == [parent], "E1 YAML search path"
        # PathFinder sees only this package's directory, not compute siblings.
        if fullname == "yaml":
            origin, package = E1_YAML_ROOT + "/__init__.py", True
        else:
            found = PathFinder.find_spec(fullname, [parent])
            if found is None:
                raise ModuleNotFoundError("Unbound E1 YAML submodule", name=fullname)
            origin, package = found.origin, found.submodule_search_locations is not None
        assert type(origin) is str and origin.startswith(E1_YAML_ROOT + "/"), "E1 YAML module origin"
        native = any(origin.endswith(suffix) for suffix in EXTENSION_SUFFIXES)
        assert not native or (fullname == "yaml._yaml" and not package), "E1 YAML unexpected extension"
        assert native or origin.endswith(".py"), "E1 YAML sourceless module denied"
        raw, row = e1_yaml_file(origin)
        if fullname == "yaml":
            e1_yaml_pin(origin, row)
        # Apply the existing physical-file/hash discipline as well, notably to
        # CPython extensions. The preliminary read forbids *all* symlink hops.
        checked, physical = self.runner._GRAPHQL_PROBE["physical_file"](origin, [E1_YAML_ROOT])
        assert checked == raw and all(physical[k] == row[k] for k in physical)
        assert len(self.loaders) < 128 and fullname not in self.loaders, "E1 YAML module ceiling/reload"
        assert sum(x.row["size"] for x in self.loaders.values()) + len(raw) <= 33554432
        loader = E1YamlLoader(self, fullname, origin, raw, row,
                              ExtensionFileLoader(fullname, origin) if native else None)
        self.loaders[fullname] = loader
        spec = importlib.util.spec_from_file_location(
            fullname, origin, loader=loader,
            submodule_search_locations=[str(Path(origin).parent)] if package else None,
        )
        assert spec is not None
        loader.spec = spec
        return spec


class E1YamlLoader:
    """Execute verified source bytes, or the identical immutable CPython extension."""

    def __init__(self, finder, name, origin, raw, row, native):
        self.finder, self.name, self.origin = finder, name, origin
        self.raw, self.row, self.native = raw, row, native
        self.spec, self.module = None, None

    def verify(self):
        raw, row = e1_yaml_file(self.origin)
        assert raw == self.raw and row == self.row, "E1 YAML module bytes changed"

    def create_module(self, spec):
        assert spec is self.spec and spec.loader is self
        self.verify()  # Extension initialization can execute here, before exec_module.
        return None if self.native is None else self.native.create_module(spec)

    def exec_module(self, module):
        assert module.__spec__ is self.spec and module.__loader__ is self
        assert module.__file__ == self.origin and self.module is None
        self.verify()
        if self.native is None:
            exec(compile(self.raw, self.origin, "exec", dont_inherit=True), module.__dict__)
        else:
            self.native.exec_module(module)
        self.verify()
        self.module = module
        self.finder.report["loaded_modules"][self.name] = dict(self.row, origin=self.origin,
                                                              file=module.__file__, native=self.native is not None)
        if self.name == "yaml":
            self.finder.report["status"] = "imported"


def install_e1_yaml(preimport, guard, runner, report):
    """Admit the observed PyYAML package after guards and the unchanged query probe."""
    from email.parser import BytesParser

    assert guard is ACTIVE and guard.role in {"server", "model"}, "E1 YAML role"
    assert sys.flags.isolated == sys.flags.no_site == sys.flags.ignore_environment == 1
    assert os.getuid() == os.getgid() == 1000 and sys.executable == EXECUTABLE
    assert runner.GRAPHQL_IMAGE == "sha256:b94e17024f1e123ac5a42759ab56651a18823fda7c701e765cba31f200154cdd"
    assert runner.GRAPHQL_MANIFEST_SHA256 == "03764536ed54c1f59cbf46305c5bc4ba618e2dc1deeeac7ffdfb21a0dffbf810"
    before_path, before_forbidden = list(sys.path), dict(guard.forbidden)
    assert before_path == runner._GRAPHQL_PROBE["PATHS"]
    assert list(DEPENDENCY_ROOTS[:5]) == runner._GRAPHQL_PROBE["ALLOWED"]
    assert not any(n == "yaml" or n.startswith("yaml.") or n == "_yaml" for n in sys.modules), "E1 YAML shadowed module"
    report.update(schema_version=1, status="verifying", role=guard.role, package_root=E1_YAML_ROOT,
                  scope="E1 fixed PyYAML only; not compute prebundle or native runtime admission",
                  image=runner.GRAPHQL_IMAGE, provision_manifest_sha256=runner.GRAPHQL_MANIFEST_SHA256,
                  image_binding="existing host select_graphql_runtime/owned inspect, not self-discovery",
                  sys_path=before_path, preimport_kernel_denial=preimport["kernel_denial"], pins={}, loaded_modules={})
    for path in (*DEPENDENCY_RECIPES, *E1_YAML_PINS):
        raw, row = e1_yaml_file(path)
        report["pins"][path] = row
        e1_yaml_pin(path, row)
        if path == E1_YAML_METADATA:
            headers = BytesParser().parsebytes(raw, headersonly=True)
            assert headers.get_all("Name") == ["PyYAML"] and headers.get_all("Version") == ["6.0.3"]
            assert headers.get_all("Requires-Dist", []) == []
            report["distribution"] = dict(distribution="PyYAML", version="6.0.3", requires_dist=[],
                                           requires_python=headers.get("Requires-Python"), metadata=row)
    assert sys.path == before_path and guard.forbidden == before_forbidden
    finder = E1YamlFinder(runner, guard, report)
    sys.meta_path.insert(0, finder)
    report["status"] = "bound_not_yet_imported"
    return finder


def e1_runtime_modules(runner, finder):
    """Check real immutable image origins, including approved vendor symlink targets."""
    if finder is None:
        return runner.graphql_runtime_modules()
    rows = {}
    probe = runner._GRAPHQL_PROBE
    # The operator approved the pinned image, not a subset of its package
    # aliases. Keep descriptor/no-follow verification through every symlink.
    physical_roots = [*probe["ALLOWED"], "/isaac-sim"]
    for name, module in sorted(list(sys.modules.items())):
        origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if name == "yaml" or name.startswith("yaml."):
            assert name in finder.loaders, "Unbound E1 YAML runtime module"
            loader = finder.loaders[name]
            assert module is loader.module and module.__spec__ is loader.spec and module.__loader__ is loader
            assert origin == module.__file__ == loader.origin, "E1 YAML runtime origin"
            if loader.spec.submodule_search_locations is not None:
                assert list(module.__path__) == loader.spec.submodule_search_locations == [str(Path(origin).parent)]
            loader.verify()
            rows[name] = dict(loader.row, origin=origin, file=module.__file__, native=loader.native is not None)
        elif not origin or origin in ("built-in", "frozen") or origin.startswith("/source/"):
            continue
        elif any(origin.startswith(p + "/") for p in probe["ALLOWED"]):
            _, row = probe["physical_file"](origin, physical_roots)
            rows[name] = dict(row, origin=origin)
        else:
            assert any(origin.startswith(p + "/") for p in probe["PATHS"][:3]), "Unrecorded runtime origin"
    assert set(finder.report["loaded_modules"]) == {n for n in rows if n == "yaml" or n.startswith("yaml.")}
    return rows


def read_json(path, limit=4 * 1024 * 1024):
    assert not path.is_symlink()
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    assert len(raw) <= limit
    return json.loads(raw)


def screen(raw):
    assert all(secret not in raw for secret in (b"synthetic-user", b"synthetic-only-secret", b"synthetic-unit-key"))


def write_evidence(name, value):
    assert re.fullmatch(r"[a-z0-9.-]+\.json", name)
    raw = json.dumps(value, sort_keys=True).encode()
    screen(raw)
    assert len(raw) <= 4 * 1024 * 1024
    pending = Path("/evidence", name + ".pending")
    pending.write_bytes(raw)
    pending.replace(Path("/evidence", name))


def verify_sources():
    if getattr(ACTIVE, "initialization_case", None) is not None:
        return initialization_verify_sources()
    root = Path("/source")
    assert os.statvfs(root).f_flag & os.ST_RDONLY
    manifest = read_json(root / "source-manifest.json", SOURCE_MANIFEST_LIMIT)
    inventory = read_json(root / INVENTORY, SOURCE_MANIFEST_LIMIT)
    assert set(manifest) == set(inventory) | {"closure.json", "graphql-import-check.py", "graphql-profile.json"}
    assert len(manifest) + 1 == SOURCE_LIMIT
    total = (root / "source-manifest.json").stat().st_size
    for name, digest in manifest.items():
        assert type(name) is str and type(digest) is str and re.fullmatch(r"[a-f0-9]{64}", digest)
        parts = Path(name).parts
        assert parts and not Path(name).is_absolute() and ".." not in parts
        path = root
        for part in parts:
            path /= part
            assert not path.is_symlink()
        assert path.is_file() and os.statvfs(path).f_flag & os.ST_RDONLY
        with path.open("rb") as stream:
            data = stream.read(8 * 1024 * 1024 + 1)
        total += len(data)
        assert total <= 8 * 1024 * 1024
        assert hashlib.sha256(data).hexdigest() == digest
    return manifest


def role_for(arguments):
    assert type(arguments) is list and all(type(x) is str for x in arguments)
    if (
        len(arguments) == 6
        and arguments[:2] == ["setup", "--config"]
        and arguments[2] in CONFIGS
        and arguments[3:5] == ["--create", "--credentials-fd"]
        and re.fullmatch(r"[1-9][0-9]{0,5}", arguments[5])
        and int(arguments[5]) >= 3
    ):
        return "setup"
    if arguments in ADMIN:
        return "admin"
    if arguments == LAUNCH or JOIN_CASE == "resume" and arguments == RELAUNCH:
        return "launcher"
    if arguments in (SUBMIT, RESULT, STOP, STATUS) or JOIN_CASE == "cancel" and arguments == CANCEL:
        return "client"
    if JOIN_CASE == "resume" and arguments == RECONCILE:
        return "client"
    if JOIN_CASE in {"evidence", "resume"} and arguments == READBACK:
        return "client"
    if JOIN_CASE in {"cancel", "resume"} and arguments == CONTROL_CHECK:
        return "client"
    if JOIN_CASE == "resume" and arguments == LOST_RESPONSE:
        return "client"
    if JOIN_CASE == "resume" and arguments[:1] == ["resume"] and arguments == resume_arguments():
        return "client"
    if (
        len(arguments) == 9
        and arguments[:4] == ["api-serve", "--config", CONFIG, "--instance"]
        and arguments[4] in ({INSTANCE, RESUME_INSTANCE} if JOIN_CASE == "resume" else {INSTANCE})
        and arguments[5] == "--lease-fd"
        and arguments[7] == "--gate-fd"
        and all(re.fullmatch(r"[1-9][0-9]{0,5}", arguments[i]) and int(arguments[i]) >= 3 for i in (6, 8))
        and arguments[6] != arguments[8]
    ):
        return "server"
    raise ValueError("Unadmitted E1 argv")


def checked_pipe(fd):
    info = os.fstat(fd)
    assert fd >= 3 and stat.S_ISFIFO(info.st_mode) and info.st_uid == info.st_gid == 1000
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
    assert re.fullmatch(r"pipe:\[[0-9]+\]", os.readlink(f"/proc/self/fd/{fd}"))


class JoinGuards(base.Guards):
    """Keep legacy denials; exempt only the exact production core owner constructor."""

    initialization_cleanup_deadline: float | None

    def __init__(self, role, db_ip=None):
        assert role in {"harness", "setup", "admin", "launcher", "server", "client", "model"}
        super().__init__(db_ip if role in {"harness", "admin", "server"} else None, query_only=True)
        self.role = role
        self.permit = None
        self.spawn_records = []
        self.basic_auth_handoffs = []
        self.owner_constructions = 0
        self.ports_issued = False
        self.positive_complete = False
        # Leave room for cold CLI status/cleanup after the four bounded model workers.
        self.deadline = time.monotonic() + (180 if role == "harness" else 140)
        self.sdk_ready = False
        self.sdk_calls = 0
        self.used = []
        self.cli_arguments = None
        self.http_operations = []
        self.http_started = None
        self.last_status = None
        self.http_interval_failure = None
        self.lost_response_status: int | None = None

    def deny(self, kind):
        if kind == "blocked_import" and self.role in {"server", "model"}:
            frames = []
            frame = sys._getframe(1)
            while frame is not None and len(frames) < 40:
                frames.append(dict(file=frame.f_code.co_filename, function=frame.f_code.co_name, line=frame.f_lineno))
                frame = frame.f_back
            self.first_blocked_import_sites = getattr(self, "first_blocked_import_sites", frames)
        if kind == "subprocess" and getattr(self, "initialization_controls_ready", False):
            traces = getattr(self, "initialization_subprocess_denials", [])
            if len(traces) < 4:
                frames = []
                frame = sys._getframe(1)
                while frame is not None and len(frames) < 16:
                    frames.append(dict(path=frame.f_code.co_filename, function=frame.f_code.co_name, line=frame.f_lineno))
                    frame = frame.f_back
                traces.append(frames)
                self.initialization_subprocess_denials = traces
        return super().deny(kind)

    def profile(self, frame, event, arg):
        # Neither this guard nor its base inspects return/C events. Dispatching
        # those through every policy layer dominates cold Pydantic imports.
        if event != "call" or frame.f_code.co_name not in PROFILE_CALL_NAMES:
            return
        if (
            JOIN_CASE == "resume"
            and self.role == "server"
            and self.cli_arguments[4] == INSTANCE
            and frame.f_code.co_name == "claim_intent"
        ):
            pause_unreleased_claim(frame)
        if getattr(self, "initialization_controls_ready", False) and event == "call":
            module = frame.f_globals.get("__name__", "")
            name = frame.f_code.co_name
            # Teardown may clear module metadata; do not skip inherited guards.
            # Unknown provenance must still fail closed for runtime actions.
            if type(module) is not str:
                module = ""
            if (not module and name in {"launch", "launch_tiled", "capture_launch", "Open", "OpenMasked"}
                    or module.startswith("warp") and name in {"launch", "launch_tiled", "capture_launch"}
                    or module.startswith("pxr") and name in {"Open", "OpenMasked"}):
                self.deny("runtime")
        if self.role == "client" and event == "call" and frame.f_code.co_name == "query":
            name = "isaaclab_arena.agentic_environment_generation.workflow.api.client"
            loaded = sys.modules.get(name)
            if loaded is not None and frame.f_code is loaded.query.__code__ and frame.f_globals is loaded.__dict__:
                now = time.monotonic()
                operation = frame.f_locals.get("operation")
                assert frame.f_locals.get("path") == (CLIENT if self.cli_arguments == SUBMIT else READ_CLIENT)
                if self.http_started is None:
                    self.http_started = now
                if self.cli_arguments == SUBMIT:
                    assert operation == "submit" and not self.http_operations
                elif JOIN_CASE == "cancel" and self.cli_arguments == CANCEL:
                    assert operation == "cancel" and not self.http_operations
                elif JOIN_CASE == "resume" and self.cli_arguments == resume_arguments():
                    assert operation == "resume" and not self.http_operations
                elif self.cli_arguments == LOST_RESPONSE:
                    assert (
                        operation == ("status" if not self.http_operations else "resume")
                        and len(self.http_operations) < 2
                    )
                    assert frame.f_locals.get("identifier") == RUN_ID
                elif self.cli_arguments == CONTROL_CHECK:
                    assert operation in {"status", "receipt", "resume", "cancel"} and len(self.http_operations) < 12
                    assert frame.f_locals.get("identifier") in {RUN_ID, "p1-resume", "p1-cancel", "p1-not-this-run"}
                elif self.cli_arguments == READBACK:
                    assert (
                        operation
                        in {
                            "result",
                            "prior",
                            "candidate",
                            "generation",
                            "evidence",
                            "assessment",
                            "artifact-inventory",
                            "artifact",
                        }
                        and len(self.http_operations) < 32
                    )
                    assert frame.f_locals.get("identifier") == RUN_ID
                else:
                    assert self.cli_arguments == RESULT and now - self.http_started < 120
                    assert operation in {"result-status", "result"} and "result" not in self.http_operations
                    if operation == "result-status":
                        assert self.http_operations.count("result-status") < 120
                        if self.last_status is not None and now - self.last_status < 1:
                            self.http_interval_failure = now - self.last_status
                        assert self.last_status is None or now - self.last_status >= 1
                        self.last_status = now
                self.http_operations.append(operation)
        if event == "call" and frame.f_code.co_name == "__init__":
            module = "isaaclab_arena.agentic_environment_generation.workflow.application"
            loaded = sys.modules.get(module)
            owner_class = getattr(loaded, "ForegroundWorkflow", None)
            if (
                self.role == "server"
                and owner_class is not None
                and frame.f_code is owner_class.__init__.__code__
                and type(frame.f_locals.get("self")) is owner_class
                and executing(module, owner_class.__init__.__code__)
            ):
                assert self.ports_issued and self.owner_constructions == 0
                assert frame.f_locals.get("owner_control") is False
                self.owner_constructions += 1
                return
        super().profile(frame, event, arg)
        if (
            event == "call"
            and self.role in {"admin", "server"}
            and frame.f_code.co_name == "driver"
            and frame.f_globals.get("__name__") == "neo4j._sync.driver"
        ):
            self.basic_auth_handoffs.append(getattr(frame.f_locals.get("auth"), "scheme", None) == "basic")

    def private_control(self, sock, address):
        if (
            self.role not in {"server", "launcher", "client"}
            or sock.family != socket.AF_UNIX
            or sock.type != socket.SOCK_STREAM
        ):
            return False
        match = re.fullmatch(r"/proc/self/fd/([0-9]+)/control\.sock", address) if type(address) is str else None
        if match is None:
            return False
        fd = int(match[1])
        info = os.fstat(fd)
        selected = self.cli_arguments[self.cli_arguments.index("--instance") + 1]
        assert selected in ({INSTANCE, RESUME_INSTANCE} if JOIN_CASE == "resume" else {INSTANCE})
        directory = Path(f"/tmp/graphql-execution/execution/runtime/instances/{selected}")
        if directory.is_symlink():
            return False
        expected = directory.stat()
        if (info.st_dev, info.st_ino) != (expected.st_dev, expected.st_ino):
            return False
        if (
            os.readlink(f"/proc/self/fd/{fd}") != "/tmp/graphql-execution/execution/runtime/instances/" + selected
            or info.st_uid != 1000
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            return False
        module = "isaaclab_arena.agentic_environment_generation.workflow.api." + (
            "server" if self.role == "server" else "instance"
        )
        loaded = sys.modules.get(module)
        if loaded is None:
            return False
        function = loaded.Control.__init__ if self.role == "server" else loaded.control
        return executing(module, function.__code__)

    def audit(self, event, args):
        if self.role == "client" and self.cli_arguments == READBACK and event == "open":
            path = args[0]
            if isinstance(path, (str, bytes, os.PathLike)):
                value = os.fsdecode(path)
                assert not value.startswith("/tmp/graphql-execution/execution/artifacts/") and Path(value).name not in {
                    "prior.json",
                    "candidate.json",
                    "candidate.yaml",
                    "provenance.json",
                    "evidence.json",
                    "manifest.json",
                }, "HTTP readback client may not read artifact files"
        if event == "import" and getattr(self, "initialization_controls_ready", False):
            top = args[0].split(".")[0]
            if top not in {"sqlite3", "_sqlite3"}:
                # Import event is not load permission: our physical finder must
                # resolve approved image/submodule bytes before they execute.
                # Constructors, runtime actions and provider calls stay guarded.
                return None
        if event == "import" and self.role == "model" and args[0].split(".")[0] == "openai":
            return None
        if event in {"socket.bind", "socket.connect"}:
            sock, address = args
            if self.private_control(sock, address):
                self.allowed.setdefault("control", 0)
                self.allowed["control"] += 1
                return None
            if (
                self.role == "client"
                and event == "socket.connect"
                and sock.family == socket.AF_INET
                and sock.type == socket.SOCK_STREAM
                and address == ("127.0.0.1", 18761)
            ):
                loaded = sys.modules.get("isaaclab_arena.agentic_environment_generation.workflow.api.client")
                if (
                    loaded is not None
                    and executing(loaded.__name__, loaded.query.__code__)
                    and executing("socket", socket.create_connection.__code__)
                ):
                    self.allowed.setdefault("http", 0)
                    self.allowed["http"] += 1
                    return None
            if (
                self.role == "server"
                and sock.family == socket.AF_INET
                and sock.type == socket.SOCK_STREAM
                and address == ("127.0.0.1", 18761)
            ):
                import asyncio
                from asyncio import selector_events

                code = (
                    asyncio.BaseEventLoop.create_server.__code__
                    if event == "socket.bind"
                    else selector_events.BaseSelectorEventLoop._sock_connect.__code__
                )
                module = "asyncio.base_events" if event == "socket.bind" else "asyncio.selector_events"
                if executing(module, code):
                    self.allowed.setdefault("http", 0)
                    self.allowed["http"] += 1
                    return None
        return super().audit(event, args)

    def install(self):
        native_listen = socket.socket.listen
        super().install()
        previous_resolve = socket.getaddrinfo

        def numeric(host, port, family=0, type=0, proto=0, flags=0):
            if (
                self.role in {"server", "client"}
                and host in ("127.0.0.1", b"127.0.0.1")
                and port == 18761
                and family in (0, socket.AF_INET)
                and type in (0, socket.SOCK_STREAM)
            ):
                return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", port))]
            return previous_resolve(host, port, family, type, proto, flags)

        def listen(sock, backlog=0):
            if self.role == "server":
                if self.private_control(sock, sock.getsockname()) and backlog == 4:
                    return native_listen(sock, backlog)
                if sock.family == socket.AF_INET and sock.getsockname() == ("127.0.0.1", 18761) and backlog == 16:
                    import asyncio.base_events

                    if executing("asyncio.base_events", asyncio.base_events.Server._start_serving.__code__):
                        return native_listen(sock, backlog)
            return self.deny("network")

        socket.getaddrinfo = numeric
        socket.socket.listen = listen

    def launch(self, args, kwargs, *, production_argv=None):
        verify_sources()
        self.local.expected = (args[0], args, kwargs["cwd"], kwargs["env"])
        self.allowed["child_launch"] += 1
        try:
            proc = self.native(args, **kwargs)
            self.children.append(proc.pid)
            row = {"pid": proc.pid, "bootstrap_argv": args, "production_argv": production_argv}
            self.spawn_records.append(row)
            # S2 captures the separate server before any checkpoint/package witness.
            # Other modes retain their original launch record and behavior.
            if getattr(self, "initialization_case", None) in {"failure", "timeout"} and production_argv is not None:
                fields = Path(f"/proc/{proc.pid}/stat").read_text().rsplit(")", 1)[1].split()
                owned = dict(pid=proc.pid, parent_pid=int(fields[1]), pgid=int(fields[2]), sid=int(fields[3]),
                             start_ticks=int(fields[19]), boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                             pid_namespace=os.readlink(f"/proc/{proc.pid}/ns/pid"))
                assert owned["parent_pid"] == os.getpid() and owned["pid"] == owned["pgid"] == owned["sid"]
                assert owned["pid_namespace"] == os.readlink("/proc/self/ns/pid")
                live_identity(owned)
                row.update(owned)
            # Independent launch evidence remains available while server is live.
            write_evidence(f"join-launch-{proc.pid}.json", {**row, "parent_pid": os.getpid()})
            return proc
        finally:
            self.local.expected = None

    def popen(self, args, *positional, **kwargs):
        initialization = getattr(self, "initialization_case", None)
        if initialization is not None and self.role == "harness":
            caller = sys._getframe(1)
            if caller.f_code is initialization_fresh.__code__ and self.permit == (args, kwargs):
                assert initialization in {"positive", "init-server"}
                assert len(self.spawn_records) < (1 if initialization == "init-server" else 4)
                self.permit = None
                return self.launch(args, kwargs)
        if positional or type(args) is not list or not all(type(v) is str for v in args):
            return self.deny("subprocess")
        if self.role == "launcher":
            module = "isaaclab_arena.agentic_environment_generation.workflow.api.instance"
            loaded = sys.modules.get(module)
            if (
                loaded is None
                or not executing(module, loaded.launch.__code__)
                or self.allowed["child_launch"] != 0
                or args[:3] != [EXECUTABLE, "-m", MODULE]
                or role_for(args[3:]) != "server"
            ):
                return self.deny("subprocess")
            lifetime, gate = int(args[9]), int(args[11])
            expected = process_kwargs(env=LAUNCH_ENV, outputs=False, pass_fds=(lifetime, gate))
            if initialization in {"failure", "timeout"}:
                expected["env"]["HOME"] = initialization_environment(initialization, "init-server")["HOME"]
            info = os.fstat(lifetime)
            if (
                kwargs != expected
                or any(type(kwargs[k]) is not type(v) for k, v in expected.items())
                or os.readlink(f"/proc/self/fd/{lifetime}") != "/tmp/graphql-execution/execution/runtime/lifetime.lock"
                or not stat.S_ISREG(info.st_mode)
                or info.st_uid != 1000
                or stat.S_IMODE(info.st_mode) != 0o600
                or not stat.S_ISFIFO(os.fstat(gate).st_mode)
            ):
                return self.deny("subprocess")
            wrapped = [EXECUTABLE, "-I", "-S", "-B", "/source/" + SELF, "--cli", *args[3:]]
            # Production's exact sanitized env is checked above. Only the owned
            # bootstrap adds these finite thread caps before interpreter startup.
            kwargs = {**kwargs, "env": dict(ENV)}
            if initialization in {"failure", "timeout"}:
                kwargs.update(env={**initialization_environment(initialization, "init-server"),
                                   "ARENA_S2_INITIALIZATION_CASE": initialization},
                              stdout=sys.stdout, stderr=sys.stderr)
            return self.launch(wrapped, kwargs, production_argv=args)
        if self.role == "server":
            module = "isaaclab_arena_examples.agentic_environment_generation.foreground_generation"
            loaded = sys.modules.get(module)
            expected_args, expected_kwargs = scene_spawn_spec()
            if (
                loaded is None
                or not executing(module, loaded.ForegroundGenerationWorker.prepare.__code__)
                or not self.ports_issued
                or self.owner_constructions != 1
                or args != expected_args
                or kwargs != expected_kwargs
                or any(type(kwargs[k]) is not type(v) for k, v in expected_kwargs.items())
            ):
                return self.deny("subprocess")
            with self.lock:
                if self.allowed["child_launch"] >= (1 if JOIN_CASE == "cancel" else 4) or any(
                    Path(f"/proc/{pid}").exists() for pid in self.children
                ):
                    return self.deny("subprocess")
                return self.launch(args, kwargs)
        frame = sys._getframe(1)
        permit = self.permit
        if (
            self.role != "harness"
            or frame.f_code is not fresh.__code__
            or frame.f_globals is not globals()
            or permit is None
            or args != permit[0]
            or kwargs != permit[1]
            or any(type(kwargs[k]) is not type(v) for k, v in permit[1].items())
            or self.allowed["child_launch"] >= CLIENT_LAUNCHES
        ):
            return self.deny("subprocess")
        self.permit = None
        return self.launch(args, kwargs)


def process_kwargs(*, env=ENV, outputs=True, pass_fds=(), model=False):
    return dict(
        executable=EXECUTABLE,
        env=dict(env),
        cwd="/source" if model else "/tmp",
        stdin=subprocess.PIPE if model else subprocess.DEVNULL,
        stdout=subprocess.PIPE if outputs else subprocess.DEVNULL,
        stderr=subprocess.PIPE if outputs else subprocess.DEVNULL,
        shell=False,
        close_fds=True,
        pass_fds=pass_fds,
        start_new_session=True,
        text=False,
    )


def scene_spawn_spec():
    """Fixed E1 scene worker entry; never use the legacy scene manifest."""
    assert sys.executable == EXECUTABLE and os.statvfs(EXECUTABLE).f_flag & os.ST_RDONLY
    return [EXECUTABLE, "-I", "-S", "-B", "/source/" + SELF, "--model"], process_kwargs(model=True)


def synthetic_ports():
    """Issue spawn/capture/vocabulary ports to the selected fixed installed composition.

    Proposed production interface: api.installed_execution.compose calls this
    bootstrap capability itself. No constructor/root/store/grant is injected.
    Its absence remains a real production refusal, never a fixture fallback.
    """
    module = "isaaclab_arena.agentic_environment_generation.workflow.api.installed_execution"
    loaded = sys.modules.get(module)
    assert type(ACTIVE) is JoinGuards and ACTIVE.role == "server" and not ACTIVE.ports_issued
    assert loaded is not None and executing(module, loaded.compose.__code__)
    verify_sources()
    from workflow_graphql_execution_join_fixture import synthetic_capture, synthetic_catalogue

    ACTIVE.ports_issued = True
    return {"spawn_spec": scene_spawn_spec, "capture": synthetic_capture, "catalogue": synthetic_catalogue}


def unused(arguments):
    return arguments not in ACTIVE.used


def fresh(arguments, *, private_fd=None):
    """Run exactly one reviewed public CLI, with incremental bounded collection."""
    guard = ACTIVE
    assert type(guard) is JoinGuards and guard.role == "harness"
    role = role_for(arguments)
    case = getattr(guard, "initialization_case", None)
    if case is not None:
        assert case in {"failure", "timeout"} and arguments not in (SUBMIT, RESULT)
        assert len(guard.used) < 10
    assert role != "server" and unused(arguments)
    index = len(guard.used)
    if role == "setup":
        assert index < 2 and arguments[2] == CONFIGS[index]
        assert type(private_fd) is int and str(private_fd) == arguments[-1]
        checked_pipe(private_fd)
    else:
        assert private_fd is None
        if arguments not in (STOP, STATUS):
            expected = COMMANDS[index - 2]
            assert index >= 2 and arguments == (resume_arguments() if expected == RESUME else expected)
        else:
            assert LAUNCH in guard.used
            assert arguments == STOP or STOP in guard.used
    guard.used.append(list(arguments))
    args = [EXECUTABLE, "-I", "-S", "-B", "/source/" + SELF, "--cli", *arguments]
    kwargs = process_kwargs(pass_fds=() if private_fd is None else (private_fd,))
    if case is not None:
        kwargs["env"]["ARENA_S2_INITIALIZATION_CASE"] = case
        kwargs["env"]["HOME"] = initialization_environment(case, "init-server")["HOME"]
    guard.permit = (args, kwargs)
    proc = None
    try:
        proc = subprocess.Popen(args, **kwargs)
        cap = 125 if arguments == RESULT else 15 if arguments in (STOP, STATUS) else 40
        stdout, stderr = collect(proc, min(guard.deadline, time.monotonic() + cap))
        result = subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
        result.pid = proc.pid
        return result
    finally:
        guard.permit = None


def collect(proc, deadline):
    if getattr(ACTIVE, "initialization_case", None) is not None:
        return initialization_collect(proc, deadline)
    buffers = {proc.stdout: bytearray(), proc.stderr: bytearray()}
    try:
        with selectors.DefaultSelector() as selector:
            for stream in buffers:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                assert remaining > 0, "E1 role collection deadline exceeded"
                for key, _ in selector.select(min(remaining, 0.1)):
                    stream = key.fileobj
                    limit = 8 * 1024 * 1024 if stream is proc.stdout else 65536
                    data = os.read(stream.fileno(), min(4096, limit + 1 - len(buffers[stream])))
                    if not data:
                        selector.unregister(stream)
                    else:
                        buffers[stream].extend(data)
                        assert len(buffers[stream]) <= limit, "E1 role output exceeded"
            proc.wait(timeout=max(0.001, deadline - time.monotonic()))
        return bytes(buffers[proc.stdout]), bytes(buffers[proc.stderr])
    finally:
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        for stream in buffers:
            stream.close()


def identity():
    return dict(
        pid=os.getpid(),
        parent_pid=os.getppid(),
        pgid=os.getpgrp(),
        sid=os.getsid(0),
        boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        pid_namespace=os.readlink("/proc/self/ns/pid"),
        start_ticks=int(Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19]),
    )


def live_identity(expected):
    """Read the exact live identity, not merely a possibly zombie /proc path."""
    from workflow_graphql_execution_join_fixture import check_live_identity

    pid = expected["pid"]
    root = Path(f"/proc/{pid}")
    fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
    observed = dict(
        pid=pid, parent_pid=int(fields[1]), pgid=int(fields[2]), sid=int(fields[3]),
        start_ticks=int(fields[19]), state=fields[0],
        boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        pid_namespace=os.readlink(root / "ns/pid"),
    )
    # Recheck after namespace lookup; do not combine two PID incarnations.
    final = (root / "stat").read_text().rsplit(")", 1)[1].split()
    assert fields[1:4] == final[1:4] and fields[19] == final[19], "live identity changed during read"
    observed["state"] = final[0]
    check_live_identity(expected, observed)
    return observed


def load_runner():
    spec = importlib.util.spec_from_file_location("joined_runner", "/source/scripts/run-workflow-neo4j-checks.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


def metadata_replay(guard):
    """Replay historical captured Git metadata; do not launch an uncounted Git."""
    from api import MetadataReplay, metadata_popen, verify_metadata_executable

    value = read_json(Path("/source/outputs/workflow/plan04-implementation/installed-execution/join-git-metadata.json"))
    verify_metadata_executable()
    metadata = {"stdout": value["stdout"].encode("ascii"), "stderr": b"", "returncode": value["returncode"]}
    replay = MetadataReplay(metadata, guard.forbidden)
    native = subprocess.Popen
    subprocess.Popen = metadata_popen(replay)
    try:
        import git  # noqa: F401
    finally:
        subprocess.Popen = native
    return {
        "source": value["source"],
        "source_sha256": value["source_sha256"],
        "replays": replay.reads,
        "scope": "historical metadata compatibility only; not fresh executable version attestation",
    }


def runtime_metadata(runner, modules, yaml_finder=None):
    """Pin metadata for actual additional imports, including SDK import aliases."""
    import importlib.metadata

    aliases = {
        "_pytest": "pytest",
        "py": "pytest",
        "yaml": "PyYAML",
        "_yaml": "PyYAML",
        "git": "GitPython",
        "PIL": "Pillow",
        "attr": "attrs",
        "dotenv": "python-dotenv",
    }
    probe = runner._GRAPHQL_PROBE
    baseline = {name.split(".")[0] for name in probe["result"]["loaded_modules"]}
    result = {}
    for name in sorted({name.split(".")[0] for name in modules} - baseline):
        if name == "yaml" and yaml_finder is not None:
            _, witness = e1_yaml_file(E1_YAML_METADATA)
            e1_yaml_pin(E1_YAML_METADATA, witness)
            assert witness == yaml_finder.report["distribution"]["metadata"]
            result[name] = dict(yaml_finder.report["distribution"])
            continue
        distribution = importlib.metadata.distribution(aliases.get(name, name))
        _, witness = probe["physical_file"](str(distribution._path) + "/METADATA", probe["ALLOWED"])
        result[name] = {"distribution": aliases.get(name, name), "version": distribution.version, "metadata": witness}
    return result


def child():
    global ACTIVE
    if sys.argv[1:3] == ["--initialization", "positive"]:
        assert len(sys.argv) == 4
        return initialization_child(sys.argv[3])
    # The executable bootstrap and production's fixed capability import must
    # resolve to this same module/guard, never a second inactive module instance.
    assert "workflow_graphql_execution_join_harness" not in sys.modules or (
        sys.modules["workflow_graphql_execution_join_harness"] is sys.modules[__name__]
    )
    sys.modules["workflow_graphql_execution_join_harness"] = sys.modules[__name__]
    assert sys.flags.isolated == sys.flags.no_site == sys.flags.ignore_environment == 1
    assert sys.executable == EXECUTABLE and os.statvfs(EXECUTABLE).f_flag & os.ST_RDONLY
    initialization = os.environ.get("ARENA_S2_INITIALIZATION_CASE")
    assert initialization is None or initialization in {"failure", "timeout"}
    model = sys.argv[1:] == ["--model"]
    assert model or sys.argv[1:2] == ["--cli"]
    arguments = [] if model else sys.argv[2:]
    role = "model" if model else role_for(arguments)
    expected_environment = (initialization_environment(initialization, "init-server")
                            if initialization and role == "server" else ENV)
    if initialization and role != "server":
        expected_environment = {**ENV, "HOME": initialization_environment(initialization, "init-server")["HOME"]}
    assert all(os.environ.get(k) == v for k, v in expected_environment.items())
    if initialization:
        assert not model and arguments not in (SUBMIT, RESULT)
        if role == "server":
            initialization_cache_create(initialization, "init-server")
    assert os.getcwd() == ("/source" if model else "/tmp")
    signal.alarm(30 if model else 130 if arguments == RESULT else 145 if role == "server" else 40)
    if role == "setup":
        checked_pipe(int(arguments[-1]))
    preimport = base.preflight()
    manifest = initialization_verify_sources() if initialization else verify_sources()
    network = read_json(Path("/network/manifest.json"), 65536)
    assert os.statvfs("/network/manifest.json").f_flag & os.ST_RDONLY
    assert set(network) == {"container_id", "network_id", "ip", "port"} and network["port"] == 7687
    guard = JoinGuards(role, network["ip"])
    if initialization:
        guard.initialization_case = initialization
        if role == "server":
            guard.initialization_role = "init-server"
            guard.initialization_preimport = preimport
            guard.initialization_cache_before = initialization_cache_manifest(
                "/tmp/s2-init/" + initialization + "/init-server", time.monotonic() + 5)
    guard.cli_arguments = arguments
    ACTIVE = base.ACTIVE = guard
    guard.install()
    runner = load_runner()
    record = dict(
        **identity(),
        role=role,
        preimport=preimport,
        source_sha256=manifest,
        network_manifest=network,
        bootstrap_argv=[EXECUTABLE, "-I", "-S", "-B", "/source/" + SELF, *sys.argv[1:]],
        argv=[MODULE, *arguments],
        status="failed",
    )
    yaml_finder = None
    catalogue_scope = contextlib.ExitStack()
    try:
        record["imports"] = runner.graphql_imports(preimport, guard)
        if role in {"server", "model"} and not initialization:
            record["e1_yaml_binding"] = {}
            yaml_finder = install_e1_yaml(preimport, guard, runner, record["e1_yaml_binding"])
        import platform

        if not initialization:
            platform.processor = lambda: os.uname().machine
        elif role == "server":
            guard.initialization_admission = InitializationAdmission(guard, runner, time.monotonic() + 35)
            record["pythonapi_bootstrap"] = guard.initialization_admission.pythonapi_bootstrap
            guard.initialization_processor = platform.processor
            guard.initialization_controls_ready = True
        closure = read_json(Path("/source/closure.json"), 65536)
        runner.install_staged_import_guard("/source", closure["files"], closure["namespaces"])
        sys.path.insert(0, "/source/scripts")
        sys.path.insert(0, "/source/web/arena-workbench/tests/e2e/functional-v7")
        # Do not initialize SDK or import legacy factories in any CLI role.
        if model:
            from generation_worker_fixture import install_synthetic_sdk, production_sdk_profile
            from workflow_graphql_execution_join_fixture import install_detachment_transport, synthetic_catalogue

            supplied = catalogue_scope.enter_context(synthetic_catalogue().activate())
            record["execution_catalogue"] = dict(
                sha256=supplied.sha256, scope="deterministic-adapter-only", payload=supplied.payload(),
            )

            transport = {}

            def sdk_profile(frame, event, arg):
                # Preserve exact constructor checks but not the fixture's optional
                # graph-access exception: this cohort allows no retrieval at all.
                if event != "call" and not (
                    event == "return" and frame.f_code is install_synthetic_sdk.__code__
                ):
                    return
                if event == "call" and frame.f_code.co_name not in PROFILE_CALL_NAMES:
                    return
                module = frame.f_globals.get("__name__", "")
                if module.endswith("graph_access"):
                    return guard.profile(frame, event, arg)
                if event == "return" and frame.f_code is install_synthetic_sdk.__code__:
                    assert module == "generation_worker_fixture" and not transport
                    original = frame.f_locals["synthetic_response"]
                    assert any(original.__code__ is code for code in install_synthetic_sdk.__code__.co_consts)
                    assert original.__globals__ is frame.f_globals and frame.f_locals["scene"] is True
                    transport.update(
                        original=original, transport_type=frame.f_locals["transport_type"],
                        evidence=frame.f_locals["evidence"],
                    )
                if event == "call" and frame.f_code.co_name == "synthetic_response":
                    assert module == "generation_worker_fixture" and guard.sdk_ready
                    assert frame.f_code is transport["original"].__code__
                    assert frame.f_globals is transport["original"].__globals__
                    assert type(frame.f_locals.get("transport")) is transport["transport_type"]
                    assert (
                        frame.f_code.co_filename
                        == "/source/web/arena-workbench/tests/e2e/functional-v7/generation_worker_fixture.py"
                    )
                    assert guard.sdk_calls < 2, "extra SDK call exceeds E1 child ceiling"
                    guard.sdk_calls += 1
                if (
                    event == "call"
                    and frame.f_code.co_name == "__init__"
                    and module
                    in {
                        "isaaclab_arena.agentic_environment_generation.inference_backend",
                        "isaaclab_arena.agentic_environment_generation.environment_generation_agent",
                        "openai._client",
                    }
                ):
                    assert guard.sdk_ready, "model constructor before synthetic transport installation"
                return admitted_profile(frame, event, arg)

            admitted_profile = production_sdk_profile(guard.profile)
            sys.setprofile(sdk_profile)
            threading.setprofile(sdk_profile)
            with contextlib.redirect_stdout(sys.stderr):
                install_synthetic_sdk(scene=True)
            install_detachment_transport(
                transport["transport_type"], transport["original"], transport["evidence"], identity, write_evidence
            )
            guard.sdk_ready = True
            sdk = read_json(Path(f"/evidence/generation-child-{os.getpid()}-sdk.json"))
            assert sdk["calls"] == 0
            record["transport_installed_before_model_construction"] = True
            write_evidence(f"join-process-{os.getpid()}-started.json", record)
            from isaaclab_arena_examples.agentic_environment_generation.web_api import scene_worker

            sys.argv = ["scene_worker", "--parent-pid", str(os.getppid())]
            code = scene_worker.main()
        else:
            if role == "server":
                write_evidence(f"join-process-{os.getpid()}-started.json", record)
            sys.argv = [MODULE, *arguments]
            previous_trace = sys.gettrace()
            previous_thread_trace = threading.gettrace()
            if role in {"server", "client"}:
                record["startup_exception_sites"] = []
                startup_lock = threading.RLock()
                startup_active = [True]
                startup_main = threading.get_ident()
                startup_targets = {
                    "/source/isaaclab_arena/agentic_environment_generation/workflow/api/server.py": {
                        "supervise",
                        "serve",
                        "serving",
                    },
                    "/source/isaaclab_arena/agentic_environment_generation/workflow/api/application.py": {
                        "boot",
                        "lifespan",
                    },
                    "/source/isaaclab_arena/agentic_environment_generation/workflow/api/installed_execution.py": {
                        "compose",
                        "build",
                    },
                    "/source/isaaclab_arena/agentic_environment_generation/workflow/application.py": {
                        "_generate",
                        "_scene",
                        "_scene_phase",
                        "_drive_scene",
                    },
                    "/source/isaaclab_arena/agentic_environment_generation/workflow/api/client.py": {
                        "query",
                        "result",
                    },
                    "/source/isaaclab_arena/agentic_environment_generation/workflow/cli.py": {"_run_installed"},
                }

                def startup_trace(frame, event, arg):
                    # Diagnostic only: bounded static source coordinates and type.
                    # Never inspect messages, values, locals, arguments or secrets.
                    if not startup_active[0]:
                        restored = previous_trace if threading.get_ident() == startup_main else previous_thread_trace
                        sys.settrace(restored)
                        return restored(frame, event, arg) if restored is not None else None
                    filename = frame.f_code.co_filename
                    if frame.f_code.co_name not in startup_targets.get(filename, ()):
                        return None
                    frame.f_trace_lines = False
                    if event == "exception":
                        exception_type, _, traceback = arg
                        if exception_type in {StopIteration, StopAsyncIteration, GeneratorExit}:
                            return startup_trace
                        typename = exception_type.__name__
                        sites = []
                        for _index in range(24):
                            if traceback is None:
                                break
                            code_object = traceback.tb_frame.f_code
                            source = code_object.co_filename.removeprefix("/source/")
                            function = code_object.co_name
                            if source in manifest and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*|<[^<>/]{1,40}>", function):
                                sites.append(dict(file=source, function=function, line=traceback.tb_lineno))
                            traceback = traceback.tb_next
                        if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,100}", typename):
                            with startup_lock:
                                if startup_active[0] and len(record["startup_exception_sites"]) < 24:
                                    record["startup_exception_sites"].append(dict(exception_type=typename, sites=sites))
                                    # Persist before lifespan cleanup can deliberately park.
                                    # One existing atomic record; at most 24 diagnostic writes.
                                    write_evidence(f"join-process-{os.getpid()}-started.json", record)
                    return startup_trace

                threading.settrace(startup_trace)
                sys.settrace(startup_trace)
            try:
                try:
                    output_scope = (contextlib.redirect_stdout(sys.stderr)
                                    if initialization and role == "server" else contextlib.nullcontext())
                    with output_scope:
                        if arguments == READBACK:
                            readback_client()
                        elif arguments == LOST_RESPONSE:
                            lost_response_client()
                        elif arguments == CONTROL_CHECK:
                            control_client()
                        else:
                            runpy.run_module(MODULE, run_name="__main__", alter_sys=False)
                except SystemExit as error:
                    code = error.code
                else:
                    code = 0
            finally:
                if role in {"server", "client"}:
                    with startup_lock:
                        startup_active[0] = False
                        threading.settrace(previous_thread_trace)
                        sys.settrace(previous_trace)
        assert type(code) is int
        record.update(status="completed", returncode=code)
        return code
    except BaseException as error:
        if role in {"server", "model"}:
            record["failure_type"] = type(error).__name__
            record["failure_sites"] = []
            trace = error.__traceback__
            while trace is not None and len(record["failure_sites"]) < 24:
                record["failure_sites"].append(dict(
                    file=trace.tb_frame.f_code.co_filename, function=trace.tb_frame.f_code.co_name,
                    line=trace.tb_lineno,
                ))
                trace = trace.tb_next
        raise
    finally:
        original_error = sys.exc_info()[0]
        catalogue_scope.close()
        if initialization and getattr(guard, "initialization_admission", None) is not None:
            record["pythonapi_bootstrap"] = guard.initialization_admission.pythonapi_bootstrap
        record.update(
            forbidden=guard.forbidden,
            first_blocked_import_sites=getattr(guard, "first_blocked_import_sites", None),
            simulator_registry_prepared=getattr(
                sys.modules.get("isaaclab_arena.assets.registries"),
                "_assets_registered",
                False,
            ),
            allowed=guard.allowed,
            spawn_records=guard.spawn_records,
            basic_auth_handoffs=guard.basic_auth_handoffs,
            owner_constructions=guard.owner_constructions,
            sdk_ready=guard.sdk_ready,
            sdk_calls=guard.sdk_calls,
            http_operations=guard.http_operations,
            http_interval_failure=guard.http_interval_failure,
            lost_response_status=guard.lost_response_status,
        )
        try:
            assert verify_sources() == manifest
            if "imports" in record and not initialization:
                record["runtime_modules"] = e1_runtime_modules(runner, yaml_finder)
                record["dependency_provenance"] = (
                    "Pinned image and physical-file witnesses; additional distribution metadata not required."
                )
        except BaseException as error:
            if role not in {"server", "model"}:
                raise
            record["finalization_error_type"] = type(error).__name__
            record["finalization_error_sites"] = []
            trace = error.__traceback__
            while trace is not None and len(record["finalization_error_sites"]) < 24:
                record["finalization_error_sites"].append(dict(
                    file=trace.tb_frame.f_code.co_filename, function=trace.tb_frame.f_code.co_name,
                    line=trace.tb_lineno,
                ))
                trace = trace.tb_next
            record["status"] = "failed"
            if original_error is None:
                raise
        finally:
            write_evidence(f"join-process-{os.getpid()}.json", record)
            signal.alarm(0)


def lost_response_client():
    """Close the real successful HTTP stream before consuming its resume body."""
    import httpx
    from isaaclab_arena.agentic_environment_generation.workflow.api.client import query

    original = httpx.Response.iter_raw

    def dropped_response(self: httpx.Response, chunk_size: int | None = None):
        if ACTIVE.http_operations and ACTIVE.http_operations[-1] == "resume":
            assert self.status_code == 200 and ACTIVE.lost_response_status is None
            ACTIVE.lost_response_status = self.status_code
            self.close()
            raise OSError("Test-only lost resume response body")
        yield from original(self, chunk_size)

    httpx.Response.iter_raw = dropped_response
    status = query(RESUME_CLIENT, "status", identifier=RUN_ID)["data"]["workflow"]
    try:
        query(
            RESUME_CLIENT,
            "resume",
            identifier=RUN_ID,
            operation_id="p1-resume",
            expected_version=status["version"],
            renew_authorization=True,
        )
    except OSError:
        assert ACTIVE.lost_response_status == 200
        raise SystemExit(2)
    raise AssertionError("Expected response body loss was not exercised")


def snapshot_resume_receipt():
    """Read the committed original after the lost body, before replaying it."""
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load

    resources = Resources(load(CONFIG))
    with resources.driver() as driver:
        receipt = resources.store(driver).get_resume_receipt("p1-resume")
        assert receipt is not None and receipt.disposition == "continuation_admitted"
    write_evidence("join-resume-original.json", receipt.model_dump(mode="json"))
    return receipt


def control_client():
    """Exercise immutable replay and blocked alternative commands through HTTP only."""
    from isaaclab_arena.agentic_environment_generation.workflow.api.client import query

    status = query(READ_CLIENT, "status", identifier=RUN_ID)["data"]["workflow"]
    kind, operation = ("RESUME", "p1-resume") if JOIN_CASE == "resume" else ("CANCEL", "p1-cancel")
    original = query(READ_CLIENT, "receipt", kind=kind, identifier=operation)["data"]["workflowCommand"]
    outcomes = {"original": original}
    if JOIN_CASE == "resume":
        expected = original["beforeVersion"]
        replay = query(
            READ_CLIENT,
            "resume",
            identifier=RUN_ID,
            operation_id=operation,
            expected_version=expected,
            renew_authorization=True,
        )["data"]["resumeWorkflow"]
        changed = query(
            READ_CLIENT,
            "resume",
            identifier=RUN_ID,
            operation_id=operation,
            expected_version=str(int(expected) + 1),
            renew_authorization=True,
        )["data"]["resumeWorkflow"]
        assert replay["receiptDigest"] == original["receiptDigest"] and changed["__typename"] == "QueryFailure"
        blocked = query(
            READ_CLIENT,
            "resume",
            identifier=RUN_ID,
            operation_id="p1-uncertain",
            expected_version=status["version"],
            renew_authorization=True,
        )["data"]["resumeWorkflow"]
        assert blocked == {"__typename": "QueryFailure", "code": "OVERLOADED"}
        outcomes.update(replay=replay, changed_payload=changed, active_uncertain_release_blocked=blocked)
    else:
        assert status["state"] == "cancelled"
        replay = query(READ_CLIENT, "cancel", identifier=RUN_ID, operation_id=operation)["data"]["cancelWorkflow"]
        assert replay["durable"] == "recorded" and replay["receipt"]["receiptDigest"] == original["receiptDigest"]
        changed = query(READ_CLIENT, "cancel", identifier="p1-not-this-run", operation_id=operation)["data"][
            "cancelWorkflow"
        ]
        assert changed["__typename"] == "CancellationResult" and changed["durable"] == "conflict"
        terminal = query(
            READ_CLIENT,
            "resume",
            identifier=RUN_ID,
            operation_id="p1-terminal",
            expected_version=status["version"],
            renew_authorization=True,
        )["data"]["resumeWorkflow"]
        assert terminal["__typename"] == "ResumeReceipt" and terminal["disposition"] == "refused"
        after = query(READ_CLIENT, "status", identifier=RUN_ID)["data"]["workflow"]
        assert after["state"] == "cancelled" and after["version"] == status["version"]
        outcomes.update(replay=replay, changed_payload=changed, terminal_resume=terminal)
    print(json.dumps(outcomes, sort_keys=True))


def verify_control_results(value):
    """Independent retained receipts, original release and unchanged reservations."""
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load

    resources = Resources(load(CONFIG))
    with resources.driver() as driver:
        store = resources.store(driver)
        attempt = store.get_generation_attempt(RUN_ID)
        reserved = store.get_run_inspection(RUN_ID).budget.reserved
        before_name = "join-unreleased.json" if JOIN_CASE == "resume" else "join-retained.json"
        assert reserved.model_dump(mode="json") == read_json(Path("/evidence") / before_name)["reserved"]
        if JOIN_CASE == "resume":
            receipt = store.get_resume_receipt("p1-resume")
            original = read_json(Path("/evidence/join-resume-original.json"))
            assert receipt.model_dump(mode="json") == original
            assert attempt.released is True and attempt.receipt is None and attempt.cleanup is None
            assert store.get_resume_receipt("p1-uncertain") is None
        else:
            receipt = store.get_cancel_receipt("p1-cancel")
            terminal = store.get_resume_receipt("p1-terminal")
            assert terminal.disposition == "refused" and store.get_run(RUN_ID).state == "cancelled"
            assert attempt.cleanup is not None
        assert value["original"]["receiptDigest"] == receipt.receipt_digest
    write_evidence("join-controls.json", value)


def readback_client():
    """A fresh installed HTTP client; the guard denies artifact filesystem reads."""
    import base64
    from isaaclab_arena.agentic_environment_generation.workflow.api.client import query

    prior = query(READ_CLIENT, "prior", identifier=RUN_ID)["data"]["workflowPrior"]
    assert prior["__typename"] == "PriorDetail" and prior["runId"] == RUN_ID
    assert prior["priorCount"] == 0 and prior["status"] == "unavailable"
    retained = query(READ_CLIENT, "result", identifier=RUN_ID, operation_id=OPERATION)["data"]["workflow"]
    selected = retained["scene"]["selectedCandidateReference"]
    candidate = query(
        READ_CLIENT,
        "candidate",
        identifier=RUN_ID,
        reference_id=selected["candidateId"],
    )[
        "data"
    ]["workflowCandidate"]
    assert candidate["__typename"] == "CandidateDetail" and candidate["digest"] == selected["digest"]
    generation_ref = retained["generationOutputs"][0]
    generation = query(READ_CLIENT, "generation", identifier=RUN_ID, reference_id=generation_ref["attemptId"])["data"][
        "workflowGeneration"
    ]
    assert (
        generation["__typename"] == "GenerationDetail"
        and generation["manifestDigest"] == generation_ref["manifestSha256"]
    )
    evidence = query(READ_CLIENT, "evidence", identifier=RUN_ID, reference_id=retained["scene"]["evidenceId"])["data"][
        "workflowEvidence"
    ]
    assert evidence["__typename"] == "EvidenceDetail" and evidence["candidateId"] == candidate["candidateId"]
    assessment = query(READ_CLIENT, "assessment", identifier=RUN_ID, reference_id=retained["scene"]["assessmentId"])[
        "data"
    ]["workflowAssessment"]
    assert assessment["__typename"] == "AssessmentDetail" and assessment["status"] == "established"
    assert assessment["evidenceId"] == evidence["evidenceId"] and assessment["candidateId"] == candidate["candidateId"]
    inventories = []
    for selector in evidence["artifactSelectors"]:
        inventory = query(
            READ_CLIENT,
            "artifact-inventory",
            identifier=RUN_ID,
            kind=selector["kind"],
            reference_id=selector["referenceId"],
        )["data"]["workflowArtifacts"]
        assert (
            inventory["__typename"] == "ArtifactInventory" and inventory["manifestDigest"] == selector["manifestDigest"]
        )
        inventories.append(inventory)
    retrieved = []
    for reference in [
        *prior["artifacts"],
        *candidate["artifacts"],
        *generation["artifacts"],
        *(item for inventory in inventories for item in inventory["artifacts"]),
    ]:
        assert reference["runId"] == RUN_ID
        raw = bytearray()
        while len(raw) < int(reference["totalBytes"]):
            result = query(
                READ_CLIENT,
                "artifact",
                identifier=RUN_ID,
                kind=reference["kind"],
                reference_id=reference["referenceId"],
                artifact_name=reference["name"],
                sha256=reference["sha256"],
                offset=str(len(raw)),
                limit=8192,
            )["data"]["workflowArtifact"]
            assert result["__typename"] == "ArtifactChunk" and result["encoding"] == "base64"
            assert int(result["offset"]) == len(raw) and result["sha256"] == reference["sha256"]
            chunk = base64.b64decode(result["data"], validate=True)
            assert len(chunk) == int(result["length"]) and 0 < len(chunk) <= 8192
            raw.extend(chunk)
            assert result["eof"] == (len(raw) == int(reference["totalBytes"]))
        assert hashlib.sha256(raw).hexdigest() == reference["sha256"]
        retrieved.append(dict(reference, retrieved_bytes=len(raw), received_sha256=hashlib.sha256(raw).hexdigest()))
    print(
        json.dumps(
            dict(
                prior=prior,
                candidate=candidate,
                generation=generation,
                evidence=evidence,
                assessment=assessment,
                inventories=inventories,
                artifacts=retrieved,
            ),
            sort_keys=True,
        )
    )


def verify_api_readback(value):
    """Independent database binding and verified immutable bytes agree with HTTP."""
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import parse_contract, contract_digest
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import GenerationArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import (
        canonical,
        SceneEvidenceArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.evidence import CandidateBinding
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea

    config = load(CONFIG)
    resources = Resources(config)
    with resources.driver() as driver:
        store = resources.store(driver)
        contract = parse_contract(store.get_run(RUN_ID).contract_json)
        candidate = store.get_scene_candidate(value["candidate"]["candidateId"]).candidate
        receipt = store.get_generation_attempt(RUN_ID).receipt
        evidence = store.get_scene_evidence(value["evidence"]["evidenceId"])
        assessment = store.get_scene_assessment(value["assessment"]["assessmentId"])
    binding = RetainedPriorArtifacts._binding(contract.source.prompt, contract_digest(contract), RUN_ID)
    version = hashlib.sha256(canonical(binding)).hexdigest()
    with ArtifactArea.open(
        config.value["artifact_root"], store_id=config.binding.store_id, registry_id=config.binding.registry_id
    ) as area:
        manifest = area.read_final_manifest("scene-prior", version, binding=binding)
        files = area.verify(f"final/scene-prior/{version}", manifest)
        generation_files = GenerationArtifacts(area).verified_bytes(receipt, protect=lambda _: None)
        evidence_files = {}
        for entry in evidence.observation.evidence:
            if entry.manifest_digest in evidence_files:
                continue
            binding = CandidateBinding(
                candidate_digest=entry.candidate_digest,
                contract_digest=entry.cohort.contract_digest,
                profile_digest=entry.cohort.profile_digest,
            )
            retained_evidence = SceneEvidenceArtifacts(area).load_receipt(
                binding,
                entry.cohort,
                kind="visual-answer" if entry.modality == "visual" else "observation",
                manifest_digest=entry.manifest_digest,
                protect=lambda _: None,
            )
            evidence_files[entry.manifest_digest] = area.verify(
                retained_evidence.relative_directory, json.loads(retained_evidence.manifest_json)
            )["evidence.json"]
    prior = value["prior"]
    assert prior["contractDigest"] == contract_digest(contract) and prior["manifestDigest"] == manifest["digest"]
    assert set(files) == {"prior.json"}
    assert value["candidate"]["digest"] == candidate.digest and value["candidate"]["sourceId"] == candidate.source_id
    expected = {
        ("PRIOR", RUN_ID, "PRIOR_JSON"): files["prior.json"],
        ("CANDIDATE", candidate.candidate_id, "CANDIDATE_JSON"): candidate.scene_json.encode(),
    }
    assert value["generation"]["manifestDigest"] == receipt.manifest_sha256
    assert value["generation"]["registrationId"] == receipt.registration.registration_id
    expected.update({
        ("GENERATION", receipt.fence.attempt_id, name.upper().replace(".", "_")): raw
        for name, raw in generation_files.items()
    })
    assert value["evidence"]["candidateId"] == evidence.candidate_id
    assert value["assessment"]["candidateId"] == assessment.candidate_id
    assert value["assessment"]["evidenceId"] == assessment.evidence_id
    assert value["assessment"]["status"] == assessment.assessment.status
    assert value["evidence"]["verifiedManifestDigests"] == list(evidence.observation.verified_manifest_digests)
    expected.update({
        ("EVIDENCE", evidence.evidence_id + manifest, "EVIDENCE_JSON"): raw for manifest, raw in evidence_files.items()
    })
    assert len(value["artifacts"]) == len(expected)
    observed_keys = set()
    for observed in value["artifacts"]:
        key = observed["kind"], observed["referenceId"], observed["name"]
        assert key not in observed_keys
        observed_keys.add(key)
        raw = expected[key]
        assert observed["received_sha256"] == hashlib.sha256(raw).hexdigest() == observed["sha256"]
        assert observed["retrieved_bytes"] == len(raw) == int(observed["totalBytes"])
    assert observed_keys == set(expected)
    write_evidence("join-api-readback.json", value)


def pause_unreleased_claim(frame):
    """Test-only pause at the real claim entry, after real reservation/owner commits."""
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore

    assert frame.f_code is Neo4jWorkflowStore.claim_intent.__code__
    assert frame.f_globals is sys.modules[Neo4jWorkflowStore.__module__].__dict__
    store = frame.f_locals["self"]
    run, attempt = store.get_run(RUN_ID), store.get_generation_attempt(RUN_ID)
    pending, owner = store.pending_generation(RUN_ID), store.get_owner()
    assert pending["intent_id"] == frame.f_locals["intent_id"]
    assert owner.owner_id == frame.f_locals["owner_id"] and owner.owner_epoch == frame.f_locals["owner_epoch"]
    assert attempt is None, "The real claim body has not created any attempt"
    assert ACTIVE.spawn_records == [] and not any(ACTIVE.forbidden.values())
    write_evidence(
        "join-unreleased.json",
        dict(
            identity=identity(),
            run_id=run.run_id,
            version=run.version,
            intent_id=pending["intent_id"],
            contract_json=run.contract_json,
            reservation=pending["reservation"].model_dump(mode="json"),
            reserved=store.get_run_inspection(RUN_ID).budget.reserved.model_dump(mode="json"),
            owner=owner.model_dump(mode="json"),
            guard=dict(
                forbidden=ACTIVE.forbidden,
                allowed=ACTIVE.allowed,
                basic_auth_handoffs=ACTIVE.basic_auth_handoffs,
                spawn_records=ACTIVE.spawn_records,
                owner_constructions=ACTIVE.owner_constructions,
                sdk_calls=ACTIVE.sdk_calls,
            ),
        ),
    )
    until = time.monotonic() + 15
    while time.monotonic() < until:
        time.sleep(0.02)
    raise RuntimeError("Test interruption was not observed before its deadline")


def resume_arguments():
    """Bind the fixed resume command to the actual retained pre-claim version."""
    assert JOIN_CASE == "resume"
    value = read_json(Path("/evidence/join-unreleased.json"))
    assert value["run_id"] == RUN_ID and type(value["version"]) is int and value["version"] >= 1
    return [*RESUME[:-1], str(value["version"])]


def interrupt_unreleased_server(pid):
    """Kill only the exact recorded worker-free server, then read its state independently."""
    from workflow_graphql_execution_join_fixture import IDENTITY_FIELDS
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load
    from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import group_members

    assert JOIN_CASE == "resume" and pid == server_pid()
    until = min(ACTIVE.deadline, time.monotonic() + 15)
    path = Path("/evidence/join-unreleased.json")
    while not path.exists():
        assert time.monotonic() < until, "Known-unreleased reservation not reached"
        time.sleep(0.02)
    value = read_json(path)
    started = read_json(Path(f"/evidence/join-process-{pid}-started.json"))
    owned = {key: started[key] for key in IDENTITY_FIELDS}
    assert value["identity"]["pid"] == pid
    for key in set(IDENTITY_FIELDS) - {"parent_pid"}:
        assert value["identity"][key] == owned[key]
    live_identity(owned)
    assert not list(Path("/evidence").glob("generation-child-*-sdk.json"))
    os.killpg(pid, signal.SIGKILL)
    while any(row["state"] not in {"Z", "X"} for row in group_members(pid).values()):
        assert time.monotonic() < until, "Exact interrupted server remains live"
        time.sleep(0.02)
    resources = Resources(load(CONFIG))
    with resources.driver() as driver:
        store = resources.store(driver)
        attempt = store.get_generation_attempt(RUN_ID)
        assert attempt is None
        assert store.get_run(RUN_ID).version == value["version"]
        assert store.get_run(RUN_ID).contract_json == value["contract_json"]
        assert store.pending_generation(RUN_ID)["reservation"].model_dump(mode="json") == value["reservation"]
        assert store.get_owner().model_dump(mode="json") == value["owner"]
    write_evidence(
        "join-restart.json",
        dict(identity=owned, signal=int(signal.SIGKILL), physical_group_absent=True, known_unreleased=True),
    )


def verify_resume_admission(value):
    """Join fresh-authorization admission to original real identities/reservation."""
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load

    before = read_json(Path("/evidence/join-unreleased.json"))
    receipt = value["data"]["resumeWorkflow"]
    assert receipt["__typename"] == "ResumeReceipt" and receipt["disposition"] == "continuation_admitted"
    assert receipt["runId"] == RUN_ID and receipt["authorizationAction"] in {"bind", "renew"}
    assert receipt["expectedVersion"] == str(before["version"]) and receipt["renewAuthorization"] is True
    assert receipt["selection"]["intentId"] == before["intent_id"]
    resources = Resources(load(CONFIG))
    with resources.driver() as driver:
        store = resources.store(driver)
        retained = store.get_resume_receipt("p1-resume")
        assert retained.receipt_digest == receipt["receiptDigest"]
        assert store.get_run(RUN_ID).contract_json == before["contract_json"]
        inspection = store.get_run_inspection(RUN_ID)
        assert inspection.budget.reserved.model_calls == before["reservation"]["model_calls"]
        assert inspection.budget.reserved.model_tokens == before["reservation"]["model_tokens"]
        assert store.get_owner().owner_id == before["owner"]["owner_id"]
        write_evidence("join-resume-receipt.json", dict(http=value, retained=retained.model_dump(mode="json")))


def server_pid():
    command = RELAUNCH if JOIN_CASE == "resume" and RELAUNCH in ACTIVE.used else LAUNCH
    launchers = [r for r in ACTIVE.spawn_records if r["bootstrap_argv"][6:] == command]
    assert len(launchers) == 1
    launcher = read_json(Path(f"/evidence/join-process-{launchers[0]['pid']}.json"))
    assert len(launcher["spawn_records"]) == 1
    return launcher["spawn_records"][0]["pid"]


def verify_result(value, raw_contract):
    """Compare independent authenticated HTTP, retained DB and real artifact bytes."""
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import GenerationArtifacts
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest, parse_contract

    assert set(value) == {"data"}, "reader must return the exact combined GraphQL envelope"
    data = value["data"]
    assert set(data) == {"workflow", "workflowSubmission", "workflowCommand"}
    result, submission, command = (data[key] for key in ("workflow", "workflowSubmission", "workflowCommand"))
    digest = contract_digest(parse_contract(raw_contract))
    assert result["__typename"] == "Workflow" and result["id"] == RUN_ID and result["operationId"] == OPERATION
    for receipt in (submission, command):
        assert receipt["__typename"] == "SubmissionReceipt" and receipt["kind"] == "SUBMIT"
        assert receipt["runId"] == RUN_ID and receipt["operationId"] == OPERATION
        assert receipt["acceptedContractDigest"] == digest
    assert submission == command, "same immutable SUBMIT projection required"
    assert result["state"] == "accepted" and result["phase"] == "scene"
    assert result["policyOutcome"] == "not_requested" and result["publicationOutcome"] == "not_permitted"
    assert result["experimentOutcome"] == "unknown"
    scene = result["scene"]
    assert scene["acceptance"] == "accepted" and scene["assessmentStatus"] == "established"
    assert scene["selectedAssessed"] is True and scene["action"] == "accept"
    assert scene["evidenceId"] and scene["assessmentId"] and scene["decisionId"]
    assert {r["criterionId"] for r in scene["criteria"]} == {"speed", "visible"}
    assert all(r["verdict"] == "established" and r["manifests"] for r in scene["criteria"])
    resources = Resources(load(CONFIG))
    with resources.driver() as driver:
        store = resources.store(driver)
        inspection = store.get_run_inspection(RUN_ID)
        accepted = store.get_submission_inspection(OPERATION)
        assert accepted.accepted_contract_digest == digest
        assert result["retainedRevision"] == inspection.retained_revision
        assert result["cleanup"]["projectionRevision"] == inspection.cleanup.projection_revision
        assert result["retainedDependenciesRevision"] == inspection.retained_dependencies_revision
        assert result["version"] == str(inspection.intent.run_version)
        assert scene["evidenceId"] == inspection.scene.evidence_id
        assert scene["assessmentId"] == inspection.scene.assessment_id
        assert scene["decisionId"] == inspection.scene.decision_id
        candidate = inspection.scene.candidate
        assert scene["selectedCandidateReference"]["candidateId"] == candidate.candidate_id
        assert scene["selectedCandidateReference"]["digest"] == candidate.digest
        assert candidate.parent_id is not None and candidate.original_id == candidate.parent_id
        assert len(inspection.cleanup.intents) == len(result["cleanup"]["intents"]) == 4
        registrations, stages = [], []
        for obligation in inspection.cleanup.intents:
            assert obligation.release_state == "released" and obligation.cleanup_state == "recorded"
            assert obligation.cleanup_observation == "owned_process_group_stopped"
            assert obligation.retired_owner is not None and not obligation.retired_owner.dirty
            http = next(r for r in result["cleanup"]["intents"] if r["intentId"] == obligation.intent_id)
            assert http["registrationId"] == obligation.registration_id
            assert http["releaseState"] == "released" and http["cleanupState"] == "recorded"
            assert http["cleanupEvidenceRef"] == obligation.cleanup_evidence_ref
            assert http["cleanupObservation"] == "owned_process_group_stopped"
            if obligation.kind == "generation":
                attempt = store.get_generation_attempt(RUN_ID)
                assert attempt.released and attempt.cleanup is not None and attempt.receipt is not None
                registration = attempt.registration
                stages.append((registration.pid, "generate"))
            else:
                retained = store.get_scene_intent(RUN_ID, obligation.intent_id)
                assert retained.released_at is not None and retained.status == "produced"
                assert retained.worker_cleanup is not None
                registration = retained.worker_registration
                stages.append((registration.pid, retained.action))
            assert registration.registration_id == obligation.registration_id
            registrations.append(registration.model_dump(mode="json"))
        # get_owner retains the last retired identity; None means never owned.
        # Retirement is independent of the four cleanup/release and OS proofs.
        owner = inspection.cleanup.current_scope_owner
        assert owner is not None and owner.dirty is False
        assert store.get_owner() == store.get_retired_owner(owner.owner_id) == owner
        assert result["cleanup"]["currentScopeOwner"] == {
            "id": owner.owner_id, "epoch": str(owner.owner_epoch), "dirty": False,
        }
        binding = resources.config.binding
        with ArtifactArea.open(
            Path(resources.config.value["artifact_root"]), store_id=binding.store_id, registry_id=binding.registry_id
        ) as area:
            attempt = store.get_generation_attempt(RUN_ID)
            files = GenerationArtifacts(area).verified_bytes(attempt.receipt, protect=resources.protect)
            original = json.loads(files["candidate.json"])
        # Candidate projection itself contains no filesystem authority. Reopen
        # its authoritative retained bytes to check actual repair, not a verdict.
        snapshot = store.scene_snapshot(RUN_ID)
        repaired = json.loads(snapshot.candidate.scene_json)
        before = original["relations"][5]["params"]["x"]
        after = repaired["relations"][5]["params"]["x"]
        assert abs(after - before - 0.03) < 1e-9
        normalized = json.loads(json.dumps(repaired))
        normalized["relations"][5]["params"]["x"] = before
        assert normalized == original, "repair changed fields outside the frozen x intervention"
        # Actual retained evidence validates candidate/cohort pairing; no joining
        # verdicts from the failed original and successful repaired candidate.
        evidence = store.get_scene_evidence(inspection.scene.evidence_id)
        assert evidence is not None and evidence.run_id == RUN_ID
        assert evidence.candidate_id == candidate.candidate_id
        assert evidence.observation == inspection.scene.observation
        assert {r.candidate_digest for r in evidence.observation.evidence} == {candidate.digest}
        assert len({r.cohort.model_dump_json() for r in evidence.observation.evidence}) == 1
        reserved = inspection.budget.reserved
        assert (reserved.model_calls, reserved.model_tokens, reserved.cost_ceiling_usd) == (8, 80000, 0)
        assert reserved.runtime_allowance_seconds == 120
        write_evidence(
            "join-retained.json",
            {
                "run_id": RUN_ID,
                "operation_id": OPERATION,
                "contract_digest": digest,
                "registrations": registrations,
                "stages": stages,
                "retained_revision": inspection.retained_revision,
                "generation_artifact_sha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
                "candidate_digest": candidate.digest,
                "evidence_id": evidence.evidence_id,
                "repaired_x_delta": after - before,
                "reserved_calls": reserved.model_calls,
            },
        )
    write_evidence("join-http-result.json", value)


def verify_children(guard, manifest, *, positive=False):
    """Preserve partial RED witnesses without claiming the unexecuted positive tree."""
    if JOIN_CASE == "cancel" and positive:
        return verify_cancel_children(guard, manifest)
    assert type(guard) is JoinGuards and guard.role == "harness"
    rows, missing = [], []
    pending = [(os.getpid(), row) for row in guard.spawn_records]
    while pending:
        parent, launch = pending.pop(0)
        pid = launch["pid"]
        path = Path(f"/evidence/join-process-{pid}.json")
        if not path.exists():
            if JOIN_CASE == "resume" and Path("/evidence/join-restart.json").exists():
                restart = read_json(Path("/evidence/join-restart.json"))
                if pid == restart["identity"]["pid"]:
                    row = read_json(Path(f"/evidence/join-process-{pid}-started.json"))
                    checkpoint = read_json(Path("/evidence/join-unreleased.json"))
                    row.update(checkpoint["guard"], status="interrupted_known_unreleased")
                    assert not row["spawn_records"] and restart["physical_group_absent"] is True
                else:
                    missing.append(pid)
                    continue
            else:
                missing.append(pid)
                continue
        else:
            row = read_json(path)
        assert row["source_sha256"] == manifest and row["parent_pid"] == parent
        assert row["pid"] == row["pgid"] == row["sid"] == pid
        assert row["bootstrap_argv"] == launch["bootstrap_argv"]
        assert row["boot"] == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        assert row["pid_namespace"] == os.readlink("/proc/self/ns/pid")
        assert type(row["start_ticks"]) is int and row["start_ticks"] > 0
        assert row["preimport"]["before_package_imports"] is True
        assert set(row["preimport"]["kernel_denial"]) == {"2", "10"}
        if row["role"] != "model":
            assert role_for(row["argv"][1:]) == row["role"]
        rows.append(row)
        pending.extend((pid, child) for child in row["spawn_records"])
    if positive:
        from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import group_members

        servers = [row for row in rows if row["role"] == "server"]
        interrupted = [row for row in rows if row["status"] == "interrupted_known_unreleased"]
        assert len(interrupted) == (1 if JOIN_CASE == "resume" else 0)
        completed = [row for row in rows if row not in interrupted]
        assert not missing and len(guard.spawn_records) == CLIENT_LAUNCHES
        assert len(servers) == (2 if JOIN_CASE == "resume" else 1)
        assert len(rows) == CLIENT_LAUNCHES + len(servers) + 4
        assert all(
            row["status"] == "completed"
            and row["returncode"]
            == (
                3
                if JOIN_CASE == "resume" and row["argv"][1:] == RECONCILE
                else 2 if JOIN_CASE == "resume" and row["argv"][1:] == LOST_RESPONSE else 0
            )
            for row in completed
        )
        if JOIN_CASE == "resume":
            lost = [row for row in completed if row["argv"][1:] == LOST_RESPONSE]
            assert len(lost) == 1 and lost[0]["lost_response_status"] == 200
        assert all(not any(row["forbidden"].values()) for row in rows)
        assert {row["pid"] for row in completed} == {
            int(p.name.removeprefix("join-process-").removesuffix(".json"))
            for p in Path("/evidence").glob("join-process-*.json")
            if not p.name.endswith("-started.json")
        }
        server = next(row for row in completed if row["role"] == "server")
        assert server["owner_constructions"] == 1 and server["allowed"]["child_launch"] == 4
        retained = read_json(Path("/evidence/join-retained.json"))
        models = [row for row in rows if row["role"] == "model"]
        assert len(models) == 4
        assert all(row["simulator_registry_prepared"] is False for row in [server, *models])
        assert {r["pid"] for r in retained["registrations"]} == {r["pid"] for r in models}
        stage_by_pid = dict(retained["stages"])
        assert [stage_by_pid[row["pid"]] for row in server["spawn_records"]] == [
            "generate",
            "observe",
            "repair",
            "observe",
        ]
        for row in rows:
            assert not any(r["state"] not in {"Z", "X"} for r in group_members(row["pid"]).values())
            if row["role"] in {"setup", "client", "launcher", "model"}:
                assert row["allowed"]["bolt"] == 0
            if row["role"] not in {"launcher", "server"}:
                assert row["allowed"]["child_launch"] == 0
            if row["role"] in {"admin", "server"}:
                assert row["basic_auth_handoffs"] and all(row["basic_auth_handoffs"])
        for row in models:
            assert row["parent_pid"] == server["pid"] and row["transport_installed_before_model_construction"] is True
            registration = next(r for r in retained["registrations"] if r["pid"] == row["pid"])
            assert registration["start_ticks"] == row["start_ticks"]
            assert registration["pgid"] == row["pgid"] and registration["sid"] == row["sid"]
            sdk = read_json(Path(f"/evidence/generation-child-{row['pid']}-sdk.json"))
            assert row["sdk_calls"] == sdk["calls"] == 2
            assert [r["kind"] for r in sdk["responses"]] == ["ping", "completion"]
        assert verify_sources() == manifest
    return {
        "join_case": JOIN_CASE,
        "joined_processes": [
            {"pid": row["pid"], "role": row["role"], "returncode": row.get("returncode"), "status": row["status"]}
            for row in rows
        ],
        "missing_process_witnesses": missing,
        "children_verified": positive and not missing,
    }


def verify_positive():
    # Installed stop may reply just before the guarded server's finalizer writes
    # its witness. Wait boundedly for that exact child, never restart/retry stop.
    path = Path(f"/evidence/join-process-{server_pid()}.json")
    deadline = min(ACTIVE.deadline, time.monotonic() + 5)
    while not path.exists():
        assert time.monotonic() < deadline, "stopped server finalization witness missing"
        time.sleep(0.02)
    proof = verify_children(ACTIVE, verify_sources(), positive=True)
    if JOIN_CASE == "cancel":
        ACTIVE.positive_complete = True
        write_evidence("join-positive.json", proof)
        return
    from workflow_graphql_execution_join_fixture import IDENTITY_FIELDS, check_detachment_proof

    detached = read_json(Path("/evidence/join-detached.json"))
    worker_pid = detached["worker_identity"]["pid"]
    active_path = Path(f"/evidence/generation-child-{worker_pid}-active.json")
    assert list(Path("/evidence").glob("generation-child-*-active.json")) == [active_path]
    release = read_json(active_path)
    check_detachment_proof(detached, release)
    retained = read_json(Path("/evidence/join-retained.json"))
    assert dict(retained["stages"])[worker_pid] == "generate"
    for kind in ("worker", "server"):
        expected = detached[kind + "_identity"]
        final = read_json(Path(f"/evidence/join-process-{expected['pid']}.json"))
        assert expected == {key: final[key] for key in IDENTITY_FIELDS}
    ACTIVE.positive_complete = True
    write_evidence("join-positive.json", proof)


def verify_cancel_result(value, cancellation, worker_identity):
    """Read cancellation/cleanup independently of the authenticated HTTP client."""
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load
    from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import group_members

    result = value["data"]["workflow"]
    command = cancellation["data"]["cancelWorkflow"]
    assert result["id"] == RUN_ID and result["state"] == "cancelled"
    assert command["durable"] == "recorded" and command["localStop"]["delivery"] == "delivered"
    resources = Resources(load(CONFIG))
    with resources.driver() as driver:
        store = resources.store(driver)
        receipt = store.get_cancel_receipt("p1-cancel")
        assert receipt.run_id == RUN_ID and receipt.receipt_digest == command["receipt"]["receiptDigest"]
        inspection = store.get_run_inspection(RUN_ID)
        assert inspection.intent.state == "cancelled"
        assert result["version"] == str(inspection.intent.run_version)
        assert result["retainedRevision"] == inspection.retained_revision
        assert len(inspection.cleanup.intents) == 1
        attempt = store.get_generation_attempt(RUN_ID)
        registration = attempt.registration
        assert registration.pid == worker_identity["pid"]
        assert registration.start_ticks == worker_identity["start_ticks"]
        assert registration.pgid == worker_identity["pgid"] and registration.sid == worker_identity["sid"]
        cleanup = inspection.cleanup.intents[0]
        assert cleanup.cleanup_state == "recorded" and cleanup.cleanup_observation == "owned_process_group_stopped"
        assert cleanup.registration_id == registration.registration_id
        assert cleanup.retired_owner is not None and not cleanup.retired_owner.dirty
        assert store.get_retired_owner(cleanup.retired_owner.owner_id) == store.get_owner() == cleanup.retired_owner
        assert not group_members(registration.pgid)
        assert inspection.budget.reserved.model_calls == 2
        write_evidence(
            "join-retained.json",
            dict(
                join_case="cancel",
                run_id=RUN_ID,
                receipt=receipt.model_dump(mode="json"),
                registration=registration.model_dump(mode="json"),
                cleanup=inspection.cleanup.model_dump(mode="json"),
                worker_identity=worker_identity,
                physical_group_absent=True,
                reserved=inspection.budget.reserved.model_dump(mode="json"),
            ),
        )
    write_evidence("join-http-result.json", {"result": value, "cancellation": cancellation})


def verify_cancel_children(guard, manifest):
    """A terminated worker needs exact parent cleanup, not an invented finally receipt."""
    from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import group_members
    from workflow_graphql_execution_join_fixture import IDENTITY_FIELDS

    retained = read_json(Path("/evidence/join-retained.json"))
    worker = retained["worker_identity"]
    rows = []
    pending = [(os.getpid(), row) for row in guard.spawn_records]
    while pending:
        parent, launch = pending.pop(0)
        pid = launch["pid"]
        terminated = pid == worker["pid"]
        name = f"join-process-{pid}{'-started' if terminated else ''}.json"
        row = read_json(Path("/evidence") / name)
        assert row["source_sha256"] == manifest and row["parent_pid"] == parent
        assert row["bootstrap_argv"] == launch["bootstrap_argv"]
        assert row["pid"] == row["pgid"] == row["sid"] == pid
        assert row["preimport"]["before_package_imports"] is True
        assert set(row["preimport"]["kernel_denial"]) == {"2", "10"}
        if terminated:
            assert row["role"] == "model" and {k: row[k] for k in IDENTITY_FIELDS} == worker
            assert row["transport_installed_before_model_construction"] is True
            active = read_json(Path(f"/evidence/generation-child-{pid}-active.json"))
            assert active["identity"] == worker and active["phase"] == "waiting"
            assert active["calls"] == 2 and active["response_returning"] is False
            assert retained["physical_group_absent"] is True and not group_members(pid)
        else:
            assert row["status"] == "completed" and row["returncode"] == 0
            assert not any(row["forbidden"].values())
            assert role_for(row["argv"][1:]) == row["role"]
            assert not any(r["state"] not in {"Z", "X"} for r in group_members(pid).values())
            pending.extend((pid, child) for child in row["spawn_records"])
            if row["role"] == "server":
                assert row["owner_constructions"] == 1 and row["allowed"]["child_launch"] == 1
                assert row["simulator_registry_prepared"] is False
        rows.append(
            dict(
                pid=pid,
                role=row["role"],
                evidence_file=name,
                status="owned_termination" if terminated else row["status"],
                returncode=None if terminated else row["returncode"],
            )
        )
    assert len(guard.spawn_records) == CLIENT_LAUNCHES and len(rows) == CLIENT_LAUNCHES + 2
    assert sum(row["status"] == "owned_termination" for row in rows) == 1
    assert verify_sources() == manifest
    return dict(join_case="cancel", joined_processes=rows, missing_process_witnesses=[], children_verified=True)


def initialization_pre_readiness(digest):
    """Inject only in the real installed build, after catalogue evaluation.

    Dormant in every legacy cohort; a reviewed S2 bootstrap must first establish
    its private case/controls capability. Raising directly preserves profiling
    guards, unlike an exception raised inside a profiling callback. Reaching
    this checkpoint alone is never a passing failure/timeout witness.
    """
    guard = ACTIVE
    case = getattr(guard, "initialization_case", None)
    if case is None:
        return
    assert case in {"failure", "timeout"}
    assert type(guard) is JoinGuards and guard.role == "server"
    assert getattr(guard, "initialization_controls_ready", False) is True
    assert guard.ports_issued and guard.owner_constructions == guard.sdk_calls == 0
    caller = sys._getframe(1)
    installed = sys.modules["isaaclab_arena.agentic_environment_generation.workflow.api.installed_execution"]
    assert caller.f_globals is installed.__dict__
    assert caller.f_code.co_name == "build" and caller.f_code.co_filename == (
        "/source/isaaclab_arena/agentic_environment_generation/workflow/api/installed_execution.py"
    )
    assert caller.f_locals["catalogue_digest"] == digest
    assert type(digest) is str and re.fullmatch(r"[a-f0-9]{64}", digest)
    from workflow_graphql_execution_join_fixture import initialization_preparation
    prepared = initialization_preparation("init-server")
    assert prepared["catalogue_sha256"] == digest
    initialization_finish_role(guard, prepared)
    marker = dict(
        **identity(), case=case, catalogue_sha256=digest,
        after_real_initialization=True, before_owner_construction=True,
        observed_at=time.monotonic(),
        kind="fixed-initialization-failure" if case == "failure" else "supervisor-stall-not-native-hang",
        status="checkpoint_only_not_lifecycle_proof",
    )
    write_evidence("initialization-pre-readiness.json", marker)
    if case == "failure":
        try:
            raise RuntimeError("S2 fixed post-initialization pre-readiness failure")
        except RuntimeError as error:
            # Observe the actual raise coordinate without exporting its message
            # or inventing a post-SIGKILL finalization witness. The same exception
            # propagates through the installed build/lifespan trace unchanged.
            marker["failure_site"] = dict(file=SELF, function="initialization_pre_readiness",
                                          line=error.__traceback__.tb_lineno)
            write_evidence("initialization-pre-readiness.json", marker)
            raise
    # Outer collection must stop the exact owned server group five seconds after
    # the marker. This independent watchdog only prevents an unbounded fixture;
    # its expiry is nonpass, not the specified external timeout witness.
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        time.sleep(0.05)
    raise TimeoutError("S2 external five-second stall supervision missing")


def initialization_environment(case, role):
    """Return the fixed S2 role environment; this grants no import authority."""
    assert type(case) is str and case in {"positive", "failure", "timeout"}
    assert type(role) is str and role in {"init-server", "init-generate", "init-refine", "init-assess"}
    assert case == "positive" or role == "init-server"
    root = "/tmp/s2-init/" + case + "/" + role
    return {
        "HOME": root + "/home", "XDG_CACHE_HOME": root + "/cache", "TMPDIR": root + "/tmp",
        "WARP_CACHE_PATH": root + "/cache/warp", "PATH": "/usr/bin:/bin",
        "NVIDIA_VISIBLE_DEVICES": "void", "CUDA_VISIBLE_DEVICES": "",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "SPATIALINDEX_C_LIBRARY": "/isaac-sim/exts/omni.pip.compute/pip_prebundle/rtree.libs/libspatialindex-e5350069.so",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def initialization_origin(name, origin, preloaded):
    """Check approved image/submodule origins; physical identity is checked separately."""
    assert type(name) is type(origin) is str and type(preloaded) is bool and not preloaded
    pure = "/isaac-sim/kit/python/lib/python3.12/site-packages/"
    roots = {
        "warp": pure + "warp", "torch": pure + "torch", "pxr": pure + "pxr",
        "openai": pure + "openai",
        "lazy_loader": pure + "lazy_loader", "numpy": pure + "numpy",
        "sympy": pure + "sympy", "mpmath": pure + "mpmath",
        "gymnasium": pure + "gymnasium",
        "torchgen": pure + "torchgen",
        "yaml": "/isaac-sim/exts/omni.pip.compute/pip_prebundle/yaml",
        "toml": "/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/toml",
        "isaaclab": "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab",
        "isaaclab_physx": "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab_physx/isaaclab_physx",
    }
    root = name.split(".")[0]
    assert all(part.isidentifier() for part in name.split("."))
    if root in roots:
        assert origin.startswith(roots[root] + "/")
    else:
        assert origin.startswith(("/isaac-sim/", "/workspaces/isaaclab_arena/submodules/"))
        relative = "/" + name.replace(".", "/")
        assert (origin.endswith((relative + ".py", relative + "/__init__.py"))
                or origin.endswith(".so") and relative + "." in origin
                and "/" not in origin.rsplit(relative + ".", 1)[1]), "S2 module name/origin mismatch"
    assert all(part not in {"", ".", ".."} for part in origin.split("/")[1:])
    assert origin.endswith((".py", ".so"))
    return root


def initialization_boundary_origins(fullname, roots, inventory):
    """Return physical Python origin candidates without calling import machinery."""
    assert re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", fullname), "S2 invalid target module"
    parts = fullname.split(".")
    assert len(parts) <= 16, "S2 target depth ceiling"
    origins, complete = [], True
    for index, root in enumerate(roots):
        directory = root + ("/" + "/".join(parts[:-1]) if len(parts) > 1 else "")
        result = inventory(directory)
        if result["status"] not in {"missing", "observed"}:
            complete = False
        if result["status"] != "observed":
            continue
        for item in result["witness"]["entries"]:
            name = item["name"]
            candidate = (name == parts[-1] + ".py" or name == parts[-1] + ".so"
                         or name.startswith(parts[-1] + ".") and name.endswith(".so"))
            if candidate:
                origins.append(dict(item, path=directory + "/" + name, path_index=index,
                                    status="stat_regular" if stat.S_ISREG(item["mode"]) and item["links"] == 1 else "refused"))
            elif name == parts[-1]:
                package = inventory(directory + "/" + name)
                if package["status"] != "observed":
                    complete = False
                    origins.append(dict(item, path=directory + "/" + name, path_index=index, status="package_refused"))
                    continue
                initializers = [leaf for leaf in package["witness"]["entries"]
                                if leaf["name"] == "__init__.py" or leaf["name"] == "__init__.so"
                                or leaf["name"].startswith("__init__.") and leaf["name"].endswith(".so")]
                for leaf in initializers:
                    origins.append(dict(leaf, path=directory + "/" + name + "/" + leaf["name"], path_index=index,
                                        status="stat_regular" if stat.S_ISREG(leaf["mode"]) and leaf["links"] == 1 else "refused"))
                if not initializers:
                    complete = False
                    origins.append(dict(item, path=directory + "/" + name, path_index=index, status="namespace_unreviewed"))
    complete &= all(row["status"] == "stat_regular" for row in origins)
    return origins, complete


def initialization_boundary_reconcile(admission, report, budget, append, replace):
    """Reconcile captured source edges with exact baseline names, never admit them."""
    boundary = report["boundary"]
    cache = {row["path"]: row for row in boundary["directories"]}

    def inventory(path):
        if path in cache:
            return cache[path]
        assert len(cache) < 512, "S2 directory count ceiling"
        row = dict(path=path, status="not_completed", witness=None, error_type=None)
        assert append(boundary["directories"], row), "S2 reconciliation encoded ceiling"
        try:
            witness = initialization_directory_inventory(path, budget)
            assert replace(row, "witness", witness), "S2 reconciliation encoded ceiling"
            row["status"] = "observed"
        except FileNotFoundError:
            row["status"] = "missing"
        except BaseException as error:
            row["status"] = "refused"
            try:
                replace(row, "error_type", type(error).__name__[:128])
            except BaseException:
                pass  # Terminal refusal is retained even when encoding expired.
        cache[path] = row
        return row

    modules = {
        "lazy_loader", "numpy", "sympy", "mpmath", "gymnasium", "cloudpickle", "filelock",
        "typing_extensions", "setuptools", "networkx", "jinja2", "fsspec", "cuda", "triton",
        "optree", "opt_einsum", "farama_notifications", "packaging",
    }
    edges = {}
    for source in report["files"]:
        for edge in source.get("imports", []):
            if edge["level"]:
                continue
            for name in [edge["module"]] if edge["module"] else edge["names"]:
                top = name.split(".")[0]
                # Only source-observed mpmath external backend names are probed.
                if "/mpmath/" in source["path"] and top in {"gmpy", "gmpy2", "sage"}:
                    modules.add(top)
                edges.setdefault(top, []).append(dict(path=source["path"], line=edge["line"],
                                                       fullname=name, qualification=edge["qualification"]))
    for module in sorted(modules):
        assert time.monotonic() < budget["deadline"], "S2 reconciliation deadline"
        name = module.replace("_", "-")
        distributions = [dict(name=row["name"], version=row["version"], metadata_path=row["metadata_path"])
                         for row in boundary["distributions"]
                         if re.sub(r"[-_.]+", "-", row["name"]).lower() == name]
        origins, complete = initialization_boundary_origins(module, ["/isaac-sim/kit/python/lib/python3.12/site-packages"], inventory)
        row = dict(module=module, candidate_root="/isaac-sim/kit/python/lib/python3.12/site-packages/" + module,
                   origins=origins, origin_coverage_complete=complete,
                   source_edges=edges.get(module, []), source_coverage_complete=all(
                       source["imports_complete"] for source in report["files"]),
                   baseline_full_names={name: origin for name, origin in admission.baseline.items()
                                        if name == module or name.startswith(module + ".")},
                   distributions=distributions, origin_status=("observed" if origins else "missing") if complete else "unresolved",
                   effect_review="required_not_admitted", admitted=False)
        assert append(boundary["external_families"], row), "S2 reconciliation encoded ceiling"


def initialization_boundary_native(boundary, budget, paths, inventory, emit, put, *, fixed_context=None):
    """Stat the retained Torch/NumPy/Warp/YAML selectors; never open a binary."""
    p = "/isaac-sim/kit/python/lib/python3.12/site-packages"
    table = (
        ("cublas", "libcublas.so.*[0-9]"), ("cudnn", "libcudnn.so.*[0-9]"),
        ("cuda_nvrtc", "libnvrtc.so.*[0-9]"), ("cuda_nvrtc", "libnvrtc-builtins.so.*[0-9]"),
        ("cuda_runtime", "libcudart.so.*[0-9]"), ("cuda_cupti", "libcupti.so.*[0-9]"),
        ("cufft", "libcufft.so.*[0-9]"), ("curand", "libcurand.so.*[0-9]"),
        ("nvjitlink", "libnvJitLink.so.*[0-9]"), ("cusparse", "libcusparse.so.*[0-9]"),
        ("cusparselt", "libcusparseLt.so.*[0-9]"), ("cusolver", "libcusolver.so.*[0-9]"),
        ("nccl", "libnccl.so.*[0-9]"), ("nvshmem", "libnvshmem_host.so.*[0-9]"),
        ("cufile", "libcufile.so.*[0-9]"), ("nvtx", "libnvToolsExt.so.*[0-9]"),
    )
    selectors = [dict(kind="torch_cuda_preload", folder=folder, pattern=pattern, required=index < 15,
                      rationale="retained-not-current torch/__init__.py:284-351; torch.version.cuda=12.8; branch not executed",
                      candidates=[], searches=[], winner=None, status="not_completed")
                 for index, (folder, pattern) in enumerate(table)]
    fixed = (
        ("torch_global_deps", p + "/torch/lib", "libtorch_global_deps.so", "ctypes", True),
        ("torch_C", p + "/torch", "_C*.so", "extension", True),
        ("torch_shm_manager", p + "/torch/bin", "torch_shm_manager", "executable_only", True),
        ("numpy_core", p + "/numpy/_core", "*.so", "extension", True),
        ("numpy_wheel_libs", p + "/numpy.libs", "*", "transitive_candidate", False),
        ("warp_core", p + "/warp/bin", "warp.so", "ctypes", True),
        ("warp_llvm", p + "/warp/bin", "warp-clang.so", "ctypes_optional", False),
        ("yaml_extension", E1_YAML_ROOT, "_yaml*.so", "extension", False),
    )
    selectors = [dict(kind=kind, directory=directory, pattern=pattern, load_kind=load_kind, required=required,
                       rationale="retained-not-current source selector; stat is not load/hash authority",
                       candidates=[], searches=[], winner=None, status="not_completed")
                  for kind, directory, pattern, load_kind, required in fixed] + selectors
    put(boundary, "native", selectors)
    put(boundary, "projection", dict(
        role_identity_limit=budget.get("native_limit", 16), role_read_limit=boundary["role_read_limit"],
        aggregate_identity_limit=64, aggregate_read_limit=8 * 1024**3,
        conditional_required_identities=17, four_role_conditional_identities=68,
        condition="full fifteen-preload branch plus global_deps and _C; not observed execution",
        branch_executed=False, admission_enabled=False, complete=False, identities=[], known_read_bytes=0,
        read_expression="5 * sum(extension sizes) + sum(ctypes size * actual admission-call count); count unknown",
        missing_or_refused=[], quota_blocker="conditional 17 > 16 and four-role 68 > 64; no allowance changed",
        excludes="manager executable and merely transitive map candidates are not explicit load identities",
    ))
    projection = boundary["projection"]

    def matches(name, pattern):
        if pattern.endswith("*[0-9]"):
            prefix = pattern[:-6]
            return name.startswith(prefix) and len(name) > len(prefix) and name[-1] in "0123456789"
        if "*" in pattern:
            left, right = pattern.split("*")
            return name.startswith(left) and name.endswith(right) and len(name) >= len(left) + len(right)
        return name == pattern

    for index, selector in enumerate(selectors):
        if index == len(fixed) and fixed_context is not None:
            fixed_context()
        complete = True
        precedence_known = True
        if selector["kind"] == "torch_cuda_preload":
            searches = [(index, layout, root + suffix) for index, root in enumerate(paths)
                        for layout, suffix in enumerate(("/nvidia/" + selector["folder"] + "/lib",
                                                         "/nvidia/cu12/lib", "/" + selector["folder"] + "/lib"))]
        else:
            searches = [(None, None, selector["directory"])]
        for path_index, layout, directory in searches:
            observed = inventory(directory)
            emit(selector["searches"], dict(path_index=path_index, layout=layout, directory=directory,
                                           status=observed["status"]))
            if observed["status"] not in {"observed", "missing"}:
                complete = False
                if selector["winner"] is None:
                    precedence_known = False
            if observed["status"] != "observed":
                continue
            # glob returns scandir order, not lexicographic evidence order.
            for item in sorted(observed["witness"]["entries"], key=lambda row: row["scan_index"]):
                if item["name"].startswith(".") or not matches(item["name"], selector["pattern"]):
                    continue
                regular = stat.S_ISREG(item["mode"]) and item["links"] == 1
                candidate = dict(item, path=directory + "/" + item["name"], path_index=path_index, layout=layout,
                                 status="stat_regular" if regular else "link_or_nonregular_refused")
                emit(selector["candidates"], candidate)
                if selector["winner"] is None and precedence_known:
                    put(selector, "winner", candidate["path"])
                if not regular:
                    complete = False
        selector["status"] = "observed" if complete else "unresolved"
        if not selector["candidates"] and complete:
            selector["status"] = "missing"
        if not precedence_known:
            selector["status"] = "unresolved_precedence"
        if selector["kind"] == "numpy_wheel_libs" or selector.get("load_kind") == "executable_only":
            continue
        chosen = (selector["candidates"] if selector.get("load_kind") == "extension" else
                  [row for row in selector["candidates"] if row["path"] == selector["winner"]])
        if not chosen or selector["status"] != "observed":
            emit(projection["missing_or_refused"], selector["kind"])
        for candidate in chosen:
            if candidate["status"] != "stat_regular":
                continue
            multiplier = 5 if selector.get("load_kind") == "extension" else 1
            emit(projection["identities"], dict(path=candidate["path"], size=candidate["size"],
                 device=candidate["device"], inode=candidate["inode"], kind=selector["kind"],
                 minimum_read_count=multiplier, projected_minimum_read_bytes=multiplier * candidate["size"]))
            projection["known_read_bytes"] += multiplier * candidate["size"]
    boundary["native_complete"] = all(row["status"] in {"observed", "missing"} for row in selectors)
    # Even complete stats do not resolve conditional branches or repeated ctypes calls.
    projection["complete"] = False


INITIALIZATION_METADATA_PAGE = "DIST"  # Future literal variants require a fresh full-source review.


def initialization_metadata_page_selection(page):
    """Return one frozen candidate page, never runtime-supplied physical paths."""
    import hashlib
    import json

    assert type(page) is str and page in ("EP-A", "EP-B", "DIST"), "S2 invalid metadata page"
    pages = {'EP-A': (['/isaac-sim/kit/python/lib/python3.12/site-packages/jupyter_server-2.20.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/jupyterlab-4.6.3.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/killport-1.2.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/lark-1.3.1.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/lightwheel_sdk-1.0.3.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/markdown-3.10.3.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/markdown_it_py-4.2.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/matplotlib_inline-0.2.2.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/mistune-3.3.4.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/mujoco_warp-3.8.1.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nbclient-0.11.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nbconvert-7.17.1.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nbformat-5.11.1.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/networkx-3.6.1.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/notebook-7.6.2.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/numpy-2.5.2.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/onnx-1.21.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/onnxruntime-1.29.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/opentelemetry_api-1.44.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/pandas-2.2.3.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/pip-26.2.1.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/pygments-2.21.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/pytest-9.1.1.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/pytest_mock-3.15.1.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/python_dotenv-1.2.3.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/ray-2.52.1.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/rerun_sdk-0.36.2.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/send2trash-2.1.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/setuptools-81.0.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/strawberry_graphql-0.327.7.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/streamlit-1.62.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/sympy-1.14.0.dist-info/entry_points.txt'],
          'febf2b0c31c951eb46a52ee2348fed4d9f522a459d3c4557e3f9e247d4abbcfc'),
 'EP-B': (['/isaac-sim/kit/python/lib/python3.12/site-packages/tabulate-0.10.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/tensorboard-2.21.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/torch-2.10.0+cu128.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/tqdm-4.67.1.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/transformers-4.57.6.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/triton-3.6.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/uvicorn-0.52.4.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/viser-1.1.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/vuer-0.1.6.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/wandb-0.28.2.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/webcolors-25.10.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/websocket_client-1.9.0.dist-info/entry_points.txt',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/websockets-16.1.1.dist-info/entry_points.txt',
           '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/annotated_doc-0.0.4.dist-info/entry_points.txt',
           '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/anyio-4.13.0.dist-info/entry_points.txt',
           '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/cffi-2.0.0.dist-info/entry_points.txt',
           '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/charset_normalizer-3.3.2.dist-info/entry_points.txt',
           '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/fastapi-0.120.4.dist-info/entry_points.txt',
           '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/jinja2-3.1.5.dist-info/entry_points.txt',
           '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/qrcode-7.4.2.dist-info/entry_points.txt',
           '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/sentry_sdk-2.42.1.dist-info/entry_points.txt',
           '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/watchdog-4.0.0.dist-info/entry_points.txt',
           '/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle/urdf_usd_converter-0.1.3.dist-info/entry_points.txt'],
          '3e6194d842fb38c44097f8c97823ec1840fae6cf3853343cde1ac9f1d4639695'),
 'DIST': (['/isaac-sim/kit/python/lib/python3.12/site-packages/lazy_loader-0.5.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/mpmath-1.3.0.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/networkx-3.6.1.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/numpy-2.5.2.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_cublas_cu12-12.8.4.1.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_cuda_cupti_cu12-12.8.90.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_cuda_nvrtc_cu12-12.8.93.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_cuda_runtime_cu12-12.8.90.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_cudnn_cu12-9.10.2.21.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_cufft_cu12-11.3.3.83.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_cufile_cu12-1.13.1.3.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_curand_cu12-10.3.9.90.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_cusolver_cu12-11.7.3.90.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_cusparse_cu12-12.5.8.93.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_cusparselt_cu12-0.7.1.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_nccl_cu12-2.27.5.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_nvjitlink_cu12-12.8.93.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_nvshmem_cu12-3.4.5.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia_nvtx_cu12-12.8.90.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/setuptools-81.0.0.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/sympy-1.14.0.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/torch-2.10.0+cu128.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/triton-3.6.0.dist-info/METADATA',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/typing_extensions-4.16.0.dist-info/METADATA',
           '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/jinja2-3.1.5.dist-info/METADATA'],
          'b2040a9b4f20a9ba99c3e725a9199107d8106add63a18be8121277a8be21e1d0')}
    paths, digest = pages[page]
    assert hashlib.sha256(json.dumps(paths, separators=(",", ":")).encode()).hexdigest() == digest, "S2 metadata membership changed"
    assert len(paths) == {"EP-A": 32, "EP-B": 23, "DIST": 25}[page] and len(set(paths)) == len(paths)
    binding = {'run': 'arena-s2-init-fda1fe67d99d469997d24745cb648ca6',
 'image': 'sha256:b94e17024f1e123ac5a42759ab56651a18823fda7c701e765cba31f200154cdd',
 'provision_manifest_sha256': '03764536ed54c1f59cbf46305c5bc4ba618e2dc1deeeac7ffdfb21a0dffbf810',
 'role_leaf_sha256': 'f24e220755fd1f4ef2aaa5c505f1899d36cf0aaeacc0fd124a3cb435f63d4fd8',
 'sys_path': ['/source/scripts',
              '/source/web/arena-workbench/tests/e2e/functional-v7',
              '/isaac-sim/kit/python/lib/python312.zip',
              '/isaac-sim/kit/python/lib/python3.12',
              '/isaac-sim/kit/python/lib/python3.12/lib-dynload',
              '/isaac-sim/kit/python/lib/python3.12/site-packages',
              '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle',
              '/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle']}
    binding.update(name=page, paths=paths, membership_sha256=digest,
        manifest_sha256="847811bdcb4f4bdfa10ad0051cd3c4b603a35f429c68fdaa9f2ff3f302fa0613",
        sources=["/isaac-sim/kit/python/lib/python3.12/importlib/metadata/" + name
                 for name in ("_collections.py", "_itertools.py", "_functools.py", "_adapters.py")] if page == "EP-A" else [])
    return binding


def initialization_metadata_page_state(page, role_read_limit):
    """Reserve finite page membership and terminal outcomes before any reads."""
    selected = initialization_metadata_page_selection(page)
    boundary = initialization_boundary_state(role_read_limit)
    boundary.update(metadata_selection="fixed_candidate_page", page=dict(
        binding=selected, started=False, page_content_complete=False, context_bound=False,
        discovery_complete=False, parser_bound=False, resolver_order_equivalent=False,
        cross_run_mount_source_equivalence=False,
        semantics="raw static candidate evidence only; not effective distributions/plugins or admission"))
    boundary["metadata"] = [dict(path=path, path_index=selected["sys_path"].index(path.rsplit("/", 2)[0]),
        status="not_read_pending", witness=None, text=None, raw_hex=None, error_type=None,
        parse_status="not_parsed") for path in selected["paths"]]
    return boundary


def initialization_metadata_page_capture(admission, report, budget, append, replace, *, page):
    """Read one frozen candidate page under the enclosing frontier's budget."""
    selected = initialization_metadata_page_selection(page)
    boundary = report["boundary"]
    state = boundary["page"]
    assert not state["started"], "S2 metadata page already consumed"
    state["started"] = True  # No continuation or second page in this invocation.
    boundary["status"] = "partial"
    paths, finders, hooks = list(sys.path), tuple(sys.meta_path), tuple(sys.path_hooks)
    provider_snapshot = None
    cache = {}

    def put(container, key, value):
        assert replace(container, key, value), "S2 metadata page encoded ceiling"

    def emit(container, value):
        assert time.monotonic() < budget["deadline"], "S2 metadata page deadline"
        assert append(container, value), "S2 metadata page encoded ceiling"

    def inventory(path, *, summary=False):
        if path in cache:
            return cache[path]
        assert len(cache) < 512, "S2 directory count ceiling"
        row = dict(path=path, status="not_completed", witness=None, error_type=None)
        emit(boundary["directories"], row)
        cache[path] = row
        try:
            witness = initialization_directory_inventory(path, budget)
            # A fresh root membership summary is NOT cached resolver order proof.
            if summary:
                projection = [[item["name"], item["scan_index"], item["mode"]] for item in witness["entries"]]
                compact = {key: value for key, value in witness.items() if key != "entries"}
                compact.update(entry_count=len(projection), membership_order_sha256=hashlib.sha256(
                    json.dumps(projection, separators=(",", ":")).encode()).hexdigest(),
                    projection="[name,raw_scan_index,mode] in name-sorted presentation; not resolver/cache equivalence")
                put(row, "witness", compact)
            else:
                put(row, "witness", witness)
            row["status"] = "observed"
        except FileNotFoundError:
            row["status"] = "missing"
        except BaseException as error:
            row["status"] = "refused"
            put(row, "error_type", type(error).__name__[:128])
        return row

    try:
        assert state["binding"] == selected, "S2 metadata page binding changed"
        assert [row["path"] for row in boundary["metadata"]] == selected["paths"], "S2 metadata rows changed"
        assert report["image"] == admission.runner.GRAPHQL_IMAGE == selected["image"], "S2 metadata image changed"
        assert (report["provision_manifest_sha256"] == admission.runner.GRAPHQL_MANIFEST_SHA256
                == selected["provision_manifest_sha256"]), "S2 metadata provision changed"
        assert len(paths) <= 128 and all(type(path) is str for path in paths), "S2 unsupported page path"
        assert paths == selected["sys_path"], "S2 metadata path order changed"
        put(boundary, "sys_path", paths)
        state["context_bound"] = True
        provider_snapshot = initialization_boundary_provider_snapshot(admission.provider_state, finders)
        for obj, nonparticipant in zip(finders, provider_snapshot):
            emit(boundary["finders"], dict(object_id=id(obj), identity=nonparticipant or "opaque_unsupported",
                status="metadata_nonparticipant_at_start" if nonparticipant is not None else "unclassified"))
        for obj in hooks:
            # Hooks remain opaque here; no discovery or callable is invoked.
            emit(boundary["path_hooks"], dict(object_id=id(obj), identity="opaque_unsupported", status="unclassified"))
        roots = {path.rsplit("/", 2)[0] for path in selected["paths"]}
        for index, root in enumerate(paths):
            row = dict(path_index=index, path=root, status="retained_not_current")
            emit(boundary["path_coverage"], row)
            if index < 2 or root in roots:
                row["status"] = inventory(root, summary=True)["status"]
        for row in boundary["metadata"]:
            if time.monotonic() >= budget["deadline"]:
                row["status"] = "not_read_deadline"
                continue
            if boundary["metadata_files"] >= 32:
                row["status"] = "not_read_metadata_limit"
                continue
            boundary["metadata_files"] += 1
            try:
                path = row["path"]
                parent, _, name = path.rpartition("/")
                directory = inventory(parent)
                if directory["status"] != "observed":
                    row["status"] = "not_read_missing" if directory["status"] == "missing" else "not_read_refused"
                    continue
                item = next((entry for entry in directory["witness"]["entries"] if entry["name"] == name), None)
                if item is None:
                    row["status"] = "not_read_missing"
                    continue
                assert stat.S_ISREG(item["mode"]) and item["links"] == 1, "S2 metadata link/nonregular"
                if item["size"] == 0:
                    put(row, "witness", item)
                    row["status"] = "empty_stat_only_unread"
                    continue  # The unchanged physical reader refuses empty non-source content.
                witness, raw = initialization_physical_file(path, budget, source=True)
                put(row, "witness", witness)
                put(row, "text", raw.decode("utf-8", errors="strict"))
                row["status"] = "observed"
            except UnicodeDecodeError:
                row["status"] = "read_decode_error"
                put(row, "raw_hex", raw.hex())
                put(row, "error_type", "UnicodeDecodeError")
            except BaseException as error:
                row["status"] = "read_error" if row["witness"] is not None else "not_read_refused"
                if type(error) is FileNotFoundError:
                    row["status"] = "not_read_missing"
                elif type(error) is PermissionError:
                    row["status"] = "not_read_permission"
                elif type(error) is OSError:
                    row["status"] = "not_read_error"
                elif type(error) is AssertionError and len(error.args) == 1 and type(error.args[0]) is str:
                    row["status"] = {
                        "S2 metadata link/nonregular": "not_read_link",
                        "S2 physical link refused": "not_read_link",
                        "S2 physical hard link refused": "not_read_link",
                        "S2 physical per-file ceiling": "not_read_oversize",
                        "S2 physical read ceiling": "not_read_byte_limit",
                        "S2 metadata page encoded ceiling": "read_encoded_limit",
                    }.get(error.args[0], row["status"])
                if time.monotonic() >= budget["deadline"]:
                    row["status"] = "read_deadline" if row["witness"] is not None else "not_read_deadline"
                put(row, "error_type", type(error).__name__[:128])
    except BaseException as error:
        # Binding failures must also prevent the enclosing source reads.
        try:
            put(boundary, "error_type", type(error).__name__[:128])
        finally:
            if not state["context_bound"]:
                raise
    finally:
        boundary["entries"] = budget["entries"]
        final_paths = list(sys.path)
        boundary["path_stable"] = all(type(path) is str for path in final_paths) and final_paths == paths
        boundary["finders_stable"] = len(sys.meta_path) == len(finders) and all(a is b for a, b in zip(sys.meta_path, finders))
        boundary["path_hooks_stable"] = len(sys.path_hooks) == len(hooks) and all(a is b for a, b in zip(sys.path_hooks, hooks))
        # Pre-reserved terminal boolean: true is smaller than its false reserve.
        boundary["provider_shapes_stable"] = (provider_snapshot is not None and
            initialization_boundary_provider_snapshot(admission.provider_state, finders) == provider_snapshot)
        for row in boundary["metadata"]:
            if row["status"] == "not_read_pending":
                row["status"] = "not_read_deadline" if time.monotonic() >= budget["deadline"] else "not_read_inspection_error"
        state["page_content_complete"] = (state["context_bound"] and all(boundary[key] for key in (
            "path_stable", "finders_stable", "path_hooks_stable", "provider_shapes_stable"))
            and all(row["status"] == "observed" for row in boundary["metadata"]))
        # Even every selected leaf says nothing about unselected/shadowing distributions or providers.
        boundary["metadata_complete"] = boundary["distributions_complete"] = False
        boundary["torch_backends"] = boundary["gymnasium_plugins"] = None


def initialization_boundary_state(role_read_limit):
    """Predeclare every terminal boundary field before any inspection read."""
    return dict(status="not_started", sys_path=[], finders=[], path_hooks=[], importer_cache=[],
                path_coverage=[], directories=[], metadata=[], distributions=[], plugins=[],
                metadata_complete=False, distributions_complete=False, metadata_selection="not_started", torch_backends=None,
                gymnasium_plugins=None, native=[], native_complete=False, numpy_hook=None,
                zip_path=dict(path="/isaac-sim/kit/python/lib/python312.zip", status="not_started",
                              parent_directory="/isaac-sim/kit/python/lib", parent_status=None, entry=None),
                gmp_backends=[dict(module=name, status="not_started", roots=[], origins=None,
                    physical_coverage_complete=False, global_availability=None, admitted=False,
                    scope="fixed image roots only; no provider/archive or selected-backend claim",
                    rationale="retained-not-current mpmath/libmp/backend.py selector; Sage remains conditional")
                    for name in ("gmpy2", "gmpy")],
                projection=None, role_read_limit=role_read_limit, external_families=[], metadata_files=0, entries=0,
                limits=dict(metadata_files=32, entries_per_directory=4096, entries_total=4096, directories=512, paths=128),
                error_type=None, incomplete_reasons=[], path_stable=False, finders_stable=False, path_hooks_stable=False,
                provider_shapes_stable=False,
                context_interval="boundary inventory only; not a later metadata discovery checkpoint")


def initialization_boundary_provider_items(namespace, *, class_namespace=False):
    """Read exact dicts or a proxy obtained directly from a proven ordinary class."""
    # MappingProxyType can wrap a hostile custom mapping. Only type's own raw
    # class dictionary descriptor establishes builtin backing for such a proxy.
    if type(namespace) is not dict and not (class_namespace and type(namespace) is type(type.__dict__)):
        raise ValueError("unsupported provider namespace")
    if len(namespace) > 4096:
        raise ValueError("provider namespace ceiling")
    items = tuple(namespace.items())
    if len(items) > 4096 or not all(type(key) is str for key, _ in items):
        raise ValueError("unsupported provider namespace keys")
    return items


def initialization_boundary_provider_freeze(value):
    """Freeze bounded builtin container membership; opaque leaves are identity-only."""
    result, seen = [], set()

    def walk(item, depth):
        if depth > 12 or len(result) >= 32768:
            raise ValueError("provider snapshot ceiling")
        result.append(item)
        kind = type(item)
        if kind is not dict and kind is not list and kind is not tuple and kind is not set:
            return
        if id(item) in seen:
            return
        seen.add(id(item))
        if kind is dict:
            entries = initialization_boundary_provider_items(item)
            for key, child in entries:
                result.append(key)
                walk(child, depth + 1)
        else:
            if len(item) > 4096:
                raise ValueError("provider container ceiling")
            for child in item:
                walk(child, depth + 1)
        result.append(kind)  # Unambiguous container terminator, not user equality.

    walk(value, 0)
    return tuple(result)


def initialization_boundary_provider_same(current, frozen):
    """Compare references only, except exact builtin layout integers."""
    return len(current) == len(frozen) and all(
        a is b or (type(a) is int and type(b) is int and a == b) for a, b in zip(current, frozen))


def initialization_boundary_provider_function(function, namespace):
    """Freeze exact live function/code/global/closure identities, never bytecode labels."""
    if type(function) is not type(lambda: None) or function.__globals__ is not namespace:
        raise ValueError("unsupported provider method")
    snapshot = [function, function.__code__, function.__globals__, function.__closure__]
    for value in (function.__defaults__, function.__kwdefaults__, function.__dict__):
        snapshot.extend(initialization_boundary_provider_freeze(value))
    if function.__closure__ is not None:
        for cell in function.__closure__:
            snapshot.append(cell)
            snapshot.extend(initialization_boundary_provider_freeze(cell.cell_contents))
    return tuple(snapshot)


def initialization_boundary_provider_context(context):
    """Snapshot shallow namespace memberships and selected deep source witnesses."""
    snapshot = []
    for namespace in context[0]:
        snapshot.append(namespace)
        for key, value in initialization_boundary_provider_items(namespace):
            snapshot.extend((key, value))
    for value in context[1]:
        snapshot.extend(initialization_boundary_provider_freeze(value))
    return tuple(snapshot)


def initialization_boundary_provider_shape(provider, namespace, methods, instance_keys):
    """Snapshot an ordinary anchored instance without binding its attributes."""
    cls = type(provider)
    if type(cls) is not type:
        raise ValueError("unsupported provider metaclass")
    mro = type.__getattribute__(cls, "__mro__")
    if type(mro) is not tuple or len(mro) != 2 or mro[0] is not cls or mro[1] is not object:
        raise ValueError("unsupported provider MRO")
    raw = type.__getattribute__(cls, "__dict__")
    items = initialization_boundary_provider_items(raw, class_namespace=True)
    allowed = {*methods, "__module__", "__doc__", "__dict__", "__weakref__"}
    if {key for key, _ in items} != allowed:
        raise ValueError("changed provider class namespace")
    descriptor = raw["__dict__"]
    if (type(descriptor) is not type(type.__dict__["__dict__"])
            or descriptor.__objclass__ is not cls or descriptor.__name__ != "__dict__"):
        raise ValueError("unsupported provider dictionary descriptor")
    # Only this proven builtin descriptor may touch the instance namespace.
    instance = descriptor.__get__(provider, cls)
    instance_items = initialization_boundary_provider_items(instance)
    if type(instance) is not dict or {key for key, _ in instance_items} != set(instance_keys):
        raise ValueError("changed provider instance namespace")
    if instance_keys:
        if (type(instance["name"]) is not str or instance["name"] != "six"
                or type(instance["known_modules"]) is not dict):
            raise ValueError("unsupported six constructor state")
    snapshot = [provider, cls, descriptor, instance]
    for name in ("__basicsize__", "__itemsize__", "__dictoffset__", "__weakrefoffset__"):
        snapshot.append(type.__getattribute__(cls, name))
    for pairs in (items, initialization_boundary_provider_items(namespace)):
        for key, value in pairs:
            snapshot.extend((key, value))
    snapshot.extend(initialization_boundary_provider_freeze(instance))
    for name in methods:
        snapshot.extend(initialization_boundary_provider_function(raw[name], namespace))
    return tuple(snapshot)


def initialization_boundary_provider_bootstrap(runner, sources):
    """Anchor only trusted post-query objects; this is not a public authenticator.

    Call once immediately after the verified query bootstrap, before application
    execution. `sources` is the existing verified staged source manifest. No
    source/finder is imported or executed here. Missing/unsafe anchors stay opaque.
    """
    state = {"anchors": [], "sources": sources}
    try:
        if type(runner) is not type(os):
            return state
        runner_ns = object.__getattribute__(runner, "__dict__")
        initialization_boundary_provider_items(runner_ns)
        initialization_boundary_provider_items(sources)
        installer = runner_ns.get("install_staged_import_guard")
        pin = sources.get("scripts/run-workflow-neo4j-checks.py")
        if (type(pin) is not str or pin != "232790f2e4aae824c6e809fc1930965feed3baa47365db4a5c1ebd996fdbe20d"
                or type(installer) is not type(lambda: None) or installer.__globals__ is not runner_ns):
            return state
        state["installer"] = (installer, installer.__code__, runner_ns,
                              initialization_boundary_provider_items(runner_ns))
        state["installer_snapshot"] = initialization_boundary_provider_function(installer, runner_ns)
        state["source_snapshot"] = initialization_boundary_provider_freeze(sources)
        importlib_module = sys.modules.get("importlib")
        bootstrap_module = sys.modules.get("_frozen_importlib")
        if type(importlib_module) is type(os) and type(bootstrap_module) is type(os):
            bootstrap_ns = object.__getattribute__(bootstrap_module, "__dict__")
            initialization_boundary_provider_items(bootstrap_ns)
            module_spec = bootstrap_ns.get("ModuleSpec")
            if type(module_spec) is type:
                state["staged_stdlib"] = (importlib_module, module_spec)
        pathlib_module = sys.modules.get("pathlib")
        if type(pathlib_module) is type(os):
            pathlib_ns = object.__getattribute__(pathlib_module, "__dict__")
            initialization_boundary_provider_items(pathlib_ns)
            path_type = pathlib_ns.get("PosixPath")
            if type(path_type) is type and runner_ns.get("Path") is pathlib_ns.get("Path"):
                state["staged_path_type"] = path_type
        probe = runner_ns.get("_GRAPHQL_PROBE")
        initialization_boundary_provider_items(probe)
        result = probe.get("result")
        initialization_boundary_provider_items(result)
        if type(result.get("status")) is not str or result["status"] != "passed":
            return state
        loaded = result.get("loaded_modules")
        initialization_boundary_provider_items(loaded)
        witness = loaded.get("six")
        initialization_boundary_provider_items(witness)
        origin = "/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle/six.py"
        digest = "c51c91f703d3d4b3696c923cb5fec213e05e75d9215393befac7f2fa6a3904df"
        for key, expected in (("file", origin), ("path", origin), ("physical", origin), ("origin", origin),
                              ("sha256", digest)):
            if type(witness.get(key)) is not str or witness[key] != expected:
                return state
        if (type(witness.get("size")) is not int or witness["size"] != 34703
                or type(witness.get("links")) is not list or len(witness["links"]) != 0):
            return state
        module = sys.modules.get("six")
        if type(module) is not type(os):
            return state
        namespace = object.__getattribute__(module, "__dict__")
        initialization_boundary_provider_items(namespace)
        if type(namespace.get("__file__")) is not str or namespace["__file__"] != origin:
            return state
        provider = namespace.get("_importer")
        if type(provider) is not namespace.get("_SixMetaPathImporter"):
            return state
        methods = ("__init__", "_add_module", "_get_module", "find_module", "find_spec",
                   "_SixMetaPathImporter__get_module", "load_module", "is_package", "get_code",
                   "get_source", "create_module", "exec_module")
        snapshot = initialization_boundary_provider_shape(provider, namespace, methods, ("name", "known_modules"))
        context = ((runner_ns, probe, result, loaded), (witness, sources))
        context_snapshot = initialization_boundary_provider_context(context)
        state["anchors"].append(dict(provider=provider, namespace=namespace, methods=methods,
                                     instance_keys=("name", "known_modules"), snapshot=snapshot, module=module,
                                     context=context, context_snapshot=context_snapshot,
                                     label="six._SixMetaPathImporter[metadata_nonparticipant]"))
    except (ValueError, KeyError, TypeError):
        pass
    return state


def initialization_boundary_provider_staged(state, provider, closure):
    """Retain the exact installer return at the sole positive S2 call site."""
    if state is None or "installer" not in state:
        return
    try:
        installer, code, namespace, frozen = state["installer"]
        current = initialization_boundary_provider_items(namespace)
        if (installer.__code__ is not code or installer.__globals__ is not namespace
                or len(current) != len(frozen)
                or not all(k is a and v is b for (k, v), (a, b) in zip(current, frozen))
                or not initialization_boundary_provider_same(
                    initialization_boundary_provider_function(installer, namespace), state["installer_snapshot"])
                or not initialization_boundary_provider_same(
                    initialization_boundary_provider_freeze(state["sources"]), state["source_snapshot"])):
            return
        snapshot = initialization_boundary_provider_shape(provider, namespace, ("find_spec",), ())
        method = type.__getattribute__(type(provider), "__dict__")["find_spec"]
        if not any(method.__code__ is nested for child in code.co_consts if type(child) is type(code)
                   for nested in child.co_consts):
            return
        initialization_boundary_provider_items(closure)
        cells = method.__closure__
        if (method.__code__.co_freevars != ("ModuleSpec", "importlib", "modules", "namespaces", "packages", "root")
                or cells is None or len(cells) != 6 or cells[3].cell_contents is not closure.get("namespaces")):
            return
        importlib_module, module_spec = state["staged_stdlib"]
        if cells[0].cell_contents is not module_spec or cells[1].cell_contents is not importlib_module:
            return
        files, namespaces = closure.get("files"), closure.get("namespaces")
        if (type(files) is not list or type(namespaces) is not list
                or not all(type(value) is str for value in files)
                or not all(type(value) is str for value in namespaces)
                or not all(value in state["sources"] for value in files)):
            return
        modules, packages = cells[2].cell_contents, cells[4].cell_contents
        if type(modules) is not dict or type(packages) is not set:
            return
        initialization_boundary_provider_items(modules)
        path_type = state["staged_path_type"]
        if (type(cells[5].cell_contents) is not path_type
                or not all(type(value) is path_type for value in modules.values())):
            return
        if not all(type(value) is str for value in packages):
            return
        expected_modules, expected_packages = set(), set()
        for filename in files:
            if not filename.endswith(".py"):
                continue
            parts = filename[:-3].split("/")
            if any(part in {"", ".", ".."} for part in parts):
                return
            if parts[-1] == "__init__":
                parts.pop()
                expected_packages.add(".".join(parts))
            expected_modules.add(".".join(parts))
            expected_packages.update(".".join(parts[:index]) for index in range(1, len(parts)))
        if set(modules) != expected_modules or packages != expected_packages:
            return
        context = ((namespace,), (closure, state["sources"]))
        context_snapshot = initialization_boundary_provider_context(context)
        state["anchors"].append(dict(provider=provider, namespace=namespace, methods=("find_spec",),
                                     instance_keys=(), snapshot=snapshot, module=None,
                                     context=context, context_snapshot=context_snapshot,
                                     label="StagedFinder[metadata_nonparticipant]"))
    except (ValueError, KeyError, TypeError):
        pass


def initialization_boundary_provider_recognize(state, provider):
    """Return a diagnostic nonparticipation label or None, never import authority."""
    if state is None:
        return None
    for anchor in state["anchors"]:
        if provider is not anchor["provider"]:
            continue
        try:
            if anchor["module"] is not None and sys.modules.get("six") is not anchor["module"]:
                return None
            if not initialization_boundary_provider_same(
                    initialization_boundary_provider_context(anchor["context"]), anchor["context_snapshot"]):
                return None
            if anchor["module"] is None:
                installer, _, namespace, _ = state["installer"]
                if not initialization_boundary_provider_same(
                        initialization_boundary_provider_function(installer, namespace), state["installer_snapshot"]):
                    return None
            current = initialization_boundary_provider_shape(
                provider, anchor["namespace"], anchor["methods"], anchor["instance_keys"])
            if initialization_boundary_provider_same(current, anchor["snapshot"]):
                return anchor["label"]
        except (ValueError, KeyError, TypeError):
            pass
    return None


def initialization_boundary_provider_snapshot(state, finders):
    """Return ordered nonparticipation labels/None for one observation checkpoint.

    Retain the finder tuple itself and compare identities/order separately. Repeat
    this call at the end of the SAME interval; equality is not certification of
    a later Torch/metadata discovery checkpoint or a complete provider universe.
    """
    return tuple(initialization_boundary_provider_recognize(state, finder) for finder in finders)


def initialization_boundary_inventory(admission, report, budget, append, replace, *, residual=False):
    """Collect S2 physical metadata only, using the frontier's shared budget."""
    boundary = report["boundary"]
    boundary["status"] = "partial"
    boundary["metadata_selection"] = "not_selected_residual_packet" if residual else "legacy_selected"
    cache = {}
    metadata_complete = True
    distributions_complete = True
    p = "/isaac-sim/kit/python/lib/python3.12/site-packages"
    families = {
        "torch", "numpy", "sympy", "mpmath", "gymnasium", "cloudpickle", "filelock",
        "typing-extensions", "setuptools", "networkx", "jinja2", "fsspec", "cuda-bindings",
        "triton", "optree", "opt-einsum", "farama-notifications", "lazy-loader",
        "nvidia-cublas-cu12", "nvidia-cudnn-cu12", "nvidia-cuda-nvrtc-cu12", "nvidia-cuda-runtime-cu12",
        "nvidia-cuda-cupti-cu12", "nvidia-cufft-cu12", "nvidia-curand-cu12", "nvidia-nvjitlink-cu12",
        "nvidia-cusparse-cu12", "nvidia-cusparselt-cu12", "nvidia-cusolver-cu12", "nvidia-nccl-cu12",
        "nvidia-nvshmem-cu12", "nvidia-cufile-cu12", "nvidia-nvtx-cu12",
    }

    def put(container, key, value):
        assert replace(container, key, value), "S2 boundary encoded ceiling"

    def emit(container, value):
        assert time.monotonic() < budget["deadline"], "S2 boundary deadline"
        assert append(container, value), "S2 boundary encoded ceiling"

    def inventory(path):
        if path in cache:
            return cache[path]
        assert len(cache) < 512, "S2 directory count ceiling"
        row = dict(path=path, status="not_completed", witness=None, error_type=None)
        emit(boundary["directories"], row)
        try:
            witness = initialization_directory_inventory(path, budget)
            put(row, "witness", witness)
            row["status"] = "observed"
        except FileNotFoundError:
            row["status"] = "missing"
        except BaseException as error:
            row["status"] = "refused"
            try:
                replace(row, "error_type", type(error).__name__[:128])
            except BaseException:
                pass  # Terminal refusal is retained even when encoding expired.
        cache[path] = row
        return row

    def content(path, item):
        row = dict(path=path, status="pending", witness=None, text=None, error_type=None)
        emit(boundary["metadata"], row)
        if boundary["metadata_files"] >= 32:
            row["status"] = "not_read_metadata_limit"
            return row
        boundary["metadata_files"] += 1
        try:
            assert stat.S_ISREG(item["mode"]) and item["links"] == 1, "S2 metadata link/nonregular"
            # An empty non-Python metadata file is an observed empty stat, not
            # an absent distribution. The shared reader intentionally refuses it.
            if item["size"] == 0:
                put(row, "witness", item)
                row["status"] = "empty_stat_only_unread"
                return row
            witness, raw = initialization_physical_file(path, budget, source=True)
            put(row, "witness", witness)
            put(row, "text", raw.decode("utf-8", errors="strict"))
            row["status"] = "observed"
        except BaseException as error:
            row["status"] = "not_read_refused"
            try:
                replace(row, "error_type", type(error).__name__[:128])
            except BaseException:
                pass
        return row

    def entry_points(row):
        group = None
        seen = set()
        for line in row["text"].splitlines():
            assert time.monotonic() < budget["deadline"], "S2 metadata parse deadline"
            line = line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("[") and line.endswith("]"):
                group = line[1:-1].strip()
                assert group, "S2 invalid entry-point group"
                continue
            name, sep, value = line.partition("=")
            name, value = name.strip(), value.strip()
            assert group and sep and name and value and (group, name) not in seen, "S2 invalid entry point"
            seen.add((group, name))
            emit(boundary["plugins"], dict(metadata_path=row["path"], metadata_sha256=row["witness"]["sha256"],
                                         group=group, name=name, value=value, target_origins=None, target_coverage_complete=False,
                                         effect_review="required_not_admitted"))

    def distribution(row, root):
        fields = []
        for line in row["text"].splitlines():
            assert time.monotonic() < budget["deadline"], "S2 metadata parse deadline"
            if not line:
                break
            if line.startswith((" ", "\t")):
                assert fields, "S2 invalid metadata continuation"
                fields[-1][1] += " " + line.strip()
            else:
                name, sep, value = line.partition(":")
                assert sep, "S2 invalid metadata header"
                fields.append([name.lower(), value.strip()])
        names = [v for k, v in fields if k == "name"]
        versions = [v for k, v in fields if k == "version"]
        assert len(names) == len(versions) == 1, "S2 missing distribution identity"
        emit(boundary["distributions"], dict(name=names[0], version=versions[0], origin=root,
             metadata_path=row["path"], witness=row["witness"], requires_dist=[v for k, v in fields if k == "requires-dist"],
             admission="not_admitted", source_edges="pending_source_review", baseline_full_names=[]))

    paths = list(sys.path)
    finders, path_hooks = tuple(sys.meta_path), tuple(sys.path_hooks)
    provider_snapshot = initialization_boundary_provider_snapshot(admission.provider_state, finders)
    put(boundary, "provider_shapes_stable", False)
    try:
        # These startup stdlib module bindings are already trusted by S2; do
        # not import/resolve providers or read attributes on unknown objects.
        def stdlib_namespace(name):
            module = sys.modules.get(name)
            return object.__getattribute__(module, "__dict__") if type(module) is type(os) else {}

        bootstrap = stdlib_namespace("_frozen_importlib")
        external = stdlib_namespace("_frozen_importlib_external")
        trusted_finders = [(admission, "InitializationAdmission")]
        for namespace, prefix, names in (
            (bootstrap, "_frozen_importlib.", ("BuiltinImporter", "FrozenImporter")),
            (external, "_frozen_importlib_external.", ("PathFinder",)),
        ):
            for name in names:
                candidate = namespace.get(name)
                if type(candidate) is type:
                    trusted_finders.append((candidate, prefix + name))
        file_finder = external.get("FileFinder")
        zip_importer = stdlib_namespace("zipimport").get("zipimporter")

        def canonical_file_hook(hook):
            # A closure has no stable function identity across factory calls.
            # Require the actual trusted factory's nested code, globals and
            # default loader closure; labels/bytecode equality prove nothing.
            function_type = type(lambda: None)
            if type(hook) is not function_type or type(file_finder) is not type:
                return False
            factory = type.__getattribute__(file_finder, "__dict__").get("path_hook")
            if type(factory) is not classmethod or type(factory.__func__) is not function_type:
                return False
            factory = factory.__func__
            if (factory.__globals__ is not external or hook.__globals__ is not external
                    or not any(hook.__code__ is code for code in factory.__code__.co_consts)
                    or hook.__code__.co_freevars != ("cls", "loader_details")
                    or hook.__closure__ is None or len(hook.__closure__) != 2):
                return False
            try:
                cls, loaders = (cell.cell_contents for cell in hook.__closure__)
            except ValueError:  # Empty cells are unsupported, never invoked.
                return False
            if cls is not file_finder or type(loaders) is not tuple or len(loaders) != 3:
                return False
            for pair, loader_name, suffix_name in zip(loaders,
                    ("ExtensionFileLoader", "SourceFileLoader", "SourcelessFileLoader"),
                    ("EXTENSION_SUFFIXES", "SOURCE_SUFFIXES", "BYTECODE_SUFFIXES")):
                if (type(pair) is not tuple or len(pair) != 2
                        or pair[0] is not external.get(loader_name)
                        or (type(pair[1]) is not list and type(pair[1]) is not tuple)):
                    return False
                suffixes = external.get(suffix_name)
                if suffixes is None or (type(suffixes) is not list and type(suffixes) is not tuple):
                    return False
                if (len(pair[1]) != len(suffixes)
                        or not all(type(suffix) is str for suffix in pair[1])
                        or list(pair[1]) != list(suffixes)):
                    return False
            return True

        # Parse only the fixed captured mpmath sources to select named optional
        # backend metadata. This executes no source and asserts no backend choice.
        import ast

        for source in report["files"]:
            if "/mpmath/" not in source["path"] or "source_evidence" not in source:
                continue
            try:
                tree = ast.parse(source["source_evidence"]["text"])
            except (SyntaxError, ValueError):
                distributions_complete = False
                continue
            for node in ast.walk(tree):
                assert time.monotonic() < budget["deadline"], "S2 backend selection deadline"
                names = ([node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else
                         [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                families.update(name.split(".")[0] for name in names if name.split(".")[0] in {"gmpy", "gmpy2", "sage"})
        assert len(paths) <= 128, "S2 actual path count ceiling"
        assert all(type(path) is str and len(path) <= 1024 for path in paths), "S2 unsupported path entry"
        put(boundary, "sys_path", paths)
        for finder, nonparticipant in zip(finders, provider_snapshot):
            name = next((label for candidate, label in trusted_finders if finder is candidate),
                        nonparticipant or "opaque_unsupported")
            supported = name != "opaque_unsupported"
            emit(boundary["finders"], dict(identity=name, object_id=id(finder),
                                          status="accounted" if supported else "unsupported_custom_finder"))
            metadata_complete &= supported
        for hook in path_hooks:
            # Inspect identity only; never call a finder, hook or metadata provider.
            if type(zip_importer) is type and hook is zip_importer:
                name = "zipimport.zipimporter"
            elif canonical_file_hook(hook):
                name = "_frozen_importlib_external.FileFinder.path_hook[canonical_code_globals_closure]"
            else:
                name = "opaque_unsupported"
            supported = name != "opaque_unsupported"
            emit(boundary["path_hooks"], dict(identity=name, object_id=id(hook),
                                             status="accounted" if supported else "unsupported_custom_hook"))
            metadata_complete &= supported
        for index, root in enumerate(paths):
            coverage = dict(path_index=index, path=root, status="pending")
            emit(boundary["path_coverage"], coverage)
            cached = sys.path_importer_cache.get(root)
            if cached is not None:
                supported = type(file_finder) is type and type(cached) is file_finder
                name = "_frozen_importlib_external.FileFinder" if supported else "opaque_unsupported"
                emit(boundary["importer_cache"], dict(path=root, identity=name, supported=supported))
                metadata_complete &= supported
            if residual:
                coverage["status"] = "metadata_not_selected"
                continue
            if not root.startswith("/") or root.lower().endswith((".zip", ".egg")):
                coverage["status"] = "unsupported_archive_or_relative_path"
                metadata_complete = False
                continue
            directory = inventory(root)
            coverage["status"] = directory["status"]
            if directory["status"] == "missing":
                continue
            if directory["status"] != "observed":
                metadata_complete = False
                continue
            for item in directory["witness"]["entries"]:
                name = item["name"]
                # Match provider suffixes case-insensitively, but never alter
                # the physical spelling used for no-follow traversal/evidence.
                stem, _, suffix = name.rpartition(".")
                suffix = suffix.lower()
                if suffix not in {"dist-info", "egg-info", "egg"}:
                    continue
                if suffix == "egg" or not stat.S_ISDIR(item["mode"]):
                    emit(boundary["incomplete_reasons"], dict(path=root + "/" + name, reason="unsupported_egg_or_metadata_form"))
                    metadata_complete = False
                    continue
                metadata_root = root + "/" + name
                metadata_dir = inventory(metadata_root)
                if metadata_dir["status"] != "observed":
                    metadata_complete = False
                    continue
                normalized = re.sub(r"[-_.]+", "-", re.split(r"-(?=[0-9])", stem, maxsplit=1)[0]).lower()
                if normalized in families and not any(leaf["name"] in {"METADATA", "PKG-INFO"}
                                                       for leaf in metadata_dir["witness"]["entries"]):
                    distributions_complete = False
                    emit(boundary["incomplete_reasons"], dict(path=metadata_root, reason="named_distribution_metadata_missing"))
                for leaf in metadata_dir["witness"]["entries"]:
                    is_points = leaf["name"] == "entry_points.txt"
                    is_family = normalized in families and leaf["name"] in {"METADATA", "PKG-INFO"}
                    if not (is_points or is_family):
                        continue
                    row = content(metadata_root + "/" + leaf["name"], leaf)
                    if row["status"] != "observed":
                        if is_points:
                            metadata_complete = False
                        if is_family:
                            distributions_complete = False
                        continue
                    try:
                        if is_points:
                            entry_points(row)
                        else:
                            distribution(row, root)
                    except BaseException as error:
                        row["status"] = "parse_refused"
                        try:
                            replace(row, "error_type", type(error).__name__[:128])
                        except BaseException:
                            pass
                        if is_points:
                            metadata_complete = False
                        else:
                            distributions_complete = False
        for plugin in boundary["plugins"]:
            if plugin["group"] == "torch.backends" or "gymnasium" in plugin["group"].lower():
                module = plugin["value"].partition(":")[0].strip()
                origins, complete = initialization_boundary_origins(module, paths, inventory)
                put(plugin, "target_origins", origins)
                put(plugin, "target_coverage_complete", complete)
        boundary["path_stable"] = list(sys.path) == paths
        metadata_complete &= boundary["path_stable"]
        metadata_complete &= not residual
        boundary["metadata_complete"] = metadata_complete
        boundary["distributions_complete"] = distributions_complete and metadata_complete
        if metadata_complete:
            put(boundary, "torch_backends", [row for row in boundary["plugins"] if row["group"] == "torch.backends"])
            put(boundary, "gymnasium_plugins", [row for row in boundary["plugins"] if "gymnasium" in row["group"].lower()])
        def cheap_context():
            numpy_dir = inventory(p + "/numpy")
            hooks = ([dict(item, path=p + "/numpy/" + item["name"]) for item in numpy_dir["witness"]["entries"]
                      if item["name"] == "_distributor_init_local" or item["name"].startswith("_distributor_init_local.")]
                     if numpy_dir["status"] == "observed" else [])
            put(boundary, "numpy_hook", dict(candidates=hooks,
                status="present_requires_review" if hooks else "absent" if numpy_dir["status"] in {"observed", "missing"} else "unresolved",
                directory_status=numpy_dir["status"], admitted=False))
            if residual:
                # Only a complete no-follow parent listing proves exact absence.
                # A present archive is never opened or treated as empty metadata.
                row = boundary["zip_path"]
                parent = inventory(row["parent_directory"])
                put(row, "parent_status", parent["status"])
                row["status"] = "unresolved"
                if parent["status"] == "observed":
                    entry = next((item for item in parent["witness"]["entries"] if item["name"] == "python312.zip"), None)
                    put(row, "entry", entry)
                    row["status"] = ("absent" if entry is None else
                        "link" if stat.S_ISLNK(entry["mode"]) or stat.S_ISREG(entry["mode"]) and entry["links"] != 1 else
                        "present_regular" if stat.S_ISREG(entry["mode"]) else "unresolved")

        initialization_boundary_native(boundary, budget, paths, inventory, emit, put, fixed_context=cheap_context)
        if residual:
            # Optional physical forms only; never enter distribution directories.
            roots = [p,
                "/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle",
                "/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle"]
            for row in boundary["gmp_backends"]:
                put(row, "roots", roots)
                origins, complete = initialization_boundary_origins(row["module"], roots, inventory)
                put(row, "origins", origins)
                row["physical_coverage_complete"] = complete
                row["status"] = ("unresolved" if not complete else
                                  "present_requires_review" if origins else "absent_at_fixed_roots")
        boundary["status"] = ("observed" if metadata_complete and boundary["distributions_complete"]
                              and boundary["native_complete"] and boundary["numpy_hook"]["status"] != "unresolved" else "partial")
    except BaseException as error:
        boundary["error_type"] = type(error).__name__[:128]
        boundary["metadata_complete"] = False
        boundary["torch_backends"] = None
        boundary["gymnasium_plugins"] = None
    finally:
        boundary["entries"] = budget["entries"]
        final_paths = list(sys.path)
        boundary["path_stable"] = (all(type(path) is str for path in final_paths) and final_paths == paths)
        boundary["finders_stable"] = (len(sys.meta_path) == len(finders)
                                       and all(a is b for a, b in zip(sys.meta_path, finders)))
        boundary["path_hooks_stable"] = (len(sys.path_hooks) == len(path_hooks)
                                          and all(a is b for a, b in zip(sys.path_hooks, path_hooks)))
        boundary["provider_shapes_stable"] = (
            initialization_boundary_provider_snapshot(admission.provider_state, finders) == provider_snapshot)
        if not all(boundary[key] for key in (
                "path_stable", "finders_stable", "path_hooks_stable", "provider_shapes_stable")):
            boundary["metadata_complete"] = boundary["distributions_complete"] = False
            boundary["torch_backends"] = boundary["gymnasium_plugins"] = None
            boundary["status"] = "partial"


def initialization_directory_inventory(path, budget):
    """Stat one caller-selected immutable directory without following entry links.

    The caller owns the fixed inspection selection. This primitive neither reads
    file contents nor grants import/native-load authority; all entries, including
    unselected ones, consume the shared inspection enumeration budget.
    """
    assert type(path) is str and path.startswith("/") and len(path) <= 1024 and "\x00" not in path
    parts = path[1:].split("/")
    assert len(parts) <= 32 and all(p not in {"", ".", ".."} for p in parts)
    limit = budget["entry_limit"]
    assert type(limit) is int and 0 < limit <= 4096
    assert type(budget["entries"]) is int and 0 <= budget["entries"] <= limit
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        assert os.fstatvfs(fd).f_flag & os.ST_RDONLY, "S2 mutable inventory root"
        for part in parts:
            assert time.monotonic() < budget["deadline"], "S2 inventory deadline"
            before = os.stat(part, dir_fd=fd, follow_symlinks=False)
            assert stat.S_ISDIR(before.st_mode), "S2 inventory directory link or non-directory"
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
            info = os.fstat(fd)
            assert (info.st_dev, info.st_ino, info.st_mode) == (before.st_dev, before.st_ino, before.st_mode)
            assert os.fstatvfs(fd).f_flag & os.ST_RDONLY, "S2 mutable inventory directory"
        rows = []
        with os.scandir(fd) as entries:
            for entry in entries:
                assert time.monotonic() < budget["deadline"], "S2 inventory deadline"
                assert budget["entries"] < limit, "S2 inventory entry ceiling"
                budget["entries"] += 1
                assert len(os.fsencode(entry.name)) <= 255
                item = entry.stat(follow_symlinks=False)
                rows.append(dict(name=entry.name, scan_index=len(rows), mode=item.st_mode, size=item.st_size,
                                 device=item.st_dev, inode=item.st_ino, links=item.st_nlink))
        final = os.fstat(fd)
        assert (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns) == (
            final.st_dev, final.st_ino, final.st_mtime_ns, final.st_ctime_ns
        ), "S2 inventory identity changed"
        assert time.monotonic() < budget["deadline"], "S2 inventory deadline"
        return dict(path=path, device=info.st_dev, inode=info.st_ino, mode=info.st_mode,
                    entries=sorted(rows, key=lambda row: row["name"]))
    finally:
        os.close(fd)


def initialization_physical_file(path, budget, *, binary=False, source=False):
    """Hash a selected immutable file through no-follow descriptors, never load it.

    Hashes are measured identities, not preapproved native pins. The caller must
    first admit the exact origin under the fixed image; transitive ELF loads
    remain trusted image behavior. Every read, including reverification, counts.
    """
    assert type(path) is str and path.startswith("/") and len(path) <= 1024 and "\x00" not in path
    parts = path[1:].split("/")
    assert len(parts) <= 32 and all(p not in {"", ".", ".."} for p in parts)
    assert type(binary) is bool and time.monotonic() < budget["deadline"]
    native_limit = budget.get("native_limit", 64)
    byte_limit = budget.get("byte_limit", 8 * 1024**3)
    assert native_limit is None or type(native_limit) is int and native_limit > 0
    assert byte_limit is None or type(byte_limit) is int and byte_limit > 0
    assert not binary or native_limit is None or budget["files"] < native_limit, "S2 native identity count ceiling"
    original, links = path, []
    approved = ("/isaac-sim/", "/workspaces/isaaclab_arena/submodules/")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        assert os.fstatvfs(fd).f_flag & os.ST_RDONLY, "S2 mutable image root"
        while True:
            for index, part in enumerate(parts):
                assert time.monotonic() < budget["deadline"]
                before = os.stat(part, dir_fd=fd, follow_symlinks=False)
                directory = index != len(parts) - 1
                if stat.S_ISLNK(before.st_mode):
                    at = "/" + "/".join(parts[:index + 1])
                    assert at.startswith(approved) and len(links) < 16, "S2 physical link refused"
                    target = os.readlink(part, dir_fd=fd)
                    assert 0 < len(os.fsencode(target)) <= 1024 and "\x00" not in target
                    resolved = os.path.normpath(os.path.join(os.path.dirname(at), target, *parts[index + 1:]))
                    assert resolved.startswith(approved), "S2 physical link escapes approved dependencies"
                    after = os.stat(part, dir_fd=fd, follow_symlinks=False)
                    keys = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
                    assert all(getattr(before, key) == getattr(after, key) for key in keys)
                    links.append(dict(path=at, target=target, resolved=resolved,
                                      device=before.st_dev, inode=before.st_ino))
                    budget["bytes"] += len(os.fsencode(target))
                    assert byte_limit is None or budget["bytes"] <= byte_limit
                    path, parts = resolved, resolved[1:].split("/")
                    assert len(path) <= 1024 and len(parts) <= 32
                    nxt = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    os.close(fd)
                    fd = nxt
                    break
                assert stat.S_ISDIR(before.st_mode) if directory else stat.S_ISREG(before.st_mode)
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if directory:
                    flags |= os.O_DIRECTORY
                nxt = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = nxt
                info = os.fstat(fd)
                assert (info.st_dev, info.st_ino, info.st_mode) == (before.st_dev, before.st_ino, before.st_mode)
                assert os.fstatvfs(fd).f_flag & os.ST_RDONLY, "S2 mutable selected origin"
            else:
                break
        file_limit = budget.get("file_limit", 2 * 1024**3)
        assert file_limit is None or type(file_limit) is int and file_limit > 0
        assert info.st_nlink == 1, "S2 physical hard link refused"
        assert info.st_size >= 0 and (file_limit is None or info.st_size <= file_limit), "S2 physical per-file ceiling"
        # Empty Python initializers/stubs are valid source, not oversized files.
        # Never extend that allowance to a native library or executable witness.
        assert info.st_size or (not binary and path.endswith((".py", ".pyi"))), "S2 empty non-source file"
        assert byte_limit is None or budget["bytes"] + info.st_size <= byte_limit, "S2 physical read ceiling"
        assert type(source) is bool and (not source or info.st_size <= 1024**2)
        chunks = [] if source else None
        digest, count = hashlib.sha256(), 0
        while True:
            assert time.monotonic() < budget["deadline"]
            chunk = os.read(fd, min(65536, info.st_size + 1 - count))
            if not chunk:
                break
            count += len(chunk)
            budget["bytes"] += len(chunk)
            assert count <= info.st_size and (byte_limit is None or budget["bytes"] <= byte_limit)
            digest.update(chunk)
            if source:
                chunks.append(chunk)
        final = os.fstat(fd)
        assert count == info.st_size
        assert (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns, final.st_ctime_ns) == (
            info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
        ), "S2 physical identity changed during read"
        budget["files"] += int(binary)
        row = dict(path=original, physical=path, links=links, size=count, sha256=digest.hexdigest(),
                   device=info.st_dev, inode=info.st_ino, uid=info.st_uid, gid=info.st_gid,
                   mode=stat.S_IMODE(info.st_mode), mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)
        return (row, b"".join(chunks)) if source else row
    finally:
        os.close(fd)


def initialization_executable_binding(budget):
    """Bind the literal invocation to a physical file and the running kernel inode.

    Only the selected terminal python3 alias is admitted. /proc/self/exe is
    explicitly a kernel magic-link observation, never an ordinary path exemption.
    Both physical reads use the existing shared byte/deadline budget.
    """
    assert EXECUTABLE == "/isaac-sim/kit/python/bin/python3"
    assert sys.executable == EXECUTABLE and sys.implementation.name == "cpython"
    assert tuple(sys.version_info[:2]) == (3, 12), "S2 CPython version mismatch"
    target = EXECUTABLE + ".12"

    def nominal():
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            assert os.fstatvfs(fd).f_flag & os.ST_RDONLY, "S2 mutable executable root"
            for part in EXECUTABLE.split("/")[1:-1]:
                assert time.monotonic() < budget["deadline"]
                before = os.stat(part, dir_fd=fd, follow_symlinks=False)
                assert stat.S_ISDIR(before.st_mode), "S2 executable parent must be no-follow directory"
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
                info = os.fstat(fd)
                assert (info.st_dev, info.st_ino, info.st_mode) == (before.st_dev, before.st_ino, before.st_mode)
                assert os.fstatvfs(fd).f_flag & os.ST_RDONLY, "S2 mutable executable parent"
            info = os.stat("python3", dir_fd=fd, follow_symlinks=False)
            metadata = dict(device=info.st_dev, inode=info.st_ino, mode=info.st_mode,
                            size=info.st_size, mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)
            if stat.S_ISREG(info.st_mode):
                return EXECUTABLE, None, metadata
            assert stat.S_ISLNK(info.st_mode), "S2 unknown executable terminal layout"
            link = os.readlink("python3", dir_fd=fd)
            assert link in {"python3.12", target}, "S2 unapproved executable terminal alias target"
            return target, dict(metadata, target=link), metadata
        finally:
            os.close(fd)

    try:
        selected, alias, metadata = nominal()
        physical = initialization_physical_file(selected, budget)
        assert time.monotonic() < budget["deadline"]
        link = os.readlink("/proc/self/exe")
        assert type(link) is str and link == selected, "S2 kernel executable path mismatch or deleted target"
        # This fixed kernel magic link alone is intentionally followed. No bytes
        # are read here; the selected no-follow physical reader owns byte costs.
        fd = os.open("/proc/self/exe", os.O_RDONLY | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            assert os.fstatvfs(fd).f_flag & os.ST_RDONLY, "S2 mutable running executable"
            assert (info.st_dev, info.st_ino) == (physical["device"], physical["inode"]), (
                "S2 kernel executable inode mismatch")
            assert os.readlink("/proc/self/exe") == link, "S2 kernel executable readback changed"
            assert initialization_physical_file(selected, budget) == physical
            assert nominal() == (selected, alias, metadata), "S2 executable alias changed"
            assert time.monotonic() < budget["deadline"]
            kernel = dict(path="/proc/self/exe", target=link, device=info.st_dev, inode=info.st_ino, pid=os.getpid())
        finally:
            os.close(fd)
        return physical, dict(invocation=EXECUTABLE, implementation="cpython", version=[3, 12],
                              alias=alias, kernel=kernel)
    except (AssertionError, OSError) as error:
        raise AssertionError("S2 executable binding unresolved: " + str(error)[:256]) from error


def initialization_cache_manifest(root, deadline):
    """Read a bounded owner-only cache tree without following any path component."""
    assert type(root) is str and root.startswith("/") and "\x00" not in root
    parts = root[1:].split("/")
    assert len(parts) <= 16 and all(p not in {"", ".", ".."} for p in parts)
    assert os.getuid() == os.getgid() == 1000
    rows, total = [], [0]
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            assert time.monotonic() < deadline
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        def visit(parent, relative, depth):
            assert time.monotonic() < deadline and depth <= 16 and len(rows) < 256
            info = os.fstat(parent)
            assert info.st_uid == info.st_gid == 1000
            assert not info.st_mode & 0o022, "S2 cache writable by another principal"
            row = dict(path=relative, device=info.st_dev, inode=info.st_ino,
                       uid=info.st_uid, gid=info.st_gid, mode=stat.S_IMODE(info.st_mode))
            rows.append(row)
            if stat.S_ISDIR(info.st_mode):
                assert depth != 0 or stat.S_IMODE(info.st_mode) == 0o700
                names = []
                with os.scandir(parent) as entries:
                    for item in entries:
                        assert time.monotonic() < deadline and len(names) < 256
                        assert item.name not in {".", ".."} and len(os.fsencode(item.name)) <= 255
                        names.append(item.name)
                for name in sorted(names):
                    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                    try:
                        visit(child, name if relative == "." else relative + "/" + name, depth + 1)
                    finally:
                        os.close(child)
                row["kind"] = "directory"
            else:
                assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                assert 0 <= info.st_size <= 128 * 1024**2
                assert total[0] + info.st_size <= 128 * 1024**2
                digest, count = hashlib.sha256(), 0
                while True:
                    assert time.monotonic() < deadline
                    chunk = os.read(parent, min(65536, info.st_size + 1 - count))
                    if not chunk:
                        break
                    count += len(chunk)
                    total[0] += len(chunk)
                    assert count <= info.st_size and total[0] <= 128 * 1024**2
                    digest.update(chunk)
                final = os.fstat(parent)
                assert (final.st_size, final.st_mtime_ns, final.st_ctime_ns) == (
                    info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                assert count == info.st_size
                row.update(kind="file", size=count, sha256=digest.hexdigest())
        visit(fd, ".", 0)
        return rows
    finally:
        os.close(fd)


INITIALIZATION_SOURCE_LIMIT = 385  # 381 measured repository leaves plus four generated.
INITIALIZATION_INVENTORY = "outputs/workflow/plan04-implementation/s2-initialization/source-files.json"
INITIALIZATION_TEST = "isaaclab_arena/tests/test_environment_workflow_initialization_neo4j.py"
INITIALIZATION_ROLES = ("init-server", "init-generate", "init-refine", "init-assess")


def initialization_verify_sources():
    """Verify the independent S2 capture without broadening any legacy source gate."""
    root = Path("/source")
    assert os.statvfs(root).f_flag & os.ST_RDONLY
    inventory = read_json(root / INITIALIZATION_INVENTORY, SOURCE_MANIFEST_LIMIT)
    manifest = read_json(root / "source-manifest.json", SOURCE_MANIFEST_LIMIT)
    assert INITIALIZATION_SOURCE_LIMIT > 0, "S2 exact source inventory not frozen"
    assert len(manifest) + 1 == INITIALIZATION_SOURCE_LIMIT
    assert set(manifest) == set(inventory) | {"closure.json", "graphql-import-check.py", "graphql-profile.json"}
    total = (root / "source-manifest.json").stat().st_size
    for name, expected in manifest.items():
        assert type(name) is type(expected) is str and re.fullmatch(r"[a-f0-9]{64}", expected)
        assert not name.startswith("/") and all(p not in {"", ".", ".."} for p in name.split("/"))
        path = root
        for part in name.split("/"):
            path /= part
            assert not path.is_symlink()
        assert path.is_file() and os.statvfs(path).f_flag & os.ST_RDONLY
        with path.open("rb") as stream:
            raw = stream.read(8 * 1024**2 + 1)
        total += len(raw)
        assert total <= 8 * 1024**2 and hashlib.sha256(raw).hexdigest() == expected
    return manifest


def initialization_cache_create(case, role):
    """Create only the finite role cache directories; refuse existing role roots."""
    env = initialization_environment(case, role)
    assert all(os.environ.get(k) == v for k, v in env.items())
    fd = os.open("/tmp", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, name in enumerate(("s2-init", case, role)):
            try:
                os.mkdir(name, 0o700, dir_fd=fd)
            except FileExistsError:
                assert index < 2, "S2 role cache already exists"
            nxt = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
            info = os.fstat(fd)
            assert info.st_uid == info.st_gid == 1000 and stat.S_IMODE(info.st_mode) == 0o700
        for name in ("home", "cache", "tmp"):
            os.mkdir(name, 0o700, dir_fd=fd)
        cache = os.open("cache", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            os.mkdir("warp", 0o700, dir_fd=cache)
        finally:
            os.close(cache)
    finally:
        os.close(fd)
    return "/tmp/s2-init/" + case + "/" + role


class InitializationLoader:
    """Gate original immutable loaders before extension create_module can run."""

    def __init__(self, admission, name, original, row):
        self.admission, self.name, self.original, self.row = admission, name, original, row

    def verify(self):
        try:
            observed = initialization_physical_file(self.row["path"], self.admission.budget)
            assert observed == self.row, "S2 loader identity drift"
        except BaseException:
            self.admission.guard.forbidden["runtime"] += 1
            raise

    def create_module(self, spec):
        self.verify()
        return self.original.create_module(spec)

    def exec_module(self, module):
        self.verify()
        original_spec = module.__spec__
        locations = original_spec.submodule_search_locations
        locations = None if locations is None else list(locations)
        # Ordinary module/schema exceptions are not admission violations.
        self.original.exec_module(module)
        try:
            assert module.__file__ == original_spec.origin == self.row["path"]
            reported = module.__spec__
            if reported is not original_spec:
                # OpenUSD's real Tf.PrepareModule copies its extension's spec
                # into the Python package. Both loaders were physically gated.
                assert self.name.startswith("pxr.") and reported.name.startswith(self.name + ".")
                assert reported is sys.modules[reported.name].__spec__
                assert reported.origin in self.admission.libraries
                assert any(row["name"] == reported.name and row["origin"] == reported.origin
                           for row in self.admission.modules)
            else:
                assert reported.submodule_search_locations == locations
            if locations is not None:
                assert list(module.__path__) == locations == [str(Path(self.row["path"]).parent)], (
                    "S2 package path rewrite is not admitted")

        except BaseException:
            self.admission.guard.forbidden["runtime"] += 1
            raise
        self.verify()
        row = dict(self.row, name=self.name, origin=self.row["path"], preloaded=False)
        if reported is not original_spec:
            row.update(extension_spec_name=reported.name, extension_spec_origin=reported.origin)
        self.admission.modules.append(row)


class InitializationPythonAPILoader(InitializationLoader):
    """Execute unchanged physical stdlib source, binding its one bootstrap call."""

    def exec_module(self, module):
        before = self.admission.guard.forbidden["runtime"]
        try:
            return self._exec_module(module)
        except BaseException:
            # Inner physical/audit checks may already have charged this refusal.
            if self.admission.guard.forbidden["runtime"] == before:
                self.admission.guard.forbidden["runtime"] += 1
            raise

    def _exec_module(self, module):
        import ast
        import types

        admission = self.admission
        self.verify()
        assert module is sys.modules[self.name] and module.__spec__._initializing
        assert module.__file__ == module.__spec__.origin == self.row["path"]
        if self.name == "_ctypes":
            assert admission.pythonapi_dlopen is None
            self.original.exec_module(module)
            assert type(module.dlopen) is types.BuiltinFunctionType
            assert module.dlopen.__self__ is module and module.dlopen.__name__ == "dlopen"
            admission.pythonapi_dlopen = module.dlopen
            self.verify()
            return
        assert self.name == "ctypes" and not admission.pythonapi_bootstrap
        assert admission.pythonapi_active is None and "pythonapi" not in module.__dict__
        assert sys.implementation.name == "cpython" and sys.executable == EXECUTABLE
        executable, executable_binding = initialization_executable_binding(admission.budget)
        row, raw = initialization_physical_file(self.row["path"], admission.budget, source=True)
        assert row == self.row
        tree = ast.parse(raw, self.row["path"])
        assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                       and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                       and node.targets[0].id == "pythonapi" and isinstance(node.value, ast.Call)
                       and isinstance(node.value.func, ast.Name) and node.value.func.id == "PyDLL"
                       and len(node.value.args) == 1 and isinstance(node.value.args[0], ast.Constant)
                       and node.value.args[0].value is None and not node.value.keywords]
        assert len(assignments) == 1, "S2 exact stdlib pythonapi assignment missing"
        code = compile(raw, self.row["path"], "exec", dont_inherit=True)
        cdll = next(c for c in code.co_consts if isinstance(c, types.CodeType) and c.co_name == "CDLL")
        init = next(c for c in cdll.co_consts if isinstance(c, types.CodeType) and c.co_name == "__init__")
        admission.pythonapi_active = dict(module=module, code=code, init=init,
                                          line=assignments[0].lineno, source=row, executable=executable,
                                          executable_binding=executable_binding)
        try:
            # Execute all original source, not a rewritten/replacement initializer.
            exec(code, module.__dict__)
            assert len(admission.pythonapi_bootstrap) == 1
            witness = admission.pythonapi_bootstrap[0]
            assert witness["status"] == "admitted"
            assert module is sys.modules.get("ctypes") and module.__spec__._initializing
            assert module.__file__ == module.__spec__.origin == self.row["path"]
            assert module.pythonapi is admission.pythonapi_active["instance"]
            assert type(module.pythonapi) is module.PyDLL and module.pythonapi._name is None
            assert module.pythonapi._handle is not None
            self.verify()
            assert initialization_executable_binding(admission.budget) == (executable, executable_binding)
            witness["status"] = "completed"
        finally:
            # Failed attempts remain admitted, never falsely completed.
            admission.pythonapi_active = None


class InitializationAdmission:
    """Lock selected origins before real loads; unknown package authority refuses."""

    def __init__(self, guard, runner, deadline, *, provider_sources=None):
        from importlib.machinery import PathFinder

        # Trusted post-query checkpoint, before selected application imports.
        # The C/legacy paths do not supply this diagnostic-only context.
        self.provider_state = (initialization_boundary_provider_bootstrap(runner, provider_sources)
                               if provider_sources is not None else None)
        self.guard, self.runner, self.pathfinder = guard, runner, PathFinder
        self.budget: dict = dict(bytes=0, files=0, deadline=deadline)
        if guard.initialization_role == "init-server":
            # Operator-authorized unbounded native/read allocation. JSON null
            # records the policy explicitly; accounting and deadlines remain.
            self.budget.update(native_limit=None, byte_limit=None, file_limit=None)
        elif guard.initialization_case == "positive":
            self.budget.update(native_limit=5, byte_limit=500 * 1024**2)
        self.modules, self.libraries, self.pins, self.cpu_metadata = [], {}, {}, []
        self.namespaces = {}
        self.dependency_frontier, self.dependency_frontier_started = None, False
        self.pythonapi_bootstrap, self.pythonapi_active, self.pythonapi_dlopen = [], None, None
        assert "ctypes" not in sys.modules and "_ctypes" not in sys.modules, "S2 preloaded ctypes bootstrap"
        self.roots = {
            name: DEPENDENCY_ROOTS[0] + "/" + name for name in (
                "warp", "torch", "pxr", "openai", "lazy_loader", "numpy", "sympy", "mpmath", "gymnasium", "torchgen")
        }
        self.roots.update(yaml=E1_YAML_ROOT,
                          toml="/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/toml",
                          isaaclab="/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab",
                          isaaclab_physx="/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab_physx/isaaclab_physx")
        assert not any(name.split(".")[0] in self.roots for name in sys.modules), "S2 preloaded selected package"
        assert runner.GRAPHQL_IMAGE == "sha256:b94e17024f1e123ac5a42759ab56651a18823fda7c701e765cba31f200154cdd"
        assert runner.GRAPHQL_MANIFEST_SHA256 == "03764536ed54c1f59cbf46305c5bc4ba618e2dc1deeeac7ffdfb21a0dffbf810"
        pins = {**DEPENDENCY_RECIPES, **REGISTRATION_PINS, **E1_YAML_PINS,
                REGISTRATION_CONTEXT_EXCEPTION["path"]: "40948811fbc2e99773883f762cc0eb939718b11d26676739e4332b13337d5ee2",
                DEPENDENCY_ROOTS[0] + "/warp/config.py": "9a1ca6a287d599e64286e600dff2c929022fb1d0d836e4f68af31217f547325c"}
        for path, digest in pins.items():
            row = initialization_physical_file(path, self.budget)
            assert row["sha256"] == digest, "S2 immutable image pin changed"
            self.pins[path] = row
        self.baseline = {}
        for name, module in list(sys.modules.items()):
            origin = getattr(getattr(module, "__spec__", None), "origin", None)
            if origin and any(origin.startswith(root + "/") for root in DEPENDENCY_ROOTS[:5]):
                # Only already verified query-probe packages, never new families.
                assert name in runner._GRAPHQL_PROBE["result"]["loaded_modules"], "Unverified preloaded dependency"
                self.baseline[name] = origin
        self.original_check_output = subprocess.check_output
        subprocess.check_output = self.check_output
        sys.meta_path.insert(0, self)
        sys.addaudithook(self.audit)

    def find_spec(self, fullname, path=None, target=None):
        try:
            spec = self._find_spec(fullname, path, target)
        except BaseException as error:
            self.guard.forbidden["blocked_import"] += 1
            if getattr(self, "first_import_denial", None) is None:
                self.first_import_denial = dict(name=fullname[:128], failure_type=type(error).__name__,
                                                reason=str(error)[:1024])
            raise
        if spec is False:
            # A verified-root absence is not a forbidden import. Raise instead
            # of returning None, which would delegate to unverified finders.
            raise ModuleNotFoundError("No module named " + repr(fullname), name=fullname)
        return spec

    def namespace(self, spec):
        """Bind a source-free namespace to no-follow approved directories."""
        assert spec.origin is None and spec.loader is None
        rows = []
        for path in spec.submodule_search_locations:
            assert path.startswith(("/isaac-sim/", "/workspaces/isaaclab_arena/submodules/"))
            assert all(part not in {"", ".", ".."} for part in path.split("/")[1:])
            fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for part in path.split("/")[1:]:
                    assert time.monotonic() <= self.budget["deadline"], "S2 namespace deadline"
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = child
                identity = os.fstat(fd)
                rows.append(dict(path=path, device=identity.st_dev, inode=identity.st_ino))
            finally:
                os.close(fd)
        assert rows
        self.namespaces[spec.name] = rows
        return spec

    def _find_spec(self, fullname, path, target):
        top = fullname.split(".")[0]
        if fullname in {"ctypes", "_ctypes"}:
            from importlib.machinery import ExtensionFileLoader, SourceFileLoader

            assert target is None and fullname not in sys.modules and not self.pythonapi_bootstrap
            stdlib = "/isaac-sim/kit/python/lib/python3.12/"
            selected = stdlib if fullname == "ctypes" else stdlib + "lib-dynload"
            spec = self.pathfinder.find_spec(fullname, [selected])
            assert spec is not None
            if fullname == "ctypes":
                assert spec.origin == stdlib + "ctypes/__init__.py" and type(spec.loader) is SourceFileLoader
            else:
                assert type(spec.loader) is ExtensionFileLoader
                assert str(Path(spec.origin).parent) == selected and Path(spec.origin).name.startswith("_ctypes.")
                assert spec.origin.endswith(".so")
            row = initialization_physical_file(spec.origin, self.budget)
            spec.loader = InitializationPythonAPILoader(self, fullname, spec.loader, row)
            return spec
        if top in {"isaaclab_arena", "isaaclab_arena_examples", "isaaclab_arena_environments", "isaaclab_arena_g1"}:
            return None  # The separately installed exact staged-closure finder owns these.
        if top in self.roots:
            assert target is None and fullname not in sys.modules
            if fullname == top:
                selected = str(Path(self.roots[top]).parent)
            else:
                selected = self.roots[top] + ("/" + "/".join(fullname.split(".")[1:-1]) if "." in fullname[len(top)+1:] else "")
                assert list(path or ()) == [selected], "S2 changed package search path"
            spec = self.pathfinder.find_spec(fullname, [selected])
            if spec is None and fullname != top:
                return False  # Ordinary optional-submodule miss; no fallback.
            if spec is not None and spec.origin is None:
                assert spec.submodule_search_locations is not None
                assert list(spec.submodule_search_locations) == [selected + "/" + fullname.rsplit(".", 1)[-1]]
                return self.namespace(spec)
            assert spec is not None and spec.origin is not None, "S2 fixed package origin missing: " + fullname[:128]
            initialization_origin(fullname, spec.origin, False)
            row = initialization_physical_file(spec.origin, self.budget)
            if spec.origin.endswith(".so"):
                self.library(spec.origin)
            spec.loader = InitializationLoader(self, fullname, spec.loader, row)
            return spec
        spec = self.pathfinder.find_spec(fullname, path)
        if spec is None and path is None and fullname == top:
            spec = self.pathfinder.find_spec(
                fullname, [*DEPENDENCY_ROOTS, DEPENDENCY_ROOTS[0] + "/cmeel.prefix/lib/python3.12/site-packages"]
            )
        if spec is None and path is None and fullname == top and top.startswith("isaaclab_"):
            # Source-installed Isaac Lab extensions are sibling packages, not
            # children of isaaclab's package search path.
            spec = self.pathfinder.find_spec(
                fullname, [f"/workspaces/isaaclab_arena/submodules/IsaacLab/source/{top}"]
            )
        if spec is not None and spec.origin is None:
            return self.namespace(spec)
        if spec is None or spec.origin in {"built-in", "frozen"}:
            return None
        origin = spec.origin
        stdlib = "/isaac-sim/kit/python/lib/python3.12/"
        if origin.startswith(stdlib) and not origin.startswith(stdlib + "site-packages/"):
            return None
        if origin.startswith("/source/"):
            assert origin.removeprefix("/source/") in initialization_verify_sources()
            return None
        # The operator admits standard dependencies throughout the pinned image
        # and submodules. Keep original loaders, immutable physical identities,
        # native quotas and effect guards; do not resume metadata discovery.
        if origin.startswith(("/isaac-sim/", "/workspaces/isaaclab_arena/submodules/")):
            initialization_origin(fullname, origin, False)
            row = initialization_physical_file(origin, self.budget)
            if origin.endswith(".so"):
                self.library(origin)
            spec.loader = InitializationLoader(self, fullname, spec.loader, row)
            return spec
        raise ImportError("Unadmitted S2 package origin: " + fullname[:128] + " at " + origin[:512]) from None

    def library(self, path):
        try:
            assert type(path) is str and path.startswith("/"), "S2 unnamed native load has no physical binding"
            assert path.startswith(("/isaac-sim/", "/workspaces/isaaclab_arena/submodules/")), (
                "S2 unreviewed explicit library origin")
            previous = self.libraries.get(path)
            row = initialization_physical_file(path, self.budget, binary=previous is None)
            assert previous is None or previous == row
            self.libraries[path] = row
            return row
        except BaseException as error:
            # Importers may catch Exception (e.g. Torch's global-deps fallback).
            # Retain the original diagnostic but never a zero-forbidden proof.
            self.guard.forbidden["runtime"] += 1
            if getattr(self, "first_native_denial", None) is None:
                self.first_native_denial = dict(path=path[:512] if type(path) is str else None,
                                                failure_type=type(error).__name__, reason=str(error)[:1024])
            raise

    def audit(self, event, args):
        if event == "ctypes.dlopen":
            if args == (None,):
                self.pythonapi_process_namespace(sys._getframe(1))
            else:
                self.library(args[0])  # Audit fires before dlopen/ELF constructors.

    def pythonapi_process_namespace(self, frame):
        """Consume exactly one genuine partial-module PyDLL(None) admission."""
        try:
            return self._pythonapi_process_namespace(frame)
        except BaseException:
            self.guard.forbidden["runtime"] += 1
            raise

    def _pythonapi_process_namespace(self, frame):
        active = self.pythonapi_active
        assert active is not None and not self.pythonapi_bootstrap, "S2 unnamed native load denied"
        module = active["module"]
        assert self.guard.initialization_controls_ready is True
        assert module is sys.modules.get("ctypes") and module.__spec__._initializing
        assert module.__file__ == module.__spec__.origin == active["source"]["path"]
        assert "pythonapi" not in module.__dict__
        assert frame.f_code is active["init"] and frame.f_globals is module.__dict__
        assert module.CDLL.__init__.__code__ is active["init"]
        assert module.CDLL.__init__.__globals__ is module.__dict__
        assert module.PyDLL.__bases__ == (module.CDLL,) and module.PyDLL.__init__ is module.CDLL.__init__
        values = frame.f_locals
        assert type(values["self"]) is module.PyDLL
        assert values["name"] is values["self"]._name is values["handle"] is None
        assert values["final_name"] is None
        assert values["mode"] == module.DEFAULT_MODE == module.CDLL.__init__.__defaults__[0]
        assert values["use_errno"] is values["use_last_error"] is False and values["winmode"] is None
        assert module.CDLL.__init__.__defaults__[1:] == (None, False, False, None)
        assert self.pythonapi_dlopen is not None
        assert module._dlopen is self.pythonapi_dlopen is sys.modules["_ctypes"].dlopen
        caller = frame.f_back
        assert caller.f_code is active["code"] and caller.f_globals is module.__dict__
        assert caller.f_locals is module.__dict__ and caller.f_lineno == active["line"]
        active["instance"] = values["self"]
        # Consume before the native call. None is not a filesystem library.
        self.pythonapi_bootstrap.append(dict(
            kind="ctypes-pythonapi-process-namespace", argument=None, status="admitted",
            role=self.guard.initialization_role, pid=os.getpid(), source=active["source"],
            executable=active["executable"], executable_binding=active["executable_binding"],
            callsite=dict(module_line=caller.f_lineno,
            init_line=frame.f_lineno, module_code="<module>", init_code="CDLL.__init__")))

    def check_output(self, *args, **kwargs):
        # Keep platform.processor itself unchanged; mediate only its exact real
        # uname command, recording the actual bounded bytes and executable hash.
        if args != (["uname", "-p"],):
            return self.original_check_output(*args, **kwargs)
        import platform

        assert executing("platform", platform._Processor.from_subprocess.__code__)
        assert kwargs == dict(stderr=subprocess.DEVNULL, text=True, encoding="utf8")
        assert not self.cpu_metadata, "S2 CPU metadata role ceiling"
        executable = initialization_physical_file("/usr/bin/uname", self.budget)
        self.cpu_metadata.append(dict(executable=executable, status="started"))
        options = dict(executable="/usr/bin/uname", env={"PATH": "/usr/bin:/bin"}, cwd="/tmp",
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       shell=False, close_fds=True, start_new_session=True, text=False)
        self.guard.local.expected = ("/usr/bin/uname", ["uname", "-p"], "/tmp", options["env"])
        try:
            proc = self.guard.native(["uname", "-p"], **options)
        finally:
            self.guard.local.expected = None
        # collect applies streaming limits; metadata uses a separate stricter cap.
        stdout, stderr = initialization_collect(proc, min(self.budget["deadline"], time.monotonic() + 2), 4096, 4096)
        self.cpu_metadata[0].update(pid=proc.pid, returncode=proc.returncode,
                                    stdout=stdout.decode("utf8"), stderr=stderr.decode("utf8"), status="completed")
        assert proc.returncode == 0
        return stdout.decode("utf8")


def initialization_owned_server(launcher_pid):
    """Retain only the independent S2 launcher-owned server identity."""
    retained = getattr(ACTIVE, "initialization_server_identity", None)
    if retained is not None:
        assert retained["parent_pid"] == launcher_pid
        return retained
    matches = []
    for index, path in enumerate(Path("/evidence").glob("join-launch-*.json")):
        assert index < 11, "S2 launch record ceiling"
        row = read_json(path)
        if row["parent_pid"] == launcher_pid:
            assert role_for(row["bootstrap_argv"][6:]) == "server"
            matches.append(row)
    assert len(matches) <= 1, "S2 ambiguous server ownership"
    if not matches:
        return None
    row = matches[0]
    owned = {key: row[key] for key in ("pid", "parent_pid", "pgid", "sid", "start_ticks", "boot", "pid_namespace")}
    assert all(type(owned[key]) is int and owned[key] > 1 for key in ("pid", "parent_pid", "pgid", "sid"))
    assert owned["pid"] == owned["pgid"] == owned["sid"] and owned["pid"] != launcher_pid
    assert type(owned["start_ticks"]) is int and owned["start_ticks"] > 0
    assert all(type(owned[key]) is str and owned[key] for key in ("boot", "pid_namespace"))
    ACTIVE.initialization_server_identity = owned
    return owned


def initialization_contain_launcher(proc, deadline):
    """Contain both owned groups within one five-second cleanup allowance."""
    guard = ACTIVE
    started = time.monotonic()
    until = getattr(guard, "initialization_cleanup_deadline", None)
    if until is None:
        until = min(deadline + 5, started + 5)
        guard.initialization_cleanup_deadline = until
    cleanup = dict(status="unknown", host_containment_required=True, launcher_pid=proc.pid)
    guard.initialization_server_cleanup = cleanup
    try:
        try:
            owned = initialization_owned_server(proc.pid)
            assert owned is not None, "S2 server identity unknown; exact host containment required"
            cleanup["server_pid"] = owned["pid"]
            if not guard.initialization_group_absent(owned["pid"]):
                live_identity(owned)  # PID/start/PGID/SID/boot/namespace; no numeric-PID fallback.
                os.killpg(owned["pid"], signal.SIGKILL)
        finally:
            if proc.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=max(0, until - time.monotonic()))
        while not guard.initialization_group_absent(owned["pid"]):
            assert time.monotonic() < until, "S2 exact server group reap deadline"
            time.sleep(min(0.02, until - time.monotonic()))
        assert guard.initialization_group_absent(proc.pid), "S2 launcher group remains"
        assert time.monotonic() <= until, "S2 combined group reap deadline"
        cleanup.update(status="contained", host_containment_required=False,
                       group_reap_seconds=time.monotonic() - started)
    except BaseException as error:
        cleanup["failure_type"] = type(error).__name__
        raise


def initialization_collect(proc, deadline, stdout_limit=8 * 1024**2, stderr_limit=65536):
    """Collect under byte/deadline caps, then reap only the owned process group."""
    buffers = {proc.stdout: bytearray(), proc.stderr: bytearray()}
    failure_type = cleanup_failure_type = None
    installed_launcher = (
        getattr(ACTIVE, "initialization_case", None) in {"failure", "timeout"}
        and ACTIVE.role == "harness"
        and any(row["pid"] == proc.pid and row["bootstrap_argv"][6:] == LAUNCH for row in ACTIVE.spawn_records)
    )
    if installed_launcher:
        # One allowance per collection, shared by checkpoint and finally cleanup.
        ACTIVE.initialization_cleanup_deadline = None
    try:
        with selectors.DefaultSelector() as selector:
            for stream in buffers:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                assert remaining > 0, "S2 cold role deadline"
                if installed_launcher:
                    initialization_owned_server(proc.pid)
                initialization_monitor_stall()
                if installed_launcher:
                    cleanup_deadline = ACTIVE.initialization_cleanup_deadline
                    if cleanup_deadline is not None:
                        deadline = min(deadline, cleanup_deadline)
                    # A successful monitor may have spent the containment
                    # allowance; neither open pipes nor EOF may restart it.
                    remaining = deadline - time.monotonic()
                    assert remaining > 0, "S2 cold role deadline"
                for key, _ in selector.select(min(remaining, 0.05)):
                    stream = key.fileobj
                    limit = stdout_limit if stream is proc.stdout else stderr_limit
                    chunk = os.read(stream.fileno(), min(4096, limit + 1 - len(buffers[stream])))
                    if not chunk:
                        selector.unregister(stream)
                    else:
                        buffers[stream].extend(chunk)
                        assert len(buffers[stream]) <= limit, "S2 output ceiling"
            proc.wait(timeout=max(0 if installed_launcher else 0.001, deadline - time.monotonic()))
        return bytes(buffers[proc.stdout]), bytes(buffers[proc.stderr])
    except BaseException as error:
        failure_type = type(error).__name__
        raise
    finally:
        try:
            if installed_launcher:
                initialization_contain_launcher(proc, deadline)
            elif proc.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
        except BaseException as error:
            cleanup_failure_type = type(error).__name__
            raise
        finally:
            for stream in buffers:
                stream.close()
            if failure_type is not None or cleanup_failure_type is not None:
                # Retain original and containment errors separately, even when
                # cleanup replaces the raised exception. One existing leaf,
                # <=11 records, <=16KiB raw prefix per stream stays below 4MiB
                # even with JSON escaping. Truncation is diagnostic, never pass.
                record: dict = dict(pid=proc.pid, failure_type=failure_type,
                                    cleanup_failure_type=cleanup_failure_type)
                for name, stream in (("stdout", proc.stdout), ("stderr", proc.stderr)):
                    raw = bytes(buffers[stream])
                    record[name + "_bytes"] = len(raw)
                    record[name + "_truncated"] = len(raw) > 16384
                    try:
                        screen(raw)  # Screen before truncation, including split sentinels.
                        record[name] = raw[:16384].decode("utf8", "replace")
                    except BaseException as error:
                        record[name] = ""
                        record[name + "_screen_failure"] = type(error).__name__
                records = getattr(ACTIVE, "initialization_collection_errors", [])
                if len(records) < 11:
                    records.append(record)
                ACTIVE.initialization_collection_errors = records


def initialization_maps():
    """Observe actual mappings; do not imply transitive binary attestation."""
    with open("/proc/self/maps", "rb") as stream:
        raw = stream.read()
    lines = raw.decode("utf8").splitlines()
    rows = []
    for line in lines:
        fields = line.split(None, 5)
        assert len(fields) in {5, 6}
        rows.append(dict(address=fields[0], permissions=fields[1], offset=fields[2],
                         device=fields[3], inode=fields[4], path=fields[5] if len(fields) == 6 else None))
    return rows


def initialization_child(role):
    """Run one genuinely cold positive preparation; no database or network manifest."""
    global ACTIVE
    assert role in INITIALIZATION_ROLES and sys.argv[1:] == ["--initialization", "positive", role]
    assert sys.flags.isolated == sys.flags.no_site == sys.flags.ignore_environment == 1
    assert sys.executable == EXECUTABLE and os.getuid() == os.getgid() == 1000
    assert os.getcwd() == "/tmp"
    sys.modules["workflow_graphql_execution_join_harness"] = sys.modules[__name__]
    signal.alarm(240 if role == "init-server" else 40)
    root = initialization_cache_create("positive", role)
    manifest = initialization_verify_sources()
    preimport = initialization_preflight()
    guard = JoinGuards("server" if role == "init-server" else "model")
    guard.initialization_role = role
    guard.initialization_case = "positive"
    ACTIVE = base.ACTIVE = guard
    guard.install()
    runner = load_runner()
    record = dict(**identity(), role=role, status="failed", source_sha256=manifest,
                  preimport=preimport, cache_before=initialization_cache_manifest(root, time.monotonic()+5))
    admission = None
    try:
        record["imports"] = runner.graphql_imports(record["preimport"], guard)
        admission = InitializationAdmission(
            guard, runner, time.monotonic() + (235 if role == "init-server" else 35), provider_sources=manifest
        )
        guard.initialization_admission = admission
        closure = read_json(Path("/source/closure.json"), 65536)
        staged_finder = runner.install_staged_import_guard("/source", closure["files"], closure["namespaces"])
        initialization_boundary_provider_staged(admission.provider_state, staged_finder, closure)
        sys.path[:0] = ["/source/scripts", "/source/web/arena-workbench/tests/e2e/functional-v7"]
        import platform
        processor = platform.processor
        guard.initialization_controls_ready = True
        from workflow_graphql_execution_join_fixture import initialization_preparation
        record.update(initialization_preparation(role))
        assert platform.processor is processor
        warp = sys.modules.get("warp")
        assert warp is not None and warp.config.kernel_cache_dir is not None
        cache = str(warp.config.kernel_cache_dir)
        assert cache.startswith(root + "/cache/warp/") and all(p not in {".", ".."} for p in cache.split("/"))
        assert not warp.is_cuda_available(), "S2 unexpectedly usable GPU"
        record.update(real_preparation_complete=True, cache_verified=True, native_bindings_verified=True,
                      module_origins_verified=True, platform_processor_unmodified=True, usable_gpu=False,
                      cache_after=initialization_cache_manifest(root, admission.budget["deadline"]),
                      native_libraries=list(admission.libraries.values()), module_origins=admission.modules,
                      mapped_libraries=initialization_maps(), cpu_metadata=admission.cpu_metadata,
                      native_trust_residual="fixed-image transitive ELF loading is trusted, not individually hash-attested",
                      status="completed")
        assert record["native_libraries"] and not any(guard.forbidden.values())
        assert any(row["path"] == cache.removeprefix(root + "/") and row["kind"] == "directory"
                   for row in record["cache_after"]), "S2 resolved cache directory not physically present"
        for before in record["cache_before"]:
            after = next(row for row in record["cache_after"] if row["path"] == before["path"])
            assert before["device"] == after["device"] and before["inode"] == after["inode"]
        assert initialization_verify_sources() == manifest
        return 0
    except BaseException as error:
        record["failure_type"] = type(error).__name__
        if isinstance(error, (AssertionError, ImportError)):
            record["bounded_reason"] = str(error)[:1024]
        raise
    finally:
        record.update(forbidden=guard.forbidden, sdk_calls=guard.sdk_calls,
                      owner_constructions=guard.owner_constructions)
        record["subprocess_denials"] = getattr(guard, "initialization_subprocess_denials", [])
        if admission is not None:
            record["physical_read_budget"] = dict(admission.budget)
            record["native_libraries"] = list(admission.libraries.values())
            record["module_origins"] = admission.modules
            record["namespace_origins"] = admission.namespaces
            record["first_native_denial"] = getattr(admission, "first_native_denial", None)
            record["first_import_denial"] = getattr(admission, "first_import_denial", None)
            record["pythonapi_bootstrap"] = admission.pythonapi_bootstrap
            if admission.dependency_frontier is not None:
                # Baseline and existing origins share the bounded diagnostic;
                # do not duplicate unbounded metadata into the 4MiB role leaf.
                record["dependency_frontier"] = admission.dependency_frontier
        write_evidence("initialization-" + role + ".json", record)
        signal.alarm(0)


def initialization_preflight():
    """Observe network-none or isolated-network kernel denial before package imports."""
    import errno

    assert os.getuid() == os.getgid() == 1000 and os.statvfs("/").f_flag & os.ST_RDONLY
    assert not any(n == "pytest" or n.startswith("isaaclab_arena") for n in sys.modules)
    assert not any(n.startswith("nvidia") or n == "dri" for n in os.listdir("/dev"))
    routes = Path("/proc/net/route").read_text()
    assert all(row.split()[1] != "00000000" and row.split()[2] == "00000000" for row in routes.splitlines()[1:])
    denied = {}
    for family, address in ((socket.AF_INET, ("192.0.2.1", 443)), (socket.AF_INET6, ("2001:db8::1", 443))):
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect(address)
            except OSError as error:
                assert error.errno in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EACCES, errno.EPERM}
                denied[str(family)] = error.errno
            else:
                raise AssertionError("S2 kernel external connect unexpectedly succeeded")
    return dict(before_package_imports=True, kernel_denial=denied, routes=routes)


def initialization_finish_role(guard, prepared):
    """Capture real C server preparation before its deliberately failing checkpoint."""
    import platform

    admission = guard.initialization_admission
    role, case = guard.initialization_role, guard.initialization_case
    root = "/tmp/s2-init/" + case + "/" + role
    assert platform.processor is guard.initialization_processor
    warp = sys.modules.get("warp")
    assert warp is not None and not warp.is_cuda_available()
    cache = str(warp.config.kernel_cache_dir)
    assert cache.startswith(root + "/cache/warp/") and all(p not in {".", ".."} for p in cache.split("/"))
    row = dict(**identity(), **prepared, role=role, source_sha256=initialization_verify_sources(),
               preimport=guard.initialization_preimport, real_preparation_complete=True,
               cache_before=guard.initialization_cache_before,
               cache_after=initialization_cache_manifest(root, admission.budget["deadline"]),
               cache_verified=True, native_bindings_verified=True, module_origins_verified=True,
               platform_processor_unmodified=True, usable_gpu=False,
               native_libraries=list(admission.libraries.values()), module_origins=admission.modules,
               mapped_libraries=initialization_maps(), cpu_metadata=admission.cpu_metadata,
               pythonapi_bootstrap=admission.pythonapi_bootstrap,
               forbidden=guard.forbidden, sdk_calls=guard.sdk_calls, owner_constructions=guard.owner_constructions,
               physical_read_budget=dict(admission.budget), status="completed")
    assert row["native_libraries"] and not any(guard.forbidden.values())
    assert any(entry["path"] == cache.removeprefix(root + "/") and entry["kind"] == "directory"
               for entry in row["cache_after"]), "S2 resolved cache directory not physically present"
    for before in row["cache_before"]:
        after = next(entry for entry in row["cache_after"] if entry["path"] == before["path"])
        assert before["device"] == after["device"] and before["inode"] == after["inode"]
    write_evidence("initialization-init-server.json", row)


def initialization_failure_witness(record):
    """Return the original fixed injection's source-bound traceback, never a generic startup error."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(__file__).read_text())
    hook = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == "initialization_pre_readiness")
    raises = [node for node in ast.walk(hook) if isinstance(node, ast.Raise)
              and isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name)
              and node.exc.func.id == "RuntimeError"
              and len(node.exc.args) == 1 and isinstance(node.exc.args[0], ast.Constant)
              and node.exc.args[0].value == "S2 fixed post-initialization pre-readiness failure"]
    assert len(raises) == 1, "S2 fixed failure source changed"
    terminal = dict(file="scripts/workflow_graphql_execution_join_harness.py",
                    function="initialization_pre_readiness", line=raises[0].lineno)
    events = record.get("startup_exception_sites")
    assert type(events) is list and 0 < len(events) <= 24, "Original installed failure missing"
    for event in events:
        assert type(event) is dict and set(event) == {"exception_type", "sites"}
        sites = event["sites"]
        assert type(sites) is list and len(sites) <= 24
        assert all(type(site) is dict and set(site) == {"file", "function", "line"}
                   and type(site["file"]) is type(site["function"]) is str
                   and type(site["line"]) is int and site["line"] > 0 for site in sites)
        if (event["exception_type"] == "RuntimeError" and len(sites) >= 2 and sites[-1] == terminal
                and any(site["file"] == "isaaclab_arena/agentic_environment_generation/workflow/api/installed_execution.py"
                        and site["function"] == "build" for site in sites[:-1])):
            return event
    raise AssertionError("Original fixed initialization failure missing")


def initialization_monitor_stall():
    """Externally contain C1's witnessed failure or C2's five-second supervisor stall."""
    guard = ACTIVE
    case = getattr(guard, "initialization_case", None)
    if case not in {"failure", "timeout"} or guard.role != "harness":
        return
    marker_path = Path("/evidence/initialization-pre-readiness.json")
    if not marker_path.exists() or getattr(guard, "initialization_stall_stop", None) is not None:
        return
    marker = read_json(marker_path)
    assert marker["case"] == case and marker["before_owner_construction"] is True
    elapsed = time.monotonic() - marker["observed_at"]
    original = None
    if case == "timeout":
        if elapsed < 5:
            return
    else:
        started_path = Path(f"/evidence/join-process-{marker['pid']}-started.json")
        if not started_path.exists():
            return
        record = read_json(started_path)
        for key in ("pid", "parent_pid", "pgid", "sid", "start_ticks", "boot", "pid_namespace"):
            assert type(record[key]) is type(marker[key]) and record[key] == marker[key], "S2 original failure identity differs"
        if not record.get("startup_exception_sites"):
            return
        original = initialization_failure_witness(record)
    assert marker["pid"] == marker["pgid"] == marker["sid"]
    launchers = [row for row in guard.spawn_records if row["bootstrap_argv"][6:] == LAUNCH]
    assert len(launchers) == 1
    spawned = read_json(Path(f"/evidence/join-launch-{marker['pid']}.json"))
    assert spawned["parent_pid"] == launchers[0]["pid"] == marker["parent_pid"]
    assert role_for(spawned["bootstrap_argv"][6:]) == "server"
    owned = getattr(guard, "initialization_server_identity", None)
    keys = {"pid", "parent_pid", "pgid", "sid", "start_ticks", "boot", "pid_namespace"}
    assert type(owned) is dict and set(owned) == keys, "S2 independent server identity missing"
    for key in keys:
        assert type(owned[key]) is type(spawned[key]) is type(marker[key]), "S2 server identity type differs"
        assert owned[key] == spawned[key] == marker[key], "S2 independent server identity differs"
    live_identity(owned)
    started = time.monotonic()
    until = getattr(guard, "initialization_cleanup_deadline", None)
    if until is None:
        until = started + 5
        guard.initialization_cleanup_deadline = until
    os.killpg(owned["pid"], signal.SIGKILL)
    from workflow_graphql_execution_join_fixture import initialization_group_absent
    while not initialization_group_absent(owned["pid"]):
        assert time.monotonic() < until, "S2 exact server group reap deadline"
        time.sleep(min(0.02, until - time.monotonic()))
    guard.initialization_stall_stop = dict(server_pid=owned["pid"], signal=signal.SIGKILL,
                                           observed_stall_seconds=started - marker["observed_at"], stall_seconds=5,
                                           group_reap_seconds=time.monotonic() - started)
    if case == "failure":
        guard.initialization_stall_stop.pop("stall_seconds")
        guard.initialization_stall_stop["original_failure"] = original
    write_evidence("initialization-stall-stop.json", guard.initialization_stall_stop)


def initialization_fresh(role):
    """Launch only the next selected preparation role in a fresh interpreter."""
    guard = ACTIVE
    assert type(guard) is JoinGuards and guard.role == "harness"
    assert guard.initialization_case in {"positive", "init-server"}
    roles = ("init-server",) if guard.initialization_case == "init-server" else INITIALIZATION_ROLES
    assert len(guard.spawn_records) < len(roles) and role == roles[len(guard.spawn_records)]
    # Reuse the cold positive preparation protocol. Init-server may use the
    # aggregate work allowance; the host deadline and exact cleanup still apply.
    arguments = [EXECUTABLE, "-I", "-S", "-B", "/source/" + SELF, "--initialization", "positive", role]
    kwargs = process_kwargs(env=initialization_environment("positive", role))
    guard.permit = (arguments, kwargs)
    try:
        proc = subprocess.Popen(arguments, **kwargs)
        stdout, stderr = initialization_collect(proc, min(guard.deadline, time.monotonic() + (240 if role == "init-server" else 40)))
        screen(stdout + stderr)
        write_evidence("initialization-" + role + "-output.json", dict(pid=proc.pid, returncode=proc.returncode,
                       stdout=stdout.decode("utf8", "replace"), stderr=stderr.decode("utf8", "replace")))
        assert proc.returncode == 0, "S2 cold preparation failed: " + role
        row = read_json(Path("/evidence/initialization-" + role + ".json"))
        assert row["pid"] == proc.pid and row["parent_pid"] == os.getpid() and row["status"] == "completed"
        from workflow_graphql_execution_join_fixture import initialization_group_absent
        assert initialization_group_absent(proc.pid), "S2 cold role group remains"
        return row
    finally:
        guard.permit = None


def initialization_installed_case(case):
    """Exercise the actual installed setup/admin/launcher and bounded stop/status path."""
    from workflow_graphql_execution_join_fixture import configuration, registrations, initialization_group_absent

    assert case in {"failure", "timeout"} and ACTIVE.initialization_case == case
    ACTIVE.initialization_group_absent = initialization_group_absent
    records, launched = [], False
    def invoke(arguments, private_fd=None):
        result = fresh(arguments, private_fd=private_fd)
        screen(result.stdout + result.stderr)
        row = dict(argv=arguments, pid=result.pid, returncode=result.returncode,
                   stdout=result.stdout.decode("utf8", "replace"), stderr=result.stderr.decode("utf8", "replace"))
        write_evidence("initialization-cli-" + str(len(records)) + ".json", row)
        records.append(row)
        return result
    try:
        profiles = registrations()
        for kind, config in zip(("query", "execution"), CONFIGS, strict=True):
            configuration(kind, profiles if kind == "execution" else (),
                          home=initialization_environment(case, "init-server")["HOME"])
            payload = json.dumps(dict(schema_version=1, databases=dict(operational=dict(
                scheme="basic", username="synthetic-user", password="synthetic-only-secret")))).encode()
            read_fd, write_fd = os.pipe()
            try:
                os.fchmod(read_fd, 0o600)
                assert os.write(write_fd, payload) == len(payload)
            finally:
                os.close(write_fd)
            try:
                result = invoke(["setup", "--config", config, "--create", "--credentials-fd", str(read_fd)], read_fd)
            finally:
                os.close(read_fd)
            assert result.returncode == 0 and json.loads(result.stdout)["code"] == "setup_complete"
        for args in ADMIN:
            result = invoke(args)
            assert result.returncode == 0 and json.loads(result.stdout)["code"] == "admin_complete"
        launched = True
        result = invoke(LAUNCH)
        receipt = json.loads(result.stdout)
        assert type(result.returncode) is int and result.returncode == 3
        assert receipt.get("state") in {"launching", "stopping"} and receipt.get("code") == "exited_unclean"
        assert not receipt.get("capabilities", {})
        checkpoint = read_json(Path("/evidence/initialization-pre-readiness.json"))
        assert checkpoint["case"] == case and checkpoint["pid"] == server_pid()
        row = read_json(Path("/evidence/initialization-init-server.json"))
        assert row["catalogue_sha256"] == checkpoint["catalogue_sha256"]
    finally:
        if launched:
            cleanup = getattr(ACTIVE, "initialization_server_cleanup", None)
            assert cleanup is not None and cleanup["status"] == "contained", (
                "S2 server cleanup unknown; stop launches and request exact host containment"
            )
            for status in (invoke(STOP), invoke(STATUS)):
                state = json.loads(status.stdout)
                assert type(status.returncode) is int and status.returncode == 3
                assert state.get("state") in {"launching", "stopping"} and state.get("code") == "exited_unclean"
                assert not state.get("capabilities", {})
            assert initialization_group_absent(server_pid()), "S2 installed server remains"
    witness = dict(checkpoint, readiness_absent=True, server_pid=row["pid"], original_failure_retained=True)
    witness.update(ACTIVE.initialization_stall_stop)
    if case == "failure":
        started = read_json(Path(f"/evidence/join-process-{row['pid']}-started.json"))
        assert witness["original_failure"] == initialization_failure_witness(started)
    ACTIVE.initialization_result = dict(initialization_roles=[row], pre_readiness_failure=witness)


def initialization_evidence_names(case, proof=None):
    """Return finite S2 archive leaves; PID leaves require bounded producer identities."""
    assert case in {"init-server", "positive", "failure", "timeout"}
    names = {"client-proof.json", "pytest.xml", "collection-ready", "initialization-harness.json"}
    roles = INITIALIZATION_ROLES if case == "positive" else ("init-server",)
    names.update("initialization-" + role + ".json" for role in roles)
    if case in {"positive", "init-server"}:
        names.update("initialization-" + role + "-output.json" for role in roles)
    else:
        names.update({"initialization-pre-readiness.json", "initialization-stall-stop.json"})
        names.update("initialization-cli-" + str(index) + ".json" for index in range(10))
    if proof is not None:
        pids = proof.get("process_pids", [])
        assert type(pids) is list and len(pids) <= (1 if case == "init-server" else 4 if case == "positive" else 11)
        assert len(set(pids)) == len(pids) and all(type(pid) is int and 1 < pid < 2**31 for pid in pids)
        for pid in pids:
            names.add(f"join-launch-{pid}.json")
            if case != "init-server":
                names.update({f"join-process-{pid}.json", f"join-process-{pid}-started.json"})
            if case == "positive":
                names.add(f"generation-child-{pid}-sdk.json")
    assert len(names) <= 55
    return names


def initialization_required_evidence(case, proof):
    """Select mandatory emitted leaves, separately from the diagnostic allowlist."""
    allowed = initialization_evidence_names(case, proof)
    pids = proof["process_pids"]
    rows = proof["initialization_roles"]
    assert len(pids) == (1 if case == "init-server" else 4 if case == "positive" else 11)
    names = {"client-proof.json", "pytest.xml", "collection-ready", "initialization-harness.json"}
    roles = INITIALIZATION_ROLES if case == "positive" else ("init-server",)
    assert [row["role"] for row in rows] == list(roles)
    names.update("initialization-" + role + ".json" for role in roles)
    names.update(f"join-launch-{pid}.json" for pid in pids)
    if case in {"positive", "init-server"}:
        assert pids == [row["pid"] for row in rows]
        names.update("initialization-" + role + "-output.json" for role in roles)
        # Cold initialization_child bypasses child(): no join-process witnesses.
        # Only the three model preparations install the SDK fixture.
        names.update(f"generation-child-{row['pid']}-sdk.json" for row in rows[1:])
    else:
        assert rows[0]["pid"] == pids[-1] and rows[0]["pid"] not in pids[:-1]
        names.update("initialization-cli-" + str(index) + ".json" for index in range(10))
        names.update(f"join-process-{pid}.json" for pid in pids[:-1])
        names.update({"initialization-pre-readiness.json", f"join-process-{pids[-1]}-started.json"})
        # Both C cases are externally contained. SIGKILL cannot emit finally;
        # C1 retains its exact original exception in the started witness.
        names.add("initialization-stall-stop.json")
    assert names <= allowed and len(names) <= 55
    return names


def initialization_verify_evidence(files, case):
    """Verify actual archive bytes against their single captured client proof."""
    import json

    proof = json.loads(files["client-proof.json"])
    assert initialization_required_evidence(case, proof) <= set(files), "S2 mandatory evidence missing"
    assert set(files) <= initialization_evidence_names(case, proof), "S2 unexpected evidence"
    assert initialization_verify_proof(proof, files["pytest.xml"], case) is True
    assert files["collection-ready"] == (case + "\n").encode()
    assert "initialization-error.json" not in files

    def read(name):
        value = json.loads(files[name])
        assert type(value) is dict
        return value

    def same(left, right):
        # bool is not an integer identity, including in nested witness records.
        assert json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True), "S2 evidence disagreement"

    def zero_effects(row):
        same(row["forbidden"], proof["forbidden"])
        for key in ("sdk_calls", "owner_constructions"):
            assert type(row[key]) is int and row[key] == 0

    harness = read("initialization-harness.json")
    assert harness.get("collection_errors", []) == [], "S2 collection diagnostics cannot certify success"
    same(harness["forbidden"], proof["forbidden"])
    spawns = harness["spawn_records"]
    assert type(spawns) is list
    same([row["pid"] for row in spawns], proof["process_pids"] if case in {"positive", "init-server"} else proof["process_pids"][:-1])
    prefix = ["/isaac-sim/kit/python/bin/python3", "-I", "-S", "-B",
              "/source/scripts/workflow_graphql_execution_join_harness.py"]
    rows = proof["initialization_roles"]
    for row in rows:
        same(read("initialization-" + row["role"] + ".json"), row)
        assert row["status"] == "completed"
        zero_effects(row)
    if case in {"positive", "init-server"}:
        same(harness["used"], [])
        assert len({row["parent_pid"] for row in rows}) == 1
        for row, spawn in zip(rows, spawns, strict=True):
            pid = row["pid"]
            same(spawn, dict(pid=pid, bootstrap_argv=prefix + ["--initialization", "positive", row["role"]],
                             production_argv=None))
            same(read(f"join-launch-{pid}.json"), dict(spawn, parent_pid=row["parent_pid"]))
            output = read("initialization-" + row["role"] + "-output.json")
            assert type(output["pid"]) is int and output["pid"] == pid
            assert type(output["returncode"]) is int and output["returncode"] == 0
            assert type(output["stdout"]) is type(output["stderr"]) is str
            if row["role"] != "init-server":
                sdk = read(f"generation-child-{pid}-sdk.json")
                assert type(sdk["pid"]) is int and sdk["pid"] == pid
                assert type(sdk["calls"]) is int and sdk["calls"] == 0 and sdk["responses"] == []
    else:
        module = "isaaclab_arena.agentic_environment_generation.workflow.cli"
        identity_fields = ("pid", "parent_pid", "pgid", "sid", "start_ticks", "boot", "pid_namespace")
        server = rows[0]
        server_pid = server["pid"]
        cleanup = proof["initialization_server_cleanup"]
        assert cleanup["launcher_pid"] == spawns[7]["pid"] == server["parent_pid"]
        server_launch = read(f"join-launch-{server_pid}.json")
        same({key: server_launch[key] for key in identity_fields}, {key: server[key] for key in identity_fields})
        argv = server_launch["bootstrap_argv"]
        assert argv[:6] == prefix + ["--cli"] and argv[6] == "api-serve"
        same(server_launch["production_argv"], [prefix[0], "-m", module] + argv[6:])
        processes = []
        for index, spawn in enumerate(spawns):
            pid = spawn["pid"]
            process = read(f"join-process-{pid}.json")
            output = read(f"initialization-cli-{index}.json")
            same(read(f"join-launch-{pid}.json"), dict(spawn, parent_pid=process["parent_pid"]))
            same(spawn["bootstrap_argv"], prefix + ["--cli"] + output["argv"])
            assert spawn["production_argv"] is None
            same(process["bootstrap_argv"], spawn["bootstrap_argv"])
            same(process["argv"], [module] + output["argv"])
            same(process["source_sha256"], proof["source_sha256"])
            assert type(process["pid"]) is int and process["pid"] == pid == output["pid"]
            assert process["pgid"] == process["sid"] == pid and type(process["start_ticks"]) is int
            assert process["start_ticks"] > 0
            same(process["boot"], server["boot"])
            same(process["pid_namespace"], server["pid_namespace"])
            expected_role = (["setup"] * 2 + ["admin"] * 5 + ["launcher", "client", "client"])[index]
            assert process["role"] == expected_role and process["status"] == "completed"
            assert output["argv"][0] == (["setup"] * 2 + ["admin"] * 5 + ["api-launch", "api-stop", "api-status"])[index]
            assert type(output["returncode"]) is int and type(process["returncode"]) is int
            same(output["returncode"], process["returncode"])
            if index < 7:
                assert output["returncode"] == 0
                result = json.loads(output["stdout"])
                assert result["code"] == ("setup_complete" if index < 2 else "admin_complete")
            else:
                result = json.loads(output["stdout"])
                assert output["returncode"] == 3
                assert result.get("state") in {"launching", "stopping"} and result.get("code") == "exited_unclean"
                assert not result.get("capabilities", {})
            assert type(output["stdout"]) is type(output["stderr"]) is str
            zero_effects(process)
            same(process["spawn_records"], [server_launch] if index == 7 else [])
            processes.append(process)
        assert len({row["parent_pid"] for row in processes}) == 1
        same(harness["used"], [read(f"initialization-cli-{i}.json")["argv"] for i in range(10)])
        for name in [f"join-process-{server_pid}-started.json"]:
            process = read(name)
            same({key: process[key] for key in identity_fields}, {key: server[key] for key in identity_fields})
            same(process["source_sha256"], proof["source_sha256"])
            assert process["role"] == "server"
            same(process["bootstrap_argv"], argv)
            same(process["argv"], [module] + argv[6:])
        marker = read("initialization-pre-readiness.json")
        same({key: marker[key] for key in identity_fields}, {key: server[key] for key in identity_fields})
        witness = dict(marker, readiness_absent=True, server_pid=server_pid, original_failure_retained=True)
        stop = read("initialization-stall-stop.json")
        assert type(stop["server_pid"]) is int and stop["server_pid"] == server_pid
        assert type(stop["signal"]) is int and stop["signal"] == 9
        assert type(stop["group_reap_seconds"]) in {int, float} and 0 <= stop["group_reap_seconds"] <= 5
        assert type(stop["observed_stall_seconds"]) in {int, float} and 0 <= stop["observed_stall_seconds"] < 40
        witness.update(stop)
        if case == "timeout":
            # The external collector polls at most every 50ms. A late kill is
            # containment, not proof of the approved five-second supervisor.
            assert 5 <= stop["observed_stall_seconds"] <= 5.05
            assert type(stop["stall_seconds"]) is int and stop["stall_seconds"] == 5
        else:
            # Keep this check within the exporter's fixed five-function AST
            # closure. The live monitor binds the original to staged source;
            # readback joins its exact event with the hook's actual raise site.
            original = stop["original_failure"]
            assert type(original) is dict and set(original) == {"exception_type", "sites"}
            assert original["exception_type"] == "RuntimeError"
            sites = original["sites"]
            assert type(sites) is list and 2 <= len(sites) <= 24
            assert all(type(site) is dict and set(site) == {"file", "function", "line"}
                       and type(site["file"]) is type(site["function"]) is str
                       and type(site["line"]) is int and site["line"] > 0 for site in sites)
            fault = marker["failure_site"]
            assert type(fault) is dict and set(fault) == {"file", "function", "line"}
            assert fault["file"] == "scripts/workflow_graphql_execution_join_harness.py"
            assert fault["function"] == "initialization_pre_readiness"
            assert type(fault["line"]) is int and fault["line"] > 0
            same(sites[-1], fault)
            assert any(site["file"] == "isaaclab_arena/agentic_environment_generation/workflow/api/installed_execution.py"
                       and site["function"] == "build" for site in sites[:-1])
            events = read(f"join-process-{server_pid}-started.json")["startup_exception_sites"]
            assert type(events) is list and 0 < len(events) <= 24
            assert original in events
        same(witness, proof["pre_readiness_failure"])
    return proof


def initialization_wait_database(uri, deadline):
    """Wait only for C's disposable Bolt endpoint within the existing attempt clock."""
    import neo4j

    deadline = min(deadline, time.monotonic() + 45)
    while True:
        remaining = deadline - time.monotonic()
        assert remaining > 0, "S2 database readiness deadline"
        try:
            with neo4j.GraphDatabase.driver(
                uri, auth=None, connection_timeout=min(2, remaining),
                connection_acquisition_timeout=min(3, remaining), max_transaction_retry_time=0,
            ) as driver:
                driver.verify_connectivity()
            assert time.monotonic() < deadline, "S2 database readiness deadline"
            return
        except (neo4j.exceptions.ServiceUnavailable, neo4j.exceptions.SessionExpired):
            remaining = deadline - time.monotonic()
            assert remaining > 0, "S2 database readiness deadline"
            time.sleep(min(1, remaining))


def initialization_inside(case):
    """Run one fixed real pytest case, retain actual failures, return for live collection."""
    global ACTIVE
    import xml.etree.ElementTree as ET

    assert type(case) is str and case in {"init-server", "positive", "failure", "timeout"}
    installed_case = case in {"failure", "timeout"}
    proof = dict(status="failed", mode="workflow-graphql-initialization", case=case, tests=0,
                 execution_attempted=False, source_sha256={}, initialization_roles=[], process_pids=[],
                 children_verified=False, missing_process_witnesses=[], release_blockers=[])
    if case == "init-server":
        proof.update(scope="init-server preparation only", all_roles_complete=False)
    guard = None
    try:
        preimport = initialization_preflight()
        manifest = initialization_verify_sources()
        network = read_json(Path("/network/manifest.json"), 65536) if installed_case else None
        if network is not None:
            assert set(network) == {"container_id", "network_id", "ip", "port"}
            assert type(network["port"]) is int and network["port"] == 7687
            os.environ["ARENA_WORKFLOW_NEO4J_URI"] = "bolt://" + network["ip"] + ":7687"
            os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"] = "workflowtest"
        guard = JoinGuards("harness", None if network is None else network["ip"])
        guard.initialization_case = case
        guard.deadline = time.monotonic() + 260  # Host owns the earlier aggregate 300s start.
        guard.initialization_result = {}
        ACTIVE = base.ACTIVE = guard
        guard.install()
        runner = load_runner()
        runner.graphql_imports(preimport, guard)
        closure = read_json(Path("/source/closure.json"), 65536)
        runner.install_staged_import_guard("/source", closure["files"], closure["namespaces"])
        if network is not None:
            initialization_wait_database(os.environ["ARENA_WORKFLOW_NEO4J_URI"], guard.deadline)
        sys.path.insert(0, "/source/scripts")
        os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        import pytest
        proof.update(execution_attempted=True, source_sha256=manifest)
        code = pytest.main(["/source/" + INITIALIZATION_TEST + "::test_initialization_" + case.replace("-", "_"),
                            "-q", "-p", "no:cacheprovider", "--confcutdir=/source/isaaclab_arena/tests",
                            "--noconftest", "--junitxml=/evidence/pytest.xml"])
        with open("/evidence/pytest.xml", "rb") as stream:
            junit = stream.read(4 * 1024**2 + 1)
        assert len(junit) <= 4 * 1024**2
        proof.update(tests=len(list(ET.fromstring(junit).iter("testcase"))), junit_sha256=hashlib.sha256(junit).hexdigest())
        assert code == 0 and guard.initialization_result, "Actual S2 pytest case failed"
        proof.update(guard.initialization_result)
        if installed_case:
            proof["initialization_server_cleanup"] = guard.initialization_server_cleanup
            proof["host_containment_required"] = guard.initialization_server_cleanup["host_containment_required"]
        from workflow_graphql_execution_join_fixture import initialization_group_absent
        pids = [row["pid"] for row in guard.spawn_records]
        if installed_case:
            pids.append(server_pid())
        assert all(initialization_group_absent(pid) for pid in pids)
        rows = proof["initialization_roles"]
        assert len(guard.spawn_records) == (1 if case == "init-server" else 4 if case == "positive" else 10)
        if installed_case:
            for launched in guard.spawn_records:
                child_record = read_json(Path(f"/evidence/join-process-{launched['pid']}.json"))
                assert child_record["source_sha256"] == manifest
                assert child_record["parent_pid"] == os.getpid()
                assert not any(child_record["forbidden"].values())
                assert child_record["owner_constructions"] == child_record["sdk_calls"] == 0
        assert all(not any(row["forbidden"].values()) and row["sdk_calls"] == row["owner_constructions"] == 0 for row in rows)
        if all(row["physical_read_budget"].get("byte_limit", 8 * 1024**3) is not None for row in rows):
            assert sum(row["physical_read_budget"]["bytes"] for row in rows) <= 8 * 1024**3
        if all(row["physical_read_budget"].get("native_limit", 64) is not None for row in rows):
            assert sum(row["physical_read_budget"]["files"] for row in rows) <= 64
        proof.update(status="passed", process_pids=pids, image=runner.GRAPHQL_IMAGE,
                     provision_manifest_sha256=runner.GRAPHQL_MANIFEST_SHA256, children_verified=True,
                     owned_groups_absent=True, sdk_calls=0, provider_constructions=0,
                     readiness_observed=False, owner_admitted=False, forbidden=guard.forbidden)
        assert initialization_verify_sources() == manifest
        initialization_verify_proof(proof, junit, case)
    except BaseException as error:
        proof.update(status="failed", failure_type=type(error).__name__)
        proof["release_blockers"].append(str(error)[:1024])
    finally:
        if guard is not None:
            proof["process_pids"] = [row["pid"] for row in guard.spawn_records]
            if installed_case and LAUNCH in guard.used:
                cleanup = getattr(guard, "initialization_server_cleanup", None)
                proof["initialization_server_cleanup"] = cleanup or dict(
                    status="unknown", host_containment_required=True)
                proof["host_containment_required"] = proof["initialization_server_cleanup"]["host_containment_required"]
                if proof["host_containment_required"]:
                    proof.update(status="failed", children_verified=False, owned_groups_absent=False)
                    proof["release_blockers"].append("S2 server cleanup unknown; exact host containment required")
                owned = getattr(guard, "initialization_server_identity", None)
                if owned is not None:
                    proof["process_pids"].append(owned["pid"])
                else:
                    with contextlib.suppress(Exception):
                        proof["process_pids"].append(server_pid())
            write_evidence("initialization-harness.json", dict(forbidden=guard.forbidden, used=guard.used,
                           spawn_records=guard.spawn_records,
                           collection_errors=getattr(guard, "initialization_collection_errors", [])))
        write_evidence("client-proof.json", proof)
    return proof


def initialization_verify_proof(proof, junit, case):
    """Fail closed on incomplete S2 evidence; raw JUnit bytes are mandatory.

    This is a readback contract, not admission and not a substitute for the
    runner's archive/source/image and exact-owned container cleanup checks.
    """
    import hashlib
    import re
    import xml.etree.ElementTree as ET

    assert type(case) is str and case in {"init-server", "positive", "failure", "timeout"}
    assert type(proof) is dict and type(junit) is bytes and 0 < len(junit) <= 4 * 1024 * 1024
    assert proof["mode"] == "workflow-graphql-initialization" and proof["case"] == case
    assert proof["status"] == "passed" and type(proof["tests"]) is int and proof["tests"] == 1
    assert proof["junit_sha256"] == hashlib.sha256(junit).hexdigest()
    assert proof["image"] == "sha256:b94e17024f1e123ac5a42759ab56651a18823fda7c701e765cba31f200154cdd"
    assert proof["provision_manifest_sha256"] == "03764536ed54c1f59cbf46305c5bc4ba618e2dc1deeeac7ffdfb21a0dffbf810"
    assert proof["source_sha256"] and all(
        type(k) is type(v) is str and re.fullmatch(r"[a-f0-9]{64}", v)
        and not k.startswith("/") and all(p not in {"", ".", ".."} for p in k.split("/"))
        for k, v in proof["source_sha256"].items()
    )
    assert b"<!DOCTYPE" not in junit and b"<!ENTITY" not in junit
    tree = ET.fromstring(junit)
    tests = list(tree.iter("testcase"))
    assert len(tests) == 1 and tests[0].get("name") == "test_initialization_" + case.replace("-", "_")
    assert not any(list(tree.iter(tag)) for tag in ("failure", "error", "skipped"))
    assert proof["release_blockers"] == [] and proof["missing_process_witnesses"] == []
    assert proof["children_verified"] is True and proof["owned_groups_absent"] is True
    assert type(proof["sdk_calls"]) is int and proof["sdk_calls"] == 0
    assert type(proof["provider_constructions"]) is int and proof["provider_constructions"] == 0
    assert proof["readiness_observed"] is False and proof["owner_admitted"] is False
    assert type(proof["forbidden"]) is dict and set(proof["forbidden"]) == {
        "network", "subprocess", "provider", "runtime", "graph", "legacy", "blocked_import",
    }
    assert all(type(v) is int and v == 0 for v in proof["forbidden"].values())

    def physical_witness(value, source=False):
        # Same fields as physical_file, with S2's no-follow requirement. This
        # checks retained structure only; it does not read or admit native bytes.
        assert type(value) is dict
        for key in ("path", "physical"):
            path = value[key]
            assert type(path) is str and path.startswith("/") and "\x00" not in path
            assert all(part not in {"", ".", ".."} for part in path.split("/")[1:])
        import posixpath

        current = value["path"]
        links = value["links"]
        assert type(links) is list and len(links) <= 16
        approved = ("/isaac-sim/", "/workspaces/isaaclab_arena/submodules/")
        for link in links:
            assert type(link) is dict and set(link) == {"path", "target", "resolved", "device", "inode"}
            assert type(link["path"]) is type(link["resolved"]) is str
            assert link["path"].startswith(approved) and (current == link["path"] or current.startswith(link["path"] + "/"))
            assert type(link["target"]) is str and 0 < len(link["target"].encode()) <= 1024 and "\x00" not in link["target"]
            current = posixpath.normpath(posixpath.join(posixpath.dirname(link["path"]), link["target"]) + current[len(link["path"]):])
            assert current == link["resolved"] and current.startswith(approved)
            assert type(link["device"]) is type(link["inode"]) is int and link["device"] >= 0 and link["inode"] > 0
        assert value["physical"] == current
        assert type(value["size"]) is int and value["size"] >= 0
        if value["size"] == 0:
            assert source and current.endswith((".py", ".pyi"))
            assert value["sha256"] == hashlib.sha256(b"").hexdigest()
        assert type(value["sha256"]) is str and re.fullmatch(r"[a-f0-9]{64}", value["sha256"])
        return value["size"]

    def executable_binding(value, physical, pid):
        assert type(value) is dict and set(value) == {"invocation", "implementation", "version", "alias", "kernel"}
        invocation = "/isaac-sim/kit/python/bin/python3"
        assert value["invocation"] == invocation and value["implementation"] == "cpython"
        assert type(value["version"]) is list and value["version"] == [3, 12]
        assert all(type(v) is int for v in value["version"])
        alias = value["alias"]
        selected = invocation
        if alias is not None:
            assert type(alias) is dict and set(alias) == {
                "target", "device", "inode", "mode", "size", "mtime_ns", "ctime_ns"}
            selected += ".12"
            assert alias["target"] in {"python3.12", selected}
            assert all(type(alias[k]) is int and alias[k] >= 0 for k in (
                "device", "inode", "mode", "size", "mtime_ns", "ctime_ns"))
            assert alias["inode"] > 0 and alias["mode"] & 0o170000 == 0o120000
            assert alias["size"] == len(alias["target"].encode())
        assert physical["path"] == selected
        kernel = value["kernel"]
        assert type(kernel) is dict and set(kernel) == {"path", "target", "device", "inode", "pid"}
        assert kernel["path"] == "/proc/self/exe" and kernel["target"] == selected
        assert type(kernel["pid"]) is int and kernel["pid"] == pid
        for key in ("device", "inode"):
            assert type(kernel[key]) is type(physical[key]) is int
            assert kernel[key] == physical[key] and kernel[key] >= (1 if key == "inode" else 0)
        # The kernel PID is role-specific; all other observed bindings agree.
        return dict(value, kernel={k: v for k, v in kernel.items() if k != "pid"})

    native_count = 0
    identity_bytes = 0
    rows = proof["initialization_roles"]
    expected = ["init-server", "init-generate", "init-refine", "init-assess"] if case == "positive" else ["init-server"]
    assert [row["role"] for row in rows] == expected
    if case == "init-server":
        assert proof["scope"] == "init-server preparation only" and proof["all_roles_complete"] is False
        assert proof["process_pids"] == [rows[0]["pid"]]
        assert all(type(pid) is int for pid in proof["process_pids"])
    assert len({row["pid"] for row in rows}) == len(rows)
    for row in rows:
        assert type(row["pid"]) is int and row["pid"] > 1
        assert row["pid"] == row["pgid"] == row["sid"] and type(row["start_ticks"]) is int
        assert row["start_ticks"] > 0 and row["source_sha256"] == proof["source_sha256"]
        assert row["preimport"]["before_package_imports"] is True
        assert row["real_preparation_complete"] is True and row["cache_verified"] is True
        assert row["native_bindings_verified"] is True and row["module_origins_verified"] is True
        assert row["platform_processor_unmodified"] is True and row["usable_gpu"] is False
        assert type(row["catalogue_sha256"]) is str and re.fullmatch(r"[a-f0-9]{64}", row["catalogue_sha256"])
        assert row["catalogue_sha256"] == rows[0]["catalogue_sha256"]
        bootstrap = row["pythonapi_bootstrap"]
        assert type(bootstrap) is list and len(bootstrap) == 1
        bootstrap = bootstrap[0]
        assert type(bootstrap) is dict and bootstrap["kind"] == "ctypes-pythonapi-process-namespace"
        assert bootstrap["argument"] is None and bootstrap["status"] == "completed"
        assert bootstrap["role"] == row["role"] and type(bootstrap["pid"]) is int
        assert bootstrap["pid"] == row["pid"]
        assert bootstrap["source"]["path"] == "/isaac-sim/kit/python/lib/python3.12/ctypes/__init__.py"
        context_bytes = 3 * physical_witness(bootstrap["source"]) + 4 * physical_witness(bootstrap["executable"])
        identity_bytes += context_bytes
        bound = executable_binding(bootstrap["executable_binding"], bootstrap["executable"], row["pid"])
        first = rows[0]["pythonapi_bootstrap"][0]
        assert bound == executable_binding(first["executable_binding"], first["executable"], rows[0]["pid"])
        for field in ("source", "executable", "callsite"):
            assert bootstrap[field] == rows[0]["pythonapi_bootstrap"][0][field]
        callsite = bootstrap["callsite"]
        assert callsite["module_code"] == "<module>" and callsite["init_code"] == "CDLL.__init__"
        assert all(type(callsite[k]) is int and callsite[k] > 0 for k in ("module_line", "init_line"))
        assert type(row["native_libraries"]) is list and row["native_libraries"]
        native_count += len(row["native_libraries"])
        for library in row["native_libraries"]:
            identity_bytes += physical_witness(library)
        assert type(row["module_origins"]) is list and row["module_origins"]
        for module in row["module_origins"]:
            identity_bytes += physical_witness(module, source=True)
            assert module["origin"] == module["path"]
            initialization_origin(module["name"], module["origin"], module["preloaded"])

        assert row["cache_before"] is not None and row["cache_after"] is not None
        maps = row["mapped_libraries"]
        assert type(maps) is list and maps
        map_bytes = 0
        for mapping in maps:
            assert type(mapping) is dict and set(mapping) == {"address", "permissions", "offset", "device", "inode", "path"}
            assert re.fullmatch(r"[a-f0-9]+-[a-f0-9]+", mapping["address"])
            assert re.fullmatch(r"[r-][w-][x-][ps]", mapping["permissions"])
            assert re.fullmatch(r"[a-f0-9]+", mapping["offset"])
            assert re.fullmatch(r"[a-f0-9]+:[a-f0-9]+", mapping["device"])
            assert re.fullmatch(r"[0-9]+", mapping["inode"])
            assert mapping["path"] is None or type(mapping["path"]) is str
            map_bytes += sum(len(value.encode()) for value in mapping.values() if value is not None) + 6
        assert map_bytes > 0
        metadata = row["cpu_metadata"]
        assert type(metadata) is list and len(metadata) <= 1
        for command in metadata:
            assert command["status"] == "completed" and type(command["returncode"]) is int and command["returncode"] == 0
            assert type(command["pid"]) is int and command["pid"] > 1
            assert command["executable"]["path"] == "/usr/bin/uname"
            physical_witness(command["executable"])
            assert type(command["stdout"]) is type(command["stderr"]) is str
            assert len(command["stdout"].encode()) <= 4096 and len(command["stderr"].encode()) <= 4096
        budget = row["physical_read_budget"]
        assert type(budget) is dict
        byte_limit = budget.get("byte_limit", 8 * 1024**3)
        native_limit = budget.get("native_limit", 64)
        file_limit = budget.get("file_limit", 2 * 1024**3)
        for limit in (byte_limit, native_limit, file_limit):
            assert limit is None or type(limit) is int and limit > 0
        if None in (byte_limit, native_limit, file_limit):
            assert row["role"] == "init-server", "Unbounded allocation is only authorized for init-server"
            assert byte_limit is native_limit is file_limit is None
        assert type(budget["bytes"]) is int and budget["bytes"] > 0
        assert byte_limit is None or budget["bytes"] <= byte_limit
        assert budget["bytes"] >= context_bytes + sum(v["size"] for v in row["native_libraries"] + row["module_origins"])
        assert type(budget["files"]) is int and budget["files"] >= len(row["native_libraries"])
        assert native_limit is None or budget["files"] <= native_limit
        if file_limit is not None:
            assert all(v["size"] <= file_limit for v in row["native_libraries"] + row["module_origins"])
        assert row["schema_checks"] == [
            "supported_normalization", "unknown_asset", "unknown_relation", "dangling_reference",
            "unknown_yaml_field", "catalogue_agreement", "catalogue_disagreement",
        ]
    if all(row["physical_read_budget"].get("byte_limit", 8 * 1024**3) is not None for row in rows):
        assert identity_bytes <= 8 * 1024**3
        assert sum(row["physical_read_budget"]["bytes"] for row in rows) <= 8 * 1024**3
    if all(row["physical_read_budget"].get("native_limit", 64) is not None for row in rows):
        assert native_count <= 64
        assert sum(row["physical_read_budget"]["files"] for row in rows) <= 64
    if case in {"failure", "timeout"}:
        cleanup = proof["initialization_server_cleanup"]
        assert type(cleanup) is dict and cleanup["status"] == "contained"
        assert cleanup["host_containment_required"] is False and proof["host_containment_required"] is False
        assert type(cleanup["server_pid"]) is int and cleanup["server_pid"] == rows[0]["pid"]
        assert type(cleanup["launcher_pid"]) is int and cleanup["launcher_pid"] > 1
        assert cleanup["launcher_pid"] != cleanup["server_pid"]
        assert type(cleanup["group_reap_seconds"]) in {int, float} and 0 <= cleanup["group_reap_seconds"] <= 5
        witness = proof["pre_readiness_failure"]
        assert type(witness["catalogue_sha256"]) is str
        assert witness["catalogue_sha256"] == rows[0]["catalogue_sha256"]
        assert witness["after_real_initialization"] is True and witness["before_owner_construction"] is True
        assert witness["case"] == case and witness["readiness_absent"] is True
        assert witness["server_pid"] == rows[0]["pid"] and witness["original_failure_retained"] is True
        if case == "timeout":
            assert witness["kind"] == "supervisor-stall-not-native-hang"
            assert witness["stall_seconds"] == 5 and witness["group_reap_seconds"] <= 5
        else:
            assert witness["kind"] == "fixed-initialization-failure"
    return True


if __name__ == "__main__":
    raise SystemExit(child())
