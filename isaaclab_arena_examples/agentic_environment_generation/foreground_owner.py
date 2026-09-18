# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit non-root foreground ownership; uncertain cleanup retains the real flock."""

import os
import secrets
import stat
from functools import wraps
from pathlib import Path
from threading import RLock

from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration

from .web_api.runtime import FileLease


def _locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return call


def _parent(path):
    path = Path(path).absolute()
    uid = os.geteuid()
    if uid == 0:
        raise RuntimeError("Foreground ownership requires non-root")
    for ancestor in (path, *path.parents):
        info = ancestor.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, uid}:
            raise RuntimeError("Uncontrolled private parent")
        if info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
            raise RuntimeError("Writable ancestor is uncontrolled")
    info = path.lstat()
    if info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError("Explicit owned private parent required")
    return path


class ForegroundOwnerLease:
    """Retain FileLease until trusted exact cleanup or a never-prepared release.

    No destructor or context exit claims cleanup. Call mark_prepared BEFORE worker
    preparation with the exact claimed AttemptFence (no invented worker PID).
    The later registration must carry that fence; uncertain preparation
    must remain retained until cleanup_verified proves physical cleanup. The callback
    is a trusted local supervisor port, never a user-supplied cleanup assertion.
    It runs under the lease lock and must not acquire the authority/coordinator
    locks; the lock order is coordinator, authority, lease. Legacy opaque prepare
    identities remain supported only with exact callback verification.
    """

    def __init__(self, private_parent, *, run_id, principal, cleanup_verified):
        self._lock = RLock()
        self.path = _parent(private_parent)
        self.run_id, self.principal = run_id, principal
        self._pid = os.getpid()
        self.owner_id = f"foreground-{self._pid}-{secrets.token_hex(16)}"
        self._cleanup_verified = cleanup_verified
        self._prepared = None
        self._released = False
        self._lease = FileLease(self.path / "foreground.lock")
        self._lease.__enter__()
        self._fd = self._lease.fd
        info = os.fstat(self._fd)
        self._identity = (info.st_dev, info.st_ino)
        parent = self.path.stat()
        self._parent_identity = (parent.st_dev, parent.st_ino)

    @_locked
    def require_held(self, run_id, principal):
        """Check exact caller/run and the original process, descriptor and inode."""
        if (
            self._released
            or os.getpid() != self._pid
            or self._lease.fd != self._fd
            or (run_id, principal) != (self.run_id, self.principal)
        ):
            raise ValueError("Foreground owner lease unavailable")
        _parent(self.path)
        parent = self.path.stat()
        info = os.fstat(self._fd)
        current = self._lease.path.lstat()
        if (
            (info.st_dev, info.st_ino) != self._identity
            or (current.st_dev, current.st_ino) != self._identity
            or (parent.st_dev, parent.st_ino) != self._parent_identity
            or info.st_nlink != 1
            or not stat.S_ISREG(current.st_mode)
            or info.st_uid != os.geteuid()
        ):
            raise ValueError("Foreground owner lease changed")

    @_locked
    def mark_prepared(self, registration):
        """Disarm never-prepared release before any worker preparation side effect."""
        self.require_held(self.run_id, self.principal)
        if registration is None or self._prepared is not None:
            raise ValueError("Exact single preparation required")
        if type(registration) is AttemptFence and (
            registration.run_id != self.run_id or registration.owner_id != self.owner_id
        ):
            raise ValueError("Exact owned preparation fence required")
        self._prepared = registration

    @_locked
    def release_never_prepared(self):
        self.require_held(self.run_id, self.principal)
        if self._prepared is not None:
            raise ValueError("Cleanup proof required")
        self._release()

    @_locked
    def release_after_cleanup(self, registration, evidence):
        self.require_held(self.run_id, self.principal)
        if (
            self._prepared is None
            or not (
                (
                    type(self._prepared) is AttemptFence
                    and type(registration) is WorkerRegistration
                    and registration.fence == self._prepared
                )
                or (type(self._prepared) is not AttemptFence and registration == self._prepared)
            )
            or self._cleanup_verified(registration, evidence) is not True
        ):
            raise ValueError("Exact trusted cleanup proof required")
        self._release()

    def _release(self):
        self._lease.__exit__(None, None, None)
        self._released = True
