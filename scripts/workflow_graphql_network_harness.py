# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Fixed additive GraphQL network roles; legacy Guards remain unchanged."""

import hashlib
import importlib.util
import json
import os
import runpy
import re
import socket
import stat
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    assert sys.flags.isolated == sys.flags.no_site == 1
    sys.path.insert(0, "/source/scripts")

import workflow_process_harness as base
from workflow_process_harness import Guards

SELF = "scripts/workflow_graphql_network_harness.py"
MODULE = "isaaclab_arena.agentic_environment_generation.workflow.cli"
ROLES = frozenset({"harness", "admin", "launcher", "server", "client"})
CONFIG = "/tmp/graphql-network/config/server.json"
INSTANCE = "a" * 32
INSTANCES = (INSTANCE, "b" * 32, "c" * 32)
RUN_ID = hashlib.sha256(
    json.dumps(["network-test", "graphql-network", "network-seed"], separators=(",", ":")).encode()
).hexdigest()


FIXED_QUERIES = (
    ["runs", "--first", "10"],
    ["events", "--first", "10"],
    ["status", RUN_ID],
    ["submission", "network-seed"],
    ["receipt", "--kind", "SUBMIT", "network-seed"],
    ["profile", "network-profile", "--revision", "9223372036854775807"],
)


def role_for(arguments):
    if arguments in (
        ["admin", "initialize-schema", "--config", CONFIG],
        ["admin", "initialize-scope", "--config", CONFIG],
        ["admin", "initialize-artifacts", "--config", CONFIG, "--create"],
        [
            "admin",
            "register-profile",
            "--config",
            CONFIG,
            "--registration",
            "/tmp/graphql-network/config/registration.json",
        ],
    ):
        return "admin"
    if (
        len(arguments) == 6
        and arguments[:5] == ["setup", "--config", CONFIG, "--create", "--credentials-fd"]
        and re.fullmatch(r"[0-9]{1,6}", arguments[5])
    ):
        return "admin"
    if arguments in [
        [*query, "--client", "/tmp/graphql-network/runtime/instances/" + INSTANCE + "/client.json"]
        for query in FIXED_QUERIES
    ]:
        return "client"
    if arguments == ["--help"] or arguments in [
        ["profiles", "--client", "/tmp/graphql-network/runtime/instances/" + item + "/client.json"]
        for item in INSTANCES
    ]:
        return "client"
    if (
        len(arguments) == 5
        and arguments[1:4] == ["--config", CONFIG, "--instance"]
        and arguments[4] in INSTANCES
        and arguments[0] in {"api-launch", "api-status", "api-stop"}
    ):
        return "launcher" if arguments[0] == "api-launch" else "client"
    if (
        len(arguments) == 9
        and arguments[:4] == ["api-serve", "--config", CONFIG, "--instance"]
        and arguments[4] in INSTANCES
        and arguments[5] == "--lease-fd"
        and arguments[7] == "--gate-fd"
        and all(re.fullmatch(r"[0-9]{1,6}", arguments[i]) for i in (6, 8))
    ):
        return "server"
    raise ValueError("Unadmitted CLI operation")


def executing(module, code):
    loaded = sys.modules.get(module)
    frame = sys._getframe(1)
    while frame:
        if (
            frame.f_code is code
            and loaded is not None
            and frame.f_globals is loaded.__dict__
            and frame.f_code.co_filename == loaded.__file__
            and os.statvfs(loaded.__file__).f_flag & os.ST_RDONLY
        ):
            return True
        frame = frame.f_back
    return False


ENV = {"HOME": "/tmp", "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}


class NetworkGuards(Guards):
    """Role selection never derives child/listener permission from a DB address."""

    def __init__(self, role, db_ip):
        if type(role) is not str or role not in ROLES:
            raise ValueError("Invalid fixed network role")
        super().__init__(db_ip if role in {"harness", "admin", "server"} else None, query_only=True)
        self.role = role
        self.permit = None
        self.spawn_records = []
        self.basic_auth_handoffs = []

    def profile(self, frame, event, arg):
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
        if (
            os.readlink(f"/proc/self/fd/{fd}")
            not in ["/tmp/graphql-network/runtime/instances/" + item for item in INSTANCES]
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

    def server_child(self, args, positional, kwargs):
        module = "isaaclab_arena.agentic_environment_generation.workflow.api.instance"
        loaded = sys.modules.get(module)
        if (
            loaded is None
            or not executing(module, loaded.launch.__code__)
            or positional
            or self.allowed["child_launch"] != 0
        ):
            return self.deny("subprocess")
        if type(args) is not list or args[:3] != [sys.executable, "-m", MODULE] or role_for(args[3:]) != "server":
            return self.deny("subprocess")
        lifetime, gate = int(args[9]), int(args[11])
        expected = dict(
            executable=sys.executable,
            env=dict(ENV),
            cwd="/tmp",
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            close_fds=True,
            pass_fds=(lifetime, gate),
            start_new_session=True,
            text=False,
        )
        if kwargs != expected or any(type(kwargs[k]) is not type(v) for k, v in expected.items()):
            return self.deny("subprocess")
        if os.readlink(
            f"/proc/self/fd/{lifetime}"
        ) != "/tmp/graphql-network/runtime/lifetime.lock" or not stat.S_ISFIFO(os.fstat(gate).st_mode):
            return self.deny("subprocess")
        base.verify_sources(query_only=True, network=True)
        wrapped = [sys.executable, "-I", "-S", "-B", "/source/" + SELF, "--cli", *args[3:]]
        self.local.expected = (wrapped[0], wrapped, kwargs["cwd"], kwargs["env"])
        self.allowed["child_launch"] += 1
        try:
            proc = self.native(wrapped, **kwargs)
            self.children.append(proc.pid)
            self.spawn_records.append({"pid": proc.pid, "production_argv": args, "bootstrap_argv": wrapped})
            return proc
        finally:
            self.local.expected = None

    def popen(self, args, *positional, **kwargs):
        frame = sys._getframe(1)
        if self.role == "launcher":
            return self.server_child(args, positional, kwargs)
        expected = self.permit
        if (
            self.role != "harness"
            or frame.f_code is not fresh.__code__
            or frame.f_globals is not globals()
            or positional
            or expected is None
            or args != expected[0]
            or kwargs != expected[1]
            or self.allowed["child_launch"] >= 23
        ):
            return self.deny("subprocess")
        self.permit = None
        base.verify_sources(query_only=True, network=True)
        self.local.expected = (args[0], args, kwargs["cwd"], kwargs["env"])
        self.allowed["child_launch"] += 1
        try:
            proc = self.native(args, **kwargs)
            self.children.append(proc.pid)
            return proc
        finally:
            self.local.expected = None


def fresh(arguments, *, private_fd=None):
    """Execute one fixed public module role after fresh preimport/source guards."""
    assert role_for(arguments) != "server"
    if arguments[0] == "setup":
        assert type(private_fd) is int and private_fd >= 3 and arguments[-1] == str(private_fd)
        metadata = os.fstat(private_fd)
        assert stat.S_ISFIFO(metadata.st_mode) and metadata.st_uid == metadata.st_gid == 1000
        assert stat.S_IMODE(metadata.st_mode) == 0o600
    else:
        assert private_fd is None
    executable = sys.executable
    assert executable == "/isaac-sim/kit/python/bin/python3"
    assert os.statvfs(executable).f_flag & os.ST_RDONLY
    args = [executable, "-I", "-S", "-B", "/source/" + SELF, "--cli", *arguments]
    kwargs = dict(
        executable=executable,
        env=dict(ENV),
        cwd="/tmp",
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        close_fds=True,
        pass_fds=() if private_fd is None else (private_fd,),
        start_new_session=True,
        text=False,
    )
    guard = base.ACTIVE
    assert type(guard) is NetworkGuards and guard.role == "harness"
    guard.permit = (args, kwargs)
    try:
        proc = subprocess.Popen(args, **kwargs)
        stdout, stderr = proc.communicate(timeout=30)
        assert len(stdout) <= 65536 and len(stderr) <= 65536
        return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
    finally:
        guard.permit = None


def verify_children(guard, manifest):
    rows = []
    for pid in guard.children:
        record = json.loads(Path(f"/evidence/graphql-process-{pid}.json").read_text())
        assert record["source_sha256"] == manifest
        assert record["parent_pid"] == os.getpid() and record["pid"] == pid
        assert record["preimport"]["before_package_imports"] is True
        assert role_for(record["argv"][1:]) == record["role"]
        assert record["role"] in {"client", "launcher", "admin"} and not any(record["forbidden"].values())
        assert not Path(f"/proc/{pid}").exists()
        if record["role"] != "admin" or record["argv"][1] == "setup":
            assert record["allowed"]["bolt"] == 0
        else:
            assert record["allowed"]["bolt"] > 0 and record["allowed"]["child_launch"] == 0
            assert record["basic_auth_handoffs"] and all(record["basic_auth_handoffs"])
        assert record["status"] == "passed"
        rows.append(record)
    assert len(rows) == guard.allowed["child_launch"] == 23
    servers = []
    for launcher in rows:
        for spawned in launcher["spawn_records"]:
            pid = spawned["pid"]
            record = json.loads(Path(f"/evidence/graphql-process-{pid}.json").read_text())
            assert record["role"] == "server" and record["parent_pid"] == launcher["pid"]
            assert record["pid"] == record["pgid"] == record["sid"] == pid
            assert record["source_sha256"] == manifest and record["preimport"]["before_package_imports"] is True
            assert record["returncode"] == (2 if record["argv"][5] == "c" * 32 else 0)
            assert not any(record["forbidden"].values())
            assert record["basic_auth_handoffs"] and all(record["basic_auth_handoffs"])
            assert (
                record["allowed"]["child_launch"] == 0
                and record["allowed"]["bolt"] > 0
                and (
                    record["allowed"].get("http", 0) == 0
                    if record["argv"][5] == "c" * 32
                    else record["allowed"]["http"] >= 2
                )
            )
            from isaaclab_arena.agentic_environment_generation.workflow.api.instance import same_process

            expected = {
                "boot": record["boot"],
                "pid": pid,
                "start_ticks": record["start_ticks"],
                "pgid": record["pgid"],
                "sid": record["sid"],
                "namespace": record["pid_namespace"],
            }
            assert not same_process(expected)
            servers.append(record)
    assert len(servers) == 3
    observed = {p.name for p in Path("/evidence").glob("graphql-process-*.json")}
    assert observed == {f"graphql-process-{r['pid']}.json" for r in [*rows, *servers]}
    import hashlib

    def compact(record):
        name = f"graphql-process-{record['pid']}.json"
        raw = (Path("/evidence") / name).read_bytes()
        assert len(raw) <= 4 * 1024 * 1024
        return {
            **{
                key: record[key]
                for key in (
                    "pid",
                    "parent_pid",
                    "role",
                    "argv",
                    "returncode",
                    "allowed",
                    "forbidden",
                    "boot",
                    "start_ticks",
                    "pgid",
                    "sid",
                    "pid_namespace",
                )
            },
            "evidence_file": name,
            "evidence_sha256": hashlib.sha256(raw).hexdigest(),
        }

    return {
        "network_processes": [compact(r) for r in rows],
        "network_servers": [compact(r) for r in servers],
        "children_verified": True,
    }


def child():
    arguments = sys.argv[2:]
    assert sys.argv[1] == "--cli"
    role = role_for(arguments)
    assert sys.flags.isolated == sys.flags.no_site == sys.flags.ignore_environment == 1
    assert os.getcwd() == "/tmp" and os.environ.get("HOME") == "/tmp"
    preimport = base.preflight()
    manifest = base.verify_sources(query_only=True, network=True)
    spec = importlib.util.spec_from_file_location("network_runner", "/source/scripts/run-workflow-neo4j-checks.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    network = json.loads(Path("/network/manifest.json").read_text())
    assert os.statvfs("/network/manifest.json").f_flag & os.ST_RDONLY
    guard = NetworkGuards(role, network["ip"])
    base.ACTIVE = guard
    guard.install()
    record = dict(
        preimport=preimport,
        source_sha256=manifest,
        role=guard.role,
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
        closure = json.loads(Path("/source/closure.json").read_text())
        runner.install_staged_import_guard("/source", closure["files"], closure["namespaces"])
        sys.argv = [MODULE, *arguments]
        record["argv"] = list(sys.argv)
        try:
            runpy.run_module(MODULE, run_name="__main__", alter_sys=False)
        except SystemExit as error:
            code = error.code
        else:
            code = 0
        record["status"] = "passed"
        record["returncode"] = code
        return code
    finally:
        record.update(
            forbidden=guard.forbidden,
            allowed=guard.allowed,
            spawn_records=guard.spawn_records,
            basic_auth_handoffs=guard.basic_auth_handoffs,
        )
        record["runtime_modules"] = runner.graphql_runtime_modules()
        record["additional_runtime_metadata"] = runner.graphql_runtime_metadata(record["runtime_modules"])
        Path(f"/evidence/graphql-process-{os.getpid()}.json").write_text(json.dumps(record, indent=2))


if __name__ == "__main__":
    raise SystemExit(child())
