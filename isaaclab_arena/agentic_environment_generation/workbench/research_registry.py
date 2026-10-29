# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Immutable Journal-backed research reservations, verified commits, and pending outbox.

The caller MUST authenticate persistence approval and protect_public all metadata;
recursive private-field rejection is defense in depth, NOT secret detection. The
facade MUST verify actual filesystem bytes before record_commit. This module never
initializes/restarts/closes the supplied Journal, grants publication, or runs a writer.

JSON contract (canonical_json uses sorted keys, compact separators, ASCII escapes):
* reservation: schema_version, registry_id, reservation_id, revision_id, workflow_id,
  version, request_digest, store_id, family, source, parent_revision_id, approval,
  publication_request. Legacy source retains exactly job_id, attempt_id, generation,
  receipt_sha256, request_sha256, with no kind tag. Manual source uses the exact v1
  editor_revision fields in research_source. Parent is explicit and committed in
  the same store/family. Manual approval scope is persist_editor_revision.
* commit: reservation, manifest, relative_directory, publication_intent_id (or null).
* publication_request: effect_id, target_profile, optional options object. Profile
  is an identifier or 1–16 identifier-to-identifier entries, never a URL/credential.
* publication_intent input: the exact request fields plus payload and payload_sha256.
  Stored output adds schema_version, registry_id, reservation_id, state='pending'.
  A frozen request requires an intent at commit, and absent request forbids one.
* list_versions: ascending {reservation, state: 'reserved'|'committed', commit|null}.
  limit is 1–100 (default 50), after_version is an exclusive nonnegative int64 cursor.
  latest_version returns highest committed integer or None, never reserved numbers.

IDs: literal [A-Za-z0-9][A-Za-z0-9_-]{0,63}. JSON: finite, depth <=16, <=4096 values
(the enclosing manifest permits depth 17). Keys <=128 chars, strings <=8192 chars,
signed int64. Canonical byte bounds:
reservation/binding 32 KiB, manifest 64 KiB, commit 96 KiB, request 8 KiB,
options 4 KiB, payload 48 KiB, stored intent 64 KiB. Manifest schema=1 binds the
entire reservation and 2–16 flat .yaml/.json files (2 MiB each, 8 MiB total),
including original UTF-8 environment.yaml and canonical full-receipt candidate.json.
Manifest digest hashes all fields except digest; directory is final/<family>/v<N>.
All writes share the existing Journal transaction; later readers issue reads only.
"""

import hashlib
import json
import re
import uuid

SCHEMA_VERSION = 1
MAX_STORES = 16
MAX_RESERVATIONS_PER_STORE = 10000


def canonical_json(value):
    """Serialize finite research metadata deterministically."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    """Hash canonical research metadata without conflating scene hash schemes."""
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def bounded_json(value, *, max_bytes=32768, public=False, max_depth=16):
    """Copy bounded finite JSON; callers MUST protect_public before using public=True."""
    budget = [4096]

    def walk(item, depth):
        budget[0] -= 1
        if budget[0] < 0 or depth > max_depth:
            raise ValueError("Research JSON exceeds bounds")
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str or len(key) > 128:
                    raise ValueError("Invalid research JSON key")
                if public and re.search(
                    r"(?i)(credential|secret|private|password|passphrase|token|api[_-]?key|access[_-]?key|authorization)",
                    key,
                ):
                    raise ValueError("Private publication field rejected")
                walk(child, depth + 1)
        elif type(item) is list:
            for child in item:
                walk(child, depth + 1)
        elif type(item) is str:
            if len(item) > 8192:
                raise ValueError("Research JSON string exceeds bounds")
        elif type(item) is int:
            if not -(2**63) <= item < 2**63:
                raise ValueError("Research JSON integer exceeds bounds")
        elif item is not None and type(item) not in (float, bool):
            raise ValueError("Invalid research JSON value")

    if type(value) is not dict:
        raise ValueError("Research JSON object required")
    walk(value, 0)
    encoded = canonical_json(value)
    if len(encoded.encode()) > max_bytes:
        raise ValueError("Research JSON exceeds bounds")
    return json.loads(encoded)


def checked_identifier(value):
    """Require a literal bounded identifier, never a path or normalized alias."""
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("Invalid research identifier")
    return value


class ResearchRegistry:
    """Share managed research authority through the existing local journal."""

    def __init__(self, journal, *, initialize=False):
        self.journal = journal
        if initialize:
            with journal._transaction() as db:
                journal._check_schema()
                db.execute(
                    "CREATE TABLE IF NOT EXISTS research_registry_meta ("
                    "singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                    "schema_version INTEGER NOT NULL, registry_id TEXT NOT NULL UNIQUE)"
                )
                row = db.execute("SELECT * FROM research_registry_meta WHERE singleton=1").fetchone()
                if row is None:
                    db.execute(
                        "INSERT INTO research_registry_meta VALUES (1,?,?)",
                        (SCHEMA_VERSION, uuid.uuid4().hex),
                    )
                self._identity(db)
                db.execute("CREATE TABLE IF NOT EXISTS research_stores (store_id TEXT PRIMARY KEY)")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS research_reservations ("
                    "reservation_id TEXT PRIMARY KEY, store_id TEXT NOT NULL REFERENCES research_stores(store_id), "
                    "family TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0), "
                    "workflow_id TEXT NOT NULL, request_digest TEXT NOT NULL, body TEXT NOT NULL, "
                    "UNIQUE(store_id,family,version), UNIQUE(store_id,workflow_id))"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS research_commits ("
                    "reservation_id TEXT PRIMARY KEY REFERENCES research_reservations(reservation_id), "
                    "body TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS research_revision_id "
                    "ON research_reservations(json_extract(body,'$.revision_id'))"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS research_publication_intents ("
                    "effect_id TEXT PRIMARY KEY, reservation_id TEXT NOT NULL UNIQUE "
                    "REFERENCES research_reservations(reservation_id), body TEXT NOT NULL)"
                )
                for table in (
                    "research_reservations",
                    "research_commits",
                    "research_publication_intents",
                    "research_stores",
                ):
                    for action in ("UPDATE", "DELETE"):
                        db.execute(
                            f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} "
                            f"BEFORE {action} ON {table} BEGIN "
                            "SELECT RAISE(ABORT, 'Immutable research record'); END"
                        )
                checks = {
                    "research_reservations": (
                        32768,
                        (
                            "json_extract(NEW.body,'$.schema_version')=1 AND "
                            "json_extract(NEW.body,'$.reservation_id')=NEW.reservation_id AND "
                            "json_extract(NEW.body,'$.store_id')=NEW.store_id AND "
                            "json_extract(NEW.body,'$.family')=NEW.family AND "
                            "json_extract(NEW.body,'$.version')=NEW.version AND "
                            "json_extract(NEW.body,'$.workflow_id')=NEW.workflow_id AND "
                            "json_extract(NEW.body,'$.request_digest')=NEW.request_digest AND "
                            "json_type(NEW.body,'$.revision_id')='text'"
                        ),
                    ),
                    "research_commits": (
                        98304,
                        (
                            "json_extract(NEW.body,'$.reservation.reservation_id')=NEW.reservation_id AND "
                            "json_type(NEW.body,'$.manifest')='object' AND "
                            "json_type(NEW.body,'$.relative_directory')='text' AND "
                            "json_type(NEW.body,'$.publication_intent_id') IN ('null','text') AND "
                            "(SELECT COUNT(*) FROM json_each(NEW.body))=4"
                        ),
                    ),
                    "research_publication_intents": (
                        65536,
                        (
                            "json_extract(NEW.body,'$.schema_version')=1 AND "
                            "json_extract(NEW.body,'$.reservation_id')=NEW.reservation_id AND "
                            "json_extract(NEW.body,'$.effect_id')=NEW.effect_id AND "
                            "json_extract(NEW.body,'$.state')='pending' AND "
                            "json_type(NEW.body,'$.payload')='object' AND "
                            "json_type(NEW.body,'$.payload_sha256')='text'"
                        ),
                    ),
                }
                for table, (bound, shape) in checks.items():
                    db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_valid_insert BEFORE INSERT ON {table} BEGIN "
                        f"SELECT CASE WHEN typeof(NEW.body)!='text' OR length(CAST(NEW.body AS BLOB))>{bound} "
                        "OR NOT json_valid(NEW.body) THEN RAISE(ABORT,'Invalid research JSON') END; "
                        f"SELECT CASE WHEN NOT COALESCE((json_type(NEW.body)='object' AND {shape}),0) "
                        "THEN RAISE(ABORT,'Invalid research record shape') END; END"
                    )
                unique_keys = {
                    "research_stores": "store_id=NEW.store_id",
                    "research_commits": "reservation_id=NEW.reservation_id",
                    "research_publication_intents": "effect_id=NEW.effect_id OR reservation_id=NEW.reservation_id",
                    "research_reservations": (
                        "reservation_id=NEW.reservation_id OR "
                        "json_extract(body,'$.revision_id')=json_extract(NEW.body,'$.revision_id') OR "
                        "(store_id=NEW.store_id AND (workflow_id=NEW.workflow_id OR "
                        "(family=NEW.family AND version=NEW.version)))"
                    ),
                }
                for table, predicate in unique_keys.items():
                    db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} "
                        f"WHEN EXISTS(SELECT 1 FROM {table} WHERE "
                        f"CASE WHEN {'1' if table == 'research_stores' else 'json_valid(NEW.body)'} "
                        f"THEN ({predicate}) ELSE 0 END) BEGIN "
                        "SELECT RAISE(ABORT,'Immutable research record'); END"
                    )
        with journal._lock:
            self.registry_id = self._identity(journal.db)

    def _identity(self, db):
        self.journal._check_schema()
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_registry_meta'"
        ).fetchone():
            raise ValueError("Research registry not initialized")
        row = db.execute("SELECT * FROM research_registry_meta WHERE singleton=1").fetchone()
        if row is None:
            raise ValueError("Research registry not initialized")
        if row["schema_version"] != SCHEMA_VERSION:
            raise ValueError("Incompatible research registry schema")
        if hasattr(self, "registry_id") and row["registry_id"] != self.registry_id:
            raise ValueError("Research registry identity conflict")
        return row["registry_id"]

    def register_store(self, store_id):
        """Register an explicit managed-store identity without modifying its filesystem."""
        checked_identifier(store_id)
        with self.journal._transaction() as db:
            self._identity(db)
            if db.execute("SELECT 1 FROM research_stores WHERE store_id=?", (store_id,)).fetchone():
                return
            if db.execute("SELECT COUNT(*) FROM research_stores").fetchone()[0] >= MAX_STORES:
                raise ValueError("Research store capacity reached")
            db.execute("INSERT INTO research_stores VALUES (?)", (store_id,))

    def store_ids(self):
        """Return registered store identifiers in stable order."""
        with self.journal._lock:
            self._identity(self.journal.db)
            return [row[0] for row in self.journal.db.execute("SELECT store_id FROM research_stores ORDER BY store_id")]

    def reserve_candidate(
        self,
        store_id,
        family,
        workflow_id,
        *,
        job_id,
        attempt_id,
        generation,
        approval,
        parent_revision_id=None,
        publication_request=None,
    ):
        """Reserve a number for an exact accepted receipt under separate persistence approval.

        The trusted adapter authenticates the principal and protects public data before
        calling. Candidate acceptance alone is not approval. No files or graph are written.
        """
        for value in (store_id, family, workflow_id, job_id, attempt_id):
            checked_identifier(value)
        if type(generation) is not int or generation < 1:
            raise ValueError("Invalid candidate generation")
        if (
            type(approval) is not dict
            or set(approval) != {"scope", "principal"}
            or approval["scope"] != "persist_candidate"
            or type(approval["principal"]) is not str
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", approval["principal"])
        ):
            raise ValueError("Explicit persistence approval required")
        publication_request = self._publication_request(publication_request)
        return self._reserve_source(store_id, family, workflow_id,
                                    lambda: self._candidate_source(job_id, attempt_id, generation),
                                    approval, parent_revision_id, publication_request, job_id=job_id)

    def reserve_editor_revision(self, store_id, family, workflow_id, *, source, bundle,
                                approval, parent_revision_id, publication_request=None):
        """Reserve an explicit manual family/parent using a verified portable source.

        As with reserve_candidate, the trusted caller authenticates approval and
        protects all public values first. This creates no job, attempt or job event.
        """
        from .research_source import verify_editor_source
        if publication_request is not None:
            raise ValueError("Editor revision publication is unsupported")
        verify_editor_source(source, bundle)
        for value in (store_id, family, workflow_id):
            checked_identifier(value)
        if (type(approval) is not dict or set(approval) != {"scope", "principal"}
                or approval["scope"] != "persist_editor_revision" or type(approval["principal"]) is not str
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", approval["principal"])):
            raise ValueError("Explicit persistence approval required")
        source, approval = bounded_json(source), bounded_json(approval)
        return self._reserve_source(store_id, family, workflow_id, lambda: source,
                                    approval, parent_revision_id, None)

    def _reserve_source(self, store_id, family, workflow_id, load_source, approval,
                        parent_revision_id, publication_request, *, job_id=None):
        with self.journal._transaction() as db:
            self._identity(db)
            if not db.execute("SELECT 1 FROM research_stores WHERE store_id=?", (store_id,)).fetchone():
                raise ValueError("Unknown research store")
            source = load_source()
            request = {
                "store_id": store_id,
                "family": family,
                "source": source,
                "parent_revision_id": parent_revision_id,
                "publication_request": publication_request,
            }
            fingerprint = digest(request)
            previous = db.execute(
                "SELECT request_digest, body FROM research_reservations WHERE store_id=? AND workflow_id=?",
                (store_id, workflow_id),
            ).fetchone()
            if previous is not None:
                original = json.loads(previous["body"])
                if canonical_json(original["approval"]) != canonical_json(approval):
                    raise ValueError("Research persistence approval conflict")
                if previous["request_digest"] != fingerprint:
                    raise ValueError("Research workflow binding conflict")
                return original
            if parent_revision_id is not None:
                checked_identifier(parent_revision_id)
                if not db.execute(
                    "SELECT 1 FROM research_reservations r JOIN research_commits c USING(reservation_id) "
                    "WHERE json_extract(r.body,'$.revision_id')=? AND r.store_id=? AND r.family=?",
                    (parent_revision_id, store_id, family),
                ).fetchone():
                    raise ValueError("Parent must be a committed research revision in the same store and family")
            if (
                db.execute(
                    "SELECT COUNT(*) FROM research_reservations WHERE store_id=?",
                    (store_id,),
                ).fetchone()[0]
                >= MAX_RESERVATIONS_PER_STORE
            ):
                raise ValueError("Research reservation capacity reached")
            version = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM research_reservations WHERE store_id=? AND family=?",
                (store_id, family),
            ).fetchone()[0]
            body = {
                "schema_version": SCHEMA_VERSION,
                "registry_id": self.registry_id,
                "reservation_id": uuid.uuid4().hex,
                "revision_id": uuid.uuid4().hex,
                "workflow_id": workflow_id,
                "version": version,
                "request_digest": fingerprint,
                **request,
                "approval": approval,
            }
            body = bounded_json(body)
            db.execute(
                "INSERT INTO research_reservations VALUES (?,?,?,?,?,?,?)",
                (
                    body["reservation_id"],
                    store_id,
                    family,
                    version,
                    workflow_id,
                    fingerprint,
                    canonical_json(body),
                ),
            )
            if job_id is not None:
                self.journal._event(db, self.journal.get_job(job_id), "research_version_reserved")
            return json.loads(canonical_json(body))

    def get_reservation_for_workflow(self, store_id, workflow_id):
        """Read one store-scoped workflow reservation without creating or changing it."""
        checked_identifier(store_id)
        checked_identifier(workflow_id)
        with self.journal._lock:
            self._identity(self.journal.db)
            if not self.journal.db.execute(
                "SELECT 1 FROM research_stores WHERE store_id=?", (store_id,)
            ).fetchone():
                raise ValueError("Unknown research store")
            row = self.journal.db.execute(
                "SELECT reservation_id FROM research_reservations WHERE store_id=? AND workflow_id=?",
                (store_id, workflow_id),
            ).fetchone()
            if row is None:
                return None
            body = self.get_reservation(row["reservation_id"])
            if body["store_id"] != store_id or body["workflow_id"] != workflow_id:
                raise ValueError("Research workflow identity conflict")
            return body

    def get_reservation(self, reservation_id):
        """Return an immutable reservation body; unknown IDs are rejected."""
        checked_identifier(reservation_id)
        with self.journal._lock:
            self._identity(self.journal.db)
            row = self.journal.db.execute(
                "SELECT body FROM research_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Unknown research reservation")
            body = json.loads(row["body"])
            if body["registry_id"] != self.registry_id:
                raise ValueError("Research reservation registry conflict")
            return body

    def list_versions(self, store_id, family, *, limit=50, after_version=0):
        """Return ascending reservation/state/commit records; limit 1–100, exclusive cursor."""
        checked_identifier(store_id)
        checked_identifier(family)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid research version limit")
        if type(after_version) is not int or not 0 <= after_version < 2**63:
            raise ValueError("Invalid research version cursor")
        with self.journal._lock:
            self._identity(self.journal.db)
            rows = self.journal.db.execute(
                "SELECT r.body AS reservation, c.body AS commit_body FROM research_reservations r "
                "LEFT JOIN research_commits c USING(reservation_id) "
                "WHERE r.store_id=? AND r.family=? AND r.version>? ORDER BY r.version LIMIT ?",
                (store_id, family, after_version, limit),
            ).fetchall()
            return [
                {
                    "reservation": json.loads(row["reservation"]),
                    "state": "reserved" if row["commit_body"] is None else "committed",
                    "commit": None if row["commit_body"] is None else json.loads(row["commit_body"]),
                }
                for row in rows
            ]

    def latest_version(self, store_id, family):
        """Return the highest committed integer, or None; reservations never advance latest."""
        checked_identifier(store_id)
        checked_identifier(family)
        with self.journal._lock:
            self._identity(self.journal.db)
            return self.journal.db.execute(
                "SELECT MAX(r.version) FROM research_reservations r JOIN research_commits c USING(reservation_id) "
                "WHERE r.store_id=? AND r.family=?",
                (store_id, family),
            ).fetchone()[0]

    def get_commit(self, reservation_id):
        """Return a commit body or None for a known uncommitted reservation."""
        with self.journal._lock:
            self.get_reservation(reservation_id)
            row = self.journal.db.execute(
                "SELECT body FROM research_commits WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            return None if row is None else json.loads(row["body"])

    def _checked_manifest(self, reservation, manifest, relative_directory, *, source_bundle=None):
        manifest = bounded_json(manifest, max_bytes=65536, max_depth=17)
        if (
            set(manifest)
            != {
                "schema",
                "store_id",
                "registry_id",
                "reservation_id",
                "binding",
                "files",
                "digest",
            }
            or type(manifest["schema"]) is not int
            or manifest["schema"] != 1
            or canonical_json(manifest["binding"]) != canonical_json(reservation)
            or any(manifest[key] != reservation[key] for key in ("store_id", "registry_id", "reservation_id"))
            or manifest["digest"] != digest({k: v for k, v in manifest.items() if k != "digest"})
        ):
            raise ValueError("Invalid research manifest binding or digest")
        bounded_json(manifest["binding"])
        if relative_directory != f"final/{reservation['family']}/v{reservation['version']}":
            raise ValueError("Invalid research artifact directory")
        files = manifest["files"]
        if type(files) is not dict or not 2 <= len(files) <= 16:
            raise ValueError("Invalid research manifest files")
        total = 0
        for name, metadata in files.items():
            if (
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\.(yaml|json)", name)
                or name == "manifest.json"
                or re.search(r"(?i)(credential|secret|private|password|token|api[_-]?key)", name)
                or type(metadata) is not dict
                or set(metadata) != {"size", "sha256"}
                or type(metadata["size"]) is not int
                or not 0 <= metadata["size"] <= 2 * 1024 * 1024
                or type(metadata["sha256"]) is not str
                or not re.fullmatch(r"[a-f0-9]{64}", metadata["sha256"])
            ):
                raise ValueError("Invalid research file metadata")
            total += metadata["size"]
        if total > 8 * 1024 * 1024:
            raise ValueError("Research file total exceeds bounds")
        source = reservation["source"]
        from .research_source import editor_source_artifacts, source_kind
        if source_kind(source) == "editor_revision":
            originals = editor_source_artifacts(source, source_bundle)
            originals["source.json"] = canonical_json(reservation).encode()
            if set(files) != set(originals) or reservation["publication_request"] is not None:
                raise ValueError("Invalid manual research manifest")
            for name, content in originals.items():
                if files[name] != {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}:
                    raise ValueError("Research source file metadata conflict")
            return manifest
        if self._candidate_source(source["job_id"], source["attempt_id"], source["generation"]) != source:
            raise ValueError("Research source binding conflict")
        receipt = self.journal.get_candidate_receipt(source["job_id"], source["attempt_id"], source["generation"])
        if receipt is None or digest(receipt) != source["receipt_sha256"]:
            raise ValueError("Research source receipt conflict")
        originals = {
            "environment.yaml": receipt["yaml_text"].encode(),
            "candidate.json": canonical_json(receipt).encode(),
        }
        for name, content in originals.items():
            if files.get(name) != {
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }:
                raise ValueError("Research source file metadata conflict")
        return manifest

    def record_commit(self, reservation_id, manifest, relative_directory, *, publication_intent=None, source_bundle=None):
        """Record verified artifact metadata; the facade MUST verify filesystem bytes first."""
        with self.journal._transaction() as db:
            reservation = self.get_reservation(reservation_id)
            manifest = self._checked_manifest(reservation, manifest, relative_directory, source_bundle=source_bundle)
            intent = self._checked_intent(reservation, publication_intent)
            commit = {
                "reservation": reservation,
                "manifest": manifest,
                "relative_directory": relative_directory,
                "publication_intent_id": None if intent is None else intent["effect_id"],
            }
            previous = self.get_commit(reservation_id)
            if previous is not None:
                if previous != commit or (
                    intent is not None and self.get_publication_intent(intent["effect_id"]) != intent
                ):
                    raise ValueError("Research commit conflict")
                return previous
            db.execute(
                "INSERT INTO research_commits VALUES (?,?)",
                (reservation_id, canonical_json(commit)),
            )
            if intent is not None:
                self._insert_publication_intent(db, reservation, publication_intent)
            if "job_id" in reservation["source"]:
                self.journal._event(
                    db,
                    self.journal.get_job(reservation["source"]["job_id"]),
                    "research_version_committed",
                )
            return json.loads(canonical_json(commit))

    @staticmethod
    def _publication_request(request):
        if request is None:
            return None
        request = bounded_json(request, max_bytes=8192, public=True)
        if not {"effect_id", "target_profile"} <= set(request) <= {"effect_id", "target_profile", "options"}:
            raise ValueError("Invalid publication request")
        checked_identifier(request["effect_id"])
        profile = request["target_profile"]
        if type(profile) is str:
            checked_identifier(profile)
        elif type(profile) is dict and 1 <= len(profile) <= 16:
            for key, value in profile.items():
                checked_identifier(key)
                checked_identifier(value)
        else:
            raise ValueError("Invalid publication target profile")
        if "options" in request:
            bounded_json(request["options"], max_bytes=4096, public=True)
        return request

    def _checked_intent(self, reservation, intent):
        request = reservation.get("publication_request")
        if intent is None:
            if request is not None:
                raise ValueError("Publication request conflict")
            return None
        intent = bounded_json(intent, max_bytes=65536, public=True)
        if (
            not {"effect_id", "target_profile", "payload", "payload_sha256"}
            <= set(intent)
            <= {"effect_id", "target_profile", "payload", "payload_sha256", "options"}
        ):
            raise ValueError("Invalid publication intent")
        supplied = {key: value for key, value in intent.items() if key not in {"payload", "payload_sha256"}}
        if canonical_json(self._publication_request(supplied)) != canonical_json(request):
            raise ValueError("Publication request conflict")
        payload = bounded_json(intent["payload"], max_bytes=49152, public=True)
        if digest(payload) != intent["payload_sha256"]:
            raise ValueError("Publication payload digest conflict")
        return {
            **intent,
            "schema_version": SCHEMA_VERSION,
            "registry_id": self.registry_id,
            "reservation_id": reservation["reservation_id"],
            "state": "pending",
        }

    def _insert_publication_intent(self, db, reservation, intent):
        """Insert pending intent in the caller's existing journal transaction, never commit."""
        if db is not self.journal.db or not db.in_transaction:
            raise ValueError("Publication insertion requires journal transaction")
        self._identity(db)
        body = self._checked_intent(self.get_reservation(reservation["reservation_id"]), intent)
        if body is None:
            raise ValueError("Publication intent required")
        commit = self.get_commit(body["reservation_id"])
        if commit is None or commit["publication_intent_id"] != body["effect_id"]:
            raise ValueError("Publication intent requires matching research commit")
        previous = self.get_publication_intent(body["effect_id"])
        if previous is not None:
            if previous != body:
                raise ValueError("Publication intent conflict")
            return previous
        db.execute(
            "INSERT INTO research_publication_intents VALUES (?,?,?)",
            (body["effect_id"], body["reservation_id"], canonical_json(body)),
        )
        return body

    def get_publication_intent(self, effect_id):
        """Return the immutable pending intent or None; this never executes publication."""
        checked_identifier(effect_id)
        with self.journal._lock:
            self._identity(self.journal.db)
            row = self.journal.db.execute(
                "SELECT body FROM research_publication_intents WHERE effect_id=?",
                (effect_id,),
            ).fetchone()
            return None if row is None else json.loads(row["body"])

    def _candidate_source(self, job_id, attempt_id, generation):
        job = self.journal.get_job(job_id)
        current = self.journal.get_attempt(job_id)
        if (
            job["kind"] != "generate"
            or job["status"] not in {"succeeded", "cancelled"}
            or current is None
            or current["attempt_id"] != attempt_id
            or current["generation"] != generation
            or current["state"] not in {"completed", "cancelled"}
            or any(worker["job_id"] == job_id for worker in self.journal.pending_workers())
        ):
            raise ValueError("Candidate attempt is not eligible for persistence")
        receipt = self.journal.get_candidate_receipt(job_id, attempt_id, generation)
        if (
            receipt is None
            or receipt.get("publication") != "not_published"
            or type(receipt.get("yaml_text")) is not str
            or not receipt["yaml_text"].strip()
            or type(receipt.get("validation")) is not dict
            or receipt["validation"].get("valid") is not True
        ):
            raise ValueError("Accepted candidate receipt required")
        return {
            "job_id": job_id,
            "attempt_id": attempt_id,
            "generation": generation,
            "receipt_sha256": digest(receipt),
            "request_sha256": digest(job["inputs"]),
        }
