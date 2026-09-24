# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Read-only retained bytes use real immutable artifacts and current authorization."""

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


class RetainedArtifactReads(unittest.TestCase):
    def test_assessment_projection_uses_retained_causal_links_and_run_scope(self):
        import asyncio

        from isaaclab_arena.agentic_environment_generation.workflow.api.client import DOCUMENTS
        from isaaclab_arena.agentic_environment_generation.workflow.api.schema import schema
        from isaaclab_arena.agentic_environment_generation.workflow.evidence import SceneEvidenceAssessment

        view = SimpleNamespace(
            run_id="run",
            assessment_id="assessment",
            candidate_id="candidate",
            evidence_id="evidence",
            assessment=SceneEvidenceAssessment(status="inconclusive", missing_ids=("missing",)),
        )
        calls = []

        async def read(method, identifier):
            calls.append((method, identifier))
            return view

        for run_id, expected in (("run", "AssessmentDetail"), ("foreign", "QueryFailure")):
            response = asyncio.run(
                schema.execute(
                    DOCUMENTS["assessment"],
                    context_value=SimpleNamespace(call=read),
                    variable_values={"id": run_id, "reference": "assessment"},
                )
            )
            self.assertIsNone(response.errors)
            value = response.data["workflowAssessment"]
            self.assertEqual(value["__typename"], expected)
            if run_id == "run":
                self.assertEqual((value["candidateId"], value["evidenceId"]), ("candidate", "evidence"))
                self.assertEqual(value["missingIds"], ["missing"])
            else:
                self.assertEqual(value["code"], "FORBIDDEN")
        self.assertEqual(calls, [("read_scene_assessment", "assessment")] * 2)

    def test_evidence_details_and_inventory_bind_retained_manifest(self):
        import asyncio

        from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
        from isaaclab_arena.agentic_environment_generation.workflow.api.client import DOCUMENTS
        from isaaclab_arena.agentic_environment_generation.workflow.api.schema import schema
        from isaaclab_arena.agentic_environment_generation.workflow.artifacts import RetainedArtifacts
        from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
        from isaaclab_arena.agentic_environment_generation.workflow.evidence import (
            CandidateBinding,
            CriterionEvidence,
            EvidenceCohort,
        )
        from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import (
            SceneEvidenceArtifacts,
        )
        from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import Observation, profile_digest
        from isaaclab_arena.tests.test_environment_workflow_service import contract

        request = contract()

        def sha(text):
            return hashlib.sha256(text.encode()).hexdigest()

        binding = CandidateBinding(
            candidate_digest=sha("test-generated candidate"),
            contract_digest=contract_digest(request),
            profile_digest=profile_digest(request),
        )
        cohort = EvidenceCohort(
            realization_id="test-realization",
            reset_id="test-reset",
            environment_id="test-env",
            window_id="test-window",
            frame_id="test-frame",
            contract_digest=binding.contract_digest,
            profile_digest=binding.profile_digest,
        )
        with tempfile.TemporaryDirectory() as temporary:
            with ArtifactArea.create(Path(temporary) / "area", store_id="test", registry_id="scope") as area:
                receipt = SceneEvidenceArtifacts(area).write(
                    binding, cohort, {"kind": "observation", "test_generated": True}, protect=lambda _: None
                )
                entry = CriterionEvidence(
                    criterion_id="test-metric",
                    criterion_digest=sha("test-metric definition"),
                    producer_id="test-producer",
                    observed_coordinate_frames=("test-frame",),
                    observed_step_window=(0, 1),
                    subject_ids=("test-subject",),
                    modality="measured",
                    evaluator_version="test-v1",
                    rubric_id="test-rubric",
                    candidate_digest=binding.candidate_digest,
                    cohort=cohort,
                    manifest_digest=receipt.manifest_digest,
                    verdict="inconclusive",
                )
                view = SimpleNamespace(
                    run_id="run",
                    evidence_id=sha("test-evidence"),
                    candidate_id=sha("test-candidate-id"),
                    observation=Observation(
                        cohort=cohort, evidence=(entry,), verified_manifest_digests=(receipt.manifest_digest,)
                    ),
                )
                service = SimpleNamespace(
                    read_run_intent=lambda *a, **k: SimpleNamespace(contract=request),
                    read_scene_evidence=lambda *a, **k: view,
                )
                reference = view.evidence_id + receipt.manifest_digest
                reader = RetainedArtifacts(service, area, lambda _: None)
                bundle = reader.read("reader", "run", "evidence", reference)
                self.assertEqual(
                    bundle.files, area.verify(receipt.relative_directory, json.loads(receipt.manifest_json))
                )

                async def read(method, *args):
                    return view if method == "read_scene_evidence" else bundle

                for operation in ("evidence", "artifact-inventory"):
                    result = asyncio.run(
                        schema.execute(
                            DOCUMENTS[operation],
                            context_value=SimpleNamespace(call=read),
                            variable_values={
                                "id": "run",
                                "reference": view.evidence_id if operation == "evidence" else reference,
                                "kind": "EVIDENCE",
                            },
                        )
                    )
                    self.assertIsNone(result.errors)
                    value = result.data["workflowEvidence" if operation == "evidence" else "workflowArtifacts"]
                    if operation == "evidence":
                        self.assertEqual(value["entries"][0]["manifestDigest"], receipt.manifest_digest)
                        self.assertEqual(value["artifactSelectors"][0]["referenceId"], reference)
                    else:
                        self.assertEqual(value["manifestDigest"], receipt.manifest_digest)
                        self.assertEqual(value["artifacts"][0]["name"], "EVIDENCE_JSON")
                with self.assertRaises(ValueError):
                    reader.read("reader", "other", "evidence", reference)
                with self.assertRaises(ValueError):
                    reader.read("reader", "run", "evidence", view.evidence_id + sha("wrong-manifest"))

    def test_generation_details_bind_exact_receipt_and_verified_bytes(self):
        import asyncio

        from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
        from isaaclab_arena.agentic_environment_generation.workflow.api.client import DOCUMENTS
        from isaaclab_arena.agentic_environment_generation.workflow.api.schema import schema
        from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
            GenerationArtifacts,
            RetainedArtifacts,
        )
        from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration
        from isaaclab_arena.tests.test_environment_workflow_decisions import generation_contract

        contract = generation_contract()
        fence = AttemptFence(
            run_id="run",
            intent_id="unit-intent",
            attempt_id="unit-attempt",
            generation=1,
            owner_id="unit-owner",
            owner_epoch=1,
        )
        registration = WorkerRegistration(
            registration_id="unit-registration",
            fence=fence,
            host="synthetic",
            boot="synthetic",
            pid=1,
            pgid=1,
            sid=1,
            start_ticks=1,
        )
        with tempfile.TemporaryDirectory() as temporary:
            with ArtifactArea.create(Path(temporary) / "area", store_id="test", registry_id="scope") as area:
                receipt = GenerationArtifacts(area).write(
                    fence,
                    registration,
                    contract,
                    b"scene: test-generated\n",
                    {"scene": "test-generated"},
                    protect=lambda _: None,
                )
                attempt = SimpleNamespace(fence=fence, receipt=receipt, registration=registration, released=True)
                service = SimpleNamespace(
                    read_run_intent=lambda *a, **k: SimpleNamespace(contract=contract),
                    read_generation_recovery=lambda *a, **k: (None, attempt, None),
                )
                reader = RetainedArtifacts(service, area, lambda _: None)
                bundle = reader.read("reader", "run", "generation", fence.attempt_id)
                self.assertEqual(set(bundle.files), {"candidate.json", "candidate.yaml", "provenance.json"})
                self.assertEqual(bundle.record, receipt)

                async def read(*args):
                    return bundle

                result = asyncio.run(
                    schema.execute(
                        DOCUMENTS["generation"],
                        context_value=SimpleNamespace(call=read),
                        variable_values={"id": "run", "reference": fence.attempt_id},
                    )
                )
                self.assertIsNone(result.errors)
                value = result.data["workflowGeneration"]
                self.assertEqual(value["registrationId"], registration.registration_id)
                self.assertEqual(value["ownerEpoch"], "1")
                self.assertEqual(value["manifestDigest"], receipt.manifest_sha256)
                with self.assertRaises(ValueError):
                    reader.read("reader", "run", "generation", "wrong-attempt")
                with self.assertRaises(ValueError):
                    reader.read("reader", "other", "generation", fence.attempt_id)

    def test_candidate_bytes_are_selected_by_retained_run_and_identity(self):
        import asyncio

        from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
        from isaaclab_arena.agentic_environment_generation.workflow.api.client import DOCUMENTS
        from isaaclab_arena.agentic_environment_generation.workflow.api.schema import schema
        from isaaclab_arena.agentic_environment_generation.workflow.artifacts import RetainedArtifacts
        from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import candidate_record
        from isaaclab_arena.tests.test_environment_workflow_service import contract

        candidate = candidate_record("run", {"test_generated": True}, source_id="test-original")
        service = SimpleNamespace(
            read_run_intent=lambda *a, **k: SimpleNamespace(contract=contract()),
            read_scene_candidate=lambda *a, **k: SimpleNamespace(run_id="run", candidate=candidate),
        )
        with tempfile.TemporaryDirectory() as temporary:
            with ArtifactArea.create(Path(temporary) / "area", store_id="test", registry_id="scope") as area:
                reader = RetainedArtifacts(service, area, lambda _: None)
                bundle = reader.read("reader", "run", "candidate", candidate.candidate_id)
                self.assertEqual(bundle.files, {"candidate.json": candidate.scene_json.encode()})
                self.assertEqual(hashlib.sha256(bundle.files["candidate.json"]).hexdigest(), candidate.digest)

                async def read(*args):
                    return bundle

                result = asyncio.run(
                    schema.execute(
                        DOCUMENTS["candidate"],
                        context_value=SimpleNamespace(call=read),
                        variable_values={"id": "run", "reference": candidate.candidate_id},
                    )
                )
                self.assertIsNone(result.errors)
                value = result.data["workflowCandidate"]
                self.assertEqual(value["candidateId"], candidate.candidate_id)
                self.assertEqual(value["originalId"], candidate.original_id)
                self.assertEqual(value["artifacts"][0]["sha256"], candidate.digest)
                with self.assertRaises(ValueError):
                    reader.read("reader", "other", "candidate", candidate.candidate_id)
                with self.assertRaises(ValueError):
                    reader.read("reader", "run", "candidate", "another-record")

    def test_prior_and_bounded_artifact_documents_are_query_only(self):
        from isaaclab_arena.agentic_environment_generation.workflow.api.client import DOCUMENTS
        from isaaclab_arena.agentic_environment_generation.workflow.api.schema import schema
        from isaaclab_arena.agentic_environment_generation.workflow.api.security import validate_document

        for operation in ("prior", "artifact"):
            with self.subTest(operation=operation):
                body = {
                    "query": DOCUMENTS[operation],
                    "variables": {
                        "id": "run",
                        "kind": "PRIOR",
                        "reference": "run",
                        "name": "PRIOR_JSON",
                        "sha": hashlib.sha256(b"test-only bytes").hexdigest(),
                        "offset": "0",
                        "limit": 65536,
                    },
                }
                validate_document(body, schema)

    def test_prior_bytes_are_exact_bounded_and_reverified_without_retrieval(self):
        from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
        from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
        from isaaclab_arena.agentic_environment_generation.workflow.artifacts import RetainedArtifacts, artifact_chunk
        from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
        from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts
        from isaaclab_arena.tests.test_environment_workflow_service import contract

        request = contract()
        reads = []

        def intent(principal, run_id, *, protect):
            if principal != "reader":
                raise PermissionError("Current scoped read required")
            reads.append(run_id)
            return SimpleNamespace(contract=request) if run_id == "run" else None

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            with ArtifactArea.create(root, store_id="test", registry_id="scope") as area:
                prior = RetainedPriorArtifacts(area).write(
                    request.source.prompt,
                    contract_digest(request),
                    "run",
                    empty_snapshot(request.source.prompt),
                    protect=lambda _: None,
                )
                reader = RetainedArtifacts(SimpleNamespace(read_run_intent=intent), area, lambda _: None)
                bundle = reader.read("reader", "run", "prior", "run")
                raw = (root / prior.relative_directory / "prior.json").read_bytes()
                self.assertEqual(bundle.files, {"prior.json": raw})
                self.assertEqual(bundle.record["status"], "unavailable")
                digest = hashlib.sha256(raw).hexdigest()
                import asyncio

                from isaaclab_arena.agentic_environment_generation.workflow.api.client import DOCUMENTS
                from isaaclab_arena.agentic_environment_generation.workflow.api.schema import schema

                async def read(method, *args):
                    if method == "read_retained_bundle":
                        return bundle
                    run_id, kind, reference_id, name, expected_sha, offset, limit = args
                    self.assertEqual((run_id, kind, reference_id), ("run", "prior", "run"))
                    return artifact_chunk(bundle, name, expected_sha, offset, limit)

                for operation in ("prior", "artifact"):
                    response = asyncio.run(
                        schema.execute(
                            DOCUMENTS[operation],
                            context_value=SimpleNamespace(call=read),
                            variable_values={
                                "id": "run",
                                "kind": "PRIOR",
                                "reference": "run",
                                "name": "PRIOR_JSON",
                                "sha": digest,
                                "offset": "0",
                                "limit": 65536,
                            },
                        )
                    )
                    self.assertIsNone(response.errors)
                    value = response.data["workflowPrior" if operation == "prior" else "workflowArtifact"]
                    size = value["artifacts"][0]["totalBytes"] if operation == "prior" else value["totalBytes"]
                    self.assertEqual(size, str(len(raw)))
                chunks = [artifact_chunk(bundle, "prior.json", digest, offset, 11) for offset in range(0, len(raw), 11)]
                self.assertEqual(b"".join(base64.b64decode(c["data"]) for c in chunks), raw)
                self.assertTrue(chunks[-1]["eof"])
                self.assertTrue(all(c["sha256"] == digest and c["total_bytes"] == len(raw) for c in chunks))
                self.assertEqual(reads, ["run"])
                with self.assertRaises(PermissionError):
                    reader.read("intruder", "run", "prior", "run")
                with self.assertRaises(ValueError):
                    reader.read("reader", "other", "prior", "run")
                for name, sha, offset, limit in (
                    ("../../private", digest, 0, 11),
                    ("prior.json", hashlib.sha256(b"not this artifact").hexdigest(), 0, 11),
                    ("prior.json", digest, -1, 11),
                    ("prior.json", digest, 0, 65537),
                    ("prior.json", digest, 0, True),
                ):
                    with self.subTest(name=name, offset=offset, limit=limit):
                        with self.assertRaises(ValueError):
                            artifact_chunk(bundle, name, sha, offset, limit)
                path = root / prior.relative_directory / "prior.json"
                path.write_bytes(raw.replace(b"unconfigured", b"changed-data"))
                with self.assertRaises(ValueError):
                    reader.read("reader", "run", "prior", "run")
                self.assertEqual(json.loads(raw)["run_id"], "run")


if __name__ == "__main__":
    unittest.main()
