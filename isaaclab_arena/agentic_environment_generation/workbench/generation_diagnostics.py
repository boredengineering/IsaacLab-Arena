# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure, closed public generation diagnostic schema; never accepts exception text."""

GENERATION_STAGES = frozenset({
    "agent_initializing",
    "catalogues_loading",
    "graph_priors_loading",
    "spec_inference",
    "prim_paths_resolving",
    "spatial_grounding",
    "validation_iteration_1",
    "validation_iteration_2",
    "generation_completed",
    "result_validating",
})
DIAGNOSTIC_STAGES = GENERATION_STAGES | {"worker_starting"}
DIAGNOSTIC_CODES = frozenset({
    "provider_authentication",
    "provider_permission",
    "provider_rate_limit",
    "provider_model_unavailable",
    "provider_request_rejected",
    "provider_schema_rejected",
    "provider_schema_min_items_unsupported",
    "provider_schema_max_items_unsupported",
    "provider_schema_prefix_items_unsupported",
    "provider_parameter_unsupported",
    "provider_timeout",
    "provider_connection",
    "dependency_unavailable",
    "required_retrieval_unavailable",
    "invalid_specification",
    "worker_protocol",
    "worker_exited",
    "worker_timeout",
    "internal_error",
})


def checked_diagnostic(value):
    """Validate the exact versioned shape and return a detached static-only copy."""
    if (
        type(value) is not dict
        or set(value) != {"schema_version", "code", "stage"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["code"]) is not str
        or value["code"] not in DIAGNOSTIC_CODES
        or type(value["stage"]) is not str
        or value["stage"] not in DIAGNOSTIC_STAGES
    ):
        raise ValueError("Invalid generation diagnostic")
    return {"schema_version": 1, "code": value["code"], "stage": value["stage"]}
