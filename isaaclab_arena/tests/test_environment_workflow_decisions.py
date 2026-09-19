# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Pure durable generation boundary contracts; no driver import."""
import pytest


def test_attempt_types_are_nested_frozen_strict_metadata():
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        AttemptFence,
        AuthorizationSnapshot,
        ReadinessReceipt,
        ReadyProfile,
        WorkerRegistration,
    )

    fence = AttemptFence(
        run_id="r",
        intent_id="i",
        attempt_id="a",
        generation=1,
        owner_id="o",
        owner_epoch=1,
    )
    reg = WorkerRegistration(
        registration_id="reg",
        fence=fence,
        host="h",
        boot="b",
        pid=1,
        pgid=1,
        sid=1,
        start_ticks=1,
    )
    auth = AuthorizationSnapshot(
        database="db",
        deployment_id="d",
        workspace_id="w",
        principal="p",
        grant_ref="g",
        contract_digest="a" * 64,
        expires_at=200.0,
        capabilities=("generation_model",),
    )
    ready = ReadinessReceipt(
        contract_digest="a" * 64,
        checked_at=100.0,
        profiles=tuple(
            ReadyProfile(role=role, profile_id="p", settings_sha256="a" * 64)
            for role in ("generation_model", "runtime", "neo4j")
        ),
    )
    for item in (fence, reg, auth, ready):
        assert type(item).model_validate_json(item.model_dump_json()) == item
        with pytest.raises(ValueError):
            item.unlisted = "secret"
    with pytest.raises(ValueError):
        reg.fence.generation = 2
    for field, bad in [("pid", True), ("start_ticks", 0), ("pgid", "1"), ("sid", -1)]:
        with pytest.raises(ValueError):
            WorkerRegistration.model_validate({**reg.model_dump(), field: bad})
    with pytest.raises(ValueError):
        AuthorizationSnapshot.model_validate({**auth.model_dump(), "credentials": "secret"})
    with pytest.raises(ValueError):
        AuthorizationSnapshot.model_validate({**auth.model_dump(), "expires_at": float("inf")})
    with pytest.raises(ValueError):
        ReadinessReceipt.model_validate(True)


def test_generation_artifacts_are_exact_protected_bytes(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow import artifacts
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration

    fence = AttemptFence(
        run_id="R:1",
        intent_id="I.1",
        attempt_id="A:1",
        generation=1,
        owner_id="O",
        owner_epoch=1,
    )
    reg = WorkerRegistration(
        registration_id="reg",
        fence=fence,
        host="synthetic",
        boot="synthetic",
        pid=1,
        pgid=1,
        sid=1,
        start_ticks=1,
    )
    screened = []
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        adapter = artifacts.GenerationArtifacts(area)
        receipt = adapter.write(
            fence,
            reg,
            generation_contract(),
            b"scene: synthetic\n",
            {"scene": "synthetic"},
            protect=lambda value: screened.append(value),
        )
        assert receipt.disposition == "produced"
        assert adapter.verify(receipt, protect=lambda value: screened.append(value)) == receipt
        assert (
            adapter.write(
                fence,
                reg,
                generation_contract(),
                b"scene: synthetic\n",
                {"scene": "synthetic"},
                protect=lambda value: None,
            )
            == receipt
        )
        assert screened
        with pytest.raises(ValueError):
            adapter.write(
                fence,
                reg,
                generation_contract(),
                b"changed\n",
                {},
                protect=lambda value: None,
            )
        (tmp_path / "area" / receipt.artifact_directory / "candidate.yaml").write_bytes(b"tampered")
        with pytest.raises(ValueError):
            adapter.verify(receipt, protect=lambda value: None)


def test_generation_receipt_loaded_by_exact_binding_after_area_reopen(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import GenerationArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration

    fence = AttemptFence(run_id="r", intent_id="i", attempt_id="a", generation=1, owner_id="o", owner_epoch=1)
    registration = WorkerRegistration(
        registration_id="reg", fence=fence, host="synthetic", boot="synthetic", pid=1, pgid=1, sid=1, start_ticks=1
    )
    contract = generation_contract()
    root = tmp_path / "area"
    with ArtifactArea.create(root, store_id="test", registry_id="scope") as area:
        expected = (
            GenerationArtifacts(area)
            .write(
                fence,
                registration,
                contract,
                b"scene: synthetic\n",
                {"scene": "synthetic"},
                protect=lambda value: None,
                producer_metadata={"warnings": ["synthetic nonconvergence"]},
            )
            .model_dump_json()
        )
    # No receipt or live ArtifactArea is carried into the reopened reader.
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    screened = []
    with ArtifactArea.open(root, store_id="test", registry_id="scope") as area:
        artifacts = GenerationArtifacts(area)
        assert hasattr(artifacts, "load_receipt"), "exact artifact receipt recovery is missing"
        loaded = artifacts.load_receipt(fence, registration, contract, protect=lambda value: screened.append(value))
        assert loaded.model_dump_json() == expected
        assert screened[0]["provenance"]["producer_metadata"]["warnings"] == ["synthetic nonconvergence"]
        assert artifacts.verify(loaded, protect=lambda value: None) == loaded
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize(
    "case",
    [
        "wrong_registration",
        "wrong_contract",
        "corrupt_bytes",
        "corrupt_manifest",
        "symlink",
        "staging_only",
        "extra_file",
        "missing_guard",
        "rejecting_guard",
        "mutating_guard",
        "resealed_boolean_binding",
        "resealed_receipt_boolean_binding",
        "fsync_failure",
    ],
)
def test_generation_recovery_rejects_unbound_or_unverified_artifacts(tmp_path, monkeypatch, case):
    import json

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import GenerationArtifacts, encoded
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import parse_contract

    fence = AttemptFence(run_id="r", intent_id="i", attempt_id="a", generation=1, owner_id="o", owner_epoch=1)
    registration = WorkerRegistration(
        registration_id="reg", fence=fence, host="synthetic", boot="synthetic", pid=1, pgid=1, sid=1, start_ticks=1
    )
    contract = generation_contract()
    root = tmp_path / "area"
    with ArtifactArea.create(root, store_id="test", registry_id="scope") as area:
        artifacts = GenerationArtifacts(area)
        receipt = artifacts.write(
            fence,
            registration,
            contract,
            b"scene: synthetic\n",
            {"scene": "synthetic"},
            protect=lambda value: None,
        )
        directory = root / receipt.artifact_directory
        if case == "wrong_registration":
            registration = registration.model_copy(update={"registration_id": "other"})
        elif case == "wrong_contract":
            changed = contract.model_dump(mode="json")
            changed["source"]["prompt"] = "Different frozen request"
            contract = parse_contract(json.dumps(changed))
        elif case == "corrupt_bytes":
            (directory / "candidate.yaml").write_bytes(b"modified")
        elif case == "corrupt_manifest":
            (directory / "manifest.json").write_bytes(b"{}")
        elif case == "symlink":
            (directory / "candidate.yaml").unlink()
            (directory / "candidate.yaml").symlink_to(directory / "candidate.json")
        elif case == "staging_only":
            directory.rename(root / "staging" / directory.name)
        elif case == "extra_file":
            (directory / "extra.json").write_bytes(b"{}")
        elif case in {"resealed_boolean_binding", "resealed_receipt_boolean_binding"}:
            manifest = json.loads(receipt.manifest_json)
            manifest["binding"]["registration"]["pid"] = True
            payloads = {name: (directory / name).read_bytes() for name in manifest["files"]}
            altered = area.expected_manifest(manifest["reservation_id"], payloads, manifest["binding"])
            (directory / "manifest.json").write_bytes(encoded(altered))

        if case == "fsync_failure":
            import os

            def failed_sync(fd):
                raise OSError("synthetic recovery durability failure")

            monkeypatch.setattr(os, "fsync", failed_sync)

        def protect(value):
            if case == "rejecting_guard":
                raise ValueError("current public policy rejects retained data")
            if case == "mutating_guard":
                value["spec"]["scene"] = "changed"

        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        with pytest.raises(ValueError):
            if case == "resealed_receipt_boolean_binding":
                changed_receipt = receipt.model_copy(
                    update={
                        "manifest_json": encoded(altered).decode(),
                        "manifest_sha256": altered["digest"],
                    }
                )
                artifacts.verify(changed_receipt, protect=protect)
            else:
                artifacts.load_receipt(
                    fence, registration, contract, protect=None if case == "missing_guard" else protect
                )
        assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_generation_protect_rejects_before_retention(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import GenerationArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration

    fence = AttemptFence(
        run_id="r",
        intent_id="i",
        attempt_id="a",
        generation=1,
        owner_id="o",
        owner_epoch=1,
    )
    reg = WorkerRegistration(
        registration_id="reg",
        fence=fence,
        host="synthetic",
        boot="synthetic",
        pid=1,
        pgid=1,
        sid=1,
        start_ticks=1,
    )
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        adapter = GenerationArtifacts(area)

        def reject(value):
            raise ValueError("private data rejected")

        def mutate(value):
            value["spec"]["changed"] = True

        for protect in (None, reject, mutate):
            with pytest.raises(ValueError):
                adapter.write(
                    fence,
                    reg,
                    generation_contract(),
                    b"synthetic: true\n",
                    {},
                    protect=protect,
                )
        assert not list((tmp_path / "area" / "staging").iterdir())
        assert not list((tmp_path / "area" / "final").iterdir())


def test_generation_artifacts_retain_producer_findings_and_exact_prior_snapshot(tmp_path):
    import inspect
    import json

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import GenerationArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration

    fence = AttemptFence(run_id="r", intent_id="i", attempt_id="a", generation=1, owner_id="o", owner_epoch=1)
    registration = WorkerRegistration(
        registration_id="reg",
        fence=fence,
        host="synthetic",
        boot="synthetic",
        pid=1,
        pgid=1,
        sid=1,
        start_ticks=1,
    )
    # Opaque synthetic producer metadata here; receipt-shape validation belongs to the adapter.
    metadata = {
        "prior_snapshot": {"status": "unavailable", "fixture": "synthetic-no-research-read"},
        "warnings": ["Agent did not converge on all physical/semantic checks; review the draft before use."],
        "publication": "not_published",
    }
    seen = []
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        artifacts = GenerationArtifacts(area)
        assert "producer_metadata" in inspect.signature(artifacts.write).parameters
        receipt = artifacts.write(
            fence,
            registration,
            generation_contract(),
            b"scene: synthetic\n",
            {"scene": "synthetic"},
            protect=lambda value: seen.append(value),
            producer_metadata=metadata,
        )
        raw = artifacts.verified_bytes(receipt, protect=lambda value: seen.append(value))
        assert json.loads(raw["provenance.json"])["producer_metadata"] == metadata
        assert all(value["provenance"]["producer_metadata"] == metadata for value in seen)
        assert (
            artifacts.write(
                fence,
                registration,
                generation_contract(),
                b"scene: synthetic\n",
                {"scene": "synthetic"},
                protect=lambda value: None,
                producer_metadata=metadata,
            )
            == receipt
        )
        metadata["warnings"] = []
        with pytest.raises(ValueError):
            artifacts.write(
                fence,
                registration,
                generation_contract(),
                b"scene: synthetic\n",
                {"scene": "synthetic"},
                protect=lambda value: None,
                producer_metadata=metadata,
            )
        assert json.loads(artifacts.verified_bytes(receipt, protect=lambda value: None)["provenance.json"])[
            "producer_metadata"
        ]["warnings"]


@pytest.mark.parametrize("case", ["nonobject", "nonfinite", "oversized", "protected", "mutating_guard"])
def test_generation_producer_metadata_rejected_without_partial_retention(tmp_path, case):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import GenerationArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration

    fence = AttemptFence(run_id="r", intent_id="i", attempt_id="a", generation=1, owner_id="o", owner_epoch=1)
    registration = WorkerRegistration(
        registration_id="reg",
        fence=fence,
        host="synthetic",
        boot="synthetic",
        pid=1,
        pgid=1,
        sid=1,
        start_ticks=1,
    )
    metadata = {"fixture": "synthetic-protected-marker"}
    if case == "nonobject":
        metadata = []
    elif case == "nonfinite":
        metadata = {"usage": float("nan")}
    elif case == "oversized":
        metadata = {"fixture": "x" * (2 * 1024 * 1024)}

    def protect(value):
        retained = value["provenance"]["producer_metadata"]
        if case == "protected":
            assert retained["fixture"] == "synthetic-protected-marker"
            raise ValueError("protected producer metadata")
        if case == "mutating_guard":
            retained["fixture"] = "changed"

    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        with pytest.raises(ValueError):
            GenerationArtifacts(area).write(
                fence,
                registration,
                generation_contract(),
                b"scene: synthetic\n",
                {"scene": "synthetic"},
                protect=protect,
                producer_metadata=metadata,
            )
        assert not list((tmp_path / "area" / "staging").iterdir())
        assert not list((tmp_path / "area" / "final").iterdir())


def test_generation_result_contract_is_callable_without_sqlite_job_or_gui():
    import importlib.util

    from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot

    name = "isaaclab_arena.agentic_environment_generation.workflow.generation_output"
    assert importlib.util.find_spec(name) is not None, "framework-independent result contract missing"
    from isaaclab_arena.agentic_environment_generation.workflow.generation_output import validate_generation_output

    inputs = {"operation": "new", "prompt": "synthetic", "execution_catalogue_sha256": "a" * 64}
    snapshot = empty_snapshot("synthetic")
    result = {
        "operation": "new",
        "yaml_text": "fixture: synthetic\n",
        "publication": "not_published",
        "validation": {"valid": False},
        "traces": [],
        "warnings": [],
        "prior_snapshot": snapshot,
        "catalogue_sha256": "a" * 64,
    }
    checked = []

    def validate(text):
        checked.append(text)
        return {"valid": True, "fixture": "fresh-schema-check"}

    validated = validate_generation_output(inputs, result, validate_document=validate)
    assert checked == [result["yaml_text"]]
    assert validated["validation"] == {"valid": True, "fixture": "fresh-schema-check"}
    assert validated["prior_snapshot"] == snapshot
    assert result["validation"] == {"valid": False}
    for changed in (
        {**result, "operation": "refine"},
        {**result, "publication": "published"},
        {**result, "catalogue_sha256": "b" * 64},
        {**result, "unrecognized": True},
    ):
        with pytest.raises(ValueError):
            validate_generation_output(inputs, changed, validate_document=validate)


def generation_contract():
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import WorkflowContract
    from isaaclab_arena.tests.test_environment_workflow_contracts import request

    raw = request()
    raw["budget"].update(max_model_calls=2, max_model_tokens=1000, max_cost_usd=2.0)
    raw["effects"]["allow_operational_writes"] = True
    return WorkflowContract.model_validate(raw)


def authority(s, contract):
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AuthorizationSnapshot
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest

    return AuthorizationSnapshot(
        database=s.database,
        **s.scope,
        principal="local",
        grant_ref="grant-1",
        contract_digest=contract_digest(contract),
        expires_at=200.0,
        capabilities=("generation_model", "operational_writes"),
    )


def gate_readiness(contract, *, instances=None, mono=None, wall=None):
    from isaaclab_arena.agentic_environment_generation.workflow import readiness as r

    assert hasattr(r, "ReadinessClock"), "explicit monotonic to wall clock bridge missing"
    mono = mono or (lambda: 10.0)
    wall = wall or (lambda: 100.0)
    mapping = r.ReadinessClock.capture(monotonic=mono, wall_clock=wall)
    required = r.required_dependencies(contract, resolved_instances=instances)
    gate = r.DependencyGate(
        lambda req, timeout: r.DependencyResult(
            req.dependency_id,
            "passed",
            req.profile_sha256,
            profile_id=req.profile_id,
            instance_id=req.instance_id,
        ),
        clock=mono,
    )
    report = gate.check(required, timeout_s=1.0)
    return r.durable_readiness(contract, required, report, mapping=mapping)


def test_structural_gate_bridge_has_exact_three_dependencies():
    ready = gate_readiness(generation_contract())
    assert {p.role for p in ready.profiles} == {"runtime", "neo4j", "generation_model"}
    assert ready.checked_at == 100.0


def test_store_requires_readiness_for_reservation_and_trusted_instance_binding():
    import inspect

    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore

    parameter = inspect.signature(Neo4jWorkflowStore.reserve_generation).parameters.get("readiness")
    assert parameter is not None and parameter.kind == inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty
    contract = generation_contract()
    instances = {("neo4j", "offline", "a" * 64): "trusted-db"}
    store = Neo4jWorkflowStore(
        None,
        database="db",
        deployment_id="d",
        workspace_id="w",
        dependency_instances=instances,
    )
    good = gate_readiness(contract, instances=instances)
    assert store._readiness(contract, good, 100.0) == good
    impostor = gate_readiness(contract, instances={**instances, ("neo4j", "offline", "a" * 64): "other-db"})
    for bad in (
        impostor,
        gate_readiness(contract),
        good.model_copy(update={"checked_at": 101.0}),
        good.model_copy(update={"checked_at": 69.0}),
        good.model_copy(update={"profiles": good.profiles + good.profiles[:1]}),
    ):
        with pytest.raises(ValueError):
            store._readiness(contract, bad, 100.0)


def test_bridge_rejects_bad_report_and_preserves_observation_age():
    from dataclasses import replace

    from isaaclab_arena.agentic_environment_generation.workflow import readiness as r

    mono_value, wall_value = [10.0], [100.0]
    mono, wall = lambda: mono_value[0], lambda: wall_value[0]
    mapping = r.ReadinessClock.capture(monotonic=mono, wall_clock=wall)
    contract = generation_contract()
    requirements = r.required_dependencies(contract)
    report = r.DependencyGate(
        lambda req, timeout: r.DependencyResult(
            req.dependency_id,
            "passed",
            req.profile_sha256,
            profile_id=req.profile_id,
        ),
        clock=mono,
    ).check(requirements, timeout_s=1.0)
    mono_value[0], wall_value[0] = 15.0, 105.0
    assert r.durable_readiness(contract, requirements, report, mapping=mapping).checked_at == 100.0
    for bad in (
        replace(report, checked_at=16.0),
        replace(report, clock=lambda: 15.0),
        replace(report, results=report.results[:-1]),
        replace(report, results=(report.results[0],) * len(report.results)),
        replace(
            report,
            results=(replace(report.results[0], status="unavailable"),) + report.results[1:],
        ),
        replace(
            report,
            results=(replace(report.results[0], profile_id="wrong"),) + report.results[1:],
        ),
    ):
        with pytest.raises(ValueError):
            r.durable_readiness(contract, requirements, bad, mapping=mapping)
    wall_value[0] = 110.0
    with pytest.raises(ValueError):
        r.durable_readiness(contract, requirements, report, mapping=mapping)


@pytest.mark.parametrize("status", ["unavailable", "not_checked"])
def test_nonstructural_requires_gpu_and_scene_only_needs_no_policy(status):
    from isaaclab_arena.agentic_environment_generation.workflow import readiness as r
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import WorkflowContract
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore

    raw = generation_contract().model_dump(mode="json")
    raw["criteria"][0].update(kind="visual", required_modalities=["rgb"])
    contract = WorkflowContract.model_validate(raw)
    good = gate_readiness(contract)
    assert {p.role for p in good.profiles} == {
        "runtime",
        "neo4j",
        "generation_model",
        "assessment_model",
        "capture",
        "gpu",
    }
    store = Neo4jWorkflowStore(None, database="db", deployment_id="d", workspace_id="w")
    assert store._readiness(contract, good, 100.0) == good
    with pytest.raises(ValueError):
        store._readiness(
            contract,
            good.model_copy(
                update={
                    "profiles": tuple(p for p in good.profiles if p.role != "gpu"),
                }
            ),
            100.0,
        )

    def mono():
        return 10.0

    mapping = r.ReadinessClock.capture(monotonic=mono, wall_clock=lambda: 100.0)
    required = r.required_dependencies(contract)
    report = r.DependencyGate(
        lambda req, timeout: r.DependencyResult(
            req.dependency_id,
            status if req.dependency_id == "gpu" else "passed",
            req.profile_sha256,
            profile_id=req.profile_id,
        ),
        clock=mono,
    ).check(required, timeout_s=1.0)
    with pytest.raises(ValueError):
        r.durable_readiness(contract, required, report, mapping=mapping)


def test_reservation_strict_frozen_roundtrip():
    try:
        from isaaclab_arena.agentic_environment_generation.workflow.attempts import GenerationReservation
    except ImportError:
        pytest.fail("generation reservation not implemented")
    fields = dict(
        model_calls=1,
        model_tokens=100,
        cost_ceiling_usd=0.0,
        runtime_allowance_seconds=1.0,
    )
    value = GenerationReservation(**fields)
    assert GenerationReservation.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValueError):
        value.model_calls = 2
    for name, bad in [
        ("model_calls", True),
        ("model_tokens", "100"),
        ("cost_ceiling_usd", float("nan")),
        ("runtime_allowance_seconds", -1.0),
        ("runtime_allowance_seconds", True),
    ]:
        with pytest.raises(ValueError):
            GenerationReservation(**{**fields, name: bad})
