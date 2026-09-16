# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Exact source dispatch; legacy candidate objects are never tagged or rehashed.

Manual bundle codec: arena-editor-bundle/v1 (Documents.verify_revision_bundle).
Snapshot/receipt artifacts use editor encode (UTF-8, sorted compact finite JSON,
ensure_ascii=False). receipt_sha256 uses legacy research canonical JSON (ASCII
escapes); source_hash hashes raw root UTF-8; canonical_hash remains Documents'
scene codec. Neither scene hash substitutes for the exact bundle digest.
"""
import json
import re

from .documents import Documents
from .editor_revision_storage import encode

CANDIDATE_FIELDS = {"job_id", "attempt_id", "generation", "receipt_sha256", "request_sha256"}
EDITOR_FIELDS = {"kind", "schema_version", "editor_revision_id", "source_hash", "canonical_hash",
                 "bundle_codec", "bundle_sha256", "receipt_sha256"}



def source_kind(source):
    """Validate exact source shape and return semantic kind without changing JSON."""
    from .research_registry import checked_identifier
    if type(source) is not dict:
        raise ValueError("Invalid research source")
    if set(source) == CANDIDATE_FIELDS:
        checked_identifier(source["job_id"])
        checked_identifier(source["attempt_id"])
        if type(source["generation"]) is not int or source["generation"] < 1:
            raise ValueError("Invalid candidate generation")
        hashes = ("receipt_sha256", "request_sha256")
        kind = "accepted_candidate"
    elif (set(source) == EDITOR_FIELDS and source["kind"] == "editor_revision"
          and type(source["schema_version"]) is int and source["schema_version"] == 1
          and source["bundle_codec"] == "arena-editor-bundle/v1"
          and type(source["editor_revision_id"]) is str
          and re.fullmatch(r"[a-f0-9]{32}", source["editor_revision_id"])):
        hashes = ("source_hash", "canonical_hash", "bundle_sha256", "receipt_sha256")
        kind = "editor_revision"
    else:
        raise ValueError("Invalid research source")
    if any(type(source[key]) is not str or not re.fullmatch(r"[a-f0-9]{64}", source[key]) for key in hashes):
        raise ValueError("Invalid research source digest")
    return kind


def editor_revision_source(bundle):
    """Return an exact manual source reference only from a verified portable bundle."""
    from .research_registry import digest
    try:
        revision_id = bundle["receipt"]["revision"]["revision_id"]
    except (KeyError, TypeError):
        raise ValueError("Invalid editor revision bundle") from None
    bundle = Documents.verify_revision_bundle(revision_id, bundle)
    return {"kind": "editor_revision", "schema_version": 1, "editor_revision_id": revision_id,
            "source_hash": bundle["snapshot"]["source_hash"], "canonical_hash": bundle["snapshot"]["canonical_hash"],
            "bundle_codec": bundle["codec"], "bundle_sha256": bundle["bundle_sha256"],
            "receipt_sha256": digest(bundle["receipt"])}


def verify_editor_source(source, bundle, *, protect_snapshot=None):
    """Check every source field against independently validated, detached bundle bytes."""
    if source_kind(source) != "editor_revision":
        raise ValueError("Editor revision source required")
    bundle = Documents.verify_revision_bundle(source["editor_revision_id"], bundle,
                                               protect_snapshot=protect_snapshot)
    if editor_revision_source(bundle) != source:
        raise ValueError("Research source binding conflict")
    return bundle


def editor_source_artifacts(source, bundle):
    """Encode the four portable manual artifacts; the store adds source.json binding."""
    bundle = verify_editor_source(source, bundle)
    return {"environment.yaml": bundle["snapshot"]["yaml_text"].encode("utf-8"),
            "editor-snapshot.json": encode(bundle["snapshot"]),
            "editor-receipt.json": encode(bundle["receipt"]),
            "export.yaml": bundle["export_yaml"].encode("utf-8")}


def verify_source_artifacts(source, files, *, protect_snapshot=None):
    """Verify source artifacts without original editor storage or a candidate job.

    Legacy candidate verification binds its exact receipt and raw root; the
    registry separately authenticates the journal's accepted candidate identity.
    """
    from .research_registry import canonical_json, digest
    try:
        if source_kind(source) == "accepted_candidate":
            receipt = json.loads(files["candidate.json"])
            if (digest(receipt) != source["receipt_sha256"]
                    or files["candidate.json"] != canonical_json(receipt).encode()
                    or files["environment.yaml"] != receipt["yaml_text"].encode()):
                raise ValueError
            return receipt
        bundle = {"schema_version": 1, "codec": source["bundle_codec"],
                  "bundle_sha256": source["bundle_sha256"],
                  "snapshot": json.loads(files["editor-snapshot.json"]),
                  "receipt": json.loads(files["editor-receipt.json"]),
                  "export_yaml": files["export.yaml"].decode("utf-8")}
        bundle = verify_editor_source(source, bundle)
        if any(files[name] != content for name, content in editor_source_artifacts(source, bundle).items()):
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise ValueError("Invalid research source artifacts") from None
    # Reject-only callback exceptions belong to the adapter, not codec errors.
    return verify_editor_source(source, bundle, protect_snapshot=protect_snapshot)


def verify_frozen_spec(source, files, *, protect_snapshot=None):
    """Return a normalized spec from verified copied source artifacts, without authority.

    A manual export is only a derivation of its verified raw root/frozen includes;
    it never replaces source, receipt, bundle, or manifest identities. Callers
    remain responsible for reservation/manifest/projection/intent bindings.
    """
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    verified = verify_source_artifacts(source, files, protect_snapshot=protect_snapshot)
    kind = source_kind(source)
    if kind == "accepted_candidate":
        import hashlib

        if verified.get("validation", {}).get("source_hash") != hashlib.sha256(files["environment.yaml"]).hexdigest():
            raise ValueError("Frozen research source hash conflict")
    text = verified["export_yaml"] if kind == "editor_revision" else verified["yaml_text"]
    validation = Documents(".").validate(text)
    if not validation["valid"]:
        raise ValueError("Invalid frozen research source")
    return ArenaEnvGraphSpec.from_dict(validation["spec"])
