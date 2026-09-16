# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Fixed native-client profiles, not policy-server readiness or checkpoint identity."""

FIXED = {"headless": True, "enable_cameras": True, "num_envs": 1, "num_steps": 1000}
PROFILES = (
    {"id": "gr00t-droid", "label": "GR00T DROID", "remote_host": "127.0.0.1", "remote_port": 5555},
    {"id": "openpi-droid", "label": "OpenPI DROID", "remote_host": "127.0.0.1", "remote_port": 8000},
)


def compatible_spec(spec):
    """Require the registered absolute-joint DROID adapter without camera/state overrides.

    DroidAbsoluteJointPositionEmbodiment supplies seven absolute arm joints plus
    its zero-to-one gripper and external_camera/wrist_camera RGB observations.
    Both native provider adapters consume that registered layout. Never remap IK,
    relative joints, concatenated state or explicitly disabled cameras.
    """
    embodiment = spec.get("embodiment", {})
    params = embodiment.get("params", {})
    allowed_params = {
        "enable_cameras",
        "concatenate_observation_terms",
        "arm_mode",
        "initial_pose",
        "initial_joint_pose",
        "initial_joint_pos",
        "stand_height_m",
        "finger_contact_friction",
    }
    if (
        embodiment.get("registry_name") != "droid_abs_joint_pos"
        or set(params) - allowed_params
        or params.get("arm_mode") not in (None, "single_arm")
        or params.get("enable_cameras", True) is not True
        or params.get("concatenate_observation_terms", False) is not False
    ):
        raise ValueError("Evaluation requires droid_abs_joint_pos with DROID cameras and separate observations")
    return spec["env_name"]
