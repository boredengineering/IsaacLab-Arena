# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Assessment-only consumers of immutable native evidence through existing scene ports."""

import hashlib
import json
import time

from .contracts import contract_digest, parse_contract
from .evidence import CandidateBinding
from .scene_evidence_artifacts import _protected
from .scene_loop import Observation, identity, profile_digest
from .scene_observation import admit_criterion, validate_visibility_response, visual_request
from .scene_ports import ScenePorts


def load_retained_source(store, artifacts, contract, *, protect):
    """Reopen the original producer bytes without adopting or rewriting its cohort."""
    assert contract.schema_version == "4" and contract.source.kind == "existing", "Retained consumer required"
    source = contract.retained_evidence
    assert source is not None, "Explicit producer links required"
    records = store.result_records(source.run_id)
    producer, scene = records["run"], records["scene"]
    original = parse_contract(producer.contract_json)
    if (
        producer.operation_id != source.operation_id
        or original.schema_version != "3"
        or original.source.kind != "existing"
        or original.source.content != contract.source.content
        or contract_digest(original) != source.contract_digest
        or profile_digest(original) != source.profile_digest
        or scene is None
        or scene.candidate.digest != source.candidate_digest
        or hashlib.sha256(contract.source.content.encode()).hexdigest() != source.candidate_sha256
    ):
        raise ValueError("Retained producer identity differs")
    rows = [row for row in records["evidence"] if row["evidence_id"] == records["selected_evidence_id"]]
    if len(rows) != 1 or rows[0]["candidate_id"] != scene.candidate.candidate_id:
        raise ValueError("Exact selected producer evidence required")
    observation = Observation.model_validate_json(rows[0]["payload"])
    if observation.verified_manifest_digests != (source.observation_manifest_digest,):
        raise ValueError("Retained native manifest differs")
    binding = CandidateBinding(
        candidate_digest=source.candidate_digest,
        contract_digest=source.contract_digest,
        profile_digest=source.profile_digest,
    )
    receipt = artifacts.load_receipt(
        binding,
        observation.cohort,
        kind="observation",
        manifest_digest=source.observation_manifest_digest,
        protect=protect,
    )
    with artifacts.area.writer_lock():
        raw = artifacts.area.verify(receipt.relative_directory, json.loads(receipt.manifest_json))["evidence.json"]
    if hashlib.sha256(raw).hexdigest() != source.evidence_sha256:
        raise ValueError("Original evidence bytes differ")
    payload = artifacts.verified_payload(receipt, protect=protect)
    if tuple(frame["sha256"] for frame in payload["frames"]) != source.frame_sha256:
        raise ValueError("Original PNG order or identity differs")
    request = visual_request(contract.criteria[0], binding, observation.cohort, artifacts, receipt, protect=protect)
    return rows[0]["evidence_id"], observation, receipt, request, raw


class RetainedAssessmentPorts(ScenePorts):
    """Reuse owned scene stages with no capture, repair, generation or policy adapter."""

    def __init__(self, *, source_store, expected_request_sha256, **options):
        self.source_store = source_store
        self.expected_request_sha256 = expected_request_sha256
        super().__init__(**options)

    def admit(self, contract):
        assert contract.schema_version == "4", "Assessment-only contract required"
        if self.profile.assurance != "retained-evidence" or set(self.model_ceilings) != {"assessment"}:
            raise ValueError("Assessment-only ports required")
        criteria = tuple(admit_criterion(c) for c in contract.criteria)
        load_retained_source(self.source_store, self.artifacts, contract, protect=self.protect)
        return criteria

    def ceiling_for(self, action):
        assert action == "assess", "Only retained assessment is supported"
        return self.model_ceilings["assessment"]

    def require_bounded_capability(self, principal, contract, reservation):
        self.admit(contract)
        ceiling = self.ceiling_for("assess")
        if (
            reservation != self.profile.assess
            or reservation.model_calls != 1
            or reservation.accounting_policy != "accounting-only-v1"
            or ceiling.max_calls != 1
            or ceiling.max_tokens is not None
            or ceiling.max_cost_usd is not None
            or ceiling.per_call_bound["version"] != 2
            or not 0 < ceiling.timeout_seconds <= 180
            or ceiling.timeout_seconds + 10 > reservation.runtime_allowance_seconds
            or self.expected_request_sha256 is None
        ):
            raise ValueError("Frozen single-attempt assessment capability required")
        return True

    def wait_retained_retry(self, run_id, contract):
        """Honor retained retry timing before preparing another owned worker."""
        records = self.source_store.result_records(run_id)
        not_before = 0
        for row in records["intents"]:
            if row["result"] is None:
                if row["assessment_send"] is not None:
                    raise ValueError("Dispatched assessment must be reconciled before retry")
                continue
            outcome = json.loads(json.loads(row["result"])["retained_assessment_json"])
            if outcome["complete"] or not outcome["retryable"]:
                raise ValueError("Retained assessment forbids another dispatch")
            not_before = max(not_before, outcome["retry_not_before_unix"])
        deadline = records["admitted_at"] + min(
            contract.budget.max_runtime_seconds, contract.budget.total_deadline_seconds
        )
        if max(time.time(), not_before) + self.profile.assess.runtime_allowance_seconds > deadline:
            raise ValueError("Retry delay and cleanup cannot fit the retained assessment deadline")
        while time.time() < not_before:
            self.check_active()
            time.sleep(min(0.25, max(0, not_before - time.time())))
        self.check_active()

    def execute(self, intent, candidate, original, contract, *, retained_observation):
        self.require_bounded_capability(getattr(self, "principal", None), contract, intent.reservation)
        evidence_id, observation, receipt, _, _ = load_retained_source(
            self.source_store, self.artifacts, contract, protect=self.protect
        )
        if (
            intent.action != "assess"
            or intent.status != "released"
            or intent.intent_id in self._executed
            or retained_observation != observation
            or intent.observation_id != evidence_id
            or intent.observation_digest != identity(observation.model_dump(mode="json"))
            or candidate != original
            or candidate.digest != receipt.candidate.candidate_digest
        ):
            raise ValueError("Exact fresh retained-assessment release required")
        self._executed.add(intent.intent_id)
        self.check_active()
        result = self._call_child(
            "assess",
            dict(
                candidate=receipt.candidate.model_dump(mode="json"),
                cohort=receipt.cohort.model_dump(mode="json"),
                criterion=contract.criteria[0].model_dump(mode="json"),
                observation_manifest_digest=receipt.manifest_digest,
                consumer_contract_digest=contract_digest(contract),
                producer_source=contract.retained_evidence.model_dump(mode="json"),
            ),
        )
        self.check_active()
        return result.receipt

    def verify_retained_assessment(self, output, contract, intent):
        from isaaclab_arena_examples.agentic_environment_generation.web_api.scene_worker import (
            read_retained,
            retained_response_candidates,
        )

        _, _, _, request, source_bytes = load_retained_source(
            self.source_store, self.artifacts, contract, protect=self.protect
        )
        value = read_retained(self.artifacts.area, output, protect=self.protect)
        binding = value["binding"]
        if (
            binding["registration"] != intent.worker_registration.model_dump(mode="json")
            or binding["contract_digest"] != contract_digest(contract)
            or binding["scene_action"] != "assess"
            or value["attempted_calls"] not in (0, 1)
        ):
            raise ValueError("Assessment output ownership differs")
        output_value = value["output"]
        records = output_value["provider_records"]
        if type(records) is not list or len(records) > 1:
            raise ValueError("Single provider attempt required")
        record = records[0] if records else None
        structured, validation_error, retryable = None, None, False
        raw, recovered_from = output_value["raw_response"], None
        if record is not None and record.get("serialized_request") is not None:
            if hashlib.sha256(record["serialized_request"].encode()).hexdigest() != self.expected_request_sha256:
                raise ValueError("Serialized request changed after preflight")
        if record and record["dispatched"]:
            for origin, text in retained_response_candidates(record, raw):
                try:
                    if type(text) is not str or not 1 <= len(text.encode()) <= 65536:
                        continue
                    structured = validate_visibility_response(text, request)
                except (ValueError, TypeError, KeyError):
                    continue
                raw, recovered_from = text, origin
                break
        if structured is not None:
            pass
        elif (record and record.get("retention_error") is not None) or (output_value.get("local_error") or {}).get(
            "diagnostic_retention_failed"
        ) is True:
            validation_error = "local_retention_failure"
        elif record and record["dispatched"] and record["transport_error"] is not None:
            validation_error = "transport_failure"
            retryable = record["transport_error"]["retryable"] is True
        elif (
            record
            and record["dispatched"]
            and (record["response"] is not None or record.get("http_response") is not None)
        ):
            validation_error, retryable = "response_json_schema_or_coverage", True
        else:
            validation_error = "local_refusal_no_verified_dispatch"
        not_before = None
        if retryable:
            not_before = time.time() + 1
            http = record.get("http_response")
            if http is not None and http.get("retry_after") is not None:
                if http.get("retry_not_before_unix") is None:
                    validation_error, retryable = "invalid_retry_after", False
                else:
                    not_before = max(not_before, http["retry_not_before_unix"])
            records_view = self.source_store.result_records(intent.worker_fence.run_id)
            deadline = records_view["admitted_at"] + min(
                contract.budget.max_runtime_seconds, contract.budget.total_deadline_seconds
            )
            if not_before + self.profile.assess.runtime_allowance_seconds > deadline:
                validation_error, retryable = "retry_delay_exceeds_deadline", False
        result = dict(
            schema_version=1,
            consumer_contract_digest=contract_digest(contract),
            producer=contract.retained_evidence.model_dump(mode="json"),
            producer_evidence_id=intent.observation_id,
            model_result=output,
            source_candidate_utf8=contract.source.content,
            source_evidence_utf8=source_bytes.decode(),
            request=request,
            request_sha256=self.expected_request_sha256,
            raw_response=raw,
            response_recovered_from=recovered_from,
            provider_records=records,
            local_error=output_value["local_error"],
            phase_receipts=output_value.get("phase_receipts", {}),
            complete=structured is not None,
            structured_result=structured,
            validation_error=validation_error,
            retryable=retryable,
            retry_not_before_unix=not_before,
            cost_usd=None,
            cost_basis="unknown_no_price_attestation",
            scene_acceptance="not_established",
            native_launches=0,
            retry_policy=dict(
                max_cumulative_sends=3, minimum_backoff_seconds=1, respect_retry_after=True, same_request=True
            ),
        )
        return _protected(result, self.protect).decode()
