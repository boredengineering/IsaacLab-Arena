# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Owner-held native GPU slot, separate from the workflow ownership lease."""

import copy
import fcntl
import os
import stat
from pathlib import Path


class NativeGpuLease:
    """Hold the shared renderer flock until exact trusted child cleanup is verified.

    The trusted launcher supplies the same host-backed path as the renderer
    (normally /eval/.arena-workbench-gpu.lock). This object neither starts workers
    nor authorizes effects. No context-manager exit unlocks an uncertain child.
    The owner must supervise child death on owner loss before using this resource.
    """

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("absolute shared GPU lease path required")
        self._fd = None
        self._fence = None

    @property
    def held(self):
        return self._fd is not None

    def acquire(self, fence):
        """Acquire once without waiting or spawning; contention remains explicit."""
        if self.held:
            raise ValueError("GPU lease already held")
        detached = copy.deepcopy(fence)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise ValueError("GPU lease must be an operator-owned regular file")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise
        self._fd, self._fence = fd, detached

    def require_held(self, fence):
        """Check this local capability and its exact claimed attempt."""
        if self._fd is None or self._fence != fence:
            raise ValueError("GPU lease binding mismatch")
        actual = os.fstat(self._fd)
        named = self.path.stat(follow_symlinks=False)
        if (actual.st_dev, actual.st_ino) != (named.st_dev, named.st_ino):
            raise ValueError("GPU lease path changed")

    def release(self, registration, cleanup, *, verify_cleanup):
        """Unlock only after the supervisor verifies cleanup for this registration.

        Args:
            registration: Exact native child's retained registration.
            cleanup: Exact independently observed physical cleanup evidence.
            verify_cleanup: Trusted supervisor verifier, never a caller success flag.
        """
        self.require_held(registration.fence)
        if cleanup.registration != registration:
            raise ValueError("GPU cleanup registration binding mismatch")
        if not callable(verify_cleanup) or verify_cleanup(registration, cleanup) is not True:
            raise ValueError("verified native cleanup required before GPU release")
        fd = self._fd
        assert fd is not None, "held GPU lease required"
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        self._fd, self._fence = None, None
