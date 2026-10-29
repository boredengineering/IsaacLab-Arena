# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Linux process-start identity, never PID alone, for diagnostic worker recovery."""

import asyncio

from .owned_process_group import OwnedProcessGroup, boot_id, group_members, process_stat, same_identity


def process_identity(pid):
    """Return boot and process-start identity, or None when the process has exited."""
    stat = process_stat(pid)
    if stat is None or stat["state"] in {"Z", "X"}:
        return None
    identity = {"boot_id": boot_id(), "start_ticks": stat["start_ticks"], "pgid": stat["pgid"], "sid": stat["sid"]}
    if stat["pgid"] == pid and stat["sid"] == pid:
        identity["members"] = {str(member): info["start_ticks"] for member, info in group_members(pid).items()}
        if not same_identity(process_stat(pid), stat):
            return None
    return identity


async def recover_workers(journal):
    """Verify or stop exact surviving diagnostic identities before permitting dispatch."""
    for record in journal.pending_workers():
        group = OwnedProcessGroup(record["pid"], record["identity"])
        await asyncio.to_thread(group.stop, term_timeout=0)
        journal.worker_cleaned(record["job_id"])
