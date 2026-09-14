# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Real subprocess publication scheduler tests; no real graph or sockets."""

import asyncio
import sys

import pytest

from isaaclab_arena_examples.tests.test_workbench_publication_execution import ready as _ready
from isaaclab_arena_examples.tests.test_workbench_publication_worker import FAKE_CODE

ready = _ready


def scheduler(ready, **kwargs):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_scheduler import (
        PublicationScheduler,
    )

    ready.attempts.initialize_worker_support()
    code = FAKE_CODE.replace("CLOSE_FAIL", "False").replace("EXPECT_COMMITS", "1")
    return PublicationScheduler(
        journal=ready.journal,
        authorization=ready.auth,
        protect_public=ready.auth.protect_public,
        configured_stores={"store": ready.store},
        worker_command=kwargs.pop("worker_command", (sys.executable, "-c", code)),
        **kwargs,
    )


def accept(run, ready, request="request", **kwargs):
    return run.accept(ready.session, "store", "effect", request, **kwargs)


def test_real_child_one_write_replay_no_worker_and_responsive_loop(ready):
    async def exercise():
        run = scheduler(ready)
        result = accept(run, ready)
        assert result["accepted_new"]
        assert run.worker_count == 0
        pulses = []

        async def pulse():
            for _ in range(20):
                pulses.append(1)
                await asyncio.sleep(0.005)

        await run.enqueue("request")
        await asyncio.gather(run.wait_idle(), pulse())
        assert len(pulses) == 20
        assert ready.attempts.get_state("effect")["state"] == "verified"
        assert run.worker_count == 1
        ready.auth.forget_owner(ready.session["session_id"])
        replay = accept(run, ready)
        assert not replay["accepted_new"]
        assert replay["accepted"] == result["accepted"]
        await run.enqueue("request")
        await run.wait_idle()
        assert run.worker_count == 1
        assert not ready.attempts.pending_workers()
        assert not ready.auth._records
        assert "fake-private-publication-password" not in "\n".join(ready.journal.db.iterdump())
        await run.stop()

    asyncio.run(exercise())


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.mark.parametrize("invalidate", ["expiry", "forget", "rotation"])
def test_authority_lost_during_ready_never_sends_private(ready, tmp_path, invalidate):
    entered, gate, called = (tmp_path / name for name in ("entered", "gate", "called"))
    code = FAKE_CODE.replace("CLOSE_FAIL", "False").replace("EXPECT_COMMITS", "1")
    code = code.replace(
        "def factory(**kwargs):", f"def factory(**kwargs):\n    open({str(called)!r}, 'w').write('called')"
    )
    code = code.replace(
        "raise SystemExit(main(driver_factory=factory))",
        f"""
import time
open({str(entered)!r}, 'w').close()
while not os.path.exists({str(gate)!r}): time.sleep(.005)
raise SystemExit(main(driver_factory=factory))
""",
    )

    async def exercise():
        run = scheduler(ready, worker_command=(sys.executable, "-c", code))
        accept(run, ready)
        await run.enqueue("request")
        await until(entered.exists)
        if invalidate == "expiry":
            ready.now[0] += 181
        elif invalidate == "forget":
            ready.auth.forget_owner(ready.session["session_id"])
        else:
            ready.profiles["graph"]["connection"]["password"] = "new-private-password"
        gate.touch()
        await run.wait_idle()
        assert not called.exists()
        assert ready.attempts.get_state("effect")["state"] == "blocked_authorization"
        assert not ready.attempts.pending_workers()
        await run.stop()

    asyncio.run(exercise())


@pytest.mark.parametrize("revoke_fails", [False, True])
def test_post_accept_observation_failure_retains_committed_handle(ready, monkeypatch, revoke_fails):
    async def exercise():
        run = scheduler(ready)
        if revoke_fails:
            original_revoke = ready.auth.revoke

            def revoke(grant):
                original_revoke(grant)
                raise RuntimeError("revocation observation failed")

            monkeypatch.setattr(ready.auth, "revoke", revoke)
        attempts = run.attempts["store"]

        def fail(*a, **kw):
            raise RuntimeError("private failure")

        def bind(*a):
            monkeypatch.setattr(attempts, "get_state", fail)
            monkeypatch.setattr(run, "_pause", fail)
            raise RuntimeError("bind failure")

        monkeypatch.setattr(ready.auth, "bind_attempt", bind)
        result = accept(run, ready)
        assert result["accepted"] == ready.attempts.get_acceptance("request")
        assert result["accepted_new"]
        assert result["state"] is None
        assert result["disposition"] == "accepted_state_unavailable"
        assert result["error"] == "Publication state unavailable"
        assert not run._slots
        assert not ready.auth._records

    asyncio.run(exercise())


def test_bind_failure_retains_acceptance_but_releases_capacity(ready, monkeypatch):
    async def exercise():
        run = scheduler(ready, queue_capacity=0)
        original = ready.auth.bind_attempt
        monkeypatch.setattr(ready.auth, "bind_attempt", lambda *a: (_ for _ in ()).throw(ValueError("denied")))
        result = accept(run, ready)
        assert result["accepted_new"]
        assert result["state"]["state"] == "blocked_authorization"
        assert not run._slots
        assert not ready.auth._records
        monkeypatch.setattr(ready.auth, "bind_attempt", original)
        renewed = accept(run, ready, "renew", operation="renew", previous_request_id="request")
        assert renewed["accepted_new"]
        await run.stop()
        assert not ready.attempts.pending_workers()

    asyncio.run(exercise())


def test_late_durable_replay_never_creates_dispatch(ready, monkeypatch):
    async def exercise():
        run = scheduler(ready)
        accepted = accept(run, ready)
        await run.stop()
        run = scheduler(ready)
        attempts = run.attempts["store"]
        original = attempts.get_acceptance
        calls = []

        def miss_once(request):
            calls.append(request)
            return None if len(calls) == 1 else original(request)

        monkeypatch.setattr(attempts, "get_acceptance", miss_once)
        monkeypatch.setattr(attempts, "accept_request", lambda *a, **kw: dict(accepted, accepted_new=False))
        replay = accept(run, ready)
        assert not replay["accepted_new"]
        assert replay["accepted"] == accepted["accepted"]
        assert not run._slots
        assert not ready.auth._records
        assert not await run.enqueue("request")
        await run.stop()

    asyncio.run(exercise())


def test_replay_scope_session_and_no_capacity_consumption(ready):
    async def exercise():
        run = scheduler(ready, queue_capacity=0)
        accept(run, ready)
        assert not accept(run, ready)["accepted_new"]
        with pytest.raises(ValueError):
            accept(run, ready, "another")
        assert ready.attempts.get_acceptance("another") is None
        other, _ = ready.sessions.create()
        with pytest.raises(ValueError):
            run.accept(other, "store", "effect", "request")
        ready.sessions.revoke(ready.cookie)
        with pytest.raises(ValueError):
            accept(run, ready)
        await run.stop()

    asyncio.run(exercise())


def test_cancel_immediately_after_enqueue_is_owned(ready):
    async def exercise():
        run = scheduler(ready)
        result = accept(run, ready)
        await run.enqueue("request")
        assert await run.cancel("store", "effect", **{k: result["accepted"][k] for k in ("attempt_id", "generation")})
        assert run.worker_count == 0
        assert not run._slots
        await run.stop()

    asyncio.run(exercise())


def test_late_spawn_during_stop_is_reaped(ready, monkeypatch):
    async def exercise():
        run = scheduler(ready)
        spawned, release = asyncio.Event(), asyncio.Event()
        processes = []
        original = asyncio.create_subprocess_exec

        async def delayed(*a, **kw):
            process = await original(*a, **kw)
            processes.append(process)
            spawned.set()
            await release.wait()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
        accept(run, ready)
        await run.enqueue("request")
        await spawned.wait()
        stopping = asyncio.create_task(run.stop())
        await asyncio.sleep(0.01)
        release.set()
        await stopping
        assert processes[0].returncode is not None
        assert not run._slots
        assert not ready.attempts.pending_workers()
        assert ready.attempts.get_state("effect")["state"] == "blocked_authorization"

    asyncio.run(exercise())


def test_secret_response_after_forget_is_screened_with_old_password(ready, tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import publication_scheduler as module

    entered, gate = tmp_path / "result-ready", tmp_path / "result-gate"
    password = ready.profiles["graph"]["connection"]["password"]
    code = FAKE_CODE.replace("CLOSE_FAIL", "False").replace("EXPECT_COMMITS", "1")
    code = code.replace(
        "raise SystemExit(main(driver_factory=factory))",
        f"""
import time
write = os.write
def intercepted(fd, raw):
    raw = bytes(raw)
    original_size = len(raw)
    if b'"receipt"' in raw:
        open({str(entered)!r}, 'w').close()
        while not os.path.exists({str(gate)!r}): time.sleep(.005)
        raw = json.dumps({{'schema_version':1, 'receipt':{password!r}}}).encode() + b'\\n'
    write(fd, raw)
    return original_size
os.write = intercepted
raise SystemExit(main(driver_factory=factory))
""",
    )
    screened = []
    original = module.screen_worker_result

    def screen(raw, expected, passwords):
        screened.append(tuple(passwords))
        return original(raw, expected, passwords)

    async def exercise():
        monkeypatch.setattr(module, "screen_worker_result", screen)
        run = scheduler(ready, worker_command=(sys.executable, "-c", code))
        accept(run, ready)
        await run.enqueue("request")
        await until(entered.exists)
        ready.auth.forget_owner(ready.session["session_id"])
        ready.profiles.clear()
        gate.touch()
        await run.wait_idle()
        assert screened and password in screened[0]
        assert ready.attempts.get_state("effect")["state"] == "unknown"
        assert password not in "\n".join(ready.journal.db.iterdump())
        await run.stop()

    asyncio.run(exercise())


def test_unknown_write_then_explicit_read_performs_no_extra_write(ready, tmp_path):
    saved = tmp_path / "fake-graph.json"
    code = FAKE_CODE.replace("CLOSE_FAIL", "True").replace("EXPECT_COMMITS", "1")
    code = code.replace(
        "    def close():",
        f"    def close():\n        open({str(saved)!r}, 'w').write(json.dumps([driver.nodes, driver.edges]))",
    )

    async def exercise():
        run = scheduler(ready, worker_command=(sys.executable, "-c", code))
        accept(run, ready)
        await run.enqueue("request")
        await run.wait_idle()
        assert ready.attempts.get_state("effect")["state"] == "unknown"
        assert saved.exists()
        assert not accept(run, ready)["accepted_new"]
        await run.enqueue("request")
        assert run.worker_count == 1
        read_code = FAKE_CODE.replace("CLOSE_FAIL", "False").replace("EXPECT_COMMITS", "0")
        read_code = read_code.replace(
            "    def close():", f"    driver.nodes, driver.edges = json.load(open({str(saved)!r}))\n    def close():"
        )
        run.command = (sys.executable, "-c", read_code)
        accept(run, ready, "read", operation="reconcile", previous_request_id="request")
        await run.enqueue("read")
        await run.wait_idle()
        assert run.worker_count == 2
        assert ready.attempts.get_state("effect")["state"] == "verified"
        await run.stop()

    asyncio.run(exercise())


def test_startup_recovery_is_explicit_never_redispatches(ready):
    async def exercise():
        first = scheduler(ready)
        accept(first, ready)
        first.authorization.clear()
        recovered = scheduler(ready)
        assert ready.attempts.get_state("effect")["state"] == "claimed"
        assert await recovered.recover() == 1
        assert await recovered.recover() == 0
        assert not accept(recovered, ready)["accepted_new"]
        assert not await recovered.enqueue("request")
        assert recovered.worker_count == 0
        await first.stop()
        await recovered.stop()

    asyncio.run(exercise())


def test_stop_cleans_process_even_when_recovery_fencing_fails(ready, tmp_path, monkeypatch):
    entered = tmp_path / "spawned"
    code = FAKE_CODE.replace(
        "raise SystemExit(main(driver_factory=factory))",
        f"import time\nopen({str(entered)!r}, 'w').close()\ntime.sleep(60)",
    )

    async def exercise():
        run = scheduler(ready, worker_command=(sys.executable, "-c", code))
        accepted = accept(run, ready)["accepted"]
        await run.enqueue("request")
        await until(entered.exists)
        dispatch = run._slots["request"]
        assert not await run.cancel("store", "effect", attempt_id="stale", generation=accepted["generation"])
        assert dispatch.process.returncode is None
        monkeypatch.setattr(
            run.attempts["store"],
            "recover_worker_dispatch",
            lambda: (_ for _ in ()).throw(ValueError("journal unavailable")),
        )
        with pytest.raises(RuntimeError):
            await run.stop()
        assert dispatch.process.returncode is not None
        assert not dispatch.group.members()

    asyncio.run(exercise())


def test_concurrency_lease_covers_physical_cleanup(ready, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import OwnedProcessGroup

    async def exercise():
        run = scheduler(ready)
        original = OwnedProcessGroup.stop
        observed = []

        def stop(group, **kwargs):
            observed.append(run._semaphore.locked())
            return original(group, **kwargs)

        monkeypatch.setattr(OwnedProcessGroup, "stop", stop)
        accept(run, ready)
        await run.enqueue("request")
        await run.wait_idle()
        assert observed == [True]
        assert not run._semaphore.locked()
        await run.stop()

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["ledger", "cleanup"])
def test_failed_stop_can_be_explicitly_retried(ready, monkeypatch, failure):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import OwnedProcessGroup

    async def exercise():
        run = scheduler(ready)
        accept(run, ready)
        await run.enqueue("request")
        await until(lambda: run._slots["request"].group is not None)
        target = run.attempts["store"] if failure == "ledger" else OwnedProcessGroup
        name = "recover_worker_dispatch" if failure == "ledger" else "stop"
        original = getattr(target, name)
        monkeypatch.setattr(target, name, lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("transient")))
        with pytest.raises(RuntimeError):
            await run.stop()
        failed = run._stop_task
        monkeypatch.setattr(target, name, original)
        await run.stop()
        assert run._stop_task is not failed
        successful = run._stop_task
        await run.stop()
        assert run._stop_task is successful
        assert not run._slots
        assert not ready.attempts.pending_workers()

    asyncio.run(exercise())


@pytest.mark.parametrize("field", ["start_ticks", "boot_id", "pgid"])
def test_changed_source_identity_never_releases_private(ready, monkeypatch, field):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import publication_scheduler as module

    original = module.process_identity

    def wrong(pid):
        identity = original(pid)
        identity[field] = identity[field] + 1 if type(identity[field]) is int else "wrong"
        return identity

    async def exercise():
        monkeypatch.setattr(module, "process_identity", wrong)
        run = scheduler(ready)
        accept(run, ready)
        await run.enqueue("request")
        await run.wait_idle()
        assert ready.attempts.get_state("effect")["state"] == "blocked_authorization"
        assert not run._slots
        await run.stop()

    asyncio.run(exercise())


def test_cancelled_stop_caller_retains_inflight_cleanup(ready, monkeypatch):
    import threading

    from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import OwnedProcessGroup

    async def exercise():
        entered, release = threading.Event(), threading.Event()
        original = OwnedProcessGroup.stop

        def blocked(group, **kw):
            entered.set()
            assert release.wait(10)
            return original(group, **kw)

        monkeypatch.setattr(OwnedProcessGroup, "stop", blocked)
        run = scheduler(ready)
        accept(run, ready)
        await run.enqueue("request")
        await until(entered.is_set)
        caller = asyncio.create_task(run.stop())
        await asyncio.sleep(0.01)
        stopping = run._stop_task
        caller.cancel()
        other = asyncio.create_task(run.stop())
        try:
            await asyncio.sleep(0.01)
            assert run._stop_task is stopping
            assert not caller.done()
            assert run._slots["request"].leased
            assert ready.attempts.pending_workers()
        finally:
            release.set()
            await asyncio.gather(caller, other)
        assert not run._slots
        assert not ready.attempts.pending_workers()

    asyncio.run(exercise())


def test_constructor_failure_before_initialization_retries_capture(ready, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import OwnedProcessGroup

    async def exercise():
        run = scheduler(ready)
        original = OwnedProcessGroup.__init__
        calls = []

        def fail_once(group, *a, **kw):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("initial capture failed")
            return original(group, *a, **kw)

        monkeypatch.setattr(OwnedProcessGroup, "__init__", fail_once)
        accept(run, ready)
        await run.enqueue("request")
        await run.wait_idle()
        try:
            assert not run._slots
            assert not ready.attempts.pending_workers()
        finally:
            for dispatch in tuple(run._slots.values()):
                original(dispatch.group, dispatch.process.pid, dispatch.identity)
            await run.stop()

    asyncio.run(exercise())


def test_missing_spawn_identity_never_releases_slot_on_leader_exit(ready, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import publication_scheduler as module

    async def exercise():
        run = scheduler(ready, worker_command=(sys.executable, "-c", "pass"), io_timeout=0.2)
        monkeypatch.setattr(module, "process_stat", lambda pid: None)
        accept(run, ready)
        await run.enqueue("request")
        await run.wait_idle()
        assert run._slots["request"].leased
        assert run._slots["request"].anchor_fd is not None
        with pytest.raises(RuntimeError):
            await run.stop()
        process = run._slots["request"].process
        process.stdin.close()
        await process.wait()

    asyncio.run(exercise())


@pytest.mark.parametrize("descendant", [False, True])
def test_group_source_capture_failure_retains_anchor_and_retries(ready, monkeypatch, tmp_path, descendant):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import owned_process_group as groups

    entered = tmp_path / "child"
    code = f"""
import os, signal, time
if {descendant!r}:
    child = os.fork()
    if child == 0:
        os.close(0)
        os.close(1)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        open({str(entered)!r}, 'w').write(str(os.getpid()))
        time.sleep(60)
    else:
        while not os.path.exists({str(entered)!r}): time.sleep(.005)
        time.sleep(60)
else:
    open({str(entered)!r}, 'w').write(str(os.getpid()))
    time.sleep(60)
"""

    async def exercise():
        run = scheduler(ready, worker_command=(sys.executable, "-c", code), io_timeout=0.2)
        original = groups.group_members

        def unavailable(*a):
            raise OSError("source capture unavailable")

        monkeypatch.setattr(groups, "group_members", unavailable)
        accept(run, ready)
        await run.enqueue("request")
        await until(entered.exists)
        await run.wait_idle()
        dispatch = run._slots["request"]
        try:
            assert dispatch.identity is not None
            assert dispatch.group is not None
            assert dispatch.group._descriptor is not None
            assert dispatch.leased
            assert ready.attempts.pending_workers()
            if descendant:
                import signal

                signal.pidfd_send_signal(dispatch.group._descriptor, signal.SIGTERM)
                await dispatch.process.wait()
                assert dispatch.process.returncode is not None
                assert groups.process_stat(int(entered.read_text()))["state"] not in {"Z", "X"}
                assert run._slots["request"].leased
            monkeypatch.setattr(groups, "group_members", original)
            await run.stop()
            assert not groups.group_members(dispatch.process.pid) or not dispatch.group.members()
            assert not run._slots
            assert not ready.attempts.pending_workers()
        finally:
            monkeypatch.setattr(groups, "group_members", original)
            # Test-owned process only, even when the regression is red.
            group = dispatch.group or groups.OwnedProcessGroup(dispatch.process.pid)
            await asyncio.to_thread(group.stop, term_timeout=0.1)
            await dispatch.process.wait()

    asyncio.run(exercise())


def test_cleanup_failure_retains_unknown_identity_until_stop(ready, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import OwnedProcessGroup

    original = OwnedProcessGroup.stop
    calls = []

    def fail_once(group, **kwargs):
        calls.append(group)
        if len(calls) == 1:
            raise RuntimeError("cleanup uncertain")
        return original(group, **kwargs)

    async def exercise():
        monkeypatch.setattr(OwnedProcessGroup, "stop", fail_once)
        run = scheduler(ready)
        accept(run, ready)
        await run.enqueue("request")
        await run.wait_idle()
        assert ready.attempts.get_state("effect")["state"] == "unknown"
        assert len(ready.attempts.pending_workers()) == 1
        assert run._slots["request"].passwords
        await run.stop()
        assert not ready.attempts.pending_workers()
        assert not run._slots
        assert not calls[0].members()

    asyncio.run(exercise())
