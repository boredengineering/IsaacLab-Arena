# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for ``SuccessMode.SEQUENCE`` and the episode-scoped state backing it."""

import traceback

import pytest

from isaaclab_arena.tests.utils.subprocess import run_simulation_app_function

HEADLESS = True


class _MockPredicate:
    """Callable predicate that returns a controlled per-env bool tensor."""

    def __init__(self, num_envs: int, name: str = "mock_predicate"):
        import torch

        self.num_envs = num_envs
        self.return_value = torch.tensor([False] * num_envs)
        self.__name__ = name

    def set(self, values: list[bool]):
        import torch

        assert len(values) == self.num_envs
        self.return_value = torch.tensor(values)

    def __call__(self, env, **kwargs):
        return self.return_value


class _MockEnv:
    def __init__(self, num_envs: int = 1, device: str = "cpu"):
        import torch

        self.num_envs = num_envs
        self.device = device
        self.episode_length_buf = torch.zeros(num_envs, dtype=torch.long)

    def step(self, n: int = 1):
        self.episode_length_buf = self.episode_length_buf + n

    def reset(self):
        import torch

        self.episode_length_buf = torch.zeros(self.num_envs, dtype=torch.long)


def _make_gate(num_envs: int, num_stages: int):
    """Return ``(stages, evaluate)`` for a SEQUENCE gate over ``num_stages`` mock predicates."""
    from isaaclab.managers import TerminationTermCfg

    from isaaclab_arena.tasks.terminations import SuccessMode, check_success

    stages = [_MockPredicate(num_envs, name=f"stage_{i}") for i in range(num_stages)]
    predicates = [TerminationTermCfg(func=stage, params={}) for stage in stages]

    def evaluate(env):
        return check_success(
            env,
            predicates=predicates,
            mode=SuccessMode.SEQUENCE,
            gate_id="test_gate",
        )

    return stages, evaluate


def _test_out_of_order_stage_does_not_succeed(simulation_app) -> bool:
    """A later stage firing before an earlier one never yields success (the v9 contact trap)."""
    try:
        env = _MockEnv(num_envs=1)
        (lift, contact), evaluate = _make_gate(num_envs=1, num_stages=2)

        # Contact fires at t=0 while the object was never lifted.
        lift.set([False])
        contact.set([True])
        for _ in range(15):
            env.step()
            assert evaluate(env).tolist() == [False]

        # Once the lift actually happens, the still-held contact completes the sequence.
        lift.set([True])
        env.step()
        assert evaluate(env).tolist() == [True]
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False
    return True


def _test_stages_latch_and_survive_transient_loss(simulation_app) -> bool:
    """Stages latch in order, and success persists after a completed stage stops holding."""
    try:
        env = _MockEnv(num_envs=1)
        (lift, contact), evaluate = _make_gate(num_envs=1, num_stages=2)

        lift.set([True])
        contact.set([False])
        env.step()
        assert evaluate(env).tolist() == [False]

        # Object is set down: the lift no longer holds, but it already latched.
        lift.set([False])
        contact.set([True])
        env.step()
        assert evaluate(env).tolist() == [True]

        # Contact chatter after success does not un-succeed the episode.
        contact.set([False])
        env.step()
        assert evaluate(env).tolist() == [True]
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False
    return True


def _test_simultaneous_stages_cascade_in_one_step(simulation_app) -> bool:
    """Stages that hold at the same step all latch together, matching ALL semantics."""
    try:
        env = _MockEnv(num_envs=1)
        (lift, contact, proximity), evaluate = _make_gate(num_envs=1, num_stages=3)

        lift.set([True])
        contact.set([True])
        proximity.set([True])
        env.step()
        assert evaluate(env).tolist() == [True]
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False
    return True


def _test_latches_are_per_env_and_clear_on_episode_restart(simulation_app) -> bool:
    """Latches are tracked per env and cleared when an env's episode step counter rewinds."""
    try:
        env = _MockEnv(num_envs=2)
        (lift, contact), evaluate = _make_gate(num_envs=2, num_stages=2)

        # Only env 0 lifts.
        lift.set([True, False])
        contact.set([False, False])
        env.step()
        assert evaluate(env).tolist() == [False, False]

        contact.set([True, True])
        env.step()
        assert evaluate(env).tolist() == [True, False]

        # A new episode must not inherit env 0's latched lift.
        env.reset()
        lift.set([False, False])
        contact.set([True, True])
        assert evaluate(env).tolist() == [False, False]
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False
    return True


def _test_repeated_evaluation_within_one_step_is_stable(simulation_app) -> bool:
    """Evaluating the gate several times in one step neither advances nor clears the latches."""
    try:
        env = _MockEnv(num_envs=1)
        (lift, contact), evaluate = _make_gate(num_envs=1, num_stages=2)

        lift.set([True])
        contact.set([True])
        env.step()
        assert evaluate(env).tolist() == [True]
        assert evaluate(env).tolist() == [True]
        assert evaluate(env).tolist() == [True]
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False
    return True


def _test_running_min_tracks_resting_height(simulation_app) -> bool:
    """The running minimum follows an object down and holds while it is lifted."""
    import torch

    try:
        from isaaclab_arena.tasks.predicates.episode_state import get_episode_scoped_state

        env = _MockEnv(num_envs=1)
        heights = [0.0128, 0.0100, 0.0027, 0.0027, 0.2500, 0.4000]
        observed = []
        for height in heights:
            env.step()
            state = get_episode_scoped_state(env)
            observed.append(float(state.running_min("z", torch.tensor([height]))[0]))

        # Tracks down to the resting height and holds there (float32, hence the tolerance).
        assert observed[-1] == pytest.approx(0.0027, abs=1e-6), observed
        assert observed == sorted(observed, reverse=True), f"running minimum must be monotone: {observed}"
        # A 5 cm lift threshold is cleared only once the object is actually raised.
        assert not heights[3] > observed[3] + 0.05
        assert heights[4] > observed[4] + 0.05

        # The minimum is re-armed on the next episode.
        env.reset()
        state = get_episode_scoped_state(env)
        assert float(state.running_min("z", torch.tensor([0.9]))[0]) == pytest.approx(0.9, abs=1e-6)
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False
    return True


def test_out_of_order_stage_does_not_succeed():
    assert run_simulation_app_function(_test_out_of_order_stage_does_not_succeed)


def test_stages_latch_and_survive_transient_loss():
    assert run_simulation_app_function(_test_stages_latch_and_survive_transient_loss)


def test_simultaneous_stages_cascade_in_one_step():
    assert run_simulation_app_function(_test_simultaneous_stages_cascade_in_one_step)


def test_latches_are_per_env_and_clear_on_episode_restart():
    assert run_simulation_app_function(_test_latches_are_per_env_and_clear_on_episode_restart)


def test_repeated_evaluation_within_one_step_is_stable():
    assert run_simulation_app_function(_test_repeated_evaluation_within_one_step_is_stable)


def test_running_min_tracks_resting_height():
    assert run_simulation_app_function(_test_running_min_tracks_resting_height)


def _test_bouncing_object_does_not_count_as_lifted(simulation_app) -> bool:
    """An object that falls, bounces, and rises must not satisfy the lift gate.

    This is the failure mode observed in the v10 evaluation: the manipuland spawned above the
    surface, fell (driving the running minimum down), rebounded past the 5 cm threshold, and
    latched the lift stage with no robot involvement -- producing a success with a zero progress
    score. Requiring the object to have been at rest first is what closes it.

    The scene accessors are patched rather than simulated so the sequence of heights and speeds is
    exact and the assertion is about the predicate's logic, not about physics.
    """
    import torch

    from isaaclab_arena.tasks.predicates import spatial

    try:
        env = _MockEnv(num_envs=1)
        # (height, speed) per step. A 1 cm spawn gap: fall to 0.00, rebound to 0.06 while still
        # moving fast, then settle at 0.01, then a genuine 6 cm lift.
        trace = [
            (0.010, 0.00),  # spawned, momentarily at rest before gravity acts
            (0.004, 0.40),  # falling
            (0.000, 0.44),  # lowest point, still fast
            (0.060, 0.35),  # REBOUND above threshold, still fast -- must NOT count
            (0.030, 0.20),  # coming back down
            (0.010, 0.01),  # settled
            (0.011, 0.02),  # at rest on the surface
            (0.010, 0.01),  # third consecutive at-rest step establishes the reference
            (0.075, 0.30),  # genuine lift, 6.5 cm above the rested height
        ]
        original_pos, original_vel = spatial.get_root_pos_w, spatial.get_root_lin_vel_w
        results = []
        try:
            for height, speed in trace:
                spatial.get_root_pos_w = lambda e, n, _h=height: torch.tensor([[0.0, 0.0, _h]])
                spatial.get_root_lin_vel_w = lambda e, n, _s=speed: torch.tensor([[_s, 0.0, 0.0]])
                env.step()
                results.append(bool(spatial.object_lifted_above_resting_min(env, "obj", distance=0.05)[0]))
        finally:
            spatial.get_root_pos_w, spatial.get_root_lin_vel_w = original_pos, original_vel

        rebound_index = 3
        assert not results[rebound_index], (
            f"the rebound at step {rebound_index} was counted as a lift; a bouncing object can then "
            f"fake a success. results={results}"
        )
        assert results[-1], f"a genuine 6.5 cm lift after resting must count. results={results}"
        # Nothing before the object first rests may qualify.
        assert not any(results[: rebound_index + 1]), f"pre-rest steps must all be False: {results}"
    except AssertionError:
        raise
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False
    return True


def test_bouncing_object_does_not_count_as_lifted():
    assert run_simulation_app_function(_test_bouncing_object_does_not_count_as_lifted)


def _test_momentary_excursion_is_not_a_lift(simulation_app) -> bool:
    """An object clipped above the threshold for one step is not "lifted and held".

    The v17-v20 evaluations measured a peak lift of under 2 cm, so the lift threshold had to come
    down from its asserted 5 cm. Lowering a height threshold alone would let a hand that swipes the
    object upward register as a pick, which is why ``min_airborne_steps`` exists: a carry is a
    sustained state. This checks the dwell requirement independently of the height one.
    """
    import torch

    from isaaclab_arena.tasks.predicates import spatial

    try:
        env = _MockEnv(num_envs=1)
        # Rest for 3 steps to establish the reference at 0.010, then a 1-step spike, then a
        # sustained 5-step carry at the same height.
        trace = [
            (0.010, 0.00),
            (0.010, 0.00),
            (0.010, 0.00),  # reference established at 0.010
            (0.040, 0.30),  # single-step spike, 3 cm above rest -- must NOT count
            (0.010, 0.05),  # back down
            (0.040, 0.20),  # sustained carry begins
            (0.041, 0.15),
            (0.040, 0.10),
            (0.042, 0.10),
            (0.040, 0.08),  # 5th consecutive airborne step -- must count
        ]
        original_pos, original_vel = spatial.get_root_pos_w, spatial.get_root_lin_vel_w
        results = []
        try:
            for height, speed in trace:
                spatial.get_root_pos_w = lambda e, n, _h=height: torch.tensor([[0.0, 0.0, _h]])
                spatial.get_root_lin_vel_w = lambda e, n, _s=speed: torch.tensor([[_s, 0.0, 0.0]])
                env.step()
                results.append(
                    bool(spatial.object_lifted_above_resting_min(env, "obj", distance=0.015, min_airborne_steps=5)[0])
                )
        finally:
            spatial.get_root_pos_w, spatial.get_root_lin_vel_w = original_pos, original_vel

        spike_index = 3
        assert not results[spike_index], f"a single-step spike must not count as a lift: {results}"
        assert not any(results[:9]), f"nothing before the 5th airborne step may qualify: {results}"
        assert results[9], f"a sustained 5-step carry must count: {results}"
    except AssertionError:
        raise
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False
    return True


def test_momentary_excursion_is_not_a_lift():
    assert run_simulation_app_function(_test_momentary_excursion_is_not_a_lift)
