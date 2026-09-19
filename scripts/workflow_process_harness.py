# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Exact disposable workflow-process guard and stdlib-only fixture producer.

The ordinary child returns captured fixture bytes. The additive scene child runs
the real scene SDK through the existing fixed synthetic HTTP fixture, never live
HTTP/native/research. Both are separate from ordinary F0 network-none guards.
"""
import errno
import hashlib
import ipaddress
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

SELF = "scripts/workflow_process_harness.py"
TEST = "isaaclab_arena/tests/test_environment_workflow_recovery_neo4j.py"
FIXTURE = "isaaclab_arena/tests/test_data/minimal_maple_table_env_graph.yaml"
DRIVER = "/isaac-sim/kit/python/lib/python3.12/site-packages/neo4j/"
ACTIVE = None
MAX_CAPTURE_FILES = 320


def verify_sources(*, scene=False):
    """Bind every staged byte to a read-only host-captured hash manifest."""
    root = Path("/source")
    assert os.statvfs(root).f_flag & os.ST_RDONLY
    manifest = json.loads((root / "source-manifest.json").read_text())
    assert {
        SELF,
        ("isaaclab_arena/tests/test_environment_workflow_scene_worker_neo4j.py" if scene else TEST),
        FIXTURE,
        "closure.json",
    } <= set(manifest)
    assert len(manifest) <= (384 if scene else MAX_CAPTURE_FILES) - 1
    total = 0
    for name, digest in manifest.items():
        parts = Path(name).parts
        assert not Path(name).is_absolute() and ".." not in parts
        path = root
        for part in parts:
            path /= part
            assert not path.is_symlink()
        data = path.read_bytes()
        total += len(data)
        assert hashlib.sha256(data).hexdigest() == digest
    assert total <= 8 * 1024 * 1024
    return manifest


def preflight():
    """Observe kernel isolation before package imports or application audit hooks."""
    assert not any(n == "pytest" or n == "neo4j" or n.startswith("isaaclab_arena") for n in sys.modules)
    assert os.getuid() == 1000 and os.statvfs("/").f_flag & os.ST_RDONLY
    assert not any(n.startswith("nvidia") or n == "dri" for n in os.listdir("/dev"))
    routes = Path("/proc/net/route").read_text()
    rows = [line.split() for line in routes.splitlines()[1:]]
    assert rows and all(row[1] != "00000000" and row[2] == "00000000" for row in rows)
    ipv6 = Path("/proc/net/ipv6_route").read_text()
    assert all(line.split()[-1] == "lo" for line in ipv6.splitlines())
    denied = {}
    for family, address in (
        (socket.AF_INET, ("192.0.2.1", 443)),
        (socket.AF_INET6, ("2001:db8::1", 443)),
    ):
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect(address)
            except OSError as error:
                assert error.errno in {
                    errno.ENETUNREACH,
                    errno.EHOSTUNREACH,
                    errno.EACCES,
                    errno.EPERM,
                }
                denied[str(family)] = error.errno
            else:
                raise AssertionError("External kernel connect unexpectedly succeeded")
    return dict(
        before_package_imports=True,
        routes=routes,
        ipv6_routes=ipv6,
        kernel_denial=denied,
    )


def driver_frame():
    """Admit only the immutable installed driver's exact network modules."""
    paths = {
        "neo4j._async_compat.network._bolt_socket": "_async_compat/network/_bolt_socket.py",
        "neo4j._async_compat.network._util": "_async_compat/network/_util.py",
    }
    frame = sys._getframe(1)
    while frame:
        module = frame.f_globals.get("__name__") or ""
        if module.startswith("neo4j."):
            filename = frame.f_code.co_filename
            loaded = sys.modules.get(module)
            return (
                module in paths
                and filename == DRIVER + paths[module]
                and loaded is not None
                and loaded.__dict__ is frame.f_globals
                and loaded.__file__ == filename
                and os.statvfs(filename).f_flag & os.ST_RDONLY
            )
        frame = frame.f_back
    return False


class Guards:
    """Separate allowed transport/child counts from forbidden effects."""

    def __init__(self, db_ip=None, *, scene=False, cli=False, control=False):
        self.scene = scene
        self.cli = cli
        self.control = control
        self.control_identity = None
        if control:
            import stat

            root = Path("/tmp/workflow-cli/owner")
            info = root.lstat()
            assert stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.getuid()
            self.control_identity = (info.st_dev, info.st_ino)
        self.db_ip = str(ipaddress.IPv4Address(db_ip)) if db_ip else None
        self.forbidden = dict.fromkeys(("network", "subprocess", "provider", "runtime", "graph"), 0)
        self.allowed = {"bolt": 0, "child_launch": 0}
        self.local = threading.local()
        self.native = subprocess.Popen
        self.lock = threading.Lock()
        self.children = []

    def deny(self, category):
        self.forbidden[category] += 1
        raise RuntimeError("workflow-process denies " + category)

    def control_allowed(self, sock, address):
        """Only immutable owner-control source and the fixed private directory."""
        import re
        import stat

        if not self.control or sock.family != socket.AF_UNIX or sock.type != socket.SOCK_STREAM:
            return False
        if type(address) is not str:
            return False
        match = re.fullmatch(r"/proc/self/fd/([0-9]+)/stop-[a-f0-9]{40}\.sock", address)
        if not match:
            return False
        fd = int(match[1])
        try:
            info = os.fstat(fd)
            if (
                os.readlink(f"/proc/self/fd/{fd}") != "/tmp/workflow-cli/owner"
                or (info.st_dev, info.st_ino) != self.control_identity
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                return False
        except OSError:
            return False
        module = "isaaclab_arena_examples.agentic_environment_generation.foreground_control"
        source = "/source/" + module.replace(".", "/") + ".py"
        frame = sys._getframe(1)
        while frame:
            if frame.f_globals.get("__name__") == module:
                loaded = sys.modules.get(module)
                return (
                    loaded is not None
                    and loaded.__dict__ is frame.f_globals
                    and loaded.__file__ == frame.f_code.co_filename == source
                    and frame.f_code.co_name in {"start", "request_owner_stop"}
                    and bool(os.statvfs(source).f_flag & os.ST_RDONLY)
                )
            frame = frame.f_back
        return False

    def audit(self, event, args):
        if event in {"socket.bind", "socket.connect"} and self.control_allowed(*args):
            return
        if event == "socket.connect":
            sock, address = args
            if (
                self.db_ip
                and sock.family == socket.AF_INET
                and sock.type == socket.SOCK_STREAM
                and address == (self.db_ip, 7687)
                and driver_frame()
            ):
                self.allowed["bolt"] += 1
                return
            self.deny("network")
        if event in {
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.gethostbyaddr",
            "socket.getnameinfo",
            "socket.bind",
            "socket.sendto",
            "socket.sendmsg",
        }:
            self.deny("network")
        if event == "subprocess.Popen" and getattr(self.local, "expected", None) == args:
            self.local.expected = None
            return
        if event in {
            "subprocess.Popen",
            "os.system",
            "os.exec",
            "os.posix_spawn",
            "os.fork",
            "os.forkpty",
        }:
            self.deny("subprocess")

    def profile(self, frame, event, arg):
        if event != "call":
            return
        name = frame.f_code.co_name
        # These are exactly the policy-bearing names below. Avoid inspecting
        # globals and class hierarchies on millions of unrelated import calls.
        if name not in {"__init__", "launch", "render", "retrieve_snapshot", "driver"}:
            return
        module = frame.f_globals.get("__name__") or ""
        instance = frame.f_locals.get("self")
        owners = {base.__name__ for base in type(instance).__mro__} if name == "__init__" else set()
        if name == "__init__" and owners & {
            "InferenceBackend",
            "EnvironmentGenerationAgent",
            "OpenAI",
            "AsyncOpenAI",
        }:
            self.deny("provider")
        if (
            module.startswith(("isaacsim", "omni", "isaaclab.app"))
            and name in {"__init__", "launch"}
            or name == "__init__"
            and owners & {"SimulationApp", "AppLauncher", "SnapshotService"}
            or module.endswith("snapshot_service")
            and name == "render"
        ):
            self.deny("runtime")
        if module.endswith("graph_access") and name == "retrieve_snapshot":
            self.deny("graph")
        if (
            module.startswith("neo4j")
            and name in {"driver", "__init__"}
            and (name == "driver" or any(owner.endswith("Driver") for owner in owners))
        ):
            loaded = sys.modules.get(module)
            if (
                not self.db_ip
                or module != "neo4j._sync.driver"
                or frame.f_code.co_filename != DRIVER + "_sync/driver.py"
                or loaded is None
                or loaded.__dict__ is not frame.f_globals
                or not os.statvfs(frame.f_code.co_filename).f_flag & os.ST_RDONLY
            ):
                self.deny("graph")

    def install(self):
        sys.addaudithook(self.audit)
        profile = self.profile
        if self.scene and not self.db_ip:
            from generation_worker_fixture import production_sdk_profile

            profile = production_sdk_profile(profile)
        sys.setprofile(profile)
        threading.setprofile(profile)
        guard = self
        self.fixed_spec = (
            (cli_spawn_spec() if self.cli else scene_spawn_spec() if self.scene else spawn_spec())
            if self.db_ip
            else None
        )

        def numeric_only(host, port, family=0, type=0, proto=0, flags=0):
            if (
                guard.db_ip
                and host == guard.db_ip
                and port == 7687
                and family in (0, socket.AF_INET)
                and type in (0, socket.SOCK_STREAM)
                and driver_frame()
            ):
                return [(
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    (host, port),
                )]
            return guard.deny("network")

        socket.getaddrinfo = numeric_only
        # bind is audited; listen itself has no CPython audit event.
        native_listen = socket.socket.listen

        def listen(sock, backlog=0):
            if self.control_allowed(sock, sock.getsockname()) and backlog == 4:
                return native_listen(sock, backlog)
            return self.deny("network")

        socket.socket.listen = listen
        socket.socket.connect_ex = lambda *a, **k: self.deny("network")
        socket.socket.sendto = lambda *a, **k: self.deny("network")
        socket.socket.sendmsg = lambda *a, **k: self.deny("network")
        subprocess.Popen = self.popen

    def popen(self, args, *positional, **kwargs):
        expected_args, expected_kwargs = getattr(self, "fixed_spec", None) or spawn_spec()
        valid = (
            self.db_ip
            and not positional
            and type(args) is list
            and args == expected_args
            and kwargs == expected_kwargs
            and all(type(v) is str for v in args)
            and all(type(kwargs[k]) is type(v) for k, v in expected_kwargs.items())
            and all(type(k) is str and type(v) is str for k, v in kwargs["env"].items())
        )
        with self.lock:
            if not valid or self.allowed["child_launch"] >= (
                31 if self.cli else 4 if self.control else 12 if self.scene else 1
            ):
                self.deny("subprocess")
            verify_sources(scene=self.scene)
            self.local.expected = (args[0], args, kwargs["cwd"], kwargs["env"])
            self.allowed["child_launch"] += 1
            try:
                proc = self.native(args, **kwargs)
                self.children.append(proc.pid)
                return proc
            finally:
                self.local.expected = None


def spawn_spec():
    """One immutable interpreter, file, environment, and fully pinned Popen shape."""
    executable = str(Path(sys.executable).resolve(strict=True))
    assert executable.startswith("/isaac-sim/") and os.statvfs(executable).f_flag & os.ST_RDONLY
    env = {"HOME": "/tmp", "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    return [executable, "-I", "-S", "-B", "/source/" + SELF, "--child"], dict(
        executable=executable,
        env=env,
        cwd="/source",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        close_fds=True,
        pass_fds=(),
        start_new_session=True,
        text=False,
    )


def child():
    """Emit a modern eight-field fixture result, not real generation."""
    proof = dict(
        preimport=preflight(),
        source_sha256=verify_sources(),
        parent_pid=os.getppid(),
        pid=os.getpid(),
        pgid=os.getpgrp(),
        sid=os.getsid(0),
        pid_namespace=os.readlink("/proc/self/ns/pid"),
        start_ticks=int(Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19]),
    )
    guard = Guards()
    guard.install()
    try:
        packet = json.loads(sys.stdin.buffer.readline(512 * 1024 + 1))
        assert set(packet) == {"inputs", "config", "graph_config", "workflow_execution"}
        execution = packet["workflow_execution"]
        assert execution["registration"]["pid"] == os.getpid()
        assert execution["released_at"] >= execution["admitted_at"]
        assert packet["inputs"]["prompt"] == "Banana on maple table"
        result = dict(
            yaml_text=Path("/source/" + FIXTURE).read_text(),
            validation={"valid": True},
            traces=[],
            publication="not_published",
            warnings=[],
            operation="new",
            catalogue_sha256=packet["inputs"]["execution_catalogue_sha256"],
            prior_snapshot=dict(
                status="unavailable",
                derived_filters={"emb_filter": "", "fixture_filter": "table"},
                priors=[],
                exact_context="",
                context_sha256=hashlib.sha256(b"").hexdigest(),
                warnings=["unconfigured"],
                effective_settings=dict(
                    limit=2,
                    min_success_rate=0.0,
                    min_episodes=1,
                    query_timeout_seconds=5.0,
                    connection_timeout_seconds=None,
                    connection_acquisition_timeout_seconds=None,
                    max_transaction_retry_time_seconds=None,
                ),
                timing={"source": "not_started", "elapsed_seconds": None},
            ),
        )
        print(json.dumps({"result": result}), flush=True)
    finally:
        proof.update(forbidden=guard.forbidden, allowed=guard.allowed)
        Path(f"/evidence/workflow-child-{os.getpid()}.json").write_text(json.dumps(proof))


def load_scene_metadata():
    """Capture immutable Git version before audit, never package-driven commands."""
    sys.path.insert(0, "/source/web/arena-workbench/tests/e2e/functional-v7")
    from api import capture_git_metadata

    return capture_git_metadata()


def replay_scene_metadata(metadata, guard):
    import platform

    from api import MetadataReplay, metadata_popen

    platform.processor = lambda: os.uname().machine
    replay = MetadataReplay(metadata, guard.forbidden)
    native = subprocess.Popen
    subprocess.Popen = metadata_popen(replay)
    try:
        import git  # noqa: F401
    finally:
        subprocess.Popen = native
    return dict(
        stdout=metadata["stdout"].decode("ascii"),
        returncode=metadata["returncode"],
        replays=replay.reads,
    )


def scene_spawn_spec():
    """Use the existing fixed SDK fixture environment, not arbitrary child modes."""
    from generation_worker_fixture import spawn_spec as fixed

    args, kwargs = fixed("scene-sdk")
    args[-2:] = ["/source/" + SELF, "--scene-child"]
    return args, kwargs


def scene_child():
    """Actual scene worker under Bolt-free child guards and synthetic HTTP only."""
    import contextlib
    import importlib.util
    import signal

    signal.alarm(30)
    proof = dict(
        preimport=preflight(),
        source_sha256=verify_sources(scene=True),
        pid=os.getpid(),
        parent_pid=os.getppid(),
        pgid=os.getpgrp(),
        sid=os.getsid(0),
        pid_namespace=os.readlink("/proc/self/ns/pid"),
        start_ticks=int(Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19]),
    )
    metadata = load_scene_metadata()
    guard = Guards(scene=True)
    guard.install()
    try:
        proof["metadata"] = replay_scene_metadata(metadata, guard)
        spec = importlib.util.spec_from_file_location("scene_runner", "/source/scripts/run-workflow-neo4j-checks.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        closure = json.loads(Path("/source/closure.json").read_text())
        runner.install_staged_import_guard("/source", closure["files"], closure["namespaces"])
        sys.path.insert(0, "/source")
        from generation_worker_fixture import install_synthetic_sdk

        with contextlib.redirect_stdout(sys.stderr):
            install_synthetic_sdk(scene=True)
        from isaaclab_arena_examples.agentic_environment_generation.web_api import scene_worker

        sys.argv = ["scene_worker", "--parent-pid", str(os.getppid())]
        return scene_worker.main()
    finally:
        proof.update(forbidden=guard.forbidden, allowed=guard.allowed)
        Path(f"/evidence/workflow-child-{os.getpid()}.json").write_text(json.dumps(proof))


def verify_scene_children(guard, manifest):
    trace = json.loads(Path("/evidence/workflow-scene.json").read_text())
    composition = json.loads(Path("/evidence/workflow-scene-ports.json").read_text())
    application = json.loads(Path("/evidence/workflow-application.json").read_text())
    resumed = json.loads(Path("/evidence/workflow-resume.json").read_text())
    assert resumed["result"]["state"] == "accepted" and resumed["cache_reconstructed"] is True
    assert len(guard.children) == 12 and trace["proposal_guarded"] is True
    assert application["result"]["state"] == "accepted" and application["default_cli_factory"] is True
    assert application["result"]["owner"]["dirty"] is False
    assert application["stages"] == ["observe", "repair", "observe"]
    assert composition["state"] == "accepted" and composition["owner_retired"] is True
    assert composition["stages"] == ["observe", "repair", "observe"]
    registrations = [
        trace["registration"],
        *composition["registrations"],
        *application["registrations"],
        *resumed["registrations"],
    ]
    assert len(registrations) == 12 and {r["pid"] for r in registrations} == set(guard.children)
    for pid in guard.children:
        proof = json.loads(Path(f"/evidence/workflow-child-{pid}.json").read_text())
        reg = next(r for r in registrations if r["pid"] == pid)
        assert proof["pid"] == proof["pgid"] == proof["sid"] == pid == reg["pid"]
        assert proof["parent_pid"] == os.getpid() and proof["start_ticks"] == reg["start_ticks"]
        assert proof["pid_namespace"] == os.readlink("/proc/self/ns/pid")
        assert proof["source_sha256"] == manifest
        assert proof["preimport"]["before_package_imports"] is True
        assert not any(proof["forbidden"].values()) and not any(proof["allowed"].values())
        assert not Path(f"/proc/{pid}").exists()
        sdk = json.loads(Path(f"/evidence/generation-child-{pid}-sdk.json").read_text())
        assert sdk["calls"] == 2
    return dict(
        children_verified=True,
        scene=trace,
        scene_ports=composition,
        application=application,
        scope=(
            "real isolated Neo4j + default CLI/application + actual initial generation and scene SDK children;"
            " synthetic HTTP/capture; no native/live/research DB"
        ),
    )


CLI_MODULE = "isaaclab_arena_examples.agentic_environment_generation.foreground_workflow_cli"


def cli_spawn_spec():
    """Only the fixed reviewed module bootstrap may become a CLI process."""
    args, kwargs = scene_spawn_spec()
    args[-1] = "--cli-child"
    # Concurrent run/cancel interpreters must fit the unchanged 256-PID role.
    # Pin only this fresh-CLI profile; ordinary scene/SDK environments are intact.
    kwargs["env"].update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    return args, kwargs


def cli_child():
    """Bootstrap a fresh interpreter, then execute the public module as __main__."""
    import importlib.util
    import re
    import runpy
    import signal

    global ACTIVE
    signal.alarm(90)
    thread_limits = {key: os.environ.get(key) for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}
    assert all(value == "1" for value in thread_limits.values())
    proof = dict(
        thread_limits=thread_limits,
        preimport=preflight(),
        source_sha256=verify_sources(scene=True),
        parent_pid=os.getppid(),
        pid=os.getpid(),
        pgid=os.getpgrp(),
        sid=os.getsid(0),
        pid_namespace=os.readlink("/proc/self/ns/pid"),
        module_entry=False,
    )
    assert os.statvfs("/network/manifest.json").f_flag & os.ST_RDONLY
    network = json.loads(Path("/network/manifest.json").read_text())
    assert set(network) == {"container_id", "network_id", "ip", "port"} and network["port"] == 7687
    metadata = load_scene_metadata()
    guard = Guards(network["ip"], scene=True, control=True)
    ACTIVE = guard
    sys.modules["workflow_process_harness"] = sys.modules[__name__]
    guard.install()
    try:
        proof["metadata"] = replay_scene_metadata(metadata, guard)
        spec = importlib.util.spec_from_file_location("cli_runner", "/source/scripts/run-workflow-neo4j-checks.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        closure = json.loads(Path("/source/closure.json").read_text())
        runner.install_staged_import_guard("/source", closure["files"], closure["namespaces"])
        sys.path.insert(0, "/source")
        raw = sys.stdin.buffer.readline(16385)
        assert len(raw) <= 16384
        argv = json.loads(raw)
        checkpoint = None
        if type(argv) is dict:
            assert set(argv) == {"argv", "checkpoint"}
            checkpoint, argv = argv["checkpoint"], argv["argv"]
            assert checkpoint in {
                "before_claim",
                "after_observation",
                "after_release",
                "cancel_check",
                "cancel_unavailable",
                "admission",
                "handoff",
                "generation_readiness_same_app",
                "generation_claim",
            }
        assert type(argv) is list and all(type(a) is str for a in argv)
        assert argv[0] in {"run", "status", "cancel", "resume"}
        assert argv[1:5] == [
            "--config",
            "/tmp/workflow-cli/profile.json",
            "--principal",
            "creator",
        ]
        if argv[0] == "run":
            assert len(argv) == 8 and argv[5] == "--operation-id" and argv[7] == "/tmp/workflow-cli/contract.json"
            identity = argv[6]
        else:
            assert len(argv) == 6 or (argv[0] == "resume" and len(argv) == 7 and argv[6] == "--renew-authorization")
            identity = argv[5]
        assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", identity)
        if checkpoint in {"generation_readiness_same_app", "generation_claim"}:
            assert argv[0] == "run"
            from isaaclab_arena.agentic_environment_generation.workflow.contracts import parse_contract
            from isaaclab_arena.agentic_environment_generation.workflow.coordinator import GenerationCoordinator
            from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore
            from isaaclab_arena_examples.agentic_environment_generation.foreground_workflow import ForegroundWorkflow

            target, method = (
                (GenerationCoordinator, "_readiness")
                if checkpoint == "generation_readiness_same_app"
                else (Neo4jWorkflowStore, "claim_intent")
            )
            original_boundary = getattr(target, method)
            original_run = ForegroundWorkflow.run
            hits = []

            def interrupt_generation(*args, **kwargs):
                hits.append(True)
                raise ValueError("fixed generation interruption before boundary transaction")

            def interrupted_run(self, principal, operation_id, raw_contract):
                setattr(target, method, interrupt_generation)
                try:
                    result = original_run(self, principal, operation_id, raw_contract)
                finally:
                    setattr(target, method, original_boundary)
                assert hits == [True] and guard.allowed["child_launch"] == 0
                run_id = result["run_id"]
                original = self.store.result_records(run_id)
                assert self.store.pending_generation(run_id) is not None
                assert self.store.get_generation_attempt(run_id) is None
                owner = self.store.get_owner()
                self._local[run_id].lease.require_held(run_id, principal)
                proof["generation_interruption"] = dict(
                    checkpoint=checkpoint,
                    run_id=run_id,
                    calls_before=0,
                    admitted_at=original["admitted_at"],
                    intents=original["intents"],
                    owner_dirty=bool(owner and owner.dirty),
                    owner=owner.model_dump(mode="json") if owner else None,
                )
                if checkpoint == "generation_readiness_same_app":
                    contract = parse_contract(raw_contract)
                    binding = self.authority.require_scene_execute(principal, contract, run_id=run_id)
                    result = self.resume(principal, run_id)
                    proof["generation_interruption"]["same_grant"] = (
                        self.authority.require_scene_execute(principal, contract, run_id=run_id) == binding
                    )
                    proof["generation_interruption"]["resumed_state"] = result["state"]
                return result

            ForegroundWorkflow.run = interrupted_run
        elif checkpoint == "admission":
            assert argv[0] == "run"
            import time

            from isaaclab_arena_examples.agentic_environment_generation.foreground_workflow import ForegroundWorkflow

            original_listener = ForegroundWorkflow.set_admission_listener

            def pause_listener(self, callback):
                def admitted(handle):
                    callback(handle)
                    deadline = time.monotonic() + 20
                    while Path("/tmp/workflow-cli/pause-admission").exists():
                        assert time.monotonic() < deadline
                        time.sleep(0.02)

                return original_listener(self, admitted)

            ForegroundWorkflow.set_admission_listener = pause_listener
        elif checkpoint == "handoff":
            assert argv[0] == "run"
            import time

            from isaaclab_arena_examples.agentic_environment_generation.foreground_initial_generation import (
                InitialGenerationReceiver,
            )

            original_receive = InitialGenerationReceiver.receive

            def pause_handoff(self, *args, **kwargs):
                result = original_receive(self, *args, **kwargs)
                Path("/tmp/workflow-cli/handoff-ready.json").write_text(json.dumps(dict(run_id=result.run.run_id)))
                deadline = time.monotonic() + 20
                while Path("/tmp/workflow-cli/pause-handoff").exists():
                    assert time.monotonic() < deadline
                    time.sleep(0.02)
                return result

            InitialGenerationReceiver.receive = pause_handoff
        elif checkpoint in {"cancel_check", "cancel_unavailable"}:
            assert argv[0] == "cancel"
            from contextlib import contextmanager

            from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
                Neo4jWorkflowStore,
                StoreUnavailable,
            )

            target = json.loads(Path("/tmp/workflow-cli/active-target.json").read_text())
            assert target["run_id"] == identity
            original_transaction = Neo4jWorkflowStore._transaction

            @contextmanager
            def checked_transaction(self, *args, **kwargs):
                if "first_store_access" not in proof:
                    proof["first_store_access"] = dict(
                        child_absent=not Path(f"/proc/{target['pid']}").exists(),
                        bolt_before=guard.allowed["bolt"],
                        unavailable=checkpoint == "cancel_unavailable",
                    )
                assert proof["first_store_access"]["child_absent"]
                assert proof["first_store_access"]["bolt_before"] == 0
                if checkpoint == "cancel_unavailable":
                    raise StoreUnavailable("fixed cancel client outage")
                try:
                    with original_transaction(self, *args, **kwargs) as tx:
                        yield tx
                except Exception as exc:
                    # Static failure categories only; never exception/provider text.
                    proof.setdefault("store_failures", []).append(
                        "stale_cancel"
                        if str(exc) == "stale cancellation version or inactive run"
                        else type(exc).__name__
                    )
                    raise

            Neo4jWorkflowStore._transaction = checked_transaction
        elif checkpoint:
            assert argv[0] == "resume"
            from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore
            from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

            if checkpoint == "before_claim":

                def interrupt_scene(*args, **kwargs):
                    raise ValueError("fixture interruption before scene claim")

                WorkflowService.run_scene = interrupt_scene
            elif checkpoint == "after_release":
                from isaaclab_arena_examples.agentic_environment_generation.foreground_scene import (
                    ForegroundSceneWorker,
                )

                held = []
                original_prepare = ForegroundSceneWorker.prepare

                def capture_prepared(self, *args, **kwargs):
                    prepared = original_prepare(self, *args, **kwargs)
                    if type(self) is ForegroundSceneWorker:
                        held.append(prepared)
                    return prepared

                ForegroundSceneWorker.prepare = capture_prepared
                original_release = Neo4jWorkflowStore.release_scene

                def interrupt_release(self, *args, **kwargs):
                    original_release(self, *args, **kwargs)
                    # Withhold every private byte, then EOF the fixed child so its
                    # independent preimport/zero-SDK witness can finish before
                    # production's normal exact-group cleanup. No fake receipt.
                    assert len(held) == 1
                    child = held[0].owned_handle.process
                    child.stdin.close()
                    child.wait(timeout=25)
                    raise ValueError("fixture interruption after durable release before send")

                Neo4jWorkflowStore.release_scene = interrupt_release
            else:
                original_finish = Neo4jWorkflowStore.finish_scene

                def interrupt_finish(self, *args, **kwargs):
                    original_finish(self, *args, **kwargs)
                    raise ValueError("fixture interruption after durable observation")

                Neo4jWorkflowStore.finish_scene = interrupt_finish
        sys.argv = [CLI_MODULE, *argv]
        proof["module_entry"] = True
        runpy.run_module(CLI_MODULE, run_name="__main__", alter_sys=True)
    finally:
        proof.update(forbidden=guard.forbidden, allowed=guard.allowed, children=guard.children)
        for pid in guard.children:
            assert not Path(f"/proc/{pid}").exists(), "CLI worker not reaped"
        Path(f"/evidence/workflow-cli-{os.getpid()}.json").write_text(json.dumps(proof))


def verify_cli_children(guard, manifest):
    """Read actual independent CLI/SDK process proofs and finite cleanup."""
    trace = json.loads(Path("/evidence/workflow-cli.json").read_text())
    assert len(guard.children) == len(trace["commands"]) == 31
    assert len(trace["active_commands"]) == 12
    assert [c["outage"] for c in trace["active_cancellations"]] == [False, True, False]
    assert all(
        c["delivery_before_db"] and c["owner_retired"] and c["no_further_release"]
        for c in trace["active_cancellations"]
    )
    assert trace["state"] == "accepted" and trace["same_database"] and trace["owner_retired"]
    assert {item["pid"] for item in trace["commands"]} == set(guard.children)
    sdk_children = []
    baseline_sdk = []
    for pid in guard.children:
        child = json.loads(Path(f"/evidence/workflow-cli-{pid}.json").read_text())
        assert child["pid"] == child["pgid"] == child["sid"] == pid
        assert child["parent_pid"] == os.getpid() and child["source_sha256"] == manifest
        assert child["pid_namespace"] == os.readlink("/proc/self/ns/pid")
        assert child["module_entry"] and child["preimport"]["before_package_imports"]
        assert not any(child["forbidden"].values()) and not Path(f"/proc/{pid}").exists()
        for worker in child["children"]:
            worker_proof = json.loads(Path(f"/evidence/workflow-child-{worker}.json").read_text())
            assert worker_proof["parent_pid"] == pid and worker_proof["source_sha256"] == manifest
            assert not any(worker_proof["forbidden"].values()) and not any(worker_proof["allowed"].values())
            assert worker_proof["preimport"]["before_package_imports"]
            assert not Path(f"/proc/{worker}").exists()
            sdk = json.loads(Path(f"/evidence/generation-child-{worker}-sdk.json").read_text())
            assert sdk["calls"] == trace["sdk_calls"][f"generation-child-{worker}-sdk.json"]
            sdk_children.append(worker)
            if pid not in trace["active_commands"] and pid not in trace["b1_commands"]:
                baseline_sdk.append(sdk["calls"])
    assert len(sdk_children) == 28
    assert sorted(baseline_sdk) == [0] + [2] * 13
    assert sorted(trace["sdk_calls"].values()) == [0] + [2] * 27
    assert trace["uncertainty_retained"] is True
    return dict(
        children_verified=True,
        cli=trace,
        scope="fresh default module-entry run/status/cancel/resume; real disposable DB and SDK; synthetic HTTP/capture",
    )


if __name__ == "__main__":
    assert sys.argv[1:] in (["--child"], ["--scene-child"], ["--cli-child"])
    if sys.argv[1] == "--cli-child":
        raise SystemExit(cli_child())
    if sys.argv[1] == "--scene-child":
        raise SystemExit(scene_child())
    child()
