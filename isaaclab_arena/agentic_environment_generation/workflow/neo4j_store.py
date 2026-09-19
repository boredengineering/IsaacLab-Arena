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
            self._event(tx, run_id, "CancellationRequested", run_id)
            result = self._run(tx, "run_id", run_id)
        return result

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
                    "i.scene_json AS scene, i.result_json AS result ORDER BY i.intent_id LIMIT 1001",
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

    def _scene_decide(self, tx, run, candidate, decision, profile, selected_evidence_id=None):
        from .scene_loop import SceneDecision, SceneIntent, identity

        contract = parse_contract(run.contract_json)
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
        if now < admitted or now >= admitted + b.total_deadline_seconds:
            decision = SceneDecision(action="stop", reason="budget_exhausted", assessment=decision.assessment)
        allowance = getattr(profile, decision.action, None) if decision.action in ("observe", "repair") else None
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
            }
            invalid = any(
                sum(c.get(key, 0) for c in charged) + getattr(allowance, key) > limit for key, limit in limits.items()
            )
            invalid |= (
                not 0 < allowance.runtime_allowance_seconds <= b.per_operation_timeout_seconds
                or now + allowance.runtime_allowance_seconds > admitted + b.total_deadline_seconds
            )
            if decision.action == "observe":
                invalid |= allowance.realizations < 1 or allowance.observations < 1
                required_steps = max(
                    c.observation_window.end_step for c in contract.criteria if c.requirement == "required"
                )
                invalid |= allowance.steps < required_steps
            else:
                invalid |= allowance.candidates < 1 or allowance.revisions < 1
            if invalid:
                decision = SceneDecision(
                    action="stop",
                    reason="budget_exhausted",
                    assessment=decision.assessment,
                )
                allowance = None
        decision_id = identity(run.run_id, run.version, "scene-decision")
        intent = None
        if allowance is not None:
            intent = SceneIntent(
                intent_id=identity(decision_id, "intent"),
                candidate_id=candidate.candidate_id,
                action=decision.action,
                status="reserved",
                reservation=allowance,
            )
            tx.run(
                "MATCH (r:ArenaWorkflowRun "
                + _SCOPE
                + ") WHERE r.run_id=$run CREATE (r)-[:HAS_SCENE_INTENT]->(i:ArenaExecutionIntent "
                + _SCOPE
                + ") "
                "SET i.intent_id=$id, i.run_id=$run, i.kind='scene', i.status='reserved', "
                "i.scene_json=$scene, i.reservation_json=$reservation",
                **self.scope,
                run=run.run_id,
                id=intent.intent_id,
                scene=intent.model_dump_json(),
                reservation=allowance.model_dump_json(),
            ).consume()
        tx.run(
            "MATCH (r:ArenaWorkflowRun "
            + _SCOPE
            + ") WHERE r.run_id=$run CREATE (r)-[:HAS_DECISION]->(d:ArenaWorkflowDecision "
            + _SCOPE
            + ") "
            "SET d.decision_id=$id, d.payload=$decision, d.candidate_id=$candidate, d.intent_id=$intent, "
            "r.scene_decision=$decision, r.scene_candidate=$record, r.scene_intent=$intent, "
            "r.scene_evidence=$evidence, d.evidence_id=$evidence, "
            "r.state=$state, r.phase='scene', r.stop_reason=$reason",
            **self.scope,
            run=run.run_id,
            id=decision_id,
            evidence=selected_evidence_id,
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

    def begin_scene(self, run_id, expected_version, candidate, validation, profile):
        """Commit original validated bytes plus first decision/reservation atomically.

        Trusted service supplies actual-byte/schema verification; this store binds
        its receipt to the retained generation, not a caller's success boolean.
        """
        from .evidence_contracts import project_required_criteria
        from .scene_loop import CandidateRecord, SceneDecision, ScenePortProfile

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
            if run is None or run.version != expected_version or (run.state, run.phase) != ("running", "validation"):
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
            try:
                required = project_required_criteria(parse_contract(run.contract_json))
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

    def claim_scene_worker(self, run_id, intent_id, owner_id, owner_epoch):
        """Persist the prepare fence before any worker creation; never infer no process."""
        from .scene_loop import identity

        with self._transaction() as tx:
            self._lock(tx)
            self._owner(tx, owner_id, owner_epoch)
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
            self._generation_authority(contract, authorization, now)
            self._readiness(contract, readiness, now)
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
                not contract.effects.allow_runtime
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
            self._generation_authority(contract, authorization, now)
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
                state=(
                    "cancel_requested"
                    if s.run.state in ("cancelled", "cancel_requested")
                    else "reconciliation_required"
                ),
            ).consume()
            self._event(tx, run_id, "SceneReconciliationRequired", intent_id)
        return True

    def finish_scene(self, run_id, intent_id, expected_version, result):
        """Retain immutable result/assessment and atomically decide/reserve next work."""
        from .scene_loop import SceneDecision, SceneResult, assess_and_route, identity, repaired_candidate

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
            if s.profile.owned_worker:
                if s.intent.worker_fence is None or s.intent.worker_cleanup is None:
                    raise ValueError("scene worker cleanup required")
                self._fenced_scene(tx, s.intent.worker_fence)
            candidate = s.candidate
            contract = parse_contract(s.run.contract_json)
            if result.failure:
                decision = SceneDecision(action="stop", reason=result.failure)
            elif s.intent.action == "observe" and result.observation is not None and result.candidate_json is None:
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
                if any(c["realization_id"] == observation.cohort.realization_id for c in old):
                    decision = SceneDecision(action="stop", reason="stale_cohort")
                else:
                    decision = assess_and_route(contract, candidate, observation)
                self._scene_node(
                    tx,
                    "ArenaWorkflowEvidence",
                    identity(intent_id, "observation"),
                    observation.model_dump_json(),
                    run_id,
                )
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
                identity(intent_id, "observation") if result.observation is not None else None,
            )
        return True

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
