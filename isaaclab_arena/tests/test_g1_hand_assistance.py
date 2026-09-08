# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Torch-only assistance contracts, run using Isaac Sim's Python (no app/server)."""

import json
import torch

import pytest


def test_explicit_privileged_config_and_hard_limits(tmp_path):
    from isaaclab_arena_gr00t.policy.g1_hand_assistance import AssistanceCfg

    path = tmp_path / "assistance.json"
    path.write_text(json.dumps({"privileged_state": True, "mode": "observe", "hand": "left"}))
    cfg = AssistanceCfg.from_json(str(path))
    assert cfg.downward_offset_m == 0.01
    assert cfg.hand_body == "left_hand_middle_1_link"
    for invalid in (
        {},
        {"privileged_state": False},
        {"downward_offset_m": 0.031},
        {"residual_joint_bound": 0.151},
        {"max_active_s": 2.01},
        {"damping": 0},
        {"gate_max_delay_s": 0.6},
        {"xy_window_m": float("nan")},
        {"hand": "right"},
        {"surprise": 1},
    ):
        path.write_text(json.dumps({"privileged_state": True, **invalid} if invalid else {}))
        with pytest.raises((AssertionError, TypeError, ValueError)):
            AssistanceCfg.from_json(str(path))


def test_dls_downward_bounded_soft_limit_slew_intersection():
    from isaaclab_arena_gr00t.policy.g1_hand_assistance import AssistanceCfg, bounded_residual

    cfg = AssistanceCfg(privileged_state=True)
    jac = torch.eye(6, 7)
    q = torch.zeros(7)
    limits = torch.tensor([[-1.0, 1.0]] * 7)
    previous = torch.zeros(7)
    delta, reason = bounded_residual(jac, q, limits, previous, 0.01, cfg)
    assert reason == "accepted"
    assert -0.005001 <= delta[2] < 0
    assert torch.linalg.vector_norm(delta) <= cfg.residual_norm_bound
    assert torch.all(delta.abs() <= cfg.residual_joint_bound)
    limits[2, 0] = -0.002
    delta, reason = bounded_residual(jac, q, limits, previous, 0.01, cfg)
    assert reason == "accepted" and delta[2] >= -0.002
    q[2] = -2
    delta, reason = bounded_residual(jac, q, limits, previous, 0.01, cfg)
    assert reason == "empty_intersection" and torch.equal(delta, previous)
    q.zero_()
    jac[0, 0] = float("nan")
    delta, reason = bounded_residual(jac, q, limits, previous, 0.01, cfg)
    assert reason == "nonfinite" and torch.equal(delta, previous)


def _inputs():
    return dict(
        raw=torch.linspace(-0.1, 0.2, 50).reshape(1, 50),
        measured=torch.zeros(43),
        jacobian=torch.eye(6, 7),
        limits=torch.tensor([[-1.0, 1.0]] * 7),
        hand_pos=torch.tensor([0.0, 0.0, 0.05]),
        object_pos=torch.zeros(3),
        dt=0.02,
    )


def test_observe_is_bitwise_noop_with_full_active_vectors_and_reset():
    from isaaclab_arena_gr00t.policy.g1_hand_assistance import AssistanceCfg, HandAssistance

    core = HandAssistance(AssistanceCfg(privileged_state=True))
    inputs = _inputs()
    original = inputs["raw"].clone()
    executed, trace = core.apply(**inputs)
    assert torch.equal(executed, original) and executed.data_ptr() != inputs["raw"].data_ptr()
    for group in ("arm", "hand"):
        for source in ("raw", "executed", "measured"):
            assert len(trace[f"{source}_{group}"]) == 7
    assert trace["privileged_state"] is True and trace["step"] == 0
    assert trace["hand_reference"] == "finger_origin_not_grasp_centre"
    core.apply(**inputs)
    core.reset()
    _, trace = core.apply(**inputs)
    assert trace["epoch"] == 1 and trace["step"] == 0
    assert trace["correction"] == [0.0] * 7


def test_offset_only_changes_left_arm_and_stops_on_lift_window_timeout():
    from isaaclab_arena_gr00t.policy.g1_hand_assistance import ARM_SLOTS, AssistanceCfg, HandAssistance

    inputs = _inputs()
    core = HandAssistance(AssistanceCfg(privileged_state=True, mode="offset", max_active_s=0.06))
    unchanged = [i for i in range(50) if i not in ARM_SLOTS]
    out, trace = core.apply(**inputs)
    assert not torch.equal(out, inputs["raw"])
    assert torch.equal(out[:, unchanged], inputs["raw"][:, unchanged])
    assert trace["residual_reason"] == "accepted"
    out2, _ = core.apply(**inputs)
    assert torch.allclose(out2, out)  # q_policy + delta, not accumulated targets
    inputs["hand_pos"][0] = 1
    out, trace = core.apply(**inputs)
    assert torch.equal(out, inputs["raw"]) and trace["residual_reason"] == "outside_window"
    inputs["hand_pos"][0] = 0
    out, trace = core.apply(**inputs)
    assert torch.equal(out, inputs["raw"]) and trace["residual_reason"] == "active_timeout"
    core.reset()
    core.apply(**inputs)
    inputs["object_pos"][2] = 0.009
    out, trace = core.apply(**inputs)
    assert torch.equal(out, inputs["raw"]) and trace["residual_reason"] == "object_lifted"
    inputs["object_pos"][2] = 0
    out, _ = core.apply(**inputs)
    assert torch.equal(out, inputs["raw"])  # lift stop is permanent until reset


@pytest.mark.parametrize("mode", ["gate", "combined"])
def test_gate_measured_open_deviation_dwell_latch_timeout_reset(mode):
    from isaaclab_arena_gr00t.policy.g1_hand_assistance import HAND_SLOTS, AssistanceCfg, HandAssistance

    cfg = AssistanceCfg(privileged_state=True, mode=mode)
    core = HandAssistance(cfg)
    inputs = _inputs()
    inputs["measured"][HAND_SLOTS] = 0.2  # post-settle measured open, NOT zeros
    inputs["raw"][0, HAND_SLOTS] = 0.2
    out, trace = core.apply(**inputs)
    assert not trace["closure_requested"] and not trace["gate_activated"]
    inputs["raw"][0, HAND_SLOTS] = 0.7
    out, trace = core.apply(**inputs)
    assert trace["gate_activated"] and torch.allclose(out[0, HAND_SLOTS], torch.full((7,), 0.2))
    inputs["hand_pos"][2] = 0.02
    core.apply(**inputs)
    inputs["hand_pos"][0] = 1.0
    _, trace = core.apply(**inputs)
    assert trace["ready_dwell_s"] == 0 and not trace["gate_permission_latched"]
    inputs["hand_pos"][0] = 0.0
    for _ in range(3):
        _, trace = core.apply(**inputs)
    assert trace["gate_permission_latched"]
    inputs["hand_pos"][0] = 1.0
    for _ in range(6):
        out, trace = core.apply(**inputs)
    assert trace["gate_authority"] == 1.0 and trace["gate_permission_latched"]
    assert torch.equal(out[0, HAND_SLOTS], inputs["raw"][0, HAND_SLOTS])
    core.reset()
    inputs["hand_pos"][0] = 1.0  # never ready; bounded delay including release ramp
    authorities = []
    for _ in range(22):
        out, trace = core.apply(**inputs)
        authorities.append(trace["gate_authority"])
    assert trace["gate_timed_out"] and not trace["gate_permission_latched"]
    assert any(0 < a < 1 for a in authorities) and authorities[-1] == 1
    assert torch.equal(out[0, HAND_SLOTS], inputs["raw"][0, HAND_SLOTS])
    core.reset()
    inputs["measured"][HAND_SLOTS] = -0.2
    out, trace = core.apply(**inputs)
    assert torch.allclose(out[0, HAND_SLOTS], torch.full((7,), -0.2))
    assert not trace["gate_timed_out"] and trace["step"] == 0


@pytest.mark.parametrize("fixed", [True, False])
@pytest.mark.parametrize("mode", ["offset", "observe"])
def test_registered_composition_adapter_scheduled_clone_mapping_trace_cleanup(tmp_path, monkeypatch, fixed, mode):
    import yaml
    from types import SimpleNamespace as NS

    from isaaclab_arena.assets.register import _policy_cfg_type_from_policy
    from isaaclab_arena_gr00t.policy import gr00t_assisted_policy as module

    names_path = "isaaclab_arena_gr00t/embodiments/g1/43dof_joint_space.yaml"
    with open(names_path) as stream:
        mapping = yaml.safe_load(stream)["joints"]
    names = sorted(mapping, key=mapping.get)
    cached = torch.zeros(1, 50)
    cached[0, 43:] = torch.arange(7)

    class FakeBase:
        is_remote = False  # This client does not own the runner's managed-server lifecycle.

        def __init__(self, config):
            self.robot_action_joints_config = mapping.copy()
            self.action_dim = 50
            self.policy_config = NS(bilateral_mirror=False, task_mode_name="g1_locomanipulation")
            self.calls = self.resets = self.closes = 0

        def get_action(self, env, observation):
            self.calls += 1
            return cached  # models a VIEW from the chunk scheduler

        def reset(self, env_ids=None):
            self.resets += 1

        def close(self):
            self.closes += 1

        def set_task_description(self, text):
            return text

    monkeypatch.setattr(module, "Gr00tRemoteClosedloopPolicy", FakeBase)
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({"privileged_state": True, "mode": mode, "rgb_checksum": True}))
    trace_path = tmp_path / "trace.jsonl"
    cfg = module.Gr00tAssistedPolicyCfg(
        policy_config_yaml_path="unused",
        policy_device="cpu",
        assistance_config_path=str(cfg_path),
        assistance_trace_path=str(trace_path),
    )
    assert _policy_cfg_type_from_policy(module.Gr00tAssistedPolicy) is module.Gr00tAssistedPolicyCfg
    base_dofs = 0 if fixed else 6
    jac = torch.full((1, 3, 6, 43 + base_dofs), float("nan"))
    row = 0 if fixed else 1
    jac[0, row] = 0
    arm_slots = [11, 15, 19, 21, 23, 25, 27]
    jac[0, row][:, [i + base_dofs for i in arm_slots]] = torch.eye(6, 7)
    robot = NS(
        joint_names=names,
        body_names=["root", "left_hand_middle_1_link", "other"],
        is_fixed_base=fixed,
        num_base_dofs=base_dofs,
    )
    robot.data = NS(
        joint_pos=NS(torch=torch.full((1, 43), 0.2)),
        soft_joint_pos_limits=NS(torch=torch.tensor([[[-1.0, 1.0]] * 43])),
        body_link_jacobian_w=NS(torch=jac),
        body_link_pos_w=NS(torch=torch.tensor([[[0.0, 0.0, 0.0], [0.0, 0.0, 0.05], [1.0, 1.0, 1.0]]])),
    )
    term = type("G1DecoupledWBCJointAction", (), {})()
    term._joint_names, term._asset, term.action_dim = names, robot, 50
    env = NS(
        num_envs=1,
        step_dt=0.02,
        common_step_counter=123,
        scene={"robot": robot, "red_apple": NS(data=NS(root_link_pos_w=NS(torch=torch.zeros(1, 3))))},
        action_manager=NS(active_terms=["g1_action"], get_term=lambda name: term),
    )
    wrapped = NS(unwrapped=env)
    obs = {"camera_obs": {"robot_head_cam_rgb": torch.ones(1, 4, 4, 3, dtype=torch.uint8)}}
    policy = module.Gr00tAssistedPolicy(cfg)
    # True selects shutdown_remote/remote_kill_on_exit in policy_runner, which
    # this independently served GR00T client deliberately does not implement.
    assert not policy.is_remote
    assert policy.set_task_description("apple") == "apple"
    robot.joint_names = list(reversed(names))
    with pytest.raises(AssertionError, match="Robot order"):
        policy.get_action(wrapped, obs)
    robot.joint_names = names
    wrong_term = type("G1DecoupledWBCPinkAction", (), {})()
    env.action_manager.get_term = lambda name: wrong_term
    with pytest.raises(AssertionError, match="Pink/IK"):
        policy.get_action(wrapped, obs)
    assert policy.base.calls == 0
    env.action_manager.get_term = lambda name: term
    out = policy.get_action(wrapped, obs)
    assert cached[0, 19] == 0 and out.data_ptr() != cached.data_ptr()
    if mode == "offset":
        assert out[0, 19] < 0
    else:
        assert torch.equal(out, cached)
    assert torch.equal(out[0, 43:], cached[0, 43:])
    assert policy.base.calls == 1
    policy.reset()
    policy.get_action(wrapped, obs)
    obs["camera_obs"]["robot_head_cam_rgb"].zero_()
    env.common_step_counter = 124
    jac[0, row, 0, arm_slots[0] + base_dofs] = float("nan")
    rejected = policy.get_action(wrapped, obs)
    assert torch.equal(rejected, cached)
    policy.close()
    assert policy.base.resets == 1 and policy.base.closes == 1
    records = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert records[0]["config"]["privileged_state"] is True
    assert records[1]["frame"] == 123 and records[2]["epoch"] == 1
    assert records[1]["rgb_checksum"] == records[2]["rgb_checksum"]
    assert records[1]["initial_open_hand"] == pytest.approx([0.2] * 7)
    assert records[3]["rgb_checksum"] != records[2]["rgb_checksum"]
    assert records[3]["residual_reason"] == ("nonfinite" if mode == "offset" else "disabled")
    assert records[3]["predicted_correction_world"][0] is None
    assert records[3]["frame"] == 124
    with pytest.raises(FileExistsError):
        module.Gr00tAssistedPolicy(cfg)


def test_dls_rejects_lateral_and_joint_norm_after_bound_projection():
    from isaaclab_arena_gr00t.policy.g1_hand_assistance import AssistanceCfg, bounded_residual

    q = torch.zeros(7)
    previous = torch.zeros(7)
    limits = torch.tensor([[-1.0, 1.0]] * 7)
    jac = torch.eye(6, 7)
    cfg = AssistanceCfg(privileged_state=True, residual_norm_bound=0.001)
    delta, reason = bounded_residual(jac, q, limits, previous, 0.02, cfg)
    assert reason == "norm_bound" and not delta.any()
    cfg = AssistanceCfg(privileged_state=True)
    limits[0] = torch.tensor([0.004, 1.0])
    delta, reason = bounded_residual(jac, q, limits, previous, 0.02, cfg)
    assert reason == "lateral_bound" and not delta.any()
    jac.zero_()
    limits[0, 0] = -1.0
    delta, reason = bounded_residual(jac, q, limits, previous, 0.02, cfg)
    assert reason == "not_downward" and not delta.any()


def test_adapter_rejects_unsupported_contracts_before_connect(tmp_path, monkeypatch):
    from dataclasses import replace

    from isaaclab_arena_gr00t.policy import gr00t_assisted_policy as module

    def forbidden_base(config):
        pytest.fail("Unsupported configuration must not connect to the policy server")

    monkeypatch.setattr(module, "Gr00tRemoteClosedloopPolicy", forbidden_base)
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text('{"privileged_state": true}')
    cfg = module.Gr00tAssistedPolicyCfg(
        policy_config_yaml_path="unused",
        assistance_config_path=str(cfg_path),
        assistance_trace_path=str(tmp_path / "trace.jsonl"),
    )
    for invalid in (
        replace(cfg, num_envs=2),
        replace(cfg, scheduler="synced_batch"),
        replace(cfg, assistance_config_path=""),
        replace(cfg, assistance_trace_path=""),
    ):
        with pytest.raises(AssertionError):
            module.Gr00tAssistedPolicy(invalid)
    assert not (tmp_path / "trace.jsonl").exists()


def test_late_readiness_cannot_extend_gate_deadline():
    from isaaclab_arena_gr00t.policy.g1_hand_assistance import AssistanceCfg, HandAssistance

    core = HandAssistance(AssistanceCfg(privileged_state=True, mode="gate"))
    inputs = _inputs()
    inputs["dt"] = 0.17
    core.apply(**inputs)
    core.apply(**inputs)
    inputs["hand_pos"][2] = 0.02
    inputs["dt"] = 0.06
    core.apply(**inputs)  # readiness arrives at t=.34, after release deadline=.30
    inputs["dt"] = 0.02
    out, trace = core.apply(**inputs)  # t=.40, absolute maximum gate delay
    assert trace["gate_authority"] == 1.0
    assert torch.equal(out, inputs["raw"])


@pytest.mark.parametrize("initial", [False, True])
def test_nonfinite_privileged_state_disables_intervention_until_reset(initial):
    from isaaclab_arena_gr00t.policy.g1_hand_assistance import AssistanceCfg, HandAssistance

    core = HandAssistance(AssistanceCfg(privileged_state=True, mode="combined"))
    inputs = _inputs()
    if not initial:
        core.apply(**inputs)
    inputs["object_pos"][2] = float("nan")
    out, trace = core.apply(**inputs)
    assert torch.equal(out, inputs["raw"])
    assert trace["state_rejected"]
    inputs["object_pos"][2] = 0.0
    out, trace = core.apply(**inputs)
    assert torch.equal(out, inputs["raw"]) and trace["state_rejected"]
    core.reset()
    out, trace = core.apply(**inputs)
    assert not trace["state_rejected"] and not torch.equal(out, inputs["raw"])
