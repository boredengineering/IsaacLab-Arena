# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""First installed execution admission assertion, not execution acceptance.

Run only through the explicit reviewed workflow-graphql-execution cohort.
The production query-only control must pass before diagnosing execution RED.
"""

import hashlib
import json
import os
import pwd
from pathlib import Path


def configuration(kind):
    """Create explicit owner-private configuration without ambient credentials."""
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
            "home": "/tmp",
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
        "required_profiles": [],
        "bootstrap_principal": "synthetic-admin",
        "read_principal": "synthetic-reader",
    }
    path = folder / "server.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


def setup(kind):
    import workflow_graphql_execution_harness as harness

    path = configuration(kind)
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
    try:
        os.fchmod(read_fd, 0o600)
        assert os.write(write_fd, raw) == len(raw)
    finally:
        os.close(write_fd)
    try:
        return harness.fresh(
            ["setup", "--config", str(path), "--create", "--credentials-fd", str(read_fd)],
            private_fd=read_fd,
        )
    finally:
        os.close(read_fd)


def configuration_regressions():
    """Exercise real loader validation without any additional setup children."""
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import (
        Config,
        credential_document,
        load,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.api.private_files import PrivateFileError, encode

    checked = {}
    for kind, version, mode in (
        ("query", 1, "query-only"),
        ("execution", 2, "isolated-synthetic-execution-v1"),
    ):
        path = Path("/tmp/graphql-execution") / kind / "config/server.json"
        original = path.read_bytes()
        value = json.loads(original)
        config = load(str(path))
        assert type(config) is Config
        assert config.path == str(path) and config.value == value
        assert (config.value["schema_version"], config.value["mode"]) == (version, mode)
        assert config.binding.model_dump(mode="json") == value["binding"]
        assert config.profiles == ()
        assert config.digest == hashlib.sha256(encode(value)).hexdigest()
        rejected = []
        invalid_pairs = [
            (1, "isolated-synthetic-execution-v1"),
            (2, "query-only"),
            (1, "execution"),
            (2, "execution"),
            (3, mode),
            (True, mode),
            (False, mode),
            (float(version), mode),
            (str(version), mode),
            (None, mode),
            ([], mode),
            ({}, mode),
            (version, True),
            (version, False),
            (version, 1),
            (version, None),
            (version, []),
            (version, {}),
            (version, mode + " "),
        ]
        try:
            for invalid_version, invalid_mode in invalid_pairs:
                invalid = dict(value, schema_version=invalid_version, mode=invalid_mode)
                path.write_bytes(encode(invalid))
                try:
                    load(str(path))
                except PrivateFileError as error:
                    assert str(error) == "Unsupported configuration"
                else:
                    raise AssertionError("Unsupported version/mode accepted")
                rejected.append([invalid_version, invalid_mode])
            for invalid in (dict(value, extra=True), {key: item for key, item in value.items() if key != "mode"}):
                path.write_bytes(encode(invalid))
                try:
                    load(str(path))
                except PrivateFileError:
                    pass
                else:
                    raise AssertionError("Changed configuration fields accepted")
        finally:
            path.write_bytes(original)
        assert path.read_bytes() == original
        assert load(str(path)) == config
        credentials = Path(value["credentials_file"]).read_bytes()
        expected = {
            "schema_version": 1,
            "databases": {
                "operational": {
                    "scheme": "basic", "username": "synthetic-user", "password": "synthetic-only-secret",
                },
            },
        }
        assert credential_document(credentials) == expected
        assert credentials == encode(expected)
        for invalid_version in (2, True, 1.0, "1"):
            try:
                credential_document(encode(dict(expected, schema_version=invalid_version)))
            except PrivateFileError:
                pass
            else:
                raise AssertionError("Changed credential schema accepted")
        checked[kind] = {
            "accepted_pair": [version, mode],
            "rejected_pairs": rejected,
            "exact_fields_preserved": True,
            "config_bytes_restored": True,
            "canonical_digest_preserved": True,
            "sentinel_credentials_v1_unchanged": True,
        }
    return checked


def test_fresh_installed_execution_configuration_admission():
    """Reach the real installed loader, with a valid query-only control first."""
    results = {}
    regressions = {}
    try:
        for kind in ("query", "execution"):
            result = setup(kind)
            assert b"synthetic-only-secret" not in result.stdout + result.stderr
            results[kind] = {
                "returncode": result.returncode,
                "stdout": result.stdout.decode("utf-8"),
                "stderr": result.stderr.decode("utf-8"),
                "loader_events": result.loader_events,
            }
        assert results["query"]["returncode"] == 0, "Invalid query-only control; not execution RED"
        assert results["query"]["loader_events"] == [{"event": "call"}, {"event": "return", "accepted": True}]
        assert json.loads(results["query"]["stdout"])["code"] == "setup_complete"
        assert results["execution"]["loader_events"][:1] == [{"event": "call"}], "Installed loader not reached"
        assert results["execution"]["returncode"] == 0, "Real installed execution configuration is not admitted"
        assert json.loads(results["execution"]["stdout"])["code"] == "setup_complete"
        assert results["execution"]["loader_events"] == [{"event": "call"}, {"event": "return", "accepted": True}]
        regressions = configuration_regressions()
    finally:
        Path("/evidence/execution-admission.json").write_text(json.dumps({
            "scope": "installed configuration admission only; no owner/SDK/workflow execution",
            "results": results,
            "regressions": regressions,
        }, indent=2))
