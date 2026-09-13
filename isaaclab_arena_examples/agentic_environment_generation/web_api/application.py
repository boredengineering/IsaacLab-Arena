# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""HTTP lifecycle composition; workers and route groups live in separate modules."""

import asyncio
import hashlib
import ipaddress
import time
from contextlib import asynccontextmanager, nullcontext, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena.agentic_environment_generation.workbench.sessions import Sessions

from .editor import router as editor_router
from .editor_execution import EditorExecution
from .events import router as event_router
from .graph_queries import router as graph_router
from .jobs import router as job_router
from .model_settings import ModelSettings
from .model_settings import router as model_settings_router
from .process_identity import recover_workers
from .runtime import StateLease
from .security import router as session_router
from .supervisor import Supervisor


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
    _state_lease=None,
):
    """Construct the API without starting Isaac Sim, external services or paid work."""
    state_dir = Path(state_dir)
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
        with nullcontext(_state_lease) if _state_lease else StateLease(state_dir):
            journal = Journal(state_dir / "journal.sqlite3")
            app.state.journal = journal
            app.state.documents = Documents(state_dir)
            try:
                app.state.sessions = Sessions(
                    journal, clock=clock, idle_seconds=idle_seconds, absolute_seconds=absolute_seconds
                )
                recovered_pause = journal.begin_run()
                app.state.model_settings = ModelSettings(clock=clock)
                await recover_workers(journal)
                supervisor = Supervisor(journal, enabled=diagnostics, paused=start_paused or recovered_pause)
                app.state.editor_execution = EditorExecution(state_dir, app.state.documents)
                app.state.editor_execution.model_settings = app.state.model_settings
                supervisor.editor_execution = app.state.editor_execution
                app.state.supervisor = supervisor
                worker_task = asyncio.create_task(supervisor.run())
                credential_task = asyncio.create_task(app.state.model_settings.maintain())
                try:
                    yield
                finally:
                    app.state.model_settings.clear()
                    credential_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await credential_task
                    await supervisor.stop()
                    await app.state.editor_execution.close()
                    await worker_task
                    journal.finish_run()
            finally:
                journal.close()

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
    app.state.active_streams = 0

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        return JSONResponse({"detail": "Invalid request input"}, status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(request, error):
        return JSONResponse({"detail": "Internal workbench error"}, status_code=500)

    @app.middleware("http")
    async def browser_boundary(request, call_next):
        expected_origin = browser_origins.get(request.headers.get("host"))
        if expected_origin is None:
            return JSONResponse({"detail": "Host not allowed"}, status_code=403)
        if request.headers.get("origin") not in (None, expected_origin):
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH"}:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                limit = 512 * 1024 if request.url.path.startswith("/api/editor/") else 16384
                if len(body) > limit:
                    return JSONResponse({"detail": f"Request body exceeds {limit} bytes"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        if "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "capabilities": {"diagnostic": diagnostics, "generation": False, "preview": False}}

    app.include_router(session_router)
    app.include_router(model_settings_router)
    app.include_router(job_router)
    app.include_router(event_router)
    app.include_router(editor_router)
    app.include_router(graph_router)
    return app
