# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit native/numeric transports for OwnedSceneStageAdapter; not enablement.

Compose with settings, SceneEvidenceArtifacts and its exact artifact_root. The
adapter must separately own native authorization/GPU lease, register the prepared
child and commit release before send. No installed entrypoint constructs these.
Inherited prepare/stop/cleanup use pinned kernel ownership and bounded deadlines.
"""

import os
import selectors
import time
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.workflow import native_worker_protocol as protocol
from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureSettings

from .foreground_generation import ForegroundGenerationReceiver, ForegroundGenerationWorker
from .web_api.native_scene_worker import open_area


class SceneChildFailed(RuntimeError):
    """Actual child exit failure, even when it managed to retain a receipt."""

    def __init__(self, returncode):
        super().__init__("Owned scene child failed; retained bytes are not successful execution")
        self.returncode = returncode


class _ForegroundStageWorker(ForegroundGenerationWorker):
    action = ""

    def __init__(self, *, settings, artifacts, artifact_root, **options):
        super().__init__(**options)
        self.settings = NativeCaptureSettings.model_validate_json(settings.canonical_bytes())
        self.artifacts, self.artifact_root = artifacts, Path(artifact_root).absolute()

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
            )
            # Open the actual configured path now, not just the caller's existing fd.
            with open_area(packet) as area:
                request = protocol.read_request(area, packet, protect=protect)
                if self.action == "assess":
                    protocol.numeric_evaluate(area, request, protect=protect)
            owned.packet, owned.request = packet, request
            mono = time.monotonic()
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
            owned.process.stdin.close()

    def _receive_stage(self, prepared, *, protect):
        owned = self._get(prepared)
        if owned.cleanup is not None:
            raise RuntimeError("stopped stage cannot produce an accepted result")
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
            self.stop_owned(prepared, timeout_s=3)
            code = owned.process.returncode
            if code is not None and code != 0 and not isinstance(exc, SceneChildFailed):
                raise SceneChildFailed(code) from exc
            raise
        finally:
            self.stop_owned(prepared, timeout_s=3)


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
