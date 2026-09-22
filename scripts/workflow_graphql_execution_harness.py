# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Explicit E0 installed execution-config admission; no owner/SDK permission.

Read outputs/workflow/plan04-implementation/installed-execution/admission.md.
This fixed bootstrap deliberately retains query-only effect denial. It is not
an execution profile, and passing it cannot certify workflow execution.
"""

import fcntl
import hashlib
import importlib.util
import json
import os
import re
import runpy
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

if __name__ == "__main__":
    assert sys.flags.isolated == sys.flags.no_site == 1
    sys.path.insert(0, "/source/scripts")

import workflow_process_harness as base

SELF = "scripts/workflow_graphql_execution_harness.py"
TEST = "isaaclab_arena/tests/test_environment_workflow_graphql_execution_neo4j.py"
SPEC = "outputs/workflow/plan04-implementation/installed-execution/admission.md"
MODULE = "isaaclab_arena.agentic_environment_generation.workflow.cli"
CONFIGS = tuple(f"/tmp/graphql-execution/{mode}/config/server.json" for mode in ("query", "execution"))
ENV = {"HOME": "/tmp", "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
EXECUTABLE = "/isaac-sim/kit/python/bin/python3"
SOURCE_LIMIT = 96
# Frozen repository leaves, excluding the four generated manifest/probe leaves.
# Host staging literal-parses this tuple; it never imports this harness on host.
SOURCE_FILES = (
    "isaaclab_arena/__init__.py",
    "isaaclab_arena/agentic_environment_generation/__init__.py",
    "isaaclab_arena/agentic_environment_generation/inference_profiles.py",
    "isaaclab_arena/agentic_environment_generation/workbench/__init__.py",
    "isaaclab_arena/agentic_environment_generation/workbench/research_artifacts.py",
    "isaaclab_arena/agentic_environment_generation/workflow/__init__.py",
    "isaaclab_arena/agentic_environment_generation/workflow/accounting.py",
    "isaaclab_arena/agentic_environment_generation/workflow/admin.py",
    "isaaclab_arena/agentic_environment_generation/workflow/api/__init__.py",
    "isaaclab_arena/agentic_environment_generation/workflow/api/application.py",
    "isaaclab_arena/agentic_environment_generation/workflow/api/client.py",
    "isaaclab_arena/agentic_environment_generation/workflow/api/installed_composition.py",
    "isaaclab_arena/agentic_environment_generation/workflow/api/installed_config.py",
    "isaaclab_arena/agentic_environment_generation/workflow/api/instance.py",
    "isaaclab_arena/agentic_environment_generation/workflow/api/private_files.py",
    "isaaclab_arena/agentic_environment_generation/workflow/api/resolvers.py",
    "isaaclab_arena/agentic_environment_generation/workflow/api/schema.py",
    "isaaclab_arena/agentic_environment_generation/workflow/api/security.py",
    "isaaclab_arena/agentic_environment_generation/workflow/api/server.py",
    "isaaclab_arena/agentic_environment_generation/workflow/artifacts.py",
    "isaaclab_arena/agentic_environment_generation/workflow/attempts.py",
    "isaaclab_arena/agentic_environment_generation/workflow/cli.py",
    "isaaclab_arena/agentic_environment_generation/workflow/commands.py",
    "isaaclab_arena/agentic_environment_generation/workflow/contracts.py",
    "isaaclab_arena/agentic_environment_generation/workflow/evidence.py",
    "isaaclab_arena/agentic_environment_generation/workflow/evidence_contracts.py",
    "isaaclab_arena/agentic_environment_generation/workflow/neo4j_store.py",
    "isaaclab_arena/agentic_environment_generation/workflow/paging.py",
    "isaaclab_arena/agentic_environment_generation/workflow/policy_contracts.py",
    "isaaclab_arena/agentic_environment_generation/workflow/profiles.py",
    "isaaclab_arena/agentic_environment_generation/workflow/queries.py",
    "isaaclab_arena/agentic_environment_generation/workflow/read_model.py",
    "isaaclab_arena/agentic_environment_generation/workflow/readiness.py",
    "isaaclab_arena/agentic_environment_generation/workflow/repairs.py",
    "isaaclab_arena/agentic_environment_generation/workflow/results.py",
    "isaaclab_arena/agentic_environment_generation/workflow/scene_evidence_artifacts.py",
    "isaaclab_arena/agentic_environment_generation/workflow/scene_loop.py",
    "isaaclab_arena/agentic_environment_generation/workflow/scope_binding.py",
    "isaaclab_arena/agentic_environment_generation/workflow/service.py",
    "isaaclab_arena/agentic_environment_generation/workflow/setup_readiness.py",
    "isaaclab_arena/tests/__init__.py",
    "isaaclab_arena/tests/test_environment_workflow_graphql_execution_neo4j.py",
    "outputs/workflow/plan04-implementation/installed-execution/admission.md",
    "scripts/run-workflow-neo4j-checks.py",
    "scripts/workflow_graphql_execution_harness.py",
    "scripts/workflow_process_harness.py",
)
CASE = "test_fresh_installed_execution_configuration_admission"


def verify_sources():
    """Verify the separate E0 manifest without changing legacy source policies."""
    root = Path("/source")
    assert os.statvfs(root).f_flag & os.ST_RDONLY
    manifest_path = root / "source-manifest.json"
    assert not manifest_path.is_symlink()
    raw = manifest_path.read_bytes()
    assert len(raw) <= 65536
    manifest = json.loads(raw)
    assert set(manifest) == set(SOURCE_FILES) | {"closure.json", "graphql-import-check.py", "graphql-profile.json"}
    assert {SELF, TEST, SPEC, base.SELF, "closure.json", "graphql-import-check.py", "graphql-profile.json"} <= set(manifest)
    assert len(manifest) + 1 <= SOURCE_LIMIT
    total = len(raw)
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


def checked_arguments(arguments):
    """Accept only the two fixed setup paths and one literal pipe descriptor."""
    assert type(arguments) is list and all(type(item) is str for item in arguments)
    assert len(arguments) == 6
    assert arguments[:2] == ["setup", "--config"] and arguments[2] in CONFIGS
    assert arguments[3:5] == ["--create", "--credentials-fd"]
    assert re.fullmatch(r"[1-9][0-9]{0,5}", arguments[5])
    fd = int(arguments[5])
    assert fd >= 3
    return CONFIGS.index(arguments[2]), fd


def checked_pipe(fd):
    assert type(fd) is int and fd >= 3
    info = os.fstat(fd)
    assert stat.S_ISFIFO(info.st_mode) and info.st_uid == info.st_gid == 1000
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
    assert re.fullmatch(r"pipe:\[[0-9]+\]", os.readlink(f"/proc/self/fd/{fd}"))


class ExecutionAdmissionGuards(base.Guards):
    """Two exact setup processes only; all original query denials still apply."""

    def __init__(self, role, db_ip=None):
        assert type(role) is str and role in {"harness", "setup"}
        assert role == "harness" or db_ip is None
        super().__init__(db_ip, query_only=True)
        self.role = role
        self.permit = None
        self.spawn_records = []
        self.loader_events = []

    def profile(self, frame, event, arg):
        # Observation only: never omit an inherited deny decision.
        super().profile(frame, event, arg)
        if self.role != "setup" or event not in {"call", "return"} or frame.f_code.co_name != "load":
            return
        name = "isaaclab_arena.agentic_environment_generation.workflow.api.installed_config"
        module = sys.modules.get(name)
        if (
            module is not None
            and frame.f_globals is module.__dict__
            and frame.f_code is module.load.__code__
            and frame.f_code.co_filename == module.__file__ == "/source/" + name.replace(".", "/") + ".py"
            and os.statvfs(module.__file__).f_flag & os.ST_RDONLY
        ):
            assert len(self.loader_events) < 2
            self.loader_events.append(
                {"event": event} if event == "call" else {"event": event, "accepted": type(arg) is module.Config}
            )

    def popen(self, args, *positional, **kwargs):
        frame = sys._getframe(1)
        permit = self.permit
        if (
            self.role != "harness"
            or frame.f_code is not fresh.__code__
            or frame.f_globals is not globals()
            or positional
            or permit is None
            or type(args) is not list
            or args != permit[0]
            or kwargs != permit[1]
            or any(type(kwargs[key]) is not type(value) for key, value in permit[1].items())
            or self.allowed["child_launch"] >= 2
        ):
            return self.deny("subprocess")
        self.permit = None
        assert all(type(item) is str for item in args)
        assert args[:6] == [EXECUTABLE, "-I", "-S", "-B", "/source/" + SELF, "--cli"]
        index, fd = checked_arguments(args[6:])
        assert index == self.allowed["child_launch"]
        checked_pipe(fd)
        verify_sources()
        self.local.expected = (args[0], args, kwargs["cwd"], kwargs["env"])
        self.allowed["child_launch"] += 1
        try:
            proc = self.native(args, **kwargs)
            self.children.append(proc.pid)
            self.spawn_records.append({"pid": proc.pid, "argv": list(args), "index": index})
            return proc
        finally:
            self.local.expected = None


def collect(proc):
    """Bound output during collection and reap the exact owned group on failure."""
    buffers = {proc.stdout: bytearray(), proc.stderr: bytearray()}
    deadline = time.monotonic() + 30
    try:
        with selectors.DefaultSelector() as selector:
            for stream in buffers:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                assert remaining > 0, "E0 setup collection deadline exceeded"
                for key, _ in selector.select(min(remaining, 0.1)):
                    stream = key.fileobj
                    data = os.read(stream.fileno(), min(4096, 65537 - len(buffers[stream])))
                    if not data:
                        selector.unregister(stream)
                        continue
                    assert len(buffers[stream]) + len(data) <= 65536, "E0 setup output exceeded"
                    buffers[stream].extend(data)
            remaining = deadline - time.monotonic()
            assert remaining > 0
            proc.wait(timeout=remaining)
        return bytes(buffers[proc.stdout]), bytes(buffers[proc.stderr])
    finally:
        if proc.poll() is None:
            # start_new_session=True binds this group to this exact owned launch.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)
        for stream in buffers:
            stream.close()


def fresh(arguments, *, private_fd):
    """Invoke the real installed setup CLI under a new isolated interpreter."""
    index, fd = checked_arguments(arguments)
    assert type(private_fd) is int and private_fd == fd
    checked_pipe(fd)
    assert sys.executable == EXECUTABLE and os.statvfs(EXECUTABLE).f_flag & os.ST_RDONLY
    args = [EXECUTABLE, "-I", "-S", "-B", "/source/" + SELF, "--cli", *arguments]
    kwargs = dict(
        executable=EXECUTABLE,
        env=dict(ENV),
        cwd="/tmp",
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        close_fds=True,
        pass_fds=(fd,),
        start_new_session=True,
        text=False,
    )
    guard = base.ACTIVE
    assert type(guard) is ExecutionAdmissionGuards and guard.role == "harness"
    assert index == guard.allowed["child_launch"]
    guard.permit = (args, kwargs)
    try:
        proc = subprocess.Popen(args, **kwargs)
        stdout, stderr = collect(proc)
        result = subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
        with Path(f"/evidence/graphql-execution-process-{proc.pid}.json").open("rb") as stream:
            raw = stream.read(4 * 1024 * 1024 + 1)
        assert len(raw) <= 4 * 1024 * 1024
        result.loader_events = json.loads(raw)["loader_events"]
        return result
    finally:
        guard.permit = None


def verify_children(guard, manifest):
    """Verify actual completed setup witnesses on assertion RED as well as GREEN."""
    assert type(guard) is ExecutionAdmissionGuards and guard.role == "harness"
    assert len(guard.children) == len(guard.spawn_records) == guard.allowed["child_launch"] == 2
    rows = []
    for index, spawn in enumerate(guard.spawn_records):
        pid = spawn["pid"]
        name = f"graphql-execution-process-{pid}.json"
        with (Path("/evidence") / name).open("rb") as stream:
            raw = stream.read(4 * 1024 * 1024 + 1)
        assert len(raw) <= 4 * 1024 * 1024
        record = json.loads(raw)
        assert record["source_sha256"] == manifest
        assert record["bootstrap_argv"] == spawn["argv"]
        assert record["role"] == "setup" and record["status"] == "completed"
        assert record["parent_pid"] == os.getpid()
        assert record["pid"] == record["pgid"] == record["sid"] == pid
        assert record["pid_namespace"] == os.readlink("/proc/self/ns/pid")
        assert record["boot"] == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        assert type(record["start_ticks"]) is int and record["start_ticks"] > 0
        assert record["preimport"]["before_package_imports"] is True
        assert set(record["preimport"]["kernel_denial"]) == {"2", "10"}
        assert not any(record["allowed"].values()) and not any(record["forbidden"].values())
        assert checked_arguments(record["argv"][1:])[0] == index
        assert type(record["returncode"]) is int and record["returncode"] in (0, 2)
        assert record["loader_events"][:1] == [{"event": "call"}]
        assert len(record["loader_events"]) == 2
        assert set(record["loader_events"][1]) == {"event", "accepted"}
        assert record["loader_events"][1]["event"] == "return"
        assert type(record["loader_events"][1]["accepted"]) is bool
        assert not Path(f"/proc/{pid}").exists(), "E0 setup process not reaped"
        rows.append({
            "pid": pid,
            "returncode": record["returncode"],
            "loader_events": record["loader_events"],
            "evidence_file": name,
            "evidence_sha256": hashlib.sha256(raw).hexdigest(),
        })
    assert {p.name for p in Path("/evidence").glob("graphql-execution-process-*.json")} == {
        row["evidence_file"] for row in rows
    }
    return {"execution_admission_processes": rows, "children_verified": True}


def child():
    assert sys.argv[1:2] == ["--cli"]
    assert sys.flags.isolated == sys.flags.no_site == sys.flags.ignore_environment == 1
    assert sys.executable == EXECUTABLE and os.getcwd() == "/tmp" and os.environ.get("HOME") == "/tmp"

    signal.alarm(25)
    arguments = sys.argv[2:]
    _, fd = checked_arguments(arguments)
    checked_pipe(fd)
    preimport = base.preflight()
    manifest = verify_sources()
    spec = importlib.util.spec_from_file_location("execution_runner", "/source/scripts/run-workflow-neo4j-checks.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    guard = ExecutionAdmissionGuards("setup")
    base.ACTIVE = guard
    guard.install()
    record = dict(
        role="setup",
        bootstrap_argv=[EXECUTABLE, "-I", "-S", "-B", "/source/" + SELF, "--cli", *arguments],
        argv=[MODULE, *arguments],
        preimport=preimport,
        source_sha256=manifest,
        pid=os.getpid(),
        parent_pid=os.getppid(),
        pgid=os.getpgrp(),
        sid=os.getsid(0),
        boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        pid_namespace=os.readlink("/proc/self/ns/pid"),
        start_ticks=int(Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19]),
        status="failed",
    )
    try:
        record["imports"] = runner.graphql_imports(preimport, guard)
        import platform

        platform.processor = lambda: os.uname().machine
        closure = json.loads(Path("/source/closure.json").read_text())
        runner.install_staged_import_guard("/source", closure["files"], closure["namespaces"])
        sys.argv = list(record["argv"])
        try:
            runpy.run_module(MODULE, run_name="__main__", alter_sys=False)
        except SystemExit as error:
            code = error.code
        else:
            code = 0
        assert type(code) is int
        record.update(status="completed", returncode=code)
        return code
    finally:
        record.update(forbidden=guard.forbidden, allowed=guard.allowed, loader_events=guard.loader_events)
        try:
            if "imports" in record:
                record["runtime_modules"] = runner.graphql_runtime_modules()
                record["additional_runtime_metadata"] = runner.graphql_runtime_metadata(record["runtime_modules"])
        except BaseException:
            record["status"] = "failed"
            raise
        finally:
            Path(f"/evidence/graphql-execution-process-{os.getpid()}.json").write_text(json.dumps(record, indent=2))
            signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(child())
