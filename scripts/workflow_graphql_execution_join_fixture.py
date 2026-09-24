# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Fixed E1 input/capture ports only; no owner, grants, service or receipt mocks."""

import json
import os
import pwd
import time
from contextlib import contextmanager
from pathlib import Path

PAUSE = Path("/tmp/workflow-cli/e1-pause-generation")
PAUSE_BYTES = b"e1-owned-generation-barrier\n"
IDENTITY_FIELDS = ("pid", "parent_pid", "pgid", "sid", "boot", "pid_namespace", "start_ticks")
LIVE_IDENTITY_FIELDS = tuple(key for key in IDENTITY_FIELDS if key != "parent_pid")


def check_live_identity(expected, observed):
    """Reject PID reuse, foreign namespaces and dead /proc entries."""
    assert observed["state"] not in {"Z", "X", "x"} and all(
        type(observed[key]) is type(expected[key]) and observed[key] == expected[key] for key in LIVE_IDENTITY_FIELDS
    ), "live identity mismatch or dead process"


def check_detachment_proof(detached, release):
    """Pure retained checker; elapsed marker age is never a release witness."""
    assert detached["submit_reaped_before_release"] is True, "submit reap missing"
    check_live_identity(detached["worker_identity"], detached["worker_live"])
    check_live_identity(detached["server_identity"], detached["server_live"])
    assert detached["worker_identity"]["parent_pid"] == detached["server_identity"]["pid"], "worker parent"
    assert detached["worker_live"]["parent_pid"] == detached["server_identity"]["pid"], "worker parent"
    assert all(
        type(release["identity"][key]) is type(detached["worker_identity"][key])
        and release["identity"][key] == detached["worker_identity"][key] for key in IDENTITY_FIELDS
    ), "release identity mismatch"
    assert release["phase"] == "released" and release["outcome"] == "marker_removed", "explicit removal missing"
    assert release["calls"] == 2 and release["response_ready"] is True and release["response_returning"] is True, (
        "transport response release missing"
    )
    assert (
        release["waiting_at"] <= detached["observed_at"] <= detached["release_requested_at"]
        <= release["released_at"] < release["deadline"]
        and release["deadline"] == release["waiting_at"] + 20
    ), "release ordering or timeout"


def install_detachment_transport(transport_type, original, evidence, identify, write):
    """Gate only E1's real synthetic generation response, without extra sends."""
    assert transport_type.handle_request is original
    assert not Path("/tmp/workflow-cli/pause-generation").exists(), "legacy generation pause is not E1 authority"

    def response(transport, request):
        # The original installed fixture still constructs every byte and counts
        # every ping/completion. No model, SDK or generation method is replaced.
        result = original(transport, request)
        if evidence["calls"] != 2:
            return result
        body = json.loads(request.content)
        texts = []
        for message in body.get("messages", []):
            content = message.get("content", "")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                texts.extend(part["text"] for part in content if part.get("type") == "text")
        if any("Request:\n" in text for text in texts) or not any(
            "Initial foreground workflow scene fixture" in text for text in texts
        ):
            return result
        assert result.status_code == 200 and PAUSE.read_bytes() == PAUSE_BYTES
        waiting_at = time.monotonic()
        deadline = waiting_at + 20
        receipt = dict(
            identity=identify(), calls=evidence["calls"], phase="waiting", outcome=None,
            waiting_at=waiting_at, deadline=deadline, released_at=None,
            response_ready=True, response_returning=False,
        )
        name = f"generation-child-{os.getpid()}-active.json"
        write(name, receipt)
        while True:
            # Sample AFTER the marker read too: descheduling during exists()
            # must not turn an expired wait into an explicit-release receipt.
            present = PAUSE.exists()
            now = time.monotonic()
            if now >= deadline:
                outcome = "timeout"
                break
            if not present:
                outcome = "marker_removed"
                break
            time.sleep(0.02)
        receipt.update(phase="released", outcome=outcome, released_at=now, response_returning=True)
        write(name, receipt)  # Worker-side witness immediately before HTTP return.
        return result

    transport_type.handle_request = response


def initialization_preparation(role):
    """Exercise real schema/catalogue components under already installed S2 guards.

    This is component preparation only. The caller owns cold interpreter,
    environment, origin/native guards and lifecycle evidence; this function
    cannot certify installed readiness, failure containment or cleanup.
    """
    from copy import deepcopy

    import workflow_graphql_execution_join_harness as harness

    assert role in {"init-server", "init-generate", "init-refine", "init-assess"}
    guard = harness.ACTIVE
    assert guard is not None and getattr(guard, "initialization_role", None) == role
    assert getattr(guard, "initialization_controls_ready", False) is True
    assert guard.sdk_calls == 0 and guard.owner_constructions == 0
    # Environment/cache ownership must already hold before the early real
    # ArenaEnvGraphSpec validation inside the existing synthetic SDK fixture.
    case = guard.initialization_case
    assert all(os.environ.get(k) == v for k, v in harness.initialization_environment(case, role).items())
    if role != "init-server":
        from generation_worker_fixture import install_synthetic_sdk

        install_synthetic_sdk(scene=True)
    from pydantic import ValidationError

    from isaaclab_arena.agentic_environment_generation.workbench.document_yaml import parse_yaml, reject_unknown_fields
    from isaaclab_arena.assets.registries import ensure_assets_registered
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena.environment_spec.arena_env_graph_yaml_loader import load_env_graph_spec_dict
    from isaaclab_arena_examples.agentic_environment_generation.web_api.catalogues import execution_catalogue_sha256
    from isaaclab_arena_examples.agentic_environment_generation.web_api.scene_worker import prepare_catalogues

    if role == "init-assess":
        # Same deferred assessment imports as scene_worker.execute, without
        # constructing BoundedSceneModels or submitting an assessment.
        from isaaclab_arena.agentic_environment_generation.workflow.contracts import Criterion
        from isaaclab_arena.agentic_environment_generation.workflow.evidence import CandidateBinding, EvidenceCohort
        from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import SceneEvidenceArtifacts

        assert all(value is not None for value in (Criterion, CandidateBinding, EvidenceCohort, SceneEvidenceArtifacts))
    elif role == "init-generate":
        from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import (
            RetainedPriorArtifacts, RetainedPriorReceipt,
        )

        assert RetainedPriorArtifacts is not None and RetainedPriorReceipt is not None

    # Initialize the real registry once, outside Pydantic's per-field error
    # aggregation, so a startup failure retains its original traceback.
    ensure_assets_registered()
    value = load_env_graph_spec_dict(
        Path(__file__).resolve().parents[1] / "isaaclab_arena/tests/test_data/minimal_maple_table_env_graph.yaml"
    )
    normalized = ArenaEnvGraphSpec.model_validate(deepcopy(value)).model_dump(mode="json")
    assert ArenaEnvGraphSpec.model_validate(deepcopy(normalized)).model_dump(mode="json") == normalized
    checks = ["supported_normalization"]
    negatives = []
    unknown_asset = deepcopy(value)
    unknown_asset["objects"][0]["registry_name"] = "s2_unknown_asset"
    negatives.append(("unknown_asset", unknown_asset, "Unknown asset registry_name"))
    unknown_relation = deepcopy(value)
    unknown_relation["relations"][0]["kind"] = "s2_unknown_relation"
    negatives.append(("unknown_relation", unknown_relation, "Unknown relation"))
    dangling = deepcopy(value)
    dangling["relations"][0]["subject"] = "s2_missing_subject"
    negatives.append(("dangling_reference", dangling, "unknown subject"))
    for name, invalid, reason in negatives:
        try:
            ArenaEnvGraphSpec.model_validate(invalid)
        except ValidationError as error:
            assert reason in str(error), "Different schema rejection is not the requested witness"
            checks.append(name)
        else:
            raise AssertionError("Real schema accepted " + name)
    text = json.dumps(dict(value, s2_unknown_field=True))  # JSON is valid YAML; use the actual parser.
    try:
        reject_unknown_fields(parse_yaml(text))
    except ValueError as error:
        assert "s2_unknown_field" in str(error)
        checks.append("unknown_yaml_field")
    else:
        raise AssertionError("Real YAML validator accepted unknown field")
    digest = execution_catalogue_sha256()
    assets, relations, tasks = prepare_catalogues(digest)
    assert execution_catalogue_sha256(assets=assets, relations=relations, tasks=tasks) == digest
    checks.append("catalogue_agreement")
    wrong_digest = ("1" if digest[0] == "0" else "0") + digest[1:]
    try:
        prepare_catalogues(wrong_digest)
    except ValueError as error:
        assert str(error) == "Catalogue mismatch"
        checks.append("catalogue_disagreement")
    else:
        raise AssertionError("Real worker accepted catalogue disagreement")
    assert guard.sdk_calls == 0 and guard.owner_constructions == 0
    if role != "init-server":
        sdk = harness.read_json(Path(f"/evidence/generation-child-{os.getpid()}-sdk.json"))
        assert sdk["calls"] == 0 and sdk["responses"] == []
    return dict(schema_checks=checks, normalized=normalized, catalogue_sha256=digest, registries_initialized=True,
                scope="real component preparation, not installed lifecycle or native acceptance")


def initialization_group_absent(pgid):
    """Read existing bounded production process census; never signal foreign groups."""
    from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import group_members

    assert type(pgid) is int and pgid > 1
    return not any(row["state"] not in {"Z", "X"} for row in group_members(pgid).values())


def registrations():
    from isaaclab_arena.agentic_environment_generation.inference_profiles import (
        frozen_builtin_profile,
        resolve_inference_profile,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration

    model, endpoint = "gpt-6-astra", "https://api.openai.com/v1"
    return tuple(
        ProfileRegistration.model_validate({
            "profile_id": role,
            "revision": 1,
            "kind": "model",
            "roles": [role + "_model"],
            "settings": {
                "model": model,
                "endpoint": endpoint,
                "billing": "free",
                "inference_policy": frozen_builtin_profile(resolve_inference_profile(model, endpoint)),
                "workflow_accounting": {
                    "version": 1,
                    "attested": True,
                    "model": model,
                    "endpoint": endpoint,
                    "max_tokens": 10000,
                    "max_cost_usd": "0",
                },
            },
        })
        for role in ("generation", "assessment")
    )


def private_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True))
    path.chmod(0o600)


def configuration(kind, profiles, *, home="/tmp"):
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import profile_revision

    assert kind in {"query", "execution"}
    root = Path("/tmp/graphql-execution") / kind
    root.mkdir(mode=0o700, parents=True)
    folder = root / "config"
    folder.mkdir(mode=0o700)
    value = {
        "schema_version": 1 if kind == "query" else 2,
        "mode": "query-only" if kind == "query" else "isolated-synthetic-execution-v1",
        "operator": {
            "uid": os.getuid(),
            "gid": os.getgid(),
            "groups": sorted(os.getgroups()),
            "account": pwd.getpwuid(os.getuid()).pw_name,
            "home": home,
            "cwd": "/tmp",
        },
        "private_root": str(root / "runtime"),
        "credentials_file": str(folder / "credentials.json"),
        "endpoint": "http://127.0.0.1:18761/graphql",
        "bolt_uri": os.environ["ARENA_WORKFLOW_NEO4J_URI"],
        "binding": {
            "schema_version": 1,
            "authority_id": "synthetic-execution-authority",
            "operational_schema_version": 1,
            "artifact_marker_schema": 1,
            "database": os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"],
            "deployment_id": "execution-admission-test",
            "workspace_id": kind,
            "store_id": "synthetic-store",
            "registry_id": "synthetic-registry",
        },
        "artifact_root": str(root / "artifacts"),
        "required_profiles": [profile_revision(p).model_dump(mode="json") for p in profiles],
        "bootstrap_principal": "synthetic-admin",
        "read_principal": "synthetic-operator",
    }
    private_json(folder / "server.json", value)
    for profile in profiles:
        private_json(folder / (profile.profile_id + ".json"), profile.model_dump(mode="json"))


def contract(profiles):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import WorkflowContract, canonical_json
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import profile_revision

    offline = {"profile_id": "offline", "settings_sha256": "a" * 64}
    subject = "mug_ycb_robolab"
    common = {
        "requirement": "required",
        "evaluator_version": "1",
        "subjects": [subject],
        "observation_window": {"start_step": 0, "end_step": 2},
    }
    return canonical_json(
        WorkflowContract.model_validate({
            "schema_version": "1",
            "source": {"kind": "new", "prompt": "Initial foreground workflow scene fixture"},
            "criteria": [
                {
                    **common,
                    "criterion_id": "speed",
                    "kind": "runtime",
                    "evidence_producer": "scene.linear-speed",
                    "required_modalities": ["state"],
                    "coordinate_frames": ["world"],
                    "rubric": "maximum linear speed",
                    "limit": {"operator": "le", "value": 0.01, "unit": "m_per_s"},
                },
                {
                    **common,
                    "criterion_id": "visible",
                    "kind": "visual",
                    "evidence_producer": "scene.visible",
                    "required_modalities": ["rgb"],
                    "coordinate_frames": ["wrist"],
                    "rubric": "subject visible in every retained frame",
                    "limit": {"operator": "eq", "value": 1.0, "unit": "boolean"},
                },
            ],
            "preserved": [],
            "allowed_interventions": [
                {
                    "subject_id": subject,
                    "schema_path": f"/relations/5/params/{axis}",
                    "operation": "replace",
                    "coordinate_frame": "env_local",
                    "units": "m",
                    "max_total_displacement_m": 0.1,
                }
                for axis in ("x", "y")
            ],
            "execution": {
                **{
                    p.profile_id
                    + "_model": {
                        "profile_id": p.profile_id,
                        "billing": "free",
                        "settings_sha256": profile_revision(p).settings_sha256,
                    }
                    for p in profiles
                },
                "runtime": offline,
                "database": offline,
                "capture": offline,
                "policy": None,
                "seed": 1,
                "timestep_seconds": 0.01,
                "decimation": 1,
                "dcrg": None,
            },
            "budget": {
                "max_candidates": 2,
                "max_revisions": 1,
                "max_runtime_seconds": 120.0,
                "max_model_calls": 8,
                "max_model_tokens": 80000,
                "max_cost_usd": 0.0,
                "max_realizations": 2,
                "max_steps": 4,
                "max_observations": 2,
                "max_policy_episodes": 0,
                "max_policy_steps": 0,
                "per_operation_timeout_seconds": 30.0,
                "total_deadline_seconds": 180.0,
            },
            "effects": {
                "allow_paid_models": False,
                "allow_runtime": True,
                "allow_database_reads": False,
                "allow_operational_writes": True,
                "allow_publication": False,
            },
        })
    )


@contextmanager
def synthetic_capture(*, candidate, contract, cohort):
    """Same fixed world-state/RGB algorithm as the retained synthetic example."""
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
        return {
            "step": step,
            "frame": "world",
            "origin_w": [10.0, 0.0, 0.0],
            "subjects": {
                "mug_ycb_robolab": {
                    "position_w": [10 + position["x"], position["y"], position["z"]],
                    "linear_velocity_w": [0.0, 0.0, 0.0],
                    "angular_velocity_w": [0.0, 0.0, 0.0],
                }
            },
        }

    yield CaptureRuntime(Env(), Policy(), sample, lambda image, path: path.write_bytes(image))
