# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bound and normalize worker diagnostics without inventing successful artifacts."""

import math


def clean_errors(value):
    if not isinstance(value, list):
        return []
    return [
        {key: error[key][: 1000 if key == "message" else 128] for key in ("id", "stage", "code", "message")}
        for error in value[:256]
        if isinstance(error, dict)
        and all(isinstance(error.get(key), str) for key in ("id", "stage", "code", "message"))
    ]


def clean_timings(value):
    if not isinstance(value, dict):
        return {}
    return {
        key: value
        for key, value in list(value.items())[:256]
        if isinstance(key, str)
        and len(key) <= 100
        and type(value) in (int, float)
        and math.isfinite(value)
        and value >= 0
    }
