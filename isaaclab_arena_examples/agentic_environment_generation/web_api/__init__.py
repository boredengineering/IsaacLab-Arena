# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Local single-operator workbench API factory."""

__all__ = ["create_app"]


def __getattr__(name):
    """Load the legacy app factory only when explicitly requested."""
    if name == "create_app":
        from .application import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
