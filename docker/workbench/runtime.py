#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Non-root, stdlib-only process ownership helper executed inside existing Arena."""

import argparse
import fcntl
import http.client
import json
import os
import select
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from workbench import api_command


def inherited_api_command(state, socket_path, origin, diagnostics):
    """Track the Python API itself; this helper already inherited Isaac's shell environment."""
    command = api_command(state, socket_path, origin, diagnostics)
    command[0] = sys.executable
    return command


def wait_for_release(stream, timeout=10):
    """Release a Docker-held lock on explicit release or missing host heartbeat."""
    pending = b""
    while select.select([stream], [], [], timeout)[0]:
        chunk = os.read(stream.fileno(), 4096)
        if not chunk:
            return False
        pending += chunk
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            if line != b"KEEPALIVE":
                return line == b"RELEASE"
        if len(pending) > 4096:
            return False
    return False


@contextmanager
def control_lock(state):
    """Serialize complete host start/stop operations on host-backed state."""
    fd = os.open(state / "control.lock", os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another workbench lifecycle operation is in progress") from error
        yield


@contextmanager
def supervisor_lock(state):
    """Use a distinct lock from the backend's authoritative launcher.lock."""
    fd = os.open(state / "process-supervisor.lock", os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another workbench process supervisor owns this state") from error
        yield


def process_start(pid):
    """Read Linux's process start tick without being confused by spaces in comm."""
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]


def owned_process(state):
    """Validate UID, start time and exact supervisor arguments, never a bare PID."""
    try:
        record = json.loads((state / "launcher.json").read_text())
        pid = int(record["pid"])
        proc = Path(f"/proc/{pid}")
        argv = (proc / "cmdline").read_bytes().decode().rstrip("\0").split("\0")
        expected = [str(Path(__file__).resolve()), "serve", "--state-dir", str(state)]
        if proc.stat().st_uid != os.getuid() or process_start(pid) != record["start"]:
            return None
        if not any(argv[i : i + len(expected)] == expected for i in range(len(argv))):
            return None
        return record
    except (OSError, ValueError, KeyError, IndexError):
        return None


def stop(state):
    """Signal only a verified workbench supervisor through a race-safe pidfd."""
    record = owned_process(state)
    if not record:
        return False
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise RuntimeError("Safe process stop requires Linux pidfd support; no unsafe PID-kill fallback")
    try:
        fd = os.pidfd_open(record["pid"])
    except ProcessLookupError:
        return False
    try:
        if owned_process(state) != record:
            raise RuntimeError("Supervisor identity changed; refusing to signal")
        signal.pidfd_send_signal(fd, signal.SIGTERM)
        for _ in range(150):
            if not owned_process(state):
                return True
            time.sleep(0.1)
        raise RuntimeError("Workbench supervisor did not stop; dependencies were not touched")
    finally:
        os.close(fd)


def private_directory(path, mode):
    """Create an owned directory without accepting symlinks or broad permissions."""
    for parent in [*reversed(path.parents), path]:
        if parent.is_symlink():
            raise RuntimeError(f"Refusing symlink in workbench storage: {parent}")
    path.mkdir(mode=mode, parents=False, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_gid != os.getgid():
        raise RuntimeError(f"Storage must be owned by API UID:GID {os.getuid()}:{os.getgid()}: {path}")
    if stat.S_IMODE(info.st_mode) != mode:
        raise RuntimeError(f"Expected mode {mode:o} on {path}; fix permissions explicitly")


def prepare(state, socket_path):
    """Create only this clone's private state and group-readable IPC directory."""
    if os.getuid() == 0 or os.getgid() == 0:
        raise RuntimeError("Workbench API lifecycle must run non-root")
    if state.name != "state" or socket_path.name != "api.sock" or socket_path.parent.name != "ipc":
        raise RuntimeError("Expected sibling state/ and ipc/api.sock paths")
    if state.parent != socket_path.parent.parent or not state.is_absolute():
        raise RuntimeError("State and IPC must share an absolute clone-local parent")
    if len(str(socket_path).encode()) >= 104:
        raise RuntimeError("Unix socket path too long")
    old_umask = os.umask(0o027)
    try:
        private_directory(state.parent.parent, 0o750)
        private_directory(state.parent, 0o750)
        private_directory(state, 0o700)
        private_directory(socket_path.parent, 0o750)
    finally:
        os.umask(old_umask)


def health(socket_path, origin):
    """Check the actual public API health endpoint over Unix HTTP only."""
    connection = http.client.HTTPConnection(urlsplit(origin).netloc, timeout=1)
    try:
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.sock.settimeout(1)
        connection.sock.connect(str(socket_path))
        connection.request("GET", "/api/health")
        response = connection.getresponse()
        return response.status == 200 and json.loads(response.read())["status"] == "ok"
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def preflight(state, socket_path, port):
    """Verify IPC/SQLite/locking support and fail rather than weaken transport."""
    prepare(state, socket_path)
    if socket_path.exists() or socket_path.is_symlink():
        raise RuntimeError("API socket already exists; refusing unsafe unlink or adopting another launcher")
    if port:
        with socket.socket() as listener:
            try:
                listener.bind(("127.0.0.1", port))
            except OSError as error:
                raise RuntimeError(f"Host loopback port {port} is unavailable; use --port") from error
    with tempfile.TemporaryDirectory(prefix="probe-", dir=state) as directory:
        database = Path(directory) / "probe.sqlite3"
        with sqlite3.connect(database) as first, sqlite3.connect(database, timeout=0) as second:
            first.execute("PRAGMA journal_mode=WAL")
            first.execute("CREATE TABLE probe (value INTEGER)")
            first.commit()
            first.execute("BEGIN IMMEDIATE")
            try:
                second.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                if "locked" not in str(error):
                    raise
            else:
                raise RuntimeError("State filesystem did not enforce SQLite writer locking")
            first.rollback()
    with tempfile.TemporaryDirectory(prefix="probe-", dir=socket_path.parent) as directory:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(Path(directory) / "s"))
    print(json.dumps({"preflight": "ok", "uid": os.getuid(), "gid": os.getgid()}))


def serve(args):
    """Own exactly one API child process group until graceful shutdown completes."""
    state, socket_path = Path(args.state_dir), Path(args.socket)
    prepare(state, socket_path)
    os.umask(0o077)
    with supervisor_lock(state):
        if socket_path.exists() or socket_path.is_symlink():
            raise RuntimeError("Socket already exists; refusing unsafe unlink")
        child = None
        stopping = False

        def shutdown(signum, frame):
            nonlocal stopping
            stopping = True
            if child is not None and child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        record = {
            "pid": os.getpid(),
            "start": process_start(os.getpid()),
            "origin": args.origin,
            "diagnostics": args.diagnostics,
        }
        marker = state / "launcher.json"
        marker.write_text(json.dumps(record))
        try:
            with (state / "launcher.log").open("ab", buffering=0) as log:
                if stopping:
                    return
                child = subprocess.Popen(
                    inherited_api_command(str(state), str(socket_path), args.origin, args.diagnostics),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                while child.poll() is None:
                    if stopping:
                        try:
                            child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait()
                    else:
                        time.sleep(0.1)
                if child.returncode and not stopping:
                    raise RuntimeError(f"API exited with status {child.returncode}; see private launcher.log")
        finally:
            if child is not None and child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=10)
            marker.unlink(missing_ok=True)
        # Backend owns socket cleanup; this helper never unlinks a socket.


def main():
    """Run one private lifecycle operation; never start a simulator or dependency."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preflight", "serve", "status", "stop", "lock"])
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if os.getuid() == 0 or os.getgid() == 0:
        raise RuntimeError("Workbench lifecycle must run non-root")
    state, socket_path = Path(args.state_dir), Path(args.socket)
    if args.action == "lock":
        prepare(state, socket_path)
        with control_lock(state):
            print("READY", flush=True)
            wait_for_release(sys.stdin)
    elif args.action == "status":
        record = owned_process(state)
        print(json.dumps({"owned": bool(record), "healthy": health(socket_path, args.origin), "supervisor": record}))
    elif args.action == "stop":
        print(json.dumps({"stopped": stop(state)}))
    elif args.action == "preflight":
        preflight(state, socket_path, args.port)
    else:
        serve(args)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as error:
        print(f"workbench runtime: {error}", file=sys.stderr)
        sys.exit(1)
