# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Generation output metadata, not scene acceptance or runtime validity."""
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .attempts import AttemptFence, AuthorizationSnapshot, WorkerRegistration
from .contracts import FrozenModel, Hash, Identifier, ModelProfile


class GenerationReceipt(FrozenModel):
    """Immutable byte binding; adoption requires the concrete artifact verifier."""

    kind: Literal["generation"] = "generation"
    disposition: Literal["produced"] = "produced"
    fence: AttemptFence
    registration: WorkerRegistration
    contract_digest: Hash
    generation_profile: ModelProfile
    candidate_yaml_sha256: Hash
    candidate_json_sha256: Hash
    provenance_sha256: Hash
    manifest_sha256: Hash
    manifest_json: Annotated[str, Field(strict=True, max_length=65536)]
    artifact_directory: Annotated[str, Field(strict=True, pattern=r"^final/generation/[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def exact_registration(self):
        if self.registration.fence != self.fence:
            raise ValueError("receipt registration fence mismatch")
        return self


class CleanupEvidence(FrozenModel):
    """Trusted owner-local observation, NOT database proof of process termination.

    Only the owning process supervisor may supply this evidence after verifying the
    full registered identity and stopping its owned group. No PID killing occurs here.
    Remote provider effects and consumption remain unknown. Tests use synthetic refs.
    """

    registration: WorkerRegistration
    evidence_ref: Identifier
    observation: Literal["owned_process_group_stopped"]
    remote_effects: Literal["unknown"]


class ReconciliationReason(str, Enum):
    """Bounded facts about an already released attempt, never retry permission."""

    RELEASED_WITHOUT_RECEIPT = "released_without_receipt"
    OWNER_OUTCOME_UNCERTAIN = "owner_outcome_uncertain"


class AttemptView(FrozenModel):
    """Retained bindings for read-authorized result recovery."""

    fence: AttemptFence
    registration: WorkerRegistration | None
    contract_json: str
    authorization: AuthorizationSnapshot
    released: bool
    status: str
    reconciliation_reason: ReconciliationReason | None = None
    receipt: GenerationReceipt | None
    cleanup: CleanupEvidence | None
    usage_disposition: Literal["fully_reserved_consumption_deferred"] = "fully_reserved_consumption_deferred"
