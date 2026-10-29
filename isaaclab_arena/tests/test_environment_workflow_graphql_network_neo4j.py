# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Installed query CLI in the separately admitted synthetic network cohort."""

import json
import os
import pwd
import stat
import pytest
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.workflow import cli


def private_json(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)


def configuration(tmp_path):
    folder = tmp_path / "config"
    folder.mkdir(mode=0o700)
    value = {
        "schema_version": 1,
        "mode": "query-only",
        "operator": {
            "uid": os.getuid(),
            "gid": os.getgid(),
            "groups": sorted(os.getgroups()),
            "account": pwd.getpwuid(os.getuid()).pw_name,
            "home": "/tmp",
            "cwd": os.getcwd(),
        },
        "private_root": str(tmp_path / "runtime"),
        "credentials_file": str(folder / "credentials.json"),
        "endpoint": "http://127.0.0.1:18761/graphql",
        "bolt_uri": os.environ["ARENA_WORKFLOW_NEO4J_URI"],
        "binding": {
            "schema_version": 1,
            "authority_id": "synthetic-query-authority",
            "operational_schema_version": 1,
            "artifact_marker_schema": 1,
            "database": os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"],
            "deployment_id": "network-test",
            "workspace_id": tmp_path.name,
            "store_id": "synthetic-store",
            "registry_id": "synthetic-registry",
        },
        "artifact_root": str(tmp_path / "artifacts"),
        "required_profiles": [],
        "bootstrap_principal": "synthetic-admin",
        "read_principal": "synthetic-reader",
    }
    path = folder / "server.json"
    private_json(path, value)
    return path, value


def setup_private(path, *, fresh=False):
    raw = json.dumps({
        "schema_version": 1,
        "databases": {
            "operational": {
                "scheme": "basic",
                "username": "synthetic-user",
                "password": "synthetic-only-secret",
            }
        },
    }).encode()
    read_fd, write_fd = os.pipe()
    os.fchmod(read_fd, 0o600)
    os.write(write_fd, raw)
    os.close(write_fd)
    try:
        arguments = ["setup", "--config", str(path), "--create", "--credentials-fd", str(read_fd)]
        if fresh:
            import workflow_graphql_network_harness as network

            assert network.fresh(arguments, private_fd=read_fd).returncode == 0
        else:
            assert cli.main(arguments) == 0
    finally:
        os.close(read_fd)


def test_network_role_admission_is_closed_and_separate_from_legacy_guard():
    import importlib.util
    import socket
    import workflow_process_harness as harness

    spec = importlib.util.find_spec("workflow_graphql_network_harness")
    assert spec is not None, "fixed GraphQL network role admission is absent"
    module = __import__("workflow_graphql_network_harness")
    for role in ("client", "launcher", "server", "admin", "harness"):
        guard = module.NetworkGuards(role, "192.0.2.2")
        assert guard.role == role
        assert bool(guard.db_ip) == (role in {"server", "admin", "harness"})
        with __import__("pytest").raises(RuntimeError):
            guard.popen(["unapproved"])
        with socket.socket() as sock, __import__("pytest").raises(RuntimeError):
            guard.audit("socket.connect", (sock, ("192.0.2.2", 7687)))
        assert guard.allowed["child_launch"] == 0
        assert guard.forbidden["subprocess"] == guard.forbidden["network"] == 1
    assert harness.Guards("192.0.2.2", query_only=True).query_only


def test_fresh_public_module_help_has_repeat_preimport_witness():
    import workflow_graphql_network_harness as network

    assert callable(getattr(network, "fresh", None)), "fresh guarded public-module CLI entry is absent"
    result = network.fresh(["--help"])
    assert result.returncode == 0
    assert b"inspect-contract" in result.stdout and b"setup" in result.stdout
    assert result.stderr == b""
    missing = network.fresh(
        ["api-status", "--config", "/tmp/graphql-network/config/server.json", "--instance", "a" * 32]
    )
    assert missing.returncode == 2 and missing.stdout == b""


def test_observe_immutable_uvicorn_shutdown_contract():
    import inspect
    import uvicorn
    from uvicorn.lifespan.on import LifespanOn

    root = Path(inspect.getfile(uvicorn)).parent
    assert os.statvfs(root).f_flag & os.ST_RDONLY
    files = {name: (root / name).read_text() for name in ("server.py", "config.py", "lifespan/on.py")}
    Path("/evidence/uvicorn-discovery.json").write_text(
        json.dumps({"version": uvicorn.__version__, "root": str(root), "files": files})
    )
    assert "shutdown_failed" in inspect.getsource(LifespanOn)


def network_profile():
    from isaaclab_arena.agentic_environment_generation.inference_profiles import (
        frozen_builtin_profile,
        resolve_inference_profile,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration

    return ProfileRegistration.model_validate({
        "profile_id": "network-profile",
        "revision": 2**63 - 1,
        "kind": "model",
        "roles": ["generation_model"],
        "settings": {
            "model": "gpt-4.1",
            "endpoint": "https://api.openai.com/v1",
            "billing": "free",
            "inference_policy": frozen_builtin_profile(
                resolve_inference_profile("gpt-4.1", "https://api.openai.com/v1")
            ),
        },
    })


def seed_retained(config_path):
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import parse_contract, canonical_json

    profile = {"profile_id": "synthetic", "settings_sha256": "a" * 64}
    value = {
        "schema_version": "1",
        "source": {"kind": "new", "prompt": "Synthetic retained query fixture"},
        "criteria": [{
            "criterion_id": "visible",
            "kind": "visual",
            "evidence_producer": "visual-v1",
            "requirement": "required",
            "evaluator_version": "1",
            "required_modalities": ["rgb"],
            "coordinate_frames": ["external_camera"],
            "observation_window": {"start_step": 0, "end_step": 1},
            "rubric": "Target is visible",
            "subjects": ["banana"],
            "limit": {"operator": "eq", "value": 1.0, "unit": "boolean"},
        }],
        "preserved": [],
        "allowed_interventions": [],
        "execution": {
            "generation_model": {**profile, "billing": "free"},
            "assessment_model": {**profile, "billing": "free"},
            "runtime": profile,
            "database": profile,
            "policy": None,
            "capture": profile,
            "seed": 1,
            "timestep_seconds": 0.01,
            "decimation": 1,
            "dcrg": None,
        },
        "budget": {
            "max_candidates": 2,
            "max_revisions": 1,
            "max_runtime_seconds": 60.0,
            "max_model_calls": 8,
            "max_model_tokens": 10000,
            "max_cost_usd": 1.0,
            "max_realizations": 2,
            "max_steps": 100,
            "max_observations": 2,
            "max_policy_episodes": 0,
            "max_policy_steps": 0,
            "per_operation_timeout_seconds": 10.0,
            "total_deadline_seconds": 60.0,
        },
        "effects": {
            "allow_paid_models": False,
            "allow_runtime": True,
            "allow_database_reads": False,
            "allow_operational_writes": True,
            "allow_publication": False,
        },
    }
    raw = canonical_json(parse_contract(json.dumps(value)))
    resources = Resources(load(str(config_path)))
    with resources.driver() as driver:
        return resources.store(driver).admit("network-seed", raw, raw, 10).run_id


def retained_snapshot(config_path):
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load

    resources = Resources(load(str(config_path)))
    binding = resources.config.binding
    with resources.driver() as driver, driver.session(database=binding.database) as session:
        rows = session.run(
            "MATCH (n {deployment_id:$deployment, workspace_id:$workspace}) RETURN labels(n) AS labels, properties(n)"
            " AS properties",
            deployment=binding.deployment_id,
            workspace=binding.workspace_id,
        ).data()
        for row in rows:
            if "ArenaWorkflowControl" in row["labels"]:
                row["properties"].pop("revision", None)
                row["properties"].pop("lock_anchor", None)
        return sorted(json.dumps(row, sort_keys=True) for row in rows)


def test_exact_instance_detached_launch_control_stop(tmp_path, capsys):
    import workflow_graphql_network_harness as network

    fixed = Path("/tmp/graphql-network")
    fixed.mkdir(mode=0o700)
    path, config = configuration(fixed)
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import profile_revision

    profile = network_profile()
    config["required_profiles"] = [profile_revision(profile).model_dump(mode="json")]
    private_json(path, config)
    registration = path.parent / "registration.json"
    private_json(registration, profile.model_dump(mode="json"))
    setup_private(path, fresh=True)
    for action, extra in (("initialize-schema", []), ("initialize-scope", []), ("initialize-artifacts", ["--create"])):
        assert network.fresh(["admin", action, "--config", str(path), *extra]).returncode == 0
    assert (
        network.fresh(
            ["admin", "register-profile", "--config", str(path), "--registration", str(registration)]
        ).returncode
        == 0
    )
    run_id = seed_retained(path)
    assert run_id == network.RUN_ID
    before_query = retained_snapshot(path)
    capsys.readouterr()
    instance = "a" * 32
    result = network.fresh(["api-launch", "--config", str(path), "--instance", instance])
    assert result.returncode == 0, "detached exact-instance API launch is unavailable"
    assert json.loads(result.stdout)["state"] == "ready"
    try:
        client = str(Path(config["private_root"]) / "instances" / instance / "client.json")
        result = network.fresh(["profiles", "--client", client])
        assert result.returncode == 0, "fixed network profile query is unavailable"
        assert [p["id"] for p in json.loads(result.stdout)["data"]["workflowProfiles"]["profiles"]] == [
            "network-profile"
        ]
        for command, expected in [
            (["runs", "--first", "10"], "workflows"),
            (["events", "--first", "10"], "workflowEvents"),
            (["status", run_id], "workflow"),
            (["submission", "network-seed"], "workflowSubmission"),
            (["receipt", "--kind", "SUBMIT", "network-seed"], "workflowCommand"),
            (["profile", "network-profile", "--revision", "9223372036854775807"], "workflowProfile"),
        ]:
            result = network.fresh([*command, "--client", client])
            assert result.returncode == 0, "typed query CLI command unavailable"
            data = json.loads(result.stdout)["data"][expected]
            assert data["__typename"] not in {"QueryFailure", "NotFound"}
            if command[0] == "runs":
                assert [node["id"] for node in data["nodes"]] == [run_id]
            elif command[0] == "events":
                assert data["events"][0]["runId"] == run_id
            elif command[0] == "status":
                assert data["id"] == run_id and data["state"] == "pending"
            elif command[0] in {"submission", "receipt"}:
                assert data["runId"] == run_id and data["operationId"] == "network-seed"
            else:
                assert data["id"] == "network-profile" and data["revision"] == "9223372036854775807"
        result = network.fresh(["api-status", "--config", str(path), "--instance", instance])
        assert result.returncode == 0
        assert json.loads(result.stdout)["state"] == "ready"
    finally:
        result = network.fresh(["api-stop", "--config", str(path), "--instance", instance])
        assert result.returncode == 0
        assert json.loads(result.stdout)["state"] == "stopped"
    assert network.fresh(["api-launch", "--config", str(path), "--instance", instance]).returncode == 2
    old_descriptor = Path(client).read_bytes()
    replacement = "b" * 32
    result = network.fresh(["api-launch", "--config", str(path), "--instance", replacement])
    assert result.returncode == 0 and json.loads(result.stdout)["state"] == "ready"
    try:
        assert network.fresh(["profiles", "--client", client]).returncode == 2
        assert Path(client).read_bytes() == old_descriptor
        new_client = client.replace(instance, replacement)
        result = network.fresh(["profiles", "--client", new_client])
        assert result.returncode == 0
        assert [p["id"] for p in json.loads(result.stdout)["data"]["workflowProfiles"]["profiles"]] == [
            "network-profile"
        ]
    finally:
        result = network.fresh(["api-stop", "--config", str(path), "--instance", replacement])
        assert result.returncode == 0 and json.loads(result.stdout)["state"] == "stopped"
    broken_instance = "c" * 32
    artifact = Path(config["artifact_root"])
    retained_artifact = artifact.with_name("retained-artifacts")
    artifact.rename(retained_artifact)
    try:
        result = network.fresh(["api-launch", "--config", str(path), "--instance", broken_instance])
        assert result.returncode == 2
        assert json.loads(result.stdout)["state"] == "failed"
        assert not artifact.exists(), "API startup silently initialized missing artifacts"
        assert not (Path(config["private_root"]) / "instances" / broken_instance / "client.json").exists()
    finally:
        retained_artifact.rename(artifact)
    assert retained_snapshot(path) == before_query
    Path("/evidence/network-retained-readback.json").write_text(
        json.dumps({
            "run_id": run_id,
            "unchanged_domain_nodes": True,
            "excluded_control_properties": ["revision", "lock_anchor"],
            "before": before_query,
        })
    )


def test_explicit_public_admin_initializes_and_independently_reads_binding(tmp_path, capsys):
    from neo4j import GraphDatabase
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea

    path, config = configuration(tmp_path)
    setup_private(path)
    for action, extra in (("initialize-schema", []), ("initialize-scope", []), ("initialize-artifacts", ["--create"])):
        result = cli.main(["admin", action, "--config", str(path), *extra])
        assert result == 0, "explicit query API administration is unavailable"
    with GraphDatabase.driver(config["bolt_uri"], auth=("synthetic-user", "synthetic-only-secret")) as driver:
        binding = ScopeBinding.model_validate(config["binding"])
        store = Neo4jWorkflowStore(
            driver, database=binding.database, deployment_id=binding.deployment_id, workspace_id=binding.workspace_id
        )
        assert store.verify_scope_binding(binding) == binding
    with ArtifactArea.open(Path(config["artifact_root"]), store_id=binding.store_id, registry_id=binding.registry_id):
        pass
    captured = capsys.readouterr()
    assert captured.err == "" and "synthetic-only-secret" not in captured.out


def test_register_exact_profile_through_public_admin(tmp_path, capsys):
    from isaaclab_arena.agentic_environment_generation.inference_profiles import (
        frozen_builtin_profile,
        resolve_inference_profile,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration, profile_revision
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load

    path, config = configuration(tmp_path)
    setup_private(path)
    assert cli.main(["admin", "initialize-schema", "--config", str(path)]) == 0
    assert cli.main(["admin", "initialize-scope", "--config", str(path)]) == 0
    value = ProfileRegistration.model_validate({
        "profile_id": "network-profile",
        "revision": 2**63 - 1,
        "kind": "model",
        "roles": ["generation_model"],
        "settings": {
            "model": "gpt-4.1",
            "endpoint": "https://api.openai.com/v1",
            "billing": "free",
            "inference_policy": frozen_builtin_profile(
                resolve_inference_profile("gpt-4.1", "https://api.openai.com/v1")
            ),
        },
    })
    source = path.parent / "registration.json"
    private_json(source, value.model_dump(mode="json"))
    capsys.readouterr()
    assert (
        cli.main(["admin", "register-profile", "--config", str(path), "--registration", str(source)]) == 0
    ), "explicit immutable profile registration unavailable"
    resources = Resources(load(str(path)))
    with resources.driver() as driver:
        assert resources.store(driver).get_profile(value.profile_id, value.revision) == profile_revision(value)
    assert "synthetic-only-secret" not in capsys.readouterr().out


def test_explicit_credential_update_and_remove_are_private_and_offline(tmp_path, capsys):
    import workflow_process_harness as harness

    path, config = configuration(tmp_path)
    setup_private(path)
    target = Path(config["credentials_file"])
    original_inode = target.stat().st_ino
    value = json.loads(target.read_text())
    value["databases"]["operational"]["password"] = "synthetic-replacement-only"
    read_fd, write_fd = os.pipe()
    os.fchmod(read_fd, 0o600)
    os.write(write_fd, json.dumps(value).encode())
    os.close(write_fd)
    before = dict(harness.ACTIVE.allowed)
    capsys.readouterr()
    try:
        result = cli.main(["credentials-update", "--config", str(path), "--credentials-fd", str(read_fd)])
    finally:
        os.close(read_fd)
    assert result == 0, "explicit private credential replacement is unavailable"
    assert target.stat().st_ino != original_inode
    assert json.loads(target.read_text()) == value
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert cli.main(["credentials-remove", "--config", str(path)]) == 0
    assert not target.exists()
    assert harness.ACTIVE.allowed == before
    captured = capsys.readouterr()
    assert captured.err == "" and "synthetic-replacement-only" not in captured.out


@pytest.mark.parametrize(
    "field,value",
    [
        ("extra", True),
        ("schema_version", True),
        ("private_root", "relative"),
        ("private_root", "/tmp/../unsafe"),
        ("endpoint", "http://localhost:18761/graphql"),
        ("endpoint", "http://127.0.0.1:0/graphql"),
        ("endpoint", "http://127.0.0.1:18761/graphql?x=1"),
        ("endpoint", "http://127.0.0.1:18761/graphql#x"),
        ("endpoint", "http://user:secret@127.0.0.1:18761/graphql"),
        ("bolt_uri", "bolt://localhost:7687"),
        ("mode", "execution"),
        ("read_principal", "synthetic-admin"),
        ("required_profiles", [{}]),
    ],
)
def test_unsafe_configuration_rejected_before_effects(tmp_path, field, value):
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load
    import workflow_process_harness as harness

    path, config = configuration(tmp_path)
    assert load(str(path)).value == config
    config[field] = value
    private_json(path, config)
    before = dict(harness.ACTIVE.allowed)
    with pytest.raises((ValueError, OSError)):
        load(str(path))
    assert harness.ACTIVE.allowed == before and not Path(config.get("private_root", "/invalid")).exists()


@pytest.mark.parametrize("fault", ["mode", "hardlink", "symlink", "parent-symlink", "directory"])
def test_private_reader_refuses_unsafe_existing_objects(tmp_path, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.api.private_files import read_private

    folder = tmp_path / "private"
    folder.mkdir(mode=0o700)
    path = folder / "value.json"
    private_json(path, {"synthetic": True})
    assert read_private(str(path), 128)
    if fault == "mode":
        path.chmod(0o644)
    elif fault == "hardlink":
        os.link(path, folder / "linked")
    elif fault == "symlink":
        target = folder / "target"
        path.rename(target)
        path.symlink_to(target)
    elif fault == "parent-symlink":
        link = tmp_path / "alias"
        link.symlink_to(folder, target_is_directory=True)
        path = link / path.name
    else:
        path.unlink()
        path.mkdir(mode=0o700)
    with pytest.raises((ValueError, OSError)):
        read_private(str(path), 128)


@pytest.mark.parametrize("selected", ["A" * 32, "a" * 31, "a" * 33, "../instance", " a" * 16])
def test_invalid_instance_never_resolves_private_state(tmp_path, selected, capsys):
    path, config = configuration(tmp_path)
    before = sorted(tmp_path.iterdir())
    assert cli.main(["api-launch", "--config", str(path), "--instance", selected]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and selected not in captured.err
    assert sorted(tmp_path.iterdir()) == before


def test_new_private_directory_modes_ignore_restrictive_umask(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workflow.api.private_files import Directory

    previous = os.umask(0o777)
    try:
        with Directory(str(tmp_path / "private"), create=True) as directory:
            assert stat.S_IMODE(os.fstat(directory.fd).st_mode) == 0o700
    finally:
        os.umask(previous)


@pytest.mark.parametrize("fault", ["replace", "directory-fsync"])
def test_credential_write_failure_never_certifies_durability(tmp_path, monkeypatch, capsys, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.api import private_files

    path, config = configuration(tmp_path)
    setup_private(path)
    target = Path(config["credentials_file"])
    before = target.read_bytes()
    value = json.loads(before)
    value["databases"]["operational"]["password"] = "synthetic-interruption-value"
    reader, writer = os.pipe()
    os.fchmod(reader, 0o600)
    os.write(writer, json.dumps(value).encode())
    os.close(writer)
    real_fsync = os.fsync

    def denied_replace(*args, **kwargs):
        raise OSError("synthetic-private-error-must-not-echo")

    def denied_directory_fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("synthetic-private-error-must-not-echo")
        return real_fsync(fd)

    capsys.readouterr()
    try:
        with monkeypatch.context() as patcher:
            if fault == "replace":
                patcher.setattr(private_files.os, "replace", denied_replace)
            else:
                patcher.setattr(private_files.os, "fsync", denied_directory_fsync)
            assert cli.main(["credentials-update", "--config", str(path), "--credentials-fd", str(reader)]) == 2
    finally:
        os.close(reader)
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "workflow: operation rejected or incomplete\n"
    unchanged = target.read_bytes() == before
    assert unchanged == (fault == "replace")
    assert not list(path.parent.glob(".pending-*"))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":1,"schema_version":1,"databases":{}}',
        b'{"schema_version":NaN,"databases":{}}',
        b'{"schema_version":1,"databases":{"provider":{}}}',
        b'{"schema_version":1,"databases":{"operational":{"scheme":"bearer","username":"u","password":"p"}}}',
        b'{"schema_version":1,"databases":{"operational":{"scheme":"basic","username":"u","password":"p\\n"}}}',
        b'{"schema_version":1,"databases":{"operational":{"scheme":"basic","username":"u","password":"p\\u0085"}}}',
    ],
)
def test_private_credentials_reject_ambiguous_or_nonoperational_documents(raw):
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import credential_document

    with pytest.raises(ValueError):
        credential_document(raw)


def test_private_input_rejects_regular_files_standard_descriptors_and_write_end(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import input_credentials

    target = tmp_path / "input"
    target.write_bytes(b"{}")
    target.chmod(0o600)
    reader, writer = os.pipe()
    os.fchmod(reader, 0o600)
    regular = os.open(target, os.O_RDONLY)
    try:
        for fd in (0, 1, 2, regular, writer):
            with pytest.raises(ValueError):
                input_credentials(fd)
    finally:
        os.close(reader)
        os.close(writer)
        os.close(regular)


def test_missing_launch_identity_stays_unknown_and_old_writer_cannot_replace_current(tmp_path, capsys):
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load
    from isaaclab_arena.agentic_environment_generation.workflow.api.instance import save_state

    path, document = configuration(tmp_path)
    setup_private(path)
    config = load(str(path))
    root = Path(document["private_root"])
    instances = root / "instances"
    instances.mkdir(mode=0o700)
    selected = "a" * 32
    old = instances / selected
    old.mkdir(mode=0o700)
    known = {
        "schema_version": 1,
        "instance": selected,
        "config_sha256": config.digest,
        "binding_sha256": config.binding.body_sha256,
        "endpoint": document["endpoint"],
        "generation": 1,
        "state": "launching",
        "code": "launch_pending",
        "identity": None,
    }
    private_json(old / "state.json", known)
    capsys.readouterr()
    assert cli.main(["api-reconcile", "--config", str(path), "--instance", selected]) == 3
    response = json.loads(capsys.readouterr().out)
    assert response["state"] == "launching" and response["code"] == "unknown" and "identity" not in response
    newer = {"schema_version": 1, "instance": "b" * 32, "config_sha256": config.digest}
    private_json(root / "current.json", newer)
    with pytest.raises(ValueError, match="Instance replaced"):
        save_state(config, selected, known)
    assert json.loads((root / "current.json").read_text()) == newer
    assert json.loads((old / "state.json").read_text()) == known


def test_public_setup_creates_private_credentials_without_database_calls(tmp_path, capsys):
    import workflow_process_harness as harness

    path, config = configuration(tmp_path)
    credential = {
        "schema_version": 1,
        "databases": {
            "operational": {"scheme": "basic", "username": "synthetic-user", "password": "synthetic-only-secret"}
        },
    }
    read_fd, write_fd = os.pipe()
    os.fchmod(read_fd, 0o600)
    os.write(write_fd, json.dumps(credential).encode())
    os.close(write_fd)
    before = dict(harness.ACTIVE.allowed)
    try:
        result = cli.main(["setup", "--config", str(path), "--create", "--credentials-fd", str(read_fd)])
    finally:
        os.close(read_fd)
    assert result == 0, "public query-only setup is unavailable"
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {"schema_version": 1, "code": "setup_complete"}
    assert "synthetic-only-secret" not in captured.out
    assert harness.ACTIVE.allowed == before
    target = Path(config["credentials_file"])
    assert json.loads(target.read_text()) == credential
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(Path(config["private_root"]).stat().st_mode) == 0o700
