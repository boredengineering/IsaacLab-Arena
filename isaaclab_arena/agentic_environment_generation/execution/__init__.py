# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Boundary execution workers for the agentic environment generation pipeline.

Architectural Invariant:
- Modules in this package MUST NEVER import `isaaclab_arena.agentic_environment_generation.workflow`
  or any control-plane GraphQL / coordinator modules.
- Heavy simulator (`isaacsim`, `omni`) and tensor (`torch`) imports are strictly deferred inside
  runtime methods so importing this package on CPU is instantaneous and side-effect-free.
"""

from .policy_rollout_worker import PolicyRolloutResult, PolicyRolloutWorker, run_zero_action_policy
from .preflight_oracle import (
    PreflightOracleWorker,
    PreflightTriadStatus,
    check_preflight_service_triad,
    probe_service_triad,
    verify_neo4j_endpoint,
    verify_service_endpoint,
)
from .refiner_worker import RefinementResult, RefinerWorker, preproject_repair_proposal
from .simulation_worker import (
    AttemptLeaseCleanupReceipt,
    DeltaPoseMutation,
    DeltaPoseMutationMap,
    PersistentSimulationSession,
    PreparedAttemptHandle,
    SettleCaptureResult,
    SimulationWorkerIPCServer,
    SimulationWorkerPort,
    relower_relations_to_object_poses,
)
from .spec_synthesis_worker import (
    SpecSynthesisResult,
    SpecSynthesisWorker,
    build_permissive_fallback_spec,
    resolve_env_spec,
    retrieve_graph_exemplars,
)
from .visual_critic_worker import (
    VisualCriticResult,
    VisualCriticWorker,
    filter_robot_link_false_positives,
)

__all__ = [
    "AttemptLeaseCleanupReceipt",
    "DeltaPoseMutation",
    "DeltaPoseMutationMap",
    "PersistentSimulationSession",
    "PolicyRolloutResult",
    "PolicyRolloutWorker",
    "PreflightOracleWorker",
    "PreflightTriadStatus",
    "PreparedAttemptHandle",
    "RefinementResult",
    "RefinerWorker",
    "SettleCaptureResult",
    "SimulationWorkerIPCServer",
    "SimulationWorkerPort",
    "SpecSynthesisResult",
    "SpecSynthesisWorker",
    "VisualCriticResult",
    "VisualCriticWorker",
    "build_permissive_fallback_spec",
    "check_preflight_service_triad",
    "filter_robot_link_false_positives",
    "preproject_repair_proposal",
    "probe_service_triad",
    "relower_relations_to_object_poses",
    "resolve_env_spec",
    "retrieve_graph_exemplars",
    "run_zero_action_policy",
    "verify_neo4j_endpoint",
    "verify_service_endpoint",
]
