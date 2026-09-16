# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Capture private operation configuration; durable jobs contain only scoped references."""

import secrets
from collections.abc import Callable
from copy import deepcopy
from urllib.parse import urlsplit

from fastapi import HTTPException

from . import generation, graph_access
from .execution_grants import ExecutionGrants
from .public_records import screen_public_record


class WorkflowAuthorization:
    """Authorize for at most 180 seconds, capped by session and temporary-key expiry.

    Resolve is synchronous and repeatable; call again after spawn immediately before
    releasing bytes. Already released detached copies may finish their bounded calls.
    """

    def __init__(self, sessions, model_settings, *, clock, journal=None):
        self.journal = journal
        self.sessions = sessions
        self.model_settings = model_settings
        self.clock = clock
        self.grants = ExecutionGrants(clock=clock)
        self.managed_context_getter: Callable | None = None
        self._managed_contexts = {}

    def capture(self, session, operation_id, *, credential_ref=None, retrieval=True, require_service=False,
                protect_public=None):
        owner = session["session_id"]
        config = self.model_settings.resolve(owner, credential_ref) if credential_ref else generation.configuration()
        if config is None:
            raise ValueError("Generation is not configured")
        graph = graph_access.configuration() if retrieval else None
        if require_service and graph is None:
            raise ValueError("Required retrieval service is not configured")
        expiry = min(session["expires_at"], self.clock() + 180)
        if credential_ref:
            expiry = min(expiry, self.model_settings.credential_expiry(owner, credential_ref))
        profile = {key: config[key] for key in ("provider", "model", "base_url", "principal") if key in config}
        for value in profile.values():
            if type(value) is not str or not 1 <= len(value) <= 2048 or any(ord(c) < 32 for c in value):
                raise ValueError("Invalid workflow profile")
        if "base_url" in profile:
            parsed = urlsplit(profile["base_url"])
            if (
                parsed.scheme not in ("https", "http")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Invalid workflow endpoint")
        profile.update(
            source="session" if credential_ref else "server",
            credential_generation=credential_ref or secrets.token_hex(16),
        )
        model_profile = profile
        retrieval_profile = None
        managed = None
        if graph is not None:
            graph = graph_access.checked_graph_config(graph)
            retrieval_profile = {key: graph[key] for key in ("uri", "user", "database")}
            retrieval_profile["credential_generation"] = secrets.token_hex(16)
            managed = None if self.managed_context_getter is None else self.managed_context_getter(graph)
            if managed is not None:
                from .managed_retrieval import context_digest

                retrieval_profile["managed_context_sha256"] = context_digest(managed)
        # Resolve and screen every public profile before issuing even the first grant.
        # Private credentials never cross this public boundary.
        public_profiles = {"model": model_profile, "retrieval": retrieval_profile}
        try:
            screen_public_record(public_profiles, self.model_settings.protect_public)
        except HTTPException:
            raise
        except Exception:
            # Screening faults are not immutable domain rejection evidence.
            # Keep configuration/profile validation outside this narrow guard.
            raise HTTPException(503, "Workflow public profile screening unavailable") from None
        if protect_public is not None:
            # Additional caller policy cannot replace the base guard or rewrite
            # the already-screened profiles used for grants.
            protect_public(deepcopy(public_profiles))
        model = self.grants.issue(owner, operation_id, "model", model_profile, config, expiry)
        result = {"model": model, "retrieval": None}
        try:
            if graph is not None:
                result["retrieval"] = self.grants.issue(
                    owner, operation_id, "retrieval_read", retrieval_profile, graph, expiry
                )
                self._managed_contexts = {
                    key: value for key, value in self._managed_contexts.items() if key in self.grants._records
                }
                if managed is not None:
                    self._managed_contexts[result["retrieval"]["grant_id"]] = deepcopy(managed)
            return result
        except Exception:
            self.rollback(result)
            raise

    def rollback(self, metadata):
        for grant in metadata.values():
            if grant is not None:
                self.grants.revoke(grant["grant_id"])
                self._managed_contexts.pop(grant["grant_id"], None)

    def capture_renewal(self, session, job, *, credential_ref=None):
        """Explicit workspace approval permits a new owner, never a new operation profile."""
        original = job["inputs"]["workflow_authorization"]
        profile = original["model"]["profile"]
        if (profile["source"] == "session") != (credential_ref is not None):
            raise ValueError("Renewal requires the original credential source")
        metadata = self.capture(
            session,
            self.journal.workflow_binding(job, generation=self.journal.renewable_attempt(job["id"])["generation"] + 1),
            credential_ref=credential_ref,
            retrieval=original["retrieval"] is not None,
            require_service=original["retrieval"] is not None,
        )
        try:
            for capability in ("model", "retrieval"):
                old, new = original[capability], metadata[capability]
                if old is None:
                    if new is not None:
                        raise ValueError("Renewal profile changed")
                    continue
                frozen = {k: v for k, v in old["profile"].items() if k != "credential_generation"}
                current = {k: v for k, v in new["profile"].items() if k != "credential_generation"}
                if frozen != current:
                    raise ValueError("Renewal profile changed")
            return metadata
        except Exception:
            self.rollback(metadata)
            raise

    def resolve(self, job, *, attempt=None):
        if self.journal is None:
            raise ValueError("Workflow authorization unavailable")
        operation_id = self.journal.workflow_binding(job, attempt=attempt)
        renewal = self.journal.latest_authorization(job["id"]) if self.journal else None
        metadata = renewal["workflow_authorization"] if renewal else job["inputs"]["workflow_authorization"]
        owner = metadata["model"]["owner_id"] if renewal else job["created_by_session_id"]
        if self.sessions.get_by_id(owner) is None:
            raise ValueError("Workflow authorization unavailable")
        model = metadata["model"]
        config = self.grants.resolve(owner, model["grant_id"], operation_id, "model")
        current = (
            self.model_settings.resolve(owner, model["profile"]["credential_generation"])
            if model["profile"]["source"] == "session"
            else generation.configuration()
        )
        if current != config:
            raise ValueError("Workflow authorization unavailable")
        graph = metadata["retrieval"]
        graph_config = (
            None if graph is None else self.grants.resolve(owner, graph["grant_id"], operation_id, "retrieval_read")
        )
        if graph_config is not None and graph_access.configuration() != graph_config:
            raise ValueError("Workflow authorization unavailable")
        private = {"config": config, "graph_config": graph_config}
        if graph is not None and "managed_context_sha256" in graph["profile"]:
            from .managed_retrieval import context_digest

            frozen = self._managed_contexts.get(graph["grant_id"])
            current = None if self.managed_context_getter is None else self.managed_context_getter(graph_config)
            if (
                frozen is None
                or current != frozen
                or context_digest(frozen) != graph["profile"]["managed_context_sha256"]
            ):
                raise ValueError("Managed retrieval authorization unavailable")
            private["managed_context"] = deepcopy(frozen)
        return private

    def protect_public(self, value):
        self.grants.protect_public(value)

    def clear(self):
        self.grants.clear()
        self._managed_contexts.clear()
