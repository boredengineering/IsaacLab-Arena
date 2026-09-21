# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Bounded immutable CANCEL/RESUME facts; not a generic command journal."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .attempts import AttemptFence
from .contracts import FrozenModel, Hash, Identifier, StrictFlag
from .queries import RunCleanupView, SceneReadScope

COMMAND_BYTES = 16384
Version = Annotated[int, Field(strict=True, ge=1, le=2**63 - 1)]


def command_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def command_digest(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CommandConflict(ValueError):
    """An exact scoped command kind/key already binds different canonical input."""


class CorruptCancelReceipt(ValueError):
    def __init__(self):
        super().__init__("Invalid retained cancellation receipt")


class LocalStopObservation(FrozenModel):
    """Delivery only; never physical cleanup or remote-effect proof."""

    delivery: Literal["delivered", "no_owner", "unconfirmed"]
    remote_effects: Literal["unknown"] = "unknown"
    durable_cancellation: Literal["unconfirmed"] = "unconfirmed"


class CancelEvent(FrozenModel):
    sequence: Version
    kind: Literal["CancellationRequested"]
    source_id: Identifier


class CancelReceipt(FrozenModel):
    scope: SceneReadScope
    kind: Literal["CANCEL"] = "CANCEL"
    operation_id: Identifier
    run_id: Identifier
    codec_version: Literal[1] = 1
    receipt_version: Literal[1] = 1
    digest_codec: Literal["sha256-canonical-json-utf8-v1"] = "sha256-canonical-json-utf8-v1"
    payload_json: Annotated[str, Field(max_length=256)]
    payload_digest: Hash
    receipt_digest: Hash
    before_version: Version | None
    after_version: Version | None
    disposition: Literal["cancellation_requested", "already_requested", "already_cancelled", "refused"]
    reason: Literal["target_not_found", "inactive_run"] | None
    first_local_stop: LocalStopObservation
    events: Annotated[tuple[CancelEvent, ...], Field(max_length=1)]

    @model_validator(mode="after")
    def exact_binding(self):
        if self.disposition == "cancellation_requested":
            if (
                self.reason is not None
                or self.before_version is None
                or self.after_version != self.before_version + 1
                or len(self.events) != 1
                or self.events[0].source_id != self.run_id
            ):
                raise ValueError("cancel transition facts mismatch")
        elif self.events or self.before_version != self.after_version:
            raise ValueError("nontransition cancellation facts mismatch")
        if self.disposition == "refused":
            if self.reason is None or ((self.before_version is None) != (self.reason == "target_not_found")):
                raise ValueError("cancel refusal facts mismatch")
        elif self.reason is not None or self.before_version is None:
            raise ValueError("cancel disposition facts mismatch")
        if self.payload_json != command_json({"runId": self.run_id}) or self.payload_digest != command_digest(
            self.payload_json
        ):
            raise ValueError("cancel payload binding mismatch")
        if self.receipt_digest != command_digest(
            command_json(self.model_dump(mode="json", exclude={"receipt_digest"}))
        ):
            raise ValueError("cancel receipt digest mismatch")
        return self


def make_cancel_receipt(**values):
    # Materialize defaults before digesting the envelope; validation is mandatory.
    body = dict(
        kind="CANCEL", codec_version=1, receipt_version=1, digest_codec="sha256-canonical-json-utf8-v1", **values
    )
    body["receipt_digest"] = command_digest(command_json(body))
    return CancelReceipt.model_validate(body)


class ResumePayload(FrozenModel):
    runId: Identifier
    expectedVersion: Version
    renewAuthorization: StrictFlag


class ResumeSelection(FrozenModel):
    run_id: Identifier
    version: Version
    contract_digest: Hash
    branch: Literal["generation", "scene", "reconciliation"]
    intent_id: Identifier
    fence: AttemptFence | None = None

    @model_validator(mode="after")
    def exact_fence(self):
        if self.branch == "reconciliation":
            if self.fence is None or self.fence.run_id != self.run_id or self.fence.intent_id != self.intent_id:
                raise ValueError("exact reconciliation fence required")
        elif self.fence is not None:
            raise ValueError("continuation must be never claimed")
        return self


class ResumeEvent(FrozenModel):
    sequence: Version
    kind: Literal["ResumeAdmitted"]
    source_id: Identifier


class ResumeReceipt(FrozenModel):
    scope: SceneReadScope
    kind: Literal["RESUME"] = "RESUME"
    operation_id: Identifier
    run_id: Identifier
    codec_version: Literal[1] = 1
    receipt_version: Literal[1] = 1
    digest_codec: Literal["sha256-canonical-json-utf8-v1"] = "sha256-canonical-json-utf8-v1"
    payload_json: Annotated[str, Field(max_length=512)]
    payload_digest: Hash
    receipt_digest: Hash
    before_version: Version | None
    after_version: Version | None
    selection: ResumeSelection | None
    contract_digest: Hash | None
    disposition: Literal["continuation_admitted", "reconciliation_admitted", "refused"]
    reason: (
        Literal[
            "target_not_found",
            "stale_version",
            "inactive_run",
            "unsupported_branch",
            "private_eligibility_not_ready",
            "selection_changed",
            "unsafe_scene",
            "renewal_not_applicable",
        ]
        | None
    )
    authorization_action: Literal["none", "bind", "renew"] | None
    events: Annotated[tuple[ResumeEvent, ...], Field(max_length=1)]

    @model_validator(mode="after")
    def exact_binding(self):
        payload = ResumePayload.model_validate_json(self.payload_json)
        if (
            self.payload_json != command_json(payload.model_dump(mode="json"))
            or payload.runId != self.run_id
            or self.payload_digest != command_digest(self.payload_json)
            or self.receipt_digest
            != command_digest(command_json(self.model_dump(mode="json", exclude={"receipt_digest"})))
        ):
            raise ValueError("resume receipt binding mismatch")
        if (self.before_version is None) != (self.contract_digest is None):
            raise ValueError("resume contract binding missing")
        if self.selection is not None and (
            self.selection.run_id != self.run_id
            or self.selection.version != self.before_version
            or self.selection.contract_digest != self.contract_digest
        ):
            raise ValueError("resume selected target mismatch")
        if self.disposition == "refused":
            if (
                self.reason is None
                or self.events
                or self.before_version != self.after_version
                or self.authorization_action is not None
                or ((self.before_version is None) != (self.reason == "target_not_found"))
                or (
                    self.reason == "renewal_not_applicable"
                    and (
                        not payload.renewAuthorization
                        or self.selection is None
                        or self.selection.branch != "reconciliation"
                    )
                )
            ):
                raise ValueError("resume refusal facts mismatch")
        elif (
            self.reason is not None
            or self.selection is None
            or self.before_version != payload.expectedVersion
            or self.after_version != self.before_version + 1
            or self.selection.run_id != self.run_id
            or self.selection.version != self.before_version
            or len(self.events) != 1
            or self.events[0].source_id != self.selection.intent_id
            or (
                self.disposition == "continuation_admitted"
                and (
                    self.authorization_action is None
                    or self.selection.branch == "reconciliation"
                    or self.authorization_action not in (("bind", "renew") if payload.renewAuthorization else ("none",))
                )
            )
            or (
                self.disposition == "reconciliation_admitted"
                and (
                    self.authorization_action is not None
                    or self.selection.branch != "reconciliation"
                    or payload.renewAuthorization
                )
            )
        ):
            raise ValueError("resume admission facts mismatch")
        return self


class ResumeAdmission(FrozenModel):
    """Transport freshness is not part of the immutable original receipt."""

    fresh: StrictFlag
    receipt: ResumeReceipt


class ResumeResult(FrozenModel):
    """Immutable admission plus a local handoff observation, never proof of release."""

    receipt: ResumeReceipt
    execution: Literal["not_requested", "blocked", "returned"]
    status_status: Literal["not_requested", "available", "unavailable"]
    status: dict | None = None


class CorruptResumeSelection(ValueError):
    def __init__(self):
        super().__init__("Invalid retained resume selection")


class CorruptResumeReceipt(ValueError):
    def __init__(self):
        super().__init__("Invalid retained resume receipt")


def make_resume_receipt(**values):
    body = dict(
        kind="RESUME", codec_version=1, receipt_version=1, digest_codec="sha256-canonical-json-utf8-v1", **values
    )
    body["receipt_digest"] = command_digest(command_json(body))
    return ResumeReceipt.model_validate(body)


class CancelResult(FrozenModel):
    """Current local observation plus original durable fact and separate cleanup."""

    local_stop: LocalStopObservation
    durable: Literal["recorded", "unknown", "conflict"]
    receipt: CancelReceipt | None
    cleanup_status: Literal["available", "unavailable", "not_requested"]
    cleanup: RunCleanupView | None
    remote_effects: Literal["unknown"] = "unknown"
