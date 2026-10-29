# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure dependency admission; probes and effect factories remain caller-owned boundaries."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import TypeVar

from .contracts import WorkflowContract

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_STATUSES = frozenset({"passed", "unavailable", "mismatch", "not_checked"})
_CODES = frozenset({"observed", "probe_failed", "probe_timeout", "invalid_receipt", "identity_mismatch"})
T = TypeVar("T")


def _identity(value: str | None, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("Invalid dependency identity")


def _digest(value: str) -> None:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError("Invalid dependency profile digest")


def _number(value: float, *, positive: bool = False) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or (positive and not 0 < value <= 120):
        raise ValueError("Invalid readiness time bound")


@dataclass(frozen=True)
class DependencyRequirement:
    """One mandatory dependency bound to an exact nonsecret profile."""

    dependency_id: str
    profile_sha256: str
    profile_id: str = field(kw_only=True)
    instance_id: str | None = None

    def __post_init__(self):
        _identity(self.dependency_id)
        _identity(self.profile_id)
        _digest(self.profile_sha256)
        _identity(self.instance_id, optional=True)


@dataclass(frozen=True)
class DependencyResult:
    """Strict nonsecret probe result; exceptions never become public diagnostic text."""

    dependency_id: str
    status: str
    profile_sha256: str
    profile_id: str = field(kw_only=True)
    instance_id: str | None = None
    code: str = "observed"

    def __post_init__(self):
        _identity(self.dependency_id)
        _identity(self.profile_id)
        _digest(self.profile_sha256)
        _identity(self.instance_id, optional=True)
        if type(self.status) is not str or self.status not in _STATUSES:
            raise ValueError("Invalid dependency status")
        if type(self.code) is not str or self.code not in _CODES:
            raise ValueError("Invalid dependency diagnostic")


def required_dependencies(contract: WorkflowContract, *, resolved_instances=None) -> tuple[DependencyRequirement, ...]:
    """Derive prerequisites for the whole frozen outcome, without resolving profiles.

    Args:
        contract: Validated immutable workflow request, not execution authorization.
        resolved_instances: Trusted resolved profile map keyed by category/profile ID/hash;
            optional instance pins, independently frozen by the store composition.

    Returns:
        Mandatory resource/capability checks, not held physical leases. Composition
        must separately acquire and retain execution/GPU leases before execution.
    """
    if type(contract) is not WorkflowContract:
        raise ValueError("Invalid workflow contract")
    config = contract.execution
    profiles = [("neo4j", config.database)]
    if contract.schema_version != "4":
        profiles.insert(0, ("runtime", config.runtime))
    if contract.source.kind == "new" or contract.allowed_interventions:
        profiles.append(("generation_model", config.generation_model))
    if any(criterion.kind == "visual" for criterion in contract.criteria):
        profiles.append(("assessment_model", config.assessment_model))
    if contract.schema_version != "4" and any(criterion.kind != "structural" for criterion in contract.criteria):
        if config.capture is None:
            raise ValueError("Capture profile required for requested evidence")
        profiles.extend((("capture", config.capture), ("gpu", config.runtime)))
    if config.policy is not None:
        profiles.append(("policy", config.policy))
    return tuple(
        DependencyRequirement(
            name,
            profile.settings_sha256,
            profile_id=profile.profile_id,
            instance_id=(resolved_instances or {}).get((name, profile.profile_id, profile.settings_sha256)),
        )
        for name, profile in profiles
    )


@dataclass(frozen=True)
class ReadinessReport:
    """Local observation, not a durable execution grant or resource reservation."""

    results: tuple[DependencyResult, ...]
    checked_at: float
    """Process-local monotonic check completion time; never replay as execution authority."""
    started_at: float | None = field(default=None, kw_only=True)
    clock: Callable[[], float] | None = field(default=None, kw_only=True, repr=False, compare=False)
    requirements: tuple[DependencyRequirement, ...] = field(default=(), kw_only=True)

    @property
    def ready(self) -> bool:
        return bool(self.results) and all(item.status == "passed" for item in self.results)

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(item.dependency_id for item in self.results if item.status != "passed")


@dataclass(frozen=True)
class ReadinessClock:
    """Trusted same-process clock mapping, captured before probes, never request data."""

    monotonic: Callable[[], float]
    wall_clock: Callable[[], float]
    monotonic_anchor: float
    wall_anchor: float

    @classmethod
    def capture(cls, *, monotonic=time.monotonic, wall_clock=time.time):
        # Wall first is conservative: the resulting observation time is no newer.
        wall, mono = wall_clock(), monotonic()
        _number(wall)
        _number(mono)
        return cls(monotonic, wall_clock, mono, wall)


def durable_readiness(contract, requirements, report, *, mapping):
    """Bridge a genuine local gate report into wall-time metadata, not a lease.

    Composition owns the probes, resolved identities and both clocks. This is not
    an authentication mechanism against hostile in-process Python. Clock identity
    must match, with at most one second drift since capture. The oldest possible
    observation (probe start) is retained, never the newer completion timestamp.
    """
    from .attempts import ReadinessReceipt, ReadyProfile
    from .contracts import contract_digest

    mono, wall = mapping.monotonic(), mapping.wall_clock()
    for value in (mono, wall, report.checked_at, report.started_at):
        _number(value)
    base = required_dependencies(contract)
    if (
        report.clock is not mapping.monotonic
        or report.requirements != requirements
        or tuple(replace(r, instance_id=None) for r in requirements) != base
        or not mapping.monotonic_anchor <= report.started_at <= report.checked_at <= mono
        or abs((wall - mapping.wall_anchor) - (mono - mapping.monotonic_anchor)) > 1.0
        or wall < mapping.wall_anchor
        or len(report.results) != len(requirements)
        or len({r.dependency_id for r in report.results}) != len(requirements)
    ):
        raise ValueError("readiness clock or requirement mismatch")
    profiles = []
    for required, observed in zip(requirements, report.results, strict=True):
        if (
            observed.status != "passed"
            or observed.dependency_id != required.dependency_id
            or observed.profile_id != required.profile_id
            or observed.profile_sha256 != required.profile_sha256
            or (required.instance_id is not None and observed.instance_id != required.instance_id)
        ):
            raise ValueError("unsuccessful or mismatched dependency")
        profiles.append(
            ReadyProfile(
                role=required.dependency_id,
                profile_id=required.profile_id,
                settings_sha256=required.profile_sha256,
                expected_instance_id=required.instance_id,
                observed_instance_id=observed.instance_id,
            )
        )
    observed_wall = min(
        mapping.wall_anchor + report.started_at - mapping.monotonic_anchor,
        wall - (mono - report.started_at),
    )
    return ReadinessReceipt(
        contract_digest=contract_digest(contract),
        checked_at=observed_wall,
        profiles=tuple(profiles),
    )


class DependencyGate:
    """Check required dependencies before invoking a deferred effect factory.

    Trusted probes must enforce the supplied remaining timeout themselves, normally
    through existing bounded worker/process transports. This synchronous gate does
    not sandbox or forcibly interrupt a caller-supplied Python function.
    """

    def __init__(
        self,
        probe: Callable[[DependencyRequirement, float], DependencyResult],
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._probe = probe
        self._clock = clock

    @staticmethod
    def _unavailable(request: DependencyRequirement, code: str) -> DependencyResult:
        return DependencyResult(
            request.dependency_id,
            "unavailable",
            request.profile_sha256,
            request.instance_id,
            code,
            profile_id=request.profile_id,
        )

    def _now(self) -> float:
        now = self._clock()
        _number(now)
        return now

    def check(self, requirements: tuple[DependencyRequirement, ...], *, timeout_s: float) -> ReadinessReport:
        """Return current bounded observations without constructing any model backend.

        Args:
            requirements: Nonempty unique, immutable required dependency declarations.
            timeout_s: Total probe deadline in seconds, at most 120.

        Returns:
            Report whose failed checks contain only fixed diagnostic codes.
        """
        _number(timeout_s, positive=True)
        if (
            type(requirements) is not tuple
            or not 1 <= len(requirements) <= 16
            or any(type(item) is not DependencyRequirement for item in requirements)
            or len({item.dependency_id for item in requirements}) != len(requirements)
        ):
            raise ValueError("Invalid dependency requirements")
        started_at = self._now()
        deadline = started_at + timeout_s
        observations = []
        for request in requirements:
            remaining = deadline - self._now()
            if remaining <= 0:
                observations.append(self._unavailable(request, "probe_timeout"))
                continue
            try:
                observed = self._probe(request, remaining)
            except TimeoutError:
                observed = self._unavailable(request, "probe_timeout")
            except Exception:
                observed = self._unavailable(request, "probe_failed")
            if self._now() >= deadline:
                observed = self._unavailable(request, "probe_timeout")
            elif type(observed) is not DependencyResult:
                observed = self._unavailable(request, "invalid_receipt")
            elif (
                observed.dependency_id != request.dependency_id
                or observed.profile_id != request.profile_id
                or observed.profile_sha256 != request.profile_sha256
                or (request.instance_id is not None and observed.instance_id != request.instance_id)
            ):
                observed = DependencyResult(
                    request.dependency_id,
                    "mismatch",
                    request.profile_sha256,
                    request.instance_id,
                    "identity_mismatch",
                    profile_id=request.profile_id,
                )
            observations.append(observed)
        return ReadinessReport(
            tuple(observations),
            self._now(),
            started_at=started_at,
            clock=self._clock,
            requirements=requirements,
        )

    def execute(
        self,
        requirements: tuple[DependencyRequirement, ...],
        start: Callable[[], T],
        *,
        timeout_s: float,
    ) -> tuple[ReadinessReport, T | None]:
        """Recheck before calling start once; never retry or reinterpret its exceptions.

        Args:
            requirements: Required profiles derived by the application from the full request.
            start: Deferred factory; model initialization must occur inside it, never before check.
            timeout_s: Total bounded readiness probe deadline.

        Returns:
            Fresh report and effect result, or None when dependencies block release.
        """
        report = self.check(requirements, timeout_s=timeout_s)
        return report, start() if report.ready else None
