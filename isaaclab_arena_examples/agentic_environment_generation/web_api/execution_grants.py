# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Memory-only operation credentials, never a durable transaction or release journal."""

import copy
import json
import math
import secrets
import time

from .provider_security import reject_secret

CAPABILITIES = frozenset({"model", "retrieval_read", "publication_write", "reconciliation_read"})
MAX_GRANTS = 128
MAX_TTL_SECONDS = 7200
MAX_JSON_BYTES = 65536
MAX_JSON_DEPTH = 16
MAX_JSON_NODES = 4096


def _bounded_copy(value, *, max_bytes=MAX_JSON_BYTES, max_nodes=MAX_JSON_NODES):
    nodes = 0
    size = 0

    def visit(item, depth):
        nonlocal nodes, size
        nodes += 1
        size += 1
        if depth > MAX_JSON_DEPTH or nodes > max_nodes or size > max_bytes:
            raise ValueError("Invalid execution grant input")
        if type(item) is str:
            if len(item) > max_bytes:
                raise ValueError("Invalid execution grant input")
            size += len(item.encode("utf-8"))
        elif type(item) is dict:
            if len(item) > max_nodes:
                raise ValueError("Invalid execution grant input")
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("Invalid execution grant input")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            if len(item) > max_nodes:
                raise ValueError("Invalid execution grant input")
            for child in item:
                visit(child, depth + 1)
        elif item is None or type(item) is bool:
            pass
        elif type(item) in (int, float):
            if (type(item) is int and item.bit_length() > 256) or (type(item) is float and not math.isfinite(item)):
                raise ValueError("Invalid execution grant input")
        else:
            raise ValueError("Invalid execution grant input")

    try:
        visit(value, 0)
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"))
        if len(encoded) > max_bytes:
            raise ValueError("Invalid execution grant input")
        return json.loads(encoded)
    except (UnicodeError, OverflowError, RecursionError):
        raise ValueError("Invalid execution grant input") from None


def _finite(value):
    return type(value) in (int, float) and abs(value) < 1e100 and math.isfinite(value)


def _private_strings(credentials):
    def walk(value):
        if type(value) is str and value:
            yield value
        elif type(value) is dict:
            for child in value.values():
                yield from walk(child)
        elif type(value) is list:
            for child in value:
                yield from walk(child)

    # These top-level config fields are explicitly nonsecret; everything else is private.
    metadata = {"model", "endpoint", "base_url", "provider", "principal", "credential_generation"}
    if {"uri", "user", "database"} & credentials.keys():
        from .graph_access import checked_graph_config

        checked_graph_config(credentials)
        metadata.update({"uri", "user", "database"})
    if "inference_profile" in credentials:
        from isaaclab_arena.agentic_environment_generation.inference_profiles import checked_inference_profile

        checked_inference_profile(
            credentials["inference_profile"], model=credentials.get("model"), base_url=credentials.get("base_url")
        )
        metadata.add("inference_profile")
    if "workflow_accounting" in credentials:
        from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import (
            checked_workflow_accounting,
        )

        if any(type(credentials.get(key)) is not str or not credentials[key] for key in ("model", "base_url")):
            raise ValueError("Invalid workflow accounting origin")
        checked_workflow_accounting(
            credentials["workflow_accounting"], model=credentials["model"], endpoint=credentials["base_url"]
        )
        metadata.add("workflow_accounting")
    for key, value in credentials.items():
        if key not in metadata:
            yield from walk(value)


def _nonsecret_profile(value, path=()):
    if type(value) is dict:
        for key, child in value.items():
            if path == () and key == "inference_profile":
                from isaaclab_arena.agentic_environment_generation.inference_profiles import checked_inference_profile

                checked_inference_profile(child, model=value.get("model"), base_url=value.get("base_url"))
                continue
            normalized = key.lower().replace("_", "").replace("-", "")
            if any(
                word in normalized
                for word in ("secret", "password", "token", "apikey", "authorization", "cookie", "privatekey")
            ):
                raise ValueError("Invalid execution grant input")
            _nonsecret_profile(child, path + ("child",))
    elif type(value) is list:
        for child in value:
            _nonsecret_profile(child, path + ("child",))


class ExecutionGrants:
    """Keep detached credentials behind random operation-scoped references.

    Caller supplies nonsecret profile metadata (model, endpoint, principal and
    credential_generation); no environment lookup or credential fallback occurs.
    Pass expires_at=min(session['expires_at'], credential_expiry, now + MAX_TTL_SECONDS).
    Session expiry is not known here and MUST be capped by the caller. Resolve is
    synchronous: the caller must not await between validation and releasing bytes,
    and must serialize access if using multiple threads. Revocation cannot retract
    copies already returned. Durable released-operation records belong to the journal.
    """

    def __init__(self, *, clock=time.time, capacity=MAX_GRANTS):
        if type(capacity) is not int or not 1 <= capacity <= MAX_GRANTS:
            raise ValueError("Invalid execution grant capacity")
        self.clock = clock
        self._capacity = capacity
        self._records = {}

    def issue(self, owner_id, operation_id, capability, profile, credentials, expires_at):
        """Return detached metadata; caller must cap expires_at to session expiry."""
        now = self.clock()
        if (
            not _finite(now)
            or not _finite(expires_at)
            or not now < expires_at <= now + MAX_TTL_SECONDS
            or type(capability) is not str
            or capability not in CAPABILITIES
            or any(type(value) is not str or not 1 <= len(value) <= 256 for value in (owner_id, operation_id))
            or type(profile) is not dict
            or type(credentials) is not dict
        ):
            raise ValueError("Invalid execution grant input")
        profile = _bounded_copy(profile)
        credentials = _bounded_copy(credentials)
        self.purge()
        if len(self._records) >= self._capacity:
            raise ValueError("Execution grant capacity reached")
        grant_id = secrets.token_hex(32)
        if grant_id in self._records:
            raise ValueError("Execution grant reference unavailable")
        public = _bounded_copy(
            dict(
                grant_id=grant_id,
                owner_id=owner_id,
                operation_id=operation_id,
                capability=capability,
                profile=profile,
                expires_at=expires_at,
            )
        )
        _nonsecret_profile(profile)
        self.protect_public(public)
        for secret in _private_strings(credentials):
            reject_secret(public, secret)
        self._records[grant_id] = (copy.deepcopy(public), credentials)
        return public

    def protect_public(self, value):
        """Reject bounded public JSON containing retained secrets, including nested keys.

        This is not a general DLP scanner: forgotten credentials are no longer held,
        and caller-declared top-level config metadata must already be nonsecret.
        """
        value = _bounded_copy(value, max_bytes=2 * 1024 * 1024, max_nodes=131072)
        for _, credentials in self._records.values():
            for secret in _private_strings(credentials):
                reject_secret(value, secret)

    def revoke(self, grant_id):
        """Forget one grant; revoking an absent reference is harmless."""
        self._records.pop(grant_id, None)

    def forget_owner(self, owner_id):
        """Forget all private grants owned by a session."""
        for grant_id, (public, _) in tuple(self._records.items()):
            if public["owner_id"] == owner_id:
                self.revoke(grant_id)

    def purge(self):
        """Forget grants at or past their exact expiry boundary."""
        now = self.clock()
        if not _finite(now):
            raise ValueError("Execution grant unavailable")
        for grant_id, (public, _) in tuple(self._records.items()):
            if now >= public["expires_at"]:
                self.revoke(grant_id)

    def clear(self):
        """Drop all in-memory grants without any persistence or provider calls."""
        self._records.clear()

    def resolve(self, owner_id, grant_id, operation_id, capability):
        """Return detached private configuration."""
        self.purge()
        if type(grant_id) is not str:
            raise ValueError("Execution grant unavailable")
        record = self._records.get(grant_id)
        if record is None or any(
            record[0][key] != value
            for key, value in (("owner_id", owner_id), ("operation_id", operation_id), ("capability", capability))
        ):
            raise ValueError("Execution grant unavailable")
        return copy.deepcopy(record[1])
