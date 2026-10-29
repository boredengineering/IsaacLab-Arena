# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Application-owned MODEL TOOL adapters; no authority, routing or physical claims.

Use only in an isolated worker: bounded_client patches a process-global SDK factory.
The caller supplies approved literal role bindings and trusted total-call accounting.
"""

import copy
import math
from dataclasses import dataclass

from ..inference_profiles import checked_inference_profile
from .inference_transport import CallAllowance, bounded_client, checked_workflow_accounting
from .request_envelope import RequestBounds, RequestEnvelope


@dataclass(frozen=True)
class SceneProposal:
    spec: object
    warnings: tuple[str, ...]
    traces: tuple[str, ...]
    publication: str = "not_published"


@dataclass(frozen=True)
class _RawSceneSpec:
    value: dict

    def model_dump(self, *, mode="json"):
        return copy.deepcopy(self.value)


class BoundedSceneModels:
    """Share one allowance across constructor pings, generation, refinement and vision.

    Approved roles are caller-authorized {role: {model, endpoint}} bindings, not grants.
    No prices are inferred. One instance serves one exact model/endpoint attestation.
    request_envelopes optionally supplies every approved role's frozen RequestEnvelope;
    refinement retains the existing generation role. An installed config's request_bounds
    supplies the exact registered envelope. Absent bounds preserve legacy callable use.
    """

    def __init__(self, *, config, approved_roles, allowance, request_envelopes=None, send_guard=None):
        required = {
            "api_key",
            "model",
            "base_url",
            "inference_profile",
            "workflow_accounting",
        }
        if type(config) is not dict or set(config) not in (required, required | {"request_bounds"}):
            raise ValueError("complete explicit model configuration required")
        if any(type(config[k]) is not str or not config[k] for k in ("api_key", "model", "base_url")):
            raise ValueError("explicit provider configuration required")
        checked_inference_profile(
            config["inference_profile"],
            model=config["model"],
            base_url=config["base_url"],
        )
        accounting = checked_workflow_accounting(
            config["workflow_accounting"],
            model=config["model"],
            endpoint=config["base_url"],
        )
        if (
            not isinstance(allowance, CallAllowance)
            or not (allowance.token_cost_bounded or allowance.accounting_only)
            or not math.isfinite(allowance.deadline)
            or allowance._bound != accounting
        ):
            raise ValueError("matching shared token/cost allowance required")
        if (
            type(approved_roles) is not dict
            or not approved_roles
            or not set(approved_roles) <= {"generation", "assessment"}
            or any(v != {"model": config["model"], "endpoint": config["base_url"]} for v in approved_roles.values())
        ):
            raise ValueError("approved role binding mismatch")
        self._config = copy.deepcopy(config)
        self._roles = frozenset(approved_roles)
        self.allowance = allowance
        self._send_guard = send_guard
        if "request_bounds" in config:
            if not callable(send_guard):
                raise ValueError("Installed model send authority required")
            envelope = RequestBounds.model_validate(config["request_bounds"]).bind(
                model=config["model"],
                endpoint=config["base_url"],
                accounting=accounting,
                inference_policy=config["inference_profile"],
            )
            installed = {role: envelope for role in approved_roles}
            if request_envelopes is not None and request_envelopes != installed:
                raise ValueError("Installed request envelope cannot be overridden")
            request_envelopes = installed
        self._envelopes = None if request_envelopes is None else dict(request_envelopes)
        if self._envelopes is not None:
            if set(self._envelopes) != self._roles:
                raise ValueError("request envelope roles mismatch")
            for envelope in self._envelopes.values():
                if type(envelope) is not RequestEnvelope:
                    raise ValueError("frozen request envelope required")
                envelope.check_binding(
                    model=config["model"],
                    endpoint=config["base_url"],
                    accounting=accounting,
                )

    def _config_for(self, role) -> dict:
        if role not in self._roles:
            raise ValueError("model role not approved")
        return (
            {k: v for k, v in self._config.items() if k not in {"workflow_accounting", "request_bounds"}}
            | {
                "load_dotenv": False,
                "max_tokens": (
                    self._envelopes[role].max_output_tokens
                    if self._envelopes is not None
                    else min(4096, self._config["workflow_accounting"]["max_tokens"])
                ),
                "max_retries": 0,
            }
            | ({"probe_connection": False} if self.allowance.accounting_only else {})
        )

    def _client(self, role):
        return bounded_client(
            self._config,
            allowance=self.allowance,
            request_envelope=None if self._envelopes is None else self._envelopes[role],
            send_guard=self._send_guard,
        )

    @staticmethod
    def _catalogues(asset_catalog, relation_catalog, task_catalog):
        if any(v is None for v in (asset_catalog, relation_catalog, task_catalog)):
            raise ValueError("explicit catalogues required")
        return dict(
            asset_catalog=asset_catalog,
            relation_catalog=relation_catalog,
            task_catalog=task_catalog,
        )

    @staticmethod
    def _proposal(spec, agent, *, protect):
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

        from .scene_evidence_artifacts import _protected

        if spec is None:
            raise ValueError("invalid model proposal")
        # Actual domain schema, without Documents discovery or file includes.
        checked = ArenaEnvGraphSpec.model_validate(spec.model_dump(mode="json"))
        proposal = SceneProposal(
            checked,
            ("Schema only; no grounding, physical validation or policy success established.",),
            tuple(agent.traces),
        )
        _protected(
            {
                "spec": checked.model_dump(mode="json"),
                "warnings": list(proposal.warnings),
                "traces": list(proposal.traces),
                "publication": proposal.publication,
            },
            protect,
        )
        return proposal

    def generate(
        self,
        *,
        prompt,
        contract_digest,
        run_id,
        priors,
        prior,
        require_prior,
        protect,
        asset_catalog,
        relation_catalog,
        task_catalog,
    ):
        """Consume exactly the retained snapshot after readback and before any SDK call."""
        config = self._config_for("generation")
        catalogues = self._catalogues(asset_catalog, relation_catalog, task_catalog)
        if type(require_prior) is not bool:
            raise ValueError("explicit prior requirement required")
        snapshot = priors.verified_snapshot(
            prior,
            prompt=prompt,
            contract_digest=contract_digest,
            run_id=run_id,
            protect=protect,
        )
        if require_prior and snapshot["status"] in {"unavailable", "not_requested"}:
            raise ValueError("required prior unavailable")
        from ..environment_generation_agent import EnvironmentGenerationAgent

        with self._client("generation"):
            agent = EnvironmentGenerationAgent(**config)
            spec, _ = agent.generate_spec(
                prompt,
                **catalogues,
                publish_to_graph=False,
                proposal_only=True,
                prior_context=snapshot["exact_context"],
            )
            return self._proposal(spec, agent, protect=protect)

    def refine(
        self,
        *,
        base_spec,
        feedback,
        protect,
        asset_catalog,
        relation_catalog,
        task_catalog,
        raw_scene=None,
    ):
        """Propose against the exact base and caller-verified retained structured feedback.

        The caller must obtain feedback from durable decision/evidence readback (ScenePorts
        does so); this tool does not invent evidence, reretrieve priors or accept repairs.
        """
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

        from ..environment_generation_agent import EnvironmentGenerationAgent
        from .scene_evidence_artifacts import _protected

        config = self._config_for("generation")
        catalogues = self._catalogues(asset_catalog, relation_catalog, task_catalog)
        if type(feedback) is not dict or not feedback:
            raise ValueError("structured retained feedback required")
        if feedback.get("codec") == "root-xy-feedback-v1":
            import hashlib

            from ..inference_backend import InferenceBackend, StructuredOutputRequest
            from ..spec_wire_adapter import _parse_value
            from .scene_eligibility import RootXYHypothesis
            from .scene_evidence_artifacts import canonical
            from .scene_ports import ScenePorts

            keys = {
                "codec",
                "selection_digest",
                "contract_digest",
                "policy_digest",
                "parent_candidate_id",
                "parent_scene_digest",
                "original_scene_digest",
                "proposed_scene_digest",
                "hypothesis",
            }
            if set(feedback) != keys or type(raw_scene) is not dict:
                raise ValueError("Exact declared feedback projection required")
            RootXYHypothesis.model_validate_json(canonical(feedback["hypothesis"]))
            if hashlib.sha256(canonical(raw_scene)).hexdigest() != feedback["parent_scene_digest"]:
                raise ValueError("Refiner parent bytes changed")
            ScenePorts.validate_candidate(raw_scene)
            request = StructuredOutputRequest(
                schema_name="BoundRootXYRepair",
                schema={
                    "type": "object",
                    "properties": {"scene_json": {"type": "string", "maxLength": 262144}},
                    "required": ["scene_json"],
                    "additionalProperties": False,
                },
                system=(
                    "Return the exact parent JSON with only the declared root-XY correction. Preserve all other values"
                    " and numeric representations. A prediction is not physical proof. No extra repairs or claims."
                ),
                user="Parent JSON:\n"
                + canonical(raw_scene).decode("utf-8")
                + "\nBound feedback:\n"
                + _protected(feedback, protect).decode("utf-8"),
                retry_label="bound-root-xy-repair",
                parse_json=_parse_value,
            )
            with self._client("generation"):
                response = InferenceBackend(**config).run_json(request)
            proposed = _parse_value(response["scene_json"])
            if (
                type(proposed) is not dict
                or hashlib.sha256(canonical(proposed)).hexdigest() != feedback["proposed_scene_digest"]
            ):
                raise ValueError("Returned proposal differs from selected hypothesis")
            _protected(proposed, protect)
            ScenePorts.validate_candidate(proposed)
            return SceneProposal(_RawSceneSpec(proposed), (), ())
        checked = ArenaEnvGraphSpec.model_validate(base_spec.model_dump(mode="json"))
        encoded = _protected(feedback, protect).decode("utf-8")
        with self._client("generation"):
            agent = EnvironmentGenerationAgent(**config)
            spec, _ = agent.refine_spec(
                checked,
                encoded,
                **catalogues,
                publish_to_graph=False,
                proposal_only=True,
            )
            return self._proposal(spec, agent, protect=protect)

    def assess(self, *, criterion, candidate, cohort, artifacts, observation, protect):
        """Return the backend's raw answer to an exact retained per-frame request, not success."""
        import base64
        import hashlib

        from ..inference_backend import InferenceBackend
        from .scene_evidence_artifacts import canonical
        from .scene_observation import visual_request

        config = self._config_for("assessment")
        request = visual_request(criterion, candidate, cohort, artifacts, observation, protect=protect)
        payload = artifacts.verified_payload(observation, protect=protect)
        images = {}
        for index, (frame, identity) in enumerate(zip(payload["frames"], request["frames"])):
            raw = base64.b64decode(frame["bytes"], validate=True)
            if hashlib.sha256(raw).hexdigest() != identity["sha256"]:
                raise ValueError("retained image changed")
            images[str(index)] = raw
        prompt = (
            "Assess only the exact criterion below against each attached image, in frame order. "
            "Return a JSON object containing every request field unchanged plus answers: "
            "one {frame_digest: the frame sha256, visible: boolean} per frame. "
            "Do not claim aggregate success, physics, support or policy performance. Request:\n"
            + canonical(request).decode("utf-8")
        )
        if criterion.evaluator_version == "visibility-v2":
            prompt = (
                "Assess visibility only, using each attached image in the exact frame order below. Use the grounded"
                " descriptions in the rubric; subject names, identifiers and tags are NOT visual proof. Return ONLY a"
                " JSON object with request_sha256 copied exactly and answers in frame order. Each answer has camera,"
                " frame_digest (the frame sha256), and subjects in the listed subject order. Each subject answer has"
                " subject, verdict (visible, not_visible, or uncertain), and a short visual reason. Use uncertain if"
                " identity or visibility cannot be determined; never infer visibility from metadata. Do not assess"
                " physics, task success or calibration. Request:\n"
                + canonical(request).decode("utf-8")
            )
        elif criterion.evaluator_version == "full-scene-ternary-v1":
            prompt = (
                "Assess only RGB visibility; metadata and names are not visual proof. Return one JSON object "
                "with codec full-scene-ternary-v1, the exact request_sha256, and answers in frame order. "
                "Each answer copies observation_id, camera, step, clock, time_seconds and modality, adds "
                "frame_digest (sha256), and subjects in requested order. Each subject has subject, truth "
                "(true/false/unknown as strings), confidence (null), conflict (boolean), and visual reason. "
                "Use unknown when identity or visibility is indeterminate. Do not infer physics, contact, "
                "goal satisfaction or calibration. Request:\n"
                + canonical(request).decode("utf-8")
            )
        with self._client("assessment"):
            backend = InferenceBackend(**config)
            return backend.multimodal_chat(prompt, images)
