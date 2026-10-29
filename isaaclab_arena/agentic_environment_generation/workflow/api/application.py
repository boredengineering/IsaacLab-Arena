# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Open-only query ASGI lifetime with an explicit trusted execution opt-in."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from fastapi import FastAPI

from ..profiles import ProfileRevision
from ..scope_binding import ScopeBinding
from .security import TokenRegistry

if TYPE_CHECKING:
    from ..neo4j_store import Neo4jWorkflowStore


class Authority(Protocol):
    def require_admin(self, principal: str) -> None:
        """Check the separately configured bootstrap principal."""

    def require_read(self, principal: str) -> None:
        """Check current scoped read authority without resolving execution grants."""


class DriverResource(Protocol):
    def close(self) -> None:
        """Close exactly this composition-owned driver."""


@dataclass(frozen=True)
class Settings:
    binding: ScopeBinding
    artifact_root: Path
    required_profiles: tuple[ProfileRevision, ...]


@dataclass(frozen=True)
class Composition:
    create_driver: Callable[[], DriverResource]
    create_store: Callable[[DriverResource], "Neo4jWorkflowStore"]
    authority: Authority
    bootstrap_principal: str
    read_principal: str
    protect: Callable[[object], None]
    tokens: TokenRegistry
    execution_factory: Callable | None = None


def create_app(*, settings: Settings, composition: Composition) -> FastAPI:
    """Open exact existing resources; administrative setup is a separate operation."""
    from contextlib import asynccontextmanager
    from dataclasses import replace
    from threading import Event, Lock

    from fastapi import Request

    from ..admin import WorkflowScopeAdmin
    from ..service import WorkflowService
    from .resolvers import OwnedOffload, QueryContext, finish_cleanup
    from .schema import schema as query_schema
    from .security import BearerBoundary

    schema = query_schema
    if composition.execution_factory is not None:
        import importlib

        # Fixed opt-in loaders, never config/plugin names. Execution cohorts must
        # explicitly root both modules; legacy static query closures stay exact.
        schema = importlib.import_module(
            "isaaclab_arena.agentic_environment_generation.workflow.api.execution_schema"
        ).schema
        execution_context = importlib.import_module(
            "isaaclab_arena.agentic_environment_generation.workflow.api.execution_owner"
        ).ExecutionContext

    assert composition.tokens.binding == settings.binding
    stop_requested, owner_lock = Event(), Lock()
    owner_slot = [None]

    def request_execution_stop():
        """Latch refusal and revoke before any request, query or admission drain."""
        stop_requested.set()
        composition.tokens.rotate()
        with owner_lock:
            app.state.ready = False
            current = owner_slot[0]
        if current is not None:
            try:
                current.request_stop()
            except Exception:
                app.state.cleanup_unknown = True

    @asynccontextmanager
    async def lifespan(app):
        executor = OwnedOffload()
        driver = None
        owner = None

        def boot():
            nonlocal driver, owner
            driver = composition.create_driver()
            store = composition.create_store(driver)
            resources = WorkflowScopeAdmin(store, composition.authority).verify_current_resources(
                composition.bootstrap_principal,
                settings.binding,
                root=settings.artifact_root,
                required_profiles=settings.required_profiles,
                protect=composition.protect,
            )
            service = WorkflowService(
                store,
                composition.authority,
                None,
                validate_support=None,
                read_scope=settings.binding,
            )
            if composition.execution_factory is not None:
                owner = composition.execution_factory(store, resources, composition.protect)
                with owner_lock:
                    owner_slot[0] = owner
                if stop_requested.is_set():
                    owner.request_stop()
            return resources, service

        try:
            try:
                resources, service = await executor.run(boot)
            except Exception:
                raise ValueError("Workflow API not ready") from None
            app.state.resources = resources
            app.state.query_context = QueryContext(service, composition, executor, artifact_root=settings.artifact_root)
            app.state.execution_owner = owner
            with owner_lock:
                app.state.ready = not stop_requested.is_set()
            yield
        finally:
            app.state.ready = False

            # Boot may still be finishing after cancellation; resolve driver after drain.
            def close_driver():
                if driver is not None:
                    driver.close()

            async def cleanup():
                import asyncio

                if composition.execution_factory is not None:
                    request_execution_stop()
                await executor.drain()
                if owner is not None:
                    while not owner._closed:
                        try:
                            await owner.close(recover_timeout=True)
                        except Exception:
                            app.state.cleanup_unknown = True
                            pending = owner._closing
                            if owner._close_failure == "timeout" and pending is not None:
                                try:
                                    await asyncio.shield(pending)
                                except (Exception, asyncio.CancelledError):
                                    await asyncio.Future()
                                continue
                            # Failed cleanup requires fenced recovery; never restart
                            # a drain after its executors/resources have closed.
                            await asyncio.Future()
                elif app.state.cleanup_unknown:
                    await asyncio.Future()
                await executor.close(close_driver)
                app.state.cleanup_unknown = False
                app.state.cleanup_complete = True

            try:
                await finish_cleanup(cleanup())
            except Exception:
                raise ValueError("Workflow API resource close failed") from None

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ready = False
    app.state.cleanup_unknown = False
    app.state.cleanup_complete = False
    app.state.request_execution_stop = request_execution_stop

    app.add_middleware(BearerBoundary, registry=composition.tokens)

    @app.post("/graphql")
    async def graphql(request: Request):
        import json

        from fastapi.responses import Response

        from .security import MAX_RESPONSE_BYTES, bounded_body, validate_document

        if not app.state.ready:
            return Response(content=b"", status_code=503)
        status = 200
        try:
            executing = composition.execution_factory is not None
            body = validate_document(await bounded_body(request, execution=executing), schema, execution=executing)
        except Exception:
            body = None
            status = 400
        value = {"errors": [{"message": "Query rejected"}]}
        if body is not None:
            try:
                context = replace(app.state.query_context, auth=request.scope["workflow_auth"])
                if app.state.execution_owner is not None:
                    context = execution_context(context, app.state.execution_owner)
                result = await schema.execute(
                    body["query"],
                    variable_values=body.get("variables"),
                    operation_name=body.get("operationName"),
                    context_value=context,
                )
                if not result.errors:
                    value = {"data": result.data}
            except Exception:
                status = 503
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) > MAX_RESPONSE_BYTES:
                value = {"errors": [{"message": "Response unavailable"}]}
                encoded = json.dumps(value, separators=(",", ":")).encode()
                status = 503
            from ..scene_evidence_artifacts import _protected

            encoded = _protected(value, composition.protect, max_bytes=MAX_RESPONSE_BYTES)
        except Exception:
            # No unprotected fallback GraphQL envelope after a trusted veto.
            return Response(content=b"", status_code=403, headers={"Cache-Control": "no-store"})
        return Response(
            content=encoded,
            status_code=status,
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    return app
