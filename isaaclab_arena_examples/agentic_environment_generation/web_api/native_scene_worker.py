# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Fixed released native/numeric child; no credentials, grants, models or controller.

The owned parent chooses --stage before prepare; JSON cannot choose code to run.
Kit is initialized only after validated release and exact physical registration.
Native artifacts precede Kit shutdown; even a valid receipt cannot hide nonzero exit.
"""

import argparse
import ctypes
import json
import logging
import os
import re
import select
import signal
import socket
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
from isaaclab_arena.agentic_environment_generation.workflow import native_worker_protocol as protocol
from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureProducer
from isaaclab_arena.agentic_environment_generation.workflow.native_resources import native_scratch_root
from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import SceneEvidenceArtifacts

from .scene_worker import retain_failure, safe_failure


class _RenewalChannel:
    """Receive fenced renewals independently of the simulator's main thread."""

    def __init__(self, request, *, emit):
        import threading

        if not callable(emit):
            raise PermissionError("Owned renewal channel required")
        self.request = request
        self.state = protocol.owned_supervision(request)
        self.emit = emit
        self._timer = None
        self._deadline_lock = threading.RLock()
        self._hard_deadline = None
        self.finished = threading.Event()
        self.fd = os.dup(sys.stdin.fileno())
        null = os.open(os.devnull, os.O_RDONLY)
        try:
            os.dup2(null, sys.stdin.fileno())
        finally:
            os.close(null)
        self._arm_lease()
        self.emit({"supervision_ack": self.state.retained_state()["last_acknowledgement"]})
        self.thread = threading.Thread(target=self._read, name="native-renewals", daemon=True)
        self.thread.start()

    def arm(self, deadline):
        """Use monotonic supervision; the separate parent can stop blocked Kit."""
        import threading

        with self._deadline_lock:
            if self._timer is not None:
                self._timer.cancel()
            self._hard_deadline = deadline

            def expired():
                with self._deadline_lock:
                    if self._hard_deadline == deadline and time.monotonic() >= deadline:
                        os.kill(os.getpid(), signal.SIGKILL)

            self._timer = threading.Timer(max(0.0, deadline - time.monotonic()), expired)
            self._timer.daemon = True
            self._timer.start()

    def _arm_lease(self):
        deadline = self.state.cursor.monotonic_deadline
        assert deadline is not None, "Accepted supervision deadline required"
        self.arm(deadline + 10.0)

    def _read(self):
        from isaaclab_arena.agentic_environment_generation.workflow.attempts import AuthorizationSnapshot
        from isaaclab_arena.agentic_environment_generation.workflow.control_protocol import SupervisionLease

        buffer = b""
        try:
            while not self.finished.is_set():
                self.state.check_active()
                if not select.select([self.fd], [], [], 0.5)[0]:
                    continue
                chunk = os.read(self.fd, 4096)
                if not chunk:
                    raise PermissionError("Owned parent renewal channel closed")
                buffer += chunk
                if len(buffer) > 8192:
                    raise ValueError("Renewal frame exceeds bound")
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    value = json.loads(line)
                    if type(value) is not dict or set(value) != {"supervision_renewal"}:
                        raise ValueError("Renewal frame required")
                    body = value["supervision_renewal"]
                    if type(body) is not dict or set(body) != {"lease", "authority"}:
                        raise ValueError("Bound renewal metadata required")
                    lease = SupervisionLease.model_validate_json(json.dumps(body["lease"]))
                    authority = AuthorizationSnapshot.model_validate_json(json.dumps(body["authority"]))
                    ack = self.state.accept(lease, authority)
                    if self.finished.is_set():
                        return
                    self._arm_lease()
                    self.emit({"supervision_ack": ack})
        except BaseException as error:
            if not self.finished.is_set():
                self.state.revoke(error)
                os.kill(os.getpid(), signal.SIGTERM)

    def finish(self):
        """End workload authority while permitting bounded independent cleanup."""
        if self.finished.is_set():
            return
        self.finished.set()
        self.thread.join(timeout=1)
        os.close(self.fd)
        self.arm(time.monotonic() + 60.0)


def open_area(packet):
    protocol.packet_action(packet)
    p = packet["payload"]
    return ArtifactArea.open(Path(p["root"]), store_id=p["store_id"], registry_id=p["registry_id"])


def _verify_identity(request):
    from .process_identity import process_identity

    actual = process_identity(os.getpid())
    reg = request.intent.worker_registration
    if (
        actual is None
        or any(
            getattr(reg, key) != value
            for key, value in dict(
                host=socket.gethostname(),
                pid=os.getpid(),
                pgid=actual["pgid"],
                sid=actual["sid"],
                boot=actual["boot_id"],
                start_ticks=int(actual["start_ticks"]),
            ).items()
        )
        or reg.pid != reg.pgid
        or reg.pid != reg.sid
    ):
        raise ValueError("exact released child identity required")


def _initialize_kit(settings):
    from isaaclab.app import AppLauncher

    return AppLauncher(headless=True, enable_cameras=bool(settings.camera_keys), device=settings.device).app


def _configure_native_tmp(scratch_root):
    """Keep native asset downloads in the operator-owned scratch namespace."""
    from isaaclab_arena.agentic_environment_generation.workflow.api.private_files import Directory

    with Directory(str(Path(scratch_root).parent / "native-tmp"), create=True) as directory:
        # tempfile may have cached its default before this released worker's
        # bootstrap. Set both interfaces; never reuse another user's /tmp USDs.
        os.environ["TMPDIR"] = directory.path
        tempfile.tempdir = directory.path
        return directory.path


def _validate_spec(request):
    # Schema/registry imports are deliberately after Kit initialization.
    import hashlib

    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    candidate = request.candidate
    if hashlib.sha256(candidate.scene_json.encode("utf-8")).hexdigest() != candidate.digest:
        raise ValueError("Canonical candidate identity changed")
    spec = ArenaEnvGraphSpec.model_validate_json(candidate.scene_json)
    if request.contract.schema_version == "5":
        actual = hashlib.sha256(protocol.canonical(spec.model_dump(mode="json"))).hexdigest()
        if actual != request.validated_semantic_sha256:
            raise ValueError("Validated semantic identity changed")
    return spec


def _diagnostic_message(cause):
    """Bound native error text without URL credentials, query tokens or input dumps."""
    from pydantic import ValidationError

    if isinstance(cause, ValidationError):
        return "Validation failed; see bounded validation locations"

    def public_url(match):
        try:
            value = urlsplit(match.group())
            host = value.hostname or "redacted"
            if value.port is not None:
                host += f":{value.port}"
            return urlunsplit((value.scheme, host, value.path, "", ""))
        except ValueError:
            return "[redacted-url]"

    message = str(cause)
    message = re.sub(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>]+", public_url, message)
    message = re.sub(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+", "[redacted-auth]", message)
    message = re.sub(
        r"(?i)\b(?:password|api[_-]?key|access[_-]?token|secret|authorization)\b[\"']?\s*[:=]\s*"
        r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)",
        "[redacted-field]",
        message,
    )
    return "".join(c if c.isprintable() or c == "\n" else " " for c in message)[:2048]


def _retain_causal_failure(area, request, phase, error, *, protect, cleanup=False):
    """Share the selected parent's first-write diagnostic identity, not workload authority."""
    if request.contract.schema_version == "5":
        registration = request.intent.worker_registration
        return retain_failure(
            area,
            run_id=request.intent.worker_fence.run_id,
            intent_id=request.intent.intent_id,
            contract_sha256=request.binding()["contract_digest"],
            fence=request.intent.worker_fence.model_dump(mode="json"),
            registration=registration.model_dump(mode="json"),
            phase=phase,
            error=error,
            protect=protect,
            cleanup=cleanup,
        )
    return None


def execute(packet, *, protect, action, arm_deadline=None, on_retained=None, on_protocol=None):
    """Execute once in the child; optional timer seam is supplied by main, not JSON."""
    from isaaclab_arena.agentic_environment_generation.workflow.control_protocol import legacy_monotonic_deadline

    if protocol.packet_action(packet) != action:
        raise ValueError("fixed child stage mismatch")
    with open_area(packet) as area:
        request = protocol.read_request(area, packet, protect=protect)
        _verify_identity(request)
        # Sample monotonic first to avoid extending the wall deadline by conversion work.
        renewable = request.contract.schema_version == "5" and action == "capture"
        renewals = _RenewalChannel(request, emit=on_protocol) if renewable else None
        deadline = None
        if renewals is None:
            mono = time.monotonic()
            deadline = legacy_monotonic_deadline(request.deadline, wall_now=time.time(), monotonic_now=mono)
            if arm_deadline is not None:
                arm_deadline(deadline)

        previous_term_handler = None
        if renewals is not None:
            previous_term_handler = signal.getsignal(signal.SIGTERM)

            def stopped(signum, frame):
                raise renewals.state.first_failure or PermissionError("Owned execution stopped")

            signal.signal(signal.SIGTERM, stopped)

        def active():
            if renewals is not None:
                return renewals.state.check_active()
            assert deadline is not None, "Transport deadline required"
            if time.monotonic() >= deadline:
                raise TimeoutError("stage deadline exhausted")
            return None

        active()
        if action == "assess":
            observation = protocol.numeric_evaluate(area, request, protect=protect)
            active()
            return protocol.retain_result(area, packet, observation.model_dump(mode="json"), protect=protect)
        capture_options = {}
        producer = NativeCaptureProducer(
            settings=request.settings,
            artifacts=SceneEvidenceArtifacts(area),
            protect=protect,
            output_root=native_scratch_root(packet["payload"]["root"]),
        )
        producer.admit(request.contract)
        app = None
        failure = None
        temporary_root = None
        phase = "configure_native_tmp"
        try:
            temporary_root = _configure_native_tmp(producer.output_root)
            phase = "initialize_kit"
            app = _initialize_kit(request.settings)
            active()
            phase = "validate_spec"
            spec = _validate_spec(request)
            if renewals is not None:
                from isaaclab_arena.agentic_environment_generation.workflow.native_capture import IsaacCaptureAdapter

                adapter = IsaacCaptureAdapter(
                    request.settings, request.contract, spec, request.candidate, request.original
                )
                scope, _, _, _ = protocol.control_values(request)
                capture_options = dict(
                    sample_state=adapter.sample_state,
                    build_environment=adapter.build_environment,
                    read_reset_count=adapter.read_reset_count,
                    read_frame_clock=adapter.read_frame_clock,
                    acquire_images=adapter.acquire_images,
                    read_diagnostics=adapter.retained_diagnostics,
                    supervision=renewals.state,
                    control_scope=scope,
                    control_instance=renewals.state.cursor.expected[1],
                    control_principal=renewals.state.cursor.expected[2],
                )
            charged = 0

            def charge(step):
                nonlocal charged
                active()
                if type(step) is not int or step != charged + 1 or step > request.intent.reservation.steps:
                    raise ValueError("native step reservation exhausted")
                charged = step

            phase = "native_capture"
            result = producer(
                spec=spec,
                intent=request.intent,
                candidate=request.candidate,
                contract=request.contract,
                worker_initialized=True,
                kit_cameras_enabled=bool(request.settings.camera_keys),
                deadline=deadline,
                **capture_options,
                charge_step=charge,
                check_active=active,
            )
            active()
            phase = "retain_capture"
            reference = protocol.capture_reference(result.receipt)
            protocol.reopen_capture(area, request, reference, protect=protect)
            receipt = protocol.retain_result(area, packet, reference, protect=protect)
            if renewals is not None:
                renewals.finish()
            if on_retained is not None:
                # Kit may terminate this interpreter during close. Publish the
                # exact retained handle first; the parent still requires zero
                # natural exit AND verified physical cleanup before adoption.
                on_retained(receipt)
        except BaseException as exc:
            failure = exc
            # Retain bounded causal diagnostics BEFORE Kit close can terminate
            # the interpreter. Never include locals or validation input dumps.
            cause = exc.__cause__ if exc.__cause__ is not None else exc
            frames, cursor = [], cause.__traceback__
            while cursor is not None and len(frames) < 24:
                frames.append(
                    dict(
                        file=Path(cursor.tb_frame.f_code.co_filename).name,
                        function=cursor.tb_frame.f_code.co_name,
                        line=cursor.tb_lineno,
                    )
                )
                cursor = cursor.tb_next
            diagnostic = dict(
                outcome="failed",
                phase=phase,
                temporary_root=temporary_root,
                exception_type=type(cause).__name__,
                exception_message=_diagnostic_message(cause),
                wrapper_type=type(exc).__name__,
                frames=frames,
            )
            from pydantic import ValidationError

            if isinstance(cause, ValidationError):
                diagnostic["validation"] = [
                    dict(location=list(item["loc"]), type=item["type"])
                    for item in cause.errors(include_input=False, include_context=False, include_url=False)[:24]
                ]
            try:
                _retain_causal_failure(area, request, phase, exc, protect=protect)
                protocol._retain(area, "native-scene-failure", request.binding(), diagnostic, protect)
            except BaseException as retention_error:
                from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import (
                    DiagnosticRetentionFailed,
                )

                if on_protocol is not None:
                    on_protocol({"diagnostic_retention_failed": safe_failure(phase, exc)})
                raise DiagnosticRetentionFailed(safe_failure(phase, exc)) from retention_error
            raise
        finally:
            try:
                if renewals is not None:
                    renewals.finish()
                    signal.signal(signal.SIGTERM, previous_term_handler)
                if app is not None:
                    app.close()
            except BaseException as cleanup_error:
                if not (isinstance(cleanup_error, SystemExit) and cleanup_error.code in (None, 0) and failure is None):
                    with suppress(BaseException):
                        _retain_causal_failure(area, request, "cleanup", cleanup_error, protect=protect, cleanup=True)
                if failure is None:
                    raise
                note = getattr(failure, "add_note", None)
                if callable(note):
                    note("Kit shutdown also failed")
        if renewals is None:
            active()
        return receipt


def _arm_deadline(deadline):
    import threading

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
    elif signal.getsignal(signal.SIGALRM) != signal.SIG_DFL:
        raise RuntimeError("Unexpected kernel supervision handler")
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("stage deadline exhausted before arming")
    signal.setitimer(signal.ITIMER_REAL, seconds)


def _parent_guard(parent_pid):
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent_pid:
        raise ValueError("owned parent unavailable")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--stage", choices=("capture", "assess"), required=True)
    published = False
    reported_failure = False
    packet = None
    phase = "child_entry"

    # No provider secret exists in this transport. Strict codecs and canonical
    # protection still apply in child; parent additionally uses current policy.
    def protect(value):
        protocol.canonical(value)

    logging.disable(sys.maxsize)
    # Establish the existing framed channel before any fallible child entry step.
    # Isolate native C/C++ writes to fd 1 as well as Python stdout.
    with os.fdopen(os.dup(sys.stdout.fileno()), "w") as channel, open(os.devnull, "w") as sink:
        os.dup2(sink.fileno(), sys.stdout.fileno())
        import threading

        output_lock = threading.RLock()

        def emit(message):
            nonlocal reported_failure
            protocol._protected(message, protect)
            with output_lock:
                channel.write(json.dumps(message, allow_nan=False) + "\n")
                channel.flush()
                if "diagnostic_retention_failed" in message:
                    reported_failure = True

        def publish(receipt):
            nonlocal published
            if published:
                raise ValueError("duplicate native result frame")
            emit({"result": receipt})
            published = True

        def report(error):
            if reported_failure:
                return
            try:
                # No artifact may be bound to an unvalidated or foreign packet.
                with open_area(packet) as area:
                    request = protocol.read_request(area, packet, protect=protect, for_execution=False)
                    _verify_identity(request)
                    _retain_causal_failure(area, request, phase, error, protect=protect)
            except BaseException:
                with suppress(BaseException):
                    emit({"diagnostic_retention_failed": safe_failure(phase, error)})

        try:
            args = parser.parse_args(argv)
            _parent_guard(args.parent_pid)
            line = sys.stdin.buffer.readline(512 * 1024 + 1)
            if len(line) > 512 * 1024 or not line.endswith(b"\n"):
                raise ValueError("Bounded complete native packet required")
            packet = protocol.decode_packet(line)
            phase = "child_execute"
            receipt = execute(
                packet,
                protect=protect,
                action=args.stage,
                arm_deadline=_arm_deadline,
                on_retained=publish,
                on_protocol=emit,
            )
            if not published:
                publish(receipt)
            return 0
        except SystemExit as exc:
            if published and exc.code in (None, 0):
                return 0
            report(exc)
            return exc.code if type(exc.code) is int and exc.code != 0 else 1
        except BaseException as exc:
            report(exc)
            # Retained diagnostics are not acceptance. Never coerce a failed
            # run/shutdown into success just because an artifact exists.
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
