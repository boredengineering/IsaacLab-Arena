# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Frozen configurable selection over the existing foreground owner and split ports."""

import hashlib
import json
import time
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ..contracts import Amount, FrozenModel, Identifier, WorkflowContract, contract_digest
from ..native_capture import NativeCaptureSettings
from ..scene_evidence_artifacts import canonical

MODE = "full-scene-workflow-v1"
CAPABILITIES = {"mode": MODE, "submit": True, "cancel": True, "resume": False, "required_policy": False}


class SelectedCase(FrozenModel):
    operation_id: Identifier
    contract: WorkflowContract


class FullSceneSelection(FrozenModel):
    """An installed selection is neither a grant nor approval of a proposed empirical case."""

    codec: Literal["installed-full-scene-v1"]
    cases: Annotated[tuple[SelectedCase, ...], Field(min_length=1, max_length=8)]
    settings: NativeCaptureSettings
    catalogue: dict
    gpu_lease_path: str
    approval_expires_at: Amount | None

    @model_validator(mode="after")
    def coherent(self):
        from isaaclab_arena.environment_spec.execution_catalogue import ExecutionCatalogue

        from ..native_capture import NativeCaptureProducer

        if (
            self.settings.codec != "native-capture-v2"
            or not Path(self.gpu_lease_path).is_absolute()
            or len({case.operation_id for case in self.cases}) != len(self.cases)
        ):
            raise ValueError("Explicit distinct configurable cases and native adapter required")
        ExecutionCatalogue(self.catalogue)
        producer = NativeCaptureProducer(settings=self.settings, artifacts=None, protect=protect, output_root=".")
        first = self.cases[0].contract
        for case in self.cases:
            contract = case.contract
            producer.admit(contract)
            if (
                contract.schema_version != "5"
                or contract.retrieval is not None
                or contract.effects.allow_database_reads
                or contract.execution.policy is not None
                or contract.budget.control != first.budget.control
                or contract.execution.database != first.execution.database
            ):
                raise ValueError("Exact scene-only scope, no-prior policy and control selection required")
        return self

    def digest(self):
        return hashlib.sha256(canonical(self.model_dump(mode="json"))).hexdigest()


def protect(value):
    canonical(value)


def selection(config):
    if (config.value["schema_version"], config.value["mode"]) != (6, MODE):
        raise ValueError("Explicit installed configurable mode required")
    return FullSceneSelection.model_validate_json(canonical(config.value["full_scene"]))


def check_contract(config, contract, *, operation_id=None):
    selected = selection(config)
    matches = [
        case
        for case in selected.cases
        if contract_digest(case.contract) == contract_digest(contract)
        and (operation_id is None or case.operation_id == operation_id)
    ]
    if len(matches) != 1:
        raise ValueError("Contract differs from the exact installed case selection")
    return selected, matches[0]


def inspect(config, contract):
    """Resolve source, parameters, roles and raw/canonical/semantic bytes without effects."""
    from isaaclab_arena.environment_spec.execution_catalogue import ExecutionCatalogue

    from ..readiness import required_dependencies
    from ..scene_ports import ScenePorts

    selected, case = check_contract(config, contract)
    catalogue = ExecutionCatalogue(selected.catalogue)
    source = dict(kind=contract.source.kind, initial_generation_required=contract.source.kind == "new")
    if contract.source.kind == "existing":
        from ..repairs import _scene_json

        raw = contract.source.content.encode("utf-8")
        candidate = _scene_json(json.loads(raw))
        with catalogue.activate():
            spec = ScenePorts.validate_candidate(candidate)
        source.update(
            source_identity=contract.source.identity,
            source_bytes_sha256=hashlib.sha256(raw).hexdigest(),
            canonical_candidate_sha256=hashlib.sha256(candidate.encode()).hexdigest(),
            validated_semantic_sha256=hashlib.sha256(canonical(spec.model_dump(mode="json"))).hexdigest(),
            canonical_candidate_utf8=candidate,
        )
    result = dict(
        codec="installed-full-scene-inspection-v1",
        mode=MODE,
        operation_id=case.operation_id,
        contract_digest=contract_digest(contract),
        selection_digest=selected.digest(),
        settings_digest=selected.settings.digest(),
        catalogue_digest=catalogue.sha256,
        source=source,
        contract=contract.model_dump(mode="json"),
        dependencies=[
            dict(role=item.dependency_id, profile_id=item.profile_id, settings_sha256=item.profile_sha256)
            for item in required_dependencies(contract)
        ],
        prior_status="not_requested",
        native_worker_credentials=False,
        refinement_binding="shared_generation",
        admitted=False,
        provider_sends=0,
        native_releases=0,
        live_admission_or_child_execution_proven=False,
    )
    return result


def preview(config, contract):
    """Inspect real inputs; NewSource reaches the existing mandatory HTTP send denial."""
    result = inspect(config, contract)
    if contract.source.kind == "existing":
        result["model_request"] = "not_constructed_without_retained_measurements_and_eligible_feedback"
        return result
    from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.environment_spec.execution_catalogue import ExecutionCatalogue

    from ..inference_transport import CallAllowance
    from ..prior_artifacts import RetainedPriorArtifacts
    from ..scene_engines import BoundedSceneModels
    from .installed_composition import Resources

    chosen, _ = check_contract(config, contract)
    resources = Resources(config)
    private = resources.private_roles().model_config("generation")
    allowance = CallAllowance(
        max_calls=1,
        deadline=time.monotonic() + contract.budget.per_operation_timeout_seconds,
        per_call_bound=private["workflow_accounting"],
    )
    denied = []

    def deny(request):
        denied.append(hashlib.sha256(request.content).hexdigest())
        raise PermissionError("Provider sends denied during configurable preview")

    with ArtifactArea.open(
        config.value["artifact_root"], store_id=config.binding.store_id, registry_id=config.binding.registry_id
    ) as area:
        priors = RetainedPriorArtifacts(area)
        preview_id = "preview-" + contract_digest(contract)
        prior = priors.write(
            contract.source.prompt,
            contract_digest(contract),
            preview_id,
            empty_snapshot(contract.source.prompt, status="not_requested", warning=None),
            protect=resources.protect,
        )
        catalogue = ExecutionCatalogue(chosen.catalogue)
        assets, relations, tasks = catalogue.catalogues()
        models = BoundedSceneModels(
            config=private,
            allowance=allowance,
            approved_roles={"generation": dict(model=private["model"], endpoint=private["base_url"])},
            send_guard=deny,
        )
        try:
            with catalogue.activate():
                models.generate(
                    prompt=contract.source.prompt,
                    contract_digest=contract_digest(contract),
                    run_id=preview_id,
                    priors=priors,
                    prior=prior,
                    require_prior=False,
                    protect=resources.protect,
                    asset_catalog=assets,
                    relation_catalog=relations,
                    task_catalog=tasks,
                )
        except Exception:
            if len(denied) != 1:
                raise ValueError("Actual generation request did not reach the mandatory send denial") from None
        else:
            raise ValueError("Mandatory send denial was not enforced")
        records = allowance.provider_records
        if len(records) != 1 or records[0]["dispatched"] or records[0]["response"] is not None:
            raise ValueError("Non-sending generation preview was not established")
        result.update(
            serialized_request=records[0]["serialized_request"],
            request_sha256=denied[0],
            denial_boundary="checked_sdk_http_request_hook",
            durable_allocation_changed=False,
            preview_artifact_id=preview_id,
            constructor_probe=False,
            sdk_retries=0,
        )
        resources.protect(result)
        return result


def native_supervision_context(*, config, tokens, auth, store, authority, admission, intent, contract):
    """Bind renewable control to the current released owner under its authority guard."""
    with authority.mutation_guard():
        api = tokens.current(auth)
        run_id = intent.worker_fence.run_id
        current = store.get_scene_intent(run_id, intent.intent_id)
        run = store.get_run(run_id)
        if (
            run.state != "running"
            or current.status != "released"
            or current.worker_fence != intent.worker_fence
            or current.worker_registration != intent.worker_registration
            or current.worker_cleanup is not None
        ):
            raise PermissionError("Exact current released native owner required")
        admission(api.principal, run.operation_id, contract)
        grant = authority.require_scene_execute(api.principal, contract, run_id=run_id, retained_run=run)
        admitted = store.inspection_bundle(run_id)["admitted_at"]
        return dict(
            scope=config.binding,
            instance=api.instance,
            principal=api.principal,
            credential_generation=api.generation,
            credential_expires_at=api.expires_at,
            authority=grant,
            admitted_at=admitted,
        )


def compose(config, *, tokens, auth, private_roles, workload_authorized=False):
    """Build one existing owner; absent separate approval, read/preview/cancel only."""
    from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.environment_spec.execution_catalogue import ExecutionCatalogue
    from isaaclab_arena_examples.agentic_environment_generation import foreground_cancellation
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import ForegroundAuthority
    from isaaclab_arena_examples.agentic_environment_generation.foreground_initial_generation import (
        InitialGenerationReceiver,
        InitialGenerationWorker,
    )
    from isaaclab_arena_examples.agentic_environment_generation.foreground_native_scene import (
        ForegroundNativeCaptureWorker,
        ForegroundNumericAssessmentWorker,
    )
    from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease
    from isaaclab_arena_examples.agentic_environment_generation.foreground_recovery import (
        ForegroundGenerationRecovery,
        OwnershipArtifacts,
    )
    from isaaclab_arena_examples.agentic_environment_generation.foreground_scene import ForegroundSceneWorker
    from isaaclab_arena_examples.agentic_environment_generation.foreground_split_scene_ports import (
        ForegroundSplitScenePorts,
    )
    from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants

    from ..application import ForegroundWorkflow
    from ..artifacts import GenerationArtifacts
    from ..attempts import GenerationReservation
    from ..bootstrap import ObservationOnlyPort, ScopedHostBootstrap
    from ..native_capture import NativeCaptureProducer
    from ..native_resources import NativeGpuLease, native_scratch_root
    from ..prior_artifacts import RetainedPriorArtifacts
    from ..readiness import DependencyResult, required_dependencies
    from ..scene_evidence_artifacts import SceneEvidenceArtifacts
    from ..scene_loop import ScenePortProfile, SceneReservation
    from ..scene_ports import ModelCeiling
    from ..split_scene_ports import OwnedSceneStageAdapter, SplitScenePorts
    from .execution_owner import ExecutionOwner

    selected = selection(config)
    catalogue = ExecutionCatalogue(selected.catalogue)
    lock, built = Lock(), False

    def unavailable(*args, **kwargs):
        raise PermissionError("No workload authority is conferred by setup or preview")

    def build(store, verified, protect):
        nonlocal built
        with lock:
            if built:
                raise ValueError("Installed composition already consumed")
            built = True
        if verified.binding != config.binding or verified.profiles != config.profiles:
            raise ValueError("Verified installed resources differ")
        roles = private_roles()
        roles.check_current()
        area = ArtifactArea.open(
            config.value["artifact_root"], store_id=config.binding.store_id, registry_id=config.binding.registry_id
        )
        authority = None
        try:
            scope = dict(database=store.database, **store.scope)

            def principal_lookup(principal):
                current = tokens.current(auth)
                if principal != current.principal:
                    raise PermissionError("Exact installed operator required")
                return dict(principal=principal, **scope, expires_at=current.expires_at, revoked=False)

            def admission(principal, operation_id, contract):
                principal_lookup(principal)
                check_contract(config, contract, operation_id=operation_id)
                roles.check_current()
                if (
                    workload_authorized is not True
                    or selected.approval_expires_at is None
                    or time.time() >= selected.approval_expires_at
                ):
                    unavailable()
                return selected.approval_expires_at

            model_configs, profiles = {}, {}
            for role in ("generation", "assessment"):
                registered = config.value["role_bindings"][role]["profile"]
                from ..profiles import ProfileRegistration, profile_revision

                revision = profile_revision(ProfileRegistration.model_validate_json(canonical(registered)))
                model_configs[role] = roles.model_config(role)
                profiles[revision.profile_id] = dict(
                    profile_id=revision.profile_id,
                    settings_sha256=revision.settings_sha256,
                    billing=revision.registration.settings.billing,
                )

            def current_config(profile_id):
                role = next(
                    role
                    for role in model_configs
                    if config.value["role_bindings"][role]["profile"]["profile_id"] == profile_id
                )
                return dict(
                    config=roles.model_config(role),
                    expires_at=(
                        selected.approval_expires_at
                        if selected.approval_expires_at is not None
                        else tokens.current(auth).expires_at
                    ),
                )

            authority = ForegroundAuthority(
                **scope,
                store=store,
                grants=ExecutionGrants(clock=time.time),
                clock=time.time,
                principal_lookup=principal_lookup,
                profiles=profiles,
                current_config=current_config,
                source_guard=roles.release_guard,
                full_scene_admission=admission,
            )
            grant_protect = authority.protect_public

            def protect_all(value):
                protect(value)
                roles.protect(value)
                grant_protect(value)

            authority.protect_public = protect_all
            settings = selected.settings
            artifacts = SceneEvidenceArtifacts(area)
            scratch = native_scratch_root(config.value["artifact_root"])
            producer = NativeCaptureProducer(
                settings=settings, artifacts=artifacts, protect=protect_all, output_root=scratch
            )
            per_operation = min(case.contract.budget.per_operation_timeout_seconds for case in selected.cases)
            models = {
                role: dict(
                    model_calls=1,
                    model_tokens=None,
                    cost_ceiling_usd=None,
                    accounting_policy="accounting-only-v1",
                    runtime_allowance_seconds=per_operation,
                )
                for role in model_configs
            }
            numeric = dict(model_calls=0, model_tokens=0, cost_ceiling_usd=0.0, runtime_allowance_seconds=per_operation)
            profile = ScenePortProfile(
                codec_version=2,
                workflow_schema="5",
                port_id=MODE,
                assurance="native-unverified",
                owned_worker=True,
                producer_ids=tuple(sorted({c.evidence_producer for c in settings.criteria})),
                capture=SceneReservation(
                    model_calls=0,
                    model_tokens=0,
                    cost_ceiling_usd=0.0,
                    runtime_allowance_seconds=None,
                    time_policy="accounting_only",
                    realizations=1,
                    observations=1,
                    steps=settings.acquisition.horizon_steps,
                ),
                assess=SceneReservation(
                    **(models["assessment"] if any(c.kind == "visual" for c in settings.criteria) else numeric)
                ),
                repair=SceneReservation(**models["generation"], candidates=1, revisions=1),
            )
            options = dict(
                profile=profile,
                artifacts=artifacts,
                model_ceilings={
                    role: ModelCeiling(1, None, None, per_operation, value["workflow_accounting"])
                    for role, value in model_configs.items()
                },
                capture_start_step=settings.window.start_step,
                capture_steps=settings.window.end_step - settings.window.start_step,
                capture_timeout_seconds=None,
                native_producer=producer,
                output_root=scratch,
                direct_root_subjects=tuple(s.subject_id for s in settings.subjects),
                displacement_tolerance_m=0.001,
            )
            support = SplitScenePorts(
                **options,
                capture_stage=unavailable,
                protect=protect_all,
                authorize=None,
                ready=None,
                refine=None,
                visual=None,
                check_active=lambda: None,
            )
            approved = tuple({item for case in selected.cases for item in required_dependencies(case.contract)})

            def probe(required, timeout):
                roles.check_current()
                passed = any(
                    (item.dependency_id, item.profile_id, item.profile_sha256)
                    == (required.dependency_id, required.profile_id, required.profile_sha256)
                    for item in approved
                )
                if passed and required.dependency_id == "neo4j":
                    passed = store.verify_schema() is True
                    store.get_owner()
                return DependencyResult(
                    required.dependency_id,
                    "passed" if passed else "unavailable",
                    required.profile_sha256,
                    profile_id=required.profile_id,
                    instance_id=required.instance_id,
                )

            def native_authorization(intent, contract):
                run_id = store.get_scene_candidate(intent.candidate_id).run_id
                run = store.get_run(run_id)
                admission(auth.principal, run.operation_id, contract)
                authority.require_scene_execute(auth.principal, contract, run_id=run_id, retained_run=run)
                return True

            def supervision_context(intent, contract):
                return native_supervision_context(
                    config=config,
                    tokens=tokens,
                    auth=auth,
                    store=store,
                    authority=authority,
                    admission=admission,
                    intent=intent,
                    contract=contract,
                )

            def retain_supervision(fence, state):
                store.record_scene_supervision(fence, state, protect=protect_all)
                if store.get_scene_supervision(fence.run_id, fence.intent_id) != state:
                    raise ValueError("Supervision acknowledgement readback differs")

            def worker(*, ownership_artifacts):
                common = dict(
                    settings=settings,
                    artifacts=artifacts,
                    artifact_root=config.value["artifact_root"],
                    ownership_artifacts=ownership_artifacts,
                    validate_document=catalogue.validate_document,
                )
                return OwnedSceneStageAdapter(
                    native_worker=ForegroundNativeCaptureWorker(
                        **common, supervision_context=supervision_context, retain_supervision=retain_supervision
                    ),
                    numeric_worker=ForegroundNumericAssessmentWorker(**common),
                    model_worker=ForegroundSceneWorker(ownership_artifacts=ownership_artifacts),
                    gpu_lease=NativeGpuLease(selected.gpu_lease_path),
                    authorize_native=native_authorization,
                )

            def prior_factory(*, principal, run_id, contract):
                if contract.source.kind != "new" or contract.retrieval is not None:
                    raise ValueError("Only an explicit not-requested generation prior is supported")
                return RetainedPriorArtifacts(area).write(
                    contract.source.prompt,
                    contract_digest(contract),
                    run_id,
                    empty_snapshot(contract.source.prompt, status="not_requested", warning=None),
                    protect=protect_all,
                )

            app = ForegroundWorkflow(
                store=store,
                authority=authority,
                gate=ScopedHostBootstrap(ObservationOnlyPort(approved, probe), allow_startup=False),
                private_parent=config.value["private_root"],
                artifacts=GenerationArtifacts(area),
                artifact_root=config.value["artifact_root"],
                catalogue_sha256=catalogue.sha256,
                generation_reservation=GenerationReservation(**models["generation"]),
                prior_factory=prior_factory,
                initial_worker_factory=lambda **kw: InitialGenerationWorker(
                    **kw, require_prior=False, execution_catalogue=catalogue
                ),
                scene_worker_factory=worker,
                validate_document=catalogue.validate_document,
                scene_options=options,
                owner_lease_factory=ForegroundOwnerLease,
                initial_receiver_factory=InitialGenerationReceiver,
                scene_ports_factory=lambda **kw: ForegroundSplitScenePorts(**kw, execution_catalogue=catalogue),
                recovery_factory=ForegroundGenerationRecovery,
                ownership_artifacts_factory=OwnershipArtifacts,
                cancellation=foreground_cancellation,
                native_support=support,
            )

            def authorize_control(kind, principal, run_id):
                if kind not in ("cancel", "numeric_reassessment"):
                    raise PermissionError("Workload continuation requires separately issued authority")
                principal_lookup(principal)

            owner = ExecutionOwner(
                app,
                area,
                tokens,
                protect_all,
                execution_context=catalogue.activate,
                authorize_control=authorize_control,
            )
            owner.installed_inspection = lambda contract: inspect(config, contract)
            owner.installed_mode = MODE
            owner.numeric_reassessment_enabled = True
            return owner
        except BaseException:
            if authority is not None:
                authority.close()
            area.close()
            raise

    return build
