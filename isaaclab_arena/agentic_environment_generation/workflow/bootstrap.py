# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Scoped readiness adapter, never an installer, Docker client or model constructor.

The existing docker/workbench/control.py Controller.start operates on the entire
reviewed stack, including API startup. It is deliberately NOT a scoped workflow
capability and must not be adapted by calling start(). Until an installed helper
provides an explicitly reviewed scoped port, pass helper=None: honest not-ready.

Trusted helper contract: capabilities() is a local, non-effecting snapshot keyed
by dependency role with exact profile_id/profile_sha256/instance_id plus literal
observe/start booleans. observe(requirement, timeout_s) returns passed, stopped or
unavailable after exact identity verification, WITHOUT model initialization.
start_scoped(requirement, timeout_s) may start only that pinned existing service;
it must retain its exact request receipt, reconcile lost ACKs without retry, and
never create/recreate/install/pull or start the API. Helper identity/profile checks
and actual timeout enforcement are helper obligations, not authority from JSON.
Synthetic ports used in tests establish no installed-host or native readiness.

The adapter preflights EVERY required role before observation or scoped effects.
All model roles must pass configuration/capability checks before any start. Model
constructors remain deferred behind the application readiness gate. Opt-in startup
only applies to runtime/neo4j with explicit pinned scoped capabilities. It grants
no capture, policy, GPU, native execution or paid-model permission.
"""

import copy
import math
import time


class ObservationOnlyPort:
    """Bridge trusted pinned metadata probes to shared readiness without startup authority."""

    def __init__(self, approved, probe):
        if type(approved) is not tuple or not 1 <= len(approved) <= 16 or not callable(probe):
            raise ValueError("explicit bounded observation capabilities required")
        self._caps = {
            r.dependency_id: dict(
                profile_id=r.profile_id,
                profile_sha256=r.profile_sha256,
                instance_id=r.instance_id,
                observe=True,
                start=False,
            )
            for r in approved
        }
        if len(self._caps) != len(approved):
            raise ValueError("duplicate observation capability")
        self._probe = probe

    def capabilities(self):
        return copy.deepcopy(self._caps)

    def observe(self, required, timeout_s):
        cap = self._caps.get(required.dependency_id)
        fields = ("profile_id", "profile_sha256", "instance_id")
        if cap is None or any(getattr(required, key) != cap[key] for key in fields):
            return "unavailable"
        result = self._probe(required, timeout_s)
        if getattr(result, "dependency_id", None) != required.dependency_id or any(
            getattr(result, key, None) != cap[key] for key in fields
        ):
            return "unavailable"
        return "passed" if getattr(result, "status", None) == "passed" else "unavailable"


class ScopedHostBootstrap:
    """Inert construction; prepare is execution-only, never a status/replay hook."""

    def __init__(self, helper=None, *, allow_startup=False, clock=time.monotonic):
        if type(allow_startup) is not bool:
            raise ValueError("invalid startup permission")
        self._helper = helper
        self._allow_startup = allow_startup
        self._clock = clock
        self._uncertain = False

    def check(self, requirements, *, timeout_s):
        """Implement the existing readiness gate API without importing an application."""
        from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyResult, ReadinessReport

        started_at = self._clock()
        statuses = self.prepare(requirements, timeout_s=timeout_s)
        return ReadinessReport(
            results=tuple(
                DependencyResult(
                    dependency_id=required.dependency_id,
                    profile_id=required.profile_id,
                    profile_sha256=required.profile_sha256,
                    instance_id=required.instance_id,
                    status=status,
                    code="observed" if status == "passed" else "probe_failed",
                )
                for required, status in zip(requirements, statuses)
            ),
            started_at=started_at,
            checked_at=self._clock(),
            clock=self._clock,
            requirements=requirements,
        )

    def prepare(self, requirements, *, timeout_s):
        """Return ordered readiness states with one bounded full-closure preflight."""
        if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 120:
            raise ValueError("invalid readiness deadline")
        if type(requirements) is not tuple or not 1 <= len(requirements) <= 16:
            raise ValueError("invalid readiness closure")
        unavailable = tuple("unavailable" for _ in requirements)
        if self._helper is None or self._uncertain:
            return unavailable
        deadline = self._clock() + timeout_s

        def remaining():
            result = deadline - self._clock()
            if result <= 0:
                raise TimeoutError()
            return result

        try:
            capabilities = copy.deepcopy(self._helper.capabilities())
            if type(capabilities) is not dict or len({r.dependency_id for r in requirements}) != len(requirements):
                return unavailable
            for required in requirements:
                cap = capabilities.get(required.dependency_id)
                if (
                    type(cap) is not dict
                    or set(cap) != {"profile_id", "profile_sha256", "instance_id", "observe", "start"}
                    or cap["profile_id"] != required.profile_id
                    or cap["profile_sha256"] != required.profile_sha256
                    or cap["instance_id"] != required.instance_id
                    or cap["observe"] is not True
                    or type(cap["start"]) is not bool
                ):
                    return unavailable
            observed = []
            for required in requirements:
                value = self._helper.observe(required, remaining())
                remaining()
                observed.append(value if type(value) is str and value in {"passed", "stopped"} else "unavailable")

            # No partial startup if any mandatory model/capture/service capability
            # is unavailable, or any stopped target is not explicitly startable.
            def startable(r):
                return (
                    self._allow_startup
                    and r.dependency_id in {"runtime", "neo4j"}
                    and type(r.instance_id) is str
                    and bool(r.instance_id)
                    and capabilities[r.dependency_id]["start"] is True
                )

            if any(
                value == "unavailable" or (value == "stopped" and not startable(r))
                for r, value in zip(requirements, observed)
            ):
                return tuple("passed" if value == "passed" else "unavailable" for value in observed)
            for index, (required, value) in enumerate(zip(requirements, observed)):
                if value == "stopped":
                    # Latch before effect: an exception/timeout must never authorize
                    # blind startup replay, even when the underlying helper erred.
                    self._uncertain = True
                    self._helper.start_scoped(required, remaining())
                    observed[index] = self._helper.observe(required, remaining())
                    remaining()
                    if observed[index] != "passed":
                        return unavailable
                    self._uncertain = False
            return tuple(observed)
        except Exception:
            return unavailable
