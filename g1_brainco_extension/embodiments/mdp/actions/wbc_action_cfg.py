# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations
from dataclasses import MISSING
from isaaclab.utils import configclass
from isaaclab_arena_g1.g1_env.mdp.actions.g1_decoupled_wbc_joint_action_cfg import G1DecoupledWBCJointActionCfg
from g1_brainco_extension.embodiments.mdp.actions.wbc_action import G1BraincoWBCAction

@configclass
class G1BraincoWBCActionCfg(G1DecoupledWBCJointActionCfg):
    """Configuration for G1 Brainco custom action term."""
    class_type: type = G1BraincoWBCAction
    lock_waist: bool = True
