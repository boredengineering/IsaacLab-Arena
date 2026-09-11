# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Identity-checked Linux process-group shutdown, including orphaned descendants."""

import errno
import os
import signal
import time
import weakref
from contextlib import suppress
from pathlib import Path

# Linux 6.9+, include/uapi/linux/pidfd.h; unlike killpg this pins the kernel group identity.
PIDFD_SIGNAL_PROCESS_GROUP = 4


def process_stat(pid):
    """Read identity and group membership, retaining zombies as identity witnesses."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {"state": fields[0], "pgid": int(fields[2]), "sid": int(fields[3]), "start_ticks": fields[19]}
    except (FileNotFoundError, ProcessLookupError):
        return None


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def same_identity(current, expected):
    return current is not None and all(current[key] == expected[key] for key in ("start_ticks", "pgid", "sid"))


def group_members(pid):
    members = {}
    for path in Path("/proc").iterdir():
        if path.name.isdecimal():
            stat = process_stat(int(path.name))
            if stat is not None and stat["pgid"] == pid and stat["sid"] == pid:
                members[int(path.name)] = stat
    return members


class OwnedProcessGroup:
    """Never release ownership until no live member remains; refuse ambiguous identities."""

    def __init__(self, pid, identity=None):
        self.cleaned = False
        self._descriptor = None
        self.pid = pid
        self.boot = boot_id() if identity is None else identity["boot_id"]
        leader = process_stat(pid) if identity is None else identity
        self.start = leader["start_ticks"] if leader else None
        self.expected_group = ((leader or {}).get("pgid", pid), (leader or {}).get("sid", pid))
        self.witnesses = {int(key): value for key, value in (identity or {}).get("members", {}).items()}
        if self.start is not None:
            self.witnesses[pid] = self.start
        if self.boot == boot_id() and self.expected_group == (pid, pid):
            current = process_stat(pid)
            if current is not None and current["start_ticks"] == self.start:
                try:
                    descriptor = os.pidfd_open(pid)
                except ProcessLookupError:
                    pass
                else:
                    try:
                        if not same_identity(process_stat(pid), current):
                            raise ProcessLookupError
                        signal.pidfd_send_signal(descriptor, 0, None, PIDFD_SIGNAL_PROCESS_GROUP)
                    except OSError as error:
                        os.close(descriptor)
                        if error.errno not in {None, errno.ESRCH, errno.EINVAL}:
                            raise
                    else:
                        self._descriptor = descriptor
                        # Keep the descriptor through concurrent callers; never close while
                        # another owner is signalling this group.
                        weakref.finalize(self, os.close, descriptor)
        # Capture descendants while the leader can still prove session ownership.
        self.members()

    def members(self):
        if self.cleaned:
            return {}
        if self.boot != boot_id():
            return {}
        candidates = group_members(self.pid)
        if not candidates:
            return {}
        if self.expected_group != (self.pid, self.pid):
            raise RuntimeError("Recorded process group/session identity does not match the owned leader")
        leader = process_stat(self.pid)
        if leader is not None and self.start is not None and leader["start_ticks"] != self.start:
            return {}  # The recorded group is gone; a reused PID never authorizes signalling.
        if self._descriptor is not None:
            try:
                signal.pidfd_send_signal(self._descriptor, 0, None, PIDFD_SIGNAL_PROCESS_GROUP)
            except ProcessLookupError:
                return {}
        anchored = self._descriptor is not None or any(
            pid in candidates
            and candidates[pid]["start_ticks"] == start
            and same_identity(process_stat(pid), candidates[pid])
            for pid, start in list(self.witnesses.items())
        )
        if not anchored:
            raise RuntimeError("Owned process group identity cannot be verified; cleanup remains pending")
        self.witnesses.update({pid: stat["start_ticks"] for pid, stat in candidates.items()})
        return {pid: stat for pid, stat in candidates.items() if stat["state"] not in {"Z", "X"}}

    def send_signal(self, sig):
        """Pin and recheck each owned member; never signal a recycled PID or numeric group."""
        members = self.members()
        if members and self._descriptor is not None:
            with suppress(ProcessLookupError):
                signal.pidfd_send_signal(self._descriptor, sig, None, PIDFD_SIGNAL_PROCESS_GROUP)
            return
        for pid, expected in members.items():
            try:
                descriptor = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            try:
                current = process_stat(pid)
                if same_identity(current, expected):
                    with suppress(ProcessLookupError):
                        signal.pidfd_send_signal(descriptor, sig)
            finally:
                os.close(descriptor)

    def stop(self, term_timeout=2, kill_timeout=3):
        """Escalate by group liveness, not leader exit, and raise on unverified cleanup."""
        self.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + term_timeout
        while self.members() and time.monotonic() < deadline:
            time.sleep(0.025)
        deadline = time.monotonic() + kill_timeout
        while self.members():
            self.send_signal(signal.SIGKILL)
            if time.monotonic() >= deadline:
                raise RuntimeError("Owned process group cleanup could not be verified")
            time.sleep(0.025)
        self.cleaned = True
