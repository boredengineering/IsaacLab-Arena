# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Owned real generate/SDK tracer; synthetic HTTP/store, never physical acceptance."""

import json

from isaaclab_arena_examples.tests.test_workbench_generation_worker_process import (
    _foreground_composition,
    _sdk_evidence,
    _validate_document,
)


def _initial(tmp_path, *, unavailable=False, frozen_key=None):
    import generation_worker_fixture as fixture
    import pytest

    from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts
    from isaaclab_arena.tests.test_environment_workflow_scene_engines import configuration
    from isaaclab_arena_examples.agentic_environment_generation.foreground_initial_generation import (
        InitialGenerationReceiver,
        InitialGenerationWorker,
    )

    original_packet = fixture.production_packet

    def attested_packet(**kwargs):
        packet = original_packet(**kwargs)
        packet["config"] = configuration()
        if frozen_key is not None:
            packet["config"]["api_key"] = frozen_key
        packet["config"]["workflow_accounting"]["max_tokens"] = 500
        packet["config"]["workflow_accounting"]["max_cost_usd"] = "0"
        return packet

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(fixture, "production_packet", attested_packet)
        c = _foreground_composition(tmp_path, dispatch=False)
    snapshot = empty_snapshot(
        c.request.source.prompt,
        status="unavailable" if unavailable else "empty",
        warning="unconfigured" if unavailable else None,
    )
    if not unavailable:
        import hashlib

        from isaaclab_arena.agentic_environment_generation.prior_receipt import PRIOR_FIELDS, format_prior_context

        prior_value = dict.fromkeys(PRIOR_FIELDS)
        prior_value.update(
            name="synthetic-retained-table-prior", objects=["banana"], relations=[], evidence="unevaluated"
        )
        snapshot.update(status="structural", priors=[prior_value])
        snapshot["exact_context"] = format_prior_context(snapshot["priors"])
        snapshot["context_sha256"] = hashlib.sha256(snapshot["exact_context"].encode()).hexdigest()
        snapshot["timing"] = {"source": "local_monotonic", "elapsed_seconds": 0.0}
    prior = RetainedPriorArtifacts(c.artifacts.area).write(
        c.request.source.prompt, contract_digest(c.request), "run", snapshot, protect=c.authority.protect_public
    )
    worker = InitialGenerationWorker(
        area=c.artifacts.area,
        root=c.private / "artifacts",
        prior=prior,
        protect=c.authority.protect_public,
        spawn_spec=lambda: fixture.spawn_spec("scene-sdk"),
    )
    # Reuse the existing real coordinator/authority/lease over its explicit fake store.
    c.coordinator._worker = worker
    c.lease._cleanup_verified = worker.cleanup_verified
    c.worker = worker
    receiver = InitialGenerationReceiver(
        worker,
        c.coordinator,
        c.lease,
        c.artifacts,
        validate_document=_validate_document,
        protect=c.authority.protect_public,
    )
    failures = []
    original_allowance = worker._allowance

    def allowance(packet, owned):
        c.enriched_packet = json.loads(json.dumps(packet))
        return original_allowance(packet, owned)

    worker._allowance = allowance
    c.sent_packets = []
    for method in ("prepare", "send"):
        original = getattr(worker, method)

        def observed(*args, _original=original, _method=method, **kwargs):
            try:
                if _method == "send":
                    c.sent_packets.append(json.loads(args[1]))
                result = _original(*args, **kwargs)
                if _method == "prepare":
                    from isaaclab_arena_examples.tests.test_workbench_generation_worker_process import _wait_evidence

                    _wait_evidence(result, "sdk")
                    assert _sdk_evidence(result)["calls"] == 0
                return result
            except Exception as exc:
                failures.append((type(exc).__name__, str(exc)))
                raise

        setattr(worker, method, observed)
    try:
        c.handle = c.coordinator.dispatch(
            "creator", expected_version=1, decision_id="decision", reservation=c.reservation
        )
    except Exception:
        prepared = c.coordinator._handle.prepared
        diagnostic = prepared.owned_handle.process.stderr.read().decode() if prepared is not None else ""
        raise AssertionError((failures, diagnostic)) from None
    return c, receiver, snapshot


def test_initial_actual_generate_adopts_existing_generation_receipt(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workflow.generation_output import validate_generation_output
    from isaaclab_arena.agentic_environment_generation.workflow.results import GenerationReceipt
    from isaaclab_arena.agentic_environment_generation.workflow.validation import validate_generation_candidate

    c, receiver, snapshot = _initial(tmp_path)
    try:
        import pytest

        from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import canonical

        c.handle.prepared.owned_handle.process.wait(timeout=25)
        before_translation = _sdk_evidence(c.handle.prepared)
        assert before_translation["calls"] == 2
        legacy = c.sent_packets[0]
        projected = dict(c.enriched_packet, inputs={k: c.enriched_packet["inputs"][k] for k in legacy["inputs"]})
        assert canonical(projected) == canonical(legacy)
        assert legacy["workflow_execution"]["admitted_at"] == c.attempt.admitted_at
        assert legacy["workflow_execution"]["released_at"] == c.attempt.released_at
        with pytest.raises(RuntimeError, match="already attempted"):
            c.worker.send(c.handle.prepared, json.dumps(legacy).encode() + b"\n", timeout_s=1)
        result = receiver.receive("creator", c.handle.prepared, release_lease=False)
        assert _sdk_evidence(c.handle.prepared) == before_translation
        assert result.disposition == "validation" and c.run.state != "accepted"
        assert type(receiver.receipt) is GenerationReceipt
        assert c.attempt.receipt == receiver.receipt
        files = c.artifacts.verified_bytes(receiver.receipt, protect=c.authority.protect_public)
        metadata = json.loads(files["provenance.json"])["producer_metadata"]
        assert metadata["prior_snapshot"] == snapshot
        assert metadata["validation"]["proposal_only"] is True
        assert metadata["validation"]["model_warnings"]
        validate_generation_output(
            c.handle.prepared.owned_handle.inputs, metadata, validate_document=_validate_document
        )
        recovered = c.artifacts.load_receipt(
            c.fence, c.handle.prepared.registration, c.request, protect=c.authority.protect_public
        )
        assert recovered == receiver.receipt
        from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import (
            ForegroundGenerationReceiver,
        )

        original_receiver = ForegroundGenerationReceiver(
            c.worker,
            c.coordinator,
            c.lease,
            c.artifacts,
            validate_document=_validate_document,
            protect=c.authority.protect_public,
        )
        original_receiver.receipt = recovered
        assert original_receiver.receive("creator", c.handle.prepared, release_lease=False).disposition == "validation"
        assert receiver.receipt.candidate_yaml_sha256 != receiver.receipt.candidate_json_sha256
        assert metadata["prior_snapshot"]["exact_context"]
        checked = validate_generation_candidate(c.artifacts, recovered, protect=c.authority.protect_public)
        assert checked.disposition == "schema_validated"
        assert checked.physical_validity == checked.task_validity == "not_established"
        sdk = _sdk_evidence(c.handle.prepared)
        assert sdk["calls"] == 2
        assert [x["kind"] for x in sdk["responses"]] == ["ping", "completion"]
        assert "real scene model methods" in sdk["scope"]
        assert c.worker.cleanup_verified(c.handle.prepared.registration, c.handle.cleanup)
        assert c.attempt.reservation == c.reservation
        assert c.handle.prepared.owned_handle.inputs["scene_action"] == "generate"
        assert receiver.receive("creator", c.handle.prepared, release_lease=False).disposition == "validation"
        assert _sdk_evidence(c.handle.prepared) == sdk
        c.lease.retire_and_release(c.store, c.handle.prepared.registration, c.handle.cleanup)
    finally:
        c.worker.stop_owned(c.handle.prepared, timeout_s=3)


def test_required_prior_unavailable_has_zero_sdk_including_ping(tmp_path):
    import pytest

    c, receiver, snapshot = _initial(tmp_path, unavailable=True)
    try:
        with pytest.raises(RuntimeError, match="reconciliation"):
            receiver.receive("creator", c.handle.prepared)
        assert snapshot["status"] == "unavailable"
        assert _sdk_evidence(c.handle.prepared)["calls"] == 0
        assert receiver.receipt is None and c.attempt.receipt is None
        assert not list((c.private / "artifacts/final/generation").glob("*"))
        assert c.worker.cleanup_verified(c.handle.prepared.registration, c.handle.cleanup)
        assert (
            c.coordinator.dispatch("creator", expected_version=1, decision_id="decision", reservation=c.reservation)
            is c.handle
        )
        assert _sdk_evidence(c.handle.prepared)["calls"] == 0
    finally:
        c.worker.stop_owned(c.handle.prepared, timeout_s=3)


def test_frozen_key_veto_precedes_model_and_generation_persistence(tmp_path):
    import pytest

    c, receiver, _ = _initial(tmp_path, frozen_key="rubiks_cube_hot3d_robolab")
    try:
        with pytest.raises(RuntimeError, match="reconciliation"):
            receiver.receive("creator", c.handle.prepared)
        assert _sdk_evidence(c.handle.prepared)["calls"] == 2
        assert not list((c.private / "artifacts/final/scene-model-output").glob("*/value.json"))
        assert not list((c.private / "artifacts/final/generation").glob("*"))
        assert receiver.receipt is None and c.attempt.receipt is None
        assert c.worker.cleanup_verified(c.handle.prepared.registration, c.handle.cleanup)
    finally:
        c.worker.stop_owned(c.handle.prepared, timeout_s=3)


def test_current_protection_veto_precedes_generation_write(tmp_path):
    import pytest

    c, receiver, _ = _initial(tmp_path)
    screened = []

    def protect(value):
        screened.append(value)
        if isinstance(value, dict) and "output" in value:
            raise ValueError("synthetic current policy veto")
        c.authority.protect_public(value)

    receiver._protect = protect
    try:
        with pytest.raises(RuntimeError, match="reconciliation"):
            receiver.receive("creator", c.handle.prepared)
        assert screened
        assert _sdk_evidence(c.handle.prepared)["calls"] == 2
        assert list((c.private / "artifacts/final/scene-model-output").glob("*/value.json"))
        assert not list((c.private / "artifacts/final/generation").glob("*"))
        assert receiver.receipt is None and c.attempt.receipt is None
        assert c.worker.cleanup_verified(c.handle.prepared.registration, c.handle.cleanup)
    finally:
        c.worker.stop_owned(c.handle.prepared, timeout_s=3)
