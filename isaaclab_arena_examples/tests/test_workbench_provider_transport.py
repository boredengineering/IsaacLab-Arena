# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Private worker transport; controlled subprocesses never invoke providers."""

import asyncio
import json
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, generation
from isaaclab_arena_examples.tests.test_workbench_editor import FIXTURE, ORIGIN, login
from isaaclab_arena_examples.tests.test_workbench_model_settings import BODY, KEY


@pytest.fixture(autouse=True)
def deny_provider_network_and_ambient_configuration(monkeypatch):
    import socket

    original = socket.socket.connect

    def no_network(sock, *args, **kwargs):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            pytest.fail("Socket network access is forbidden in provider tests")
        return original(sock, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    for prefix in ("OPENAI", "GEMINI", "OPENROUTER", "NV"):
        for suffix in ("API_KEY", "MODEL", "BASE_URL"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    monkeypatch.delenv("BASE_URL", raising=False)


@pytest.mark.parametrize("leak", [False, True])
@pytest.mark.parametrize("source", ["session", "server"])
def test_worker_private_stdin_and_result_secret_rejection(tmp_path, monkeypatch, leak, source):
    endpoint = "https://api.openai.com/v1" if source == "session" else "https://private.internal/custom/v1"
    result = {
        "yaml_text": FIXTURE.read_text(),
        "validation": {},
        "traces": [],
        "publication": "not_published",
        "warnings": [],
    }
    script = f"""
import json, sys
envelope = json.loads(sys.stdin.readline())
assert envelope['config']['api_key']
assert envelope['config']['model'] == 'explicit-test-model'
assert envelope['config']['base_url'] == {endpoint!r}
assert envelope['config'].get('trusted_server', False) == {source == 'server'!r}
assert 'api_key' not in envelope['inputs']
result = {result!r}
if {leak!r}:
    result['warnings'].append(envelope['config']['api_key'])
print(json.dumps({{'result': result}}), flush=True)
"""
    original = asyncio.create_subprocess_exec
    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", KEY + "-ambient")
    monkeypatch.setenv("OTHER_SECRET_TOKEN", KEY + "-unrelated")
    if source == "session":
        monkeypatch.setattr(generation, "configuration", lambda: None)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", KEY)
        monkeypatch.setenv("OPENAI_MODEL", BODY["model"])
        monkeypatch.setenv("OPENAI_BASE_URL", endpoint)

    async def controlled_worker(*args, **kwargs):
        assert KEY not in json.dumps(args)
        assert "env" in kwargs
        assert KEY not in json.dumps(kwargs["env"])
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert "OTHER_SECRET_TOKEN" not in kwargs["env"]
        calls.append(True)
        return await original(sys.executable, "-c", script, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", controlled_worker)
    with TestClient(create_app(tmp_path), base_url=ORIGIN) as client:
        headers = login(client)
        credential = {}
        if source == "session":
            saved = client.put("/api/model-settings", headers=headers, json=BODY).json()
            credential = {"credential_ref": saved["credential_ref"]}
        job = client.post(
            "/api/editor/generate",
            headers=headers,
            json={
                "prompt": "No inference",
                "idempotency_key": "private-pipe",
                **credential,
            },
        ).json()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{job['id']}").json()
            if current["status"] in {"failed", "succeeded"}:
                break
            time.sleep(0.02)
        assert calls
        assert current["status"] == ("failed" if leak else "succeeded"), current
        assert KEY not in json.dumps(current)
        assert os.environ["OPENAI_API_KEY"] == (KEY + "-ambient" if source == "session" else KEY)
    assert all(KEY.encode() not in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


@pytest.mark.parametrize("invalidate", ["replace", "forget", "expire", "revoke", "metadata"])
def test_revocation_during_spawn_never_writes_credentials_and_reaps_child(tmp_path, monkeypatch, invalidate):
    import threading
    from unittest.mock import Mock

    now = [1000.0]
    app = create_app(tmp_path, clock=lambda: now[0])
    spawned, release = threading.Event(), threading.Event()
    children, writes = [], []
    original = asyncio.create_subprocess_exec

    async def suspended_spawn(*args, **kwargs):
        process = await original(sys.executable, "-c", "import sys; sys.stdin.read()", **kwargs)
        children.append(process)
        process.stdin = Mock(wraps=process.stdin)
        process.stdin.write.side_effect = lambda data: writes.append(data)
        spawned.set()
        assert await asyncio.to_thread(release.wait, 5)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", suspended_spawn)
    monkeypatch.setattr(generation, "configuration", lambda: None)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        saved = client.put("/api/model-settings", headers=headers, json=BODY).json()
        job = client.post(
            "/api/editor/generate",
            headers=headers,
            json={"prompt": "No inference", "idempotency_key": "spawn-race", "credential_ref": saved["credential_ref"]},
        ).json()
        try:
            assert spawned.wait(5)
            if invalidate == "replace":
                client.put("/api/model-settings", headers=headers, json={**BODY, "api_key": KEY + "-replacement"})
            elif invalidate == "forget":
                client.delete("/api/model-settings", headers=headers)
            elif invalidate == "expire":
                now[0] = saved["expires_at"]
            elif invalidate == "revoke":
                client.delete("/api/session", headers=headers)
                headers = login(client)
            else:
                app.state.model_settings._records[job["created_by_session_id"]]["model"] = "changed-metadata"
        finally:
            release.set()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{job['id']}").json()
            if current["status"] == "failed" and not app.state.journal.pending_workers():
                break
            time.sleep(0.02)
        assert current["status"] == "failed"
        assert children[0].returncode is not None
        with pytest.raises(ProcessLookupError):
            os.kill(children[0].pid, 0)
        assert app.state.journal.pending_workers() == []
        assert writes == []
        assert KEY not in json.dumps(current)


@pytest.mark.parametrize("outcome", ["success", "secret", "exception"])
def test_generation_worker_reads_config_envelope_and_suppresses_secret_output(monkeypatch, capsys, caplog, outcome):
    import io
    from types import SimpleNamespace

    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation_worker

    config = {"api_key": KEY, "model": BODY["model"], "base_url": "https://api.openai.com/v1"}
    envelope = {"inputs": {"prompt": "no inference"}, "config": config}
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO((json.dumps(envelope) + "\n").encode())))
    monkeypatch.setattr(sys, "argv", ["worker", "--parent-pid", str(os.getppid())])
    monkeypatch.setattr(generation_worker.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(prctl=lambda *a: 0))
    observed = []

    def controlled_generate(inputs, emit, *, config=None):
        import logging

        observed.append((inputs, config))
        print(KEY)
        logging.getLogger("provider-test").warning(KEY)
        if outcome == "exception":
            raise ValueError(KEY)
        return {"value": KEY if outcome == "secret" else "safe"}

    monkeypatch.setattr(generation, "generate", controlled_generate)
    code = generation_worker.main()
    output = capsys.readouterr()
    assert observed == [(envelope["inputs"], config)]
    assert KEY not in output.out + output.err
    assert KEY not in caplog.text
    assert code == (0 if outcome == "success" else 1)
    assert json.loads(output.out) == (
        {"result": {"value": "safe"}}
        if outcome == "success"
        else {"error": "Generation failed: check server model configuration, endpoint access, and draft validity"}
    )


@pytest.mark.parametrize("source", ["session", "server"])
def test_provider_transport_never_follows_redirect_even_during_agent_initialization(monkeypatch, source):
    import importlib
    import socket

    from openai import DefaultHttpxClient

    def no_network(*args, **kwargs):
        pytest.fail("Socket network access is forbidden in provider tests")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    with DefaultHttpxClient() as client:
        transport_type = type(client._transport)
    httpx = importlib.import_module(transport_type.__module__.split(".")[0])

    requests = []

    def redirect(transport, request):
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://attacker.invalid/steal"}, request=request)

    monkeypatch.setattr(transport_type, "handle_request", redirect)
    model = "openai/vendor/exact-explicit-model"
    config = {"api_key": KEY, "base_url": "https://api.openai.com/v1", "model": model}
    if source == "server":
        monkeypatch.setenv("OPENAI_API_KEY", KEY)
        monkeypatch.setenv("OPENAI_MODEL", model)
        monkeypatch.setenv("OPENAI_BASE_URL", "https://trusted.internal/provider/v1")
        config = generation.configuration()
    with pytest.raises(Exception) as failure:
        generation.generate(
            {"prompt": "Transport only"},
            lambda stage: None,
            config=config,
        )
    assert len(requests) == 1, str(failure.value)
    assert str(requests[0].url) == config["base_url"] + "/chat/completions"
    assert json.loads(requests[0].content)["model"] == model


@pytest.mark.parametrize(
    "prefix,provider,endpoint,model",
    [
        ("OPENAI", "openai", "https://api.openai.com/v1", "gpt-6-astra"),
        ("GEMINI", "gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
        ("OPENROUTER", "openrouter", "https://openrouter.ai/api/v1", "anthropic/claude-sonnet-4.5"),
        ("NV", "nvidia", "https://inference-api.nvidia.com", "azure/anthropic/claude-opus-4-8"),
    ],
)
@pytest.mark.parametrize("override", ["default", "global", "provider"])
def test_server_fallback_preserves_original_models_endpoint_precedence_and_private_metadata(
    tmp_path, monkeypatch, prefix, provider, endpoint, model, override
):
    monkeypatch.setenv(prefix + "_API_KEY", "  " + KEY + "  ")
    if override != "default":
        monkeypatch.setenv("BASE_URL", "http://trusted.internal/global/v1")
        endpoint = "http://trusted.internal/global/v1"
    if override == "provider":
        monkeypatch.setenv(prefix + "_BASE_URL", "https://private.internal/provider/v1")
        endpoint = "https://private.internal/provider/v1"
    config = generation.configuration()
    assert config is not None
    assert {name: config[name] for name in ("api_key", "model", "base_url", "provider")} == {
        "api_key": KEY,
        "model": model,
        "base_url": endpoint,
        "provider": provider,
    }
    explicit = "vendor/exact-effective-model"
    monkeypatch.setenv(prefix + "_MODEL", explicit)
    assert generation.configuration()["model"] == explicit
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        headers = login(client)
        status = client.get("/api/model-settings")
        assert status.json()["source"] == "server"
        assert status.json()["model"] == explicit
        assert KEY not in status.text
        assert "trusted.internal" not in status.text and "private.internal" not in status.text
        for extras in ({"base_url": endpoint}, {"trusted_server": True, "base_url": endpoint}):
            denied = client.put("/api/model-settings", headers=headers, json={**BODY, **extras})
            assert denied.status_code == 422
        saved = client.put("/api/model-settings", headers=headers, json=BODY).json()
        assert saved["source"] == "session"
        owner = next(iter(client.app.state.model_settings._records))
        assert (
            client.app.state.model_settings.resolve(owner, saved["credential_ref"])["base_url"]
            == "https://api.openai.com/v1"
        )


@pytest.mark.parametrize("field", ["MODEL", "BASE_URL"])
def test_server_fallback_rejects_key_in_metadata_without_public_echo(tmp_path, monkeypatch, field):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.setenv("OPENAI_" + field, "https://private.invalid/" + KEY)
    assert generation.configuration() is None
    with TestClient(create_app(tmp_path), base_url=ORIGIN) as client:
        login(client)
        response = client.get("/api/model-settings")
        assert response.json()["configured"] is False
        assert KEY not in response.text


@pytest.mark.parametrize("refine", [False, True])
def test_generation_validates_real_spec_with_private_config_and_no_publication(refine):
    import yaml
    from types import SimpleNamespace

    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    calls = []
    spec = ArenaEnvGraphSpec.from_dict(yaml.safe_load(FIXTURE.read_text()))

    class Agent:
        telemetry = SimpleNamespace(converged=True)

        def __init__(self, **kwargs):
            assert kwargs == {
                "api_key": KEY,
                "model": BODY["model"],
                "base_url": "https://api.openai.com/v1",
                "max_tokens": 4096,
                "max_retries": 1,
                "load_dotenv": False,
            }

        def generate_spec(self, prompt, *, publish_to_graph, progress):
            assert not publish_to_graph
            progress("spec_inference")
            progress("untrusted-stage")
            calls.append("generate")
            return spec, None

        def refine_spec(self, base, prompt, **kwargs):
            assert isinstance(base, ArenaEnvGraphSpec)
            result = self.generate_spec(prompt, **kwargs)
            calls.append("refine")
            return result

    stages = []
    inputs = {"prompt": "No inference", "base_yaml": FIXTURE.read_text()} if refine else {"prompt": "No inference"}
    result = generation.generate(
        inputs,
        stages.append,
        agent_factory=Agent,
        config={"api_key": KEY, "model": BODY["model"], "base_url": "https://api.openai.com/v1"},
    )
    assert result["validation"]["valid"]
    assert result["publication"] == "not_published"
    assert calls == (["generate", "refine"] if refine else ["generate"])
    assert "untrusted-stage" not in stages
    assert KEY not in json.dumps(result)
