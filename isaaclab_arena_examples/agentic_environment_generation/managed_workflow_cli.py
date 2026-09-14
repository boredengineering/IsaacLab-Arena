# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Opt-in client of an already-running managed workbench; never a lifecycle owner.

All operations require --mode resolve and an explicit managed UNIX socket/origin.
--managed_publication profiles lists the four-field read-only target catalogue.
With the ordinary managed store/family/operation ID, a profile plus its exact
--managed_publication_revision prepares save-time intent, never graph authority.
--managed_publication write and --managed_publication_request_id give separate
explicit consent. The operation ID is the immutable save key; publication keys
are caller-supplied and never generated or changed by this adapter.

For saved-version actions, --managed_reservation_id and --managed_publication_effect_id
bypass generation entirely. Actions are write, observe, renew and reconcile; the
last two require a distinct request ID and --managed_publication_previous_request_id.
Observe performs only authenticated reads. Reconcile grants graph_read, not write.

Policy limit: publication ownership is API-session-bound. Each standalone CLI
invocation has a fresh ephemeral session, so it cannot recover a prior invocation's
accepted publication. Followups work only within the original still-live session
(e.g. an in-process caller retaining its transport); no session adoption, exported
credentials, persistent cookies or invented recovery endpoint are provided.
A frozen binding GET also requires the original profile to remain configured.
Verified means exact accepted GET plus the operator-attested immutable-scope receipt,
NOT an atomic database snapshot or protection against uncooperative outside writers.
"""

import argparse
import hashlib
import http.client
import json
import math
import os
import re
import socket
import stat
import struct
import sys
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _unique_json_object(pairs):
    """Reject ambiguous object keys at every nesting level of a wire response."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ManagedError("Ambiguous JSON response")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ManagedError("Invalid JSON constant")


def _finite_json_float(value):
    """Decode finite JSON floats, including bounded exponent notation."""
    result = float(value)
    if not math.isfinite(result):
        raise ManagedError("Invalid JSON number")
    return result


def validate_origin(origin):
    if not isinstance(origin, str) or not re.fullmatch(
        r"http://(?:localhost|127\.0\.0\.1|\[::1\])(?::[1-9][0-9]{0,4})?", origin
    ):
        raise ManagedError("Exact loopback HTTP origin required")
    parsed = urlsplit(origin)
    if parsed.port is not None and parsed.port > 65535:
        raise ManagedError("Invalid origin port")
    return parsed.netloc


def validate_socket(path):
    if sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED") or not hasattr(os, "geteuid"):
        raise ManagedError("Managed UNIX transport requires Linux peer credentials")
    path = Path(path).absolute()
    try:
        for entry in (path, *path.parents):
            if entry.is_symlink():
                raise ManagedError("Socket path must not contain symlinks")
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
            raise ManagedError("Socket must be a UNIX socket owned by the current user")
        return path
    except OSError:
        raise ManagedError("Managed UNIX socket unavailable") from None


class DeadlineSocket(socket.socket):
    """Apply one absolute deadline to every raw read, including buffered HTTP reads.

    SocketIO uses recv_into, so slow-drip headers/body cannot refresh the budget.
    No watchdog thread or cross-thread buffered close is needed.
    """

    def __init__(self, deadline):
        super().__init__(socket.AF_UNIX, socket.SOCK_STREAM)
        self.deadline = deadline

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Managed request deadline exceeded")
        self.settimeout(remaining)

    def connect(self, address):
        self.remaining()
        return super().connect(address)

    def recv_into(self, buffer, nbytes=0, flags=0):
        self.remaining()
        return super().recv_into(buffer, nbytes, flags)

    def sendall(self, data, flags=0):
        self.remaining()
        return super().sendall(data, flags)


class UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP framing over an explicitly owned UNIX socket, never DNS or TCP."""

    def __init__(self, path, host, timeout=10):
        super().__init__(host, timeout=timeout)
        self.path = path
        self.deadline = time.monotonic() + timeout

    def connect(self):
        path = validate_socket(self.path)
        owner = os.geteuid()
        before = path.lstat()
        self.sock = DeadlineSocket(self.deadline)
        self.sock.connect(str(path))
        # Authenticate the connected endpoint, not just a raceable pathname.
        _, uid, _ = struct.unpack(
            "3i", self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        )
        after = validate_socket(path).lstat()
        if (
            uid != owner
            or before.st_uid != owner
            or (before.st_dev, before.st_ino, before.st_uid, before.st_mode)
            != (after.st_dev, after.st_ino, after.st_uid, after.st_mode)
        ):
            raise ManagedError("Managed socket identity changed or peer owner mismatched")


class UnixTransport:
    """Bounded requests with ephemeral session credentials and no POST retries."""

    def __init__(self, path, origin, *, timeout=10):
        self.host = validate_origin(origin)
        self.path = validate_socket(path)
        self.origin = origin
        self.cookie = None
        self.csrf = None
        self.timeout = timeout

    def request(self, method, path, body=None, *, raw=False):
        connection = response = None
        try:
            if not isinstance(path, str) or not path.startswith("/api/"):
                raise ManagedError("Invalid API path")
            connection = UnixHTTPConnection(self.path, self.host, timeout=self.timeout)
            headers = {
                "Host": self.host,
                "Origin": self.origin,
                "Accept": "application/json",
            }
            if self.cookie:
                headers["Cookie"] = self.cookie
            if self.csrf:
                headers["X-CSRF-Token"] = self.csrf
            data = None if body is None else json.dumps(body, allow_nan=False).encode()
            if data is not None:
                if len(data) > MAX_RESPONSE_BYTES:
                    raise ManagedError("Request exceeds bounds")
                headers["Content-Type"] = "application/json"
            connection.request(method, path, data, headers)
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                raise ManagedError("Managed API rejected request; retain operation ID for recovery")
            length = response.getheader("Content-Length")
            if length is not None:
                if not re.fullmatch(r"[0-9]{1,10}", length) or response.getheader("Transfer-Encoding") is not None:
                    raise ManagedError("Invalid managed response framing")
                if int(length) > MAX_RESPONSE_BYTES:
                    raise ManagedError("Managed response exceeds bounds")
            content = response.read(MAX_RESPONSE_BYTES + 1)
            if time.monotonic() >= connection.deadline:
                raise ManagedError("Managed request deadline exceeded")
            if len(content) > MAX_RESPONSE_BYTES:
                raise ManagedError("Managed response exceeds bounds")
            if length is not None and len(content) != int(length):
                raise ManagedError("Truncated managed response")
            if raw:
                return content
            if response.getheader("Content-Type", "").split(";", 1)[0] != "application/json":
                raise ManagedError("Expected JSON response")
            result = json.loads(
                content,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
                parse_float=_finite_json_float,
            )
            if not isinstance(result, dict):
                raise ManagedError("Expected bounded response object")
            if path == "/api/sessions":
                csrf = result.get("csrf_token")
                header = response.getheader("Set-Cookie")
                cookies = SimpleCookie()
                cookies.load(header or "")
                if not isinstance(csrf, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", csrf):
                    raise ManagedError("Invalid session response")
                if header is None:
                    # The real establish route returns no cookie for a still-live session.
                    if self.cookie is None or self.csrf != csrf:
                        raise ManagedError("Session continuity unavailable")
                else:
                    if len(cookies) != 1:
                        raise ManagedError("Invalid session response")
                    morsel = next(iter(cookies.values()))
                    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", morsel.value):
                        raise ManagedError("Invalid session cookie")
                    self.cookie = f"{morsel.key}={morsel.value}"
                self.csrf = csrf
            return result
        except ManagedError:
            raise
        except Exception:
            raise ManagedError(
                "Managed response unavailable or ambiguous; rerun unchanged with the same operation ID"
            ) from None
        finally:
            cleanup_failed = False
            # HTTP/1.0 detaches its response from the connection; close both.
            for resource in (response, connection):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        cleanup_failed = True
            if cleanup_failed:
                raise ManagedError("Managed transport cleanup failed; retain operation ID for recovery") from None


class ManagedError(ValueError):
    """An adapter-authored diagnostic safe to print, never a server exception."""


def checked(value, pattern=r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}"):
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ManagedError("Invalid or missing managed identifier")
    return value


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _submit_new_generation(client, payload, *, model, store):
    """Submit a missing operation only after current model and store preflight."""
    caps = client.request("GET", "/api/editor")["capabilities"]
    if caps.get("generation_modes") is not True or caps.get("generation") is not True:
        raise ManagedError("Server generation_modes capability required")
    config = client.request("GET", "/api/model-settings")
    if config.get("configured") is not True or config.get("source") != "server" or not config.get("model"):
        raise ManagedError("Configured server model required")
    if model is not None and model != config["model"]:
        raise ManagedError("Requested model differs from configured server model")
    stores = client.request("GET", "/api/research/stores")["stores"]
    if not any(row.get("store_id") == store and row.get("available") is True for row in stores):
        raise ManagedError("Managed store unavailable")
    return client.request("POST", "/api/editor/generate", payload)


def _validate_acceptance(accepted):
    """Validate the complete immutable acceptance before using any control field."""
    binding_keys = (
        "store_id",
        "effect_id",
        "request_id",
        "owner_session",
        "principal",
        "operation",
        "previous_request_id",
    )
    if type(accepted) is not dict or set(accepted) != set(binding_keys) | {
        "schema_version",
        "registry_id",
        "request_digest",
        "attempt_id",
        "generation",
        "capability",
    }:
        raise ManagedError("Invalid publication acceptance schema")
    operation = accepted["operation"]
    if (
        type(accepted["schema_version"]) is not int
        or accepted["schema_version"] != 1
        or type(accepted["generation"]) is not int
        or accepted["generation"] < 1
        or operation not in ("write", "renew", "reconcile")
        or accepted["capability"] != ("graph_read" if operation == "reconcile" else "graph_write")
    ):
        raise ManagedError("Invalid publication acceptance controls")
    for key in ("store_id", "effect_id", "request_id", "owner_session", "principal"):
        checked(accepted[key])
    checked(accepted["registry_id"], r"[a-f0-9]{32}")
    checked(accepted["attempt_id"], r"[a-f0-9]{32}")
    previous = accepted["previous_request_id"]
    if previous is not None:
        checked(previous)
    if (
        (operation == "write" and previous is not None)
        or (operation == "renew" and previous is None)
        or previous == accepted["request_id"]
    ):
        raise ManagedError("Invalid publication predecessor")
    if accepted["request_digest"] != digest({k: accepted[k] for k in binding_keys}):
        raise ManagedError("Publication acceptance digest mismatch")


def _validate_publication_state(state):
    """Reject malformed public state before eligibility or verification branching."""
    if type(state) is not dict or set(state) != {
        "schema_version",
        "effect_id",
        "target_profile",
        "payload_sha256",
        "state",
        "cancelled",
        "generation",
        "attempt_id",
        "request_id",
        "receipt",
        "write_claim_count",
        "reconciliation",
        "write_callback_open",
    }:
        raise ManagedError("Invalid publication state schema")
    if (
        type(state["schema_version"]) is not int
        or state["schema_version"] != 1
        or any(type(state[k]) is not bool for k in ("cancelled", "write_callback_open"))
        or type(state["generation"]) is not int
        or state["generation"] < 1
        or type(state["write_claim_count"]) is not int
        or state["write_claim_count"] < 0
        or state["state"]
        not in ("pending", "claimed", "released", "verified", "unknown", "blocked_authorization", "cancelled_no_send")
    ):
        raise ManagedError("Invalid publication state controls")
    checked(state["effect_id"])
    checked(state["request_id"])
    checked(state["attempt_id"], r"[a-f0-9]{32}")
    checked(state["payload_sha256"], r"[a-f0-9]{64}")
    reconciliation = state["reconciliation"]
    if reconciliation is not None and (
        type(reconciliation) is not dict
        or set(reconciliation) != {"state"}
        or reconciliation["state"] not in ("claimed", "released", "unknown", "verified")
    ):
        raise ManagedError("Invalid publication reconciliation")
    if state["state"] == "verified":
        if type(state["receipt"]) is not dict:
            raise ManagedError("Missing publication receipt")
    elif state["receipt"] is not None:
        raise ManagedError("Unexpected publication receipt")


def _match_publication_fence(state, accepted):
    fence = ("effect_id", "request_id", "attempt_id", "generation")
    if digest({k: state[k] for k in fence}) != digest({k: accepted[k] for k in fence}):
        raise ManagedError("Exact publication request binding mismatch")


def _publication(client, args, result, commit, session, deadline_seconds, poll_interval, *, submitted=None):
    """Authorize one explicit write and verify its exact accepted receipt readback."""
    from isaaclab_arena.agentic_environment_generation.workbench.research_graph_transport import (
        IMMUTABLE_SCOPE_DECLARATION,
    )

    reservation = commit["reservation"]
    effect = checked(commit["publication_intent_id"])
    request_id = checked(args.managed_publication_request_id)
    store = checked(args.managed_store_id)
    root = f"/api/research/stores/{store}"
    base = f"{root}/publications/{effect}"
    result.update(publication="unknown", publication_effect_id=effect, publication_request_id=request_id)
    if submitted is None:
        body = {"request_id": request_id}
        if args.managed_publication in ("renew", "reconcile"):
            body["previous_request_id"] = args.managed_publication_previous_request_id
        # GET has no authoritative absence response. Explicit POST replays the exact
        # immutable key before the server prepares config or issues any new grant.
        try:
            submitted = client.request("POST", base + "/" + args.managed_publication, body)
        except Exception:
            raise ManagedError(
                "Publication submission unavailable or ambiguous; retain exact saved version/effect/request IDs. API"
                " recovery is session-bound; use read-only observe in the original live session, never regenerate or"
                " substitute credentials"
            ) from None
        if type(submitted["accepted_new"]) is not bool:
            raise ManagedError("Ambiguous publication acceptance")
    accepted = submitted["accepted"]
    _validate_acceptance(accepted)
    _validate_publication_state(submitted["state"])
    expected = {
        "store_id": store,
        "effect_id": effect,
        "request_id": request_id,
        "owner_session": checked(session["session_id"]),
        "principal": session["session_id"],
        "operation": accepted["operation"] if args.managed_publication == "observe" else args.managed_publication,
        "previous_request_id": (
            accepted["previous_request_id"]
            if args.managed_publication == "observe"
            else args.managed_publication_previous_request_id
        ),
    }
    if (
        any(accepted[k] != v for k, v in expected.items())
        or type(accepted["schema_version"]) is not int
        or accepted["schema_version"] != 1
        or accepted["request_digest"] != digest(expected)
        or accepted["registry_id"] != reservation["registry_id"]
        or accepted["capability"] != ("graph_read" if expected["operation"] == "reconcile" else "graph_write")
        or expected["operation"] not in ("write", "renew", "reconcile")
        or type(accepted["generation"]) is not int
        or accepted["generation"] < 1
    ):
        raise ManagedError("Publication acceptance binding mismatch")
    checked(accepted["attempt_id"], r"[a-f0-9]{32}")
    result["publication_accepted"] = accepted
    deadline = time.monotonic() + min(max(deadline_seconds, 0), 600)
    while True:
        try:
            observed = client.request("GET", base + f"/requests/{request_id}")
        except Exception:
            raise ManagedError(
                "Publication accepted; exact observation unavailable. Retain saved version/effect/request IDs; "
                "recovery is session-bound: use read-only observe in the original live session, not a new CLI "
                "invocation. Never regenerate or substitute credentials"
            ) from None
        state = observed["state"]
        _validate_publication_state(state)
        fence = ("effect_id", "request_id", "attempt_id", "generation")
        if digest(observed["accepted"]) != digest(accepted) or digest({k: state[k] for k in fence}) != digest(
            {k: accepted[k] for k in fence}
        ):
            raise ManagedError("Exact publication request binding mismatch")
        if state["target_profile"] != reservation["publication_request"]["target_profile"]:
            raise ManagedError("Publication target binding mismatch")
        if state["state"] == "verified":
            break
        reconciling = accepted["operation"] == "reconcile" and state["reconciliation"] in (
            {"state": "claimed"},
            {"state": "released"},
        )
        if state["state"] not in ("claimed", "released") and not reconciling:
            result["publication"] = state["state"] if state["state"] == "blocked_authorization" else "unknown"
            raise ManagedError(
                "Publication not verified; unknown requires explicit read-only reconcile, blocked_authorization"
                " requires explicit renew. API ownership is session-bound; no automatic retry or credential"
                " substitution"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ManagedError("Publication observation deadline exceeded; accepted work was not cancelled")
        time.sleep(min(max(poll_interval, 0.05), 2, remaining))
    # A status string alone is never evidence. Read the API's verified frozen binding.
    try:
        binding = client.request("GET", f"{root}/versions/{reservation['reservation_id']}/publication-binding")
    except Exception:
        raise ManagedError(
            "Publication accepted; frozen binding unavailable under current API profile policy"
        ) from None
    version = binding["versionRef"]
    if (
        binding["storeId"] != store
        or binding["effectId"] != effect
        or binding["registryId"] != reservation["registry_id"]
        or binding["target"] != reservation["publication_request"]["target_profile"]
        or digest({k: version[k] for k in ("reservation_id", "revision_id", "version")})
        != digest({k: reservation[k] for k in ("reservation_id", "revision_id", "version")})
        or version["payload_sha256"] != state["payload_sha256"]
    ):
        raise ManagedError("Frozen publication binding mismatch")
    expected_receipt = {
        "schema_version": 1,
        "status": "verified",
        "effect_id": effect,
        "target_profile": binding["target"],
        "payload_sha256": version["payload_sha256"],
        "transport": {
            "status": "verified",
            "effect_id": effect,
            **{k: version[k] for k in ("database", "scope_id", "projection_digest", "canonical_identity")},
            "verification_boundary": {
                "method": "operator_attested_immutable_scope_v1",
                "operator_attested": True,
                "declaration": IMMUTABLE_SCOPE_DECLARATION,
                "database_snapshot": False,
            },
        },
    }
    if digest(state["receipt"]) != digest(expected_receipt):
        raise ManagedError("Publication receipt or verification boundary mismatch")
    result.update(publication="verified", publication_receipt=expected_receipt)


def _resume_publication(client, args, result, session, target, deadline_seconds, poll_interval):
    """Observe accepted publication before reading config-dependent frozen metadata."""
    root = f"/api/research/stores/{args.managed_store_id}"
    effect, request_id = args.managed_publication_effect_id, args.managed_publication_request_id
    lookup_id = args.managed_publication_previous_request_id or request_id
    result.update(publication="unknown", publication_effect_id=effect, publication_request_id=request_id)
    observed = accepted = None
    if args.managed_publication != "write":
        try:
            observed = client.request("GET", f"{root}/publications/{effect}/requests/{lookup_id}")
        except Exception:
            raise ManagedError(
                "Publication lookup unavailable: API ownership is session-bound; a new CLI session cannot adopt "
                "accepted work. No persistent cookies or cross-session recovery route; retain exact identifiers"
            ) from None
        accepted = observed["accepted"]
        _validate_acceptance(accepted)
        _validate_publication_state(observed["state"])
        request_binding = {
            k: accepted[k]
            for k in (
                "store_id",
                "effect_id",
                "request_id",
                "owner_session",
                "principal",
                "operation",
                "previous_request_id",
            )
        }
        if accepted["request_digest"] != digest(request_binding) or observed["state"]["effect_id"] != effect:
            raise ManagedError("Publication predecessor binding mismatch")
        if any(
            accepted[k] != v
            for k, v in {
                "effect_id": effect,
                "request_id": lookup_id,
                "store_id": args.managed_store_id,
                "owner_session": session["session_id"],
                "principal": session["session_id"],
            }.items()
        ):
            raise ManagedError("Publication acceptance binding mismatch")
        result["publication_accepted"] = accepted
    resid = args.managed_reservation_id
    if args.managed_publication in ("renew", "reconcile"):
        state = observed["state"]
        eligible = "blocked_authorization" if args.managed_publication == "renew" else "unknown"
        # Never treat a failed GET as absence or old acceptance as current state.
        if state["request_id"] == request_id:
            # An old acceptance GET carries current state, not the old attempt.
            # Resolve and validate the exact followup separately; never POST replay.
            observed = client.request("GET", f"{root}/publications/{effect}/requests/{request_id}")
            replay = observed["accepted"]
            _validate_acceptance(replay)
            _validate_publication_state(observed["state"])
            _match_publication_fence(observed["state"], replay)
            if any(
                replay[k] != accepted[k] for k in ("store_id", "effect_id", "owner_session", "principal", "registry_id")
            ) or (
                replay["operation"] != args.managed_publication
                or replay["previous_request_id"] != lookup_id
                or replay["request_id"] != request_id
            ):
                raise ManagedError("Publication followup replay mismatch")
        else:
            _match_publication_fence(state, accepted)
            if state["state"] != eligible:
                raise ManagedError("Publication predecessor is not eligible for explicit followup")
    commit = client.request("GET", f"{root}/versions/{resid}")
    reservation, manifest = commit["reservation"], commit["manifest"]
    if (
        reservation["reservation_id"] != resid
        or reservation["store_id"] != args.managed_store_id
        or reservation["workflow_id"] != args.managed_operation_id
        or reservation["family"] != args.managed_family
        or (accepted is not None and reservation["registry_id"] != accepted["registry_id"])
        or commit["publication_intent_id"] != effect
        or reservation["publication_request"]["effect_id"] != effect
        or (target is not None and reservation["publication_request"]["target_profile"] != target)
        or manifest["binding"] != reservation
        or manifest["reservation_id"] != resid
        or manifest["store_id"] != args.managed_store_id
        or manifest["registry_id"] != reservation["registry_id"]
        or manifest["digest"] != digest({k: v for k, v in manifest.items() if k != "digest"})
    ):
        raise ManagedError("Saved publication binding mismatch")
    if args.managed_publication in ("renew", "reconcile"):
        binding = client.request("GET", f"{root}/versions/{resid}/publication-binding")
        version = binding["versionRef"]
        if (
            binding["storeId"] != args.managed_store_id
            or binding["effectId"] != effect
            or binding["registryId"] != reservation["registry_id"]
            or binding["target"] != reservation["publication_request"]["target_profile"]
            or observed["state"]["target_profile"] != binding["target"]
            or observed["state"]["payload_sha256"] != version["payload_sha256"]
            or digest({k: version[k] for k in ("reservation_id", "revision_id", "version")})
            != digest({k: reservation[k] for k in ("reservation_id", "revision_id", "version")})
        ):
            raise ManagedError("Publication predecessor frozen binding mismatch")
    artifact = client.request("GET", f"{root}/versions/{resid}/artifacts/environment.yaml", raw=True)
    meta = manifest["files"]["environment.yaml"]
    if len(artifact) != meta["size"] or hashlib.sha256(artifact).hexdigest() != meta["sha256"]:
        raise ManagedError("Saved artifact hash mismatch")
    result.update(
        persistence="saved",
        version_ref={
            **{k: reservation[k] for k in ("store_id", "family", "reservation_id", "revision_id", "version")},
            "sha256": meta["sha256"],
        },
    )
    _publication(
        client,
        args,
        result,
        commit,
        session,
        deadline_seconds,
        poll_interval,
        submitted=observed if observed is not None and observed["accepted"]["request_id"] == request_id else None,
    )


def _list_profiles(args, argv, transport, result):
    """Read bounded publication target metadata without creating execution authority."""
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False, exit_on_error=False)
    for option in ("--mode", "--managed_api_socket", "--managed_api_origin", "--managed_publication"):
        parser.add_argument(option)
    _, unsupported = parser.parse_known_args(argv)
    if unsupported or args.api_key is not None or args.base_url is not None or args.temperature != 0.2:
        raise ManagedError("Profile catalogue accepts only transport options and --mode resolve")
    validate_origin(args.managed_api_origin)
    client = transport if transport is not None else UnixTransport(args.managed_api_socket, args.managed_api_origin)
    client.request("POST", "/api/sessions", {})
    catalogue = client.request("GET", "/api/research/publication-profiles")
    profiles = catalogue["profiles"]
    if set(catalogue) != {"profiles"} or type(profiles) is not list or len(profiles) > 16:
        raise ManagedError("Ambiguous publication profile catalogue")
    seen = set()
    for row in profiles:
        if (
            set(row) != {"profile_id", "revision", "scope_ownership", "available"}
            or row["available"] is not True
            or row["scope_ownership"] != "cooperative_immutable"
        ):
            raise ManagedError("Invalid publication profile metadata")
        profile_id = checked(row["profile_id"])
        checked(row["revision"], r"[a-f0-9]{64}")
        if profile_id in seen:
            raise ManagedError("Duplicate publication profile")
        seen.add(profile_id)
    result["profiles"] = profiles


def _resolve_options(args, argv, result):
    """Validate explicit managed options before session or model activity."""
    operation_id = checked(args.managed_operation_id)
    result["operation_id"] = operation_id
    store = checked(args.managed_store_id)
    family = checked(args.managed_family)
    target = None
    if args.managed_publication_profile is not None or args.managed_publication_revision is not None:
        target = {
            "profile_id": checked(args.managed_publication_profile),
            "revision": checked(args.managed_publication_revision, r"[a-f0-9]{64}"),
            "scope_ownership": "cooperative_immutable",
        }
    recovery = args.managed_reservation_id is not None or args.managed_publication_effect_id is not None
    if recovery:
        checked(args.managed_reservation_id, r"[a-f0-9]{32}")
        checked(args.managed_publication_effect_id)
        if args.managed_publication not in ("write", "observe", "renew", "reconcile"):
            raise ManagedError("Explicit publication observation or followup required")
    if args.managed_publication in ("renew", "reconcile"):
        checked(args.managed_publication_previous_request_id)
        if not recovery or args.managed_publication_previous_request_id == args.managed_publication_request_id:
            raise ManagedError("Explicit followup requires saved version and distinct stable request keys")
    elif args.managed_publication_previous_request_id is not None:
        raise ManagedError("Predecessor requires explicit renew or reconcile")
    if args.managed_publication is not None or args.managed_publication_request_id is not None:
        if not recovery and (args.managed_publication != "write" or target is None):
            raise ManagedError("Explicit write consent and frozen publication target required")
        checked(args.managed_publication_request_id)
    allowed = {"--mode", "--prompt", "--model", "--base_spec", "--feedback"} | {
        f"--managed_{name}"
        for name in (
            "api_socket",
            "api_origin",
            "store_id",
            "family",
            "operation_id",
            "publication_profile",
            "publication_revision",
            "publication",
            "publication_request_id",
            "reservation_id",
            "publication_effect_id",
            "publication_previous_request_id",
        )
    }
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False, exit_on_error=False)
    for option in sorted(allowed):
        parser.add_argument(option)
    _, unsupported = parser.parse_known_args(argv)
    if unsupported:
        raise ManagedError("Unsupported managed CLI override; only prompt, model and frozen base are supported")
    if args.api_key is not None or args.base_url is not None or args.temperature != 0.2:
        raise ManagedError("Managed API cannot honor credential, endpoint or sampling overrides")
    return operation_id, store, family, target, recovery


def _generation_payload(args, operation_id):
    """Freeze and validate the explicit generation input without opening a session."""
    if args.feedback is not None and args.base_spec is None:
        raise ManagedError("Feedback requires an explicit frozen base")
    payload = {
        "operation": "new",
        "prompt": args.prompt,
        "retrieval_policy": "allow_fallback",
        "idempotency_key": operation_id,
    }
    if args.base_spec is not None:
        from isaaclab_arena.agentic_environment_generation.workbench.document_yaml import (
            MAX_YAML_BYTES,
            parse_yaml,
            reject_unknown_fields,
        )
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

        with args.base_spec.open("rb") as stream:
            frozen = stream.read(MAX_YAML_BYTES + 1)
        if len(frozen) > MAX_YAML_BYTES:
            raise ManagedError("Base exceeds bounded document size")
        text = frozen.decode("utf-8")
        data = parse_yaml(text)
        if "external_yaml" in data:
            raise ManagedError("Managed refinement requires flattened YAML; includes are unsupported")
        reject_unknown_fields(data)
        ArenaEnvGraphSpec.from_dict(data)
        payload.update(operation="refine", base_yaml=text, prompt=args.feedback or args.prompt)
    if not payload["prompt"].strip() or len(payload["prompt"]) > 16000:
        raise ManagedError("Prompt must be nonblank and bounded")
    return payload


def run_managed(args, *, argv=(), transport=None, deadline_seconds=120, poll_interval=0.5):
    """Resolve and persist an exact candidate; preparation is not publication."""
    result = {
        "publication": "not_requested",
        "persistence": "not_saved",
    }
    try:
        if args.mode != "resolve":
            raise ManagedError("Managed mode requires --mode resolve")
        if args.managed_publication == "profiles":
            _list_profiles(args, argv, transport, result)
            print(json.dumps(result, sort_keys=True))
            return 0
        operation_id, store, family, target, recovery = _resolve_options(args, argv, result)
        if recovery:
            validate_origin(args.managed_api_origin)
            client = (
                transport if transport is not None else UnixTransport(args.managed_api_socket, args.managed_api_origin)
            )
            session = client.request("POST", "/api/sessions", {})
            _resume_publication(client, args, result, session, target, deadline_seconds, poll_interval)
            print(json.dumps(result, sort_keys=True))
            return 0
        payload = _generation_payload(args, operation_id)
        validate_origin(args.managed_api_origin)
        client = transport if transport is not None else UnixTransport(args.managed_api_socket, args.managed_api_origin)
        session = client.request("POST", "/api/sessions", {})
        # Match GenerateDraft.model_dump(), including its omitted-field defaults.
        request_sha256 = digest({"credential_ref": None, "document_id": None, "base_yaml": None, **payload})
        lookup = client.request(
            "GET", f"/api/editor/generate/operations/{operation_id}?request_sha256={request_sha256}"
        )
        if set(lookup) != {"job"}:
            raise ManagedError("Ambiguous operation lookup; retain operation ID for recovery")
        job = lookup["job"]
        if job is None:
            job = _submit_new_generation(client, payload, model=args.model, store=store)
        if job["kind"] != "generate" or job["inputs"]["request_sha256"] != request_sha256:
            raise ManagedError("Accepted request binding mismatch")
        accepted_inputs = job["inputs"]
        profile = accepted_inputs["workflow_authorization"]["model"]["profile"]
        if profile["source"] != "server" or not profile["model"]:
            raise ManagedError("Accepted server model required")
        if args.model is not None and args.model != profile["model"]:
            raise ManagedError("Requested model differs from accepted server model")
        result["effective_settings"] = {
            "model_source": profile["source"],
            "model": profile["model"],
            "endpoint": "server configured; not exposed",
            "temperature": "server default; not exposed",
        }
        job_id = checked(job["id"], r"[a-f0-9]{32}")
        result["job_id"] = job_id
        deadline = time.monotonic() + min(max(deadline_seconds, 0), 600)
        while True:
            job = client.request("GET", f"/api/jobs/{job_id}")
            if job["id"] != job_id or job["kind"] != "generate" or job["inputs"] != accepted_inputs:
                raise ManagedError("Exact job binding mismatch")
            if job["status"] == "succeeded":
                break
            if job["status"] not in ("queued", "running"):
                raise ManagedError("Accepted job did not succeed; no automatic retry or reauthorization")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ManagedError("Polling deadline exceeded; accepted work was not cancelled")
            time.sleep(min(max(poll_interval, 0.05), 2, remaining))
        root = f"/api/research/stores/{store}"
        source = client.request("GET", f"{root}/candidates/{job_id}")
        if source["job_id"] != job_id or source["request_sha256"] != digest(accepted_inputs):
            raise ManagedError("Candidate binding mismatch")
        checked(source["attempt_id"], r"[a-f0-9]{32}")
        for field in ("receipt_sha256", "request_sha256"):
            checked(source[field], r"[a-f0-9]{64}")
        if type(source["generation"]) is not int or source["generation"] < 1:
            raise ManagedError("Invalid candidate generation")
        result["persistence"] = "unknown"
        commit = client.request(
            "POST",
            root + "/versions",
            {
                "idempotency_key": operation_id,
                "family": family,
                "parent_revision_id": None,
                "source_job_id": job_id,
                "source_attempt_id": source["attempt_id"],
                "source_generation": source["generation"],
                **({"publication_target": target} if target is not None else {}),
            },
        )
        reservation = commit["reservation"]
        resid = checked(reservation["reservation_id"], r"[a-f0-9]{32}")
        revision = checked(reservation["revision_id"], r"[a-f0-9]{32}")
        if (
            reservation["store_id"] != store
            or reservation["family"] != family
            or reservation["workflow_id"] != operation_id
            or reservation["source"] != source
            or reservation["parent_revision_id"] is not None
        ):
            raise ManagedError("Commit binding mismatch")
        if target is None:
            if commit["publication_intent_id"] is not None:
                raise ManagedError("Unexpected publication preparation")
        else:
            effect = checked(commit["publication_intent_id"], r"[a-f0-9]{64}")
            if reservation["publication_request"] != {"effect_id": effect, "target_profile": target}:
                raise ManagedError("Frozen publication target mismatch")
        manifest = commit["manifest"]
        if (
            manifest["binding"] != reservation
            or manifest["reservation_id"] != resid
            or manifest["store_id"] != store
            or manifest["registry_id"] != reservation["registry_id"]
            or manifest["digest"] != digest({k: v for k, v in manifest.items() if k != "digest"})
        ):
            raise ManagedError("Commit manifest hash mismatch")
        if client.request("GET", f"{root}/versions/{resid}") != commit:
            raise ManagedError("Commit readback mismatch")
        artifact_path = f"{root}/versions/{resid}/artifacts/environment.yaml"
        artifact = client.request("GET", artifact_path, raw=True)
        meta = manifest["files"]["environment.yaml"]
        if len(artifact) != meta["size"] or hashlib.sha256(artifact).hexdigest() != meta["sha256"]:
            raise ManagedError("Artifact hash mismatch")
        result.update(
            persistence="saved",
            version_ref={
                "store_id": store,
                "family": family,
                "reservation_id": resid,
                "revision_id": revision,
                "version": reservation["version"],
                "sha256": meta["sha256"],
            },
            artifact_url=args.managed_api_origin + artifact_path,
            authentication_required=True,
        )
        if target is not None:
            result.update(publication="prepared", publication_effect_id=effect, publication_target=target)
        if args.managed_publication == "write":
            _publication(client, args, result, commit, session, deadline_seconds, poll_interval)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        result["error"] = (
            str(error)
            if isinstance(error, ManagedError)
            else "Managed request failed or response was ambiguous; rerun unchanged with the same operation ID"
        )
        print(json.dumps(result, sort_keys=True))
        return 2
