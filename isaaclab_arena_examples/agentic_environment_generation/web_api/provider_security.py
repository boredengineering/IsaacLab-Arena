# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Small secret-boundary helpers shared by the API and its private worker."""

import os
from contextlib import contextmanager

from isaaclab_arena.agentic_environment_generation.workflow.provider_configuration import (  # noqa: F401
    ENDPOINTS,
    PROVIDERS,
    checked_config,
    reject_secret,
)


@contextmanager
def bounded_client(config, *, allowance=None):
    """Install transport before the legacy agent's initialization ping, in its isolated worker only."""
    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import CallAllowance
    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import (
        bounded_client as shared_bounded_client,
    )

    # Legacy contexts retain eight calls, a 45s HTTP timeout and no new expiry.
    with shared_bounded_client(
        config,
        allowance=allowance if allowance is not None else CallAllowance(max_calls=8, deadline=float("inf")),
        strict_model_binding=allowance is not None,
    ) as client:
        yield client


def worker_environment(api_key):
    """Pass runtime search paths, not inherited credentials or provider overrides."""
    allowed = {"PATH", "PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}
    return {key: value for key, value in os.environ.items() if key in allowed and (not api_key or api_key not in value)}
