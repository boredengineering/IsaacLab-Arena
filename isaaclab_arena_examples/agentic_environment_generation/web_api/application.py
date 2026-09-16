# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""HTTP lifecycle composition; workers and route groups live in separate modules."""

import asyncio
import hashlib
import ipaddress
import sqlite3
import time
from contextlib import asynccontextmanager, closing, nullcontext
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import SafeBusy
from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
from isaaclab_arena.agentic_environment_generation.workbench.sessions import Sessions

from .catalogues import router as catalogue_router
from .editor import router as editor_router
from .editor_execution import EditorExecution
from .evaluate import router as evaluate_router
from .events import router as event_router
from .graph_queries import router as graph_router
from .jobs import router as job_router
from .model_settings import ModelSettings
from .model_settings import router as model_settings_router
from .process_identity import recover_workers
from .publication_authorization import PublicationAuthorization
from .publication_routes import router as publication_router
from .publication_scheduler import PublicationScheduler
from .readiness import router as readiness_router
from .research_profiles import configured_publication_profiles, configured_research_roots
from .research_routes import router as research_router
from .runtime import StateLease
from .security import router as session_router
from .supervisor import Supervisor
from .workflow_authorization import WorkflowAuthorization
from .workflow_routes import router as workflow_router

# Keep failed physical-cleanup ownership alive even if the ASGI app is discarded.
_PENDING_CLEANUPS = set()


def _bound_state_directory(value, lease=None):
    """Freeze one absolute directory without bypassing symlink or lease ownership checks."""
    path = Path(value).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Symlink state directories are not allowed")
    path = path.resolve()
    if lease is not None and (
        not isinstance(lease, StateLease)
        or lease.path.resolve() != path
        or lease.lock is None
        or lease.lock.fd is None
        or lease._exit_requested
    ):
        raise ValueError("Borrowed lease must actively own the requested state directory")
    return path


class _LifespanCleanup:
    """Private, explicit retry handle; pending tasks and lease survive failed exit."""

    def __init__(self, app, lease, journal_path):
        self.app = app
        self.token = lease.retain()
        self.journal = None
        self.journal_path = journal_path
        self._dirty_reset_pending = False
        self.stores = {}
        self.supervisor = None
        self.worker = None
        self.credentials = None
        self.pending = {}
        self.done = set()
        self.failed = False
        self.started = False
        self.closed = False
        self.timeout = 5.0
        self._retry_lock = asyncio.Lock()
        _PENDING_CLEANUPS.add(self)

    async def step(self, name, factory, *, cancelled_ok=False):
        if name in self.done:
            return
        task = self.pending.get(name)
        if task is None:
            task = asyncio.ensure_future(factory())
            self.pending[name] = task
        # wait_for can wait indefinitely for cancellation-resistant cleanup.
        # Do not cancel or discard an unproven owned operation on timeout.
        completed, _ = await asyncio.wait({task}, timeout=self.timeout)
        if not completed:
            raise RuntimeError(f"Cleanup pending: {name}")
        del self.pending[name]
        if not (cancelled_ok and task.cancelled()):
            task.result()
        self.done.add(name)

    def _reset_dirty(self):
        """Revoke an ambiguous clean mark without opening/migrating another Journal."""
        # begin_run consumes this exact bit. A failed close may already have closed
        # the connection, so use only the existing source SQLite file under our lease.
        # Persistent I/O failure is an operator boundary, not proof of dirty state:
        # keep the obligation/lease and surface both failures until explicit retry.
        uri = self.journal_path.absolute().as_uri() + "?mode=rw"
        with closing(sqlite3.connect(uri, uri=True, timeout=0.1)) as db:
            with db:
                db.execute("UPDATE metadata SET value=0 WHERE key='clean_shutdown'")
        with closing(sqlite3.connect(uri, uri=True, timeout=0.1)) as db:
            if db.execute("SELECT value FROM metadata WHERE key='clean_shutdown'").fetchone() != (0,):
                raise RuntimeError("Journal dirty reset could not be verified; operator intervention required")
        self._dirty_reset_pending = False

    async def retry(self):
        """Retry on the owning live event loop; never expose this over HTTP."""
        async with self._retry_lock:
            if self.closed:
                return
            state = self.app.state
            state.publication_admitting = False
            state._closing = True
            errors = []

            async def attempt(name, factory, **kwargs):
                try:
                    await self.step(name, factory, **kwargs)
                except BaseException as error:
                    errors.append(error)

            if self.credentials is not None:
                self.credentials.cancel()
                await attempt("credentials", lambda: self.credentials, cancelled_ok=True)
            scheduler = state.publication_scheduler
            if scheduler is not None:
                # Startup recovery may still own a thread after its bounded await.
                if "publication startup" in self.pending:
                    await attempt("publication startup", scheduler.recover)
                if "publication startup" not in self.pending:
                    await attempt("publication stop", scheduler.stop)
                    if "publication stop" in self.done:
                        await attempt("publication recovery", scheduler.recover)
            if self.journal is not None and hasattr(state, "model_settings"):
                await attempt("worker startup", lambda: recover_workers(self.journal))
            if self.supervisor is not None:
                # Fence P1 dispatch even if stop itself fails before setting it.
                self.supervisor.stopping = True
                self.supervisor.wake.set()
                await attempt("supervisor", self.supervisor.stop)
            editor = getattr(state, "editor_execution", None)
            if editor is not None:
                await attempt("editor", editor.close)
            if self.worker is not None:
                await attempt("worker", lambda: self.worker)
            # P1 authorities are independent of publication's captured credentials.
            for name in ("workflow_authorization", "model_settings"):
                resource = getattr(state, name, None)
                if resource is not None:
                    try:
                        resource.clear()
                    except BaseException as error:
                        errors.append(error)
            publication_safe = scheduler is None or "publication recovery" in self.done
            if publication_safe:
                try:
                    authority = getattr(state, "publication_authorization", None)
                    if authority is not None:
                        authority.clear()
                    state.publication_profiles.clear()
                except BaseException as error:
                    errors.append(error)
            if errors:
                self.failed = True
                raise errors[0]
            self._finalize()

    def _finalize(self):
        """Close resources, retaining failed finalization until explicit dirty retry."""
        if self._dirty_reset_pending:
            self._reset_dirty()
        try:
            for key, store in tuple(self.stores.items()):
                store.close()
                del self.stores[key]
            if self.journal is not None:
                if self.started and not self.failed:
                    self._dirty_reset_pending = True
                    self.journal.finish_run()
                self.journal.close()
                self.journal = None
                self._dirty_reset_pending = False
        except BaseException as error:
            self.failed = True
            if self._dirty_reset_pending:
                try:
                    self._reset_dirty()
                except BaseException as reset_error:
                    # Preserve the original failure and the failed repair evidence.
                    raise error from reset_error
            raise
        self.token.release()
        self.closed = True
        _PENDING_CLEANUPS.discard(self)


def create_app(
    state_dir,
    *,
    origin="http://127.0.0.1:3000",
    diagnostics=False,
    clock=time.time,
    idle_seconds=86400,
    absolute_seconds=604800,
    start_paused=False,
    max_pending=32,
    research_roots=None,
    publication_profiles=None,
    publication_enabled=False,
    managed_retrieval_enabled=False,
    _publication_worker_command=None,
    _state_lease=None,
):
    """Construct the API without starting Isaac Sim, external services or paid work."""
    state_dir = _bound_state_directory(state_dir, _state_lease)
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Origin must be an exact HTTP(S) origin without a path")
    browser_origins = {parsed.netloc: origin}
    loopback_alias = {"127.0.0.1": "localhost", "localhost": "127.0.0.1"}.get(parsed.hostname or "")
    if loopback_alias:
        authority = loopback_alias + (f":{parsed.port}" if parsed.port is not None else "")
        browser_origins[authority] = f"{parsed.scheme}://{authority}"
    identity = hashlib.sha256(f"{state_dir.resolve()}|{origin}".encode()).hexdigest()[:16]

    @asynccontextmanager
    async def lifespan(app):
        with nullcontext(_state_lease) if _state_lease else StateLease(state_dir) as lease:
            if _bound_state_directory(state_dir, lease) != state_dir:
                raise ValueError("State lease directory changed before startup")
            cleanup = _LifespanCleanup(app, lease, state_dir / "journal.sqlite3")
            app.state._cleanup = cleanup
            publication_stores = cleanup.stores
            try:
                journal = Journal(state_dir / "journal.sqlite3")
                cleanup.journal = journal
                app.state.journal = journal
                app.state.documents = Documents(state_dir)
                app.state.sessions = Sessions(
                    journal, clock=clock, idle_seconds=idle_seconds, absolute_seconds=absolute_seconds
                )
                recovered_pause = journal.begin_run()
                app.state.model_settings = ModelSettings(clock=clock)
                await cleanup.step("worker startup", lambda: recover_workers(journal))
                supervisor = Supervisor(journal, enabled=diagnostics, paused=start_paused or recovered_pause)
                cleanup.supervisor = supervisor
                app.state.editor_execution = EditorExecution(state_dir, app.state.documents)
                app.state.editor_execution.model_settings = app.state.model_settings
                app.state.workflow_authorization = WorkflowAuthorization(
                    app.state.sessions, app.state.model_settings, clock=clock, journal=journal
                )
                if managed_retrieval_enabled:
                    from .managed_retrieval import configured_context

                    def managed_context(graph):
                        if not app.state.managed_retrieval_enabled:
                            raise ValueError("Managed retrieval disabled")
                        return configured_context(
                            state_dir / "journal.sqlite3",
                            journal,
                            app.state.research_roots,
                            app.state.publication_profiles,
                            graph,
                        )

                    app.state.workflow_authorization.managed_context_getter = managed_context
                app.state.publication_authorization = PublicationAuthorization(
                    app.state.sessions, lambda: app.state.publication_profiles, clock=clock
                )

                def forget_session_authority(owner):
                    app.state.workflow_authorization.grants.forget_owner(owner)
                    app.state.publication_authorization.forget_owner(owner)

                app.state.sessions.on_invalidate = forget_session_authority
                app.state.model_settings.on_invalidate = app.state.workflow_authorization.grants.forget_owner
                app.state.editor_execution.workflow_authorizer = app.state.workflow_authorization.resolve

                def protect_grants(value):
                    app.state.publication_authorization.protect_public(value)
                    app.state.workflow_authorization.protect_public(value)

                def purge_grants():
                    app.state.workflow_authorization.grants.purge()
                    app.state.publication_authorization.purge()

                app.state.model_settings.protect_grants = protect_grants
                app.state.model_settings.purge_grants = purge_grants
                app.state.editor_execution.protect_workflow = app.state.model_settings.protect_public
                if publication_enabled:
                    for store_id, root in app.state.research_roots.items():
                        publication_stores[store_id] = ResearchStore.open(
                            journal, root, store_id, protect_public=app.state.model_settings.protect_public
                        )
                    app.state.publication_scheduler = PublicationScheduler(
                        journal=journal,
                        authorization=app.state.publication_authorization,
                        protect_public=app.state.model_settings.protect_public,
                        configured_stores=publication_stores,
                        worker_command=_publication_worker_command,
                    )
                    await cleanup.step("publication startup", app.state.publication_scheduler.recover)
                    app.state.publication_admitting = True
                supervisor.editor_execution = app.state.editor_execution
                app.state.supervisor = supervisor
                cleanup.worker = asyncio.create_task(supervisor.run())
                cleanup.credentials = asyncio.create_task(app.state.model_settings.maintain())
                cleanup.started = True
                yield
            finally:
                await cleanup.retry()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.origin = origin
    app.state.browser_origins = browser_origins
    app.state.cookie_name = f"arena_wb_{identity}"
    app.state.secure_cookie = parsed.scheme == "https"
    try:
        loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        loopback = parsed.hostname == "localhost"
    app.state.session_keys_allowed = parsed.scheme == "https" or loopback
    app.state.absolute_seconds = absolute_seconds
    app.state.diagnostics = diagnostics
    app.state.neo4j_available = True
    app.state.start_paused = start_paused
    app.state.max_pending = max_pending
    app.state.research_roots = configured_research_roots(research_roots)
    app.state.publication_profiles = configured_publication_profiles(publication_profiles)
    if type(publication_enabled) is not bool:
        raise ValueError("Invalid publication enable flag")
    if publication_enabled and (not app.state.research_roots or not app.state.publication_profiles):
        raise ValueError("Publication requires configured stores and profiles")
    from .managed_retrieval import configured_enabled

    app.state.managed_retrieval_enabled = configured_enabled(
        managed_retrieval_enabled, app.state.research_roots, app.state.publication_profiles
    )
    app.state.publication_enabled = publication_enabled
    app.state.publication_admitting = False
    app.state._closing = False
    app.state.publication_scheduler = None
    app.state.active_streams = 0

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        return JSONResponse({"detail": "Invalid request input"}, status_code=422)

    @app.exception_handler(SafeBusy)
    async def research_busy(request, error):
        return JSONResponse(
            {"detail": "Managed store busy; retry the retained request later"},
            status_code=503,
            headers={"Retry-After": "1"},
        )

    @app.exception_handler(Exception)
    async def internal_error(request, error):
        return JSONResponse({"detail": "Internal workbench error"}, status_code=500)

    @app.middleware("http")
    async def browser_boundary(request, call_next):
        if app.state._closing:
            return JSONResponse({"detail": "Workbench is shutting down"}, status_code=503)
        expected_origin = browser_origins.get(request.headers.get("host"))
        if expected_origin is None:
            return JSONResponse({"detail": "Host not allowed"}, status_code=403)
        if request.headers.get("origin") not in (None, expected_origin):
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH"}:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                editor_body = request.url.path.startswith("/api/editor/") and not request.url.path.endswith(
                    "/reauthorize"
                )
                limit = 512 * 1024 if editor_body else 16384
                if len(body) > limit:
                    return JSONResponse({"detail": f"Request body exceeds {limit} bytes"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        if "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "capabilities": {
                "diagnostic": diagnostics,
                "generation": False,
                "preview": False,
                "durable_editor_save": True,
                "build": app.state.editor_execution.build_available,
                "policy_evaluation": app.state.editor_execution.evaluation_available,
            },
        }

    app.include_router(session_router)
    app.include_router(model_settings_router)
    app.include_router(job_router)
    app.include_router(event_router)
    app.include_router(editor_router)
    app.include_router(readiness_router)
    app.include_router(evaluate_router)
    app.include_router(research_router)
    app.include_router(publication_router)
    app.include_router(catalogue_router)
    app.include_router(graph_router)
    app.include_router(workflow_router)
    return app
