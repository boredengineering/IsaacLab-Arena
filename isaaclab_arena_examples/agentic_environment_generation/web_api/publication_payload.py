# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Shared frozen publication preparation and one-shot transport; no authority changes."""

import copy
import hashlib
import json

from isaaclab_arena.agentic_environment_generation.workbench import research_graph_transport
from isaaclab_arena.agentic_environment_generation.workbench.research_projection import (
    project_scene,
    validate_projection,
)
from isaaclab_arena.agentic_environment_generation.workbench.research_registry import (
    canonical_json,
    checked_identifier,
    digest,
)
from isaaclab_arena.agentic_environment_generation.workbench.research_source import source_kind, verify_frozen_spec
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

from .graph_access import checked_graph_config


def prepare_publication(store, authorization, effect_id):
    intent = store.registry.get_publication_intent(effect_id)
    if intent is None:
        raise ValueError("Publication intent required")
    reservation = store.get_reservation(intent["reservation_id"])
    commit = store.registry.get_commit(intent["reservation_id"])
    request = reservation["publication_request"]
    if (
        commit is None
        or commit["reservation"] != reservation
        or commit["publication_intent_id"] != effect_id
        or request is None
        or request["effect_id"] != effect_id
    ):
        raise ValueError("Publication reservation conflict")
    expected_intent = dict(
        **request,
        payload=intent["payload"],
        payload_sha256=digest(intent["payload"]),
        schema_version=1,
        registry_id=store.registry.registry_id,
        reservation_id=reservation["reservation_id"],
        state="pending",
    )
    if canonical_json(intent) != canonical_json(expected_intent):
        raise ValueError("Publication intent binding conflict")
    target = intent["target_profile"]
    if (
        type(target) is not dict
        or set(target) != {"profile_id", "revision", "scope_ownership"}
        or target["scope_ownership"] != "cooperative_immutable"
        or target != authorization.profile_metadata(target["profile_id"])
    ):
        raise ValueError("Publication frozen profile ownership required")
    files = store.read_version(intent["reservation_id"])
    source_artifacts = (
        ("candidate.json",)
        if source_kind(reservation["source"]) == "accepted_candidate"
        else ("editor-snapshot.json", "editor-receipt.json", "export.yaml")
    )
    for name in ("environment.yaml", "source.json", "projection.json", *source_artifacts):
        if name not in files or commit["manifest"]["files"].get(name) != dict(
            size=len(files[name]), sha256=hashlib.sha256(files[name]).hexdigest()
        ):
            raise ValueError("Publication artifact manifest conflict")
    if canonical_json(json.loads(files["source.json"])) != canonical_json(reservation):
        raise ValueError("Publication frozen source binding conflict")
    spec = verify_frozen_spec(reservation["source"], files)
    projection = json.loads(files["projection.json"])
    validate_projection(projection, spec=spec)
    rebuilt = project_scene(
        spec,
        revision_id=reservation["revision_id"],
        store_id=reservation["store_id"],
        family=reservation["family"],
        version=f"v{reservation['version']}",
    )
    descriptor = dict(
        artifact="projection.json",
        artifact_sha256=hashlib.sha256(files["projection.json"]).hexdigest(),
        projection_digest=rebuilt["digest"],
        scope_id=rebuilt["scope_id"],
    )
    if canonical_json(projection) != canonical_json(rebuilt) or canonical_json(intent["payload"]) != canonical_json(
        descriptor
    ):
        raise ValueError("Publication projection or artifact descriptor conflict")
    return intent, spec, projection


def checked_frozen_config(config, target):
    """Bind explicit connection settings to the frozen ownership profile."""
    config = checked_graph_config(config)
    revision = digest({**{key: config[key] for key in ("uri", "user", "database")}, "immutable_scope": True})
    if (
        type(target) is not dict
        or set(target) != {"profile_id", "revision", "scope_ownership"}
        or target["scope_ownership"] != "cooperative_immutable"
        or revision != target["revision"]
    ):
        raise ValueError("Authorized connection frozen profile conflict")
    checked_identifier(target["profile_id"])
    return config


def receipt_envelope(intent, receipt):
    """Bind a transport receipt to its immutable publication intent."""
    return dict(
        schema_version=1,
        status="verified",
        effect_id=intent["effect_id"],
        target_profile=copy.deepcopy(intent["target_profile"]),
        payload_sha256=intent["payload_sha256"],
        transport=receipt,
    )


def expected_receipt(intent, projection, config):
    """Build expected bindings independently of any transport response."""
    config = checked_frozen_config(config, intent["target_profile"])
    return receipt_envelope(
        intent,
        dict(
            status="verified",
            effect_id=intent["effect_id"],
            database=config["database"],
            scope_id=projection["scope_id"],
            projection_digest=projection["digest"],
            canonical_identity=copy.deepcopy(projection["canonical_identity"]),
            verification_boundary=dict(
                method="operator_attested_immutable_scope_v1",
                operator_attested=True,
                declaration=research_graph_transport.IMMUTABLE_SCOPE_DECLARATION,
                database_snapshot=False,
            ),
        ),
    )


def transport_once(
    intent, spec, projection, config, capability, *, driver_factory=None, transport=research_graph_transport
):
    """Execute one physical operation and close the driver before returning."""
    if capability not in {"graph_write", "graph_read"}:
        raise ValueError("Invalid publication capability")
    config = checked_frozen_config(config, intent["target_profile"])
    if driver_factory is None:
        from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver

        driver_factory = get_neo4j_driver
    driver = driver_factory(
        uri=config["uri"],
        user=config["user"],
        password=config["password"],
        connection_timeout=3,
        connection_acquisition_timeout=5,
        max_connection_pool_size=1,
        max_transaction_retry_time=0,
    )
    try:
        send = transport.publish_once if capability == "graph_write" else transport.reconcile_once
        receipt = send(
            driver,
            config["database"],
            copy.deepcopy(projection),
            spec=spec.model_copy(deep=True),
            effect_id=intent["effect_id"],
            immutable_scope_attested=True,
        )
        if capability == "graph_read" and (receipt is None or receipt.get("status") == "unknown"):
            return None
        return receipt_envelope(intent, receipt)
    finally:
        driver.close()


def build_private_envelope(intent, spec, projection, config, capability):
    """Return private JSON-line bytes and an independent expected receipt; grant nothing."""
    config = checked_frozen_config(config, intent["target_profile"])
    if capability not in {"graph_write", "graph_read"}:
        raise ValueError("Invalid publication capability")
    expected = expected_receipt(intent, projection, config)
    from .provider_security import reject_secret

    reject_secret(expected, config["password"])
    envelope = dict(
        schema_version=1,
        scope="publication",
        effect_id=intent["effect_id"],
        capability=capability,
        intent=copy.deepcopy(intent),
        source=spec.model_dump(mode="json"),
        projection=copy.deepcopy(projection),
        config=config,
        immutable_scope_attested=True,
    )
    raw = (canonical_json(envelope) + "\n").encode()
    from .publication_worker import MAX_ENVELOPE_BYTES

    validate_private_envelope(parse_frame(raw, MAX_ENVELOPE_BYTES))
    return raw, expected


def parse_frame(raw, limit):
    """Decode exactly one bounded JSON line, rejecting duplicates and deep structures."""
    from .publication_worker import MAX_DEPTH

    if type(raw) is not bytes or len(raw) > limit or not raw.endswith(b"\n") or b"\n" in raw[:-1]:
        raise ValueError("Invalid publication frame")
    text = raw[:-1].decode("utf-8", errors="strict")
    depth = 0
    quoted = escaped = False
    for char in text:
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
            if depth > MAX_DEPTH:
                raise ValueError("Invalid publication depth")
        elif char in "]}":
            depth -= 1

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate publication key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Invalid publication number")

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    if type(value) is not dict:
        raise ValueError("Invalid publication object")
    canonical_json(value)
    return value


def validate_private_envelope(envelope):
    """Validate literal authority declaration and canonical frozen source/profile bindings."""
    if (
        set(envelope)
        != {
            "schema_version",
            "scope",
            "effect_id",
            "capability",
            "intent",
            "source",
            "projection",
            "config",
            "immutable_scope_attested",
        }
        or type(envelope["schema_version"]) is not int
        or envelope["schema_version"] != 1
        or envelope["scope"] != "publication"
        or envelope["capability"] not in {"graph_write", "graph_read"}
        or envelope["immutable_scope_attested"] is not True
    ):
        raise ValueError("Invalid private publication envelope")
    checked_identifier(envelope["effect_id"])
    intent, projection = envelope["intent"], envelope["projection"]
    config = checked_frozen_config(envelope["config"], intent["target_profile"])
    if intent["effect_id"] != envelope["effect_id"] or digest(intent["payload"]) != intent["payload_sha256"]:
        raise ValueError("Invalid publication intent")
    spec = ArenaEnvGraphSpec.from_dict(envelope["source"])
    if canonical_json(spec.model_dump(mode="json")) != canonical_json(envelope["source"]):
        raise ValueError("Invalid canonical publication source")
    validate_projection(projection, spec=spec)
    scope = {key: projection["scope"][key] for key in ("revision_id", "store_id", "family", "version")}
    rebuilt = project_scene(spec, **scope)
    descriptor = dict(
        artifact="projection.json",
        artifact_sha256=hashlib.sha256(canonical_json(projection).encode()).hexdigest(),
        projection_digest=rebuilt["digest"],
        scope_id=rebuilt["scope_id"],
    )
    if canonical_json(projection) != canonical_json(rebuilt) or canonical_json(intent["payload"]) != canonical_json(
        descriptor
    ):
        raise ValueError("Invalid canonical publication projection")
    return intent, spec, projection, config, envelope["capability"]


def execute_private_envelope(raw, *, driver_factory=None):
    """Validate and perform one operation; no ledger, grant, or session access."""
    from .provider_security import reject_secret
    from .publication_worker import ERROR, MAX_ENVELOPE_BYTES

    values = validate_private_envelope(parse_frame(raw, MAX_ENVELOPE_BYTES))
    intent, spec, projection, config, capability = values
    expected = expected_receipt(intent, projection, config)
    receipt = transport_once(*values, driver_factory=driver_factory)
    if receipt is None:
        return dict(ERROR)
    if canonical_json(receipt) != canonical_json(expected):
        raise ValueError("Invalid publication receipt")
    reject_secret(receipt, config["password"])
    return dict(schema_version=1, receipt=receipt)


def screen_worker_result(raw, expected, passwords):
    """Return only the independent expected receipt or None; reject malformed/secret data."""
    from .provider_security import reject_secret
    from .publication_worker import ERROR, MAX_RESULT_BYTES

    result = parse_frame(raw, MAX_RESULT_BYTES)
    for password in passwords:
        reject_secret(result, password)
    if canonical_json(result) == canonical_json(ERROR):
        return None
    if canonical_json(result) != canonical_json(dict(schema_version=1, receipt=expected)):
        raise ValueError("Invalid publication result")
    return copy.deepcopy(expected)
