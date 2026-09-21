# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Trusted isolated composition and patchable legacy application entry point."""

import time

from isaaclab_arena.agentic_environment_generation.workflow.application import (
    ForegroundWorkflow as CoreForegroundWorkflow,
)

from . import foreground_cancellation
from .foreground_initial_generation import InitialGenerationReceiver
from .foreground_owner import ForegroundOwnerLease
from .foreground_recovery import ForegroundGenerationRecovery, OwnershipArtifacts
from .foreground_scene_ports import ForegroundScenePorts


def application_from_cli(config, credentials, *, allow_startup=False):
    """Bind the fixed isolated synthetic profile; never infer native permission.

    Available only inside the reviewed workflow-scene harness with its active
    kernel/network/process guards and pinned numeric Bolt endpoint. No plugins,
    environment credentials, live provider traffic, schema creation or startup.
    The artifact area (store/registry identities) and scope must already exist.
    Outside that admitted environment this raises NotImplementedError, including
    when --allow-startup is requested: no installed scoped helper exists yet.
    """
    import json
    from pathlib import Path
    from urllib.parse import urlsplit

    from .foreground_workflow_cli import _config

    config = _config(json.dumps(config).encode())
    if credentials or allow_startup:
        raise NotImplementedError("Isolated profile accepts no credentials or startup")
    try:
        import workflow_process_harness as harness
    except ImportError:
        raise NotImplementedError("Reviewed isolated composition unavailable") from None
    if (
        harness.ACTIVE is None
        or not harness.ACTIVE.scene
        or config["database"]["uri"] != "bolt://" + harness.ACTIVE.db_ip + ":7687"
        or urlsplit(config["database"]["uri"]).port != 7687
    ):
        raise NotImplementedError("Reviewed isolated composition unavailable")

    from neo4j import GraphDatabase

    from isaaclab_arena.agentic_environment_generation.inference_profiles import (
        frozen_builtin_profile,
        resolve_inference_profile,
    )
    from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
    from isaaclab_arena.agentic_environment_generation.workbench.document_yaml import parse_yaml, reject_unknown_fields
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import GenerationArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import GenerationReservation
    from isaaclab_arena.agentic_environment_generation.workflow.bootstrap import (
        ObservationOnlyPort,
        ScopedHostBootstrap,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyRequirement, DependencyResult
    from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import SceneEvidenceArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import ScenePortProfile
    from isaaclab_arena.agentic_environment_generation.workflow.scene_ports import ModelCeiling
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    from .foreground_authorization import ForegroundAuthority, model_settings_sha256
    from .foreground_initial_generation import InitialGenerationWorker
    from .foreground_scene import ForegroundSceneWorker
    from .web_api.catalogues import execution_catalogue_sha256
    from .web_api.execution_grants import ExecutionGrants

    model, endpoint = "gpt-6-astra", "https://api.openai.com/v1"
    model_config = dict(
        api_key="synthetic-unit-key",
        model=model,
        base_url=endpoint,
        inference_profile=frozen_builtin_profile(resolve_inference_profile(model, endpoint)),
        workflow_accounting=dict(
            version=1,
            attested=True,
            model=model,
            endpoint=endpoint,
            max_tokens=10000,
            max_cost_usd="0",
        ),
    )
    profiles = {
        r: dict(
            profile_id=r,
            billing="free",
            settings_sha256=model_settings_sha256(model_config, billing="free"),
        )
        for r in ("generation", "assessment")
    }
    driver = GraphDatabase.driver(
        config["database"]["uri"],
        auth=None,
        connection_timeout=2,
        connection_acquisition_timeout=3,
        max_transaction_retry_time=0,
    )
    area = None
    try:
        # Opening retained artifacts is observation, not lazy state initialization.
        area = ArtifactArea.open(config["artifact_root"], store_id="store", registry_id="registry")
        store = Neo4jWorkflowStore(
            driver,
            database=config["database"]["database"],
            deployment_id=config["deployment_id"],
            workspace_id=config["workspace_id"],
        )
        scope = dict(database=store.database, **store.scope)
        expires = time.time() + 240
        authority = ForegroundAuthority(
            **scope,
            store=store,
            grants=ExecutionGrants(clock=time.time),
            clock=time.time,
            principal_lookup=lambda p: dict(principal=p, **scope, expires_at=expires, revoked=False),
            profiles=profiles,
            current_config=lambda p: dict(config=model_config, expires_at=expires),
        )

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

        def prior_factory(*, principal, run_id, contract):
            snapshot = empty_snapshot(contract.source.prompt, status="unavailable", warning="unconfigured")
            return RetainedPriorArtifacts(area).write(
                contract.source.prompt,
                contract_digest(contract),
                run_id,
                snapshot,
                protect=authority.protect_public,
            )

        def validate_document(text):
            value = parse_yaml(text)
            reject_unknown_fields(value)
            return dict(
                valid=True,
                spec=ArenaEnvGraphSpec.from_dict(value).model_dump(mode="json"),
            )

        common = dict(
            model_calls=2,
            model_tokens=20000,
            cost_ceiling_usd=0.0,
            runtime_allowance_seconds=30.0,
        )
        ceiling = ModelCeiling(
            max_calls=2,
            max_tokens=20000,
            max_cost_usd="0",
            timeout_seconds=25.0,
            per_call_bound=model_config["workflow_accounting"],
        )
        profile = ScenePortProfile(
            port_id="synthetic-retained",
            assurance="synthetic",
            owned_worker=True,
            producer_ids=("scene.linear-speed", "scene.visible"),
            observe=dict(common, observations=1, realizations=1, steps=2),
            repair=dict(common, candidates=1, revisions=1),
        )
        approved = tuple(
            DependencyRequirement(
                role,
                profiles[role.removesuffix("_model")]["settings_sha256"] if role.endswith("_model") else "a" * 64,
                profile_id=role.removesuffix("_model") if role.endswith("_model") else "offline",
            )
            for role in ("runtime", "neo4j", "generation_model", "assessment_model", "capture", "gpu")
        )
        app = ForegroundWorkflow(
            store=store,
            authority=authority,
            gate=ScopedHostBootstrap(ObservationOnlyPort(approved, probe), allow_startup=False),
            owner_control=harness.ACTIVE.control,
            private_parent=config["lease_root"],
            artifacts=GenerationArtifacts(area),
            artifact_root=config["artifact_root"],
            catalogue_sha256=execution_catalogue_sha256(),
            generation_reservation=GenerationReservation(**common),
            prior_factory=prior_factory,
            initial_worker_factory=lambda **kw: InitialGenerationWorker(
                **kw, require_prior=False, spawn_spec=harness.scene_spawn_spec
            ),
            scene_worker_factory=lambda **kw: ForegroundSceneWorker(**kw, spawn_spec=harness.scene_spawn_spec),
            validate_document=validate_document,
            scene_options=dict(
                profile=profile,
                artifacts=SceneEvidenceArtifacts(area),
                capture=_synthetic_capture,
                model_ceilings={r: ceiling for r in profiles},
                capture_steps=2,
                capture_timeout_seconds=5.0,
                output_root=Path(config["lease_root"]) / "capture",
                direct_root_subjects=("mug_ycb_robolab",),
                displacement_tolerance_m=0.001,
            ),
        )
        app._owned_resources = (area, driver)
        return app
    except Exception:
        if area is not None:
            area.close()
        driver.close()
        raise


def _synthetic_capture(*, candidate, contract, cohort):
    """Fixed synthetic state/RGB only; no Isaac import or physical-validity claim."""
    import json
    from contextlib import contextmanager

    from isaaclab_arena.agentic_environment_generation.workflow.scene_ports import CaptureRuntime

    class Flag:
        def any(self):
            return False

    class Env:
        def reset(self):
            return {"camera_obs": {"wrist": b"synthetic-image"}}, {}

        def step(self, action):
            return self.reset()[0], 0, Flag(), Flag(), {}

    class Policy:
        def reset(self):
            pass

        def get_action(self, *args):
            return 0

    position = json.loads(candidate.scene_json)["relations"][5]["params"]

    def sample(env, step):
        return dict(
            step=step,
            frame="world",
            origin_w=[10.0, 0.0, 0.0],
            subjects={
                "mug_ycb_robolab": dict(
                    position_w=[10 + position["x"], position["y"], position["z"]],
                    linear_velocity_w=[0.0, 0.0, 0.0],
                    angular_velocity_w=[0.0, 0.0, 0.0],
                )
            },
        )

    @contextmanager
    def capture():
        yield CaptureRuntime(Env(), Policy(), sample, lambda image, path: path.write_bytes(image))

    return capture()


class ForegroundWorkflow(CoreForegroundWorkflow):
    """Bind existing runtime adapters while inheriting shared orchestration.

    Runtime factories are captured when constructed; rebinding legacy helper
    globals afterward does not change an existing application. Class-method
    patching remains supported for the existing isolated CLI harness.
    """

    def __init__(
        self,
        *,
        store,
        authority,
        gate,
        private_parent,
        artifacts,
        artifact_root,
        catalogue_sha256,
        generation_reservation,
        prior_factory,
        initial_worker_factory,
        scene_worker_factory,
        validate_document,
        scene_options,
        owner_control=False,
    ):
        super().__init__(
            store=store,
            authority=authority,
            gate=gate,
            private_parent=private_parent,
            artifacts=artifacts,
            artifact_root=artifact_root,
            catalogue_sha256=catalogue_sha256,
            generation_reservation=generation_reservation,
            prior_factory=prior_factory,
            initial_worker_factory=initial_worker_factory,
            scene_worker_factory=scene_worker_factory,
            validate_document=validate_document,
            scene_options=scene_options,
            owner_control=owner_control,
            owner_lease_factory=ForegroundOwnerLease,
            initial_receiver_factory=InitialGenerationReceiver,
            scene_ports_factory=ForegroundScenePorts,
            recovery_factory=ForegroundGenerationRecovery,
            ownership_artifacts_factory=OwnershipArtifacts,
            cancellation=foreground_cancellation,
        )
