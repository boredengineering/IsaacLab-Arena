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

from isaaclab_arena.agentic_environment_generation.inference_profiles import (
    ModelProfileUnavailable,
    freeze_configuration,
)
from isaaclab_arena.agentic_environment_generation.workflow.attempts import AuthorizationSnapshot
from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json, contract_digest
from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import checked_workflow_accounting

from .web_api.provider_security import checked_config, reject_secret


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
    if "workflow_accounting" in config:
        result["workflow_accounting"] = checked_workflow_accounting(
            config["workflow_accounting"], model=result["model"], endpoint=result["base_url"]
        )
        reject_secret(result["workflow_accounting"], result["api_key"])
    if trusted:
        result["trusted_server"] = True
    return result


def model_settings_sha256(config, *, billing):
    """Hash literal nonsecret settings and frozen inference policy, never the key."""
    if billing not in {"free", "paid"}:
        raise ValueError("Invalid model billing")
    frozen = _config(config)
    settings = {
        "version": 1,
        "model": frozen["model"],
        "endpoint": frozen["base_url"],
        "billing": billing,
        "inference_policy": frozen.get("inference_profile"),
    }
    if "workflow_accounting" in frozen:
        settings["workflow_accounting"] = frozen["workflow_accounting"]
    return _hash(settings)


def _deadline(value) -> int | float:
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
        self._workflow_bindings = {}
        self._release_scopes = []
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
    def release_guard(self, principal, contract, fence=None, registration=None, *, run_id=None):
        """Hold authority through bounded send; scene adapters pass only run_id.

        Scene adapters must validate their retained stage fence/registration and
        lease inside this guard, then resolve private_model_config immediately
        before bounded send. This guard grants no stage or price permission.
        """
        with self._lock:
            if run_id is None:
                self.private_envelope(principal, contract, fence, registration)
                yield
            else:
                if fence is not None or registration is not None:
                    raise ValueError("Ambiguous release scope")
                self.require_scene_execute(principal, contract, run_id=run_id)
                self._release_scopes.append((principal, run_id, contract_digest(contract)))
                try:
                    yield
                finally:
                    self._release_scopes.pop()

    @_locked
    def revoke_run(self, run_id):
        for reference, _, _, _ in self._workflow_bindings.pop(run_id, {}).values():
            self.grants.revoke(reference)
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

    def _source(self, contract, *, role="generation"):
        if role not in ("generation", "assessment"):
            raise ValueError("Unsupported model role")
        model_profile = (
            contract.execution.generation_model if role == "generation" else contract.execution.assessment_model
        )
        profile = model_profile.model_dump(mode="json")
        if self.profiles.get(profile["profile_id"]) != profile:
            raise ModelProfileUnavailable("Approved frozen profile required")
        source = self.current_config(profile["profile_id"])
        if not isinstance(source, dict):
            raise ValueError("Explicit model source required")
        config = _config(source.get("config"))
        if model_settings_sha256(config, billing=profile["billing"]) != profile["settings_sha256"]:
            raise ModelProfileUnavailable("Frozen model settings changed")
        return profile, config, _deadline(source.get("expires_at"))

    @_locked
    def require_token_cost_bound(self, principal, contract, *, role="generation"):
        """Gate new hard-budget admission on a current approved total-call attestation.

        Returns a detached private bound, not a grant or provider-bill verification.
        Legacy count-only admission deliberately does not call this opt-in gate.
        """
        self.require_read(principal)
        profile, config, expires = self._source(contract, role=role)
        if profile["billing"] == "paid" and not contract.effects.allow_paid_models:
            raise ValueError("Paid model permission required")
        if self.clock() >= expires or "workflow_accounting" not in config:
            raise ValueError("Current attested token/cost bound required")
        return dict(config["workflow_accounting"])

    @_locked
    def require_workflow_model_bounds(self, principal, contract):
        """Check every required model role using the same full-outcome dependency projection."""
        from isaaclab_arena.agentic_environment_generation.workflow.readiness import required_dependencies

        self.require_read(principal)
        required = {item.dependency_id for item in required_dependencies(contract)}
        return {
            role: self.require_token_cost_bound(principal, contract, role=role)
            for role in ("generation", "assessment")
            if role + "_model" in required
        }

    def _workflow_sources(self, principal, contract, *, operation_id=None):
        from isaaclab_arena.agentic_environment_generation.workflow.readiness import required_dependencies

        self.require_read(principal)
        required = {item.dependency_id for item in required_dependencies(contract)}
        sources = {
            role: self._source(contract, role=role)
            for role in ("generation", "assessment")
            if role + "_model" in required
        }
        public = {"contract": contract.model_dump(mode="json"), "profiles": [s[0] for s in sources.values()]}
        if operation_id is not None:
            public["operation_id"] = operation_id
        self.protect_public(public)
        for profile, config, expires in sources.values():
            if profile["billing"] == "paid" and not contract.effects.allow_paid_models:
                raise ValueError("Paid model permission required")
            if _deadline(self.clock()) >= expires:
                raise ValueError("Execution source changed or expired")
            reject_secret(public, config["api_key"])
        return sources

    @_locked
    def protect_workflow_contract(self, principal, contract, *, operation_id=None):
        """Screen fresh full intent against every required current key before persistence.

        Check-only: no grant, renewal, model construction or dependency probe.
        The composition root includes operation_id before accepting a fresh run;
        ordinary read/replay paths deliberately do not resolve current sources.
        """
        self._workflow_sources(principal, contract, operation_id=operation_id)

    def _issue_workflow_roles(self, principal, snapshot, binding, sources):
        roles = {}
        try:
            for role, (profile, config, expiry) in sources.items():
                if role == "generation":
                    continue
                operation = _hash(dict(version=1, run_binding=binding, role=role))
                expires = min(expiry, snapshot.expires_at)
                public = self.grants.issue(principal, operation, "model", profile, config, expires)
                roles[role] = (public["grant_id"], operation, profile, expires)
        except BaseException:
            for reference, _, _, _ in roles.values():
                self.grants.revoke(reference)
            raise
        return roles

    @_locked
    def bind_workflow_models(self, principal, contract, *, run_id):
        """Explicitly capture required extra roles after generation's retained binding.

        Return existing run metadata, never extra public bearer authority.
        """
        snapshot = self.require_execute(principal, contract, run_id=run_id)
        if run_id in self._workflow_bindings:
            raise ValueError("Explicit new workflow binding required")
        sources = self._workflow_sources(principal, contract)
        self._workflow_bindings[run_id] = self._issue_workflow_roles(
            principal, snapshot, self._bindings[run_id][1], sources
        )
        return snapshot

    @_locked
    def require_scene_execute(self, principal, contract, *, run_id):
        """Check all explicitly captured roles; retain the existing run snapshot."""
        snapshot = self.require_execute(principal, contract, run_id=run_id)
        roles = self._workflow_bindings.get(run_id)
        if roles is None:
            raise ValueError("Explicit workflow model binding required")
        sources = self._workflow_sources(principal, contract)
        if set(roles) != set(sources) - {"generation"}:
            raise ValueError("Exact workflow roles required")
        for role, (reference, binding, profile, expiry) in roles.items():
            current_profile, current, current_expiry = sources[role]
            config = self.grants.resolve(principal, reference, binding, "model")
            if profile != current_profile or config != current or self.clock() >= min(expiry, current_expiry):
                raise ValueError("Execution source changed or expired")
        return snapshot

    @_locked
    def private_model_config(self, principal, contract, *, run_id, role):
        """Detach one private role only inside this run's held scene release guard."""
        scope = (principal, run_id, contract_digest(contract))
        if scope not in self._release_scopes:
            raise ValueError("Held scene release guard required")
        snapshot = self.require_scene_execute(principal, contract, run_id=run_id)
        if role == "generation":
            reference, binding = snapshot.grant_ref, self._bindings[run_id][1]
        else:
            if role not in self._workflow_bindings[run_id]:
                raise ValueError("Unbound workflow model role")
            reference, binding, _, _ = self._workflow_bindings[run_id][role]
        return self.grants.resolve(principal, reference, binding, "model")

    @_locked
    def private_model_deadline(self, principal, contract, *, run_id, role):
        """Bound a held private release by original grant and current source lifetimes."""
        self.private_model_config(principal, contract, run_id=run_id, role=role)
        snapshot = self._bindings[run_id][0]
        expiry = snapshot.expires_at if role == "generation" else self._workflow_bindings[run_id][role][3]
        _, _, current_expiry = self._source(contract, role=role)
        return min(expiry, snapshot.expires_at, current_expiry, _deadline(self.require_read(principal)["expires_at"]))

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

    def _issue(self, principal, contract, run_id, operation_id, catalogue, *, workflow_sources=None):
        p = self.require_read(principal)
        profile, config, credential_expiry = self._source(contract)
        public_intent = {"contract": contract.model_dump(mode="json"), "profile": profile}
        self.protect_public(public_intent)
        reject_secret(public_intent, config["api_key"])
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
            if workflow_sources is not None:
                roles = self._issue_workflow_roles(principal, snapshot, binding, workflow_sources)
        except BaseException:
            self.grants.revoke(public["grant_id"])
            raise
        old = self._bindings.get(run_id)
        self._bindings[run_id] = (snapshot, binding, catalogue, profile)
        if workflow_sources is not None:
            old_roles = self._workflow_bindings.get(run_id, {})
            self._workflow_bindings[run_id] = roles
            for reference, _, _, _ in old_roles.values():
                self.grants.revoke(reference)
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
            "workflow_execution": {
                "version": 1,
                "fence": attempt.fence.model_dump(mode="json"),
                "registration": attempt.registration.model_dump(mode="json"),
                "reservation": attempt.reservation.model_dump(mode="json"),
                "admitted_at": attempt.admitted_at,
                "released_at": attempt.released_at,
                "deadline": min(
                    attempt.admitted_at + contract.budget.total_deadline_seconds,
                    snapshot.expires_at,
                    *(
                        [attempt.released_at + attempt.reservation.runtime_allowance_seconds]
                        if attempt.released_at is not None
                        else []
                    ),
                ),
            },
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
        sources = self._workflow_sources(principal, contract) if run_id in self._workflow_bindings else None
        return self._issue(principal, contract, run_id, run.operation_id, old[2], workflow_sources=sources)

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
