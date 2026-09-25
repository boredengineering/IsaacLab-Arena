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
import signal
import socket
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
from isaaclab_arena.agentic_environment_generation.workflow import native_worker_protocol as protocol
from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureProducer
from isaaclab_arena.agentic_environment_generation.workflow.native_resources import native_scratch_root
from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import SceneEvidenceArtifacts


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


def _validate_spec(candidate):
    # Schema/registry imports are deliberately after Kit initialization.
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    return ArenaEnvGraphSpec.model_validate_json(candidate.scene_json)


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


def execute(packet, *, protect, action, arm_deadline=None, on_retained=None):
    """Execute once in the child; optional timer seam is supplied by main, not JSON."""
    if protocol.packet_action(packet) != action:
        raise ValueError("fixed child stage mismatch")
    with open_area(packet) as area:
        request = protocol.read_request(area, packet, protect=protect)
        _verify_identity(request)
        # Sample monotonic first to avoid extending the wall deadline by conversion work.
        mono = time.monotonic()
        deadline = mono + request.deadline - time.time()
        if deadline <= mono:
            raise TimeoutError("expired stage release")
        if arm_deadline is not None:
            arm_deadline(deadline)

        def active():
            if time.monotonic() >= deadline:
                raise TimeoutError("stage deadline exhausted")

        active()
        if action == "assess":
            observation = protocol.numeric_evaluate(area, request, protect=protect)
            active()
            return protocol.retain_result(area, packet, observation.model_dump(mode="json"), protect=protect)
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
            spec = _validate_spec(request.candidate)
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
                charge_step=charge,
                check_active=active,
            )
            active()
            phase = "retain_capture"
            reference = protocol.capture_reference(result.receipt)
            protocol.reopen_capture(area, request, reference, protect=protect)
            receipt = protocol.retain_result(area, packet, reference, protect=protect)
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
            protocol._retain(area, "native-scene-failure", request.binding(), diagnostic, protect)
            raise
        finally:
            try:
                if app is not None:
                    app.close()
            except BaseException:
                if failure is None:
                    raise
                failure.add_note("Kit shutdown also failed")
        active()
        return receipt


def _arm_deadline(deadline):
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
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
    args = parser.parse_args(argv)
    published = False
    try:
        _parent_guard(args.parent_pid)
        line = sys.stdin.buffer.readline(512 * 1024 + 1)
        if len(line) > 512 * 1024 or not line.endswith(b"\n"):
            return 1
        packet = protocol.decode_packet(line)

        # No provider secret exists in this transport. Strict codecs and canonical
        # protection still apply in child; parent additionally uses current policy.
        def protect(value):
            protocol.canonical(value)

        logging.disable(sys.maxsize)
        # Isolate native C/C++ writes to fd 1 as well as Python stdout.
        with os.fdopen(os.dup(sys.stdout.fileno()), "w") as channel, open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())

            def publish(receipt):
                nonlocal published
                if published:
                    raise ValueError("duplicate native result frame")
                message = {"result": receipt}
                protocol._protected(message, protect)
                channel.write(json.dumps(message, allow_nan=False) + "\n")
                channel.flush()
                published = True

            receipt = execute(
                packet, protect=protect, action=args.stage, arm_deadline=_arm_deadline, on_retained=publish
            )
            if not published:
                publish(receipt)
        return 0
    except SystemExit as exc:
        if type(exc.code) is int and exc.code != 0:
            return exc.code
        return 0 if published and exc.code in (None, 0) else 1
    except BaseException:
        # Retained diagnostics are not acceptance. Never coerce a failed native
        # run/shutdown into success just because an artifact exists.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
