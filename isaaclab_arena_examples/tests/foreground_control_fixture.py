# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Exact stdlib host launcher / isolated UDS-only CANCEL-01 fixture.

--sandbox executes only frozen control source and tests in a disposable nonroot,
read-only, network-none container. No dependency install or live container exec.
This additive fixture does not change any ordinary F0 network/process profile.
--application-sandbox adds the application helper units and distinct owner-child
proof; the ordinary four-file/16-case selection stays unchanged.
"""
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

SELF = "isaaclab_arena_examples/tests/foreground_control_fixture.py"
TEST = "isaaclab_arena_examples/tests/test_foreground_control.py"
CONTROL = "isaaclab_arena_examples/agentic_environment_generation/foreground_control.py"
IMAGE = "sha256:e20b3cc8258b793aaf1fe47c130f54e677fa9c0a6427991cfc1045b743162da5"
COORDINATOR = "isaaclab_arena/agentic_environment_generation/workflow/coordinator.py"
CANCELLATION = "isaaclab_arena_examples/agentic_environment_generation/foreground_cancellation.py"
CANCELLATION_TEST = "isaaclab_arena_examples/tests/test_foreground_cancellation.py"
FILES = (SELF, TEST, CONTROL, COORDINATOR)
APPLICATION_FILES = (*FILES, CANCELLATION, CANCELLATION_TEST)


def sandbox(*, application=False):
    """Run the exact captured UDS cohort through the shared owned lifecycle."""
    import signal
    import traceback

    root = Path(__file__).absolute().parents[2]
    sys.path.insert(0, str(root / "web/arena-workbench/tests/e2e/functional-v7"))
    import run as f0
    from confined_io import ConfinedRoot, new_destination

    name = "arena-owner-stop-" + uuid.uuid4().hex
    evidence = root / "outputs/workflow" / name
    # Validate every existing ancestor before creating anything or asking Docker.
    with new_destination(evidence):
        pass

    def command(*args):
        if args[0] == "create":
            replacements = {
                "--pids-limit=256": "--pids-limit=64",
                "--memory=4g": "--memory=1g",
                "--workdir=/tmp": "--workdir=/source",
                "--tmpfs=/tmp:rw,nosuid,nodev,uid=1000,gid=1000,mode=1777,size=1073741824":
                    "--tmpfs=/tmp:rw,nosuid,nodev,uid=0,gid=0,mode=1777,size=33554432",
            }
            args = tuple(replacements.get(arg, arg) for arg in args)
            args = (args[0], "--cpus=2", *args[1:])
        return f0.docker(*args)

    class FixtureRun(f0.OwnedRun):
        """Keep every durable snapshot conservative when create ACK is missing."""

        def save(self):
            import re

            unresolved = [candidate for candidate in self.candidates
                          if not re.fullmatch(r"[0-9a-f]{64}", self.proof["created_ids"].get(candidate, ""))]
            self.proof["unresolved_create_ack"] = unresolved
            if unresolved and "cleanup_verification" in self.proof:
                self.proof["cleanup_verified"] = False
                self.proof["cleanup_verification"].update(status="unknown", authoritative=False)
            super().save()

    owned = FixtureRun(evidence, name, command=command)
    proof = owned.proof
    proof.update(status="failed", image=IMAGE, name=name, cleanup_verified=False)
    previous = {}

    def interrupted(signum, frame):
        raise InterruptedError(f"signal {signum}")

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, interrupted)
    try:
        discovery = f0.discover(root, False)
        proof["discovery"] = discovery
        f0.image_metadata(IMAGE)
        with ConfinedRoot(root) as source:
            captured = {rel: source.read(rel) for rel in (APPLICATION_FILES if application else FILES)}
        manifest = {rel: hashlib.sha256(data).hexdigest() for rel, data in captured.items()}
        proof["source_sha256"] = manifest
        with new_destination(evidence / "source") as destination:
            for rel, data in captured.items():
                destination.write_new(rel, data)
            destination.write_new("manifest.json", json.dumps(manifest).encode())
        host = discovery["host_root"] + "/" + evidence.relative_to(root).as_posix()
        mounts = [f"type=bind,src={host}/source,dst=/source,readonly"]
        cid = owned.create(
            "tests", IMAGE, "/usr/bin/env",
            ["-i", "HOME=/tmp", "PATH=/usr/bin:/bin", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
             "NVIDIA_VISIBLE_DEVICES=void", "CUDA_VISIBLE_DEVICES=", "/isaac-sim/python.sh",
             "-I", "-B", "/source/" + SELF, "--application-inside" if application else "--inside"], mounts,
        )
        proof["container_id"] = cid
        f0.verify_container(owned, cid, mounts)
        bounds = json.loads(command("inspect", "--format", f0.projection({
            "Id": ".Id", "Image": ".Image", "NanoCpus": ".HostConfig.NanoCpus",
        }), cid))
        assert bounds == {"Id": cid, "Image": IMAGE, "NanoCpus": 2000000000}
        host_config = proof["containers"][-1]["host_config"]
        assert host_config["PidsLimit"] == 64 and host_config["Memory"] == 1073741824
        proof["prestart_bounds"] = bounds
        command("start", cid)
        proof["exit_code"] = int(command("wait", cid))
        output = command("logs", "--tail", "1000", cid)
        (evidence / "stdout.txt").write_text(output)
        lines = [line.removeprefix("CANCEL01_PROOF ") for line in output.splitlines()
                 if line.startswith("CANCEL01_PROOF ")]
        assert len(lines) == 1, "Missing or duplicate CANCEL01 proof"
        observed = json.loads(lines[0])
        assert observed["manifest"] == manifest and observed["forbidden"] == []
        assert type(observed["result"]) is int and observed["result"] == 0
        junit = observed.pop("junit")
        (evidence / "junit.xml").write_text(junit)
        import xml.etree.ElementTree as ET

        report = ET.fromstring(junit)
        cases = report.findall(".//testcase")
        assert len(cases) == (28 if application else 16), "Expected exact selected cancellation cohort"
        assert not any(list(report.iter(tag)) for tag in ("failure", "error", "skipped"))
        suites = list(report.iter("testsuite"))
        assert suites and sum(int(suite.attrib["tests"]) for suite in suites) == len(cases)
        assert all(int(suite.attrib.get(key, 0)) == 0
                   for suite in suites for key in ("failures", "errors", "skipped"))
        proof["observed"] = observed
        proof["tests"] = len(cases)
        assert proof["exit_code"] == 0
        proof["status"] = "passed"
    except BaseException:
        proof["failure"] = traceback.format_exc()
    finally:
        for signum in previous:
            signal.signal(signum, signal.SIG_IGN)
        try:
            proof["cleanup_verified"] = owned.cleanup() and not proof.get("unresolved_create_ack")
            changed, rejected = f0.compare_source(evidence / "source", proof.get("source_sha256", {}))
            proof["staged_source_unchanged"] = bool(proof.get("source_sha256")) and not (changed or rejected)
            proof["source_errors"] = changed + rejected
            if not proof["cleanup_verified"] or not proof["staged_source_unchanged"]:
                proof["status"] = "failed"
            owned.save()
            (evidence / "proof.json").write_text(json.dumps(proof, indent=2))
            print("EVIDENCE", evidence)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    return 0 if proof["status"] == "passed" else 1


def preflight():
    assert os.getuid() == 1000 and os.statvfs("/").f_flag & os.ST_RDONLY
    assert not any(n.startswith(("pytest", "isaaclab_arena")) for n in sys.modules)
    assert not any(n.startswith("nvidia") or n == "dri" for n in os.listdir("/dev"))
    for family, address in (
        (socket.AF_INET, ("192.0.2.1", 443)),
        (socket.AF_INET6, ("2001:db8::1", 443)),
    ):
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            try:
                sock.connect(address)
            except OSError:
                pass
            else:
                raise AssertionError("kernel network isolation absent")
    manifest = json.loads(Path("/source/manifest.json").read_text())
    assert set(manifest) in (set(FILES), set(APPLICATION_FILES))
    for rel, digest in manifest.items():
        assert hashlib.sha256((Path("/source") / rel).read_bytes()).hexdigest() == digest
    return manifest


def install_guards(*, child_mode):
    forbidden = []
    native_popen = subprocess.Popen

    def pinned_popen(args, **kwargs):
        expected_kwargs = dict(
            cwd="/source",
            env={"PATH": "/usr/bin:/bin"},
            stdin=subprocess.PIPE if child_mode == "--owner" else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert child_mode in {"--owner", "--sleeper"}
        assert args == [sys.executable, "-I", "-S", "-B", "/source/" + SELF, child_mode]
        assert kwargs == expected_kwargs and all(type(kwargs[k]) is type(v) for k, v in expected_kwargs.items())
        return native_popen(args, **kwargs)

    def audit(event, args):
        if event in {"socket.bind", "socket.connect"}:
            sock, address = args
            if sock.family == socket.AF_UNIX and type(address) is str and address.startswith("/proc/self/fd/"):
                frame = sys._getframe(1)
                while frame and not frame.f_code.co_filename.startswith("/source/"):
                    frame = frame.f_back
                assert frame and frame.f_code.co_filename in {
                    "/source/" + CONTROL,
                    "/source/" + TEST,
                }
                assert os.statvfs(frame.f_code.co_filename).f_flag & os.ST_RDONLY
                target = Path(address).parent.resolve(strict=True)
                assert (
                    str(target).startswith(("/tmp/owner-stop-", "/tmp/pytest-of-"))
                    and target.stat().st_uid == os.getuid()
                )
                assert target.stat().st_mode & 0o777 == 0o700
                assert Path(address).name.startswith("stop-") and Path(address).suffix == ".sock"
                return
            forbidden.append(event)
            raise RuntimeError("nonlocal transport denied")
        if event in {
            "socket.getaddrinfo",
            "socket.sendto",
            "socket.sendmsg",
            "os.system",
            "os.fork",
            "os.exec",
        }:
            forbidden.append(event)
            raise RuntimeError("effect denied")
        if event == "subprocess.Popen":
            exe, args, cwd, env = args
            assert child_mode is not None
            assert args == [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "/source/" + SELF,
                child_mode,
            ]
            assert exe == sys.executable and cwd == "/source" and env == {"PATH": "/usr/bin:/bin"}

    sys.addaudithook(audit)
    subprocess.Popen = pinned_popen
    return forbidden


def inside(*, application=False):
    manifest = preflight()
    assert set(manifest) == set(APPLICATION_FILES if application else FILES)
    sys.path.insert(0, "/source")
    forbidden = install_guards(child_mode="--owner")
    import pytest

    result = pytest.main(
        [
            "-q",
            "-p",
            "no:cacheprovider",
            "--confcutdir=/source/isaaclab_arena_examples/tests",
            "--junitxml=/tmp/owner-stop-junit.xml",
            "/source/" + TEST,
        ] + (["/source/" + CANCELLATION_TEST] if application else [])
    )
    print(
        "CANCEL01_PROOF "
        + json.dumps(
            {
                "manifest": manifest,
                "forbidden": forbidden,
                "result": result,
                "junit": Path("/tmp/owner-stop-junit.xml").read_text(),
            }
        )
    )
    assert not forbidden
    return result


def owner():
    import signal
    import threading
    from types import SimpleNamespace

    signal.alarm(15)
    manifest = preflight()
    forbidden = install_guards(child_mode="--sleeper")
    sys.path.insert(0, "/source")
    from isaaclab_arena_examples.agentic_environment_generation.foreground_control import (
        OwnerStopServer,
    )
    application = CANCELLATION in manifest
    if application:
        from isaaclab_arena_examples.agentic_environment_generation.foreground_cancellation import (
            close_controls, start_owner_control, stop_requested,
        )

    with tempfile.TemporaryDirectory(prefix="owner-stop-") as root:
        child = subprocess.Popen(
            [sys.executable, "-I", "-S", "-B", "/source/" + SELF, "--sleeper"],
            cwd="/source",
            env={"PATH": "/usr/bin:/bin"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        stopped = threading.Event()

        def stop():
            stopped.set()
            child.terminate()
            child.wait(timeout=2)

        server = OwnerStopServer(root, run_id="run-1", principal="alice", scope="scope-1", stop=stop)
        def application_stop(principal):
            assert principal == "alice"
            stop()
            return SimpleNamespace(cleanup_pending=False)

        app = SimpleNamespace(
            private_parent=root, _lock=threading.RLock(), _closed=False,
            authority=SimpleNamespace(scope=dict(database="neo4j", deployment_id="test", workspace_id="private")),
            _local={"run-application": SimpleNamespace(
                principal="alice", retired=False, stopped=False, ports=None,
                coordinator=SimpleNamespace(stop_local=application_stop), handle=None,
            )},
        )
        try:
            assert child.stdout.readline() == b"ready\n"
            server.start()
            if application:
                start_owner_control(app, "alice", "run-application")
            print(
                json.dumps(dict(root=root, owner_pid=os.getpid(), child_pid=child.pid)),
                flush=True,
            )
            assert sys.stdin.buffer.readline() == b"finish\n"
            assert stopped.is_set() and child.poll() is not None
            try:
                raise ConnectionError("synthetic unavailable database after physical stop")
            except ConnectionError:
                db_unavailable = True
            print(
                json.dumps(
                    dict(
                        sticky_stop=stopped.is_set(),
                        application_sticky_stop=application and stop_requested(app, "run-application"),
                        child_reaped=child.poll() is not None,
                        db_unavailable=db_unavailable,
                        source_sha256=manifest,
                        forbidden=forbidden,
                    )
                ),
                flush=True,
            )
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=2)
            server.close()
            if application:
                close_controls(app)
    assert not forbidden


def sleeper():
    import signal
    import time

    signal.alarm(12)
    preflight()
    install_guards(child_mode=None)
    print("ready", flush=True)
    time.sleep(10)


if __name__ == "__main__":
    assert sys.argv[1:] in (["--sandbox"], ["--inside"], ["--owner"], ["--sleeper"],
                            ["--application-sandbox"], ["--application-inside"])
    if sys.argv[1] == "--application-sandbox":
        raise SystemExit(sandbox(application=True))
    if sys.argv[1] == "--application-inside":
        raise SystemExit(inside(application=True))
    if sys.argv[1] == "--sandbox":
        raise SystemExit(sandbox())
    if sys.argv[1] == "--inside":
        raise SystemExit(inside())
    if sys.argv[1] == "--owner":
        owner()
    else:
        sleeper()
