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
    max_model_tokens: Count | None
    max_cost_usd: Amount | None
    max_realizations: Count
    max_steps: Count
    max_observations: Count
    max_policy_episodes: Count
    max_policy_steps: Count
    per_operation_timeout_seconds: Duration
    total_deadline_seconds: Duration

    def enforced_limit(self, resource):
        """Return an effective aggregate ceiling, not a transport or supervision limit."""
        field = {
            "runtime": "max_runtime_seconds",
            "deadline": "total_deadline_seconds",
            "model_tokens": "max_model_tokens",
            "cost": "max_cost_usd",
        }[resource]
        policy = getattr(self, "policy", None)
        return getattr(self, field) if policy is None or getattr(policy, resource) == "enforced" else None

    def deadline_at(self, admitted_at):
        """Resolve the immutable admission deadline only when enforcement is selected."""
        limit = self.enforced_limit("deadline")
        return None if limit is None else admitted_at + limit

    def allows_resource(self, resource, amount):
        """Check a cumulative reservation only when its resource policy is enforced."""
        limit = self.enforced_limit(resource)
        return limit is None or (amount is not None and amount <= limit)

    def allows_time(self, admitted_at, now, duration):
        """Keep a finite transport allowance distinct from the aggregate deadline."""
        if type(admitted_at) not in (int, float) or not math.isfinite(admitted_at) or now < admitted_at:
            return False
        deadline = self.deadline_at(admitted_at)
        if duration is None:
            return deadline is None and self.enforced_limit("runtime") is None
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            return False
        return duration <= self.per_operation_timeout_seconds and (
            deadline is None or (now < deadline and now + duration <= deadline)
        )

    @model_validator(mode="after")
    def bounded_time(self):
        policy = getattr(self, "policy", None)
        if (
            self.total_deadline_seconds is not None
            and (policy is None or policy.deadline == "enforced")
            and self.per_operation_timeout_seconds > self.total_deadline_seconds
        ):
            raise ValueError("operation timeout exceeds total deadline duration")
        return self


ExperimentMode = Literal["enforced", "advisory", "accounting_only"]


class ExperimentPolicy(FrozenModel):
    """Aggregate experiment ceilings only; issued effect counts remain ceilings."""

    codec: Literal["experiment-policy-v1"]
    runtime: ExperimentMode
    deadline: ExperimentMode
    model_tokens: ExperimentMode
    cost: ExperimentMode


class ControlPolicy(FrozenModel):
    """Finite renewable control selections, not workload or credential authority."""

    codec: Literal["renewable-control-v1"]
    max_supervision_lease_seconds: Duration
    heartbeat_seconds: Duration
    max_credential_lifetime_seconds: Annotated[float, Field(strict=True, gt=0, le=3600, allow_inf_nan=False)]
    client_descriptor_schema: Literal["2"]

    @model_validator(mode="after")
    def finite_heartbeat(self):
        if self.heartbeat_seconds >= self.max_supervision_lease_seconds:
            raise ValueError("heartbeat must precede finite supervision expiry")
        return self


class ExperimentBudget(WorkflowBudget):
    """Schema-5 accounting; per-operation timeout remains a finite backend bound."""

    max_runtime_seconds: Amount | None
    total_deadline_seconds: Duration | None
    policy: ExperimentPolicy
    control: ControlPolicy

    @model_validator(mode="after")
    def explicit_ceiling_policy(self):
        for resource, value in (
            ("runtime", self.max_runtime_seconds),
            ("deadline", self.total_deadline_seconds),
            ("model_tokens", self.max_model_tokens),
            ("cost", self.max_cost_usd),
        ):
            mode = getattr(self.policy, resource)
            if (mode == "enforced" and value is None) or (mode == "accounting_only" and value is not None):
                raise ValueError("enforced ceilings must be finite; accounting-only ceilings must be null")
        return self

    def experiment_limit_status(self, resource, used):
        """Interpret measured usage without refunding reservations or granting effects."""
        limits = {
            "runtime": self.max_runtime_seconds,
            "deadline": self.total_deadline_seconds,
            "model_tokens": self.max_model_tokens,
            "cost": self.max_cost_usd,
        }
        if resource not in limits:
            raise ValueError("unsupported aggregate experiment resource")
        if used is None:
            return "unknown"
        if type(used) not in (int, float) or not math.isfinite(used) or used < 0:
            raise ValueError("finite nonnegative usage required")
        mode, limit = getattr(self.policy, resource), limits[resource]
        if mode == "accounting_only":
            return "accounted"
        if limit is None:
            return "unbounded_advisory"
        exceeded = used >= limit if resource == "deadline" else used > limit
        return f"{mode}_exceeded" if exceeded else "within"


class CriterionLimit(FrozenModel):
    operator: Literal["lt", "gt", "ge", "le", "eq"]
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


class ImageSelection(FrozenModel):
    """A saved observation selection, not an assertion that a sensor updated."""

    camera: Identifier
    step: Count
    modality: Literal["rgb"]


class CriterionCoverage(FrozenModel):
    """Exact criterion coverage, independent of the acquisition's other streams."""

    clock: Literal["control_step"]
    state_steps: Annotated[tuple[Count, ...], Field(max_length=256)]
    images: Annotated[tuple[ImageSelection, ...], Field(max_length=16)]

    @model_validator(mode="after")
    def unique_coverage(self):
        if tuple(sorted(set(self.state_steps))) != self.state_steps or len(set(self.images)) != len(self.images):
            raise ValueError("duplicate or unordered criterion coverage")
        if not self.state_steps and not self.images:
            raise ValueError("empty criterion coverage")
        return self


class AcquisitionSchedule(FrozenModel):
    """Initial explicit adapter capability; event/adaptive policies are unsupported."""

    codec: Literal["explicit-acquisition-v1"]
    adapter: Literal["droid-rigid-world-v1"]
    clock: Literal["control_step"]
    reference_frame: Literal["world"]
    control_dt_seconds: Duration
    horizon_steps: Annotated[int, Field(strict=True, ge=1, le=10000)]
    subjects: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=16)]
    state_steps: Annotated[tuple[Count, ...], Field(max_length=256)]
    images: Annotated[tuple[ImageSelection, ...], Field(max_length=16)]
    renderer_update_steps: Annotated[tuple[Count, ...], Field(max_length=256)]
    """Requested update events; collection must separately attest actual sensor time."""
    displacement_step: Count | None

    @model_validator(mode="after")
    def supported_schedule(self):
        if len(set(self.subjects)) != len(self.subjects) or not (self.state_steps or self.images):
            raise ValueError("unique subjects and nonempty acquisition required")
        for steps in (self.state_steps, self.renderer_update_steps):
            if tuple(sorted(set(steps))) != steps or any(step > self.horizon_steps for step in steps):
                raise ValueError("schedule steps must be unique, ordered and within the horizon")
        image_steps = tuple(image.step for image in self.images)
        if image_steps != tuple(sorted(image_steps)):
            raise ValueError("image steps must be temporally ordered; same-step order is preserved")
        if len(set(self.images)) != len(self.images) or any(
            image.step not in self.renderer_update_steps for image in self.images
        ):
            raise ValueError("unique image identities with declared renderer updates required")
        if self.displacement_step is not None and self.displacement_step not in self.state_steps:
            raise ValueError("displacement requires an explicitly sampled state step")
        return self


class ObservationInterventionPolicy(FrozenModel):
    """Frozen scientific continuation choices; never a release or repair grant."""

    codec: Literal["scene-action-policy-v1"]
    on_unknown: Literal["stop", "informative_observation", "diagnostic_intervention"]
    on_false: Literal["stop", "informative_observation", "diagnostic_intervention", "corrective_repair"]
    target_subject: Identifier | None
    mechanism: Literal["direct-root-xy-goal-v1"] | None
    goal_criterion_id: Identifier | None
    prerequisite_criterion_ids: Annotated[tuple[Identifier, ...], Field(max_length=32)]
    observation: AcquisitionSchedule | None
    displacement_tolerance_m: Annotated[float, Field(strict=True, gt=0, le=1e12, allow_inf_nan=False)] | None = None
    diagnostic_delta_xy_m: (
        tuple[
            Annotated[float, Field(strict=True, allow_inf_nan=False)],
            Annotated[float, Field(strict=True, allow_inf_nan=False)],
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def explicit_action_permissions(self):
        actions = (self.on_unknown, self.on_false)
        if ("informative_observation" in actions) != (self.observation is not None):
            raise ValueError("informative observation requires its selected acquisition")
        intervention = any(action in ("diagnostic_intervention", "corrective_repair") for action in actions)
        if intervention != all((self.target_subject, self.mechanism, self.goal_criterion_id)):
            raise ValueError("intervention requires an explicit target, mechanism and goal")
        if not intervention and any((self.target_subject, self.mechanism, self.goal_criterion_id)):
            raise ValueError("unselected intervention fields")
        if intervention != (self.displacement_tolerance_m is not None):
            raise ValueError("intervention requires a selected displacement tolerance in meters")
        if ("diagnostic_intervention" in actions) != (self.diagnostic_delta_xy_m is not None):
            raise ValueError("diagnostic intervention requires its selected nonzero perturbation")
        if self.diagnostic_delta_xy_m is not None and not any(self.diagnostic_delta_xy_m):
            raise ValueError("diagnostic intervention cannot be a no-op")
        if len(set(self.prerequisite_criterion_ids)) != len(self.prerequisite_criterion_ids):
            raise ValueError("duplicate prerequisite criteria")
        return self


class NumericCoverageParameters(FrozenModel):
    """Explicit sampled semantics; accepting this DTO starts no adapter."""

    reference_frame: Literal["world"]
    clock: Literal["control_step"]
    sample_steps: Annotated[tuple[Count, ...], Field(min_length=1, max_length=256)]
    temporal_aggregation: Literal["all", "any"]
    subject_aggregation: Literal["all", "any"]
    missing_data: Literal["reject"]
    invalid_data: Literal["reject"]

    @model_validator(mode="after")
    def exact_steps(self):
        if tuple(sorted(set(self.sample_steps))) != self.sample_steps:
            raise ValueError("explicit sample steps must be unique and ordered")
        return self


class NumericPredicateParameters(NumericCoverageParameters):
    metric: Literal["linear_speed"]


class PoseErrorParameters(NumericCoverageParameters):
    """Immutable world XY goal, separate from any editable authored placement."""

    metric: Literal["xy_target_error"]
    target_xy_m: tuple[
        Annotated[float, Field(strict=True, allow_inf_nan=False)],
        Annotated[float, Field(strict=True, allow_inf_nan=False)],
    ]


class StationaryPredicateParameters(NumericCoverageParameters):
    """Both velocity norms under selected strict or inclusive stationary limits."""

    metric: Literal["stationary"]
    linear_limit: CriterionLimit
    angular_limit: CriterionLimit

    @model_validator(mode="after")
    def stationary_units(self):
        for limit, unit in ((self.linear_limit, "m_per_s"), (self.angular_limit, "rad_per_s")):
            if limit.unit != unit or limit.operator not in ("lt", "le") or limit.value < 0:
                raise ValueError("unsupported stationary units/operator/limit")
        return self


class VisibilityPredicateParameters(FrozenModel):
    """Explicit camera/time propositions, independently of numeric sampling."""

    metric: Literal["visibility"]
    reference_frame: Literal["camera"]
    clock: Literal["control_step"]
    images: Annotated[tuple[ImageSelection, ...], Field(min_length=1, max_length=16)]
    temporal_aggregation: Literal["all", "any"]
    camera_aggregation: Literal["all", "any"]
    subject_aggregation: Literal["all", "any"]
    missing_data: Literal["reject"]
    invalid_data: Literal["reject"]

    @model_validator(mode="after")
    def unique_images(self):
        if len(set(self.images)) != len(self.images):
            raise ValueError("duplicate visual observation identity")
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
    parameters: (
        Annotated[
            NumericPredicateParameters
            | StationaryPredicateParameters
            | PoseErrorParameters
            | VisibilityPredicateParameters,
            Field(discriminator="metric"),
        ]
        | None
    ) = None

    @model_serializer(mode="wrap")
    def versioned_wire(self, serialize):
        value = serialize(self)
        if self.parameters is None:
            value.pop("parameters", None)
        return value

    @model_validator(mode="wrap")
    @classmethod
    def versioned_input(cls, value, validate):
        if isinstance(value, cls):
            fields, version, limit = value.model_fields_set, value.evaluator_version, value.limit
        elif isinstance(value, dict):
            fields, version, limit = set(value), value.get("evaluator_version"), value.get("limit", {})
        else:
            return validate(value)
        operator = limit.get("operator") if isinstance(limit, dict) else getattr(limit, "operator", None)
        if version not in ("numeric-v2", "full-scene-ternary-v1") and (
            "parameters" in fields or operator in ("lt", "gt")
        ):
            raise ValueError("legacy criterion fields and operators are unchanged")
        return validate(value)

    @model_validator(mode="after")
    def parameter_binding(self):
        if self.parameters is not None:
            visual = self.parameters.metric == "visibility"
            if self.evaluator_version != ("full-scene-ternary-v1" if visual else "numeric-v2"):
                raise ValueError("predicate parameters require an explicit supported evaluator")
            steps = tuple(image.step for image in self.parameters.images) if visual else self.parameters.sample_steps
            if (self.observation_window.start_step, self.observation_window.end_step) != (min(steps), max(steps)):
                raise ValueError("criterion window must bound its explicit sample coverage")
        elif self.evaluator_version in ("numeric-v2", "full-scene-ternary-v1"):
            raise ValueError("explicit versioned predicate parameters required")
        return self


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


class RetainedEvidenceSource(FrozenModel):
    """Immutable producer links for a consumer, not a replacement capture cohort."""

    operation_id: Identifier
    run_id: Hash
    candidate_sha256: Hash
    candidate_digest: Hash
    contract_digest: Hash
    profile_digest: Hash
    observation_manifest_digest: Hash
    evidence_sha256: Hash
    frame_sha256: Annotated[tuple[Hash, ...], Field(min_length=1, max_length=16)]


class WorkflowContract(FrozenModel):
    schema_version: Literal["1", "2", "3", "4", "5"]
    source: Annotated[NewSource | ExistingSource, Field(discriminator="kind")]
    criteria: Annotated[tuple[Criterion, ...], Field(min_length=1, max_length=256)]
    preserved: Annotated[tuple[PreservationRule, ...], Field(max_length=256)]
    allowed_interventions: Annotated[tuple[InterventionRule, ...], Field(max_length=256)]
    execution: ExecutionConfiguration
    budget: ExperimentBudget | WorkflowBudget
    effects: EffectsPolicy
    retrieval: PriorRetrievalSelection | None = None
    """Required in schema 2; omitted from schema 1's unchanged wire representation."""
    retained_evidence: RetainedEvidenceSource | None = None
    predecessor_run_id: Hash | None = None
    """Cancelled assessment consumer superseded by this separately admitted schema-4 operation."""
    acquisition: AcquisitionSchedule | None = None
    action_policy: ObservationInterventionPolicy | None = None

    @model_validator(mode="before")
    @classmethod
    def versioned_fields(cls, value):
        if type(value) is dict and value.get("schema_version") == "1" and "retrieval" in value:
            raise ValueError("Retrieval selection requires workflow schema 2")
        if type(value) is dict and value.get("schema_version") != "5":
            if "acquisition" in value or "action_policy" in value:
                raise ValueError("Configurable selections require workflow schema 5")
            criteria = value.get("criteria", ())
            if type(criteria) in (list, tuple) and any(type(c) is dict and "parameters" in c for c in criteria):
                raise ValueError("Predicate parameters require workflow schema 5")
        return value

    @model_serializer(mode="wrap")
    def versioned_wire(self, serialize):
        value = serialize(self)
        if self.schema_version == "1":
            value.pop("retrieval", None)
        if self.schema_version != "4":
            value.pop("retained_evidence", None)
        if self.predecessor_run_id is None:
            value.pop("predecessor_run_id", None)
        if self.schema_version != "5":
            value.pop("acquisition", None)
            value.pop("action_policy", None)
        return value

    @model_validator(mode="after")
    def versioned_intent(self):
        if self.schema_version == "5":
            from .observation_schedule import criterion_coverage
            from .scene_observation import admit_criterion

            if (
                not isinstance(self.budget, ExperimentBudget)
                or self.acquisition is None
                or self.action_policy is None
                or self.retained_evidence is not None
                or self.predecessor_run_id is not None
                or self.retrieval is not None
                or self.effects.allow_database_reads
                or self.execution.policy is not None
                or self.execution.capture is None
                or not self.effects.allow_runtime
                or self.acquisition.horizon_steps > self.budget.max_steps
                or self.acquisition.control_dt_seconds != self.execution.timestep_seconds * self.execution.decimation
            ):
                raise ValueError("Schema 5 requires explicit configurable capture, policy and clock selections")
            if self.source.kind == "new" and self.execution.generation_model is None:
                raise ValueError("New-source selection requires its generation model")
            if any(c.kind == "visual" for c in self.criteria) and self.execution.assessment_model is None:
                raise ValueError("Visual selection requires its assessment model")
            if sum(c.kind == "visual" for c in self.criteria) > 1:
                raise ValueError("Initial installed capability selects one full-scene visual request per acquisition")
            for criterion in self.criteria:
                criterion = admit_criterion(criterion)
                coverage = criterion_coverage(criterion)
                if (
                    coverage is None
                    or not set(criterion.subjects) <= set(self.acquisition.subjects)
                    or not set(coverage.state_steps) <= set(self.acquisition.state_steps)
                    or not set(coverage.images) <= set(self.acquisition.images)
                ):
                    raise ValueError("Schema 5 requires supported exact acquisition coverage")
            required = {c.criterion_id for c in self.criteria if c.requirement == "required"}
            if not required or not set(self.action_policy.prerequisite_criterion_ids) <= required:
                raise ValueError("Required action prerequisites must name frozen required criteria")
            if (
                self.action_policy.goal_criterion_id is not None
                and self.action_policy.goal_criterion_id not in required
            ):
                raise ValueError("Action goal must name a frozen required criterion")
            if len(self.criteria) > 32:
                raise ValueError("Initial configurable capability supports at most 32 predicates")
            if self.action_policy.goal_criterion_id is not None:
                goal = next(c for c in self.criteria if c.criterion_id == self.action_policy.goal_criterion_id)
                if (
                    not isinstance(goal.parameters, PoseErrorParameters)
                    or goal.subjects != (self.action_policy.target_subject,)
                    or self.acquisition.displacement_step not in goal.parameters.sample_steps
                    or not self.allowed_interventions
                    or any(r.subject_id != self.action_policy.target_subject for r in self.allowed_interventions)
                ):
                    raise ValueError("Supported action requires one target's immutable sampled XY goal and permissions")
            if self.action_policy.observation is not None:
                observation = self.action_policy.observation
                if (
                    observation.adapter != self.acquisition.adapter
                    or observation.clock != self.acquisition.clock
                    or observation.control_dt_seconds != self.acquisition.control_dt_seconds
                    or observation.subjects != self.acquisition.subjects
                    or observation.horizon_steps > self.budget.max_steps
                ):
                    raise ValueError("Unsupported informative acquisition selection")
        elif (
            isinstance(self.budget, ExperimentBudget)
            or self.acquisition is not None
            or self.action_policy is not None
            or any(c.parameters is not None or c.limit.operator in ("lt", "gt") for c in self.criteria)
        ):
            raise ValueError("New predicate and policy semantics require workflow schema 5")
        return self

    @model_validator(mode="after")
    def consistent_intent(self):
        if self.schema_version == "4":
            b = self.budget
            if (
                self.source.kind != "existing"
                or self.retained_evidence is None
                or self.execution.generation_model is not None
                or self.execution.assessment_model is None
                or self.execution.policy is not None
                or self.execution.capture is not None
                or self.retrieval is not None
                or self.allowed_interventions
                or len(self.criteria) != 1
                or self.criteria[0].kind != "visual"
                or self.criteria[0].evaluator_version != "visibility-v2"
                or self.effects.allow_runtime
                or self.effects.allow_database_reads
                or not self.effects.allow_operational_writes
                or b.max_model_tokens is not None
                or b.max_cost_usd is not None
                or not 1 <= b.max_model_calls <= 3
                or b.max_candidates != 1
                or any((
                    b.max_revisions,
                    b.max_realizations,
                    b.max_steps,
                    b.max_observations,
                    b.max_policy_episodes,
                    b.max_policy_steps,
                ))
                or b.max_runtime_seconds > 570
                or b.per_operation_timeout_seconds > 190
                or b.total_deadline_seconds > 600
            ):
                raise ValueError("Schema 4 requires explicit accounting-only retained visibility assessment")
            if hashlib.sha256(self.source.content.encode()).hexdigest() != self.retained_evidence.candidate_sha256:
                raise ValueError("Retained candidate source bytes differ")
        if self.schema_version not in ("4", "5") and (
            self.retained_evidence is not None
            or self.predecessor_run_id is not None
            or self.budget.max_model_tokens is None
            or self.budget.max_cost_usd is None
        ):
            raise ValueError("Accounting-only retained evidence requires schema 4")
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
        elif self.schema_version not in ("4", "5") and (
            self.execution.generation_model is None or self.execution.assessment_model is None
        ):
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
            if self.schema_version != "4" and criterion.observation_window.end_step > self.budget.max_steps:
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
