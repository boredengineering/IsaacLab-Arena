# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Cleanup failures veto graph evidence, independently of availability policy."""

import sys
from contextlib import contextmanager


class GraphCleanupError(ValueError):
    """An owned graph resource failed cleanup; retrieval fallback is forbidden."""


def close_graph_resources(*resources):
    """Attempt every owned close and veto the result if any cleanup fails."""
    failed = False
    for resource in resources:
        if resource is not None:
            try:
                resource.close()
            except Exception:
                failed = True
    if failed:
        raise GraphCleanupError("Graph retrieval cleanup failed") from None


@contextmanager
def graph_session(session):
    """Run session exit while keeping query and cleanup failures unsuppressible."""
    value = session.__enter__()
    try:
        yield value
    finally:
        try:
            session.__exit__(*sys.exc_info())
        except Exception:
            raise GraphCleanupError("Graph retrieval cleanup failed") from None
