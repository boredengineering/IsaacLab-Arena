# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Immutable workflow intent only; profile references are never resolved here."""
import hashlib
import json
import math
from ipaddress import IPv4Address
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

MAX_CONTRACT_BYTES = 2_097_152
MAX_CONTRACT_DEPTH = 32

Text = Annotated[str, Field(strict=True, min_length=1, max_length=16384, pattern=r"\S")]
Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
Hash = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)]
Amount = Annotated[float, Field(strict=True, ge=0, le=1e12, allow_inf_nan=False)]
Duration = Annotated[float, Field(strict=True, gt=0, le=1e12, allow_inf_nan=False)]
StrictFlag = Annotated[bool, Field(strict=True)]
SchemaPath = Annotated[
    str, Field(strict=True, min_length=2, max_length=1024, pattern=r"^(?:/(?:[A-Za-z0-9_.:-]|~[01])+)+$")
]


class FrozenModel(BaseModel):
    """Reject undeclared input and freeze every node in the request tree."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)


class PreservationRule(FrozenModel):
    """Freeze the exact existing JSON-pointer subtree against the original scene."""

    subject_id: Identifier
    schema_path: SchemaPath
    mode: Literal["frozen"]
    description: Text | None = None


class InterventionRule(FrozenModel):
    """Replace only an existing exact path; displacement is measured from original.

    Path existence and subject binding must be checked by the repair validator,
    never inferred by this request DTO or relaxed to insertion or wildcard edits.
    """

    subject_id: Identifier
    schema_path: SchemaPath
    operation: Literal["replace"]
    coordinate_frame: Identifier
    units: Literal["m"]
    max_total_displacement_m: Amount
    description: Text | None = None


class ProfileReference(FrozenModel):
    """Public identity and immutable settings hash, not settings or credentials."""

    profile_id: Identifier
    settings_sha256: Hash


class ModelProfile(ProfileReference):
    billing: Literal["free", "paid"]


class ExecutionConfiguration(FrozenModel):
    generation_model: ModelProfile | None
    assessment_model: ModelProfile | None
    runtime: ProfileReference
    database: ProfileReference
    policy: ProfileReference | None
    capture: ProfileReference | None
    seed: Count
    timestep_seconds: Duration
    decimation: Annotated[int, Field(strict=True, ge=1, le=1_000_000)]
    dcrg: None
    """DCRG configuration is explicitly unsupported in this schema version."""


class WorkflowBudget(FrozenModel):
    """Cumulative ceilings across all candidates and revisions, never per retry."""

    max_candidates: Annotated[int, Field(strict=True, ge=1, le=10000)]
    max_revisions: Count
    max_runtime_seconds: Amount
    max_model_calls: Count
    max_model_tokens: Count
    max_cost_usd: Amount
    max_realizations: Count
    max_steps: Count
    max_observations: Count
    max_policy_episodes: Count
    max_policy_steps: Count
    per_operation_timeout_seconds: Duration
    total_deadline_seconds: Duration

    @model_validator(mode="after")
    def bounded_time(self):
        if self.per_operation_timeout_seconds > self.total_deadline_seconds:
            raise ValueError("operation timeout exceeds total deadline duration")
        return self


class CriterionLimit(FrozenModel):
    operator: Literal["ge", "le", "eq"]
    value: Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-1e12, le=1e12)]
    unit: Identifier


class ObservationWindow(FrozenModel):
    """Inclusive control-step bounds; zero is the initial scene observation."""

    start_step: Count
    end_step: Count

    @model_validator(mode="after")
    def ordered(self):
        if self.end_step < self.start_step:
            raise ValueError("observation window end precedes start")
        return self


class Criterion(FrozenModel):
    criterion_id: Identifier
    kind: Literal["structural", "geometry", "visual", "runtime", "policy"]
    evidence_producer: Identifier
    requirement: Literal["required", "advisory"]
    evaluator_version: Identifier
    required_modalities: Annotated[
        tuple[Literal["scene_graph", "rgb", "depth", "segmentation", "state", "policy_rollout"], ...],
        Field(min_length=1, max_length=6),
    ]
    coordinate_frames: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=256)]
    """Exact frame identities, not free-text frame conventions or wildcards."""
    observation_window: ObservationWindow
    rubric: Text
    subjects: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=256)]
    limit: CriterionLimit


class NewSource(FrozenModel):
    kind: Literal["new"]
    prompt: Text


class ExistingSource(FrozenModel):
    """Opaque caller-supplied identity and text, never loaded as a graph or path."""

    kind: Literal["existing"]
    identity: Identifier
    content: Annotated[str, Field(strict=True, min_length=1, max_length=1_048_576)]


class EffectsPolicy(FrozenModel):
    """Intent ceilings only, never execution authorization or a credential grant."""

    allow_paid_models: Annotated[bool, Field(strict=True)]
    allow_runtime: Annotated[bool, Field(strict=True)]
    allow_database_reads: Annotated[bool, Field(strict=True)]
    allow_publication: StrictFlag
    allow_dcrg: StrictFlag = False
    allow_operational_writes: StrictFlag = False

    @model_validator(mode="after")
    def supported_effects(self):
        if self.allow_publication:
            raise ValueError("publication is unsupported in workflow schema 1")
        if self.allow_dcrg:
            raise ValueError("DCRG is unsupported in workflow schema 1")
        return self


class PriorRetrievalSettings(FrozenModel):
    """Explicit bounds for the existing snapshot retriever and its caller-owned driver."""

    limit: Annotated[int, Field(strict=True, ge=1, le=5)]
    min_success_rate: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
    min_episodes: Annotated[int, Field(strict=True, ge=1, le=1_000_000)]
    query_timeout_seconds: Annotated[float, Field(strict=True, ge=5, le=5, allow_inf_nan=False)]
    connection_timeout_seconds: Annotated[float, Field(strict=True, gt=0, le=5, allow_inf_nan=False)]
    connection_acquisition_timeout_seconds: Annotated[float, Field(strict=True, gt=0, le=5, allow_inf_nan=False)]
    max_transaction_retry_time_seconds: Annotated[float, Field(strict=True, ge=0, le=0, allow_inf_nan=False)]


class PriorRetrievalSelection(FrozenModel):
    """Public frozen selection, never prior-read permission or managed-migration certification."""

    schema_version: Literal["1"]
    source: Literal["neo4j-legacy-graph-rag"]
    credential_alias: Identifier
    endpoint: Text
    database: Identifier
    eligibility: Literal["measured-or-structural-v1"]
    settings: PriorRetrievalSettings
    settings_sha256: Hash
    required: StrictFlag
    allow_empty: StrictFlag

    @model_validator(mode="after")
    def explicit_supported_selection(self):
        try:
            parsed = urlsplit(self.endpoint)
            ip = IPv4Address(parsed.hostname)
            port = parsed.port
        except (TypeError, ValueError):
            raise ValueError("Literal numeric IPv4 Bolt prior source required") from None
        if port is None or not 1 <= port <= 65535 or self.endpoint != f"bolt://{ip}:{port}":
            raise ValueError("Literal numeric IPv4 Bolt prior source required")
        raw = json.dumps(
            {"eligibility": self.eligibility, "settings": self.settings.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if hashlib.sha256(raw).hexdigest() != self.settings_sha256:
            raise ValueError("Prior eligibility/settings digest differs")
        return self


class WorkflowContract(FrozenModel):
    schema_version: Literal["1", "2", "3"]
    source: Annotated[NewSource | ExistingSource, Field(discriminator="kind")]
    criteria: Annotated[tuple[Criterion, ...], Field(min_length=1, max_length=256)]
    preserved: Annotated[tuple[PreservationRule, ...], Field(max_length=256)]
    allowed_interventions: Annotated[tuple[InterventionRule, ...], Field(max_length=256)]
    execution: ExecutionConfiguration
    budget: WorkflowBudget
    effects: EffectsPolicy
    retrieval: PriorRetrievalSelection | None = None
    """Required in schema 2; omitted from schema 1's unchanged wire representation."""

    @model_validator(mode="before")
    @classmethod
    def versioned_fields(cls, value):
        if type(value) is dict and value.get("schema_version") == "1" and "retrieval" in value:
            raise ValueError("Retrieval selection requires workflow schema 2")
        return value

    @model_serializer(mode="wrap")
    def versioned_wire(self, serialize):
        value = serialize(self)
        if self.schema_version == "1":
            value.pop("retrieval", None)
        return value

    @model_validator(mode="after")
    def consistent_intent(self):
        if self.schema_version == "3":
            if (
                self.source.kind != "existing"
                or self.execution.generation_model is not None
                or self.execution.assessment_model is not None
                or self.execution.policy is not None
                or self.execution.capture is None
                or self.retrieval is not None
                or self.allowed_interventions
                or any(c.kind != "runtime" for c in self.criteria)
                or self.effects.allow_paid_models
                or self.effects.allow_database_reads
                or not self.effects.allow_runtime
                or not self.effects.allow_operational_writes
                or self.budget.max_candidates != 1
                or self.budget.max_revisions
                or self.budget.max_model_calls
                or self.budget.max_model_tokens
                or self.budget.max_cost_usd
            ):
                raise ValueError("Schema 3 requires explicit model-free retained-candidate native validation")
        elif self.execution.generation_model is None or self.execution.assessment_model is None:
            raise ValueError("Legacy workflow schemas require both explicit model selections")
        if self.schema_version == "2" and (
            self.retrieval is None or self.source.kind != "new" or not self.effects.allow_database_reads
        ):
            raise ValueError("Workflow schema 2 requires explicit generation retrieval and read intent")
        ids = tuple(criterion.criterion_id for criterion in self.criteria)
        if len(ids) != len(set(ids)):
            raise ValueError("criterion IDs must be unique")
        for intervention in self.allowed_interventions:
            for preserved in self.preserved:
                a, b = intervention.schema_path, preserved.schema_path
                if a == b or a.startswith(b + "/") or b.startswith(a + "/"):
                    raise ValueError("intervention overlaps a frozen preservation path")
        for criterion in self.criteria:
            if criterion.observation_window.end_step > self.budget.max_steps:
                raise ValueError("observation window exceeds step budget")
            if "policy_rollout" in criterion.required_modalities and criterion.kind != "policy":
                raise ValueError("policy_rollout modality requires policy criterion")
        policy_requested = any(criterion.kind == "policy" for criterion in self.criteria)
        if policy_requested != (self.execution.policy is not None):
            raise ValueError("policy criteria and explicit policy configuration must agree")
        if policy_requested:
            if not (
                self.effects.allow_runtime
                and self.execution.capture is not None
                and self.budget.max_realizations
                and self.budget.max_steps
                and self.budget.max_observations
                and self.budget.max_policy_episodes
                and self.budget.max_policy_steps
            ):
                raise ValueError("policy requires runtime, capture and nonzero evaluation budgets")
            if any(c.kind == "policy" and "policy_rollout" not in c.required_modalities for c in self.criteria):
                raise ValueError("policy criteria require policy_rollout modality")
        elif self.budget.max_policy_episodes or self.budget.max_policy_steps:
            raise ValueError("policy budgets require policy criteria and configuration")
        if (
            any(
                m is not None and m.billing == "paid"
                for m in (self.execution.generation_model, self.execution.assessment_model)
            )
            and not self.effects.allow_paid_models
        ):
            raise ValueError("paid model requires explicit effects permission")
        return self


def canonical_json(contract: WorkflowContract) -> str:
    """Return byte-bounded UTF-8 JSON text with sorted keys and no whitespace."""
    canonical = json.dumps(
        contract.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    if len(canonical.encode("utf-8")) > MAX_CONTRACT_BYTES:
        raise ValueError("canonical contract JSON size exceeds byte limit")
    return canonical


def parse_contract(raw: str | bytes) -> WorkflowContract:
    """Parse strict JSON without duplicate keys, nonfinite numbers or reference IO."""
    if not isinstance(raw, (str, bytes)):
        raise ValueError("contract JSON must be text or UTF-8 bytes")
    if len(raw) > MAX_CONTRACT_BYTES:
        raise ValueError("contract JSON size exceeds byte limit")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if len(raw.encode("utf-8")) > MAX_CONTRACT_BYTES:
        raise ValueError("contract JSON size exceeds byte limit")
    depth, quoted, escaped = 0, False, False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_CONTRACT_DEPTH:
                raise ValueError("contract JSON depth exceeds limit")
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError("invalid contract JSON depth")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("nonfinite JSON number: " + value)

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            reject_constant(value)
        return result

    contract = WorkflowContract.model_validate(
        json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant, parse_float=finite_float)
    )
    canonical_json(contract)
    return contract


def contract_digest(contract: WorkflowContract) -> str:
    """Return lowercase SHA-256 over canonical UTF-8 request bytes."""
    return hashlib.sha256(canonical_json(contract).encode("utf-8")).hexdigest()
