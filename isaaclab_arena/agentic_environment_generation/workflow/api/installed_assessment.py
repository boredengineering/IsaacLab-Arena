# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit retained-image assessment composition, with a non-sending request preview."""

import base64
import hashlib
import json
import time
from threading import Lock

from ..contracts import Amount, FrozenModel, Hash, Identifier, ProfileReference, contract_digest
from ..scene_evidence_artifacts import canonical

MODE = "retained-visual-assessment-v1"
CAPABILITIES = {"mode": MODE, "submit": True, "cancel": True, "resume": False, "required_policy": False}


class AssessmentSelection(FrozenModel):
    """Frozen operator selection; configuration alone cannot release a provider send."""

    operation_id: Identifier
    contract_sha256: Hash
    scene_namespace: Identifier
    database_profile: ProfileReference
    approval_expires_at: Amount
    request_sha256: Hash | None


def protect(value):
    """Bound public JSON; the installed resources separately screen private values."""
    canonical(value)


def selection(config):
    assert config.value["schema_version"] == 5 and config.value["mode"] == MODE, "Explicit assessment mode required"
    selected = AssessmentSelection.model_validate_json(json.dumps(config.value["retained_assessment"]))
    if len(config.profiles) != 1:
        raise ValueError("Exactly one registered assessment profile required")
    profile = config.profiles[0]
    settings = profile.registration.settings
    if (
        profile.registration.roles != ("assessment_model",)
        or settings.billing != "paid"
        or settings.model != "gpt-6-astra"
        or settings.endpoint != "https://api.openai.com/v1"
        or settings.request_bounds is None
        or settings.request_bounds.version != 2
        or settings.workflow_accounting is None
        or settings.workflow_accounting.version != 2
    ):
        raise ValueError("Explicit accounting-only gpt-6-astra assessment profile required")
    return selected, profile


def check_contract(config, contract):
    selected, profile = selection(config)
    if (
        contract.schema_version != "4"
        or contract.source.kind != "existing"
        or contract_digest(contract) != selected.contract_sha256
        or json.loads(contract.source.content).get("env_name") != selected.scene_namespace
        or selected.scene_namespace != config.binding.workspace_id
        or contract.execution.database != selected.database_profile
        or contract.execution.assessment_model.profile_id != profile.profile_id
        or contract.execution.assessment_model.settings_sha256 != profile.settings_sha256
        or time.time() >= selected.approval_expires_at
    ):
        raise PermissionError("Retained assessment differs from the approved selection")
    return selected, profile


def recover_cancellation(config, run_id, selected_instance):
    """Recover one exact dead instance without execution grants or provider construction."""
    from .private_files import Directory

    with (
        Directory(config.value["private_root"]) as root,
        root.lease("metadata.lock"),
        root.lease("lifetime.lock"),
    ):
        return _recover_cancellation(config, run_id, selected_instance, verify_only=False)


def verify_recovery(config, selected_instance):
    """Recheck retained proof while the launcher holds metadata and lifetime leases."""
    from .instance import instance_path
    from .private_files import Directory, decode

    with Directory(instance_path(config, selected_instance)) as directory:
        retained = decode(directory.read("recovery.json", 32768), 32768)
    return _recover_cancellation(config, retained["run_id"], selected_instance, verify_only=True)


def _recover_cancellation(config, run_id, selected_instance, *, verify_only):
    """Require original configuration, physical witnesses and exact durable retirement."""
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena_examples.agentic_environment_generation.foreground_recovery import (
        ForegroundAssessmentRecovery,
        OwnershipArtifacts,
    )

    from ..artifacts import GenerationArtifacts
    from ..contracts import parse_contract
    from ..service import WorkflowService
    from .installed_composition import Resources
    from .installed_config import MAX_CONFIG
    from .instance import instance_id, instance_path, same_process, state
    from .private_files import Directory, decode, encode

    selected, _ = selection(config)
    instance_id(selected_instance)
    resources = Resources(config)
    resources.authority.require_admin(config.value["bootstrap_principal"])
    with Directory(config.value["private_root"]) as root:
        if decode(root.read("current.json", 4096), 4096) != dict(
            schema_version=1, instance=selected_instance, config_sha256=config.digest
        ):
            raise ValueError("Exact previous instance configuration required")
    known = state(config, selected_instance)
    if known["state"] != "exited_unclean" or known["identity"] is None or same_process(known["identity"]):
        raise ValueError("Reconcile the exact dead instance before assessment recovery")
    with Directory(instance_path(config, selected_instance)) as directory:
        if decode(directory.read("configuration.json", MAX_CONFIG), MAX_CONFIG) != config.value:
            raise ValueError("Retained previous configuration differs")
        with (
            resources.driver() as driver,
            ArtifactArea.open(
                config.value["artifact_root"], store_id=config.binding.store_id, registry_id=config.binding.registry_id
            ) as area,
        ):
            store = resources.store(driver)
            store.verify_schema()
            run = store.get_run(run_id)
            if (
                run is None
                or run.operation_id != selected.operation_id
                or contract_digest(parse_contract(run.contract_json)) != selected.contract_sha256
            ):
                raise ValueError("Run is outside the retained assessment selection")
            service = WorkflowService(
                store, resources.authority, None, validate_support=None, read_scope=config.binding
            )
            recovery = ForegroundAssessmentRecovery(
                config.value["private_root"],
                run_id=run_id,
                principal=config.value["read_principal"],
                service=service,
                ownership_artifacts=OwnershipArtifacts(area),
                artifacts=GenerationArtifacts(area),
                protect=resources.protect,
            )
            try:
                result = recovery.recover(previous_identity=known["identity"], verify_only=verify_only)
            finally:
                if not recovery.lease._released and recovery.lease._prepared is None:
                    recovery.lease.release_never_prepared()
        result.update(
            schema_version=1,
            code="assessment_cancellation_recovered",
            instance=selected_instance,
            config_sha256=config.digest,
            binding_sha256=config.binding.body_sha256,
            identity=known["identity"],
        )
        resources.protect(result)
        try:
            retained = decode(directory.read("recovery.json", 32768), 32768)
        except FileNotFoundError:
            if verify_only:
                raise ValueError("Retained assessment recovery evidence required") from None
            directory.write("recovery.json", encode(result))
        else:
            if retained != result:
                raise ValueError("Retained assessment recovery differs")
        return result


def _checked_preview_body(serialized, request, config):
    body = json.loads(serialized)
    limits = config["request_bounds"]["envelope"]
    messages = body.get("messages")
    if (
        body.get("model") != config["model"]
        or body.get(limits["output_parameter"]) != limits["max_output_tokens"]
        or body.get("store") is not False
        or type(messages) is not list
        or len(messages) != 1
        or messages[0].get("role") != "user"
    ):
        raise ValueError("Serialized assessment model, completion or message differs")
    content = messages[0].get("content")
    if (
        type(content) is not list
        or len(content) != len(request["frames"]) + 1
        or content[0].get("type") != "text"
        or not content[0].get("text", "").endswith("Request:\n" + canonical(request).decode())
    ):
        raise ValueError("Serialized request lacks the frozen visibility rubric and frames")
    for part, frame in zip(content[1:], request["frames"]):
        url = part.get("image_url", {}).get("url", "")
        prefix = "data:image/png;base64,"
        if part.get("type") != "image_url" or not url.startswith(prefix):
            raise ValueError("Serialized retained PNG required")
        raw = base64.b64decode(url[len(prefix) :], validate=True)
        if hashlib.sha256(raw).hexdigest() != frame["sha256"]:
            raise ValueError("Serialized image bytes or order differ")
    return dict(
        image_count=len(request["frames"]),
        camera_order=[frame["camera"] for frame in request["frames"]],
        image_sha256=[frame["sha256"] for frame in request["frames"]],
        subjects_by_frame=[frame["subjects"] for frame in request["frames"]],
        completion_allowance=body[limits["output_parameter"]],
        constructor_probe=False,
    )


def preview(config, contract):
    """Run the actual input/model/SDK serialization path with a mandatory send denial."""
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea

    from ..inference_transport import CallAllowance
    from ..readiness import required_dependencies
    from ..retained_assessment import load_retained_source
    from ..scene_engines import BoundedSceneModels
    from ..scene_evidence_artifacts import SceneEvidenceArtifacts, _protected
    from .installed_composition import Resources

    selected, profile = check_contract(config, contract)
    resources = Resources(config)
    roles = resources.private_roles()
    config_value = roles.model_config("assessment")
    allowance = CallAllowance(
        max_calls=1, deadline=time.monotonic() + 30, per_call_bound=config_value["workflow_accounting"]
    )
    denied = []

    def deny(request):
        denied.append(hashlib.sha256(request.content).hexdigest())
        raise ValueError("Provider sends denied during installed preview")

    with (
        resources.driver() as driver,
        ArtifactArea.open(
            config.value["artifact_root"], store_id=config.binding.store_id, registry_id=config.binding.registry_id
        ) as area,
    ):
        store = resources.store(driver)
        dependencies = required_dependencies(contract, resolved_instances=store.dependency_instances)
        expected = {
            "assessment_model": (profile.profile_id, profile.settings_sha256),
            "neo4j": (selected.database_profile.profile_id, selected.database_profile.settings_sha256),
        }
        if {item.dependency_id: (item.profile_id, item.profile_sha256) for item in dependencies} != expected:
            raise ValueError("Retained assessment admission requires only the frozen model and store")
        artifacts = SceneEvidenceArtifacts(area)
        evidence_id, _, receipt, request, raw = load_retained_source(
            store, artifacts, contract, protect=resources.protect
        )
        tools = BoundedSceneModels(
            config=config_value,
            allowance=allowance,
            approved_roles={"assessment": {"model": config_value["model"], "endpoint": config_value["base_url"]}},
            send_guard=deny,
        )
        try:
            tools.assess(
                criterion=contract.criteria[0],
                candidate=receipt.candidate,
                cohort=receipt.cohort,
                artifacts=artifacts,
                observation=receipt,
                protect=resources.protect,
            )
        except Exception:
            if len(denied) != 1:
                raise ValueError("Production request did not reach the mandatory send denial") from None
        else:
            raise ValueError("Mandatory send denial was not enforced")
        records = allowance.provider_records
        if len(records) != 1 or records[0]["dispatched"] or records[0]["response"] is not None:
            raise ValueError("Non-sending preview was not established")
        content_verification = _checked_preview_body(records[0]["serialized_request"], request, config_value)
        return json.loads(
            _protected(
                dict(
                    code="retained_assessment_request_prepared",
                    operation_id=selected.operation_id,
                    consumer_contract_digest=contract_digest(contract),
                    producer=contract.retained_evidence.model_dump(mode="json"),
                    producer_evidence_id=evidence_id,
                    source_candidate_utf8=contract.source.content,
                    source_evidence_utf8=raw.decode(),
                    request=request,
                    serialized_request=records[0]["serialized_request"],
                    request_sha256=denied[0],
                    content_verification=content_verification,
                    planned_dependencies=[
                        dict(role=item.dependency_id, profile_id=item.profile_id, settings_sha256=item.profile_sha256)
                        for item in dependencies
                    ],
                    profile=profile.model_dump(mode="json"),
                    provider_sends=0,
                    denial_boundary="checked_sdk_http_request_hook",
                    durable_allocation_changed=False,
                ),
                resources.protect,
            )
        )


def compose(config, *, tokens, auth, assessment_authorized=False, private_roles):
    """Use the existing execution owner and coordinator for sequential counted assessment."""
    selected, registered = selection(config)
    if assessment_authorized is not True or selected.request_sha256 is None:
        raise PermissionError("Separate assessment approval and frozen request are required")

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena_examples.agentic_environment_generation import foreground_cancellation
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import ForegroundAuthority
    from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease
    from isaaclab_arena_examples.agentic_environment_generation.foreground_recovery import (
        ForegroundAssessmentRecovery,
        OwnershipArtifacts,
    )
    from isaaclab_arena_examples.agentic_environment_generation.foreground_scene import ForegroundSceneWorker
    from isaaclab_arena_examples.agentic_environment_generation.foreground_scene_ports import ForegroundScenePorts
    from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants

    from ..application import ForegroundWorkflow
    from ..artifacts import GenerationArtifacts
    from ..bootstrap import ObservationOnlyPort, ScopedHostBootstrap
    from ..readiness import DependencyRequirement, DependencyResult
    from ..retained_assessment import RetainedAssessmentPorts
    from ..scene_evidence_artifacts import SceneEvidenceArtifacts
    from ..scene_loop import ScenePortProfile, SceneReservation
    from ..scene_ports import ModelCeiling
    from .execution_owner import ExecutionOwner

    class OwnedAssessmentPorts(ForegroundScenePorts, RetainedAssessmentPorts):
        """Existing owned model lifecycle with the retained-only producer consumer."""

        def prepare_worker(self, intent, candidate, original, contract, **stage_args):
            self.wait_retained_retry(self.run_id, contract)
            return super().prepare_worker(intent, candidate, original, contract, **stage_args)

    lock, built = Lock(), False

    def unavailable(*args, **kwargs):
        raise PermissionError("Native, generation, repair, policy and prior retrieval are disabled")

    def build(store, verified, protect):
        nonlocal built
        with lock:
            if built:
                raise ValueError("Assessment composition already consumed")
            built = True
        if verified.binding != config.binding or verified.profiles != config.profiles:
            raise ValueError("Verified retained assessment resources differ")
        roles = private_roles()
        roles.check_current()
        model_config = roles.model_config("assessment")
        area = ArtifactArea.open(
            config.value["artifact_root"], store_id=config.binding.store_id, registry_id=config.binding.registry_id
        )
        authority = None
        try:
            scope = dict(database=store.database, **store.scope)
            model_profile = dict(
                profile_id=registered.profile_id, settings_sha256=registered.settings_sha256, billing="paid"
            )

            def principal_lookup(principal):
                tokens.recheck(auth)
                if principal != auth.principal:
                    raise PermissionError("Exact assessment operator required")
                return dict(principal=principal, **scope, expires_at=auth.expires_at, revoked=False)

            def admission(principal, operation_id, contract):
                principal_lookup(principal)
                roles.check_current()
                check_contract(config, contract)
                if operation_id != selected.operation_id:
                    raise PermissionError("Assessment operation identity changed")
                expires_at = min(auth.expires_at, selected.approval_expires_at)
                if time.time() + contract.budget.total_deadline_seconds >= expires_at:
                    raise PermissionError("Full assessment execution and cleanup authority required at admission")
                return True

            def current_config(profile_id):
                if profile_id != registered.profile_id:
                    raise ValueError("Only the assessment model is configured")
                return dict(
                    config=roles.model_config("assessment"),
                    expires_at=min(auth.expires_at, selected.approval_expires_at),
                )

            authority = ForegroundAuthority(
                **scope,
                store=store,
                grants=ExecutionGrants(clock=time.time),
                clock=time.time,
                principal_lookup=principal_lookup,
                profiles={registered.profile_id: model_profile},
                current_config=current_config,
                source_guard=roles.release_guard,
                assessment_admission=admission,
            )
            grant_protect = authority.protect_public

            def protect_all(value):
                protect(value)
                roles.protect(value)
                grant_protect(value)

            authority.protect_public = protect_all
            references = dict(assessment_model=model_profile, neo4j=selected.database_profile.model_dump(mode="json"))
            approved = tuple(
                DependencyRequirement(role, ref["settings_sha256"], profile_id=ref["profile_id"])
                for role, ref in references.items()
            )

            def probe(required, timeout):
                roles.check_current()
                ref = references.get(required.dependency_id)
                passed = ref is not None and (required.profile_id, required.profile_sha256) == (
                    ref["profile_id"],
                    ref["settings_sha256"],
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

            profile = ScenePortProfile(
                codec_version=2,
                port_id=MODE,
                assurance="retained-evidence",
                owned_worker=True,
                producer_ids=("scene.visible",),
                assess=SceneReservation(
                    model_calls=1,
                    model_tokens=None,
                    cost_ceiling_usd=None,
                    accounting_policy="accounting-only-v1",
                    runtime_allowance_seconds=190.0,
                ),
                repair=SceneReservation(
                    model_calls=0, model_tokens=0, cost_ceiling_usd=0.0, runtime_allowance_seconds=0.0
                ),
            )
            options = dict(
                profile=profile,
                artifacts=SceneEvidenceArtifacts(area),
                source_store=store,
                expected_request_sha256=selected.request_sha256,
                capture=unavailable,
                model_ceilings={"assessment": ModelCeiling(1, None, None, 180.0, model_config["workflow_accounting"])},
                capture_steps=0,
                capture_timeout_seconds=0,
                output_root=config.value["artifact_root"],
                direct_root_subjects=(),
                displacement_tolerance_m=0,
            )
            support = RetainedAssessmentPorts(
                **options,
                protect=protect_all,
                authorize=None,
                ready=None,
                refine=None,
                visual=None,
                check_active=lambda: None,
            )
            app = ForegroundWorkflow(
                store=store,
                authority=authority,
                gate=ScopedHostBootstrap(ObservationOnlyPort(approved, probe), allow_startup=False),
                private_parent=config.value["private_root"],
                artifacts=GenerationArtifacts(area),
                artifact_root=config.value["artifact_root"],
                catalogue_sha256=selected.contract_sha256,
                generation_reservation=None,
                prior_factory=unavailable,
                initial_worker_factory=unavailable,
                scene_worker_factory=ForegroundSceneWorker,
                validate_document=unavailable,
                scene_options=options,
                owner_lease_factory=ForegroundOwnerLease,
                initial_receiver_factory=unavailable,
                scene_ports_factory=OwnedAssessmentPorts,
                recovery_factory=ForegroundAssessmentRecovery,
                ownership_artifacts_factory=OwnershipArtifacts,
                cancellation=foreground_cancellation,
                retained_support=support,
            )

            def authorize_control(kind, principal, run_id):
                if kind != "cancel":
                    raise PermissionError("Completed or interrupted assessment permits readback, not redispatch")
                principal_lookup(principal)

            return ExecutionOwner(app, area, tokens, protect_all, authorize_control=authorize_control)
        except BaseException:
            if authority is not None:
                authority.close()
            area.close()
            raise

    return build
