# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Synthetic UNIX HTTP and CLI contracts, never model or simulation acceptance.

Live managed-server/model/graph persistence and simulation acceptance remain pending.
UID mismatch is injected at SO_PEERCRED; successful requests use real Linux credentials.
"""

import argparse
import hashlib
import json
import socket
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from socketserver import UnixStreamServer

import pytest

from isaaclab_arena_examples.agentic_environment_generation import environment_generation_runner as runner
from isaaclab_arena_examples.agentic_environment_generation import managed_workflow_cli as managed
from isaaclab_arena_examples.tests.test_workbench_publication_execution import ready as _publication_ready

publication_ready = _publication_ready


class RealAPITransport:
    """Actual HTTP routes and Journal completion; fake only model and graph I/O."""

    def __init__(self, peer, app):
        self.peer, self.app = peer, app
        self.calls = []
        self.csrf = None

    def request(self, method, path, body=None, *, raw=False):
        from isaaclab_arena_examples.tests.test_workbench_editor import FIXTURE
        from isaaclab_arena_examples.tests.test_workbench_publication_routes import ORIGIN

        self.calls.append((method, path, body))
        response = self.peer.request(
            method, path, json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": self.csrf or ""}
        )
        if not response.is_success:
            raise managed.ManagedError("Managed API rejected request")
        if path == "/api/sessions":
            self.csrf = response.json()["csrf_token"]
        if path == "/api/editor/generate":
            journal = self.app.state.journal
            job = response.json()
            # Only the model substitute claims; the real generation scheduler stays paused.
            journal.resume_queue()
            attempt = journal.claim_attempt(job["id"])
            assert attempt is not None
            assert journal.release_attempt(job["id"], **attempt)
            text = FIXTURE.read_text()
            receipt = dict(
                yaml_text=text,
                validation=dict(valid=True, source_hash=hashlib.sha256(text.encode()).hexdigest()),
                publication="not_published",
            )
            assert journal.commit_candidate(job["id"], **attempt, receipt=receipt)
            assert journal.complete_attempt(job["id"], **attempt, expected_state="candidate_committed")
        return response.content if raw else response.json()


def test_real_cli_preparation_is_not_publication(publication_ready, tmp_path, monkeypatch, capsys):
    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation, graph_access
    from isaaclab_arena_examples.tests.test_workbench_publication_routes import ORIGIN, app_for
    from isaaclab_arena_examples.tests.test_workbench_workflow_authorization import MODEL

    monkeypatch.setattr(generation, "configuration", lambda: MODEL)
    monkeypatch.setattr(graph_access, "configuration", lambda: None)
    monkeypatch.setattr(generation, "generate", forbidden)
    publication_ready.now[0] = time.time()
    app = app_for(publication_ready, tmp_path)
    with TestClient(app, base_url=ORIGIN) as peer:
        client = RealAPITransport(peer, app)
        monkeypatch.setattr(managed, "UnixTransport", lambda *a: client)
        target = app.state.publication_authorization.profile_metadata("graph")
        flags = [
            *FLAGS,
            "--mode",
            "resolve",
            "--managed_publication_profile",
            "graph",
            "--managed_publication_revision",
            target["revision"],
        ]
        monkeypatch.setattr(sys, "argv", ["runner", *flags])
        assert runner.main() == 0, client.calls
        output = json.loads(capsys.readouterr().out)
        assert output["publication"] == "prepared"
        assert output["persistence"] == "saved"
        save = next(body for method, path, body in client.calls if method == "POST" and path.endswith("/versions"))
        assert save["publication_target"] == target
        assert save["idempotency_key"] == "stable-op"
        assert app.state.publication_scheduler.worker_count == 0
        assert not app.state.publication_authorization._records
        assert not any("/publications/" in path for _, path, _ in client.calls)
        # The frozen target, not today's catalogue, controls immutable save replay.
        app.state.publication_profiles.clear()
        client.calls.clear()
        assert runner.main() == 0
        assert json.loads(capsys.readouterr().out)["version_ref"] == output["version_ref"]
        assert not any(
            path in ("/api/editor/generate", "/api/research/publication-profiles") for _, path, _ in client.calls
        )


def test_real_cli_explicit_publication_write(publication_ready, tmp_path, monkeypatch, capsys):
    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation, graph_access
    from isaaclab_arena_examples.tests.test_workbench_publication_routes import ORIGIN, app_for
    from isaaclab_arena_examples.tests.test_workbench_workflow_authorization import MODEL

    monkeypatch.setattr(generation, "configuration", lambda: MODEL)
    monkeypatch.setattr(graph_access, "configuration", lambda: None)
    monkeypatch.setattr(generation, "generate", forbidden)
    publication_ready.now[0] = time.time()
    app = app_for(publication_ready, tmp_path)
    with TestClient(app, base_url=ORIGIN) as peer:
        client = RealAPITransport(peer, app)
        monkeypatch.setattr(managed, "UnixTransport", lambda *a: client)
        target = app.state.publication_authorization.profile_metadata("graph")
        flags = [
            *FLAGS,
            "--mode",
            "resolve",
            "--managed_publication_profile",
            "graph",
            "--managed_publication_revision",
            target["revision"],
            "--managed_publication",
            "write",
            "--managed_publication_request_id",
            "publish-stable",
        ]
        monkeypatch.setattr(sys, "argv", ["runner", *flags])
        assert runner.main() == 0
        output = json.loads(capsys.readouterr().out)
        assert output["publication"] == "verified"
        assert output["persistence"] == "saved"
        effect = output["publication_effect_id"]
        base = f"/api/research/stores/store/publications/{effect}"
        writes = [(path, body) for method, path, body in client.calls if method == "POST" and "/publications/" in path]
        assert writes == [(base + "/write", {"request_id": "publish-stable"})]
        assert ("GET", base + "/requests/publish-stable", None) in client.calls
        assert output["publication_receipt"]["transport"]["verification_boundary"]["database_snapshot"] is False
        assert app.state.publication_scheduler.worker_count == 1
        assert not app.state.publication_scheduler.attempts["store"].pending_workers()
        assert "fake-private-publication-password" not in json.dumps(output)


def publication_flags(ready, action, request="publish-stable", previous=None):
    flags = [
        *FLAGS,
        "--mode",
        "resolve",
        "--managed_operation_id",
        "save",
        "--managed_reservation_id",
        ready.commit["reservation"]["reservation_id"],
        "--managed_publication_effect_id",
        "effect",
        "--managed_publication",
        action,
        "--managed_publication_request_id",
        request,
    ]
    if previous is not None:
        flags.extend(["--managed_publication_previous_request_id", previous])
    return flags


@pytest.mark.parametrize("other_session", [False, True])
def test_real_cli_observe_before_config_or_generation(publication_ready, tmp_path, monkeypatch, capsys, other_session):
    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.tests.test_workbench_publication_routes import BASE, ORIGIN, app_for, login, wait_for

    app = app_for(publication_ready, tmp_path)
    with TestClient(app, base_url=ORIGIN) as peer:
        headers = login(peer)
        response = peer.post(BASE + "/write", headers=headers, json={"request_id": "publish-stable"})
        assert response.status_code == 202
        wait_for(lambda: peer.get(response.headers["location"]).json()["state"]["state"] == "verified")
        # Accepted lookup must succeed without grants or current profile availability.
        app.state.publication_profiles.clear()
        app.state.publication_authorization.clear()
        monkeypatch.setattr(app.state.publication_authorization, "issue", forbidden)
        monkeypatch.setattr(app.state.workflow_authorization, "capture", forbidden)
        if other_session:
            peer.cookies.clear()
        client = RealAPITransport(peer, app)
        monkeypatch.setattr(managed, "UnixTransport", lambda *a: client)
        flags = publication_flags(publication_ready, "observe")
        # Recovery must not read old prompt/base files or resolve models.
        monkeypatch.setattr(sys, "argv", ["runner", *flags, "--base_spec", "/absent.yaml"])
        assert runner.main() == 2
        output = json.loads(capsys.readouterr().out)
        assert output["publication"] == "unknown"
        assert client.calls[1] == ("GET", BASE + "/requests/publish-stable", None)
        assert not any(method == "POST" and path != "/api/sessions" for method, path, _ in client.calls)
        if other_session:
            assert "session-bound" in output["error"]
            assert len(client.calls) == 2
        else:
            assert output["publication_accepted"] == response.json()["accepted"]
            assert "binding" in output["error"]
        assert app.state.publication_scheduler.worker_count == 1


@pytest.mark.parametrize("action", ["renew", "reconcile"])
def test_real_cli_explicit_followup_never_regenerates(publication_ready, tmp_path, monkeypatch, capsys, action):
    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.tests.test_workbench_publication_routes import BASE, ORIGIN, app_for, login, wait_for
    from isaaclab_arena_examples.tests.test_workbench_publication_worker import FAKE_CODE

    saved = tmp_path / "fake-graph.json"
    code = FAKE_CODE.replace("CLOSE_FAIL", "True").replace("EXPECT_COMMITS", "1")
    code = code.replace(
        "    def close():",
        f"    def close():\n        open({str(saved)!r}, 'w').write(json.dumps([driver.nodes, driver.edges]))",
    )
    app = app_for(publication_ready, tmp_path, code if action == "reconcile" else None)
    with TestClient(app, base_url=ORIGIN) as peer:
        headers = login(peer)
        auth = app.state.publication_authorization
        original_bind = auth.bind_attempt
        if action == "renew":
            monkeypatch.setattr(auth, "bind_attempt", lambda *a: (_ for _ in ()).throw(ValueError("private")))
        initial = peer.post(BASE + "/write", headers=headers, json={"request_id": "publish-stable"})
        assert initial.status_code == 202
        expected_state = "unknown" if action == "reconcile" else "blocked_authorization"
        wait_for(lambda: peer.get(initial.headers["location"]).json()["state"]["state"] == expected_state)
        monkeypatch.setattr(auth, "bind_attempt", original_bind)
        run = app.state.publication_scheduler
        if action == "reconcile":
            read = FAKE_CODE.replace("CLOSE_FAIL", "False").replace("EXPECT_COMMITS", "0")
            read = read.replace(
                "    def close():",
                f"    driver.nodes, driver.edges = json.load(open({str(saved)!r}))\n    def close():",
            )
            run.command = (sys.executable, "-c", read)
        client = RealAPITransport(peer, app)
        monkeypatch.setattr(managed, "UnixTransport", lambda *a: client)
        flags = publication_flags(publication_ready, action, "followup-stable", "publish-stable")
        monkeypatch.setattr(sys, "argv", ["runner", *flags])
        assert runner.main() == 0
        output = json.loads(capsys.readouterr().out)
        assert output["publication"] == "verified"
        accepted = output["publication_accepted"]
        assert accepted["operation"] == action
        assert accepted["capability"] == ("graph_read" if action == "reconcile" else "graph_write")
        assert accepted["previous_request_id"] == "publish-stable"
        assert [
            (path, body) for method, path, body in client.calls if method == "POST" and path != "/api/sessions"
        ] == [(BASE + "/" + action, {"request_id": "followup-stable", "previous_request_id": "publish-stable"})]
        count = run.worker_count
        app.state.publication_authorization.clear()
        monkeypatch.setattr(auth, "issue", forbidden)
        client.calls.clear()
        assert runner.main() == 0
        assert json.loads(capsys.readouterr().out)["publication_accepted"] == accepted
        assert run.worker_count == count
        assert not any(method == "POST" and path != "/api/sessions" for method, path, _ in client.calls)
        assert not run.attempts["store"].pending_workers()
        peer.cookies.clear()
        client.calls.clear()
        assert runner.main() == 2
        assert "session-bound" in json.loads(capsys.readouterr().out)["error"]
        assert not any(method == "POST" and path != "/api/sessions" for method, path, _ in client.calls)


def test_real_cli_saved_write_lost_acceptance_readonly_recovery(publication_ready, tmp_path, monkeypatch, capsys):
    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.tests.test_workbench_publication_routes import BASE, ORIGIN, app_for, wait_for

    app = app_for(publication_ready, tmp_path)
    with TestClient(app, base_url=ORIGIN) as peer:
        client = RealAPITransport(peer, app)
        request = client.request

        def lose(method, path, body=None, **kwargs):
            value = request(method, path, body, **kwargs)
            if path == BASE + "/write":
                raise OSError("lost accepted response private-marker")
            return value

        client.request = lose
        monkeypatch.setattr(managed, "UnixTransport", lambda *a: client)
        flags = publication_flags(publication_ready, "write")
        monkeypatch.setattr(sys, "argv", ["runner", *flags, "--base_spec", "/absent"])
        assert runner.main() == 2
        output = json.loads(capsys.readouterr().out)
        assert output["persistence"] == "saved"
        assert output["publication"] == "unknown"
        assert "session-bound" in output["error"]
        assert output["publication_request_id"] == "publish-stable"
        assert "private-marker" not in str(output)
        wait_for(lambda: peer.get(BASE + "/requests/publish-stable").json()["state"]["state"] == "verified")
        client.request = request
        client.calls.clear()
        monkeypatch.setattr(sys, "argv", ["runner", *publication_flags(publication_ready, "observe")])
        assert runner.main() == 0
        assert json.loads(capsys.readouterr().out)["publication"] == "verified"
        assert not any(method == "POST" and path != "/api/sessions" for method, path, _ in client.calls)
        assert app.state.publication_scheduler.worker_count == 1


def test_real_cli_profile_catalogue_is_readonly(publication_ready, tmp_path, monkeypatch, capsys):
    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.tests.test_workbench_publication_routes import ORIGIN, app_for

    app = app_for(publication_ready, tmp_path)
    with TestClient(app, base_url=ORIGIN) as peer:
        client = RealAPITransport(peer, app)
        monkeypatch.setattr(managed, "UnixTransport", lambda *a: client)
        monkeypatch.setattr(runner, "resolve_env_spec", forbidden)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "runner",
                "--mode",
                "resolve",
                "--managed_api_socket",
                "/unused.sock",
                "--managed_api_origin",
                ORIGIN,
                "--managed_publication",
                "profiles",
            ],
        )
        assert runner.main() == 0
        output = json.loads(capsys.readouterr().out)
        assert output["profiles"] == [
            {**app.state.publication_authorization.profile_metadata("graph"), "available": True}
        ]
        assert output["publication"] == "not_requested"
        assert [path for _, path, _ in client.calls] == ["/api/sessions", "/api/research/publication-profiles"]
        assert app.state.publication_scheduler.worker_count == 0
        assert not app.state.publication_authorization._records


@pytest.mark.parametrize(
    "corruption",
    [
        "acceptance_schema",
        "state_schema",
        "state_cancelled",
        "state_callback",
        "state_reconciliation",
        "state_generation",
        "binding_version",
        "receipt_missing",
        "receipt_snapshot",
        "receipt_attestation",
        "receipt_declaration",
        "receipt_database",
        "receipt_identity",
        "binding_target",
        "acceptance_drift",
        "exact_get_unavailable",
        "binding_unavailable",
    ],
)
def test_real_cli_publication_verification_boundaries(publication_ready, tmp_path, monkeypatch, capsys, corruption):
    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.tests.test_workbench_publication_routes import BASE, ORIGIN, app_for, login, wait_for

    app = app_for(publication_ready, tmp_path)
    with TestClient(app, base_url=ORIGIN) as peer:
        response = peer.post(BASE + "/write", headers=login(peer), json={"request_id": "publish-stable"})
        assert response.status_code == 202
        wait_for(lambda: peer.get(response.headers["location"]).json()["state"]["state"] == "verified")
        client = RealAPITransport(peer, app)
        request = client.request
        observations = 0

        def corrupt(method, path, body=None, **kwargs):
            nonlocal observations
            value = request(method, path, body, **kwargs)
            if "/requests/" in path:
                observations += 1
                if corruption == "acceptance_schema":
                    value["accepted"]["schema_version"] = True
                elif corruption == "state_schema":
                    value["state"]["schema_version"] = True
                elif corruption == "state_cancelled":
                    value["state"]["cancelled"] = 0
                elif corruption == "state_callback":
                    value["state"]["write_callback_open"] = 0
                elif corruption == "state_reconciliation":
                    value["state"]["reconciliation"] = {"state": True}
                elif corruption == "state_generation":
                    value["state"]["generation"] = True
                elif corruption == "receipt_missing":
                    value["state"]["receipt"] = None
                elif corruption.startswith("receipt_"):
                    receipt = value["state"]["receipt"]["transport"]
                    if corruption == "receipt_snapshot":
                        receipt["verification_boundary"]["database_snapshot"] = True
                    elif corruption == "receipt_attestation":
                        receipt["verification_boundary"]["operator_attested"] = 1
                    elif corruption == "receipt_declaration":
                        receipt["verification_boundary"]["declaration"] = "different"
                    elif corruption == "receipt_database":
                        receipt["database"] = "different"
                    elif corruption == "receipt_identity":
                        receipt["canonical_identity"]["name"] = "different"
                elif observations > 1 and corruption == "acceptance_drift":
                    value["accepted"]["request_id"] = "different"
                elif observations > 1 and corruption == "exact_get_unavailable":
                    raise OSError("private-marker")
            if path.endswith("/publication-binding"):
                if corruption == "binding_version":
                    value["versionRef"]["version"] = True
                elif corruption == "binding_target":
                    value["target"]["revision"] = "0" * 64
                elif corruption == "binding_unavailable":
                    raise OSError("private-marker")
            return value

        client.request = corrupt
        monkeypatch.setattr(managed, "UnixTransport", lambda *a: client)
        monkeypatch.setattr(sys, "argv", ["runner", *publication_flags(publication_ready, "observe")])
        assert runner.main() == 2
        output = json.loads(capsys.readouterr().out)
        assert output["publication"] == "unknown"
        assert "publication_receipt" not in output
        assert "private-marker" not in str(output)
        assert not any(method == "POST" and path != "/api/sessions" for method, path, _ in client.calls)
        assert app.state.publication_scheduler.worker_count == 1


def test_lost_save_is_unknown_not_unsaved(capsys):
    client = FakeTransport()
    request = client.request

    def lose(method, path, body=None, **kwargs):
        value = request(method, path, body, **kwargs)
        if method == "POST" and path.endswith("/versions"):
            raise OSError("private-marker")
        return value

    client.request = lose
    assert managed.run_managed(args(), transport=client) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["persistence"] == "unknown"
    assert output["publication"] == "not_requested"
    assert output["operation_id"] == "stable-op"
    client.request = request
    assert managed.run_managed(args(), transport=client) == 0
    assert json.loads(capsys.readouterr().out)["persistence"] == "saved"
    saves = [body for method, path, body in client.calls if method == "POST" and path.endswith("/versions")]
    assert len(saves) == 2 and saves[0] == saves[1]
    assert len([path for _, path, _ in client.calls if path == "/api/editor/generate"]) == 1


def test_live_unix_session_reestablishment_does_not_require_new_cookie(tmp_path):
    path = tmp_path / "sessions.sock"
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            seen.append(self.headers.get("Cookie"))
            body = b'{"csrf_token":"private-csrf","session_id":"owner"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if len(seen) == 1:
                self.send_header("Set-Cookie", "arena=private-cookie; HttpOnly; Path=/api; SameSite=Strict")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with UnixStreamServer(str(path), Handler) as server:
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        try:
            client = managed.UnixTransport(path, "http://localhost")
            original = client.request("POST", "/api/sessions", {})
            assert client.request("POST", "/api/sessions", {}) == original
            assert seen == [None, "arena=private-cookie"]
            assert client.cookie == "arena=private-cookie"
        finally:
            server.shutdown()
            worker.join(2)
            assert not worker.is_alive()


@pytest.mark.parametrize(
    "corruption",
    ["request_digest", "state_effect"]
    + [
        f"accepted:{key}:{value}"
        for key, value in (
            ("schema_version", "true"),
            ("schema_version", "2"),
            ("generation", "true"),
            ("generation", "1.0"),
            ("generation", "0"),
            ("generation", "2"),
            ("attempt_id", '"bad"'),
            ("attempt_id", '"' + "a" * 32 + '"'),
            ("capability", '"graph_read"'),
            ("operation", '"bogus"'),
        )
    ]
    + [
        f"state:{key}:{value}"
        for key, value in (
            ("schema_version", "true"),
            ("schema_version", "2"),
            ("generation", "true"),
            ("generation", "1.0"),
            ("cancelled", "0"),
            ("cancelled", "null"),
            ("write_callback_open", "0"),
            ("write_callback_open", "null"),
            ("write_claim_count", "true"),
            ("state", "true"),
            ("reconciliation", "false"),
            ("reconciliation", '{"state":true}'),
            ("receipt", "false"),
            ("receipt", "{}"),
            ("target_profile", "{}"),
            ("payload_sha256", '"' + "0" * 64 + '"'),
        )
    ],
)
@pytest.mark.parametrize("action", ["renew", "reconcile"])
def test_corrupt_predecessor_never_authorizes_followup(
    publication_ready, tmp_path, monkeypatch, capsys, corruption, action
):
    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.tests.test_workbench_publication_routes import BASE, ORIGIN, app_for, login, wait_for
    from isaaclab_arena_examples.tests.test_workbench_publication_worker import FAKE_CODE

    code = FAKE_CODE.replace("CLOSE_FAIL", "True").replace("EXPECT_COMMITS", "1")
    app = app_for(publication_ready, tmp_path, code if action == "reconcile" else None)
    with TestClient(app, base_url=ORIGIN) as peer:
        if action == "renew":
            monkeypatch.setattr(
                app.state.publication_authorization,
                "bind_attempt",
                lambda *a: (_ for _ in ()).throw(ValueError("blocked")),
            )
        response = peer.post(BASE + "/write", headers=login(peer), json={"request_id": "publish-stable"})
        assert response.status_code == 202
        expected = "blocked_authorization" if action == "renew" else "unknown"
        wait_for(lambda: peer.get(response.headers["location"]).json()["state"]["state"] == expected)
        client = RealAPITransport(peer, app)
        request = client.request

        def corrupt(method, path, body=None, **kwargs):
            value = request(method, path, body, **kwargs)
            if "/requests/" in path:
                if corruption == "request_digest":
                    value["accepted"]["request_digest"] = "0" * 64
                elif corruption == "state_effect":
                    value["state"]["effect_id"] = "other"
                else:
                    section, key, replacement = corruption.split(":", 2)
                    value[section][key] = json.loads(replacement)
                    if section == "accepted":
                        binding = {
                            k: value[section][k]
                            for k in (
                                "store_id",
                                "effect_id",
                                "request_id",
                                "owner_session",
                                "principal",
                                "operation",
                                "previous_request_id",
                            )
                        }
                        value[section]["request_digest"] = digest(binding)
            return value

        client.request = corrupt
        monkeypatch.setattr(managed, "UnixTransport", lambda *a: client)
        monkeypatch.setattr(
            sys, "argv", ["runner", *publication_flags(publication_ready, action, "followup", "publish-stable")]
        )
        assert runner.main() == 2
        capsys.readouterr()
        assert not any(method == "POST" and path != "/api/sessions" for method, path, _ in client.calls)
        assert app.state.publication_scheduler.attempts["store"].get_acceptance("followup") is None


def wire_server(path, chunks):
    """Serve finite synthetic HTTP bytes, with bounded shutdown even on failure."""

    @contextmanager
    def serve():
        stopped = threading.Event()
        received = []
        errors = []
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            listener.listen(1)
            listener.settimeout(0.05)

            def respond():
                try:
                    while not stopped.is_set():
                        try:
                            peer, _ = listener.accept()
                            break
                        except TimeoutError:
                            continue
                    else:
                        return
                    with peer:
                        peer.settimeout(0.5)
                        received.append(peer.recv(65536))
                        for delay, chunk in chunks:
                            if stopped.wait(delay):
                                break
                            peer.sendall(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as error:
                    errors.append(type(error).__name__)

            worker = threading.Thread(target=respond, name="synthetic-unix-http")
            worker.start()
            try:
                yield received
            finally:
                stopped.set()
                worker.join(1)
                assert not worker.is_alive()
                assert not errors

    return serve()


@pytest.mark.parametrize("phase", ["headers", "body", "combined", "upload"])
def test_absolute_request_deadline(tmp_path, phase, capsys):
    path = tmp_path / "deadline.sock"
    headers = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 42\r\n\r\n"
    body = b'{"value":"' + b"x" * 30 + b'"}'
    chunks = (
        [(0.025, bytes([byte])) for byte in headers] + [(0, body)]
        if phase == "headers"
        else [(0, headers)] + [(0.025, bytes([byte])) for byte in body]
    )
    payload = {"prompt": "secret-marker"}
    if phase == "combined":
        chunks = [(0.1, headers), (0.1, body)]
    elif phase == "upload":
        chunks = [(0.8, b"")]
        payload["prompt"] += "x" * (1024 * 1024)
    with wire_server(path, chunks):
        client = managed.UnixTransport(path, "http://localhost", timeout=0.15)
        started = time.monotonic()
        with pytest.raises(managed.ManagedError):
            client.request("POST", "/api/editor", payload)
        assert time.monotonic() - started < 0.65
    assert "secret-marker" not in capsys.readouterr().out


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class FakeTransport:
    def __init__(self, *args):
        self.calls = []
        self.job = None
        self.source = {
            "job_id": "a" * 32,
            "attempt_id": "b" * 32,
            "generation": 1,
            "receipt_sha256": "c" * 64,
            "request_sha256": "d" * 64,
        }
        reservation = {
            "reservation_id": "e" * 32,
            "revision_id": "f" * 32,
            "registry_id": "1" * 32,
            "store_id": "store",
            "family": "family",
            "workflow_id": "stable-op",
            "version": 1,
            "parent_revision_id": None,
            "source": self.source,
        }
        self.artifact = b"test artifact"
        manifest = {
            "schema": 1,
            "binding": reservation,
            "store_id": "store",
            "registry_id": "1" * 32,
            "reservation_id": "e" * 32,
            "files": {
                "environment.yaml": {
                    "sha256": hashlib.sha256(self.artifact).hexdigest(),
                    "size": len(self.artifact),
                }
            },
        }
        manifest["digest"] = digest(manifest)
        self.commit = {
            "reservation": reservation,
            "manifest": manifest,
            "publication_intent_id": None,
        }

    def request(self, method, path, body=None, *, raw=False):
        self.calls.append((method, path, body))
        if path == "/api/sessions":
            return {"csrf_token": "private-csrf"}
        if path == "/api/editor":
            return {"capabilities": {"generation_modes": True, "generation": True}}
        if path == "/api/model-settings":
            return {"configured": True, "source": "server", "model": "server-model"}
        if path == "/api/research/stores":
            return {"stores": [{"store_id": "store", "available": True}]}
        if path.startswith("/api/editor/generate/operations/"):
            return {"job": self.job}
        if path == "/api/editor/generate":
            from isaaclab_arena_examples.agentic_environment_generation.web_api.editor import GenerateDraft

            inputs = {
                "request_sha256": digest(GenerateDraft(**body).model_dump()),
                "workflow_authorization": {"model": {"profile": {"source": "server", "model": "server-model"}}},
            }
            self.job = {"id": "a" * 32, "status": "succeeded", "kind": "generate", "inputs": inputs}
            self.source["request_sha256"] = digest(inputs)
            manifest = self.commit["manifest"]
            manifest["digest"] = digest({k: v for k, v in manifest.items() if k != "digest"})
            return self.job
        if path == "/api/jobs/" + "a" * 32:
            return self.job
        if "/candidates/" in path:
            return self.source
        if raw:
            return self.artifact
        return self.commit


def args(extra=()):
    parser = argparse.ArgumentParser()
    runner.add_agentic_env_gen_runner_cli_args(parser)
    return parser.parse_args([*FLAGS, "--mode", "resolve", *extra])


@pytest.mark.parametrize("failure", ["uid", "credentials-error", "inode", "symlink", "owner"])
def test_peer_and_path_races_send_no_bytes(tmp_path, monkeypatch, failure, capsys):
    import os
    import struct

    path = tmp_path / "peer.sock"
    with wire_server(path, []) as received:
        client = managed.UnixTransport(path, "http://localhost", timeout=0.2)
        client.cookie = "arena=secret-marker"
        original = managed.DeadlineSocket.connect
        credentials = managed.DeadlineSocket.getsockopt

        def connect(sock, address):
            value = original(sock, address)
            if failure in ("inode", "symlink"):
                path.rename(tmp_path / "old.sock")
                if failure == "symlink":
                    path.symlink_to(tmp_path / "old.sock")
                else:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as replacement:
                        replacement.bind(str(path))
            return value

        def getsockopt(sock, level, option, size):
            assert (level, option) == (socket.SOL_SOCKET, socket.SO_PEERCRED)
            if failure == "credentials-error":
                raise OSError("secret-marker")
            value = credentials(sock, level, option, size)
            pid, uid, gid = struct.unpack("3i", value)
            return struct.pack("3i", pid, uid + 1, gid) if failure == "uid" else value

        monkeypatch.setattr(managed.DeadlineSocket, "connect", connect)
        monkeypatch.setattr(managed.DeadlineSocket, "getsockopt", getsockopt)
        if failure == "owner":
            monkeypatch.setattr(os, "geteuid", lambda: 999999)
        with pytest.raises(managed.ManagedError) as error:
            client.request("POST", "/api/editor", {"prompt": "secret-marker"})
        assert "secret-marker" not in str(error.value)
    assert not any(received)
    assert "secret-marker" not in capsys.readouterr().out


@pytest.mark.parametrize("feature", ["platform", "credentials"])
def test_unsupported_peer_profile_fails_closed(tmp_path, monkeypatch, feature):
    path = tmp_path / "unsupported.sock"
    with wire_server(path, []) as received:
        if feature == "platform":
            monkeypatch.setattr(sys, "platform", "darwin")
        else:
            monkeypatch.delattr(socket, "SO_PEERCRED")
        with pytest.raises(managed.ManagedError):
            managed.UnixTransport(path, "http://localhost")
    assert not received


@pytest.mark.parametrize(
    "wire",
    [
        b"",
        b"secret-marker\r\n\r\n",
        b"HTTP/1.1 xyz secret-marker\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Length: secret-marker\r\n\r\n{}",
        b"HTTP/1.1 200 OK\r\nContent-Length: -1\r\n\r\n{}",
        b"HTTP/1.1 200 OK\r\nContent-Length: +2\r\n\r\n{}",
        b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Length: 3\r\n\r\n{}",
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Length: 2\r\n\r\n0\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\n{}",
        b"HTTP/1.1 200 OK\r\nContent-Length: 2097153\r\n\r\n",
        b"HTTP/1.0 200 OK\r\n\r\n" + b"x" * (managed.MAX_RESPONSE_BYTES + 1),
    ],
)
def test_bad_http_framing_is_bounded_and_sanitized(tmp_path, wire, capsys):
    import traceback

    path = tmp_path / "framing.sock"
    with wire_server(path, [(0, wire)]):
        client = managed.UnixTransport(path, "http://localhost", timeout=0.2)
        started = time.monotonic()
        with pytest.raises(managed.ManagedError) as error:
            client.request("GET", "/api/editor", raw=True)
        assert time.monotonic() - started < 0.65
        assert "secret-marker" not in "".join(traceback.format_exception(error.value))
    assert "secret-marker" not in capsys.readouterr().out


def test_cleanup_exceptions_are_sanitized(tmp_path, monkeypatch, capsys):
    path = tmp_path / "cleanup.sock"
    original = managed.UnixHTTPConnection.close

    def close(connection):
        original(connection)
        raise OSError("secret-marker")

    with wire_server(path, [(0, b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")]):
        monkeypatch.setattr(managed.UnixHTTPConnection, "close", close)
        client = managed.UnixTransport(path, "http://localhost", timeout=0.2)
        with pytest.raises(managed.ManagedError) as error:
            client.request("GET", "/api/editor", raw=True)
        assert "secret-marker" not in str(error.value)
    assert "secret-marker" not in capsys.readouterr().out


@pytest.mark.parametrize("outcome", ["success", "headers", "body", "framing"])
def test_http10_response_cleanup_without_gc_or_threads(tmp_path, monkeypatch, outcome):
    sockets = []
    original = managed.DeadlineSocket.__init__

    def init(sock, deadline):
        original(sock, deadline)
        sockets.append(sock)

    monkeypatch.setattr(managed.DeadlineSocket, "__init__", init)
    baseline = set(threading.enumerate())
    wire = b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\n{}"
    chunks = [(0, wire)]
    if outcome == "headers":
        chunks = [(0.025, bytes([byte])) for byte in wire]
    elif outcome == "body":
        chunks = [(0, wire[:-2]), (0.4, b"{}")]
    elif outcome == "framing":
        chunks = [(0, b"HTTP/1.0 200 OK\r\nContent-Length: 9999999\r\n\r\n")]
    for index in range(6):
        path = tmp_path / f"cleanup{index}.sock"
        with wire_server(path, chunks):
            client = managed.UnixTransport(path, "http://localhost", timeout=0.15)
            started = time.monotonic()
            if outcome == "success":
                assert client.request("GET", "/api/editor", raw=True) == b"{}"
            else:
                with pytest.raises(managed.ManagedError) as error:
                    client.request("GET", "/api/editor", raw=True)
                # Retain traceback/response references: cleanup must not depend on GC.
                assert error.value
            assert time.monotonic() - started < 0.65
            assert all(sock.fileno() == -1 for sock in sockets)
    assert set(threading.enumerate()) == baseline


@pytest.mark.parametrize(
    "extra",
    [
        ["--prompt", "--literal prompt value"],
        ["--prompt=--literal"],
        ["--prompt", "-a literal prompt"],
    ],
)
def test_argparse_prompt_values_are_not_overrides(extra, capsys):
    client = FakeTransport()
    parsed = args(extra)
    assert managed.run_managed(parsed, argv=[*FLAGS, "--mode", "resolve", *extra], transport=client) == 0
    payload = next(body for _, path, body in client.calls if path == "/api/editor/generate")
    assert payload["prompt"] == parsed.prompt
    capsys.readouterr()


@pytest.mark.parametrize(
    "extra", [["--temperature=0.2"], ["--prompt=--out_dir", "--out_dir=/tmp/no"], ["--temp", "0.2"]]
)
def test_argparse_unsupported_options_still_rejected(extra, capsys):
    client = FakeTransport()
    assert managed.run_managed(args(extra), argv=extra, transport=client) == 2
    assert not client.calls
    capsys.readouterr()


def test_new_exact_candidate_persistence(capsys):
    transport = FakeTransport()
    assert managed.run_managed(args(), transport=transport) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["publication"] == "not_requested"
    assert output["version_ref"]["revision_id"] == "f" * 32
    payload = next(body for method, path, body in transport.calls if path == "/api/editor/generate")
    assert payload == {
        "operation": "new",
        "prompt": runner.DEFAULT_PROMPT,
        "retrieval_policy": "allow_fallback",
        "idempotency_key": "stable-op",
    }
    save = next(body for method, path, body in transport.calls if method == "POST" and path.endswith("/versions"))
    assert save == {
        "idempotency_key": "stable-op",
        "family": "family",
        "parent_revision_id": None,
        "source_job_id": "a" * 32,
        "source_attempt_id": "b" * 32,
        "source_generation": 1,
    }
    assert "private-csrf" not in json.dumps(output)


FLAGS = [
    "--managed_api_socket",
    "/tmp/arena.sock",
    "--managed_api_origin",
    "http://localhost:8000",
    "--managed_store_id",
    "store",
    "--managed_family",
    "family",
    "--managed_operation_id",
    "stable-op",
]


def forbidden(*args, **kwargs):
    pytest.fail("Legacy/model/simulation must not run")


@pytest.mark.parametrize(
    "extra",
    [
        ["--api_key", "secret-value"],
        ["--temperature", "0.2"],
        ["--base_url", "https://example.com"],
        ["--out_dir", "/tmp/out"],
    ],
)
def test_unsupported_overrides_before_requests(extra, capsys):
    transport = FakeTransport()
    assert managed.run_managed(args(extra), argv=extra, transport=transport) == 2
    assert transport.calls == []
    assert "secret-value" not in capsys.readouterr().out


def test_refine_frozen_base(tmp_path, capsys):
    from pathlib import Path

    path = tmp_path / "base.yaml"
    text = Path("isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml").read_text()
    path.write_text(text)
    transport = FakeTransport()
    assert (
        managed.run_managed(
            args(["--base_spec", str(path), "--feedback", "move cube"]),
            transport=transport,
        )
        == 0
    )
    body = next(body for _, path, body in transport.calls if path == "/api/editor/generate")
    assert body["operation"] == "refine" and body["base_yaml"] == text and body["prompt"] == "move cube"
    assert "document_id" not in body


@pytest.mark.parametrize("text", ["external_yaml: missing.yaml", "{}", "x: &x [*x]", "x" * (256 * 1024 + 1)])
def test_invalid_base_never_uses_template(tmp_path, text):
    path = tmp_path / "base.yaml"
    path.write_text(text)
    transport = FakeTransport()
    assert managed.run_managed(args(["--base_spec", str(path)]), transport=transport) == 2
    assert transport.calls == []


@pytest.mark.parametrize(
    "origin",
    [
        "https://localhost:8000",
        "http://example.com",
        "http://localhost:8000/",
        "http://user@localhost:8000",
        "http://127.0.0.1:8000?x",
        "http://LOCALHOST:8000",
    ],
)
def test_reject_nonexact_origin(origin, tmp_path):
    with pytest.raises(managed.ManagedError):
        managed.UnixTransport(tmp_path / "missing", origin)


def test_unix_transport_session_bounds_and_no_tcp(tmp_path, monkeypatch):
    path = tmp_path / "server.sock"
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(dict(self.headers))
            body = b'{"csrf_token":"private-csrf"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header(
                "Set-Cookie",
                "arena=private-cookie; HttpOnly; Path=/api; SameSite=Strict",
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            seen.append(dict(self.headers))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(managed.MAX_RESPONSE_BYTES + 1))
            self.end_headers()

        def log_message(self, *args):
            pass

    with UnixStreamServer(str(path), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        monkeypatch.setattr(socket, "create_connection", forbidden)
        monkeypatch.setattr(socket, "getaddrinfo", forbidden)
        try:
            client = managed.UnixTransport(path, "http://localhost:8000")
            client.request("POST", "/api/sessions", {})
            with pytest.raises(managed.ManagedError):
                client.request("GET", "/api/editor")
            assert seen[0]["Host"] == "localhost:8000" and seen[0]["Origin"] == "http://localhost:8000"
            assert seen[1]["Cookie"] == "arena=private-cookie"
            assert seen[1]["X-CSRF-Token"] == "private-csrf"
            link = tmp_path / "link"
            link.symlink_to(path)
            with pytest.raises(managed.ManagedError):
                managed.UnixTransport(link, "http://localhost:8000")
        finally:
            server.shutdown()
            thread.join()
    ordinary = tmp_path / "file"
    ordinary.touch()
    with pytest.raises(managed.ManagedError):
        managed.UnixTransport(ordinary, "http://localhost:8000")


@pytest.mark.parametrize(
    "route,replacement",
    [
        ("/api/editor", {"capabilities": {"generation": True}}),
        ("/api/model-settings", {"configured": False}),
        (
            "/api/model-settings",
            {"configured": True, "source": "session", "model": "secret"},
        ),
        ("/api/editor/generate", {}),
        ("/api/jobs/" + "a" * 32, {"id": "b" * 32, "status": "succeeded"}),
        ("/api/research/stores/store/candidates/" + "a" * 32, {"job_id": "b" * 32}),
    ],
)
def test_bad_contract_fails_closed(route, replacement, capsys):
    client = FakeTransport()
    request = client.request
    client.request = lambda method, path, body=None, **kw: (
        replacement if path == route else request(method, path, body, **kw)
    )
    assert managed.run_managed(args(), transport=client) == 2
    assert "secret" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "status",
    ["blocked_authorization", "indeterminate", "failed", "cancelled", "running"],
)
def test_accepted_work_not_retried_or_cancelled(status, capsys):
    client = FakeTransport()
    request = client.request

    def wrapped(method, path, body=None, **kw):
        value = request(method, path, body, **kw)
        if path.startswith("/api/jobs/"):
            value["status"] = status
        return value

    client.request = wrapped
    assert managed.run_managed(args(), transport=client, deadline_seconds=0) == 2
    assert json.loads(capsys.readouterr().out)["job_id"] == "a" * 32
    assert len([1 for method, path, _ in client.calls if path == "/api/editor/generate"]) == 1
    assert not any("cancel" in path or "reauthor" in path or method == "DELETE" for method, path, _ in client.calls)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"job":null,"job":null}',
        b'{"payload":{"secret-marker":1,"secret-marker":2}}',
        b'{"payload":[{"x":1,"\\u0078":2}]}',
    ],
)
def test_wire_duplicate_keys_are_rejected_at_all_depths(tmp_path, payload):
    path = tmp_path / "duplicates.sock"
    wire = (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(payload)).encode()
        + b"\r\n\r\n"
        + payload
    )
    with wire_server(path, [(0, wire)]):
        client = managed.UnixTransport(path, "http://localhost")
        with pytest.raises(managed.ManagedError, match="Ambiguous JSON response") as error:
            client.request("GET", "/api/test")
        assert "secret-marker" not in str(error.value)


def test_duplicate_key_wire_lookup_never_submits_generation(tmp_path):
    path = tmp_path / "ambiguous.sock"
    payload = b'{"job":{"id":"accepted-job"},"job":null}'
    wire = (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(payload)).encode()
        + b"\r\n\r\n"
        + payload
    )
    client = FakeTransport()
    original = client.request
    with wire_server(path, [(0, wire)]):
        transport = managed.UnixTransport(path, "http://localhost")

        def request(method, route, body=None, **kwargs):
            if route.startswith("/api/editor/generate/operations/"):
                return transport.request(method, route, body, **kwargs)
            return original(method, route, body, **kwargs)

        client.request = request
        assert managed.run_managed(args(), transport=client) == 2
    assert not any(method == "POST" and route == "/api/editor/generate" for method, route, _ in client.calls)


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_wire_nonfinite_constants_are_rejected(tmp_path, constant):
    payload = b'{"nested":[{"secret-marker":' + constant + b"}]}"
    wire = (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(payload)).encode()
        + b"\r\n\r\n"
        + payload
    )
    path = tmp_path / "nonfinite.sock"
    with wire_server(path, [(0, wire)]):
        with pytest.raises(managed.ManagedError, match="Invalid JSON constant") as error:
            managed.UnixTransport(path, "http://localhost").request("GET", "/api/test")
        assert "secret-marker" not in str(error.value)


@pytest.mark.parametrize("number", [b"1e999", b"-1e999", b"9.99e400"])
def test_wire_overflow_exponents_are_rejected(tmp_path, number):
    payload = b'{"nested":[{"private-marker":' + number + b"}]}"
    wire = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
    wire += str(len(payload)).encode() + b"\r\n\r\n" + payload
    path = tmp_path / "overflow.sock"
    with wire_server(path, [(0, wire)]):
        with pytest.raises(managed.ManagedError, match="Invalid JSON number") as error:
            managed.UnixTransport(path, "http://localhost").request("GET", "/api/test")
    assert "private-marker" not in str(error.value)


@pytest.mark.parametrize("number", [b"1.25", b"-1.25", b"1e308", b"-1e-308", b"0.0"])
def test_wire_finite_numbers_remain_valid(tmp_path, number):
    payload = b'{"nested":[' + number + b"]}"
    wire = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
    wire += str(len(payload)).encode() + b"\r\n\r\n" + payload
    path = tmp_path / "finite.sock"
    with wire_server(path, [(0, wire)]):
        result = managed.UnixTransport(path, "http://localhost").request("GET", "/api/test")
    assert result == {"nested": [float(number)]}


def test_known_publication_acceptance_get_failure(publication_ready, tmp_path, monkeypatch, capsys):
    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.tests.test_workbench_publication_routes import BASE, ORIGIN, app_for

    app = app_for(publication_ready, tmp_path)
    with TestClient(app, base_url=ORIGIN) as peer:
        client = RealAPITransport(peer, app)
        request = client.request
        accepted = []

        def fail_get(method, path, body=None, **kwargs):
            if "/requests/" in path:
                raise managed.ManagedError(
                    "Managed response unavailable or ambiguous; rerun unchanged with the same operation ID"
                )
            value = request(method, path, body, **kwargs)
            if path == BASE + "/write":
                accepted.append(value["accepted"])
            return value

        client.request = fail_get
        monkeypatch.setattr(managed, "UnixTransport", lambda *a: client)
        monkeypatch.setattr(sys, "argv", ["runner", *publication_flags(publication_ready, "write")])
        assert runner.main() == 2
        output = json.loads(capsys.readouterr().out)
        assert output["publication_accepted"] == accepted[0]
        assert output["publication_effect_id"] == "effect"
        assert output["publication_request_id"] == "publish-stable"
        assert output["version_ref"]["reservation_id"] == publication_ready.commit["reservation"]["reservation_id"]
        assert output["publication"] == "unknown"
        assert "accepted" in output["error"]
        assert "session-bound" in output["error"]
        assert "read-only" in output["error"]
        assert "rerun unchanged" not in output["error"]


def test_lost_submission_same_operation_replay(capsys):
    client = FakeTransport()
    request = client.request
    lost = True

    def wrapped(method, path, body=None, **kw):
        nonlocal lost
        value = request(method, path, body, **kw)
        if path == "/api/editor/generate" and lost:
            lost = False
            raise OSError("secret-cookie-and-key")
        return value

    client.request = wrapped
    assert managed.run_managed(args(), transport=client) == 2
    output = capsys.readouterr().out
    assert "stable-op" in output and "secret-cookie" not in output
    assert managed.run_managed(args(), transport=client) == 0
    submissions = [body for _, path, body in client.calls if path == "/api/editor/generate"]
    assert len(submissions) == 1


@pytest.mark.parametrize("boundary", ["job", "candidate"])
def test_requested_operation_fingerprint_is_bound_through_save(boundary):
    client = FakeTransport()
    request = client.request

    def wrapped(method, path, body=None, **kw):
        value = request(method, path, body, **kw)
        if boundary == "job" and path.startswith("/api/jobs/"):
            return {**value, "inputs": {**value["inputs"], "request_sha256": "0" * 64}}
        if boundary == "candidate" and "/candidates/" in path:
            return {**value, "request_sha256": "0" * 64}
        return value

    client.request = wrapped
    assert managed.run_managed(args(), transport=client) == 2
    assert not any(method == "POST" and path.endswith("/versions") for method, path, _ in client.calls)


@pytest.mark.parametrize("lookup", [{}, {"job": False}, {"job": None, "error": "ambiguous"}])
def test_ambiguous_lookup_never_submits(lookup):
    client = FakeTransport()
    request = client.request
    client.request = lambda method, path, body=None, **kw: (
        lookup if "/operations/" in path else request(method, path, body, **kw)
    )
    assert managed.run_managed(args(), transport=client) == 2
    assert not any(path == "/api/editor/generate" for _, path, _ in client.calls)


@pytest.mark.parametrize(
    "field,value",
    [
        ("family", "other"),
        ("workflow_id", "other"),
        ("parent_revision_id", "1" * 32),
        ("revision_id", "bad"),
    ],
)
def test_commit_binding_rejected(field, value):
    client = FakeTransport()
    client.commit["reservation"][field] = value
    assert managed.run_managed(args(), transport=client) == 2


def test_artifact_hash_rejected():
    client = FakeTransport()
    client.artifact = b"changed"
    assert managed.run_managed(args(), transport=client) == 2


def test_real_runner_resolve_dispatch_and_legacy_preserved(monkeypatch):
    client = FakeTransport()
    monkeypatch.setattr(managed, "UnixTransport", lambda *a: client)
    monkeypatch.setattr(runner, "SimulationAppContext", forbidden)
    monkeypatch.setattr(runner, "resolve_env_spec", forbidden)
    monkeypatch.setattr(sys, "argv", ["runner", *FLAGS, "--mode", "resolve"])
    assert runner.main() == 0
    calls = []
    monkeypatch.setattr(runner, "resolve_env_spec", lambda args: calls.append(args.temperature))
    monkeypatch.setattr(sys, "argv", ["runner", "--mode", "resolve"])
    assert runner.main() == 0 and calls == [0.2]


@pytest.mark.parametrize("configuration", ["changed", "disabled"])
def test_real_api_lost_acceptance_recovers_without_current_model(tmp_path, monkeypatch, capsys, configuration):
    from fastapi.testclient import TestClient

    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, generation, graph_access
    from isaaclab_arena_examples.tests.test_workbench_editor import FIXTURE, ORIGIN
    from isaaclab_arena_examples.tests.test_workbench_workflow_authorization import MODEL

    model = {**MODEL, "model": "server-model"}
    monkeypatch.setattr(generation, "configuration", lambda: dict(model) if model else None)
    monkeypatch.setattr(graph_access, "configuration", lambda: None)
    monkeypatch.setattr(generation, "generate", forbidden)
    app = create_app(tmp_path / "state", start_paused=True, research_roots={"store": tmp_path / "store"})
    with TestClient(app, base_url=ORIGIN) as peer:
        with ResearchStore.create(
            app.state.journal, tmp_path / "store", "store", protect_public=app.state.model_settings.protect_public
        ):
            pass

        class APITransport:
            def __init__(self):
                self.calls = []
                self.csrf = None
                self.lost = True

            def request(self, method, path, body=None, *, raw=False):
                self.calls.append((method, path))
                response = peer.request(
                    method, path, json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": self.csrf or ""}
                )
                assert response.is_success, response.text
                if path == "/api/sessions":
                    self.csrf = response.json()["csrf_token"]
                if path == "/api/editor/generate" and self.lost:
                    self.lost = False
                    raise OSError("Lost accepted response")
                return response.content if raw else response.json()

        client = APITransport()
        requested = args(["--model", "server-model"])
        assert managed.run_managed(requested, transport=client) == 2
        capsys.readouterr()
        job = app.state.journal.get_submission("default", "stable-op")
        assert job is not None
        attempt = app.state.journal.claim_attempt(job["id"])
        assert app.state.journal.release_attempt(job["id"], **attempt)
        text = FIXTURE.read_text()
        receipt = {
            "yaml_text": text,
            "validation": {"valid": True, "source_hash": hashlib.sha256(text.encode()).hexdigest()},
            "publication": "not_published",
        }
        assert app.state.journal.commit_candidate(job["id"], **attempt, receipt=receipt)
        assert app.state.journal.complete_attempt(job["id"], **attempt, expected_state="candidate_committed")
        peer.cookies.clear()
        model.clear() if configuration == "disabled" else model.update(model="replacement-model")
        monkeypatch.setattr(app.state.workflow_authorization, "capture", forbidden)
        monkeypatch.setattr(app.state.workflow_authorization, "resolve", forbidden)
        client.calls.clear()
        assert managed.run_managed(requested, transport=client) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["job_id"] == job["id"]
        assert result["effective_settings"]["model"] == "server-model"
        assert result["version_ref"]["version"] == 1
        assert not any(
            path in ("/api/editor", "/api/model-settings", "/api/editor/generate") for _, path in client.calls
        )
        lookup = f'/api/editor/generate/operations/stable-op?request_sha256={job["inputs"]["request_sha256"]}'
        with monkeypatch.context() as guard:
            guard.setattr(generation, "configuration", forbidden)
            guard.setattr(graph_access, "configuration", forbidden)
            assert peer.get(lookup).json()["job"]["inputs"] == job["inputs"]
            assert peer.get(lookup.replace(job["inputs"]["request_sha256"], "0" * 64)).status_code == 409
            assert peer.get(lookup + "&request_sha256=" + "0" * 64).status_code == 422
            assert peer.get(lookup.replace("stable-op", "missing")).json() == {"job": None}
            peer.cookies.clear()
            assert peer.get(lookup).status_code == 401
        for extra in (["--prompt", "different request"], ["--managed_operation_id", "missing"]):
            client.calls.clear()
            assert managed.run_managed(args(["--model", "server-model", *extra]), transport=client) == 2
            capsys.readouterr()
            assert not any(method == "POST" and path != "/api/sessions" for method, path in client.calls)
        assert len(peer.get("/api/jobs").json()["jobs"]) == 1


def test_managed_dispatch_rejects_full_before_legacy(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["runner", *FLAGS])
    monkeypatch.setattr(runner, "SimulationAppContext", forbidden)
    monkeypatch.setattr(runner, "resolve_env_spec", forbidden)
    assert runner.main() == 2
    assert "resolve" in capsys.readouterr().out
