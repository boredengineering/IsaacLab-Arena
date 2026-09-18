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
