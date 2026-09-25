# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit retained-candidate native composition; no model transport or credentials."""

import hashlib
import json
import time
from pathlib import Path
from threading import Lock
from typing import Annotated

from pydantic import Field, model_validator

from ..contracts import Amount, FrozenModel, Hash, Identifier, ProfileReference, contract_digest
from ..native_capture import NativeCaptureSettings

MODE = "retained-native-validation-v1"
CAPABILITIES = {"mode": MODE, "submit": True, "cancel": True, "resume": False, "required_policy": False}


class NativeSelection(FrozenModel):
    """Frozen selection; only a separate explicit launch approval enables execution."""

    candidate_sha256: Hash
    contract_sha256: Hash
    source_identity: Identifier
    scene_namespace: Identifier
    operation_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=3)]
    approval_expires_at: Amount
    database_profile: ProfileReference
    settings: NativeCaptureSettings
    gpu_lease_path: str

    @model_validator(mode="after")
    def bounded(self):
        if (
            len(set(self.operation_ids)) != len(self.operation_ids)
            or not Path(self.gpu_lease_path).is_absolute()
            or not self.settings.evidence_only
            or self.settings.max_runtime_seconds > 590
            or self.settings.window.start_step != self.settings.window.end_step
        ):
            raise ValueError("Bounded model-free native selection required")
        return self


def protect(value):
    """No model secret exists; strict public JSON encoding still applies."""
    from ..scene_evidence_artifacts import canonical

    canonical(value)


def compose(config, *, tokens, auth, native_authorized=False):
    """Compose existing owners and split scene ports after separate operator approval."""
    if config.value["schema_version"] != 4 or config.value["mode"] != MODE or native_authorized is not True:
        raise PermissionError("Separate explicit native launch approval required")
    selected = NativeSelection.model_validate_json(json.dumps(config.value["native_validation"]))
    if config.profiles:
        raise ValueError("Native-only execution must not select model profiles")

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena_examples.agentic_environment_generation import foreground_cancellation
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import ForegroundAuthority
    from isaaclab_arena_examples.agentic_environment_generation.foreground_native_scene import (
        ForegroundNativeCaptureWorker,
        ForegroundNumericAssessmentWorker,
    )
    from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease
    from isaaclab_arena_examples.agentic_environment_generation.foreground_recovery import OwnershipArtifacts
    from isaaclab_arena_examples.agentic_environment_generation.foreground_split_scene_ports import (
        ForegroundSplitScenePorts,
    )
    from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants

    from ..application import ForegroundWorkflow
    from ..artifacts import GenerationArtifacts
    from ..bootstrap import ObservationOnlyPort, ScopedHostBootstrap
    from ..native_capture import NativeCaptureProducer
    from ..native_resources import NativeGpuLease
    from ..readiness import DependencyRequirement, DependencyResult
    from ..scene_evidence_artifacts import SceneEvidenceArtifacts
    from ..scene_loop import ScenePortProfile, SceneReservation
    from ..split_scene_ports import OwnedSceneStageAdapter, SplitScenePorts
    from .execution_owner import ExecutionOwner
    from .installed_composition import PrivateRoles

    roles = PrivateRoles(config)
    if roles.document["models"] or set(roles.document["databases"]) != {"operational"}:
        raise ValueError("Native-only private setup requires only the operational database binding")
    lock, built = Lock(), False

    def unavailable(*args, **kwargs):
        raise PermissionError("Generation, model assessment, repair and prior retrieval are disabled")

    def build(store, verified, protect):
        nonlocal built
        with lock:
            if built:
                raise ValueError("Native composition already consumed")
            built = True
        if verified.binding != config.binding or verified.profiles:
            raise ValueError("Verified native resources differ")
        area = ArtifactArea.open(
            config.value["artifact_root"], store_id=config.binding.store_id, registry_id=config.binding.registry_id
        )
        authority = None
        try:
            scope = dict(database=store.database, **store.scope)

            def principal_lookup(principal):
                tokens.recheck(auth)
                if principal != auth.principal:
                    raise PermissionError("Exact native operator required")
                return dict(principal=principal, **scope, expires_at=auth.expires_at, revoked=False)

            def native_admission(principal, operation_id, contract):
                principal_lookup(principal)
                roles.check_current()
                if (
                    contract.schema_version != "3"
                    or contract.source.kind != "existing"
                    or operation_id not in selected.operation_ids
                    or time.time() >= selected.approval_expires_at
                    or contract_digest(contract) != selected.contract_sha256
                    or contract.source.identity != selected.source_identity
                    or hashlib.sha256(contract.source.content.encode("utf-8")).hexdigest() != selected.candidate_sha256
                    or json.loads(contract.source.content).get("env_name") != selected.scene_namespace
                    or contract.execution.database != selected.database_profile
                    or contract.budget.max_realizations != 1
                    or contract.budget.max_observations != 1
                    or contract.budget.max_steps != selected.settings.window.end_step
                    or contract.budget.per_operation_timeout_seconds > 600
                ):
                    raise PermissionError("Native request differs from the explicit bounded approval")
                return True

            authority = ForegroundAuthority(
                **scope,
                store=store,
                grants=ExecutionGrants(clock=time.time),
                clock=time.time,
                principal_lookup=principal_lookup,
                profiles={},
                current_config=unavailable,
                source_guard=roles.release_guard,
                native_admission=native_admission,
            )
            grant_protect = authority.protect_public

            def protect_all(value):
                protect(value)
                grant_protect(value)

            authority.protect_public = protect_all
            settings = selected.settings
            references = dict(
                runtime=settings.runtime_reference(),
                capture=settings.capture_reference(),
                gpu=settings.runtime_reference(),
                neo4j=selected.database_profile,
            )
            approved = tuple(
                DependencyRequirement(role, ref.settings_sha256, profile_id=ref.profile_id)
                for role, ref in references.items()
            )

            def probe(required, timeout):
                import importlib.util
                import subprocess

                reference = references.get(required.dependency_id)
                passed = reference is not None and (required.profile_id, required.profile_sha256) == (
                    reference.profile_id,
                    reference.settings_sha256,
                )
                if passed and required.dependency_id == "neo4j":
                    passed = store.verify_schema() is True
                    store.get_owner()
                elif passed and required.dependency_id == "runtime":
                    passed = importlib.util.find_spec("isaaclab") is not None
                elif passed and required.dependency_id == "gpu":
                    result = subprocess.run(
                        ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
                        capture_output=True,
                        check=False,
                        timeout=min(5, timeout),
                    )
                    passed = result.returncode == 0 and settings.device.removeprefix("cuda:") in (
                        result.stdout.decode("ascii").split()
                    )
                return DependencyResult(
                    required.dependency_id,
                    "passed" if passed else "unavailable",
                    required.profile_sha256,
                    profile_id=required.profile_id,
                    instance_id=required.instance_id,
                )

            capture_budget = dict(
                model_calls=0,
                model_tokens=0,
                cost_ceiling_usd=0.0,
                runtime_allowance_seconds=600.0,
                realizations=1,
                observations=1,
                steps=settings.window.end_step,
            )
            numeric_budget = dict(model_calls=0, model_tokens=0, cost_ceiling_usd=0.0, runtime_allowance_seconds=30.0)
            profile = ScenePortProfile(
                codec_version=2,
                port_id=MODE,
                assurance="native-unverified",
                owned_worker=True,
                producer_ids=tuple(sorted({c.evidence_producer for c in settings.criteria})),
                capture=SceneReservation.model_validate(capture_budget),
                assess=SceneReservation.model_validate(numeric_budget),
                repair=SceneReservation.model_validate(dict(numeric_budget, candidates=1, revisions=1)),
            )
            artifacts = SceneEvidenceArtifacts(area)
            producer = NativeCaptureProducer(
                settings=settings,
                artifacts=artifacts,
                protect=protect_all,
                output_root=Path(config.value["artifact_root"]) / "native-capture-work",
            )
            scene_options = dict(
                profile=profile,
                artifacts=artifacts,
                model_ceilings={},
                capture_start_step=settings.window.start_step,
                capture_steps=settings.window.end_step - settings.window.start_step,
                capture_timeout_seconds=settings.max_runtime_seconds,
                native_producer=producer,
                output_root=Path(config.value["artifact_root"]) / "native-capture-work",
                direct_root_subjects=tuple(s.subject_id for s in settings.subjects),
                displacement_tolerance_m=0.001,
            )
            support = SplitScenePorts(
                **scene_options,
                capture_stage=unavailable,
                protect=protect_all,
                authorize=None,
                ready=None,
                refine=None,
                visual=None,
                check_active=lambda: None,
            )

            def authorize_native(intent, contract):
                run_id = intent.worker_fence.run_id if intent.worker_fence is not None else None
                if run_id is None:
                    # The service's check-only pre-claim call still has a retained candidate.
                    candidate = store.get_scene_candidate(intent.candidate_id)
                    run_id = candidate.run_id
                run = store.get_run(run_id)
                native_admission(auth.principal, run.operation_id, contract)
                authority.require_scene_execute(auth.principal, contract, run_id=run_id, retained_run=run)
                return True

            def scene_worker_factory(*, ownership_artifacts):
                options = dict(
                    settings=settings,
                    artifacts=artifacts,
                    artifact_root=config.value["artifact_root"],
                    ownership_artifacts=ownership_artifacts,
                )
                return OwnedSceneStageAdapter(
                    native_worker=ForegroundNativeCaptureWorker(**options),
                    model_worker=None,
                    numeric_worker=ForegroundNumericAssessmentWorker(**options),
                    gpu_lease=NativeGpuLease(selected.gpu_lease_path),
                    authorize_native=authorize_native,
                )

            app = ForegroundWorkflow(
                store=store,
                authority=authority,
                gate=ScopedHostBootstrap(ObservationOnlyPort(approved, probe), allow_startup=False),
                private_parent=config.value["private_root"],
                artifacts=GenerationArtifacts(area),
                artifact_root=config.value["artifact_root"],
                catalogue_sha256=settings.digest(),
                generation_reservation=None,
                prior_factory=unavailable,
                initial_worker_factory=unavailable,
                scene_worker_factory=scene_worker_factory,
                validate_document=unavailable,
                scene_options=scene_options,
                owner_lease_factory=ForegroundOwnerLease,
                initial_receiver_factory=unavailable,
                scene_ports_factory=ForegroundSplitScenePorts,
                recovery_factory=unavailable,
                ownership_artifacts_factory=OwnershipArtifacts,
                cancellation=foreground_cancellation,
                native_support=support,
            )

            def authorize_control(kind, principal, run_id):
                if kind != "cancel":
                    raise PermissionError("Native continuation requires a separate approved operation")
                principal_lookup(principal)

            return ExecutionOwner(app, area, tokens, protect_all, authorize_control=authorize_control)
        except BaseException:
            if authority is not None:
                authority.close()
            area.close()
            raise

    return build
