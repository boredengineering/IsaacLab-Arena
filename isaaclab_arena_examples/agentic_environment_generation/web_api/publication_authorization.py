# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Memory-only graph authority, independent of model credentials and graph probes.

Interface (all calls synchronous; serialize access and release without awaiting):
* PublicationAuthorization(sessions, profiles_getter, *, clock=time.time,
  capacity=128). Getter returns ID -> {connection: {uri,user,password,database},
  immutable_scope: True}. No environment defaults, network IO or initialization.
* profile_metadata(profile_id) returns detached {profile_id, revision: SHA256,
  scope_ownership: 'cooperative_immutable'}. Revision hashes URI/user/database and
  explicit scope approval, excluding password. Only this full frozen mapping is
  accepted as an intent target; a bare ID cannot bind an endpoint revision.
* issue(session, effect_intent, request_id, capability) returns exactly grant_id,
  request_id, effect_id, target_profile, payload_sha256, capability, expires_at.
  Intent must contain effect_id, target_profile, payload, payload_sha256; extra
  registry fields are frozen too. TTL is <=180 seconds and capped to session.
  Only graph_write/graph_read are accepted. This owns separate records, not an
  ExecutionGrants instance (whose corresponding roles are publication_write and
  reconciliation_read); never pass those role names or model/source references.
* bind_attempt(metadata, attempt_id, generation) is TRUSTED COORDINATOR ONLY,
  called after the core claim. It binds once, never changes an existing binding.
* resolve(metadata, *, capability, effect_id, request_id, attempt_id, generation)
  and __call__ return (detached_private_connection, exact_detached_metadata).
  Core must supply identifiers from its authenticated current immutable intent
  and fenced attempt. Binding is not a claim/current-state oracle: coordinator
  must revoke superseded attempts; never expose bind_attempt as a public route.
* revoke(grant_id), forget_owner(session_id), purge(), clear(), protect_public(v).
  Wire session invalidation to forget_owner and shutdown to clear, not model-key
  Forget. Purge additionally checks session validity and the original full private
  profile. Password rotation denies old grants; explicit issue can approve a new
  secret for the same frozen public target. protect_public screens configured
  passwords even without grants, plus frozen passwords before purging. Safe
  URI/user/database are not secrets; scope revocation is not a public-output ban.
  Already returned copies cannot be retracted. Transport MUST receive
  immutable_scope=True explicitly only after
  successful authorization; a returned connection alone is not scope approval.

IDs use the core's 1..64 ASCII identifier syntax. Intent/metadata are finite
32-KiB JSON, depth <=16 and <=4096 nodes; public scanning permits 2 MiB. All
failures expose generic ValueError messages, never private configuration.
"""

import hashlib
import json
import re
import secrets
import time

from .execution_grants import _bounded_copy, _finite
from .graph_access import checked_graph_config
from .provider_security import reject_secret

ERROR = "Publication authorization unavailable"


def _identifier(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError(ERROR)
    return value


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class PublicationAuthorization:
    """Own publication credentials without accessing providers during construction."""

    def __init__(self, sessions, profiles_getter, *, clock=time.time, capacity=128):
        if type(capacity) is not int or not 1 <= capacity <= 128:
            raise ValueError(ERROR)
        self.sessions = sessions
        self.profiles_getter = profiles_getter
        self.clock = clock
        self._capacity = capacity
        self._records = {}

    def issue(self, session, effect_intent, request_id, capability):
        """Freeze an explicit profile and descriptor; return only core grant metadata."""
        try:
            session = _bounded_copy(session)
            frozen = _bounded_copy(effect_intent, max_bytes=32768)
            owner = _identifier(session["session_id"])
            _identifier(request_id)
            _identifier(frozen["effect_id"])
            if capability not in ("graph_write", "graph_read"):
                raise ValueError(ERROR)
            target = frozen["target_profile"]
            if type(target) is not dict:
                raise ValueError(ERROR)
            public, config = self._profile(target["profile_id"])
            if target != public or _digest(frozen["payload"]) != frozen["payload_sha256"]:
                raise ValueError(ERROR)
            current = self.sessions.get_by_id(owner)
            now = self.clock()
            if (
                current is None
                or current.get("session_id") != owner
                or not _finite(now)
                or not _finite(current["expires_at"])
                or not _finite(session["expires_at"])
            ):
                raise ValueError(ERROR)
            expires_at = min(now + 180, current["expires_at"], session["expires_at"])
            if expires_at <= now:
                raise ValueError(ERROR)
            metadata = dict(
                grant_id=secrets.token_hex(32),
                request_id=request_id,
                effect_id=frozen["effect_id"],
                target_profile=public,
                payload_sha256=frozen["payload_sha256"],
                capability=capability,
                expires_at=expires_at,
            )
            reject_secret(frozen, config["password"])
            reject_secret(metadata, config["password"])
            self.protect_public(frozen)
            self.protect_public(metadata)
            if len(self._records) >= self._capacity or metadata["grant_id"] in self._records:
                raise ValueError(ERROR)
            self._records[metadata["grant_id"]] = dict(
                metadata=_bounded_copy(metadata), config=config, owner=owner, intent=frozen, attempt=None
            )
            return _bounded_copy(metadata)
        except Exception:
            raise ValueError(ERROR) from None

    def revoke(self, grant_id):
        """Forget one independent grant reference."""
        self._records.pop(_identifier(grant_id), None)

    def forget_owner(self, owner_id):
        """Session invalidation hook; do not connect this to model-key Forget."""
        _identifier(owner_id)
        for grant_id, record in tuple(self._records.items()):
            if record["owner"] == owner_id:
                self.revoke(grant_id)

    def clear(self):
        """Drop private memory on application shutdown."""
        self._records.clear()

    def purge(self):
        """Forget expired, revoked, or changed original authority without graph IO."""
        now = self.clock()
        if not _finite(now):
            self.clear()
            raise ValueError(ERROR)
        for grant_id, record in tuple(self._records.items()):
            try:
                session = self.sessions.get_by_id(record["owner"])
                public, config = self._profile(record["metadata"]["target_profile"]["profile_id"])
                if (
                    session is None
                    or session.get("session_id") != record["owner"]
                    or not _finite(session["expires_at"])
                    or now >= min(session["expires_at"], record["metadata"]["expires_at"])
                    or public != record["metadata"]["target_profile"]
                    or config != record["config"]
                ):
                    self.revoke(grant_id)
            except Exception:
                self.revoke(grant_id)

    def protect_public(self, value):
        """Reject configured and frozen passwords without rewriting caller values.

        Scan frozen records before purge so this call rejects an old in-flight
        marker during rotation. Purge still runs on rejection. Once forgotten,
        old passwords are not retained: coordinators must fence/discard stale
        results and screen already released private copies at their own boundary.
        This guard is not authorization or an indefinite revoked-secret denylist.
        Recover nonempty text passwords independently of connection/scope validity;
        absent, empty or nontext finite-JSON passwords provide no text marker.
        Nonempty blank text is scanned literally. Uninspectable JSON fails closed.
        """
        try:
            value = _bounded_copy(value, max_bytes=2 * 1024 * 1024, max_nodes=131072)
            try:
                for record in self._records.values():
                    reject_secret(value, record["config"]["password"])
                profiles = self.profiles_getter()
                if type(profiles) is not dict or len(profiles) > 16:
                    raise ValueError(ERROR)
                # Bound/detach the collection as well as each profile. Invalid JSON
                # is uninspectable and must fail closed, never be silently skipped.
                profiles = _bounded_copy(profiles, max_bytes=16 * 65536, max_nodes=16 * 4096)
                # Connection validity and scope approval confer authority, not secrecy.
                for profile in profiles.values():
                    profile = _bounded_copy(profile)
                    if type(profile) is not dict:
                        continue
                    connection = profile.get("connection")
                    if type(connection) is not dict:
                        continue
                    password = connection.get("password")
                    # Absent/null/nontext JSON passwords have no text marker. Empty
                    # strings have none either; preserve all nonempty text literally,
                    # including whitespace-only passwords (never strip or coerce).
                    if type(password) is str and password:
                        reject_secret(value, password)
            finally:
                self.purge()
        except Exception:
            raise ValueError(ERROR) from None

    def _record(self, metadata):
        metadata = _bounded_copy(metadata, max_bytes=32768)
        self.purge()
        if type(metadata) is not dict:
            raise ValueError(ERROR)
        grant_id = _identifier(metadata.get("grant_id"))
        record = self._records.get(grant_id)
        if record is None or metadata != record["metadata"]:
            raise ValueError(ERROR)
        return record

    def bind_attempt(self, metadata, attempt_id, generation):
        """Trusted coordinator only: bind once after claim, before any worker release."""
        record = self._record(metadata)
        _identifier(attempt_id)
        if type(generation) is not int or not 1 <= generation <= 2**63 - 1:
            raise ValueError(ERROR)
        binding = (attempt_id, generation)
        if record["attempt"] not in (None, binding):
            raise ValueError(ERROR)
        record["attempt"] = binding

    def resolve(self, metadata, *, capability, effect_id, request_id, attempt_id, generation):
        """Return detached config and exact metadata; resolving never binds an attempt."""
        try:
            record = self._record(metadata)
            for value in (effect_id, request_id, attempt_id):
                _identifier(value)
            if type(generation) is not int or not 1 <= generation <= 2**63 - 1:
                raise ValueError(ERROR)
            if record["attempt"] != (attempt_id, generation):
                raise ValueError(ERROR)
            if any(
                record["metadata"][key] != value
                for key, value in (("capability", capability), ("effect_id", effect_id), ("request_id", request_id))
            ):
                raise ValueError(ERROR)
            return _bounded_copy(record["config"]), _bounded_copy(record["metadata"])
        except Exception:
            raise ValueError(ERROR) from None

    __call__ = resolve

    def _profile(self, profile_id):
        try:
            _identifier(profile_id)
            profile = _bounded_copy(self.profiles_getter()[profile_id])
            if type(profile) is not dict or set(profile) != {"connection", "immutable_scope"}:
                raise ValueError(ERROR)
            if profile["immutable_scope"] is not True:
                raise ValueError(ERROR)
            config = checked_graph_config(profile["connection"])
            public = dict(
                profile_id=profile_id,
                revision=_digest({
                    **{k: config[k] for k in ("uri", "user", "database")},
                    "immutable_scope": True,
                }),
                scope_ownership="cooperative_immutable",
            )
            reject_secret(public, config["password"])
            return public, config
        except Exception:
            raise ValueError(ERROR) from None

    def profile_metadata(self, profile_id):
        """Return detached identifiers for an explicitly approved immutable scope."""
        return self._profile(profile_id)[0]
