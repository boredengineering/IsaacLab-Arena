# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bound live keysets, not snapshot tokens, signatures or authorization capabilities.

Same-binding destructive reset/divergent restore is unsupported. Rotate identity
through explicit administration; no cursor can prove stream incarnation here.
"""

import base64
import json
import re
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from .contracts import FrozenModel, Hash, Identifier
from .scope_binding import ScopeBinding

MAX_CURSOR_BYTES = 4096
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_COUNTER = 2**63 - 1


def _counter(value):
    if not re.fullmatch(r"0|[1-9][0-9]{0,18}", value) or int(value) > MAX_COUNTER:
        raise ValueError("Invalid decimal counter")
    return value


Counter = Annotated[str, Field(strict=True, max_length=19), AfterValidator(_counter)]


def validate_first(first):
    if type(first) is not int or not 1 <= first <= 1000:
        raise ValueError("Page size must be an integer between 1 and 1000")


def physical_counter(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= MAX_COUNTER:
        raise CorruptPage()
    return str(value)


class CorruptPage(ValueError):
    def __init__(self):
        super().__init__("Invalid retained page")


class RunSummary(FrozenModel):
    """Current compact lifecycle; operation_id is the original submission key."""

    run_id: Hash
    operation_id: Identifier
    state: Literal[
        "pending", "running", "cancel_requested", "cancelled", "reconciliation_required", "accepted", "stopped"
    ]
    phase: Literal["dependency_readiness", "generation", "validation", "scene"]
    run_version: Counter
    event_cursor: Counter

    @model_validator(mode="after")
    def positive_version(self):
        if self.run_version == "0":
            raise ValueError("Positive run version required")
        return self


class RunWindow(FrozenModel):
    binding: ScopeBinding
    floor: Counter
    ceiling: Counter
    runs: Annotated[tuple[RunSummary, ...], Field(max_length=1001)]


class RunPage(FrozenModel):
    binding: ScopeBinding
    semantics: Literal["live_keyset"] = "live_keyset"
    floor: Counter
    ceiling: Counter
    runs: Annotated[tuple[RunSummary, ...], Field(max_length=1000)]
    has_more: bool
    end_cursor: str | None
    event_watermark: str


class RunPosition(FrozenModel):
    position: Hash


class EventPosition(FrozenModel):
    position: Counter
    floor: Counter
    ceiling: Counter

    @model_validator(mode="after")
    def ordered(self):
        if not int(self.floor) <= int(self.position) <= int(self.ceiling):
            raise ValueError("Invalid issued event bounds")
        return self


class FutureCursor(ValueError):
    def __init__(self):
        super().__init__("Page cursor exceeds committed ceiling")


class ScopeEvent(FrozenModel):
    """Exact retained event fields, not invented event-time versions or source types."""

    sequence: Counter
    run_id: Hash
    operation_id: Identifier
    kind: Identifier
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    source_id: Identifier | None
    command_kind: Literal["CANCEL", "RESUME"] | None
    command_operation_id: Identifier | None

    @model_validator(mode="after")
    def paired_command(self):
        if (self.command_kind is None) != (self.command_operation_id is None):
            raise ValueError("Incomplete retained command identity")
        return self


class EventWindow(FrozenModel):
    binding: ScopeBinding
    floor: Counter
    ceiling: Counter
    position: Counter
    events: Annotated[tuple[ScopeEvent, ...], Field(max_length=1001)]


class ScopeEventPage(FrozenModel):
    binding: ScopeBinding
    semantics: Literal["live_keyset"] = "live_keyset"
    coverage: Literal["retained"] = "retained"
    floor: Counter
    ceiling: Counter
    events: Annotated[tuple[ScopeEvent, ...], Field(max_length=1000)]
    has_more: bool
    resume_cursor: str


class MalformedCursor(ValueError):
    def __init__(self):
        super().__init__("Malformed page cursor")


class CursorVersionMismatch(ValueError):
    def __init__(self):
        super().__init__("Unsupported page cursor version")


class CursorQueryMismatch(ValueError):
    def __init__(self):
        super().__init__("Page cursor query differs")


class CursorBindingMismatch(ValueError):
    def __init__(self):
        super().__init__("Page cursor binding differs")


class CandidateItem(FrozenModel):
    """Identity/ownership discovery only; payload, digest and lineage are not checked."""

    candidate_id: Hash
    run_id: Hash


class CandidateWindow(FrozenModel):
    binding: ScopeBinding
    run_id: Hash
    floor: Counter
    ceiling: Counter
    candidates: Annotated[tuple[CandidateItem, ...], Field(max_length=1001)]


class CandidatePage(FrozenModel):
    binding: ScopeBinding
    run_id: Hash
    semantics: Literal["live_keyset"] = "live_keyset"
    floor: Counter
    ceiling: Counter
    candidates: Annotated[tuple[CandidateItem, ...], Field(max_length=1000)]
    has_more: bool
    end_cursor: str | None


class CandidatePosition(FrozenModel):
    """Exact owning run and live record-ID position, not chronology."""

    run_id: Hash
    position: Hash


class UnsupportedDecisionCoverage(ValueError):
    def __init__(self):
        super().__init__("Unsupported decision coverage version")


class DecisionItem(FrozenModel):
    """Producer assertion only; no payload validation or guaranteed detail reader."""

    run_id: Hash
    decision_id: Identifier
    record_kind: Literal["generation_reservation", "scene_decision"]


class DecisionWindow(FrozenModel):
    binding: ScopeBinding
    run_id: Hash
    floor: Counter
    ceiling: Counter
    decisions: Annotated[tuple[DecisionItem, ...], Field(max_length=1001)]


class DecisionPage(FrozenModel):
    binding: ScopeBinding
    run_id: Hash
    semantics: Literal["live_keyset"] = "live_keyset"
    coverage: Literal["cooperative_membership_v1"] = "cooperative_membership_v1"
    floor: Counter
    ceiling: Counter
    decisions: Annotated[tuple[DecisionItem, ...], Field(max_length=1000)]
    has_more: bool
    end_cursor: str | None


class DecisionCoverageUnavailable(FrozenModel):
    """Missing provenance, not proof of legacy chronology or an empty collection."""

    binding: ScopeBinding
    run_id: Hash
    reason: Literal["coverage_provenance_unavailable"] = "coverage_provenance_unavailable"
    floor: Counter
    ceiling: Counter


class DecisionPosition(FrozenModel):
    """Run-qualified live Identifier order, not chronology or a payload reference."""

    run_id: Hash
    position: Identifier


_FAMILIES = {
    DecisionPosition: "run-decisions:decisionId:asc:v1",
    RunPosition: "runs:runId:asc:v1",
    EventPosition: "scope-events:sequence:asc:v1",
    CandidatePosition: "run-candidates:recordId:asc:v1",
}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def encode_cursor(binding, position):
    """Encode a verified binding and typed position; never infer authority."""
    if type(position) not in _FAMILIES:
        raise MalformedCursor()
    position = type(position).model_validate_json(position.model_dump_json())
    value = dict(schemaVersion=1, binding=binding.body_sha256, query=_FAMILIES[type(position)])
    value.update(position.model_dump(mode="json"))
    return base64.urlsafe_b64encode(_json(value).encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(token, binding, position_type):
    """Reject noncanonical encodings and cross-query/binding use before IO."""
    if position_type not in _FAMILIES:
        raise MalformedCursor()
    try:
        if type(token) is not str or not 0 < len(token) <= MAX_CURSOR_BYTES:
            raise ValueError()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError()
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != token:
            raise ValueError()
        value = json.loads(raw.decode("utf-8"))
        if type(value) is not dict or _json(value).encode("utf-8") != raw:
            raise ValueError()
        if type(value.get("schemaVersion")) is not int:
            raise ValueError()
        if not {"schemaVersion", "binding", "query", "position"} <= value.keys():
            raise ValueError()
        if type(value["query"]) is not str or type(value["binding"]) is not str:
            raise ValueError()
        if not re.fullmatch(r"[a-f0-9]{64}", value["binding"]):
            raise ValueError()
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise MalformedCursor() from None
    if value["schemaVersion"] != 1:
        raise CursorVersionMismatch()
    if value.get("query") != _FAMILIES[position_type]:
        raise CursorQueryMismatch()
    if value.get("binding") != binding.body_sha256:
        raise CursorBindingMismatch()
    try:
        return position_type.model_validate(
            {k: v for k, v in value.items() if k not in ("schemaVersion", "binding", "query")}
        )
    except (ValueError, TypeError, RecursionError):
        raise MalformedCursor() from None
