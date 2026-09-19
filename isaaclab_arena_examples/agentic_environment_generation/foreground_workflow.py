# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Shared foreground application, not a CLI, queue or second scene controller.

Factories are trusted composition, never request data. They construct transports
and retained prior inputs only; all next-step decisions belong to WorkflowService
and Neo4j. Capture remains explicitly synthetic; native execution is not admitted.
"""

import time
from threading import RLock
from types import SimpleNamespace

from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json, parse_contract
from isaaclab_arena.agentic_environment_generation.workflow.coordinator import GenerationCoordinator
from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import StoreUnavailable, validate_operation_id
from isaaclab_arena.agentic_environment_generation.workflow.readiness import (
    ReadinessClock,
    durable_readiness,
    required_dependencies,
)
from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import canonical
from isaaclab_arena.agentic_environment_generation.workflow.scene_ports import ScenePorts
from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
from isaaclab_arena.agentic_environment_generation.workflow.validation import validate_generation_candidate

from .foreground_cancellation import (
    cancel_workflow,
    close_controls,
    finish_cancelled,
    start_owner_control,
    stop_local,
    stop_requested,
)
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


class ForegroundWorkflow:
    """Synchronous foreground run plus read/cancel/reconcile application boundary.

    initial_worker_factory(**kwargs) receives area, root, prior, protect and
    ownership_artifacts; scene_worker_factory(**kwargs) receives ownership_artifacts.
    prior_factory(principal=..., run_id=..., contract=...) returns a retained prior
    receipt. scene_options is the explicit ScenePorts configuration excluding its
    authority/ready/refine/visual/check_active/protect hooks. No decision callbacks.
    Caller owns the already-open store/driver and artifact area; close revokes this
    root's authority and stops its workers, but never closes shared storage or
    unlocks uncertain ownership.
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
        if authority.store is not store:
            raise ValueError("Exact same-store authority required")
        self.store, self.authority, self.gate = store, authority, gate
        self.private_parent, self.artifacts, self.artifact_root = (
            private_parent,
            artifacts,
            artifact_root,
        )
        self.catalogue_sha256 = catalogue_sha256
        self.generation_reservation = generation_reservation
        self.prior_factory, self.initial_worker_factory = (
            prior_factory,
            initial_worker_factory,
        )
        self.scene_worker_factory, self.validate_document = (
            scene_worker_factory,
            validate_document,
        )
        self.scene_options = dict(scene_options)
        if not self.scene_options["profile"].owned_worker or self.scene_options["profile"].assurance != "synthetic":
            raise ValueError("Only explicitly synthetic owned scene composition is supported")
        # Construct only pure admission ports: no worker, backend, SDK or ping.
        self._support = ScenePorts(
            **self.scene_options,
            protect=authority.protect_public,
            authorize=None,
            ready=None,
            refine=None,
            visual=None,
            check_active=lambda: None,
        )
        self.service = WorkflowService(store, authority, gate, validate_support=self._support.admit)
        self.ownership = OwnershipArtifacts(artifacts.area)
        self._local, self._recoveries = {}, {}
        self._owned_resources = ()
        self._lock, self._closed = RLock(), False
        self._admission_listener = None
        if type(owner_control) is not bool:
            raise TypeError("Trusted owner-control opt-in required")
        self._owner_control = owner_control
        self._cancel_controls = {}

    def set_admission_listener(self, callback):
        """Install a trusted observer; failure leaves acceptance pending, never dispatches."""
        if callback is not None and not callable(callback):
            raise TypeError("Admission listener must be callable")
        self._admission_listener = callback

    def _check(self, principal):
        if self._closed:
            raise ValueError("Foreground workflow closed")
        self.authority.require_read(principal)

    def _preflight(self, principal, contract):
        self._support.admit(contract)
        self.authority.protect_workflow_contract(principal, contract)
        bounds = self.authority.require_workflow_model_bounds(principal, contract)
        for role, bound in bounds.items():
            if canonical(self._support.model_ceilings[role].per_call_bound) != canonical(bound):
                raise ValueError("Frozen role accounting mismatch")
        for reservation in (
            self._support.profile.observe,
            self._support.profile.repair,
        ):
            self._support.require_bounded_capability(principal, contract, reservation)
        generation = self._support.model_ceilings["generation"]
        reservation = self.generation_reservation
        if (
            generation.max_calls > reservation.model_calls
            or generation.max_tokens > reservation.model_tokens
            or generation.timeout_seconds > reservation.runtime_allowance_seconds
        ):
            raise ValueError("Initial generation reservation below configured bounds")

    def _ready(self, contract):
        mapping = ReadinessClock.capture()
        requirements = required_dependencies(contract, resolved_instances=self.store.dependency_instances)
        report = self.gate.check(
            requirements,
            timeout_s=min(120, contract.budget.per_operation_timeout_seconds),
        )
        return durable_readiness(contract, requirements, report, mapping=mapping)

    def run(self, principal, operation_id, raw_contract):
        self._check(principal)
        validate_operation_id(operation_id)
        contract = parse_contract(raw_contract)
        # Replay must precede current configuration, grants, readiness and factories.
        try:
            retained = self.store.lookup_submission(operation_id, canonical_json(contract))
        except StoreUnavailable:
            return self._unknown(None)
        if retained is not None:
            return self.status(principal, retained.run_id)
        with self.authority.mutation_guard():
            self.authority.protect_workflow_contract(principal, contract, operation_id=operation_id)
            self._preflight(principal, contract)
            submitted = self.service.submit(principal, operation_id, raw_contract)
            if submitted.disposition == "dependencies_not_ready":
                return self._public(
                    dict(
                        disposition="dependencies_not_ready",
                        run_id=None,
                        blockers=list(submitted.readiness.blockers),
                        available_actions=[],
                    )
                )
            if submitted.disposition == "retained":
                return self.status(principal, submitted.run.run_id)
            run = submitted.run
            self._start_control(principal, run.run_id)
            if self._admission_listener is not None:
                handle = self._public(
                    dict(
                        schema_version=1,
                        disposition="admitted",
                        run_id=run.run_id,
                        operation_id=run.operation_id,
                        state=run.state,
                        version=run.version,
                        event_cursor=run.event_cursor,
                    )
                )
                self._admission_listener(handle)
            if stop_requested(self, run.run_id):
                return self.status(principal, run.run_id)
            self.authority.bind_run(
                principal,
                operation_id,
                contract,
                run_id=run.run_id,
                catalogue_sha256=self.catalogue_sha256,
            )
            self.authority.bind_workflow_models(principal, contract, run_id=run.run_id)
        return self._generate(principal, run, contract)

    def _generate(self, principal, run, contract, *, pending=None):
        if stop_requested(self, run.run_id):
            return self.status(principal, run.run_id)
        prior = self.prior_factory(principal=principal, run_id=run.run_id, contract=contract)
        worker = self.initial_worker_factory(
            area=self.artifacts.area,
            root=self.artifact_root,
            prior=prior,
            protect=self.authority.protect_public,
            ownership_artifacts=self.ownership,
        )
        lease = ForegroundOwnerLease(
            self.private_parent,
            run_id=run.run_id,
            principal=principal,
            cleanup_verified=worker.cleanup_verified,
        )
        coordinator = GenerationCoordinator(
            self.store,
            self.authority,
            self.gate,
            worker,
            run_id=run.run_id,
            principal=principal,
            lease=lease,
            readiness_clock=ReadinessClock.capture(),
            workflow_service=self.service,
        )
        receiver = InitialGenerationReceiver(
            worker,
            coordinator,
            lease,
            self.artifacts,
            validate_document=self.validate_document,
            protect=self.authority.protect_public,
        )
        local = SimpleNamespace(
            principal=principal,
            worker=worker,
            lease=lease,
            coordinator=coordinator,
            receiver=receiver,
            handle=None,
            ports=None,
            stopped=False,
            retired=False,
            busy=True,
        )
        with self._lock:
            local.stopped = stop_requested(self, run.run_id)
            self._local[run.run_id] = local
        completed = None
        try:
            if local.stopped or stop_requested(self, run.run_id):
                stop_local(self, principal, run.run_id)
                lease.release_never_prepared()
                local.retired = True
                return self.status(principal, run.run_id)
            if pending is not None:
                owner = self.store.get_owner()
                if owner is not None and owner.dirty:
                    # The new exclusive lease must prove the complete durable
                    # obligation set unclaimed/settled before adopting identity.
                    # Claimed or uncertain preparation remains reconciliation.
                    lease.recover_unprepared_owner(self.store, self.ownership)
            local.handle = coordinator.dispatch(
                principal,
                expected_version=run.version,
                decision_id="foreground-initial-generation",
                reservation=(
                    pending["reservation"]
                    if pending and pending["reservation"] is not None
                    else self.generation_reservation
                ),
                pending_intent=pending["intent_id"] if pending else None,
            )
            completed = receiver.receive(principal, local.handle.prepared, release_lease=True)
            local.retired = True
        except Exception as exc:
            # Receiver/coordinator retain exact cleanup and receipts. Never redispatch.
            if getattr(exc, "handle", None) is not None:
                local.handle = exc.handle
        finally:
            local.busy = False
            self._settle_cancel(principal, run.run_id, local)
        if completed is not None and completed.disposition == "validation" and not stop_requested(self, run.run_id):
            return self._scene(principal, run.run_id, contract)
        return self._blocked_status(principal, run.run_id)

    def _scene(self, principal, run_id, contract, *, continuation=False):
        try:
            return self._scene_phase(principal, run_id, contract, continuation=continuation)
        except Exception:
            with self._lock:
                local = self._local.get(run_id)
            if local is not None:
                local.busy = False
                self._settle_cancel(principal, run_id, local)
            return self._blocked_status(principal, run_id)

    def _scene_phase(self, principal, run_id, contract, *, continuation=False):
        if stop_requested(self, run_id):
            return self.status(principal, run_id)
        self._preflight(principal, contract)
        self._ready(contract)
        worker = self.scene_worker_factory(ownership_artifacts=self.ownership)
        lease = ForegroundOwnerLease(
            self.private_parent,
            run_id=run_id,
            principal=principal,
            cleanup_verified=worker.cleanup_verified,
        )
        local = SimpleNamespace(
            principal=principal,
            worker=worker,
            lease=lease,
            coordinator=None,
            receiver=None,
            handle=None,
            ports=None,
            stopped=False,
            retired=False,
            busy=True,
        )
        with self._lock:
            local.stopped = stop_requested(self, run_id)
            self._local[run_id] = local
        if local.stopped:
            lease.release_never_prepared()
            local.retired = True
            return self.status(principal, run_id)
        # New physical owner is held before start_scene reserves its first intent.
        if continuation:
            lease.recover_unprepared_owner(self.store, self.ownership)
        else:
            self.store.begin_owner(lease.owner_id)
        self.service.start_scene(
            principal,
            run_id,
            artifacts=self.artifacts,
            protect=self.authority.protect_public,
            validate_generation_candidate=validate_generation_candidate,
            profile=self.scene_options["profile"],
        )
        ports = ForegroundScenePorts(
            store=self.store,
            authority=self.authority,
            lease=lease,
            worker=worker,
            principal=principal,
            run_id=run_id,
            catalogue_sha256=self.catalogue_sha256,
            artifact_root=self.artifact_root,
            ready=self._ready,
            protect=self.authority.protect_public,
            **self.scene_options,
        )
        with self._lock:
            local.ports = ports
            local.stopped = stop_requested(self, run_id)
        if local.stopped:
            stop_local(self, principal, run_id)
        elif continuation:
            local.ports.restore_observations(self.store.result_records(run_id), contract)
        return self._drive_scene(principal, run_id, local)

    def _drive_scene(self, principal, run_id, local):
        local.busy = True
        try:
            if stop_requested(self, run_id):
                stop_local(self, principal, run_id)
            else:
                result = self.service.run_scene(principal, run_id, ports=local.ports)
                if result.run.state in ("accepted", "stopped"):
                    local.ports.retire_terminal()
                    local.retired = True
        finally:
            local.busy = False
            self._settle_cancel(principal, run_id, local)
        return self.status(principal, run_id)

    def _public(self, value):
        self.authority.protect_public(value)
        return value

    def _unknown(self, run_id):
        return self._public(
            dict(
                disposition="unknown",
                run_id=run_id,
                state="unknown",
                reason="authoritative_store_unavailable",
                available_actions=[],
                ownership="retained_if_held",
            )
        )

    def status(self, principal, run_id):
        self._check(principal)
        validate_operation_id(run_id)
        from isaaclab_arena.agentic_environment_generation.workflow.read_model import workflow_result

        try:
            return workflow_result(self.store, run_id, protect=self.authority.protect_public)
        except StoreUnavailable:
            return self._unknown(run_id)

    def _blocked_status(self, principal, run_id):
        result = self.status(principal, run_id)
        if result["disposition"] != "unknown" and result["state"] not in (
            "accepted",
            "stopped",
            "cancelled",
        ):
            result.update(disposition="blocked", reason="reconciliation_required_no_redispatch")
        return self._public(result)

    def cancel(self, principal, run_id):
        validate_operation_id(run_id)
        result = cancel_workflow(self, principal, run_id)
        if not self._owner_control:
            # Preserve the existing in-process result contract outside IPC opt-in.
            result.pop("local_stop", None)
            result.pop("durable_cancellation", None)
        return result

    def _start_control(self, principal, run_id):
        if self._owner_control:
            return start_owner_control(self, principal, run_id)
        # Ordinary injected compositions retain the same memory fence, no UDS.
        with self._lock:
            state = self._cancel_controls.get(run_id)
            if state is not None and state.principal != principal:
                raise PermissionError("Creator required")
            if state is None:
                self._cancel_controls[run_id] = SimpleNamespace(
                    principal=principal, stopped=False, server=SimpleNamespace(close=lambda: None)
                )
        return None

    def _settle_cancel(self, principal, run_id, local):
        if local.retired:
            return
        # ACK precedes the client's DB request. Retain the actual owner/cleanup
        # for bounded reconciliation, never redispatch or resend private bytes.
        latched = stop_requested(self, run_id)
        try:
            cancelled = self.store.get_run(run_id).state in ("cancel_requested", "cancelled")
        except Exception:
            cancelled = False
        if not (latched or cancelled):
            return
        stop_local(self, principal, run_id)
        if not hasattr(local, "cancel_wait_deadline"):
            local.cancel_wait_deadline = time.monotonic() + 20.0
        deadline = local.cancel_wait_deadline
        while True:
            if finish_cancelled(self, principal, run_id, local):
                return
            if time.monotonic() >= deadline:
                return  # uncertain ownership remains held; no forced unlock
            time.sleep(0.05)

    def _resume_authority(self, principal, run, contract, *, renew_authorization):
        """Capture absent local grants; only explicit renewal replaces old grants."""
        self._preflight(principal, contract)
        with self.authority.mutation_guard():
            try:
                self.authority.require_scene_execute(principal, contract, run_id=run.run_id)
            except ValueError as exc:
                if str(exc) == "Explicit execution binding required":
                    self.authority.bind_run(
                        principal,
                        run.operation_id,
                        contract,
                        run_id=run.run_id,
                        catalogue_sha256=self.catalogue_sha256,
                    )
                    self.authority.bind_workflow_models(principal, contract, run_id=run.run_id)
                elif renew_authorization:
                    self.authority.renew_run(principal, contract, run_id=run.run_id)
                else:
                    raise
            else:
                if renew_authorization:
                    self.authority.renew_run(principal, contract, run_id=run.run_id)

    def resume(self, principal, run_id, *, renew_authorization=False):
        if type(renew_authorization) is not bool:
            raise TypeError("Explicit boolean renewal required")
        current = self.status(principal, run_id)
        if current["disposition"] == "unknown" or current["state"] in (
            "accepted",
            "stopped",
            "cancelled",
        ):
            return current
        if "resume" not in current["available_actions"]:
            return self._blocked_status(principal, run_id)
        local = self._local.get(run_id)
        if local is not None and local.busy:
            return self._public(
                dict(
                    current,
                    disposition="blocked",
                    reason="foreground_operation_in_progress",
                )
            )
        try:
            self._start_control(principal, run_id)
            if stop_requested(self, run_id):
                stop_local(self, principal, run_id)
                if local is not None:
                    self._settle_cancel(principal, run_id, local)
                return self._blocked_status(principal, run_id)
            scene = self.store.scene_snapshot(run_id)
            if scene is not None:
                if scene.intent is not None and scene.intent.status == "reserved" and scene.intent.worker_fence is None:
                    contract = parse_contract(scene.run.contract_json)
                    self._resume_authority(principal, scene.run, contract, renew_authorization=renew_authorization)
                    if local is None:
                        return self._scene(principal, run_id, contract, continuation=True)
                    if local.ports is None or local.retired or local.stopped:
                        return self._blocked_status(principal, run_id)
                    local.ports.require_held_owner()
                    local.ports.restore_observations(
                        self.store.result_records(run_id),
                        parse_contract(scene.run.contract_json),
                    )
                    return self._drive_scene(principal, run_id, local)
                return self._blocked_status(principal, run_id)
            pending = self.store.pending_generation(run_id)
            if pending is not None:
                run = self.store.get_run(run_id)
                contract = parse_contract(run.contract_json)
                self._resume_authority(principal, run, contract, renew_authorization=renew_authorization)
                if local is not None and not local.retired:
                    # The authoritative pending read excludes a claim. Disarm the
                    # old coordinator, then release only its exact never-prepared
                    # capability; a preparation latch still vetoes this path.
                    if (
                        local.stopped
                        or local.ports is not None
                        or (
                            local.handle is not None
                            and (local.handle.fence is not None or local.handle.prepared is not None)
                        )
                    ):
                        return self._blocked_status(principal, run_id)
                    local.coordinator.stop_local(principal)
                    local.lease.release_never_prepared()
                    local.retired = True
                return self._generate(principal, run, contract, pending=pending)
            if local is not None and local.receiver is not None and local.handle is not None and not local.retired:
                result = local.receiver.receive(principal, local.handle.prepared, release_lease=True)
            else:
                recovery = self._recoveries.get(run_id)
                if recovery is None:
                    recovery = ForegroundGenerationRecovery(
                        self.private_parent,
                        run_id=run_id,
                        principal=principal,
                        service=self.service,
                        ownership_artifacts=self.ownership,
                        artifacts=self.artifacts,
                        protect=self.authority.protect_public,
                    )
                    self._recoveries[run_id] = recovery
                result = recovery.recover(release_lease=True)
                # Successful recovery releases this physical lease. A later
                # preflight denial must not cache an unusable recovery handle.
                self._recoveries.pop(run_id, None)
            if result.disposition == "validation":
                contract = parse_contract(result.run.contract_json)
                self._resume_authority(principal, result.run, contract, renew_authorization=renew_authorization)
                return self._scene(principal, run_id, contract)
            return self.status(principal, run_id)
        except Exception:
            with self._lock:
                local = self._local.get(run_id)
            if local is not None:
                self._settle_cancel(principal, run_id, local)
            return self._blocked_status(principal, run_id)

    def close(self):
        if self._closed:
            return
        try:
            # Attempt every owner even if another owner's cleanup fails.
            with self._lock:
                owners = tuple(self._local.items())
            for run_id, local in owners:
                try:
                    stop_local(self, local.principal, run_id)
                    if not local.retired:
                        finish_cancelled(self, local.principal, run_id, local)
                except Exception:
                    pass  # never release uncertain physical ownership here
        finally:
            try:
                close_controls(self)
            finally:
                self.authority.close()
                for resource in self._owned_resources:
                    resource.close()
                self._closed = True
