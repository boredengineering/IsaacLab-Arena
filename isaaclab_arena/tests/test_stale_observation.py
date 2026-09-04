# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Asserts, in pixel space, whether the first camera observation of an episode is stale.

``ManagerBasedEnv._reset_idx`` is followed by ``write_data_to_sim()``, ``sim.forward()`` and then
``sim.render()`` (``manager_based_env.py:425-431``). ``sim.forward()`` does not step physics, so
with fabric enabled the poses written during reset may not have reached the renderer when the
re-render happens. The observation returned by ``reset()`` can therefore show the *previous*
episode's scene while proprioception is already post-reset, and a vision-conditioned policy
conditions its first action chunk on a scene that no longer exists.

Why this is measured in pixels rather than inferred from a success rate: ``num_rerenders_on_reset``
is the documented remedy and is reported not to fix the underlying ordering problem, so a
"success rate did not change" result would exonerate the defect instead of testing it.

The discriminating statistic, per episode:

    d_self = mean |obs_reset - obs_after_one_step|      ~0 when the reset frame is fresh
    d_prev = mean |obs_reset - obs_final_of_previous|   large when the reset frame is fresh

Fresh frames give ``d_prev >> d_self``. Stale frames invert that relation.

The scene is deliberately light. Stale reset frames are a property of the render/physics ordering
in ``ManagerBasedEnv``, not of any particular asset, so a heavy scene would add minutes per
configuration to the same measurement.
"""

import contextlib
import traceback

import pytest

from isaaclab_arena.tests.utils.subprocess import run_simulation_app_function

HEADLESS = True
ENABLE_CAMERAS = True

NUM_EPISODES = 3
STEPS_PER_EPISODE = 4

# Two spawn poses far enough apart that the rendered frames are unmistakably different. Both are
# above the drawer so the object simply falls; the movement is what the defect needs, not the task.
POSE_A = (0.0758, -0.5088, 0.50)
POSE_B = (-0.3000, -0.5088, 0.50)

# (num_rerenders_on_reset, disable_fabric). The first is the shipped default; the flags are the
# documented remedies; disable_fabric targets the root cause.
CONFIGS = ((0, False), (1, False), (2, False), (1, True))


def _camera_tensor(obs):
    """Return a detached CPU copy of the first camera image in an observation dict, or None.

    The copy is deliberate. Observations produced under ``inference_mode`` are inference tensors,
    and retaining one across a later step then using it in arithmetic raises "Inplace update to
    inference tensor outside InferenceMode".
    """
    import torch

    from isaaclab_arena.video.camera_observation_video_recorder import CAMERA_OBS_GROUP_KEY

    group = obs.get(CAMERA_OBS_GROUP_KEY, {}) if isinstance(obs, dict) else {}
    for value in group.values():
        if torch.is_tensor(value):
            with torch.inference_mode(False), torch.no_grad():
                return torch.empty(value.shape, dtype=torch.float32, device="cpu").copy_(value)
    return None


def _build_probe_env(disable_fabric: bool, num_rerenders: int):
    """Build a minimal camera-equipped scene whose reset event moves the manipuland."""
    import torch

    from isaaclab.managers import EventTermCfg, SceneEntityCfg

    from isaaclab_arena.assets.object_reference import ObjectReference
    from isaaclab_arena.assets.registries import AssetRegistry
    from isaaclab_arena.embodiments.franka.franka import FrankaIKEmbodiment
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
    from isaaclab_arena.scene.scene import Scene
    from isaaclab_arena.tasks.pick_and_place_task import PickAndPlaceTask
    from isaaclab_arena.utils.pose import Pose

    registry = AssetRegistry()
    background = registry.get_asset_by_name("kitchen_with_open_drawer")()
    manipuland = registry.get_asset_by_name("cracker_box")()
    manipuland.set_initial_pose(Pose(position_xyz=POSE_A, rotation_xyzw=(0, 0, 0, 1)))
    # A rigid destination prim is required: the task builds a contact sensor filtered against it,
    # and the background as a whole is not a rigid body.
    destination = ObjectReference(
        name="destination_location",
        prim_path="{ENV_REGEX_NS}/kitchen_with_open_drawer/Cabinet_B_02",
        parent_asset=background,
    )

    arena_env = IsaacLabArenaEnvironment(
        name="stale_observation_probe",
        embodiment=FrankaIKEmbodiment(enable_cameras=True),
        scene=Scene(assets=[background, manipuland, destination]),
        # The task is irrelevant to this measurement; the lift gate is opted out so it cannot
        # terminate an episode mid-comparison.
        task=PickAndPlaceTask(manipuland, destination, background, require_lift_before_place=False),
    )

    builder = ArenaEnvBuilder(arena_env, cfg=ArenaEnvBuilderCfg(num_envs=1, disable_fabric=disable_fabric))
    env_cfg, env_kwargs = builder.compose_manager_cfg()

    episode_counter = {"n": 0}

    def _alternate_pose(env, env_ids, asset_cfg: SceneEntityCfg):
        """Teleport the manipuland to one of two poses, alternating per episode.

        ``inference_mode(False)`` is load-bearing: reset events can run under an ambient inference
        context, and a tensor allocated there is an inference tensor that cannot then be written in
        place, which surfaces as "Inplace update to inference tensor outside InferenceMode".
        """
        asset = env.scene[asset_cfg.name]
        pose = POSE_A if episode_counter["n"] % 2 == 0 else POSE_B
        episode_counter["n"] += 1

        with torch.inference_mode(False), torch.no_grad():
            origins = env.scene.env_origins
            offsets = torch.empty(origins.shape, dtype=torch.float32, device=origins.device)
            offsets.copy_(origins)
            root_pose = torch.zeros((offsets.shape[0], 7), dtype=torch.float32, device=offsets.device)
            root_pose[:, 0] = pose[0] + offsets[:, 0]
            root_pose[:, 1] = pose[1] + offsets[:, 1]
            root_pose[:, 2] = pose[2] + offsets[:, 2]
            root_pose[:, 6] = 1.0  # identity quaternion, w last
            asset.write_root_pose_to_sim(root_pose)

    env_cfg.events.stale_probe_alternate_pose = EventTermCfg(
        func=_alternate_pose,
        mode="reset",
        params={"asset_cfg": SceneEntityCfg(manipuland.name)},
    )
    env_cfg.num_rerenders_on_reset = num_rerenders

    return builder.make_registered(env_cfg, env_kwargs)


def _measure_reset_freshness(num_rerenders: int, disable_fabric: bool):
    """Return ``(episode, d_self, d_prev)`` for one configuration of the render/fabric flags."""
    import torch

    print(f"[stale] config: num_rerenders_on_reset={num_rerenders} disable_fabric={disable_fabric}", flush=True)
    env = None
    try:
        env = _build_probe_env(disable_fabric, num_rerenders)
        zero_action = torch.zeros(
            (env.unwrapped.num_envs,) + env.unwrapped.single_action_space.shape,
            device=env.unwrapped.device,
        )

        previous_final = None
        records = []
        # The whole loop shares one inference context. Mixing modes is not safe here: the progress
        # tracker mutates its state tensors in place during reset (progress_tracker.py:318), so a
        # reset outside inference mode after steps taken inside it raises "Inplace update to
        # inference tensor". The production runner keeps steps and auto-resets in one context for
        # the same reason.
        for episode in range(NUM_EPISODES):
            with torch.inference_mode():
                obs_reset, _ = env.reset()
                frame_reset = _camera_tensor(obs_reset)
                assert frame_reset is not None, "no camera observation found; run with --enable_cameras"

                obs_step, *_ = env.step(zero_action)
                frame_step1 = _camera_tensor(obs_step)

                d_self = float((frame_reset - frame_step1).abs().mean())
                d_prev = float((frame_reset - previous_final).abs().mean()) if previous_final is not None else None

                obs_last = obs_step
                for _ in range(STEPS_PER_EPISODE - 1):
                    obs_last, *_ = env.step(zero_action)
                previous_final = _camera_tensor(obs_last)

                records.append((episode, d_self, d_prev))
                print(f"[stale] episode {episode}: d_self={d_self:.6f} d_prev={d_prev}", flush=True)
        return records
    finally:
        if env is not None:
            with contextlib.suppress(Exception):
                env.close()


def _test_reset_frame_freshness(simulation_app) -> bool:
    """Report d_self and d_prev across the flag matrix and assert the reset frame is fresh."""
    try:
        verdicts = {}
        for num_rerenders, disable_fabric in CONFIGS:
            records = _measure_reset_freshness(num_rerenders, disable_fabric)
            comparable = [(e, s, p) for e, s, p in records if p is not None]
            assert comparable, "need at least two episodes to compare against a predecessor"
            stale = [e for e, s, p in comparable if p < s]
            verdicts[(num_rerenders, disable_fabric)] = (stale, comparable)
            print(
                f"[stale] VERDICT rerenders={num_rerenders} disable_fabric={disable_fabric}: "
                f"{len(stale)}/{len(comparable)} stale episodes {stale}",
                flush=True,
            )

        default_stale, default_comparable = verdicts[(0, False)]
        remedied_stale, _ = verdicts[(1, False)]
        print(
            "[stale] SUMMARY: Isaac Lab's default (num_rerenders_on_reset=0, fabric on) had "
            f"{len(default_stale)}/{len(default_comparable)} stale episodes; with one re-render, "
            f"{len(remedied_stale)}.",
            flush=True,
        )
        for key, (stale, _comparable) in verdicts.items():
            state = "FRESH in every episode" if not stale else f"STALE in episodes {stale}"
            print(f"[stale] config rerenders={key[0]} disable_fabric={key[1]}: {state}", flush=True)

        # MEASURED 2026-09-03. The assertion is on the remedy, not on the default, for two reasons:
        # the default's staleness is an upstream Isaac Lab behaviour this repository does not
        # control, and a test that always fails guards nothing. What this repository *does* control
        # is that its generated environments enable the re-render -- which
        # arena_env_graph_conversion_utils now does -- so the property worth protecting is that one
        # re-render actually produces fresh frames on this Isaac Lab version.
        assert not remedied_stale, (
            "num_rerenders_on_reset=1 no longer yields fresh reset frames (stale in episodes "
            f"{remedied_stale}). The remedy that generated environments rely on has regressed; "
            f"per-config verdicts: { {k: v[0] for k, v in verdicts.items()} }"
        )
        # And the default must still be observably worse, or the flag has become a no-op and the
        # generated-environment fix is buying nothing.
        assert default_stale, (
            "the shipped default no longer produces stale frames. If upstream fixed the ordering, "
            "the forced re-render in arena_env_graph_conversion_utils is now redundant and the "
            "comment there should be updated."
        )
    except AssertionError:
        raise
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False
    return True


@pytest.mark.with_cameras
def test_reset_frame_freshness():
    """The observation returned by reset() must reflect the post-reset scene, not the previous one."""
    assert run_simulation_app_function(
        _test_reset_frame_freshness,
        headless=HEADLESS,
        enable_cameras=ENABLE_CAMERAS,
    )
