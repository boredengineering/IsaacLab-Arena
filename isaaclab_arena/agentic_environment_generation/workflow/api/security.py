# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Nonbrowser local bearer authentication before body consumption."""

import hashlib
import math
import re
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass

from ..scope_binding import ScopeBinding


@dataclass(frozen=True)
class AuthContext:
    principal: str
    binding: ScopeBinding
    instance: str
    generation: int
    expires_at: float
    handle: str


class TokenRegistry:
    """Private in-memory tokens; construction never reads credentials or environment."""

    def __init__(
        self,
        *,
        binding: ScopeBinding,
        instance: str,
        generation: int,
        clock: Callable[[], float],
    ):
        assert type(instance) is str and instance and type(generation) is int and generation >= 1
        assert callable(clock)
        self.binding = binding
        self.instance = instance
        self.generation = generation
        self.clock = clock
        self._tokens = {}
        self._active = {}
        self._lock = threading.Lock()

    def issue(self, *, principal: str, lifetime: float) -> str:
        assert type(principal) is str and principal
        assert type(lifetime) in (float, int) and math.isfinite(lifetime) and 0 < lifetime <= 3600
        now = self.clock()
        assert math.isfinite(now) and now >= 0
        token = secrets.token_urlsafe(32)
        with self._lock:
            context = AuthContext(
                principal,
                self.binding,
                self.instance,
                self.generation,
                now + lifetime,
                secrets.token_hex(16),
            )
            self._tokens[hashlib.sha256(token.encode("ascii")).digest()] = context
            self._active[context.handle] = context
        return token

    def authenticate(self, value: bytes) -> AuthContext:
        if not re.fullmatch(rb"Bearer [A-Za-z0-9_-]{43}", value):
            raise PermissionError("Unauthorized")
        digest = hashlib.sha256(value[7:]).digest()
        now = self.clock()
        with self._lock:
            context = self._tokens.get(digest)
            self._check(context, now)
            return context

    def _check(self, context, now):
        if (
            context is None
            or self._active.get(context.handle) is not context
            or context.binding != self.binding
            or context.instance != self.instance
            or context.generation != self.generation
            or not math.isfinite(now)
            or now < 0
            or now >= context.expires_at
        ):
            raise PermissionError("Unauthorized")

    def recheck(self, context: AuthContext) -> None:
        now = self.clock()
        with self._lock:
            self._check(context, now)

    def revoke(self, context: AuthContext) -> None:
        with self._lock:
            self._active.pop(context.handle, None)

    def rotate(self) -> None:
        with self._lock:
            self.generation += 1
            self._active.clear()
            self._tokens.clear()


MAX_BODY_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def strict_json(raw):
    import json

    depth = 0
    quoted = escaped = False
    for char in raw.decode("utf-8"):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 32:
                raise ValueError("Request rejected")
        elif char in "]}":
            depth -= 1

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("Request rejected")
            value[key] = item
        return value

    def reject(_):
        raise ValueError("Request rejected")

    def finite_float(raw):
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError("Request rejected")
        return value

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject, parse_float=finite_float)
    if (
        type(value) is not dict
        or not set(value) <= {"query", "variables", "operationName"}
        or type(value.get("query")) is not str
        or type(value.get("variables", {})) is not dict
        or value.get("operationName") is not None
        and type(value["operationName"]) is not str
    ):
        raise ValueError("Request rejected")
    return value


async def bounded_body(request, *, execution=False):
    from ..contracts import MAX_CONTRACT_BYTES

    # A JSON string may escape every contract byte. Domain parsing separately
    # enforces the unchanged raw/canonical 2 MiB and depth-32 contract bounds.
    limit = 6 * MAX_CONTRACT_BYTES + MAX_BODY_BYTES if execution else MAX_BODY_BYTES
    declared = request.headers.get("content-length")
    if declared is not None and (not re.fullmatch(r"0|[1-9][0-9]{0,9}", declared) or int(declared) > limit):
        raise ValueError("Request rejected")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > limit:
            raise ValueError("Request rejected")
        data.extend(chunk)
    if declared is not None and len(data) != int(declared):
        raise ValueError("Request rejected")
    return strict_json(bytes(data))


def validate_document(body, schema, *, execution=False):
    """Bound the expanded operation and validate all variables before resolver IO."""
    from graphql import Undefined, get_variable_values, parse, validate, value_from_ast_untyped
    from graphql.language import OperationType, ast

    query = body["query"]
    if len(query.encode("utf-8")) > 16384:
        raise ValueError("Request rejected")
    document = parse(query, max_tokens=2048)
    operations = [n for n in document.definitions if isinstance(n, ast.OperationDefinitionNode)]
    fragments = {n.name.value: n for n in document.definitions if isinstance(n, ast.FragmentDefinitionNode)}
    if (
        len(operations) != 1
        or operations[0].operation
        not in ({OperationType.QUERY, OperationType.MUTATION} if execution else {OperationType.QUERY})
        or len(fragments) > 16
        or len(document.definitions) != 1 + len(fragments)
    ):
        raise ValueError("Request rejected")
    operation = operations[0]
    mutation = operation.operation == OperationType.MUTATION
    if body.get("operationName") is not None and (
        operation.name is None or operation.name.value != body["operationName"]
    ):
        raise ValueError("Request rejected")
    # Cycle/expansion limits run before GraphQL's recursive validation rules.
    counts = {"fields": 0, "aliases": 0, "roots": 0, "list_work": 0}

    def walk(selection, depth, stack, variables, cost, at_root=True):
        if depth > 16:
            raise ValueError("Request rejected")
        for node in selection.selections:
            if isinstance(node, ast.FragmentSpreadNode):
                name = node.name.value
                if name in stack or name not in fragments:
                    raise ValueError("Request rejected")
                walk(
                    fragments[name].selection_set,
                    depth + 1,
                    (*stack, name),
                    variables,
                    cost,
                    at_root,
                )
            elif isinstance(node, ast.InlineFragmentNode):
                walk(node.selection_set, depth + 1, stack, variables, cost, at_root)
            else:
                counts["fields"] += 1
                counts["aliases"] += node.alias is not None
                counts["roots"] += at_root
                if (
                    counts["fields"] > 256
                    or counts["aliases"] > 16
                    or counts["roots"] > (1 if mutation else 8)
                    or mutation
                    and at_root
                    and node.name.value not in {"submitWorkflow", "cancelWorkflow", "resumeWorkflow"}
                    or node.name.value in ("__schema", "__type")
                ):
                    raise ValueError("Request rejected")
                multiplier = 1
                if variables is not None:
                    args = {a.name.value: value_from_ast_untyped(a.value, variables) for a in node.arguments}
                    if "first" in args:
                        first = args["first"]
                        if type(first) is not int or not 1 <= first <= 1000:
                            raise ValueError("Request rejected")
                        counts["list_work"] += cost * first
                        multiplier = first
                    if (
                        "after" in args
                        and args["after"] is not None
                        and args["after"] is not Undefined
                        and (type(args["after"]) is not str or len(args["after"].encode("utf-8")) > 4096)
                    ):
                        raise ValueError("Request rejected")
                    if counts["list_work"] > 1000:
                        raise ValueError("Request rejected")
                if node.selection_set:
                    walk(
                        node.selection_set,
                        depth + 1,
                        stack,
                        variables,
                        cost * multiplier,
                        False,
                    )

    walk(operation.selection_set, 1, (), None, 1)
    if validate(schema._schema, document, max_errors=1):
        raise ValueError("Request rejected")
    variables = get_variable_values(
        schema._schema,
        operation.variable_definitions,
        body.get("variables", {}),
        max_errors=1,
    )
    if isinstance(variables, list):
        raise ValueError("Request rejected")
    counts.update(fields=0, aliases=0, roots=0, list_work=0)
    walk(operation.selection_set, 1, (), variables, 1)
    return body


async def fixed_error(send, status=401):
    """Constant transport refusal contains no request-dependent value."""
    body = b'{"errors":[{"message":"Request rejected"}]}'
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"cache-control", b"no-store"),
        ],
    })
    await send({"type": "http.response.body", "body": body})


class BearerBoundary:
    """Pure ASGI; bearer bytes are removed before calling the application."""

    def __init__(self, app, *, registry: TokenRegistry):
        self.app = app
        self.registry = registry

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return None
        headers = scope.get("headers", [])
        values = [v for k, v in headers if k.lower() == b"authorization"]
        try:
            if len(values) != 1:
                raise PermissionError("Unauthorized")
            context = self.registry.authenticate(values[0])
        except Exception:
            return await fixed_error(send)
        names = [k.lower() for k, _ in headers]
        allowed = {
            b"authorization",
            b"content-type",
            b"content-length",
            b"host",
            b"accept",
            b"accept-encoding",
            b"user-agent",
            b"connection",
        }
        if (
            len(names) != len(set(names))
            or any(n not in allowed for n in names)
            or scope.get("method") != "POST"
            or scope.get("path") != "/graphql"
            or scope.get("query_string")
            or dict(headers).get(b"content-type") not in (b"application/json", b"application/json; charset=utf-8")
        ):
            return await fixed_error(send, 400)
        scope = dict(
            scope,
            headers=[(k, v) for k, v in headers if k.lower() != b"authorization"],
            workflow_auth=context,
        )
        return await self.app(scope, receive, send)
