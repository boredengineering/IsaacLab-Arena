# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit quiescent administration and current resources, never cross-store readiness."""

from typing import Literal

from ..workbench.research_artifacts import ArtifactArea, ArtifactError
from .contracts import FrozenModel
from .profiles import MAX_PROFILE_REVISIONS, ProfileRevision
from .scene_evidence_artifacts import _protected
from .scope_binding import ScopeBinding


class ArtifactSetupIncomplete(ArtifactError):
    """DB binding was observed; filesystem completion/durability is not certified."""

    db_binding_retained = True
    artifact_state = "incomplete_or_unknown"
    durability = "not_established"


class ArtifactInitialization(FrozenModel):
    binding: ScopeBinding
    db_binding_retained: Literal[True]
    artifact_state: Literal["artifact_created", "existing_layout_verified"]
    durability: Literal["creation_acknowledged", "not_established"]


class CurrentResources(FrozenModel):
    """Current observations only, neither past fsync proof nor execution authority."""

    binding: ScopeBinding
    profiles: tuple[ProfileRevision, ...]
    db_binding_retained: Literal[True] = True
    artifact_state: Literal["existing_layout_verified"] = "existing_layout_verified"
    durability: Literal["not_established"] = "not_established"


class WorkflowScopeAdmin:
    """Trusted composition binds require_admin and injected store to one scope.

    Construction is inert. Paths stay private configuration, not public identity.
    Every owned ArtifactArea is closed before return (also on screening failure).
    No returned descriptor, driver ownership, lease, grant or readiness probe.
    """

    def __init__(self, store, authority):
        self._store = store
        self._authority = authority

    def _request(self, principal, binding, protect):
        self._authority.require_admin(principal)
        if not callable(protect):
            raise ValueError("public protection callback required")
        binding = ScopeBinding.model_validate_json(binding.model_dump_json())
        _protected(binding.model_dump(mode="json"), protect, max_bytes=4096)
        return binding

    def initialize_scope(self, principal, binding, *, protect):
        """Commit the immutable DB binding explicitly before any filesystem setup."""
        binding = self._request(principal, binding, protect)
        return self._store.initialize_bound_scope(binding, protect=protect)

    def initialize_artifacts(self, principal, binding, *, root, create, protect):
        """Explicit create or exact open; never fall back from rejection to repair.

        The DB verification transaction must acknowledge before filesystem IO.
        create=True accepts missing/empty only; False only verifies existing bytes.
        A failed creation may retain partial or complete bytes without durability.
        Successful open never certifies an earlier failed fsync.
        """
        binding = self._request(principal, binding, protect)
        if type(create) is not bool:
            raise ValueError("Explicit artifact initialization mode required")
        retained = self._store.verify_scope_binding(binding)
        load = ArtifactArea.create if create else ArtifactArea.open
        try:
            area = load(root, store_id=binding.store_id, registry_id=binding.registry_id)
        except ArtifactError:
            # Preserve rejected bytes; do not infer absence or fall back to create.
            raise ArtifactSetupIncomplete("Artifact setup incomplete or unknown") from None
        with area:
            result = ArtifactInitialization(
                binding=retained,
                db_binding_retained=True,
                artifact_state="artifact_created" if create else "existing_layout_verified",
                durability="creation_acknowledged" if create else "not_established",
            )
        _protected(result.model_dump(mode="json"), protect)
        return result

    def verify_current_resources(self, principal, binding, *, root, required_profiles, protect):
        """Verify current MATCH/SHOW records and existing area without initialization.

        Exact profile revisions are composition-owned expectations, not defaults.
        ArtifactArea.open may traverse the whole tree under its writer lock; this
        is not a constant-time check or a distributed snapshot. Open does not
        certify prior fsync success. All opened descriptors close before return.
        """
        binding = self._request(principal, binding, protect)
        if type(required_profiles) is not tuple or len(required_profiles) > MAX_PROFILE_REVISIONS:
            raise ValueError("Bounded exact required profiles required")
        expected = tuple(ProfileRevision.model_validate_json(p.model_dump_json()) for p in required_profiles)
        if len({(p.profile_id, p.revision) for p in expected}) != len(expected):
            raise ValueError("Duplicate required profile identity")
        _protected([p.model_dump(mode="json") for p in expected], protect)
        retained = self._store.verify_scope_binding(binding)
        profiles = []
        for profile in expected:
            current = self._store.get_profile(profile.profile_id, profile.revision)
            if current != profile:
                raise ValueError("Required profile is missing or differs")
            profiles.append(current)
        with ArtifactArea.open(root, store_id=binding.store_id, registry_id=binding.registry_id):
            result = CurrentResources(binding=retained, profiles=tuple(profiles))
        _protected(result.model_dump(mode="json"), protect)
        return result
