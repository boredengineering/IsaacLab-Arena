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
SUBMIT = ["submit", "--client", CLIENT, "--operation-id", OPERATION, "--contract", CONTRACT]
RESULT = ["result", RUN_ID, "--client", CLIENT, "--operation-id", OPERATION, "--wait-terminal-seconds", "120"]
STOP = ["api-stop", "--config", CONFIG, "--instance", INSTANCE]
STATUS = ["api-status", "--config", CONFIG, "--instance", INSTANCE]
THREAD_ENV = {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
LAUNCH_ENV = {"HOME": "/tmp", "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
ENV = {**LAUNCH_ENV, **THREAD_ENV}
SOURCE_LIMIT = 383  # Exact static closure plus four generated leaves.
SOURCE_MANIFEST_LIMIT = 65536
ACTIVE = None

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


def registration_metadata_probe(preimport, guard, runner, report):
    """Prepare E1 immutable candidate evidence without enabling package imports."""
    import ast
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
    """Keep legacy origin rules, with only exact finder-owned YAML objects added."""
    if finder is None:
        return runner.graphql_runtime_modules()
    rows = {}
    probe = runner._GRAPHQL_PROBE
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
            _, row = probe["physical_file"](origin, probe["ALLOWED"])
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
    if arguments == LAUNCH:
        return "launcher"
    if arguments in (SUBMIT, RESULT, STOP, STATUS):
        return "client"
    if (
        len(arguments) == 9
        and arguments[:5] == ["api-serve", "--config", CONFIG, "--instance", INSTANCE]
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
        self.deadline = time.monotonic() + 140
        self.sdk_ready = False
        self.sdk_calls = 0
        self.used = []
        self.cli_arguments = None
        self.http_operations = []
        self.http_started = None
        self.last_status = None

    def profile(self, frame, event, arg):
        if self.role == "client" and event == "call" and frame.f_code.co_name == "query":
            name = "isaaclab_arena.agentic_environment_generation.workflow.api.client"
            loaded = sys.modules.get(name)
            if loaded is not None and frame.f_code is loaded.query.__code__ and frame.f_globals is loaded.__dict__:
                now = time.monotonic()
                operation = frame.f_locals.get("operation")
                assert frame.f_locals.get("path") == CLIENT
                if self.http_started is None:
                    self.http_started = now
                if self.cli_arguments == SUBMIT:
                    assert operation == "submit" and not self.http_operations
                else:
                    assert self.cli_arguments == RESULT and now - self.http_started < 120
                    assert operation in {"result-status", "result"} and "result" not in self.http_operations
                    if operation == "result-status":
                        assert self.http_operations.count("result-status") < 120
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
        directory = Path(f"/tmp/graphql-execution/execution/runtime/instances/{INSTANCE}")
        if directory.is_symlink():
            return False
        expected = directory.stat()
        if (info.st_dev, info.st_ino) != (expected.st_dev, expected.st_ino):
            return False
        if (
            os.readlink(f"/proc/self/fd/{fd}")
            not in ["/tmp/graphql-execution/execution/runtime/instances/" + item for item in (INSTANCE,)]
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
            # Independent launch evidence remains available while server is live.
            write_evidence(f"join-launch-{proc.pid}.json", {**row, "parent_pid": os.getpid()})
            return proc
        finally:
            self.local.expected = None

    def popen(self, args, *positional, **kwargs):
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
                if self.allowed["child_launch"] >= 4 or any(Path(f"/proc/{pid}").exists() for pid in self.children):
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
            or self.allowed["child_launch"] >= 12
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
    """Issue only spawn/capture ports to the selected fixed installed composition.

    Proposed production interface: api.installed_execution.compose calls this
    bootstrap capability itself. No constructor/root/store/grant is injected.
    Its absence remains a real production refusal, never a fixture fallback.
    """
    module = "isaaclab_arena.agentic_environment_generation.workflow.api.installed_execution"
    loaded = sys.modules.get(module)
    assert type(ACTIVE) is JoinGuards and ACTIVE.role == "server" and not ACTIVE.ports_issued
    assert loaded is not None and executing(module, loaded.compose.__code__)
    verify_sources()
    from workflow_graphql_execution_join_fixture import synthetic_capture

    ACTIVE.ports_issued = True
    return {"spawn_spec": scene_spawn_spec, "capture": synthetic_capture}


def unused(arguments):
    return arguments not in ACTIVE.used


def fresh(arguments, *, private_fd=None):
    """Run exactly one reviewed public CLI, with incremental bounded collection."""
    guard = ACTIVE
    assert type(guard) is JoinGuards and guard.role == "harness"
    role = role_for(arguments)
    assert role != "server" and unused(arguments)
    index = len(guard.used)
    if role == "setup":
        assert index < 2 and arguments[2] == CONFIGS[index]
        assert type(private_fd) is int and str(private_fd) == arguments[-1]
        checked_pipe(private_fd)
    else:
        assert private_fd is None
        if arguments not in (STOP, STATUS):
            assert arguments == [*ADMIN, LAUNCH, SUBMIT, RESULT][index - 2] and index >= 2
        else:
            assert LAUNCH in guard.used
            assert arguments == STOP or STOP in guard.used
    guard.used.append(list(arguments))
    args = [EXECUTABLE, "-I", "-S", "-B", "/source/" + SELF, "--cli", *arguments]
    kwargs = process_kwargs(pass_fds=() if private_fd is None else (private_fd,))
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
    # The executable bootstrap and production's fixed capability import must
    # resolve to this same module/guard, never a second inactive module instance.
    assert "workflow_graphql_execution_join_harness" not in sys.modules or (
        sys.modules["workflow_graphql_execution_join_harness"] is sys.modules[__name__]
    )
    sys.modules["workflow_graphql_execution_join_harness"] = sys.modules[__name__]
    assert sys.flags.isolated == sys.flags.no_site == sys.flags.ignore_environment == 1
    assert sys.executable == EXECUTABLE and os.statvfs(EXECUTABLE).f_flag & os.ST_RDONLY
    assert all(os.environ.get(k) == v for k, v in ENV.items())
    model = sys.argv[1:] == ["--model"]
    assert model or sys.argv[1:2] == ["--cli"]
    arguments = [] if model else sys.argv[2:]
    role = "model" if model else role_for(arguments)
    assert os.getcwd() == ("/source" if model else "/tmp")
    signal.alarm(30 if model else 130 if arguments == RESULT else 145 if role == "server" else 40)
    if role == "setup":
        checked_pipe(int(arguments[-1]))
    preimport = base.preflight()
    manifest = verify_sources()
    network = read_json(Path("/network/manifest.json"), 65536)
    assert os.statvfs("/network/manifest.json").f_flag & os.ST_RDONLY
    assert set(network) == {"container_id", "network_id", "ip", "port"} and network["port"] == 7687
    guard = JoinGuards(role, network["ip"])
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
    try:
        record["imports"] = runner.graphql_imports(preimport, guard)
        if role == "server":
            record["dependency_location_probe"] = dependency_location_probe(preimport, guard, runner)
            record["registration_metadata_probe"] = {}
            registration_metadata_probe(preimport, guard, runner, record["registration_metadata_probe"])
        if role in {"server", "model"}:
            record["e1_yaml_binding"] = {}
            yaml_finder = install_e1_yaml(preimport, guard, runner, record["e1_yaml_binding"])
        import platform

        platform.processor = lambda: os.uname().machine
        closure = read_json(Path("/source/closure.json"), 65536)
        runner.install_staged_import_guard("/source", closure["files"], closure["namespaces"])
        sys.path.insert(0, "/source/scripts")
        sys.path.insert(0, "/source/web/arena-workbench/tests/e2e/functional-v7")
        # Do not initialize SDK or import legacy factories in any CLI role.
        if model:
            record["metadata"] = metadata_replay(guard)
            from generation_worker_fixture import install_synthetic_sdk, production_sdk_profile
            from workflow_graphql_execution_join_fixture import install_detachment_transport

            transport = {}

            def sdk_profile(frame, event, arg):
                # Preserve exact constructor checks but not the fixture's optional
                # graph-access exception: this cohort allows no retrieval at all.
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
            if role == "server":
                record["startup_exception_sites"] = []
                startup_lock = threading.RLock()
                startup_active = [True]
                startup_main = threading.get_ident()
                startup_targets = {
                    "/source/isaaclab_arena/agentic_environment_generation/workflow/api/server.py": {
                        "supervise", "serve", "serving",
                    },
                    "/source/isaaclab_arena/agentic_environment_generation/workflow/api/application.py": {
                        "boot", "lifespan",
                    },
                    "/source/isaaclab_arena/agentic_environment_generation/workflow/api/installed_execution.py": {
                        "compose", "build",
                    },
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
                    runpy.run_module(MODULE, run_name="__main__", alter_sys=False)
                except SystemExit as error:
                    code = error.code
                else:
                    code = 0
            finally:
                if role == "server":
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
        raise
    finally:
        original_error = sys.exc_info()[0]
        record.update(
            forbidden=guard.forbidden,
            allowed=guard.allowed,
            spawn_records=guard.spawn_records,
            basic_auth_handoffs=guard.basic_auth_handoffs,
            owner_constructions=guard.owner_constructions,
            sdk_ready=guard.sdk_ready,
            sdk_calls=guard.sdk_calls,
            http_operations=guard.http_operations,
        )
        try:
            assert verify_sources() == manifest
            if "imports" in record:
                record["runtime_modules"] = e1_runtime_modules(runner, yaml_finder)
                record["additional_runtime_metadata"] = runtime_metadata(runner, record["runtime_modules"], yaml_finder)
        except BaseException as error:
            if role not in {"server", "model"}:
                raise
            record["finalization_error_type"] = type(error).__name__
            record["status"] = "failed"
            if original_error is None:
                raise
        finally:
            write_evidence(f"join-process-{os.getpid()}.json", record)
            signal.alarm(0)


def server_pid():
    launchers = [r for r in ACTIVE.spawn_records if r["bootstrap_argv"][6:] == LAUNCH]
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
        evidence = store.get_scene_evidence(RUN_ID, inspection.scene.evidence_id)
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
    assert type(guard) is JoinGuards and guard.role == "harness"
    rows, missing = [], []
    pending = [(os.getpid(), row) for row in guard.spawn_records]
    while pending:
        parent, launch = pending.pop(0)
        pid = launch["pid"]
        path = Path(f"/evidence/join-process-{pid}.json")
        if not path.exists():
            missing.append(pid)
            continue
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

        assert not missing and len(guard.spawn_records) == 12 and len(rows) == 17
        assert all(row["status"] == "completed" and row["returncode"] == 0 for row in rows)
        assert all(not any(row["forbidden"].values()) for row in rows)
        assert {row["pid"] for row in rows} == {
            int(p.name.removeprefix("join-process-").removesuffix(".json"))
            for p in Path("/evidence").glob("join-process-*.json")
            if not p.name.endswith("-started.json")
        }
        server = next(row for row in rows if row["role"] == "server")
        assert server["owner_constructions"] == 1 and server["allowed"]["child_launch"] == 4
        retained = read_json(Path("/evidence/join-retained.json"))
        models = [row for row in rows if row["role"] == "model"]
        assert len(models) == 4
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
    marker = dict(
        **identity(), case=case, catalogue_sha256=digest,
        after_real_initialization=True, before_owner_construction=True,
        observed_at=time.monotonic(),
        kind="fixed-initialization-failure" if case == "failure" else "supervisor-stall-not-native-hang",
        status="checkpoint_only_not_lifecycle_proof",
    )
    write_evidence("initialization-pre-readiness.json", marker)
    if case == "failure":
        raise RuntimeError("S2 fixed post-initialization pre-readiness failure")
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
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def initialization_origin(name, origin, preloaded):
    """Check one selected package's lexical origin, not its physical identity.

    The caller must separately no-follow/hash the actual loader bytes before
    loading. This deliberately does NOT admit arbitrary purelib dependencies,
    Isaac Lab path rewrites, namespace fallbacks, or preloaded package objects.
    """
    assert type(name) is type(origin) is str and type(preloaded) is bool and not preloaded
    pure = "/isaac-sim/kit/python/lib/python3.12/site-packages/"
    roots = {
        "warp": pure + "warp", "torch": pure + "torch", "pxr": pure + "pxr",
        "openai": pure + "openai",
        "yaml": "/isaac-sim/exts/omni.pip.compute/pip_prebundle/yaml",
        "isaaclab": "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab",
    }
    root = name.split(".")[0]
    assert root in roots and all(part.isidentifier() for part in name.split("."))
    assert origin.startswith(roots[root] + "/")
    assert all(part not in {"", ".", ".."} for part in origin.split("/")[1:])
    assert origin.endswith((".py", ".so"))
    return root


def initialization_inside(case):
    """Return an explicit nonpass while S2's execution controls remain incomplete.

    No imports, native initialization, children or pytest are attempted here.
    In particular, never manufacture pytest.xml or promote static guard checks
    to IF-B/IF-C evidence. Returning normally leaves collection to the runner.
    This refusal must be replaced by reviewed orchestration before release.
    """
    assert type(case) is str and case in {"positive", "failure", "timeout"}
    proof = dict(
        status="failed", mode="workflow-graphql-initialization", case=case, tests=0,
        execution_attempted=False, source_sha256={}, initialization_roles=[],
        children_verified=False, missing_process_witnesses=[],
        release_blockers=[
            "cold-role origin/native-loader enforcement and cache identity preflight are not wired",
            "exact CPU metadata subprocess mediation and loaded-map bounds are not wired",
            "installed pre-readiness failure/stall and exact group cleanup witnesses are not wired",
            "fixed real pytest case dispatch and source-frozen role collection are not wired",
        ],
    )
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

    assert type(case) is str and case in {"positive", "failure", "timeout"}
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
    assert len(tests) == 1 and tests[0].get("name") == "test_initialization_" + case
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

    def physical_witness(value):
        # Same fields as physical_file, with S2's no-follow requirement. This
        # checks retained structure only; it does not read or admit native bytes.
        assert type(value) is dict
        for key in ("path", "physical"):
            path = value[key]
            assert type(path) is str and path.startswith("/") and "\x00" not in path
            assert all(part not in {"", ".", ".."} for part in path.split("/")[1:])
        assert value["physical"] == value["path"] and value["links"] == []
        assert type(value["size"]) is int and 0 < value["size"] <= 2 * 1024**3
        assert type(value["sha256"]) is str and re.fullmatch(r"[a-f0-9]{64}", value["sha256"])
        return value["size"]

    native_count = 0
    identity_bytes = 0
    rows = proof["initialization_roles"]
    expected = ["init-server", "init-generate", "init-refine", "init-assess"] if case == "positive" else ["init-server"]
    assert [row["role"] for row in rows] == expected
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
        assert type(row["native_libraries"]) is list and row["native_libraries"]
        native_count += len(row["native_libraries"])
        assert native_count <= 64
        for library in row["native_libraries"]:
            identity_bytes += physical_witness(library)
        assert type(row["module_origins"]) is list and row["module_origins"]
        for module in row["module_origins"]:
            identity_bytes += physical_witness(module)
            assert module["origin"] == module["path"]
            initialization_origin(module["name"], module["origin"], module["preloaded"])
        assert identity_bytes <= 8 * 1024**3
        assert row["cache_before"] is not None and row["cache_after"] is not None
        assert row["schema_checks"] == [
            "supported_normalization", "unknown_asset", "unknown_relation", "dangling_reference",
            "unknown_yaml_field", "catalogue_agreement", "catalogue_disagreement",
        ]
    if case != "positive":
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
