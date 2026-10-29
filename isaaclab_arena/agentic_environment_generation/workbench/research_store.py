# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit persistence for trusted-operator Linux-local research stores.

This is not a distributed filesystem protocol or an authorization boundary against
other processes running as the operator. The caller owns the Journal lifecycle.
Publication execution is deliberately not implemented; the registry's atomic
publication-intent API is an extension point, not evidence of publication.
"""

import hashlib
import json
import os
from collections.abc import Callable
from contextlib import suppress

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

from .documents import Documents
from .research_artifacts import ArtifactArea, SafeBusy  # noqa: F401
from .research_projection import project_scene, validate_projection
from .research_registry import ResearchRegistry, bounded_json, canonical_json, checked_identifier, digest
from .research_source import editor_source_artifacts, source_kind, verify_editor_source, verify_source_artifacts


def _verify_public_unchanged(value, before):
    """Reject changed or no-longer-canonical data without reflecting callback values."""
    with suppress(TypeError, ValueError, RecursionError):
        if canonical_json(value) == before:
            return
    raise ValueError("Public protection must not mutate immutable research data") from None


class ResearchStore:
    """Coordinate immutable artifacts with a caller-owned, initialized Journal."""

    registry: ResearchRegistry
    area: ArtifactArea
    store_id: str
    protect_public: Callable

    def __init__(self, *args, **kwargs):
        raise ValueError("Use ResearchStore.create or ResearchStore.open")

    @classmethod
    def create(cls, journal, root, store_id, *, protect_public):
        """Explicitly initialize research registry tables and a fresh private area."""
        return cls._load(journal, root, store_id, protect_public, create=True)

    @classmethod
    def open(cls, journal, root, store_id, *, protect_public):
        """Open an existing registered store without initializing or creating anything."""
        return cls._load(journal, root, store_id, protect_public, create=False)

    @classmethod
    def _load(cls, journal, root, store_id, protect_public, *, create):
        checked_identifier(store_id)
        if not callable(protect_public):
            raise ValueError("Public protection callback required")
        raw = os.fspath(root)
        if not isinstance(raw, str):
            raise ValueError("Invalid research root")
        if {"generated_envs", "eval_output"}.intersection(os.path.abspath(raw).split("/")):
            raise ValueError("Managed root cannot be inside legacy output directories")
        registry = ResearchRegistry(journal, initialize=create)
        if create:
            registry.register_store(store_id)
        elif store_id not in registry.store_ids():
            raise ValueError("Unknown research store")
        loader = ArtifactArea.create if create else ArtifactArea.open
        area = loader(root, store_id=store_id, registry_id=registry.registry_id)
        store = object.__new__(cls)
        store.registry, store.area = registry, area
        store.store_id, store.protect_public = store_id, protect_public
        return store

    def persist_candidate(
        self,
        family,
        workflow_id,
        job_id,
        attempt_id,
        generation,
        approval,
        parent_revision_id=None,
        publication_request=None,
    ):
        """Freeze an accepted receipt under explicit persistence approval, never regenerate."""
        with self.area.writer_lock():
            return self._persist_candidate(
                family,
                workflow_id,
                job_id,
                attempt_id,
                generation,
                approval,
                parent_revision_id,
                publication_request,
            )

    def persist_editor_revision(self, family, workflow_id, *, source, bundle_loader,
                                approval, parent_revision_id, publication_request=None):
        """Persist a verified editor source with explicit lineage and separate approval.

        bundle_loader(revision_id) is a trusted adapter to Documents.load_revision_bundle;
        fresh/incomplete retries require it. Exact committed replay ignores the loader
        (None is permitted) and verifies the copied artifacts. The caller authenticates
        approval; family and parent_revision_id are explicit, never inferred. Returns
        the unchanged four-field commit contract. Publication requests are unsupported.
        """
        if publication_request is not None:
            raise ValueError("Editor revision publication is unsupported")
        binding = bounded_json({"family": family, "workflow_id": workflow_id, "source": source,
                                "approval": approval, "parent_revision_id": parent_revision_id})
        detached = json.loads(canonical_json(binding))
        self.protect_public(detached)
        _verify_public_unchanged(detached, canonical_json(binding))
        source, approval = binding["source"], binding["approval"]
        if source_kind(source) != "editor_revision":
            raise ValueError("Editor revision source required")
        with self.area.writer_lock():
            previous = self.registry.get_reservation_for_workflow(self.store_id, workflow_id)
            if previous is not None:
                if any(previous[key] != value for key, value in binding.items()):
                    raise ValueError("Research workflow or approval binding conflict")
                committed = self.registry.get_commit(previous["reservation_id"])
                if committed is not None:
                    self.read_version(previous["reservation_id"])
                    return committed
            if not callable(bundle_loader):
                raise ValueError("Verified editor bundle loader required")
            bundle = verify_editor_source(source, bundle_loader(source["editor_revision_id"]),
                                          protect_snapshot=self.protect_public)
            reservation = self.registry.reserve_editor_revision(
                self.store_id, family, workflow_id, source=source, bundle=bundle,
                approval=approval, parent_revision_id=parent_revision_id)
            files = editor_source_artifacts(source, bundle)
            files["source.json"] = canonical_json(reservation).encode()
            return self._persist_artifacts(reservation, files, source_bundle=bundle)

    def _persist_candidate(
        self,
        family,
        workflow_id,
        job_id,
        attempt_id,
        generation,
        approval,
        parent_revision_id,
        publication_request,
    ):
        journal = self.registry.journal
        request = journal.get_job(job_id)["inputs"]
        receipt = journal.get_candidate_receipt(job_id, attempt_id, generation)
        protected_binding = canonical_json([request, receipt, approval, publication_request])
        self.protect_public(request)
        self.protect_public(receipt)
        self.protect_public({
            "family": family,
            "workflow_id": workflow_id,
            "approval": approval,
            "parent_revision_id": parent_revision_id,
            "publication_request": publication_request,
        })
        _verify_public_unchanged([request, receipt, approval, publication_request], protected_binding)
        if (
            type(receipt) is not dict
            or type(receipt.get("yaml_text")) is not str
            or type(receipt.get("validation")) is not dict
            or receipt["validation"].get("source_hash") != hashlib.sha256(receipt["yaml_text"].encode()).hexdigest()
        ):
            raise ValueError("Candidate receipt source hash binding required")
        reservation = self.registry.reserve_candidate(
            self.store_id,
            family,
            workflow_id,
            job_id=job_id,
            attempt_id=attempt_id,
            generation=generation,
            approval=approval,
            parent_revision_id=parent_revision_id,
            publication_request=publication_request,
        )
        files = {
            "environment.yaml": receipt["yaml_text"].encode(),
            "candidate.json": canonical_json(receipt).encode(),
            "source.json": canonical_json(reservation).encode(),
        }
        intent = None
        if publication_request is not None:
            validation = Documents(".").validate(receipt["yaml_text"])
            if not validation["valid"]:
                raise ValueError("Publication requires a valid frozen source")
            projection = project_scene(
                ArenaEnvGraphSpec.from_dict(validation["spec"]),
                revision_id=reservation["revision_id"],
                store_id=self.store_id,
                family=family,
                version=f"v{reservation['version']}",
            )
            protected_projection = canonical_json(projection)
            self.protect_public(projection)
            _verify_public_unchanged(projection, protected_projection)
            _verify_public_unchanged([request, receipt, approval, publication_request], protected_binding)
            files["projection.json"] = canonical_json(projection).encode()
            payload = {
                "artifact": "projection.json",
                "artifact_sha256": hashlib.sha256(files["projection.json"]).hexdigest(),
                "projection_digest": projection["digest"],
                "scope_id": projection["scope_id"],
            }
            intent = {**publication_request, "payload": payload, "payload_sha256": digest(payload)}
            protected_intent = canonical_json(intent)
            self.protect_public(intent)
            _verify_public_unchanged(intent, protected_intent)
            _verify_public_unchanged(projection, protected_projection)
            _verify_public_unchanged([request, receipt, approval, publication_request], protected_binding)
            validate_projection(projection, spec=ArenaEnvGraphSpec.from_dict(validation["spec"]))
            expected_scope = {
                "revision_id": reservation["revision_id"],
                "store_id": self.store_id,
                "family": family,
                "version": f"v{reservation['version']}",
            }
            if any(projection["scope"].get(key) != value for key, value in expected_scope.items()):
                raise ValueError("Projection reservation scope conflict")
            if canonical_json(intent["payload"]) != canonical_json({
                "artifact": "projection.json",
                "artifact_sha256": hashlib.sha256(files["projection.json"]).hexdigest(),
                "projection_digest": projection["digest"],
                "scope_id": projection["scope_id"],
            }):
                raise ValueError("Publication artifact descriptor conflict")
            self.registry._checked_intent(reservation, intent)
        return self._persist_artifacts(reservation, files, intent=intent)

    def _persist_artifacts(self, reservation, files, *, intent=None, source_bundle=None):
        resid, family = reservation["reservation_id"], reservation["family"]
        manifest = self.area.expected_manifest(resid, files, reservation)
        previous = self.registry.get_commit(resid)
        if previous is not None:
            if previous["manifest"] != manifest:
                raise ValueError("Research commit binding conflict")
            self.read_version(resid)
            return previous
        version = f"v{reservation['version']}"
        if self.area.has_final(family, version):
            self.area.verify(f"final/{family}/{version}", manifest)
        else:
            self.area.stage(resid, files, reservation)
        relative = self.area.promote(resid, family, version, manifest)
        self.area.verify(relative, manifest)
        extra = {} if source_bundle is None else {"source_bundle": source_bundle}
        return self.registry.record_commit(resid, manifest, relative, publication_intent=intent, **extra)

    def read_version(self, reservation_id):
        """Read all exact artifact bytes by committed reservation ID, verifying every file."""
        commit = self.registry.get_commit(reservation_id)
        if commit is None or commit["reservation"]["store_id"] != self.store_id:
            raise ValueError("Unknown committed research version")
        files = self.area.verify(commit["relative_directory"], commit["manifest"])
        if source_kind(commit["reservation"]["source"]) == "editor_revision":
            bundle = verify_source_artifacts(commit["reservation"]["source"], files,
                                             protect_snapshot=self.protect_public)
            self.registry._checked_manifest(commit["reservation"], commit["manifest"],
                                            commit["relative_directory"], source_bundle=bundle)
        return files

    def candidate_reference(self, job_id):
        """Read the exact eligible candidate reference without granting persistence."""
        checked_identifier(job_id)
        journal = self.registry.journal
        with journal._lock:
            self.registry._identity(journal.db)
            attempt = journal.get_attempt(job_id)
            if attempt is None:
                raise ValueError("No managed candidate attempt")
            reference = self.registry._candidate_source(job_id, attempt["attempt_id"], attempt["generation"])
        protected_reference = canonical_json(reference)
        self.protect_public(reference)
        _verify_public_unchanged(reference, protected_reference)
        return reference

    def get_reservation(self, reservation_id):
        """Read a reservation belonging to this store without touching filesystem bytes."""
        reservation = self.registry.get_reservation(reservation_id)
        if reservation["store_id"] != self.store_id:
            raise ValueError("Unknown research reservation")
        return reservation

    def list_versions(self, family, *, limit=50, after_version=0):
        """Return at most 100 registry reservation/state/commit records in version order."""
        return self.registry.list_versions(self.store_id, family, limit=limit, after_version=after_version)

    def latest_version(self, family):
        """Return the highest committed version number or None, never a file alias."""
        return self.registry.latest_version(self.store_id, family)

    def lineage(self, family, *, limit=50, after_version=0):
        """Return a bounded page of committed revision/parent edges, not a recursive walk."""
        return [
            {
                key: row["reservation"][key]
                for key in (
                    "revision_id",
                    "parent_revision_id",
                    "reservation_id",
                    "version",
                )
            }
            for row in self.list_versions(family, limit=limit, after_version=after_version)
            if row["state"] == "committed"
        ]

    def close(self):
        """Close only owned artifact descriptors, never the caller's Journal."""
        self.area.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
