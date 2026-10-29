# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Real editor schema, immutable document and HTTP boundary tests."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

ORIGIN = "http://127.0.0.1:3000"
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml"


def login(client):
    session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
    return {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}


def test_snapshot_options_are_frozen_validated_and_idempotent(tmp_path):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        body = {"yaml_text": FIXTURE.read_text(), "idempotency_key": "camera"}
        options = {"view": "front", "resolution": 512, "asset_views": {"mug_ycb_robolab": "top"}}
        response = client.post("/api/editor/snapshots", headers=headers, json={**body, "options": options})
        assert response.status_code == 202, response.text
        job = response.json()
        assert job["inputs"]["options"] == options
        assert "asset_views" not in job["inputs"]["yaml_text"]
        assert (
            client.post("/api/editor/snapshots", headers=headers, json={**body, "options": options}).json()["id"]
            == job["id"]
        )
        assert client.post("/api/editor/snapshots", headers=headers, json=body).status_code == 409
        for invalid in (
            {"view": "back"},
            {"resolution": "512"},
            {"resolution": True},
            {"asset_views": {"unknown": "top"}},
            {"extra": 1},
        ):
            assert (
                client.post("/api/editor/snapshots", headers=headers, json={**body, "options": invalid}).status_code
                == 422
            )
        defaults = client.post("/api/editor/snapshots", headers=headers, json={**body, "idempotency_key": "default"})
        assert defaults.json()["inputs"]["options"] == {"view": "isometric", "resolution": 1024, "asset_views": {}}


@pytest.mark.parametrize("revision, status", [("transport-test-revision", "hit"), (None, "historical")])
def test_preview_lookup_is_authenticated_read_only_and_independent_of_jobs(tmp_path, monkeypatch, revision, status):
    from isaaclab_arena_examples.tests.test_workbench_preview_catalogue import peer

    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/editor/previews/" + "a" * 64).status_code == 401
        login(client)
        service = app.state.editor_execution.snapshots
        service.asset_revision = lambda spec: revision
        monkeypatch.setattr(service, "_rpc", peer([]))
        receipt = service.render(FIXTURE.read_text(), "not-in-journal", lambda _: None, {"view": "top"})
        url = "/api/editor/previews/" + receipt["canonical_hash"]
        monkeypatch.setattr(service, "_rpc", lambda *args: pytest.fail("GET triggered rendering"))
        before = service._db_path.read_bytes()
        result = client.get(url, params={"view": "top"})
        assert result.status_code == 200, result.text
        assert result.json() == {"status": status, "canonical_hash": receipt["canonical_hash"], "receipt": receipt}
        assert receipt["freshness"] == ("verified_assets" if revision else "unverified_assets")
        assert service._db_path.read_bytes() == before
        assert client.get(url).json()["status"] == "miss"
        assert client.get("/api/jobs").json()["jobs"] == []
        for params in (
            {"view": "unknown"},
            {"resolution": "513"},
            {"asset_views": "[]"},
            {"asset_views": "bad"},
            {"asset_views": '{"../escape":"top"}'},
            {"extra": "1"},
        ):
            assert client.get(url, params=params).status_code == 422
        assert client.get("/api/editor/previews/not-a-hash").status_code == 422
        assert client.get(url, params={"asset_views": '{"not_a_scene_node":"top"}'}).status_code == 422
        assert (
            client.get(url, params={"asset_views": '{"mug_ycb_robolab":"top","mug_ycb_robolab":"front"}'}).status_code
            == 422
        )
        assert client.get(receipt["scene"]["url"]).status_code == 200


def test_failed_snapshot_journal_retains_structured_errors_and_timings(tmp_path, monkeypatch):
    import time

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        errors = [{"id": "scene", "stage": "camera", "code": "camera_failed", "message": "Camera unavailable"}]
        monkeypatch.setattr(
            app.state.editor_execution.snapshots,
            "_rpc",
            lambda *args: {"ok": False, "errors": errors, "timings": {"scene_s": 1.0}},
        )
        job = client.post(
            "/api/editor/snapshots",
            headers=headers,
            json={"yaml_text": FIXTURE.read_text(), "idempotency_key": "structured-failure"},
        ).json()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{job['id']}").json()
            if current["status"] == "failed":
                break
            time.sleep(0.02)
        assert current["status"] == "failed", current
        assert current["result"]["errors"] == errors
        assert current["result"]["timings"]["scene_s"] == 1.0
        assert current["result"]["canonical_hash"] == job["inputs"]["canonical_hash"]


def test_real_default_document_and_semantic_validation(tmp_path):
    with TestClient(create_app(tmp_path), base_url=ORIGIN) as client:
        assert client.get("/api/editor").status_code == 401
        headers = login(client)
        index = client.get("/api/editor").json()
        assert index["documents"]
        doc = client.get(f"/api/editor/documents/{index['default_document_id']}").json()
        assert doc["yaml_text"] == FIXTURE.read_text()
        validation = doc["validation"]
        assert validation["valid"] is True
        assert len(validation["assets"]) == 6
        assert len(validation["tasks"]) == 2
        assert validation["reified_relations"] == []
        assert all(n["role"] != "reifier" for n in validation["graph"]["nodes"])
        invalid = client.post(
            "/api/editor/validate",
            headers=headers,
            json={"yaml_text": doc["yaml_text"].replace("subject: rubiks_cube_hot3d_robolab", "subject: missing")},
        ).json()
        assert invalid["valid"] is False
        assert invalid["canonical_hash"] is None
        assert "unknown subject" in " ".join(invalid["errors"])


def test_frozen_includes_save_conflicts_and_flattened_download(tmp_path):
    import json
    import yaml

    import pytest

    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents

    root = tmp_path / "repo"
    source = root / "generated_envs" / "scene.yaml"
    source.parent.mkdir(parents=True)
    data = yaml.safe_load(FIXTURE.read_text())
    name = data.pop("env_name")
    include = source.with_name("assets.yaml")
    include.write_text(yaml.safe_dump(data))
    source.write_text(f"env_name: {name}\nexternal_yaml: assets.yaml\n")
    documents = Documents(tmp_path / "state", root=root)
    document_id = next(d["id"] for d in documents.index() if d["name"] == "scene")
    doc = documents.load(document_id)
    assert doc["validation"]["valid"]
    draft = doc["yaml_text"].replace(name, "edited_scene")
    saved = documents.save(draft, document_id, doc["source_hash"])
    assert source.read_text() == doc["yaml_text"]
    exported = documents.download(saved["revision_id"])
    assert "external_yaml" not in exported
    assert "Flattened" in exported
    assert yaml.safe_load(exported)["env_name"] == "edited_scene"
    manifest = json.loads((tmp_path / "state/editor-revisions" / saved["revision_id"] / "snapshot.json").read_text())
    assert manifest["includes"]["assets.yaml"] == include.read_text()
    include.write_text("broken: changed\n")
    assert documents.validate(draft, document_id)["valid"]
    with pytest.raises(ValueError, match="changed"):
        documents.save(draft, document_id, doc["source_hash"])
    assert Documents(tmp_path / "state", root=root).download(saved["revision_id"]) == exported


def test_yaml_boundary_rejects_unknown_fields_aliases_and_include_escape(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents

    documents = Documents(tmp_path)
    for text in (
        FIXTURE.read_text() + "\nnot_a_field: secret\n",
        "a: &x [1]\nb: *x\n",
        FIXTURE.read_text().replace("  params: {}", "  typo: {}", 1),
        "external_yaml: /etc/passwd\n",
        "a: 1\na: 2\n",
        "x: " + "[" * 100 + "]" * 100,
    ):
        result = documents.validate(text)
        assert result["valid"] is False, text
        assert result["errors"]


def test_save_http_guards_hashes_and_request_bounds(tmp_path):
    with TestClient(create_app(tmp_path), base_url=ORIGIN) as client:
        headers = login(client)
        index = client.get("/api/editor").json()
        doc = client.get(f"/api/editor/documents/{index['default_document_id']}").json()
        body = {"yaml_text": doc["yaml_text"], "document_id": doc["document_id"], "expected_source_hash": "0" * 64}
        assert client.post("/api/editor/save", json=body, headers=headers).status_code == 409
        body["expected_source_hash"] = doc["source_hash"]
        saved = client.post("/api/editor/save", json=body, headers=headers)
        assert saved.status_code == 200, saved.text
        assert client.get(saved.json()["download_url"]).status_code == 200
        assert client.post("/api/editor/validate", json={"yaml_text": "#" * 20000}, headers=headers).status_code == 200
        assert client.post("/api/editor/validate", json={"yaml_text": "é" * 150000}, headers=headers).status_code in {
            413,
            422,
        }
        assert client.post("/api/editor/save", json={**body, "path": "/etc/passwd"}, headers=headers).status_code == 422


def test_generation_unconfigured_and_job_inputs_are_frozen(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation

    monkeypatch.setattr(generation, "configuration", lambda: None)
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        body = {"prompt": "Move the cube", "base_yaml": FIXTURE.read_text(), "idempotency_key": "gen1"}
        assert client.get("/api/editor").json()["capabilities"]["generation"] is False
        response = client.post("/api/editor/generate", headers=headers, json=body)
        assert response.status_code == 503
        assert "configured" in response.json()["detail"]
        monkeypatch.setattr(generation, "configuration", lambda: {"model": "unit-test"})
        assert (
            client.post("/api/editor/generate", headers=headers, json={**body, "api_key": "secret"}).status_code == 422
        )
        accepted = client.post("/api/editor/generate", headers=headers, json=body)
        assert accepted.status_code == 202, accepted.text
        job = accepted.json()
        assert job["kind"] == "generate"
        assert job["inputs"]["base_yaml"]
        assert client.post("/api/editor/generate", headers=headers, json=body).json()["id"] == job["id"]
        assert client.post("/api/editor/generate", headers=headers, json={**body, "prompt": "other"}).status_code == 409
        assert (
            client.post("/api/editor/generate", headers=headers, json={**body, "base_yaml": "bad"}).status_code == 422
        )
        assert len(client.get("/api/jobs").json()["jobs"]) == 1


def test_generation_load_uses_current_frozen_view_and_idempotency(tmp_path, monkeypatch):
    import yaml

    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation

    root = tmp_path / "repo"
    source = root / "generated_envs" / "scene.yaml"
    source.parent.mkdir(parents=True)
    data = yaml.safe_load(FIXTURE.read_text())
    data.pop("env_name")
    include = source.with_name("base.yaml")
    include.write_text(yaml.safe_dump(data))
    source.write_text("env_name: scene\nexternal_yaml: base.yaml\n")
    monkeypatch.setattr(generation, "configuration", lambda: {"model": "no-inference"})
    app = create_app(tmp_path / "state", start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        documents = Documents(tmp_path / "state", root=root)
        app.state.documents = documents
        source_id = next(d["id"] for d in documents.index() if d["name"] == "scene")
        older = documents.load(source_id)
        data["objects"][0]["params"]["review_marker"] = "new-include"
        include.write_text(yaml.safe_dump(data))
        current = documents.load(source_id)
        assert current["validation"]["valid"]
        assert older["document_id"] != current["document_id"]
        headers = login(client)
        body = {"prompt": "Move cube", "document_id": source_id, "idempotency_key": "loaded-view"}
        accepted = client.post("/api/editor/generate", headers=headers, json=body)
        assert accepted.status_code == 202, accepted.text
        job = accepted.json()
        assert "new-include" in job["inputs"]["base_yaml"]
        assert job["inputs"]["document_id"] == current["document_id"]
        assert job["inputs"]["input_hash"] == current["source_hash"]
        assert client.post("/api/editor/generate", headers=headers, json=body).json()["id"] == job["id"]
        include.write_text(include.read_text() + "# new frozen bytes\n")
        assert client.post("/api/editor/generate", headers=headers, json=body).status_code == 409


def test_snapshot_job_runs_off_loop_and_authenticates_artifacts(tmp_path, monkeypatch):
    import threading
    import time

    from isaaclab_arena_examples.agentic_environment_generation.web_api import editor_execution

    worker_threads = []
    observed_options = []
    closed = []

    class Service:
        def render(self, yaml_text, job_id, emit, options=None):
            observed_options.append(options)
            worker_threads.append(threading.get_ident())
            emit("scene_loading")
            time.sleep(0.1)
            return {
                "input_hash": "test-receipt",
                "assets": [],
                "scene": None,
                "warnings": ["Transport-only test; no rendered pixels"],
            }

        def close(self):
            closed.append(True)

        def artifact_path(self, artifact_id):
            raise KeyError(artifact_id)

    monkeypatch.setattr(editor_execution, "make_snapshot_service", lambda state: Service())
    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        assert client.get("/api/editor").json()["capabilities"]["snapshots"]
        body = {"yaml_text": FIXTURE.read_text(), "idempotency_key": "snap1", "options": {"view": "front"}}
        assert (
            client.post("/api/editor/snapshots", headers=headers, json={**body, "yaml_text": "bad"}).status_code == 422
        )
        response = client.post("/api/editor/snapshots", headers=headers, json=body)
        assert response.status_code == 202, response.text
        job = response.json()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{job['id']}").json()
            if current["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.02)
        assert current["status"] == "succeeded", current
        assert current["result"]["scene"] is None
        assert current["result"]["input_hash"] == job["inputs"]["input_hash"]
        assert current["result"]["canonical_hash"] == job["inputs"]["canonical_hash"]
        assert observed_options == [{"view": "front", "resolution": 1024, "asset_views": {}}]
        assert worker_threads and worker_threads[0] != app.state.editor_execution.loop_thread
        assert client.get("/api/editor/artifacts/not-indexed").status_code == 404
    assert closed


def test_authored_reifier_nodes_keep_exact_identity_and_endpoints(tmp_path):
    import yaml

    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents

    data = yaml.safe_load(FIXTURE.read_text())
    data["reified_relations"] = [{
        "reifier_id": "authored_statement",
        "source_id": data["objects"][0]["id"],
        "target_id": data["background"]["id"],
        "relation_type": "PLACED_ON",
    }]
    result = Documents(tmp_path).validate(yaml.safe_dump(data))
    assert result["valid"], result["errors"]
    node = next(n for n in result["graph"]["nodes"] if n["role"] == "reifier")
    assert node["id"] == "authored_statement"
    assert node["label"] == "PLACED_ON"
    edges = [e for e in result["graph"]["edges"] if e["source"] == "authored_statement"]
    assert {e["target"] for e in edges} == {data["objects"][0]["id"], data["background"]["id"]}


def test_generation_real_subprocess_unconfigured_failure_is_durable_and_reaped(tmp_path, monkeypatch):
    import time

    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation

    for prefix in ("OPENAI", "GEMINI", "OPENROUTER", "NV"):
        monkeypatch.delenv(prefix + "_API_KEY", raising=False)
    monkeypatch.setattr(generation, "configuration", lambda: {"model": "transport-test-only"})
    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        accepted = client.post(
            "/api/editor/generate",
            headers=headers,
            json={"prompt": "test unconfigured worker", "idempotency_key": "real-worker"},
        )
        assert accepted.status_code == 202
        job_id = accepted.json()["id"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] == "failed":
                break
            time.sleep(0.05)
        assert job["status"] == "failed", job
        assert "configured" in job["error"]
        assert app.state.journal.pending_workers() == []
        assert job["result"] is None


def test_snapshot_cancel_closes_active_adapter_and_returns_cancelled(tmp_path, monkeypatch):
    import threading
    import time

    from isaaclab_arena_examples.agentic_environment_generation.web_api import editor_execution

    started = threading.Event()
    released = threading.Event()

    class Service:
        def render(self, text, job_id, emit):
            started.set()
            assert released.wait(5), "Cancellation did not stop the owned adapter"
            raise RuntimeError("Closed")

        def close(self):
            released.set()

    monkeypatch.setattr(editor_execution, "make_snapshot_service", lambda state: Service())
    with TestClient(create_app(tmp_path), base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post(
            "/api/editor/snapshots",
            headers=headers,
            json={"yaml_text": FIXTURE.read_text(), "idempotency_key": "cancel"},
        ).json()
        assert started.wait(3)
        client.post(f"/api/jobs/{job['id']}/cancel", headers=headers)
        assert released.wait(1)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{job['id']}").json()
            if current["status"] == "cancelled":
                break
            time.sleep(0.02)
        assert current["status"] == "cancelled"


def test_generation_wall_clock_budget_reaps_owned_process(tmp_path, monkeypatch):
    import asyncio
    import os
    import sys
    import time

    import pytest

    from isaaclab_arena_examples.agentic_environment_generation.web_api import editor_execution, generation

    original = asyncio.create_subprocess_exec
    pids = []

    async def blocked_worker(*args, **kwargs):
        process = await original(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
        pids.append(process.pid)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", blocked_worker)
    monkeypatch.setattr(editor_execution, "GENERATION_TIMEOUT", 0.3)
    monkeypatch.setattr(generation, "configuration", lambda: {"model": "transport-test"})
    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post(
            "/api/editor/generate", headers=headers, json={"prompt": "timeout test", "idempotency_key": "timeout"}
        ).json()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{job['id']}").json()
            if current["status"] == "failed":
                break
            time.sleep(0.02)
        assert current["status"] == "failed", current
        assert app.state.journal.pending_workers() == []
        assert len(pids) == 1
        with pytest.raises(ProcessLookupError):
            os.kill(pids[0], 0)


@pytest.mark.parametrize("outcome", ["failed", "cancelled", "succeeded"])
def test_generation_finishes_group_cleanup_before_worker_acknowledgement(tmp_path, monkeypatch, outcome):
    import asyncio
    import json
    import os
    import signal
    import sys
    import time
    from contextlib import suppress

    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation
    from isaaclab_arena_examples.agentic_environment_generation.web_api.process_identity import process_identity

    receipt = tmp_path / "child.pid"
    result = {
        "yaml_text": FIXTURE.read_text(),
        "validation": {},
        "traces": [],
        "publication": "not_published",
        "warnings": ["Controlled subprocess transport test only"],
    }
    script = f"""
import json, os, signal, sys, time
from pathlib import Path
sys.stdin.readline()
child = os.fork()
if child == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    os.close(0)
    os.close(1)
    os.close(2)
    Path({str(receipt)!r}).write_text(str(os.getpid()))
    time.sleep(60)
    os._exit(0)
while not Path({str(receipt)!r}).exists():
    time.sleep(0.005)
if {outcome!r} == 'cancelled':
    time.sleep(60)
elif {outcome!r} == 'failed':
    print('invalid receipt', flush=True)
else:
    print({json.dumps({'result': result})!r}, flush=True)
"""
    original = asyncio.create_subprocess_exec
    pids = []

    async def controlled_worker(*args, **kwargs):
        process = await original(sys.executable, "-c", script, **kwargs)
        pids.append(process.pid)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", controlled_worker)
    monkeypatch.setattr(generation, "configuration", lambda: {"model": "transport-only"})
    app = create_app(tmp_path / "state")
    try:
        with TestClient(app, base_url=ORIGIN) as client:
            headers = login(client)
            job = client.post(
                "/api/editor/generate",
                headers=headers,
                json={"prompt": "No inference", "idempotency_key": outcome},
            ).json()
            deadline = time.monotonic() + 8
            while not receipt.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert receipt.exists()
            child = int(receipt.read_text())
            if outcome == "cancelled":
                assert client.post(f"/api/jobs/{job['id']}/cancel", headers=headers).status_code == 200
            while time.monotonic() < deadline:
                current = client.get(f"/api/jobs/{job['id']}").json()
                if current["status"] == outcome and not app.state.journal.pending_workers():
                    break
                time.sleep(0.02)
            assert current["status"] == outcome, current
            assert app.state.journal.pending_workers() == []
            assert process_identity(child) is None
            assert all(process_identity(pid) is None for pid in pids)
    finally:
        for pid in pids:
            with suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)


def test_another_document_load_cannot_replace_an_older_frozen_include(tmp_path):
    import yaml

    import pytest

    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents

    root = tmp_path / "repo"
    source = root / "generated_envs" / "scene.yaml"
    source.parent.mkdir(parents=True)
    data = yaml.safe_load(FIXTURE.read_text())
    data.pop("env_name")
    include = source.with_name("base.yaml")
    include.write_text(yaml.safe_dump(data))
    source.write_text("env_name: scene\nexternal_yaml: base.yaml\n")
    documents = Documents(tmp_path / "state", root=root)
    source_id = next(d["id"] for d in documents.index() if d["name"] == "scene")
    older = documents.load(source_id)
    include.write_text(include.read_text() + "# changed source bytes\n")
    newer = documents.load(source_id)
    assert older["source_hash"] == newer["source_hash"]
    assert older["document_id"] != newer["document_id"]
    with pytest.raises(ValueError, match="changed"):
        documents.save(older["yaml_text"], older["document_id"], older["source_hash"])
    documents.save(newer["yaml_text"], newer["document_id"], newer["source_hash"])
