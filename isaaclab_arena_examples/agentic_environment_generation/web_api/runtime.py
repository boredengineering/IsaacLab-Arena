# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Linux-local non-root ownership, exclusive state locks and safe Unix listeners."""

import errno
import fcntl
import os
import socket
import stat
from pathlib import Path


def validate_layout(state_dir, socket_path):
    """Keep private state outside the directory shared with the frontend."""
    state = Path(state_dir).resolve()
    ipc = Path(socket_path).resolve().parent
    if state == ipc or state in ipc.parents or ipc in state.parents:
        raise ValueError("Private state and IPC must use separate, non-overlapping directories")


def controlled_directory(path, mode):
    """Create an owned directory without following symlink components."""
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise RuntimeError("Symlink directory components are not allowed")
    path.mkdir(mode=mode, parents=True, exist_ok=True)
    if not path.is_dir() or path.stat().st_uid != os.geteuid():
        raise RuntimeError("Directory must be owned by the non-root API user")
    path.chmod(mode)
    return path


class FileLease:
    """Hold a non-inherited flock on a regular, owned, non-symlink file."""

    def __init__(self, path):
        self.path = path
        self.fd = None

    def __enter__(self):
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            info = os.fstat(self.fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
                raise RuntimeError("Lock must be an owned regular file")
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Workbench instance already owns this lock") from None
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class StateLease:
    """Serialize all API/supervisor instances sharing a private journal directory."""

    def __init__(self, state_dir):
        self.path = Path(state_dir)
        self.lock = None

    def __enter__(self):
        if os.geteuid() == 0:
            raise RuntimeError("Workbench must run as a non-root user")
        self.path = controlled_directory(self.path, 0o700)
        self.lock = FileLease(self.path / "launcher.lock")
        self.lock.__enter__()
        return self

    def __exit__(self, *args):
        if self.lock is not None:
            self.lock.__exit__(*args)


class UnixListener:
    """Bind only an owned UDS; refuse live, foreign, symlink and non-socket targets."""

    def __init__(self, path):
        self.path = Path(path).absolute()
        self.lock = None
        self.socket = None
        self.identity = None

    def __enter__(self):
        if len(os.fsencode(self.path)) >= 108:
            raise ValueError("Unix socket path is too long (maximum 107 bytes)")
        controlled_directory(self.path.parent, 0o750)
        self.lock = FileLease(self.path.with_name(self.path.name + ".lock"))
        self.lock.__enter__()
        try:
            self._remove_stale()
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.socket.bind(str(self.path))
            self.identity = self.path.lstat()
            self.path.chmod(0o660)
            self.socket.listen(128)
            self.socket.setblocking(False)
            return self.socket
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _remove_stale(self):
        try:
            original = self.path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(original.st_mode) or original.st_uid != os.geteuid():
            raise RuntimeError("Refusing to replace a foreign or non-socket path")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            try:
                probe.connect(str(self.path))
            except OSError as error:
                if error.errno != errno.ECONNREFUSED:
                    raise RuntimeError("Cannot prove existing socket is stale") from error
            else:
                raise RuntimeError("A live server owns the existing socket")
        current = self.path.lstat()
        if (original.st_dev, original.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("Socket changed during stale check")
        self.path.unlink()

    def __exit__(self, *args):
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        if self.identity is not None:
            try:
                current = self.path.lstat()
                if (current.st_dev, current.st_ino) == (self.identity.st_dev, self.identity.st_ino):
                    self.path.unlink()
            except FileNotFoundError:
                pass
            self.identity = None
        if self.lock is not None:
            self.lock.__exit__(*args)
