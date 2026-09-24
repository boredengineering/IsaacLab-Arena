# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Fixed guarded synthetic composition; config selection is not execution authority."""

import sys
import time
from decimal import Decimal
from pathlib import Path
from threading import Lock

MODE = "isolated-synthetic-execution-v1"
CAPABILITIES = {"mode": MODE, "submit": True, "cancel": True, "resume": True, "required_policy": False}


def protect(value):
    """Screen the fixed synthetic sentinel only in the explicit composition."""
    from ..provider_configuration import reject_secret

    reject_secret(value, "synthetic-unit-key")


def compose(config, *, tokens, auth):
    """Authorize fixed ports before resources; return one lifespan-only builder."""
    if (config.value["schema_version"], config.value["mode"]) not in ((2, MODE), (3, MODE)):
        raise ValueError("Explicit synthetic mode required")
    # Never import a discoverable plugin. Only the already executing reviewed
    # bootstrap may issue this one-use capability to this exact compose frame.
    harness = sys.modules.get("workflow_graphql_execution_join_harness")
    if harness is None:
        raise NotImplementedError("Guarded synthetic execution unavailable")
    ports = harness.synthetic_ports()
    if set(ports) != {"spawn_spec", "capture", "catalogue"} or not all(callable(p) for p in ports.values()):
        raise ValueError("Fixed synthetic ports required")
    from isaaclab_arena.environment_spec.execution_catalogue import ExecutionCatalogue

    catalogue = ports["catalogue"]()
    if not isinstance(catalogue, ExecutionCatalogue):
        raise ValueError("Explicit adapter vocabulary required")

    from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import GenerationArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import GenerationReservation
    from isaaclab_arena.agentic_environment_generation.workflow.bootstrap import (
        ObservationOnlyPort,
        ScopedHostBootstrap,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyRequirement, DependencyResult
    from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import SceneEvidenceArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import ScenePortProfile
    from isaaclab_arena.agentic_environment_generation.workflow.scene_ports import ModelCeiling
    from isaaclab_arena_examples.agentic_environment_generation import foreground_cancellation
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import (
        ForegroundAuthority,
        model_settings_sha256,
    )
    from isaaclab_arena_examples.agentic_environment_generation.foreground_initial_generation import (
        InitialGenerationReceiver,
        InitialGenerationWorker,
    )
    from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease
    from isaaclab_arena_examples.agentic_environment_generation.foreground_recovery import (
        ForegroundGenerationRecovery,
        OwnershipArtifacts,
    )
    from isaaclab_arena_examples.agentic_environment_generation.foreground_scene import ForegroundSceneWorker
    from isaaclab_arena_examples.agentic_environment_generation.foreground_scene_ports import ForegroundScenePorts
    from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants

    from ..application import ForegroundWorkflow
    from .execution_owner import ExecutionOwner

    expected = tuple(config.profiles)
    if {p.profile_id for p in expected} != {"generation", "assessment"} or len(expected) != 2:
        raise ValueError("Exact synthetic role selections required")
    model_configs, profiles = {}, {}
    for selected in expected:
        settings = selected.registration.settings
        if (
            selected.registration.roles != (selected.profile_id + "_model",)
            or settings.model != "gpt-6-astra"
            or settings.endpoint != "https://api.openai.com/v1"
            or settings.request_bounds is None
            or settings.workflow_accounting is None
            or settings.inference_policy is None
            or settings.request_bounds.pricing.kind != "synthetic_fixture"
            or (settings.billing == "free" and Decimal(settings.workflow_accounting.max_cost_usd) != 0)
        ):
            raise ValueError("Explicit supported synthetic request/pricing selections required")
        model_configs[selected.profile_id] = dict(
            api_key="synthetic-unit-key",
            model=settings.model,
            base_url=settings.endpoint,
            inference_profile=settings.inference_policy.model_dump(mode="json"),
            workflow_accounting=settings.workflow_accounting.model_dump(mode="json"),
            request_bounds=settings.request_bounds.model_dump(mode="json"),
        )
        profiles[selected.profile_id] = dict(
            profile_id=selected.profile_id, billing=settings.billing, settings_sha256=selected.settings_sha256
        )
    # Registry and execution use independently checked codecs. Never substitute
    # an unrelated registry body hash or suppress the authority's settings check.
    if any(
        p.settings_sha256 != model_settings_sha256(model_configs[p.profile_id], billing=p.registration.settings.billing)
        for p in expected
    ):
        raise ValueError("Synthetic registry/execution settings differ")

    private_roles = None
    if config.value["schema_version"] == 3:
        from .installed_composition import PrivateRoles

        private_roles = PrivateRoles(config)
        for role in ("generation", "assessment", "repair"):
            selected = private_roles.model_config(role)
            profile = profiles["generation" if role == "repair" else role]
            if (
                model_settings_sha256(selected, billing=profile["billing"])
                != profile["settings_sha256"]
            ):
                raise ValueError("Exact synthetic role settings required")
        if private_roles.model_config("repair") != private_roles.model_config("generation"):
            raise ValueError("Explicit shared repair source required")

    build_lock = Lock()
    built = False

    def build(store, verified, protect):
        nonlocal built
        with build_lock:
            if built:
                raise ValueError("Synthetic composition already consumed")
            built = True
        if verified.binding != config.binding or verified.profiles != expected:
            raise ValueError("Verified synthetic resources differ")
        area = ArtifactArea.open(
            config.value["artifact_root"], store_id=config.binding.store_id, registry_id=config.binding.registry_id
        )
        authority = None
        try:
            scope = dict(database=store.database, **store.scope)
            expires = auth.expires_at

            def principal_lookup(principal):
                tokens.recheck(auth)
                if principal != auth.principal:
                    raise PermissionError("Exact instance operator required")
                return dict(principal=principal, **scope, expires_at=expires, revoked=False)

            authority = ForegroundAuthority(
                **scope,
                store=store,
                grants=ExecutionGrants(clock=time.time),
                clock=time.time,
                principal_lookup=principal_lookup,
                profiles=profiles,
                current_config=lambda p: dict(
                    config=model_configs[p] if private_roles is None else private_roles.model_config(p), expires_at=expires
                ),
                source_guard=None if private_roles is None else private_roles.release_guard,
                prior_source=None if private_roles is None else private_roles.prior_source,
            )

            grant_protect = authority.protect_public

            def protect_all(value):
                protect(value)
                grant_protect(value)
                if private_roles is not None:
                    private_roles.protect(value)

            authority.protect_public = protect_all

            def probe(required, timeout):
                expected = (
                    profiles.get(required.dependency_id.removesuffix("_model"))
                    if required.dependency_id.endswith("_model")
                    else dict(profile_id="offline", settings_sha256="a" * 64)
                )
                passed = (
                    required.dependency_id
                    in {
                        "runtime",
                        "neo4j",
                        "generation_model",
                        "assessment_model",
                        "capture",
                        "gpu",
                    }
                    and expected is not None
                    and required.profile_id == expected["profile_id"]
                    and required.profile_sha256 == expected["settings_sha256"]
                )
                if passed and required.dependency_id == "neo4j":
                    passed = store.verify_schema() is True
                    store.get_owner()  # exact existing scope, no initialization
                return DependencyResult(
                    required.dependency_id,
                    "passed" if passed else "unavailable",
                    required.profile_sha256,
                    profile_id=required.profile_id,
                    instance_id=required.instance_id,
                )

            def prior_driver(*, uri, user, password, **options):
                from neo4j import GraphDatabase, basic_auth

                return GraphDatabase.driver(uri, auth=basic_auth(user, password), **options)

            def prior_factory(*, principal, run_id, contract):
                if contract.retrieval is not None:
                    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_access import (
                        retrieve_snapshot,
                    )

                    retained = RetainedPriorArtifacts(area)
                    reference = store.get_prior_reference(run_id)
                    if reference is None:
                        deadline = store.begin_prior_retrieval(run_id)
                        with authority.prior_read(principal, contract, run_id=run_id, deadline=deadline) as (
                            source,
                            check,
                        ):
                            snapshot = retrieve_snapshot(
                                contract.source.prompt,
                                source,
                                settings=contract.retrieval.settings,
                                driver_factory=prior_driver,
                                read_guard=check,
                            )
                        receipt = retained.write(
                            contract.source.prompt,
                            contract_digest(contract),
                            run_id,
                            snapshot,
                            protect=authority.protect_public,
                        )
                        reference = retained.reference(
                            receipt,
                            contract=contract,
                            run_id=run_id,
                            protect=authority.protect_public,
                        )
                        store.retain_prior_reference(run_id, reference)
                    return retained.reopen(
                        reference, contract=contract, run_id=run_id, protect=authority.protect_public
                    )
                snapshot = empty_snapshot(contract.source.prompt, status="unavailable", warning="unconfigured")
                return RetainedPriorArtifacts(area).write(
                    contract.source.prompt,
                    contract_digest(contract),
                    run_id,
                    snapshot,
                    protect=authority.protect_public,
                )

            def validate_document(text):
                return catalogue.validate_document(text)

            reservations, ceilings = {}, {}
            for role, selected in model_configs.items():
                bound = selected["workflow_accounting"]
                cost = 2 * Decimal(bound["max_cost_usd"])
                reservations[role] = dict(
                    model_calls=2, model_tokens=2 * bound["max_tokens"],
                    cost_ceiling_usd=float(cost), runtime_allowance_seconds=30.0,
                )
                ceilings[role] = ModelCeiling(
                    max_calls=2, max_tokens=2 * bound["max_tokens"], max_cost_usd=format(cost, "f"),
                    timeout_seconds=25.0, per_call_bound=bound,
                )
            profile = ScenePortProfile(
                port_id="synthetic-retained",
                assurance="synthetic",
                owned_worker=True,
                producer_ids=("scene.linear-speed", "scene.visible"),
                observe=dict(reservations["assessment"], observations=1, realizations=1, steps=2),
                repair=dict(reservations["generation"], candidates=1, revisions=1),
            )
            approved = tuple(
                DependencyRequirement(
                    role,
                    profiles[role.removesuffix("_model")]["settings_sha256"] if role.endswith("_model") else "a" * 64,
                    profile_id=role.removesuffix("_model") if role.endswith("_model") else "offline",
                )
                for role in ("runtime", "neo4j", "generation_model", "assessment_model", "capture", "gpu")
            )
            catalogue_digest = catalogue.sha256
            app = ForegroundWorkflow(
                store=store,
                authority=authority,
                gate=ScopedHostBootstrap(ObservationOnlyPort(approved, probe), allow_startup=False),
                owner_control=False,
                private_parent=config.value["private_root"],
                artifacts=GenerationArtifacts(area),
                artifact_root=config.value["artifact_root"],
                catalogue_sha256=catalogue_digest,
                generation_reservation=GenerationReservation(**reservations["generation"]),
                prior_factory=prior_factory,
                initial_worker_factory=lambda **kw: InitialGenerationWorker(
                    **kw, require_prior=False, spawn_spec=ports["spawn_spec"]
                ),
                scene_worker_factory=lambda **kw: ForegroundSceneWorker(**kw, spawn_spec=ports["spawn_spec"]),
                validate_document=validate_document,
                owner_lease_factory=ForegroundOwnerLease,
                initial_receiver_factory=InitialGenerationReceiver,
                scene_ports_factory=ForegroundScenePorts,
                recovery_factory=ForegroundGenerationRecovery,
                ownership_artifacts_factory=OwnershipArtifacts,
                cancellation=foreground_cancellation,
                scene_options=dict(
                    profile=profile,
                    artifacts=SceneEvidenceArtifacts(area),
                    capture=ports["capture"],
                    model_ceilings=ceilings,
                    capture_steps=2,
                    capture_timeout_seconds=5.0,
                    output_root=Path(config.value["private_root"]) / "capture",
                    direct_root_subjects=("mug_ycb_robolab",),
                    displacement_tolerance_m=0.001,
                ),
            )

            def authorize_control(kind, principal, run_id):
                # Explicit control is granted only to this composition's fixed
                # operator, independently of model/execution credentials.
                if kind not in {"cancel", "resume"}:
                    raise PermissionError("Unsupported installed control")
                principal_lookup(principal)
                authority.require_read(principal)

            return ExecutionOwner(
                app,
                area,
                tokens,
                protect_all,
                execution_context=catalogue.activate,
                authorize_control=authorize_control,
            )
        except BaseException:
            if authority is not None:
                authority.close()
            area.close()
            raise

    return build
