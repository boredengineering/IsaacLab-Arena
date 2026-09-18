# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Trusted local composition only: explicit bindings, no login or ambient settings."""

import copy
import hashlib
import json
import math
import re
from contextlib import contextmanager
from functools import wraps
from threading import RLock

from isaaclab_arena.agentic_environment_generation.workflow.attempts import AuthorizationSnapshot
from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json, contract_digest

from .web_api.generation import freeze_configuration
from .web_api.provider_security import checked_config


def _locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return call


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _config(config):
    trusted = isinstance(config, dict) and config.get("trusted_server") is True
    result = freeze_configuration(checked_config(config, trusted_server=trusted))
    if trusted:
        result["trusted_server"] = True
    return result


def model_settings_sha256(config, *, billing):
    """Hash literal nonsecret settings and frozen inference policy, never the key."""
    if billing not in {"free", "paid"}:
        raise ValueError("Invalid model billing")
    frozen = _config(config)
    return _hash({
        "version": 1,
        "model": frozen["model"],
        "endpoint": frozen["base_url"],
        "billing": billing,
        "inference_policy": frozen.get("inference_profile"),
    })


def _deadline(value):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("Foreground authority unavailable")
    return value


class ForegroundAuthority:
    """Run-scoped private grants; exact store fences constrain every attempt resolve.

    principal_lookup returns trusted principal/scope/expires_at/revoked metadata.
    current_config(profile_id) returns explicit config/expires_at; neither callback
    may load ambient credentials. Profiles are approved nonsecret ModelProfile dicts.
    The trusted caller owns principal revocation; this is not an HTTP authenticator.
    This is a single trusted local operator boundary, not per-principal paid/read
    roles. All callback-owned mutations must use mutation_guard.
    Grant metadata is deliberately run-bound, never fictitious attempt metadata.
    """

    def __init__(
        self, *, database, deployment_id, workspace_id, store, grants, clock, principal_lookup, profiles, current_config
    ):
        self.scope = dict(database=database, deployment_id=deployment_id, workspace_id=workspace_id)
        self.store, self.grants, self.clock = store, grants, clock
        self.principal_lookup, self.current_config = principal_lookup, current_config
        self.profiles = copy.deepcopy(profiles)
        self._lock = RLock()
        self._closed = False
        self._bindings = {}
        self._scope_check()

    @contextmanager
    def mutation_guard(self):
        """Serialize trusted principal/source changes with release; never call coordinator here.

        This adapter exclusively owns ExecutionGrants. Raw external grant mutation
        is unsupported. Callback owners must hold this guard for all principal,
        approved-profile and source mutations, including callback replacement.
        Lock order is coordinator interlock, authority guard, then owner lease.
        """
        with self._lock:
            yield

    @contextmanager
    def release_guard(self, principal, contract, fence, registration):
        """Hold current authority from final resolution through bounded send."""
        with self._lock:
            self.private_envelope(principal, contract, fence, registration)
            yield

    @_locked
    def revoke_run(self, run_id):
        retained = self._bindings.pop(run_id, None)
        if retained is not None:
            self.grants.revoke(retained[0].grant_ref)

    @_locked
    def close(self):
        for run_id in tuple(self._bindings):
            self.revoke_run(run_id)
        self._closed = True

    def _scope_check(self):
        if self._closed:
            raise ValueError("Foreground authority closed")
        if self.store.database != self.scope["database"] or self.store.scope != {
            k: v for k, v in self.scope.items() if k != "database"
        }:
            raise ValueError("Foreground scope unavailable")

    @_locked
    def require_read(self, principal):
        """Check current trusted principal without touching execution grants."""
        self._scope_check()
        p = self.principal_lookup(principal)
        if (
            not isinstance(p, dict)
            or p.get("principal") != principal
            or p.get("revoked") is not False
            or any(p.get(k) != v for k, v in self.scope.items())
            or _deadline(self.clock()) >= _deadline(p.get("expires_at"))
        ):
            raise ValueError("Foreground authority unavailable")
        return p

    @_locked
    def protect_public(self, value):
        self.grants.protect_public(value)

    @_locked
    def require_submit(self, principal, operation_id, contract):
        """Check intent only; replay remains independent of execution credentials."""
        self.require_read(principal)
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Invalid operation")
        if contract.source.kind != "new" or contract.effects.allow_database_reads:
            raise ValueError("Foreground refinement and research reads are unsupported")
        if not contract.effects.allow_operational_writes:
            raise ValueError("Operational writes require permission")
        self.protect_public(contract.model_dump(mode="json"))

    def _retained(self, principal, contract, run_id, operation_id=None):
        self.require_read(principal)
        run = self.store.get_run(run_id)
        if (
            run is None
            or run.run_id != run_id
            or run.contract_json != canonical_json(contract)
            or (operation_id is not None and run.operation_id != operation_id)
        ):
            raise ValueError("Exact retained run required")
        self.require_submit(principal, run.operation_id, contract)
        return run

    def _source(self, contract):
        profile = contract.execution.generation_model.model_dump(mode="json")
        if self.profiles.get(profile["profile_id"]) != profile:
            raise ValueError("Approved frozen profile required")
        source = self.current_config(profile["profile_id"])
        if not isinstance(source, dict):
            raise ValueError("Explicit model source required")
        config = _config(source.get("config"))
        if model_settings_sha256(config, billing=profile["billing"]) != profile["settings_sha256"]:
            raise ValueError("Frozen model settings changed")
        return profile, config, _deadline(source.get("expires_at"))

    @_locked
    def bind_run(self, principal, operation_id, contract, *, run_id, catalogue_sha256):
        """Explicitly capture a retained run; repeated binds never renew implicitly."""
        self._retained(principal, contract, run_id, operation_id)
        if (
            run_id in self._bindings
            or not isinstance(catalogue_sha256, str)
            or not re.fullmatch("[0-9a-f]{64}", catalogue_sha256)
        ):
            raise ValueError("Explicit new binding required")
        return self._issue(principal, contract, run_id, operation_id, catalogue_sha256)

    def _issue(self, principal, contract, run_id, operation_id, catalogue):
        p = self.require_read(principal)
        profile, config, credential_expiry = self._source(contract)
        expires = min(_deadline(p["expires_at"]), credential_expiry, _deadline(self.clock()) + 180)
        binding = _hash(
            dict(
                version=1,
                scope=self.scope,
                operation=operation_id,
                run=run_id,
                contract=canonical_json(contract),
                catalogue=catalogue,
            )
        )
        public = self.grants.issue(principal, binding, "model", profile, config, expires)
        capabilities = ["generation_model", "operational_writes"]
        if contract.effects.allow_paid_models:
            capabilities.append("paid_models")
        try:
            snapshot = AuthorizationSnapshot(
                **self.scope,
                principal=principal,
                grant_ref=public["grant_id"],
                contract_digest=contract_digest(contract),
                expires_at=expires,
                capabilities=tuple(capabilities),
            )
            self.protect_public(contract.model_dump(mode="json"))
        except BaseException:
            self.grants.revoke(public["grant_id"])
            raise
        old = self._bindings.get(run_id)
        self._bindings[run_id] = (snapshot, binding, catalogue, profile)
        if old:
            self.grants.revoke(old[0].grant_ref)
        return snapshot

    @_locked
    def private_envelope(self, principal, contract, fence, registration):
        """Revalidate retained registration and emit the existing bounded worker packet."""
        snapshot = self.require_execute(principal, contract, run_id=fence.run_id, fence=fence)
        attempt = self.store.get_attempt(fence)
        if registration.fence != fence or attempt.fence != fence or attempt.registration != registration:
            raise ValueError("Exact retained registration required")
        _, binding, catalogue, _ = self._bindings[fence.run_id]
        config = self.grants.resolve(principal, snapshot.grant_ref, binding, "model")
        packet = {
            "inputs": {
                "operation": "new",
                "prompt": contract.source.prompt,
                "retrieval_policy": "allow_fallback",
                "execution_catalogue_sha256": catalogue,
            },
            "config": config,
            "graph_config": None,
        }
        encoded = (json.dumps(packet, allow_nan=False, separators=(",", ":")) + "\n").encode()
        if len(encoded) > 512 * 1024:
            raise ValueError("Private generation packet too large")
        return encoded

    @_locked
    def renew_run(self, principal, contract, *, run_id):
        """Explicit credential renewal only within the same retained frozen intent."""
        run = self._retained(principal, contract, run_id)
        old = self._bindings.get(run_id)
        if old is None or old[0].principal != principal or old[0].contract_digest != contract_digest(contract):
            raise ValueError("Exact original binding required")
        return self._issue(principal, contract, run_id, run.operation_id, old[2])

    @_locked
    def require_execute(self, principal, contract, *, run_id, fence=None):
        """Revalidate exact run, current source and optional retained attempt fence."""
        run = self._retained(principal, contract, run_id)
        retained = self._bindings.get(run_id)
        if retained is None:
            raise ValueError("Explicit execution binding required")
        snapshot, binding, catalogue, profile = retained
        expected = _hash(
            dict(
                version=1,
                scope=self.scope,
                operation=run.operation_id,
                run=run_id,
                contract=canonical_json(contract),
                catalogue=catalogue,
            )
        )
        if snapshot.principal != principal or expected != binding:
            raise ValueError("Exact execution binding required")
        if fence is not None:
            if fence.run_id != run_id:
                raise ValueError("Exact retained attempt required")
            attempt = self.store.get_attempt(fence)
            if (
                fence.run_id != run_id
                or attempt.fence != fence
                or attempt.contract_json != canonical_json(contract)
                or attempt.authorization.model_dump(exclude={"grant_ref", "expires_at"})
                != snapshot.model_dump(exclude={"grant_ref", "expires_at"})
            ):
                raise ValueError("Exact retained attempt required")
        current_profile, current, expires = self._source(contract)
        config = self.grants.resolve(principal, snapshot.grant_ref, binding, "model")
        if current != config or profile != current_profile or self.clock() >= min(expires, snapshot.expires_at):
            raise ValueError("Execution source changed or expired")
        return snapshot
