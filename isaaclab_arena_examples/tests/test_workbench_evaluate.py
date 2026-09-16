# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Prototype evaluation API and simulated OS/harness units, never GPU evidence."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, editor_execution

ORIGIN = "http://127.0.0.1:3000"
FIXTURE = Path(__file__).resolve().parents[2] / "isaaclab_arena/tests/test_data/minimal_maple_table_env_graph.yaml"
FIXED = {"headless": True, "enable_cameras": True, "num_envs": 1, "num_steps": 1000}


@pytest.fixture(autouse=True)
def no_renderer(monkeypatch):
    def unavailable(_):
        raise RuntimeError("Evaluation units have no renderer")

    monkeypatch.setattr(editor_execution, "make_snapshot_service", unavailable)


def droid_text():
    return FIXTURE.read_text().replace("franka_ik", "droid_abs_joint_pos")


def login(client):
    session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
    return {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}


def test_fixed_profiles_route_freezes_and_replays_without_resolving_source(tmp_path, monkeypatch):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/editor/evaluation-profiles").status_code == 401
        headers = login(client)
        catalogue = client.get("/api/editor/evaluation-profiles")
        assert catalogue.status_code == 200, catalogue.text
        assert catalogue.json() == {
            "profiles": [
                {"id": "gr00t-droid", "label": "GR00T DROID", "remote_host": "127.0.0.1", "remote_port": 5555},
                {"id": "openpi-droid", "label": "OpenPI DROID", "remote_host": "127.0.0.1", "remote_port": 8000},
            ],
            **FIXED,
            "publication": "not_requested",
        }
        for url in ("/api/editor", "/api/health"):
            assert client.get(url).json()["capabilities"]["policy_evaluation"] is True
        body = {"yaml_text": droid_text(), "idempotency_key": "eval-first", "profile": "gr00t-droid"}
        assert client.post("/api/editor/evaluate", json=body).status_code == 403
        response = client.post("/api/editor/evaluate", json=body, headers=headers)
        assert response.status_code == 202, response.text
        job = response.json()
        assert job["kind"] == "evaluate" and job["status"] == "queued"
        assert {key: job["inputs"][key] for key in FIXED} == FIXED
        assert job["inputs"]["language_instruction"] is None
        assert job["inputs"]["profile"] == "gr00t-droid"
        assert job["inputs"]["document_id"] is None
        assert "external_yaml:" not in job["inputs"]["yaml_text"]
        validation = client.post("/api/editor/validate", json={"yaml_text": droid_text()}, headers=headers).json()
        assert job["inputs"]["input_hash"] == validation["source_hash"]
        assert job["inputs"]["canonical_hash"] == validation["canonical_hash"]
        monkeypatch.setattr(app.state.documents, "validate", lambda *a: pytest.fail("replay resolved source"))
        assert client.post("/api/editor/evaluate", json=body, headers=headers).json() == job
        assert (
            client.post("/api/editor/evaluate", json={**body, "profile": "openpi-droid"}, headers=headers).status_code
            == 409
        )
        assert client.get("/api/jobs/" + job["id"]).json() == job
        assert client.post("/api/jobs/" + job["id"] + "/cancel", headers=headers).json()["status"] == "cancelled"


@pytest.mark.parametrize("profile", ["gr00t-droid", "openpi-droid"])
@pytest.mark.parametrize("instruction", ["Pick up the cube", "--headless"])
@pytest.mark.parametrize("no_episodes", [False, True])
def test_worker_uses_local_only_harness_callback_and_actual_artifacts(
    tmp_path, monkeypatch, profile, instruction, no_episodes
):
    """Simulated policy_runner boundary; artifact bytes/counts are actual local files."""
    import json
    import sys
    import yaml
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    from isaaclab_arena_examples.agentic_environment_generation.web_api import evaluation_worker

    validation = Documents(tmp_path / "documents").validate(droid_text())
    inputs = {
        **FIXED,
        "yaml_text": yaml.safe_dump(validation["spec"], sort_keys=False),
        "document_id": None,
        "input_hash": validation["source_hash"],
        "canonical_hash": validation["canonical_hash"],
        "request_sha256": "e" * 64,
        "profile": profile,
        "language_instruction": instruction,
    }
    root = tmp_path / "owned-job"
    root.mkdir()
    receipts = []
    argv_before = sys.argv
    metrics = None if no_episodes else {"success_rate": 0.5, "task_progress": {"lifted": 0.25}}
    artifacts = {
        "index.html": b"<html><body>Actual unit report</body></html>",
        "episode_results_rank0.jsonl": b'{"success":true,"episode_length":12}\n{"success":false,"episode_length":25}\n',
        "eval_telemetry.ttl": b"@prefix prov: <http://www.w3.org/ns/prov#> .\n",
    }
    if no_episodes:
        artifacts["episode_results_rank0.jsonl"] = b""

    def runner_main(**kwargs):
        assert kwargs["publish_to_graph"] is False
        assert kwargs["update_lineage"] is False
        assert kwargs["telemetry_env_name"] == validation["spec"]["env_name"]
        argv = sys.argv

        def value(flag):
            return argv[argv.index(flag) + 1]

        assert "--headless" in argv and "--enable_cameras" in argv
        assert value("--num_envs") == "1" and value("--num_steps") == "1000"
        assert value("--remote_host") == "127.0.0.1"
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--language_instruction")
        parser.add_argument("--headless", action="store_true")
        parsed, _ = parser.parse_known_args(argv[1:])
        assert parsed.language_instruction == instruction
        assert Path(value("--env_graph_spec_yaml")).read_text() == inputs["yaml_text"]
        assert Path.cwd() == Path(evaluation_worker.__file__).resolve().parents[3]
        assert not any(
            flag in argv
            for flag in (
                "--record_camera_video",
                "--record_viewport_video",
                "--distributed",
                "--serve_evaluation_report",
                "--remote_kill_on_exit",
                "--num_episodes",
            )
        )
        if profile == "gr00t-droid":
            assert value("--remote_port") == "5555"
            assert (
                value("--policy_type")
                == "isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy"
            )
            assert (
                value("--policy_config_yaml_path")
                == "isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml"
            )
        else:
            assert value("--remote_port") == "8000"
            assert value("--policy_type") == "isaaclab_arena_openpi.policy.pi0_remote_policy.Pi0RemotePolicy"
            assert value("--policy_variant") == "pi05"
            assert value("--openpi_embodiment_adapter") == "droid"
        output = Path(value("--output_base_dir")) / "actual-run"
        output.mkdir(parents=True)
        for name, data in artifacts.items():
            (output / name).write_bytes(data)
        (output / "private.hdf5").write_bytes(b"not exposed")
        kwargs["on_evaluation_completed"]({
            "output_dir": str(output),
            "report_path": str(output / "index.html"),
            "metrics": metrics,
            "num_steps": 1000,
            "num_episodes": None,
            "warnings": [],
        })
        assert len(receipts) == 1  # receipt is flushed before simulated terminating shutdown
        raise SystemExit(0)

    monkeypatch.setitem(sys.modules, "isaaclab_arena.evaluation.policy_runner", SimpleNamespace(main=runner_main))
    with pytest.raises(SystemExit) as exited:
        evaluation_worker.run_evaluation(inputs, root, on_completed=receipts.append)
    assert exited.value.code == 0 and sys.argv is argv_before
    result = receipts[0]
    assert result["metrics"] == metrics
    assert (result["episode_count"], result["success_count"]) == ((0, None) if no_episodes else (2, 1))
    if no_episodes:
        assert any("No completed-episode evidence" in warning for warning in result["warnings"])
    assert result["publication"] == "not_requested" and result["completed"] is True
    assert str(root) not in json.dumps(result)
    assert {row["name"] for row in result["artifacts"]} == set(artifacts)
    import hashlib

    for row in result["artifacts"]:
        data = (root / "artifacts" / row["name"]).read_bytes()
        assert data == artifacts[row["name"]]
        assert row == {"name": row["name"], "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def wait_job(client, job_id, statuses):
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get("/api/jobs/" + job_id).json()
        if job["status"] in statuses or job["stage"] == "cleanup_pending":
            return job
        time.sleep(0.01)
    return pytest.fail(f"Evaluation never reached {statuses}: {job}")


def simulated_peer(
    monkeypatch,
    app,
    tmp_path,
    *,
    change=None,
    exit_code=0,
    frames=1,
    cleanup_error=False,
    wait_for_signal=False,
    on_cleanup=None,
):
    """Simulated OS ownership only, using real artifact files and the production dispatcher."""
    import asyncio
    import fcntl
    import json
    import threading
    from types import SimpleNamespace

    from isaaclab_arena_examples.agentic_environment_generation.web_api import snapshot_process, supervisor
    from isaaclab_arena_examples.agentic_environment_generation.web_api.evaluation_artifacts import artifact_metadata

    events = []
    signal = threading.Event()
    lease = tmp_path / "gpu.lock"
    monkeypatch.setattr(snapshot_process, "GPU_LEASE", lease)
    monkeypatch.setattr(editor_execution, "process_identity", lambda pid: "123")

    class Snapshot:
        def close(self):
            events.append("snapshot_reaped")

    app.state.editor_execution.snapshots = Snapshot()

    class Group:
        cleaned = False

        def __init__(self, pid):
            assert pid == 987654

        def stop(self):
            events.append("cleanup")
            with lease.open("rb") as other:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if on_cleanup:
                on_cleanup()
            if cleanup_error:
                raise RuntimeError("private cleanup details")
            self.cleaned = True

        def send_signal(self, sig):
            events.append("signal")
            signal.set()

    monkeypatch.setattr(supervisor, "OwnedProcessGroup", Group)

    async def spawn(*argv, **kwargs):
        assert events == ["snapshot_reaped"]
        assert argv[1:4] == (
            "-u",
            "-m",
            "isaaclab_arena_examples.agentic_environment_generation.web_api.evaluation_worker",
        )
        assert kwargs["start_new_session"] is True and kwargs["pass_fds"]
        assert kwargs["limit"] == 256 * 1024
        assert "OPENAI_API_KEY" not in kwargs["env"] and "NEO4J_PASSWORD" not in kwargs["env"]
        events.append("spawn")
        pending = []

        class Input:
            def write(self, data):
                envelope = json.loads(data)
                inputs = envelope["inputs"]
                artifacts = Path(envelope["output_root"]) / "artifacts"
                assert str(artifacts) not in json.dumps(inputs)
                artifacts.mkdir()
                files = {
                    "index.html": b"<html><script>fetch('/api/jobs')</script></html>",
                    "episode_results_rank0.jsonl": b'{"success":true,"episode_length":20}\n',
                }
                for name, value in files.items():
                    (artifacts / name).write_bytes(value)
                result = {
                    "schema_version": 1,
                    **FIXED,
                    "profile": inputs["profile"],
                    "language_instruction": inputs["language_instruction"],
                    "completed": True,
                    "input_hash": inputs["input_hash"],
                    "canonical_hash": inputs["canonical_hash"],
                    "publication": "not_requested",
                    "metrics": {"task_progress": 0.25},
                    "episode_count": 1,
                    "success_count": 1,
                    "warnings": [],
                    "artifacts": [artifact_metadata(name, value) for name, value in files.items()],
                }
                if change:
                    change(result, artifacts)
                pending.extend([(json.dumps({"result": result}) + "\n").encode()] * frames + [b""])

            async def drain(self):
                pass

            def close(self):
                pass

        class Output:
            async def readline(self):
                while wait_for_signal and not signal.is_set():
                    await asyncio.sleep(0.01)
                return pending.pop(0)

        async def wait():
            process.returncode = exit_code
            events.append("reaped")
            return exit_code

        process = SimpleNamespace(pid=987654, returncode=None, stdin=Input(), stdout=Output(), wait=wait)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return events, lease


def test_dispatch_reaps_then_exposes_verified_authenticated_artifact(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, lease = simulated_peer(monkeypatch, app, tmp_path)
        headers = login(client)
        body = {"yaml_text": droid_text(), "profile": "openpi-droid", "idempotency_key": "execute"}
        response = client.post("/api/editor/evaluate", json=body, headers=headers)
        assert response.status_code == 202, response.text
        job = wait_job(client, response.json()["id"], {"succeeded", "failed"})
        assert job["status"] == "succeeded", job
        assert events.index("snapshot_reaped") < events.index("spawn") < events.index("cleanup")
        assert app.state.supervisor.process is None and app.state.journal.pending_workers() == []
        assert client.post("/api/editor/evaluate", json=body, headers=headers).json() == job
        assert events.count("spawn") == 1
        url = f"/api/editor/evaluations/{job['id']}/artifacts/index.html"
        download = client.get(url)
        assert download.status_code == 200, download.text
        assert download.content == b"<html><script>fetch('/api/jobs')</script></html>"
        assert download.headers["x-content-type-options"] == "nosniff"
        assert "attachment" in download.headers["content-disposition"]
        assert "sandbox" in download.headers["content-security-policy"]
        assert "allow-scripts" not in download.headers["content-security-policy"]
        assert client.get(url.replace("index.html", "private.hdf5")).status_code == 404
        assert client.get(url.replace(job["id"], "0" * 32)).status_code == 404
        client.cookies.clear()
        assert client.get(url).status_code == 401
        login(client)
        # Readback hashes actual bytes on every request, not an earlier metadata assertion.
        root = tmp_path / "evaluations" / job["id"] / "artifacts"
        (root / "index.html").write_text("changed")
        assert client.get(url).status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"profile": "other"},
        {"num_steps": 1},
        {"remote_host": "example.com"},
        {"output_base_dir": "/tmp/out"},
        {"language_instruction": " "},
        {"language_instruction": "é" * 2001},
        {"language_instruction": 123},
    ],
)
def test_route_rejects_overrides_and_bad_instruction(tmp_path, change):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        body = {"yaml_text": droid_text(), "profile": "gr00t-droid", "idempotency_key": "bad", **change}
        assert client.post("/api/editor/evaluate", json=body, headers=headers).status_code == 422
        assert app.state.journal.snapshot()["jobs"] == []


@pytest.mark.parametrize(
    "embodiment,params",
    [
        ("franka_ik", {}),
        ("droid_rel_joint_pos", {}),
        ("droid_abs_joint_pos", {"enable_cameras": False}),
        ("droid_abs_joint_pos", {"concatenate_observation_terms": True}),
        ("droid_abs_joint_pos", {"arm_mode": "dual_arm"}),
        ("droid_abs_joint_pos", {"camera_config": {"wrist_camera": None}}),
    ],
)
def test_incompatible_source_is_rejected_before_dispatch(tmp_path, embodiment, params):
    import yaml

    spec = yaml.safe_load(droid_text())
    spec["embodiment"].update(registry_name=embodiment, params=params)
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post(
            "/api/editor/evaluate",
            headers=login(client),
            json={"yaml_text": yaml.safe_dump(spec), "profile": "openpi-droid", "idempotency_key": "incompatible"},
        )
        assert response.status_code == 422, response.text
        assert app.state.journal.snapshot()["jobs"] == []


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_hash",
        "wrong_profile",
        "wrong_instruction",
        "wrong_budget",
        "bool_count",
        "publication",
        "nan",
        "oversized_metrics",
        "extra_path",
        "false_episode_count",
        "empty_episodes_with_positive_count",
        "missing_report",
        "digest",
        "size",
        "name",
        "duplicate_artifact",
        "leaf_symlink",
        "ancestor_symlink",
        "zero_receipts",
        "two_receipts",
        "nonzero_exit",
    ],
)
def test_parent_rejects_invalid_result_identity_and_artifacts(tmp_path, monkeypatch, fault):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.evaluation_artifacts import artifact_metadata

    def change(result, root):
        changes = {
            "wrong_hash": {"input_hash": "0" * 64},
            "wrong_profile": {"profile": "gr00t-droid"},
            "wrong_instruction": {"language_instruction": "other"},
            "wrong_budget": {"num_steps": 999},
            "bool_count": {"episode_count": True},
            "publication": {"publication": "published"},
            "nan": {"metrics": {"rate": float("nan")}},
            "extra_path": {"output_dir": str(root)},
            "oversized_metrics": {"metrics": {"large": "a" * (128 * 1024)}},
            "false_episode_count": {"episode_count": 2},
        }
        result.update(changes.get(fault, {}))
        if fault == "empty_episodes_with_positive_count":
            (root / "episode_results_rank0.jsonl").write_bytes(b"")
            result["artifacts"][1] = artifact_metadata("episode_results_rank0.jsonl", b"")
        elif fault == "missing_report":
            (root / "index.html").unlink()
        elif fault == "digest":
            result["artifacts"][0]["sha256"] = "0" * 64
        elif fault == "size":
            result["artifacts"][0]["size"] += 1
        elif fault == "name":
            result["artifacts"][0]["name"] = "../index.html"
        elif fault == "duplicate_artifact":
            result["artifacts"].append(result["artifacts"][0])
        elif fault == "leaf_symlink":
            leaf = root / "index.html"
            copy = root / "other.html"
            leaf.rename(copy)
            leaf.symlink_to(copy)
        elif fault == "ancestor_symlink":
            copy = root.parent / "linked"
            root.rename(copy)
            root.symlink_to(copy, target_is_directory=True)

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_peer(
            monkeypatch,
            app,
            tmp_path,
            change=change,
            frames=0 if fault == "zero_receipts" else 2 if fault == "two_receipts" else 1,
            exit_code=1 if fault == "nonzero_exit" else 0,
        )
        response = client.post(
            "/api/editor/evaluate",
            headers=login(client),
            json={"yaml_text": droid_text(), "profile": "openpi-droid", "idempotency_key": "invalid-evidence"},
        )
        job = wait_job(client, response.json()["id"], {"failed", "succeeded"})
        assert job["status"] == "failed" and job["result"] is None, job
        assert "cleanup" in events and app.state.journal.pending_workers() == []
        assert client.get(f"/api/editor/evaluations/{job['id']}/artifacts/index.html").status_code == 404


def test_episode_counts_preserve_null_and_every_actual_row():
    from isaaclab_arena_examples.agentic_environment_generation.web_api.evaluation_artifacts import episode_counts

    assert episode_counts(b'{"success":true}\n{"success":null}\n') == (2, None)
    assert episode_counts(b'{"success":false}\n{"success":true}\n') == (2, 1)
    assert episode_counts(b'{"success":true}\n{"success":1}\n') == (2, None)
    assert episode_counts(b"") == (0, None)
    assert episode_counts(b"\n \n") == (0, None)


def test_zero_episode_run_completes_with_unknown_success_and_empty_artifact(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.evaluation_artifacts import artifact_metadata

    def no_episodes(result, root):
        name = "episode_results_rank0.jsonl"
        (root / name).write_bytes(b"")
        result["artifacts"][1] = artifact_metadata(name, b"")
        result.update(
            episode_count=0, success_count=None, metrics=None,
            warnings=["No completed-episode evidence was recorded"],
        )

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_peer(monkeypatch, app, tmp_path, change=no_episodes)
        response = client.post(
            "/api/editor/evaluate", headers=login(client),
            json={"yaml_text": droid_text(), "profile": "openpi-droid", "idempotency_key": "no-episodes"},
        )
        assert response.status_code == 202
        job = wait_job(client, response.json()["id"], {"succeeded", "failed"})
        assert job["status"] == "succeeded", job
        assert job["result"]["episode_count"] == 0 and job["result"]["success_count"] is None
        assert job["result"]["metrics"] is None and "cleanup" in events
        download = client.get(f"/api/editor/evaluations/{job['id']}/artifacts/episode_results_rank0.jsonl")
        assert download.status_code == 200 and download.content == b""


def test_evaluation_timeout_reaps_worker_without_changing_build_bound(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import build_execution

    assert build_execution.EVALUATION_TIMEOUT == 900 and build_execution.BUILD_TIMEOUT == 300
    monkeypatch.setattr(build_execution, "EVALUATION_TIMEOUT", 0.1)
    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_peer(monkeypatch, app, tmp_path, wait_for_signal=True)
        response = client.post(
            "/api/editor/evaluate",
            headers=login(client),
            json={"yaml_text": droid_text(), "profile": "openpi-droid", "idempotency_key": "timeout"},
        )
        job = wait_job(client, response.json()["id"], {"failed", "succeeded"})
        assert job["status"] == "failed" and job["result"] is None
        assert "cleanup" in events and app.state.journal.pending_workers() == []


def test_cancellation_signals_owned_group_and_hides_artifacts(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_peer(monkeypatch, app, tmp_path, wait_for_signal=True)
        headers = login(client)
        response = client.post(
            "/api/editor/evaluate",
            headers=headers,
            json={"yaml_text": droid_text(), "profile": "openpi-droid", "idempotency_key": "cancel"},
        )
        job_id = response.json()["id"]
        import time

        deadline = time.monotonic() + 3
        while "spawn" not in events and time.monotonic() < deadline:
            time.sleep(0.01)
        assert "spawn" in events
        client.post(f"/api/jobs/{job_id}/cancel", headers=headers)
        job = wait_job(client, job_id, {"cancelled"})
        assert job["result"] is None and "signal" in events and "cleanup" in events
        assert client.get(f"/api/editor/evaluations/{job_id}/artifacts/index.html").status_code == 404


@pytest.mark.parametrize("when", ["before_acceptance", "after_acceptance"])
def test_actual_artifact_bytes_are_screened_under_current_public_policy(tmp_path, monkeypatch, when):
    from fastapi import HTTPException

    from isaaclab_arena_examples.agentic_environment_generation.web_api.evaluation_artifacts import artifact_metadata

    marker = "synthetic-private-marker"
    active = when == "before_acceptance"

    def change(result, root):
        # HTML entity spelling verifies the actual downloadable bytes, not just result metadata.
        data = ("<html>" + "".join(f"&#{ord(c)};" for c in marker) + "</html>").encode()
        (root / "index.html").write_bytes(data)
        result["artifacts"][0] = artifact_metadata("index.html", data)

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        original = app.state.model_settings.protect_public

        def protect(value):
            original(value)
            if active and marker in str(value):
                raise HTTPException(422, "Invalid request input")

        monkeypatch.setattr(app.state.model_settings, "protect_public", protect)
        simulated_peer(monkeypatch, app, tmp_path, change=change)
        response = client.post(
            "/api/editor/evaluate",
            headers=login(client),
            json={"yaml_text": droid_text(), "profile": "openpi-droid", "idempotency_key": "public-screen"},
        )
        job = wait_job(client, response.json()["id"], {"succeeded", "failed"})
        assert job["status"] == ("failed" if active else "succeeded")
        active = True
        download = client.get(f"/api/editor/evaluations/{job['id']}/artifacts/index.html")
        assert download.status_code in (404, 422)
        assert marker not in download.text


@pytest.mark.parametrize("when", ["before_acceptance", "after_acceptance"])
@pytest.mark.parametrize("spelling", ["html-u", "html-U", "html-x", "html-folded", "html-entity", "jsonl-u"])
def test_cross_chunk_escaped_credentials_rejected_at_acceptance_and_download(tmp_path, monkeypatch, when, spelling):
    """Real current credential guard and file readback; only the worker/OS seam is simulated."""
    import hashlib
    import html
    import json

    from fastapi import HTTPException

    from isaaclab_arena_examples.agentic_environment_generation.web_api.evaluation_artifacts import (
        MAX_ARTIFACT_BYTES,
        artifact_metadata,
    )

    marker = "synthetic-boundary-" + "k" * (4096 - len("synthetic-boundary-"))
    escape = {"html-x": "x", "html-U": "U"}.get(spelling, "u")
    digits = {"x": 2, "u": 4, "U": 8}[escape]
    encoded = "".join("\\" + escape + format(ord(c), f"0{digits}x") for c in marker)
    # Straddle both ends of the old 8192-character overlap, using ASCII so
    # byte and character boundaries coincide. Neither chunk contains the key.
    width, overlap = 128 * 1024, 8192
    start = width - overlap // 2 - len(encoded) // 2
    assert start < width - overlap and start + len(encoded) > width
    if spelling == "html-folded":
        middle = len(encoded) // 2
        encoded = encoded[:middle] + "\\\n" + " " * (width + 1) + encoded[middle:]
    if spelling == "jsonl-u":
        name = "episode_results_rank0.jsonl"
        prefix = '{"success":true,"padding":"'
        prefix += "p" * (start - len(prefix) - len('","note":"')) + '","note":"'
        text = prefix + encoded + '"}\n'
        assert json.loads(text)["note"] == marker
    else:
        name = "index.html"
        prefix = "<html><!--" + "p" * (start - len("<html><!----><pre>")) + "--><pre>"
        text = prefix + encoded + "</pre></html>"
        if spelling == "html-entity":
            text = text.replace("\\", "&#92;")
    data = text.encode("ascii")
    assert len(prefix) == start and len(data) < MAX_ARTIFACT_BYTES
    assert marker not in text and marker not in html.unescape(text)

    def change(result, root):
        (root / name).write_bytes(data)
        result["artifacts"] = [
            artifact_metadata(name, data) if row["name"] == name else row for row in result["artifacts"]
        ]

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        simulated_peer(monkeypatch, app, tmp_path, change=change)
        headers = login(client)

        def activate():
            saved = client.put(
                "/api/model-settings",
                headers=headers,
                json={"provider": "openai", "model": "offline-unit", "api_key": marker, "ttl_minutes": 15},
            )
            assert saved.status_code == 200
            assert marker not in saved.text
            with pytest.raises(HTTPException) as rejected:
                app.state.model_settings.protect_public(marker)
            assert rejected.value.status_code == 422 and rejected.value.detail == "Invalid request input"

        if when == "before_acceptance":
            activate()
        response = client.post(
            "/api/editor/evaluate",
            headers=headers,
            json={"yaml_text": droid_text(), "profile": "openpi-droid", "idempotency_key": "escaped-screen"},
        )
        assert response.status_code == 202
        job = wait_job(client, response.json()["id"], {"succeeded", "failed"})
        artifact = tmp_path / "evaluations" / job["id"] / "artifacts" / name
        assert artifact.read_bytes() == data  # candidate really reached the production verifier
        assert job["status"] == ("failed" if when == "before_acceptance" else "succeeded")
        url = f"/api/editor/evaluations/{job['id']}/artifacts/{name}"
        if when == "after_acceptance":
            row = next(row for row in job["result"]["artifacts"] if row["name"] == name)
            assert row == {"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            original = client.get(url)
            assert original.status_code == 200 and original.content == data
            activate()
        else:
            assert job["result"] is None
        download = client.get(url)
        assert download.status_code == (404 if when == "before_acceptance" else 422)
        assert marker not in download.text and encoded not in download.text
        assert artifact.read_bytes() == data  # screening must not rewrite sealed bytes
        assert app.state.journal.pending_workers() == []


def test_unverified_evaluation_cleanup_retains_dispatch_slot_and_lease(tmp_path, monkeypatch):
    import os
    import time

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_peer(monkeypatch, app, tmp_path, cleanup_error=True)
        headers = login(client)
        body = {"yaml_text": droid_text(), "profile": "openpi-droid", "idempotency_key": "cleanup-fault"}
        response = client.post("/api/editor/evaluate", headers=headers, json=body)
        job = wait_job(client, response.json()["id"], {"succeeded", "failed"})
        try:
            assert job["stage"] == "cleanup_pending" and job["status"] == "running"
            assert job["result"] is None and app.state.supervisor.process is not None
            assert app.state.editor_execution.build_lease_fd is not None
            assert app.state.journal.pending_workers()[0]["job_id"] == job["id"]
            later = client.post(
                "/api/editor/evaluate", headers=headers, json={**body, "idempotency_key": "later"}
            ).json()
            client.post("/api/jobs/resume-queue", headers=headers)
            time.sleep(0.3)
            assert client.get("/api/jobs/" + later["id"]).json()["status"] == "queued"
            assert events.count("spawn") == 1
        finally:
            # Dispose fake OS identities only; not a production recovery procedure.
            app.state.supervisor.paused = True
            app.state.supervisor._process_group.cleaned = True
            app.state.supervisor.process.returncode = 0
            for name in ("build_owner_fd", "build_lease_fd"):
                fd = getattr(app.state.editor_execution, name, None)
                if fd is not None:
                    os.close(fd)
                    setattr(app.state.editor_execution, name, None)


@pytest.mark.parametrize(
    "fault",
    [
        "before_callback",
        "missing_callback",
        "missing_report",
        "zero_episodes",
        "outside_output",
        "after_callback",
        "nonzero_return",
        "duplicate_callback",
    ],
)
def test_worker_main_emits_only_bounded_completion_or_private_failure(tmp_path, monkeypatch, fault, capsys):
    """Simulated harness boundary through the real worker envelope/protocol, no simulator imports."""
    import contextlib
    import io
    import json
    import sys
    import yaml
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    from isaaclab_arena_examples.agentic_environment_generation.web_api import evaluation_worker, snapshot_process

    validation = Documents(tmp_path / "docs").validate(droid_text())
    inputs = {
        **FIXED,
        "yaml_text": yaml.safe_dump(validation["spec"]),
        "document_id": None,
        "input_hash": validation["source_hash"],
        "canonical_hash": validation["canonical_hash"],
        "request_sha256": "e" * 64,
        "profile": "openpi-droid",
        "language_instruction": None,
    }
    root = tmp_path / "job"
    root.mkdir()
    channel = io.StringIO()

    @contextlib.contextmanager
    def private_channel():
        yield channel

    def fail():
        raise RuntimeError("synthetic private harness failure")

    def runner_main(**kwargs):
        assert kwargs["publish_to_graph"] is False and kwargs["update_lineage"] is False
        assert "--language_instruction" not in sys.argv  # null preserves the real task description
        if fault == "before_callback":
            fail()
        if fault == "missing_callback":
            return None
        output = (tmp_path / "outside") if fault == "outside_output" else root / "output" / "run"
        output.mkdir(parents=True)
        if fault != "missing_report":
            (output / "index.html").write_text("<html>unit report</html>")
        (output / "episode_results_rank0.jsonl").write_text("" if fault == "zero_episodes" else '{"success":null}\n')
        evidence = {
            "output_dir": str(output),
            "report_path": str(output / "index.html"),
            "metrics": None,
            "num_steps": 1000,
            "num_episodes": None,
            "warnings": [],
        }
        kwargs["on_evaluation_completed"](evidence)
        if fault == "after_callback":
            fail()
        if fault == "nonzero_return":
            return 1
        if fault == "duplicate_callback":
            kwargs["on_evaluation_completed"](evidence)
        return None

    monkeypatch.setitem(sys.modules, "isaaclab_arena.evaluation.policy_runner", SimpleNamespace(main=runner_main))
    monkeypatch.setattr(evaluation_worker, "private_channel", private_channel)
    monkeypatch.setattr(snapshot_process, "watch_parent", lambda fd: None)
    monkeypatch.setattr(sys, "argv", ["worker", "--owner-fd", "123"])
    monkeypatch.setattr(
        sys,
        "stdin",
        SimpleNamespace(buffer=io.BytesIO((json.dumps({"inputs": inputs, "output_root": str(root)}) + "\n").encode())),
    )
    assert evaluation_worker.main() == (0 if fault == "zero_episodes" else 1)
    messages = [json.loads(line) for line in channel.getvalue().splitlines()]
    assert messages[0] == {"stage": "evaluating_policy"}
    if fault == "zero_episodes":
        assert len(messages) == 2 and set(messages[1]) == {"result"}
        result = messages[1]["result"]
        assert result["episode_count"] == 0 and result["success_count"] is None
        assert result["metrics"] is None
        assert "No completed-episode evidence was recorded" in result["warnings"]
        assert "synthetic private" not in channel.getvalue() and str(root) not in channel.getvalue()
        assert "Traceback" not in capsys.readouterr().err
        return
    assert messages[-1] == {"error": "Evaluation failed; check private runtime logs"}
    assert sum("result" in m for m in messages) == int(
        fault in {"after_callback", "nonzero_return", "duplicate_callback"}
    )
    assert "synthetic private" not in channel.getvalue() and str(root) not in channel.getvalue()
    assert "Traceback" in capsys.readouterr().err
