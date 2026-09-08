# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

import torch
from types import SimpleNamespace

import pytest

from isaaclab_arena.evaluation import policy_runner


def test_recorded_environment_routes_hdf5_to_run_directory(tmp_path):
    cfg = SimpleNamespace(recorders=SimpleNamespace(dataset_export_dir_path="/tmp/isaaclab/logs"))
    kwargs = {"variation_recorder": object()}
    calls = []
    builder = SimpleNamespace(
        compose_manager_cfg=lambda: (cfg, kwargs),
        make_registered=lambda **kw: calls.append(kw) or "environment",
    )
    assert policy_runner.make_recorded_environment(builder, str(tmp_path), None) == "environment"
    assert cfg.recorders.dataset_export_dir_path == str(tmp_path)
    assert calls == [{"env_cfg": cfg, "env_kwargs": kwargs, "render_mode": None}]


def test_termination_during_settle_rejects_the_run(monkeypatch):
    env = SimpleNamespace()
    env.unwrapped = SimpleNamespace(scene={})
    env.step = lambda action: (None, None, torch.tensor([True]), torch.tensor([False]), {})
    monkeypatch.setattr(policy_runner, "build_neutral_hold_action", lambda base: None)
    with pytest.raises(RuntimeError, match="terminated during settling"):
        policy_runner.verify_and_settle_scene(env)


def test_final_episode_does_not_start_an_unrequested_settle(monkeypatch):
    calls = []

    def settle(*args, **kwargs):
        calls.append(1)
        assert len(calls) == 1, "Settled after the final requested episode"
        return {}, None

    monkeypatch.setattr(policy_runner, "verify_and_settle_scene", settle)
    env = SimpleNamespace()
    env.unwrapped = SimpleNamespace(cfg=SimpleNamespace(metrics=None), get_language_instruction=lambda: "task")
    env.reset = lambda: (None, {})
    env.step = lambda action: (None, None, torch.tensor([True]), torch.tensor([False]), {})
    policy = SimpleNamespace(
        reset=lambda **kwargs: None, set_task_description=lambda text: None, get_action=lambda *a: None
    )
    policy_runner.rollout_policy(env, policy, num_steps=None, num_episodes=1)
    assert calls == [1]
