# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Trusted query-only ASGI composition with open-only owned resource lifetime."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Protocol

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


def create_app(*, settings: Settings, composition: Composition) -> FastAPI:
    """Open exact existing resources; administrative setup is a separate operation."""
    from contextlib import asynccontextmanager
    from dataclasses import replace

    from fastapi import Request

    from ..admin import WorkflowScopeAdmin
    from ..service import WorkflowService
    from .resolvers import OwnedOffload, QueryContext, finish_cleanup
    from .schema import schema
    from .security import BearerBoundary

    assert composition.tokens.binding == settings.binding

    @asynccontextmanager
    async def lifespan(app):
        executor = OwnedOffload()
        driver = None

        def boot():
            nonlocal driver
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
            return resources, service

        try:
            try:
                resources, service = await executor.run(boot)
            except Exception:
                raise ValueError("Workflow API not ready") from None
            app.state.resources = resources
            app.state.query_context = QueryContext(service, composition, executor)
            app.state.ready = True
            yield
        finally:
            app.state.ready = False

            # Boot may still be finishing after cancellation; resolve driver after drain.
            def close_driver():
                if driver is not None:
                    driver.close()

            try:
                await finish_cleanup(executor.close(close_driver))
            except Exception:
                raise ValueError("Workflow API resource close failed") from None

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ready = False

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
            body = validate_document(await bounded_body(request), schema)
        except Exception:
            body = None
            status = 400
        value = {"errors": [{"message": "Query rejected"}]}
        if body is not None:
            try:
                result = await schema.execute(
                    body["query"],
                    variable_values=body.get("variables"),
                    operation_name=body.get("operationName"),
                    context_value=replace(app.state.query_context, auth=request.scope["workflow_auth"]),
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
