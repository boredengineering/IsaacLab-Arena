# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Pure bounded Graph-RAG projection and canonical receipt validation; no transports."""
import hashlib
import json
import math
import re

TEXT_FIELDS = frozenset({
    "name",
    "task_description",
    "task_composition",
    "embodiment",
    "background",
    "evaluation_id",
    "graph_version",
    "policy_identity",
    "checkpoint_identity",
})
PRIOR_FIELDS = TEXT_FIELDS | {"objects", "relations", "success_rate", "episodes", "evidence"}


class SnapshotRejected(ValueError):
    """Carry a fixed public-safe rejection code."""


def bounded_text(value, *, nullable=True):
    if value is None and nullable:
        return
    if type(value) is not str or (not nullable and not value.strip()):
        raise SnapshotRejected("invalid_record")
    if len(value) > 4096:
        raise SnapshotRejected("bounds_exceeded")
    if any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value) or re.search(
        r"(?i)(://|password|passwd|secret|api[_-]?key|access[_-]?token|bearer\s|-----BEGIN)", value
    ):
        raise SnapshotRejected("unsafe_record")


def validate_prior(prior, evidence, min_success_rate=0.0, min_episodes=1):
    """Validate every projected field, keeping unknown provenance explicitly null."""
    if type(prior) is not dict or set(prior) != PRIOR_FIELDS:
        raise SnapshotRejected("invalid_record")
    for field in TEXT_FIELDS:
        bounded_text(
            prior[field],
            nullable=field not in {"name", "evaluation_id"} or (field == "evaluation_id" and evidence == "unevaluated"),
        )
    for field in ("evaluation_id", "graph_version", "policy_identity", "checkpoint_identity"):
        if prior[field] is not None and not prior[field].strip():
            raise SnapshotRejected("invalid_record")
    for field in ("objects", "relations"):
        values = prior[field]
        if type(values) is not list:
            raise SnapshotRejected("invalid_record")
        if len(values) > 32:
            raise SnapshotRejected("bounds_exceeded")
        for value in values:
            if field == "objects":
                bounded_text(value, nullable=False)
            else:
                if type(value) is not dict or set(value) != {"relation_type", "manifold", "anchor"}:
                    raise SnapshotRejected("invalid_record")
                for key in value:
                    bounded_text(value[key], nullable=key != "relation_type")
    if prior["evidence"] != evidence or evidence not in ("measured", "unevaluated"):
        raise SnapshotRejected("invalid_record")
    rate, episodes = prior["success_rate"], prior["episodes"]
    if evidence == "measured":
        if (
            type(rate) not in (int, float)
            or not min_success_rate < rate <= 1
            or not math.isfinite(rate)
            or type(episodes) is not int
            or not min_episodes <= episodes <= 1000000
        ):
            raise SnapshotRejected("invalid_record")
    elif any(
        prior[k] is not None
        for k in ("success_rate", "episodes", "evaluation_id", "policy_identity", "checkpoint_identity")
    ):
        raise SnapshotRejected("invalid_record")
    return prior


def keyword_filters(prompt):
    p = prompt.lower()
    embodiment = next((v for v in ("g1", "droid", "franka") if v in p), "")
    fixture = (
        "wireshelving"
        if "shelv" in p or "rack" in p
        else "kitchen" if "kitchen" in p or "counter" in p else "table" if "table" in p or "desk" in p else ""
    )
    return embodiment, fixture


def format_prior_context(priors, *, structural_outcome="no qualifying measured evidence"):
    """Render the existing context format from the validated projection only."""
    if not priors:
        return ""
    if any(p.get("evidence") == "measured" for p in priors):
        header = [
            "### Prior Environment Subgraphs (Graph-RAG, ranked by measured success rate):",
            "These structural patterns come from environments that were evaluated and scored above zero.",
        ]
    else:
        header = [
            "### Prior Environment Subgraphs (Graph-RAG, structural precedent only):",
            "No evaluated environment cleared the evidence bar. The patterns below are structurally",
            "valid but carry NO evidence that a policy performs well in them -- reuse their grounding",
            "and relations, not their assumed quality.",
        ]
    lines = [*header, ""]
    for idx, p in enumerate(priors, 1):
        outcome = (
            f"success_rate={p.get('success_rate')} over {p.get('episodes')} episode(s)"
            if p.get("evidence") == "measured"
            else structural_outcome
        )
        lines.append(f"Example {idx} ({p.get('name', 'env')}) -- {outcome}:")
        lines.append(f"  - Task: {p.get('task_description')}")
        if p.get("task_composition"):
            lines.append(f"  - Composition: {p.get('task_composition')}")
        lines.append(f"  - Embodiment: {p.get('embodiment')}")
        lines.append(f"  - Background: {p.get('background')}")
        lines.append(f"  - Objects: {', '.join(p.get('objects', []))}")
        for rel in p.get("relations", []):
            lines.append(
                f"  - Relation: {rel.get('relation_type')} (manifold={rel.get('manifold')}, anchor={rel.get('anchor')})"
            )
        lines.append("")
    return "\n".join(lines)


def effective_settings(limit=2, min_success_rate=0.0, min_episodes=1):
    """Unknown caller-owned driver configuration is explicitly null."""
    return {
        "limit": limit,
        "min_success_rate": min_success_rate,
        "min_episodes": min_episodes,
        "query_timeout_seconds": 5.0,
        "connection_timeout_seconds": None,
        "connection_acquisition_timeout_seconds": None,
        "max_transaction_retry_time_seconds": None,
    }


def empty_snapshot(prompt, *, status="unavailable", warning="unconfigured"):
    emb, fixture = keyword_filters(prompt)
    return {
        "status": status,
        "derived_filters": {"emb_filter": emb, "fixture_filter": fixture},
        "priors": [],
        "exact_context": "",
        "context_sha256": hashlib.sha256(b"").hexdigest(),
        "warnings": [warning] if warning else [],
        "effective_settings": effective_settings(),
        "timing": {"source": "not_started", "elapsed_seconds": None},
    }


def _number(value, low, high, *, integer=False):
    return type(value) in ((int,) if integer else (int, float)) and low <= value <= high and math.isfinite(value)


def validate_prior_snapshot(snapshot, *, prompt):
    """Reject malformed evidence and context not canonically derived from that evidence."""
    fields = {
        "status",
        "derived_filters",
        "priors",
        "exact_context",
        "context_sha256",
        "warnings",
        "effective_settings",
        "timing",
    }
    if type(snapshot) is not dict or set(snapshot) != fields:
        raise SnapshotRejected("invalid_record")
    status = snapshot["status"]
    if type(status) is not str or status not in ("measured", "structural", "empty", "unavailable", "not_requested"):
        raise SnapshotRejected("invalid_record")
    emb, fixture = keyword_filters(prompt)
    if snapshot["derived_filters"] != {"emb_filter": emb, "fixture_filter": fixture}:
        raise SnapshotRejected("invalid_record")
    settings = snapshot["effective_settings"]
    if type(settings) is not dict or set(settings) != set(effective_settings()):
        raise SnapshotRejected("invalid_record")
    for key, low, high, integer in (
        ("limit", 1, 5, True),
        ("min_success_rate", 0, 1, False),
        ("min_episodes", 1, 1000000, True),
        ("query_timeout_seconds", 0.001, 180, False),
    ):
        if not _number(settings[key], low, high, integer=integer):
            raise SnapshotRejected("invalid_record")
    for key in (
        "connection_timeout_seconds",
        "connection_acquisition_timeout_seconds",
        "max_transaction_retry_time_seconds",
    ):
        if settings[key] is not None and not _number(settings[key], 0, 180):
            raise SnapshotRejected("invalid_record")
    timing = snapshot["timing"]
    if type(timing) is not dict or set(timing) != {"source", "elapsed_seconds"}:
        raise SnapshotRejected("invalid_record")
    if timing["source"] == "local_monotonic":
        if not _number(timing["elapsed_seconds"], 0, 180):
            raise SnapshotRejected("invalid_record")
    elif timing["source"] == "unavailable":
        if status != "unavailable" or timing["elapsed_seconds"] is not None:
            raise SnapshotRejected("invalid_record")
    elif timing["source"] != "not_started" or timing["elapsed_seconds"] is not None:
        raise SnapshotRejected("invalid_record")
    if status in ("measured", "structural", "empty") and timing["source"] != "local_monotonic":
        raise SnapshotRejected("invalid_record")
    if status == "not_requested" and timing["source"] != "not_started":
        raise SnapshotRejected("invalid_record")
    priors = snapshot["priors"]
    if type(priors) is not list or len(priors) > settings["limit"]:
        raise SnapshotRejected("bounds_exceeded")
    if bool(priors) != (status in ("measured", "structural")):
        raise SnapshotRejected("invalid_record")
    for prior in priors:
        validate_prior(
            prior,
            "measured" if status == "measured" else "unevaluated",
            settings["min_success_rate"],
            settings["min_episodes"],
        )
    warnings = snapshot["warnings"]
    codes = (
        "unconfigured",
        "invalid_request",
        "bounds_exceeded",
        "invalid_record",
        "unsafe_record",
        "retrieval_failed",
    )
    if (
        type(warnings) is not list
        or len(warnings) > 1
        or any(type(w) is not str or w not in codes for w in warnings)
        or bool(warnings) != (status == "unavailable")
    ):
        raise SnapshotRejected("invalid_record")
    context = snapshot["exact_context"]
    if type(context) is not str or context != format_prior_context(priors):
        raise SnapshotRejected("invalid_record")
    if len(context.encode()) > 32768 or len(json.dumps(priors, allow_nan=False)) > 65536:
        raise SnapshotRejected("bounds_exceeded")
    if snapshot["context_sha256"] != hashlib.sha256(context.encode()).hexdigest():
        raise SnapshotRejected("invalid_record")
    return snapshot
