# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Exercise failed exit without closing the event loop or masking orphan tasks."""

import asyncio
import sqlite3
from contextlib import closing, nullcontext

import pytest

from isaaclab_arena_examples.agentic_environment_generation.web_api.runtime import StateLease
from isaaclab_arena_examples.tests.test_workbench_publication_execution import ready as _ready
from isaaclab_arena_examples.tests.test_workbench_publication_routes import app_for

ready = _ready


@pytest.mark.parametrize("borrowed", [False, True])
@pytest.mark.parametrize("phase", ["before_close", "after_close", "after_finish"])
def test_finalization_failure_remains_dirty_until_operator_resume(ready, tmp_path, monkeypatch, borrowed, phase):
    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
    from isaaclab_arena_examples.agentic_environment_generation.web_api import application

    async def scenario():
        with StateLease(tmp_path) if borrowed else nullcontext() as lease:
            app = app_for(ready, tmp_path, _state_lease=lease)
            context = app.router.lifespan_context(app)
            await context.__aenter__()
            journal = app.state.journal
            journal.resume_queue()
            method = "finish_run" if phase == "after_finish" else "close"
            original = getattr(journal, method)

            def fail():
                if phase != "before_close":
                    original()
                raise RuntimeError("finalization failed")

            monkeypatch.setattr(journal, method, fail)
            with pytest.raises(RuntimeError, match="finalization failed"):
                await context.__aexit__(None, None, None)
            cleanup = app.state._cleanup
            assert cleanup.failed and not cleanup.closed
            assert cleanup in application._PENDING_CLEANUPS
            assert cleanup.credentials.done() and cleanup.worker.done()
            assert not app.state.publication_admitting
        try:
            with pytest.raises(RuntimeError, match="already owns"):
                with StateLease(tmp_path):
                    pass
            with closing(sqlite3.connect(tmp_path / "journal.sqlite3")) as db:
                assert db.execute("SELECT value FROM metadata WHERE key='clean_shutdown'").fetchone()[0] == 0
        finally:
            monkeypatch.setattr(journal, method, original)
            await cleanup.retry()
        assert cleanup.closed and cleanup not in application._PENDING_CLEANUPS
        with StateLease(tmp_path):
            recovered = Journal(tmp_path / "journal.sqlite3")
            try:
                assert recovered.begin_run() is True
            finally:
                recovered.close()

    asyncio.run(scenario())


def test_dirty_reset_io_failure_retains_obligation_and_original_error(ready, tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import application

    async def scenario():
        app = app_for(ready, tmp_path)
        context = app.router.lifespan_context(app)
        await context.__aenter__()
        cleanup = app.state._cleanup
        journal = app.state.journal
        original_close = journal.close
        original_connect = sqlite3.connect

        def fail_close():
            original_close()
            raise RuntimeError("finalization failed")

        def fail_connect(*args, **kwargs):
            raise sqlite3.OperationalError("storage unavailable")

        monkeypatch.setattr(journal, "close", fail_close)
        monkeypatch.setattr(application.sqlite3, "connect", fail_connect)
        try:
            with pytest.raises(RuntimeError, match="finalization failed") as caught:
                await context.__aexit__(None, None, None)
            assert isinstance(caught.value.__cause__, sqlite3.OperationalError)
            assert cleanup._dirty_reset_pending and not cleanup.closed
            with pytest.raises(sqlite3.OperationalError, match="storage unavailable"):
                await cleanup.retry()
            with pytest.raises(RuntimeError, match="already owns"):
                with StateLease(tmp_path):
                    pass
        finally:
            monkeypatch.setattr(journal, "close", original_close)
            monkeypatch.setattr(application.sqlite3, "connect", original_connect)
            await cleanup.retry()
        with StateLease(tmp_path), closing(sqlite3.connect(tmp_path / "journal.sqlite3")) as db:
            assert db.execute("SELECT value FROM metadata WHERE key='clean_shutdown'").fetchone()[0] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("borrowed", [False, True])
def test_failed_exit_stops_independent_tasks_and_retains_lease(ready, tmp_path, monkeypatch, borrowed):
    async def scenario():
        before = asyncio.all_tasks()
        with StateLease(tmp_path) if borrowed else nullcontext() as lease:
            app = app_for(ready, tmp_path, _state_lease=lease)
            context = app.router.lifespan_context(app)
            await context.__aenter__()
            scheduler = app.state.publication_scheduler
            original = scheduler.stop

            async def fail():
                raise RuntimeError("cleanup pending")

            monkeypatch.setattr(scheduler, "stop", fail)
            with pytest.raises(RuntimeError, match="cleanup pending"):
                await context.__aexit__(None, None, None)
            await asyncio.sleep(0)
            assert not (asyncio.all_tasks() - before)
            assert not app.state.publication_admitting
            assert app.state.publication_profiles
            assert (
                app.state.journal.db.execute("SELECT value FROM metadata WHERE key='clean_shutdown'").fetchone()[0] == 0
            )
        with pytest.raises(RuntimeError, match="already owns"):
            with StateLease(tmp_path):
                pass
        monkeypatch.setattr(scheduler, "stop", original)
        await app.state._cleanup.retry()
        assert not app.state.publication_profiles
        with StateLease(tmp_path):
            pass

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["publication", "worker"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_startup_recovery_failure_cleanup_and_retry(ready, tmp_path, monkeypatch, phase, cleanup_fails):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import application

    async def scenario():
        app = app_for(ready, tmp_path)
        target = application.PublicationScheduler if phase == "publication" else application
        name = "recover" if phase == "publication" else "recover_workers"
        original = getattr(target, name)
        calls = []

        async def fail(*args):
            calls.append(1)
            if len(calls) == 1 or cleanup_fails:
                raise RuntimeError("recovery pending")
            return await original(*args)

        monkeypatch.setattr(target, name, fail)
        with pytest.raises(RuntimeError, match="recovery pending"):
            async with app.router.lifespan_context(app):
                pytest.fail("startup admitted")
        assert not app.state.publication_admitting
        assert app.state.model_settings._records == {}
        if cleanup_fails:
            with pytest.raises(RuntimeError, match="already owns"):
                with StateLease(tmp_path):
                    pass
            monkeypatch.setattr(target, name, original)
            await app.state._cleanup.retry()
        assert not app.state.publication_profiles
        assert app.state._cleanup.closed
        with StateLease(tmp_path):
            pass

    asyncio.run(scenario())


@pytest.mark.parametrize("resource", ["publication", "editor", "supervisor"])
def test_bounded_exit_retains_pending_operation_until_explicit_retry(ready, tmp_path, monkeypatch, resource):
    async def scenario():
        app = app_for(ready, tmp_path)
        context = app.router.lifespan_context(app)
        await context.__aenter__()
        cleanup = app.state._cleanup
        cleanup.timeout = 0.02
        target, method = {
            "publication": (app.state.publication_scheduler, "stop"),
            "editor": (app.state.editor_execution, "close"),
            "supervisor": (app.state.supervisor, "stop"),
        }[resource]
        original = getattr(target, method)
        gate = asyncio.Event()
        calls = []

        async def delayed():
            calls.append(1)
            await gate.wait()
            await original()

        monkeypatch.setattr(target, method, delayed)
        with pytest.raises(RuntimeError, match="Cleanup pending"):
            await asyncio.wait_for(context.__aexit__(None, None, None), timeout=1)
        assert cleanup.pending
        with pytest.raises(RuntimeError, match="already owns"):
            with StateLease(tmp_path):
                pass
        gate.set()
        await cleanup.retry()
        assert calls == [1]
        assert not cleanup.pending
        assert cleanup.closed
        with StateLease(tmp_path):
            pass

    asyncio.run(scenario())
