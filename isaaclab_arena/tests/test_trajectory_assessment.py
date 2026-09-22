# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Offline trajectory assessment contracts; synthetic images and model responses only."""

import hashlib
import importlib
import json
from pathlib import Path

import pytest


def test_task_driven_assessment_is_returned_and_retained(tmp_path):
    from isaaclab_arena.agentic_environment_generation.trajectory_assessment import assess_trajectory

    spec = {
        "env_name": "drawer_task",
        "task": {"description": "Open the blue drawer", "subtasks": [{"kind": "OpenDrawerTask"}]},
        "embodiment": {"id": "robot", "registry_name": "example_robot"},
        "objects": [{"id": "drawer", "registry_name": "blue_drawer"}],
    }
    frame = tmp_path / "step_000_wrist.png"
    frame.write_bytes(b"synthetic-image-fixture")
    calls = []

    class SyntheticBackend:
        def multimodal_chat(self, prompt, images):
            calls.append((prompt, images))
            return json.dumps({
                "status": "inconclusive",
                "observations": ["The drawer handle is outside the captured view."],
                "actionable_feedback": "Capture a view containing the handle.",
            })

    result = assess_trajectory(
        spec,
        {"step_000_wrist": frame},
        backend=SyntheticBackend(),
        model="test/vision",
        executed_steps=1,
        output_path=tmp_path / "assessment.json",
    )
    prompt, images = calls[0]
    assert "Open the blue drawer" in prompt and "blue_drawer" in prompt
    assert "red apple" not in prompt and "robot failed" not in prompt
    assert images == {"step_000_wrist": frame.read_bytes()}
    assert result["assessment"]["status"] == "inconclusive"
    assert result["task_success"] is None
    assert result["frames"][0]["sha256"] == hashlib.sha256(frame.read_bytes()).hexdigest()
    assert result["model"] == "test/vision"
    assert json.loads((tmp_path / "assessment.json").read_text()) == result


def test_no_images_retains_inconclusive_without_provider_call(tmp_path):
    from isaaclab_arena.agentic_environment_generation.trajectory_assessment import assess_trajectory

    result = assess_trajectory(
        {"task": {"description": "Close a door"}},
        {},
        backend=None,
        model=None,
        executed_steps=3,
        output_path=tmp_path / "assessment.json",
    )
    assert result["assessment"]["status"] == "inconclusive"
    assert result["frames"] == [] and result["task_success"] is None
    assert json.loads((tmp_path / "assessment.json").read_text()) == result


@pytest.mark.parametrize(
    "response",
    [
        "{}",
        '{"status":"satisfactory","observations":[],"actionable_feedback":""}',
        '{"status":"success","observations":["visible"],"actionable_feedback":""}',
        '{"status":"satisfactory","observations":[1],"actionable_feedback":""}',
        '{"status":"satisfactory","observations":["visible"],"actionable_feedback":"","success":true}',
        '{"status":"satisfactory","status":"inconclusive","observations":["visible"],"actionable_feedback":""}',
        '{"status":"issues_detected","observations":["visible"],"actionable_feedback":NaN}',
    ],
)
def test_invalid_assessment_never_becomes_retained_success(tmp_path, response):
    from isaaclab_arena.agentic_environment_generation.trajectory_assessment import assess_trajectory

    class Backend:
        def multimodal_chat(self, *args):
            return response

    frame = tmp_path / "frame.png"
    frame.write_bytes(b"synthetic-image")
    output = tmp_path / "assessment.json"
    with pytest.raises(ValueError):
        assess_trajectory(
            {}, {"step_000_camera": frame}, backend=Backend(), model="test/model", executed_steps=1, output_path=output
        )
    assert not output.exists()


def test_retained_assessment_is_not_overwritten_or_reexecuted(tmp_path):
    from isaaclab_arena.agentic_environment_generation.trajectory_assessment import assess_trajectory

    output = tmp_path / "assessment.json"
    output.write_text("existing receipt")
    with pytest.raises(FileExistsError):
        assess_trajectory({}, {}, backend=None, model=None, executed_steps=0, output_path=output)
    assert output.read_text() == "existing receipt"


def test_cli_import_does_not_parse_launch_simulator_or_import_provider(monkeypatch):
    import builtins

    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert not name.startswith(("isaaclab.", "torch", "PIL", "openai")), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    from isaaclab_arena_examples.tools import render_policy_trajectory

    module = importlib.reload(render_policy_trajectory)
    parser = module.build_parser()
    args = parser.parse_args([
        "--env_graph_spec_yaml",
        "scene.yaml",
        "--policy_config_yaml_path",
        "policy.yaml",
        "--model",
        "test/vision",
        "--camera_names",
        "wrist",
        "external",
    ])
    assert args.model == "test/vision"
    assert args.camera_names == ["wrist", "external"]
    assert args.out_dir is None


@pytest.mark.parametrize("end_flags", [(True, False), (False, True), (True, True), (False, False)])
@pytest.mark.parametrize("end_step", [1, 3, 4])
def test_capture_omits_autoreset_images_and_preserves_prior_samples(tmp_path, end_flags, end_step):
    from isaaclab_arena.agentic_environment_generation.trajectory_capture import capture_trajectory

    class Flag:
        def __init__(self, value):
            self.value = value

        def any(self):
            return self.value

    class Env:
        step_count = 0

        def reset(self):
            return {"camera_obs": {"wrist": 0, "external": 10}}, {}

        def step(self, action):
            self.step_count += 1
            ended, limited = end_flags if self.step_count == end_step else (False, False)
            # IsaacLab returns reset observations, not the terminal scene.
            value = "AUTORESET" if ended or limited else self.step_count
            return {"camera_obs": {"wrist": value, "external": value}}, 0, Flag(ended), Flag(limited), {}

    class Policy:
        def reset(self):
            pass

        def get_action(self, env, obs):
            return 0

    def save_frame(value, path):
        path.write_text(str(value))

    env = Env()
    result = capture_trajectory(
        env, Policy(), out_dir=tmp_path, num_steps=4, frame_interval=2, camera_names=None, save_frame=save_frame
    )
    ended, limited = end_flags
    expected_steps = end_step if ended or limited else 4
    assert result["executed_steps"] == env.step_count == expected_steps
    assert result["stop_reason"] == (
        "terminated_and_truncated"
        if ended and limited
        else "terminated" if ended else "truncated" if limited else "step_budget"
    )
    sampled_steps = [0] + [
        step for step in (2, 4) if step < expected_steps or (step == expected_steps and not any(end_flags))
    ]
    assert list(result["frames"]) == [
        f"step_{step:06d}_{camera}" for step in sampled_steps for camera in ("external", "wrist")
    ]
    assert all("AUTORESET" not in path.read_text() for path in result["frames"].values())
    assert result["terminal_image_unavailable"] is any(end_flags)
    assert set(tmp_path.glob("*.png")) == set(result["frames"].values())


@pytest.mark.parametrize("fail", [False, True])
def test_cli_main_closes_app_on_result_or_error(monkeypatch, fail):
    import sys
    from types import SimpleNamespace

    from isaaclab_arena_examples.tools import render_policy_trajectory as cli

    closed = []

    class Launcher:
        def __init__(self, args):
            assert args.headless and args.enable_cameras
            self.app = SimpleNamespace(close=lambda **kwargs: closed.append(kwargs.get("exit_code", 0)))

        @staticmethod
        def add_app_launcher_args(parser):
            # The real launcher probes process argv before adding its options.
            # main(argv) must not require trajectory inputs during this probe.
            parser.parse_known_args([])

    def run(args):
        if fail:
            raise ValueError("synthetic run failure")
        return {"assessment": "synthetic"}

    monkeypatch.setitem(sys.modules, "isaaclab.app", SimpleNamespace(AppLauncher=Launcher))
    monkeypatch.setattr(cli, "run", run)
    argv = ["--env_graph_spec_yaml", "scene.yaml", "--policy_config_yaml_path", "policy.yaml"]
    if fail:
        with pytest.raises(ValueError, match="synthetic"):
            cli.main(argv)
    else:
        assert cli.main(argv) == {"assessment": "synthetic"}
    assert closed == [1 if fail else 0]


def test_cli_help_includes_simulator_options_without_launch(monkeypatch, capsys):
    import sys
    from types import SimpleNamespace

    from isaaclab_arena_examples.tools import render_policy_trajectory as cli

    class Launcher:
        def __init__(self, args):
            pytest.fail("Help must not launch SimulationApp")

        @staticmethod
        def add_app_launcher_args(parser):
            parser.parse_known_args([])
            parser.add_argument("--device", default="cuda:0")

    monkeypatch.setitem(sys.modules, "isaaclab.app", SimpleNamespace(AppLauncher=Launcher))
    with pytest.raises(SystemExit) as result:
        cli.main(["--help"])
    assert result.value.code == 0
    help_text = capsys.readouterr().out
    assert "--device" in help_text and "--env_graph_spec_yaml" in help_text


@pytest.mark.parametrize("with_camera", [True, False])
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "policy_construct",
        "policy_task",
        "policy_reset",
        "policy_action",
        "policy_close",
        "env_close",
        "both_close",
        "backend_init",
        "model",
        "model_response",
    ],
)
def test_cli_run_connects_capture_to_retained_assessment(monkeypatch, tmp_path, with_camera, fault):
    _check_cli_run(monkeypatch, tmp_path, with_camera, fault)


@pytest.mark.parametrize("with_camera", [True, False])
@pytest.mark.parametrize(
    "env_instruction,policy_fallback",
    [
        ("  Generated task instruction\n", "Unused policy fallback"),
        (None, "  Policy YAML fallback\n"),
        (None, None),
    ],
)
def test_cli_retains_resolved_instruction_not_authored_description(
    monkeypatch, tmp_path, with_camera, env_instruction, policy_fallback
):
    _check_cli_run(monkeypatch, tmp_path, with_camera, None, env_instruction, policy_fallback)


@pytest.mark.parametrize(
    "simulator_device,policy_device",
    [(None, None), ("cuda:1", None), ("cpu", None), ("cuda:1", "cpu"), ("cpu", "cuda:2")],
)
def test_cli_forwards_simulator_device_and_policy_override(monkeypatch, tmp_path, simulator_device, policy_device):
    _check_cli_run(monkeypatch, tmp_path, True, None, simulator_device=simulator_device, policy_device=policy_device)


def _check_completed_capture(tmp_path, fault, with_camera, expected_instruction):
    if fault not in ("policy_construct", "policy_task", "policy_reset", "policy_action"):
        capture = json.loads((tmp_path / "run/capture.json").read_text())
        assert capture["executed_steps"] == 1 and capture["stop_reason"] == "terminated"
        assert capture["terminal_image_unavailable"] is True
        assert bool(capture["frames"]) is with_camera
        assert capture["policy_instruction"] == expected_instruction
        for path in capture["frames"].values():
            assert Path(path).read_bytes() == b"synthetic-image"


def _check_cli_run(
    monkeypatch,
    tmp_path,
    with_camera,
    fault,
    env_instruction="Open the blue door",
    policy_fallback="Policy fallback",
    simulator_device=None,
    policy_device=None,
):
    """Exercise production CLI/capture/assessment wiring with synthetic simulator and provider seams."""
    import contextlib
    import sys
    from types import SimpleNamespace

    from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg
    from isaaclab_arena_examples.tools import render_policy_trajectory as cli

    spec_data = {
        "env_name": "door",
        "task": {"description": "Open the blue door", "params": {"task_description": None}},
    }
    authored_spec = json.dumps(spec_data, sort_keys=True)
    expected_instruction = env_instruction if env_instruction is not None else policy_fallback
    calls, closed = [], []

    def fail_at(stage):
        if fault == stage or (fault == "both_close" and stage in ("policy_close", "env_close")):
            raise RuntimeError(stage)

    class Spec:
        def to_dict(self):
            return spec_data

        def write_yaml(self, path):
            path.write_text(json.dumps(spec_data))

    class Env:
        unwrapped = SimpleNamespace(get_language_instruction=lambda: env_instruction)

        def reset(self):
            return {"camera_obs": {"external": 7} if with_camera else {}}, {}

        def step(self, action):
            return self.reset()[0], 0, SimpleNamespace(any=lambda: True), SimpleNamespace(any=lambda: False), {}

        def close(self):
            closed.append("env")
            _check_completed_capture(tmp_path, fault, with_camera, expected_instruction)
            fail_at("env_close")

    class Builder:
        def __init__(self, arena_env, *, cfg):
            assert isinstance(cfg, ArenaEnvBuilderCfg)
            assert cfg.num_envs == 1
            assert cfg.device == (simulator_device or "cuda:0")

        def make_registered(self, **kwargs):
            return Env()

    class Backend:
        model = "test/vision"

        def __init__(self, **kwargs):
            calls.append("backend")
            assert kwargs["model"] == self.model
            fail_at("backend_init")
            self.client = SimpleNamespace(close=lambda: closed.append("client"))

        def multimodal_chat(self, prompt, images):
            assert "Open the blue door" in prompt and len(images) == 1
            assert f"Authored environment specification: {authored_spec}" in prompt
            assert f"Resolved policy instruction (JSON): {json.dumps(expected_instruction)}" in prompt
            assert "may differ" in prompt
            assert "Terminal image unavailable" in prompt
            assert "autoreset" in prompt and "terminated" in prompt
            fail_at("model")
            if fault == "model_response":
                return "{}"
            return json.dumps(
                {"status": "satisfactory", "observations": ["The door is visible."], "actionable_feedback": ""}
            )

    class Policy:
        def reset(self):
            fail_at("policy_reset")

        def get_action(self, *args):
            fail_at("policy_action")
            return 0

        def set_task_description(self, value):
            assert value == env_instruction
            calls.append(value)
            fail_at("policy_task")
            return value if value is not None else policy_fallback

        def close(self):
            closed.append("policy")
            _check_completed_capture(tmp_path, fault, with_camera, expected_instruction)
            fail_at("policy_close")

    def build_policy(policy_cls, args):
        assert args.policy_device == (policy_device or simulator_device or "cuda:0")
        fail_at("policy_construct")
        return Policy()

    modules = {
        "torch": SimpleNamespace(inference_mode=contextlib.nullcontext),
        "PIL": SimpleNamespace(Image=SimpleNamespace(fromarray=lambda value: None)),
        "isaaclab_arena.agentic_environment_generation.inference_backend": SimpleNamespace(InferenceBackend=Backend),
        "isaaclab_arena.environment_spec.arena_env_graph_spec": SimpleNamespace(
            ArenaEnvGraphSpec=SimpleNamespace(from_yaml=lambda path: Spec())
        ),
        "isaaclab_arena.environment_spec.arena_env_graph_conversion_utils": SimpleNamespace(
            build_arena_env_from_graph_spec=lambda *args, **kwargs: object()
        ),
        "isaaclab_arena.environments.arena_env_builder": SimpleNamespace(ArenaEnvBuilder=Builder),
        "isaaclab_arena.evaluation.policy_runner": SimpleNamespace(get_policy_cls=lambda name: object()),
        "isaaclab_arena.evaluation.policy_runner_cli": SimpleNamespace(build_policy_from_cli=build_policy),
    }

    # Minimal tensor/PIL boundary, while capture and assessment implementations remain real.
    class Tensor:
        def __getitem__(self, index):
            return self

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return b"synthetic-image"

    def reset(self):
        return {"camera_obs": {"external": Tensor()} if with_camera else {}}, {}

    monkeypatch.setattr(Env, "reset", reset)
    modules["PIL"].Image.fromarray = lambda value: SimpleNamespace(save=lambda path: path.write_bytes(value))
    for name, value in modules.items():
        monkeypatch.setitem(sys.modules, name, value)
    config = tmp_path / "policy.yaml"
    config.write_text("synthetic: true")

    class Launcher:
        @staticmethod
        def add_app_launcher_args(parser):
            parser.parse_known_args([])
            parser.add_argument("--device", default="cuda:0")

    device_args = []
    if simulator_device is not None:
        device_args += ["--device", simulator_device]
    if policy_device is not None:
        device_args += ["--policy_device", policy_device]
    args = cli.build_parser(Launcher).parse_args([
        "--env_graph_spec_yaml",
        "scene.yaml",
        "--policy_config_yaml_path",
        str(config),
        "--model",
        "test/vision",
        "--out_dir",
        str(tmp_path / "run"),
        *device_args,
    ])
    policy_fault = fault is not None and fault.startswith("policy_")
    teardown_fault = fault in ("policy_close", "env_close", "both_close")
    expected_error = policy_fault or teardown_fault or (with_camera and fault is not None)
    if expected_error:
        error_type = ValueError if fault == "model_response" else RuntimeError
        match = "Invalid assessment fields" if fault == "model_response" else fault
        if fault == "both_close":
            match = "env_close"
        with pytest.raises(error_type, match=match):
            cli.run(args)
    else:
        result = cli.run(args)
    backend_constructed = with_camera and not policy_fault and not teardown_fault and fault != "backend_init"
    assert closed == (
        ([] if fault == "policy_construct" else ["policy"]) + ["env"] + (["client"] if backend_constructed else [])
    )
    assert ("backend" in calls) == (with_camera and not policy_fault and not teardown_fault)
    _check_completed_capture(tmp_path, fault, with_camera, expected_instruction)
    assert json.dumps(spec_data, sort_keys=True) == authored_spec
    assert json.loads((tmp_path / "run/spec.yaml").read_text()) == json.loads(authored_spec)
    if expected_error:
        assert not (tmp_path / "run/assessment.json").exists()
        return
    assert result["task_success"] is None
    assert result["assessment"]["status"] == ("satisfactory" if with_camera else "inconclusive")
    assert result["policy_instruction"] == expected_instruction
    assert result["spec_sha256"] == hashlib.sha256(authored_spec.encode()).hexdigest()
    assert json.loads((tmp_path / "run/assessment.json").read_text()) == result
    capture = json.loads((tmp_path / "run/capture.json").read_text())
    assert capture["executed_steps"] == 1 and capture["stop_reason"] == "terminated"
    assert capture["terminal_image_unavailable"] is True
    assert result["terminal_image_unavailable"] is True
    assert result["stop_reason"] == "terminated"


def test_initialized_capture_preserves_reset_cohort_and_absolute_steps(tmp_path):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.trajectory_capture import capture_trajectory

    calls, samples = [], []
    flag = SimpleNamespace(any=lambda: False)

    class Env:
        def reset(self):
            pytest.fail("Initialized capture must not reset")

        def step(self, action):
            calls.append(action)
            return {"camera_obs": {"wrist": len(calls)}}, 0, flag, flag, {}

    policy = SimpleNamespace(
        reset=lambda: pytest.fail("Policy already initialized"),
        get_action=lambda *args: 7,
    )
    result = capture_trajectory(
        Env(),
        policy,
        out_dir=tmp_path,
        num_steps=2,
        frame_interval=1,
        camera_names=["wrist"],
        save_frame=lambda value, path: path.write_text(str(value)),
        sample_state=lambda env, step: samples.append(step),
        initial_observation={"camera_obs": {"wrist": "settled"}},
        step_offset=3,
        reset_policy=False,
    )
    assert samples == [3, 4, 5]
    assert list(result["frames"]) == [f"step_{step:06d}_wrist" for step in samples]
    assert result["executed_steps"] == 2
    assert result["step_offset"] == 3 and result["end_step"] == 5
    assert calls == [7, 7]


def test_capture_offset_without_initialized_observation_rejects_before_reset(tmp_path):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.trajectory_capture import capture_trajectory

    with pytest.raises(AssertionError, match="initialized"):
        capture_trajectory(
            SimpleNamespace(reset=lambda: pytest.fail("Invalid input must not reset")),
            None,
            out_dir=tmp_path,
            num_steps=1,
            frame_interval=1,
            camera_names=[],
            save_frame=None,
            step_offset=1,
        )


@pytest.mark.parametrize("override", [None, True, False])
def test_native_builder_reuses_typed_builder_and_camera_contract(monkeypatch, override):
    import sys
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.native_realization import build_native_environment
    from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg

    calls = []
    params = {} if override is None else {"enable_cameras": override}
    arena = object()
    wrapper = SimpleNamespace(unwrapped=object())
    spec = SimpleNamespace(
        embodiment=SimpleNamespace(params=params),
        to_arena_env=lambda **kw: (calls.append(kw), arena)[1],
    )
    cfg = ArenaEnvBuilderCfg(seed=13, placement_seed=17, resolve_on_reset=False)

    class Builder:
        def __init__(self, env, *, cfg):
            assert env is arena and isinstance(cfg, ArenaEnvBuilderCfg)
            assert cfg.seed == 13 and cfg.placement_seed == 17 and cfg.resolve_on_reset is False

        def make_registered(self):
            calls.append("build")
            return wrapper

    monkeypatch.setitem(
        sys.modules,
        "isaaclab_arena.environments.arena_env_builder",
        SimpleNamespace(ArenaEnvBuilder=Builder),
    )
    if override is False:
        with pytest.raises(AssertionError, match="camera"):
            build_native_environment(spec, builder_cfg=cfg, enable_cameras=True, kit_cameras_enabled=True)
        assert calls == []
    else:
        assert build_native_environment(spec, builder_cfg=cfg, enable_cameras=True, kit_cameras_enabled=True) is wrapper
        assert calls == [{"enable_cameras": True}, "build"]
    assert params == ({} if override is None else {"enable_cameras": override})


def test_native_builder_rejects_kit_camera_conflict_before_conversion():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.native_realization import build_native_environment
    from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg

    spec = SimpleNamespace(embodiment=SimpleNamespace(params={}))
    with pytest.raises(AssertionError, match="Kit"):
        build_native_environment(
            spec,
            builder_cfg=ArenaEnvBuilderCfg(),
            enable_cameras=True,
            kit_cameras_enabled=False,
        )


@pytest.mark.parametrize("closed", [False, True])
def test_droid_hold_uses_actual_term_order_affine_targets_and_binary_gripper(monkeypatch, closed):
    import sys
    import torch
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.native_realization import build_droid_posture_hold

    class JointPositionAction:
        pass

    class BinaryJointPositionZeroToOneAction:
        pass

    monkeypatch.setitem(
        sys.modules,
        "isaaclab.envs.mdp.actions.joint_actions",
        SimpleNamespace(JointPositionAction=JointPositionAction),
    )
    monkeypatch.setitem(
        sys.modules,
        "isaaclab_arena.embodiments.droid.actions",
        SimpleNamespace(BinaryJointPositionZeroToOneAction=BinaryJointPositionZeroToOneAction),
    )
    q = torch.tensor([[0.78 if closed else 0.01, 0.2, -0.4, 0.6, -0.8, 1.0, -1.2, 1.4]])
    robot = SimpleNamespace(data=SimpleNamespace(joint_pos=q))
    arm, gripper = JointPositionAction(), BinaryJointPositionZeroToOneAction()
    arm._asset, gripper._asset = robot, robot
    arm._joint_ids, gripper._joint_ids = [7, 5, 3, 1, 6, 4, 2], [0]
    arm.action_dim, gripper.action_dim = 7, 1
    arm._scale, arm._offset = 2.0, 0.25
    arm.cfg = SimpleNamespace(use_default_offset=False, clip=None)
    gripper.cfg = SimpleNamespace(clip=None)
    gripper._open_command, gripper._close_command = torch.tensor([[0.0]]), torch.tensor([[0.785398]])
    terms = {"gripper_action": gripper, "arm_action": arm}
    base = SimpleNamespace(
        num_envs=1,
        device="cpu",
        action_manager=SimpleNamespace(active_terms=list(terms), get_term=terms.__getitem__, total_action_dim=8),
    )
    action = build_droid_posture_hold(SimpleNamespace(unwrapped=base))
    assert action.shape == (1, 8) and action[0, 0].item() == int(closed)
    torch.testing.assert_close(action[:, 1:] * arm._scale + arm._offset, q[:, arm._joint_ids])
    original = action.clone()
    q[:] = 99  # The settled hold targets must not track later drift.
    torch.testing.assert_close(action, original)
    arm._scale = 0.0
    with pytest.raises(AssertionError, match="scale"):
        build_droid_posture_hold(SimpleNamespace(unwrapped=base))


@pytest.mark.parametrize("already_reset", [False, True], ids=["legacy-reset", "already-reset"])
@pytest.mark.parametrize(
    "velocity,terminal,expected",
    [
        (0.000999999, None, "settled"),
        (0.001, None, "unsettled"),
        (0.001000001, None, "unsettled"),
        (float("nan"), None, "invalid_measurement"),
        (float("inf"), None, "invalid_measurement"),
        (0.0, "terminated", "terminated"),
        (0.0, "truncated", "truncated"),
        (0.0, "terminated_and_truncated", "terminated_and_truncated"),
    ],
)
def test_native_settle_is_blocking_raw_strict_bounded_and_single_reset(
    tmp_path, velocity, terminal, expected, already_reset
):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.trajectory_capture import capture_trajectory
    from isaaclab_arena.agentic_environment_generation.workflow.native_realization import (
        NativeSettleSettings,
        SceneSettleRejected,
        initialize_and_settle,
    )

    calls, charges, samples, holds = [], [], [], []
    entry_observation = {"camera_obs": {"wrist": "supplied-reset"}}

    class Env:
        unwrapped = SimpleNamespace(num_envs=1)
        steps = 0

        def reset(self):
            assert not already_reset, "Already-reset preparation must never call reset"
            calls.append("reset")
            return {"camera_obs": {"wrist": 0}}, {}

        def step(self, action):
            assert charges[-1] == self.steps + 1
            self.steps += 1
            calls.append(action)

            def flag(name):
                return SimpleNamespace(any=lambda: terminal is not None and name in terminal)

            return (
                {"camera_obs": {"wrist": "autoreset-not-terminal" if terminal else self.steps}},
                0,
                flag("terminated"),
                flag("truncated"),
                {},
            )

    def measure(env, names):
        assert names == ("object", "robot")
        samples.append(env.steps)
        return {
            name: {
                "linear_velocity_w": [velocity, 0.0, 0.0],
                "angular_velocity_w": [0.0, 0.0, 0.0],
            }
            for name in names
        }

    def hold(env):
        assert calls == ([] if already_reset else ["reset"])
        holds.append(env)
        return "hold"

    env = Env()
    settings = NativeSettleSettings(
        settle_steps=3,
        subjects=("object", "robot"),
        angular_velocity_limit=0.001,
        camera_names=("wrist",),
        consecutive_steps=2,
    )
    kwargs: dict = dict(
        settings=settings,
        charge_step=charges.append,
        sample_velocities=measure,
        hold_action_factory=hold,
    )
    if already_reset:
        kwargs["initialized_observation"] = entry_observation
    if expected != "settled":
        with pytest.raises(SceneSettleRejected) as failure:
            initialize_and_settle(env, **kwargs)
        report = failure.value.report
        assert report["reason"] == expected and report["all_objects_settled"] is False
        assert report["executed_steps"] == env.steps == (3 if expected == "unsettled" else 1)
        assert samples == ([] if terminal else [1] if expected == "invalid_measurement" else [1, 2, 3])
        assert charges == list(range(1, env.steps + 1))
        if terminal:
            assert report["samples"] == []  # Never measure the newly autoreset cohort.
    else:
        initialized = initialize_and_settle(env, **kwargs)
        assert initialized.step_offset == env.steps == 3
        assert initialized.observation == {"camera_obs": {"wrist": 3}}
        assert initialized.hold_action == "hold"
        assert initialized.report["executed_steps"] == 3
        assert initialized.report["samples"][-1]["subjects"]["object"]["linear_speed"] == velocity
        assert initialized.report["all_objects_settled"] is True
        assert charges == [1, 2, 3]
        charges.append(4)
        policy = SimpleNamespace(reset=lambda: None, get_action=lambda *args: initialized.hold_action)
        result = capture_trajectory(
            env,
            policy,
            out_dir=tmp_path,
            num_steps=1,
            frame_interval=1,
            camera_names=["wrist"],
            save_frame=lambda value, path: path.write_text(str(value)),
            initial_observation=initialized.observation,
            step_offset=initialized.step_offset,
        )
        assert list(result["frames"]) == ["step_000003_wrist", "step_000004_wrist"]
    assert holds == [env]
    assert calls == ([] if already_reset else ["reset"]) + ["hold"] * env.steps


@pytest.mark.parametrize("shape", [(1, 3), (2, 3)])
def test_native_settle_default_reader_reuses_world_velocity_getters(monkeypatch, shape):
    import sys
    import torch
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.native_realization import (
        NativeSettleSettings,
        SceneSettleRejected,
        initialize_and_settle,
    )

    monkeypatch.setitem(sys.modules, "warp", SimpleNamespace(to_torch=lambda value: value))
    monkeypatch.setitem(sys.modules, "isaaclab.assets", SimpleNamespace(RigidObject=object))
    # The production predicate getters are retained, not replaced by a permissive sampler.
    from isaaclab_arena.tasks.predicates import predicate_utils

    monkeypatch.setattr(predicate_utils, "wp", sys.modules["warp"])
    flag = SimpleNamespace(any=lambda: False)
    data = SimpleNamespace(root_lin_vel_w=torch.zeros(shape), root_ang_vel_w=torch.zeros(shape))
    base = SimpleNamespace(num_envs=1, scene={"object": SimpleNamespace(data=data)})
    env = SimpleNamespace(
        unwrapped=base,
        reset=lambda: ({}, {}),
        step=lambda action: ({}, 0, flag, flag, {}),
    )
    kwargs = dict(
        settings=NativeSettleSettings(1, ("object",), 0.001),
        charge_step=lambda step: None,
        hold_action_factory=lambda env: 0,
    )
    if shape == (1, 3):
        result = initialize_and_settle(env, **kwargs)
        assert result.report["samples"][0]["subjects"]["object"]["linear_velocity_w"] == [0.0, 0.0, 0.0]
    else:
        with pytest.raises(SceneSettleRejected) as failure:
            initialize_and_settle(env, **kwargs)
        assert failure.value.report["reason"] == "invalid_measurement"


def test_uninitialized_capture_cannot_reuse_policy_state(tmp_path):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.trajectory_capture import capture_trajectory

    with pytest.raises(AssertionError, match="initialized"):
        capture_trajectory(
            SimpleNamespace(reset=lambda: pytest.fail("Must fail before reset")),
            None,
            out_dir=tmp_path,
            num_steps=1,
            frame_interval=1,
            camera_names=[],
            save_frame=None,
            reset_policy=False,
        )


@pytest.mark.parametrize("already_reset", [False, True], ids=["legacy-reset", "already-reset"])
@pytest.mark.parametrize(
    "defect",
    [
        "angular",
        "vector_norm",
        "other_subject",
        "coverage",
        "camera",
        "camera_after_step",
        "late_motion",
        "cancel",
        "budget",
    ],
)
def test_settle_rejects_incomplete_or_unstable_cohorts_before_followup(defect, already_reset):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.native_realization import (
        NativeSettleSettings,
        SceneSettleRejected,
        initialize_and_settle,
    )

    steps, charges, resets = [], [], []
    flag = SimpleNamespace(any=lambda: False)
    obs = {"camera_obs": {} if defect == "camera" else {"wrist": 0}}

    def reset():
        assert not already_reset, "Already-reset preparation must never call reset"
        resets.append("reset")
        return obs, {}

    def step(action):
        assert charges[-1] == len(steps) + 1
        steps.append(action)
        return ({} if defect == "camera_after_step" else obs), 0, flag, flag, {}

    env = SimpleNamespace(
        unwrapped=SimpleNamespace(num_envs=1),
        reset=reset,
        step=step,
    )

    def charge(step):
        if defect == "cancel":
            raise RuntimeError("cancelled")
        if defect == "budget" and step == 2:
            raise RuntimeError("budget exhausted")
        charges.append(step)

    def measure(env, names):
        result = {
            name: {
                "linear_velocity_w": [0.0, 0.0, 0.0],
                "angular_velocity_w": [0.0, 0.0, 0.0],
            }
            for name in names
        }
        if defect == "angular":
            result["object"]["angular_velocity_w"][0] = 0.001
        if defect == "vector_norm":
            result["object"]["linear_velocity_w"] = [0.0008, 0.0008, 0.0]
        if defect == "other_subject" or (defect == "late_motion" and len(steps) == 2):
            result["robot"]["linear_velocity_w"][0] = 0.001
        if defect == "coverage":
            del result["robot"]
        return result

    settings = NativeSettleSettings(3, ("object", "robot"), 0.001, consecutive_steps=2, camera_names=("wrist",))
    with pytest.raises(RuntimeError) as failure:
        initialize_and_settle(
            env,
            settings=settings,
            charge_step=charge,
            sample_velocities=measure,
            hold_action_factory=lambda env: "hold",
            **({"initialized_observation": obs} if already_reset else {}),
        )
    if defect == "cancel":
        assert str(failure.value) == "cancelled" and steps == []
    elif defect == "budget":
        assert str(failure.value) == "budget exhausted" and steps == ["hold"]
    else:
        assert isinstance(failure.value, SceneSettleRejected)
        assert failure.value.report["reason"] == (
            "camera_unavailable"
            if defect in ("camera", "camera_after_step")
            else "invalid_measurement" if defect == "coverage" else "unsettled"
        )
        assert len(steps) == (0 if defect == "camera" else 1 if defect in ("coverage", "camera_after_step") else 3)
        assert failure.value.report["executed_steps"] == len(steps)
    assert len(charges) == len(steps)
    assert resets == ([] if already_reset else ["reset"])


def test_graph_requested_cameras_also_require_kit_activation():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.native_realization import build_native_environment
    from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg

    spec = SimpleNamespace(
        embodiment=SimpleNamespace(params={"enable_cameras": True}),
        to_arena_env=lambda **kw: pytest.fail("Cannot construct sensors without Kit activation"),
    )
    with pytest.raises(AssertionError, match="Kit"):
        build_native_environment(
            spec,
            builder_cfg=ArenaEnvBuilderCfg(),
            enable_cameras=False,
            kit_cameras_enabled=False,
        )


def test_native_adapter_import_does_not_initialize_runtime(monkeypatch):
    import builtins

    from isaaclab_arena.agentic_environment_generation.workflow import native_realization

    original = builtins.__import__

    def guard(name, *args, **kwargs):
        assert not name.startswith(("isaaclab.", "torch", "warp", "omni", "openai")), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    importlib.reload(native_realization)


@pytest.mark.parametrize(
    "settings",
    [
        dict(settle_steps=0),
        dict(settle_steps=True),
        dict(settle_steps=10001),
        dict(subjects=()),
        dict(subjects=("object", "object")),
        dict(subjects=["object"]),
        dict(angular_velocity_limit=float("nan")),
        dict(angular_velocity_limit=0.0),
        dict(consecutive_steps=3),
        dict(camera_names=("wrist", "wrist")),
    ],
)
def test_native_settle_settings_reject_invalid_frozen_bounds(settings):
    from isaaclab_arena.agentic_environment_generation.workflow.native_realization import NativeSettleSettings

    values = dict(settle_steps=2, subjects=("object",), angular_velocity_limit=0.001)
    values.update(settings)
    with pytest.raises(AssertionError):
        NativeSettleSettings(**values)


def _native_capture_settings():
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureSettings

    return NativeCaptureSettings.model_validate({
        "runtime_profile_id": "native-runtime-test",
        "capture_profile_id": "native-capture-test",
        "seed": 17,
        "timestep_seconds": 0.01,
        "decimation": 2,
        "settle_steps": 2,
        "settle_consecutive_steps": 2,
        "settle_angular_rad_per_s": 0.001,
        "window": {"start_step": 2, "end_step": 3},
        "subjects": [{
            "subject_id": "object",
            "scene_name": "object",
            "prim_path": "/World/object",
        }],
        "camera_keys": ["wrist_camera_rgb"],
        "criteria": [
            {
                "criterion_id": "speed",
                "kind": "runtime",
                "evidence_producer": "scene.linear-speed",
                "requirement": "required",
                "evaluator_version": "1",
                "required_modalities": ["state"],
                "coordinate_frames": ["world"],
                "observation_window": {"start_step": 2, "end_step": 3},
                "rubric": "maximum linear speed",
                "subjects": ["object"],
                "limit": {"operator": "le", "value": 0.001, "unit": "m_per_s"},
            },
            {
                "criterion_id": "visible",
                "kind": "visual",
                "evidence_producer": "scene.visible",
                "requirement": "required",
                "evaluator_version": "1",
                "required_modalities": ["rgb"],
                "coordinate_frames": ["wrist_camera_rgb"],
                "observation_window": {"start_step": 2, "end_step": 3},
                "rubric": "subject visible in every retained frame",
                "subjects": ["object"],
                "limit": {"operator": "eq", "value": 1.0, "unit": "boolean"},
            },
        ],
        "max_runtime_seconds": 10.0,
    })


def test_native_capture_settings_are_executable_frozen_sha_bound():
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureSettings

    settings = _native_capture_settings()
    assert settings.runtime_reference().settings_sha256 == settings.capture_reference().settings_sha256
    assert settings.digest() == hashlib.sha256(settings.canonical_bytes()).hexdigest()
    assert NativeCaptureSettings.model_validate_json(settings.canonical_bytes()) == settings
    assert settings.settle_settings().camera_names == ("wrist_camera_rgb",)
    assert settings.settle_settings().subjects == ("object",)
    assert settings.builder_config().seed == 17 and settings.builder_config().num_envs == 1
    with pytest.raises(ValueError):
        settings.seed = 18
    with pytest.raises(ValueError):
        settings.subjects[0].scene_name = "other"


def _native_capture_fixture(tmp_path, monkeypatch):
    import sys
    import time
    import torch
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow import native_realization
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import WorkflowContract
    from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import SceneEvidenceArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        SceneIntent,
        SceneReservation,
        candidate_record,
    )
    from isaaclab_arena.tests.test_environment_workflow_contracts import request

    settings = _native_capture_settings()
    raw = request()
    raw.update(
        criteria=[c.model_dump(mode="json") for c in settings.criteria],
        preserved=[],
        allowed_interventions=[],
    )
    raw["execution"].update(
        runtime=settings.runtime_reference().model_dump(),
        capture=settings.capture_reference().model_dump(),
        seed=17,
    )
    raw["budget"].update(max_realizations=1, max_observations=1, max_steps=3)
    raw["effects"]["allow_runtime"] = True
    contract = WorkflowContract.model_validate(raw)
    scene = {
        "embodiment": {"registry_name": "droid_abs_joint_pos", "params": {}},
        "objects": [{"id": "object", "registry_name": "banana_ycb_robolab", "params": {"prim_path": "/World/object"}}],
    }
    candidate = candidate_record("run", scene, source_id="source")
    fence = AttemptFence(
        run_id="run",
        intent_id="b" * 64,
        attempt_id="attempt",
        generation=1,
        owner_id="owner",
        owner_epoch=1,
    )
    registration = WorkerRegistration(
        registration_id="registered",
        fence=fence,
        host="host",
        boot="boot",
        pid=1,
        pgid=1,
        sid=1,
        start_ticks=1,
    )
    intent = SceneIntent(
        codec_version=2,
        intent_id=fence.intent_id,
        candidate_id=candidate.candidate_id,
        action="capture",
        status="released",
        released_at=1.0,
        worker_fence=fence,
        worker_registration=registration,
        reservation=SceneReservation(
            model_calls=0,
            model_tokens=0,
            cost_ceiling_usd=0.0,
            runtime_allowance_seconds=10.0,
            realizations=1,
            observations=1,
            steps=3,
        ),
    )
    events, charges = [], []

    class Scene(dict):
        env_origins = torch.tensor([[10.0, 0.0, 0.0]])

    body = SimpleNamespace(
        cfg=SimpleNamespace(prim_path="/World/object"),
        data=SimpleNamespace(
            root_pos_w=torch.tensor([[10.2, 0.0, 0.1]]),
            root_lin_vel_w=torch.zeros((1, 3)),
            root_ang_vel_w=torch.zeros((1, 3)),
        ),
    )
    base = SimpleNamespace(
        num_envs=1,
        scene=Scene(object=body),
        cfg=SimpleNamespace(sim=SimpleNamespace(dt=0.01), decimation=2),
    )

    class Env:
        unwrapped = base
        steps = 0
        terminal = False
        fail_step = False
        missing_camera = False

        def observation(self):
            image = torch.full((1, 240, 320, 3), self.steps, dtype=torch.uint8)
            return {"camera_obs": {} if self.missing_camera else {"wrist_camera_rgb": image}}

        def reset(self):
            events.append("reset")
            return self.observation(), {}

        def step(self, action):
            assert action == "measured-hold" and charges[-1] == self.steps + 1
            self.steps += 1
            if self.fail_step and self.steps == 3:
                raise RuntimeError("synthetic native step failure")
            end = self.terminal and self.steps == 3
            return (
                self.observation(),
                0,
                SimpleNamespace(any=lambda: end),
                SimpleNamespace(any=lambda: False),
                {},
            )

        def close(self):
            events.append("close")

    env = Env()
    spec = SimpleNamespace(
        embodiment=SimpleNamespace(params=scene["embodiment"]["params"]),
        to_dict=lambda: scene,
        model_dump=lambda **kwargs: scene,
        to_arena_env=lambda **kwargs: (events.append(("convert", kwargs)), "arena")[1],
    )

    class Builder:
        def __init__(self, arena, *, cfg):
            assert arena == "arena" and cfg.seed == 17 and cfg.num_envs == 1

        def make_registered(self):
            events.append("build")
            return env

    monkeypatch.setitem(
        sys.modules,
        "isaaclab_arena.environments.arena_env_builder",
        SimpleNamespace(ArenaEnvBuilder=Builder),
    )
    monkeypatch.setattr(native_realization, "build_droid_posture_hold", lambda env: "measured-hold")
    monkeypatch.setitem(sys.modules, "warp", SimpleNamespace(to_torch=lambda value: value))
    monkeypatch.setitem(sys.modules, "isaaclab.assets", SimpleNamespace(RigidObject=object))
    monkeypatch.setitem(
        sys.modules,
        "isaaclab.managers",
        SimpleNamespace(SceneEntityCfg=lambda name: name),
    )
    monkeypatch.setitem(
        sys.modules,
        "isaaclab_arena.tasks.predicates.object_settling",
        SimpleNamespace(objects_settled=lambda *args, **kwargs: torch.tensor(True)),
    )
    monkeypatch.setitem(
        sys.modules,
        "isaaclab_arena.tasks.predicates.spatial",
        SimpleNamespace(object_on_destination=lambda *args, **kwargs: pytest.fail("No invented contacts")),
    )
    from isaaclab_arena.tasks.predicates import predicate_utils

    monkeypatch.setattr(predicate_utils, "wp", sys.modules["warp"])
    area = ArtifactArea.create(tmp_path / "artifacts", store_id="store", registry_id="registry")
    artifacts = SceneEvidenceArtifacts(area)
    kwargs = dict(
        spec=spec,
        intent=intent,
        candidate=candidate,
        contract=contract,
        worker_initialized=True,
        kit_cameras_enabled=True,
        deadline=time.monotonic() + 10,
        charge_step=charges.append,
        check_active=lambda: None,
    )
    return SimpleNamespace(
        settings=settings,
        area=area,
        artifacts=artifacts,
        env=env,
        events=events,
        charges=charges,
        kwargs=kwargs,
    )


def test_native_capture_producer_joins_actual_capture_sampler_numeric_receipt(tmp_path, monkeypatch):
    import base64
    import io

    from PIL import Image

    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureProducer
    from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import visual_request

    fixture = _native_capture_fixture(tmp_path, monkeypatch)
    producer = NativeCaptureProducer(
        settings=fixture.settings,
        artifacts=fixture.artifacts,
        protect=lambda value: None,
        output_root=tmp_path / "frames",
    )
    try:
        result = producer(**fixture.kwargs)
        payload = fixture.artifacts.verified_payload(result.receipt, protect=lambda value: None)
        assert fixture.events == [
            ("convert", {"enable_cameras": True}),
            "build",
            "reset",
            "close",
        ]
        assert fixture.charges == [1, 2, 3] and fixture.env.steps == 3
        assert [s["step"] for s in payload["samples"]] == [2, 3]
        assert payload["samples"][0]["origin_w"] == [10.0, 0.0, 0.0]
        assert payload["provenance"] == "native-unverified"
        assert payload["settings"] == fixture.settings.model_dump(mode="json")
        assert payload["settings_sha256"] == fixture.settings.digest()
        assert payload["diagnostics"]["settle"]["all_objects_settled"] is True
        assert payload["diagnostics"]["charged_steps"] == 3
        assert result.observation.evidence[0].verdict == "established"
        assert "native_sampler_not_independently_validated" in result.observation.evidence[0].limitations
        assert len(result.observation.evidence) == 1  # No fabricated visual/model verdict.
        request = visual_request(
            fixture.settings.criteria[1],
            result.receipt.candidate,
            result.receipt.cohort,
            fixture.artifacts,
            result.receipt,
            protect=lambda value: None,
        )
        assert request["step_window"] == [2, 3]
        for frame in payload["frames"]:
            raw = base64.b64decode(frame["bytes"])
            assert hashlib.sha256(raw).hexdigest() == frame["sha256"]
            assert Image.open(io.BytesIO(raw)).size == (128, 96)
            retained_path = (
                tmp_path
                / "frames"
                / result.receipt.cohort.realization_id
                / f'step_{frame["step"]:06d}_wrist_camera_rgb.png'
            )
            assert raw == retained_path.read_bytes()
        assert (
            producer.replay(
                result.receipt,
                contract=fixture.kwargs["contract"],
                candidate=fixture.kwargs["candidate"],
            )
            == result.observation
        )
    finally:
        fixture.area.close()


def test_native_capture_accepts_exact_generation_serialization_without_dropping_nulls(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureProducer
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import candidate_record
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena.tests.utils.agentic_environment_generation import minimal_spec_dict

    raw_spec = minimal_spec_dict()
    raw_spec["embodiment"]["registry_name"] = "droid_abs_joint_pos"
    raw_spec["objects"].append(
        {"id": "object", "registry_name": "banana_ycb_robolab", "params": {"prim_path": "/World/object"}}
    )
    spec = ArenaEnvGraphSpec.model_validate(raw_spec)
    fixture = _native_capture_fixture(tmp_path, monkeypatch)
    producer = NativeCaptureProducer(
        settings=fixture.settings,
        artifacts=fixture.artifacts,
        protect=lambda _: None,
        output_root=tmp_path / "frames",
    )
    try:
        for payload in (spec.model_dump(mode="json"), spec.to_dict()):
            candidate = candidate_record("run", payload, source_id="generation")
            producer._check_spec(spec, candidate, True)
        changed = spec.model_copy(update={"env_name": "different"})
        with pytest.raises(ValueError, match="candidate"):
            producer._check_spec(changed, candidate, True)
        assert fixture.events == []
    finally:
        fixture.area.close()


@pytest.mark.parametrize("mapping", ["swapped", "collision", "prim", "alias"])
def test_native_subject_mapping_follows_graph_asset_identity_before_construction(tmp_path, monkeypatch, mapping):
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureProducer
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import candidate_record
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena.tests.utils.agentic_environment_generation import minimal_spec_dict

    raw = minimal_spec_dict()
    raw["embodiment"]["registry_name"] = "droid_abs_joint_pos"
    raw["objects"].extend([
        {
            "id": "object",
            "registry_name": "banana_ycb_robolab",
            "params": {"instance_name": "object", "prim_path": "/World/object"},
        },
        {
            "id": "distractor",
            "registry_name": "plate_large_vomp_robolab",
            "params": {"instance_name": "other", "prim_path": "/World/other"},
        },
    ])
    target, distractor = raw["objects"][-2:]
    if mapping == "swapped":
        target["params"], distractor["params"] = distractor["params"], target["params"]
    elif mapping == "collision":
        distractor["params"] = dict(target["params"])
    elif mapping == "prim":
        target["params"]["prim_path"] = "/World/other"
    else:
        target["params"]["instance_name"] = "measured_object"
    spec = ArenaEnvGraphSpec.model_validate(raw)
    f = _native_capture_fixture(tmp_path, monkeypatch)
    settings = f.settings
    if mapping == "alias":
        settings = settings.model_copy(
            update={"subjects": (settings.subjects[0].model_copy(update={"scene_name": "measured_object"}),)}
        )
    producer = NativeCaptureProducer(
        settings=settings, artifacts=f.artifacts, protect=lambda _: None, output_root=tmp_path / "frames"
    )
    candidate = candidate_record("run", spec.model_dump(mode="json"), source_id="generation")
    try:
        if mapping == "alias":
            producer._check_spec(spec, candidate, True)
        else:
            with pytest.raises(ValueError, match="mapping"):
                producer._check_spec(spec, candidate, True)
        assert f.events == []
    finally:
        f.area.close()


@pytest.mark.parametrize("fault", ["unsettled", "step", "camera", "cancel", "clock", "runtime", "prim"])
def test_native_capture_failures_retain_diagnostics_before_cleanup(tmp_path, monkeypatch, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import (
        NativeCaptureFailed,
        NativeCaptureProducer,
    )

    fixture = _native_capture_fixture(tmp_path, monkeypatch)
    if fault == "unsettled":
        fixture.env.unwrapped.scene["object"].data.root_lin_vel_w[:] = 0.001
    if fault == "step":
        fixture.env.fail_step = True
    if fault == "camera":
        fixture.env.missing_camera = True
    if fault == "runtime":
        fixture.env.unwrapped.cfg.sim.dt = 0.02
    if fault == "prim":
        fixture.env.unwrapped.scene["object"].cfg.prim_path = "/Wrong"
    if fault in ("cancel", "clock"):

        def check():
            if fixture.env.steps == 2:
                if fault == "cancel":
                    raise RuntimeError("revoked")
                import time

                monkeypatch.setattr(time, "monotonic", lambda: fixture.kwargs["deadline"] + 1)

        fixture.kwargs["check_active"] = check
    writes = []
    real_write = fixture.artifacts.write

    def write(*args, **kwargs):
        assert "close" not in fixture.events
        receipt = real_write(*args, **kwargs)
        writes.append(receipt)
        return receipt

    monkeypatch.setattr(fixture.artifacts, "write", write)
    producer = NativeCaptureProducer(
        settings=fixture.settings,
        artifacts=fixture.artifacts,
        protect=lambda value: None,
        output_root=tmp_path / "frames",
    )
    try:
        with pytest.raises(NativeCaptureFailed) as caught:
            producer(**fixture.kwargs)
        assert fixture.events[-1] == "close" and len(writes) == 1
        assert caught.value.receipt == writes[0]
        payload = fixture.artifacts.verified_payload(writes[0], protect=lambda value: None)
        assert payload["diagnostics"]["status"] == "failed"
        assert payload["diagnostics"]["charged_steps"] == len(fixture.charges)
        if fault == "unsettled":
            assert payload["diagnostics"]["settle"]["reason"] == "unsettled"
        if fault == "step":
            assert [s["step"] for s in payload["samples"]] == [2]
            assert [f["step"] for f in payload["frames"]] == [2]
        with pytest.raises(ValueError, match="incomplete"):
            producer.replay(
                writes[0],
                contract=fixture.kwargs["contract"],
                candidate=fixture.kwargs["candidate"],
            )
    finally:
        fixture.area.close()


def test_native_capture_storage_failure_is_not_retried_and_still_closes(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import (
        NativeCaptureFailed,
        NativeCaptureProducer,
    )

    fixture = _native_capture_fixture(tmp_path, monkeypatch)
    writes = []

    def fail(*args, **kwargs):
        writes.append(1)
        raise OSError("storage unavailable")

    monkeypatch.setattr(fixture.artifacts, "write", fail)
    producer = NativeCaptureProducer(
        settings=fixture.settings,
        artifacts=fixture.artifacts,
        protect=lambda value: None,
        output_root=tmp_path / "frames",
    )
    try:
        with pytest.raises(NativeCaptureFailed) as caught:
            producer(**fixture.kwargs)
        assert isinstance(caught.value.__cause__, OSError)
        assert caught.value.receipt is None and writes == [1]
        assert fixture.events[-1] == "close"
    finally:
        fixture.area.close()


@pytest.mark.parametrize(
    "fault",
    [
        "runtime_ref",
        "capture_ref",
        "seed",
        "unreleased",
        "unregistered",
        "kit",
        "worker",
        "deadline",
        "budget",
        "candidate",
        "graph_camera",
    ],
)
def test_native_capture_preflight_has_no_native_effects(tmp_path, monkeypatch, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureProducer

    fixture = _native_capture_fixture(tmp_path, monkeypatch)
    kwargs = fixture.kwargs
    if fault in ("runtime_ref", "capture_ref", "seed"):
        execution = kwargs["contract"].execution
        changes = (
            {"seed": 99}
            if fault == "seed"
            else {fault.removesuffix("_ref"): execution.runtime.model_copy(update={"settings_sha256": "f" * 64})}
        )
        kwargs["contract"] = kwargs["contract"].model_copy(update={"execution": execution.model_copy(update=changes)})
    if fault == "unreleased":
        kwargs["intent"] = kwargs["intent"].model_copy(update={"status": "reserved"})
    if fault == "unregistered":
        kwargs["intent"] = kwargs["intent"].model_copy(update={"worker_registration": None})
    if fault == "kit":
        kwargs["kit_cameras_enabled"] = False
    if fault == "worker":
        kwargs["worker_initialized"] = False
    if fault == "deadline":
        kwargs["deadline"] = 0.0
    if fault == "budget":
        intent = kwargs["intent"]
        kwargs["intent"] = intent.model_copy(update={"reservation": intent.reservation.model_copy(update={"steps": 2})})
    if fault == "candidate":
        kwargs["candidate"] = kwargs["candidate"].model_copy(update={"digest": "f" * 64})
    if fault == "graph_camera":
        kwargs["spec"].embodiment.params["enable_cameras"] = False
    producer = NativeCaptureProducer(
        settings=fixture.settings,
        artifacts=fixture.artifacts,
        protect=lambda value: None,
        output_root=tmp_path / "frames",
    )
    try:
        with pytest.raises((ValueError, TimeoutError)):
            producer(**kwargs)
        assert fixture.events == [] and fixture.charges == []
        assert not (tmp_path / "frames").exists()
    finally:
        fixture.area.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("camera_keys", ["wrist"]),
        ("camera_keys", ["wrist_camera_depth"]),
        ("camera_keys", ["../wrist_camera_rgb"]),
        ("camera_keys", ["wrist_camera_rgb", "wrist_camera_rgb"]),
        ("window", {"start_step": 0, "end_step": 3}),
        ("settle_steps", True),
        ("settle_consecutive_steps", 3),
        ("evaluator_linear_m_per_s", 0.1),
        ("image_transform", {"max_edge": 129}),
        ("max_payload_bytes", 4194304),
        (
            "contacts",
            [{
                "subject_id": "object",
                "destination_id": "table",
                "sensor_name": "guessed",
            }],
        ),
    ],
)
def test_native_capture_settings_reject_unsupported_camera_and_frozen_bounds(field, value):
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureSettings

    raw = _native_capture_settings().model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValueError):
        NativeCaptureSettings.model_validate(raw)


def test_native_capture_parent_import_is_runtime_free(monkeypatch):
    import builtins

    from isaaclab_arena.agentic_environment_generation.workflow import native_capture

    original = builtins.__import__

    def guard(name, *args, **kwargs):
        assert not name.startswith(("isaaclab.", "torch", "warp", "omni", "openai", "PIL")), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    importlib.reload(native_capture)
    _native_capture_settings()


def test_native_capture_bounds_entire_envelope_before_effects():
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureSettings

    raw = _native_capture_settings().model_dump(mode="json")
    raw["settle_steps"] = 256
    raw["window"] = {"start_step": 256, "end_step": 257}
    raw["subjects"] = [
        {
            "subject_id": f"object{i}",
            "scene_name": f"object{i}",
            "prim_path": f"/World/object{i}",
        }
        for i in range(16)
    ]
    criterion = raw["criteria"][0]
    raw["criteria"] = [
        dict(
            criterion,
            criterion_id=f"speed{i}",
            subjects=[f"object{i}"],
            observation_window=raw["window"],
        )
        for i in range(16)
    ]
    raw["camera_keys"] = []
    with pytest.raises(ValueError, match="whole payload"):
        NativeCaptureSettings.model_validate(raw)


@pytest.mark.parametrize("terminal", [False, True])
def test_native_capture_numeric_only_composes_assessment_and_terminal_is_unknown(tmp_path, monkeypatch, terminal):
    from isaaclab_arena.agentic_environment_generation.workflow.evidence import assess_scene_evidence
    from isaaclab_arena.agentic_environment_generation.workflow.evidence_contracts import project_required_criteria
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import (
        NativeCaptureProducer,
        NativeCaptureSettings,
    )

    f = _native_capture_fixture(tmp_path, monkeypatch)
    f.env.terminal = terminal
    raw = f.settings.model_dump(mode="json")
    raw.update(criteria=raw["criteria"][:1], camera_keys=[])
    settings = NativeCaptureSettings.model_validate(raw)
    contract = f.kwargs["contract"]
    contract = contract.model_copy(
        update={
            "criteria": settings.criteria,
            "execution": contract.execution.model_copy(
                update={
                    "runtime": settings.runtime_reference(),
                    "capture": settings.capture_reference(),
                }
            ),
        }
    )
    f.kwargs.update(contract=contract, kit_cameras_enabled=False)
    producer = NativeCaptureProducer(
        settings=settings,
        artifacts=f.artifacts,
        protect=lambda value: None,
        output_root=tmp_path / "frames",
    )
    try:
        result = producer(**f.kwargs)
        payload = f.artifacts.verified_payload(result.receipt, protect=lambda value: None)
        assert payload["frames"] == []
        assert payload["diagnostics"]["capture"]["terminal_image_unavailable"] is terminal
        assert result.observation.evidence[0].verdict == ("inconclusive" if terminal else "established")
        assessment = assess_scene_evidence(
            required=project_required_criteria(contract),
            candidate=result.receipt.candidate,
            evidence=result.observation.evidence,
            selected_cohort=result.receipt.cohort,
            verified_manifest_digests=frozenset(result.observation.verified_manifest_digests),
        )
        assert assessment.status == ("inconclusive" if terminal else "established")
        assert f.charges == [1, 2, 3] and f.events[-1] == "close"
        with pytest.raises(ValueError, match="cannot be repeated"):
            producer(**f.kwargs)
    finally:
        f.area.close()


@pytest.mark.parametrize("fault", ["float", "rgba", "multi_env", "source_bound"])
def test_native_rgb_transform_refuses_implicit_coercions(fault):
    import numpy as np

    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import (
        NativeImageTransform,
        encode_native_rgb,
    )

    pixels = np.zeros((1, 4, 6, 3), dtype=np.uint8)
    settings = NativeImageTransform()
    if fault == "float":
        pixels = pixels.astype(float)
    elif fault == "rgba":
        pixels = np.zeros((1, 4, 6, 4), dtype=np.uint8)
    elif fault == "multi_env":
        pixels = np.zeros((2, 4, 6, 3), dtype=np.uint8)
    else:
        settings = NativeImageTransform(max_source_pixels=20)
    with pytest.raises(ValueError):
        encode_native_rgb(pixels, settings)


@pytest.mark.parametrize("step_failure", [False, True])
def test_native_capture_cleanup_failure_never_returns_success(tmp_path, monkeypatch, step_failure):
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import (
        NativeCaptureFailed,
        NativeCaptureProducer,
    )

    f = _native_capture_fixture(tmp_path, monkeypatch)
    f.env.fail_step = step_failure

    def close():
        f.events.append("close")
        raise RuntimeError("synthetic close failure")

    monkeypatch.setattr(f.env, "close", close)
    producer = NativeCaptureProducer(
        settings=f.settings, artifacts=f.artifacts, protect=lambda value: None, output_root=tmp_path / "frames"
    )
    try:
        with pytest.raises(NativeCaptureFailed) as caught:
            producer(**f.kwargs)
        assert caught.value.cleanup_failed and f.events[-1] == "close"
        assert caught.value.receipt is not None
        payload = f.artifacts.verified_payload(caught.value.receipt, protect=lambda value: None)
        assert payload["diagnostics"]["status"] == ("failed" if step_failure else "complete")
        if step_failure:
            assert str(caught.value.__cause__) == "synthetic native step failure"
    finally:
        f.area.close()


def test_native_capture_replay_checks_actual_retained_bytes(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow.native_capture import NativeCaptureProducer

    f = _native_capture_fixture(tmp_path, monkeypatch)
    producer = NativeCaptureProducer(
        settings=f.settings, artifacts=f.artifacts, protect=lambda value: None, output_root=tmp_path / "frames"
    )
    try:
        result = producer(**f.kwargs)
        path = tmp_path / "artifacts" / result.receipt.relative_directory / "evidence.json"
        path.write_bytes(path.read_bytes() + b" ")
        with pytest.raises(ValueError):
            producer.replay(result.receipt, contract=f.kwargs["contract"], candidate=f.kwargs["candidate"])
    finally:
        f.area.close()
