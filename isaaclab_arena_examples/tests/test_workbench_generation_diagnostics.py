# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Safe generation failures survive the real managed dispatcher and temporary journal."""

import asyncio
import io
import json
import os
import socket
import sys
from types import SimpleNamespace

import pytest

from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena_examples.tests.test_workbench_managed_execution import harness


def diagnostic(code="provider_authentication", stage="agent_initializing"):
    return {"schema_version": 1, "code": code, "stage": stage}


def stream(monkeypatch, frames, *, exit_code=1):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import editor_execution

    spawn = editor_execution.asyncio.create_subprocess_exec

    async def replacement(*args, **kwargs):
        process = await spawn(*args, **kwargs)
        lines = iter([(json.dumps(frame) + "\n").encode() for frame in frames])

        async def readline():
            return next(lines, b"")

        async def wait():
            return exit_code

        process.stdout.readline = readline
        process.wait = wait
        return process

    monkeypatch.setattr(editor_execution.asyncio, "create_subprocess_exec", replacement)


@pytest.mark.parametrize(
    "code",
    [
        "provider_authentication",
        "provider_request_rejected",
        "provider_schema_rejected",
        "provider_parameter_unsupported",
        "provider_schema_min_items_unsupported",
        "provider_schema_max_items_unsupported",
        "provider_schema_prefix_items_unsupported",
    ],
)
def test_safe_worker_error_is_durable_without_changing_unknown_outcome(tmp_path, monkeypatch, code):
    journal, job, runner, supervisor, writes, _, _ = harness(tmp_path, monkeypatch, result=False)
    expected = diagnostic(code)
    stream(monkeypatch, [{"stage": "agent_initializing"}, {"error": expected}])
    asyncio.run(runner.execute_managed(supervisor, job))
    current = journal.get_job(job["id"])
    assert current.get("diagnostic") == expected
    assert current["status"] == "indeterminate"
    assert current["execution"] == {"released": True, "candidate_accepted": False, "outcome": "unknown"}
    assert current["result"] is None
    assert journal.claim_attempt(job["id"]) is None
    assert len(writes) == 1
    assert not journal.pending_workers()
    events = [json.loads(row[0]) for row in journal.db.execute("SELECT body FROM events ORDER BY id")]
    assert expected in [event["job"].get("diagnostic") for event in events]
    journal.close()
    reopened = Journal(tmp_path / "journal.sqlite3")
    assert reopened.get_job(job["id"])["diagnostic"] == expected
    reopened.close()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Diagnostics tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", denied)


def test_http_secret_guard_rejection_cannot_skip_worker_cleanup(tmp_path, monkeypatch):
    from fastapi import HTTPException

    journal, job, runner, supervisor, _, _, _ = harness(tmp_path, monkeypatch, result=False)
    stream(monkeypatch, [{"stage": "agent_initializing"}, {"error": diagnostic()}])

    def reject_wrapper(value):
        if isinstance(value, dict) and "diagnostic" in value:
            raise HTTPException(422, "Invalid request input")

    runner.protect_workflow = reject_wrapper
    asyncio.run(runner.execute_managed(supervisor, job))
    current = journal.get_job(job["id"])
    assert current["status"] == "indeterminate"
    assert "diagnostic" not in current
    assert not journal.pending_workers()
    assert supervisor.process is None and supervisor.job_id is None
    journal.close()


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_diagnostic_attempt_read_failure_cannot_skip_worker_cleanup(tmp_path, monkeypatch, cleanup_fails):
    journal, job, runner, supervisor, _, order, _ = harness(tmp_path, monkeypatch, result=False)
    stream(monkeypatch, [{"stage": "agent_initializing"}, {"error": diagnostic()}])
    get_attempt = journal.get_attempt
    failed_reads = []

    def fail_once(job_id):
        monkeypatch.setattr(journal, "get_attempt", get_attempt)
        failed_reads.append(job_id)
        raise RuntimeError("synthetic diagnostic read failure")

    def arm_cleanup_read_failure(value):
        if isinstance(value, dict) and "error" in value:
            # Authorization/release reads have finished; fail the diagnostic lookup.
            monkeypatch.setattr(journal, "get_attempt", fail_once)

    async def stop():
        order.append("reaped")
        if cleanup_fails:
            raise RuntimeError("synthetic cleanup failure")

    runner.protect_workflow = arm_cleanup_read_failure
    supervisor.stop_process = stop
    try:
        try:
            if cleanup_fails:
                with pytest.raises(RuntimeError, match="synthetic cleanup failure"):
                    asyncio.run(runner.execute_managed(supervisor, job))
            else:
                asyncio.run(runner.execute_managed(supervisor, job))
        finally:
            assert failed_reads == [job["id"]]
            assert order == ["reaped"]
        current = journal.get_job(job["id"])
        assert "diagnostic" not in current
        assert current["result"] is None
        assert current["execution"] == {"released": True, "candidate_accepted": False, "outcome": "unknown"}
        if cleanup_fails:
            assert current["status"] == "running"
            assert journal.get_attempt(job["id"])["state"] == "released"
            assert journal.pending_workers()
            assert supervisor.process is not None and supervisor.job_id == job["id"]
        else:
            assert current["status"] == "indeterminate"
            assert not journal.pending_workers()
            assert supervisor.process is None and supervisor.job_id is None
        assert journal.claim_attempt(job["id"]) is None
    finally:
        journal.close()


@pytest.mark.parametrize(
    "name,status", [("BadRequestError", 400), ("UnprocessableEntityError", 422), ("APIStatusError", 400)]
)
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize(
    "provider_code,expected",
    [
        ("invalid_json_schema", "provider_schema_rejected"),
        ("unsupported_parameter", "provider_parameter_unsupported"),
        ("unsupported_value", "provider_parameter_unsupported"),
        ("model_not_found", "provider_model_unavailable"),
    ],
)
def test_sdk_rejection_detail_is_a_closed_v1_code(name, status, nested, provider_code, expected):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.generation_diagnostics import classify_failure

    failure = sdk_failure(name, status)
    body = {"code": provider_code, "message": "synthetic-private-marker", "synthetic-private-marker": "private"}
    failure.body = {"error": body} if nested else body
    wrapped = RuntimeError("synthetic-private-marker")
    wrapped.__cause__ = failure
    assert classify_failure(wrapped, "spec_inference") == diagnostic(expected, "spec_inference")


@pytest.mark.parametrize(
    "keyword,code",
    [
        ("minItems", "provider_schema_min_items_unsupported"),
        ("maxItems", "provider_schema_max_items_unsupported"),
        ("prefixItems", "provider_schema_prefix_items_unsupported"),
    ],
)
@pytest.mark.parametrize("provider_code", ["invalid_json_schema", None])
@pytest.mark.parametrize("nested", [False, True])
def test_known_schema_keyword_signatures_are_static(keyword, code, provider_code, nested):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.generation_diagnostics import classify_failure

    failure = sdk_failure("BadRequestError", 400)
    body = {
        "code": provider_code,
        "message": (
            "Invalid schema for response_format 'synthetic-private-marker': In context=('properties', "
            f"'synthetic-private-marker'), '{keyword}' is not permitted."
        ),
    }
    failure.body = {"error": body} if nested else body
    assert classify_failure(failure, "spec_inference") == diagnostic(code, "spec_inference")


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Invalid schema for response_format 'synthetic-private-marker': unknown defect", "provider_schema_rejected"),
        (
            "Unsupported parameter: 'synthetic-private-marker' is not supported with this model.",
            "provider_parameter_unsupported",
        ),
        (
            "Unsupported value: 'synthetic-private-marker' does not support this value.",
            "provider_parameter_unsupported",
        ),
    ],
)
def test_known_missing_code_message_prefixes_map_to_categories(message, expected):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.generation_diagnostics import classify_failure

    failure = sdk_failure("UnprocessableEntityError", 422)
    failure.body = {"code": None, "message": message}
    assert classify_failure(failure, "spec_inference") == diagnostic(expected, "spec_inference")


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "synthetic-private-marker",
        {"error": "synthetic-private-marker", "code": "invalid_json_schema"},
        {"code": ["invalid_json_schema"], "message": ["'minItems' is not permitted"]},
        {"code": "synthetic-private-marker", "message": "synthetic-private-marker"},
        {"code": "invalid_json_schema-synthetic-private-marker", "message": "private"},
        {"code": None, "message": "synthetic-private-marker mentions minItems"},
        {"code": None, "message": "'minItems' is not permitted."},
        {"code": None, "message": "Unsupported parameter: " + "x" * 8192},
    ],
)
def test_unmapped_or_malformed_body_is_generic_without_reflection(body):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.generation_diagnostics import classify_failure

    failure = sdk_failure("BadRequestError", 400)
    failure.body = body
    assert classify_failure(failure, "spec_inference") == diagnostic("provider_request_rejected", "spec_inference")


@pytest.mark.parametrize(
    "message",
    [
        "'unknownKeyword' is not permitted.",
        "minItems is allowed, but something else failed.",
        "'minItems' is not permitted. 'maxItems' is not permitted.",
    ],
)
def test_uncertain_keyword_remains_schema_only(message):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.generation_diagnostics import classify_failure

    failure = sdk_failure("BadRequestError", 400)
    failure.body = {"code": "invalid_json_schema", "message": message}
    assert classify_failure(failure, "spec_inference") == diagnostic("provider_schema_rejected", "spec_inference")


def test_provider_fields_are_not_coerced_or_stringified():
    from isaaclab_arena_examples.agentic_environment_generation.web_api.generation_diagnostics import classify_failure

    class PrivateString(str):
        def __hash__(self):
            pytest.fail("Provider field subclass was hashed")

        def startswith(self, *args):
            pytest.fail("Provider field subclass was matched")

    failure = sdk_failure("BadRequestError", 400)
    failure.body = {"code": PrivateString("invalid_json_schema"), "message": PrivateString("Unsupported parameter:")}
    assert classify_failure(failure, "spec_inference") == diagnostic("provider_request_rejected", "spec_inference")


@pytest.mark.parametrize(
    "name,status,expected",
    [
        ("AuthenticationError", 401, "provider_authentication"),
        ("PermissionDeniedError", 403, "provider_permission"),
        ("RateLimitError", 429, "provider_rate_limit"),
        ("APIStatusError", 408, "provider_timeout"),
        ("APIStatusError", 413, "provider_request_rejected"),
        ("APIStatusError", 503, "internal_error"),
    ],
)
def test_rejection_details_never_override_other_statuses(name, status, expected):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.generation_diagnostics import classify_failure

    failure = sdk_failure(name, status)
    failure.body = {"code": "invalid_json_schema", "message": "'minItems' is not permitted."}
    assert classify_failure(failure, "spec_inference") == diagnostic(expected, "spec_inference")


def sdk_failure(name, status=None):
    import httpx
    import openai

    request = httpx.Request("POST", "https://provider.invalid/private-path", headers={"Authorization": "secret-header"})
    if status is not None:
        return getattr(openai, name)(
            "private-key secret-error secret-prompt",
            response=httpx.Response(status, request=request),
            body={"secret-body": "secret-response"},
        )
    return getattr(openai, name)(request=request)


@pytest.mark.parametrize(
    "name,status,code",
    [
        ("AuthenticationError", 401, "provider_authentication"),
        ("PermissionDeniedError", 403, "provider_permission"),
        ("RateLimitError", 429, "provider_rate_limit"),
        ("NotFoundError", 404, "provider_model_unavailable"),
        ("BadRequestError", 400, "provider_request_rejected"),
        ("UnprocessableEntityError", 422, "provider_request_rejected"),
        ("APIStatusError", 401, "provider_authentication"),
        ("APIStatusError", 408, "provider_timeout"),
        ("APIStatusError", 413, "provider_request_rejected"),
        ("ConflictError", 409, "provider_request_rejected"),
        ("APIStatusError", 503, "internal_error"),
        ("APITimeoutError", None, "provider_timeout"),
        ("APIConnectionError", None, "provider_connection"),
    ],
)
def test_worker_emits_only_typed_static_error(tmp_path, monkeypatch, capsys, name, status, code):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation, generation_worker

    envelope = {
        "inputs": {"operation": "new", "execution_catalogue_sha256": "a" * 64},
        "config": {"api_key": "private-key"},
        "graph_config": None,
    }
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO((json.dumps(envelope) + "\n").encode())))
    monkeypatch.setattr(sys, "argv", ["worker", "--parent-pid", str(os.getppid())])
    monkeypatch.setattr(generation_worker.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(prctl=lambda *a: 0))
    failure = sdk_failure(name, status)

    def generate(inputs, emit, **kwargs):
        emit("agent_initializing")
        raise RuntimeError("wrapper-private-key") from failure

    monkeypatch.setattr(generation, "generate", generate)
    assert generation_worker.main() == 1
    output = capsys.readouterr()
    assert output.err == ""
    assert [json.loads(line) for line in output.out.splitlines()] == [
        {"stage": "agent_initializing"},
        {"error": diagnostic(code)},
    ]
    journal, job, runner, supervisor, _, _, _ = harness(tmp_path, monkeypatch, result=False)
    stream(monkeypatch, [json.loads(line) for line in output.out.splitlines()])
    asyncio.run(runner.execute_managed(supervisor, job))
    assert journal.get_job(job["id"])["diagnostic"] == diagnostic(code)
    assert journal.get_job(job["id"])["status"] == "indeterminate"
    assert "secret-" not in "\n".join(journal.db.iterdump())
    assert "private-key" not in "\n".join(journal.db.iterdump())
    journal.close()


@pytest.mark.parametrize(
    "body,code",
    [
        ({"code": "invalid_json_schema", "message": "synthetic-private-marker"}, "provider_schema_rejected"),
        ({"code": "unsupported_parameter", "message": "synthetic-private-marker"}, "provider_parameter_unsupported"),
        (
            {"code": "invalid_json_schema", "message": "synthetic-private-marker: 'minItems' is not permitted."},
            "provider_schema_min_items_unsupported",
        ),
        (
            {"code": "invalid_json_schema", "message": "synthetic-private-marker: 'maxItems' is not permitted."},
            "provider_schema_max_items_unsupported",
        ),
        (
            {"code": "invalid_json_schema", "message": "synthetic-private-marker: 'prefixItems' is not permitted."},
            "provider_schema_prefix_items_unsupported",
        ),
        ({"code": "synthetic-private-marker", "message": "synthetic-private-marker"}, "provider_request_rejected"),
    ],
)
def test_rejection_body_never_reaches_worker_output_or_journal(tmp_path, monkeypatch, capsys, body, code):
    failure = sdk_failure("BadRequestError", 400)
    failure.body = {"error": {**body, "synthetic-private-marker": "private"}}
    monkeypatch.setattr(sys.modules[__name__], "sdk_failure", lambda *args: failure)
    test_worker_emits_only_typed_static_error(tmp_path, monkeypatch, capsys, "BadRequestError", 400, code)
    reopened = Journal(tmp_path / "journal.sqlite3")
    assert "synthetic-private-marker" not in "\n".join(reopened.db.iterdump())
    reopened.close()


@pytest.mark.parametrize(
    "frames,code",
    [
        ([], "worker_exited"),
        ([{"error": "private-key raw provider response"}], "worker_protocol"),
        ([{"error": {**diagnostic(), "message": "secret-response"}}], "worker_protocol"),
        ([{"error": diagnostic(stage="private-path")}], "worker_protocol"),
        ([{"error": diagnostic(code="secret-response")}], "worker_protocol"),
        ([{"stage": "private-key"}], "worker_protocol"),
        ([None], "worker_protocol"),
        ([{"result": {"yaml_text": "private-key"}}], "worker_protocol"),
    ],
)
def test_parent_synthesizes_safe_unknown_exit_and_protocol_diagnostics(tmp_path, monkeypatch, frames, code):
    journal, job, runner, supervisor, _, _, _ = harness(tmp_path, monkeypatch, result=False)
    stream(monkeypatch, [{"stage": "agent_initializing"}, *frames])
    asyncio.run(runner.execute_managed(supervisor, job))
    current = journal.get_job(job["id"])
    assert current.get("diagnostic") == diagnostic(code)
    assert current["status"] == "indeterminate"
    assert current["result"] is None
    assert "private-key" not in "\n".join(journal.db.iterdump())
    assert "secret-response" not in "\n".join(journal.db.iterdump())
    journal.close()


def test_parent_watchdog_is_not_provider_timeout(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import editor_execution

    journal, job, runner, supervisor, _, _, _ = harness(tmp_path, monkeypatch, result=False)
    spawn = editor_execution.asyncio.create_subprocess_exec

    async def hanging(*args, **kwargs):
        process = await spawn(*args, **kwargs)

        async def readline():
            await asyncio.sleep(10)

        process.stdout.readline = readline
        return process

    monkeypatch.setattr(editor_execution.asyncio, "create_subprocess_exec", hanging)
    monkeypatch.setattr(editor_execution, "GENERATION_TIMEOUT", 0.01)
    asyncio.run(runner.execute_managed(supervisor, job))
    assert journal.get_job(job["id"]).get("diagnostic") == diagnostic("worker_timeout", "worker_starting")
    assert journal.get_job(job["id"])["status"] == "indeterminate"
    assert not journal.pending_workers()
    journal.close()


def test_diagnostics_never_override_accepted_candidate(tmp_path, monkeypatch):
    journal, job, runner, supervisor, _, _, receipt = harness(tmp_path, monkeypatch)
    stream(monkeypatch, [{"result": receipt}, {"error": diagnostic()}])
    asyncio.run(runner.execute_managed(supervisor, job))
    current = journal.get_job(job["id"])
    assert current["status"] == "succeeded"
    assert current["result"] == receipt
    assert "diagnostic" not in current
    journal.close()


@pytest.mark.parametrize(
    "case,code",
    [
        ("missing_dependency", "dependency_unavailable"),
        ("invalid_spec", "invalid_specification"),
        ("required_retrieval", "required_retrieval_unavailable"),
    ],
)
def test_trusted_generation_conditions_have_safe_typed_codes(monkeypatch, case, code):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation
    from isaaclab_arena_examples.agentic_environment_generation.web_api.catalogues import execution_catalogue_sha256
    from isaaclab_arena_examples.agentic_environment_generation.web_api.generation_diagnostics import classify_failure

    class Agent:
        def __init__(self, **kwargs):
            if case == "missing_dependency":
                raise ModuleNotFoundError("secret-path private-key")

        def generate_spec(self, *args, **kwargs):
            return None, None

    inputs = {"prompt": "synthetic prompt"}
    if case == "required_retrieval":
        inputs.update(
            operation="new", retrieval_policy="require_service", execution_catalogue_sha256=execution_catalogue_sha256()
        )
    stages = []
    with pytest.raises(Exception) as caught:
        generation.generate(
            inputs,
            stages.append,
            agent_factory=Agent,
            config={
                "api_key": "synthetic-credential",
                "model": "test",
                "base_url": "https://api.openai.com/v1",
            },
        )
    assert classify_failure(caught.value, stages[-1])["code"] == code


def test_classifier_never_stringifies_and_bounds_cyclic_causes():
    from isaaclab_arena_examples.agentic_environment_generation.web_api.generation_diagnostics import classify_failure

    class PrivateError(Exception):
        status_code = 401  # Not an SDK exception: no duck-typed provider classification.

        def __str__(self):
            pytest.fail("Private exception was stringified")

    error = PrivateError()
    error.__cause__ = error
    assert classify_failure(error, "worker_starting") == diagnostic("internal_error", "worker_starting")
    error.__cause__ = sdk_failure("AuthenticationError", 401)
    for _ in range(9):
        wrapper = PrivateError()
        wrapper.__cause__ = error
        error = wrapper
    assert classify_failure(error, "worker_starting") == diagnostic("internal_error", "worker_starting")


def test_missing_sdk_still_classifies_dependency_without_importing_it(monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.generation_diagnostics import classify_failure

    monkeypatch.setitem(sys.modules, "openai", None)
    assert classify_failure(ModuleNotFoundError("private-path"), "worker_starting") == diagnostic(
        "dependency_unavailable", "worker_starting"
    )


def test_diagnostic_persists_even_if_worker_cleanup_is_not_acknowledged(tmp_path, monkeypatch):
    journal, job, runner, supervisor, _, _, _ = harness(tmp_path, monkeypatch, result=False)
    stream(monkeypatch, [{"stage": "agent_initializing"}, {"error": diagnostic()}])

    async def incomplete():
        raise RuntimeError("synthetic cleanup failure")

    supervisor.stop_process = incomplete
    with pytest.raises(RuntimeError):
        asyncio.run(runner.execute_managed(supervisor, job))
    assert journal.get_job(job["id"]).get("diagnostic") == diagnostic()
    assert journal.get_job(job["id"])["status"] == "running"
    assert journal.pending_workers()
    journal.close()


def test_journal_diagnostic_fences_and_rejects_extra_metadata(tmp_path):
    journal = Journal(tmp_path / "journal.sqlite3")
    job = journal.submit("s", "w", "generate", "one", {"operation": "new"})
    other = journal.submit("s", "w", "generate", "two", {"operation": "new"})
    attempt = journal.claim_attempt(job["id"])
    journal.claim_attempt(other["id"])
    assert journal.release_attempt(job["id"], **attempt)
    record = journal.record_attempt_diagnostic
    kwargs = dict(expected_state="released", diagnostic=diagnostic(), protect_public=lambda value: None)
    baseline = journal.snapshot()
    assert not record(other["id"], **attempt, **kwargs)
    assert not record(job["id"], attempt_id=attempt["attempt_id"], generation=attempt["generation"] + 1, **kwargs)
    for invalid in (
        {**diagnostic(), "message": "private-key"},
        {**diagnostic(), "schema_version": True},
        diagnostic(code="private-key"),
        diagnostic(stage="private-path"),
    ):
        with pytest.raises(ValueError):
            record(job["id"], **attempt, **{**kwargs, "diagnostic": invalid})
    assert journal.snapshot() == baseline
    assert journal.commit_candidate(job["id"], **attempt, receipt={"safe": True})
    baseline = journal.snapshot()
    assert not record(job["id"], **attempt, **kwargs)
    assert journal.snapshot() == baseline
    journal.close()


@pytest.mark.parametrize(
    "marker", ["provider_authentication", "worker_exited", "schema_version", "diagnostic", "generation_diagnostic"]
)
def test_static_diagnostics_still_obey_protected_markers(tmp_path, monkeypatch, marker):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import reject_secret

    journal, job, runner, supervisor, _, _, _ = harness(tmp_path, monkeypatch, result=False)
    stream(monkeypatch, [] if marker == "worker_exited" else [{"stage": "agent_initializing"}, {"error": diagnostic()}])
    runner.protect_workflow = lambda value: reject_secret(value, marker)
    asyncio.run(runner.execute_managed(supervisor, job))
    public = [journal.get_job(job["id"])]
    public.extend(json.loads(row[0])["job"] for row in journal.db.execute("SELECT body FROM events"))
    assert marker not in [json.loads(row[0])["kind"] for row in journal.db.execute("SELECT body FROM events")]
    assert marker not in json.dumps(public)
    assert journal.get_job(job["id"])["status"] == "indeterminate"
    journal.close()
