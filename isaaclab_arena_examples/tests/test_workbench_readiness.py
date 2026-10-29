# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Readiness is explicit configuration evidence, never a generated or simulated result."""

import socket

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import (
    create_app,
    editor_execution,
    generation,
    graph_access,
)

GPU_UUID = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.mark.parametrize(
    "with_source", [False, True], ids=["prompt-first", "franka-source"]
)
def test_general_generation_readiness_uses_existing_reads_without_policy_or_jobs(
    client, monkeypatch, with_source
):
    """Real API validation and worker logic; synthetic dependency reads, not live readiness."""
    import os
    from pathlib import Path

    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        policy_readiness,
        provider_readiness,
        readiness,
        readiness_worker,
        resource_readiness,
    )

    def forbidden(*args, **kwargs):
        pytest.fail(
            "Base readiness must not call policy, inference, process control or operation authorization"
        )

    monkeypatch.setattr(policy_readiness, "probe_gr00t", forbidden)
    monkeypatch.setattr(policy_readiness, "expected_hashes", forbidden)
    monkeypatch.setattr(readiness, "probe_policy", forbidden)
    monkeypatch.setattr(generation, "generate", forbidden)
    monkeypatch.setattr(client.app.state.workflow_authorization, "capture", forbidden)
    monkeypatch.setattr(os, "kill", forbidden)
    monkeypatch.setattr(os, "killpg", forbidden)
    graph = {
        "uri": "bolt://127.0.0.1:7688",
        "user": "u",
        "password": "synthetic-graph-key",
        "database": "research",
    }
    monkeypatch.setattr(graph_access, "configuration", lambda: graph)
    reads = []
    monkeypatch.setattr(
        graph_access,
        "retrieve_snapshot",
        lambda prompt, config: reads.append((prompt, config)) or {"status": "empty"},
    )
    monkeypatch.setattr(
        resource_readiness, "probe_gpu", lambda config: "resource_headroom_observed"
    )
    monkeypatch.setattr(readiness, "run_readiness_worker", readiness_worker.run_checks)
    monkeypatch.setattr(provider_readiness, "probe_provider", forbidden)
    headers = login(client)
    before = client.get("/api/workspaces/default").json()
    prompt = "  Design a Franka workspace for sorting unfamiliar objects by shape.  "
    body = {"schema_version": 2, "workflow": "agentic_generation", "prompt": prompt}
    if with_source:
        path = (
            Path(__file__).resolve().parents[2]
            / "isaaclab_arena/tests/test_data/minimal_maple_table_env_graph.yaml"
        )
        body["yaml_text"] = path.read_text()
        assert "franka_ik" in body["yaml_text"] and "droid" not in body["yaml_text"]
    metadata = client.get("/api/editor/readiness?version=2&workflow=agentic_generation")
    assert metadata.status_code == 200, metadata.text
    assert metadata.json()["checked_at"] is None and not metadata.json()["ready"]
    assert reads == []
    result = client.post("/api/editor/readiness/check", headers=headers, json=body)
    assert result.status_code == 200, result.text
    value = result.json()
    rows = {row["id"]: row for row in value["checks"]}
    assert {key for key, row in rows.items() if row["required"]} == {
        "api_contract",
        "runtime",
        "generation_model",
        "graph",
        "gpu",
    }
    assert all(
        rows[key]["status"] == "passed"
        for key in ("api_contract", "runtime", "graph", "gpu")
    )
    assert (
        rows["generation_model"]["code"] == "generation_not_configured"
        and not value["ready"]
    )
    assert all(
        rows[key]["status"] == "not_required"
        for key in ("policy_protocol", "policy_model", "policy_transport")
    )
    assert value["policy"] is None and reads == [(prompt, graph)]
    assert client.get("/api/workspaces/default").json() == before


@pytest.mark.parametrize(
    "workflow", ["agentic_generation", "a2_gr00t", "graph_generation", "build"]
)
def test_explicit_workflow_contracts_preserve_legacy_identifiers_and_mutation_auth(
    client, monkeypatch, workflow
):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    url = f"/api/editor/readiness?version=2&workflow={workflow}"
    assert client.get(url).status_code == 401
    headers = login(client)
    calls = []
    monkeypatch.setattr(
        readiness,
        "run_readiness_worker",
        lambda value: calls.append(value)
        or {
            "runtime": "runtime_available",
            "graph": "graph_not_configured",
            "policy": None,
        },
    )
    body = {"schema_version": 2, "workflow": workflow}
    assert client.get(url).json()["workflow"] == workflow
    assert client.post("/api/editor/readiness/check", json=body).status_code == 403
    assert calls == []
    result = client.post("/api/editor/readiness/check", headers=headers, json=body)
    assert result.status_code == 200 and result.json()["workflow"] == workflow
    assert len(calls) == 1 and calls[0]["workflow"] == workflow
    assert calls[0]["check_provider"] is False and calls[0]["provider_config"] is None
    assert client.get("/api/editor/readiness").json()["schema_version"] == 1


@pytest.mark.parametrize(
    "query",
    [
        "version=1&workflow=agentic_generation",
        "version=2.0&workflow=agentic_generation",
        "version=2&workflow=agentic_generation&workflow=a2_gr00t",
        "version=2&workflow=agentic_generation&check_provider=true",
        "version=2&workflow=agentic_generation%20",
        "version=2&workflow=unknown",
        "version=2",
    ],
)
def test_invalid_versioned_selection_never_falls_back_to_legacy(client, query):
    login(client)
    assert client.get("/api/editor/readiness?" + query).status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"schema_version": 1},
        {"schema_version": 2.0},
        {"workflow": "agentic_generation "},
        {"workflow": "unknown"},
        {"check_provider": "true"},
        {"check_provider": 1},
        {"check_provider": None},
        {"base_spec": "forced.yaml"},
        {"policy": "gr00t-droid"},
        {"prompt": None},
        {"yaml_text": "not_an_arena_spec: true"},
        {"document_id": "a" * 32},
        {"prompt": " "},
    ],
)
def test_general_readiness_invalid_input_never_reaches_worker_or_legacy_probes(
    client, monkeypatch, extra
):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)

    def forbidden(*args):
        pytest.fail("Invalid modern requests must not dispatch any readiness path")

    monkeypatch.setattr(readiness, "run_readiness_worker", forbidden)
    monkeypatch.setattr(readiness, "probe_dependencies", forbidden)
    result = client.post(
        "/api/editor/readiness/check",
        headers=headers,
        json={
            "schema_version": 2,
            "workflow": "agentic_generation",
            "check_provider": True,
            **extra,
        },
    )
    assert result.status_code == 422


@pytest.mark.parametrize("snapshots_available", [False, True])
@pytest.mark.parametrize(
    "path",
    [
        "/api/model-settings",
        "/api/editor/generate",
        "/api/editor/generate/operations/{idempotency_key}",
        "/api/editor/validate",
        "/api/editor/build",
        "/api/editor/snapshots",
        "/api/editor/previews/{canonical_hash}",
        "/api/editor/artifacts/{artifact_id}",
    ],
)
def test_general_api_contract_covers_generation_build_and_offered_snapshots(
    client, monkeypatch, path, snapshots_available
):
    """Inspect registered routes and capability flags; never dispatch the stage itself."""
    login(client)
    # A sentinel advertises an adapter; no renderer is instantiated or called.
    with monkeypatch.context() as scoped:
        scoped.setattr(
            client.app.state.editor_execution,
            "snapshots",
            object() if snapshots_available else None,
        )
        scoped.setattr(client.app.state.editor_execution, "evaluation_available", False)
        routes = client.app.router.routes
        scoped.setattr(
            client.app.router,
            "routes",
            [r for r in routes if getattr(r, "path", None) != "/api/editor/evaluate"],
        )

        def contract():
            value = client.get(
                "/api/editor/readiness?version=2&workflow=agentic_generation"
            )
            assert value.status_code == 200
            return next(
                row for row in value.json()["checks"] if row["id"] == "api_contract"
            )

        assert (
            contract()["status"] == "passed"
        ), "Evaluate is not required for generation/build"
        scoped.setattr(client.app.state.editor_execution, "build_available", False)
        assert contract()["status"] == "unavailable"
        scoped.setattr(client.app.state.editor_execution, "build_available", True)
        scoped.setattr(
            client.app.router,
            "routes",
            [r for r in client.app.router.routes if getattr(r, "path", None) != path],
        )
        optional = path in {
            "/api/editor/snapshots",
            "/api/editor/previews/{canonical_hash}",
            "/api/editor/artifacts/{artifact_id}",
        }
        assert contract()["status"] == (
            "passed" if optional and not snapshots_available else "unavailable"
        )


@pytest.mark.parametrize(
    "path",
    [
        "/api/editor/validate",
        "/api/editor/generate",
        "/api/editor/build",
        "/api/editor/snapshots",
    ],
)
def test_general_api_contract_rejects_wrong_registered_body_model(
    client, monkeypatch, path
):
    login(client)
    with monkeypatch.context() as scoped:
        scoped.setattr(client.app.state.editor_execution, "snapshots", object())
        route = next(r for r in client.app.routes if getattr(r, "path", None) == path)
        scoped.setattr(route.dependant, "body_params", [])
        result = client.get(
            "/api/editor/readiness?version=2&workflow=agentic_generation"
        ).json()
        assert (
            next(row for row in result["checks"] if row["id"] == "api_contract")[
                "status"
            ]
            == "unavailable"
        )


@pytest.mark.parametrize("workflow", ["build", "a2_gr00t"])
def test_build_can_pass_observed_gpu_headroom_without_simulation(
    client, monkeypatch, tmp_path, workflow
):
    import importlib.util

    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        readiness,
        readiness_worker,
        snapshot_process,
    )

    name = "isaaclab_arena_examples.agentic_environment_generation.web_api.resource_readiness"
    assert (
        importlib.util.find_spec(name) is not None
    ), "GPU admission needs actual bounded metadata evidence"
    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        resource_readiness as resource,
    )

    lease = tmp_path / "gpu.lock"
    lease.write_bytes(b"existing lease, never rewrite")
    before = lease.stat()
    monkeypatch.setattr(snapshot_process, "GPU_LEASE", lease)
    monkeypatch.setenv("ARENA_WORKBENCH_GPU_MIN_FREE_MIB", "2048")
    monkeypatch.setenv("ARENA_WORKBENCH_GPU_UUID", GPU_UUID)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", GPU_UUID)
    monkeypatch.setenv("NVIDIA_VISIBLE_DEVICES", GPU_UUID)
    calls = []
    monkeypatch.setattr(
        resource,
        "query_gpu",
        lambda deadline: calls.append(deadline)
        or f"0, {GPU_UUID}, 4096, 8192, Disabled\n",
    )
    monkeypatch.setattr(readiness, "run_readiness_worker", readiness_worker.run_checks)
    graph_calls = []
    if workflow == "a2_gr00t":
        from isaaclab_arena_examples.agentic_environment_generation.web_api import (
            policy_readiness,
        )

        monkeypatch.setenv("ARENA_GR00T_CHECKPOINT_SHA256", "a" * 64)
        monkeypatch.setenv("ARENA_GR00T_CONFIG_SHA256", "b" * 64)
        monkeypatch.setattr(
            graph_access,
            "configuration",
            lambda: {
                "uri": "bolt://127.0.0.1:7688",
                "user": "u",
                "password": "private-graph-password",
                "database": "research",
            },
        )
        monkeypatch.setattr(
            graph_access,
            "retrieve_snapshot",
            lambda prompt, config: graph_calls.append(config) or {"status": "empty"},
        )
        monkeypatch.setattr(
            policy_readiness,
            "probe_gr00t",
            lambda _, **_kwargs: {
                "policy_protocol": {
                    "status": "passed",
                    "code": "policy_protocol_available",
                },
                "policy_model": {"status": "passed", "code": "policy_model_verified"},
                "policy_transport": {
                    "status": "passed",
                    "code": "policy_transport_verified",
                },
                "evidence": {
                    "profile": "gr00t-droid",
                    "expected_checkpoint": "nvidia/GR00T-N1.6-DROID",
                    "instance_id": "c" * 32,
                    "checkpoint_sha256": "a" * 64,
                    "config_sha256": "b" * 64,
                    "serializer_sha256": "d" * 64,
                    "modalities_sha256": "e" * 64,
                    "inference": "not_run",
                },
            },
        )
    headers = login(client)
    before_workspace = client.get("/api/workspaces/default").json()
    response = client.post(
        "/api/editor/readiness/check",
        headers=headers,
        json={"schema_version": 2, "workflow": workflow},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ready"] is True
    assert next(row for row in result["checks"] if row["id"] == "gpu") == {
        "id": "gpu",
        "required": True,
        "status": "passed",
        "code": "resource_headroom_observed",
    }
    assert len(calls) == 2 and calls[0] == calls[1]
    assert lease.read_bytes() == b"existing lease, never rewrite"
    assert (lease.stat().st_ino, lease.stat().st_mtime_ns) == (
        before.st_ino,
        before.st_mtime_ns,
    )
    assert client.get("/api/workspaces/default").json() == before_workspace
    assert GPU_UUID not in response.text
    if workflow == "a2_gr00t":
        assert len(graph_calls) == 1 and graph_calls[0]["database"] == "research"
        assert result["policy"]["inference"] == "not_run"
        monkeypatch.setattr(graph_access, "configuration", lambda: None)
        result = client.post(
            "/api/editor/readiness/check",
            headers=headers,
            json={"schema_version": 2, "workflow": workflow},
        ).json()
        assert result["ready"] is False
        assert (
            next(row for row in result["checks"] if row["id"] == "graph")["code"]
            == "graph_not_configured"
        )


@pytest.mark.parametrize("source", ["session", "server"])
@pytest.mark.parametrize("workflow", ["graph_generation", "agentic_generation"])
def test_provider_opt_in_reads_exact_model_and_can_pass_without_inference(
    client, monkeypatch, source, workflow
):
    import json
    from contextlib import contextmanager

    import httpx

    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        readiness,
        readiness_worker,
    )

    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        policy_readiness,
        resource_readiness,
    )

    monkeypatch.setattr(
        policy_readiness,
        "probe_gr00t",
        lambda *args: pytest.fail("No policy RPC in generation"),
    )
    monkeypatch.setattr(
        resource_readiness, "probe_gpu", lambda config: "resource_headroom_observed"
    )
    headers = login(client)
    secret = "synthetic-private-provider-key"
    config = {
        "provider": "openai",
        "api_key": secret,
        "model": "gpt-6-astra",
        "base_url": "https://api.openai.com/v1",
    }
    if source == "session":
        assert (
            client.put(
                "/api/model-settings",
                headers=headers,
                json={
                    "provider": "openai",
                    "model": config["model"],
                    "api_key": secret,
                },
            ).status_code
            == 200
        )
    else:
        monkeypatch.setattr(generation, "configuration", lambda: dict(config))
    graph = {
        "uri": "bolt://127.0.0.1:7688",
        "user": "u",
        "password": "graph-secret",
        "database": "research",
    }
    monkeypatch.setattr(graph_access, "configuration", lambda: graph)
    monkeypatch.setattr(
        graph_access, "retrieve_snapshot", lambda *args: {"status": "empty"}
    )
    monkeypatch.setattr(readiness, "run_readiness_worker", readiness_worker.run_checks)
    calls = []

    class HTTP:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
            assert 0 < kwargs["timeout"] <= 3

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        @contextmanager
        def stream(self, method, url, *, headers):
            calls.append((method, url))
            assert headers["Authorization"] == "Bearer " + secret
            assert headers["Accept-Encoding"] == "identity"

            class Response:
                status_code = 200
                headers = {}

                def iter_raw(self):
                    yield json.dumps({"object": "model", "id": "gpt-6-astra"}).encode()

            yield Response()

    monkeypatch.setattr(httpx, "Client", HTTP)
    before = client.get("/api/workspaces/default").json()
    body = {"schema_version": 2, "workflow": workflow}
    ordinary = client.post("/api/editor/readiness/check", headers=headers, json=body)
    assert ordinary.status_code == 200 and not ordinary.json()["ready"]
    assert calls == []
    response = client.post(
        "/api/editor/readiness/check",
        headers=headers,
        json={**body, "check_provider": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["ready"] is True
    row = next(
        row for row in response.json()["checks"] if row["id"] == "generation_model"
    )
    assert row["status"] == "passed" and row["code"] == "generation_model_readable"
    assert calls == [("GET", "https://api.openai.com/v1/models/gpt-6-astra")]
    assert secret not in response.text and "graph-secret" not in response.text
    assert client.get("/api/workspaces/default").json() == before
    assert (
        client.get(f"/api/editor/readiness?version=2&workflow={workflow}").json()[
            "ready"
        ]
        is False
    )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "case,expected",
    [
        ("duplicate", "generation_metadata_invalid"),
        ("http_timeout", "generation_check_timeout"),
        ("auth", "generation_authentication_failed"),
        ("forbidden", "generation_permission_denied"),
        ("missing", "generation_model_missing"),
        ("quota", "generation_rate_limited"),
        ("redirect", "generation_redirect_refused"),
        ("server", "generation_provider_unavailable"),
        ("wrong_id", "generation_model_mismatch"),
        ("object", "generation_metadata_invalid"),
        ("oversize", "generation_metadata_invalid"),
        ("compression", "generation_metadata_invalid"),
        ("slow", "generation_check_timeout"),
        ("malformed", "generation_metadata_invalid"),
    ],
)
def test_provider_read_failures_are_static_and_never_retried(
    monkeypatch, case, expected
):
    from contextlib import contextmanager

    import httpx

    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        provider_readiness as provider,
    )

    now = [0.0]
    monkeypatch.setattr(provider.time, "monotonic", lambda: now[0])
    calls = []
    status = {
        "auth": 401,
        "forbidden": 403,
        "missing": 404,
        "quota": 429,
        "redirect": 302,
        "server": 503,
    }.get(case, 200)

    class Response:
        status_code = status
        headers = {"content-encoding": "gzip"} if case == "compression" else {}

        def iter_raw(self):
            assert status == 200, "Error/redirect bodies must never be consumed"
            if case == "slow":
                now[0] = 5
            yield {
                "duplicate": b'{"id":"wrong","id":"gpt-6-astra","object":"model"}',
                "wrong_id": b'{"id":"gpt-6-astra ","object":"model"}',
                "object": b'{"id":"gpt-6-astra","object":"other"}',
                "oversize": b"x" * 8193,
                "malformed": b"{",
            }.get(case, b'{"id":"gpt-6-astra","object":"model"}')

    class HTTP:
        def __init__(self, **options):
            assert options == {
                "trust_env": False,
                "follow_redirects": False,
                "timeout": 2,
            }

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        @contextmanager
        def stream(self, *args, **kwargs):
            calls.append(args)
            if case == "http_timeout":
                raise httpx.ReadTimeout("private-key-never-publish")
            yield Response()

    monkeypatch.setattr(httpx, "Client", HTTP)
    assert (
        provider.probe_provider(
            {
                "provider": "openai",
                "api_key": "private-key-never-publish",
                "model": "gpt-6-astra",
                "base_url": "https://api.openai.com/v1",
            }
        )
        == expected
    )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "case,expected",
    [
        ("ok", "resource_headroom_observed"),
        ("late", "resource_unknown"),
        ("missing_budget", "resource_unknown"),
        ("invalid_budget", "resource_unknown"),
        ("missing_lease", "resource_unknown"),
        ("busy", "resource_lease_busy"),
        ("hidden", "resource_hidden"),
        ("cuda_hidden", "resource_hidden"),
        ("ambiguous", "resource_ambiguous"),
        ("cuda_ordinal", "resource_ambiguous"),
        ("insufficient", "resource_insufficient"),
        ("changed", "resource_device_changed"),
        ("lease_changed", "resource_device_changed"),
        ("malformed", "resource_unknown"),
        ("oversize", "resource_unknown"),
        ("mig", "resource_unknown"),
        ("unknown_mig", "resource_unknown"),
        ("visibility_changed", "resource_device_changed"),
    ],
)
def test_gpu_resource_evidence_is_bounded_visible_and_read_only(
    monkeypatch, tmp_path, case, expected
):
    import fcntl

    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        resource_readiness as resource,
    )

    lease = tmp_path / "existing.lock"
    lease.write_bytes(b"lease")
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    monkeypatch.delenv("NVIDIA_VISIBLE_DEVICES", raising=False)
    config = {
        "min_free_mib": "2048",
        "uuid": None,
        "lease": str(lease),
        "CUDA_VISIBLE_DEVICES": None,
        "NVIDIA_VISIBLE_DEVICES": None,
    }
    now = [0.0]
    monkeypatch.setattr(resource.time, "monotonic", lambda: now[0])
    if case == "missing_budget":
        config["min_free_mib"] = None
    if case == "invalid_budget":
        config["min_free_mib"] = " 2048"
    if case == "missing_lease":
        lease.unlink()
    for name, value in (
        {"NVIDIA_VISIBLE_DEVICES": "none"}
        if case == "hidden"
        else (
            {"CUDA_VISIBLE_DEVICES": ""}
            if case == "cuda_hidden"
            else {"CUDA_VISIBLE_DEVICES": "1"} if case == "cuda_ordinal" else {}
        )
    ).items():
        config[name] = value
        monkeypatch.setenv(name, value)
    if case == "visibility_changed":
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "none")
    calls = []

    def metadata(deadline):
        calls.append(deadline)
        if case == "late":
            now[0] = 4
        if case == "lease_changed":
            lease.unlink()
            lease.write_bytes(b"replacement")
        uuid = (
            GPU_UUID
            if case != "changed" or len(calls) == 1
            else GPU_UUID.replace("a", "f")
        )
        free = 100 if case == "insufficient" and len(calls) == 2 else 4096
        raw = f"0, {uuid}, {free}, 8192, Disabled\n"
        if case in ("ambiguous", "cuda_ordinal"):
            raw += f"1, {GPU_UUID.replace('a', 'f')}, 4096, 8192, Disabled\n"
        return {
            "malformed": "not metadata",
            "oversize": "x" * 16385,
            "mig": raw.replace("Disabled", "Enabled"),
            "unknown_mig": raw.replace(", Disabled", ""),
        }.get(case, raw)

    monkeypatch.setattr(resource, "query_gpu", metadata)
    if case == "busy":
        with lease.open("rb") as fd:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert resource.probe_gpu(config) == expected
    else:
        assert resource.probe_gpu(config) == expected
    if case == "missing_lease":
        assert not lease.exists()
    elif case != "lease_changed":
        assert lease.read_bytes() == b"lease"
    if len(calls) == 2:
        assert calls[0] == calls[1]
    if case == "late":
        assert (
            len(calls) == 1
        ), "Never start a second GPU read after its shared deadline"


@pytest.mark.parametrize("fault", [None, "oversize", "timeout", "exit"])
def test_nvidia_metadata_transport_has_total_deadline_and_output_bound(
    monkeypatch, fault
):
    import os
    import threading
    import time

    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        resource_readiness as resource,
    )

    payload = f"0, {GPU_UUID}, 4096, 8192, Disabled\n".encode()
    if fault == "oversize":
        payload = b"x" * 16385
    calls = []
    children = []

    class Child:
        def __init__(self, argv, **options):
            calls.append((argv, options))
            read, write = os.pipe()
            self.stdout = os.fdopen(read, "rb", buffering=0)

            def serve():
                with os.fdopen(write, "wb") as output:
                    output.write(payload)

            self.thread = threading.Thread(target=serve)
            self.thread.start()
            children.append(self)

        def poll(self):
            return None if self.thread.is_alive() else 0

        def kill(self):
            pass

        def wait(self, timeout):
            self.thread.join(timeout)
            assert not self.thread.is_alive()
            return 1 if fault == "exit" else 0

    monkeypatch.setattr(resource.subprocess, "Popen", Child)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", GPU_UUID)
    monkeypatch.setenv("NVIDIA_VISIBLE_DEVICES", GPU_UUID)
    monkeypatch.setenv("HTTPS_PROXY", "http://must-not-use")
    deadline = time.monotonic() + (2 if fault != "timeout" else -1)
    if fault is None:
        assert resource.query_gpu(deadline) == payload.decode()
    else:
        with pytest.raises((ValueError, TimeoutError)):
            resource.query_gpu(deadline)
    if fault == "timeout":
        assert calls == [], "An expired read budget must not spawn nvidia-smi"
        return
    assert len(calls) == 1
    argv, options = calls[0]
    assert argv == [
        "nvidia-smi",
        "--query-gpu=index,uuid,memory.free,memory.total,mig.mode.current",
        "--format=csv,noheader,nounits",
    ]
    assert options["env"]["CUDA_VISIBLE_DEVICES"] == GPU_UUID
    assert options["env"]["NVIDIA_VISIBLE_DEVICES"] == GPU_UUID
    assert "HTTPS_PROXY" not in options["env"]
    assert children[0].stdout.closed


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_provider_check_requires_literal_boolean(client, monkeypatch, value):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    monkeypatch.setattr(
        readiness,
        "run_readiness_worker",
        lambda _: pytest.fail("No worker for invalid consent"),
    )
    assert (
        client.post(
            "/api/editor/readiness/check",
            headers=headers,
            json={
                "schema_version": 2,
                "workflow": "graph_generation",
                "check_provider": value,
            },
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "override",
    [
        {"provider": "gemini"},
        {"base_url": "http://api.openai.com/v1"},
        {"base_url": "https://api.openai.com/v1?redirect=x"},
        {"base_url": "https://untrusted.invalid/v1"},
        {"model": "gpt-6-astra "},
        {"model": "GPT-6-astra"},
        {"model": "other"},
    ],
)
def test_unsupported_provider_profile_never_creates_http_client(monkeypatch, override):
    import httpx

    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        provider_readiness as provider,
    )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **_: pytest.fail("Unsupported profile must not contact provider"),
    )
    assert (
        provider.probe_provider(
            {
                "api_key": "private-provider-secret",
                "provider": "openai",
                "model": "gpt-6-astra",
                "base_url": "https://api.openai.com/v1",
                **override,
            }
        )
        == "generation_provider_unsupported"
    )


@pytest.mark.parametrize(
    "change", ["same_key_replacement", "forget", "expiry", "server_config"]
)
@pytest.mark.parametrize("workflow", ["graph_generation", "agentic_generation"])
def test_provider_completion_retires_changed_authority_without_workflow_grants(
    client, monkeypatch, change, workflow
):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    config = {
        "provider": "openai",
        "api_key": "synthetic-private-provider-key",
        "model": "gpt-6-astra",
        "base_url": "https://api.openai.com/v1",
    }
    if change == "server_config":
        monkeypatch.setattr(generation, "configuration", lambda: dict(config))
    else:
        assert (
            client.put(
                "/api/model-settings",
                headers=headers,
                json={key: config[key] for key in ("provider", "api_key", "model")},
            ).status_code
            == 200
        )
    monkeypatch.setattr(
        client.app.state.workflow_authorization,
        "capture",
        lambda *a, **kw: pytest.fail("Readiness must never issue grants"),
    )

    def worker(envelope):
        assert envelope["provider_config"]["api_key"] == config["api_key"]
        if change == "same_key_replacement":
            assert (
                client.put(
                    "/api/model-settings",
                    headers=headers,
                    json={key: config[key] for key in ("provider", "api_key", "model")},
                ).status_code
                == 200
            )
        elif change == "forget":
            assert (
                client.delete("/api/model-settings", headers=headers).status_code == 200
            )
        elif change == "expiry":
            settings = client.app.state.model_settings
            now = settings.clock()
            monkeypatch.setattr(settings, "clock", lambda: now + 7201)
        else:
            config["api_key"] = "different-private-server-key"
        return {
            "runtime": "runtime_available",
            "graph": "graph_retrieval_empty",
            "policy": None,
            "provider": "generation_model_readable",
        }

    monkeypatch.setattr(readiness, "run_readiness_worker", worker)
    response = client.post(
        "/api/editor/readiness/check",
        headers=headers,
        json={"schema_version": 2, "workflow": workflow, "check_provider": True},
    )
    assert response.status_code == 200, response.text
    row = next(
        row for row in response.json()["checks"] if row["id"] == "generation_model"
    )
    assert row["code"] == "configuration_changed" and row["status"] != "passed"
    assert not response.json()["ready"]


def test_provider_missing_http_dependency_stays_static(monkeypatch):
    import sys

    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        provider_readiness as provider,
    )

    monkeypatch.setitem(sys.modules, "httpx", None)
    assert (
        provider.probe_provider(
            {
                "api_key": "private-provider-secret",
                "provider": "openai",
                "model": "gpt-6-astra",
                "base_url": "https://api.openai.com/v1",
            }
        )
        == "generation_provider_unavailable"
    )


@pytest.mark.parametrize(
    "field", ["ARENA_WORKBENCH_GPU_MIN_FREE_MIB", "CUDA_VISIBLE_DEVICES"]
)
def test_resource_completion_retires_changed_operator_configuration(
    client, monkeypatch, field
):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)

    def worker(envelope):
        monkeypatch.setenv(field, "changed")
        return {
            "runtime": "runtime_available",
            "graph": "not_required",
            "policy": None,
            "gpu": "resource_headroom_observed",
        }

    monkeypatch.setattr(readiness, "run_readiness_worker", worker)
    result = client.post(
        "/api/editor/readiness/check",
        headers=headers,
        json={"schema_version": 2, "workflow": "build"},
    ).json()
    assert (
        next(row for row in result["checks"] if row["id"] == "gpu")["code"]
        == "configuration_changed"
    )
    assert result["ready"] is False


@pytest.mark.parametrize(
    "extra",
    [
        {"yaml_text": "not_an_arena_spec: true"},
        {"document_id": "a" * 32},
        {"prompt": " "},
    ],
)
def test_provider_consent_never_bypasses_source_validation(client, monkeypatch, extra):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    monkeypatch.setattr(
        readiness,
        "run_readiness_worker",
        lambda _: pytest.fail("Invalid source must not dispatch reads"),
    )
    assert (
        client.post(
            "/api/editor/readiness/check",
            headers=headers,
            json={
                "schema_version": 2,
                "workflow": "graph_generation",
                "check_provider": True,
                **extra,
            },
        ).status_code
        == 422
    )


ORIGIN = "http://127.0.0.1:3000"


@pytest.mark.parametrize("port", [None, "5559", "1", "65535"])
def test_legacy_readiness_captures_configured_endpoint_for_metadata_and_tcp(client, monkeypatch, port):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    if port is None:
        monkeypatch.delenv("ARENA_WORKBENCH_GR00T_PORT", raising=False)
    else:
        monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", port)
    headers = login(client)
    expected = 5555 if port is None else int(port)
    before = client.get("/api/workspaces/default").json()
    assert client.get("/api/editor/readiness").json()["policy_servers"][0]["port"] == expected
    calls = []
    monkeypatch.setattr(readiness, "probe_graph", lambda _: "not_configured")

    def tcp(row):
        calls.append((row["remote_host"], row["remote_port"]))
        return "reachable"

    monkeypatch.setattr(readiness, "probe_policy", tcp)
    result = client.post("/api/editor/readiness/check", json={}, headers=headers)
    assert result.status_code == 200, result.text
    assert calls == [("127.0.0.1", expected), ("127.0.0.1", 8000)]
    assert result.json()["policy_servers"][0] == {
        "profile": "gr00t-droid", "host": "127.0.0.1", "port": expected, "status": "reachable",
    }
    assert client.get("/api/workspaces/default").json() == before


@pytest.mark.parametrize("change", [False, True])
def test_legacy_readiness_never_labels_replacement_endpoint_reachable(client, monkeypatch, change):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", "5559")
    headers = login(client)
    monkeypatch.setattr(readiness, "probe_graph", lambda _: "not_configured")

    def tcp(row):
        if change:
            monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", "5560")
        return "reachable"

    monkeypatch.setattr(readiness, "probe_policy", tcp)
    result = client.post("/api/editor/readiness/check", json={}, headers=headers).json()
    assert result["policy_servers"][0]["port"] == (5560 if change else 5559)
    assert result["policy_servers"][0]["status"] == ("not_checked" if change else "reachable")


@pytest.mark.parametrize("port", [None, 5559, 1, 65535])
def test_private_policy_worker_uses_captured_port_not_environment(monkeypatch, port):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness_worker, policy_readiness

    monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", "invalid-after-capture")
    calls = []
    monkeypatch.setattr(policy_readiness, "probe_gr00t", lambda expected, **kwargs: calls.append((expected, kwargs)))
    envelope = {"workflow": "a2_gr00t", "prompt": "readiness", "graph_config": None, "expectations": None}
    if port is not None:
        envelope["gr00t_port"] = port
    assert readiness_worker.run_checks(envelope)["policy"] is None
    assert calls == [(None, {"port": 5555 if port is None else port})]


@pytest.mark.parametrize("port", [None, True, 0, -1, 65536, 5559.0, "5559"])
def test_private_policy_worker_rejects_invalid_explicit_port_before_reads(monkeypatch, port):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness_worker, policy_readiness

    monkeypatch.setattr(policy_readiness, "probe_gr00t", lambda *_a, **_k: pytest.fail("Invalid port reached RPC"))
    with pytest.raises(ValueError):
        readiness_worker.run_checks({"workflow": "a2_gr00t", "prompt": "readiness", "graph_config": None,
                                     "expectations": None, "gr00t_port": port})


@pytest.mark.parametrize("workflow", ["agentic_generation", "graph_generation", "build"])
def test_nonpolicy_worker_rejects_policy_endpoint_override(monkeypatch, workflow):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness_worker

    with pytest.raises(ValueError):
        readiness_worker.run_checks({"workflow": workflow, "prompt": "readiness", "graph_config": None,
                                     "expectations": None, "gr00t_port": 5559})


@pytest.mark.parametrize("change", [None, "5560", "invalid"])
def test_a2_readiness_captures_port_and_retires_changed_endpoint(client, monkeypatch, change):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness, policy_readiness

    monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", "5559")
    monkeypatch.setattr(policy_readiness, "expected_hashes", lambda: None)
    headers = login(client)
    calls = []

    def worker(envelope):
        calls.append(envelope)
        assert envelope["gr00t_port"] == 5559
        if change:
            monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", change)
        return {"runtime": "runtime_available", "graph": "graph_not_configured", "policy": {
            "policy_protocol": {"status": "passed", "code": "policy_protocol_available"},
            "policy_model": {"status": "passed", "code": "policy_model_verified"},
            "policy_transport": {"status": "passed", "code": "policy_transport_verified"},
            "evidence": {"fixture": "bound-to-captured-port"},
        }}

    monkeypatch.setattr(readiness, "run_readiness_worker", worker)
    result = client.post("/api/editor/readiness/check", headers=headers,
                         json={"schema_version": 2, "workflow": "a2_gr00t"})
    assert result.status_code == 200, result.text
    rows = {row["id"]: row for row in result.json()["checks"]}
    assert len(calls) == 1
    assert rows["policy_model"]["code"] == ("configuration_changed" if change else "policy_model_verified")
    assert (result.json()["policy"] is None) is bool(change)
    if change:
        assert rows["policy_transport"]["status"] == "not_checked"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(editor_execution, "make_snapshot_service", lambda _root: None)
    monkeypatch.setattr(generation, "configuration", lambda: None)
    monkeypatch.setattr(graph_access, "configuration", lambda: None)
    monkeypatch.setattr(
        socket.socket, "connect", lambda *args: pytest.fail("Unexpected network probe")
    )
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        yield client


def login(client):
    session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
    return {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}


def test_v2_metadata_is_exact_workflow_specific_and_never_infers_readiness(client):
    login(client)
    before = client.get("/api/workspaces/default").json()
    response = client.get("/api/editor/readiness?version=2&workflow=a2_gr00t")
    assert response.status_code == 200
    result = response.json()
    assert result["schema_version"] == 2
    assert set(result) == {
        "schema_version",
        "workflow",
        "checked_at",
        "checks",
        "policy",
        "ready",
    }
    assert result["workflow"] == "a2_gr00t" and result["checked_at"] is None
    assert result["policy"] is None and result["ready"] is False
    checks = {row["id"]: row for row in result["checks"]}
    assert set(checks) == {
        "api_contract",
        "runtime",
        "generation_model",
        "graph",
        "policy_protocol",
        "policy_model",
        "policy_transport",
        "gpu",
    }
    assert all(
        set(row) == {"id", "status", "code", "required"} for row in checks.values()
    )
    assert checks["graph"]["required"] is True
    assert checks["graph"]["code"] == "graph_not_configured"
    assert checks["policy_model"]["required"] is True
    assert checks["policy_model"]["status"] == "not_checked"
    assert checks["gpu"]["code"] == "resource_unknown"
    assert checks["generation_model"]["code"] == "not_required"
    assert client.get("/api/workspaces/default").json() == before


def test_v2_check_uses_private_worker_and_preserves_unknowns(client, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    config = {
        "uri": "bolt://127.0.0.1:7688",
        "user": "operator",
        "password": "private-graph-secret",
        "database": "research",
    }
    monkeypatch.setattr(graph_access, "configuration", lambda: config)
    calls = []

    def worker(envelope):
        calls.append(envelope)
        return {
            "runtime": "runtime_available",
            "graph": "graph_retrieval_empty",
            "policy": None,
        }

    monkeypatch.setattr(readiness, "run_readiness_worker", worker, raising=False)
    before = client.get("/api/workspaces/default").json()
    result = client.post(
        "/api/editor/readiness/check",
        headers=headers,
        json={
            "schema_version": 2,
            "workflow": "graph_generation",
            "prompt": "Pick up a cube",
        },
    )
    assert result.status_code == 200, result.text
    rows = {row["id"]: row for row in result.json()["checks"]}
    assert rows["graph"]["code"] == "graph_retrieval_empty"
    assert rows["graph"]["status"] == "passed"
    assert rows["runtime"]["status"] == "passed"
    assert rows["generation_model"]["status"] != "passed"
    assert not result.json()["ready"]
    assert len(calls) == 1 and calls[0]["graph_config"] == config
    assert calls[0]["prompt"] == "Pick up a cube"
    assert config["password"] not in result.text
    assert client.get("/api/workspaces/default").json() == before


@pytest.mark.parametrize(
    "workflow", ["agentic_generation", "graph_generation", "a2_gr00t"]
)
def test_worker_retrieves_with_private_configuration_and_returns_only_static_codes(
    monkeypatch,
    workflow,
):
    import importlib.util

    name = "isaaclab_arena_examples.agentic_environment_generation.web_api.readiness_worker"
    assert (
        importlib.util.find_spec(name) is not None
    ), "A real worker-context adapter is required"
    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        readiness_worker,
    )

    config = {
        "uri": "bolt://127.0.0.1:7688",
        "user": "operator",
        "password": "private-secret",
        "database": "research",
    }
    calls = []
    monkeypatch.setattr(
        graph_access,
        "retrieve_snapshot",
        lambda prompt, actual: calls.append((prompt, actual)) or {"status": "empty"},
    )
    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        policy_readiness,
    )

    monkeypatch.setattr(policy_readiness, "probe_gr00t", lambda expected, **_kwargs: None)
    result = readiness_worker.run_checks(
        {
            "workflow": workflow,
            "prompt": "lift cube",
            "graph_config": config,
            "expectations": None,
        }
    )
    assert calls == [("lift cube", config)]
    assert result == {
        "runtime": "runtime_available",
        "graph": "graph_retrieval_empty",
        "policy": None,
    }


def test_worker_process_receipt_rejects_unknown_or_arbitrary_metadata():
    import importlib.util

    name = "isaaclab_arena_examples.agentic_environment_generation.web_api.readiness_process"
    assert (
        importlib.util.find_spec(name) is not None
    ), "Bounded process receipt validation is required"
    from isaaclab_arena_examples.agentic_environment_generation.web_api.readiness_process import (
        validate_receipt,
    )

    result = {
        "runtime": "runtime_available",
        "graph": "graph_retrieval_empty",
        "policy": None,
    }
    assert validate_receipt(result) == result
    for bad in (
        {**result, "secret": "raw"},
        {**result, "graph": "private-diagnostic"},
        {**result, "runtime": True},
    ):
        with pytest.raises(ValueError):
            validate_receipt(bad)


@pytest.mark.parametrize(
    "workflow,missing",
    [
        ("a2_gr00t", "/api/editor/evaluate"),
        ("build", "/api/editor/build"),
        ("graph_generation", "/api/editor/generate"),
    ],
)
def test_v2_api_contract_requires_actual_routes_and_advertised_capability(
    client, monkeypatch, workflow, missing
):
    login(client)

    def row():
        result = client.get(
            f"/api/editor/readiness?version=2&workflow={workflow}"
        ).json()
        return next(row for row in result["checks"] if row["id"] == "api_contract")

    assert row()["status"] == "passed"
    if workflow == "a2_gr00t":
        monkeypatch.setattr(
            client.app.state.editor_execution, "evaluation_available", False
        )
        assert row()["code"] == "api_contract_unavailable"
        monkeypatch.setattr(
            client.app.state.editor_execution, "evaluation_available", True
        )
    client.app.router.routes[:] = [
        route
        for route in client.app.router.routes
        if getattr(route, "path", None) != missing
    ]
    assert row()["status"] == "unavailable"
    assert row()["code"] == "api_contract_unavailable"


@pytest.mark.parametrize("fault", [None, "duplicate", "oversize", "cleanup"])
@pytest.mark.parametrize("port", [None, 5559])
def test_readiness_process_uses_bounded_private_pipes_and_retains_unknown_cleanup(
    monkeypatch, fault, port
):
    """Real pipe I/O, simulated process/group identity; not subprocess execution evidence."""
    import json
    import os
    import threading

    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        readiness_process as process,
    )

    envelope = {
        "workflow": "graph_generation",
        "prompt": "cube",
        "graph_config": {"password": "private-secret"},
        "expectations": None,
        "check_provider": True,
        "provider_config": {"api_key": "private-provider-key"},
    }
    expected = {"runtime": "runtime_available", "graph": "not_required", "policy": None}
    if port is not None:
        envelope.update(workflow="a2_gr00t", gr00t_port=port)
    reply = json.dumps(expected).encode()
    if fault == "duplicate":
        reply = b'{"runtime":"runtime_unavailable","runtime":"runtime_available","graph":"not_required","policy":null}'
    if fault == "oversize":
        reply = b"x" * 8193
    captured = []

    class Child:
        pid = 999999

        def __init__(self, argv, **options):
            captured.append((argv, options))
            read_in, write_in = os.pipe()
            read_out, write_out = os.pipe()
            self.stdin, self.stdout = os.fdopen(write_in, "wb", buffering=0), os.fdopen(
                read_out, "rb", buffering=0
            )

            def serve():
                with os.fdopen(read_in, "rb") as source:
                    captured.append(json.loads(source.read()))
                with os.fdopen(write_out, "wb") as target:
                    target.write(reply)

            self.thread = threading.Thread(target=serve)
            self.thread.start()

        def wait(self, timeout):
            self.thread.join(timeout)
            assert not self.thread.is_alive()
            return 0

    class Group:
        def __init__(self, pid):
            assert pid == 999999

        def stop(self):
            if fault == "cleanup":
                raise RuntimeError("Unknown cleanup")

    monkeypatch.setenv("READINESS_TEST_SECRET", "must-not-be-inherited")
    monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", "invalid-after-capture")
    monkeypatch.setenv("HOME", "/synthetic/private-provider-key/home")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", GPU_UUID)
    monkeypatch.setenv("NVIDIA_VISIBLE_DEVICES", "none")
    monkeypatch.setattr(process.subprocess, "Popen", Child)
    monkeypatch.setattr(process, "OwnedProcessGroup", Group)
    monkeypatch.setattr(process, "_PENDING", [])
    try:
        if fault is None:
            assert process.run_worker(envelope) == expected
        else:
            with pytest.raises((ValueError, RuntimeError)):
                process.run_worker(envelope)
        assert captured[1] == envelope
        argv, options = captured[0]
        assert "private-secret" not in str(argv) + str(options["env"])
        assert "private-provider-key" not in str(argv) + str(options["env"])
        assert "READINESS_TEST_SECRET" not in options["env"]
        assert "ARENA_WORKBENCH_GR00T_PORT" not in options["env"]
        assert options["env"].get("CUDA_VISIBLE_DEVICES") == GPU_UUID
        assert options["env"].get("NVIDIA_VISIBLE_DEVICES") == "none"
        assert options["start_new_session"] is True
        assert process.cleanup_pending() is (fault == "cleanup")
    finally:
        for child, _group, owner in process._PENDING:
            child.stdin.close()
            child.stdout.close()
            os.close(owner)
        process._PENDING.clear()


@pytest.mark.parametrize(
    "character", ["a", "\u754c", "\U0001f600"], ids=["ascii", "bmp", "astral"]
)
@pytest.mark.parametrize("length", [16000, 16001])
def test_v2_prompt_boundary_crosses_actual_private_worker_serialization(
    client, monkeypatch, character, length
):
    """Exercise API and real pipe serialization with a synthetic child, never live probes."""
    import json
    import os
    import threading

    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        readiness_process as process,
    )
    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        readiness_worker,
    )

    prompt = character * length
    config = {
        "uri": "bolt://127.0.0.1:7688",
        "user": "operator",
        "password": "synthetic-private-graph-secret",
        "database": "research",
    }
    monkeypatch.setattr(graph_access, "configuration", lambda: config)
    retrieved = []
    monkeypatch.setattr(
        graph_access,
        "retrieve_snapshot",
        lambda text, actual: retrieved.append((text, actual)) or {"status": "empty"},
    )
    captured = []
    children = []

    class Child:
        pid = 999999

        def __init__(self, argv, **options):
            assert config["password"] not in str(argv) + str(options["env"])
            read_in, write_in = os.pipe()
            read_out, write_out = os.pipe()
            self.stdin, self.stdout = os.fdopen(write_in, "wb", buffering=0), os.fdopen(
                read_out, "rb", buffering=0
            )
            self.error = None

            def serve():
                with (
                    os.fdopen(read_in, "rb") as source,
                    os.fdopen(write_out, "wb") as target,
                ):
                    try:
                        raw = source.read()
                        captured.append(raw)
                        receipt = readiness_worker.run_checks(
                            json.loads(raw.decode("utf-8"))
                        )
                        target.write(
                            json.dumps(receipt, ensure_ascii=False).encode("utf-8")
                        )
                    except Exception as error:
                        self.error = error

            self.thread = threading.Thread(target=serve)
            children.append(self)
            self.thread.start()

        def wait(self, timeout):
            self.thread.join(timeout)
            assert not self.thread.is_alive()
            return 0 if self.error is None else 1

    class Group:
        def __init__(self, pid):
            assert pid == 999999

        def stop(self):
            pass

    monkeypatch.setattr(process.subprocess, "Popen", Child)
    monkeypatch.setattr(process, "OwnedProcessGroup", Group)
    monkeypatch.setattr(process, "_PENDING", [])
    headers = login(client)
    before = client.get("/api/workspaces/default").json()
    response = client.post(
        "/api/editor/readiness/check",
        headers=headers,
        json={"schema_version": 2, "workflow": "graph_generation", "prompt": prompt},
    )
    if length > 16000:
        assert response.status_code == 422
        assert children == [] and retrieved == []
        with pytest.raises(ValueError, match="Invalid readiness prompt"):
            readiness_worker.run_checks(
                {
                    "workflow": "graph_generation",
                    "prompt": prompt,
                    "graph_config": config,
                    "expectations": None,
                }
            )
        assert retrieved == []
        return
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["checks"]}
    assert rows["runtime"]["code"] == "runtime_available"
    assert rows["graph"]["code"] == "graph_retrieval_empty"
    assert len(children) == 1 and children[0].error is None
    assert len(captured) == 1 and len(captured[0]) <= 96 * 1024
    assert captured[0].endswith(b"\n") and prompt.encode("utf-8") in captured[0]
    assert retrieved == [(prompt, config)]
    assert children[0].stdin.closed and children[0].stdout.closed
    assert not process.cleanup_pending()
    assert config["password"] not in response.text
    assert client.get("/api/workspaces/default").json() == before


def test_readiness_private_envelope_over_byte_budget_is_refused_before_spawn(
    monkeypatch,
):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        readiness_process as process,
    )

    monkeypatch.setattr(
        process.subprocess,
        "Popen",
        lambda *a, **kw: pytest.fail("Oversize input must not spawn"),
    )
    with pytest.raises(ValueError, match="Readiness input exceeds bound"):
        process.run_worker(
            {
                "workflow": "graph_generation",
                "prompt": "\U0001f600" * 16000,
                "graph_config": {"password": "x" * (96 * 1024)},
                "expectations": None,
            }
        )


@pytest.mark.parametrize(
    "workflow", ["agentic_generation", "graph_generation", "a2_gr00t"]
)
def test_v2_invalid_graph_profile_does_not_start_worker(client, monkeypatch, workflow):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    monkeypatch.setattr(
        graph_access,
        "configuration",
        lambda: {
            "uri": "bolt://127.0.0.1:7688",
            "user": "u",
            "password": "secret",
            "database": " invalid ",
        },
    )
    calls = []
    monkeypatch.setattr(
        readiness,
        "run_readiness_worker",
        lambda envelope: calls.append(envelope)
        or {
            "runtime": "runtime_available",
            "graph": "graph_retrieval_empty",
            "policy": None,
        },
    )
    response = client.post(
        "/api/editor/readiness/check",
        headers=headers,
        json={"schema_version": 2, "workflow": workflow, "check_provider": True},
    )
    assert response.status_code == 200
    assert calls == []
    assert (
        next(
            row for row in response.json()["checks"] if row["id"] == "generation_model"
        )["required"]
        is True
    )
    row = next(row for row in response.json()["checks"] if row["id"] == "graph")
    assert row == {
        "id": "graph",
        "status": "blocked",
        "code": "graph_invalid_configuration",
        "required": True,
    }


def test_v2_retires_policy_evidence_when_operator_pins_change(client, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    monkeypatch.setenv("ARENA_GR00T_CHECKPOINT_SHA256", "a" * 64)
    monkeypatch.setenv("ARENA_GR00T_CONFIG_SHA256", "b" * 64)

    def changed(envelope):
        monkeypatch.setenv("ARENA_GR00T_CONFIG_SHA256", "f" * 64)
        return {
            "runtime": "runtime_available",
            "graph": "not_required",
            "policy": {
                "policy_protocol": {
                    "status": "passed",
                    "code": "policy_protocol_available",
                },
                "policy_model": {"status": "passed", "code": "policy_model_verified"},
                "policy_transport": {
                    "status": "passed",
                    "code": "policy_transport_verified",
                },
                "evidence": {"instance_id": "c" * 32},
            },
        }

    monkeypatch.setattr(readiness, "run_readiness_worker", changed)
    result = client.post(
        "/api/editor/readiness/check",
        headers=headers,
        json={"schema_version": 2, "workflow": "a2_gr00t"},
    ).json()
    row = next(row for row in result["checks"] if row["id"] == "policy_model")
    assert row["status"] == "mismatch" and row["code"] == "configuration_changed"
    assert result["policy"] is None


@pytest.mark.parametrize("workflow", ["build", "agentic_generation"])
def test_worker_runtime_missing_simulator_remains_unavailable(monkeypatch, workflow):
    import importlib.util

    from isaaclab_arena_examples.agentic_environment_generation.web_api import (
        readiness_worker,
    )

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    result = readiness_worker.run_checks(
        {
            "workflow": workflow,
            "prompt": "readiness",
            "graph_config": None,
            "expectations": None,
        }
    )
    assert result == {
        "runtime": "runtime_unavailable",
        "graph": (
            "graph_not_configured"
            if workflow == "agentic_generation"
            else "not_required"
        ),
        "policy": None,
    }


@pytest.mark.parametrize(
    "extra",
    [
        {"schema_version": 2.0},
        {"prompt": None},
        {"yaml_text": None},
        {"document_id": None},
    ],
)
def test_v2_requires_literal_version_and_omitted_or_string_optional_fields(
    client, monkeypatch, extra
):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    calls = []
    monkeypatch.setattr(
        readiness,
        "run_readiness_worker",
        lambda value: calls.append(value)
        or {"runtime": "runtime_available", "graph": "not_required", "policy": None},
    )
    response = client.post(
        "/api/editor/readiness/check",
        headers=headers,
        json={"schema_version": 2, "workflow": "build", **extra},
    )
    assert response.status_code == 422
    assert calls == []


def test_readiness_reports_missing_configuration_without_network_or_jobs(client):
    headers = login(client)
    before = client.get("/api/workspaces/default").json()
    response = client.get("/api/editor/readiness")
    assert response.status_code == 200
    result = response.json()
    assert result["schema_version"] == 1
    assert result["provider"] == {
        "configured": False,
        "source": "none",
        "verification": "not_checked",
    }
    assert result["graph"] == {"configured": False, "status": "not_configured"}
    assert result["runtime"]["simulation"] == "not_checked"
    assert result["workflow"]["scenario_harness"] == "cli_only"
    assert result["workflow"]["evaluation_scope"] == "droid_fixed_profiles"
    assert result["workflow"]["research_versions"] is False
    assert all(row["status"] == "not_checked" for row in result["policy_servers"])
    assert client.get("/api/workspaces/default").json() == before
    assert client.post("/api/editor/readiness/check", json={}).status_code == 403
    assert (
        client.post(
            "/api/editor/readiness/check",
            headers=headers,
            json={"uri": "http://untrusted"},
        ).status_code
        == 422
    )


def test_explicit_checks_use_server_targets_without_provider_calls_or_job_writes(
    client, monkeypatch
):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    secret = "synthetic-provider-secret"
    saved = client.put(
        "/api/model-settings",
        headers=headers,
        json={"provider": "openai", "model": "test-model", "api_key": secret},
    )
    assert saved.status_code == 200
    config = {
        "uri": "bolt://127.0.0.1:7688",
        "user": "operator",
        "password": "synthetic-graph-secret",
        "database": "research",
    }
    monkeypatch.setattr(graph_access, "configuration", lambda: config)
    calls = []
    monkeypatch.setattr(
        readiness, "probe_graph", lambda actual: calls.append(actual) or "available"
    )
    monkeypatch.setattr(readiness, "probe_policy", lambda row: "unreachable")
    before = client.get("/api/workspaces/default").json()
    result = client.post("/api/editor/readiness/check", headers=headers, json={})
    assert result.status_code == 200
    assert calls == [config]
    assert result.json()["provider"] == {
        "configured": True,
        "source": "session",
        "verification": "not_checked",
    }
    assert result.json()["graph"] == {"configured": True, "status": "available"}
    assert result.json()["checked_at"] is not None
    assert all(
        row["status"] == "unreachable" for row in result.json()["policy_servers"]
    )
    assert secret not in result.text and config["password"] not in result.text
    assert client.get("/api/workspaces/default").json() == before
    assert (
        client.get("/api/editor/readiness").json()["graph"]["status"] == "not_checked"
    )
    assert calls == [config]


def test_readiness_does_not_relabel_old_graph_probe_after_configuration_change(
    client, monkeypatch
):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    config = {
        "uri": "bolt://127.0.0.1:7688",
        "user": "operator",
        "password": "synthetic-graph-secret",
        "database": "research",
    }
    monkeypatch.setattr(graph_access, "configuration", lambda: config)

    def change(_config):
        monkeypatch.setattr(graph_access, "configuration", lambda: None)
        return "available"

    monkeypatch.setattr(readiness, "probe_graph", change)
    monkeypatch.setattr(readiness, "probe_policy", lambda row: "unreachable")
    result = client.post("/api/editor/readiness/check", headers=headers, json={}).json()
    assert result["graph"] == {"configured": False, "status": "configuration_changed"}


def test_revoked_session_cannot_receive_completed_check(client, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    token = client.cookies.get(client.app.state.cookie_name)

    def revoke(_config):
        client.app.state.sessions.revoke(token)
        return "available"

    monkeypatch.setattr(readiness, "probe_graph", revoke)
    monkeypatch.setattr(readiness, "probe_policy", lambda row: "unreachable")
    assert (
        client.post("/api/editor/readiness/check", headers=headers, json={}).status_code
        == 401
    )


def test_graph_probe_uses_explicit_database_read_and_rolls_back(monkeypatch):
    from unittest.mock import MagicMock

    from isaaclab_arena.agentic_environment_generation import lpg_neo4j_sync
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    driver = MagicMock()
    factory = MagicMock(return_value=driver)
    monkeypatch.setattr(lpg_neo4j_sync, "get_neo4j_driver", factory)
    transaction = (
        driver.session.return_value.__enter__.return_value.begin_transaction.return_value.__enter__.return_value
    )
    transaction.run.return_value.single.return_value = {"ready": 1}
    config = {
        "uri": "bolt://127.0.0.1:7688",
        "user": "operator",
        "password": "synthetic-secret",
        "database": "research",
    }
    assert readiness.probe_graph(config) == "available"
    driver.session.assert_called_once_with(
        database="research", default_access_mode="READ"
    )
    transaction.run.assert_called_once_with("RETURN 1 AS ready")
    transaction.rollback.assert_called_once()
    driver.close.assert_called_once()
    assert factory.call_args.kwargs["uri"] == config["uri"]
    assert factory.call_args.kwargs["max_transaction_retry_time"] == 0
    factory.reset_mock()
    assert readiness.probe_graph(None) == "not_configured"
    factory.assert_not_called()


def test_graph_probe_never_returns_raw_driver_errors(monkeypatch):
    from unittest.mock import MagicMock

    from neo4j.exceptions import AuthError

    from isaaclab_arena.agentic_environment_generation import lpg_neo4j_sync
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    config = {
        "uri": "bolt://127.0.0.1:7688",
        "user": "operator",
        "password": "synthetic-secret",
        "database": "research",
    }
    monkeypatch.setattr(
        lpg_neo4j_sync,
        "get_neo4j_driver",
        MagicMock(side_effect=AuthError(config["password"])),
    )
    assert readiness.probe_graph(config) == "authentication_failed"
    monkeypatch.setattr(
        lpg_neo4j_sync,
        "get_neo4j_driver",
        MagicMock(side_effect=RuntimeError(config["password"])),
    )
    assert readiness.probe_graph(config) == "unavailable"


@pytest.mark.parametrize("database", [" research ", "a" * 129])
def test_graph_readiness_rejects_retriever_incompatible_database_before_probe(
    client, monkeypatch, database
):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    login(client)
    config = {
        "uri": "bolt://127.0.0.1:7688",
        "user": "operator",
        "password": "synthetic-secret",
        "database": database,
    }
    monkeypatch.setattr(graph_access, "configuration", lambda: config)
    assert client.get("/api/editor/readiness").json()["graph"] == {
        "configured": True,
        "status": "invalid_configuration",
    }
    assert readiness.probe_graph(config) == "invalid_configuration"


@pytest.mark.parametrize("wait_for_http_timeout", [False, True])
def test_busy_probe_retains_slot_until_thread_finishes(
    client, monkeypatch, wait_for_http_timeout
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setattr(readiness, "_PROBE_SLOT", threading.BoundedSemaphore(1))

    def blocked(_config):
        entered.set()
        assert release.wait(15), "Probe fixture was not released"
        return "not_configured"

    original = readiness.probe_dependencies

    def tracked(config, profiles):
        try:
            return original(config, profiles)
        finally:
            finished.set()

    monkeypatch.setattr(readiness, "probe_graph", blocked)
    monkeypatch.setattr(readiness, "probe_policy", lambda row: "unreachable")
    monkeypatch.setattr(readiness, "probe_dependencies", tracked)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(
            client.post, "/api/editor/readiness/check", headers=headers, json={}
        )
        try:
            assert entered.wait(3)
            assert (
                client.post(
                    "/api/editor/readiness/check", headers=headers, json={}
                ).status_code
                == 429
            )
            if wait_for_http_timeout:
                timed_out = pending.result(timeout=12)
                assert timed_out.status_code == 200
                assert timed_out.json()["graph"]["status"] == "timeout"
                assert not finished.is_set()
                assert (
                    client.post(
                        "/api/editor/readiness/check", headers=headers, json={}
                    ).status_code
                    == 429
                )
        finally:
            release.set()
        assert finished.wait(3)
        assert pending.result(timeout=3).status_code == 200
    assert (
        client.post("/api/editor/readiness/check", headers=headers, json={}).status_code
        == 200
    )


def test_cancelled_request_does_not_release_running_probe_slot(monkeypatch):
    """Exercise actual coroutine cancellation with a blocked, mocked dependency thread."""
    import asyncio
    import threading

    from fastapi import HTTPException

    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setattr(readiness, "_PROBE_SLOT", threading.BoundedSemaphore(1))
    monkeypatch.setattr(graph_access, "configuration", lambda: None)
    monkeypatch.setattr(readiness, "require_session", lambda request: {})
    monkeypatch.setattr(
        readiness, "metadata", lambda *args: {"graph": {}, "policy_servers": [
            {"host": row["remote_host"], "port": row["remote_port"]} for row in readiness.configured_profiles()
        ]}
    )
    monkeypatch.setattr(
        readiness, "protect_public_record", lambda request, value: value
    )

    def blocked(_config):
        entered.set()
        assert release.wait(5)
        return "not_configured"

    original = readiness.probe_dependencies

    def tracked(config, profiles):
        try:
            return original(config, profiles)
        finally:
            finished.set()

    monkeypatch.setattr(readiness, "probe_graph", blocked)
    monkeypatch.setattr(readiness, "probe_policy", lambda row: "unreachable")
    monkeypatch.setattr(readiness, "probe_dependencies", tracked)

    async def run():
        task = asyncio.create_task(
            readiness.check(None, readiness.CheckInput(), session={})
        )
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(HTTPException) as busy:
                await readiness.check(None, readiness.CheckInput(), session={})
            assert busy.value.status_code == 429
            assert not finished.is_set()
        finally:
            release.set()
        assert await asyncio.to_thread(finished.wait, 2)
        result = await readiness.check(None, readiness.CheckInput(), session={})
        assert result["graph"]["status"] == "not_configured"

    asyncio.run(run())
