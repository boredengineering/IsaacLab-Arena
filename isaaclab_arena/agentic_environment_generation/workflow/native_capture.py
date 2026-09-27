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

from .contracts import (
    AcquisitionSchedule,
    Amount,
    Count,
    Criterion,
    Duration,
    FrozenModel,
    Identifier,
    ObservationWindow,
    ProfileReference,
)
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

    codec: Literal["native-capture-v1", "native-capture-v2"] = "native-capture-v1"
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
    settle_linear_m_per_s: Amount = 0.001
    settle_angular_rad_per_s: Amount
    settle_linear_operator: Literal["lt", "le"] = "lt"
    settle_angular_operator: Literal["lt", "le"] = "lt"
    window: ObservationWindow
    subjects: Annotated[tuple[NativeSubject, ...], Field(min_length=1, max_length=16)]
    contacts: Annotated[tuple[NativeContact, ...], Field(max_length=16)] = ()
    camera_keys: Annotated[tuple[str, ...], Field(max_length=3)] = ()
    evidence_only: Annotated[bool, Field(strict=True)] = False
    """Retain ungraded cameras for an explicit model-free validation request."""
    image_transform: NativeImageTransform = NativeImageTransform()
    criteria: Annotated[tuple[Criterion, ...], Field(min_length=1, max_length=32)]
    evaluator_version: Literal["1", "numeric-v2"] = "1"
    evaluator_linear_m_per_s: Annotated[float, Field(strict=True, ge=0.01, le=0.01)] = 0.01
    evaluator_angular_rad_per_s: Annotated[float, Field(strict=True, ge=0.05, le=0.05)] = 0.05
    evaluator_xy_m: Annotated[float, Field(strict=True, ge=0.05, le=0.05)] = 0.05
    coordinate_frame: Literal["world"] = "world"
    position_mapping: Literal["root-world-with-env-origin-v1"] = "root-world-with-env-origin-v1"
    max_runtime_seconds: Duration | None
    max_payload_bytes: Literal[2097152] = 2097152
    acquisition: AcquisitionSchedule | None = None

    @model_validator(mode="before")
    @classmethod
    def versioned_fields(cls, value):
        if type(value) is dict:
            if value.get("codec", "native-capture-v1") == "native-capture-v1" and any(
                key in value for key in ("acquisition", "settle_linear_operator", "settle_angular_operator")
            ):
                raise ValueError("New native fields require native-capture-v2")
            if value.get("codec") == "native-capture-v2" and any(
                key in value for key in ("evaluator_linear_m_per_s", "evaluator_angular_rad_per_s", "evaluator_xy_m")
            ):
                raise ValueError("New capture cannot select legacy evaluator constants")
        return value

    @model_validator(mode="after")
    def supported(self):
        if self.codec == "native-capture-v2":
            return self.supported_explicit_schedule()
        if (
            self.max_runtime_seconds is None
            or self.settle_linear_m_per_s != 0.001
            or self.settle_angular_rad_per_s <= 0
        ):
            raise ValueError("Legacy capture requires its original settle limits and runtime bound")
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

    def supported_explicit_schedule(self):
        """Validate the declared rigid/world adapter, not generic physical capability."""
        from .observation_schedule import criterion_coverage

        plan = self.acquisition
        if plan is None or self.max_runtime_seconds is not None or self.contacts:
            raise ValueError("Explicit capture requires acquisition, renewable supervision and no contact adapter")
        steps = sorted(set(plan.state_steps) | {image.step for image in plan.images})
        if (
            not steps
            or self.settle_consecutive_steps > self.settle_steps
            or self.settle_steps > plan.horizon_steps
            or self.window != ObservationWindow(start_step=steps[0], end_step=plan.horizon_steps)
            or plan.control_dt_seconds != self.timestep_seconds * self.decimation
        ):
            raise ValueError("Unsupported absolute capture/settle clock selection")
        if (
            len(set(self.camera_keys)) != len(self.camera_keys)
            or set(self.camera_keys) != {image.camera for image in plan.images}
            or not set(self.camera_keys) <= {"external_camera_rgb", "external_camera_2_rgb", "wrist_camera_rgb"}
        ):
            raise ValueError("Unsupported RGB observation keys")
        names = {s.subject_id: s.scene_name for s in self.subjects}
        if (
            len(names) != len(self.subjects)
            or len(set(names.values())) != len(names)
            or set(names) != set(plan.subjects)
            or len({s.prim_path for s in self.subjects}) != len(self.subjects)
            or any(not s.prim_path.startswith(("/", "{ENV_REGEX_NS}/")) for s in self.subjects)
        ):
            raise ValueError("Unique rigid subject/prim mappings required")
        criteria = tuple(admit_criterion(c) for c in self.criteria)
        if len({c.criterion_id for c in criteria}) != len(criteria):
            raise ValueError("Unique criteria required")
        for criterion in criteria:
            coverage = criterion_coverage(criterion)
            if (
                coverage is None
                or not set(criterion.subjects) <= set(names)
                or not set(coverage.state_steps) <= set(plan.state_steps)
                or not set(coverage.images) <= set(plan.images)
            ):
                raise ValueError("Exact supported criterion coverage required")
            parameters = criterion.parameters
            if parameters.metric == "stationary" and (
                parameters.linear_limit.value != self.settle_linear_m_per_s
                or parameters.angular_limit.value != self.settle_angular_rad_per_s
                or parameters.linear_limit.operator != self.settle_linear_operator
                or parameters.angular_limit.operator != self.settle_angular_operator
            ):
                raise ValueError("Selected stationary limits differ from mechanical reporting limits")
        if self.evidence_only and any(c.kind == "visual" for c in criteria):
            raise ValueError("Evidence-only acquisition cannot request visual assessment")
        image_bound = len(plan.images) * (4 * (3 * self.image_transform.max_edge**2 + 4096) // 3 + 4)
        state_bound = 2048 * len(self.subjects) * (self.settle_steps + len(plan.state_steps))
        if image_bound + state_bound + len(self.canonical_bytes()) + 65536 > self.max_payload_bytes:
            raise ValueError("Whole payload bound")
        self.check_evaluator()
        return self

    @model_serializer(mode="wrap")
    def compatible_bytes(self, serialize):
        value = serialize(self)
        if not self.evidence_only:
            value.pop("evidence_only", None)
        omitted = (
            ("acquisition", "settle_linear_operator", "settle_angular_operator")
            if self.codec == "native-capture-v1"
            else ("evaluator_linear_m_per_s", "evaluator_angular_rad_per_s", "evaluator_xy_m")
        )
        for key in omitted:
            value.pop(key, None)
        return value

    def check_evaluator(self):
        """Refuse changed evaluator defaults instead of reinterpreting old bytes."""
        if self.codec == "native-capture-v2":
            if self.evaluator_version != "numeric-v2" or any(c.parameters is None for c in self.criteria):
                raise ValueError("Explicit capture requires its parameterized evaluators")
            return
        if (
            self.acquisition is not None
            or self.settle_linear_operator != "lt"
            or self.settle_angular_operator != "lt"
            or any(c.parameters is not None for c in self.criteria)
        ):
            raise ValueError("Legacy capture cannot reinterpret configurable selections")
        if EVALUATOR_VERSION != self.evaluator_version or dict(SUPPORT_THRESHOLDS) != {
            "linear_m_per_s": self.evaluator_linear_m_per_s,
            "angular_rad_per_s": self.evaluator_angular_rad_per_s,
            "xy_m": self.evaluator_xy_m,
        }:
            raise ValueError("frozen evaluator revision mismatch")

    def canonical_bytes(self):
        self.check_evaluator()
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
            camera_names=self.camera_keys if self.codec == "native-capture-v1" else (),
            linear_velocity_limit=self.settle_linear_m_per_s,
            linear_operator=self.settle_linear_operator,
            angular_operator=self.settle_angular_operator,
            codec="native-settle-v2" if self.codec == "native-capture-v2" else "native-settle-v1",
            unsettled_policy="record" if self.codec == "native-capture-v2" else "reject",
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


def camera_geometry(*, camera_to_world, source_shape_hw, clipping_range, meters_per_unit, image_transform):
    """Bind measured USD camera geometry to the exact evaluator image transform.

    Args:
        camera_to_world: USD row-vector homogeneous transform, in stage units.
        source_shape_hw: Actual acquired RGB height and width.
        clipping_range: USD near and far clipping distances in stage units.
        meters_per_unit: Measured stage scale; this adapter requires metres.
        image_transform: Frozen evaluator-only RGB transform.

    Returns:
        Bounded geometry and image dimensions, not a physical calibration verdict.
    """
    import math

    if (
        type(meters_per_unit) not in (int, float)
        or meters_per_unit != 1.0
        or len(camera_to_world) != 4
        or any(len(row) != 4 for row in camera_to_world)
        or len(source_shape_hw) != 2
        or any(type(value) is not int or value < 1 for value in source_shape_hw)
        or source_shape_hw[0] * source_shape_hw[1] > image_transform.max_source_pixels
        or len(clipping_range) != 2
        or any(
            type(value) not in (int, float) or not math.isfinite(value)
            for value in [item for row in camera_to_world for item in row] + list(clipping_range)
        )
        or not 0 < clipping_range[0] < clipping_range[1]
    ):
        raise ValueError("Unsupported measured camera geometry")
    height, width = source_shape_hw
    edge = max(height, width)
    encoded_shape = (
        [max(1, value * image_transform.max_edge // edge) for value in source_shape_hw]
        if edge > image_transform.max_edge
        else list(source_shape_hw)
    )
    return {
        "camera_to_world_row_matrix": [list(row) for row in camera_to_world],
        "camera_axes": "usd_camera_negative_z_forward_positive_y_up",
        "matrix_convention": "homogeneous_row_vector_right_multiplication",
        "stage_meters_per_unit": meters_per_unit,
        "clipping_range_m": list(clipping_range),
        "source_image_shape_hw": [height, width],
        "encoded_image_shape_hw": encoded_shape,
        "intrinsics_and_projection_units": "source_image_pixels",
        "image_transform": image_transform.model_dump(mode="json"),
    }


@dataclass(frozen=True)
class NativeCaptureResult:
    receipt: object
    observation: object


def capture_failure_category(error):
    """Classify acquisition/control failure independently of physical predicate truth."""
    from .native_realization import SceneSettleRejected
    from .observation_schedule import CollectionFailure

    if isinstance(error, CollectionFailure):
        return error.category
    if isinstance(error, SceneSettleRejected):
        if error.report.get("reason") in ("terminated", "truncated", "terminated_and_truncated"):
            return "unexpected_termination"
        return "invalid_collection"
    if isinstance(error, (PermissionError, TimeoutError)):
        return "unsafe_execution"
    return "infrastructure_failure"


class NativeCaptureFailed(RuntimeError):
    """Failed native effect; optional diagnostic receipt is never a retry grant."""

    def __init__(self, receipt=None):
        super().__init__("Native capture failed; diagnostic receipt is not acceptance")
        self.receipt = receipt
        self.cleanup_failed = False


class IsaacCaptureAdapter:
    """Apply explicit acquisition to one owned environment, never registry defaults."""

    cameras = {
        "wrist_camera_rgb": "wrist_camera",
        "external_camera_rgb": "external_camera",
        "external_camera_2_rgb": "external_camera_2",
    }

    def __init__(self, settings, contract, spec, candidate, original):
        from .scene_observation import make_native_sampler

        if settings.codec != "native-capture-v2" or settings.contacts:
            raise ValueError("Explicit rigid-root RGB adapter required")
        self.settings, self.contract, self.spec = settings, contract, spec
        self.candidate, self.original = candidate, original
        self.resets = 0
        self.time_origin = None
        self.physics_origin = None
        self.env = None
        self.arena = None
        self.frame_clocks = {}
        self.last_diagnostic = {}
        self.sampler = make_native_sampler(
            settings.criteria,
            subject_names={s.subject_id: s.scene_name for s in settings.subjects},
            acquisition=settings.acquisition,
        )

    def configure_arena(self, arena):
        import copy

        previous = arena.env_cfg_callback

        def configure(cfg):
            cfg = copy.deepcopy(cfg)
            if previous is not None:
                cfg = previous(cfg)
            cfg.sim.dt = self.settings.timestep_seconds
            cfg.decimation = self.settings.decimation
            cfg.seed = self.settings.seed
            cfg.sim.render_interval = self.settings.acquisition.horizon_steps * cfg.decimation + 1
            for key in self.cameras:
                if hasattr(cfg.observations.camera_obs, key):
                    setattr(cfg.observations.camera_obs, key, None)
            return cfg

        arena.env_cfg_callback = configure
        self.arena = arena
        return arena

    def build_environment(self, spec, *, builder_cfg, enable_cameras, kit_cameras_enabled):
        from .native_realization import build_native_environment

        env = build_native_environment(
            spec=spec,
            builder_cfg=builder_cfg,
            enable_cameras=enable_cameras,
            kit_cameras_enabled=kit_cameras_enabled,
            configure_arena=self.configure_arena,
        )
        self.env = env
        base = env.unwrapped
        reset = base._reset_idx

        def measured_reset(*args, **kwargs):
            self.resets += 1
            result = reset(*args, **kwargs)
            self.time_origin = float(base.sim.physics_manager.get_time())
            self.physics_origin = base._sim_step_counter
            return result

        base._reset_idx = measured_reset
        return env

    def read_reset_count(self, env):
        if env is not self.env:
            raise ValueError("Wrong measured environment")
        return self.resets

    def clocks(self, env):
        base = env.unwrapped
        if self.time_origin is None or self.physics_origin is None:
            raise ValueError("Unmeasured reset origin")
        ticks = base._sim_step_counter - self.physics_origin
        if type(ticks) is not int or ticks % self.settings.decimation:
            raise ValueError("Unsupported control clock")
        return {
            "control_step": ticks // self.settings.decimation,
            "simulation_time_seconds": float(base.sim.physics_manager.get_time()) - self.time_origin,
            "physics_step": ticks,
            "reset_count": self.read_reset_count(env),
        }

    @staticmethod
    def array(value):
        if hasattr(value, "detach"):
            return value.detach().cpu().numpy()
        if hasattr(value, "numpy"):
            return value.numpy()
        raise ValueError("Unsupported native buffer")

    def sample_state(self, env, step):
        import math

        value = self.sampler(env, step)
        clocks = self.clocks(env)
        if clocks["control_step"] != step or clocks["reset_count"] != 1:
            raise ValueError("Measured native clock mismatch")
        value["measured_clocks"] = clocks
        for subject in self.settings.subjects:
            if subject.scene_name not in env.unwrapped.scene.rigid_objects:
                raise ValueError("Unsupported non-rigid subject")
            entity = env.unwrapped.scene[subject.scene_name]
            quaternion = self.array(entity.data.root_quat_w)[0].tolist()
            if len(quaternion) != 4 or not all(math.isfinite(x) for x in quaternion):
                raise ValueError("Unsupported root orientation")
            value["subjects"][subject.subject_id]["orientation_w"] = quaternion
        self.last_diagnostic = self.diagnostics(env, step)
        return value

    def acquire_images(self, env, step, keys, observation):
        import numpy as np

        before = self.clocks(env)
        if step not in self.settings.acquisition.renderer_update_steps or before["control_step"] != step:
            raise ValueError("Unscheduled native render")
        env.unwrapped.sim.render()
        if self.clocks(env) != before:
            raise ValueError("Rendering advanced physics or reset state")
        policy = dict(observation.get("camera_obs", {}))
        for key in keys:
            camera = env.unwrapped.scene.sensors[self.cameras[key]]
            camera.update(0.0, force_recompute=True)
            image = camera.data.output["rgb"]
            sequence = int(self.array(camera.frame)[0])
            sensor_time = float(self.array(camera._timestamp_last_update)[0])
            error_bound = (
                before["physics_step"]
                * (
                    abs(float(np.spacing(np.float32(sensor_time))))
                    + abs(float(np.float32(self.settings.timestep_seconds)) - self.settings.timestep_seconds)
                )
                + 1e-8
            )
            control_dt = self.settings.timestep_seconds * self.settings.decimation
            if error_bound >= control_dt / 4 or abs(sensor_time - before["simulation_time_seconds"]) > error_bound:
                raise ValueError("Ambiguous or stale sensor clock")
            measured_step = int(round(sensor_time / control_dt))
            previous = self.frame_clocks.get(key)
            if measured_step != step or (previous is not None and sequence <= previous["sensor_sequence"]):
                raise ValueError("Stale sensor frame")
            self.frame_clocks[key] = {
                "sensor_update_step": measured_step,
                "sensor_sequence": sequence,
                "sensor_time_seconds": sensor_time,
                "quantization_bound_seconds": error_bound,
            }
            policy[key] = image
        self.last_diagnostic = self.diagnostics(env, step)
        return {**observation, "camera_obs": policy}

    def read_frame_clock(self, env, key):
        if env is not self.env or key not in self.frame_clocks:
            raise ValueError("No measured frame")
        value = self.frame_clocks[key]
        return {key: value[key] for key in ("sensor_update_step", "sensor_sequence")}

    def diagnostics(self, env, step):
        import re

        from isaaclab_arena.relations.placement_asset import PlaceableAsset

        from .repairs import resolve_repair_selection
        from .scene_eligibility import RootXYMappingPremise

        scene = env.unwrapped.scene
        roots = {}
        for subject in self.settings.subjects:
            entity = scene[subject.scene_name]
            paths = tuple(entity.root_view.prim_paths)
            configured = str(entity.cfg.prim_path)
            if len(paths) != 1 or re.fullmatch(configured + r"(?:/.*)?", paths[0]) is None:
                raise ValueError("Ambiguous rigid-root mapping")
            roots[subject.subject_id] = {
                "scene_name": subject.scene_name,
                "configured_prim": configured,
                "physical_root_prim": paths[0],
                "root_kind": "rigid_object",
            }
        result = {
            "measured_clocks": self.clocks(env),
            "resolved_rigid_roots": roots,
            "sensor_clocks": dict(self.frame_clocks),
            "camera_support_proxy": self._camera_support_proxy(env, roots),
        }
        if self.contract.action_policy.target_subject is not None:
            selection = resolve_repair_selection(self.contract, self.original)
            root = roots[selection.target_subject]
            asset = self.arena.scene.assets[root["scene_name"]]
            writer = asset.layout_pose_to_scene_writes
            if getattr(writer, "__func__", None) is not PlaceableAsset.layout_pose_to_scene_writes:
                raise ValueError("Unsupported compound placement mapping")
            if asset.get_scene_key() != root["scene_name"]:
                raise ValueError("Placement and measured root differ")
            premise = RootXYMappingPremise(
                codec="root-xy-mapping-v1",
                subject=selection.target_subject,
                scene_name=root["scene_name"],
                prim_path=root["configured_prim"],
                root_kind="rigid_object",
                position_mapping="root-world-with-env-origin-v1",
                authored_coordinate_frame="env_local",
                placement_semantics="weighted-at-position-root-xy-v1",
                relation_index=selection.relation_index,
                relation_loss_weight=selection.relation_loss_weight,
                original_scene_digest=self.original.digest,
                candidate_scene_digest=self.candidate.digest,
            )
            result["root_xy_mapping"] = premise.model_dump(mode="json")
        return result

    def background_scene_name(self):
        """Use the validated graph identity without rewriting retained candidate bytes."""
        return self.spec.background.id

    def _camera_support_proxy(self, env, roots):
        import itertools
        import math

        import omni.usd
        from pxr import Gf, Usd, UsdGeom

        scene = env.unwrapped.scene
        stage = omni.usd.get_context().get_stage()
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
        background = self.background_scene_name()
        name, _ = self.arena.scene.assets[background].get_object_cfg()
        configured = str(getattr(scene.cfg, name).prim_path)
        background_path = configured.format(ENV_REGEX_NS=scene.env_prim_paths[0]).replace(
            scene.env_regex_ns, scene.env_prim_paths[0]
        )
        paths = {key: value["physical_root_prim"] for key, value in roots.items()}
        paths[background] = background_path
        bounds = {}
        for name, path in paths.items():
            prim = stage.GetPrimAtPath(path)
            if not prim.IsValid():
                raise ValueError("Unresolved diagnostic prim")
            box = cache.ComputeWorldBound(prim).ComputeAlignedRange()
            lo, hi = list(box.GetMin()), list(box.GetMax())
            if not all(math.isfinite(v) for v in lo + hi) or any(a > b for a, b in zip(lo, hi)):
                raise ValueError("Invalid diagnostic world bounds")
            bounds[name] = {"prim_path": path, "min_world_m": lo, "max_world_m": hi}
        cameras = {}
        for key in self.settings.camera_keys:
            camera = scene.sensors[self.cameras[key]]
            if len(camera._sensor_prims) != 1:
                raise ValueError("Ambiguous camera mapping")
            prim = camera._sensor_prims[0].GetPrim()
            entry = {
                "sensor": self.cameras[key],
                "prim_path": str(prim.GetPath()),
                "acquired": key in self.frame_clocks,
            }
            if entry["acquired"]:
                matrix = self.array(camera.data.intrinsic_matrices)[0].tolist()
                transform = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
                source_shape = tuple(camera.data.output["rgb"].shape[1:3])
                if source_shape != camera.image_shape:
                    raise ValueError("Acquired and configured camera dimensions differ")
                entry.update(
                    camera_geometry(
                        camera_to_world=[list(row) for row in transform],
                        source_shape_hw=source_shape,
                        clipping_range=list(prim.GetAttribute("clippingRange").Get()),
                        meters_per_unit=float(UsdGeom.GetStageMetersPerUnit(stage)),
                        image_transform=self.settings.image_transform,
                    ),
                    camera_pose_control_step=self.clocks(env)["control_step"],
                    source_image_step=self.frame_clocks[key]["sensor_update_step"],
                )
                inverse = transform.GetInverse()
                projections = {}
                for name, box in bounds.items():
                    points = [
                        inverse.Transform(Gf.Vec3d(*p))
                        for p in itertools.product(*zip(box["min_world_m"], box["max_world_m"]))
                    ]
                    front = [p for p in points if -p[2] > 1e-6]
                    if len(front) != len(points):
                        projections[name] = {"status": "near_plane_crossing_or_behind"}
                        continue
                    pixels = [
                        (matrix[0][0] * p[0] / -p[2] + matrix[0][2], matrix[1][2] - matrix[1][1] * p[1] / -p[2])
                        for p in front
                    ]
                    projections[name] = {
                        "status": "projected_aabb",
                        "bounds_px": [
                            min(p[0] for p in pixels),
                            min(p[1] for p in pixels),
                            max(p[0] for p in pixels),
                            max(p[1] for p in pixels),
                        ],
                        "depth_range_m": [min(-p[2] for p in front), max(-p[2] for p in front)],
                    }
                entry.update(intrinsics=matrix, projections=projections)
            cameras[key] = entry
        support = {
            key: {
                "background_prim": background_path,
                "vertical_aabb_gap_m": value["min_world_m"][2] - bounds[background]["max_world_m"][2],
                "xy_aabb_overlap": all(
                    value["max_world_m"][axis] >= bounds[background]["min_world_m"][axis]
                    and value["min_world_m"][axis] <= bounds[background]["max_world_m"][axis]
                    for axis in (0, 1)
                ),
            }
            for key, value in bounds.items()
            if key != background
        }
        return {
            "codec": "camera-support-aabb-v1",
            "bounds": bounds,
            "cameras": cameras,
            "support_proxy": support,
            "limitations": [
                "AABB projection is not pixel visibility or occlusion ground truth",
                "No contact/manifold or IK measurement",
                "Background bounds do not identify a contact surface",
            ],
        }

    def retained_diagnostics(self):
        if not self.last_diagnostic:
            raise ValueError("No measured native diagnostics")
        return self.last_diagnostic


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
        explicit = s.codec == "native-capture-v2"
        if explicit != (contract.schema_version == "5") or (explicit and contract.acquisition != s.acquisition):
            raise ValueError("native codec/contract/acquisition selection mismatch")
        if s.evidence_only and contract.schema_version not in ("3", "5"):
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
        ):
            raise ValueError("native capture budget mismatch")
        if not explicit:
            assert s.max_runtime_seconds is not None
            assert contract.budget.max_runtime_seconds is not None
            assert contract.budget.total_deadline_seconds is not None
            if s.max_runtime_seconds > min(
                contract.budget.per_operation_timeout_seconds,
                contract.budget.max_runtime_seconds,
                contract.budget.total_deadline_seconds,
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
        if self.settings.codec == "native-capture-v2":
            from .observation_schedule import validate_collection

            compiled = validate_collection(payload, candidate=binding, cohort=receipt.cohort)
            if (
                compiled.plan != self.settings.acquisition
                or payload["diagnostics"]["settle"]["collection_status"] != "complete"
            ):
                raise ValueError("exact complete collection required; unsettled is a scientific result")
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
            self._check_realized_runtime(payload["diagnostics"].get("realized_runtime", {}))
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
            **(
                {"codec": "scene-observation-v2", "source_manifest_digest": receipt.manifest_digest}
                if self.settings.codec == "native-capture-v2"
                else {}
            ),
        )

    @staticmethod
    def _realized_runtime(env):
        """Read the selected environment and its existing reset-placement pool."""
        import tempfile

        from isaaclab_arena.relations.placement_events import PLACEMENT_RESET_EVENT_NAME, get_placement_pool

        base = env.unwrapped
        term = base.event_manager.get_term_cfg(PLACEMENT_RESET_EVENT_NAME)
        pool = get_placement_pool(env)
        assert pool is not None and pool.num_envs == 1, "Selected reset placement pool required"
        return dict(
            seed=base.cfg.seed,
            placement_seed=pool._base_placement_seed,
            resolve_on_reset=term.mode == "reset",
            num_envs=base.num_envs,
            timestep_seconds=base.cfg.sim.dt,
            decimation=base.cfg.decimation,
            control_dt=base.step_dt,
            remaining_layouts=pool.remaining,
            temporary_root=tempfile.gettempdir(),
        )

    def _check_realized_runtime(self, report):
        """Require frozen realized settings and exactly one reset placement draw."""
        s = self.settings
        expected = dict(
            seed=s.seed,
            placement_seed=s.placement_seed,
            resolve_on_reset=s.resolve_on_reset,
            num_envs=1,
            timestep_seconds=s.timestep_seconds,
            decimation=s.decimation,
            control_dt=s.timestep_seconds * s.decimation,
        )
        before, after = report.get("before_reset", {}), report.get("after_capture", {})
        for observed in (before, after):
            if {key: observed.get(key) for key in expected} != expected:
                raise ValueError("Realized native seeds, timestep or reset policy differ")
        if before["remaining_layouts"] - after["remaining_layouts"] != 1:
            raise ValueError("Exactly one initial placement reset required")

    def _check_spec(self, spec, candidate, kit_cameras_enabled):
        """Check the exact validated candidate and graph camera intent without construction."""
        from .repairs import _scene_json

        s = self.settings
        scene = spec.to_dict()
        if hashlib.sha256(candidate.scene_json.encode()).hexdigest() != candidate.digest:
            raise ValueError("validated spec must match exact retained candidate")
        if candidate.scene_json not in (_scene_json(scene), _scene_json(spec.model_dump(mode="json"))):
            if not s.evidence_only and s.codec != "native-capture-v2":
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

    def _active_guard(
        self,
        contract,
        intent,
        deadline,
        check_active,
        supervision,
        control_scope,
        control_instance,
        control_principal,
        read_reset_count,
        read_frame_clock,
        acquire_images,
    ):
        """Select fixed legacy containment or the explicitly renewable control protocol."""
        import math
        import time

        from .contracts import contract_digest
        from .control_protocol import OwnedSupervision, SupervisionCursor, _require_workload
        from .scene_loop import identity

        s = self.settings
        cursor = None
        shared = None
        if s.codec == "native-capture-v2":
            if (
                deadline is not None
                or not callable(supervision)
                or not callable(read_reset_count)
                or control_scope is None
                or not control_instance
                or not control_principal
                or (s.camera_keys and (not callable(read_frame_clock) or not callable(acquire_images)))
            ):
                raise ValueError("explicit capture requires scoped renewable control and reset/sensor ports")
            cursor = SupervisionCursor(
                policy=contract.budget.control,
                scope=control_scope,
                instance=control_instance,
                principal=control_principal,
                fence=intent.worker_fence,
                contract_digest=contract_digest(contract),
                allocation_digest=identity(intent.reservation.model_dump(mode="json")),
            )
            if isinstance(supervision, OwnedSupervision):
                if (
                    supervision.cursor.expected != cursor.expected
                    or supervision.cursor.fence != cursor.fence
                    or supervision.cursor.policy.model_dump(mode="json") != cursor.policy.model_dump(mode="json")
                ):
                    raise PermissionError("Exact consumed owned supervision required")
                shared = supervision
        else:
            if type(deadline) not in (int, float) or not math.isfinite(deadline):
                raise ValueError("original monotonic deadline required")
            assert s.max_runtime_seconds is not None
            stop_at = min(deadline, time.monotonic() + s.max_runtime_seconds)

        def active():
            authority = check_active()
            if shared is not None:
                # The private channel consumes every renewal even when Kit blocks
                # the simulation thread. Do not replay only the newest lease into
                # a second cursor or slide the same lease's monotonic deadline.
                _require_workload(
                    authority,
                    scope=control_scope,
                    principal=control_principal,
                    contract_digest=contract_digest(contract),
                    capability="native_validation",
                    now=time.time(),
                )
                shared.check_active()
            elif cursor is not None:
                cursor.check(supervision(), authority=authority, wall_now=time.time(), monotonic_now=time.monotonic())
            elif time.monotonic() >= stop_at:
                raise TimeoutError("native capture deadline exhausted")

        return active

    def _bound_sampler(self, native_sampler, active):
        """Check configured prim identity at each selected numeric sample."""

        def sample(env, step):
            active()
            value = native_sampler(env, step)
            for subject in self.settings.subjects:
                expected_prim = subject.prim_path
                if "{ENV_REGEX_NS}" in expected_prim:
                    expected_prim = expected_prim.format(ENV_REGEX_NS=env.unwrapped.scene.env_regex_ns)
                if value["subjects"][subject.subject_id]["prim_path"] != expected_prim:
                    raise ValueError("native subject prim identity mismatch")
            return value

        return sample

    def _explicit_observer(
        self, compiled, recorder, diagnostics, active, read_reset_count, read_frame_clock, acquire_images
    ):
        """Give settle/capture distinct ownership while observing actual sensor clocks."""
        from .observation_schedule import CollectionFailure

        s = self.settings

        def observed(env, step, observation):
            phase = "settle" if diagnostics["phase"] == "initialize_and_settle" else "capture"
            if compiled.phase_for(step, s.settle_steps) != phase:
                return
            active()
            reset_count = read_reset_count(env)
            if type(reset_count) is not int or reset_count != 1:
                raise CollectionFailure("unexpected_reset")
            recorder(env, step)
            if step in compiled.renderer_update_steps:
                keys = tuple(image.camera for image in compiled.plan.images if image.step == step)
                observation = acquire_images(env, step, keys, observation)
            for selected in compiled.plan.images:
                if selected.step == step:
                    clock = read_frame_clock(env, selected.camera)
                    recorder.add_frame(
                        camera=selected.camera,
                        step=step,
                        subject_ids=compiled.plan.subjects,
                        image_bytes=encode_native_rgb(observation["camera_obs"][selected.camera], s.image_transform),
                        sensor_update_step=clock["sensor_update_step"],
                        sensor_sequence=clock["sensor_sequence"],
                    )

        return observed

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
        supervision=None,
        control_scope=None,
        control_instance=None,
        control_principal=None,
        read_reset_count=None,
        read_frame_clock=None,
        acquire_images=None,
        read_diagnostics=None,
        sample_state=None,
        build_environment=None,
    ):
        """Capture under versioned control, never granting authority or renewing work.

        V2 requires trusted owner supervision/current-grant callbacks and actual
        reset/sensor/sampling ports. No timer disabling or inferred sensor freshness is allowed.
        """
        from isaaclab_arena.agentic_environment_generation.trajectory_capture import capture_trajectory

        from . import native_realization
        from .contracts import contract_digest
        from .evidence import CandidateBinding, EvidenceCohort
        from .scene_loop import identity, profile_digest
        from .scene_observation import ObservationRecorder, make_native_sampler

        self.admit(contract)
        s = self.settings
        explicit = s.codec == "native-capture-v2"
        if explicit and not callable(sample_state) or not explicit and sample_state is not None:
            raise ValueError("Trusted sampler is required only for explicit capture")
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
            or (not explicit and reservation.runtime_allowance_seconds < s.max_runtime_seconds)
            or any((
                reservation.model_calls,
                reservation.model_tokens,
                reservation.cost_ceiling_usd,
                reservation.candidates,
                reservation.revisions,
            ))
        ):
            raise ValueError("bounded model-free capture reservation required")
        active = self._active_guard(
            contract,
            intent,
            deadline,
            check_active,
            supervision,
            control_scope,
            control_instance,
            control_principal,
            read_reset_count,
            read_frame_clock,
            acquire_images,
        )
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
        native_sampler = (
            sample_state
            if explicit
            else make_native_sampler(
                s.criteria,
                subject_names={v.subject_id: v.scene_name for v in s.subjects},
                contact_sensors={(v.subject_id, v.destination_id): v.sensor_name for v in s.contacts},
            )
        )

        sample = self._bound_sampler(native_sampler, active)
        compiled = None
        if explicit:
            from .observation_schedule import compile_acquisition

            compiled = compile_acquisition(s.acquisition, s.criteria, candidate=binding, cohort=cohort)
        recorder = ObservationRecorder(sample, provenance="native-unverified", acquisition=compiled)
        diagnostics = {"status": "incomplete", "phase": "construct_environment", "charged_steps": 0}
        frames = []
        visual = next((c for c in s.criteria if c.kind == "visual"), None)

        observed = (
            self._explicit_observer(
                compiled, recorder, diagnostics, active, read_reset_count, read_frame_clock, acquire_images
            )
            if explicit
            else None
        )

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
            if callable(read_diagnostics) and diagnostics.get("status") == "complete":
                measured = read_diagnostics()
                allowed = {
                    "measured_clocks",
                    "resolved_rigid_roots",
                    "sensor_clocks",
                    "camera_support_proxy",
                    "root_xy_mapping",
                }
                if type(measured) is not dict or set(measured) - allowed:
                    raise ValueError("Unsupported measured diagnostic projection")
                diagnostics.update(measured)
            payload = recorder.payload() | {
                "settings": s.model_dump(mode="json"),
                "settings_sha256": s.digest(),
                "diagnostics": diagnostics,
            }
            retention_attempted = True
            return self.artifacts.write(binding, cohort, payload, protect=self.protect)

        env, receipt, failure = None, None, None
        try:
            build_native = build_environment or native_realization.build_native_environment
            env = build_native(
                spec,
                builder_cfg=s.builder_config(),
                enable_cameras=bool(s.camera_keys),
                kit_cameras_enabled=kit_cameras_enabled,
            )
            active()
            base = env.unwrapped
            if base.num_envs != 1 or base.cfg.sim.dt != s.timestep_seconds or base.cfg.decimation != s.decimation:
                raise ValueError("realized runtime settings mismatch")
            if s.evidence_only and not explicit:
                diagnostics["phase"] = "validate_runtime"
                diagnostics["realized_runtime"] = {"before_reset": self._realized_runtime(env)}
            diagnostics["phase"] = "initialize_and_settle"
            initialized = native_realization.initialize_and_settle(
                env,
                settings=s.settle_settings(),
                charge_step=charge,
                hold_action_factory=native_realization.build_droid_posture_hold,
                observe_step=observed if explicit else None,
            )
            diagnostics["settle"] = initialized.report

            class Hold:
                def get_action(self, env, observation):
                    charge(diagnostics["charged_steps"] + 1)
                    return initialized.hold_action

            diagnostics["phase"] = "capture_trajectory"
            captured = capture_trajectory(
                env,
                Hold(),
                out_dir=out_dir,
                num_steps=s.window.end_step - (s.settle_steps if explicit else s.window.start_step),
                frame_interval=1,
                camera_names=() if explicit else s.camera_keys,
                save_frame=save_frame,
                sample_state=None if explicit else recorder,
                initial_observation=initialized.observation,
                step_offset=initialized.step_offset,
                reset_policy=False,
                observe_step=observed if explicit else None,
            )
            diagnostics["capture"] = {k: v for k, v in captured.items() if k != "frames"}
            if s.evidence_only and not explicit:
                diagnostics["realized_runtime"]["after_capture"] = self._realized_runtime(env)
                self._check_realized_runtime(diagnostics["realized_runtime"])
            if explicit:
                recorder.complete(
                    executed_steps=diagnostics["charged_steps"],
                    reset_count=read_reset_count(env),
                    terminated="terminated" in captured["stop_reason"],
                    truncated="truncated" in captured["stop_reason"],
                )
            active()
            diagnostics["status"] = "complete"
            receipt = retain()
            observation = self.replay(receipt, contract=contract, candidate=candidate)
        except BaseException as exc:
            failure = NativeCaptureFailed(receipt)
            if receipt is None and not retention_attempted:
                diagnostics.update(status="failed", failure_type=type(exc).__name__)
                if explicit:
                    diagnostics["failure_category"] = capture_failure_category(exc)
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
