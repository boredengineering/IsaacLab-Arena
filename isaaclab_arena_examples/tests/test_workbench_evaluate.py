# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Prototype evaluation API and simulated OS/harness units, never GPU evidence."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, editor_execution

ORIGIN = "http://127.0.0.1:3000"
FIXTURE = Path(__file__).resolve().parents[2] / "isaaclab_arena/tests/test_data/minimal_maple_table_env_graph.yaml"
FIXED = {"headless": True, "enable_cameras": True, "num_envs": 1, "num_steps": 1000}


def native_transport_fixture(tmp_path):
    """Pure released metadata; never native permission or process evidence."""
    import time
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import Criterion, WorkflowContract
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureSettings
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        SceneIntent,
        SceneReservation,
        candidate_record,
    )
    from isaaclab_arena.tests.test_environment_workflow_contracts import request

    criterion = Criterion.model_validate(
        dict(
            criterion_id="speed",
            kind="runtime",
            evidence_producer="scene.linear-speed",
            requirement="required",
            evaluator_version="1",
            required_modalities=["state"],
            coordinate_frames=["world"],
            observation_window=dict(start_step=2, end_step=3),
            rubric="maximum linear speed",
            subjects=["table"],
            limit=dict(operator="le", value=0.01, unit="m_per_s"),
        )
    )
    settings = NativeCaptureSettings(
        runtime_profile_id="runtime",
        capture_profile_id="capture",
        seed=42,
        timestep_seconds=0.01,
        decimation=2,
        settle_steps=2,
        settle_consecutive_steps=1,
        settle_angular_rad_per_s=0.01,
        window=criterion.observation_window,
        subjects=(dict(subject_id="table", scene_name="table", prim_path="/World/table"),),
        criteria=(criterion,),
        max_runtime_seconds=5.0,
    )
    raw = request()
    raw["criteria"] = [criterion.model_dump(mode="json")]
    raw["execution"].update(
        runtime=settings.runtime_reference().model_dump(mode="json"),
        capture=settings.capture_reference().model_dump(mode="json"),
    )
    raw["effects"]["allow_runtime"] = True
    raw["budget"].update(max_realizations=1, max_observations=1, max_steps=3)
    contract = WorkflowContract.model_validate(raw)
    candidate = candidate_record("native-run", {"objects": []}, source_id="fixture")
    fence = AttemptFence(
        run_id=candidate.run_id, intent_id="a" * 64, attempt_id="attempt", generation=1, owner_id="owner", owner_epoch=1
    )
    registration = WorkerRegistration(
        registration_id="native-worker",
        fence=fence,
        host="host",
        boot="boot",
        pid=101,
        pgid=101,
        sid=101,
        start_ticks=1,
    )
    intent = SceneIntent(
        codec_version=2,
        intent_id=fence.intent_id,
        candidate_id=candidate.candidate_id,
        action="capture",
        status="released",
        released_at=time.time(),
        worker_fence=fence,
        worker_registration=registration,
        reservation=SceneReservation(
            model_calls=0,
            model_tokens=0,
            cost_ceiling_usd=0.0,
            realizations=1,
            observations=1,
            steps=3,
            runtime_allowance_seconds=5.0,
        ),
    )
    root = tmp_path / "artifacts"
    area = ArtifactArea.create(root, store_id="store", registry_id="registry")
    return SimpleNamespace(
        settings=settings,
        contract=contract,
        candidate=candidate,
        intent=intent,
        registration=registration,
        root=root,
        area=area,
        protect=lambda value: None,
    )


def test_native_transport_request_retains_exact_released_bindings(tmp_path):
    import copy
    import time

    try:
        from isaaclab_arena.agentic_environment_generation.workflow import native_worker_protocol as protocol
    except ImportError:
        pytest.fail("native/numeric immutable worker protocol is missing")
    f = native_transport_fixture(tmp_path)
    try:
        deadline = time.time() + 4
        packet = protocol.retain_request(
            f.area,
            root=f.root,
            action="capture",
            intent=f.intent,
            candidate=f.candidate,
            original=f.candidate,
            contract=f.contract,
            settings=f.settings,
            deadline=deadline,
            protect=f.protect,
        )
        assert packet["codec"] == "native-scene-packet-v1"
        request = protocol.read_request(f.area, packet, protect=f.protect)
        assert request.intent == f.intent
        assert request.settings == f.settings
        assert request.deadline == deadline
        for field in ("deadline", "candidate_digest", "settings_sha256", "registration", "contract_digest"):
            changed = copy.deepcopy(packet)
            changed["payload"]["request"]["binding"][field] = "forged"
            with pytest.raises(ValueError):
                protocol.read_request(f.area, changed, protect=f.protect)
        changed = copy.deepcopy(packet)
        changed["config"] = {"api_key": "not-allowed"}
        with pytest.raises(ValueError):
            protocol.read_request(f.area, changed, protect=f.protect)
        with pytest.raises(ValueError):
            protocol.retain_request(
                f.area,
                root=f.root,
                action="capture",
                intent=f.intent.model_copy(update={"status": "reserved"}),
                candidate=f.candidate,
                original=f.candidate,
                contract=f.contract,
                settings=f.settings,
                deadline=deadline,
                protect=f.protect,
            )
    finally:
        f.area.close()


def native_transport_evidence(f):
    """Synthetic samples exercising real immutable storage and numeric replay."""
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
    from isaaclab_arena.agentic_environment_generation.workflow.evidence import CandidateBinding, EvidenceCohort
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureProducer
    from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import SceneEvidenceArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import identity, profile_digest

    tag = identity(f.intent.intent_id, f.candidate.candidate_id)
    cohort = EvidenceCohort(
        realization_id=tag,
        reset_id=identity(tag, "reset"),
        environment_id="native-env0",
        window_id=identity(tag, "window", f.settings.window.model_dump(), f.settings.digest()),
        frame_id="world",
        contract_digest=contract_digest(f.contract),
        profile_digest=profile_digest(f.contract),
    )
    binding = CandidateBinding(
        candidate_digest=f.candidate.digest,
        contract_digest=cohort.contract_digest,
        profile_digest=cohort.profile_digest,
    )
    artifacts = SceneEvidenceArtifacts(f.area)
    receipt = artifacts.write(
        binding,
        cohort,
        dict(
            kind="observation",
            provenance="native-unverified",
            settings=f.settings.model_dump(mode="json"),
            settings_sha256=f.settings.digest(),
            diagnostics={"status": "complete"},
            frames=[],
            samples=[
                dict(step=step, frame="world", subjects={"table": {"linear_velocity_w": [0.0, 0.0, 0.0]}})
                for step in (2, 3)
            ],
        ),
        protect=f.protect,
    )
    producer = NativeCaptureProducer(settings=f.settings, artifacts=artifacts, protect=f.protect, output_root=f.root)
    return receipt, producer.replay(receipt, contract=f.contract, candidate=f.candidate)


def test_numeric_worker_replays_exact_retained_capture_and_result(tmp_path, monkeypatch):
    import time

    from isaaclab_arena.agentic_environment_generation.workflow import native_worker_protocol as protocol
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import identity

    try:
        from isaaclab_arena_examples.agentic_environment_generation.web_api import native_scene_worker as child
    except ImportError:
        pytest.fail("fixed native/numeric worker entrypoint is missing")
    f = native_transport_fixture(tmp_path)
    try:
        receipt, observation = native_transport_evidence(f)
        assess_id = "b" * 64
        fence = f.registration.fence.model_copy(update={"intent_id": assess_id})
        reg = f.registration.model_copy(update={"fence": fence})
        intent = f.intent.model_copy(
            update=dict(
                action="assess",
                intent_id=assess_id,
                worker_fence=fence,
                worker_registration=reg,
                observation_id="c" * 64,
                observation_digest=identity(observation.model_dump(mode="json")),
                reservation=f.intent.reservation.model_copy(update=dict(realizations=0, observations=0, steps=0)),
            )
        )
        packet = protocol.retain_request(
            f.area,
            root=f.root,
            action="assess",
            intent=intent,
            candidate=f.candidate,
            original=f.candidate,
            contract=f.contract,
            settings=f.settings,
            deadline=time.time() + 4,
            protect=f.protect,
            retained_observation=observation,
        )
        assert packet["codec"] == "numeric-scene-packet-v1"
        monkeypatch.setattr(child, "_verify_identity", lambda request: None)
        monkeypatch.setattr(child, "_initialize_kit", lambda settings: pytest.fail("numeric child imported Kit"))
        result = child.execute(packet, protect=f.protect, action="assess")
        request = protocol.read_request(f.area, packet, protect=f.protect)
        assert protocol.read_result(f.area, packet, request, result, protect=f.protect) == observation
        assert observation.evidence[0].verdict == "established"
        forged = dict(result, manifest_digest="0" * 64)
        with pytest.raises(ValueError):
            protocol.read_result(f.area, packet, request, forged, protect=f.protect)
        # The retained verdict cannot substitute for re-reading actual source bytes.
        path = f.root / receipt.relative_directory / "evidence.json"
        path.write_bytes(path.read_bytes().replace(b'"complete"', b'"tampered"'))
        with pytest.raises(ValueError):
            protocol.read_result(f.area, packet, request, result, protect=f.protect)
    finally:
        f.area.close()


@pytest.mark.parametrize("terminating_close", [False, True])
def test_native_child_validates_release_then_retains_before_kit_close(tmp_path, monkeypatch, terminating_close):
    import copy
    import time
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow import native_worker_protocol as protocol
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import (
        NativeCaptureProducer,
        NativeCaptureResult,
    )

    try:
        from isaaclab_arena_examples.agentic_environment_generation.web_api import native_scene_worker as child
    except ImportError:
        pytest.fail("fixed native/numeric worker entrypoint is missing")
    f = native_transport_fixture(tmp_path)
    events = []
    try:
        receipt, observation = native_transport_evidence(f)
        packet = protocol.retain_request(
            f.area,
            root=f.root,
            action="capture",
            intent=f.intent,
            candidate=f.candidate,
            original=f.candidate,
            contract=f.contract,
            settings=f.settings,
            deadline=time.time() + 4,
            protect=f.protect,
        )

        def close():
            # Final output exists before Kit teardown (not just a transient pipe reply).
            assert f.area.has_final("native-scene-output", protocol.result_version(packet))
            assert events[-1] == "published"
            events.append("close")
            if terminating_close:
                raise SystemExit(0)

        monkeypatch.setattr(child, "_verify_identity", lambda request: events.append("identity"))
        monkeypatch.setattr(
            child, "_initialize_kit", lambda settings: (events.append("kit") or SimpleNamespace(close=close))
        )
        monkeypatch.setattr(child, "_validate_spec", lambda candidate: candidate)

        def capture(self, **kwargs):
            assert kwargs["worker_initialized"] is True
            assert kwargs["candidate"] == f.candidate
            kwargs["check_active"]()
            kwargs["charge_step"](1)
            events.append("capture")
            return NativeCaptureResult(receipt, observation)

        monkeypatch.setattr(NativeCaptureProducer, "__call__", capture)
        forged = copy.deepcopy(packet)
        forged["payload"]["request"]["binding"]["deadline"] = 0
        with pytest.raises(ValueError):
            child.execute(forged, protect=f.protect, action="capture")
        assert not events
        published = []

        def publish(reference):
            published.append(reference)
            events.append("published")

        if terminating_close:
            with pytest.raises(SystemExit):
                child.execute(packet, protect=f.protect, action="capture", on_retained=publish)
            result = published[0]
        else:
            result = child.execute(packet, protect=f.protect, action="capture", on_retained=publish)
        assert events == ["identity", "kit", "capture", "published", "close"]
        request = protocol.read_request(f.area, packet, protect=f.protect)
        assert protocol.read_result(f.area, packet, request, result, protect=f.protect) == receipt
    finally:
        f.area.close()


@pytest.mark.parametrize("exit_code", [0, 7, -9])
def test_native_parent_requires_genuine_exit_before_receipt_adoption(tmp_path, monkeypatch, exit_code):
    import time
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow import native_worker_protocol as protocol
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import PreparedWorker
    from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import (
        ForegroundGenerationReceiver,
    )

    try:
        from isaaclab_arena_examples.agentic_environment_generation.foreground_native_scene import (
            ForegroundNativeCaptureWorker,
            SceneChildFailed,
        )
    except ImportError:
        pytest.fail("owned native transport is missing")
    f = native_transport_fixture(tmp_path)
    try:
        receipt, _ = native_transport_evidence(f)
        packet = protocol.retain_request(
            f.area,
            root=f.root,
            action="capture",
            intent=f.intent,
            candidate=f.candidate,
            original=f.candidate,
            contract=f.contract,
            settings=f.settings,
            deadline=time.time() + 4,
            protect=f.protect,
        )
        request = protocol.read_request(f.area, packet, protect=f.protect)
        result = protocol.retain_result(f.area, packet, protocol.capture_reference(receipt), protect=f.protect)
        worker = ForegroundNativeCaptureWorker(
            settings=f.settings, artifacts=SimpleNamespace(area=f.area), artifact_root=f.root
        )
        events = []

        def wait(timeout):
            events.append("natural-exit")
            process.returncode = exit_code
            return exit_code

        process = SimpleNamespace(wait=wait, returncode=None)
        owned = SimpleNamespace(
            process=process,
            registration=f.registration,
            deadline=time.monotonic() + 4,
            packet=packet,
            request=request,
            cleanup=None,
        )
        worker._owned.append(owned)
        prepared = PreparedWorker(f.registration, owned)
        monkeypatch.setattr(ForegroundGenerationReceiver, "_read", lambda *args: result)

        def stop(prepared, *, timeout_s):
            if owned.cleanup is None:
                events.append("cleanup")
                owned.cleanup = object()
            return owned.cleanup

        monkeypatch.setattr(worker, "stop_owned", stop)
        monkeypatch.setattr(worker, "cleanup_verified", lambda reg, cleanup: cleanup is owned.cleanup)
        if exit_code:
            with pytest.raises(SceneChildFailed) as failed:
                worker.receive_capture(prepared, protect=f.protect)
            assert failed.value.returncode == exit_code
        else:
            assert worker.receive_capture(prepared, protect=f.protect) == receipt
        assert events == ["natural-exit", "cleanup"]
    finally:
        f.area.close()


def test_native_transport_one_shot_send_is_latched_before_invalid_release(tmp_path):
    import threading
    import time
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import PreparedWorker

    try:
        from isaaclab_arena_examples.agentic_environment_generation.foreground_native_scene import (
            ForegroundNativeCaptureWorker,
        )
    except ImportError:
        pytest.fail("owned native transport is missing")
    f = native_transport_fixture(tmp_path)
    try:
        worker = ForegroundNativeCaptureWorker(
            settings=f.settings, artifacts=SimpleNamespace(area=f.area), artifact_root=f.root
        )
        owned = SimpleNamespace(
            registration=f.registration,
            contract=f.contract,
            lock=threading.RLock(),
            attempted=False,
            cleanup=None,
            deadline=time.monotonic() + 4,
        )
        worker._owned.append(owned)
        prepared = PreparedWorker(f.registration, owned)
        with pytest.raises(ValueError):
            worker.send_capture(
                prepared,
                f.intent.model_copy(update={"status": "reserved"}),
                f.candidate,
                f.candidate,
                f.contract,
                protect=f.protect,
                deadline=time.time() + 4,
            )
        with pytest.raises(RuntimeError, match="already attempted"):
            worker.send_capture(
                prepared, f.intent, f.candidate, f.candidate, f.contract, protect=f.protect, deadline=time.time() + 4
            )
    finally:
        f.area.close()


def test_native_packet_decoder_rejects_ambiguous_json():
    from isaaclab_arena.agentic_environment_generation.workflow import native_worker_protocol as protocol

    assert callable(getattr(protocol, "decode_packet", None)), "strict native packet decoder required"
    for raw in (
        b'{"codec":"numeric-scene-packet-v1","codec":"native-scene-packet-v1","payload":{}}\n',
        b'{"codec":"native-scene-packet-v1","payload":{"root":NaN}}\n',
        b"{}",
        b"{}\n{}\n",
        b"x" * (512 * 1024 + 1),
    ):
        with pytest.raises(ValueError):
            protocol.decode_packet(raw)


def test_native_alarm_does_not_extend_absolute_deadline(monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import native_scene_worker as child

    armed = []
    monkeypatch.setattr(child.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(child.signal, "signal", lambda *args: None)
    monkeypatch.setattr(child.signal, "setitimer", lambda *args: armed.append(args))
    child._arm_deadline(103.0)
    assert armed == [(child.signal.ITIMER_REAL, 3.0)]
    with pytest.raises(TimeoutError):
        child._arm_deadline(99.0)


@pytest.mark.parametrize("failure", ["capture", "shutdown", "exit-zero", "exit-seven"])
def test_native_child_failure_remains_nonzero_after_retention(tmp_path, monkeypatch, failure):
    import io
    import json
    import time
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow import native_worker_protocol as protocol
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import (
        NativeCaptureProducer,
        NativeCaptureResult,
    )
    from isaaclab_arena_examples.agentic_environment_generation.web_api import native_scene_worker as child

    f = native_transport_fixture(tmp_path)
    events = []
    try:
        receipt, observation = native_transport_evidence(f)
        packet = protocol.retain_request(
            f.area,
            root=f.root,
            action="capture",
            intent=f.intent,
            candidate=f.candidate,
            original=f.candidate,
            contract=f.contract,
            settings=f.settings,
            deadline=time.time() + 4,
            protect=f.protect,
        )

        def close():
            events.append("close")
            if failure.startswith("exit-"):
                raise SystemExit(0 if failure == "exit-zero" else 7)
            if failure == "shutdown":
                assert f.area.has_final("native-scene-output", protocol.result_version(packet))
                raise RuntimeError("synthetic Kit shutdown failure")

        def capture(self, **kwargs):
            events.append("capture")
            if failure == "capture":
                raise RuntimeError("synthetic native failure")
            return NativeCaptureResult(receipt, observation)

        monkeypatch.setattr(child, "_parent_guard", lambda parent: None)
        monkeypatch.setattr(child, "_arm_deadline", lambda deadline: None)
        monkeypatch.setattr(child, "_verify_identity", lambda request: None)
        monkeypatch.setattr(child, "_initialize_kit", lambda settings: SimpleNamespace(close=close))
        monkeypatch.setattr(child, "_validate_spec", lambda candidate: candidate)
        monkeypatch.setattr(NativeCaptureProducer, "__call__", capture)
        monkeypatch.setattr(child.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(packet).encode() + b"\n")))
        monkeypatch.setattr(child.os, "dup2", lambda *args: None)  # Never redirect the test runner's stdout.
        with (tmp_path / "channel").open("w+") as channel:
            monkeypatch.setattr(child.sys, "stdout", channel)
            assert child.main(["--parent-pid", "101", "--stage", "capture"]) == {
                "exit-zero": 0,
                "exit-seven": 7,
            }.get(failure, 1)
            channel.seek(0)
            raw = channel.read()
            if failure == "capture":
                assert raw == ""
            else:
                # A receipt precedes possibly process-terminating Kit shutdown;
                # the receiver must still refuse its nonzero exit (tested above).
                frame = json.loads(raw)
                assert frame["result"]["version"] == protocol.result_version(packet)
        assert events == ["capture", "close"]
    finally:
        f.area.close()


@pytest.mark.parametrize("stage", ["capture", "assess"])
def test_owned_native_numeric_send_receive_over_local_pipe_without_child(tmp_path, monkeypatch, stage):
    """Real bounded pipe I/O and immutable receipts; synthetic process/cleanup seam."""
    import os
    import threading
    import time
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow import native_worker_protocol as protocol
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import PreparedWorker
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import identity
    from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import (
        ForegroundGenerationReceiver,
    )
    from isaaclab_arena_examples.agentic_environment_generation.foreground_native_scene import (
        ForegroundNativeCaptureWorker,
        ForegroundNumericAssessmentWorker,
    )

    f = native_transport_fixture(tmp_path)
    read_fd, write_fd = os.pipe()
    try:
        receipt, observation = native_transport_evidence(f)
        if stage == "assess":
            fence = f.registration.fence.model_copy(update={"intent_id": "b" * 64})
            f.registration = f.registration.model_copy(update={"fence": fence})
            f.intent = f.intent.model_copy(
                update=dict(
                    action="assess",
                    intent_id=fence.intent_id,
                    worker_fence=fence,
                    worker_registration=f.registration,
                    observation_id="c" * 64,
                    observation_digest=identity(observation.model_dump(mode="json")),
                    reservation=f.intent.reservation.model_copy(update=dict(realizations=0, observations=0, steps=0)),
                )
            )
        worker_type = ForegroundNativeCaptureWorker if stage == "capture" else ForegroundNumericAssessmentWorker
        worker = worker_type(settings=f.settings, artifacts=SimpleNamespace(area=f.area), artifact_root=f.root)
        monkeypatch.setenv("OPENAI_API_KEY", "must-not-leave-parent")
        args, kwargs = worker._production_spawn()
        assert args[2].endswith(".native_scene_worker") and args[-2:] == ["--stage", stage]
        assert "OPENAI_API_KEY" not in kwargs["env"]
        process = SimpleNamespace(stdin=os.fdopen(write_fd, "wb"), returncode=0, wait=lambda timeout: 0)
        owned = SimpleNamespace(
            process=process,
            registration=f.registration,
            contract=f.contract,
            lock=threading.RLock(),
            attempted=False,
            cleanup=None,
            started=time.monotonic(),
            deadline=time.monotonic() + 3,
        )
        worker._owned.append(owned)
        prepared = PreparedWorker(f.registration, owned)
        deadline = owned.deadline
        monkeypatch.setattr(worker, "_arm", lambda owned, value: setattr(owned, "deadline", value))
        options = dict(protect=f.protect, deadline=time.time() + 4)
        send = worker.send_capture if stage == "capture" else worker.send_evaluate
        receive = worker.receive_capture if stage == "capture" else worker.receive_evaluate
        if stage == "assess":
            options["retained_observation"] = observation
        send(prepared, f.intent, f.candidate, f.candidate, f.contract, **options)
        packet = protocol.decode_packet(os.read(read_fd, 512 * 1024))
        assert packet == owned.packet and owned.deadline <= deadline
        with pytest.raises(RuntimeError, match="already attempted"):
            send(prepared, f.intent, f.candidate, f.candidate, f.contract, **options)
        output = protocol.capture_reference(receipt) if stage == "capture" else observation.model_dump(mode="json")
        result = protocol.retain_result(f.area, packet, output, protect=f.protect)
        monkeypatch.setattr(ForegroundGenerationReceiver, "_read", lambda *args: result)

        def stop(prepared, *, timeout_s):
            if owned.cleanup is None:
                owned.cleanup = object()
            return owned.cleanup

        monkeypatch.setattr(worker, "stop_owned", stop)
        monkeypatch.setattr(worker, "cleanup_verified", lambda reg, cleanup: cleanup is owned.cleanup)
        assert receive(prepared, protect=f.protect) == (receipt if stage == "capture" else observation)
        with pytest.raises(RuntimeError, match="stopped"):
            receive(prepared, protect=f.protect)
    finally:
        os.close(read_fd)
        if not process.stdin.closed:
            process.stdin.close()
        f.area.close()


def server_info():
    """Synthetic admitted worker identity, not a live server assertion."""
    return {
        "schema_version": 1,
        "instance_id": "c" * 32,
        "checkpoint_id": "nvidia/GR00T-N1.6-DROID",
        "checkpoint_sha256": "a" * 64,
        "config_sha256": "b" * 64,
        "embodiment": "OXE_DROID",
        "serializer_sha256": "d" * 64,
        "modalities_sha256": "e" * 64,
    }


def policy_proof():
    return {
        "policy_protocol": {"status": "passed", "code": "policy_protocol_available"},
        "policy_model": {"status": "passed", "code": "policy_model_verified"},
        "policy_transport": {"status": "passed", "code": "policy_transport_verified"},
        "server_info": server_info(),
        "evidence": None,
    }


@pytest.fixture(autouse=True)
def no_renderer(monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    async def synthetic_check(_envelope):
        return {
            "runtime": "runtime_available",
            "graph": "not_required",
            "policy": policy_proof(),
        }

    monkeypatch.setattr(readiness, "checked_worker", synthetic_check)
    monkeypatch.setenv("ARENA_GR00T_CHECKPOINT_SHA256", "a" * 64)
    monkeypatch.setenv("ARENA_GR00T_CONFIG_SHA256", "b" * 64)

    def unavailable(_):
        raise RuntimeError("Evaluation units have no renderer")

    monkeypatch.setattr(editor_execution, "make_snapshot_service", unavailable)


def droid_text():
    return FIXTURE.read_text().replace("franka_ik", "droid_abs_joint_pos")


def login(client):
    session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
    return {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}


def test_gr00t_evaluation_refuses_missing_operator_expectation_without_submission(tmp_path, monkeypatch):
    monkeypatch.delenv("ARENA_GR00T_CHECKPOINT_SHA256", raising=False)
    monkeypatch.delenv("ARENA_GR00T_CONFIG_SHA256", raising=False)
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        before = client.get("/api/workspaces/default").json()
        result = client.post(
            "/api/editor/evaluate",
            headers=headers,
            json={
                "yaml_text": droid_text(),
                "idempotency_key": "missing-policy",
                "profile": "gr00t-droid",
            },
        )
        assert result.status_code == 503
        assert result.json()["detail"] == "policy_expectation_missing"
        assert client.get("/api/workspaces/default").json() == before


@pytest.mark.parametrize(
    "failure",
    [
        "policy_model_mismatch",
        "policy_transport_unverified",
        "policy_instance_mismatch",
    ],
)
def test_gr00t_admission_refuses_worker_contract_failures(tmp_path, monkeypatch, failure):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    async def checked(envelope):
        assert envelope["expectations"] == {
            "checkpoint_sha256": "a" * 64,
            "config_sha256": "b" * 64,
        }
        return {
            "runtime": "runtime_available",
            "graph": "not_required",
            "policy": {
                "policy_protocol": {
                    "status": "passed",
                    "code": "policy_protocol_available",
                },
                "policy_model": {
                    "status": "mismatch" if failure != "policy_transport_unverified" else "passed",
                    "code": failure if failure != "policy_transport_unverified" else "policy_model_verified",
                },
                "policy_transport": {
                    "status": "not_checked",
                    "code": "policy_transport_unverified",
                },
                "server_info": None,
                "evidence": None,
            },
        }

    monkeypatch.setattr(readiness, "checked_worker", checked)
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        headers = login(client)
        before = client.get("/api/workspaces/default").json()
        result = client.post(
            "/api/editor/evaluate",
            headers=headers,
            json={
                "yaml_text": droid_text(),
                "idempotency_key": failure,
                "profile": "gr00t-droid",
            },
        )
        assert result.status_code == 503
        assert result.json()["detail"] == failure
        assert client.get("/api/workspaces/default").json() == before


@pytest.mark.parametrize(
    "value",
    ["", "0", "65536", "999999", "05559", "+5559", "-1", " 5559", "5559 ", "5559\n", "５５５９", "5559.0", "1e3"],
)
def test_invalid_operator_port_fails_closed_before_admission(tmp_path, monkeypatch, value):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import policy_endpoint, readiness

    monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", value)
    with pytest.raises(ValueError, match="Invalid GR00T port configuration"):
        policy_endpoint.configured_gr00t_port()
    monkeypatch.setattr(readiness, "checked_worker", lambda *_a: pytest.fail("Invalid port reached worker"))
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        headers = login(client)
        before = client.get("/api/workspaces/default").json()
        result = client.post(
            "/api/editor/evaluate",
            headers=headers,
            json={"yaml_text": droid_text(), "profile": "gr00t-droid", "idempotency_key": "bad-port"},
        )
        assert result.status_code == 503
        assert result.json()["detail"] == "configuration_changed"
        assert client.get("/api/workspaces/default").json() == before


@pytest.mark.parametrize("change", ["5560", "invalid"])
def test_admission_retires_policy_proof_after_port_configuration_changes(tmp_path, monkeypatch, change):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", "5559")

    async def checked(envelope):
        assert envelope["gr00t_port"] == 5559
        monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", change)
        return {"runtime": "runtime_available", "graph": "not_required", "policy": policy_proof()}

    monkeypatch.setattr(readiness, "checked_worker", checked)
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        headers = login(client)
        before = client.get("/api/workspaces/default").json()
        result = client.post(
            "/api/editor/evaluate",
            headers=headers,
            json={"yaml_text": droid_text(), "profile": "gr00t-droid", "idempotency_key": "changed-port"},
        )
        assert result.status_code == 503
        assert result.json()["detail"] == "configuration_changed"
        assert client.get("/api/workspaces/default").json() == before


@pytest.mark.parametrize(
    "endpoint",
    [
        {"remote_host": "127.0.0.1"},
        {"remote_port": 5559},
        {"remote_host": "example.test", "remote_port": 5559},
        *({"remote_host": "127.0.0.1", "remote_port": value} for value in (None, True, 0, -1, 65536, 5559.0, "5559")),
    ],
)
def test_worker_rejects_malformed_frozen_endpoint_before_read_or_write(tmp_path, monkeypatch, endpoint):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import evaluation_worker, policy_readiness

    monkeypatch.setattr(
        policy_readiness, "probe_gr00t", lambda *_a, **_k: pytest.fail("Invalid endpoint reached policy")
    )
    inputs = {
        **FIXED,
        "yaml_text": "unparsed",
        "document_id": None,
        "input_hash": "a" * 64,
        "canonical_hash": "b" * 64,
        "request_sha256": "c" * 64,
        "profile": "gr00t-droid",
        "language_instruction": None,
        "expected_server_info": server_info(),
        **endpoint,
    }
    with pytest.raises(ValueError, match="Invalid frozen evaluation"):
        evaluation_worker.run_evaluation(inputs, tmp_path, on_completed=lambda _: pytest.fail("No evaluation"))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("port", [None, "5559", "1", "65535"])
def test_fixed_profiles_route_freezes_and_replays_without_resolving_source(tmp_path, monkeypatch, port):
    if port is None:
        monkeypatch.delenv("ARENA_WORKBENCH_GR00T_PORT", raising=False)
    else:
        monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", port)
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    async def checked(envelope):
        assert envelope["gr00t_port"] == (5555 if port is None else int(port))
        return {"runtime": "runtime_available", "graph": "not_required", "policy": policy_proof()}

    monkeypatch.setattr(readiness, "checked_worker", checked)
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/editor/evaluation-profiles").status_code == 401
        headers = login(client)
        catalogue = client.get("/api/editor/evaluation-profiles")
        assert catalogue.status_code == 200, catalogue.text
        assert catalogue.json() == {
            "profiles": [
                {
                    "id": "gr00t-droid",
                    "label": "GR00T DROID",
                    "remote_host": "127.0.0.1",
                    "remote_port": 5555 if port is None else int(port),
                },
                {
                    "id": "openpi-droid",
                    "label": "OpenPI DROID",
                    "remote_host": "127.0.0.1",
                    "remote_port": 8000,
                },
            ],
            **FIXED,
            "publication": "not_requested",
            "policy_contracts": {
                "gr00t-droid": {
                    "schema_version": 1,
                    "protocol": "gr00t-zmq",
                    "checkpoint_id": "nvidia/GR00T-N1.6-DROID",
                    "verification": "pinned_model_and_codec_required",
                },
                "openpi-droid": {
                    "schema_version": 1,
                    "protocol": "openpi-websocket",
                    "checkpoint_id": None,
                    "verification": "openpi_verification_unsupported",
                },
            },
        }
        for url in ("/api/editor", "/api/health"):
            assert client.get(url).json()["capabilities"]["policy_evaluation"] is True
        body = {
            "yaml_text": droid_text(),
            "idempotency_key": "eval-first",
            "profile": "gr00t-droid",
        }
        assert client.post("/api/editor/evaluate", json=body).status_code == 403
        response = client.post("/api/editor/evaluate", json=body, headers=headers)
        assert response.status_code == 202, response.text
        job = response.json()
        assert job["kind"] == "evaluate" and job["status"] == "queued"
        assert {key: job["inputs"][key] for key in FIXED} == FIXED
        assert job["inputs"]["language_instruction"] is None
        assert job["inputs"]["profile"] == "gr00t-droid"
        assert job["inputs"]["remote_host"] == "127.0.0.1"
        assert job["inputs"]["remote_port"] == (5555 if port is None else int(port))
        assert job["inputs"]["document_id"] is None
        assert "external_yaml:" not in job["inputs"]["yaml_text"]
        validation = client.post("/api/editor/validate", json={"yaml_text": droid_text()}, headers=headers).json()
        assert job["inputs"]["input_hash"] == validation["source_hash"]
        assert job["inputs"]["canonical_hash"] == validation["canonical_hash"]
        monkeypatch.setattr(
            app.state.documents,
            "validate",
            lambda *a: pytest.fail("replay resolved source"),
        )
        monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", "invalid-after-admission")
        monkeypatch.setattr(readiness, "checked_worker", lambda *a: pytest.fail("replay rechecked policy"))
        assert client.post("/api/editor/evaluate", json=body, headers=headers).json() == job
        assert (
            client.post(
                "/api/editor/evaluate",
                json={**body, "profile": "openpi-droid"},
                headers=headers,
            ).status_code
            == 409
        )
        assert client.get("/api/jobs/" + job["id"]).json() == job
        assert client.post("/api/jobs/" + job["id"] + "/cancel", headers=headers).json()["status"] == "cancelled"


@pytest.mark.parametrize("profile", ["gr00t-droid", "openpi-droid"])
@pytest.mark.parametrize("frozen_port", [None, 5559])
@pytest.mark.parametrize("instruction", ["Pick up the cube", "--headless"])
@pytest.mark.parametrize("no_episodes", [False, True])
def test_worker_uses_local_only_harness_callback_and_actual_artifacts(
    tmp_path, monkeypatch, profile, instruction, no_episodes, frozen_port
):
    """Simulated policy_runner boundary; artifact bytes/counts are actual local files."""
    import json
    import sys
    import yaml
    from dataclasses import dataclass
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    from isaaclab_arena.evaluation import policy_runner_cli
    from isaaclab_arena_examples.agentic_environment_generation.web_api import evaluation_worker, policy_readiness

    @dataclass
    class NativeCfg:
        expected_server_info: dict | None = None

    def probe(expected, **kwargs):
        assert kwargs["port"] == (5555 if frozen_port is None else frozen_port)
        return policy_proof()

    monkeypatch.setattr(policy_readiness, "probe_gr00t", probe)
    monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", "invalid-after-admission")
    monkeypatch.setattr(policy_runner_cli, "policy_cfg_from_cli", lambda *_: NativeCfg())
    validation = Documents(tmp_path / "documents").validate(droid_text())
    inputs = {
        **FIXED,
        "yaml_text": yaml.safe_dump(validation["spec"], sort_keys=False),
        "document_id": None,
        "input_hash": validation["source_hash"],
        "canonical_hash": validation["canonical_hash"],
        "request_sha256": "e" * 64,
        "profile": profile,
        "language_instruction": instruction,
    }
    if profile == "gr00t-droid":
        inputs["expected_server_info"] = server_info()
    if frozen_port is not None:
        inputs.update(remote_host="127.0.0.1", remote_port=frozen_port if profile == "gr00t-droid" else 8000)
    root = tmp_path / "owned-job"
    root.mkdir()
    receipts = []
    argv_before = sys.argv
    metrics = None if no_episodes else {"success_rate": 0.5, "task_progress": {"lifted": 0.25}}
    artifacts = {
        "index.html": b"<html><body>Actual unit report</body></html>",
        "episode_results_rank0.jsonl": b'{"success":true,"episode_length":12}\n{"success":false,"episode_length":25}\n',
        "eval_telemetry.ttl": b"@prefix prov: <http://www.w3.org/ns/prov#> .\n",
    }
    if no_episodes:
        artifacts["episode_results_rank0.jsonl"] = b""

    def runner_main(**kwargs):
        assert kwargs["publish_to_graph"] is False
        assert kwargs["update_lineage"] is False
        assert kwargs["telemetry_env_name"] == validation["spec"]["env_name"]
        argv = sys.argv

        def value(flag):
            return argv[argv.index(flag) + 1]

        assert "--headless" in argv and "--enable_cameras" in argv
        assert value("--num_envs") == "1" and value("--num_steps") == "1000"
        assert value("--remote_host") == "127.0.0.1"
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--language_instruction")
        parser.add_argument("--headless", action="store_true")
        parsed, _ = parser.parse_known_args(argv[1:])
        assert parsed.language_instruction == instruction
        assert Path(value("--env_graph_spec_yaml")).read_text() == inputs["yaml_text"]
        assert Path.cwd() == Path(evaluation_worker.__file__).resolve().parents[3]
        assert not any(
            flag in argv
            for flag in (
                "--record_camera_video",
                "--record_viewport_video",
                "--distributed",
                "--serve_evaluation_report",
                "--remote_kill_on_exit",
                "--num_episodes",
            )
        )
        if profile == "gr00t-droid":
            bound = runner_module.build_policy_from_cli(lambda cfg: cfg, None)
            assert bound.expected_server_info == server_info()
            assert bound.expected_server_info is not inputs["expected_server_info"]
            assert value("--remote_port") == str(5555 if frozen_port is None else frozen_port)
            assert (
                value("--policy_type")
                == "isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy"
            )
            assert (
                value("--policy_config_yaml_path")
                == "isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml"
            )
        else:
            assert value("--remote_port") == "8000"
            assert value("--policy_type") == "isaaclab_arena_openpi.policy.pi0_remote_policy.Pi0RemotePolicy"
            assert value("--policy_variant") == "pi05"
            assert value("--openpi_embodiment_adapter") == "droid"
        output = Path(value("--output_base_dir")) / "actual-run"
        output.mkdir(parents=True)
        for name, data in artifacts.items():
            (output / name).write_bytes(data)
        (output / "private.hdf5").write_bytes(b"not exposed")
        kwargs["on_evaluation_completed"]({
            "output_dir": str(output),
            "report_path": str(output / "index.html"),
            "metrics": metrics,
            "num_steps": 1000,
            "num_episodes": None,
            "warnings": [],
        })
        assert len(receipts) == 1  # receipt is flushed before simulated terminating shutdown
        raise SystemExit(0)

    def original_factory(*_):
        return NativeCfg()

    runner_module = SimpleNamespace(main=runner_main, build_policy_from_cli=original_factory)
    monkeypatch.setitem(sys.modules, "isaaclab_arena.evaluation.policy_runner", runner_module)
    with pytest.raises(SystemExit) as exited:
        evaluation_worker.run_evaluation(inputs, root, on_completed=receipts.append)
    assert exited.value.code == 0 and sys.argv is argv_before
    result = receipts[0]
    assert result["metrics"] == metrics
    assert (result["episode_count"], result["success_count"]) == ((0, None) if no_episodes else (2, 1))
    if no_episodes:
        assert any("No completed-episode evidence" in warning for warning in result["warnings"])
    assert result["publication"] == "not_requested" and result["completed"] is True
    assert str(root) not in json.dumps(result)
    assert {row["name"] for row in result["artifacts"]} == set(artifacts)
    import hashlib

    for row in result["artifacts"]:
        data = (root / "artifacts" / row["name"]).read_bytes()
        assert data == artifacts[row["name"]]
        assert row == {
            "name": row["name"],
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }


@pytest.mark.parametrize(
    "fault,code",
    [
        ("missing", "policy_metadata_unavailable"),
        ("instance", "policy_instance_mismatch"),
        ("transport", "policy_transport_unverified"),
    ],
)
def test_worker_refuses_unpinned_or_changed_policy_before_writing_scene(tmp_path, monkeypatch, fault, code):
    import yaml

    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    from isaaclab_arena_examples.agentic_environment_generation.web_api import evaluation_worker, policy_readiness

    validated = Documents(tmp_path / "documents").validate(droid_text())
    inputs = {
        **FIXED,
        "yaml_text": yaml.safe_dump(validated["spec"]),
        "document_id": None,
        "input_hash": validated["source_hash"],
        "canonical_hash": validated["canonical_hash"],
        "request_sha256": "f" * 64,
        "profile": "gr00t-droid",
        "language_instruction": None,
    }
    if fault != "missing":
        inputs["expected_server_info"] = server_info()

    def probe(expectations, **_kwargs):
        assert expectations == {
            "checkpoint_sha256": "a" * 64,
            "config_sha256": "b" * 64,
        }
        proof = policy_proof()
        if fault == "instance":
            proof["server_info"]["instance_id"] = "f" * 32
        if fault == "transport":
            proof["policy_transport"] = {
                "status": "not_checked",
                "code": "policy_transport_unverified",
            }
        return proof

    monkeypatch.setattr(policy_readiness, "probe_gr00t", probe)
    output = tmp_path / "owned"
    output.mkdir()
    with pytest.raises(ValueError, match=code):
        evaluation_worker.run_evaluation(inputs, output, on_completed=lambda _: pytest.fail("Unexpected evaluation"))
    assert list(output.iterdir()) == []


def wait_job(client, job_id, statuses):
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get("/api/jobs/" + job_id).json()
        if job["status"] in statuses or job["stage"] == "cleanup_pending":
            return job
        time.sleep(0.01)
    return pytest.fail(f"Evaluation never reached {statuses}: {job}")


def simulated_peer(
    monkeypatch,
    app,
    tmp_path,
    *,
    change=None,
    exit_code=0,
    frames=1,
    cleanup_error=False,
    wait_for_signal=False,
    on_cleanup=None,
):
    """Simulated OS ownership only, using real artifact files and the production dispatcher."""
    import asyncio
    import fcntl
    import json
    import threading
    from types import SimpleNamespace

    from isaaclab_arena_examples.agentic_environment_generation.web_api import snapshot_process, supervisor
    from isaaclab_arena_examples.agentic_environment_generation.web_api.evaluation_artifacts import artifact_metadata

    events = []
    signal = threading.Event()
    lease = tmp_path / "gpu.lock"
    monkeypatch.setattr(snapshot_process, "GPU_LEASE", lease)
    monkeypatch.setattr(editor_execution, "process_identity", lambda pid: "123")

    class Snapshot:
        def close(self):
            events.append("snapshot_reaped")

    app.state.editor_execution.snapshots = Snapshot()

    class Group:
        cleaned = False

        def __init__(self, pid):
            assert pid == 987654

        def stop(self):
            events.append("cleanup")
            with lease.open("rb") as other:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if on_cleanup:
                on_cleanup()
            if cleanup_error:
                raise RuntimeError("private cleanup details")
            self.cleaned = True

        def send_signal(self, sig):
            events.append("signal")
            signal.set()

    monkeypatch.setattr(supervisor, "OwnedProcessGroup", Group)

    async def spawn(*argv, **kwargs):
        assert events == ["snapshot_reaped"]
        assert argv[1:4] == (
            "-u",
            "-m",
            "isaaclab_arena_examples.agentic_environment_generation.web_api.evaluation_worker",
        )
        assert kwargs["start_new_session"] is True and kwargs["pass_fds"]
        assert kwargs["limit"] == 256 * 1024
        assert "OPENAI_API_KEY" not in kwargs["env"] and "NEO4J_PASSWORD" not in kwargs["env"]
        events.append("spawn")
        pending = []

        class Input:
            def write(self, data):
                envelope = json.loads(data)
                inputs = envelope["inputs"]
                artifacts = Path(envelope["output_root"]) / "artifacts"
                assert str(artifacts) not in json.dumps(inputs)
                artifacts.mkdir()
                files = {
                    "index.html": b"<html><script>fetch('/api/jobs')</script></html>",
                    "episode_results_rank0.jsonl": b'{"success":true,"episode_length":20}\n',
                }
                for name, value in files.items():
                    (artifacts / name).write_bytes(value)
                result = {
                    "schema_version": 1,
                    **FIXED,
                    "profile": inputs["profile"],
                    "language_instruction": inputs["language_instruction"],
                    "completed": True,
                    "input_hash": inputs["input_hash"],
                    "canonical_hash": inputs["canonical_hash"],
                    "publication": "not_requested",
                    "metrics": {"task_progress": 0.25},
                    "episode_count": 1,
                    "success_count": 1,
                    "warnings": [],
                    "artifacts": [artifact_metadata(name, value) for name, value in files.items()],
                }
                if change:
                    change(result, artifacts)
                pending.extend([(json.dumps({"result": result}) + "\n").encode()] * frames + [b""])

            async def drain(self):
                pass

            def close(self):
                pass

        class Output:
            async def readline(self):
                while wait_for_signal and not signal.is_set():
                    await asyncio.sleep(0.01)
                return pending.pop(0)

        async def wait():
            process.returncode = exit_code
            events.append("reaped")
            return exit_code

        process = SimpleNamespace(pid=987654, returncode=None, stdin=Input(), stdout=Output(), wait=wait)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return events, lease


def test_dispatch_reaps_then_exposes_verified_authenticated_artifact(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, lease = simulated_peer(monkeypatch, app, tmp_path)
        headers = login(client)
        body = {
            "yaml_text": droid_text(),
            "profile": "openpi-droid",
            "idempotency_key": "execute",
        }
        response = client.post("/api/editor/evaluate", json=body, headers=headers)
        assert response.status_code == 202, response.text
        job = wait_job(client, response.json()["id"], {"succeeded", "failed"})
        assert job["status"] == "succeeded", job
        assert events.index("snapshot_reaped") < events.index("spawn") < events.index("cleanup")
        assert app.state.supervisor.process is None and app.state.journal.pending_workers() == []
        assert client.post("/api/editor/evaluate", json=body, headers=headers).json() == job
        assert events.count("spawn") == 1
        url = f"/api/editor/evaluations/{job['id']}/artifacts/index.html"
        download = client.get(url)
        assert download.status_code == 200, download.text
        assert download.content == b"<html><script>fetch('/api/jobs')</script></html>"
        assert download.headers["x-content-type-options"] == "nosniff"
        assert "attachment" in download.headers["content-disposition"]
        assert "sandbox" in download.headers["content-security-policy"]
        assert "allow-scripts" not in download.headers["content-security-policy"]
        assert client.get(url.replace("index.html", "private.hdf5")).status_code == 404
        assert client.get(url.replace(job["id"], "0" * 32)).status_code == 404
        client.cookies.clear()
        assert client.get(url).status_code == 401
        login(client)
        # Readback hashes actual bytes on every request, not an earlier metadata assertion.
        root = tmp_path / "evaluations" / job["id"] / "artifacts"
        (root / "index.html").write_text("changed")
        assert client.get(url).status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"profile": "other"},
        {"num_steps": 1},
        {"remote_host": "example.com"},
        {"remote_host": "127.0.0.1"},
        {"remote_port": 5559},
        {"gr00t_port": 5559},
        {"output_base_dir": "/tmp/out"},
        {"language_instruction": " "},
        {"language_instruction": "é" * 2001},
        {"language_instruction": 123},
    ],
)
def test_route_rejects_overrides_and_bad_instruction(tmp_path, change):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        body = {
            "yaml_text": droid_text(),
            "profile": "gr00t-droid",
            "idempotency_key": "bad",
            **change,
        }
        assert client.post("/api/editor/evaluate", json=body, headers=headers).status_code == 422
        assert app.state.journal.snapshot()["jobs"] == []


@pytest.mark.parametrize(
    "embodiment,params",
    [
        ("franka_ik", {}),
        ("droid_rel_joint_pos", {}),
        ("droid_abs_joint_pos", {"enable_cameras": False}),
        ("droid_abs_joint_pos", {"concatenate_observation_terms": True}),
        ("droid_abs_joint_pos", {"arm_mode": "dual_arm"}),
        ("droid_abs_joint_pos", {"camera_config": {"wrist_camera": None}}),
    ],
)
def test_incompatible_source_is_rejected_before_dispatch(tmp_path, embodiment, params):
    import yaml

    spec = yaml.safe_load(droid_text())
    spec["embodiment"].update(registry_name=embodiment, params=params)
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post(
            "/api/editor/evaluate",
            headers=login(client),
            json={
                "yaml_text": yaml.safe_dump(spec),
                "profile": "openpi-droid",
                "idempotency_key": "incompatible",
            },
        )
        assert response.status_code == 422, response.text
        assert app.state.journal.snapshot()["jobs"] == []


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_hash",
        "wrong_profile",
        "wrong_instruction",
        "wrong_budget",
        "bool_count",
        "publication",
        "nan",
        "oversized_metrics",
        "extra_path",
        "false_episode_count",
        "empty_episodes_with_positive_count",
        "missing_report",
        "digest",
        "size",
        "name",
        "duplicate_artifact",
        "leaf_symlink",
        "ancestor_symlink",
        "zero_receipts",
        "two_receipts",
        "nonzero_exit",
    ],
)
def test_parent_rejects_invalid_result_identity_and_artifacts(tmp_path, monkeypatch, fault):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.evaluation_artifacts import artifact_metadata

    def change(result, root):
        changes = {
            "wrong_hash": {"input_hash": "0" * 64},
            "wrong_profile": {"profile": "gr00t-droid"},
            "wrong_instruction": {"language_instruction": "other"},
            "wrong_budget": {"num_steps": 999},
            "bool_count": {"episode_count": True},
            "publication": {"publication": "published"},
            "nan": {"metrics": {"rate": float("nan")}},
            "extra_path": {"output_dir": str(root)},
            "oversized_metrics": {"metrics": {"large": "a" * (128 * 1024)}},
            "false_episode_count": {"episode_count": 2},
        }
        result.update(changes.get(fault, {}))
        if fault == "empty_episodes_with_positive_count":
            (root / "episode_results_rank0.jsonl").write_bytes(b"")
            result["artifacts"][1] = artifact_metadata("episode_results_rank0.jsonl", b"")
        elif fault == "missing_report":
            (root / "index.html").unlink()
        elif fault == "digest":
            result["artifacts"][0]["sha256"] = "0" * 64
        elif fault == "size":
            result["artifacts"][0]["size"] += 1
        elif fault == "name":
            result["artifacts"][0]["name"] = "../index.html"
        elif fault == "duplicate_artifact":
            result["artifacts"].append(result["artifacts"][0])
        elif fault == "leaf_symlink":
            leaf = root / "index.html"
            copy = root / "other.html"
            leaf.rename(copy)
            leaf.symlink_to(copy)
        elif fault == "ancestor_symlink":
            copy = root.parent / "linked"
            root.rename(copy)
            root.symlink_to(copy, target_is_directory=True)

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_peer(
            monkeypatch,
            app,
            tmp_path,
            change=change,
            frames=(0 if fault == "zero_receipts" else 2 if fault == "two_receipts" else 1),
            exit_code=1 if fault == "nonzero_exit" else 0,
        )
        response = client.post(
            "/api/editor/evaluate",
            headers=login(client),
            json={
                "yaml_text": droid_text(),
                "profile": "openpi-droid",
                "idempotency_key": "invalid-evidence",
            },
        )
        job = wait_job(client, response.json()["id"], {"failed", "succeeded"})
        assert job["status"] == "failed" and job["result"] is None, job
        assert "cleanup" in events and app.state.journal.pending_workers() == []
        assert client.get(f"/api/editor/evaluations/{job['id']}/artifacts/index.html").status_code == 404


def test_episode_counts_preserve_null_and_every_actual_row():
    from isaaclab_arena_examples.agentic_environment_generation.web_api.evaluation_artifacts import episode_counts

    assert episode_counts(b'{"success":true}\n{"success":null}\n') == (2, None)
    assert episode_counts(b'{"success":false}\n{"success":true}\n') == (2, 1)
    assert episode_counts(b'{"success":true}\n{"success":1}\n') == (2, None)
    assert episode_counts(b"") == (0, None)
    assert episode_counts(b"\n \n") == (0, None)


def test_zero_episode_run_completes_with_unknown_success_and_empty_artifact(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.evaluation_artifacts import artifact_metadata

    def no_episodes(result, root):
        name = "episode_results_rank0.jsonl"
        (root / name).write_bytes(b"")
        result["artifacts"][1] = artifact_metadata(name, b"")
        result.update(
            episode_count=0,
            success_count=None,
            metrics=None,
            warnings=["No completed-episode evidence was recorded"],
        )

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_peer(monkeypatch, app, tmp_path, change=no_episodes)
        response = client.post(
            "/api/editor/evaluate",
            headers=login(client),
            json={
                "yaml_text": droid_text(),
                "profile": "openpi-droid",
                "idempotency_key": "no-episodes",
            },
        )
        assert response.status_code == 202
        job = wait_job(client, response.json()["id"], {"succeeded", "failed"})
        assert job["status"] == "succeeded", job
        assert job["result"]["episode_count"] == 0 and job["result"]["success_count"] is None
        assert job["result"]["metrics"] is None and "cleanup" in events
        download = client.get(f"/api/editor/evaluations/{job['id']}/artifacts/episode_results_rank0.jsonl")
        assert download.status_code == 200 and download.content == b""


def test_evaluation_timeout_reaps_worker_without_changing_build_bound(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import build_execution

    assert build_execution.EVALUATION_TIMEOUT == 900 and build_execution.BUILD_TIMEOUT == 300
    monkeypatch.setattr(build_execution, "EVALUATION_TIMEOUT", 0.1)
    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_peer(monkeypatch, app, tmp_path, wait_for_signal=True)
        response = client.post(
            "/api/editor/evaluate",
            headers=login(client),
            json={
                "yaml_text": droid_text(),
                "profile": "openpi-droid",
                "idempotency_key": "timeout",
            },
        )
        job = wait_job(client, response.json()["id"], {"failed", "succeeded"})
        assert job["status"] == "failed" and job["result"] is None
        assert "cleanup" in events and app.state.journal.pending_workers() == []


def test_cancellation_signals_owned_group_and_hides_artifacts(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_peer(monkeypatch, app, tmp_path, wait_for_signal=True)
        headers = login(client)
        response = client.post(
            "/api/editor/evaluate",
            headers=headers,
            json={
                "yaml_text": droid_text(),
                "profile": "openpi-droid",
                "idempotency_key": "cancel",
            },
        )
        job_id = response.json()["id"]
        import time

        deadline = time.monotonic() + 3
        while "spawn" not in events and time.monotonic() < deadline:
            time.sleep(0.01)
        assert "spawn" in events
        client.post(f"/api/jobs/{job_id}/cancel", headers=headers)
        job = wait_job(client, job_id, {"cancelled"})
        assert job["result"] is None and "signal" in events and "cleanup" in events
        assert client.get(f"/api/editor/evaluations/{job_id}/artifacts/index.html").status_code == 404


@pytest.mark.parametrize("when", ["before_acceptance", "after_acceptance"])
def test_actual_artifact_bytes_are_screened_under_current_public_policy(tmp_path, monkeypatch, when):
    from fastapi import HTTPException

    from isaaclab_arena_examples.agentic_environment_generation.web_api.evaluation_artifacts import artifact_metadata

    marker = "synthetic-private-marker"
    active = when == "before_acceptance"

    def change(result, root):
        # HTML entity spelling verifies the actual downloadable bytes, not just result metadata.
        data = ("<html>" + "".join(f"&#{ord(c)};" for c in marker) + "</html>").encode()
        (root / "index.html").write_bytes(data)
        result["artifacts"][0] = artifact_metadata("index.html", data)

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        original = app.state.model_settings.protect_public

        def protect(value):
            original(value)
            if active and marker in str(value):
                raise HTTPException(422, "Invalid request input")

        monkeypatch.setattr(app.state.model_settings, "protect_public", protect)
        simulated_peer(monkeypatch, app, tmp_path, change=change)
        response = client.post(
            "/api/editor/evaluate",
            headers=login(client),
            json={
                "yaml_text": droid_text(),
                "profile": "openpi-droid",
                "idempotency_key": "public-screen",
            },
        )
        job = wait_job(client, response.json()["id"], {"succeeded", "failed"})
        assert job["status"] == ("failed" if active else "succeeded")
        active = True
        download = client.get(f"/api/editor/evaluations/{job['id']}/artifacts/index.html")
        assert download.status_code in (404, 422)
        assert marker not in download.text


@pytest.mark.parametrize("when", ["before_acceptance", "after_acceptance"])
@pytest.mark.parametrize("spelling", ["html-u", "html-U", "html-x", "html-folded", "html-entity", "jsonl-u"])
def test_cross_chunk_escaped_credentials_rejected_at_acceptance_and_download(tmp_path, monkeypatch, when, spelling):
    """Real current credential guard and file readback; only the worker/OS seam is simulated."""
    import hashlib
    import html
    import json

    from fastapi import HTTPException

    from isaaclab_arena_examples.agentic_environment_generation.web_api.evaluation_artifacts import (
        MAX_ARTIFACT_BYTES,
        artifact_metadata,
    )

    marker = "synthetic-boundary-" + "k" * (4096 - len("synthetic-boundary-"))
    escape = {"html-x": "x", "html-U": "U"}.get(spelling, "u")
    digits = {"x": 2, "u": 4, "U": 8}[escape]
    encoded = "".join("\\" + escape + format(ord(c), f"0{digits}x") for c in marker)
    # Straddle both ends of the old 8192-character overlap, using ASCII so
    # byte and character boundaries coincide. Neither chunk contains the key.
    width, overlap = 128 * 1024, 8192
    start = width - overlap // 2 - len(encoded) // 2
    assert start < width - overlap and start + len(encoded) > width
    if spelling == "html-folded":
        middle = len(encoded) // 2
        encoded = encoded[:middle] + "\\\n" + " " * (width + 1) + encoded[middle:]
    if spelling == "jsonl-u":
        name = "episode_results_rank0.jsonl"
        prefix = '{"success":true,"padding":"'
        prefix += "p" * (start - len(prefix) - len('","note":"')) + '","note":"'
        text = prefix + encoded + '"}\n'
        assert json.loads(text)["note"] == marker
    else:
        name = "index.html"
        prefix = "<html><!--" + "p" * (start - len("<html><!----><pre>")) + "--><pre>"
        text = prefix + encoded + "</pre></html>"
        if spelling == "html-entity":
            text = text.replace("\\", "&#92;")
    data = text.encode("ascii")
    assert len(prefix) == start and len(data) < MAX_ARTIFACT_BYTES
    assert marker not in text and marker not in html.unescape(text)

    def change(result, root):
        (root / name).write_bytes(data)
        result["artifacts"] = [
            artifact_metadata(name, data) if row["name"] == name else row for row in result["artifacts"]
        ]

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        simulated_peer(monkeypatch, app, tmp_path, change=change)
        headers = login(client)

        def activate():
            saved = client.put(
                "/api/model-settings",
                headers=headers,
                json={
                    "provider": "openai",
                    "model": "offline-unit",
                    "api_key": marker,
                    "ttl_minutes": 15,
                },
            )
            assert saved.status_code == 200
            assert marker not in saved.text
            with pytest.raises(HTTPException) as rejected:
                app.state.model_settings.protect_public(marker)
            assert rejected.value.status_code == 422 and rejected.value.detail == "Invalid request input"

        if when == "before_acceptance":
            activate()
        response = client.post(
            "/api/editor/evaluate",
            headers=headers,
            json={
                "yaml_text": droid_text(),
                "profile": "openpi-droid",
                "idempotency_key": "escaped-screen",
            },
        )
        assert response.status_code == 202
        job = wait_job(client, response.json()["id"], {"succeeded", "failed"})
        artifact = tmp_path / "evaluations" / job["id"] / "artifacts" / name
        assert artifact.read_bytes() == data  # candidate really reached the production verifier
        assert job["status"] == ("failed" if when == "before_acceptance" else "succeeded")
        url = f"/api/editor/evaluations/{job['id']}/artifacts/{name}"
        if when == "after_acceptance":
            row = next(row for row in job["result"]["artifacts"] if row["name"] == name)
            assert row == {
                "name": name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            original = client.get(url)
            assert original.status_code == 200 and original.content == data
            activate()
        else:
            assert job["result"] is None
        download = client.get(url)
        assert download.status_code == (404 if when == "before_acceptance" else 422)
        assert marker not in download.text and encoded not in download.text
        assert artifact.read_bytes() == data  # screening must not rewrite sealed bytes
        assert app.state.journal.pending_workers() == []


def test_unverified_evaluation_cleanup_retains_dispatch_slot_and_lease(tmp_path, monkeypatch):
    import os
    import time

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_peer(monkeypatch, app, tmp_path, cleanup_error=True)
        headers = login(client)
        body = {
            "yaml_text": droid_text(),
            "profile": "openpi-droid",
            "idempotency_key": "cleanup-fault",
        }
        response = client.post("/api/editor/evaluate", headers=headers, json=body)
        job = wait_job(client, response.json()["id"], {"succeeded", "failed"})
        try:
            assert job["stage"] == "cleanup_pending" and job["status"] == "running"
            assert job["result"] is None and app.state.supervisor.process is not None
            assert app.state.editor_execution.build_lease_fd is not None
            assert app.state.journal.pending_workers()[0]["job_id"] == job["id"]
            later = client.post(
                "/api/editor/evaluate",
                headers=headers,
                json={**body, "idempotency_key": "later"},
            ).json()
            client.post("/api/jobs/resume-queue", headers=headers)
            time.sleep(0.3)
            assert client.get("/api/jobs/" + later["id"]).json()["status"] == "queued"
            assert events.count("spawn") == 1
        finally:
            # Dispose fake OS identities only; not a production recovery procedure.
            app.state.supervisor.paused = True
            app.state.supervisor._process_group.cleaned = True
            app.state.supervisor.process.returncode = 0
            for name in ("build_owner_fd", "build_lease_fd"):
                fd = getattr(app.state.editor_execution, name, None)
                if fd is not None:
                    os.close(fd)
                    setattr(app.state.editor_execution, name, None)


@pytest.mark.parametrize(
    "fault",
    [
        "before_callback",
        "missing_callback",
        "missing_report",
        "zero_episodes",
        "outside_output",
        "after_callback",
        "nonzero_return",
        "duplicate_callback",
    ],
)
def test_worker_main_emits_only_bounded_completion_or_private_failure(tmp_path, monkeypatch, fault, capsys):
    """Simulated harness boundary through the real worker envelope/protocol, no simulator imports."""
    import contextlib
    import io
    import json
    import sys
    import yaml
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    from isaaclab_arena_examples.agentic_environment_generation.web_api import evaluation_worker, snapshot_process

    validation = Documents(tmp_path / "docs").validate(droid_text())
    inputs = {
        **FIXED,
        "yaml_text": yaml.safe_dump(validation["spec"]),
        "document_id": None,
        "input_hash": validation["source_hash"],
        "canonical_hash": validation["canonical_hash"],
        "request_sha256": "e" * 64,
        "profile": "openpi-droid",
        "language_instruction": None,
    }
    root = tmp_path / "job"
    root.mkdir()
    channel = io.StringIO()

    @contextlib.contextmanager
    def private_channel():
        yield channel

    def fail():
        raise RuntimeError("synthetic private harness failure")

    def runner_main(**kwargs):
        assert kwargs["publish_to_graph"] is False and kwargs["update_lineage"] is False
        assert "--language_instruction" not in sys.argv  # null preserves the real task description
        if fault == "before_callback":
            fail()
        if fault == "missing_callback":
            return None
        output = (tmp_path / "outside") if fault == "outside_output" else root / "output" / "run"
        output.mkdir(parents=True)
        if fault != "missing_report":
            (output / "index.html").write_text("<html>unit report</html>")
        (output / "episode_results_rank0.jsonl").write_text("" if fault == "zero_episodes" else '{"success":null}\n')
        evidence = {
            "output_dir": str(output),
            "report_path": str(output / "index.html"),
            "metrics": None,
            "num_steps": 1000,
            "num_episodes": None,
            "warnings": [],
        }
        kwargs["on_evaluation_completed"](evidence)
        if fault == "after_callback":
            fail()
        if fault == "nonzero_return":
            return 1
        if fault == "duplicate_callback":
            kwargs["on_evaluation_completed"](evidence)
        return None

    monkeypatch.setitem(
        sys.modules,
        "isaaclab_arena.evaluation.policy_runner",
        SimpleNamespace(main=runner_main),
    )
    monkeypatch.setattr(evaluation_worker, "private_channel", private_channel)
    monkeypatch.setattr(snapshot_process, "watch_parent", lambda fd: None)
    monkeypatch.setattr(sys, "argv", ["worker", "--owner-fd", "123"])
    monkeypatch.setattr(
        sys,
        "stdin",
        SimpleNamespace(buffer=io.BytesIO((json.dumps({"inputs": inputs, "output_root": str(root)}) + "\n").encode())),
    )
    assert evaluation_worker.main() == (0 if fault == "zero_episodes" else 1)
    messages = [json.loads(line) for line in channel.getvalue().splitlines()]
    assert messages[0] == {"stage": "evaluating_policy"}
    if fault == "zero_episodes":
        assert len(messages) == 2 and set(messages[1]) == {"result"}
        result = messages[1]["result"]
        assert result["episode_count"] == 0 and result["success_count"] is None
        assert result["metrics"] is None
        assert "No completed-episode evidence was recorded" in result["warnings"]
        assert "synthetic private" not in channel.getvalue() and str(root) not in channel.getvalue()
        assert "Traceback" not in capsys.readouterr().err
        return
    assert messages[-1] == {"error": "Evaluation failed; check private runtime logs"}
    assert sum("result" in m for m in messages) == int(
        fault in {"after_callback", "nonzero_return", "duplicate_callback"}
    )
    assert "synthetic private" not in channel.getvalue() and str(root) not in channel.getvalue()
    assert "Traceback" in capsys.readouterr().err
