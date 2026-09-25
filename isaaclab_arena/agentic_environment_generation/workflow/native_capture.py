# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Frozen capture mechanics for an already initialized, released native worker.

No Kit startup, resource acquisition, model/policy construction or authorization
lives here. The execution owner retains responsibility for those boundaries and
for hard process deadlines/cleanup. Hashes establish integrity, not calibration.
"""

import hashlib
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, model_serializer, model_validator

from .contracts import Count, Criterion, Duration, FrozenModel, Identifier, ObservationWindow, ProfileReference
from .scene_evidence_artifacts import canonical
from .scene_observation import EVALUATOR_VERSION, SUPPORT_THRESHOLDS, admit_criterion


class NativeSubject(FrozenModel):
    subject_id: Identifier
    scene_name: Identifier
    prim_path: Annotated[str, Field(strict=True, min_length=1, max_length=512)]


class NativeContact(FrozenModel):
    subject_id: Identifier
    destination_id: Identifier
    sensor_name: Identifier


class NativeImageTransform(FrozenModel):
    """Evaluator-only RGB uint8 nearest resize; never mutate policy observations."""

    codec: Literal["rgb8-nearest-png-v1"] = "rgb8-nearest-png-v1"
    max_edge: Annotated[int, Field(strict=True, ge=1, le=128)] = 128
    max_source_pixels: Annotated[int, Field(strict=True, ge=1, le=16777216)] = 4194304
    max_frame_bytes: Literal[131072] = 131072


class NativeCaptureSettings(FrozenModel):
    """One executable payload shared by immutable runtime and capture references.

    Evaluator v1's fixed constants are explicitly pinned, NOT calibrated. Unknown
    contact expansion and other embodiments/hold adapters remain unsupported.
    """

    codec: Literal["native-capture-v1"] = "native-capture-v1"
    runtime_profile_id: Identifier
    capture_profile_id: Identifier
    embodiment: Literal["droid_abs_joint_pos"] = "droid_abs_joint_pos"
    seed: Count
    placement_seed: Count | None = None
    device: Annotated[str, Field(strict=True, pattern=r"^cuda:[0-9]+$")] = "cuda:0"
    env_spacing: Duration = 30.0
    solve_relations: Annotated[bool, Field(strict=True)] = True
    resolve_on_reset: Annotated[bool, Field(strict=True)] | None = None
    timestep_seconds: Duration
    decimation: Annotated[int, Field(strict=True, ge=1, le=1000000)]
    settle_steps: Annotated[int, Field(strict=True, ge=1, le=256)]
    settle_consecutive_steps: Annotated[int, Field(strict=True, ge=1, le=256)]
    settle_linear_m_per_s: Annotated[float, Field(strict=True, ge=0.001, le=0.001)] = 0.001
    settle_angular_rad_per_s: Duration
    window: ObservationWindow
    subjects: Annotated[tuple[NativeSubject, ...], Field(min_length=1, max_length=16)]
    contacts: Annotated[tuple[NativeContact, ...], Field(max_length=16)] = ()
    camera_keys: Annotated[tuple[str, ...], Field(max_length=3)] = ()
    evidence_only: Annotated[bool, Field(strict=True)] = False
    """Retain ungraded cameras for an explicit model-free validation request."""
    image_transform: NativeImageTransform = NativeImageTransform()
    criteria: Annotated[tuple[Criterion, ...], Field(min_length=1, max_length=32)]
    evaluator_version: Literal["1"] = "1"
    evaluator_linear_m_per_s: Annotated[float, Field(strict=True, ge=0.01, le=0.01)] = 0.01
    evaluator_angular_rad_per_s: Annotated[float, Field(strict=True, ge=0.05, le=0.05)] = 0.05
    evaluator_xy_m: Annotated[float, Field(strict=True, ge=0.05, le=0.05)] = 0.05
    coordinate_frame: Literal["world"] = "world"
    position_mapping: Literal["root-world-with-env-origin-v1"] = "root-world-with-env-origin-v1"
    max_runtime_seconds: Duration
    max_payload_bytes: Literal[2097152] = 2097152

    @model_validator(mode="after")
    def supported(self):
        if self.settle_consecutive_steps > self.settle_steps or self.window.start_step != self.settle_steps:
            raise ValueError("fixed settle allocation must end at absolute window start")
        count = self.window.end_step - self.window.start_step + 1
        if not (1 if self.evidence_only else 2) <= count <= 256:
            raise ValueError("unsupported capture window")
        if len(set(self.camera_keys)) != len(self.camera_keys) or not set(self.camera_keys) <= {
            "external_camera_rgb",
            "external_camera_2_rgb",
            "wrist_camera_rgb",
        }:
            raise ValueError("unsupported RGB observation keys")
        if count * len(self.camera_keys) > 16:
            raise ValueError("image coverage bound")
        # Reserve space for raw state/settle metadata as well as base64 PNGs. The
        # encoder's 128px ceiling is below the independent 128KiB/frame ceiling.
        image_bound = count * len(self.camera_keys) * (4 * (3 * self.image_transform.max_edge**2 + 4096) // 3 + 4)
        state_bound = 2048 * len(self.subjects) * (self.settle_steps + count)
        if image_bound + state_bound + len(self.canonical_bytes()) + 65536 > self.max_payload_bytes:
            raise ValueError("whole payload bound")
        names = {s.subject_id: s.scene_name for s in self.subjects}
        if len(names) != len(self.subjects) or len(set(names.values())) != len(names):
            raise ValueError("unique subject mapping required")
        criteria = tuple(admit_criterion(c) for c in self.criteria)
        if len({c.criterion_id for c in criteria}) != len(criteria):
            raise ValueError("unique criteria required")
        if {s for c in criteria for s in c.subjects} != set(names):
            raise ValueError("exact subject mapping required")
        if any(c.observation_window != self.window for c in criteria):
            raise ValueError("exact absolute criterion window required")
        visual = [c for c in criteria if c.kind == "visual"]
        if self.evidence_only:
            if visual or any(c.kind != "runtime" for c in criteria):
                raise ValueError("Evidence-only cameras cannot request visual assessment")
        elif len(visual) > 1 or set(self.camera_keys) != {k for c in visual for k in c.coordinate_frames}:
            raise ValueError("exact single visual criterion camera coverage required")
        pairs = {(c.subject_id, c.destination_id) for c in self.contacts}
        required = {c.subjects for c in criteria if c.evidence_producer == "scene.filtered-support"}
        if pairs != required or len(pairs) != len(self.contacts):
            raise ValueError("exact explicit contact sensor mappings required")
        for subject in self.subjects:
            if not subject.prim_path.startswith(("/", "{ENV_REGEX_NS}/")):
                raise ValueError("absolute prim identity required")
            if any(subject.subject_id in pair for pair in pairs) and any(ch in subject.prim_path for ch in "{}*[]"):
                raise ValueError("templated contact mapping unsupported")
        self.check_evaluator()
        return self

    @model_serializer(mode="wrap")
    def compatible_bytes(self, serialize):
        value = serialize(self)
        if not self.evidence_only:
            value.pop("evidence_only", None)
        return value

    def check_evaluator(self):
        """Refuse changed evaluator defaults instead of reinterpreting old bytes."""
        if EVALUATOR_VERSION != self.evaluator_version or dict(SUPPORT_THRESHOLDS) != {
            "linear_m_per_s": self.evaluator_linear_m_per_s,
            "angular_rad_per_s": self.evaluator_angular_rad_per_s,
            "xy_m": self.evaluator_xy_m,
        }:
            raise ValueError("frozen evaluator revision mismatch")

    def canonical_bytes(self):
        return canonical(self.model_dump(mode="json"))

    def digest(self):
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def runtime_reference(self):
        return ProfileReference(profile_id=self.runtime_profile_id, settings_sha256=self.digest())

    def capture_reference(self):
        return ProfileReference(profile_id=self.capture_profile_id, settings_sha256=self.digest())

    def builder_config(self):
        from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg

        return ArenaEnvBuilderCfg(
            num_envs=1,
            seed=self.seed,
            placement_seed=self.placement_seed,
            device=self.device,
            env_spacing=self.env_spacing,
            solve_relations=self.solve_relations,
            resolve_on_reset=self.resolve_on_reset,
            disable_fabric=False,
            mimic=False,
            presets=None,
            language_instruction=None,
        )

    def settle_settings(self):
        from .native_realization import NativeSettleSettings

        return NativeSettleSettings(
            settle_steps=self.settle_steps,
            subjects=tuple(s.scene_name for s in self.subjects),
            angular_velocity_limit=self.settle_angular_rad_per_s,
            consecutive_steps=self.settle_consecutive_steps,
            camera_names=self.camera_keys,
        )


def encode_native_rgb(value, settings):
    """Encode one singleton uint8 RGB observation with the frozen evaluator transform."""
    import io
    import numpy as np

    from PIL import Image

    shape = tuple(value.shape)
    if len(shape) != 4 or shape[0] != 1 or shape[-1] != 3 or not 0 < shape[1] * shape[2] <= settings.max_source_pixels:
        raise ValueError("bounded singleton RGB observation required")
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    pixels = np.asarray(value)
    if pixels.dtype != np.uint8:
        raise ValueError("RGB uint8 required; no implicit float scaling")
    image = Image.fromarray(pixels[0])
    width, height = image.size
    edge = max(width, height)
    if edge > settings.max_edge:
        image = image.resize(
            (
                max(1, width * settings.max_edge // edge),
                max(1, height * settings.max_edge // edge),
            ),
            resample=Image.Resampling.NEAREST,
        )
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=False, compress_level=6)
    raw = stream.getvalue()
    if not 0 < len(raw) <= settings.max_frame_bytes:
        raise ValueError("encoded image bound")
    return raw


@dataclass(frozen=True)
class NativeCaptureResult:
    receipt: object
    observation: object


class NativeCaptureFailed(RuntimeError):
    """Failed native effect; optional diagnostic receipt is never a retry grant."""

    def __init__(self, receipt=None):
        super().__init__("Native capture failed; diagnostic receipt is not acceptance")
        self.receipt = receipt
        self.cleanup_failed = False


class NativeCaptureProducer:
    """Child-only capture port; never a worker launcher or workflow coordinator.

    Call with an already validated graph spec inside the registered released
    worker, AFTER the owner initialized Kit and acquired native resources. The
    booleans/intent are trusted handoff metadata, not a sandbox or permission.
    Accounting and cancellation callbacks are check-only trusted ports. This
    adapter constructs no policy/model and closes only its environment, not Kit.
    """

    def __init__(self, *, settings, artifacts, protect, output_root):
        from pathlib import Path

        self.settings = NativeCaptureSettings.model_validate_json(settings.canonical_bytes())
        self.artifacts, self.protect = artifacts, protect
        self.output_root = Path(output_root)
        self._used = set()

    def admit(self, contract):
        """Bind actual executable bytes to both frozen profile references before effects."""
        from .contracts import WorkflowContract

        contract = WorkflowContract.model_validate_json(contract.model_dump_json())
        s = self.settings
        s.check_evaluator()
        if s.evidence_only and contract.schema_version != "3":
            raise ValueError("Evidence-only capture requires explicit native-only admission")
        if (
            contract.execution.runtime != s.runtime_reference()
            or contract.execution.capture != s.capture_reference()
            or (
                contract.execution.seed,
                contract.execution.timestep_seconds,
                contract.execution.decimation,
            )
            != (s.seed, s.timestep_seconds, s.decimation)
            or tuple(c for c in contract.criteria if c.kind != "policy") != s.criteria
        ):
            raise ValueError("native settings/profile/criteria binding mismatch")
        if (
            not contract.effects.allow_runtime
            or contract.budget.max_realizations < 1
            or contract.budget.max_observations < 1
            or contract.budget.max_steps < s.window.end_step
            or s.max_runtime_seconds
            > min(
                contract.budget.per_operation_timeout_seconds,
                contract.budget.max_runtime_seconds,
                contract.budget.total_deadline_seconds,
            )
        ):
            raise ValueError("native capture budget mismatch")
        return s.criteria

    def replay(self, receipt, *, contract, candidate):
        """Reopen exact bytes and reevaluate numeric criteria, without native effects."""
        from .contracts import contract_digest
        from .evidence import CandidateBinding
        from .scene_loop import Observation, profile_digest
        from .scene_observation import evaluate_measurement

        criteria = self.admit(contract)
        binding = CandidateBinding(
            candidate_digest=candidate.digest,
            contract_digest=contract_digest(contract),
            profile_digest=profile_digest(contract),
        )
        if receipt.candidate != binding:
            raise ValueError("native candidate binding mismatch")
        payload = self.artifacts.verified_payload(receipt, protect=self.protect)
        if (
            payload.get("provenance") != "native-unverified"
            or payload.get("settings_sha256") != self.settings.digest()
            or canonical(payload.get("settings")) != self.settings.canonical_bytes()
            or payload.get("diagnostics", {}).get("status") != "complete"
        ):
            raise ValueError("incomplete or mismatched native capture receipt")
        if contract.schema_version == "3":
            import math

            report = payload["diagnostics"].get("settle", {})
            samples = report.get("samples", [])
            s = self.settings
            if (
                report.get("all_objects_settled") is not True
                or report.get("executed_steps") != s.settle_steps
                or report.get("linear_speed_limit") != s.settle_linear_m_per_s
                or report.get("angular_speed_limit") != s.settle_angular_rad_per_s
                or len(samples) != s.settle_steps
                or [sample.get("step") for sample in samples] != list(range(1, s.settle_steps + 1))
            ):
                raise ValueError("Exact native settling report required")
            for sample in samples[-s.settle_consecutive_steps :]:
                if set(sample["subjects"]) != {subject.scene_name for subject in s.subjects}:
                    raise ValueError("Settling subject coverage differs")
                for value in sample["subjects"].values():
                    for field, limit in (
                        ("linear_velocity_w", s.settle_linear_m_per_s),
                        ("angular_velocity_w", s.settle_angular_rad_per_s),
                    ):
                        vector = value[field]
                        if len(vector) != 3 or any(type(v) not in (float, int) or not math.isfinite(v) for v in vector):
                            raise ValueError("Finite native velocity required")
                        if not math.hypot(*vector) < limit:
                            raise ValueError("Final native settling window rejected")
            expected_frames = {
                (step, camera) for step in range(s.window.start_step, s.window.end_step + 1) for camera in s.camera_keys
            }
            if {(frame["step"], frame["camera"]) for frame in payload["frames"]} != expected_frames:
                raise ValueError("Exact same-cohort native cameras required")
        evidence = tuple(
            evaluate_measurement(
                c,
                binding,
                receipt.cohort,
                self.artifacts,
                receipt,
                protect=self.protect,
            )
            for c in criteria
            if c.kind != "visual"
        )
        return Observation(
            cohort=receipt.cohort,
            evidence=evidence,
            verified_manifest_digests=(receipt.manifest_digest,),
        )

    def _check_spec(self, spec, candidate, kit_cameras_enabled):
        """Check the exact validated candidate and graph camera intent without construction."""
        from .repairs import _scene_json

        s = self.settings
        scene = spec.to_dict()
        if hashlib.sha256(candidate.scene_json.encode()).hexdigest() != candidate.digest:
            raise ValueError("validated spec must match exact retained candidate")
        if candidate.scene_json not in (_scene_json(scene), _scene_json(spec.model_dump(mode="json"))):
            if not s.evidence_only:
                raise ValueError("validated spec must match exact retained candidate")
            from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

            # The retained input remains byte-exact. Schema defaults and typed
            # values can change its serialization; revalidate that exact input
            # instead of treating the normalized representation as a new scene.
            if type(spec) is not ArenaEnvGraphSpec:
                raise ValueError("exact native graph schema required")
            rebound = ArenaEnvGraphSpec.model_validate_json(candidate.scene_json)
            if rebound.model_dump(mode="json") != spec.model_dump(mode="json") or rebound.to_dict() != scene:
                raise ValueError("validated spec differs from exact retained candidate")
        if scene.get("embodiment", {}).get("registry_name") != s.embodiment:
            raise ValueError("unsupported hold embodiment")
        self._check_subject_mapping(scene)
        pending = [scene]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                if "external_yaml" in node:
                    raise ValueError("external_yaml_refused")
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
        graph_cameras = spec.embodiment.params.get("enable_cameras", bool(s.camera_keys))
        if (
            type(graph_cameras) is not bool
            or (s.camera_keys and not graph_cameras)
            or (graph_cameras and not kit_cameras_enabled)
        ):
            raise ValueError("graph/Kit camera conflict")

    def _check_subject_mapping(self, scene):
        """Bind measured spawnable objects using the graph converter's naming rules.

        Background/subasset and arbitrary object-reference measurements require
        their own mapping adapter; they are not inferred from a matching prim name.
        """
        objects = scene.get("objects", [])
        by_id, names, paths = {}, [], []
        for node in objects:
            params = node.get("params", {})
            name = params.get("instance_name", node["id"])
            if type(name) is not str or not name:
                raise ValueError("unsupported native object mapping")
            prim = params.get("prim_path") or "{ENV_REGEX_NS}/" + name
            by_id[node["id"]] = (name, prim)
            names.append(name)
            paths.append(prim)
        background = scene.get("background", {})
        background_name = background.get("params", {}).get("instance_name") or background.get("registry_name")
        reserved_names = {background_name, "light"}
        reserved_names.update(
            ref.get("params", {}).get("name", ref["id"]) for ref in scene.get("object_references") or []
        )
        if len(by_id) != len(objects) or len(set(names)) != len(names) or len(set(paths)) != len(paths):
            raise ValueError("ambiguous native object mapping")
        for subject in self.settings.subjects:
            if (
                by_id.get(subject.subject_id) != (subject.scene_name, subject.prim_path)
                or subject.scene_name in reserved_names
            ):
                raise ValueError("native subject graph/runtime mapping mismatch")

    def __call__(
        self,
        *,
        spec,
        intent,
        candidate,
        contract,
        worker_initialized,
        kit_cameras_enabled,
        deadline,
        charge_step,
        check_active,
    ):
        """Capture within the original absolute monotonic deadline and step reservation."""
        import math
        import time

        from isaaclab_arena.agentic_environment_generation.trajectory_capture import capture_trajectory

        from . import native_realization
        from .contracts import contract_digest
        from .evidence import CandidateBinding, EvidenceCohort
        from .scene_loop import identity, profile_digest
        from .scene_observation import ObservationRecorder, make_native_sampler

        self.admit(contract)
        s = self.settings
        if (
            worker_initialized is not True
            or type(kit_cameras_enabled) is not bool
            or (s.camera_keys and not kit_cameras_enabled)
        ):
            raise ValueError("initialized native worker and Kit camera activation required")
        if (
            intent.codec_version != 2
            or intent.action != "capture"
            or intent.status != "released"
            or intent.released_at is None
            or intent.candidate_id != candidate.candidate_id
            or intent.worker_fence is None
            or intent.worker_registration is None
            or intent.worker_registration.fence != intent.worker_fence
            or intent.worker_fence.intent_id != intent.intent_id
            or intent.worker_fence.run_id != candidate.run_id
            or intent.worker_cleanup is not None
        ):
            raise ValueError("exact registered released capture intent required")
        reservation = intent.reservation
        if (
            reservation.realizations != 1
            or reservation.observations != 1
            or reservation.steps < s.window.end_step
            or reservation.runtime_allowance_seconds < s.max_runtime_seconds
            or any((
                reservation.model_calls,
                reservation.model_tokens,
                reservation.cost_ceiling_usd,
                reservation.candidates,
                reservation.revisions,
            ))
        ):
            raise ValueError("bounded model-free capture reservation required")
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError("original monotonic deadline required")
        stop_at = min(deadline, time.monotonic() + s.max_runtime_seconds)

        def active():
            check_active()
            if time.monotonic() >= stop_at:
                raise TimeoutError("native capture deadline exhausted")

        active()
        self._check_spec(spec, candidate, kit_cameras_enabled)
        if intent.intent_id in self._used:
            raise ValueError("released native capture cannot be repeated")
        self._used.add(intent.intent_id)
        tag = identity(intent.intent_id, candidate.candidate_id)
        out_dir = self.output_root / tag
        out_dir.mkdir(parents=True, exist_ok=False)  # Persist a local no-reexecution sentinel before construction.
        cohort = EvidenceCohort(
            realization_id=tag,
            reset_id=identity(tag, "reset"),
            environment_id="native-env0",
            window_id=identity(tag, "window", s.window.model_dump(), s.digest()),
            frame_id="world",
            contract_digest=contract_digest(contract),
            profile_digest=profile_digest(contract),
        )
        binding = CandidateBinding(
            candidate_digest=candidate.digest,
            contract_digest=cohort.contract_digest,
            profile_digest=cohort.profile_digest,
        )
        native_sampler = make_native_sampler(
            s.criteria,
            subject_names={v.subject_id: v.scene_name for v in s.subjects},
            contact_sensors={(v.subject_id, v.destination_id): v.sensor_name for v in s.contacts},
        )

        def sample(env, step):
            active()
            value = native_sampler(env, step)
            for subject in s.subjects:
                expected_prim = subject.prim_path
                if "{ENV_REGEX_NS}" in expected_prim:
                    expected_prim = expected_prim.format(ENV_REGEX_NS=env.unwrapped.scene.env_regex_ns)
                if value["subjects"][subject.subject_id]["prim_path"] != expected_prim:
                    raise ValueError("native subject prim identity mismatch")
            return value

        recorder = ObservationRecorder(sample, provenance="native-unverified")
        diagnostics = {"status": "incomplete", "charged_steps": 0}
        frames = []
        visual = next((c for c in s.criteria if c.kind == "visual"), None)

        def charge(step):
            active()
            if step != diagnostics["charged_steps"] + 1 or step > s.window.end_step:
                raise ValueError("absolute control step bound")
            charge_step(step)
            diagnostics["charged_steps"] = step

        def save_frame(value, path):
            active()
            raw = encode_native_rgb(value, s.image_transform)
            with path.open("xb") as stream:
                stream.write(raw)
            step, camera = path.stem[5:].split("_", 1)
            frames.append((int(step), camera, raw))

        retention_attempted = False

        def retain():
            import base64

            nonlocal retention_attempted
            paired = {(f["step"], f["camera"]) for f in recorder.frames}
            sampled = {v["step"] for v in recorder.samples}
            unpaired = []
            for step, camera, raw in frames:
                if (step, camera) in paired:
                    continue
                if step in sampled:
                    recorder.add_frame(
                        camera=camera,
                        step=step,
                        subject_ids=visual.subjects if visual is not None else tuple(v.subject_id for v in s.subjects),
                        image_bytes=raw,
                    )
                else:
                    # An image may precede a failed initial sample. Keep its exact
                    # bytes diagnostically, never assert synchronized coverage.
                    unpaired.append({
                        "step": step,
                        "camera": camera,
                        "encoding": "base64",
                        "bytes": base64.b64encode(raw).decode("ascii"),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                    })
            diagnostics["unpaired_frames"] = unpaired
            payload = recorder.payload() | {
                "settings": s.model_dump(mode="json"),
                "settings_sha256": s.digest(),
                "diagnostics": diagnostics,
            }
            retention_attempted = True
            return self.artifacts.write(binding, cohort, payload, protect=self.protect)

        env, receipt, failure = None, None, None
        try:
            env = native_realization.build_native_environment(
                spec,
                builder_cfg=s.builder_config(),
                enable_cameras=bool(s.camera_keys),
                kit_cameras_enabled=kit_cameras_enabled,
            )
            active()
            base = env.unwrapped
            if base.num_envs != 1 or base.cfg.sim.dt != s.timestep_seconds or base.cfg.decimation != s.decimation:
                raise ValueError("realized runtime settings mismatch")
            initialized = native_realization.initialize_and_settle(
                env,
                settings=s.settle_settings(),
                charge_step=charge,
                hold_action_factory=native_realization.build_droid_posture_hold,
            )
            diagnostics["settle"] = initialized.report

            class Hold:
                def get_action(self, env, observation):
                    charge(diagnostics["charged_steps"] + 1)
                    return initialized.hold_action

            captured = capture_trajectory(
                env,
                Hold(),
                out_dir=out_dir,
                num_steps=s.window.end_step - s.window.start_step,
                frame_interval=1,
                camera_names=s.camera_keys,
                save_frame=save_frame,
                sample_state=recorder,
                initial_observation=initialized.observation,
                step_offset=initialized.step_offset,
                reset_policy=False,
            )
            diagnostics["capture"] = {k: v for k, v in captured.items() if k != "frames"}
            active()
            diagnostics["status"] = "complete"
            receipt = retain()
            observation = self.replay(receipt, contract=contract, candidate=candidate)
        except BaseException as exc:
            failure = NativeCaptureFailed(receipt)
            if receipt is None and not retention_attempted:
                diagnostics.update(status="failed", failure_type=type(exc).__name__)
                if isinstance(exc, native_realization.SceneSettleRejected):
                    diagnostics["settle"] = exc.report
                try:
                    failure.receipt = retain()
                except BaseException:
                    # Do not hide the original failure or prevent environment
                    # cleanup if storage/protection also fails. Never retry work.
                    failure.add_note("Diagnostic retention failed")
            raise failure from exc
        finally:
            if env is not None:
                try:
                    env.close()
                except BaseException:
                    if failure is None:
                        failure = NativeCaptureFailed(receipt)
                        failure.cleanup_failed = True
                        raise failure
                    failure.cleanup_failed = True
                    failure.add_note("Environment cleanup also failed")
        active()  # A receipt is not an accepted return after cancellation/expiry.
        return NativeCaptureResult(receipt, observation)
