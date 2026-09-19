# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Actual Linux UDS owner-local stop; no model, database, or arbitrary PID port."""

import ast
import importlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from threading import Event, RLock
from types import SimpleNamespace

import pytest


def control():
    return importlib.import_module("isaaclab_arena_examples.agentic_environment_generation.foreground_control")


def test_fresh_clients_stop_before_ack_and_repeat_idempotently(tmp_path):
    module = control()
    assert hasattr(module, "OwnerStopServer"), "CANCEL-01 authenticated owner stop transport missing"
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    calls = []
    server = module.OwnerStopServer(
        root,
        run_id="run-1",
        principal="alice",
        scope="scope-1",
        stop=lambda: calls.append(1),
    )
    assert server.start() is server
    try:
        for _ in range(2):
            receipt = module.request_owner_stop(root, run_id="run-1", principal="alice", scope="scope-1", timeout_s=2)
            assert receipt == {
                "delivery": "delivered",
                "remote_effects": "unknown",
                "durable_cancellation": "unconfirmed",
            }
            assert calls == [1]
    finally:
        server.close()
        server.close()
    assert module.request_owner_stop(root, run_id="run-1", principal="alice", scope="scope-1")["delivery"] == "no_owner"


def test_coordinator_local_stop_has_no_authority_or_database_callback():
    # Execute exact captured coordinator methods, without importing its unrelated
    # DB/schema dependency closure. This is a local-method unit, not DB evidence.
    source = Path("/source/isaaclab_arena/agentic_environment_generation/workflow/coordinator.py")
    tree = ast.parse(source.read_text())
    coordinator = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GenerationCoordinator")
    selected = [n for n in coordinator.body if isinstance(n, ast.FunctionDef) and n.name in {"stop_local", "cancel"}]
    assert any(n.name == "stop_local" for n in selected), "DB-independent stop_local missing"
    namespace = {
        "StopResult": lambda durable, cleanup: SimpleNamespace(
            durable_cancellation_pending=durable, cleanup_pending=cleanup
        )
    }
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"),
        namespace,
    )
    calls = []

    def forbidden(*args):
        raise AssertionError("Database/authority must not prevent owned stop")

    obj = SimpleNamespace(
        _principal="alice",
        _lock=RLock(),
        _preparing=False,
        _handle=None,
        _cancelled=False,
        _stop=lambda: calls.append("physical"),
        _authenticate=forbidden,
        _store=SimpleNamespace(get_run=forbidden),
    )
    result = namespace["stop_local"](obj, "alice")
    assert obj._cancelled and calls == ["physical"]
    assert result.durable_cancellation_pending and not result.cleanup_pending
    with pytest.raises(PermissionError):
        namespace["stop_local"](obj, "rogue")
    assert calls == ["physical"]
    obj._authenticate = lambda principal: calls.append("auth")
    obj._run_id = "run-1"
    obj.stop_local = lambda principal: namespace["stop_local"](obj, principal)

    def db_failure(run_id):
        calls.append("db")
        raise ConnectionError("unavailable")

    obj._store.get_run = db_failure
    result = namespace["cancel"](obj, "alice")
    assert calls == ["physical", "auth", "physical", "db"]
    assert result.durable_cancellation_pending and not result.cleanup_pending
    obj._preparing = True

    def stop_failure():
        calls.append("stop-failed")
        raise RuntimeError("uncertain owned stop")

    obj._stop = stop_failure
    result = namespace["cancel"](obj, "alice")
    assert calls[-1] == "stop-failed", "cancel must preserve early return on stop failure"
    assert result.cleanup_pending


def test_distinct_owner_process_stops_real_owned_child_without_database(tmp_path):
    module = control()
    helper = "/source/isaaclab_arena_examples/tests/foreground_control_fixture.py"
    proc = subprocess.Popen(
        [sys.executable, "-I", "-S", "-B", helper, "--owner"],
        cwd="/source",
        env={"PATH": "/usr/bin:/bin"},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        first = proc.stdout.readline()
        assert first, "Fixed distinct owner fixture unavailable"
        info = json.loads(first)
        assert info["owner_pid"] == proc.pid != os.getpid()
        assert Path(f'/proc/{info["child_pid"]}').exists()
        directory = module._Directory(info["root"])
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(2)
                sock.connect(directory.address(module._name(dict(run_id="run-1", principal="alice", scope="scope-1"))))
                challenge = json.loads(sock.recv(4096))["challenge"]
                sock.sendall(
                    json.dumps(
                        dict(
                            action="stop",
                            challenge=challenge,
                            run_id="run-1",
                            principal="alice",
                            scope="scope-1",
                            pid=proc.pid,
                        )
                    ).encode()
                    + b"\n"
                )
                assert sock.recv(4096) == b""
        finally:
            directory.close()
        assert proc.poll() is None and Path(f'/proc/{info["child_pid"]}').exists()
        assert (
            module.request_owner_stop(info["root"], run_id="rogue", principal="alice", scope="scope-1")["delivery"]
            == "no_owner"
        )
        assert Path(f'/proc/{info["child_pid"]}').exists()
        receipt = module.request_owner_stop(info["root"], run_id="run-1", principal="alice", scope="scope-1")
        assert receipt["delivery"] == "delivered"
        proc.stdin.write(b"finish\n")
        proc.stdin.flush()
        out, err = proc.communicate(timeout=5)
        assert proc.returncode == 0, err.decode()
        final = json.loads(out)
        assert final["sticky_stop"] and final["child_reaped"] and final["db_unavailable"]
        assert final["forbidden"] == []
        assert final["source_sha256"] == json.loads(Path("/source/manifest.json").read_text())
        assert not Path(f'/proc/{info["child_pid"]}').exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def server_at(root, callback):
    root.mkdir(mode=0o700)
    return control().OwnerStopServer(root, run_id="run-1", principal="alice", scope="scope-1", stop=callback).start()


def raw(server):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(3)
    sock.connect(server._directory.address(server._name))
    hello = json.loads(sock.recv(4096))
    return sock, dict(
        action="stop",
        challenge=hello["challenge"],
        run_id="run-1",
        principal="alice",
        scope="scope-1",
    )


@pytest.mark.parametrize(
    "change",
    [
        {"run_id": "rogue"},
        {"principal": "rogue"},
        {"scope": "rogue"},
        {"pid": 1},
        {"action": "kill"},
    ],
)
def test_exact_wire_binding_rejects_rogue_ids_and_pid_commands(tmp_path, change):
    calls = []
    server = server_at(tmp_path / "private", lambda: calls.append(1))
    try:
        sock, packet = raw(server)
        with sock:
            packet.update(change)
            sock.sendall(json.dumps(packet).encode() + b"\n")
            assert sock.recv(4096) == b""
        assert not calls
    finally:
        server.close()


def test_connection_challenge_rejects_replay_and_oversize(tmp_path):
    calls = []
    server = server_at(tmp_path / "private", lambda: calls.append(1))
    try:
        sock, original = raw(server)
        with sock:
            sock.sendall(json.dumps(original).encode() + b"\n")
            assert json.loads(sock.recv(4096))["delivery"] == "delivered"
        sock, _ = raw(server)
        with sock:
            sock.sendall(json.dumps(original).encode() + b"\n")
            assert sock.recv(4096) == b""
        sock, _ = raw(server)
        with sock:
            sock.sendall(b"x" * 4097)
            assert sock.recv(4096) == b""
        assert calls == [1]
    finally:
        server.close()


def test_long_private_path_and_bounded_unicode_bindings(tmp_path):
    root = tmp_path / ("p" * 100) / ("q" * 100)
    root.mkdir(parents=True, mode=0o700)
    binding = dict(run_id="😀" * 128, principal="😀" * 128, scope="😀" * 128)
    server = control().OwnerStopServer(root, **binding, stop=lambda: None).start()
    try:
        assert control().request_owner_stop(root, **binding)["delivery"] == "delivered"
    finally:
        server.close()


def test_callback_fault_never_acknowledges_and_fresh_retry_is_possible(tmp_path):
    attempts = []

    def stop():
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("must-not-appear-in-public-receipt")

    root = tmp_path / "private"
    server = server_at(root, stop)
    try:
        binding = dict(run_id="run-1", principal="alice", scope="scope-1")
        failed = control().request_owner_stop(root, **binding)
        assert failed["delivery"] == "unconfirmed" and "must-not" not in repr(failed)
        assert control().request_owner_stop(root, **binding)["delivery"] == "delivered"
        assert attempts == [1, 1]
    finally:
        server.close()


def test_no_ack_before_local_stop_settles_and_client_deadline_is_bounded(tmp_path):
    entered, finish = Event(), Event()

    def stop():
        entered.set()
        assert finish.wait(3)

    root = tmp_path / "private"
    server = server_at(root, stop)
    start = time.monotonic()
    try:
        result = control().request_owner_stop(root, run_id="run-1", principal="alice", scope="scope-1", timeout_s=0.1)
        assert entered.is_set() and result["delivery"] == "unconfirmed"
        assert time.monotonic() - start < 1
    finally:
        finish.set()
        server.close()


def test_private_path_modes_symlinks_and_live_inode_drift_fail_closed(tmp_path):
    root = tmp_path / "private"
    calls = []
    server = server_at(root, lambda: calls.append(1))
    binding = dict(run_id="run-1", principal="alice", scope="scope-1")
    try:
        link = tmp_path / "link"
        link.symlink_to(root, target_is_directory=True)
        assert control().request_owner_stop(link, **binding)["delivery"] == "unconfirmed"
        root.chmod(0o755)
        assert control().request_owner_stop(root, **binding)["delivery"] == "unconfirmed"
        root.chmod(0o700)
        sock, packet = raw(server)
        endpoint = root / server._name
        endpoint.unlink()
        endpoint.write_text("not a socket")
        with sock:
            sock.sendall(json.dumps(packet).encode() + b"\n")
            assert sock.recv(4096) == b""
        assert control().request_owner_stop(root, **binding)["delivery"] == "unconfirmed"
        assert not calls
    finally:
        server.close()
    assert endpoint.read_text() == "not a socket"


def test_peer_credentials_observed_from_kernel_and_wrong_uid_rejected(tmp_path, monkeypatch):
    module = control()
    seen = []
    actual_peer = module._peer

    def wrong_uid(sock, uid):
        pid, peer_uid, gid = module.struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        assert peer_uid == os.geteuid() and pid == os.getpid()
        seen.append((pid, peer_uid, gid))
        actual_peer(sock, uid + 1)  # synthetic foreign UID at the real credential boundary

    monkeypatch.setattr(module, "_peer", wrong_uid)
    calls = []
    root = tmp_path / "private"
    server = server_at(root, lambda: calls.append(1))
    try:
        assert (
            module.request_owner_stop(root, run_id="run-1", principal="alice", scope="scope-1")["delivery"]
            == "unconfirmed"
        )
        assert seen and not calls
    finally:
        server.close()


def test_inherited_server_cannot_unlink_original_owner_endpoint(tmp_path, monkeypatch):
    root = tmp_path / "private"
    server = server_at(root, lambda: None)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(server, "_pid", os.getpid() + 1)
            with pytest.raises(PermissionError):
                server.close()
        assert (root / server._name).exists()
        assert (
            control().request_owner_stop(root, run_id="run-1", principal="alice", scope="scope-1")["delivery"]
            == "delivered"
        )
    finally:
        server.close()


def test_duplicate_wire_keys_and_duplicate_live_server_fail_closed(tmp_path):
    calls = []
    root = tmp_path / "private"
    server = server_at(root, lambda: calls.append(1))
    try:
        with pytest.raises(OSError):
            control().OwnerStopServer(
                root,
                run_id="run-1",
                principal="alice",
                scope="scope-1",
                stop=lambda: None,
            ).start()
        sock, packet = raw(server)
        with sock:
            data = json.dumps(packet)[:-1] + ', "principal":"alice"}\n'
            sock.sendall(data.encode())
            assert sock.recv(4096) == b""
        assert not calls
        assert (
            control().request_owner_stop(root, run_id="run-1", principal="alice", scope="scope-1")["delivery"]
            == "delivered"
        )
        assert calls == [1]
    finally:
        server.close()
