# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Real isolated process-group regressions; no simulator or model execution."""

import asyncio
import os
import signal
import subprocess
import sys
from contextlib import suppress

import pytest

from isaaclab_arena_examples.agentic_environment_generation.web_api.process_identity import process_identity
from isaaclab_arena_examples.agentic_environment_generation.web_api.supervisor import Supervisor

LEADER = """
import os, signal, sys, time
child = os.fork()
if child == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    os.write(int(sys.argv[1]), str(os.getpid()).encode() + b'\\n')
    os.close(int(sys.argv[1]))
    while True:
        time.sleep(1)
os.close(int(sys.argv[1]))
sys.stdin.readline()
"""


class WorkerJournal:
    def __init__(self):
        self.records = []
        self.cleaned = []

    def pending_workers(self):
        return self.records

    def worker_cleaned(self, job_id):
        self.cleaned.append(job_id)


async def start_group():
    reader, writer = os.pipe()
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            LEADER,
            str(writer),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            pass_fds=(writer,),
            start_new_session=True,
        )
    finally:
        os.close(writer)
    try:
        child = int(await asyncio.wait_for(asyncio.to_thread(os.read, reader, 100), 5))
    finally:
        os.close(reader)
    return process, child


async def emergency_cleanup(process):
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    await asyncio.wait_for(process.wait(), 3)


def test_supervisor_cleans_descendants_after_leader_exit():
    async def scenario():
        process, child = await start_group()
        supervisor = Supervisor(WorkerJournal())
        supervisor.process = process
        try:
            process.stdin.close()
            await asyncio.wait_for(process.wait(), 3)
            assert process_identity(child) is not None
            await supervisor.stop_process()
            assert process_identity(child) is None, "Exited leader left its owned child alive"
        finally:
            await emergency_cleanup(process)

    asyncio.run(scenario())


def test_supervisor_cleans_child_created_after_identity_capture():
    async def scenario():
        reader, writer = os.pipe()
        script = LEADER.replace("child = os.fork()", "sys.stdin.readline()\nchild = os.fork()")
        script = script.replace("os.close(int(sys.argv[1]))\nsys.stdin.readline()", "os.close(int(sys.argv[1]))")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            str(writer),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            pass_fds=(writer,),
            start_new_session=True,
        )
        os.close(writer)
        supervisor = Supervisor(WorkerJournal())
        supervisor.process = process
        try:
            process.stdin.write(b"go\n")
            await process.stdin.drain()
            child = int(await asyncio.wait_for(asyncio.to_thread(os.read, reader, 100), 5))
            await asyncio.wait_for(process.wait(), 3)
            await supervisor.stop_process()
            assert process_identity(child) is None
        finally:
            os.close(reader)
            await emergency_cleanup(process)

    asyncio.run(scenario())


def test_supervisor_escalates_when_term_exits_leader_but_not_child():
    async def scenario():
        process, child = await start_group()
        supervisor = Supervisor(WorkerJournal())
        supervisor.process = process
        try:
            assert process.returncode is None
            await supervisor.stop_process()
            assert process.returncode == -signal.SIGTERM
            assert process_identity(child) is None, "TERM-resistant descendant must receive KILL"
        finally:
            await emergency_cleanup(process)

    asyncio.run(scenario())


def test_snapshot_keeps_ownership_when_descendant_cleanup_is_unverified(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_process import SnapshotProcess

    reader, writer = os.pipe()
    process = subprocess.Popen(
        [sys.executable, "-c", LEADER, str(writer)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        pass_fds=(writer,),
        start_new_session=True,
    )
    os.close(writer)
    child = int(os.read(reader, 100))
    os.close(reader)
    snapshot = SnapshotProcess(tmp_path)
    snapshot.proc = process
    snapshot._lease_fd = os.open(tmp_path / "test-lease", os.O_CREAT | os.O_RDWR, 0o600)
    killpg = os.killpg
    send = signal.pidfd_send_signal

    def leader_only(pgid, sig):
        with suppress(ProcessLookupError):
            os.kill(process.pid, sig)

    def ignore_kill(descriptor, sig, *args):
        if sig != signal.SIGKILL:
            send(descriptor, sig, *args)

    monkeypatch.setattr(os, "killpg", leader_only)
    monkeypatch.setattr(signal, "pidfd_send_signal", ignore_kill)
    try:
        with pytest.raises(RuntimeError, match="cleanup could not be verified"):
            snapshot.close()
        assert snapshot.proc is process
        assert snapshot._lease_fd is not None
        os.fstat(snapshot._lease_fd)
        assert process_identity(child) is not None
    finally:
        with suppress(ProcessLookupError):
            killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
        if snapshot._lease_fd is not None:
            os.close(snapshot._lease_fd)


@pytest.mark.parametrize("field", ["pgid", "sid"])
def test_cleanup_rejects_mismatched_recorded_group_identity(field):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.process_identity import recover_workers

    async def scenario():
        process, child = await start_group()
        journal = WorkerJournal()
        identity = {**process_identity(process.pid), field: os.getpid()}
        journal.records = [{"job_id": "mismatch", "pid": process.pid, "identity": identity}]
        try:
            with pytest.raises(RuntimeError, match="identity"):
                await recover_workers(journal)
            assert not journal.cleaned
            assert process_identity(child) is not None
            assert process.returncode is None
        finally:
            await emergency_cleanup(process)

    asyncio.run(scenario())


def test_liveness_state_changes_do_not_invalidate_start_identity(monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import owned_process_group as groups

    async def scenario():
        process, child = await start_group()
        identity = process_identity(process.pid)
        real_stat = groups.process_stat

        def changing_state(pid):
            stat = real_stat(pid)
            return {**stat, "state": "R"} if stat is not None else None

        candidates = groups.group_members(process.pid)
        for stat in candidates.values():
            stat["state"] = "S"
        monkeypatch.setattr(groups, "group_members", lambda pid: candidates)
        monkeypatch.setattr(groups, "process_stat", changing_state)
        try:
            group = groups.OwnedProcessGroup(process.pid, identity)
            assert child in group.members()
        finally:
            await emergency_cleanup(process)

    asyncio.run(scenario())


@pytest.mark.parametrize("field,value", [("boot_id", "other-boot"), ("start_ticks", "other-start")])
def test_recovery_does_not_signal_reused_identity(field, value):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.process_identity import recover_workers

    async def scenario():
        process, child = await start_group()
        identity = {**process_identity(process.pid), field: value}
        journal = WorkerJournal()
        journal.records = [{"job_id": "old", "pid": process.pid, "identity": identity}]
        try:
            await recover_workers(journal)
            assert process_identity(child) is not None
            assert process.returncode is None
        finally:
            await emergency_cleanup(process)

    asyncio.run(scenario())


def test_recovery_without_surviving_identity_witness_stays_pending():
    from isaaclab_arena_examples.agentic_environment_generation.web_api.process_identity import recover_workers

    async def scenario():
        process, child = await start_group()
        identity = process_identity(process.pid)
        identity.pop("members")  # Older journals have only the leader identity.
        journal = WorkerJournal()
        journal.records = [{"job_id": "unverifiable", "pid": process.pid, "identity": identity}]
        try:
            process.stdin.close()
            await asyncio.wait_for(process.wait(), 3)
            with pytest.raises(RuntimeError, match="identity cannot be verified"):
                await recover_workers(journal)
            assert journal.cleaned == []
            assert process_identity(child) is not None
        finally:
            await emergency_cleanup(process)

    asyncio.run(scenario())


def test_identity_capture_rechecks_leader_after_collecting_members(monkeypatch):
    import importlib

    identities = importlib.import_module(
        "isaaclab_arena_examples.agentic_environment_generation.web_api.process_identity"
    )

    async def scenario():
        process, _ = await start_group()
        original = identities.group_members
        real_stat = identities.process_stat

        def changed_leader(pid):
            members = original(pid)
            monkeypatch.setattr(identities, "process_stat", lambda pid: {**real_stat(pid), "start_ticks": "reused"})
            return members

        monkeypatch.setattr(identities, "group_members", changed_leader)
        try:
            assert identities.process_identity(process.pid) is None
        finally:
            await emergency_cleanup(process)

    asyncio.run(scenario())


def test_recovery_timeout_never_acknowledges_cleanup(monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import OwnedProcessGroup
    from isaaclab_arena_examples.agentic_environment_generation.web_api.process_identity import recover_workers

    async def scenario():
        process, child = await start_group()
        journal = WorkerJournal()
        journal.records = [{"job_id": "blocked", "pid": process.pid, "identity": process_identity(process.pid)}]
        original = OwnedProcessGroup.stop
        monkeypatch.setattr(OwnedProcessGroup, "stop", lambda self, **kw: original(self, 0, 0))
        monkeypatch.setattr(signal, "pidfd_send_signal", lambda *args: None)
        try:
            with pytest.raises(RuntimeError, match="cleanup could not be verified"):
                await recover_workers(journal)
            assert journal.cleaned == []
            assert process_identity(child) is not None
        finally:
            await emergency_cleanup(process)

    asyncio.run(scenario())


@pytest.mark.parametrize("leader_exited", [False, True])
def test_restart_cleans_whole_owned_group(leader_exited):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.process_identity import recover_workers

    async def scenario():
        process, child = await start_group()
        journal = WorkerJournal()
        journal.records = [{"job_id": "owned", "pid": process.pid, "identity": process_identity(process.pid)}]
        try:
            if leader_exited:
                process.stdin.close()
                await asyncio.wait_for(process.wait(), 3)
            await recover_workers(journal)
            assert process_identity(child) is None, "Recovery acknowledged a surviving owned descendant"
            assert journal.cleaned == ["owned"]
        finally:
            await emergency_cleanup(process)

    asyncio.run(scenario())
