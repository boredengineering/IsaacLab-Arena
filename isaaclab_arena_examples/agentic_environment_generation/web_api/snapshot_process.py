# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Owned, bounded Unix RPC transport; imports no simulator libraries."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from .owned_process_group import OwnedProcessGroup


def gpu_lease_path() -> Path:
    """Use shared host-backed storage so separate clone containers cooperate."""
    path = Path(os.environ.get("ARENA_WORKBENCH_GPU_LEASE", "/eval/.arena-workbench-gpu.lock"))
    if not path.is_absolute():
        raise ValueError("ARENA_WORKBENCH_GPU_LEASE must be an absolute shared path")
    return path


GPU_LEASE = gpu_lease_path()
MAX_REPLY = 2 * 1024 * 1024


def watch_parent(owner_fd: int) -> None:
    """Kill the entire owned session on API death, including during Kit native hangs."""
    if os.getpgrp() != os.getpid():
        raise RuntimeError("Snapshot worker requires its own process group")

    def watch():
        try:
            while os.read(owner_fd, 1):
                pass
        finally:
            os.killpg(os.getpgrp(), signal.SIGKILL)

    threading.Thread(target=watch, name="snapshot-owner-watch", daemon=True).start()


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Snapshot deadline exceeded")
    return remaining


class SnapshotProcess:
    """Hold the global GPU lease for the entire lifetime of a reusable SimApp."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.proc: subprocess.Popen | None = None
        self.socket_path: Path | None = None
        self.log_path: Path | None = None
        self._short_dir: Path | None = None
        self._owner_fd: int | None = None
        self._lease_fd: int | None = None
        self._socket: socket.socket | None = None
        self._start_lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._closing = threading.Event()

    def _command(self) -> list[str]:
        return [sys.executable, "-m", "isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_worker"]

    def _exited(self) -> bool:
        # WNOWAIT reserves the child's PID until group cleanup, unlike Popen.poll().
        # Never reap a group leader before signalling its remaining descendants.
        proc = self.proc
        return proc is None or os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None

    def _start(self, deadline: float, emit: Callable[[str], None]) -> None:
        with self._start_lock:
            if self._closing.is_set():
                raise RuntimeError("Snapshot renderer is closed")
            if self.proc is not None:
                if self._exited():
                    raise RuntimeError("Isaac Sim exited; retry the snapshot job")
                return
            if os.getuid() == 0 or os.getgid() == 0:
                raise RuntimeError("Run the snapshot API non-root in the Arena container (ubuntu:1234)")
            emit("waiting_for_gpu_lease")
            self._lease_fd = os.open(GPU_LEASE, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            info = os.fstat(self._lease_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise RuntimeError("GPU lease is not owned by this runtime user")
            while True:
                try:
                    fcntl.flock(self._lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if self._closing.is_set() or deadline <= time.monotonic():
                        raise TimeoutError(
                            "GPU lease unavailable: another editor renderer owns the GPU; close it and retry"
                        )
                    time.sleep(min(0.05, _remaining(deadline)))
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._short_dir = Path(tempfile.mkdtemp(prefix="as-", dir="/tmp"))
            self.socket_path = self._short_dir / "rpc.sock"
            token = uuid.uuid4().hex
            self.log_path = self.root / f"renderer-{token}.log"
            temp = self.root / "runtime" / token / "tmp"
            temp.mkdir(parents=True, mode=0o700)
            environment = os.environ.copy()
            environment.update(OMNICLIENT_HUB_MODE="disabled", TMPDIR=str(temp), PYTHONUNBUFFERED="1")
            reader, self._owner_fd = os.pipe()
            command = [
                *self._command(),
                "--socket",
                str(self.socket_path),
                "--root",
                str(self.root),
                "--owner-fd",
                str(reader),
            ]
            emit("booting_simapp")
            try:
                with self.log_path.open("xb") as log:
                    log.write(
                        (json.dumps({"command": command, "tmpdir": str(temp), "hub": "disabled"}) + "\n").encode()
                    )
                    log.flush()
                    self.proc = subprocess.Popen(
                        command,
                        env=environment,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        start_new_session=True,
                        pass_fds=(reader, self._lease_fd),
                    )
                (self.root / f"renderer-{token}.json").write_text(
                    json.dumps({
                        "pid": self.proc.pid,
                        "socket": str(self.socket_path),
                        "log": str(self.log_path),
                        "start_ticks": Path(f"/proc/{self.proc.pid}/stat").read_text().rsplit(")", 1)[1].split()[19],
                    })
                )
            finally:
                os.close(reader)

    def request(self, request: dict, deadline: float, emit: Callable[[str], None]) -> dict:
        """Read real stage frames followed by one result, bounded by an absolute deadline."""
        if not self._request_lock.acquire(timeout=_remaining(deadline)):
            raise TimeoutError("Snapshot RPC serialization deadline exceeded")
        try:
            self._start(deadline, emit)
            while True:
                if self._closing.is_set():
                    raise RuntimeError("Snapshot renderer closed")
                if self._exited():
                    raise RuntimeError("Isaac Sim failed during startup")
                conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                conn.settimeout(min(0.5, _remaining(deadline)))
                try:
                    conn.connect(str(self.socket_path))
                    break
                except (FileNotFoundError, ConnectionRefusedError):
                    conn.close()
                    time.sleep(min(0.05, _remaining(deadline)))
                except BaseException:
                    conn.close()
                    raise
            self._socket = conn
            with conn:
                conn.settimeout(_remaining(deadline))
                conn.sendall((json.dumps(request) + "\n").encode())
                pending = b""
                received = 0
                while True:
                    conn.settimeout(_remaining(deadline))
                    chunk = conn.recv(65536)
                    if not chunk:
                        raise RuntimeError("Isaac Sim closed its RPC socket before completing the snapshot")
                    pending += chunk
                    received += len(chunk)
                    if received > MAX_REPLY:
                        raise RuntimeError("Snapshot RPC reply exceeds its bounded size")
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        response = json.loads(line)
                        if not isinstance(response, dict):
                            raise RuntimeError("Invalid snapshot RPC response")
                        if "stage" in response:
                            emit(str(response["stage"]))
                        else:
                            return response
        except BaseException as exc:
            self._stop()
            if not isinstance(exc, Exception):
                raise
            raise RuntimeError(
                f"Isaac Sim snapshot unavailable: {exc}. Run in the non-root Arena runtime with GPU access; "
                f"check renderer log {self.log_path or '(not started)'}."
            ) from exc
        finally:
            self._socket = None
            self._request_lock.release()

    def _stop(self) -> None:
        with self._start_lock:
            if self._socket is not None:
                with contextlib.suppress(OSError):
                    self._socket.shutdown(socket.SHUT_RDWR)
                self._socket.close()
            if self.proc is not None:
                # TERM is bounded: Kit can override signal handlers or hang inside native shutdown.
                # The unreaped leader anchors identity even after exit. Do not release the
                # GPU lease merely because the leader died while a descendant is alive.
                OwnedProcessGroup(self.proc.pid).stop(term_timeout=1, kill_timeout=2)
                self.proc.wait(timeout=2)
                self.proc = None
            if self._owner_fd is not None:
                os.close(self._owner_fd)
                self._owner_fd = None
            if self._lease_fd is not None:
                os.close(self._lease_fd)
                self._lease_fd = None
            if self._short_dir is not None:
                logs = self._short_dir / "kit" / "logs"
                if logs.exists() and self.log_path is not None:
                    shutil.copytree(logs, self.log_path.with_suffix(".kit-logs"), dirs_exist_ok=True)
                shutil.rmtree(self._short_dir, ignore_errors=True)
                self._short_dir = None

    def close(self) -> None:
        """Interrupt active reads and reap only this instance's owned process group."""
        self._closing.set()
        self._stop()
