# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Synthetic-only composition of retained producers, not a lifecycle controller.

Callbacks are trusted effects, NOT permission inferred from installed credentials.
Capture returns a context manager yielding CaptureRuntime; its exit owns cleanup.
Refine accepts exact CandidateRecords, original baseline and byte-verified feedback.
Visual accepts the exact producer request and retained frames (including bytes).
Both model callbacks must use the supplied CallAllowance for every SDK attempt,
including constructor pings/retries, and must not use unmanaged fallback transports.

Only cooperative synthetic callbacks are admitted here. This is NOT a hard timeout,
process ownership, native permission or restart recovery implementation. A released
intent never retries; the existing service/store owns uncertainty and cancellation.
"""

import hashlib
import json
import math
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .contracts import contract_digest
from .evidence import CandidateBinding, EvidenceCohort
from .evidence_contracts import project_required_criteria
from .inference_transport import CallAllowance, checked_workflow_accounting
from .scene_loop import Observation, ScenePortProfile, assess_and_route, identity, profile_digest
from .scene_observation import (
    ObservationRecorder,
    admit_criterion,
    effective_displacement,
    evaluate_measurement,
    evaluate_visual_answer,
    retain_visual_answer,
    visual_request,
)


@dataclass(frozen=True)
class CaptureRuntime:
    env: object
    policy: object
    sample_state: object
    save_frame: object


@dataclass(frozen=True)
class ModelCeiling:
    """Configured adapter ceilings, independent of the requested reservation."""

    max_calls: int
    max_tokens: int | None
    max_cost_usd: str | None
    timeout_seconds: float
    per_call_bound: dict

    def allowance(self, *, now):
        return CallAllowance(
            max_calls=self.max_calls,
            deadline=now + self.timeout_seconds,
            max_tokens=self.max_tokens,
            cost_ceiling_usd=self.max_cost_usd,
            per_call_bound=self.per_call_bound,
        )


class ScenePorts:
    """Compose existing capture, storage, numeric/per-frame evaluators and repair port.

    authorize(principal, contract, action) and ready(contract) are check-only ports
    returning the existing store's authorization/readiness receipts. check_active()
    must raise on cancellation/revocation; it is polled between bounded operations.
    direct_root_subjects explicitly attests identity root translation in env-local
    meters; neither an at_position relation nor a reservation establishes it.
    """

    def __init__(
        self,
        *,
        profile,
        artifacts,
        protect,
        authorize,
        ready,
        capture,
        refine,
        visual,
        model_ceiling=None,
        model_ceilings=None,
        capture_steps,
        capture_timeout_seconds,
        output_root,
        direct_root_subjects,
        displacement_tolerance_m,
        check_active,
    ):
        self.profile = ScenePortProfile.model_validate_json(profile.model_dump_json())
        self.artifacts, self.protect = artifacts, protect
        self._authorize, self._ready = authorize, ready
        self._capture, self._refine, self._visual = capture, refine, visual
        # Legacy pure-synthetic ports may retain one shared ceiling. Model-backed
        # composition must supply both literal roles; never guess the assessor.
        if (model_ceiling is None) == (model_ceilings is None):
            raise ValueError("choose shared synthetic or exact role model ceilings")
        native_only = (
            self.profile.codec_version == 2 and self.profile.assurance == "native-unverified" and model_ceilings == {}
        )
        retained_only = self.profile.assurance == "retained-evidence" and set(model_ceilings or {}) == {"assessment"}
        configurable = self.profile.workflow_schema == "5" and set(model_ceilings or {}) <= {"generation", "assessment"}
        if (
            model_ceilings is not None
            and not native_only
            and not retained_only
            and not configurable
            and (type(model_ceilings) is not dict or set(model_ceilings) != {"generation", "assessment"})
        ):
            raise ValueError("complete generation/assessment ceilings required")

        def detach(ceiling):
            return ModelCeiling(
                **(vars(ceiling) | {"per_call_bound": checked_workflow_accounting(ceiling.per_call_bound)})
            )

        self.model_ceiling = detach(model_ceiling) if model_ceiling is not None else None
        self.model_ceilings = {role: detach(value) for role, value in (model_ceilings or {}).items()}
        self.capture_steps = capture_steps
        self.capture_timeout_seconds = capture_timeout_seconds
        self.output_root = Path(output_root)
        self.direct_root_subjects = frozenset(direct_root_subjects)
        self.displacement_tolerance_m = displacement_tolerance_m
        self.check_active = check_active
        self._retained = {}
        self._latest = {}
        self._executed = set()
        self._restored_decisions = {}

    def admit(self, contract):
        """Pure support checks; run also at submission before any model construction."""
        explicit = contract.schema_version == "5"
        if explicit != (self.profile.workflow_schema == "5"):
            raise ValueError("configurable scene execution requires installed G2 wiring")
        if self.model_ceiling is None and not self.model_ceilings and contract.schema_version != "3" and not explicit:
            raise ValueError("Model-free ports require the explicit native-only contract")
        project_required_criteria(contract)
        criteria = tuple(admit_criterion(c) for c in contract.criteria)
        windows = {(c.observation_window.start_step, c.observation_window.end_step) for c in criteria}
        minimum_steps = 0 if contract.schema_version == "3" else 1
        if (
            (not explicit and windows != {self.capture_window()})
            or type(self.capture_steps) is not int
            or self.capture_steps < minimum_steps
        ):
            raise ValueError("unsupported capture window")
        visual = [c for c in criteria if c.kind == "visual"]
        if len(visual) > 1:
            raise ValueError("unsupported multiple visual criteria: one-answer codec")
        if (
            visual
            and (
                len(contract.acquisition.images)
                if explicit
                else len(visual[0].coordinate_frames) * (self.capture_steps + 1)
            )
            > 16
        ):
            raise ValueError("unsupported image coverage bound")
        if not {c.evidence_producer for c in criteria} <= set(self.profile.producer_ids):
            raise ValueError("unsupported configured producer")
        if any(rule.subject_id not in self.direct_root_subjects for rule in contract.allowed_interventions):
            raise ValueError("explicit direct root origin mapping required")
        if (
            contract.schema_version == "5"
            and contract.action_policy.observation is not None
            and contract.action_policy.observation != contract.acquisition
        ):
            raise ValueError("Changed acquisition schedules are not implemented by this installed adapter")
        return criteria

    def capture_window(self):
        """Return the exact absolute evidence window admitted by this producer."""
        return (0, self.capture_steps)

    def authorize(self, principal, contract, action):
        self.admit(contract)
        self.check_active()
        return self._authorize(principal, contract, action)

    def ready(self, contract):
        self.admit(contract)
        return self._ready(contract)

    def ceiling_for(self, action):
        """Select generation for repair and assessment for observation, never fallback roles."""
        if action not in ("observe", "repair"):
            raise ValueError("unsupported scene action")
        if self.model_ceiling is not None:
            return self.model_ceiling
        return self.model_ceilings["generation" if action == "repair" else "assessment"]

    def require_bounded_capability(self, principal, contract, reservation):
        """Compare actual configured ceilings and attestation, not reservation truthiness."""
        self.admit(contract)
        self.check_active()
        if reservation not in (self.profile.observe, self.profile.repair):
            raise ValueError("unconfigured reservation")
        ceiling = self.ceiling_for("observe" if reservation == self.profile.observe else "repair")
        allowance = ceiling.allowance(now=time.monotonic())  # check-only, no model construction
        if (
            not allowance.token_cost_bounded
            or not math.isfinite(ceiling.timeout_seconds)
            or ceiling.timeout_seconds <= 0
        ):
            raise ValueError("bounded model allowance required")
        bound = checked_workflow_accounting(ceiling.per_call_bound)
        if (
            ceiling.max_calls > reservation.model_calls
            or ceiling.max_tokens > reservation.model_tokens
            or Decimal(ceiling.max_cost_usd) > Decimal(str(reservation.cost_ceiling_usd))
            or bound["max_tokens"] > ceiling.max_tokens
            or Decimal(bound["max_cost_usd"]) > Decimal(ceiling.max_cost_usd)
        ):
            raise ValueError("configured model ceiling exceeds reservation or attested allowance")
        runtime = ceiling.timeout_seconds
        if reservation == self.profile.observe:
            runtime += self.capture_timeout_seconds
            if (
                not math.isfinite(self.capture_timeout_seconds)
                or self.capture_timeout_seconds <= 0
                or self.capture_steps > reservation.steps
                or reservation.realizations < 1
                or reservation.observations < 1
            ):
                raise ValueError("configured capture ceiling exceeds reservation")
        if runtime > min(reservation.runtime_allowance_seconds, contract.budget.per_operation_timeout_seconds):
            raise ValueError("configured runtime ceiling exceeds reservation")
        return True

    @staticmethod
    def validate_candidate(candidate):
        """Validate the real Arena schema without normalizing away forbidden edits."""
        from isaaclab_arena.agentic_environment_generation.workbench.document_yaml import reject_unknown_fields
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

        value = json.loads(candidate) if isinstance(candidate, str) else candidate
        pending = [value]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                if "external_yaml" in node:
                    raise ValueError("external_yaml_refused")
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
        try:
            reject_unknown_fields(value)
            return ArenaEnvGraphSpec.from_dict(value)
        except (AssertionError, TypeError) as exc:
            raise ValueError("invalid_candidate") from exc

    def execute(self, intent, candidate, original, contract):
        """Consume only a released intent once; the store remains lifecycle authority."""
        criteria = self.admit(contract)
        if (
            intent.status != "released"
            or intent.released_at is None
            or intent.candidate_id != candidate.candidate_id
            or intent.intent_id in self._executed
            or candidate.original_id != original.candidate_id
        ):
            raise ValueError("exact fresh released scene intent required")
        self.require_bounded_capability(getattr(self, "principal", None), contract, intent.reservation)
        if intent.reservation != getattr(self.profile, intent.action):
            raise ValueError("action reservation mismatch")
        self._executed.add(intent.intent_id)  # includes failed/uncertain callbacks, never refunded
        self.check_active()
        if intent.action == "repair":
            observation = self._latest.get(candidate.candidate_id)
            if observation is None:
                raise ValueError("retained parent feedback required")
            checked = self.verify_observation(observation, contract, candidate)
            decision = assess_and_route(contract, candidate, checked)
            if decision.action != "repair":
                raise ValueError("retained assessment does not permit repair")
            feedback = decision.model_dump(mode="json") | {"observation": checked.model_dump(mode="json")}
            from .repairs import repair_permission_envelope

            feedback["repair_permissions"] = repair_permission_envelope(
                contract, original, candidate, effective_subjects=self.direct_root_subjects
            )
            scientific = None
            if contract.schema_version == "5":
                from .scene_eligibility import bound_action_selection, validate_selected_effect

                scientific = bound_action_selection(contract, candidate, checked)
                validate_selected_effect(contract, candidate, "repair", intent.action_selection)
                if intent.action_selection != scientific.model_dump(mode="json") or scientific.hypothesis is None:
                    raise ValueError("Retained refiner selection changed")
                feedback = {
                    "codec": "root-xy-feedback-v1",
                    "selection_digest": scientific.digest(),
                    "contract_digest": scientific.contract_digest,
                    "policy_digest": scientific.policy_digest,
                    "parent_candidate_id": candidate.candidate_id,
                    "parent_scene_digest": candidate.digest,
                    "original_scene_digest": original.digest,
                    "proposed_scene_digest": scientific.proposed_scene_digest,
                    "hypothesis": scientific.hypothesis.model_dump(mode="json"),
                }
            proposed = self._refine(
                parent=candidate,
                original=original,
                feedback=feedback,
                contract=contract,
                allowance=self.ceiling_for("repair").allowance(now=time.monotonic()),
            )
            self.check_active()
            from .scene_evidence_artifacts import _protected

            # Screen untrusted returned candidates before the service can persist
            # them, including schema-invalid or subsequently rejected proposals.
            proposed = json.loads(_protected(proposed, self.protect))
            if scientific is not None:
                from .scene_eligibility import validate_action_proposal
                from .scene_loop import repaired_candidate

                _, source, answer = self._retained[checked.cohort.realization_id]
                premise = self.artifacts.load_receipt(
                    source.candidate,
                    source.cohort,
                    kind="diagnostic",
                    manifest_digest=scientific.hypothesis.diagnostic_manifest_digest,
                    assessment_id=scientific.hypothesis.diagnostic_assessment_id,
                    protect=self.protect,
                )
                validate_action_proposal(
                    contract,
                    original,
                    candidate,
                    self.artifacts,
                    source,
                    scientific,
                    proposed,
                    visual_answer=answer,
                    diagnostic=premise,
                    protect=self.protect,
                )
                child = repaired_candidate(contract, original, candidate, proposed, source_id=intent.intent_id)
                self._restored_decisions[child.candidate_id] = scientific
            return proposed
        return self._observe(intent, candidate, contract, criteria)

    def _observe(self, intent, candidate, contract, criteria):
        from isaaclab_arena.agentic_environment_generation.trajectory_capture import capture_trajectory

        tag = identity(intent.intent_id, candidate.candidate_id)
        cohort = EvidenceCohort(
            realization_id=tag,
            reset_id=identity(tag, "reset"),
            environment_id="synthetic-env0",
            window_id=identity(tag, "window"),
            frame_id="world",
            contract_digest=contract_digest(contract),
            profile_digest=profile_digest(contract),
        )
        binding = CandidateBinding(
            candidate_digest=candidate.digest,
            contract_digest=cohort.contract_digest,
            profile_digest=cohort.profile_digest,
        )
        visual = next((c for c in criteria if c.kind == "visual"), None)
        cameras = list(visual.coordinate_frames) if visual else []
        deadline = time.monotonic() + self.capture_timeout_seconds
        with self._capture(candidate=candidate, contract=contract, cohort=cohort) as runtime:
            recorder = ObservationRecorder(runtime.sample_state, provenance="synthetic")

            def sample(env, step):
                self.check_active()
                if time.monotonic() >= deadline:
                    raise ValueError("capture deadline exhausted")
                recorder(env, step)

            captured = capture_trajectory(
                runtime.env,
                runtime.policy,
                out_dir=self.output_root / tag,
                num_steps=self.capture_steps,
                frame_interval=1,
                camera_names=cameras,
                save_frame=runtime.save_frame,
                sample_state=sample,
            )
            for step in range(self.capture_steps + 1):
                for camera in cameras:
                    path = captured["frames"].get(f"step_{step:06d}_{camera}")
                    if path is not None:
                        with Path(path).open("rb") as stream:
                            raw = stream.read(128 * 1024 + 1)
                        recorder.add_frame(camera=camera, step=step, subject_ids=visual.subjects, image_bytes=raw)
        self.check_active()
        payload = recorder.payload() | {"diagnostics": {k: v for k, v in captured.items() if k != "frames"}}
        observation = self.artifacts.write(binding, cohort, payload, protect=self.protect)
        answer = None
        if visual:
            request = visual_request(visual, binding, cohort, self.artifacts, observation, protect=self.protect)
            raw = self._visual(
                request=request,
                frames=payload["frames"],
                allowance=self.ceiling_for("observe").allowance(now=time.monotonic()),
            )
            answer = retain_visual_answer(
                visual, binding, cohort, self.artifacts, observation, raw, protect=self.protect
            )
        self._retained[tag] = (candidate, observation, answer)
        self.check_active()
        output = self._evaluate(tag, contract, candidate)
        self._latest[candidate.candidate_id] = output
        return output

    def _evaluate(self, tag, contract, candidate, *, include_visual=True):
        retained_candidate, receipt, answer = self._retained[tag]
        if retained_candidate != candidate or receipt.candidate != CandidateBinding(
            candidate_digest=candidate.digest,
            contract_digest=contract_digest(contract),
            profile_digest=profile_digest(contract),
        ):
            raise ValueError("stale or cross-candidate evidence")
        evidence, digests = [], []
        diagnostic_references = []
        failure = None
        # Corrupt manifests are verification failures, not malformed model answers.
        payload = self.artifacts.verified_payload(receipt, protect=self.protect)
        answer_payload = self.artifacts.verified_payload(answer, protect=self.protect) if answer is not None else None
        input_ancestry = {}
        if contract.schema_version == "5":
            # Data-only decoding does not admit any of this legacy executor's effects.
            project_required_criteria(contract)
            if payload.get("codec") != "observation-v2" or payload["acquisition"][
                "plan"
            ] != contract.acquisition.model_dump(mode="json"):
                raise ValueError("retained configurable acquisition selection mismatch")
            input_ancestry = dict(
                codec="scene-observation-v2",
                source_manifest_digest=receipt.manifest_digest,
                answer_manifest_digest=None,
                answer_assessment_id=None,
            )
            digests.append(receipt.manifest_digest)
            if answer_payload is not None:
                if (
                    answer_payload.get("codec") != "full-scene-answer-v1"
                    or answer_payload.get("source_manifest_digest") != receipt.manifest_digest
                ):
                    raise ValueError("exact versioned retained answer ancestry required")
                input_ancestry.update(
                    answer_manifest_digest=answer.manifest_digest,
                    answer_assessment_id=answer_payload["assessment_id"],
                )
                digests.append(answer.manifest_digest)
            criteria = tuple(admit_criterion(c) for c in contract.criteria)
        else:
            criteria = self.admit(contract)
        for criterion in criteria:
            if criterion.kind == "visual":
                if not include_visual:
                    continue
                try:
                    value = evaluate_visual_answer(
                        criterion,
                        receipt.candidate,
                        receipt.cohort,
                        self.artifacts,
                        receipt,
                        answer,
                        protect=self.protect,
                    )
                except (ValueError, KeyError, TypeError, AttributeError):
                    failure = "invalid_visual_answer"
                    continue
            else:
                value = evaluate_measurement(
                    criterion, receipt.candidate, receipt.cohort, self.artifacts, receipt, protect=self.protect
                )
            evidence.append(value)
            digests.append(value.manifest_digest)  # evaluator has verified the actual bytes above
        if candidate.parent_id:
            previous = self._latest.get(candidate.parent_id)
            if previous is None:
                raise ValueError("retained before-cohort required")
            parent, before, parent_answer = self._retained[previous.cohort.realization_id]
            hypothesis = None
            sample_step, tolerance = self.capture_window()[0], self.displacement_tolerance_m
            if contract.schema_version == "5":
                from .scene_eligibility import validate_action_proposal

                decision = self._restored_decisions.get(candidate.candidate_id)
                if decision is None or decision.hypothesis is None or candidate.original_id not in self._latest:
                    raise ValueError("exact retained eligibility decision and original ancestry required")
                hypothesis = decision.hypothesis
                original = self._retained[self._latest[candidate.original_id].cohort.realization_id][0]
                premise = self.artifacts.load_receipt(
                    before.candidate,
                    before.cohort,
                    kind="diagnostic",
                    assessment_id=hypothesis.diagnostic_assessment_id,
                    manifest_digest=hypothesis.diagnostic_manifest_digest,
                    protect=self.protect,
                )
                validate_action_proposal(
                    contract,
                    original,
                    parent,
                    self.artifacts,
                    before,
                    decision,
                    json.loads(candidate.scene_json),
                    visual_answer=parent_answer,
                    diagnostic=premise,
                    protect=self.protect,
                )
                sample_step, tolerance = hypothesis.step, hypothesis.displacement_tolerance_m
            new = json.loads(candidate.scene_json)
            subject = contract.allowed_interventions[0].subject_id
            relations = [r for r in new["relations"] if r["kind"] == "at_position" and r["subject"] == subject]
            if len(relations) != 1 or (contract.schema_version != "5" and subject not in self.direct_root_subjects):
                raise ValueError("explicit direct root origin mapping required")
            params = relations[0]["params"]
            before_payload = self.artifacts.verified_payload(before, protect=self.protect)
            initial = (
                next(s for s in before_payload["samples"] if s["step"] == sample_step)
                if contract.schema_version == "5"
                else before_payload["samples"][0]
            )
            z = params.get("z", initial["subjects"][subject]["position_w"][2] - initial["origin_w"][2])
            result = effective_displacement(
                self.artifacts,
                before,
                receipt,
                subject=subject,
                step=sample_step,
                target_local=[params["x"], params["y"], z],
                mapping="direct-root-translation-v1",
                tolerance_m=tolerance,
                protect=self.protect,
                hypothesis=hypothesis,
            )
            diagnostic_cohort = receipt.cohort.model_copy(update={"window_id": identity(tag, "displacement")})
            diagnostic = self.artifacts.write(
                receipt.candidate,
                diagnostic_cohort,
                {
                    "kind": "observation",
                    "provenance": self.artifacts.verified_payload(receipt, protect=self.protect).get("provenance"),
                    "diagnostics": result,
                },
                protect=self.protect,
            )
            self.artifacts.verified_payload(diagnostic, protect=self.protect)
            if contract.schema_version == "5" and getattr(self.profile, "workflow_schema", None) == "5":
                digests.append(diagnostic.manifest_digest)
                diagnostic_references.append(
                    dict(
                        kind="observation",
                        cohort=diagnostic.cohort.model_dump(mode="json"),
                        manifest_digest=diagnostic.manifest_digest,
                        assessment_id=None,
                    )
                )
            if not result["effective"]:
                failure = "ineffective_edit"
        action_selection = None
        if (
            contract.schema_version == "5"
            and getattr(self.profile, "workflow_schema", None) == "5"
            and include_visual
            and failure is None
        ):
            from .scene_eligibility import evaluate_action_eligibility, retain_root_xy_diagnostic

            original = candidate
            if candidate.parent_id is not None:
                original = self._retained[self._latest[candidate.original_id].cohort.realization_id][0]
            diagnostic = None
            payload = self.artifacts.verified_payload(receipt, protect=self.protect)
            if payload.get("diagnostics", {}).get("root_xy_mapping") is not None:
                diagnostic = retain_root_xy_diagnostic(
                    contract, original, candidate, self.artifacts, receipt, protect=self.protect
                )
                digests.append(diagnostic.manifest_digest)
                diagnostic_references.append(
                    dict(
                        kind="diagnostic",
                        cohort=diagnostic.cohort.model_dump(mode="json"),
                        manifest_digest=diagnostic.manifest_digest,
                        assessment_id=self.artifacts.verified_payload(diagnostic, protect=self.protect)[
                            "assessment_id"
                        ],
                    )
                )
            selected = evaluate_action_eligibility(
                contract,
                original,
                candidate,
                self.artifacts,
                receipt,
                visual_answer=answer,
                diagnostic=diagnostic,
                protect=self.protect,
            )
            action_selection = selected.model_dump(mode="json")
        return Observation.model_validate(
            dict(
                cohort=receipt.cohort,
                evidence=tuple(evidence),
                verified_manifest_digests=tuple(dict.fromkeys(digests)),
                static_failure=failure,
                **({"action_selection": action_selection} if action_selection is not None else {}),
                **({"diagnostic_references": tuple(diagnostic_references)} if diagnostic_references else {}),
                **input_ancestry,
            )
        )

    def restore_observations(self, records, contract, *, decisions=None):
        """Rebuild feedback from exact durable identities and verified artifact bytes."""
        from .scene_loop import CandidateRecord

        if decisions is not None:
            from .scene_eligibility import SceneActionDecision
            from .scene_evidence_artifacts import canonical

            if contract.schema_version != "5" or type(decisions) is not dict:
                raise ValueError("versioned retained decisions require configurable readback")
            self._restored_decisions = {
                key: SceneActionDecision.model_validate_json(canonical(value.model_dump(mode="json")))
                for key, value in decisions.items()
            }
        records = self._selected_restore_rows(records)
        pending = [
            (CandidateRecord.model_validate_json(row["candidate"]), Observation.model_validate_json(row["payload"]))
            for row in records
        ]
        while pending:
            progress = False
            for candidate, output in tuple(pending):
                if candidate.parent_id and candidate.parent_id not in self._latest:
                    continue
                binding = CandidateBinding(
                    candidate_digest=candidate.digest,
                    contract_digest=contract_digest(contract),
                    profile_digest=profile_digest(contract),
                )
                visual_ids = {c.criterion_id for c in contract.criteria if c.kind == "visual"}
                measured = {e.manifest_digest for e in output.evidence if e.criterion_id not in visual_ids}
                visual = {e.manifest_digest for e in output.evidence if e.criterion_id in visual_ids}
                answer = None
                if contract.schema_version == "5":
                    if output.codec != "scene-observation-v2":
                        raise ValueError("exact versioned observation input ancestry required")
                    selections = {e.assessment_id for e in output.evidence if e.criterion_id in visual_ids}
                    if (
                        not measured <= {output.source_manifest_digest}
                        or not visual <= {output.answer_manifest_digest}
                        or not selections <= {output.answer_assessment_id}
                    ):
                        raise ValueError("truth evidence and retained input ancestry differ")
                    measured = {output.source_manifest_digest}
                    visual = set() if output.answer_manifest_digest is None else {output.answer_manifest_digest}
                    if visual:
                        answer = self.artifacts.load_receipt(
                            binding,
                            output.cohort,
                            kind="visual-answer",
                            manifest_digest=output.answer_manifest_digest,
                            assessment_id=output.answer_assessment_id,
                            protect=self.protect,
                        )
                elif output.codec != "scene-observation-v1":
                    raise ValueError("legacy readback refuses versioned observation metadata")
                if len(measured) != 1 or len(visual) > 1:
                    raise ValueError("Exact retained producer manifests required")
                receipt = self.artifacts.load_receipt(
                    binding,
                    output.cohort,
                    kind="observation",
                    manifest_digest=next(iter(measured)),
                    protect=self.protect,
                )
                if visual and answer is None:
                    answer = self.artifacts.load_receipt(
                        binding,
                        output.cohort,
                        kind="visual-answer",
                        manifest_digest=next(iter(visual)),
                        protect=self.protect,
                    )
                tag = output.cohort.realization_id
                self._retained[tag] = (candidate, receipt, answer)
                try:
                    checked = self.verify_observation(output, contract, candidate)
                except BaseException:
                    self._retained.pop(tag, None)
                    raise
                self._latest[candidate.candidate_id] = checked
                pending.remove((candidate, output))
                progress = True
            if not progress:
                raise ValueError("Missing retained parent observation")

    @staticmethod
    def _selected_restore_rows(records):
        """Select the current cohort and its repair ancestors, never opaque-ID order."""
        from .scene_loop import CandidateRecord

        if not isinstance(records, dict):
            candidates = [row["candidate_id"] for row in records]
            if len(candidates) != len(set(candidates)):
                raise ValueError("Explicit retained evidence selection required")
            return records
        rows = {row["evidence_id"]: row for row in records["evidence"]}
        if len(rows) != len(records["evidence"]):
            raise ValueError("Conflicting retained evidence selection")
        selections = records["evidence_selections"]
        selected, visited = [], set()

        def row_for(candidate_id, evidence_id):
            row = rows.get(evidence_id)
            if row is None or row["candidate_id"] != candidate_id:
                raise ValueError("Missing exact retained evidence selection")
            candidate = CandidateRecord.model_validate_json(row["candidate"])
            if (
                candidate.candidate_id != candidate_id
                or hashlib.sha256(candidate.scene_json.encode()).hexdigest() != candidate.digest
            ):
                raise ValueError("Retained selection candidate bytes changed")
            return row, candidate

        def visit(candidate, evidence_id):
            if candidate.candidate_id in visited:
                raise ValueError("Cyclic retained evidence selection")
            visited.add(candidate.candidate_id)
            if candidate.parent_id:
                linked = {
                    link["evidence_id"]
                    for link in selections
                    if link["candidate_id"] == candidate.parent_id and link["intent_id"] == candidate.source_id
                }
                if not linked:
                    # Legacy rows are unambiguous only with one parent cohort.
                    linked = {key for key, row in rows.items() if row["candidate_id"] == candidate.parent_id}
                if len(linked) != 1:
                    raise ValueError("Exact repair-parent evidence selection required")
                parent_id = next(iter(linked))
                _, parent = row_for(candidate.parent_id, parent_id)
                visit(parent, parent_id)
            if evidence_id is not None:
                row, retained = row_for(candidate.candidate_id, evidence_id)
                if retained != candidate:
                    raise ValueError("Retained selection candidate mismatch")
                selected.append(row)

        scene = records["scene"]
        if scene is None:
            raise ValueError("Scene evidence selection unavailable")
        visit(scene.candidate, records["selected_evidence_id"])
        return selected

    def verify_observation(self, output, contract, candidate):
        """Recompute ALL criterion findings from exact bytes; reject supplied digest lists."""
        self.check_active()
        if not isinstance(output, Observation) or output.cohort.realization_id not in self._retained:
            raise ValueError("unknown retained observation")
        self.verify_diagnostic_references(output, candidate)
        verified = self._evaluate(output.cohort.realization_id, contract, candidate)
        if verified != output:
            raise ValueError("observation differs from retained producer evaluation")
        return verified

    def verify_diagnostic_references(self, output, candidate):
        from .evidence import EvidenceCohort

        for reference in output.diagnostic_references:
            cohort = EvidenceCohort.model_validate_json(json.dumps(reference["cohort"]))
            if reference["manifest_digest"] not in output.verified_manifest_digests:
                raise ValueError("Unverified diagnostic reference")
            binding = CandidateBinding(
                candidate_digest=candidate.digest,
                contract_digest=cohort.contract_digest,
                profile_digest=cohort.profile_digest,
            )
            self.artifacts.load_receipt(
                binding,
                cohort,
                kind=reference["kind"],
                manifest_digest=reference["manifest_digest"],
                assessment_id=reference["assessment_id"],
                protect=self.protect,
            )
