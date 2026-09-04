# Copyright (c) 2025-2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
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
    for name in scene.keys():
        if name in ("robot", "terrain", "ground", "maple_table", "table") or "robot" in name:
            continue
        asset = scene[name]
        if hasattr(asset, "data") and hasattr(asset.data, "root_lin_vel_w"):
            movable_objects.append(name)

    obs = None
    max_steps = max(settle_steps, 25)
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
                break
            if step_idx >= 15:
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
                if curr_settled:
                    break

    settle_status = {}
    all_settled = True
    print(
        f"[policy_runner] 🔍 Phase 1 Settle Verification: Checking {len(movable_objects)} scene objects for"
        " stationarity..."
    )
    for name in movable_objects:
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
        print("[policy_runner] ✅ All scene objects are physically settled. Proceeding to policy inference.")
    else:
        print("[policy_runner] ⚠️ Warning: One or more objects are NOT sitting still at inference start!")

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
    ):
        self._path = path
        self._rows: list[str] = []
        self._env = base_env
        self._object_name = object_name
        self._destination_name = destination_name
        self._contact_sensor_name = contact_sensor_name
        self._rest_z: torch.Tensor | None = None
        self._step = 0

    def _pos(self, name):
        return wp.to_torch(self._env.scene[name].data.root_pos_w)

    def record(self) -> None:
        obj = self._pos(self._object_name)
        speed = wp.to_torch(self._env.scene[self._object_name].data.root_lin_vel_w).norm(dim=-1)
        z = obj[:, 2]
        # Resting reference: first sample taken while essentially still.
        if self._rest_z is None and bool((speed < 1e-2).all()):
            self._rest_z = z.clone()
        row = {
            "step": self._step,
            "obj_z": [round(v, 5) for v in z.tolist()],
            "speed": [round(v, 5) for v in speed.tolist()],
        }
        if self._rest_z is not None:
            row["lift"] = [round(v, 5) for v in (z - self._rest_z).tolist()]
        if self._destination_name is not None:
            dest = self._pos(self._destination_name)
            row["dist_to_dest"] = [round(v, 5) for v in (obj - dest).norm(dim=-1).tolist()]
            row["xy_to_dest"] = [round(v, 5) for v in (obj[:, :2] - dest[:, :2]).norm(dim=-1).tolist()]
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

    def close(self) -> None:
        """Write the buffered trace. Called on every rollout exit path, including exceptions."""
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
                    # Break if number of episodes is reached
                    completed_episodes = env_ids.shape[0]
                    num_episodes_completed += completed_episodes
                    if hasattr(env.unwrapped.cfg, "metrics") and env.unwrapped.cfg.metrics is not None:
                        metrics = env.unwrapped.compute_metrics()
                        tqdm.tqdm.write(
                            f"[Rank {get_local_rank()}/{get_world_size()}] Metrics:"
                            f" {metrics_to_plain_python_types(metrics)}"
                        )
                    if num_episodes is not None:
                        pbar.update(completed_episodes)
                        if num_episodes_completed >= num_episodes:
                            break
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
        env = arena_builder.make_registered(render_mode=video_cfg.render_mode)

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
