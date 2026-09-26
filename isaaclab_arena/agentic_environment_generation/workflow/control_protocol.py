# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure control/credential selections for G2; no issuer, timer, executor or ledger.

The installed owner must authenticate/recheck and retain issued snapshots. A
snapshot is not authority. Renewal cannot change admitted intent or allocation.
The schema-2 descriptor below is public binding metadata, never bearer material.
"""

import math
from typing import Literal

from pydantic import model_validator

from .attempts import AttemptFence, AuthorizationSnapshot, PositiveCount
from .contracts import Amount, ControlPolicy, FrozenModel, Hash, Identifier
from .scope_binding import ScopeBinding


def _finite(value):
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        raise ValueError("finite nonnegative clock/bound required")
    return value


def finite_backend_timeout(value, *, ceiling=120.0):
    """Resolve a positive transport/readiness bound, not aggregate runtime policy."""
    value, ceiling = _finite(value), _finite(ceiling)
    if not value or not ceiling:
        raise ValueError("positive finite backend bound required")
    return min(value, ceiling)


def legacy_monotonic_deadline(value, *, wall_now, monotonic_now):
    """Resolve a legacy fixed deadline; null never reaches legacy arithmetic."""
    value, wall_now, monotonic_now = _finite(value), _finite(wall_now), _finite(monotonic_now)
    deadline = monotonic_now + value - wall_now
    if deadline <= monotonic_now:
        raise TimeoutError("expired stage release")
    return deadline


class PrincipalDescriptor(FrozenModel):
    """Exact current-principal metadata of a version-2 private client descriptor."""

    schema_version: Literal[2]
    binding: ScopeBinding
    instance: Identifier
    principal: Identifier
    generation: PositiveCount
    credential_revision: PositiveCount
    context_handle: Identifier
    issued_at: Amount
    expires_at: Amount

    @model_validator(mode="after")
    def lifetime(self):
        if self.issued_at >= self.expires_at:
            raise ValueError("finite credential lifetime required")
        return self


def _require_workload(authority, *, scope, principal, contract_digest, capability, now):
    if authority is None:
        raise PermissionError("current workload authority required separately")
    authority = AuthorizationSnapshot.model_validate(authority.model_dump(mode="json"))
    if (
        (authority.database, authority.deployment_id, authority.workspace_id)
        != (scope.database, scope.deployment_id, scope.workspace_id)
        or authority.principal != principal
        or authority.contract_digest != contract_digest
        or capability not in authority.capabilities
        or now >= authority.expires_at
    ):
        raise PermissionError("current exact workload authority required")
    return authority


def resolve_current_principal(
    previous,
    descriptor,
    current,
    *,
    policy,
    now,
    generation,
    recheck,
    action,
    contract_digest,
    authority=None,
    capability=None,
):
    """Rebind to an authenticated current context; refresh never renews approval.

    Args:
        previous: Previously selected public descriptor, possibly expired.
        descriptor: Offered descriptor metadata, delivered by the trusted issuer.
        current: Exact AuthContext obtained by authenticating the offered credential.
        policy: Frozen finite lifetime/descriptor policy.
        now: Trusted current wall clock.
        generation: Current issuer registry generation, not caller-selected.
        recheck: Trusted TokenRegistry.recheck equivalent; must reject revoked contexts.
        action: Read/cancel or continuation, never a grant operation.
        contract_digest: Frozen workload identity.
        authority: Separately current trusted workload-grant snapshot for continuation.
        capability: Explicit requested workload capability for continuation.

    Returns:
        The offered current context for atomic server/composition rebinding in G2.
    """
    now = _finite(now)
    if current is None or not callable(recheck):
        raise PermissionError("authenticated current principal required")
    recheck(current)
    previous = PrincipalDescriptor.model_validate(previous.model_dump(mode="json"))
    descriptor = PrincipalDescriptor.model_validate(descriptor.model_dump(mode="json"))
    policy = ControlPolicy.model_validate(policy.model_dump(mode="json"))
    if (
        policy.client_descriptor_schema != "2"
        or type(generation) is not int
        or generation < 1
        or (descriptor.binding, descriptor.instance, descriptor.principal)
        != (previous.binding, previous.instance, previous.principal)
        or (
            descriptor.binding,
            descriptor.instance,
            descriptor.principal,
            descriptor.generation,
            descriptor.context_handle,
            descriptor.expires_at,
        )
        != (
            current.binding,
            current.instance,
            current.principal,
            current.generation,
            current.handle,
            current.expires_at,
        )
        or descriptor.generation != generation
        or descriptor.generation < previous.generation
        or descriptor.credential_revision < previous.credential_revision
        or (descriptor.credential_revision == previous.credential_revision and descriptor != previous)
        or not descriptor.issued_at <= now < descriptor.expires_at
        or descriptor.expires_at - descriptor.issued_at > policy.max_credential_lifetime_seconds
    ):
        raise PermissionError("exact current principal/instance/scope/credential generation required")
    if action == "continue":
        _require_workload(
            authority,
            scope=descriptor.binding,
            principal=descriptor.principal,
            contract_digest=contract_digest,
            capability=capability,
            now=now,
        )
    elif action not in ("read", "cancel"):
        raise PermissionError("unsupported control action")
    return current


class SupervisionLease(FrozenModel):
    """Fenced finite parent-control metadata, independently of experiment horizons."""

    codec: Literal["supervision-lease-v1"]
    fence: AttemptFence
    scope_sha256: Hash
    instance: Identifier
    principal: Identifier
    contract_digest: Hash
    allocation_digest: Hash
    generation: PositiveCount
    credential_generation: PositiveCount
    credential_expires_at: Amount
    issued_at: Amount
    expires_at: Amount

    @model_validator(mode="after")
    def lifetime(self):
        if not self.issued_at < self.expires_at <= self.credential_expires_at:
            raise ValueError("finite supervision within current credential lifetime required")
        return self


class SupervisionCursor:
    """Pure per-worker clock cursor; G2 owns issuance, persistence and containment."""

    def __init__(self, *, policy, scope, instance, principal, fence, contract_digest, allocation_digest):
        self.policy = ControlPolicy.model_validate(policy.model_dump(mode="json"))
        self.scope = ScopeBinding.model_validate(scope.model_dump(mode="json"))
        self.fence = AttemptFence.model_validate(fence.model_dump(mode="json"))
        self.expected = (scope.body_sha256, instance, principal, contract_digest, allocation_digest)
        self.previous = None
        self.monotonic_deadline = None
        self.last_monotonic = None

    def check(self, lease, *, authority, wall_now, monotonic_now):
        """Check a trusted current lease without sliding the same lease's deadline."""
        wall_now, monotonic_now = _finite(wall_now), _finite(monotonic_now)
        lease = SupervisionLease.model_validate(lease.model_dump(mode="json"))
        if (
            (lease.scope_sha256, lease.instance, lease.principal, lease.contract_digest, lease.allocation_digest)
            != self.expected
            or lease.fence != self.fence
            or lease.expires_at - lease.issued_at > self.policy.max_supervision_lease_seconds
            or wall_now < lease.issued_at
            or (self.last_monotonic is not None and monotonic_now < self.last_monotonic)
        ):
            raise PermissionError("supervision cannot change scope, fence, allocation or clocks")
        authority = _require_workload(
            authority,
            scope=self.scope,
            principal=lease.principal,
            contract_digest=lease.contract_digest,
            capability="native_validation",
            now=wall_now,
        )
        if self.previous is not None:
            if wall_now >= self.previous.expires_at or monotonic_now >= self.monotonic_deadline:
                raise TimeoutError("expired supervision cannot be renewed in place")
            if lease != self.previous and (
                lease.generation != self.previous.generation + 1
                or lease.credential_generation < self.previous.credential_generation
                or lease.issued_at <= self.previous.issued_at
                or lease.expires_at <= self.previous.expires_at
            ):
                raise PermissionError("monotone separately issued supervision renewal required")
        remaining = min(lease.expires_at, lease.credential_expires_at, authority.expires_at) - wall_now
        if remaining <= 0:
            raise TimeoutError("control credential or supervision expired")
        proposed = monotonic_now + remaining
        if lease == self.previous:
            assert self.monotonic_deadline is not None
            proposed = min(proposed, self.monotonic_deadline)
        self.previous, self.monotonic_deadline, self.last_monotonic = lease, proposed, monotonic_now
        return proposed


class OwnedSupervision:
    """One synchronized cursor for the existing owned process and its private channel.

    This object consumes independently issued authority and never issues grants,
    changes an allocation or supplies resource-release/cleanup evidence.
    """

    def __init__(self, *, wall_clock=None, monotonic_clock=None, **binding):
        import threading
        import time

        self.cursor = SupervisionCursor(**binding)
        self._wall_clock = time.time if wall_clock is None else wall_clock
        self._monotonic_clock = time.monotonic if monotonic_clock is None else monotonic_clock
        self._lock = threading.RLock()
        self._authority = None
        self._acknowledgement = None
        self._failure = None

    def accept(self, lease, authority):
        """Acknowledge a checked renewal; identical delivery cannot slide its deadline."""
        import hashlib
        import json

        with self._lock:
            if self._failure is not None:
                raise self._failure
            try:
                lease = SupervisionLease.model_validate_json(lease.model_dump_json())
                authority = AuthorizationSnapshot.model_validate_json(authority.model_dump_json())
                if self.cursor.previous == lease and authority != self._authority:
                    raise PermissionError("Duplicate supervision cannot change workload authority")
                self.cursor.check(
                    lease, authority=authority, wall_now=self._wall_clock(), monotonic_now=self._monotonic_clock()
                )
                self._authority = authority
                digest = hashlib.sha256(
                    json.dumps(
                        lease.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    ).encode()
                ).hexdigest()
                self._acknowledgement = dict(
                    codec="supervision-ack-v1",
                    generation=lease.generation,
                    fence=lease.fence.model_dump(mode="json"),
                    lease_sha256=digest,
                )
                return dict(self._acknowledgement)
            except BaseException as exc:
                self._failure = exc
                raise

    def check_active(self):
        """Refuse stale/revoked control while retaining the original first failure."""
        with self._lock:
            if self._failure is not None:
                raise self._failure
            try:
                if self.cursor.previous is None or self._authority is None:
                    raise PermissionError("Acknowledged owned supervision required")
                self.cursor.check(
                    self.cursor.previous,
                    authority=self._authority,
                    wall_now=self._wall_clock(),
                    monotonic_now=self._monotonic_clock(),
                )
                return self._authority
            except BaseException as exc:
                self._failure = exc
                raise

    def __call__(self):
        with self._lock:
            self.check_active()
            return self.cursor.previous

    def revoke(self, error):
        """Fence new work without disabling cleanup or diagnostic readback."""
        assert isinstance(error, BaseException), "An original causal error is required"
        with self._lock:
            if self._failure is None:
                self._failure = error

    def retained_state(self):
        """Return bounded control metadata after expiry; this is not a cleanup witness."""
        with self._lock:
            return dict(
                last_acknowledgement=None if self._acknowledgement is None else dict(self._acknowledgement),
                lease=None if self.cursor.previous is None else self.cursor.previous.model_dump(mode="json"),
                failure_type=None if self._failure is None else type(self._failure).__name__,
                workload_authority_expires_at=None if self._authority is None else self._authority.expires_at,
                cleanup_verified=False,
            )

    @property
    def first_failure(self):
        with self._lock:
            return self._failure
