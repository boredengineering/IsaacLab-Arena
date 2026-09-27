# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit native/numeric transports for OwnedSceneStageAdapter; not enablement.

Compose with settings, SceneEvidenceArtifacts and its exact artifact_root. The
adapter must separately own native authorization/GPU lease, register the prepared
child and commit release before send. Configurable installation supplies current
supervision and readback; this module never issues workload authority or drops a
GPU lease on a timer. Prepare/write/cleanup limits remain distinct from workload.
"""

import hashlib
import os
import selectors
import threading
import time
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.workflow import native_worker_protocol as protocol
from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureSettings

from .foreground_generation import DiagnosticRetentionFailed, ForegroundGenerationReceiver, ForegroundGenerationWorker
from .web_api.native_scene_worker import open_area


def _validated_semantic_sha256(document, validate_document):
    """Hash the validated spec projection, not its callback envelope."""
    if not callable(validate_document):
        raise ValueError("Selected semantic validator required")
    result = validate_document(document)
    if type(result) is not dict or result.get("valid") is not True or type(result.get("spec")) is not dict:
        raise ValueError("Successful semantic validation with a spec required")
    return hashlib.sha256(protocol.canonical(result["spec"])).hexdigest()


class SceneChildFailed(RuntimeError):
    """Actual child exit failure, even when it managed to retain a receipt."""

    def __init__(self, returncode):
        super().__init__("Owned scene child failed; retained bytes are not successful execution")
        self.returncode = returncode


class _ForegroundStageWorker(ForegroundGenerationWorker):
    action = ""

    def __init__(
        self,
        *,
        settings,
        artifacts,
        artifact_root,
        supervision_context=None,
        retain_supervision=None,
        validate_document=None,
        **options,
    ):
        super().__init__(**options)
        self.settings = NativeCaptureSettings.model_validate_json(settings.canonical_bytes())
        self.artifacts, self.artifact_root = artifacts, Path(artifact_root).absolute()
        self.supervision_context = supervision_context
        self.retain_supervision = retain_supervision
        self.validate_document = validate_document
        if (
            self.settings.codec == "native-capture-v2"
            and self.action == "capture"
            and (
                not callable(supervision_context) or not callable(retain_supervision) or not callable(validate_document)
            )
        ):
            raise ValueError("Bound supervision, readback and semantic validation required")

    @classmethod
    def _production_spawn(cls):
        args, kwargs = ForegroundGenerationWorker._production_spawn()
        args[2] = "isaaclab_arena_examples.agentic_environment_generation.web_api.native_scene_worker"
        args.extend(("--stage", cls.action))
        environment = kwargs["env"]
        assert isinstance(environment, dict), "Private worker environment required"
        for key in ("EXP_PATH", "ISAAC_PATH", "CARB_APP_PATH"):
            if key in os.environ:
                environment[key] = os.environ[key]
        environment["OMNICLIENT_HUB_MODE"] = "disabled"
        return args, kwargs

    def prepare(self, fence, contract, *, timeout_s):
        """Leave bounded cleanup time within the native operation's reservation."""
        limit = timeout_s
        if contract.schema_version == "3" and self.action == "capture":
            limit = min(timeout_s - 10, self.settings.max_runtime_seconds)
        if limit <= 0:
            raise ValueError("Native operation has no cleanup allowance")
        return super().prepare(fence, contract, timeout_s=limit)

    def _control_value(self, intent, contract, previous=None):
        from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
        from isaaclab_arena.agentic_environment_generation.workflow.control_protocol import SupervisionLease
        from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import identity

        assert callable(self.supervision_context), "Installed supervision source required"
        meta = self.supervision_context(intent, contract)
        if type(meta) is not dict:
            raise PermissionError("Selected private supervision metadata required")
        policy = contract.budget.control
        now = time.time()
        end = contract.budget.deadline_at(meta["admitted_at"])
        bounds = [
            now + policy.max_supervision_lease_seconds,
            meta["credential_expires_at"],
            meta["authority"].expires_at,
        ]
        if end is not None:
            bounds.append(end)
        if intent.reservation.runtime_allowance_seconds is not None:
            bounds.append(intent.released_at + intent.reservation.runtime_allowance_seconds)
        expires = min(bounds)
        if expires <= now:
            raise PermissionError("Current native workload/control authority exhausted")
        if previous is not None and expires <= previous.expires_at:
            return None
        lease = SupervisionLease(
            codec="supervision-lease-v1",
            fence=intent.worker_fence,
            scope_sha256=meta["scope"].body_sha256,
            instance=meta["instance"],
            principal=meta["principal"],
            contract_digest=contract_digest(contract),
            allocation_digest=identity(intent.reservation.model_dump(mode="json")),
            generation=1 if previous is None else previous.generation + 1,
            credential_generation=meta["credential_generation"],
            credential_expires_at=meta["credential_expires_at"],
            issued_at=now,
            expires_at=expires,
        )
        return dict(
            scope=meta["scope"].model_dump(mode="json"),
            lease=lease.model_dump(mode="json"),
            authority=meta["authority"].model_dump(mode="json"),
            admitted_at=meta["admitted_at"],
        )

    def _write_control(self, owned, value):
        raw = protocol.canonical(value, max_bytes=8192) + b"\n"
        fd = owned.process.stdin.fileno()
        end = min(owned.deadline, time.monotonic() + 5.0)
        with selectors.DefaultSelector() as selector:
            selector.register(fd, selectors.EVENT_WRITE)
            offset = 0
            while offset < len(raw):
                remaining = end - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError("Private control write deadline")
                try:
                    sent = os.write(fd, raw[offset:])
                except BlockingIOError:
                    continue
                if sent <= 0:
                    raise BrokenPipeError("Private control channel closed")
                offset += sent

    def _bind_supervision(self, owned, prepared, intent, contract):
        owned.supervision = protocol.owned_supervision(owned.request)
        owned.awaiting_ack = owned.supervision.retained_state()["last_acknowledgement"]
        owned.last_ack = None
        owned.supervision_acked = threading.Event()
        owned.supervision_stop = threading.Event()

        def acknowledge(ack):
            with owned.lock:
                if owned.awaiting_ack is None:
                    if ack == owned.last_ack:
                        return
                    raise PermissionError("Stale supervision acknowledgement")
                if ack != owned.awaiting_ack:
                    raise PermissionError("Exact private supervision acknowledgement required")
                owned.supervision.check_active()
                state = owned.supervision.retained_state()
                assert callable(self.retain_supervision), "Owned acknowledgement readback required"
                self.retain_supervision(intent.worker_fence, state)
                owned.last_ack, owned.awaiting_ack = ack, None
                owned.confirmed_supervision = state
                self._arm(owned, owned.supervision.cursor.monotonic_deadline)
                owned.supervision_acked.set()

        def retained(_):
            # This is a bounded natural-exit/cleanup allowance, not workload permission.
            with owned.lock:
                owned.supervision_stop.set()
                self._arm(owned, time.monotonic() + 60.0)

        owned.supervision_ack_handler = acknowledge
        owned.result_retained_handler = retained

        def renew():
            interval = contract.budget.control.heartbeat_seconds
            try:
                if not owned.supervision_acked.wait(interval):
                    raise TimeoutError("Initial supervision acknowledgement missing")
                while not owned.supervision_stop.wait(interval):
                    with owned.lock:
                        if owned.cleanup is not None or owned.process.poll() is not None:
                            return
                        owned.supervision.check_active()
                        if owned.awaiting_ack is not None:
                            raise TimeoutError("Supervision renewal acknowledgement missing")
                        value = self._control_value(intent, contract, owned.supervision.cursor.previous)
                        if value is None:
                            continue
                        from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
                            AuthorizationSnapshot,
                        )
                        from isaaclab_arena.agentic_environment_generation.workflow.control_protocol import (
                            SupervisionLease,
                        )

                        lease = SupervisionLease.model_validate_json(protocol.canonical(value["lease"]))
                        authority = AuthorizationSnapshot.model_validate_json(protocol.canonical(value["authority"]))
                        owned.awaiting_ack = owned.supervision.accept(lease, authority)
                        owned.supervision_acked.clear()
                        try:
                            self._write_control(
                                owned,
                                {"supervision_renewal": {"lease": value["lease"], "authority": value["authority"]}},
                            )
                        except BrokenPipeError:
                            # A retained-result/exit frame may already be queued. The
                            # last acknowledged deadline still contains missing results.
                            return
            except BaseException as exc:
                owned.supervision.revoke(exc)
                from contextlib import suppress

                with suppress(BaseException):
                    self.stop_owned(prepared, timeout_s=3)

        owned.supervision_thread = threading.Thread(target=renew, name="arena-native-supervision", daemon=True)

    def send(self, *args, **kwargs):
        raise ValueError("fixed native/numeric send port required; no model envelope")

    def _send_stage(
        self, prepared, intent, candidate, original, contract, *, protect, deadline, retained_observation=None
    ):
        owned = self._get(prepared)
        with owned.lock:
            if owned.attempted:
                raise RuntimeError("Private stage send already attempted")
            owned.attempted = True  # Includes failed validation and ambiguous writes.
            if (
                contract != owned.contract
                or intent.worker_registration != prepared.registration
                or intent.worker_fence != prepared.registration.fence
                or intent.action != self.action
                or owned.cleanup is not None
                or time.monotonic() >= owned.deadline
            ):
                raise ValueError("exact active prepared stage release required")
            selected = {}
            if contract.schema_version == "5":
                selected["validated_semantic_sha256"] = _validated_semantic_sha256(
                    candidate.scene_json, self.validate_document
                )
                if self.action == "capture":
                    control = self._control_value(intent, contract)
                    assert control is not None, "Initial owned supervision required"
                    selected["control"] = control
                    deadline = control["lease"]["expires_at"]
            packet = protocol.retain_request(
                self.artifacts.area,
                root=self.artifact_root,
                action=self.action,
                intent=intent,
                candidate=candidate,
                original=original,
                contract=contract,
                settings=self.settings,
                deadline=deadline,
                protect=protect,
                retained_observation=retained_observation,
                **selected,
            )
            # Open the actual configured path now, not just the caller's existing fd.
            with open_area(packet) as area:
                request = protocol.read_request(area, packet, protect=protect)
                if self.action == "assess":
                    protocol.numeric_evaluate(area, request, protect=protect)
            owned.packet, owned.request = packet, request
            mono = time.monotonic()
            if selected.get("control") is not None:
                self._bind_supervision(owned, prepared, intent, contract)
            else:
                self._arm(
                    owned,
                    min(
                        owned.deadline,
                        mono + deadline - time.time(),
                        owned.started + intent.reservation.runtime_allowance_seconds,
                    ),
                )
            raw = protocol._protected(packet, protect, max_bytes=512 * 1024 - 1) + b"\n"
            fd = owned.process.stdin.fileno()
            os.set_blocking(fd, False)
            with selectors.DefaultSelector() as selector:
                selector.register(fd, selectors.EVENT_WRITE)
                offset = 0
                while offset < len(raw):
                    remaining = owned.deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError("stage release write deadline")
                    try:
                        sent = os.write(fd, raw[offset:])
                    except BlockingIOError:
                        continue
                    if sent <= 0:
                        raise RuntimeError("stage release write incomplete")
                    offset += sent
            if selected.get("control") is None:
                owned.process.stdin.close()
            else:
                owned.supervision_thread.start()

    def _receive_stage(self, prepared, *, protect):
        owned = self._get(prepared)
        if owned.cleanup is not None:
            raise RuntimeError("stopped stage cannot produce an accepted result")
        primary_failure = None
        try:
            reference = ForegroundGenerationReceiver._read(self, owned)
            remaining = owned.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("stage exit deadline")
            # EOF or retained bytes alone are not an exit witness. Wait BEFORE
            # owned cleanup so termination caused by cleanup cannot look natural.
            returncode = owned.process.wait(timeout=remaining)
            if returncode != 0:
                raise SceneChildFailed(returncode)
            cleanup = self.stop_owned(prepared, timeout_s=3)
            if not self.cleanup_verified(prepared.registration, cleanup) or owned.process.returncode != 0:
                raise RuntimeError("verified natural exit and owned cleanup required")
            # Reopen only after the writer is gone; service still repeats evidence
            # verification after durable cleanup acknowledgement and GPU release.
            with open_area(owned.packet) as area:
                return protocol.read_result(area, owned.packet, owned.request, reference, protect=protect)
        except BaseException as exc:
            primary_failure = exc
            try:
                self.stop_owned(prepared, timeout_s=3)
            except BaseException as cleanup_error:
                owned.cleanup_failure = cleanup_error
                note = getattr(exc, "add_note", None)
                if callable(note):
                    note("Owned cleanup also failed: " + type(cleanup_error).__name__)
            if isinstance(exc, DiagnosticRetentionFailed):
                raise
            supervision = getattr(owned, "supervision", None)
            if supervision is not None and supervision.first_failure is not None:
                raise supervision.first_failure from exc
            code = owned.process.returncode
            if code is not None and code != 0 and not isinstance(exc, SceneChildFailed):
                raise SceneChildFailed(code) from exc
            raise
        finally:
            event = getattr(owned, "supervision_stop", None)
            if event is not None:
                event.set()
            try:
                self.stop_owned(prepared, timeout_s=3)
            except BaseException as cleanup_error:
                owned.cleanup_failure = cleanup_error
                if primary_failure is None:
                    raise

    def stop_owned(self, prepared, *, timeout_s):
        owned = self._get(prepared)
        event = getattr(owned, "supervision_stop", None)
        if event is not None:
            event.set()
        return super().stop_owned(prepared, timeout_s=timeout_s)


class ForegroundNativeCaptureWorker(_ForegroundStageWorker):
    """Callable native prepare/send_capture/receive_capture/stop/cleanup port."""

    action = "capture"

    def send_capture(self, prepared, intent, candidate, original, contract, *, protect, deadline):
        return self._send_stage(prepared, intent, candidate, original, contract, protect=protect, deadline=deadline)

    def receive_capture(self, prepared, *, protect):
        return self._receive_stage(prepared, protect=protect)


class ForegroundNumericAssessmentWorker(_ForegroundStageWorker):
    """Callable retained numeric evaluation port; never initializes Kit or a model."""

    action = "assess"

    def send_evaluate(
        self, prepared, intent, candidate, original, contract, *, retained_observation, protect, deadline
    ):
        return self._send_stage(
            prepared,
            intent,
            candidate,
            original,
            contract,
            protect=protect,
            deadline=deadline,
            retained_observation=retained_observation,
        )

    def receive_evaluate(self, prepared, *, protect):
        return self._receive_stage(prepared, protect=protect)
