# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Scoped workflow admission; injected driver, explicit schema provisioning."""

import hashlib
import json
import math
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from .attempts import AttemptFence, AuthorizationSnapshot, GenerationReservation, ReadinessReceipt, WorkerRegistration
from .commands import (
    COMMAND_BYTES,
    CancelReceipt,
    CommandConflict,
    CorruptCancelReceipt,
    CorruptResumeReceipt,
    CorruptResumeSelection,
    LocalStopObservation,
    ResumeAdmission,
    ResumePayload,
    ResumeReceipt,
    ResumeSelection,
    command_digest,
    command_json,
    make_cancel_receipt,
    make_resume_receipt,
)
from .contracts import contract_digest, parse_contract
from .queries import (
    HISTORICAL_CANDIDATE_BYTES,
    CorruptCleanupRecord,
    CorruptSceneRecord,
    FrozenRunIntentView,
    FrozenSubmissionInspection,
    IntentCleanupView,
    RunCleanupView,
    RunInspection,
    SceneAssessmentView,
    SceneCandidateView,
    SceneDecisionView,
    SceneEvidenceView,
    SceneReadScope,
)
from .readiness import required_dependencies
from .results import AttemptView, CleanupEvidence, GenerationReceipt, OwnerView, ReconciliationReason


class SubmissionConflict(ValueError):
    """Operation already accepted a different request."""


class CapacityExceeded(RuntimeError):
    """Scoped pending capacity is exhausted."""


class ScopeMissing(RuntimeError):
    """Explicit scope initialization is required."""


@dataclass(frozen=True)
class RunHandle:
    run_id: str
    operation_id: str
    request_json: str
    contract_json: str
    version: int
    state: str
    phase: str
    event_cursor: int


class ReplayGap(ValueError):
    """Cursor is outside the retained committed prefix; resnapshot required."""


@dataclass(frozen=True)
class WorkflowEvent:
    sequence: int
    run_id: str
    operation_id: str
    kind: str
    schema_version: int
    source_id: str | None = None
    """Stored source identity, or None when unavailable; not inferred causation."""
    command_kind: Literal["CANCEL", "RESUME"] | None = None
    command_operation_id: str | None = None


@dataclass(frozen=True)
class Snapshot:
    runs: tuple[RunHandle, ...]
    cursor: int
    floor: int


@dataclass(frozen=True)
class EventPage:
    events: tuple[WorkflowEvent, ...]
    cursor: int
    floor: int
    ceiling: int


def validate_operation_id(value):
    """Reject malformed operation keys without normalizing or touching the store."""
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is None:
        raise ValueError("Invalid operation id")


def _identifier(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty string identifier required")


def _canonical(raw):
    if not isinstance(raw, str):
        raise ValueError("canonical JSON text required")
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        != raw
    ):
        raise ValueError("canonical JSON object required")
    raw.encode("utf-8")


class SchemaMissing(RuntimeError):
    """Required provisioned uniqueness constraints are missing."""


class OutcomeUnknown(RuntimeError):
    """Commit or cleanup failed; no execution or retry authority is granted."""


class StoreUnavailable(RuntimeError):
    """Initial submission lookup failed at the transport boundary."""


def _lookup_transport_errors():
    # Keep the optional driver out of module import and service construction.
    try:
        from neo4j.exceptions import ServiceUnavailable, SessionExpired
    except ModuleNotFoundError as exc:
        if exc.name != "neo4j":
            raise
        return (OSError,)
    return (OSError, ServiceUnavailable, SessionExpired)


_VIEW = "r {.run_id, .operation_id, .request_json, .contract_json, .version, .state, .phase, .event_cursor}"
_SCOPE = "{deployment_id: $deployment_id, workspace_id: $workspace_id}"
_CONTROL = "MATCH (c:ArenaWorkflowControl " + _SCOPE + ") "

_HISTORY_FIELDS = {
    "ArenaWorkflowCandidate": "record_id",
    "ArenaWorkflowEvidence": "record_id",
    "ArenaCriterionAssessment": "record_id",
    "ArenaWorkflowDecision": "decision_id",
    "ArenaWorkflowRun": "run_id",
    "ArenaExecutionIntent": "intent_id",
}
# Bound payloads before transport, then enforce UTF-8 bytes before parsing. Never
# return arbitrary node properties (notably private authorization snapshots).
_HISTORY_VIEW = (
    "n {"
    + ", ".join(
        f"{field}: CASE WHEN size(toStringOrNull(n.{field}))<={limit} THEN n.{field} "
        f"WHEN n.{field} IS NULL THEN null ELSE [false] END"
        for field, limit in (
            ("deployment_id", 4096),
            ("workspace_id", 4096),
            ("run_id", 128),
            ("record_id", 128),
            ("decision_id", 128),
            ("candidate_id", 128),
            ("intent_id", 128),
            ("evidence_id", 128),
            ("kind", 128),
        )
    )
    + ", payload: CASE WHEN size(toStringOrNull(n.payload))<=CASE WHEN n:ArenaWorkflowCandidate THEN "
    + str(HISTORICAL_CANDIDATE_BYTES)
    + " ELSE 2097152 END THEN n.payload ELSE null END, scene_json: CASE WHEN"
    " size(toStringOrNull(n.scene_json))<=2097152 THEN n.scene_json ELSE null END, contract_json: CASE WHEN"
    " size(toStringOrNull(n.contract_json))<=2097152 THEN n.contract_json ELSE null END} AS node, elementId(n) AS"
    " key, labels(n) AS labels"
)


_KEYS = (
    ("resume_command", "ArenaResumeReceipt", ("deployment_id", "workspace_id", "kind", "operation_id")),
    ("cancel_command", "ArenaCancelReceipt", ("deployment_id", "workspace_id", "kind", "operation_id")),
    ("control", "ArenaWorkflowControl", ("deployment_id", "workspace_id")),
    (
        "operation",
        "ArenaWorkflowRun",
        ("deployment_id", "workspace_id", "operation_id"),
    ),
    ("run", "ArenaWorkflowRun", ("deployment_id", "workspace_id", "run_id")),
    ("event", "ArenaWorkflowEvent", ("deployment_id", "workspace_id", "sequence")),
    ("profile", "ArenaWorkflowProfile", ("deployment_id", "workspace_id", "profile_id")),
    ("profile_revision", "ArenaWorkflowProfileRevision", ("deployment_id", "workspace_id", "profile_id", "revision")),
)


# Nonunique scoped lookups preserve LIMIT 2 corruption/duplicate detection.
# Run lookup is already backed by _KEYS; no writer identity rules change.
_HISTORY_INDEXES = (
    ("candidate", "ArenaWorkflowCandidate", "record_id"),
    ("evidence", "ArenaWorkflowEvidence", "record_id"),
    ("assessment", "ArenaCriterionAssessment", "record_id"),
    ("decision", "ArenaWorkflowDecision", "decision_id"),
    ("selection", "ArenaWorkflowDecision", "evidence_id"),
    ("intent", "ArenaExecutionIntent", "intent_id"),
    ("run_intent", "ArenaExecutionIntent", "run_id"),
    ("attempt", "ArenaExecutionAttempt", "attempt_id"),
    ("retired_owner", "ArenaRetiredWorkflowOwner", "owner_id"),
)


class Neo4jWorkflowStore:
    """Coordinate cooperative writers within an explicitly initialized scope."""

    def __init__(
        self,
        driver,
        *,
        database,
        deployment_id,
        workspace_id,
        clock=time.time,
        readiness_ttl=30.0,
        dependency_instances=None,
    ):
        # Frozen composition-owned pins keyed by category/profile/hash. Missing
        # pins mean profile-only checking, never caller-chosen expected IDs.
        self.dependency_instances = MappingProxyType(dict(dependency_instances or {}))
        if type(readiness_ttl) not in (int, float) or not math.isfinite(readiness_ttl) or not 0 < readiness_ttl <= 300:
            raise ValueError("readiness TTL must be positive and at most 300 seconds")
        self.clock = clock
        self.readiness_ttl = readiness_ttl
        for value in (database, deployment_id, workspace_id):
            _identifier(value)
        self.driver = driver
        self.database = database
        self.scope = dict(deployment_id=deployment_id, workspace_id=workspace_id)

    @contextmanager
    def _transaction(self, *, fetch_size=None):
        options = {} if fetch_size is None else {"fetch_size": fetch_size}
        session = self.driver.session(database=self.database, **options)
        tx = None
        try:
            tx = session.begin_transaction(timeout=5)
            yield tx
            try:
                tx.commit()
            except Exception as exc:
                raise OutcomeUnknown("commit acknowledgement unknown") from exc
        finally:
            errors = []
            for resource in (tx, session):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception as exc:
                        errors.append(exc)
            if errors:
                raise OutcomeUnknown("transaction/session cleanup failed") from errors[0]

    def _verify(self, tx):
        rows = list(tx.run("SHOW CONSTRAINTS YIELD entityType, type, labelsOrTypes, properties RETURN *"))
        for _, label, fields in _KEYS:
            if not any(
                r["entityType"] == "NODE"
                and r["type"] in ("UNIQUENESS", "NODE_KEY")
                and r["labelsOrTypes"] == [label]
                and tuple(r["properties"]) == fields
                for r in rows
            ):
                raise SchemaMissing(label)

        indexes = list(
            tx.run("SHOW INDEXES YIELD entityType, type, state, labelsOrTypes, properties, owningConstraint RETURN *")
        )
        if not any(
            r["entityType"] == "NODE"
            and r["type"] == "RANGE"
            and r["state"] == "ONLINE"
            and r["labelsOrTypes"] == ["ArenaResumeReceipt"]
            and r["properties"] == ["deployment_id", "workspace_id", "kind", "operation_id"]
            for r in indexes
        ):
            raise SchemaMissing("online resume receipt index required")
        lookup_indexes = [(label, ["deployment_id", "workspace_id", field]) for _, label, field in _HISTORY_INDEXES]
        lookup_indexes.append(("ArenaWorkflowProfileRevision", ["deployment_id", "workspace_id"]))
        lookup_indexes.append(("ArenaWorkflowEvent", ["deployment_id", "workspace_id", "run_id", "kind", "sequence"]))
        lookup_indexes.append((
            "ArenaWorkflowCandidate",
            ["deployment_id", "workspace_id", "run_id", "record_id"],
        ))
        lookup_indexes.append(("ArenaWorkflowDecision", ["deployment_id", "workspace_id", "run_id", "decision_id"]))
        for label, fields in lookup_indexes:
            if not any(
                r["entityType"] == "NODE"
                and r["type"] == "RANGE"
                and r["state"] == "ONLINE"
                and r["owningConstraint"] is None
                and r["labelsOrTypes"] == [label]
                and r["properties"] == fields
                for r in indexes
            ):
                raise SchemaMissing("online historical lookup index required: " + label)

    def verify_schema(self):
        """Read schema without provisioning or repairing it."""
        with self._transaction() as tx:
            self._verify(tx)
        return True

    def initialize_scope(self):
        """Initialize after administrator provisioning, before cooperative writers start.

        Schema provisioning and initialization are explicit quiescent gates, not
        concurrent runtime operations. No legacy run migration is performed here.
        """
        with self._transaction() as tx:
            self._verify(tx)
            list(
                tx.run(
                    "MERGE (c:ArenaWorkflowControl "
                    + _SCOPE
                    + ") "
                    "ON CREATE SET c.revision=0, c.sequence=0, c.floor=0 "
                    "SET c.revision=c.revision+1 RETURN c.floor AS floor, c.sequence AS ceiling",
                    **self.scope,
                )
            )

    def _checked_scope_binding(self, binding):
        from .scope_binding import ScopeBinding

        value = ScopeBinding.model_validate_json(binding.model_dump_json())
        if (value.database, value.deployment_id, value.workspace_id) != (
            self.database,
            self.scope["deployment_id"],
            self.scope["workspace_id"],
        ):
            raise SubmissionConflict("Scope binding target differs")
        return value

    def _scope_binding(self, tx):
        from .scope_binding import CorruptScopeBinding, ScopeMigrationRequired, decode_scope_binding

        rows = list(
            tx.run(
                _CONTROL
                + "RETURN "
                "CASE WHEN size(toStringOrNull(c.scope_binding_json))<=4096 "
                "THEN c.scope_binding_json ELSE null END AS body, "
                "CASE WHEN size(toStringOrNull(c.scope_binding_sha256))<=64 "
                "THEN c.scope_binding_sha256 ELSE null END AS digest, "
                "c.scope_binding_json IS NOT NULL OR c.scope_binding_sha256 IS NOT NULL AS present LIMIT 2",
                **self.scope,
            )
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise CorruptScopeBinding("Ambiguous retained scope binding")
        row = rows[0]
        if not row["present"]:
            raise ScopeMigrationRequired("Existing scope requires explicit migration")
        binding = decode_scope_binding(row["body"], row["digest"])
        if (binding.database, binding.deployment_id, binding.workspace_id) != (
            self.database,
            self.scope["deployment_id"],
            self.scope["workspace_id"],
        ):
            raise CorruptScopeBinding("Retained scope binding target differs")
        return binding

    def initialize_bound_scope(self, binding, *, protect):
        """Quiescent explicit initialization; exact replay never advances counters.

        Schema must already be provisioned. The existing unique control key owns
        binding and control atomically; legacy controls require separate migration.
        No retry on unknown commit, concurrent initialization or cleanup failure.
        """
        from .scene_evidence_artifacts import _protected

        binding = self._checked_scope_binding(binding)
        if not callable(protect):
            raise ValueError("public protection callback required")
        _protected(binding.model_dump(mode="json"), protect, max_bytes=4096)
        with self._transaction() as tx:
            self._verify(tx)
            retained = self._scope_binding(tx)
            if retained is None:
                orphan = list(
                    tx.run(
                        "MATCH (n " + _SCOPE + ") RETURN true AS present LIMIT 1",
                        **self.scope,
                    )
                )
                if orphan:
                    raise ScopeMissing("Orphan scope requires explicit migration")
                list(
                    tx.run(
                        "CREATE (c:ArenaWorkflowControl "
                        + _SCOPE
                        + ") "
                        "SET c.revision=0, c.sequence=0, c.floor=0, "
                        "c.scope_binding_json=$body, c.scope_binding_sha256=$digest RETURN c.workspace_id",
                        **self.scope,
                        body=binding.body_json,
                        digest=binding.body_sha256,
                    )
                )
                retained = self._scope_binding(tx)
            if retained != binding:
                raise SubmissionConflict("Scope binding differs")
        _protected(retained.model_dump(mode="json"), protect, max_bytes=4096)
        return retained

    def verify_scope_binding(self, binding):
        """Verify current schema and exact retained binding with MATCH/SHOW only."""
        binding = self._checked_scope_binding(binding)
        with self._transaction() as tx:
            self._verify(tx)
            retained = self._scope_binding(tx)
            if retained is None:
                raise ScopeMissing("Scope must be explicitly initialized")
            if retained != binding:
                raise SubmissionConflict("Scope binding differs")
        return retained

    def _lock(self, tx, *, bounded=False):
        # Constant SET takes the complete write lock before the dependent increment.
        rows = list(
            tx.run(
                _CONTROL
                + "SET c.lock_anchor=true SET c.revision=c.revision+1 RETURN "
                + (
                    "CASE WHEN size(toStringOrNull(c.floor))<=19 THEN c.floor ELSE null END AS floor, "
                    "CASE WHEN size(toStringOrNull(c.sequence))<=19 THEN c.sequence ELSE null END AS ceiling"
                    if bounded
                    else "c.floor AS floor, c.sequence AS ceiling"
                ),
                **self.scope,
            )
        )
        if len(rows) != 1:
            raise ScopeMissing("scope must be explicitly initialized")
        return rows[0]

    def _profile_scope(self):
        from .profiles import ProfileScope

        return ProfileScope(database=self.database, **self.scope)

    def _profile_read_scope(self, tx):
        rows = list(tx.run(_CONTROL + "RETURN c.workspace_id AS workspace_id LIMIT 2", **self.scope))
        if len(rows) != 1:
            raise ScopeMissing("scope must be explicitly initialized")

    def _profile_rows(self, tx, profile_id=None, revision=None):
        # Exact identity uses the full unique key; list/count use the scope index.
        # Use fixed-key dynamic node access for the physical scalar. Both p.revision
        # and properties(p).revision can reuse equality-index cache values (float
        # 2.0 hydrated as integer predicate 2), bypassing strict type validation.
        assert (profile_id is None) == (revision is None)
        predicate = "" if profile_id is None else "WHERE p.profile_id=$profile_id AND p.revision=$revision "
        params = {} if profile_id is None else dict(profile_id=profile_id, revision=revision)
        rows = list(
            tx.run(
                "MATCH (p:ArenaWorkflowProfileRevision "
                + _SCOPE
                + ") "
                + predicate
                + "RETURN p {.profile_id, revision: p[$revision_property], .kind, .schema_version, "
                ".body_sha256, .settings_sha256, "
                "body_json: CASE WHEN size(p.body_json)<=16384 THEN p.body_json ELSE null END} AS profile "
                "ORDER BY p.profile_id, p.revision LIMIT 65",
                revision_property="revision",
                **self.scope,
                **params,
            )
        )
        if len(rows) > 64:
            raise ValueError("Retained profile capacity exceeded")
        result = [self._profile_readback(row["profile"]) for row in rows]
        if len({(value.profile_id, value.revision) for value in result}) != len(result):
            raise ValueError("Ambiguous profile revision identity")
        for value in result:
            if self._profile_anchor(tx, value.profile_id) != value.registration.kind:
                raise ValueError("Retained profile kind anchor differs")
        return result

    def _profile_anchor(self, tx, profile_id):
        rows = list(
            tx.run(
                "MATCH (p:ArenaWorkflowProfile "
                + _SCOPE
                + ") WHERE p.profile_id=$profile_id RETURN p.kind AS kind LIMIT 2",
                **self.scope,
                profile_id=profile_id,
            )
        )
        if len(rows) > 1:
            raise ValueError("Ambiguous profile anchor")
        return rows[0]["kind"] if rows else None

    @staticmethod
    def _profile_readback(row):
        from .profiles import (
            MAX_PROFILE_BYTES,
            CorruptProfileRecord,
            ProfileRegistration,
            profile_body,
            profile_revision,
        )

        # Only retained decoding/validation is sanitized, never transport or cleanup.
        try:
            if type(row.get("schema_version")) is not int or type(row.get("revision")) is not int:
                raise ValueError("Invalid retained profile scalar types")
            body = row["body_json"]
            if type(body) is not str or len(body.encode("utf-8")) > MAX_PROFILE_BYTES:
                raise ValueError("Invalid retained profile body")
            value = json.loads(body)
            if type(value) is not dict or set(value) != {"schema_version", "registration"}:
                raise ValueError("Invalid retained profile envelope")
            if type(value["schema_version"]) is not int or value["schema_version"] != 1:
                raise ValueError("Unsupported retained profile codec")
            result = profile_revision(ProfileRegistration.model_validate(value["registration"]))
            if body != profile_body(result.registration) or row != {
                "profile_id": result.profile_id,
                "revision": result.revision,
                "kind": result.registration.kind,
                "schema_version": result.schema_version,
                "body_sha256": result.body_sha256,
                "settings_sha256": result.settings_sha256,
                "body_json": body,
            }:
                raise ValueError("Retained profile identity or digest differs")
            return result
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptProfileRecord("Invalid retained profile record") from None

    def register_profile(self, registration, *, protect):
        """Register public immutable bytes under initialized scope; grants no execution."""
        from ..inference_profiles import checked_inference_profile
        from .profiles import MAX_PROFILE_REVISIONS, ProfileRegistration, profile_body, profile_revision
        from .scene_evidence_artifacts import _protected

        self._profile_scope()
        registration = ProfileRegistration.model_validate_json(registration.model_dump_json())
        result = profile_revision(registration)
        if not callable(protect):
            raise ValueError("public protection callback required")
        _protected(result.model_dump(mode="json"), protect)
        with self._transaction() as tx:
            self._lock(tx)
            self._verify(tx)
            previous = self._profile_rows(tx, registration.profile_id, registration.revision)
            if previous:
                if previous != [result]:
                    raise SubmissionConflict("profile revision differs")
                return previous[0]
            count = list(
                tx.run(
                    "MATCH (p:ArenaWorkflowProfileRevision " + _SCOPE + ") RETURN count(p) AS count",
                    **self.scope,
                )
            )[0]["count"]
            if count >= MAX_PROFILE_REVISIONS:
                raise CapacityExceeded("profile revision capacity exhausted")
            settings = registration.settings
            checked_inference_profile(
                settings.inference_policy.model_dump(mode="json"), model=settings.model, base_url=settings.endpoint
            )
            kind = self._profile_anchor(tx, registration.profile_id)
            if kind is not None and kind != registration.kind:
                raise SubmissionConflict("profile kind differs")
            if kind is None:
                list(
                    tx.run(
                        "CREATE (p:ArenaWorkflowProfile "
                        + _SCOPE
                        + ") SET p.profile_id=$profile_id, p.kind=$kind RETURN p.kind AS kind",
                        **self.scope,
                        profile_id=registration.profile_id,
                        kind=registration.kind,
                    )
                )
            rows = list(
                tx.run(
                    "CREATE (p:ArenaWorkflowProfileRevision "
                    + _SCOPE
                    + ") "
                    "SET p.profile_id=$profile_id, p.revision=$revision, p.kind=$kind, "
                    "p.schema_version=$schema_version, p.body_json=$body_json, "
                    "p.body_sha256=$body_sha256, p.settings_sha256=$settings_sha256 RETURN p.profile_id AS id",
                    **self.scope,
                    profile_id=result.profile_id,
                    revision=result.revision,
                    kind=registration.kind,
                    schema_version=result.schema_version,
                    body_json=profile_body(registration),
                    body_sha256=result.body_sha256,
                    settings_sha256=result.settings_sha256,
                )
            )
            if len(rows) != 1 or self._profile_rows(tx, result.profile_id, result.revision) != [result]:
                raise ValueError("Profile creation readback differs")
        return result

    def get_profile(self, profile_id, revision):
        """Read retained codec and digests only; no control lock or catalogue lookup."""
        from .profiles import ProfileIdentity

        self._profile_scope()
        ProfileIdentity(profile_id=profile_id, revision=revision)
        with self._transaction() as tx:
            self._profile_read_scope(tx)
            rows = self._profile_rows(tx, profile_id, revision)
            if len(rows) > 1:
                raise ValueError("Ambiguous profile identity")
            result = rows[0] if rows else None
        return result

    def list_profiles(self):
        """Read the bounded retained catalogue without probing or resolving defaults."""
        self._profile_scope()
        with self._transaction() as tx:
            self._profile_read_scope(tx)
            result = tuple(self._profile_rows(tx))
        return result

    def _run(self, tx, field, value):
        assert field in ("operation_id", "run_id")
        rows = list(
            tx.run(
                "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r." + field + "=$identity RETURN " + _VIEW + " AS run",
                **self.scope,
                identity=value,
            )
        )
        return RunHandle(**rows[0]["run"]) if rows else None

    @staticmethod
    def _replay(run, request_json):
        if run is not None and run.request_json != request_json:
            raise SubmissionConflict("operation request differs")
        return run

    def lookup_submission(self, operation_id, request_json):
        """Return retained acceptance without resolving mutable execution inputs."""
        validate_operation_id(operation_id)
        _canonical(request_json)
        try:
            with self._transaction() as tx:
                self._lock(tx)
                result = self._replay(self._run(tx, "operation_id", operation_id), request_json)
        except _lookup_transport_errors() as exc:
            raise StoreUnavailable("workflow store unavailable") from exc
        return result

    def _inspection_rows(self, tx, field, identity):
        assert field in ("operation_id", "run_id")
        # Exact predicates use the existing composite unique indexes. Bound each
        # string before Bolt hydration; UTF-8 byte validation follows locally.
        bounds = (
            ("deployment_id", 4096),
            ("workspace_id", 4096),
            ("run_id", 128),
            ("operation_id", 128),
            ("request_json", 2097152),
            ("contract_json", 2097152),
            ("admitted_at", 64),
        )
        if field == "run_id":
            bounds += (("version", 32), ("event_cursor", 32), ("state", 64), ("phase", 64))
        # toStringOrNull guards corrupt arrays and non-string scalar properties
        # without hydrating them or throwing input-bearing Cypher type errors.
        # Return the physical value, not the string conversion: strict local
        # validation must still distinguish boolean, float and integer counters.
        projection = [
            f"{key}: CASE WHEN size(toStringOrNull(r.{key}))<={limit} THEN r.{key} ELSE null END"
            for key, limit in bounds
        ]
        for key in ("request_digest", "accepted_contract_digest", "digest_codec"):
            projection.append(
                f"{key}: CASE WHEN r.{key} IS NULL THEN null "
                f"WHEN size(toStringOrNull(r.{key}))<=64 THEN r.{key} ELSE '' END"
            )
        return list(
            tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") WHERE r."
                + field
                + "=$identity RETURN r {"
                + ", ".join(projection)
                + "} AS retained LIMIT 2",
                **self.scope,
                identity=identity,
            )
        )

    def _submission_readback(self, row, field, identity):
        from .queries import SUBMISSION_INSPECTION_BYTES
        from .scene_evidence_artifacts import canonical

        if row[field] != identity or any(row[key] != value for key, value in self.scope.items()):
            raise ValueError("Retained identity differs")
        validate_operation_id(row["operation_id"])
        raw_identity = json.dumps(
            [self.scope["deployment_id"], self.scope["workspace_id"], row["operation_id"]],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if row["run_id"] != hashlib.sha256(raw_identity.encode("utf-8")).hexdigest():
            raise ValueError("Retained admission identity differs")
        digests = []
        for key in ("request_json", "contract_json"):
            body = row[key]
            if type(body) is not str or len(body.encode("utf-8")) > 2 * 1024 * 1024:
                raise ValueError("Retained body bound")
            _canonical(body)
            digests.append(hashlib.sha256(body.encode("utf-8")).hexdigest())
        # Legacy writers retained no independent digest metadata. Compute from
        # exact canonical bytes; if metadata exists, it must agree, never repair it.
        for key, expected in zip(
            ("request_digest", "accepted_contract_digest", "digest_codec"),
            (*digests, "sha256-canonical-json-utf8-v1"),
        ):
            if row[key] is not None and row[key] != expected:
                raise ValueError("Retained digest metadata differs")
        result = FrozenSubmissionInspection(
            scope=SceneReadScope(database=self.database, **self.scope),
            kind="SUBMIT",
            operation_id=row["operation_id"],
            run_id=row["run_id"],
            request_digest=digests[0],
            accepted_contract_digest=digests[1],
            digest_codec="sha256-canonical-json-utf8-v1",
            admitted_at=row["admitted_at"],
            disposition="retained_admission",
            provenance="legacy_run_record",
            receipt_version=None,
            cause_id=None,
        )
        canonical(result.model_dump(mode="json"), max_bytes=SUBMISSION_INSPECTION_BYTES)
        return result

    def get_submission_inspection(self, operation_id) -> FrozenSubmissionInspection | None:
        """Read bounded legacy admission facts without the original request or effects."""
        from .queries import CorruptRunRecord

        validate_operation_id(operation_id)
        with self._transaction(fetch_size=2) as tx:
            rows = self._inspection_rows(tx, "operation_id", operation_id)
            # Query/transport and transaction cleanup stay outside this boundary.
            try:
                if len(rows) > 1:
                    raise ValueError("Ambiguous retained admission")
                result = self._submission_readback(rows[0]["retained"], "operation_id", operation_id) if rows else None
            except (ValueError, TypeError, KeyError, RecursionError):
                raise CorruptRunRecord() from None
        return result

    def get_run_intent(self, run_id) -> FrozenRunIntentView | None:
        """Read the supported frozen contract and cooperative current lifecycle only."""
        validate_operation_id(run_id)
        with self._transaction(fetch_size=2) as tx:
            result = self._run_intent(tx, run_id)
        return result

    def _run_intent(self, tx, run_id):
        from .contracts import canonical_json
        from .queries import RUN_INTENT_VIEW_BYTES, CorruptRunRecord
        from .scene_evidence_artifacts import canonical

        # Same cooperative lock as writers, but an absent scope/root is a
        # query miss, not an invitation to initialize a control record.
        anchors = list(
            tx.run(
                _CONTROL + "SET c.lock_anchor=true SET c.revision=c.revision+1 RETURN 1 AS present LIMIT 2",
                **self.scope,
            )
        )
        rows = self._inspection_rows(tx, "run_id", run_id)
        try:
            if len(anchors) > 1 or (rows and len(anchors) != 1):
                raise ValueError("Retained run control binding differs")
            if len(rows) > 1:
                raise ValueError("Ambiguous retained run")
            result = None
            if rows:
                row = rows[0]["retained"]
                submission = self._submission_readback(row, "run_id", run_id)
                contract = parse_contract(row["contract_json"])
                # Defaults and coercions may be useful at admission, never
                # when reconstructing the exact supported retained codec.
                if canonical_json(contract) != row["contract_json"]:
                    raise ValueError("Retained contract does not roundtrip")
                result = FrozenRunIntentView(
                    scope=submission.scope,
                    run_id=submission.run_id,
                    submission=submission,
                    contract=contract,
                    state=row["state"],
                    phase=row["phase"],
                    run_version=row["version"],
                    event_cursor=row["event_cursor"],
                    intent_projection_revision="0" * 64,
                )
                body = result.model_dump(mode="json", exclude={"intent_projection_revision"})
                revision = hashlib.sha256(canonical(body, max_bytes=RUN_INTENT_VIEW_BYTES)).hexdigest()
                result = result.model_copy(update={"intent_projection_revision": revision})
                canonical(result.model_dump(mode="json"), max_bytes=RUN_INTENT_VIEW_BYTES)
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptRunRecord() from None
        return result

    def get_run_inspection(self, run_id) -> RunInspection | None:
        """Join retained point-read dependencies under one cooperative transaction."""
        from types import SimpleNamespace

        from .contracts import canonical_json
        from .queries import RUN_INSPECTION_BYTES, CorruptRunInspection, InspectionActions
        from .read_model import inspection_budget, inspection_response_revision
        from .scene_evidence_artifacts import canonical

        validate_operation_id(run_id)
        with self._transaction(fetch_size=1) as tx:
            intent = self._run_intent(tx, run_id)
            result = None
            if intent is not None:
                try:
                    dependencies = []
                    cleanup = self._run_cleanup(tx, run_id, dependencies=dependencies)
                    reservations, readiness, attempts, outputs = self._inspection_ledger(
                        tx, intent, cleanup, dependencies
                    )
                    run = SimpleNamespace(
                        run_id=run_id,
                        state=intent.state,
                        phase=intent.phase,
                        version=intent.run_version,
                        contract_json=canonical_json(intent.contract),
                    )
                    preview = self._resume_preview(tx, run_id, retained_run=run, retained_attempts=attempts)
                    scene = self._inspection_scene(tx, intent)
                except (CorruptCleanupRecord, CorruptSceneRecord, CorruptResumeSelection):
                    raise CorruptRunInspection() from None
                # Only local decoding/projection errors are retained corruption.
                try:
                    result = RunInspection(
                        intent=intent,
                        cleanup=cleanup,
                        budget=inspection_budget(intent, reservations),
                        readiness=readiness,
                        scene=scene,
                        generation_outputs=outputs,
                        retained_assessment_json=self._retained_assessment_history(tx, intent),
                        actions=InspectionActions(
                            cancel_applicable=intent.state
                            in ("pending", "running", "cancel_requested", "reconciliation_required"),
                            resume_branch=preview.selection.branch if preview.selection else None,
                            resume_intent_id=preview.selection.intent_id if preview.selection else None,
                        ),
                        policy_outcome=(
                            "not_requested"
                            if intent.contract.execution.policy is None
                            else (
                                scene.policy_trial.aggregate().outcome
                                if scene is not None and scene.policy_trial
                                else (
                                    "ready_for_policy"
                                    if scene is not None and scene.action == "policy"
                                    else "unsupported_or_unretained"
                                )
                            )
                        ),
                        publication_outcome="unknown" if intent.contract.effects.allow_publication else "not_permitted",
                        retained_dependencies_revision=hashlib.sha256(
                            canonical(dependencies, max_bytes=17 * 1024 * 1024)
                        ).hexdigest(),
                        retained_revision="0" * 64,
                        response_revision="0" * 64,
                    )
                    raw = canonical(
                        result.model_dump(mode="json", exclude={"retained_revision", "response_revision"}),
                        max_bytes=RUN_INSPECTION_BYTES,
                    )
                    result = result.model_copy(update={"retained_revision": hashlib.sha256(raw).hexdigest()})
                    result = inspection_response_revision(result)
                except (ValueError, TypeError, KeyError, RecursionError):
                    raise CorruptRunInspection() from None
        return result

    def _retained_assessment_history(self, tx, intent):
        from .queries import CorruptRunInspection
        from .scene_evidence_artifacts import canonical
        from .scene_loop import SceneIntent, SceneResult

        if intent.contract.schema_version != "4":
            return None
        rows = list(
            tx.run(
                "MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ") WHERE i.run_id=$run RETURN i.intent_id AS id, "
                "CASE WHEN size(toStringOrNull(i.scene_json))<=2097152 THEN i.scene_json ELSE [false] END AS scene, "
                "CASE WHEN i.result_json IS NULL THEN null WHEN size(toStringOrNull(i.result_json))<=2097152 "
                "THEN i.result_json ELSE [false] END AS result, "
                "CASE WHEN i.assessment_send_json IS NULL THEN null "
                "WHEN size(toStringOrNull(i.assessment_send_json))<=4096 THEN i.assessment_send_json "
                "ELSE [false] END AS dispatch LIMIT 4",
                **self.scope,
                run=intent.run_id,
            )
        )
        if len(rows) > 3:
            raise CorruptRunInspection()
        records = []
        for row in rows:
            scene = SceneIntent.model_validate_json(row["scene"])
            result = None if row["result"] is None else SceneResult.model_validate_json(row["result"])
            value = (
                json.loads(result.retained_assessment_json)
                if result is not None and result.retained_assessment_json is not None
                else None
            )
            if scene.intent_id != row["id"] or (
                value is not None
                and (
                    value["consumer_contract_digest"] != contract_digest(intent.contract)
                    or value["producer"] != intent.contract.retained_evidence.model_dump(mode="json")
                )
            ):
                raise CorruptRunInspection()
            records.append(
                dict(
                    intent_id=row["id"],
                    dispatch=None if row["dispatch"] is None else json.loads(row["dispatch"]),
                    result=value,
                    failure=None if result is None else result.failure,
                )
            )
        return canonical(dict(attempts=sorted(records, key=lambda row: row["intent_id"]))).decode()

    def _inspection_scene(self, tx, intent):
        from .queries import CorruptRunInspection
        from .read_model import inspection_scene
        from .scene_loop import CandidateRecord, SceneDecision, SceneIntent

        bounds = (
            ("scene_candidate", HISTORICAL_CANDIDATE_BYTES),
            ("scene_decision", 2097152),
            ("scene_evidence", 128),
            ("scene_intent", 128),
        )
        projection = [
            f"{field}: CASE WHEN size(toStringOrNull(r.{field}))<={limit} THEN r.{field} "
            f"WHEN r.{field} IS NULL THEN null ELSE [false] END"
            for field, limit in bounds
        ]
        rows = list(
            tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") WHERE r.run_id=$run RETURN r {"
                + ", ".join(projection)
                + "} AS scene LIMIT 2",
                **self.scope,
                run=intent.run_id,
            )
        )
        if len(rows) != 1:
            raise CorruptRunInspection()
        root = rows[0]["scene"]
        if all(value is None for value in root.values()):
            if intent.phase == "scene":
                raise CorruptRunInspection()
            return None
        candidate = self._historical_payload({"node": {"payload": root["scene_candidate"]}}, CandidateRecord)
        candidate_row = self._historical_node(tx, "ArenaWorkflowCandidate", candidate.candidate_id)
        if candidate_row is None or self._historical_candidate(tx, candidate_row).candidate != candidate:
            raise CorruptRunInspection()
        if candidate.run_id != intent.run_id:
            raise CorruptRunInspection()
        decision = self._historical_payload({"node": {"payload": root["scene_decision"]}}, SceneDecision)
        # Equality prefix plus sequence range uses the explicit nonunique admin index.
        # Do not filter source_id: a latest legacy source-less event must stay latest.
        events = list(
            tx.run(
                "MATCH (e:ArenaWorkflowEvent "
                + _SCOPE
                + ") "
                "USING INDEX e:ArenaWorkflowEvent(deployment_id, workspace_id, run_id, kind, sequence) "
                "WHERE e.run_id=$run AND e.kind='SceneDecisionRecorded' AND e.sequence>=0 "
                "RETURN CASE WHEN size(toStringOrNull(e.source_id))<=128 THEN e.source_id "
                "WHEN e.source_id IS NULL THEN null ELSE [false] END AS source, e.sequence AS sequence "
                "ORDER BY e.sequence DESC LIMIT 1",
                **self.scope,
                run=intent.run_id,
            )
        )
        decision_id = events[0]["source"] if events else None
        if events and (type(events[0]["sequence"]) is not int or events[0]["sequence"] > intent.event_cursor):
            raise CorruptRunInspection()
        if decision_id is not None:
            row = self._historical_node(tx, "ArenaWorkflowDecision", decision_id)
            if row is None:
                raise CorruptRunInspection()
            historical = self._historical_decision(tx, row)
            if (
                historical is None
                or historical.run_id != intent.run_id
                or historical.decision != decision
                or historical.candidate_id != candidate.candidate_id
                or historical.evidence_id != root["scene_evidence"]
                or historical.next_intent_id != root["scene_intent"]
            ):
                raise CorruptRunInspection()
        if root["scene_intent"] is not None:
            row = self._historical_node(tx, "ArenaExecutionIntent", root["scene_intent"])
            if row is None:
                raise CorruptRunInspection()
            selected_intent = self._historical_payload(row, SceneIntent, "scene_json")
            owner = self._historical_owner(tx, row, "HAS_SCENE_INTENT")
            if (
                owner["node"]["run_id"] != intent.run_id
                or selected_intent.intent_id != root["scene_intent"]
                or selected_intent.candidate_id != candidate.candidate_id
                or selected_intent.action != decision.action
            ):
                raise CorruptRunInspection()
        evidence, assessment_id = None, None
        if root["scene_evidence"] is not None:
            row = self._historical_node(tx, "ArenaWorkflowEvidence", root["scene_evidence"])
            if row is None:
                raise CorruptRunInspection()
            evidence = self._historical_evidence(tx, row)
            if evidence.run_id != intent.run_id or evidence.candidate_id not in (None, candidate.candidate_id):
                raise CorruptRunInspection()
            assessed = self._historical_link(
                tx, row, "ASSESSES", "ArenaCriterionAssessment", incoming=True, required=False
            )
            if assessed is not None:
                assessment = self._historical_assessment(tx, assessed)
                if assessment.assessment != decision.assessment or assessment.candidate_id != candidate.candidate_id:
                    raise CorruptRunInspection()
                assessment_id = assessment.assessment_id
        if decision.assessment is not None and assessment_id is None:
            raise CorruptRunInspection()
        try:
            return inspection_scene(
                intent.contract, candidate, decision, evidence, assessment_id, decision_id, root["scene_intent"]
            )
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptRunInspection() from None

    def _inspection_ledger(self, tx, intent, cleanup, dependencies):
        from .queries import CorruptRunInspection, GenerationOutputReference, RetainedReadiness
        from .scene_loop import SceneReservation

        fields = ("intent_id", "reservation_json", "readiness_json")
        query = (
            "MATCH (i:ArenaExecutionIntent "
            + _SCOPE
            + ") WHERE i.run_id=$run OPTIONAL MATCH (i)-[:HAS_ATTEMPT]->(a) RETURN "
            + self._cleanup_projection("i", fields)
            + " AS intent, "
            + self._cleanup_projection(
                "a", ("attempt_id", "readiness_json", "registration_json", "receipt_disposition")
            )
            + " AS attempt, CASE WHEN size(toStringOrNull(a.receipt_json))<=401408 THEN a.receipt_json "
            "WHEN a.receipt_json IS NULL THEN null ELSE [false] END AS receipt LIMIT 1001"
        )
        rows, size = [], 0
        for record in tx.run(query, **self.scope, run=intent.run_id):
            try:
                row = dict(record)
                size += len(json.dumps(row, allow_nan=False).encode())
            except (ValueError, TypeError, KeyError, RecursionError):
                raise CorruptRunInspection() from None
            if len(rows) >= 1000 or size > 8 * 1024 * 1024:
                raise CorruptRunInspection()
            rows.append(row)
        try:
            dependencies.append(sorted(rows, key=lambda row: row["intent"]["intent_id"]))
            obligations = {item.intent_id: item for item in cleanup.intents}
            if len(rows) != len(obligations) or {row["intent"]["intent_id"] for row in rows} != set(obligations):
                raise CorruptRunInspection()
            reservations, readiness, attempts, outputs = [], [], {}, []
            for row in sorted(rows, key=lambda row: row["intent"]["intent_id"]):
                i, a = row["intent"], row["attempt"]
                obligation = obligations[i["intent_id"]]
                model = GenerationReservation if obligation.kind == "generation" else SceneReservation
                allocation = self._cleanup_json(i["reservation_json"], model).model_dump(mode="json")
                if obligation.kind == "generation":
                    allocation["candidates"] = 1
                reservations.append(allocation)
                for source, data in (("intent.readiness_json", i), ("attempt.readiness_json", a)):
                    if data is None or data["readiness_json"] is None:
                        continue
                    receipt = self._cleanup_json(data["readiness_json"], ReadinessReceipt)
                    expected = {
                        (r.dependency_id, r.profile_id, r.profile_sha256)
                        for r in required_dependencies(intent.contract)
                    }
                    reported = {(p.role, p.profile_id, p.settings_sha256) for p in receipt.profiles}
                    if (
                        receipt.contract_digest != contract_digest(intent.contract)
                        or reported != expected
                        or len(receipt.profiles) != len(expected)
                        or any(
                            p.expected_instance_id is not None and p.expected_instance_id != p.observed_instance_id
                            for p in receipt.profiles
                        )
                    ):
                        raise CorruptRunInspection()
                    readiness.append(
                        RetainedReadiness(
                            intent_id=i["intent_id"],
                            attempt_id=a["attempt_id"] if source.startswith("attempt") else None,
                            source=source,
                            receipt=receipt,
                        )
                    )
                if a is not None and a["attempt_id"] is not None:
                    if obligation.fence is None or a["attempt_id"] != obligation.fence.attempt_id:
                        raise CorruptRunInspection()
                    attempts[a["attempt_id"]] = a
                if row["receipt"] is not None:
                    receipt = self._historical_payload({"node": {"payload": row["receipt"]}}, GenerationReceipt)
                    if (
                        obligation.kind != "generation"
                        or receipt.fence != obligation.fence
                        or receipt.registration.registration_id != obligation.registration_id
                        or receipt.registration != self._cleanup_json(a["registration_json"], WorkerRegistration)
                        or obligation.release_state != "released"
                        or receipt.contract_digest != contract_digest(intent.contract)
                        or receipt.generation_profile != intent.contract.execution.generation_model
                    ):
                        raise CorruptRunInspection()
                    outputs.append(
                        GenerationOutputReference(
                            intent_id=i["intent_id"],
                            attempt_id=receipt.fence.attempt_id,
                            registration_id=receipt.registration.registration_id,
                            contract_digest=receipt.contract_digest,
                            candidate_yaml_sha256=receipt.candidate_yaml_sha256,
                            candidate_json_sha256=receipt.candidate_json_sha256,
                            provenance_sha256=receipt.provenance_sha256,
                            manifest_sha256=receipt.manifest_sha256,
                            disposition=a["receipt_disposition"],
                        )
                    )
            return reservations, tuple(readiness), attempts, tuple(outputs)
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptRunInspection() from None

    def get_run(self, run_id):
        """Return the single canonical run view in this scope."""
        _identifier(run_id)
        with self._transaction() as tx:
            self._lock(tx)
            result = self._run(tx, "run_id", run_id)
        return result

    def _prior_reference(self, tx, run_id):
        from .prior_artifacts import PRIOR_REFERENCE_BYTES, checked_prior_reference

        run = self._run(tx, "run_id", run_id)
        if run is None:
            raise ValueError("Unknown prior run")
        contract = parse_contract(run.contract_json)
        rows = list(
            tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") WHERE r.run_id=$run_id "
                "RETURN (r.prior_retrieval_state IS NOT NULL OR r.prior_reference_sha256 IS NOT NULL "
                "OR r.prior_reference_json IS NOT NULL) AS present, "
                "CASE WHEN size(toStringOrNull(r.prior_retrieval_state))<=16 "
                "THEN r.prior_retrieval_state ELSE null END AS state, "
                "CASE WHEN size(toStringOrNull(r.prior_reference_sha256))<=64 "
                "THEN r.prior_reference_sha256 ELSE null END AS sha, "
                "CASE WHEN size(toStringOrNull(r.prior_reference_json))<=$bound "
                "THEN r.prior_reference_json ELSE null END AS body LIMIT 2",
                **self.scope,
                run_id=run_id,
                bound=PRIOR_REFERENCE_BYTES,
            )
        )
        if len(rows) != 1 or contract.retrieval is None:
            raise ValueError("Missing or ambiguous prior selection")
        row = rows[0]
        if row["present"] is False:
            return None
        if row["state"] != "retained" or type(row["body"]) is not str:
            raise ValueError("Prior retrieval incomplete or linkage missing")
        if hashlib.sha256(row["body"].encode()).hexdigest() != row["sha"]:
            raise ValueError("Prior linkage digest differs")
        checked_prior_reference(row["body"], contract=contract, run_id=run_id)
        return row["body"]

    def get_prior_reference(self, run_id):
        """Read the exact authoritative prior linkage, including incomplete-selection refusal."""
        validate_operation_id(run_id)
        with self._transaction() as tx:
            self._lock(tx)
            result = self._prior_reference(tx, run_id)
        return result

    def begin_prior_retrieval(self, run_id):
        """Consume the one-shot prior selection before any source access, under the existing lock."""
        validate_operation_id(run_id)
        with self._transaction() as tx:
            self._lock(tx)
            run = self._run(tx, "run_id", run_id)
            if (
                run is None
                or run.state != "pending"
                or run.version != 1
                or self._prior_reference(tx, run_id) is not None
            ):
                raise ValueError("Prior retrieval is not a fresh admission")
            contract = parse_contract(run.contract_json)
            row = tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") WHERE r.run_id=$run_id "
                "RETURN CASE WHEN size(toStringOrNull(r.admitted_at))<=64 "
                "THEN r.admitted_at ELSE null END AS admitted_at",
                **self.scope,
                run_id=run_id,
            ).single()
            admitted_at, now = row["admitted_at"], self._now()
            if (
                type(admitted_at) not in (int, float)
                or not math.isfinite(admitted_at)
                or not admitted_at <= now < admitted_at + contract.budget.total_deadline_seconds
            ):
                raise ValueError("Prior retrieval deadline expired")
            tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") WHERE r.run_id=$run_id SET r.prior_retrieval_state='retrieving'",
                **self.scope,
                run_id=run_id,
            ).consume()
            self._event(tx, run_id, "PriorRetrievalStarted", contract.retrieval.settings_sha256)
        return admitted_at + contract.budget.total_deadline_seconds

    def retain_prior_reference(self, run_id, reference):
        """Commit the immutable artifact link before generation reservation or release."""
        from .prior_artifacts import checked_prior_reference

        validate_operation_id(run_id)
        with self._transaction() as tx:
            self._lock(tx)
            run = self._run(tx, "run_id", run_id)
            if run is None or run.state != "pending":
                raise ValueError("Prior run no longer pending")
            checked_prior_reference(reference, contract=parse_contract(run.contract_json), run_id=run_id)
            rows = list(
                tx.run(
                    "MATCH (r:ArenaWorkflowRun "
                    + _SCOPE
                    + ") WHERE r.run_id=$run_id "
                    "AND r.prior_retrieval_state='retrieving' AND r.prior_reference_json IS NULL "
                    "AND r.prior_reference_sha256 IS NULL SET r.prior_retrieval_state='retained', "
                    "r.prior_reference_json=$body, r.prior_reference_sha256=$sha RETURN r.run_id AS id",
                    **self.scope,
                    run_id=run_id,
                    body=reference,
                    sha=hashlib.sha256(reference.encode()).hexdigest(),
                )
            )
            if len(rows) != 1:
                raise ValueError("Prior selection already consumed or ambiguous")
            self._event(tx, run_id, "PriorRetained", hashlib.sha256(reference.encode()).hexdigest())

    def admit(self, operation_id, request_json, contract_json, max_pending):
        """Atomically admit or replay a request; a handle grants no execution authority."""
        validate_operation_id(operation_id)
        _canonical(request_json)
        with self._transaction() as tx:
            self._lock(tx)
            result = self._replay(self._run(tx, "operation_id", operation_id), request_json)
            if result is None:
                _canonical(contract_json)
                if type(max_pending) is not int or max_pending < 0:
                    raise ValueError("nonnegative integer capacity required")
                pending = list(
                    tx.run(
                        "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r.state=$state RETURN count(r) AS pending",
                        **self.scope,
                        state="pending",
                    )
                )
                if pending[0]["pending"] >= max_pending:
                    raise CapacityExceeded("pending capacity exhausted")
                identity = json.dumps(
                    [
                        self.scope["deployment_id"],
                        self.scope["workspace_id"],
                        operation_id,
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                run_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                rows = list(
                    tx.run(
                        _CONTROL
                        + "SET c.sequence=c.sequence+1 CREATE (r:ArenaWorkflowRun "
                        + _SCOPE
                        + ") "
                        "SET r.run_id=$run_id, r.operation_id=$operation_id, r.request_json=$request_json, "
                        "r.contract_json=$contract_json, r.version=1, r.state=$state, r.event_cursor=c.sequence, "
                        "r.admitted_at=$admitted_at, r.phase='dependency_readiness', r.decision_coverage=1 "
                        "CREATE (e:ArenaWorkflowEvent "
                        + _SCOPE
                        + ") "
                        "SET e.sequence=c.sequence, e.run_id=$run_id, e.operation_id=$operation_id, "
                        "e.kind=$kind, e.schema_version=1 RETURN "
                        + _VIEW
                        + " AS run",
                        **self.scope,
                        run_id=run_id,
                        operation_id=operation_id,
                        request_json=request_json,
                        contract_json=contract_json,
                        state="pending",
                        kind="WorkflowRequested",
                        admitted_at=self._now(),
                    )
                )
                result = RunHandle(**rows[0]["run"])
        return result

    def _now(self):
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError("trusted finite clock required")
        return now

    def _generation_authority(self, contract, authorization, now):
        authorization = AuthorizationSnapshot.model_validate_json(authorization.model_dump_json())
        if (
            authorization.database != self.database
            or any(getattr(authorization, key) != value for key, value in self.scope.items())
            or authorization.contract_digest != contract_digest(contract)
            or authorization.expires_at <= now
            or not {"generation_model", "operational_writes"} <= set(authorization.capabilities)
            or not contract.effects.allow_operational_writes
            or contract.source.kind != "new"
        ):
            raise ValueError("generation authority or contract scope denied")
        if contract.execution.generation_model.billing == "paid" and (
            not contract.effects.allow_paid_models or "paid_models" not in authorization.capabilities
        ):
            raise ValueError("paid generation denied")

    def _scene_authority(self, contract, authorization, now):
        """Keep native-only grants separate from the unchanged generation boundary."""
        if contract.schema_version == "4":
            authorization = AuthorizationSnapshot.model_validate_json(authorization.model_dump_json())
            expected = {"assessment_model", "operational_writes"}
            if contract.execution.assessment_model.billing == "paid":
                expected.add("paid_models")
            if (
                authorization.database != self.database
                or any(getattr(authorization, key) != value for key, value in self.scope.items())
                or authorization.contract_digest != contract_digest(contract)
                or authorization.expires_at <= now
                or set(authorization.capabilities) != expected
                or contract.effects.allow_runtime
                or not contract.effects.allow_operational_writes
            ):
                raise ValueError("Retained assessment authority denied")
            return
        if contract.schema_version != "3":
            self._generation_authority(contract, authorization, now)
            return
        authorization = AuthorizationSnapshot.model_validate_json(authorization.model_dump_json())
        if (
            authorization.database != self.database
            or any(getattr(authorization, key) != value for key, value in self.scope.items())
            or authorization.contract_digest != contract_digest(contract)
            or authorization.expires_at <= now
            or set(authorization.capabilities) != {"native_validation", "operational_writes"}
            or not contract.effects.allow_runtime
            or not contract.effects.allow_operational_writes
        ):
            raise ValueError("native-only scene authority denied")

    def _event(self, tx, run_id, kind, source_id, *, command_operation_id=None, command_kind="CANCEL"):
        tx.run(
            _CONTROL
            + "MATCH (r:ArenaWorkflowRun "
            + _SCOPE
            + ") WHERE r.run_id=$run_id "
            "SET c.sequence=c.sequence+1 SET r.version=r.version+1, r.event_cursor=c.sequence "
            "CREATE (e:ArenaWorkflowEvent "
            + _SCOPE
            + ") "
            "SET e.sequence=c.sequence, e.run_id=r.run_id, e.operation_id=r.operation_id, "
            "e.kind=$kind, e.schema_version=1, e.source_id=$source_id, "
            "e.command_kind=$command_kind, e.command_operation_id=$command_operation_id",
            **self.scope,
            run_id=run_id,
            kind=kind,
            source_id=source_id,
            command_kind=command_kind if command_operation_id is not None else None,
            command_operation_id=command_operation_id,
        ).consume()

    def _readiness(self, contract, readiness, now):
        if type(readiness) is not ReadinessReceipt:
            raise ValueError("typed readiness receipt required")
        readiness = ReadinessReceipt.model_validate_json(readiness.model_dump_json())
        required = required_dependencies(contract, resolved_instances=self.dependency_instances)
        expected = {(r.dependency_id, r.profile_id, r.profile_sha256, r.instance_id) for r in required}
        observed = {(p.role, p.profile_id, p.settings_sha256, p.expected_instance_id) for p in readiness.profiles}
        if (
            readiness.contract_digest != contract_digest(contract)
            or not 0 <= now - readiness.checked_at <= self.readiness_ttl
            or observed != expected
            or len(readiness.profiles) != len(expected)
            or any(
                p.expected_instance_id is not None and p.expected_instance_id != p.observed_instance_id
                for p in readiness.profiles
            )
        ):
            raise ValueError("readiness stale or mismatched")
        return readiness

    def reserve_generation(
        self,
        run_id,
        expected_version,
        decision_id,
        authorization,
        reservation,
        *,
        readiness,
    ):
        """Reserve the initial New generation atomically; return a stable intent ID.

        Exact transition replay is observation, not fresh execution authority. Only
        pending versioned runs are supported; no candidate verification, retries,
        refunds or acceptance transitions exist. Clock is supplied by trusted local
        composition, never by an untrusted request. Whole retained contracts are
        validated, not a reduced projection. All effects remain outside transactions.
        """
        validate_operation_id(run_id)
        validate_operation_id(decision_id)
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("positive expected version required")
        reservation = GenerationReservation.model_validate_json(reservation.model_dump_json())
        authorization = AuthorizationSnapshot.model_validate_json(authorization.model_dump_json())
        intent_id = hashlib.sha256(
            json.dumps(
                [self.database, self.scope, run_id, expected_version, "generation"],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        payload = json.dumps(
            [
                decision_id,
                authorization.model_dump(mode="json"),
                reservation.model_dump(mode="json"),
            ],
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._transaction() as tx:
            self._lock(tx)
            run = self._run(tx, "run_id", run_id)
            if run is None:
                raise ValueError("unknown run")
            prior = tx.run(
                "MATCH (i:ArenaExecutionIntent " + _SCOPE + ") WHERE i.intent_id=$id RETURN i.payload AS payload",
                **self.scope,
                id=intent_id,
            ).single()
            if prior is not None:
                if prior["payload"] != payload:
                    raise ValueError("conflicting decision replay")
                return intent_id
            if run.version != expected_version or run.state != "pending":
                raise ValueError("stale version or inactive generation phase")
            contract = parse_contract(run.contract_json)
            now = self._now()
            self._generation_authority(contract, authorization, now)
            if contract.retrieval is not None and self._prior_reference(tx, run_id) is None:
                raise ValueError("Authoritative prior linkage required before generation")
            readiness = self._readiness(contract, readiness, now)
            row = tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") WHERE r.run_id=$id "
                "OPTIONAL MATCH (r)-[:HAS_INTENT]->(i:ArenaExecutionIntent) "
                "RETURN r.admitted_at AS admitted_at, count(i) AS intents",
                **self.scope,
                id=run_id,
            ).single()
            b = contract.budget
            if (
                row["intents"]
                or row["admitted_at"] is None
                or now < row["admitted_at"]
                or now + reservation.runtime_allowance_seconds > row["admitted_at"] + b.total_deadline_seconds
                or now >= row["admitted_at"] + b.total_deadline_seconds
                or not 0 < reservation.model_calls <= b.max_model_calls
                or not 0 < reservation.model_tokens <= b.max_model_tokens
                or reservation.cost_ceiling_usd > b.max_cost_usd
                or not 0
                < reservation.runtime_allowance_seconds
                <= min(b.max_runtime_seconds, b.per_operation_timeout_seconds)
            ):
                raise ValueError("generation budget, deadline or active intent denied")
            tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") WHERE r.run_id=$run_id CREATE (r)-[:HAS_INTENT]->(i:ArenaExecutionIntent "
                + _SCOPE
                + ") CREATE (r)-[:HAS_DECISION]->(d:ArenaWorkflowDecision "
                + _SCOPE
                + ") "
                "CREATE (d)-[:RESERVES]->(i) "
                "SET i.intent_id=$id, i.run_id=$run_id, i.payload=$payload, i.status='reserved', "
                "i.reservation_json=$reservation, i.authorization_json=$authorization, i.readiness_json=$readiness, "
                "d.decision_id=$decision, d.intent_id=$id, d.payload=$payload, "
                "d.run_id=$run_id, d.record_kind='generation_reservation', d.membership_codec=1, "
                "r.state='running', r.phase='generation'",
                **self.scope,
                run_id=run_id,
                id=intent_id,
                payload=payload,
                decision=decision_id,
                reservation=reservation.model_dump_json(),
                authorization=authorization.model_dump_json(),
                readiness=readiness.model_dump_json(),
            ).consume()
            self._event(tx, run_id, "GenerationReserved", decision_id)
        return intent_id

    def _owner(self, tx, owner_id, owner_epoch):
        if type(owner_epoch) is not int or owner_epoch < 1:
            raise ValueError("positive owner epoch required")
        row = tx.run(
            _CONTROL + "RETURN c.owner_id AS owner, c.owner_epoch AS epoch, c.owner_dirty AS dirty",
            **self.scope,
        ).single()
        if row["owner"] != owner_id or row["epoch"] != owner_epoch or row["dirty"] is not True:
            raise ValueError("stale or unknown owner")

    def _intent(self, tx, intent_id):
        rows = list(
            tx.run(
                "MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ") WHERE i.intent_id=$id RETURN properties(i) AS intent LIMIT 2",
                **self.scope,
                id=intent_id,
            )
        )
        if len(rows) != 1:
            raise ValueError("unknown or ambiguous scoped intent")
        return rows[0]["intent"]

    def claim_intent(self, intent_id, owner_id, owner_epoch, *, resume_operation_id=None):
        """Claim one stable attempt; replay unreleased ownership only, never retry.

        Local owner lease is a composition prerequisite. Neither this metadata nor
        a successful claim permits worker execution; only a fresh release winner can.
        """
        validate_operation_id(intent_id)
        validate_operation_id(owner_id)
        with self._transaction() as tx:
            self._lock(tx)
            self._owner(tx, owner_id, owner_epoch)
            intent = self._intent(tx, intent_id)
            run = self._run(tx, "run_id", intent["run_id"])
            if resume_operation_id is not None:
                self._resume_claim_guard(tx, resume_operation_id, run.run_id, intent_id, "generation")
            if run.state != "running" or intent["status"] not in (
                "reserved",
                "claimed",
                "registered",
            ):
                raise ValueError("intent is not claimable")
            if "fence_json" in intent:
                fence = AttemptFence.model_validate_json(intent["fence_json"])
                if fence.owner_id != owner_id or fence.owner_epoch != owner_epoch:
                    raise ValueError("attempt belongs to another owner")
                return fence
            fence = AttemptFence(
                run_id=run.run_id,
                intent_id=intent_id,
                attempt_id=hashlib.sha256((intent_id + ":attempt:1").encode()).hexdigest(),
                generation=1,
                owner_id=owner_id,
                owner_epoch=owner_epoch,
            )
            tx.run(
                "MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ") WHERE i.intent_id=$id CREATE (i)-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt "
                + _SCOPE
                + ") "
                "SET i.fence_json=$fence, i.status='claimed', a.fence_json=$fence, "
                "a.attempt_id=$attempt, a.status='claimed'",
                **self.scope,
                id=intent_id,
                fence=fence.model_dump_json(),
                attempt=fence.attempt_id,
            ).consume()
            self._event(tx, run.run_id, "IntentClaimed", fence.attempt_id)
        return fence

    def _fenced_intent(self, tx, fence):
        self._owner(tx, fence.owner_id, fence.owner_epoch)
        return self._retained_intent(tx, fence)

    def _retained_intent(self, tx, fence):
        intent = self._intent(tx, fence.intent_id)
        if intent.get("fence_json") != fence.model_dump_json() or intent["run_id"] != fence.run_id:
            raise ValueError("stale attempt fence")
        return intent

    def register_worker(self, fence, registration):
        """Retain exact verified-local registration; identical replay is read-only.

        Database checks binding only, never OS liveness/ownership. Worker execution
        remains prohibited until release; conflicting identity is never overwritten.
        """
        fence = AttemptFence.model_validate_json(fence.model_dump_json())
        registration = WorkerRegistration.model_validate_json(registration.model_dump_json())
        if registration.fence != fence:
            raise ValueError("registration fence mismatch")
        with self._transaction() as tx:
            self._lock(tx)
            intent = self._fenced_intent(tx, fence)
            if "registration_json" in intent:
                if intent["registration_json"] != registration.model_dump_json():
                    raise ValueError("conflicting registration")
                return registration
            if intent["status"] != "claimed" or self._run(tx, "run_id", fence.run_id).state != "running":
                raise ValueError("attempt not registerable")
            tx.run(
                "MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ")-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
                "WHERE i.intent_id=$id AND a.attempt_id=$attempt "
                "SET i.registration_json=$registration, a.registration_json=$registration, "
                "i.status='registered', a.status='registered'",
                **self.scope,
                id=fence.intent_id,
                attempt=fence.attempt_id,
                registration=registration.model_dump_json(),
            ).consume()
            self._event(tx, fence.run_id, "WorkerRegistered", registration.registration_id)
        return registration

    def release_attempt(self, fence, registration_id, authorization, *, readiness):
        """Return True only for the fresh registered-to-released CAS winner.

        Required readiness binds the whole frozen profile set. Trusted composition
        must supply current private authorization, verified registration and held
        local leases, and serialize local cancellation with its worker send. No
        workers, probes or provider calls run inside this transaction. False replay
        and OutcomeUnknown confer no send authority. Acceptance, refunds and owner
        takeover remain unsupported.
        """
        fence = AttemptFence.model_validate_json(fence.model_dump_json())
        validate_operation_id(registration_id)
        with self._transaction() as tx:
            self._lock(tx)
            intent = self._fenced_intent(tx, fence)
            run = self._run(tx, "run_id", fence.run_id)
            if (
                intent["status"] in ("released", "reconciliation_required", "produced", "cancelled")
                or "cleanup_json" in intent
                or run.state != "running"
            ):
                return False
            if intent["status"] != "registered" or "registration_json" not in intent:
                raise ValueError("exact registration required")
            registration = WorkerRegistration.model_validate_json(intent["registration_json"])
            if registration.registration_id != registration_id or registration.fence != fence:
                raise ValueError("registration mismatch")
            contract = parse_contract(run.contract_json)
            now = self._now()
            self._generation_authority(contract, authorization, now)
            original = AuthorizationSnapshot.model_validate_json(intent["authorization_json"])
            if authorization.principal != original.principal:
                raise ValueError("authorization principal changed")
            readiness = self._readiness(contract, readiness, now)
            admitted_at = tx.run(
                "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r.run_id=$id RETURN r.admitted_at AS at",
                **self.scope,
                id=fence.run_id,
            ).single()["at"]
            reservation = GenerationReservation.model_validate_json(intent["reservation_json"])
            if (
                admitted_at is None
                or now < admitted_at
                or now + reservation.runtime_allowance_seconds > admitted_at + contract.budget.total_deadline_seconds
                or now >= admitted_at + contract.budget.total_deadline_seconds
            ):
                raise ValueError("workflow deadline exhausted")
            rows = list(
                tx.run(
                    "MATCH (i:ArenaExecutionIntent "
                    + _SCOPE
                    + ")-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
                    "WHERE i.intent_id=$id AND a.attempt_id=$attempt "
                    "AND i.status='registered' AND a.status='registered' "
                    "SET i.status='released', a.status='released', a.released_at=$now, "
                    "a.release_authorization_json=$auth, a.readiness_json=$ready RETURN a.attempt_id AS id",
                    **self.scope,
                    id=fence.intent_id,
                    attempt=fence.attempt_id,
                    now=now,
                    auth=authorization.model_dump_json(),
                    ready=readiness.model_dump_json(),
                )
            )
            if len(rows) != 1:
                raise ValueError("attempt release CAS failed")
            self._event(tx, fence.run_id, "AttemptReleased", fence.attempt_id)
        return True

    def _attempt(self, tx, fence):
        self._owner(tx, fence.owner_id, fence.owner_epoch)
        return self._retained_attempt(tx, fence)

    def _retained_attempt(self, tx, fence):
        intent = self._retained_intent(tx, fence)
        rows = list(
            tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ")-[:HAS_INTENT]->(i:ArenaExecutionIntent "
                + _SCOPE
                + ")-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt "
                + _SCOPE
                + ") "
                "WHERE r.run_id=$run AND i.intent_id=$id AND a.attempt_id=$attempt "
                "RETURN properties(a) AS attempt LIMIT 2",
                **self.scope,
                run=fence.run_id,
                id=fence.intent_id,
                attempt=fence.attempt_id,
            )
        )
        if len(rows) != 1 or rows[0]["attempt"].get("fence_json") != fence.model_dump_json():
            raise ValueError("exact unambiguous attempt required")
        return intent, rows[0]["attempt"]

    def pending_generation(self, run_id):
        """Return the sole never-claimed reservation, not permission to resend."""
        with self._transaction() as tx:
            self._lock(tx)
            run = self._run(tx, "run_id", run_id)
            rows = list(
                tx.run(
                    "MATCH (i:ArenaExecutionIntent "
                    + _SCOPE
                    + ") WHERE i.run_id=$run "
                    "OPTIONAL MATCH (i)-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
                    "RETURN properties(i) AS intent, a IS NOT NULL AS attempted LIMIT 2",
                    **self.scope,
                    run=run_id,
                )
            )
            if run.state == "pending" and not rows:
                return dict(intent_id=None, reservation=None)
            if len(rows) != 1 or rows[0]["attempted"]:
                return None
            intent = rows[0]["intent"]
            if (
                (run.state, run.phase) != ("running", "generation")
                or intent.get("status") != "reserved"
                or intent.get("fence_json")
            ):
                return None
            return dict(
                intent_id=intent["intent_id"],
                reservation=GenerationReservation.model_validate_json(intent["reservation_json"]),
            )

    def get_generation_attempt(self, run_id):
        """Read the sole retained generation attempt for an exact scoped run.

        This initial-generation-only lookup reads at most two paths and rejects
        ambiguity instead of choosing a latest intent/attempt. None means no
        retained attempt, NOT no process or permission to execute/retry. Service
        composition must authorize reads; this lookup grants no mutation authority.
        """
        validate_operation_id(run_id)
        with self._transaction() as tx:
            self._lock(tx)
            rows = list(
                tx.run(
                    "MATCH (r:ArenaWorkflowRun "
                    + _SCOPE
                    + ")-[:HAS_INTENT]->(i:ArenaExecutionIntent) "
                    "WHERE r.run_id=$run OPTIONAL MATCH (i)-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
                    "RETURN i.intent_id AS intent, a IS NOT NULL AS present, a.fence_json AS fence LIMIT 2",
                    **self.scope,
                    run=run_id,
                )
            )
            if len(rows) > 1:
                raise ValueError("ambiguous generation recovery")
            if not rows or not rows[0]["present"]:
                return None
            if rows[0]["fence"] is None:
                raise ValueError("missing retained attempt fence")
            fence = AttemptFence.model_validate_json(rows[0]["fence"])
            if fence.run_id != run_id or fence.intent_id != rows[0]["intent"]:
                raise ValueError("generation recovery binding mismatch")
            return self._attempt_view(tx, fence)

    def get_admitted_at(self, run_id):
        """Read the original deadline anchor without inventing a generation attempt."""
        validate_operation_id(run_id)
        with self._transaction() as tx:
            row = tx.run(
                "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r.run_id=$id RETURN r.admitted_at AS at",
                **self.scope,
                id=run_id,
            ).single(strict=True)
            value = row["at"]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("Invalid retained admission time")
            return value

    def get_attempt(self, fence):
        """Read exact retained bindings; this confers no execution authority."""
        fence = AttemptFence.model_validate_json(fence.model_dump_json())
        with self._transaction() as tx:
            self._lock(tx)
            return self._attempt_view(tx, fence)

    def _attempt_view(self, tx, fence):
        intent, attempt = self._retained_attempt(tx, fence)
        run = self._run(tx, "run_id", fence.run_id)
        admitted_at = tx.run(
            "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r.run_id=$id RETURN r.admitted_at AS at",
            **self.scope,
            id=fence.run_id,
        ).single()["at"]
        return AttemptView(
            fence=fence,
            contract_json=run.contract_json,
            registration=(
                WorkerRegistration.model_validate_json(attempt["registration_json"])
                if "registration_json" in attempt
                else None
            ),
            authorization=AuthorizationSnapshot.model_validate_json(intent["authorization_json"]),
            reservation=GenerationReservation.model_validate_json(intent["reservation_json"]),
            admitted_at=admitted_at,
            released_at=attempt.get("released_at"),
            released="released_at" in attempt,
            status=attempt["status"],
            reconciliation_reason=attempt.get("reconciliation_reason"),
            receipt=(
                GenerationReceipt.model_validate_json(attempt["receipt_json"]) if "receipt_json" in attempt else None
            ),
            cleanup=(
                CleanupEvidence.model_validate_json(attempt["cleanup_json"]) if "cleanup_json" in attempt else None
            ),
        )

    def mark_reconciliation_required(self, fence, reason):
        """Retain a released unknown outcome without reopening execution or usage.

        No unreleased attempt can enter this path. Exact duplicate facts are
        observations even after resolution; conflicting reasons never overwrite.
        Owner cleanup and byte-verified receipt adoption remain separate gates.
        """
        if type(reason) is not ReconciliationReason:
            raise ValueError("typed reconciliation reason required")
        fence = AttemptFence.model_validate_json(fence.model_dump_json())
        with self._transaction() as tx:
            self._lock(tx)
            _, attempt = self._attempt(tx, fence)
            prior = attempt.get("reconciliation_reason")
            if prior is not None:
                if prior != reason.value:
                    raise ValueError("conflicting reconciliation reason")
                return False
            run = self._run(tx, "run_id", fence.run_id)
            if (
                "released_at" not in attempt
                or (reason is ReconciliationReason.RELEASED_WITHOUT_RECEIPT and "receipt_json" in attempt)
                or ("receipt_json" in attempt and "cleanup_json" in attempt)
                or run.phase != "generation"
                or run.state not in ("running", "cancel_requested", "cancelled")
            ):
                raise ValueError("released unresolved generation required")
            cancelled = run.state in ("cancel_requested", "cancelled")
            tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ")-[:HAS_INTENT]->(i:ArenaExecutionIntent) "
                "-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
                "WHERE r.run_id=$run AND i.intent_id=$id AND a.attempt_id=$attempt "
                "SET a.reconciliation_reason=$reason, a.status=$status, i.status=$status, r.state=$state",
                **self.scope,
                run=fence.run_id,
                id=fence.intent_id,
                attempt=fence.attempt_id,
                reason=reason.value,
                status=("cancelled" if run.state == "cancelled" else "reconciliation_required"),
                state=run.state if cancelled else "reconciliation_required",
            ).consume()
            self._event(tx, fence.run_id, "ReconciliationRequired", fence.attempt_id)
        return True

    def _complete_generation(self, tx, fence, attempt, run):
        # Consumption reconciliation is deferred: retain the entire reservation and dirty owner.
        if "cleanup_json" not in attempt:
            return
        if run.state in ("cancel_requested", "cancelled"):
            state, status = "cancelled", "cancelled"
            phase = run.phase
        elif "receipt_json" in attempt:
            state, status = "running", "produced"
            phase = "validation"
        else:
            return
        tx.run(
            "MATCH (r:ArenaWorkflowRun "
            + _SCOPE
            + ")-[:HAS_INTENT]->(i:ArenaExecutionIntent) "
            "-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) WHERE r.run_id=$run AND i.intent_id=$id "
            "AND a.attempt_id=$attempt SET r.state=$state, r.phase=$phase, i.status=$status, a.status=$status",
            **self.scope,
            run=fence.run_id,
            id=fence.intent_id,
            attempt=fence.attempt_id,
            state=state,
            phase=phase,
            status=status,
        ).consume()

    def commit_generation_receipt(self, fence, receipt):
        """Adopt upstream byte-verified output only; never validate a scene or refund usage.

        Trusted service must invoke the concrete artifact verifier outside this
        transaction. This low-level store accepts no caller 'verified' boolean.
        Cancellation retains receipts diagnostically, including after cleanup.
        """
        if type(receipt) is not GenerationReceipt:
            raise ValueError("typed generation receipt required")
        receipt = GenerationReceipt.model_validate_json(receipt.model_dump_json())
        fence = AttemptFence.model_validate_json(fence.model_dump_json())
        if receipt.fence != fence:
            raise ValueError("receipt fence mismatch")
        with self._transaction() as tx:
            self._lock(tx)
            intent, attempt = self._attempt(tx, fence)
            run = self._run(tx, "run_id", fence.run_id)
            contract = parse_contract(run.contract_json)
            if (
                "released_at" not in attempt
                or attempt.get("registration_json") != receipt.registration.model_dump_json()
                or receipt.contract_digest != contract_digest(contract)
                or receipt.generation_profile != contract.execution.generation_model
            ):
                raise ValueError("receipt retained binding mismatch")
            payload = receipt.model_dump_json()
            if "receipt_json" in attempt:
                if attempt["receipt_json"] != payload:
                    raise ValueError("conflicting generation receipt")
                return False
            if run.state not in (
                "running",
                "reconciliation_required",
                "cancel_requested",
                "cancelled",
            ):
                raise ValueError("inactive generation")
            tx.run(
                "MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ")-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
                "WHERE i.intent_id=$id AND a.attempt_id=$attempt SET a.receipt_json=$receipt, "
                "a.receipt_disposition=$disposition, a.usage_disposition='fully_reserved_consumption_deferred'",
                **self.scope,
                id=fence.intent_id,
                attempt=fence.attempt_id,
                receipt=payload,
                disposition=("diagnostic" if run.state in ("cancel_requested", "cancelled") else "produced"),
            ).consume()
            attempt["receipt_json"] = payload
            self._complete_generation(tx, fence, attempt, run)
            self._event(tx, fence.run_id, "GenerationReceiptRetained", fence.attempt_id)
        return True

    def acknowledge_cleanup(self, fence, evidence):
        """Retain trusted owner stop evidence for this exact registration, never clear owner.

        Composition must verify actual process identity and stop outside Neo4j;
        database binding alone cannot establish OS cleanup or remote cancellation.
        """
        if type(evidence) is not CleanupEvidence:
            raise ValueError("typed owner cleanup evidence required")
        evidence = CleanupEvidence.model_validate_json(evidence.model_dump_json())
        fence = AttemptFence.model_validate_json(fence.model_dump_json())
        if evidence.registration.fence != fence:
            raise ValueError("cleanup fence mismatch")
        with self._transaction() as tx:
            self._lock(tx)
            intent, attempt = self._attempt(tx, fence)
            if attempt.get("registration_json") != evidence.registration.model_dump_json():
                raise ValueError("cleanup registration mismatch")
            payload = evidence.model_dump_json()
            if "cleanup_json" in attempt:
                if attempt["cleanup_json"] != payload:
                    raise ValueError("conflicting cleanup evidence")
                return False
            run = self._run(tx, "run_id", fence.run_id)
            tx.run(
                "MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ")-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
                "WHERE i.intent_id=$id AND a.attempt_id=$attempt SET a.cleanup_json=$cleanup, i.cleanup_json=$cleanup",
                **self.scope,
                id=fence.intent_id,
                attempt=fence.attempt_id,
                cleanup=payload,
            ).consume()
            attempt["cleanup_json"] = payload
            self._complete_generation(tx, fence, attempt, run)
            self._event(tx, fence.run_id, "AttemptCleanupAcknowledged", fence.attempt_id)
        return True

    def request_cancel(self, run_id, expected_version):
        """Fence release; terminal only if never dispatched or exact cleanup retained.

        The service authenticates cancellation; owner-local stopping/leases remain
        mandatory even during database outages. Cancellation after release cannot
        undo remote effects. Exact request replay returns the retained run.
        """
        validate_operation_id(run_id)
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("positive expected version required")
        with self._transaction() as tx:
            self._lock(tx)
            result = self._request_cancel(tx, run_id, expected_version)
        return result

    def _request_cancel(self, tx, run_id, expected_version, *, command_operation_id=None):
        run = self._run(tx, "run_id", run_id)
        if run is None:
            raise ValueError("unknown run")
        row = tx.run(
            "MATCH (r:ArenaWorkflowRun "
            + _SCOPE
            + ") WHERE r.run_id=$id "
            "OPTIONAL MATCH (r)-[:HAS_INTENT]->(i:ArenaExecutionIntent) "
            "OPTIONAL MATCH (i)-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
            "RETURN r.cancel_from_version AS version, count(i) AS intents, count(a) AS attempts",
            **self.scope,
            id=run_id,
        ).single()
        if run.state in ("cancel_requested", "cancelled") and row["version"] == expected_version:
            return run
        if run.version != expected_version or run.state not in (
            "pending",
            "running",
            "reconciliation_required",
        ):
            raise ValueError("stale cancellation version or inactive run")
        tx.run(
            "MATCH (r:ArenaWorkflowRun "
            + _SCOPE
            + ") WHERE r.run_id=$id SET r.state=$state, r.cancel_from_version=$version",
            **self.scope,
            id=run_id,
            version=expected_version,
            state=(
                "cancelled"
                if run.state == "pending" and row["intents"] == 0 and row["attempts"] == 0
                else "cancel_requested"
            ),
        ).consume()
        tx.run(
            "MATCH (r:ArenaWorkflowRun "
            + _SCOPE
            + ")-[:HAS_INTENT]->(:ArenaExecutionIntent)-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
            "WHERE r.run_id=$id AND a.receipt_json IS NOT NULL SET a.receipt_disposition='diagnostic'",
            **self.scope,
            id=run_id,
        ).consume()
        cleaned = list(
            tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ")-[:HAS_INTENT]->(i:ArenaExecutionIntent) "
                "WHERE r.run_id=$id AND i.cleanup_json IS NOT NULL RETURN i.fence_json AS fence",
                **self.scope,
                id=run_id,
            )
        )
        for row in cleaned:
            fence = AttemptFence.model_validate_json(row["fence"])
            _, attempt = self._retained_attempt(tx, fence)
            self._complete_generation(tx, fence, attempt, self._run(tx, "run_id", run_id))
        # Generation cleanup cannot certify a subsequently released scene effect.
        from .scene_loop import SceneIntent

        scene_rows = tx.run(
            "MATCH (i:ArenaExecutionIntent "
            + _SCOPE
            + ") WHERE i.run_id=$id AND i.kind='scene' RETURN i.scene_json AS scene",
            **self.scope,
            id=run_id,
        )
        scenes = [SceneIntent.model_validate_json(row["scene"]) for row in scene_rows]
        unresolved_scene = any(
            (i.worker_fence is not None and i.worker_cleanup is None)
            or (i.worker_fence is None and i.status in ("released", "reconciliation_required"))
            for i in scenes
        )
        if unresolved_scene:
            tx.run(
                "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r.run_id=$id SET r.state='cancel_requested'",
                **self.scope,
                id=run_id,
            ).consume()
        self._event(tx, run_id, "CancellationRequested", run_id, command_operation_id=command_operation_id)
        result = self._run(tx, "run_id", run_id)
        return result

    def _resume_receipt(self, tx, operation_id):
        rows = list(
            tx.run(
                "MATCH (c:ArenaResumeReceipt "
                + _SCOPE
                + ") "
                "WHERE c.kind=$kind AND c.operation_id=$key "
                "RETURN CASE WHEN size(toStringOrNull(c.receipt_json))<=16384 "
                "THEN c.receipt_json ELSE null END AS receipt LIMIT 2",
                **self.scope,
                kind="RESUME",
                key=operation_id,
            )
        )
        if not rows:
            return None
        try:
            if len(rows) != 1 or type(rows[0]["receipt"]) is not str:
                raise ValueError
            raw = rows[0]["receipt"]
            if len(raw.encode("utf-8")) > COMMAND_BYTES:
                raise ValueError
            value = ResumeReceipt.model_validate_json(raw)
            if (
                command_json(value.model_dump(mode="json")) != raw
                or value.operation_id != operation_id
                or value.scope.model_dump() != dict(database=self.database, **self.scope)
            ):
                raise ValueError
            return value
        except (ValueError, TypeError, KeyError):
            raise CorruptResumeReceipt() from None

    def get_resume_receipt(self, operation_id):
        """Exact MATCH-only immutable receipt lookup; no stop or control lock."""
        validate_operation_id(operation_id)
        with self._transaction(fetch_size=2) as tx:
            result = self._resume_receipt(tx, operation_id)
        return result

    def _resume_json(self, raw, model):
        """Decode selected metadata locally; never translate driver failures."""
        try:
            return self._cleanup_json(raw, model)
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptResumeSelection() from None

    def _resume_preview(self, tx, run_id, *, retained_run=None, retained_attempts=None):
        from types import SimpleNamespace

        run = retained_run if retained_run is not None else self._run(tx, "run_id", run_id)
        if run is not None and run.phase in ("generation", "scene"):
            try:
                parse_contract(run.contract_json)
            except (ValueError, TypeError, KeyError, RecursionError):
                raise CorruptResumeSelection() from None
        if run is not None and run.phase == "scene":
            # Read only the selected ownership record, not the legacy full scene
            # snapshot. Missing writer-emitted nulls cannot prove never claimed.
            rows = list(
                tx.run(
                    "MATCH (r:ArenaWorkflowRun "
                    + _SCOPE
                    + ") WHERE r.run_id=$run OPTIONAL MATCH (i:ArenaExecutionIntent "
                    + _SCOPE
                    + ") WHERE i.intent_id=r.scene_intent "
                    "RETURN CASE WHEN size(toStringOrNull(r.scene_profile))<=65536 THEN r.scene_profile "
                    "ELSE [false] END AS profile, "
                    "CASE WHEN size(toStringOrNull(i.scene_json))<=65536 THEN i.scene_json "
                    "ELSE [false] END AS scene, "
                    "CASE WHEN size(toStringOrNull(i.intent_id))<=128 THEN i.intent_id "
                    "WHEN i.intent_id IS NULL THEN null ELSE [false] END AS id, "
                    "CASE WHEN size(toStringOrNull(i.run_id))<=128 THEN i.run_id "
                    "WHEN i.run_id IS NULL THEN null ELSE [false] END AS run, "
                    "CASE WHEN size(toStringOrNull(i.status))<=64 THEN i.status "
                    "WHEN i.status IS NULL THEN null ELSE [false] END AS status LIMIT 2",
                    **self.scope,
                    run=run_id,
                )
            )
            if len(rows) != 1:
                raise CorruptResumeSelection()
            row = rows[0]
            from .scene_loop import SceneIntent, ScenePortProfile

            scene = None
            if row["id"] is not None:
                scene = SimpleNamespace(
                    intent=self._resume_json(row["scene"], SceneIntent),
                    profile=self._resume_json(row["profile"], ScenePortProfile),
                )
                raw = json.loads(row["scene"])
                fields = ("worker_fence", "worker_registration", "worker_cleanup", "released_at")
                if type(raw) is not dict or not set(fields) <= raw.keys():
                    raise CorruptResumeSelection()
                if (
                    scene.profile.owned_worker
                    and raw["worker_fence"] is None
                    and any(raw[k] is not None for k in fields[1:])
                ):
                    raise CorruptResumeSelection()
                if row["run"] != run_id or row["id"] != scene.intent.intent_id or row["status"] != scene.intent.status:
                    raise CorruptResumeSelection()
            selected = None
            if (
                run.state == "running"
                and scene is not None
                and scene.intent is not None
                and scene.intent.status == "reserved"
                and scene.intent.worker_fence is None
                and scene.profile.owned_worker
            ):
                selected = ResumeSelection(
                    run_id=run_id,
                    version=run.version,
                    contract_digest=command_digest(run.contract_json),
                    branch="scene",
                    intent_id=scene.intent.intent_id,
                )
            return SimpleNamespace(run=run, selection=selected)
        rows = list(
            tx.run(
                "MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ") WHERE i.run_id=$run "
                "OPTIONAL MATCH (i)-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
                "RETURN CASE WHEN size(toStringOrNull(i.intent_id))<=128 THEN i.intent_id ELSE [false] END AS id, "
                "CASE WHEN size(toStringOrNull(i.status))<=64 THEN i.status ELSE [false] END AS status, "
                "CASE WHEN size(toStringOrNull(i.fence_json))<=65536 THEN i.fence_json "
                "WHEN i.fence_json IS NULL THEN null ELSE [false] END AS fence, "
                "i.registration_json IS NOT NULL OR i.cleanup_json IS NOT NULL "
                "OR i.released_at IS NOT NULL AS ownership, "
                "a IS NOT NULL AS attempted LIMIT 2",
                **self.scope,
                run=run_id,
            )
        )
        selection = None
        if len(rows) == 1 and rows[0]["fence"] is None and rows[0]["ownership"]:
            raise CorruptResumeSelection()
        if (
            run is not None
            and (run.state, run.phase) == ("running", "generation")
            and len(rows) == 1
            and rows[0]["status"] == "reserved"
            and rows[0]["fence"] is None
            and not rows[0]["attempted"]
        ):
            selection = ResumeSelection(
                run_id=run_id,
                version=run.version,
                contract_digest=command_digest(run.contract_json),
                branch="generation",
                intent_id=rows[0]["id"],
            )
        elif (
            run is not None
            and run.phase == "generation"
            and run.state in ("running", "reconciliation_required")
            and len(rows) == 1
            and rows[0]["fence"] is not None
            and rows[0]["attempted"]
        ):
            fence = self._resume_json(rows[0]["fence"], AttemptFence)
            if fence.run_id != run_id or fence.intent_id != rows[0]["id"]:
                raise CorruptResumeSelection()
            if retained_attempts is None:
                _, attempt = self._retained_attempt(tx, fence)
            else:
                attempt = retained_attempts[fence.attempt_id]
            if attempt.get("registration_json") is not None:
                registration = self._resume_json(attempt["registration_json"], WorkerRegistration)
                if registration.fence != fence:
                    raise CorruptResumeSelection()
                selection = ResumeSelection(
                    run_id=run_id,
                    version=run.version,
                    contract_digest=command_digest(run.contract_json),
                    branch="reconciliation",
                    intent_id=fence.intent_id,
                    fence=fence,
                )
        return SimpleNamespace(run=run, selection=selection)

    def preview_resume(self, run_id):
        """Read bounded retained selection; never read private configuration or bytes."""
        validate_operation_id(run_id)
        with self._transaction(fetch_size=2) as tx:
            result = self._resume_preview(tx, run_id)
        return result

    def admit_resume(self, operation_id, payload, *, selection, eligibility, protect):
        """Internal admission only; callbacks never run under the database lock.

        Failure after commit, including response screening or cleanup, confers no
        fresh result. Recover by read-authorized lookup, never automatic execution.
        """
        from .scene_evidence_artifacts import _protected

        validate_operation_id(operation_id)
        payload = ResumePayload.model_validate(payload)
        if not callable(protect):
            raise ValueError("public protection callback required")
        _protected(
            dict(operation_id=operation_id, payload=payload.model_dump(mode="json")), protect, max_bytes=COMMAND_BYTES
        )
        with self._transaction(fetch_size=2) as tx:
            result = self._admit_resume(tx, operation_id, payload, selection, eligibility)
        _protected(result.model_dump(mode="json"), protect, max_bytes=COMMAND_BYTES)
        return result

    def _admit_resume(self, tx, operation_id, payload, selection, eligibility):
        raw_payload = command_json(payload.model_dump(mode="json"))
        self._lock(tx)
        retained = self._resume_receipt(tx, operation_id)
        if retained is not None:
            if retained.payload_json != raw_payload:
                raise CommandConflict("Resume key binds different input")
            return ResumeAdmission(fresh=False, receipt=retained)
        preview = self._resume_preview(tx, payload.runId)
        reason = None
        if preview.run is None:
            reason = "target_not_found"
        elif preview.run.version != payload.expectedVersion:
            reason = "stale_version"
        elif preview.run.state not in ("pending", "running", "reconciliation_required"):
            reason = "inactive_run"
        elif preview.selection is None:
            reason = "unsafe_scene" if preview.run.phase == "scene" else "unsupported_branch"
        elif preview.selection != selection:
            reason = "selection_changed"
        elif preview.selection.branch == "reconciliation":
            if payload.renewAuthorization:
                reason = "renewal_not_applicable"
        elif eligibility not in (("bind", "renew") if payload.renewAuthorization else ("current",)):
            reason = "private_eligibility_not_ready"
        selection = preview.selection
        after = preview.run
        rows = []
        if reason is None:
            self._event(
                tx,
                payload.runId,
                "ResumeAdmitted",
                selection.intent_id,
                command_operation_id=operation_id,
                command_kind="RESUME",
            )
            after = self._run(tx, "run_id", payload.runId)
            rows = list(
                tx.run(
                    "MATCH (e:ArenaWorkflowEvent "
                    + _SCOPE
                    + ") WHERE e.sequence=$sequence AND e.run_id=$run "
                    "AND e.command_kind='RESUME' AND e.command_operation_id=$key "
                    "AND e.kind='ResumeAdmitted' AND e.source_id=$source "
                    "RETURN e {.sequence, .kind, .source_id} AS event LIMIT 2",
                    **self.scope,
                    sequence=after.event_cursor,
                    run=payload.runId,
                    key=operation_id,
                    source=selection.intent_id,
                )
            )
            if len(rows) != 1:
                raise CorruptResumeReceipt()
        result = make_resume_receipt(
            scope=dict(database=self.database, **self.scope),
            operation_id=operation_id,
            run_id=payload.runId,
            payload_json=raw_payload,
            payload_digest=command_digest(raw_payload),
            before_version=None if preview.run is None else preview.run.version,
            after_version=None if after is None else after.version,
            selection=None if selection is None else selection.model_dump(mode="json"),
            contract_digest=None if preview.run is None else command_digest(preview.run.contract_json),
            disposition=(
                "refused"
                if reason is not None
                else "reconciliation_admitted" if selection.branch == "reconciliation" else "continuation_admitted"
            ),
            reason=reason,
            authorization_action=(
                None
                if reason is not None or selection.branch == "reconciliation"
                else "none" if eligibility == "current" else eligibility
            ),
            events=[dict(r["event"]) for r in rows],
        )
        raw = command_json(result.model_dump(mode="json"))
        if len(raw.encode("utf-8")) > COMMAND_BYTES:
            raise ValueError("Resume receipt byte bound exceeded")
        tx.run(
            "CREATE (c:ArenaResumeReceipt "
            + _SCOPE
            + ") SET c.kind='RESUME', c.operation_id=$key, c.receipt_json=$raw",
            **self.scope,
            key=operation_id,
            raw=raw,
        ).consume()
        if result.events:
            linked = tx.run(
                "MATCH (c:ArenaResumeReceipt "
                + _SCOPE
                + ") WHERE c.kind='RESUME' AND c.operation_id=$key MATCH (e:ArenaWorkflowEvent "
                + _SCOPE
                + ") WHERE e.sequence=$sequence AND e.run_id=$run "
                "AND e.command_kind='RESUME' AND e.command_operation_id=$key "
                "AND e.kind='ResumeAdmitted' AND e.source_id=$source "
                "CREATE (c)-[:CAUSED]->(e) RETURN count(e) AS count",
                **self.scope,
                key=operation_id,
                sequence=after.event_cursor,
                run=payload.runId,
                source=selection.intent_id,
            ).single(strict=True)
            if linked["count"] != 1:
                raise CorruptResumeReceipt()
        return ResumeAdmission(fresh=True, receipt=result)

    def _resume_claim_guard(self, tx, operation_id, run_id, intent_id, branch):
        """Validate the immutable admission under the very same claim write lock."""
        validate_operation_id(operation_id)
        receipt = self._resume_receipt(tx, operation_id)
        if (
            receipt is None
            or receipt.disposition != "continuation_admitted"
            or receipt.run_id != run_id
            or receipt.selection.branch != branch
            or receipt.selection.intent_id != intent_id
        ):
            raise ValueError("Resume claim selection mismatch")
        preview = self._resume_preview(tx, run_id)
        expected = receipt.selection.model_copy(update={"version": receipt.after_version})
        if preview.selection != expected or preview.run.version != receipt.after_version:
            raise ValueError("Resume claim selection changed")

    def _cancel_receipt(self, tx, operation_id):
        rows = list(
            tx.run(
                "MATCH (c:ArenaCancelReceipt "
                + _SCOPE
                + ") "
                "WHERE c.kind=$kind AND c.operation_id=$key "
                "RETURN CASE WHEN size(toStringOrNull(c.receipt_json))<=16384 "
                "THEN c.receipt_json ELSE null END AS receipt LIMIT 2",
                **self.scope,
                kind="CANCEL",
                key=operation_id,
            )
        )
        if not rows:
            return None
        try:
            if len(rows) != 1 or type(rows[0]["receipt"]) is not str:
                raise ValueError
            raw = rows[0]["receipt"]
            if len(raw.encode("utf-8")) > COMMAND_BYTES:
                raise ValueError
            value = CancelReceipt.model_validate_json(raw)
            if (
                command_json(value.model_dump(mode="json")) != raw
                or value.operation_id != operation_id
                or value.scope.model_dump() != dict(database=self.database, **self.scope)
            ):
                raise ValueError
            return value
        except (ValueError, TypeError, KeyError):
            raise CorruptCancelReceipt() from None

    def get_cancel_receipt(self, operation_id):
        """Exact MATCH-only immutable receipt lookup; no stop or control lock."""
        validate_operation_id(operation_id)
        with self._transaction(fetch_size=2) as tx:
            result = self._cancel_receipt(tx, operation_id)
        return result

    def cancel_command(self, operation_id, run_id, local_stop, *, protect):
        """Atomically bind exact CANCEL input, transition and immutable receipt."""
        from .scene_evidence_artifacts import _protected

        validate_operation_id(operation_id)
        validate_operation_id(run_id)
        if not callable(protect):
            raise ValueError("public protection callback required")
        local_stop = LocalStopObservation.model_validate_json(local_stop.model_dump_json())
        payload = command_json({"runId": run_id})
        _protected(dict(operation_id=operation_id, runId=run_id), protect, max_bytes=COMMAND_BYTES)
        with self._transaction(fetch_size=2) as tx:
            self._lock(tx)
            retained = self._cancel_receipt(tx, operation_id)
            if retained is not None:
                if retained.payload_json != payload or retained.payload_digest != command_digest(payload):
                    raise CommandConflict("Cancellation key binds different input")
                _protected(retained.model_dump(mode="json"), protect, max_bytes=COMMAND_BYTES)
                return retained
            before = self._run(tx, "run_id", run_id)
            after, reason = before, None
            if before is None:
                disposition, reason = "refused", "target_not_found"
            elif before.state in ("cancel_requested", "cancelled"):
                disposition = "already_requested" if before.state == "cancel_requested" else "already_cancelled"
            elif before.state not in ("pending", "running", "reconciliation_required"):
                disposition, reason = "refused", "inactive_run"
            else:
                disposition = "cancellation_requested"
                after = self._request_cancel(tx, run_id, before.version, command_operation_id=operation_id)
            rows = []
            if disposition == "cancellation_requested":
                rows = list(
                    tx.run(
                        "MATCH (e:ArenaWorkflowEvent "
                        + _SCOPE
                        + ") WHERE e.sequence=$sequence AND e.run_id=$run "
                        "AND e.command_kind='CANCEL' AND e.command_operation_id=$key "
                        "AND e.kind='CancellationRequested' AND e.source_id=$run "
                        "RETURN e {.sequence, .kind, .source_id} AS event LIMIT 2",
                        **self.scope,
                        sequence=after.event_cursor,
                        run=run_id,
                        key=operation_id,
                    )
                )
                if len(rows) != 1:
                    raise CorruptCancelReceipt()
            result = make_cancel_receipt(
                scope=dict(database=self.database, **self.scope),
                operation_id=operation_id,
                run_id=run_id,
                payload_json=payload,
                payload_digest=command_digest(payload),
                before_version=None if before is None else before.version,
                after_version=None if after is None else after.version,
                disposition=disposition,
                reason=reason,
                first_local_stop=local_stop.model_dump(mode="json"),
                events=[dict(row["event"]) for row in rows],
            )
            raw = _protected(result.model_dump(mode="json"), protect, max_bytes=COMMAND_BYTES).decode("utf-8")
            tx.run(
                "CREATE (c:ArenaCancelReceipt "
                + _SCOPE
                + ") SET c.kind='CANCEL', c.operation_id=$key, c.receipt_json=$raw",
                **self.scope,
                key=operation_id,
                raw=raw,
            ).consume()
            if result.events:
                linked = tx.run(
                    "MATCH (c:ArenaCancelReceipt "
                    + _SCOPE
                    + ") WHERE c.kind='CANCEL' AND c.operation_id=$key MATCH (e:ArenaWorkflowEvent "
                    + _SCOPE
                    + ") WHERE e.sequence=$sequence AND e.run_id=$run "
                    "AND e.command_kind='CANCEL' AND e.command_operation_id=$key "
                    "AND e.kind='CancellationRequested' AND e.source_id=$run "
                    "CREATE (c)-[:CAUSED]->(e) RETURN count(e) AS count",
                    **self.scope,
                    key=operation_id,
                    sequence=after.event_cursor,
                    run=run_id,
                ).single(strict=True)
                if linked["count"] != 1:
                    raise CorruptCancelReceipt()
        return result

    def _historical_node(self, tx, label, record_id):
        field = _HISTORY_FIELDS[label]
        try:
            validate_operation_id(record_id)
        except (ValueError, TypeError):
            raise CorruptSceneRecord("invalid retained scene identity") from None
        rows = list(
            tx.run(
                "MATCH (n:" + label + " " + _SCOPE + ") WHERE n." + field + "=$id RETURN " + _HISTORY_VIEW + " LIMIT 2",
                **self.scope,
                id=record_id,
            )
        )
        if len(rows) > 1:
            raise CorruptSceneRecord("ambiguous retained scene identity")
        return rows[0] if rows else None

    def _historical_link(self, tx, row, relation, label, *, incoming=False, required=True):
        assert relation in {
            "HAS_SCENE_RECORD",
            "HAS_DECISION",
            "HAS_SCENE_INTENT",
            "DERIVED_FROM",
            "ORIGINAL",
            "ASSESSES",
            "FOR_CANDIDATE",
        }
        pattern = "(root)<-[:" + relation + "]-(n)" if incoming else "(root)-[:" + relation + "]->(n)"
        rows = list(
            tx.run(
                "MATCH " + pattern + " WHERE elementId(root)=$key RETURN " + _HISTORY_VIEW + " LIMIT 2",
                key=row["key"],
            )
        )
        if not rows and not required:
            return None
        if len(rows) != 1:
            raise CorruptSceneRecord("missing or ambiguous retained scene relationship")
        target = rows[0]
        if label not in target["labels"] or any(target["node"].get(k) != v for k, v in self.scope.items()):
            raise CorruptSceneRecord("retained scene relationship scope or type mismatch")
        exact = self._historical_node(tx, label, target["node"].get(_HISTORY_FIELDS[label]))
        if exact is None or exact["key"] != target["key"]:
            raise CorruptSceneRecord("retained scene relationship identity mismatch")
        return target

    def _historical_owner(self, tx, row, relation="HAS_SCENE_RECORD"):
        owner = self._historical_link(tx, row, relation, "ArenaWorkflowRun", incoming=True)
        run_id = owner["node"]["run_id"]
        retained_run = row["node"].get("run_id")
        if retained_run != run_id and not (relation == "HAS_DECISION" and retained_run is None):
            raise CorruptSceneRecord("retained scene run mismatch")
        return owner

    @staticmethod
    def _historical_payload(row, model, field="payload"):
        from .scene_loop import CandidateRecord

        raw = row["node"].get(field)
        limit = HISTORICAL_CANDIDATE_BYTES if model is CandidateRecord else 2 * 1024 * 1024
        if type(raw) is not str or len(raw.encode("utf-8")) > limit:
            raise CorruptSceneRecord("invalid or excessive retained scene payload")
        try:
            return model.model_validate_json(raw)
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptSceneRecord("invalid retained scene payload") from None

    def _historical_candidate_value(self, tx, row, run_id):
        from .scene_loop import CandidateRecord, candidate_record

        candidate = self._historical_payload(row, CandidateRecord)
        owner = self._historical_owner(tx, row)
        if (
            candidate.candidate_id != row["node"]["record_id"]
            or candidate.run_id != run_id
            or owner["node"]["run_id"] != run_id
        ):
            raise CorruptSceneRecord("retained candidate identity or run mismatch")
        try:
            rebuilt = candidate_record(
                run_id,
                json.loads(candidate.scene_json),
                source_id=candidate.source_id,
                original_id=candidate.original_id,
                parent_id=candidate.parent_id,
            )
            if rebuilt != candidate:
                raise CorruptSceneRecord("retained candidate digest mismatch")
            return candidate
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptSceneRecord("invalid retained candidate") from None

    def _historical_candidate(self, tx, row):
        run_id = row["node"]["run_id"]
        candidate = self._historical_candidate_value(tx, row, run_id)
        parent = self._historical_link(tx, row, "DERIVED_FROM", "ArenaWorkflowCandidate", required=False)
        original = self._historical_link(tx, row, "ORIGINAL", "ArenaWorkflowCandidate", required=False)
        if candidate.parent_id is None:
            if candidate.original_id != candidate.candidate_id or parent is not None or original is not None:
                raise CorruptSceneRecord("retained original lineage mismatch")
        else:
            if parent is None or original is None:
                raise CorruptSceneRecord("missing retained candidate lineage")
            p = self._historical_candidate_value(tx, parent, run_id)
            o = self._historical_candidate_value(tx, original, run_id)
            if (
                p.candidate_id != candidate.parent_id
                or o.candidate_id != candidate.original_id
                or p.original_id != o.candidate_id
                or o.original_id != o.candidate_id
                or o.parent_id is not None
                or p.candidate_id == candidate.candidate_id
            ):
                raise CorruptSceneRecord("retained candidate lineage mismatch")
        try:
            return SceneCandidateView(scope=self._scene_read_scope(), run_id=run_id, candidate=candidate)
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptSceneRecord("invalid retained scene record") from None

    def _scene_read_scope(self):
        return SceneReadScope(database=self.database, **self.scope)

    def _historical_selection(self, tx, evidence_id, run_id, candidate_id):
        from .scene_loop import SceneDecision

        selected = list(
            tx.run(
                "MATCH (n:ArenaWorkflowDecision "
                + _SCOPE
                + ") WHERE n.evidence_id=$id RETURN "
                + _HISTORY_VIEW
                + " LIMIT 2",
                **self.scope,
                id=evidence_id,
            )
        )
        if len(selected) > 1:
            raise CorruptSceneRecord("ambiguous retained assessment selection")
        if not selected:
            return None
        row = selected[0]
        exact = self._historical_node(tx, "ArenaWorkflowDecision", row["node"]["decision_id"])
        owner = self._historical_owner(tx, row, "HAS_DECISION")
        decision = self._historical_payload(row, SceneDecision)
        if (
            exact is None
            or exact["key"] != row["key"]
            or owner["node"]["run_id"] != run_id
            or (candidate_id is not None and row["node"].get("candidate_id") != candidate_id)
            or (candidate_id is None and decision.assessment is not None)
        ):
            raise CorruptSceneRecord("retained evidence selection mismatch")
        return decision

    def _historical_evidence(self, tx, row):
        from .scene_loop import Observation, profile_digest

        owner = self._historical_owner(tx, row)
        run_id = owner["node"]["run_id"]
        observation = self._historical_payload(row, Observation)
        raw = owner["node"].get("contract_json")
        if type(raw) is not str:
            raise CorruptSceneRecord("missing retained scene contract")
        try:
            contract = parse_contract(raw)
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptSceneRecord("invalid retained scene contract") from None
        if observation.cohort.contract_digest != contract_digest(
            contract
        ) or observation.cohort.profile_digest != profile_digest(contract):
            raise CorruptSceneRecord("retained evidence contract mismatch")
        linked = self._historical_link(tx, row, "FOR_CANDIDATE", "ArenaWorkflowCandidate", required=False)
        candidate_id = None
        if linked is not None:
            candidate = self._historical_candidate(tx, linked).candidate
            if candidate.run_id != run_id:
                raise CorruptSceneRecord("retained evidence candidate run mismatch")
            candidate_id = candidate.candidate_id
        self._historical_selection(tx, row["node"]["record_id"], run_id, candidate_id)
        try:
            return SceneEvidenceView(
                scope=self._scene_read_scope(),
                run_id=run_id,
                evidence_id=row["node"]["record_id"],
                candidate_id=candidate_id,
                observation=observation,
            )
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptSceneRecord("invalid retained scene record") from None

    def _historical_assessment(self, tx, row):
        from .evidence import SceneEvidenceAssessment

        owner = self._historical_owner(tx, row)
        assessment = self._historical_payload(row, SceneEvidenceAssessment)
        evidence_row = self._historical_link(tx, row, "ASSESSES", "ArenaWorkflowEvidence")
        evidence = self._historical_evidence(tx, evidence_row)
        if evidence.run_id != owner["node"]["run_id"] or evidence.candidate_id is None:
            raise CorruptSceneRecord("retained assessment evidence mismatch")
        decision = self._historical_selection(tx, evidence.evidence_id, evidence.run_id, evidence.candidate_id)
        if decision is not None and decision.assessment != assessment:
            raise CorruptSceneRecord("retained assessment selection mismatch")
        try:
            return SceneAssessmentView(
                scope=self._scene_read_scope(),
                run_id=evidence.run_id,
                assessment_id=row["node"]["record_id"],
                evidence_id=evidence.evidence_id,
                candidate_id=evidence.candidate_id,
                assessment=assessment,
            )
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptSceneRecord("invalid retained scene record") from None

    def _historical_policy_trial(self, tx, run_id, candidate, decision, evidence_id):
        """Bind retained policy metadata to the exact producing cleaned intent."""
        from .scene_loop import SceneIntent, SceneResult, identity

        trial = decision.policy_trial
        row = self._historical_node(tx, "ArenaExecutionIntent", trial.intent_id)
        if row is None:
            raise CorruptSceneRecord("missing policy trial intent")
        intent = self._historical_payload(row, SceneIntent, "scene_json")
        results = list(
            tx.run(
                "MATCH (i:ArenaExecutionIntent) WHERE elementId(i)=$key "
                "RETURN CASE WHEN size(toStringOrNull(i.result_json))<=2097152 "
                "THEN i.result_json ELSE null END AS result LIMIT 2",
                key=row["key"],
            )
        )
        if len(results) != 1:
            raise CorruptSceneRecord("missing policy result")
        result = self._historical_payload({"node": {"payload": results[0]["result"]}}, SceneResult)
        owner = self._historical_owner(tx, row, "HAS_SCENE_INTENT")
        if (
            owner["node"]["run_id"] != run_id
            or intent.action != "policy"
            or intent.status != "produced"
            or intent.intent_id != trial.intent_id
            or intent.candidate_id != candidate.candidate_id
            or intent.worker_cleanup is None
            or intent.worker_registration is None
            or intent.worker_fence is None
            or intent.worker_fence.intent_id != trial.intent_id
            or intent.worker_fence.run_id != run_id
            or intent.worker_registration.fence != intent.worker_fence
            or intent.worker_cleanup.registration != intent.worker_registration
            or result.codec_version != 2
            or result.failure is not None
            or result.observation is not None
            or result.candidate_json is not None
            or intent.policy_binding != trial.binding
            or result.policy_trial != trial
            or trial.binding.candidate_digest != candidate.digest
            or evidence_id != identity(trial.intent_id, "observation")
        ):
            raise CorruptSceneRecord("retained policy trial binding mismatch")
        try:
            contract = parse_contract(owner["node"]["contract_json"])
            if (
                trial.binding.contract_digest != contract_digest(contract)
                or trial.binding.seed != contract.execution.seed
            ):
                raise ValueError("policy contract mismatch")
            if decision.action == "accept" and trial.aggregate().outcome != "passed":
                raise ValueError("policy acceptance mismatch")
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptSceneRecord("invalid retained policy trial") from None

    def _historical_decision(self, tx, row):
        from .scene_loop import SceneDecision, SceneIntent, identity

        owner = self._historical_owner(tx, row, "HAS_DECISION")
        run_id, node = owner["node"]["run_id"], row["node"]
        # The shared label also holds generation reservations with a list codec.
        # They are explicitly outside this scene-only query capability.
        if node.get("candidate_id") is None and type(node.get("payload")) is str and node["payload"].startswith("["):
            return None
        decision = self._historical_payload(row, SceneDecision)
        candidate_row = self._historical_node(tx, "ArenaWorkflowCandidate", node.get("candidate_id"))
        if candidate_row is None or self._historical_candidate(tx, candidate_row).run_id != run_id:
            raise CorruptSceneRecord("retained decision candidate mismatch")
        assessment_id = None
        evidence_id = node.get("evidence_id")
        if evidence_id is not None:
            evidence_row = self._historical_node(tx, "ArenaWorkflowEvidence", evidence_id)
            if evidence_row is None:
                raise CorruptSceneRecord("missing retained decision evidence")
            evidence = self._historical_evidence(tx, evidence_row)
            if evidence.run_id != run_id or evidence.candidate_id not in (None, node["candidate_id"]):
                raise CorruptSceneRecord("retained decision evidence mismatch")
            assessment_row = self._historical_link(
                tx,
                evidence_row,
                "ASSESSES",
                "ArenaCriterionAssessment",
                incoming=True,
                required=False,
            )
            if assessment_row is not None:
                assessment = self._historical_assessment(tx, assessment_row)
                if assessment.assessment != decision.assessment or assessment.candidate_id != node["candidate_id"]:
                    raise CorruptSceneRecord("retained decision assessment mismatch")
                assessment_id = assessment.assessment_id
            elif decision.assessment is not None:
                raise CorruptSceneRecord("missing selected retained assessment")
        if decision.policy_trial is not None:
            self._historical_policy_trial(
                tx, run_id, self._historical_candidate(tx, candidate_row).candidate, decision, evidence_id
            )
        next_intent_id = node.get("intent_id")
        if next_intent_id is not None:
            if next_intent_id != identity(node["decision_id"], "intent"):
                raise CorruptSceneRecord("retained next intent cause mismatch")
            intent_row = self._historical_node(tx, "ArenaExecutionIntent", next_intent_id)
            if intent_row is None:
                raise CorruptSceneRecord("missing retained next intent")
            intent = self._historical_payload(intent_row, SceneIntent, "scene_json")
            intent_owner = self._historical_owner(tx, intent_row, "HAS_SCENE_INTENT")
            if (
                intent_owner["node"]["run_id"] != run_id
                or intent.intent_id != next_intent_id
                or intent.candidate_id != node["candidate_id"]
                or intent.action != decision.action
            ):
                raise CorruptSceneRecord("retained next intent mismatch")
        try:
            return SceneDecisionView(
                scope=self._scene_read_scope(),
                run_id=run_id,
                decision_id=node["decision_id"],
                candidate_id=node["candidate_id"],
                decision=decision,
                next_intent_id=next_intent_id,
                evidence_id=evidence_id,
                selected_assessment_id=assessment_id,
            )
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptSceneRecord("invalid retained scene record") from None

    def _get_historical_scene(self, label, record_id, project):
        validate_operation_id(record_id)
        # Immutable scene records need no control SET, grant, readiness check or
        # latest snapshot. Cooperative writers commit each binding atomically;
        # this is not snapshot isolation against external graph mutation.
        with self._transaction() as tx:
            row = self._historical_node(tx, label, record_id)
            try:
                return None if row is None else project(tx, row)
            except CorruptSceneRecord:
                raise
            except (ValueError, TypeError, KeyError, RecursionError):
                # Retained JSON, nested candidate reconstruction and final typed
                # views may include raw input in decoder/validation exceptions.
                raise CorruptSceneRecord("invalid retained scene record") from None

    def get_scene_candidate(self, candidate_id) -> SceneCandidateView | None:
        """Read exact scoped candidate and verify bounded immediate parent/original bindings."""
        return self._get_historical_scene("ArenaWorkflowCandidate", candidate_id, self._historical_candidate)

    def get_scene_decision(self, decision_id) -> SceneDecisionView | None:
        """Read exact scoped scene decision; never decode generation reservations as scene decisions."""
        return self._get_historical_scene("ArenaWorkflowDecision", decision_id, self._historical_decision)

    def get_scene_assessment(self, assessment_id) -> SceneAssessmentView | None:
        """Read exact scoped assessment with its retained evidence and candidate."""
        return self._get_historical_scene("ArenaCriterionAssessment", assessment_id, self._historical_assessment)

    def get_scene_evidence(self, evidence_id) -> SceneEvidenceView | None:
        """Read exact scoped observation, retaining unavailable legacy candidate linkage as None."""
        return self._get_historical_scene("ArenaWorkflowEvidence", evidence_id, self._historical_evidence)

    def _scene_node(self, tx, label, record_id, payload, run_id):
        assert label in (
            "ArenaWorkflowCandidate",
            "ArenaWorkflowEvidence",
            "ArenaCriterionAssessment",
        )
        row = tx.run(
            "MATCH (n:" + label + " " + _SCOPE + ") WHERE n.record_id=$id RETURN n.payload AS payload",
            **self.scope,
            id=record_id,
        ).single()
        if row:
            if row["payload"] != payload:
                raise ValueError("immutable scene record conflict")
            return
        tx.run(
            "MATCH (r:ArenaWorkflowRun "
            + _SCOPE
            + ") WHERE r.run_id=$run CREATE (r)-[:HAS_SCENE_RECORD]->(n:"
            + label
            + " "
            + _SCOPE
            + ") SET n.record_id=$id, n.payload=$payload, n.run_id=$run",
            **self.scope,
            id=record_id,
            payload=payload,
            run=run_id,
        ).consume()

    def _scene_snapshot(self, tx, run_id):
        from .scene_loop import CandidateRecord, SceneDecision, SceneIntent, ScenePortProfile, SceneSnapshot

        row = tx.run(
            "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r.run_id=$id RETURN properties(r) AS r",
            **self.scope,
            id=run_id,
        ).single()
        if row is None or "scene_original" not in row["r"]:
            return None
        r = row["r"]
        intent = None
        if r.get("scene_intent"):
            stored = self._intent(tx, r["scene_intent"])
            intent = SceneIntent.model_validate_json(stored["scene_json"])
        return SceneSnapshot(
            self._run(tx, "run_id", run_id),
            CandidateRecord.model_validate_json(r["scene_original"]),
            CandidateRecord.model_validate_json(r["scene_candidate"]),
            SceneDecision.model_validate_json(r["scene_decision"]),
            intent,
            ScenePortProfile.model_validate_json(r["scene_profile"]),
        )

    def get_run_cleanup(self, run_id) -> RunCleanupView | None:
        """Read retained obligations consistently; lock revision is not a domain fact."""
        validate_operation_id(run_id)
        with self._transaction(fetch_size=1) as tx:
            self._lock(tx)
            result = self._run_cleanup(tx, run_id)
        return result

    def _run_cleanup(self, tx, run_id, *, dependencies=None):
        roots = list(
            tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") WHERE r.run_id=$run RETURN "
                + self._cleanup_projection("r", ("version", "scene_profile"))
                + " AS run, elementId(r) AS key LIMIT 2",
                **self.scope,
                run=run_id,
            )
        )
        if not roots:
            return None
        if len(roots) != 1:
            raise CorruptCleanupRecord()
        root = roots[0]
        owner_data = tx.run(
            _CONTROL
            + "RETURN "
            + self._cleanup_projection("c", ("owner_id", "owner_epoch", "owner_dirty"))
            + " AS owner",
            **self.scope,
        ).single(strict=True)["owner"]
        try:
            owner_row = dict(
                owner_id=owner_data["owner_id"],
                owner_epoch=owner_data["owner_epoch"],
                dirty=owner_data["owner_dirty"],
            )
            owner = None
            if owner_row["owner_id"] is not None:
                if type(owner_row["dirty"]) is not bool:
                    raise CorruptCleanupRecord()
                owner = OwnerView(**owner_row)
            elif any(owner_row[k] is not None for k in ("owner_epoch", "dirty")):
                raise CorruptCleanupRecord()
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptCleanupRecord() from None
        if owner is not None:
            retired_epoch = self._cleanup_retired_epoch(tx, owner.owner_id)
            if (not owner.dirty and (type(retired_epoch) is not int or retired_epoch != owner.owner_epoch)) or (
                owner.dirty and retired_epoch is not None
            ):
                raise CorruptCleanupRecord()
        rows = self._cleanup_rows(tx, run_id, root)
        items = tuple(self._cleanup_obligation(tx, run_id, row, owner) for row in rows)
        try:
            if dependencies is not None:
                dependencies.extend([
                    root["run"],
                    owner_data,
                    sorted(
                        [
                            {k: row[k] for k in ("intent", "attempt", "release_authorized", "receipt_present")}
                            for row in rows
                        ],
                        key=lambda row: row["intent"]["intent_id"],
                    ),
                ])
            items = tuple(sorted(items, key=lambda item: item.intent_id))
            if len({item.intent_id for item in items}) != len(items):
                raise CorruptCleanupRecord()
            payload = dict(
                scope=SceneReadScope(database=self.database, **self.scope),
                run_id=run_id,
                run_version=root["run"]["version"],
                current_scope_owner=owner,
                intents=items,
            )
            value = RunCleanupView(**payload, projection_revision="0" * 64)
            raw = json.dumps(
                value.model_dump(mode="json", exclude={"projection_revision"}),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            if len(raw.encode()) > 2 * 1024 * 1024:
                raise CorruptCleanupRecord()
            return value.model_copy(update={"projection_revision": hashlib.sha256(raw.encode()).hexdigest()})
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptCleanupRecord() from None

    @staticmethod
    def _cleanup_projection(alias, fields):
        # Fixed call-site fields only. Bound values before Bolt, including malformed
        # scalars; [False] is invalid for every selected field, never absence.
        parts = []
        for field in fields:
            prop = f"{alias}.{field}"
            parts.append(
                f"{field}: CASE WHEN size(toStringOrNull({prop}))<=65536 THEN {prop} "
                f"WHEN {prop} IS NULL THEN null ELSE [false] END"
            )
        return alias + " {" + ", ".join(parts) + "}"

    @staticmethod
    def _cleanup_json(raw, model):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise CorruptCleanupRecord()
                result[key] = value
            return result

        if type(raw) is not str or len(raw.encode("utf-8")) > 65536:
            raise CorruptCleanupRecord()
        try:
            json.loads(raw, object_pairs_hook=unique)
            return model.model_validate_json(raw)
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptCleanupRecord() from None

    def _cleanup_exact(self, tx, label, field, value, key):
        rows = list(
            tx.run(
                "MATCH (n:" + label + " " + _SCOPE + ") WHERE n." + field + "=$id RETURN elementId(n) AS key LIMIT 2",
                **self.scope,
                id=value,
            )
        )
        if len(rows) != 1 or rows[0]["key"] != key:
            raise CorruptCleanupRecord()

    @staticmethod
    def _cleanup_parent(tx, key, parent, relation):
        # Do not filter the incoming end by label/scope: foreign and duplicate
        # links must remain visible rather than disappearing from validation.
        rows = list(
            tx.run(
                "MATCH (n)<-[link:"
                + relation
                + "]-(p) WHERE elementId(n)=$key RETURN elementId(p) AS key, type(link) AS relation LIMIT 2",
                key=key,
            )
        )
        if len(rows) != 1 or rows[0]["key"] != parent:
            raise CorruptCleanupRecord()
        return rows[0]["relation"]

    def _cleanup_rows(self, tx, run_id, root):
        count = tx.run(
            "MATCH (i:ArenaExecutionIntent " + _SCOPE + ") WHERE i.run_id=$run RETURN count(i) AS n",
            **self.scope,
            run=run_id,
        ).single(strict=True)["n"]
        if count > 1000:
            raise CorruptCleanupRecord()
        fields = (
            "deployment_id",
            "workspace_id",
            "run_id",
            "intent_id",
            "kind",
            "status",
            "fence_json",
            "registration_json",
            "cleanup_json",
            "scene_json",
            "released_at",
        )
        query = (
            "MATCH (r:ArenaWorkflowRun "
            + _SCOPE
            + ")-[:HAS_INTENT|HAS_SCENE_INTENT]->(i) WHERE r.run_id=$run OPTIONAL MATCH (i)-[:HAS_ATTEMPT]->(a) RETURN "
            + self._cleanup_projection("i", fields)
            + " AS intent, "
            + self._cleanup_projection("a", fields + ("attempt_id",))
            + " AS attempt, "
            "elementId(i) AS ikey, elementId(a) AS akey, i:ArenaExecutionIntent AS ityped, "
            "a:ArenaExecutionAttempt AS atyped, "
            "a.release_authorization_json IS NOT NULL AS release_authorized, "
            "a.receipt_json IS NOT NULL AS receipt_present LIMIT 1001"
        )
        rows, total = [], 0
        for record in tx.run(query, **self.scope, run=run_id):
            try:
                row = dict(record)
                total += len(json.dumps(row, allow_nan=False).encode("utf-8"))
            except (ValueError, TypeError, KeyError, RecursionError):
                raise CorruptCleanupRecord() from None
            if len(rows) >= 1000 or total > 8 * 1024 * 1024:
                raise CorruptCleanupRecord()
            rows.append(row)
        if len(rows) != count:
            raise CorruptCleanupRecord()
        # Finish the byte-checked outer stream before issuing validation queries:
        # pending Bolt batches can otherwise be hydrated by nested tx.run calls.
        # This bounds selected serialized rows, not total RSS: one bounded row/
        # fetch batch plus protocol and Python object overhead remain additional.
        for row in rows:
            intent, attempt = row["intent"], row["attempt"]
            if row["ityped"] is not True or any(intent.get(k) != v for k, v in self.scope.items()):
                raise CorruptCleanupRecord()
            self._cleanup_exact(tx, "ArenaExecutionIntent", "intent_id", intent["intent_id"], row["ikey"])
            relation = self._cleanup_parent(tx, row["ikey"], root["key"], "HAS_INTENT|HAS_SCENE_INTENT")
            if relation != ("HAS_SCENE_INTENT" if intent.get("kind") == "scene" else "HAS_INTENT"):
                raise CorruptCleanupRecord()
            if attempt is not None:
                if row["atyped"] is not True or any(attempt.get(k) != v for k, v in self.scope.items()):
                    raise CorruptCleanupRecord()
                self._cleanup_exact(tx, "ArenaExecutionAttempt", "attempt_id", attempt["attempt_id"], row["akey"])
                self._cleanup_parent(tx, row["akey"], row["ikey"], "HAS_ATTEMPT")
            row["profile"] = root["run"]["scene_profile"]
        return rows

    def _cleanup_obligation(self, tx, run_id, row, owner):
        from .scene_loop import SceneIntent, ScenePortProfile

        node = row["intent"]
        if node.get("kind") != "scene":
            return self._cleanup_generation(tx, run_id, row, owner)
        profile = self._cleanup_json(row["profile"], ScenePortProfile)
        if type(json.loads(row["profile"]).get("owned_worker")) is not bool:
            raise CorruptCleanupRecord()
        intent = self._cleanup_json(node["scene_json"], SceneIntent)
        raw_intent = json.loads(node["scene_json"])
        # Writer-emitted nulls mean unclaimed; missing members do not.
        if (
            type(raw_intent) is not dict
            or not {"worker_fence", "worker_registration", "worker_cleanup", "released_at"} <= raw_intent.keys()
        ):
            raise CorruptCleanupRecord()
        if (
            node["run_id"] != run_id
            or node["intent_id"] != intent.intent_id
            or node["status"] != intent.status
            or row["attempt"] is not None
        ):
            raise CorruptCleanupRecord()
        fence, registration, cleanup = intent.worker_fence, intent.worker_registration, intent.worker_cleanup
        if any(node[k] is not None for k in ("fence_json", "registration_json", "cleanup_json", "released_at")):
            raise CorruptCleanupRecord()
        raw_release = json.loads(node["scene_json"]).get("released_at")
        if raw_release is not None and (
            type(raw_release) not in (int, float) or not math.isfinite(raw_release) or raw_release < 0
        ):
            raise CorruptCleanupRecord()
        if fence is not None and (fence.run_id != run_id or fence.intent_id != intent.intent_id):
            raise CorruptCleanupRecord()
        if not profile.owned_worker and any(v is not None for v in (fence, registration, cleanup)):
            raise CorruptCleanupRecord()
        released = intent.released_at is not None
        if (
            (intent.status == "reserved" and released)
            or (intent.status in ("released", "produced") and not released)
            or (profile.owned_worker and fence is None and intent.status != "reserved")
        ):
            raise CorruptCleanupRecord()
        value = self._cleanup_item(
            tx,
            owner,
            intent.intent_id,
            "scene",
            fence,
            registration,
            cleanup,
            released if profile.owned_worker else False,
        )
        if not profile.owned_worker:
            value = value.model_copy(
                update={
                    "cleanup_state": "not_applicable",
                    "release_state": "released" if released else "known_unreleased",
                }
            )
        return value

    def _cleanup_generation(self, tx, run_id, row, owner):
        intent, attempt = row["intent"], row["attempt"]
        if intent.get("kind") not in (None, "generation") or intent["run_id"] != run_id:
            raise CorruptCleanupRecord()
        if intent["scene_json"] is not None or intent["released_at"] is not None:
            raise CorruptCleanupRecord()
        fence = self._cleanup_json(intent["fence_json"], AttemptFence) if intent["fence_json"] is not None else None
        if fence is None:
            if attempt is not None or intent["status"] != "reserved":
                raise CorruptCleanupRecord()
        else:
            if fence.run_id != run_id or fence.intent_id != intent["intent_id"] or attempt is None:
                raise CorruptCleanupRecord()
            if attempt["attempt_id"] != fence.attempt_id:
                raise CorruptCleanupRecord()
            for key in ("fence_json", "registration_json", "cleanup_json", "status"):
                if intent.get(key) != attempt.get(key):
                    raise CorruptCleanupRecord()
        registration = (
            self._cleanup_json(intent["registration_json"], WorkerRegistration)
            if intent["registration_json"] is not None
            else None
        )
        cleanup = (
            self._cleanup_json(intent["cleanup_json"], CleanupEvidence) if intent["cleanup_json"] is not None else None
        )
        released = attempt is not None and attempt["released_at"] is not None
        if not released and (row["release_authorized"] or row["receipt_present"]):
            raise CorruptCleanupRecord()
        if released and (
            type(attempt["released_at"]) not in (int, float)
            or not math.isfinite(attempt["released_at"])
            or attempt["released_at"] < 0
        ):
            raise CorruptCleanupRecord()
        if intent["status"] not in (
            "reserved",
            "claimed",
            "registered",
            "released",
            "produced",
            "cancelled",
            "reconciliation_required",
        ):
            raise CorruptCleanupRecord()
        status = intent["status"]
        if (
            (status == "reserved" and fence is not None)
            or (status == "claimed" and (registration is not None or released))
            or (status == "registered" and (registration is None or released))
            or (status in ("released", "produced", "reconciliation_required") and not released)
        ):
            raise CorruptCleanupRecord()
        return self._cleanup_item(tx, owner, intent["intent_id"], "generation", fence, registration, cleanup, released)

    def _cleanup_retired_epoch(self, tx, owner_id):
        rows = list(
            tx.run(
                "MATCH (o:ArenaRetiredWorkflowOwner "
                + _SCOPE
                + ") WHERE o.owner_id=$owner RETURN "
                + self._cleanup_projection("o", ("owner_epoch",))
                + " AS owner LIMIT 2",
                **self.scope,
                owner=owner_id,
            )
        )
        if len(rows) > 1:
            raise CorruptCleanupRecord()
        if not rows:
            return None
        epoch = rows[0]["owner"]["owner_epoch"]
        if type(epoch) is not int or epoch < 1:
            raise CorruptCleanupRecord()
        return epoch

    def _cleanup_item(self, tx, owner, intent_id, kind, fence, registration, cleanup, released):
        if (
            (registration is not None and registration.fence != fence)
            or (cleanup is not None and cleanup.registration != registration)
            or (released and registration is None)
        ):
            raise CorruptCleanupRecord()
        retired = None
        if fence is not None:
            epoch = self._cleanup_retired_epoch(tx, fence.owner_id)
            if epoch is not None:
                if type(epoch) is not int or epoch != fence.owner_epoch:
                    raise CorruptCleanupRecord()
                retired = OwnerView(owner_id=fence.owner_id, owner_epoch=epoch, dirty=False)
            if owner is None or (
                retired is None
                and (owner.owner_id != fence.owner_id or owner.owner_epoch != fence.owner_epoch or not owner.dirty)
            ):
                raise CorruptCleanupRecord()
        try:
            return IntentCleanupView(
                intent_id=intent_id,
                kind=kind,
                fence=fence,
                registration_id=None if registration is None else registration.registration_id,
                release_state="released" if released else "known_unreleased",
                cleanup_state="recorded" if cleanup else "unknown" if fence else "not_started",
                cleanup_evidence_ref=None if cleanup is None else cleanup.evidence_ref,
                cleanup_observation=None if cleanup is None else cleanup.observation,
                remote_effects=None if cleanup is None else cleanup.remote_effects,
                retired_owner=retired,
            )
        except (ValueError, TypeError, KeyError, RecursionError):
            raise CorruptCleanupRecord() from None

    def result_records(self, run_id):
        """Read one consistent bounded public result source without effects or grants."""
        with self._transaction() as tx:
            self._lock(tx)
            run = self._run(tx, "run_id", run_id)
            if run is None:
                raise ValueError("Unknown workflow run")
            intents = list(
                tx.run(
                    "MATCH (i:ArenaExecutionIntent "
                    + _SCOPE
                    + ") WHERE i.run_id=$id "
                    "RETURN i.intent_id AS intent_id, i.status AS status, i.reservation_json AS reservation, "
                    "i.scene_json AS scene, i.result_json AS result, i.assessment_send_json AS assessment_send "
                    "ORDER BY i.intent_id LIMIT 1001",
                    **self.scope,
                    id=run_id,
                )
            )
            evidence = list(
                tx.run(
                    "MATCH (e:ArenaWorkflowEvidence "
                    + _SCOPE
                    + ") WHERE e.run_id=$id "
                    "OPTIONAL MATCH (e)-[:FOR_CANDIDATE]->(c:ArenaWorkflowCandidate) "
                    "RETURN e.record_id AS evidence_id, e.payload AS payload, c.record_id AS candidate_id, "
                    "c.payload AS candidate "
                    "ORDER BY e.record_id LIMIT 1001",
                    **self.scope,
                    id=run_id,
                )
            )
            if len(intents) > 1000 or len(evidence) > 1000:
                raise ValueError("Result record bound exceeded")
            admitted = tx.run(
                "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r.run_id=$id RETURN r.admitted_at AS at",
                **self.scope,
                id=run_id,
            ).single()["at"]
            return dict(
                run=run,
                scene=self._scene_snapshot(tx, run_id),
                owner=self._owner_view(tx),
                intents=[dict(row) for row in intents],
                evidence=[dict(row) for row in evidence],
                evidence_selections=[
                    dict(row)
                    for row in tx.run(
                        "MATCH (r:ArenaWorkflowRun "
                        + _SCOPE
                        + ")-[:HAS_DECISION]->(d:ArenaWorkflowDecision) WHERE r.run_id=$id AND d.evidence_id IS NOT"
                        " NULL RETURN d.candidate_id AS candidate_id, d.intent_id AS intent_id, d.evidence_id AS"
                        " evidence_id LIMIT 1001",
                        **self.scope,
                        id=run_id,
                    )
                ],
                admitted_at=admitted,
                selected_evidence_id=tx.run(
                    "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r.run_id=$id RETURN r.scene_evidence AS evidence",
                    **self.scope,
                    id=run_id,
                ).single()["evidence"],
            )

    def scene_snapshot(self, run_id):
        """Read durable scene identity/actions without dispatch or renewal."""
        with self._transaction() as tx:
            self._lock(tx)
            return self._scene_snapshot(tx, run_id)

    def assessment_send_record(self, run_id, intent_id):
        """Reconcile one durably charged send without issuing another reservation."""
        with self._transaction() as tx:
            self._lock(tx)
            record = self._intent(tx, intent_id)
            if record["run_id"] != run_id:
                raise ValueError("Assessment send scope differs")
            raw = record.get("assessment_send_json")
            return None if raw is None else json.loads(raw)

    def _scene_decide(self, tx, run, candidate, decision, profile, selected_evidence_id=None):
        from .scene_loop import SceneIntent, identity

        contract = parse_contract(run.contract_json)
        retained_assessment = contract.schema_version == "4"
        if retained_assessment and decision.action == "assess":
            selected_evidence_id = self._retained_assessment_source(tx, contract).evidence_id
        admitted = tx.run(
            "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r.run_id=$id RETURN r.admitted_at AS at",
            **self.scope,
            id=run.run_id,
        ).single()["at"]
        now = self._now()
        # Every allocation, including initial generation, remains charged in one
        # intent ledger. No trust in provider usage; no refunds on failure.
        rows = list(
            tx.run(
                "MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ") WHERE i.run_id=$id RETURN i.reservation_json AS reservation",
                **self.scope,
                id=run.run_id,
            )
        )
        charged = [json.loads(r["reservation"]) for r in rows]
        b = contract.budget
        deadline = admitted + (
            min(b.max_runtime_seconds, b.total_deadline_seconds) if retained_assessment else b.total_deadline_seconds
        )
        if now < admitted or now >= deadline:
            decision = decision.model_copy(update={"action": "stop", "reason": "budget_exhausted"})
        if decision.action == "observe" and profile.codec_version == 2:
            decision = decision.model_copy(update={"action": "capture"})
        allowance = (
            getattr(profile, decision.action, None)
            if decision.action in ("observe", "repair", "capture", "assess", "policy")
            else None
        )
        if allowance is not None:
            limits = {
                "model_calls": b.max_model_calls,
                "model_tokens": b.max_model_tokens,
                "cost_ceiling_usd": b.max_cost_usd,
                "runtime_allowance_seconds": b.max_runtime_seconds,
                "candidates": b.max_candidates - 1,
                "revisions": b.max_revisions,
                "realizations": b.max_realizations,
                "steps": b.max_steps,
                "observations": b.max_observations,
                "policy_episodes": b.max_policy_episodes,
                "policy_steps": b.max_policy_steps,
            }
            invalid = any(
                sum(c.get(key, 0) for c in charged) + getattr(allowance, key) > limit
                for key, limit in limits.items()
                if limit is not None and not (retained_assessment and key == "model_calls")
            )
            if retained_assessment:
                sends = tx.run(
                    "MATCH (i:ArenaExecutionIntent "
                    + _SCOPE
                    + ") WHERE i.assessment_source=$source "
                    "AND i.assessment_send_json IS NOT NULL RETURN count(i) AS count",
                    **self.scope,
                    source=contract.retained_evidence.run_id,
                ).single()["count"]
                invalid |= sends >= b.max_model_calls
            invalid |= (
                not 0 < allowance.runtime_allowance_seconds <= b.per_operation_timeout_seconds
                or now + allowance.runtime_allowance_seconds > deadline
            )
            if decision.action in ("observe", "capture"):
                invalid |= allowance.realizations < 1 or allowance.observations < 1
                required_steps = max(
                    c.observation_window.end_step
                    for c in contract.criteria
                    if c.requirement == "required" and c.kind != "policy"
                )
                invalid |= allowance.steps < required_steps
            elif decision.action == "repair":
                invalid |= allowance.candidates < 1 or allowance.revisions < 1
            elif decision.action == "policy":
                binding = profile.policy_binding
                invalid |= (
                    allowance.policy_episodes != binding.max_episodes
                    or allowance.policy_steps != binding.max_policy_steps
                    or allowance.steps < binding.max_prerequisite_steps
                    or allowance.realizations < 1
                    or now >= binding.deadline_unix
                    or binding.deadline_unix > admitted + b.total_deadline_seconds
                )
            if invalid:
                decision = decision.model_copy(update={"action": "stop", "reason": "budget_exhausted"})
                allowance = None
        decision_id = identity(run.run_id, run.version, "scene-decision")
        intent = None
        if allowance is not None:
            observation_digest = None
            if decision.action in ("assess", "policy"):
                row = self._historical_node(tx, "ArenaWorkflowEvidence", selected_evidence_id)
                evidence = self._historical_evidence(tx, row)
                if not retained_assessment and (
                    evidence.run_id != run.run_id or evidence.candidate_id != candidate.candidate_id
                ):
                    raise ValueError("capture candidate binding mismatch")
                observation_digest = identity(evidence.observation.model_dump(mode="json"))
            intent = SceneIntent(
                codec_version=profile.codec_version,
                intent_id=identity(decision_id, "intent"),
                candidate_id=candidate.candidate_id,
                action=decision.action,
                status="reserved",
                reservation=allowance,
                observation_id=selected_evidence_id if decision.action in ("assess", "policy") else None,
                observation_digest=observation_digest,
                policy_binding=(
                    profile.policy_binding.model_copy(update={"candidate_digest": candidate.digest})
                    if decision.action == "policy"
                    else None
                ),
            )
            tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") WHERE r.run_id=$run CREATE (r)-[:HAS_SCENE_INTENT]->(i:ArenaExecutionIntent "
                + _SCOPE
                + ") "
                "SET i.intent_id=$id, i.run_id=$run, i.kind='scene', i.status='reserved', "
                "i.scene_json=$scene, i.reservation_json=$reservation, i.assessment_source=$assessment_source",
                **self.scope,
                run=run.run_id,
                id=intent.intent_id,
                scene=intent.model_dump_json(),
                reservation=allowance.model_dump_json(),
                assessment_source=contract.retained_evidence.run_id if retained_assessment else None,
            ).consume()
        tx.run(
            "MATCH (r:ArenaWorkflowRun "
            + _SCOPE
            + ") WHERE r.run_id=$run CREATE (r)-[:HAS_DECISION]->(d:ArenaWorkflowDecision "
            + _SCOPE
            + ") "
            "SET d.decision_id=$id, d.payload=$decision, d.candidate_id=$candidate, d.intent_id=$intent, "
            "d.run_id=$run, d.record_kind='scene_decision', d.membership_codec=1, "
            "r.scene_decision=$decision, r.scene_candidate=$record, r.scene_intent=$intent, "
            "r.scene_evidence=$evidence, d.evidence_id=$evidence, "
            "r.state=$state, r.phase='scene', r.stop_reason=$reason",
            **self.scope,
            run=run.run_id,
            id=decision_id,
            evidence=None if retained_assessment else selected_evidence_id,
            decision=decision.model_dump_json(),
            candidate=candidate.candidate_id,
            record=candidate.model_dump_json(),
            intent=intent.intent_id if intent else None,
            state=(
                "accepted" if decision.action == "accept" else "stopped" if decision.action == "stop" else "running"
            ),
            reason=decision.reason,
        ).consume()
        self._event(tx, run.run_id, "SceneDecisionRecorded", decision_id)
        if contract.schema_version == "3":
            assert contract.source.kind == "existing", "Retained native source required"
            namespace = json.loads(contract.source.content)["env_name"]
            # Preserve the original failed graph and its verification flags. This
            # is a new native-only attempt, never an eligible structural prior.
            tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") WHERE r.run_id=$run "
                "MATCH (g:EnvironmentGraph {name:$namespace}) "
                "MERGE (a:NativeValidationAttempt {attempt_id:$run, scene_namespace:$namespace}) "
                "SET a.candidate_sha256=$source_sha, a.candidate_json_sha256=$candidate_sha, "
                "a.contract_sha256=$contract_sha, a.settings_sha256=$settings_sha, "
                "a.native_settled=$settled, a.converged=false, a.verified=false, "
                "a.provider_calls=0, a.policy_executed=false, a.decision=$decision, "
                "a.evidence_id=$evidence, a.execution_path='installed-native-validation', "
                "a.policy_basis='operator-approved revised settling policy, not calibration' "
                "MERGE (g)-[:HAS_NATIVE_VALIDATION_ATTEMPT]->(a) "
                "MERGE (r)-[:HAS_NATIVE_VALIDATION_RESULT]->(a)",
                **self.scope,
                run=run.run_id,
                namespace=namespace,
                source_sha=hashlib.sha256(contract.source.content.encode("utf-8")).hexdigest(),
                candidate_sha=candidate.digest,
                contract_sha=contract_digest(contract),
                settings_sha=contract.execution.runtime.settings_sha256,
                settled=decision.action == "accept",
                decision=decision.reason,
                evidence=selected_evidence_id,
            ).consume()

    def begin_scene(self, run_id, expected_version, candidate, validation, profile, *, authorization=None):
        """Commit original validated bytes plus first decision/reservation atomically.

        Trusted service supplies actual-byte/schema verification; this store binds
        its receipt to the retained generation, not a caller's success boolean.
        """
        from .evidence_contracts import project_required_criteria
        from .scene_loop import CandidateRecord, SceneDecision, ScenePortProfile, policy_compatible

        candidate = CandidateRecord.model_validate_json(candidate.model_dump_json())
        profile = ScenePortProfile.model_validate_json(profile.model_dump_json())
        payload = json.dumps(
            [
                candidate.model_dump(mode="json"),
                validation,
                profile.model_dump(mode="json"),
            ],
            sort_keys=True,
        )
        with self._transaction() as tx:
            self._lock(tx)
            run = self._run(tx, "run_id", run_id)
            prior = tx.run(
                "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r.run_id=$id RETURN r.scene_start AS start",
                **self.scope,
                id=run_id,
            ).single()
            if prior and prior["start"]:
                if prior["start"] != payload:
                    raise ValueError("conflicting scene start")
                return candidate.candidate_id
            if run is None or run.version != expected_version:
                raise ValueError("inactive scene start")
            contract = parse_contract(run.contract_json)
            if contract.schema_version == "4":
                from .scene_loop import candidate_record

                self._scene_authority(contract, authorization, self._now())
                evidence = self._retained_assessment_source(tx, contract)
                expected = candidate_record(
                    run_id, json.loads(contract.source.content), source_id=contract.source.identity
                )
                if (
                    run.state != "pending"
                    or candidate != expected
                    or profile.assurance != "retained-evidence"
                    or validation
                    != dict(
                        disposition="retained_assessment_consumer",
                        producer=contract.retained_evidence.model_dump(mode="json"),
                        producer_evidence_id=evidence.evidence_id,
                    )
                ):
                    raise ValueError("Retained assessment consumer binding mismatch")
                decision = SceneDecision(action="assess", reason="retained_producer_linked")
            elif contract.schema_version == "3":
                from .scene_loop import candidate_record

                assert contract.source.kind == "existing", "Retained native source required"
                self._scene_authority(contract, authorization, self._now())
                expected = candidate_record(
                    run_id, json.loads(contract.source.content), source_id=contract.source.identity
                )
                if (
                    run.state != "pending"
                    or candidate != expected
                    or profile.codec_version != 2
                    or profile.assurance != "native-unverified"
                    or not profile.owned_worker
                    or validation
                    != dict(
                        disposition="external_candidate_admitted",
                        source_identity=contract.source.identity,
                        source_bytes_sha256=hashlib.sha256(contract.source.content.encode("utf-8")).hexdigest(),
                        candidate_json_sha256=candidate.digest,
                        contract_digest=contract_digest(contract),
                        native_schema_validation_required=True,
                    )
                ):
                    raise ValueError("external candidate binding mismatch")
                decision = SceneDecision(action="observe", reason="external_candidate_admitted")
            else:
                if (run.state, run.phase) != ("running", "validation"):
                    raise ValueError("inactive scene start")
                fence = AttemptFence.model_validate(validation["fence"])
                retained = self._attempt_view(tx, fence)
                receipt = retained.receipt
                if (
                    receipt is None
                    or retained.cleanup is None
                    or retained.status != "produced"
                    or fence.run_id != run_id
                    or candidate.run_id != run_id
                    or candidate.parent_id is not None
                    or candidate.original_id != candidate.candidate_id
                    or candidate.source_id != fence.attempt_id
                    or candidate.digest != receipt.candidate_json_sha256
                    or any(
                        validation.get(key) != getattr(receipt, key)
                        for key in (
                            "contract_digest",
                            "candidate_yaml_sha256",
                            "candidate_json_sha256",
                            "provenance_sha256",
                            "manifest_sha256",
                        )
                    )
                ):
                    raise ValueError("scene generation binding mismatch")
                decision = SceneDecision(action="observe", reason="schema_validated")
                if validation.get("disposition") != "schema_validated":
                    decision = SceneDecision(action="stop", reason="invalid_candidate")
            if contract.schema_version in ("3", "4"):
                tx.run(
                    "MATCH (r:ArenaWorkflowRun "
                    + _SCOPE
                    + ") WHERE r.run_id=$id SET r.native_authorization_json=$auth",
                    **self.scope,
                    id=run_id,
                    auth=authorization.model_dump_json(),
                ).consume()
            try:
                contract = parse_contract(run.contract_json)
                if profile.policy_binding is not None and profile.policy_binding.candidate_digest != candidate.digest:
                    raise ValueError("policy original candidate mismatch")
                required = project_required_criteria(contract, include_policy=policy_compatible(contract, profile))
                if not {r.producer_id for r in required} <= set(profile.producer_ids):
                    raise ValueError("unsupported producer")
            except ValueError:
                decision = SceneDecision(action="stop", reason="unsupported_criterion")
            self._scene_node(
                tx,
                "ArenaWorkflowCandidate",
                candidate.candidate_id,
                candidate.model_dump_json(),
                run_id,
            )
            tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") WHERE r.run_id=$id SET r.scene_start=$start, r.scene_original=$original, r.scene_profile=$profile,"
                " r.scene_validation=$validation",
                **self.scope,
                id=run_id,
                start=payload,
                original=candidate.model_dump_json(),
                profile=profile.model_dump_json(),
                validation=json.dumps(validation, sort_keys=True),
            ).consume()
            self._scene_decide(tx, run, candidate, decision, profile)
        return candidate.candidate_id

    def _retained_scene_intent(self, tx, run_id, intent_id):
        from .scene_loop import SceneIntent

        stored = self._intent(tx, intent_id)
        if stored.get("kind") != "scene" or stored["run_id"] != run_id:
            raise ValueError("scene intent mismatch")
        return SceneIntent.model_validate_json(stored["scene_json"])

    def get_scene_intent(self, run_id, intent_id):
        """Read exact historical scene worker bindings, including after handover."""
        with self._transaction() as tx:
            self._lock(tx)
            return self._retained_scene_intent(tx, run_id, intent_id)

    def _retained_assessment_source(self, tx, contract):
        from .scene_loop import profile_digest

        source = contract.retained_evidence
        producer = self._run(tx, "run_id", source.run_id)
        original = parse_contract(producer.contract_json)
        selected = self._scene_snapshot(tx, source.run_id)
        if (
            producer.operation_id != source.operation_id
            or original.schema_version != "3"
            or original.source.content != contract.source.content
            or contract_digest(original) != source.contract_digest
            or profile_digest(original) != source.profile_digest
            or selected.candidate.digest != source.candidate_digest
        ):
            raise ValueError("Original assessment producer changed")
        row = tx.run(
            "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r.run_id=$id RETURN r.scene_evidence AS evidence",
            **self.scope,
            id=source.run_id,
        ).single()
        evidence = self._historical_evidence(tx, self._historical_node(tx, "ArenaWorkflowEvidence", row["evidence"]))
        if evidence.observation.verified_manifest_digests != (source.observation_manifest_digest,):
            raise ValueError("Original assessment capture changed")
        return evidence

    def record_assessment_send(self, run_id, intent_id, registration, message):
        """Consume one cumulative send before the owned pipe acknowledges dispatch."""
        with self._transaction() as tx:
            self._lock(tx)
            snapshot = self._scene_snapshot(tx, run_id)
            contract = parse_contract(snapshot.run.contract_json)
            intent = snapshot.intent
            if (
                contract.schema_version != "4"
                or snapshot.run.state != "running"
                or intent is None
                or intent.intent_id != intent_id
                or intent.status != "released"
                or intent.worker_registration != registration
                or intent.worker_cleanup is not None
                or self._intent(tx, intent_id).get("assessment_send_json") is not None
            ):
                raise ValueError("Fresh owned assessment send required")
            self._fenced_scene(tx, registration.fence)
            source = contract.retained_evidence.run_id
            count = tx.run(
                "MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ") WHERE i.assessment_source=$source AND i.assessment_send_json IS NOT NULL RETURN count(i) AS count",
                **self.scope,
                source=source,
            ).single()["count"]
            if count >= contract.budget.max_model_calls:
                raise ValueError("Cumulative assessment attempt allowance exhausted")
            record = dict(
                message, cumulative_attempt=count + 1, authorized_at=self._now(), provider_outcome="uncertain"
            )
            tx.run(
                "MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ") WHERE i.intent_id=$id SET i.assessment_send_json=$record",
                **self.scope,
                id=intent_id,
                record=json.dumps(record, sort_keys=True),
            ).consume()
            self._event(tx, run_id, "AssessmentProviderSendAuthorized", intent_id)
        return record

    def _scene_capture(self, tx, run_id, intent):
        from .scene_loop import identity

        if intent.codec_version != 2 or intent.action not in ("assess", "policy"):
            raise ValueError("split assessment intent required")
        row = self._historical_node(tx, "ArenaWorkflowEvidence", intent.observation_id)
        if row is None:
            raise ValueError("retained capture missing")
        value = self._historical_evidence(tx, row)
        contract = parse_contract(self._run(tx, "run_id", run_id).contract_json)
        if contract.schema_version == "4":
            source = self._retained_assessment_source(tx, contract)
            if value != source or identity(value.observation.model_dump(mode="json")) != intent.observation_digest:
                raise ValueError("Retained producer capture binding mismatch")
            return value.observation
        if (
            value.run_id != run_id
            or value.candidate_id != intent.candidate_id
            or identity(value.observation.model_dump(mode="json")) != intent.observation_digest
        ):
            raise ValueError("retained capture binding mismatch")
        return value.observation

    def get_scene_capture(self, run_id, intent_id):
        """Read only the exact pinned capture; ports must independently reopen bytes."""
        with self._transaction() as tx:
            self._lock(tx)
            return self._scene_capture(tx, run_id, self._retained_scene_intent(tx, run_id, intent_id))

    def _write_scene_intent(self, tx, run_id, intent):
        tx.run(
            "MATCH (i:ArenaExecutionIntent "
            + _SCOPE
            + ") WHERE i.run_id=$run AND i.intent_id=$id SET i.scene_json=$scene, i.status=$status",
            **self.scope,
            run=run_id,
            id=intent.intent_id,
            scene=intent.model_dump_json(),
            status=intent.status,
        ).consume()

    def claim_scene_worker(self, run_id, intent_id, owner_id, owner_epoch, *, resume_operation_id=None):
        """Persist the prepare fence before any worker creation; never infer no process."""
        from .scene_loop import identity

        with self._transaction() as tx:
            self._lock(tx)
            self._owner(tx, owner_id, owner_epoch)
            if resume_operation_id is not None:
                self._resume_claim_guard(tx, resume_operation_id, run_id, intent_id, "scene")
            s = self._scene_snapshot(tx, run_id)
            if (
                s is None
                or s.intent is None
                or s.intent.intent_id != intent_id
                or s.run.state != "running"
                or s.intent.status != "reserved"
                or not s.profile.owned_worker
            ):
                raise ValueError("managed reserved scene required")
            fence = AttemptFence(
                run_id=run_id,
                intent_id=intent_id,
                attempt_id=identity(intent_id, "worker"),
                generation=1,
                owner_id=owner_id,
                owner_epoch=owner_epoch,
            )
            if s.intent.worker_fence is not None:
                raise ValueError("scene worker already claimed; reconcile without preparing again")
            intent = s.intent.model_copy(update={"worker_fence": fence})
            self._write_scene_intent(tx, run_id, intent)
            self._event(tx, run_id, "SceneWorkerClaimed", fence.attempt_id)
        return fence

    def _fenced_scene(self, tx, fence):
        self._owner(tx, fence.owner_id, fence.owner_epoch)
        intent = self._retained_scene_intent(tx, fence.run_id, fence.intent_id)
        if intent.worker_fence != fence:
            raise ValueError("scene worker fence mismatch")
        return intent

    def register_scene_worker(self, fence, registration):
        """Retain exact owner-verified prepare identity; no OS operations in the store."""
        fence = AttemptFence.model_validate_json(fence.model_dump_json())
        registration = WorkerRegistration.model_validate_json(registration.model_dump_json())
        if registration.fence != fence:
            raise ValueError("scene registration fence mismatch")
        with self._transaction() as tx:
            self._lock(tx)
            intent = self._fenced_scene(tx, fence)
            if intent.worker_registration is not None:
                if intent.worker_registration != registration:
                    raise ValueError("conflicting scene registration")
                return False
            if intent.status != "reserved" or self._run(tx, "run_id", fence.run_id).state != "running":
                raise ValueError("scene worker not registerable")
            self._write_scene_intent(
                tx,
                fence.run_id,
                intent.model_copy(update={"worker_registration": registration}),
            )
            self._event(tx, fence.run_id, "SceneWorkerRegistered", registration.registration_id)
        return True

    def acknowledge_scene_cleanup(self, fence, evidence):
        """Retain exact physical-port evidence; never infer cleanup from cancellation."""
        fence = AttemptFence.model_validate_json(fence.model_dump_json())
        if type(evidence) is not CleanupEvidence:
            raise ValueError("typed scene cleanup required")
        evidence = CleanupEvidence.model_validate_json(evidence.model_dump_json())
        with self._transaction() as tx:
            self._lock(tx)
            intent = self._fenced_scene(tx, fence)
            if intent.worker_registration is None or evidence.registration != intent.worker_registration:
                raise ValueError("scene cleanup registration mismatch")
            if intent.worker_cleanup is not None:
                if intent.worker_cleanup != evidence:
                    raise ValueError("conflicting scene cleanup")
                self._finish_known_native_cancel(tx, fence.run_id)
                return False
            self._write_scene_intent(tx, fence.run_id, intent.model_copy(update={"worker_cleanup": evidence}))
            run = self._run(tx, "run_id", fence.run_id)
            if run.state == "cancel_requested":
                tx.run(
                    "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r.run_id=$id SET r.state='cancelled'",
                    **self.scope,
                    id=fence.run_id,
                ).consume()
            self._event(tx, fence.run_id, "SceneWorkerCleanupAcknowledged", fence.attempt_id)
        return True

    def _finish_known_native_cancel(self, tx, run_id):
        run = self._run(tx, "run_id", run_id)
        if run is None or run.state != "cancel_requested" or parse_contract(run.contract_json).schema_version != "3":
            return False
        from .scene_loop import SceneIntent

        rows = tx.run(
            "MATCH (i:ArenaExecutionIntent "
            + _SCOPE
            + ") WHERE i.run_id=$id AND i.kind='scene' RETURN i.scene_json AS scene",
            **self.scope,
            id=run_id,
        )
        intents = [SceneIntent.model_validate_json(row["scene"]) for row in rows]
        if not intents or any(
            (
                i.worker_fence is not None
                and (
                    i.worker_registration is None
                    or i.worker_cleanup is None
                    or i.worker_cleanup.registration != i.worker_registration
                )
            )
            or (i.worker_fence is None and i.status in ("released", "reconciliation_required"))
            for i in intents
        ):
            raise ValueError("Native cancellation still has unresolved physical obligations")
        tx.run(
            "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r.run_id=$id SET r.state='cancelled'",
            **self.scope,
            id=run_id,
        ).consume()
        self._event(tx, run_id, "KnownNativeCancellationCompleted", run_id)
        return True

    def reconcile_native_cancellation(self, run_id):
        """Complete only already-acknowledged cleanup; never retire or unlock its owner."""
        validate_operation_id(run_id)
        with self._transaction() as tx:
            self._lock(tx)
            self._finish_known_native_cancel(tx, run_id)
            return self._run(tx, "run_id", run_id)

    def release_scene(
        self,
        run_id,
        intent_id,
        authorization,
        *,
        readiness,
        fence=None,
        registration_id=None,
    ):
        """One committed release winner; unknown/replayed effects never retry."""
        with self._transaction() as tx:
            self._lock(tx)
            snapshot = self._scene_snapshot(tx, run_id)
            if snapshot is None or snapshot.run.state != "running" or snapshot.intent is None:
                return False
            intent = snapshot.intent
            if intent.intent_id != intent_id or intent.status != "reserved":
                return False
            if snapshot.profile.owned_worker:
                if fence is None or intent.worker_fence != fence or intent.worker_registration is None:
                    raise ValueError("exact scene worker registration required")
                self._fenced_scene(tx, fence)
                if intent.worker_registration.registration_id != registration_id:
                    raise ValueError("scene registration mismatch")
                if intent.worker_cleanup is not None:
                    return False
            elif fence is not None or registration_id is not None:
                raise ValueError("unexpected scene worker binding")
            contract = parse_contract(snapshot.run.contract_json)
            now = self._now()
            self._scene_authority(contract, authorization, now)
            self._readiness(contract, readiness, now)
            if intent.policy_binding is not None and now >= intent.policy_binding.deadline_unix:
                raise ValueError("policy trial deadline exhausted")
            if contract.schema_version in ("3", "4"):
                original_auth = tx.run(
                    "MATCH (r:ArenaWorkflowRun "
                    + _SCOPE
                    + ") WHERE r.run_id=$id RETURN r.native_authorization_json AS auth, r.admitted_at AS at",
                    **self.scope,
                    id=run_id,
                ).single(strict=True)
            else:
                original_auth = tx.run(
                    "MATCH (r:ArenaWorkflowRun "
                    + _SCOPE
                    + ")-[:HAS_INTENT]->(i:ArenaExecutionIntent) "
                    "WHERE r.run_id=$id RETURN i.authorization_json AS auth, r.admitted_at AS at",
                    **self.scope,
                    id=run_id,
                ).single(strict=True)
            if authorization.principal != AuthorizationSnapshot.model_validate_json(original_auth["auth"]).principal:
                raise ValueError("scene principal mismatch")
            if (
                (not contract.effects.allow_runtime and contract.schema_version != "4")
                or now < original_auth["at"]
                or now + intent.reservation.runtime_allowance_seconds
                > original_auth["at"] + contract.budget.total_deadline_seconds
            ):
                raise ValueError("scene effects or deadline denied")
            released = intent.model_copy(update={"status": "released", "released_at": now})
            tx.run(
                "MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ") WHERE i.intent_id=$id "
                "SET i.status='released', i.scene_json=$scene, i.authorization_json=$auth, i.readiness_json=$ready",
                **self.scope,
                id=intent_id,
                scene=released.model_dump_json(),
                auth=authorization.model_dump_json(),
                ready=readiness.model_dump_json(),
            ).consume()
            self._event(tx, run_id, "SceneEffectReleased", intent_id)
        return True

    def check_scene_release(
        self,
        run_id,
        intent_id,
        authorization,
        *,
        readiness,
        fence=None,
        registration_id=None,
    ):
        """Recheck a fresh winner before send; this read NEVER grants resend authority.

        Trusted send still serializes local cancellation and private grant revocation
        with its held-lease/exact-registration check under the authority release guard.
        """
        with self._transaction() as tx:
            self._lock(tx)
            s = self._scene_snapshot(tx, run_id)
            if (
                s is None
                or s.intent is None
                or s.intent.intent_id != intent_id
                or s.intent.status != "released"
                or s.run.state != "running"
            ):
                raise ValueError("inactive scene release")
            if s.intent.policy_binding is not None and self._now() >= s.intent.policy_binding.deadline_unix:
                raise ValueError("policy trial deadline exhausted")
            stored = self._intent(tx, intent_id)
            if stored.get("authorization_json") != authorization.model_dump_json():
                raise ValueError("scene release authorization changed")
            if s.profile.owned_worker:
                if fence is None or s.intent.worker_fence != fence:
                    raise ValueError("scene worker fence mismatch")
                self._fenced_scene(tx, fence)
                if (
                    s.intent.worker_registration is None
                    or s.intent.worker_registration.registration_id != registration_id
                    or s.intent.worker_cleanup is not None
                ):
                    raise ValueError("inactive scene worker registration")
            contract = parse_contract(s.run.contract_json)
            now = self._now()
            self._scene_authority(contract, authorization, now)
            self._readiness(contract, readiness, now)
            admitted = tx.run(
                "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") WHERE r.run_id=$id RETURN r.admitted_at AS at",
                **self.scope,
                id=run_id,
            ).single()["at"]
            if (
                now < admitted
                or now + s.intent.reservation.runtime_allowance_seconds
                > admitted + contract.budget.total_deadline_seconds
            ):
                raise ValueError("scene deadline exhausted")
            return s.intent

    def mark_scene_unknown(self, run_id, intent_id):
        """Retain uncertain released effects without retry, refund or cleanup claims."""
        with self._transaction() as tx:
            self._lock(tx)
            s = self._scene_snapshot(tx, run_id)
            if s is None or s.intent is None or s.intent.intent_id != intent_id:
                raise ValueError("unknown scene intent")
            if s.intent.status == "reconciliation_required":
                return False
            if s.intent.status != "released" and not (s.intent.status == "reserved" and s.intent.worker_fence):
                raise ValueError("released scene required")
            intent = s.intent.model_copy(update={"status": "reconciliation_required"})
            tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") WHERE r.run_id=$run MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ") WHERE i.intent_id=$id "
                "SET r.state=$state, r.stop_reason='released_scene_outcome_unknown', "
                "i.status='reconciliation_required', i.scene_json=$scene",
                **self.scope,
                run=run_id,
                id=intent_id,
                scene=intent.model_dump_json(),
                state=(s.run.state if s.run.state in ("cancelled", "cancel_requested") else "reconciliation_required"),
            ).consume()
            self._event(tx, run_id, "SceneReconciliationRequired", intent_id)
        return True

    def finish_scene(self, run_id, intent_id, expected_version, result):
        """Retain immutable result/assessment and atomically decide/reserve next work."""
        from .scene_loop import (
            SceneDecision,
            SceneResult,
            assess_and_route,
            identity,
            repaired_candidate,
            route_capture,
        )

        result = SceneResult.model_validate_json(result.model_dump_json())
        payload = result.model_dump_json()
        with self._transaction() as tx:
            self._lock(tx)
            stored = self._intent(tx, intent_id)
            if stored["run_id"] != run_id or stored.get("kind") != "scene":
                raise ValueError("scene intent mismatch")
            if "result_json" in stored:
                if stored["result_json"] != payload:
                    raise ValueError("conflicting scene result")
                return False
            s = self._scene_snapshot(tx, run_id)
            if s.intent is None or s.intent.intent_id != intent_id or s.intent.status != "released":
                raise ValueError("released scene intent required")
            if s.run.version != expected_version or s.run.state != "running":
                raise ValueError("stale scene completion or cancellation")
            if result.codec_version != s.intent.codec_version:
                raise ValueError("scene result codec mismatch")
            if s.profile.owned_worker:
                if s.intent.worker_fence is None or s.intent.worker_cleanup is None:
                    raise ValueError("scene worker cleanup required")
                self._fenced_scene(tx, s.intent.worker_fence)
            candidate = s.candidate
            contract = parse_contract(s.run.contract_json)
            selected_evidence_id = None
            if contract.schema_version != "4" and result.retained_assessment_json is not None:
                raise ValueError("Retained assessment result requires schema 4")
            if contract.schema_version == "4":
                if result.retained_assessment_json is None or any(
                    (result.failure, result.observation, result.candidate_json, result.policy_trial)
                ):
                    raise ValueError("Retained-only assessment result required")
                outcome = json.loads(result.retained_assessment_json)
                if (
                    outcome["consumer_contract_digest"] != contract_digest(contract)
                    or outcome["producer"] != contract.retained_evidence.model_dump(mode="json")
                    or outcome["producer_evidence_id"] != s.intent.observation_id
                ):
                    raise ValueError("Retained assessment result changed its source")
                retry = not outcome["complete"] and outcome["retryable"]
                decision = SceneDecision(
                    action="assess" if retry else "stop",
                    reason="retained_visibility_complete" if outcome["complete"] else outcome["validation_error"],
                )
            elif result.failure:
                decision = SceneDecision(action="stop", reason=result.failure)
                if s.intent.action == "policy":
                    observation = self._scene_capture(tx, run_id, s.intent)
                    prerequisite = assess_and_route(contract, candidate, observation, s.profile)
                    if prerequisite.action != "policy" or prerequisite.assessment != s.decision.assessment:
                        raise ValueError("policy prerequisite assessment mismatch")
                    decision = SceneDecision(
                        action="stop",
                        reason=result.failure,
                        assessment=prerequisite.assessment,
                        scene_disposition=prerequisite.scene_disposition,
                    )
                    selected_evidence_id = self._retain_policy_prerequisites(
                        tx, run_id, intent_id, candidate, observation, prerequisite.assessment
                    )
            elif (
                s.intent.action == "policy"
                and result.policy_trial is not None
                and result.observation is None
                and result.candidate_json is None
            ):
                from .scene_loop import policy_compatible

                trial = result.policy_trial
                if (
                    trial.intent_id != intent_id
                    or not policy_compatible(contract, s.profile)
                    or trial.binding != s.intent.policy_binding
                    or trial.binding.candidate_digest != candidate.digest
                    or trial.binding.contract_digest != contract_digest(contract)
                    or trial.binding.seed != contract.execution.seed
                ):
                    raise ValueError("policy trial frozen binding mismatch")
                observation = self._scene_capture(tx, run_id, s.intent)
                prerequisite = assess_and_route(contract, candidate, observation, s.profile)
                if prerequisite.action != "policy" or prerequisite.assessment != s.decision.assessment:
                    raise ValueError("policy prerequisite assessment mismatch")
                outcome = trial.aggregate().outcome
                expired = self._now() >= trial.binding.deadline_unix
                decision = SceneDecision(
                    action="accept" if outcome == "passed" and not expired else "stop",
                    reason="policy_" + ("deadline_exceeded" if expired else outcome),
                    assessment=prerequisite.assessment,
                    policy_trial=trial,
                    scene_disposition=prerequisite.scene_disposition,
                )
                selected_evidence_id = self._retain_policy_prerequisites(
                    tx, run_id, intent_id, candidate, observation, prerequisite.assessment
                )
            elif (
                s.intent.action in ("observe", "capture", "assess")
                and result.observation is not None
                and result.candidate_json is None
                and result.policy_trial is None
            ):
                observation = result.observation
                previous = list(
                    tx.run(
                        "MATCH (e:ArenaWorkflowEvidence "
                        + _SCOPE
                        + ") WHERE e.run_id=$run RETURN e.payload AS payload",
                        **self.scope,
                        run=run_id,
                    )
                )
                old = [json.loads(r["payload"])["cohort"] for r in previous]
                if s.intent.action == "assess":
                    capture = self._scene_capture(tx, run_id, s.intent)
                    if (
                        observation.cohort != capture.cohort
                        or not all(e in observation.evidence for e in capture.evidence)
                        or not set(capture.verified_manifest_digests) <= set(observation.verified_manifest_digests)
                        or (capture.static_failure is not None and capture.static_failure != observation.static_failure)
                    ):
                        raise ValueError("assessment changed retained capture")
                    decision = assess_and_route(contract, candidate, observation, s.profile)
                elif any(c["realization_id"] == observation.cohort.realization_id for c in old):
                    decision = SceneDecision(action="stop", reason="stale_cohort")
                elif s.intent.action == "capture":
                    decision = route_capture(contract, candidate, observation)
                else:
                    decision = assess_and_route(contract, candidate, observation, s.profile)
                self._scene_node(
                    tx,
                    "ArenaWorkflowEvidence",
                    identity(intent_id, "observation"),
                    observation.model_dump_json(),
                    run_id,
                )
                if s.intent.codec_version == 2 and decision.assessment is None:
                    tx.run(
                        "MATCH (e:ArenaWorkflowEvidence "
                        + _SCOPE
                        + ") WHERE e.record_id=$evidence MATCH (c:ArenaWorkflowCandidate "
                        + _SCOPE
                        + ") WHERE c.record_id=$candidate CREATE (e)-[:FOR_CANDIDATE]->(c)",
                        **self.scope,
                        evidence=identity(intent_id, "observation"),
                        candidate=candidate.candidate_id,
                    ).consume()
                if decision.assessment is not None:
                    self._scene_node(
                        tx,
                        "ArenaCriterionAssessment",
                        identity(intent_id, "assessment"),
                        decision.assessment.model_dump_json(),
                        run_id,
                    )
                    tx.run(
                        "MATCH (a:ArenaCriterionAssessment "
                        + _SCOPE
                        + ") WHERE a.record_id=$assessment MATCH (e:ArenaWorkflowEvidence "
                        + _SCOPE
                        + ") WHERE e.record_id=$evidence MATCH (c:ArenaWorkflowCandidate "
                        + _SCOPE
                        + ") WHERE c.record_id=$candidate CREATE (a)-[:ASSESSES]->(e), (e)-[:FOR_CANDIDATE]->(c)",
                        **self.scope,
                        assessment=identity(intent_id, "assessment"),
                        evidence=identity(intent_id, "observation"),
                        candidate=candidate.candidate_id,
                    ).consume()
            elif s.intent.action == "repair" and result.candidate_json is not None and result.observation is None:
                try:
                    candidate = repaired_candidate(
                        contract,
                        s.original,
                        s.candidate,
                        json.loads(result.candidate_json),
                        source_id=intent_id,
                    )
                except ValueError:
                    decision = SceneDecision(action="stop", reason="repair_rejected")
                else:
                    self._scene_node(
                        tx,
                        "ArenaWorkflowCandidate",
                        candidate.candidate_id,
                        candidate.model_dump_json(),
                        run_id,
                    )
                    tx.run(
                        "MATCH (c:ArenaWorkflowCandidate "
                        + _SCOPE
                        + ") WHERE c.record_id=$child MATCH (p:ArenaWorkflowCandidate "
                        + _SCOPE
                        + ") WHERE p.record_id=$parent MATCH (o:ArenaWorkflowCandidate "
                        + _SCOPE
                        + ") WHERE o.record_id=$original CREATE (c)-[:DERIVED_FROM]->(p), (c)-[:ORIGINAL]->(o)",
                        **self.scope,
                        child=candidate.candidate_id,
                        parent=candidate.parent_id,
                        original=candidate.original_id,
                    ).consume()
                    decision = SceneDecision(action="observe", reason="fresh_child_cohort_required")
            else:
                raise ValueError("scene result action mismatch")
            produced = s.intent.model_copy(update={"status": "produced"})
            tx.run(
                "MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ") WHERE i.intent_id=$id SET i.status='produced', i.scene_json=$scene, i.result_json=$result",
                **self.scope,
                id=intent_id,
                scene=produced.model_dump_json(),
                result=payload,
            ).consume()
            self._scene_decide(
                tx,
                s.run,
                candidate,
                decision,
                s.profile,
                identity(intent_id, "observation") if result.observation is not None else selected_evidence_id,
            )
        return True

    def _retain_policy_prerequisites(self, tx, run_id, intent_id, candidate, observation, assessment):
        """Retain selected scene facts for a policy disposition without another capture."""
        from .scene_loop import identity

        evidence_id = identity(intent_id, "observation")
        assessment_id = identity(intent_id, "assessment")
        self._scene_node(tx, "ArenaWorkflowEvidence", evidence_id, observation.model_dump_json(), run_id)
        self._scene_node(tx, "ArenaCriterionAssessment", assessment_id, assessment.model_dump_json(), run_id)
        tx.run(
            "MATCH (a:ArenaCriterionAssessment "
            + _SCOPE
            + ") WHERE a.record_id=$assessment MATCH (e:ArenaWorkflowEvidence "
            + _SCOPE
            + ") WHERE e.record_id=$evidence MATCH (c:ArenaWorkflowCandidate "
            + _SCOPE
            + ") WHERE c.record_id=$candidate CREATE (a)-[:ASSESSES]->(e), (e)-[:FOR_CANDIDATE]->(c)",
            **self.scope,
            assessment=assessment_id,
            evidence=evidence_id,
            candidate=candidate.candidate_id,
        ).consume()
        return evidence_id

    def unprepared_owner_snapshot(self, run_id):
        """Read a bounded continuation obligation set; caller must hold the OS lease.

        No claimed, registered, released or unknown work may be transferred. Past
        produced workers still require independent physical verification by caller.
        """
        from .scene_loop import SceneIntent

        with self._transaction() as tx:
            self._lock(tx)
            run = self._run(tx, "run_id", run_id)
            if run is None or run.state not in ("pending", "running"):
                raise ValueError("Active continuation required")
            owner = self._owner_view(tx)
            if owner is None or not owner.dirty:
                raise ValueError("Active unprepared owner required")
            rows = list(
                tx.run(
                    "MATCH (i:ArenaExecutionIntent " + _SCOPE + ") RETURN properties(i) AS intent LIMIT 1001",
                    **self.scope,
                )
            )
            if len(rows) > 1000:
                raise ValueError("Continuation obligation bound exceeded")
            registrations = []
            for row in rows:
                i = row["intent"]
                if i.get("kind") == "scene":
                    intent = SceneIntent.model_validate_json(i["scene_json"])
                    fence, registration, cleanup = (
                        intent.worker_fence,
                        intent.worker_registration,
                        intent.worker_cleanup,
                    )
                    status = intent.status
                else:
                    fence = AttemptFence.model_validate_json(i["fence_json"]) if i.get("fence_json") else None
                    registration = (
                        WorkerRegistration.model_validate_json(i["registration_json"])
                        if i.get("registration_json")
                        else None
                    )
                    cleanup = CleanupEvidence.model_validate_json(i["cleanup_json"]) if i.get("cleanup_json") else None
                    status = i["status"]
                if fence is None:
                    if i["run_id"] != run_id or status != "reserved" or registration is not None or cleanup is not None:
                        raise ValueError("Unknown unprepared scope obligation")
                    continue
                if (fence.owner_id, fence.owner_epoch) != (owner.owner_id, owner.owner_epoch):
                    if self._retired_owner(tx, fence.owner_id) != fence.owner_epoch:
                        raise ValueError("Foreign active owner obligation")
                    continue
                if i["run_id"] != run_id or status != "produced" or registration is None or cleanup is None:
                    raise ValueError("Prepared or uncertain continuation forbidden")
                if registration.fence != fence or cleanup.registration != registration:
                    raise ValueError("Exact settled cleanup binding required")
                registrations.append(registration)
            return owner, tuple(sorted(registrations, key=lambda r: r.registration_id))

    def get_owner(self):
        """Read nonsecret active/last-retired identity; None means never owned.

        Neither absence nor dirty=False proves OS cleanup or permits takeover.
        """
        with self._transaction() as tx:
            self._lock(tx)
            return self._owner_view(tx)

    def get_retired_owner(self, owner_id):
        """Read an immutable retirement without claiming or changing the current owner."""
        validate_operation_id(owner_id)
        with self._transaction() as tx:
            epoch = self._retired_owner(tx, owner_id)
            return None if epoch is None else OwnerView(owner_id=owner_id, owner_epoch=epoch, dirty=False)

    def _owner_view(self, tx):
        row = tx.run(
            _CONTROL + "RETURN c.owner_id AS owner_id, c.owner_epoch AS owner_epoch, c.owner_dirty AS dirty",
            **self.scope,
        ).single(strict=True)
        return OwnerView(**dict(row)) if row["owner_id"] is not None else None

    def _retired_owner(self, tx, owner_id):
        rows = list(
            tx.run(
                "MATCH (o:ArenaRetiredWorkflowOwner "
                + _SCOPE
                + ") WHERE o.owner_id=$owner RETURN o.owner_epoch AS epoch LIMIT 2",
                **self.scope,
                owner=owner_id,
            )
        )
        if len(rows) > 1:
            raise ValueError("ambiguous retired owner")
        return rows[0]["epoch"] if rows else None

    def _require_settled_scope(self, tx):
        scene_obligations = list(
            tx.run(
                "MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ") WHERE i.kind='scene' MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") WHERE r.run_id=i.run_id RETURN i.status AS status, r.state AS state, "
                "i.scene_json AS scene, r.scene_profile AS profile LIMIT 1001",
                **self.scope,
            )
        )
        from .scene_loop import SceneIntent, ScenePortProfile

        if len(scene_obligations) > 1000:
            raise ValueError("unresolved scene obligations")
        for row in scene_obligations:
            intent = SceneIntent.model_validate_json(row["scene"])
            profile = ScenePortProfile.model_validate_json(row["profile"])
            if profile.owned_worker and (
                intent.worker_fence is None
                or intent.worker_registration is None
                or intent.worker_cleanup is None
                or intent.worker_registration.fence != intent.worker_fence
                or intent.worker_cleanup.registration != intent.worker_registration
            ):
                raise ValueError("unresolved scene cleanup obligations")
            settled = row["status"] == "produced" and row["state"] in (
                "accepted",
                "stopped",
            )
            cancelled = row["state"] == "cancelled" and intent.worker_cleanup is not None
            if not (settled or cancelled):
                raise ValueError("unresolved scene obligations")
        # Conservative, bounded gate: even an unregistered claim may have spawned
        # a prepared process. Unclaimed reservations and malformed/orphan records
        # also require reconciliation; absence is never manufactured stop evidence.
        rows = list(
            tx.run(
                "MATCH (i:ArenaExecutionIntent "
                + _SCOPE
                + ") WHERE coalesce(i.kind, 'generation') <> 'scene' "
                "OPTIONAL MATCH (i)-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
                "RETURN properties(i) AS intent, properties(a) AS attempt LIMIT 1001",
                **self.scope,
            )
        )
        count = tx.run(
            "MATCH (a:ArenaExecutionAttempt " + _SCOPE + ") RETURN count(a) AS n",
            **self.scope,
        ).single(
            strict=True
        )["n"]
        if len(rows) > 1000 or count != len(rows):
            raise ValueError("unresolved or excessive owner obligations")
        seen = set()
        for row in rows:
            intent, attempt = row["intent"], row["attempt"]
            if (
                attempt is None
                or not attempt.get("registration_json")
                or not attempt.get("cleanup_json")
                or attempt.get("status") not in ("produced", "cancelled")
                or intent.get("status") != attempt["status"]
                or intent.get("registration_json") != attempt["registration_json"]
                or intent.get("cleanup_json") != attempt["cleanup_json"]
            ):
                raise ValueError("unresolved owner obligations")
            fence = AttemptFence.model_validate_json(attempt["fence_json"])
            if fence.attempt_id in seen:
                raise ValueError("unresolved ambiguous owner obligations")
            seen.add(fence.attempt_id)
            view = self._attempt_view(tx, fence)
            run = self._run(tx, "run_id", fence.run_id)
            if view.registration.fence != fence or view.cleanup.registration != view.registration:
                raise ValueError("unresolved cleanup binding")
            if view.status == "cancelled":
                if run.state != "cancelled":
                    raise ValueError("unresolved cancellation")
            elif (
                not view.released
                or view.receipt is None
                or view.receipt.fence != fence
                or view.receipt.registration != view.registration
                or view.receipt.contract_digest != contract_digest(parse_contract(run.contract_json))
                or view.receipt.generation_profile != parse_contract(run.contract_json).execution.generation_model
                or attempt.get("receipt_disposition") != "produced"
                or (
                    (run.state, run.phase) != ("running", "validation")
                    and not (run.state in ("accepted", "stopped") and run.phase == "scene")
                )
            ):
                raise ValueError("unresolved generation outcome")

    def retire_owner(self, expected_owner, expected_epoch):
        """Retire a clean owner; True is a new commit, False an exact retained replay.

        Caller MUST hold the trusted physical lease and verify local cleanup,
        including prepared/unregistered workers. DB checks are NOT OS proof.
        Commit and read back retirement before releasing the caller's flock. On
        OutcomeUnknown retain the lease and reconcile this exact identity/epoch;
        never infer retirement from absence or retry external work. This does not
        refund budget, reconcile remote effects, stop processes or allow takeover.
        """
        validate_operation_id(expected_owner)
        if type(expected_epoch) is not int or expected_epoch < 1:
            raise ValueError("positive owner epoch required")
        with self._transaction() as tx:
            self._lock(tx)
            retired = self._retired_owner(tx, expected_owner)
            if retired is not None:
                if retired != expected_epoch:
                    raise ValueError("stale retirement epoch")
                return False
            self._owner(tx, expected_owner, expected_epoch)
            self._require_settled_scope(tx)
            tx.run(
                _CONTROL
                + "SET c.owner_dirty=false CREATE (o:ArenaRetiredWorkflowOwner "
                + _SCOPE
                + ") SET o.owner_id=$owner, o.owner_epoch=$epoch",
                **self.scope,
                owner=expected_owner,
                epoch=expected_epoch,
            ).consume()
        return True

    def begin_owner(self, owner_id):
        """Begin a fresh epoch only after clean retirement; active replay is unchanged.

        Composition MUST hold the physical owner lease. Dirty takeover is never
        supported; retired IDs are permanently unavailable, even after later owners.
        """
        validate_operation_id(owner_id)
        with self._transaction() as tx:
            self._lock(tx)
            if self._retired_owner(tx, owner_id) is not None:
                raise ValueError("retired owner cannot reopen")
            owner = self._owner_view(tx)
            if owner is not None and owner.dirty:
                if owner.owner_id != owner_id:
                    raise ValueError("dirty owner requires reconciliation; takeover unsupported")
                return owner.owner_epoch
            if owner is not None and self._retired_owner(tx, owner.owner_id) != owner.owner_epoch:
                raise ValueError("exact prior retirement required")
            epoch = 1 if owner is None else owner.owner_epoch + 1
            tx.run(
                _CONTROL + "SET c.owner_id=$owner, c.owner_epoch=$epoch, c.owner_dirty=true",
                **self.scope,
                owner=owner_id,
                epoch=epoch,
            ).consume()
        return epoch

    def _page_boundary(self, tx, expected, *, candidates=False, decisions=False):
        from .paging import CorruptPage, physical_counter

        boundary = self._lock(tx, bounded=True)
        retained = self._scope_binding(tx)
        if retained != expected:
            raise SubmissionConflict("Scope binding differs")
        floor = physical_counter(boundary["floor"])
        ceiling = physical_counter(boundary["ceiling"])
        if int(floor) > int(ceiling):
            raise CorruptPage()
        # Existing unique RANGE backing indexes suffice. No DDL or waiting.
        indexes = list(
            tx.run("SHOW INDEXES YIELD entityType, type, state, labelsOrTypes, properties, owningConstraint RETURN *")
        )
        for label, key in (("ArenaWorkflowRun", "run_id"), ("ArenaWorkflowEvent", "sequence")):
            if not any(
                r["entityType"] == "NODE"
                and r["type"] == "RANGE"
                and r["state"] == "ONLINE"
                and r["owningConstraint"] is not None
                and r["labelsOrTypes"] == [label]
                and r["properties"] == ["deployment_id", "workspace_id", key]
                for r in indexes
            ):
                raise SchemaMissing("Online unique page index required")
        if candidates:
            for keys in (("record_id",), ("run_id", "record_id")):
                if not any(
                    r["entityType"] == "NODE"
                    and r["type"] == "RANGE"
                    and r["state"] == "ONLINE"
                    and r["owningConstraint"] is None
                    and r["labelsOrTypes"] == ["ArenaWorkflowCandidate"]
                    and r["properties"] == ["deployment_id", "workspace_id", *keys]
                    for r in indexes
                ):
                    raise SchemaMissing("Online nonunique candidate page index required")
        if decisions and not any(
            r["entityType"] == "NODE"
            and r["type"] == "RANGE"
            and r["state"] == "ONLINE"
            and r["owningConstraint"] is None
            and r["labelsOrTypes"] == ["ArenaWorkflowDecision"]
            and r["properties"] == ["deployment_id", "workspace_id", "run_id", "decision_id"]
            for r in indexes
        ):
            raise SchemaMissing("Online nonunique decision page index required")
        return retained, floor, ceiling

    def list_runs_window(self, binding, *, first=100, after=None):
        """Read one verified live run window including one validated lookahead."""
        from .paging import CorruptPage, RunPosition, RunSummary, RunWindow, physical_counter, validate_first

        binding = self._checked_scope_binding(binding)
        validate_first(first)
        if after is not None:
            after = RunPosition.model_validate_json(after.model_dump_json())
        with self._transaction(fetch_size=first + 1) as tx:
            retained, floor, ceiling = self._page_boundary(tx, binding)
            predicate = "r.run_id >= ''" if after is None else "r.run_id > $after"
            fields = (
                ("run_id", 64),
                ("operation_id", 128),
                ("state", 32),
                ("phase", 32),
                ("version", 19),
                ("event_cursor", 19),
            )
            projection = ", ".join(
                f"{key}: CASE WHEN size(toStringOrNull(r.{key}))<={cap} THEN r.{key} ELSE null END"
                for key, cap in fields
            )
            stream = tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") USING INDEX r:ArenaWorkflowRun(deployment_id, workspace_id, run_id) WHERE "
                + predicate
                + " WITH r ORDER BY r.deployment_id, r.workspace_id, r.run_id ASC LIMIT $limit RETURN {"
                + projection
                + "} AS row",
                **self.scope,
                after=None if after is None else after.position,
                limit=first + 1,
            )
            # Include the constant scope prefix in ORDER BY: Neo4j's composite
            # unique index otherwise uses an unbounded Top over the scoped range.
            rows = []
            previous = "" if after is None else after.position
            for record in stream:
                # Query execution and advancement deliberately stay outside decoding catches.
                try:
                    raw = dict(record["row"])
                    raw["run_version"] = physical_counter(raw.pop("version"), positive=True)
                    raw["event_cursor"] = physical_counter(raw["event_cursor"])
                    row = RunSummary.model_validate(raw)
                    identity = json.dumps(
                        [retained.deployment_id, retained.workspace_id, row.operation_id],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    if (
                        hashlib.sha256(identity.encode("utf-8")).hexdigest() != row.run_id
                        or row.run_id <= previous
                        or int(row.event_cursor) > int(ceiling)
                        or len(rows) >= first + 1
                    ):
                        raise ValueError()
                except (ValueError, TypeError, KeyError, RecursionError):
                    raise CorruptPage() from None
                rows.append(row)
                previous = row.run_id
            result = RunWindow(binding=retained, floor=floor, ceiling=ceiling, runs=tuple(rows))
        return result

    def list_scene_candidates_window(self, binding, run_id, *, first=100, after=None):
        """Read compact run-owned identities; historical point reads validate payloads."""
        from .paging import (
            CandidateItem,
            CandidatePosition,
            CandidateWindow,
            CorruptPage,
            CursorQueryMismatch,
            RunPosition,
            RunSummary,
            physical_counter,
            validate_first,
        )

        binding = self._checked_scope_binding(binding)
        validate_first(first)
        RunPosition(position=run_id)
        if after is not None:
            after = CandidatePosition.model_validate_json(after.model_dump_json())
            if after.run_id != run_id:
                raise CursorQueryMismatch()
        with self._transaction(fetch_size=first + 1) as tx:
            retained, floor, ceiling = self._page_boundary(tx, binding, candidates=True)
            fields = (
                ("run_id", 64),
                ("operation_id", 128),
                ("state", 32),
                ("phase", 32),
                ("version", 19),
                ("event_cursor", 19),
            )
            projection = ", ".join(
                f"{key}: CASE WHEN size(toStringOrNull(r.{key}))<={cap} THEN r.{key} ELSE null END"
                for key, cap in fields
            )
            parents = list(
                tx.run(
                    "MATCH (r:ArenaWorkflowRun "
                    + _SCOPE
                    + ") "
                    "USING INDEX r:ArenaWorkflowRun(deployment_id, workspace_id, run_id) "
                    "WHERE r.run_id=$run RETURN elementId(r) AS key, {"
                    + projection
                    + "} AS parent LIMIT 2",
                    **self.scope,
                    run=run_id,
                )
            )
            if not parents:
                return None
            if len(parents) != 1:
                raise CorruptPage()
            try:
                raw = dict(parents[0]["parent"])
                raw["run_version"] = physical_counter(raw.pop("version"), positive=True)
                raw["event_cursor"] = physical_counter(raw["event_cursor"])
                parent = RunSummary.model_validate(raw)
                identity = json.dumps(
                    [
                        retained.deployment_id,
                        retained.workspace_id,
                        parent.operation_id,
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                if (
                    parent.run_id != run_id
                    or hashlib.sha256(identity.encode("utf-8")).hexdigest() != run_id
                    or int(parent.event_cursor) > int(ceiling)
                ):
                    raise ValueError()
            except (ValueError, TypeError, KeyError, RecursionError):
                raise CorruptPage() from None
            predicate = "n.record_id >= ''" if after is None else "n.record_id > $after"
            stream = tx.run(
                "MATCH (n:ArenaWorkflowCandidate "
                + _SCOPE
                + ") "
                "USING INDEX n:ArenaWorkflowCandidate(deployment_id, workspace_id, run_id, record_id) "
                "WHERE n.run_id=$run AND "
                + predicate
                + " WITH n ORDER BY n.deployment_id, n.workspace_id, n.run_id, n.record_id ASC LIMIT $limit "
                "RETURN {candidate_id: CASE WHEN size(toStringOrNull(n.record_id))<=64 THEN n.record_id ELSE null END, "
                "run_id: CASE WHEN size(toStringOrNull(n.run_id))<=64 THEN n.run_id ELSE null END} AS row",
                **self.scope,
                run=run_id,
                after=None if after is None else after.position,
                limit=first + 1,
            )
            rows = []
            previous = "" if after is None else after.position
            for record in stream:
                try:
                    row = CandidateItem.model_validate(dict(record["row"]))
                    if row.run_id != run_id or row.candidate_id <= previous or len(rows) >= first + 1:
                        raise ValueError()
                except (ValueError, TypeError, KeyError, RecursionError):
                    raise CorruptPage() from None
                rows.append(row)
                previous = row.candidate_id
            # Drain the bounded selected stream before nested queries: the driver
            # otherwise implicitly buffers pending Bolt batches on tx.run().
            for row in rows:
                identities = list(
                    tx.run(
                        "MATCH (n:ArenaWorkflowCandidate "
                        + _SCOPE
                        + ") "
                        "USING INDEX n:ArenaWorkflowCandidate(deployment_id, workspace_id, record_id) "
                        "WHERE n.record_id=$id RETURN elementId(n) AS key LIMIT 2",
                        **self.scope,
                        id=row.candidate_id,
                    )
                )
                if len(identities) != 1:
                    raise CorruptPage()
                owners = list(
                    tx.run(
                        "MATCH (n)<-[:HAS_SCENE_RECORD]-(r) WHERE elementId(n)=$key "
                        "RETURN elementId(r)=$parent AND r:ArenaWorkflowRun AS valid LIMIT 2",
                        key=identities[0]["key"],
                        parent=parents[0]["key"],
                    )
                )
                if len(owners) != 1 or owners[0]["valid"] is not True:
                    raise CorruptPage()
            result = CandidateWindow(
                binding=retained,
                run_id=run_id,
                floor=floor,
                ceiling=ceiling,
                candidates=tuple(rows),
            )
        return result

    def list_decisions_window(self, binding, run_id, *, first=100, after=None):
        """Read live decision references; not payloads, chronology or a graph audit."""
        from .paging import (
            CorruptPage,
            CursorQueryMismatch,
            DecisionCoverageUnavailable,
            DecisionItem,
            DecisionPosition,
            DecisionWindow,
            RunPosition,
            RunSummary,
            UnsupportedDecisionCoverage,
            physical_counter,
            validate_first,
        )

        binding = self._checked_scope_binding(binding)
        validate_first(first)
        RunPosition(position=run_id)
        if after is not None:
            after = DecisionPosition.model_validate_json(after.model_dump_json())
            if after.run_id != run_id:
                raise CursorQueryMismatch()
        with self._transaction(fetch_size=first + 1) as tx:
            retained, floor, ceiling = self._page_boundary(tx, binding, decisions=True)
            fields = (
                ("run_id", 64),
                ("operation_id", 128),
                ("state", 32),
                ("phase", 32),
                ("version", 19),
                ("event_cursor", 19),
            )
            projection = ", ".join(
                f"{key}: CASE WHEN size(toStringOrNull(r.{key}))<={cap} THEN r.{key} ELSE null END"
                for key, cap in fields
            )
            parents = list(
                tx.run(
                    "MATCH (r:ArenaWorkflowRun "
                    + _SCOPE
                    + ") "
                    "USING INDEX r:ArenaWorkflowRun(deployment_id, workspace_id, run_id) "
                    "WHERE r.run_id=$run RETURN elementId(r) AS key, {"
                    + projection
                    + "} AS parent, r.decision_coverage IS NOT NULL AS coverage_present, "
                    "CASE WHEN size(toStringOrNull(r.decision_coverage))<=20 "
                    "THEN r.decision_coverage ELSE null END AS coverage LIMIT 2",
                    **self.scope,
                    run=run_id,
                )
            )
            if not parents:
                return None
            if len(parents) != 1:
                raise CorruptPage()
            try:
                raw = dict(parents[0]["parent"])
                raw["run_version"] = physical_counter(raw.pop("version"), positive=True)
                raw["event_cursor"] = physical_counter(raw["event_cursor"])
                parent = RunSummary.model_validate(raw)
                identity = json.dumps(
                    [
                        retained.deployment_id,
                        retained.workspace_id,
                        parent.operation_id,
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                if (
                    parent.run_id != run_id
                    or hashlib.sha256(identity.encode("utf-8")).hexdigest() != run_id
                    or int(parent.event_cursor) > int(ceiling)
                ):
                    raise ValueError()
            except (ValueError, TypeError, KeyError, RecursionError):
                raise CorruptPage() from None
            if parents[0]["coverage_present"] is False:
                return DecisionCoverageUnavailable(binding=retained, run_id=run_id, floor=floor, ceiling=ceiling)
            coverage = parents[0]["coverage"]
            if parents[0]["coverage_present"] is not True or type(coverage) is not int:
                raise CorruptPage()
            if coverage != 1:
                raise UnsupportedDecisionCoverage()
            predicate = "n.decision_id >= ''" if after is None else "n.decision_id > $after"
            stream = tx.run(
                "MATCH (n:ArenaWorkflowDecision "
                + _SCOPE
                + ") "
                "USING INDEX n:ArenaWorkflowDecision(deployment_id, workspace_id, run_id, decision_id) "
                "WHERE n.run_id=$run AND "
                + predicate
                + " WITH n ORDER BY n.deployment_id, n.workspace_id, n.run_id, n.decision_id ASC LIMIT $limit RETURN"
                " {decision_id: CASE WHEN size(toStringOrNull(n.decision_id))<=128 THEN n.decision_id ELSE null END,"
                " run_id: CASE WHEN size(toStringOrNull(n.run_id))<=64 THEN n.run_id ELSE null END, record_kind: CASE"
                " WHEN size(toStringOrNull(n.record_kind))<=32 THEN n.record_kind ELSE null END, membership_codec:"
                " CASE WHEN size(toStringOrNull(n.membership_codec))<=20 THEN n.membership_codec ELSE null END}"
                " AS row",
                **self.scope,
                run=run_id,
                after=None if after is None else after.position,
                limit=first + 1,
            )
            rows = []
            previous = "" if after is None else after.position
            for record in stream:
                try:
                    raw = dict(record["row"])
                    codec = raw.pop("membership_codec")
                    if type(codec) is not int or codec != 1:
                        raise ValueError()
                    row = DecisionItem.model_validate(raw)
                    if row.run_id != run_id or row.decision_id <= previous or len(rows) >= first + 1:
                        raise ValueError()
                except (ValueError, TypeError, KeyError, RecursionError):
                    raise CorruptPage() from None
                rows.append(row)
                previous = row.decision_id
            # Drain the bounded selected stream before nested queries: the driver
            # otherwise implicitly buffers pending Bolt batches on tx.run().
            for row in rows:
                identities = list(
                    tx.run(
                        "MATCH (n:ArenaWorkflowDecision "
                        + _SCOPE
                        + ") "
                        "USING INDEX n:ArenaWorkflowDecision(deployment_id, workspace_id, run_id, decision_id) "
                        "WHERE n.run_id=$run AND n.decision_id=$id RETURN elementId(n) AS key LIMIT 2",
                        **self.scope,
                        id=row.decision_id,
                        run=run_id,
                    )
                )
                if len(identities) != 1:
                    raise CorruptPage()
                owners = list(
                    tx.run(
                        "MATCH (n)<-[:HAS_DECISION]-(r) WHERE elementId(n)=$key "
                        "RETURN elementId(r)=$parent AND r:ArenaWorkflowRun AS valid LIMIT 2",
                        key=identities[0]["key"],
                        parent=parents[0]["key"],
                    )
                )
                if len(owners) != 1 or owners[0]["valid"] is not True:
                    raise CorruptPage()
            result = DecisionWindow(
                binding=retained,
                run_id=run_id,
                floor=floor,
                ceiling=ceiling,
                decisions=tuple(rows),
            )
        return result

    def read_scope_events_window(self, binding, *, first=100, after=None):
        """Read current retained bounds and at most first+1 physical event rows."""
        from .paging import (
            CorruptPage,
            EventPosition,
            EventWindow,
            FutureCursor,
            ScopeEvent,
            physical_counter,
            validate_first,
        )

        binding = self._checked_scope_binding(binding)
        validate_first(first)
        if after is not None:
            after = EventPosition.model_validate_json(after.model_dump_json())
        with self._transaction(fetch_size=first + 1) as tx:
            retained, floor, ceiling = self._page_boundary(tx, binding)
            position = floor if after is None else after.position
            if int(position) < int(floor):
                raise ReplayGap("Page cursor precedes retained floor")
            if int(position) > int(ceiling):
                raise FutureCursor()
            fields = (
                ("sequence", 19),
                ("run_id", 64),
                ("operation_id", 128),
                ("kind", 128),
                ("schema_version", 19),
                ("source_id", 128),
                ("command_kind", 128),
                ("command_operation_id", 128),
            )
            projection = ", ".join(
                f"{key}: CASE WHEN size(toStringOrNull(e.{key}))<={cap} THEN e.{key} "
                f"WHEN e.{key} IS NULL THEN null ELSE [false] END"
                for key, cap in fields
            )
            stream = tx.run(
                "MATCH (e:ArenaWorkflowEvent "
                + _SCOPE
                + ") "
                "USING INDEX e:ArenaWorkflowEvent(deployment_id, workspace_id, sequence) "
                "WHERE e.sequence > $after AND e.sequence <= $ceiling "
                "WITH e ORDER BY e.deployment_id, e.workspace_id, e.sequence ASC LIMIT $limit RETURN {"
                + projection
                + "} AS row",
                **self.scope,
                after=int(position),
                ceiling=int(ceiling),
                limit=first + 1,
            )
            rows = []
            previous = int(position)
            for record in stream:
                try:
                    raw = dict(record["row"])
                    raw["sequence"] = physical_counter(raw["sequence"])
                    row = ScopeEvent.model_validate(raw)
                    identity = json.dumps(
                        [retained.deployment_id, retained.workspace_id, row.operation_id],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    if (
                        hashlib.sha256(identity.encode("utf-8")).hexdigest() != row.run_id
                        or not previous < int(row.sequence) <= int(ceiling)
                        or len(rows) >= first + 1
                    ):
                        raise ValueError()
                except (ValueError, TypeError, KeyError, RecursionError):
                    raise CorruptPage() from None
                rows.append(row)
                previous = int(row.sequence)
            result = EventWindow(binding=retained, floor=floor, ceiling=ceiling, position=position, events=tuple(rows))
        return result

    def snapshot(self):
        """Read canonical runs and committed cursor under the shared control lock."""
        with self._transaction() as tx:
            boundary = self._lock(tx)
            runs = tuple(
                RunHandle(**row["run"])
                for row in tx.run(
                    "MATCH (r:ArenaWorkflowRun " + _SCOPE + ") RETURN " + _VIEW + " AS run ORDER BY r.run_id",
                    **self.scope,
                )
            )
            result = Snapshot(runs, boundary["ceiling"], boundary["floor"])
        return result

    def events_after(self, cursor, limit=100):
        """Read at most 1000 ordered events with floor/ceiling in the same lock boundary."""
        if type(cursor) is not int or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("integer cursor and limit between 1 and 1000 required")
        with self._transaction() as tx:
            boundary = self._lock(tx)
            if not boundary["floor"] <= cursor <= boundary["ceiling"]:
                raise ReplayGap("cursor outside retained floor/committed ceiling")
            events = tuple(
                WorkflowEvent(**row["event"])
                for row in tx.run(
                    "MATCH (e:ArenaWorkflowEvent "
                    + _SCOPE
                    + ") "
                    "WHERE e.sequence>$cursor AND e.sequence<=$ceiling "
                    "RETURN e {.sequence, .run_id, .operation_id, .kind, .schema_version, .source_id, "
                    ".command_kind, .command_operation_id} AS event "
                    "ORDER BY e.sequence LIMIT $limit",
                    **self.scope,
                    cursor=cursor,
                    ceiling=boundary["ceiling"],
                    limit=limit,
                )
            )
            result = EventPage(
                events,
                events[-1].sequence if events else cursor,
                boundary["floor"],
                boundary["ceiling"],
            )
        return result

    @staticmethod
    def schema_requirements():
        """Return administrator-only DDL; await indexes online before verify/open.

        Provision at the explicit quiescent admin gate, then CALL db.awaitIndexes
        with an operator-selected bounded timeout. Runtime never provisions or waits.
        """
        return (
            tuple(
                f"CREATE CONSTRAINT arena_workflow_{name} IF NOT EXISTS FOR (n:{label}) "
                f"REQUIRE ({', '.join('n.' + field for field in fields)}) IS UNIQUE"
                for name, label, fields in _KEYS
            )
            + tuple(
                f"CREATE INDEX arena_workflow_history_{name} IF NOT EXISTS FOR (n:{label}) "
                f"ON (n.deployment_id, n.workspace_id, n.{field})"
                for name, label, field in _HISTORY_INDEXES
            )
            + (
                (
                    "CREATE INDEX arena_workflow_decision_run_id IF NOT EXISTS FOR"
                    " (n:ArenaWorkflowDecision) ON (n.deployment_id, n.workspace_id, n.run_id, n.decision_id)"
                ),
                (
                    "CREATE INDEX arena_workflow_candidate_run_record IF NOT EXISTS FOR"
                    " (n:ArenaWorkflowCandidate) ON (n.deployment_id, n.workspace_id, n.run_id, n.record_id)"
                ),
                (
                    "CREATE INDEX arena_workflow_profile_revision_scope IF NOT EXISTS FOR"
                    " (n:ArenaWorkflowProfileRevision) ON (n.deployment_id, n.workspace_id)"
                ),
                (
                    "CREATE INDEX arena_workflow_event_run_kind_sequence IF NOT EXISTS FOR"
                    " (n:ArenaWorkflowEvent) ON (n.deployment_id, n.workspace_id, n.run_id, n.kind, n.sequence)"
                ),
            )
        )
