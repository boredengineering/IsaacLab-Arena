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

from .attempts import AttemptFence, AuthorizationSnapshot, GenerationReservation, ReadinessReceipt, WorkerRegistration
from .contracts import contract_digest, parse_contract
from .readiness import required_dependencies
from .results import AttemptView, CleanupEvidence, GenerationReceipt, ReconciliationReason


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

_KEYS = (
    ("control", "ArenaWorkflowControl", ("deployment_id", "workspace_id")),
    (
        "operation",
        "ArenaWorkflowRun",
        ("deployment_id", "workspace_id", "operation_id"),
    ),
    ("run", "ArenaWorkflowRun", ("deployment_id", "workspace_id", "run_id")),
    ("event", "ArenaWorkflowEvent", ("deployment_id", "workspace_id", "sequence")),
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
    def _transaction(self):
        session = self.driver.session(database=self.database)
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

    def _lock(self, tx):
        # Constant SET takes the complete write lock before the dependent increment.
        rows = list(
            tx.run(
                _CONTROL
                + "SET c.lock_anchor=true SET c.revision=c.revision+1 RETURN c.floor AS floor, c.sequence AS ceiling",
                **self.scope,
            )
        )
        if len(rows) != 1:
            raise ScopeMissing("scope must be explicitly initialized")
        return rows[0]

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

    def get_run(self, run_id):
        """Return the single canonical run view in this scope."""
        _identifier(run_id)
        with self._transaction() as tx:
            self._lock(tx)
            result = self._run(tx, "run_id", run_id)
        return result

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
                        "r.admitted_at=$admitted_at, r.phase='dependency_readiness' "
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

    def _event(self, tx, run_id, kind, source_id):
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
            "e.kind=$kind, e.schema_version=1, e.source_id=$source_id",
            **self.scope,
            run_id=run_id,
            kind=kind,
            source_id=source_id,
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
                "d.decision_id=$decision, d.intent_id=$id, d.payload=$payload, r.state='running', r.phase='generation'",
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
        row = tx.run(
            "MATCH (i:ArenaExecutionIntent " + _SCOPE + ") WHERE i.intent_id=$id RETURN properties(i) AS intent",
            **self.scope,
            id=intent_id,
        ).single()
        if row is None:
            raise ValueError("unknown scoped intent")
        return row["intent"]

    def claim_intent(self, intent_id, owner_id, owner_epoch):
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
        intent = self._fenced_intent(tx, fence)
        row = tx.run(
            "MATCH (i:ArenaExecutionIntent "
            + _SCOPE
            + ")-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
            "WHERE i.intent_id=$id AND a.attempt_id=$attempt RETURN properties(a) AS attempt",
            **self.scope,
            id=fence.intent_id,
            attempt=fence.attempt_id,
        ).single()
        if row is None or row["attempt"].get("fence_json") != fence.model_dump_json():
            raise ValueError("exact attempt required")
        return intent, row["attempt"]

    def get_attempt(self, fence):
        """Read exact retained bindings; this confers no execution authority."""
        fence = AttemptFence.model_validate_json(fence.model_dump_json())
        with self._transaction() as tx:
            self._lock(tx)
            intent, attempt = self._attempt(tx, fence)
            run = self._run(tx, "run_id", fence.run_id)
            return AttemptView(
                fence=fence,
                contract_json=run.contract_json,
                registration=(
                    WorkerRegistration.model_validate_json(attempt["registration_json"])
                    if "registration_json" in attempt
                    else None
                ),
                authorization=AuthorizationSnapshot.model_validate_json(intent["authorization_json"]),
                released="released_at" in attempt,
                status=attempt["status"],
                reconciliation_reason=attempt.get("reconciliation_reason"),
                receipt=(
                    GenerationReceipt.model_validate_json(attempt["receipt_json"])
                    if "receipt_json" in attempt
                    else None
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
                status="cancelled" if run.state == "cancelled" else "reconciliation_required",
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
            if run.state not in ("running", "reconciliation_required", "cancel_requested", "cancelled"):
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
                _, attempt = self._attempt(tx, fence)
                self._complete_generation(tx, fence, attempt, self._run(tx, "run_id", run_id))
            self._event(tx, run_id, "CancellationRequested", run_id)
            result = self._run(tx, "run_id", run_id)
        return result

    def begin_owner(self, owner_id):
        """Persist one dirty local owner; exact replay never renews its epoch.

        No timeout takeover or owner clearing is supported. Composition must hold
        the local owner lease; a database identity is not OS ownership.
        """
        validate_operation_id(owner_id)
        with self._transaction() as tx:
            self._lock(tx)
            row = tx.run(
                _CONTROL + "RETURN c.owner_id AS owner, c.owner_epoch AS epoch",
                **self.scope,
            ).single()
            if row["owner"] is not None and row["owner"] != owner_id:
                raise ValueError("dirty owner requires reconciliation; takeover unsupported")
            epoch = row["epoch"] or 1
            tx.run(
                _CONTROL + "SET c.owner_id=$owner, c.owner_epoch=$epoch, c.owner_dirty=true",
                **self.scope,
                owner=owner_id,
                epoch=epoch,
            ).consume()
        return epoch

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
                    "RETURN e {.sequence, .run_id, .operation_id, .kind, .schema_version} AS event "
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
        """Return administrator-only DDL; never execute it at runtime."""
        return tuple(
            f"CREATE CONSTRAINT arena_workflow_{name} IF NOT EXISTS FOR (n:{label}) "
            f"REQUIRE ({', '.join('n.' + field for field in fields)}) IS UNIQUE"
            for name, label, fields in _KEYS
        )
