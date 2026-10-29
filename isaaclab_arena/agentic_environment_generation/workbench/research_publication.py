# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Durable publication fencing, separate from immutable research intents.

Only explicit initialize creates tables; attaching never recovers or owns Journal.
Every public write requires the trusted caller's protect_public callback. Bounded
JSON and obvious credential-key rejection are defense in depth, NOT general secret
detection. Authorizers/transport comparators are trusted synchronous callbacks;
never pass user-supplied callables. This module does not open a graph connection.

Background API (explicit opt-in, no process or graph IO):
* initialize_worker_support() -> None; worker_support_ready() -> bool (incompatible
  versions raise). Core schema remains v1; worker meta/requests/workers are v1.
* get_acceptance(request_id) -> AcceptanceRequest | None.
* accept_request(effect_id, request_id, grant_metadata, *, owner_session, principal,
  store_id, operation, request_digest, previous_request_id=None) ->
  {accepted_new: bool, accepted: AcceptanceRequest, state: current_state}.
  AcceptanceRequest is immutable public {schema_version, registry_id, effect_id,
  request_id, owner_session, principal, store_id, operation, request_digest,
  previous_request_id, attempt_id, generation, capability}. Digest MUST describe
  public request content only, never credentials or their derived hashes.
  Caller authenticates declared ownership; exact replay does not authorize dispatch.
* record_worker(effect_id, attempt_id, generation, capability, pid, identity) -> bool.
* pending_workers() -> list[{schema_version, effect_id, attempt_id, generation,
  capability, pid, identity, released: bool, callback_open: bool, cleaned: bool}].
* worker_cleaned(effect_id, attempt_id, generation, *, worker_identity) -> bool.
* release_worker(effect_id, attempt_id, generation, *, worker_identity,
  grant_metadata, prepare_private) -> bytes | None. prepare_private(config, intent)
  synchronously serializes 1..2097152 private bytes; result escapes only after commit.
* complete_worker_verified(effect_id, attempt_id, generation, *, worker_identity,
  receipt, comparator=None) -> bool; close_worker_unknown(effect_id, attempt_id,
  generation, *, worker_identity) -> bool. Both require current released worker.
  Accept verified evidence BEFORE cleanup acknowledgement; cleanup fences all later
  callbacks and pauses unsent claims or closes released outcomes as unknown.
* recover_worker_dispatch() -> number of effects fenced/paused, before external
  cleanup. It retains every worker identity, never grants, spawns, or replays.

Legacy public API (unchanged for synchronous-only requests):
* PublicationAttempts(journal, registry, initialize=False, *, clock=time.time,
  protect_public=None, authorizer=None). protect_public(value) raises on secrets;
  it may return None or the unchanged value, but must not mutate/redact bindings.
* claim(effect_id, request_id, grant_metadata) and renew(...,
  previous_request_id=...) return immutable acceptance snapshots. Replay returns
  that original snapshot even after release/expiry; it is NOT dispatch permission.
* release(effect_id, attempt_id, generation, *, grant_metadata), mark_unknown(...),
  block_authorization(...), complete_verified(..., receipt=..., comparator=...)
  return bool (False is stale/ineligible). Invalid scope/conflicting replay raises
  ValueError; release returning True alone permits one write.
* claim_reconciliation(effect_id, request_id, grant_metadata) returns a new current
  identity, superseding old callbacks. finish_reconciliation_unknown(...) closes
  that read, never the publication outcome or write fence.
* cancel(effect_id), get_state(effect_id) return detached public snapshots.
  recover() returns the number explicitly paused/fenced; construction never calls it.
* execute_write/execute_reconciliation(effect_id, attempt_id, generation, *,
  grant_metadata, operation, comparator) run synchronous injected callbacks once.
  operation(private_config, immutable_intent) returns the receipt below (read may
  return None or status='unknown'); exceptions are re-raised, not persisted.

Grant metadata requires grant_id, request_id, effect_id, target_profile,
 payload_sha256, capability ('graph_write' or 'graph_read'), expires_at (epoch).
The low-level methods trust these to be authenticated by the adapter. Optional
 authorizer(metadata, *, capability, effect_id, request_id, attempt_id, generation)
returns (detached_private_config, exact_approved_metadata); operation helpers
require it. No private configuration is persisted. Async worker preparation and
source/config release hooks remain the parent's responsibility.

State JSON has schema_version=1, effect_id, target_profile, payload_sha256,
state, cancelled (independent bool), generation, attempt_id, request_id, receipt,
write_claim_count, reconciliation (null or {state}), write_callback_open (bool).
States: pending -> claimed -> released -> verified/unknown; pre-release blocking
is blocked_authorization, pre-release cancellation is terminal cancelled_no_send.
Read claims keep state=unknown; reconciliation state is claimed/released/unknown/
verified. Cancellation after write release preserves in-flight verification eligibility;
failure or explicit recovery closes it and requires a fresh read claim. Cancelling
an active read closes that attempt even when cancelled was already historically true.
New claims require predecessor cleanup; background ownership requires accept_request.

Receipts are exactly {schema_version:1,status:'verified',effect_id,target_profile,
payload_sha256,transport:{status:'verified',effect_id,database,scope_id,
projection_digest,canonical_identity,verification_boundary}}. Transport keys match research_graph_transport;
projection_digest and scope_id also match the frozen descriptor when present.
comparator(intent, receipt) must return True based on actual projection/spec/readback
verification, NEVER callback equality alone. Payload may be an artifact descriptor,
not the projection. Receipt <=8 KiB; other public JSON <=32 KiB, finite, depth<=16,
<=4096 values (research_registry bounds). Writes consume at most 64 claims/effect;
read plus write request bindings are capped at 128/effect. Bindings/receipts are
append-only, including against SQLite REPLACE. All transitions and events share
one BEGIN IMMEDIATE; no nested transactions, job recovery, or Journal ownership.
"""

import json
import time
import uuid
from contextlib import nullcontext

from .research_registry import bounded_json, canonical_json, checked_identifier, digest

SCHEMA_VERSION = 1
MAX_ATTEMPTS = 64
_ANY_WORKER_IDENTITY = object()

# Required trigger identities from the v1 initialization SQL below. Validate
# object type and table binding, not arbitrary forged SQL-body equivalence.
CORE_TRIGGERS = {
    f"{table}_no_{action}": table
    for table in ("publication_bindings", "publication_receipts")
    for action in ("update", "delete", "replace")
}
WORKER_TRIGGERS = {
    **{
        f"{table}_no_{action}": table
        for table in ("publication_requests", "publication_workers")
        for action in ("update", "delete", "replace")
    },
    "publication_workers_monotonic": "publication_workers",
}


def _check_triggers(db, required):
    """Require initialized trigger identities and their original table bindings."""
    actual = {row[0]: (row[1], row[2]) for row in db.execute("SELECT name,type,tbl_name FROM sqlite_master")}
    if any(actual.get(name) != ("trigger", table) for name, table in required.items()):
        raise ValueError("Incomplete publication trigger schema")


class PublicationAttempts:
    """Borrow Journal transactions without running/recovering API jobs or workers."""

    def __init__(self, journal, registry, initialize=False, *, clock=time.time, protect_public=None, authorizer=None):
        if getattr(registry, "journal", journal) is not journal:
            raise ValueError("Publication registry requires same Journal")
        self.journal = journal
        self.registry = registry
        self.clock = clock
        self.protect_public = protect_public
        self.authorizer = authorizer
        with journal._lock:
            journal._check_schema()
            exists = journal.db.execute("SELECT 1 FROM sqlite_master WHERE name='publication_meta'").fetchone()
            if exists:
                self._check(journal.db)
        if initialize:
            with journal._transaction() as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS publication_meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
                    " schema_version INTEGER NOT NULL, registry_id TEXT NOT NULL)"
                )
                if not db.execute("SELECT 1 FROM publication_meta").fetchone():
                    db.execute("INSERT INTO publication_meta VALUES (1,?,?)", (SCHEMA_VERSION, registry.registry_id))
                self._check(db, creating=not exists)
                db.execute(
                    "CREATE TABLE IF NOT EXISTS publication_states (effect_id TEXT PRIMARY KEY, schema_version INTEGER"
                    " NOT NULL CHECK(schema_version=1), body TEXT NOT NULL CHECK(json_valid(body) AND length(CAST(body"
                    " AS BLOB))<=32768))"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS publication_bindings (request_id TEXT PRIMARY KEY, effect_id TEXT NOT"
                    " NULL, schema_version INTEGER NOT NULL CHECK(schema_version=1), body TEXT NOT NULL"
                    " CHECK(json_valid(body) AND length(CAST(body AS BLOB))<=32768))"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS publication_receipts (effect_id TEXT PRIMARY KEY, schema_version"
                    " INTEGER NOT NULL CHECK(schema_version=1), body TEXT NOT NULL CHECK(json_valid(body) AND"
                    " length(CAST(body AS BLOB))<=16384))"
                )
                for action in ("UPDATE", "DELETE"):
                    db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS publication_receipts_no_{action.lower()} BEFORE {action} ON"
                        " publication_receipts BEGIN SELECT RAISE(ABORT,'Immutable publication receipt'); END"
                    )
                db.execute(
                    "CREATE TRIGGER IF NOT EXISTS publication_receipts_no_replace BEFORE INSERT ON publication_receipts"
                    " WHEN EXISTS(SELECT 1 FROM publication_receipts WHERE effect_id=NEW.effect_id) BEGIN SELECT"
                    " RAISE(ABORT,'Immutable publication receipt'); END"
                )
                for action in ("UPDATE", "DELETE"):
                    db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS publication_bindings_no_{action.lower()} BEFORE {action} ON"
                        " publication_bindings BEGIN SELECT RAISE(ABORT,'Immutable publication binding'); END"
                    )
                db.execute(
                    "CREATE TRIGGER IF NOT EXISTS publication_bindings_no_replace BEFORE INSERT ON publication_bindings"
                    " WHEN EXISTS(SELECT 1 FROM publication_bindings WHERE request_id=NEW.request_id) BEGIN SELECT"
                    " RAISE(ABORT,'Immutable publication binding'); END"
                )
        with journal._lock:
            self._check(journal.db)

    def _check(self, db, *, creating=False):
        if getattr(self.registry, "journal", self.journal) is not self.journal:
            raise ValueError("Publication registry requires same Journal")
        self.journal._check_schema()
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='publication_meta'").fetchone():
            raise ValueError("Publication state not initialized")
        row = db.execute("SELECT * FROM publication_meta WHERE singleton=1").fetchone()
        if row is None or row["schema_version"] != SCHEMA_VERSION or row["registry_id"] != self.registry.registry_id:
            raise ValueError("Incompatible publication schema or registry")
        for table, columns in {
            "publication_states": {"effect_id", "schema_version", "body"},
            "publication_bindings": {"request_id", "effect_id", "schema_version", "body"},
            "publication_receipts": {"effect_id", "schema_version", "body"},
        }.items():
            actual = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
            if creating and not actual:
                continue
            if (
                actual != columns
                or db.execute(f"SELECT 1 FROM {table} WHERE schema_version != ? LIMIT 1", (SCHEMA_VERSION,)).fetchone()
            ):
                raise ValueError("Incompatible publication table schema")

        if not creating:
            _check_triggers(db, CORE_TRIGGERS)
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='publication_worker_meta'").fetchone():
            self._worker_check(db)
        elif any(
            row[0] in {"publication_requests", "publication_workers", *WORKER_TRIGGERS}
            for row in db.execute("SELECT name FROM sqlite_master")
        ):
            raise ValueError("Incomplete publication worker schema")

    def _worker_check(self, db):
        row = db.execute("SELECT schema_version, registry_id FROM publication_worker_meta WHERE singleton=1").fetchone()
        if row is None or row[0] != 1 or row[1] != self.registry.registry_id:
            raise ValueError("Incompatible publication worker schema")
        for table, columns in {
            "publication_requests": {"request_id", "effect_id", "schema_version", "body"},
            "publication_workers": {
                "effect_id",
                "attempt_id",
                "generation",
                "schema_version",
                "body",
                "released",
                "callback_open",
                "cleaned",
            },
        }.items():
            if {r[1] for r in db.execute(f"PRAGMA table_info({table})")} != columns:
                raise ValueError("Incompatible publication worker schema")
            if db.execute(f"SELECT 1 FROM {table} WHERE schema_version != 1 LIMIT 1").fetchone():
                raise ValueError("Incompatible publication worker schema")
        _check_triggers(db, WORKER_TRIGGERS)

    def worker_support_ready(self):
        """Return False for legacy-only schema; refuse incompatible worker support."""
        with self.journal._lock:
            self._check(self.journal.db)
            if not self.journal.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='publication_worker_meta'"
            ).fetchone():
                return False
            self._worker_check(self.journal.db)
            return True

    def initialize_worker_support(self):
        """Explicitly create additive versioned worker support, never recover dispatch."""
        with self.journal._transaction() as db:
            self._check(db)
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='publication_worker_meta'").fetchone():
                self._worker_check(db)
                return
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE name IN ('publication_requests','publication_workers')"
            ).fetchone():
                raise ValueError("Incomplete publication worker schema")
            db.execute(
                "CREATE TABLE publication_worker_meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version"
                " INTEGER NOT NULL, registry_id TEXT NOT NULL)"
            )
            db.execute("INSERT INTO publication_worker_meta VALUES (1,1,?)", (self.registry.registry_id,))
            db.execute(
                "CREATE TABLE publication_requests (request_id TEXT PRIMARY KEY, effect_id TEXT NOT NULL,"
                " schema_version INTEGER NOT NULL CHECK(schema_version=1), body TEXT NOT NULL CHECK(json_valid(body)"
                " AND length(CAST(body AS BLOB))<=32768))"
            )
            db.execute(
                "CREATE TABLE publication_workers (effect_id TEXT NOT NULL, attempt_id TEXT NOT NULL, generation"
                " INTEGER NOT NULL, schema_version INTEGER NOT NULL CHECK(schema_version=1), body TEXT NOT NULL"
                " CHECK(json_valid(body) AND length(CAST(body AS BLOB))<=32768), released INTEGER NOT NULL DEFAULT 0"
                " CHECK(released IN (0,1)), callback_open INTEGER NOT NULL DEFAULT 0 CHECK(callback_open IN (0,1)),"
                " cleaned INTEGER NOT NULL DEFAULT 0 CHECK(cleaned IN (0,1)), PRIMARY"
                " KEY(effect_id,attempt_id,generation), UNIQUE(attempt_id))"
            )
            db.execute(
                "CREATE TRIGGER publication_workers_monotonic BEFORE UPDATE ON publication_workers WHEN"
                " NEW.released<OLD.released OR NEW.cleaned<OLD.cleaned OR (NEW.callback_open=1 AND (NEW.released=0 OR"
                " NEW.cleaned=1)) OR (NEW.callback_open>OLD.callback_open AND NOT (OLD.released=0 AND NEW.released=1"
                " AND OLD.cleaned=0)) BEGIN SELECT RAISE(ABORT,'Immutable worker release or callback fence'); END"
            )
            for table in ("publication_requests", "publication_workers"):
                db.execute(
                    f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'Immutable"
                    " publication record'); END"
                )
                clause = (
                    "" if table == "publication_requests" else " OF effect_id,attempt_id,generation,schema_version,body"
                )
                db.execute(
                    f"CREATE TRIGGER {table}_no_update BEFORE UPDATE{clause} ON {table} BEGIN SELECT"
                    " RAISE(ABORT,'Immutable publication record'); END"
                )
                key = (
                    "request_id=NEW.request_id"
                    if table == "publication_requests"
                    else (
                        "attempt_id=NEW.attempt_id OR (effect_id=NEW.effect_id AND generation=NEW.generation AND"
                        " attempt_id=NEW.attempt_id)"
                    )
                )
                db.execute(
                    f"CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM"
                    f" {table} WHERE {key}) BEGIN SELECT RAISE(ABORT,'Immutable publication record'); END"
                )
            self._worker_check(db)

    def get_acceptance(self, request_id):
        """Return immutable public AcceptanceRequest, or None; never dispatch."""
        checked_identifier(request_id)
        with self.journal._lock:
            if not self.worker_support_ready():
                raise ValueError("Publication worker schema not initialized")
            row = self.journal.db.execute(
                "SELECT body FROM publication_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            return None if row is None else json.loads(row[0])

    def accept_request(
        self,
        effect_id,
        request_id,
        grant_metadata,
        *,
        owner_session,
        principal,
        store_id,
        operation,
        request_digest,
        previous_request_id=None,
    ):
        """Atomically accept ownership plus claim; replay is observation only."""
        for value in (effect_id, request_id, owner_session, principal, store_id):
            checked_identifier(value)
        if operation not in ("write", "renew", "reconcile"):
            raise ValueError("Invalid publication operation")
        if (
            type(request_digest) is not str
            or len(request_digest) != 64
            or any(c not in "0123456789abcdef" for c in request_digest)
        ):
            raise ValueError("Invalid public request digest")
        if operation == "renew" and (previous_request_id is None or previous_request_id == request_id):
            raise ValueError("Renewal requires eligible predecessor")
        if previous_request_id is not None:
            checked_identifier(previous_request_id)
        if operation == "write" and previous_request_id is not None:
            raise ValueError("Write cannot name predecessor")
        binding = self._public(
            dict(
                schema_version=1,
                registry_id=self.registry.registry_id,
                effect_id=effect_id,
                request_id=request_id,
                owner_session=owner_session,
                principal=principal,
                store_id=store_id,
                operation=operation,
                request_digest=request_digest,
                previous_request_id=previous_request_id,
            )
        )
        metadata = self._public(grant_metadata)
        with self.journal._transaction() as db:
            if not self.worker_support_ready():
                raise ValueError("Publication worker schema not initialized")
            old = self.get_acceptance(request_id)
            if old is not None:
                if any(old[k] != v for k, v in binding.items()) or metadata != self._approved(db, request_id):
                    raise ValueError("Publication request owner or binding conflict")
                return dict(accepted_new=False, accepted=old, state=self.get_state(effect_id))
            intent = self._intent(effect_id)
            reservation = self.registry.get_reservation(intent["reservation_id"])
            if reservation.get("store_id", store_id) != store_id:
                raise ValueError("Publication store conflict")
            if getattr(self.registry, "journal", self.journal) is not self.journal:
                raise ValueError("Publication registry requires same Journal")
            owners = db.execute("SELECT body FROM publication_requests WHERE effect_id=?", (effect_id,)).fetchall()
            for row in owners:
                previous = json.loads(row[0])
                if any(previous[k] != binding[k] for k in ("owner_session", "principal", "store_id")):
                    raise ValueError("Publication owner conflict")
            state = self.get_state(effect_id)
            if previous_request_id is not None and state["request_id"] != previous_request_id:
                raise ValueError("Publication predecessor conflict")
            if db.execute("SELECT 1 FROM publication_bindings WHERE request_id=?", (request_id,)).fetchone():
                raise ValueError("Publication request already bound without owner")
            if operation == "reconcile":
                state = self._claim_read(effect_id, request_id, metadata, db=db)
            else:
                state = self._claim(effect_id, request_id, metadata, previous_request_id, db=db)
            accepted = self._public(
                dict(
                    binding,
                    attempt_id=state["attempt_id"],
                    generation=state["generation"],
                    capability=metadata["capability"],
                )
            )
            db.execute(
                "INSERT INTO publication_requests VALUES (?,?,1,?)", (request_id, effect_id, canonical_json(accepted))
            )
            return dict(accepted_new=True, accepted=accepted, state=state)

    def _background(self, db, state):
        return (
            state is not None
            and db.execute("SELECT 1 FROM sqlite_master WHERE name='publication_requests'").fetchone() is not None
            and db.execute("SELECT 1 FROM publication_requests WHERE request_id=?", (state["request_id"],)).fetchone()
            is not None
        )

    def _claim_predecessor(self, db, state, *, synchronous):
        """Keep cleanup and background ownership fences across every new claim."""
        if (
            db.execute("SELECT 1 FROM sqlite_master WHERE name='publication_workers'").fetchone()
            and db.execute(
                "SELECT 1 FROM publication_workers WHERE effect_id=? AND cleaned=0", (state["effect_id"],)
            ).fetchone()
        ):
            raise ValueError("Publication predecessor worker uncleaned")
        if synchronous and self._background(db, state):
            raise ValueError("Publication background ownership requires explicit accept_request")

    def _worker(self, db, effect_id, attempt_id, generation, worker_identity=_ANY_WORKER_IDENTITY):
        self._worker_check(db)
        if type(generation) is not int:
            return None
        row = db.execute(
            "SELECT * FROM publication_workers WHERE effect_id=? AND attempt_id=? AND generation=?",
            (effect_id, attempt_id, generation),
        ).fetchone()
        if row is None:
            return None
        result = json.loads(row["body"])
        if worker_identity is not _ANY_WORKER_IDENTITY and canonical_json(result["identity"]) != canonical_json(
            worker_identity
        ):
            return None
        return dict(
            result,
            released=bool(row["released"]),
            callback_open=bool(row["callback_open"]),
            cleaned=bool(row["cleaned"]),
        )

    def record_worker(self, effect_id, attempt_id, generation, capability, pid, identity):
        """Record one credential-free owned worker per attempt; duplicates return False."""
        identity = self._public(identity)
        if (
            type(pid) is not int
            or pid <= 0
            or type(identity) is not dict
            or not identity
            or identity.get("pid", pid) != pid
        ):
            raise ValueError("Invalid worker identity")
        with self.journal._transaction() as db:
            self._check(db)
            self._worker_check(db)
            state = self._load(db, effect_id)
            if not self._matches(state, attempt_id, generation) or (capability == "graph_write" and state["cancelled"]):
                return False
            accepted = self.get_acceptance(state["request_id"])
            if accepted is None or accepted["capability"] != capability:
                raise ValueError("Worker acceptance capability conflict")
            eligible = (
                state["state"] == "claimed"
                if capability == "graph_write"
                else state["reconciliation"] == {"state": "claimed"}
            )
            if not eligible or self._worker(db, effect_id, attempt_id, generation) is not None:
                return False
            if db.execute("SELECT 1 FROM publication_workers WHERE effect_id=? AND cleaned=0", (effect_id,)).fetchone():
                raise ValueError("Publication predecessor worker uncleaned")
            body = self._public(
                dict(
                    schema_version=1,
                    effect_id=effect_id,
                    attempt_id=attempt_id,
                    generation=generation,
                    capability=capability,
                    pid=pid,
                    identity=identity,
                )
            )
            db.execute(
                "INSERT INTO publication_workers VALUES (?,?,?,1,?,0,0,0)",
                (effect_id, attempt_id, generation, canonical_json(body)),
            )
            self._save(db, state, "publication_worker_recorded")
            return True

    def pending_workers(self):
        """Return uncleaned owned identities, including recovered and completed attempts."""
        with self.journal._lock:
            self._check(self.journal.db)
            self._worker_check(self.journal.db)
            rows = self.journal.db.execute(
                "SELECT effect_id,attempt_id,generation FROM publication_workers WHERE cleaned=0 ORDER BY"
                " effect_id,generation"
            ).fetchall()
            return [self._worker(self.journal.db, *row) for row in rows]

    def worker_cleaned(self, effect_id, attempt_id, generation, *, worker_identity):
        """Acknowledge exact owned identity cleanup; close callbacks, retain identity forever."""
        with self.journal._transaction() as db:
            self._check(db)
            worker = self._worker(db, effect_id, attempt_id, generation, worker_identity)
            if worker is None or worker["cleaned"]:
                return False
            db.execute(
                "UPDATE publication_workers SET cleaned=1,callback_open=0 WHERE effect_id=? AND attempt_id=? AND"
                " generation=?",
                (effect_id, attempt_id, generation),
            )
            state = self._load(db, effect_id)
            if self._matches(state, attempt_id, generation):
                if state["reconciliation"] is not None and state["reconciliation"]["state"] in ("claimed", "released"):
                    state["reconciliation"]["state"] = "unknown"
                elif state["state"] in ("claimed", "released"):
                    state["state"] = "blocked_authorization" if state["state"] == "claimed" else "unknown"
                state["write_callback_open"] = False
                self._save(db, state, "publication_worker_cleaned")
            return True

    def release_worker(self, effect_id, attempt_id, generation, *, worker_identity, grant_metadata, prepare_private):
        """Return 1..2MiB private bytes ONLY after durable release commit, otherwise None.

        prepare_private(private_config, immutable_intent) is trusted synchronous
        serialization only: no IO, transport, callbacks, grants, or nested writes.
        Private bytes and their hashes are never persisted.
        """
        metadata = self._public(grant_metadata)
        with self.journal._transaction() as db:
            self._check(db)
            worker = self._worker(db, effect_id, attempt_id, generation, worker_identity)
            state = self._load(db, effect_id)
            if (
                worker is None
                or worker["released"]
                or worker["cleaned"]
                or not self._matches(state, attempt_id, generation)
                or (worker["capability"] == "graph_write" and state["cancelled"])
            ):
                return None
            capability = worker["capability"]
            eligible = (
                state["state"] == "claimed"
                if capability == "graph_write"
                else state["state"] == "unknown" and state["reconciliation"] == {"state": "claimed"}
            )
            if not eligible:
                return None
            if metadata != self._approved(db, state["request_id"]):
                raise ValueError("Publication worker grant conflict")
            config = self._authorize(state, metadata, capability)
            if not callable(prepare_private):
                raise ValueError("Synchronous private preparation required")
            private_bytes = prepare_private(config, self._intent(effect_id))
            if type(private_bytes) is not bytes or not 1 <= len(private_bytes) <= 2 * 1024 * 1024:
                raise ValueError("Private worker bytes must be bounded")
            self._validate_grant(self._intent(effect_id), state["request_id"], metadata, capability)
            if capability == "graph_write":
                state.update(state="released", write_callback_open=True)
            else:
                state["reconciliation"]["state"] = "released"
            db.execute(
                "UPDATE publication_workers SET released=1,callback_open=1 WHERE effect_id=? AND attempt_id=? AND"
                " generation=?",
                (effect_id, attempt_id, generation),
            )
            self._save(db, state, "publication_worker_released")
        return private_bytes

    def _worker_callback(self, db, effect_id, attempt_id, generation, worker_identity):
        worker = self._worker(db, effect_id, attempt_id, generation, worker_identity)
        state = self._load(db, effect_id)
        if (
            worker is None
            or not worker["released"]
            or not worker["callback_open"]
            or worker["cleaned"]
            or not self._matches(state, attempt_id, generation)
        ):
            return None
        if worker["capability"] == "graph_read":
            if state["state"] != "unknown" or state["reconciliation"] != {"state": "released"}:
                return None
        elif (
            state["state"] not in ("released", "unknown")
            or not state["write_callback_open"]
            or state["reconciliation"] is not None
        ):
            return None
        return state

    def complete_worker_verified(self, effect_id, attempt_id, generation, *, worker_identity, receipt, comparator=None):
        """Accept only genuinely released current worker evidence, before cleanup."""
        with self.journal._transaction() as db:
            self._check(db)
            if self._worker_callback(db, effect_id, attempt_id, generation, worker_identity) is None:
                return False
            if not self._complete_verified(
                effect_id, attempt_id, generation, receipt=receipt, comparator=comparator, db=db
            ):
                return False
            db.execute(
                "UPDATE publication_workers SET callback_open=0 WHERE effect_id=? AND attempt_id=? AND generation=?",
                (effect_id, attempt_id, generation),
            )
            return True

    def close_worker_unknown(self, effect_id, attempt_id, generation, *, worker_identity):
        """Close released current callbacks without unlocking the write fence."""
        with self.journal._transaction() as db:
            self._check(db)
            state = self._worker_callback(db, effect_id, attempt_id, generation, worker_identity)
            if state is None:
                return False
            state.update(state="unknown", write_callback_open=False)
            if state["reconciliation"] is not None:
                state["reconciliation"]["state"] = "unknown"
            db.execute(
                "UPDATE publication_workers SET callback_open=0 WHERE effect_id=? AND attempt_id=? AND generation=?",
                (effect_id, attempt_id, generation),
            )
            self._save(db, state, "publication_worker_unknown")
            return True

    def recover_worker_dispatch(self):
        """Fence every interrupted background dispatch before external cleanup; never replay."""
        count = 0
        with self.journal._transaction() as db:
            self._check(db)
            self._worker_check(db)
            rows = db.execute("SELECT DISTINCT effect_id FROM publication_requests").fetchall()
            for row in rows:
                state = self._load(db, row[0])
                if state is None:
                    continue
                changed = False
                if state["reconciliation"] is not None and state["reconciliation"]["state"] in ("claimed", "released"):
                    state["reconciliation"]["state"] = "unknown"
                    changed = True
                elif state["state"] in ("claimed", "released"):
                    state["state"] = "blocked_authorization" if state["state"] == "claimed" else "unknown"
                    changed = True
                if state["write_callback_open"]:
                    state["write_callback_open"] = False
                    changed = True
                open_worker = db.execute(
                    "SELECT 1 FROM publication_workers WHERE effect_id=? AND callback_open=1", (row[0],)
                ).fetchone()
                if open_worker:
                    db.execute("UPDATE publication_workers SET callback_open=0 WHERE effect_id=?", (row[0],))
                    changed = True
                if changed:
                    self._save(db, state, "publication_worker_recovered")
                    count += 1
        return count

    def _public(self, value):
        value = bounded_json(value, public=True)
        if not callable(self.protect_public):
            raise ValueError("protect_public callback required before writes")
        encoded = canonical_json(value)
        protected = self.protect_public(value)
        if canonical_json(value) != encoded or (protected is not None and canonical_json(protected) != encoded):
            raise ValueError("protect_public must approve exact public metadata")
        return json.loads(encoded)

    def _intent(self, effect_id):
        checked_identifier(effect_id)
        intent = self.registry.get_publication_intent(effect_id)
        if intent is None or intent["effect_id"] != effect_id or intent["registry_id"] != self.registry.registry_id:
            raise ValueError("Publication intent conflict")
        if digest(intent["payload"]) != intent["payload_sha256"]:
            raise ValueError("Publication payload conflict")
        commit = self.registry.get_commit(intent["reservation_id"])
        if commit is None or commit["publication_intent_id"] != effect_id:
            raise ValueError("Publication requires committed intent")
        return intent

    def _load(self, db, effect_id):
        row = db.execute("SELECT body FROM publication_states WHERE effect_id=?", (effect_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def _save(self, db, state, kind):
        from .research_source import source_kind

        state = self._public(state)
        db.execute(
            "INSERT INTO publication_states VALUES (?,1,?) ON CONFLICT(effect_id) DO UPDATE SET body=excluded.body",
            (state["effect_id"], canonical_json(state)),
        )
        intent = self._intent(state["effect_id"])
        source = self.registry.get_reservation(intent["reservation_id"])["source"]
        if source_kind(source) == "accepted_candidate":
            self.journal._event(db, self.journal.get_job(source["job_id"]), kind)
        return state

    def get_state(self, effect_id):
        """Return detached public state, or a pending snapshot without creating a row."""
        intent = self._intent(effect_id)
        with self.journal._lock:
            self._check(self.journal.db)
            return self._load(self.journal.db, effect_id) or dict(
                schema_version=1,
                effect_id=effect_id,
                target_profile=intent["target_profile"],
                payload_sha256=intent["payload_sha256"],
                state="pending",
                cancelled=False,
                generation=0,
                attempt_id=None,
                request_id=None,
                receipt=None,
                write_claim_count=0,
                reconciliation=None,
                write_callback_open=False,
            )

    max_attempts = MAX_ATTEMPTS

    def claim(self, effect_id, request_id, grant_metadata):
        """Claim once; identical HTTP request replay returns its immutable acceptance."""
        return self._claim(effect_id, request_id, grant_metadata, None)

    def renew(self, effect_id, request_id, grant_metadata, *, previous_request_id):
        """Explicitly approve a new request linked to a blocked, unsent attempt."""
        checked_identifier(previous_request_id)
        if previous_request_id == request_id:
            raise ValueError("Renewal requires a new request")
        return self._claim(effect_id, request_id, grant_metadata, previous_request_id)

    def _claim(self, effect_id, request_id, grant_metadata, previous_request_id, *, db=None):
        synchronous = db is None
        checked_identifier(request_id)
        intent = self._intent(effect_id)
        metadata = self._public(grant_metadata)
        binding = self._public(
            dict(
                effect_id=effect_id,
                request_id=request_id,
                grant_metadata=metadata,
                intent_sha256=digest(intent),
                previous_request_id=previous_request_id,
            )
        )
        with self.journal._transaction() if db is None else nullcontext(db) as db:
            self._check(db)
            old = db.execute("SELECT body FROM publication_bindings WHERE request_id=?", (request_id,)).fetchone()
            if old:
                previous = json.loads(old[0])
                if previous["binding"] != binding:
                    raise ValueError("Publication request conflict")
                return previous["accepted"]
            self._validate_grant(intent, request_id, metadata, "graph_write")
            state = self.get_state(effect_id)
            self._claim_predecessor(db, state, synchronous=synchronous)
            if (
                state["cancelled"]
                or (previous_request_id is None and state["state"] != "pending")
                or (
                    previous_request_id is not None
                    and (state["state"] != "blocked_authorization" or state["request_id"] != previous_request_id)
                )
            ):
                raise ValueError("Publication exclusive claim unavailable")
            if state["write_claim_count"] >= self.max_attempts:
                raise ValueError("Publication attempt quota exceeded")
            if previous_request_id is not None:
                previous = json.loads(
                    db.execute(
                        "SELECT body FROM publication_bindings WHERE request_id=?", (previous_request_id,)
                    ).fetchone()[0]
                )
                if previous["binding"]["intent_sha256"] != digest(intent):
                    raise ValueError("Publication renewal intent conflict")
            state.update(
                state="claimed",
                generation=state["generation"] + 1,
                attempt_id=uuid.uuid4().hex,
                request_id=request_id,
                write_claim_count=state["write_claim_count"] + 1,
            )
            record = self._public(dict(binding=binding, accepted=state))
            db.execute(
                "INSERT INTO publication_bindings VALUES (?,?,1,?)", (request_id, effect_id, canonical_json(record))
            )
            return self._save(db, state, "publication_write_claimed")

    def _validate_grant(self, intent, request_id, metadata, capability):
        expected = dict(
            effect_id=intent["effect_id"],
            target_profile=intent["target_profile"],
            payload_sha256=intent["payload_sha256"],
            request_id=request_id,
            capability=capability,
        )
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise ValueError("Publication grant scope conflict")
        checked_identifier(metadata.get("grant_id"))
        expiry = metadata.get("expires_at")
        if type(expiry) not in (int, float) or not self.clock() < expiry:
            raise ValueError("Publication grant expired")

    @staticmethod
    def _matches(state, attempt_id, generation):
        return (
            state is not None
            and type(generation) is int
            and state["attempt_id"] == attempt_id
            and state["generation"] == generation
        )

    def _approved(self, db, request_id):
        return json.loads(
            db.execute("SELECT body FROM publication_bindings WHERE request_id=?", (request_id,)).fetchone()[0]
        )["binding"]["grant_metadata"]

    def release(self, effect_id, attempt_id, generation, *, grant_metadata):
        """Fence the exact approved grant before any transport write is allowed."""
        metadata = self._public(grant_metadata)
        with self.journal._transaction() as db:
            self._check(db)
            state = self._load(db, effect_id)
            if self._background(db, state):
                return False
            if not self._matches(state, attempt_id, generation) or state["state"] != "claimed" or state["cancelled"]:
                return False
            if metadata != self._approved(db, state["request_id"]):
                raise ValueError("Publication grant conflict; explicit renewal required")
            if self.authorizer is not None:
                self._authorize(state, metadata, "graph_write")
            self._validate_grant(self._intent(effect_id), state["request_id"], metadata, "graph_write")
            state["state"] = "released"
            state["write_callback_open"] = True
            self._save(db, state, "publication_released")
            return True

    def mark_unknown(self, effect_id, attempt_id, generation):
        """Persist released failure without granting any subsequent write claim."""
        with self.journal._transaction() as db:
            self._check(db)
            state = self._load(db, effect_id)
            if (
                not self._matches(state, attempt_id, generation)
                or state["state"] not in ("released", "unknown")
                or not state["write_callback_open"]
            ):
                return False
            state["state"] = "unknown"
            state["write_callback_open"] = False
            self._save(db, state, "publication_unknown")
            return True

    def cancel(self, effect_id):
        """Record cancellation independently of the known/unknown publication outcome."""
        with self.journal._transaction() as db:
            self._check(db)
            state = self.get_state(effect_id)
            active_read = state["reconciliation"] is not None and state["reconciliation"]["state"] in (
                "claimed",
                "released",
            )
            if state["cancelled"] and not active_read:
                return state
            state["cancelled"] = True
            if active_read:
                # Historical effect cancellation does not cancel a separately granted
                # read. This call closes only the current read's dispatch/callback fence.
                state["reconciliation"]["state"] = "unknown"
                if self._background(db, state):
                    db.execute(
                        "UPDATE publication_workers SET callback_open=0 WHERE effect_id=? AND attempt_id=? AND"
                        " generation=?",
                        (effect_id, state["attempt_id"], state["generation"]),
                    )
            if state["state"] in ("pending", "claimed", "blocked_authorization"):
                state["state"] = "cancelled_no_send"
            elif state["state"] == "released":
                state["state"] = "unknown"
            return self._save(db, state, "publication_cancel_requested")

    def block_authorization(self, effect_id, attempt_id, generation):
        """Pause an unsent claim; quota and immutable approval remain consumed."""
        with self.journal._transaction() as db:
            self._check(db)
            state = self._load(db, effect_id)
            if not self._matches(state, attempt_id, generation) or state["state"] != "claimed":
                return False
            state["state"] = "blocked_authorization"
            self._save(db, state, "publication_blocked_authorization")
            return True

    def recover(self):
        """Explicit startup pause/unknown transition, with no external calls or jobs."""
        count = 0
        with self.journal._transaction() as db:
            self._check(db)
            for row in db.execute("SELECT body FROM publication_states").fetchall():
                state = json.loads(row[0])
                if state["state"] == "unknown" and state["write_callback_open"]:
                    state["write_callback_open"] = False
                elif state["reconciliation"] is not None and state["reconciliation"]["state"] in (
                    "claimed",
                    "released",
                ):
                    state["reconciliation"]["state"] = "unknown"
                elif state["state"] in ("claimed", "released"):
                    state["state"] = "blocked_authorization" if state["state"] == "claimed" else "unknown"
                else:
                    continue
                state["write_callback_open"] = False
                self._save(db, state, "publication_recovered")
                count += 1
        return count

    def _receipt(self, intent, receipt):
        receipt = self._public(bounded_json(receipt, public=True, max_bytes=8192))
        expected = dict(
            schema_version=1,
            status="verified",
            effect_id=intent["effect_id"],
            target_profile=intent["target_profile"],
            payload_sha256=intent["payload_sha256"],
        )
        if set(receipt) != set(expected) | {"transport"} or any(receipt.get(k) != v for k, v in expected.items()):
            raise ValueError("Publication receipt scope conflict")
        transport = receipt["transport"]
        if type(transport) is not dict or set(transport) != {
            "status",
            "effect_id",
            "database",
            "scope_id",
            "projection_digest",
            "canonical_identity",
            "verification_boundary",
        }:
            raise ValueError("Publication transport evidence required")
        boundary = transport["verification_boundary"]
        if (
            type(boundary) is not dict
            or set(boundary) != {"method", "operator_attested", "declaration", "database_snapshot"}
            or boundary["method"] != "operator_attested_immutable_scope_v1"
            or boundary["operator_attested"] is not True
            or boundary["database_snapshot"] is not False
            or type(boundary["declaration"]) is not str
            or not 1 <= len(boundary["declaration"]) <= 4096
        ):
            raise ValueError("Publication verification boundary required")
        if transport["status"] != "verified" or transport["effect_id"] != intent["effect_id"]:
            raise ValueError("Publication transport scope conflict")
        for key in ("database", "scope_id"):
            if type(transport[key]) is not str or not transport[key] or len(transport[key]) > 256:
                raise ValueError("Invalid transport evidence")
        value = transport["projection_digest"]
        if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("Invalid transport projection digest")
        if type(transport["canonical_identity"]) is not dict or not transport["canonical_identity"]:
            raise ValueError("Invalid transport canonical identity")
        for key in ("scope_id", "projection_digest"):
            if key in intent["payload"] and intent["payload"][key] != transport[key]:
                raise ValueError("Publication descriptor evidence conflict")
        return receipt

    def complete_verified(self, effect_id, attempt_id, generation, *, receipt, comparator=None):
        """Accept exact current released evidence; comparator must verify actual readback.

        comparator(intent, receipt) MUST return True after checking actual transport
        evidence against the frozen projection/spec, not merely callback fields. No
        metadata check here establishes graph truth. Receipts have exactly the outer
        binding fields and the transport keys defined by research_graph_transport.
        """
        return self._complete_verified(effect_id, attempt_id, generation, receipt=receipt, comparator=comparator)

    def _complete_verified(self, effect_id, attempt_id, generation, *, receipt, comparator=None, db=None):
        synchronous = db is None
        with self.journal._transaction() if db is None else nullcontext(db) as db:
            self._check(db)
            state = self._load(db, effect_id)
            if synchronous and self._background(db, state):
                return False
            if not self._matches(state, attempt_id, generation) or state["state"] not in (
                "released",
                "unknown",
                "verified",
            ):
                return False
            if state["reconciliation"] is not None and state["reconciliation"]["state"] not in (
                "claimed",
                "released",
                "verified",
            ):
                return False
            if state["state"] == "unknown" and state["reconciliation"] is None and not state["write_callback_open"]:
                return False
            intent = self._intent(effect_id)
            receipt = self._receipt(intent, receipt)
            if state["receipt"] is not None:
                if state["receipt"] != receipt:
                    raise ValueError("Immutable publication receipt conflict")
                return True
            if not callable(comparator):
                raise ValueError("Actual transport comparator required")
            if comparator(bounded_json(intent, max_bytes=65536), bounded_json(receipt)) is not True:
                raise ValueError("Actual transport verification failed")
            record = self._public(dict(attempt_id=attempt_id, generation=generation, receipt=receipt))
            db.execute("INSERT INTO publication_receipts VALUES (?,1,?)", (effect_id, canonical_json(record)))
            state.update(state="verified", receipt=receipt, write_callback_open=False)
            if state["reconciliation"] is not None:
                state["reconciliation"]["state"] = "verified"
            self._save(db, state, "publication_verified")
            return True

    def claim_reconciliation(self, effect_id, request_id, grant_metadata):
        """Claim read-only authority while preserving an unknown write outcome."""
        return self._claim_read(effect_id, request_id, grant_metadata)

    def _claim_read(self, effect_id, request_id, grant_metadata, *, db=None):
        synchronous = db is None
        checked_identifier(request_id)
        intent = self._intent(effect_id)
        metadata = self._public(grant_metadata)
        binding = self._public(
            dict(
                effect_id=effect_id,
                request_id=request_id,
                grant_metadata=metadata,
                intent_sha256=digest(intent),
                operation="reconcile",
            )
        )
        with self.journal._transaction() if db is None else nullcontext(db) as db:
            self._check(db)
            old = db.execute("SELECT body FROM publication_bindings WHERE request_id=?", (request_id,)).fetchone()
            if old:
                old = json.loads(old[0])
                if old["binding"] != binding:
                    raise ValueError("Publication request conflict")
                return old["accepted"]
            self._validate_grant(intent, request_id, metadata, "graph_read")
            state = self.get_state(effect_id)
            self._claim_predecessor(db, state, synchronous=synchronous)
            if state["state"] != "unknown" or (
                state["reconciliation"] is not None and state["reconciliation"]["state"] in ("claimed", "released")
            ):
                raise ValueError("Reconciliation exclusive claim unavailable")
            if (
                db.execute("SELECT COUNT(*) FROM publication_bindings WHERE effect_id=?", (effect_id,)).fetchone()[0]
                >= self.max_attempts * 2
            ):
                raise ValueError("Reconciliation attempt quota exceeded")
            state.update(
                generation=state["generation"] + 1,
                attempt_id=uuid.uuid4().hex,
                request_id=request_id,
                reconciliation={"state": "claimed"},
                write_callback_open=False,
            )
            record = self._public(dict(binding=binding, accepted=state))
            db.execute(
                "INSERT INTO publication_bindings VALUES (?,?,1,?)", (request_id, effect_id, canonical_json(record))
            )
            return self._save(db, state, "publication_read_claimed")

    def finish_reconciliation_unknown(self, effect_id, attempt_id, generation):
        """Finish negative/failed reads without ever reopening write permission."""
        with self.journal._transaction() as db:
            self._check(db)
            state = self._load(db, effect_id)
            if (
                not self._matches(state, attempt_id, generation)
                or state["state"] != "unknown"
                or state["reconciliation"] is None
                or state["reconciliation"]["state"] not in ("claimed", "released")
            ):
                return False
            state["reconciliation"]["state"] = "unknown"
            self._save(db, state, "publication_read_unknown")
            return True

    def _authorize(self, state, metadata, capability):
        if not callable(self.authorizer):
            raise ValueError("Private authorizer required for operations")
        metadata = self._public(metadata)
        self._validate_grant(self._intent(state["effect_id"]), state["request_id"], metadata, capability)
        original = canonical_json(metadata)
        config, approved = self.authorizer(
            metadata,
            capability=capability,
            effect_id=state["effect_id"],
            request_id=state["request_id"],
            attempt_id=state["attempt_id"],
            generation=state["generation"],
        )
        if canonical_json(self._public(approved)) != original or canonical_json(metadata) != original:
            raise ValueError("Authorizer grant conflict; no silent renewal")
        self._validate_grant(self._intent(state["effect_id"]), state["request_id"], metadata, capability)
        return config

    def execute_write(self, effect_id, attempt_id, generation, *, grant_metadata, operation, comparator):
        """Run one injected synchronous writer, never replay it on failure/restart."""
        state = self.get_state(effect_id)
        if not self._matches(state, attempt_id, generation) or state["state"] != "claimed":
            return False
        try:
            config = self._authorize(state, grant_metadata, "graph_write")
            if not self.release(effect_id, attempt_id, generation, grant_metadata=grant_metadata):
                return False
        except ValueError:
            self.block_authorization(effect_id, attempt_id, generation)
            raise
        try:
            result = operation(config, self._intent(effect_id))
            return self.complete_verified(effect_id, attempt_id, generation, receipt=result, comparator=comparator)
        except BaseException:
            self.mark_unknown(effect_id, attempt_id, generation)
            raise

    def execute_reconciliation(self, effect_id, attempt_id, generation, *, grant_metadata, operation, comparator):
        """Run one injected reader using independent current read capability only."""
        with self.journal._transaction() as db:
            self._check(db)
            state = self._load(db, effect_id)
            if self._background(db, state):
                return False
            if (
                not self._matches(state, attempt_id, generation)
                or state["state"] != "unknown"
                or state["reconciliation"] != {"state": "claimed"}
            ):
                return False
            if self._public(grant_metadata) != self._approved(db, state["request_id"]):
                raise ValueError("Read grant conflict")
            config = self._authorize(state, grant_metadata, "graph_read")
            state["reconciliation"]["state"] = "released"
            self._save(db, state, "publication_read_released")
        try:
            result = operation(config, self._intent(effect_id))
            if result is None or result.get("status") == "unknown":
                self.finish_reconciliation_unknown(effect_id, attempt_id, generation)
                return False
            return self.complete_verified(effect_id, attempt_id, generation, receipt=result, comparator=comparator)
        except BaseException:
            self.finish_reconciliation_unknown(effect_id, attempt_id, generation)
            raise
