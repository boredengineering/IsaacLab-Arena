# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Application admission boundary; acceptance never releases an execution attempt."""

import time
from dataclasses import dataclass

from .admin import WorkflowScopeAdmin
from .contracts import canonical_json, parse_contract
from .neo4j_store import StoreUnavailable, validate_operation_id
from .queries import (
    HISTORICAL_CANDIDATE_VIEW_BYTES,
    FrozenRunIntentView,
    FrozenSubmissionInspection,
    RunCleanupView,
    RunInspection,
    SceneAssessmentView,
    SceneCandidateView,
    SceneDecisionView,
    SceneEvidenceView,
)
from .readiness import DependencyResult, ReadinessReport, required_dependencies
from .scope_binding import ScopeBinding


@dataclass(frozen=True)
class SubmissionResult:
    """Retained acceptance or a non-durable admission refusal."""

    disposition: str
    run: object | None
    readiness: ReadinessReport | None = None


class WorkflowProfileAdmin(WorkflowScopeAdmin):
    """Explicit catalogue and scope administration, never execution authority.

    Trusted composition binds store and require_admin(principal) to one scope.
    Registration never initializes; separate inherited admin methods are explicit.
    """

    def register_profile(self, principal, registration, *, protect):
        self._authority.require_admin(principal)
        if not callable(protect):
            raise ValueError("public protection callback required")
        return self._store.register_profile(registration, protect=protect)


class WorkflowService:
    """Compose scoped read authorization and exact replay before mutable checks.

    Store and authority are already bound to the same deployment/workspace by
    the trusted composition root. require_submit(principal, operation_id, contract)
    is a check-only admission port: never issue/renew/capture execution grants.
    Authority methods raise on denial; they never infer permissions from
    configured credentials or request effect flags. Exact replay requires only
    require_read(principal), independent of current execution authority.
    """

    def __init__(
        self, store, authority, gate, *, validate_support, max_pending=1, read_scope: ScopeBinding | None = None
    ):
        if type(max_pending) is not int or not 1 <= max_pending <= 1000:
            raise ValueError("Invalid pending workflow capacity")
        self._store = store
        self._authority = authority
        self._gate = gate
        self._validate_support = validate_support
        self._max_pending = max_pending
        self._read_scope = (
            None if read_scope is None else ScopeBinding.model_validate_json(read_scope.model_dump_json())
        )

    def _page_request(self, principal, first, after, protect, position_type):
        from .paging import decode_cursor, validate_first

        self._authority.require_read(principal)
        if self._read_scope is None:
            raise ValueError("Explicit read scope binding required")
        if not callable(protect):
            raise ValueError("public protection callback required")
        validate_first(first)
        return None if after is None else decode_cursor(after, self._read_scope, position_type)

    def list_runs(self, principal, *, first=100, after=None, protect):
        """Discover compact live keysets; retain the FIRST page watermark for bootstrap."""
        from .paging import MAX_PAGE_BYTES, EventPosition, RunPage, RunPosition, encode_cursor
        from .scene_evidence_artifacts import _protected

        position = self._page_request(principal, first, after, protect, RunPosition)
        window = self._store.list_runs_window(self._read_scope, first=first, after=position)
        rows = window.runs[:first]
        end = RunPosition(position=rows[-1].run_id) if rows else position
        result = RunPage(
            binding=window.binding,
            floor=window.floor,
            ceiling=window.ceiling,
            runs=rows,
            has_more=len(window.runs) > first,
            end_cursor=None if end is None else encode_cursor(window.binding, end),
            event_watermark=encode_cursor(
                window.binding, EventPosition(position=window.ceiling, floor=window.floor, ceiling=window.ceiling)
            ),
        )
        _protected(result.model_dump(mode="json"), protect, max_bytes=MAX_PAGE_BYTES)
        return result

    def list_scene_candidates(self, principal, run_id, *, first=100, after=None, protect):
        """Discover run-owned identities, not validated candidate payloads or artifacts."""
        from .paging import (
            MAX_PAGE_BYTES,
            CandidatePage,
            CandidatePosition,
            CursorQueryMismatch,
            RunPosition,
            encode_cursor,
        )
        from .scene_evidence_artifacts import _protected

        position = self._page_request(principal, first, after, protect, CandidatePosition)
        RunPosition(position=run_id)
        if position is not None and position.run_id != run_id:
            raise CursorQueryMismatch()
        window = self._store.list_scene_candidates_window(self._read_scope, run_id, first=first, after=position)
        result = None
        if window is not None:
            rows = window.candidates[:first]
            end = CandidatePosition(run_id=run_id, position=rows[-1].candidate_id) if rows else position
            result = CandidatePage(
                binding=window.binding,
                run_id=run_id,
                floor=window.floor,
                ceiling=window.ceiling,
                candidates=rows,
                has_more=len(window.candidates) > first,
                end_cursor=None if end is None else encode_cursor(window.binding, end),
            )
        _protected(
            None if result is None else result.model_dump(mode="json"),
            protect,
            max_bytes=MAX_PAGE_BYTES,
        )
        return result

    def list_decisions(self, principal, run_id, *, first=100, after=None, protect):
        """Discover producer-tagged identities; generation detail is unsupported."""
        from .paging import (
            MAX_PAGE_BYTES,
            CursorQueryMismatch,
            DecisionCoverageUnavailable,
            DecisionPage,
            DecisionPosition,
            RunPosition,
            encode_cursor,
        )
        from .scene_evidence_artifacts import _protected

        position = self._page_request(principal, first, after, protect, DecisionPosition)
        RunPosition(position=run_id)
        if position is not None and position.run_id != run_id:
            raise CursorQueryMismatch()
        window = self._store.list_decisions_window(self._read_scope, run_id, first=first, after=position)
        result = window
        if window is not None and not isinstance(window, DecisionCoverageUnavailable):
            rows = window.decisions[:first]
            end = DecisionPosition(run_id=run_id, position=rows[-1].decision_id) if rows else position
            result = DecisionPage(
                binding=window.binding,
                run_id=run_id,
                floor=window.floor,
                ceiling=window.ceiling,
                decisions=rows,
                has_more=len(window.decisions) > first,
                end_cursor=None if end is None else encode_cursor(window.binding, end),
            )
        _protected(
            None if result is None else result.model_dump(mode="json"),
            protect,
            max_bytes=MAX_PAGE_BYTES,
        )
        return result

    def read_scope_events(self, principal, *, first=100, after=None, protect):
        """Read retained invalidations, starting at the current floor when after is absent.

        Owner-only activity is not a run event; retain point polling. On replay
        expiry restart bounded bootstrap, never silently skip to the current tail.
        """
        from .paging import MAX_PAGE_BYTES, EventPosition, ScopeEventPage, encode_cursor
        from .scene_evidence_artifacts import _protected

        position = self._page_request(principal, first, after, protect, EventPosition)
        window = self._store.read_scope_events_window(self._read_scope, first=first, after=position)
        rows = window.events[:first]
        result = ScopeEventPage(
            binding=window.binding,
            floor=window.floor,
            ceiling=window.ceiling,
            events=rows,
            has_more=len(window.events) > first,
            resume_cursor=encode_cursor(
                window.binding,
                EventPosition(
                    position=rows[-1].sequence if rows else window.position, floor=window.floor, ceiling=window.ceiling
                ),
            ),
        )
        _protected(result.model_dump(mode="json"), protect, max_bytes=MAX_PAGE_BYTES)
        return result

    @property
    def bound_store(self):
        """Expose exact store identity for trusted coordinator composition."""
        return self._store

    def read_command(self, principal, kind, operation_id, *, protect):
        """Read exact scoped SUBMIT/CANCEL/RESUME facts without execution authority."""
        from .commands import COMMAND_BYTES, CancelReceipt, ResumeReceipt
        from .scene_evidence_artifacts import _protected

        if kind == "SUBMIT":
            return self.read_submission(principal, operation_id, protect=protect)
        self._authority.require_read(principal)
        validate_operation_id(operation_id)
        if not callable(protect):
            raise ValueError("public protection callback required")
        if type(kind) is not str or kind not in ("CANCEL", "RESUME"):
            raise ValueError("Unsupported command kind")
        model = CancelReceipt if kind == "CANCEL" else ResumeReceipt
        value = (self._store.get_cancel_receipt if kind == "CANCEL" else self._store.get_resume_receipt)(operation_id)
        result = None if value is None else model.model_validate_json(value.model_dump_json())
        _protected(None if result is None else result.model_dump(mode="json"), protect, max_bytes=COMMAND_BYTES)
        return result

    def admit_resume(self, principal, operation_id, payload, *, check_resume, check_eligibility, protect):
        """Admit a pinned continuation only; trusted callbacks are check-only ports.

        check_resume checks explicit command permission. check_eligibility checks
        the frozen contract/selection against current grants/readiness, or requested
        future binding/renewal eligibility; returns current/bind/renew/not_ready.
        Requested renewal requires bind or renew, never mere current credentials.
        Neither callback may issue grants, prepare, release, or perform execution.
        Both finish before the admission transaction takes the cooperative lock.
        """
        from .commands import (
            COMMAND_BYTES,
            CommandConflict,
            CorruptResumeSelection,
            ResumeAdmission,
            ResumePayload,
            command_json,
        )
        from .scene_evidence_artifacts import _protected

        self._authority.require_read(principal)
        validate_operation_id(operation_id)
        request = ResumePayload.model_validate(payload)
        if not callable(protect):
            raise ValueError("public protection callback required")
        retained = self._store.get_resume_receipt(operation_id)
        if retained is not None:
            if retained.payload_json != command_json(request.model_dump(mode="json")):
                raise CommandConflict("Resume key binds different input")
            result = ResumeAdmission(fresh=False, receipt=retained)
        else:
            if not callable(check_resume):
                raise ValueError("check-only resume permission required")
            preview = self._store.preview_resume(request.runId)
            contract = None
            if preview.selection is not None:
                try:
                    contract = parse_contract(preview.run.contract_json)
                except (ValueError, TypeError, KeyError, RecursionError):
                    raise CorruptResumeSelection() from None
            check_resume(principal, operation_id, request)
            eligibility = None
            if (
                preview.selection is not None
                and preview.selection.branch != "reconciliation"
                and preview.run.version == request.expectedVersion
            ):
                if not callable(check_eligibility):
                    raise ValueError("check-only continuation eligibility required")
                eligibility = check_eligibility(
                    principal,
                    contract,
                    preview.selection,
                    renew_authorization=request.renewAuthorization,
                )
            result = self._store.admit_resume(
                operation_id,
                request.model_dump(mode="json"),
                selection=preview.selection,
                eligibility=eligibility,
                protect=protect,
            )
        _protected(result.model_dump(mode="json"), protect, max_bytes=COMMAND_BYTES)
        return result

    def read_submission(self, principal, operation_id, *, protect) -> FrozenSubmissionInspection | None:
        """Recover immutable legacy admission without original request bytes."""
        from .queries import SUBMISSION_INSPECTION_BYTES
        from .scene_evidence_artifacts import _protected

        self._authority.require_read(principal)
        validate_operation_id(operation_id)
        if not callable(protect):
            raise ValueError("public protection callback required")
        value = self._store.get_submission_inspection(operation_id)
        result = None if value is None else FrozenSubmissionInspection.model_validate_json(value.model_dump_json())
        _protected(
            None if result is None else result.model_dump(mode="json"), protect, max_bytes=SUBMISSION_INSPECTION_BYTES
        )
        return result

    def read_run_intent(self, principal, run_id, *, protect) -> FrozenRunIntentView | None:
        """Screen frozen retained intent and lifecycle, not a joined operational view."""
        from .queries import RUN_INTENT_VIEW_BYTES
        from .scene_evidence_artifacts import _protected

        self._authority.require_read(principal)
        validate_operation_id(run_id)
        if not callable(protect):
            raise ValueError("public protection callback required")
        value = self._store.get_run_intent(run_id)
        result = None if value is None else FrozenRunIntentView.model_validate_json(value.model_dump_json())
        _protected(None if result is None else result.model_dump(mode="json"), protect, max_bytes=RUN_INTENT_VIEW_BYTES)
        return result

    def read_run_inspection(self, principal, run_id, *, protect, check_action_permission=None) -> RunInspection | None:
        """Screen an atomic retained snapshot, then optionally observe check-only permission.

        The trusted permission port receives (principal, retained RunInspection) and
        returns ActionPermissionObservation. It must not issue grants, probe readiness
        or execute commands. Its observation is outside the retained transaction.
        """
        from .queries import RUN_INSPECTION_BYTES, ActionPermissionObservation
        from .read_model import inspection_response_revision
        from .scene_evidence_artifacts import _protected

        try:
            self._authority.require_read(principal)
        except Exception:
            raise PermissionError("Run inspection read denied") from None
        validate_operation_id(run_id)
        if not callable(protect):
            raise ValueError("public protection callback required")
        if check_action_permission is not None and not callable(check_action_permission):
            raise ValueError("check-only permission callback required")
        value = self._store.get_run_inspection(run_id)
        result = None if value is None else RunInspection.model_validate_json(value.model_dump_json())
        try:
            if result is not None and check_action_permission is not None:
                observed = check_action_permission(principal, result)
                if type(observed) is not ActionPermissionObservation:
                    raise ValueError("typed permission observation required")
                observed = ActionPermissionObservation.model_validate_json(observed.model_dump_json())
                actions = result.actions.model_copy(update={"permission_observation": observed})
                result = inspection_response_revision(result.model_copy(update={"actions": actions}))
            _protected(
                None if result is None else result.model_dump(mode="json"), protect, max_bytes=RUN_INSPECTION_BYTES
            )
        except Exception:
            raise ValueError("Run inspection public observation rejected") from None
        return result

    def read_run_cleanup(self, principal, run_id, *, protect) -> RunCleanupView | None:
        """Screen all retained cleanup obligations under current read authority, without effects."""
        from .scene_evidence_artifacts import _protected

        self._authority.require_read(principal)
        validate_operation_id(run_id)
        if not callable(protect):
            raise ValueError("public protection callback required")
        value = self._store.get_run_cleanup(run_id)
        result = None if value is None else RunCleanupView.model_validate_json(value.model_dump_json())
        _protected(None if result is None else result.model_dump(mode="json"), protect)
        return result

    def read_profile(self, principal, profile_id, revision, *, protect):
        """Return exact immutable public metadata under current read authorization."""
        from .profiles import ProfileIdentity, ProfileRevision
        from .scene_evidence_artifacts import _protected

        self._authority.require_read(principal)
        ProfileIdentity(profile_id=profile_id, revision=revision)
        if not callable(protect):
            raise ValueError("public protection callback required")
        value = self._store.get_profile(profile_id, revision)
        result = None if value is None else ProfileRevision.model_validate_json(value.model_dump_json())
        _protected(None if result is None else result.model_dump(mode="json"), protect)
        return result

    def list_profiles(self, principal, *, protect):
        """Screen the entire bounded catalogue without readiness checks or grants."""
        from .profiles import MAX_PROFILE_REVISIONS, ProfileRevision
        from .scene_evidence_artifacts import _protected

        self._authority.require_read(principal)
        if not callable(protect):
            raise ValueError("public protection callback required")
        values = self._store.list_profiles()
        if len(values) > MAX_PROFILE_REVISIONS:
            raise ValueError("Public profile capacity exceeded")
        result = tuple(ProfileRevision.model_validate_json(value.model_dump_json()) for value in values)
        _protected([value.model_dump(mode="json") for value in result], protect)
        return result

    def _read_scene(self, principal, record_id, kind, view_type, protect):
        from .scene_evidence_artifacts import _protected

        self._authority.require_read(principal)
        validate_operation_id(record_id)
        if not callable(protect):
            raise ValueError("public protection callback required")
        value = getattr(self._store, "get_scene_" + kind)(record_id)
        if value is None:
            _protected(None, protect)
            return None
        # Revalidate and screen a detached public tree; reject-only callbacks may
        # neither redact retained identities nor mutate the returned typed value.
        value = view_type.model_validate_json(value.model_dump_json())
        limit = HISTORICAL_CANDIDATE_VIEW_BYTES if view_type is SceneCandidateView else 2 * 1024 * 1024
        _protected(value.model_dump(mode="json"), protect, max_bytes=limit)
        return value

    def read_scene_candidate(self, principal, candidate_id, *, protect) -> SceneCandidateView | None:
        """Read exact retained candidate bytes and parent/original IDs under current read authority."""
        return self._read_scene(principal, candidate_id, "candidate", SceneCandidateView, protect)

    def read_scene_decision(self, principal, decision_id, *, protect) -> SceneDecisionView | None:
        """Read a scene decision and its exact selected links; generation decisions are unsupported."""
        return self._read_scene(principal, decision_id, "decision", SceneDecisionView, protect)

    def read_scene_assessment(self, principal, assessment_id, *, protect) -> SceneAssessmentView | None:
        """Read an exact retained assessment and evidence/candidate identity, without reassessment."""
        return self._read_scene(principal, assessment_id, "assessment", SceneAssessmentView, protect)

    def read_scene_evidence(self, principal, evidence_id, *, protect) -> SceneEvidenceView | None:
        """Read an exact retained observation; metadata does not reverify artifact bytes."""
        return self._read_scene(principal, evidence_id, "evidence", SceneEvidenceView, protect)

    def read_retained_bundle(self, principal, run_id, kind, reference_id, *, artifact_root, artifact_binding, protect):
        """Authenticate retained references and verify bytes in the configured private artifact area."""
        from ..workbench.research_artifacts import ArtifactArea
        from .artifacts import RetainedArtifacts

        self._authority.require_read(principal)
        if self._read_scope is None or self._read_scope != artifact_binding or artifact_root is None:
            raise ValueError("Bound read-only artifact configuration required")
        validate_operation_id(run_id)
        validate_operation_id(reference_id)
        with ArtifactArea.open(
            artifact_root, store_id=artifact_binding.store_id, registry_id=artifact_binding.registry_id
        ) as area:
            return RetainedArtifacts(self, area, protect).read(principal, run_id, kind, reference_id)

    def read_artifact_chunk(
        self,
        principal,
        run_id,
        kind,
        reference_id,
        name,
        expected_sha256,
        offset,
        limit,
        *,
        artifact_root,
        artifact_binding,
        protect,
    ):
        """Return bounded exact bytes, with current read authority and no execution credentials."""
        from .artifacts import artifact_chunk

        self._authority.require_read(principal)
        if type(limit) is not int or not 1 <= limit <= 65536 or type(offset) is not int or offset < 0:
            raise ValueError("Invalid artifact byte range")
        bundle = self.read_retained_bundle(
            principal,
            run_id,
            kind,
            reference_id,
            artifact_root=artifact_root,
            artifact_binding=artifact_binding,
            protect=protect,
        )
        return None if bundle is None else artifact_chunk(bundle, name, expected_sha256, offset, limit)

    def read_generation_recovery(self, principal, run_id, *, expected_fence=None):
        """Authenticate the exact original attempt without issuing execution authority."""
        self._authority.require_read(principal)
        run = self._store.get_run(run_id)
        attempt = (
            self._store.get_generation_attempt(run_id)
            if expected_fence is None
            else self._store.get_attempt(expected_fence)
        )
        if (
            attempt is None
            or attempt.fence.run_id != run_id
            or (
                expected_fence is not None
                and (
                    attempt.fence != expected_fence
                    or attempt.registration is None
                    or attempt.registration.fence != expected_fence
                )
            )
            or attempt.authorization.principal != principal
            or attempt.contract_json != run.contract_json
        ):
            raise ValueError("Original generation recovery binding required")
        return run, attempt, self._store.get_owner()

    def adopt_generation(self, principal, fence, receipt, *, artifacts, protect):
        """Read-authorized exact released recovery; expired execution grants are irrelevant.

        The protection callback remains mandatory under current data policy. No
        authority renewal, provider call or current-configuration inference occurs.
        """
        checked = WorkflowService.prepare_generation_adoption(
            self, principal, fence, receipt, artifacts=artifacts, protect=protect
        )
        return self._store.commit_generation_receipt(fence, checked)

    def prepare_generation_adoption(self, principal, fence, receipt, *, artifacts, protect):
        """Verify retained authority/bindings and actual bytes before possible commit.

        This returns a receipt, not durable adoption. Trusted receivers may pin
        this exact verified value before calling the same store's commit boundary.
        Every adoption/repeat must perform this verification again.
        """
        from .artifacts import GenerationArtifacts
        from .contracts import contract_digest
        from .results import GenerationReceipt

        self._authority.require_read(principal)
        retained = self._store.get_attempt(fence)
        if principal != retained.authorization.principal:
            raise ValueError("receipt principal does not own retained attempt")
        if type(artifacts) is not GenerationArtifacts or type(receipt) is not GenerationReceipt:
            raise ValueError("concrete generation artifacts and typed receipt required")
        contract = parse_contract(retained.contract_json)
        if (
            not retained.released
            or retained.registration != receipt.registration
            or receipt.fence != fence
            or contract_digest(contract) != receipt.contract_digest
            or contract.execution.generation_model != receipt.generation_profile
        ):
            raise ValueError("receipt retained binding mismatch")
        checked = artifacts.verify(receipt, protect=protect)
        if checked != receipt:
            raise ValueError("verified artifact digests differ")
        return checked

    def start_scene(self, principal, run_id, *, artifacts, protect, validate_generation_candidate, profile):
        """Reverify retained generation bytes and stage the original candidate.

        The trusted composition passes workflow.validation.validate_generation_candidate
        as the schema port. Keeping the callable explicit avoids importing native
        registries into this runtime-independent service. Synthetic test validators
        must stay labelled synthetic; they are not actual-schema acceptance.
        """
        import json

        from .artifacts import GenerationArtifacts
        from .scene_loop import candidate_record

        self._authority.require_read(principal)
        run = self._store.get_run(run_id)
        contract = parse_contract(run.contract_json)
        if contract.schema_version == "3":
            import hashlib

            from .contracts import contract_digest

            authorization = self._authority.require_scene_execute(principal, contract, run_id=run_id, retained_run=run)
            assert contract.source.kind == "existing", "Retained native source required"
            raw = contract.source.content.encode("utf-8")
            spec = json.loads(raw)
            if type(spec) is not dict:
                raise ValueError("Retained candidate must be a JSON object")
            candidate = candidate_record(run_id, spec, source_id=contract.source.identity)
            validation = dict(
                disposition="external_candidate_admitted",
                source_identity=contract.source.identity,
                source_bytes_sha256=hashlib.sha256(raw).hexdigest(),
                candidate_json_sha256=candidate.digest,
                contract_digest=contract_digest(contract),
                native_schema_validation_required=True,
            )
            protect(validation)
            return self._store.begin_scene(
                run_id, run.version, candidate, validation, profile, authorization=authorization
            )
        if contract.schema_version == "4":
            from .retained_assessment import load_retained_source
            from .scene_evidence_artifacts import SceneEvidenceArtifacts

            authorization = self._authority.require_scene_execute(principal, contract, run_id=run_id, retained_run=run)
            evidence_id, _, _, _, _ = load_retained_source(
                self._store, SceneEvidenceArtifacts(artifacts.area), contract, protect=protect
            )
            candidate = candidate_record(
                run_id, json.loads(contract.source.content), source_id=contract.source.identity
            )
            validation = dict(
                disposition="retained_assessment_consumer",
                producer=contract.retained_evidence.model_dump(mode="json"),
                producer_evidence_id=evidence_id,
            )
            return self._store.begin_scene(
                run_id, run.version, candidate, validation, profile, authorization=authorization
            )
        run, attempt, _ = self.read_generation_recovery(principal, run_id)
        if type(artifacts) is not GenerationArtifacts or attempt.receipt is None or attempt.cleanup is None:
            raise ValueError("retained generation bytes and cleanup required")
        files = artifacts.verified_bytes(attempt.receipt, protect=protect)
        validation = validate_generation_candidate(artifacts, attempt.receipt, protect=protect)
        if hasattr(validation, "model_dump"):
            validation = validation.model_dump(mode="json")
        candidate = candidate_record(run_id, json.loads(files["candidate.json"]), source_id=attempt.fence.attempt_id)
        return self._store.begin_scene(run_id, run.version, candidate, validation, profile)

    def run_scene(self, principal, run_id, *, ports, resume_receipt=None):
        """Drive the retained scene loop through explicitly trusted bounded ports.

        Native adapters, physical owner-local stop and transport enforcement remain
        composition gates, not inferred from a profile label or successful callback.
        With profile.owned_worker=True the required trusted hooks are:
        require_held_owner() -> OwnerView (checks the actual held lease),
        prepare_worker(intent, candidate, original, contract) -> WorkerRegistration,
        cleanup_worker(intent) -> CleanupEvidence. Prepare receives worker_fence;
        execute receives its committed registration and release. Cleanup MUST retain
        its local witness and handle partial prepare even without a registration.
        execute must use authority.release_guard(..., run_id=...), recheck exact
        retained fence/registration and lease, then resolve private_model_config
        inside that guard before the one bounded send. Its deadline is the minimum
        private_model_deadline for every required role, original run deadline and
        stage runtime allowance; generation snapshot expiry is NOT assessment TTL.
        No private resolution or
        SDK/runtime operation belongs in a store transaction. Ports are application
        composition, never user-supplied callbacks or booleans.
        require_bounded_capability is a check-only trusted port returning literal
        True after validating current authority/configuration AND enforced call,
        token, cost, runtime and capture ceilings for this reservation. Missing or
        false capability blocks release. Native composition must bind the existing
        authority token/cost check and CallAllowance.token_cost_bounded, not copy
        reservation values or accept provider self-reported usage as proof.
        V2 splits capture/assessment into separately owned intents. Capture has no
        model reservation. After trusted cleanup and durable acknowledgement,
        release_native_resource(intent, cleanup) must verify/release the physical
        GPU slot and return literal True; it must not release the scope owner lease.
        Assessment prepare/execute receive retained_observation=Observation, read
        from the intent's exact observation_id/digest. Ports reopen its manifests,
        never recreate a simulator. V2 output verification runs after child cleanup,
        before atomic capture adoption and next-intent reservation. Zero-call numeric
        assessment may use an owned evaluator child, never a model child.
        """
        self._authority.require_read(principal)
        profile = self._checked_scene_ports(ports)
        while True:
            snapshot = self._store.scene_snapshot(run_id)
            if snapshot is None:
                raise ValueError("retained validated scene required")
            if resume_receipt is not None:
                from .commands import ResumeReceipt
                from .contracts import contract_digest

                receipt = ResumeReceipt.model_validate_json(resume_receipt.model_dump_json())
                if (
                    receipt.disposition != "continuation_admitted"
                    or receipt.run_id != run_id
                    or receipt.selection.branch != "scene"
                    or not profile.owned_worker
                    or snapshot.run.version != receipt.after_version
                    or contract_digest(parse_contract(snapshot.run.contract_json)) != receipt.contract_digest
                    or snapshot.run.state != "running"
                    or snapshot.intent is None
                    or snapshot.intent.intent_id != receipt.selection.intent_id
                    or snapshot.intent.status != "reserved"
                    or snapshot.intent.worker_fence is not None
                ):
                    raise ValueError("Resume scene selection changed")
            if snapshot.profile != profile:
                raise ValueError("scene port profile changed")
            if snapshot.run.state != "running" or snapshot.intent is None:
                return snapshot
            if snapshot.intent.status != "reserved":
                # Released effects are never attempted again, including fresh
                # interpreter recovery. The caller must reconcile exact output.
                if snapshot.intent.status == "released":
                    self._store.mark_scene_unknown(run_id, snapshot.intent.intent_id)
                    return self._store.scene_snapshot(run_id)
                return snapshot
            if snapshot.intent.worker_fence is not None:
                return snapshot  # Prepared/ambiguous ownership is never fresh work.
            contract = parse_contract(snapshot.run.contract_json)
            stage_args = {}
            if snapshot.intent.action == "assess":
                stage_args["retained_observation"] = self._store.get_scene_capture(run_id, snapshot.intent.intent_id)
            auth = ports.authorize(principal, contract, snapshot.intent.action)
            ready = ports.ready(contract)
            auth = ports.authorize(principal, contract, snapshot.intent.action)
            bounded = getattr(ports, "require_bounded_capability", None)
            if not callable(bounded) or bounded(principal, contract, snapshot.intent.reservation) is not True:
                raise ValueError("bounded scene port capability required")
            failed = False
            worker_intent = None
            release_args = {}
            try:
                if profile.owned_worker:
                    owner = ports.require_held_owner()
                    fence = self._store.claim_scene_worker(
                        run_id,
                        snapshot.intent.intent_id,
                        owner.owner_id,
                        owner.owner_epoch,
                        **({} if resume_receipt is None else dict(resume_operation_id=resume_receipt.operation_id)),
                    )
                    resume_receipt = None  # Only acknowledged first claim consumes the pin.
                    worker_intent = snapshot.intent.model_copy(update={"worker_fence": fence})
                    registration = ports.prepare_worker(
                        worker_intent, snapshot.candidate, snapshot.original, contract, **stage_args
                    )
                    worker_intent = worker_intent.model_copy(update={"worker_registration": registration})
                    self._store.register_scene_worker(fence, registration)
                    if ports.require_held_owner() != owner:
                        raise ValueError("scene owner changed")
                    auth = ports.authorize(principal, contract, snapshot.intent.action)
                    ready = ports.ready(contract)
                    if bounded(principal, contract, snapshot.intent.reservation) is not True:
                        raise ValueError("bounded scene port capability revoked")
                    release_args = dict(fence=fence, registration_id=registration.registration_id)
                if not self._store.release_scene(
                    run_id, snapshot.intent.intent_id, auth, readiness=ready, **release_args
                ):
                    return self._store.scene_snapshot(run_id)
                released = self._store.scene_snapshot(run_id)
                # Recheck after committed release; a denial is unresolved, not retry.
                self._check_released_scene(
                    ports, principal, run_id, contract, released, release_args, owner if profile.owned_worker else None
                )
                output = ports.execute(released.intent, released.candidate, released.original, contract, **stage_args)
                if released.intent.action in ("capture", "assess", "policy"):
                    # Reopen immutable receipt bytes only after the owned child
                    # has stopped; an earlier read could race its final writes.
                    result = None
                else:
                    result = self._verify_scene_result(ports, released, contract, output)
                if self._store.get_run(run_id).state != "running":
                    raise ValueError("scene cancelled during execution")
            except Exception:
                if resume_receipt is not None and worker_intent is None:
                    # Stale first-claim rejection must not poison replacement work.
                    # An unknown claim ACK still leaves its durable fence obligation;
                    # it is not proof of nonclaim, cleanup or permission to retry.
                    raise
                if not profile.owned_worker and self._store.scene_snapshot(run_id).intent.status == "reserved":
                    raise
                self._store.mark_scene_unknown(run_id, snapshot.intent.intent_id)
                failed = True
            finally:
                if worker_intent is not None:
                    self._cleanup_scene_stage(ports, run_id, worker_intent, profile)
            current = self._store.scene_snapshot(run_id)
            if failed or current.run.state != "running":
                return current
            if result is None:
                try:
                    result = self._verify_scene_result(ports, released, contract, output)
                except Exception:
                    self._store.mark_scene_unknown(run_id, released.intent.intent_id)
                    raise
            try:
                self._store.finish_scene(run_id, released.intent.intent_id, current.run.version, result)
            except Exception:
                if released.intent.action == "policy":
                    self._store.mark_scene_unknown(run_id, released.intent.intent_id)
                raise

    @staticmethod
    def _checked_scene_ports(ports):
        """Validate the selected version's trusted lifecycle hooks without effects."""
        from .scene_loop import ScenePortProfile

        profile = ScenePortProfile.model_validate_json(ports.profile.model_dump_json())
        if profile.owned_worker and any(
            not callable(getattr(ports, name, None))
            for name in ("prepare_worker", "cleanup_worker", "require_held_owner")
        ):
            raise ValueError("managed scene worker ports required")
        if (
            profile.codec_version == 2
            and profile.assurance != "retained-evidence"
            and not callable(getattr(ports, "release_native_resource", None))
        ):
            raise ValueError("trusted capture slot release port required")
        if profile.policy is not None and not callable(getattr(ports, "verify_policy", None)):
            raise ValueError("trusted policy receipt verification port required")
        return profile

    def _check_released_scene(self, ports, principal, run_id, contract, released, release_args, owner):
        """Recheck authority, readiness and exact ownership at the released effect boundary."""
        auth = ports.authorize(principal, contract, released.intent.action)
        ready = ports.ready(contract)
        checked = self._store.check_scene_release(
            run_id, released.intent.intent_id, auth, readiness=ready, **release_args
        )
        if checked != released.intent:
            raise ValueError("committed scene release changed")
        if released.profile.owned_worker and ports.require_held_owner() != owner:
            raise ValueError("scene owner changed")
        if ports.require_bounded_capability(principal, contract, released.intent.reservation) is not True:
            raise ValueError("bounded scene port capability revoked")
        if released.run.state != "running":
            raise ValueError("scene cancelled after release")

    def _cleanup_scene_stage(self, ports, run_id, intent, profile):
        """Stop before database dependence; release GPU only after exact cleanup acknowledgement."""
        try:
            cleanup = ports.cleanup_worker(intent)
            self._store.acknowledge_scene_cleanup(intent.worker_fence, cleanup)
            if intent.action in ("capture", "policy"):
                if ports.release_native_resource(intent, cleanup) is not True:
                    raise ValueError("capture slot release unverified")
        except Exception:
            if profile.codec_version == 2:
                self._store.mark_scene_unknown(run_id, intent.intent_id)
            raise

    @staticmethod
    def _verify_scene_result(ports, released, contract, output):
        """Reopen exact stage evidence; V2 callers invoke only after child cleanup."""
        from .policy_contracts import PolicyTrialReceipt
        from .repairs import _scene_json
        from .scene_loop import Observation, SceneResult

        version = released.profile.codec_version
        if contract.schema_version == "4":
            return SceneResult(
                codec_version=version,
                retained_assessment_json=ports.verify_retained_assessment(output, contract, released.intent),
            )
        if released.intent.action == "policy":
            checked = ports.verify_policy(output, contract, released.candidate, released.intent.policy_binding)
            if type(checked) is not PolicyTrialReceipt:
                raise ValueError("typed verified policy trial required")
            return SceneResult(
                codec_version=version, policy_trial=PolicyTrialReceipt.model_validate_json(checked.model_dump_json())
            )
        if released.intent.action in ("observe", "capture", "assess"):
            checked = ports.verify_observation(output, contract, released.candidate)
            return SceneResult(codec_version=version, observation=Observation.model_validate(checked))
        try:
            ports.validate_candidate(output)
            return SceneResult(codec_version=version, candidate_json=_scene_json(output))
        except ValueError:
            return SceneResult(codec_version=version, failure="invalid_candidate")

    def submit(self, principal, operation_id: str, raw: str | bytes) -> SubmissionResult:
        """Admit or replay without releasing model, simulator or worker execution.

        Args:
            principal: Trusted authenticated identity, never credentials.
            operation_id: Scoped submission key; a changed request is a conflict.
            raw: Strict versioned workflow JSON.

        Returns:
            Retained acceptance, fresh pending admission, or local not-ready report.
        """
        self._authority.require_read(principal)
        validate_operation_id(operation_id)
        request = parse_contract(raw)
        normalized = canonical_json(request)
        try:
            retained = self._store.lookup_submission(operation_id, normalized)
        except StoreUnavailable:
            profile = request.execution.database
            report = ReadinessReport(
                (
                    DependencyResult(
                        "neo4j",
                        "unavailable",
                        profile.settings_sha256,
                        profile_id=profile.profile_id,
                        code="probe_failed",
                    ),
                ),
                time.monotonic(),
            )
            return SubmissionResult("dependencies_not_ready", None, report)
        if retained is not None:
            return SubmissionResult("retained", retained)
        if not request.effects.allow_operational_writes:
            raise ValueError("operational_writes_not_permitted")
        self._validate_support(request)
        self._authority.require_submit(principal, operation_id, request)
        report = self._gate.check(
            required_dependencies(request),
            timeout_s=min(120, request.budget.per_operation_timeout_seconds),
        )
        if not report.ready:
            return SubmissionResult("dependencies_not_ready", None, report)
        # Readiness consumes time. Recheck current authority before accepting;
        # every subsequent worker release still needs its own durable grant check.
        self._authority.require_submit(principal, operation_id, request)
        retained = self._store.admit(operation_id, normalized, normalized, self._max_pending)
        return SubmissionResult("accepted", retained, report)
