# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Authenticated owner-local stop, not durable cancellation or cleanup evidence.

Frozen integration API:
    OwnerStopServer(private_parent, *, run_id, principal, scope, stop).start()
    OwnerStopServer.close()
    request_owner_stop(private_parent, *, run_id, principal, scope, timeout_s=5.0)

start returns self; close is idempotent. private_parent is an existing non-root
UID-owned mode-0700 directory with controlled, nonsymlink ancestors. run_id,
principal and scope are nonempty bounded strings (scope is a canonical opaque
application scope identifier, not a dict). The endpoint name is derived from all
three; callers must provide the same frozen values. No persisted credentials.

The trusted zero-argument stop callback MUST latch the run-level sticky stop and
stop all currently owned work before returning; it MUST NOT access DB/model APIs.
An exception yields unconfirmed delivery, never an ACK. Repeat fresh requests are
idempotent after successful stop. Callback results are discarded, never serialized.
A callback wrapping coordinator.stop_local MUST raise if cleanup_pending is true.

Client returns a JSON-safe dict with exactly:
    delivery: 'delivered' | 'unconfirmed' | 'no_owner'
    remote_effects: 'unknown'
    durable_cancellation: 'unconfirmed'
No receipt is WorkerPort.cleanup_verified evidence or claims DB cancellation.
Client timeout bounds delivery observation, not a possibly running owner callback.
Path/peer/protocol failures return unconfirmed; only absent/refused valid endpoints
return no_owner. Invalid API arguments raise ValueError. close never stops work or
retires ownership; application composition owns those obligations separately.

Linux filesystem AF_UNIX/SO_PEERCRED only. fd-relative /proc/self/fd endpoint paths
avoid sun_path length limits; no abstract sockets, PID commands, dynamic callbacks,
secret-file reads, daemon, HTTP, database or model imports.

Harness admission: bind/connect use /proc/self/fd/<owned-directory-fd>/stop-<40
lowercase hex>.sock; listen is on that AF_UNIX/SOCK_STREAM descriptor only. Keep
ordinary network-denying profiles unchanged; admit this captured module only in
the exact foreground profile and validate the descriptor's private root.
"""

import hashlib
import json
import math
import os
import secrets
import socket
import stat
import struct
import threading
import time
from contextlib import suppress
from pathlib import Path

_LIMIT = 4096


def _binding(run_id, principal, scope):
    values = (run_id, principal, scope)
    if any(type(v) is not str or not v or len(v.encode("utf-8")) > 512 for v in values):
        raise ValueError("Bounded exact owner binding required")
    return dict(run_id=run_id, principal=principal, scope=scope)


def _name(binding):
    digest = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return "stop-" + digest[:40] + ".sock"


def _identity(info):
    return info.st_dev, info.st_ino


class _Directory:
    def __init__(self, path):
        self.path = Path(path).absolute()
        self.uid = os.geteuid()
        self.fd = None
        if self.uid == 0 or ".." in self.path.parts:
            raise ValueError("Nonroot private parent required")
        self.fd, self.identities = self._open()

    def _open(self):
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        identities = []
        try:
            for part in self.path.parts[1:]:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=fd,
                )
                os.close(fd)
                fd = child
                info = os.fstat(fd)
                if info.st_uid not in (0, self.uid) or (
                    info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX)
                ):
                    raise ValueError("Uncontrolled private path")
                identities.append(_identity(info))
            info = os.fstat(fd)
            if info.st_uid != self.uid or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError("Private parent must be UID-owned mode 0700")
            return fd, identities
        except BaseException:
            os.close(fd)
            raise

    def check(self):
        fd, identities = self._open()
        try:
            if identities != self.identities or _identity(os.fstat(self.fd)) != _identity(os.fstat(fd)):
                raise ValueError("Private path changed")
        finally:
            os.close(fd)

    def address(self, name):
        return f"/proc/self/fd/{self.fd}/{name}"

    def endpoint(self, name):
        self.check()
        info = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        if (
            not stat.S_ISSOCK(info.st_mode)
            or info.st_uid != self.uid
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise ValueError("Untrusted stop endpoint")
        return _identity(info)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _peer(sock, uid):
    _pid, actual, _gid = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if actual != uid:
        raise PermissionError("Owner UID required")


def _remaining(sock, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Stop delivery deadline")
    sock.settimeout(remaining)


def _send(sock, message, deadline):
    data = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
    if len(data) > _LIMIT:
        raise ValueError("Stop packet too large")
    _remaining(sock, deadline)
    sock.sendall(data)


def _receive(sock, deadline):
    data = bytearray()
    while b"\n" not in data:
        _remaining(sock, deadline)
        chunk = sock.recv(_LIMIT + 1 - len(data))
        if not chunk:
            raise ValueError("Stop packet truncated")
        data.extend(chunk)
        if len(data) > _LIMIT:
            raise ValueError("Stop packet too large")
    if data[-1:] != b"\n" or data.count(b"\n") != 1:
        raise ValueError("One stop packet required")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate stop field")
            result[key] = value
        return result

    packet = json.loads(data, object_pairs_hook=unique)
    if type(packet) is not dict:
        raise ValueError("Stop object required")
    return packet


def _receipt(delivery):
    return dict(delivery=delivery, remote_effects="unknown", durable_cancellation="unconfirmed")


class OwnerStopServer:
    """One ephemeral thread owned by the existing foreground process."""

    def __init__(self, private_parent, *, run_id, principal, scope, stop):
        self._binding = _binding(run_id, principal, scope)
        if not callable(stop):
            raise ValueError("Trusted local stop callback required")
        self._parent, self._stop = private_parent, stop
        self._name = _name(self._binding)
        self._directory = self._socket = self._thread = None
        self._inode = None
        self._closed = threading.Event()
        self._stopped = False
        self._pid = os.getpid()

    def start(self):
        """Bind exclusively before publishing admission; never remove stale endpoints."""
        if self._thread is not None or self._closed.is_set() or os.getpid() != self._pid:
            raise ValueError("Owner stop lifecycle already started or closed")
        self._directory = _Directory(self._parent)
        try:
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._socket.bind(self._directory.address(self._name))
            os.chmod(self._name, 0o600, dir_fd=self._directory.fd, follow_symlinks=False)
            self._inode = self._directory.endpoint(self._name)
            self._socket.listen(4)
            self._socket.settimeout(0.1)
            self._thread = threading.Thread(target=self._serve, name="foreground-owner-stop", daemon=True)
            self._thread.start()
            return self
        except BaseException:
            self.close()
            raise

    def _check(self):
        if self._closed.is_set() or os.getpid() != self._pid or self._directory.endpoint(self._name) != self._inode:
            raise ValueError("Stop owner path changed")

    def _serve(self):
        while not self._closed.is_set():
            try:
                conn, _ = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with conn:
                try:
                    deadline = time.monotonic() + 2.0
                    _peer(conn, self._directory.uid)
                    self._check()
                    challenge = secrets.token_hex(16)
                    _send(conn, {"challenge": challenge}, deadline)
                    packet = _receive(conn, deadline)
                    if packet != {
                        "action": "stop",
                        "challenge": challenge,
                        **self._binding,
                    }:
                        raise ValueError("Stop binding mismatch")
                    self._check()
                    if not self._stopped:
                        self._stop()
                        self._stopped = True
                    self._check()
                    _send(
                        conn,
                        {"challenge": challenge, "delivery": "delivered"},
                        deadline,
                    )
                except Exception:
                    # No exception details or callback objects cross the public boundary.
                    pass

    def close(self):
        """Remove only this exact endpoint; never imply worker cleanup."""
        if os.getpid() != self._pid:
            raise PermissionError("Original stop owner process required")
        self._closed.set()
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.1)
        if self._directory is not None and self._directory.fd is not None:
            try:
                with suppress(OSError, ValueError):
                    if self._inode is not None and self._directory.endpoint(self._name) == self._inode:
                        os.unlink(self._name, dir_fd=self._directory.fd)
            finally:
                self._directory.close()


def request_owner_stop(private_parent, *, run_id, principal, scope, timeout_s=5.0):
    """Observe local delivery only; database and remote effects remain unconfirmed."""
    binding = _binding(run_id, principal, scope)
    if type(timeout_s) not in (float, int) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 30:
        raise ValueError("Stop timeout must be finite and in (0, 30]")
    deadline = time.monotonic() + timeout_s
    directory = None
    try:
        directory = _Directory(private_parent)
        name = _name(binding)
        try:
            inode = directory.endpoint(name)
        except FileNotFoundError:
            return _receipt("no_owner")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            _remaining(sock, deadline)
            try:
                sock.connect(directory.address(name))
            except ConnectionRefusedError:
                return _receipt("no_owner")
            _peer(sock, directory.uid)
            if directory.endpoint(name) != inode:
                raise ValueError("Stop endpoint changed")
            hello = _receive(sock, deadline)
            challenge = hello.get("challenge")
            if set(hello) != {"challenge"} or type(challenge) is not str or len(challenge) != 32:
                raise ValueError("Invalid stop challenge")
            _send(sock, {"action": "stop", "challenge": challenge, **binding}, deadline)
            ack = _receive(sock, deadline)
            if ack != {"challenge": challenge, "delivery": "delivered"} or directory.endpoint(name) != inode:
                raise ValueError("Invalid stop acknowledgement")
            return _receipt("delivered")
    except (OSError, ValueError):
        return _receipt("unconfirmed")
    finally:
        if directory is not None:
            directory.close()
