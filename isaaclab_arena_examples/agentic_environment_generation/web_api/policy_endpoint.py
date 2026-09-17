# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Operator-only loopback GR00T configuration and immutable worker targets."""

import os
import re

GR00T_PORT_ENV = "ARENA_WORKBENCH_GR00T_PORT"
LEGACY_GR00T_PORT = 5555


def validate_gr00t_port(value):
    """Validate a captured integer without consulting mutable process configuration."""
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("Invalid GR00T port")
    return value


def configured_gr00t_port():
    """Read a canonical decimal TCP port; an invalid explicit value never defaults."""
    value = os.environ.get(GR00T_PORT_ENV)
    if value is None:
        return LEGACY_GR00T_PORT
    if re.fullmatch(r"[1-9][0-9]{0,4}", value) is None or int(value) > 65535:
        raise ValueError("Invalid GR00T port configuration")
    return int(value)
