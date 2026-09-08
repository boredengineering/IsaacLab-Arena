# Copyright (c) 2025-2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import math
import os
import torch
import tqdm
from importlib import import_module
from typing import TYPE_CHECKING, Any

import warp as wp

from isaaclab_arena.assets.registries import PolicyRegistry
from isaaclab_arena.cli.isaaclab_arena_cli import get_isaaclab_arena_cli_parser
from isaaclab_arena.evaluation.policy_runner_cli import (
    add_policy_cli_args,
    add_policy_runner_arguments,
    build_policy_from_cli,
)
from isaaclab_arena.metrics.metrics_logger import metrics_to_plain_python_types
from isaaclab_arena.utils.hydra_overrides import assert_hydra_overrides
from isaaclab_arena.utils.isaaclab_utils.simulation_app import SimulationAppContext
from isaaclab_arena.utils.multiprocess import get_local_rank, get_world_size
from isaaclab_arena.video.video_recording import VideoRecordingCfg, timestamped_run_dir, wrap_env_for_video
from isaaclab_arena.visualization.report import build_report, serve_until_ctrl_c
from isaaclab_arena_environments.cli import get_arena_builder_from_cli, get_isaaclab_arena_environments_cli_parser

if TYPE_CHECKING:
    from isaaclab_arena.metrics.metric_data import MetricsDataCollection
    from isaaclab_arena.policy.policy_base import PolicyBase


def get_policy_cls(policy_type: str) -> type[PolicyBase]:
    """Get the policy class for the given policy type name.

    Note that this function:
    - first: checks for a registered policy type in the PolicyRegistry
    - if not found, it tries to dynamically import the policy class, treating
      the policy_type argument as a string representing the module path and class name.

    """
    policy_registry = PolicyRegistry()
    if policy_registry.is_registered(policy_type):
        return policy_registry.get_policy(policy_type)
    else:
        print(f"Policy {policy_type} is not registered. Dynamically importing from path: {policy_type}")
        assert "." in policy_type, (
            "policy_type must be a dotted Python import path of the form 'module.submodule.ClassName', got:"
            f" {policy_type}"
        )
        # Dynamically import the class from the string path
        module_path, class_name = policy_type.rsplit(".", 1)
        module = import_module(module_path)
        policy_cls = getattr(module, class_name)
        return policy_cls


def is_distributed(args_cli: argparse.Namespace) -> bool:
    return (
        "cuda" in args_cli.device and hasattr(args_cli, "distributed") and args_cli.distributed and get_world_size() > 1
    )


def make_recorded_environment(arena_builder, output_dir: str, render_mode: str | None):
    """Build the environment with HDF5 metrics in this run's writable artifact directory.

    Args:
        arena_builder: Builder for the configured scene and policy task.
        output_dir: Evaluation run directory, also used for JSON and video results.
        render_mode: Gymnasium render mode for the video recorder.

    Returns:
        Registered, wrapped environment with unchanged task and physics configuration.
    """
    env_cfg, env_kwargs = arena_builder.compose_manager_cfg()
    if getattr(env_cfg, "recorders", None) is not None:
        env_cfg.recorders.dataset_export_dir_path = output_dir
    return arena_builder.make_registered(env_cfg=env_cfg, env_kwargs=env_kwargs, render_mode=render_mode)


def build_neutral_hold_action(base_env) -> torch.Tensor:
    """Build an action that holds the robot's current posture, for use while the scene settles.

    A zero action is **not** neutral for every embodiment. For the G1 decoupled whole-body
    controller the action vector is ``[joint_targets | navigate_cmd(3) | base_height(1) |
    torso_rpy(3)]`` where the joint entries are *absolute* targets and the base-height entry is a
    commanded pelvis height whose default is 0.75 m
    (``g1_decoupled_wbc_joint_action.py:87``). Sending zeros therefore commands the robot to squat
    to the floor and drive every upper-body joint to 0 rad, discarding the scene's
    ``initial_joint_pos``. During a settle loop that swings the arms through the workspace and
    launches the very objects the loop is waiting on -- which is what produced 5-16 step episodes in
    the g1_tabletop_apple_to_plate evaluations, with the manipuland tripping ``object_dropped``
    before the policy ever ran.

    For delta-style action spaces (Franka IK and friends) zero *is* the correct hold, so that
    remains the fallback.
    """
    num_envs = base_env.num_envs
    action_dim = base_env.action_manager.total_action_dim
    hold_action = torch.zeros((num_envs, action_dim), device=base_env.device)

    # Detect a whole-body-control action term rather than keying on the action width, which
    # several embodiments share.
    is_wbc = any(
        "wbc" in type(term).__name__.lower() for term in getattr(base_env.action_manager, "_terms", {}).values()
    )
    if not is_wbc:
        return hold_action

    num_navigate_cmd, num_base_height_cmd, num_torso_rpy_cmd = 3, 1, 3
    tail = num_navigate_cmd + num_base_height_cmd + num_torso_rpy_cmd
    if action_dim <= tail:
        return hold_action

    robot = base_env.scene["robot"]
    default_joint_pos = wp.to_torch(robot.data.default_joint_pos)
    num_joints = min(action_dim - tail, default_joint_pos.shape[-1])
    hold_action[:, :num_joints] = default_joint_pos[:, :num_joints].to(hold_action.device)
    # Hold the standing pelvis height instead of commanding a squat to the floor.
    hold_action[:, -num_base_height_cmd - num_torso_rpy_cmd] = 0.75
    return hold_action


def verify_and_settle_scene(
    env,
    settle_steps: int = 25,
    lin_vel_thresh: float = 0.1,
    ang_vel_thresh: float = 1.0,
) -> tuple[dict[str, Any], Any]:
    """Verify that all movable scene objects physically settle before policy inference.

    Steps the environment with zero/neutral posture-holding actions to allow normal-force contact
    resolution and settle transients, dynamically monitoring linear and angular velocities until
    every object is sitting still.
    """
    base_env = env.unwrapped
    scene = base_env.scene

    movable_objects = []
    robot_asset = None
    for name in scene.keys():
        if name in ("terrain", "ground", "maple_table", "table"):
            continue
        if name in ("robot",) or "robot" in name:
            asset = scene[name]
            if hasattr(asset, "data") and hasattr(asset.data, "root_lin_vel_w"):
                robot_asset = (name, asset)
            continue
        asset = scene[name]
        if hasattr(asset, "data") and hasattr(asset.data, "root_lin_vel_w"):
            movable_objects.append(name)

    obs = None
    max_steps = max(settle_steps, 50)
    if max_steps > 0:
        hold_action = build_neutral_hold_action(base_env)
        for step_idx in range(max_steps):
            obs, _, terminated, truncated, _ = env.step(hold_action)
            # A termination during settling is auto-reset by ManagerBasedRLEnv.step and would
            # otherwise be silently recorded as a completed episode. Surface it instead of
            # consuming it: an object that cannot survive a posture-hold has a scene problem, and
            # continuing to step only produces more phantom episodes.
            if terminated is not None and bool(torch.as_tensor(terminated).any()):
                print(
                    f"[policy_runner] ⚠️  Scene terminated during settling at step {step_idx} "
                    f"(terminated={torch.as_tensor(terminated).tolist()}). The scene is not stable "
                    "under a posture hold; the episodes recorded here are settle artefacts, not "
                    "policy rollouts.",
                    flush=True,
                )
                raise RuntimeError(f"Scene terminated during settling at step {step_idx}; reject this rollout")
            # Bipedal humanoid robots (e.g. Unitree G1 WBC) require ~35-45 steps to damp out
            # startup ground contact depenetration and reach steady standing balance.
            if step_idx >= 40:
                curr_settled = True
                for name in movable_objects:
                    asset = scene[name]
                    # max, not mean: averaging over envs lets one object in free fall be masked by
                    # three still ones, which is how an unsettled scene previously read as settled.
                    lin_v = wp.to_torch(asset.data.root_lin_vel_w).norm(dim=-1).max().item()
                    ang_v = wp.to_torch(asset.data.root_ang_vel_w).norm(dim=-1).max().item()
                    if lin_v > lin_vel_thresh or ang_v > ang_vel_thresh:
                        curr_settled = False
                        break
                if curr_settled and robot_asset is not None:
                    _, r_asset = robot_asset
                    r_lin_v = wp.to_torch(r_asset.data.root_lin_vel_w).norm(dim=-1).max().item()
                    r_ang_v = wp.to_torch(r_asset.data.root_ang_vel_w).norm(dim=-1).max().item()
                    if r_lin_v > lin_vel_thresh or r_ang_v > ang_vel_thresh:
                        curr_settled = False
                if curr_settled:
                    break

    settle_status = {}
    all_settled = True
    tracked_entities = list(movable_objects)
    if robot_asset is not None:
        tracked_entities.append(robot_asset[0])
    print(
        f"[policy_runner] 🔍 Phase 1 Settle Verification: Checking {len(tracked_entities)} entities (objects + robot)"
        " for stationarity..."
    )
    for name in tracked_entities:
        asset = scene[name]
        # Worst env, not the average: the report decides whether inference starts on a still
        # scene, and one object in free fall makes that false regardless of the other envs.
        lin_vel = wp.to_torch(asset.data.root_lin_vel_w).norm(dim=-1).max().item()
        ang_vel = wp.to_torch(asset.data.root_ang_vel_w).norm(dim=-1).max().item()
        is_settled = bool((lin_vel <= lin_vel_thresh) and (ang_vel <= ang_vel_thresh))
        settle_status[name] = {
            "lin_vel_m_s": round(lin_vel, 4),
            "ang_vel_rad_s": round(ang_vel, 4),
            "settled": is_settled,
        }
        if is_settled:
            status_tag = "✅ SETTLED"
        else:
            reasons = []
            if lin_vel > lin_vel_thresh:
                reasons.append(f"lin_vel={lin_vel:.4f} > {lin_vel_thresh}")
            if ang_vel > ang_vel_thresh:
                reasons.append(f"ang_vel={ang_vel:.4f} > {ang_vel_thresh}")
            status_tag = f"⚠️ UNSETTLED ({', '.join(reasons)})"
        print(f"  - '{name}': lin_vel={lin_vel:.4f} m/s, ang_vel={ang_vel:.4f} rad/s -> {status_tag}")
        if not is_settled:
            all_settled = False

    if all_settled:
        print(
            "[policy_runner] ✅ All scene entities (including robot) are physically settled. Proceeding to policy"
            " inference."
        )
    else:
        print("[policy_runner] ⚠️ Warning: One or more entities are NOT sitting still at inference start!")

    report = {"all_objects_settled": all_settled, "object_settle_status": settle_status}
    base_env.settle_report = report
    return report, obs


class ReachTracer:
    """Records manipuland height-above-rest, speed, and distance to destination, per step.

    Written for choosing lift thresholds from data instead of asserting them: the success gate's
    ``min_lift_height`` is only meaningful against the distribution of lifts the policy actually
    produces on a given scene.
    """

    def __init__(
        self,
        path: str,
        base_env,
        object_name: str,
        destination_name: str | None,
        contact_sensor_name: str | None = None,
        hand_body_patterns: tuple[str, ...] = ("wrist", "hand"),
        hand_body_name: str | None = None,
        gripper_joint_patterns: tuple[str, ...] = ("hand_index", "hand_middle", "hand_thumb"),
    ):
        self._path = path
        self._rows: list[str] = []
        self._env = base_env
        self._object_name = object_name
        self._destination_name = destination_name
        self._contact_sensor_name = contact_sensor_name
        self._rest_z: torch.Tensor | None = None
        self._step = 0
        self._step_in_episode = 0
        self._episode_index: torch.Tensor | None = None
        self._hand_body_name = hand_body_name
        # Finger-joint indices, so a trace can say *when* the hand closed relative to where it
        # was. Without this, premature closure is untestable: the contact sensor reads ~0 N on
        # these scenes even while object_moved_rate is 0.75-0.95, so contact cannot time it
        # either.
        self._gripper_indices = self._resolve_gripper_joints(gripper_joint_patterns)
        self._hand_indices = self._resolve_hand_bodies(hand_body_patterns)
        if hand_body_name is not None:
            # Pinning to one named body. Without this the tracer minimises over every matching
            # body each step, which is a selection bias, not a measurement: taking the minimum
            # over six links reports a smaller distance than any single link would, and the
            # reported distance silently changes frame between steps. Measured on this repo's own
            # traces, the mixed metric understated lateral error by 3.2-5.2 cm -- roughly half --
            # and made every historical reach figure irreproducible.
            assert hand_body_name in self._hand_indices, (
                f"hand_body_name={hand_body_name!r} is not a tracked body. Available:"
                f" {sorted(self._hand_indices)}. Widen hand_body_patterns or name one of these."
            )
            self._hand_indices = {hand_body_name: self._hand_indices[hand_body_name]}

    def _resolve_hand_bodies(self, patterns: tuple[str, ...]) -> dict[str, int]:
        """Map end-effector body names to their index in the robot's body array.

        Discovered by substring rather than hardcoded, because body naming differs across
        embodiments. Returning an empty mapping simply omits the hand columns from the trace.
        """
        try:
            body_names = self._env.scene["robot"].body_names
        except Exception:
            return {}
        return {name: i for i, name in enumerate(body_names) if any(p in name.lower() for p in patterns)}

    def _resolve_gripper_joints(self, patterns: tuple[str, ...]) -> dict[str, int]:
        """Map finger-joint names to their index in the robot's joint array.

        Args:
            patterns: Substrings identifying finger joints.

        Returns:
            Mapping of joint name to index; empty when none match, which omits the columns.
        """
        try:
            names = self._env.scene["robot"].joint_names
        except Exception:
            return {}
        return {n: i for i, n in enumerate(names) if any(p in n.lower() for p in patterns)}

    def _pos(self, name):
        return wp.to_torch(self._env.scene[name].data.root_pos_w)

    def _nearest_hand_to(self, target: torch.Tensor) -> tuple[str, torch.Tensor] | None:
        """Return the tracked end-effector body closest to ``target``, with its world position.

        Which hand does the reaching is not known in advance, and picking the nearer one each step
        is what makes the horizontal/vertical error decomposition meaningful: a fixed choice would
        report the idle arm's distance whenever the other arm is the one working.
        """
        if not self._hand_indices:
            return None
        pos_w = wp.to_torch(self._env.scene["robot"].data.body_pos_w)
        best_name, best_pos, best_dist = None, None, None
        for name, index in self._hand_indices.items():
            candidate = pos_w[:, index, :]
            dist = float((candidate - target).norm(dim=-1)[0])
            if best_dist is None or dist < best_dist:
                best_name, best_pos, best_dist = name, candidate, dist
        return (best_name, best_pos) if best_name is not None else None

    def record(self) -> None:
        obj = self._pos(self._object_name)
        speed = wp.to_torch(self._env.scene[self._object_name].data.root_lin_vel_w).norm(dim=-1)
        z = obj[:, 2]

        # Resting reference, captured per environment and re-captured after each reset. Two
        # reasons it is not one shared sample taken once:
        #
        # - Waiting for *every* environment to be still, as this did, means one still-settling
        #   environment withholds the reference from all of them, and ``lift`` then never appears.
        # - The reference belongs to an episode. Carrying episode 0's resting height across a whole
        #   rollout reports every later episode's lift against the wrong datum.
        if self._rest_z is None:
            self._rest_z = torch.full_like(z, float("nan"))
            self._episode_index = torch.zeros_like(z, dtype=torch.long)
        pending = torch.isnan(self._rest_z) & (speed < 1e-2)
        self._rest_z[pending] = z[pending]

        # ``lift`` is None where this episode's reference is not yet established, rather than the
        # column being omitted: a missing key and a not-yet-known value are different facts, and a
        # reader that sees the column appear halfway through cannot tell which it is looking at.
        row = {
            "step": self._step,
            "step_in_episode": self._step_in_episode,
            "episode": self._episode_index.tolist(),
            "obj_z": [round(v, 5) for v in z.tolist()],
            "speed": [round(v, 5) for v in speed.tolist()],
            "lift": [None if math.isnan(v) else round(v, 5) for v in (z - self._rest_z).tolist()],
        }
        if self._destination_name is not None:
            dest = self._pos(self._destination_name)
            row["dist_to_dest"] = [round(v, 5) for v in (obj - dest).norm(dim=-1).tolist()]
            row["xy_to_dest"] = [round(v, 5) for v in (obj[:, :2] - dest[:, :2]).norm(dim=-1).tolist()]
        # Hand-to-object error, split into horizontal and vertical. This is what separates "reached
        # the wrong place" from "reached the right place at the wrong height": a policy with no
        # depth input can converge in XY off a correct bearing while missing in Z entirely, which
        # presents as closing the hand on air.
        nearest = self._nearest_hand_to(obj)
        if nearest is not None:
            name, hand = nearest
            row["hand_body"] = name
            row["hand_frame_mode"] = "pinned" if self._hand_body_name else "nearest_of_matching"
        if self._gripper_indices:
            joint_pos = wp.to_torch(self._env.scene["robot"].data.joint_pos)
            indices = list(self._gripper_indices.values())
            closure = joint_pos[:, indices].abs().mean(dim=-1)
            row["gripper_closure"] = [round(v, 5) for v in closure.tolist()]
            row["gripper_joint_count"] = len(indices)
            row["hand_x_minus_obj"] = [round(v, 5) for v in (hand[:, 0] - obj[:, 0]).tolist()]
            row["hand_y_minus_obj"] = [round(v, 5) for v in (hand[:, 1] - obj[:, 1]).tolist()]
            row["hand_xy_to_obj"] = [round(v, 5) for v in (hand[:, :2] - obj[:, :2]).norm(dim=-1).tolist()]
            row["hand_z_minus_obj"] = [round(v, 5) for v in (hand[:, 2] - obj[:, 2]).tolist()]
            row["hand_dist_to_obj"] = [round(v, 5) for v in (hand - obj).norm(dim=-1).tolist()]
            row["hand_pos_w"] = [[round(coord, 5) for coord in v] for v in hand.tolist()]
            row["obj_pos_w"] = [[round(coord, 5) for coord in v] for v in obj.tolist()]
        if self._contact_sensor_name is not None:
            try:
                sensor = self._env.scene[self._contact_sensor_name]
                force = torch.norm(wp.to_torch(sensor.data.force_matrix_w), dim=-1).reshape(-1)
                row["contact_force"] = [round(v, 5) for v in force.tolist()]
            except Exception:
                # Catch-all rather than KeyError alone: a sensor that exists but filters no prims
                # leaves force_matrix_w as None, and wp.to_torch(None) raises. This is a purely
                # diagnostic trace, so no failure reading it should abort the evaluation around it.
                self._contact_sensor_name = None
        self._rows.append(json.dumps(row))
        self._step += 1
        self._step_in_episode += 1

    def begin_episode(self, env_ids: torch.Tensor | None = None) -> None:
        """Mark an episode boundary so each episode's rows can be read on their own.

        Without this the trace is one undifferentiated stream: the per-episode tables in the
        evidence appendix could not be re-derived from it, because nothing recorded where one
        episode ended and the next began.

        Args:
            env_ids: Environments that just reset. None treats every environment as reset.
        """
        if self._rest_z is None or self._episode_index is None:
            # Nothing recorded yet, so there is no episode to close.
            return
        if env_ids is None:
            self._rest_z[:] = float("nan")
            self._episode_index += 1
        else:
            self._rest_z[env_ids] = float("nan")
            self._episode_index[env_ids] += 1
        self._step_in_episode = 0

    def close(self) -> None:
        """Write the buffered trace. Called on every rollout exit path, including exceptions."""
        os.makedirs(os.path.dirname(os.path.abspath(self._path)), exist_ok=True)
        with open(self._path, "w") as fh:
            fh.write("\n".join(self._rows) + "\n")


def rollout_policy(
    env,
    policy: PolicyBase,
    num_steps: int | None,
    num_episodes: int | None,
    check_settling: bool = True,
    settle_steps: int = 12,
    lin_vel_thresh: float = 0.1,
    ang_vel_thresh: float = 1.0,
    trace_reach: str | None = None,
    trace_reach_object: str | None = None,
    trace_reach_destination: str | None = None,
    trace_reach_hand_body: str | None = None,
) -> MetricsDataCollection | None:
    assert num_steps is not None or num_episodes is not None, "Either num_steps or num_episodes must be provided"
    assert num_steps is None or num_episodes is None, "Only one of num_steps or num_episodes must be provided"

    pbar = None
    tracer = None
    try:
        obs, _ = env.reset()

        # Check and verify object settling at start of inference
        if check_settling:
            _, settle_obs = verify_and_settle_scene(
                env,
                settle_steps=settle_steps,
                lin_vel_thresh=lin_vel_thresh,
                ang_vel_thresh=ang_vel_thresh,
            )
            if settle_obs is not None:
                obs = settle_obs

        policy.reset()
        policy.set_task_description(env.unwrapped.get_language_instruction())

        if trace_reach is not None:
            assert trace_reach_object is not None, "--trace_reach requires --trace_reach_object"
            tracer = ReachTracer(
                trace_reach,
                env.unwrapped,
                object_name=trace_reach_object,
                destination_name=trace_reach_destination,
                contact_sensor_name=f"contact_sensor_{trace_reach_object}",
                hand_body_name=trace_reach_hand_body,
            )

        # Setup progress bar based on num_steps or num_episodes
        if num_steps is not None:
            pbar = tqdm.tqdm(total=num_steps, desc="Steps", unit="step")
        else:
            pbar = tqdm.tqdm(total=num_episodes, desc="Episodes", unit="episode")

        num_episodes_completed = 0
        num_steps_completed = 0

        while True:
            with torch.inference_mode():
                actions = policy.get_action(env, obs)
                obs, _, terminated, truncated, _ = env.step(actions)
                if tracer is not None:
                    tracer.record()

                if terminated.any() or truncated.any():
                    # Only reset policy for those envs that are terminated or truncated
                    print(
                        f"Resetting policy for terminated env_ids: {terminated.nonzero().flatten()}"
                        f" and truncated env_ids: {truncated.nonzero().flatten()}"
                    )
                    env_ids = (terminated | truncated).nonzero().flatten()
                    completed_episodes = env_ids.shape[0]
                    num_episodes_completed += completed_episodes
                    if num_episodes is not None:
                        pbar.update(completed_episodes)
                        if num_episodes_completed >= num_episodes:
                            break
                    if num_steps is not None and num_steps_completed + 1 >= num_steps:
                        pbar.update(1)
                        break
                    if check_settling:
                        verify_and_settle_scene(
                            env,
                            settle_steps=settle_steps,
                            lin_vel_thresh=lin_vel_thresh,
                            ang_vel_thresh=ang_vel_thresh,
                        )
                        if hasattr(env.unwrapped, "observation_manager"):
                            obs = env.unwrapped.observation_manager.compute()

                    policy.reset(env_ids=env_ids)
                    if tracer is not None:
                        tracer.begin_episode(env_ids)
                    if hasattr(env.unwrapped.cfg, "metrics") and env.unwrapped.cfg.metrics is not None:
                        metrics = env.unwrapped.compute_metrics()
                        tqdm.tqdm.write(
                            f"[Rank {get_local_rank()}/{get_world_size()}] Metrics:"
                            f" {metrics_to_plain_python_types(metrics)}"
                        )
                # Break if number of steps is reached
                num_steps_completed += 1
                if num_steps is not None:
                    pbar.update(1)
                    if num_steps_completed >= num_steps:
                        break

        pbar.close()
        if tracer is not None:
            tracer.close()

    except Exception as e:
        if pbar is not None:
            pbar.close()
        # Flush the trace before re-raising: a crashed rollout is exactly when it is wanted.
        if tracer is not None:
            tracer.close()
        raise RuntimeError(f"Error rolling out policy: {e}")

    else:

        # Only compute metrics if env has non-None metrics.
        # Use unwrapped to reach the base env through any gym wrappers (e.g. OrderEnforcing)
        if hasattr(env.unwrapped.cfg, "metrics") and env.unwrapped.cfg.metrics is not None:
            return env.unwrapped.compute_metrics()
        return None


def _resolve_telemetry_env_name(args_cli: argparse.Namespace) -> str:
    """Resolve the environment name that evaluation telemetry is attached to.

    The name is the join key between an evaluation run and its environment node in the graph, so a
    generic fallback silently orphans the run. Registered example environments arrive under the
    subparser destination ``example_environment`` rather than ``environment_name``, which is why
    both are consulted before the graph-spec filename.

    Args:
        args_cli: Parsed evaluation arguments.

    Returns:
        The resolved name, or ``"arena_env"`` when no source identifies the environment.
    """
    for attr in ("environment_name", "example_environment"):
        candidate = getattr(args_cli, attr, None)
        if candidate and candidate != "arena_env":
            return str(candidate)

    yaml_arg = getattr(args_cli, "env_graph_spec_yaml", None)
    if yaml_arg:
        from pathlib import Path

        return Path(yaml_arg).stem.replace("_env_graph", "")

    return "arena_env"


def list_variations(args_parser: argparse.ArgumentParser) -> None:
    """Print the Hydra-configurable variations for the selected environment."""
    args_parser = get_isaaclab_arena_environments_cli_parser(args_parser)
    args_cli, hydra_overrides = args_parser.parse_known_args()
    assert_hydra_overrides(hydra_overrides, args_parser)
    arena_builder = get_arena_builder_from_cli(args_cli, hydra_overrides=hydra_overrides)
    print(arena_builder.get_variations_catalogue_as_string())


def main():
    """Run an IsaacLab Arena environment with a policy.
    Use --distributed with torchrun command for one process per GPU on multi-GPU machines. AppLauncher uses LOCAL_RANK for device.
    """
    args_parser = get_isaaclab_arena_cli_parser()
    # We do this as the parser is shared between the example environment and policy runner
    args_cli, unknown = args_parser.parse_known_args()

    local_rank = get_local_rank()
    world_size = get_world_size()
    # Setting device to local rank before SimulationAppContext
    if is_distributed(args_cli):
        args_cli.device = f"cuda:{local_rank}"
        print(f"[Rank {local_rank}/{world_size}] One Isaac Lab instance per process on cuda:{local_rank}")

    # --record_camera_video requires cameras to be enabled at sim startup, before SimulationAppContext.
    if "--record_camera_video" in unknown:
        args_cli.enable_cameras = True

    with SimulationAppContext(args_cli):

        # Get the policy-type flag before proceeding to other arguments
        add_policy_runner_arguments(args_parser)
        args_cli, _ = args_parser.parse_known_args()

        # --list_variations only inspects the environment, so short-circuit reading other args.
        if args_cli.list_variations:
            list_variations(args_parser)
            return

        # Get the policy class from the policy type
        assert args_cli.policy_type is not None, "--policy_type is required."
        policy_cls = get_policy_cls(args_cli.policy_type)
        print(
            f"[Rank {local_rank}/{world_size}] Requested policy type: {args_cli.policy_type} -> Policy class:"
            f" {policy_cls}"
        )

        # Add the example environment arguments and config-derived policy arguments.
        args_parser = get_isaaclab_arena_environments_cli_parser(args_parser)
        args_parser = add_policy_cli_args(args_parser, policy_cls)
        args_cli, hydra_overrides = args_parser.parse_known_args()
        assert_hydra_overrides(hydra_overrides, args_parser)
        # Re-apply per-rank device after parse preventing device got overwritten by the default value
        if is_distributed(args_cli):
            args_cli.distributed = True
            args_cli.device = f"cuda:{local_rank}"
            # Per-rank seed when distributed so each process has a different seed
            if args_cli.seed is not None:
                args_cli.seed += local_rank

        # Re-apply enable_cameras: the full parse resets it to default False.
        if args_cli.record_camera_video:
            args_cli.enable_cameras = True

        # Build scene. Use rgb_array render mode when recording so RecordVideo can grab frames.
        arena_builder = get_arena_builder_from_cli(args_cli, hydra_overrides=hydra_overrides)

        output_dir = timestamped_run_dir(args_cli.output_base_dir)
        video_cfg = VideoRecordingCfg(
            record_viewport_video=args_cli.record_viewport_video,
            record_camera_video=args_cli.record_camera_video,
            video_base_dir=output_dir,
        )
        env = make_recorded_environment(arena_builder, output_dir, video_cfg.render_mode)

        # Write per-episode results to disk.
        results_path = os.path.join(output_dir, f"episode_results_rank{local_rank}.jsonl")
        env.unwrapped.episode_recorder.set_job_name("policy_runner")
        env.unwrapped.episode_recorder.set_output_path(results_path)

        # Create the policy through the typed config compatibility adapter.
        policy = build_policy_from_cli(policy_cls, args_cli)

        # Simulation length.
        if policy.has_length():
            num_steps = policy.length()
            num_episodes = None
        else:
            if args_cli.num_steps is not None:
                num_steps = args_cli.num_steps
                num_episodes = None
                print(f"[Rank {local_rank}/{world_size}] Simulation length: {num_steps} steps")
            elif args_cli.num_episodes is not None:
                num_steps = None
                num_episodes = args_cli.num_episodes
                print(f"[Rank {local_rank}/{world_size}] Simulation length: {num_episodes} episodes")
            else:
                raise ValueError(f"[Rank {local_rank}/{world_size}] Either num_steps or num_episodes must be provided")

        # Optionally wrap with the viewport/camera video recorders (both independent).
        env = wrap_env_for_video(env, video_cfg, num_steps, num_episodes)

        steps_str = f"{num_steps} steps" if num_steps is not None else f"{num_episodes} episodes"
        print(f"[Rank {local_rank}/{world_size}] Starting rollout ({steps_str})")
        metrics = rollout_policy(
            env,
            policy,
            num_steps,
            num_episodes,
            check_settling=getattr(args_cli, "check_settling", True),
            settle_steps=getattr(args_cli, "settle_steps", 12),
            trace_reach=getattr(args_cli, "trace_reach", None),
            trace_reach_object=getattr(args_cli, "trace_reach_object", None),
            trace_reach_destination=getattr(args_cli, "trace_reach_destination", None),
            trace_reach_hand_body=getattr(args_cli, "trace_reach_hand_body", None),
            lin_vel_thresh=getattr(args_cli, "settle_lin_vel_thresh", 0.1),
            ang_vel_thresh=getattr(args_cli, "settle_ang_vel_thresh", 1.0),
        )

        if metrics is not None:
            print(f"[Rank {local_rank}/{world_size}] Metrics: {metrics_to_plain_python_types(metrics)}")

        # NOTE(huikang, 2025-12-30)Explicitly clean up the remote policy client / server.
        # Do NOT rely on a __del__ destructor in policy for this, since destructors are
        # triggered implicitly and their execution time (or even whether they run)
        # is not guaranteed, which makes resource cleanup unreliable.
        if policy.is_remote:
            policy.shutdown_remote(kill_server=args_cli.remote_kill_on_exit)

        # Close the environment.
        env.close()

        # Write and serve the evaluation report.
        # Only the local rank 0 writes/serves it, to avoid races on a shared output dir.
        if get_local_rank() == 0:
            if metrics is not None:
                try:
                    from isaaclab_arena.evaluation.telemetry_to_prov import record_eval_telemetry_to_prov

                    env_name = _resolve_telemetry_env_name(args_cli)
                    policy_name = getattr(args_cli, "policy_type", None)
                    plain_metrics = metrics_to_plain_python_types(metrics)
                    record_eval_telemetry_to_prov(
                        output_dir=output_dir,
                        env_name=env_name,
                        metrics=plain_metrics if isinstance(plain_metrics, dict) else {},
                        policy_name=policy_name,
                    )

                    # Auto-update EnvironmentVersionManager lineage ledger if inside versioned tree
                    try:
                        from isaaclab_arena.agentic_environment_generation.version_manager import (
                            EnvironmentVersionManager,
                        )

                        yaml_arg = getattr(args_cli, "env_graph_spec_yaml", None)
                        if yaml_arg:
                            from pathlib import Path

                            p = Path(yaml_arg).resolve()
                            if "generated_envs" in p.parts:
                                idx = p.parts.index("generated_envs")
                                if len(p.parts) > idx + 2 and p.parts[idx + 2].startswith("v"):
                                    e_name = p.parts[idx + 1]
                                    v_str = p.parts[idx + 2][1:]
                                    if v_str.isdigit():
                                        v_num = int(v_str)
                                        vm = EnvironmentVersionManager(e_name)
                                        vm.record_evaluation_metrics(
                                            version=v_num,
                                            metrics=plain_metrics if isinstance(plain_metrics, dict) else {},
                                            eval_output_dir=output_dir,
                                        )
                                        print(
                                            f"[policy_runner] 📜 Auto-updated lineage ledger for {e_name} v{v_num} with"
                                            " evaluation metrics."
                                        )
                    except Exception as exc:
                        print(f"Warning: Failed to update EnvironmentVersionManager lineage: {exc}")
                except Exception as exc:
                    print(f"Warning: Failed to record PROV-O telemetry: {exc}")

            report_path = build_report(output_dir)
            if args_cli.serve_evaluation_report:
                serve_until_ctrl_c(report_path.parent, args_cli.evaluation_report_port, report_path.name)


if __name__ == "__main__":
    main()
