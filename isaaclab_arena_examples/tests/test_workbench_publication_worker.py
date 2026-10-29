# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Private worker protocol exercised in network-denied real subprocesses."""

import importlib
import json
import os
import select
import subprocess
import sys
from pathlib import Path

import pytest

from isaaclab_arena_examples.tests import test_workbench_publication_execution as execution_tests

executor = execution_tests.executor
ready = execution_tests.ready

WORKER = str(Path(__file__).parents[1] / "agentic_environment_generation/web_api/publication_worker.py")
READY = {"schema_version": 1, "ready": "publication"}
ERROR = {"schema_version": 1, "error": "publication_unknown"}


def test_protocol_write_handles_positive_short_writes(monkeypatch):
    import runpy

    worker = runpy.run_path(WORKER)
    received = bytearray()

    def short_write(fd, data):
        assert fd == 99
        count = min(3, len(data))
        received.extend(data[:count])
        return count

    monkeypatch.setattr(os, "write", short_write)
    worker["_write_all"](99, b'{"ready":"publication"}\n')
    assert bytes(received) == b'{"ready":"publication"}\n'


def spawn(code=None, parent_pid=None):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import worker_environment

    args = [sys.executable, "-c", code] if code else [sys.executable, WORKER]
    return subprocess.Popen(
        args + ["--parent-pid", str(parent_pid or os.getpid())],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=worker_environment(None),
        start_new_session=True,
    )


def read_ready(child):
    assert select.select([child.stdout], [], [], 10)[0], "readiness timeout"
    assert json.loads(child.stdout.readline()) == READY


def test_production_ready_before_private_input_without_graph(monkeypatch):
    monkeypatch.setenv("NEO4J_PASSWORD", "ambient-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-model-secret")
    child = spawn()
    try:
        read_ready(child)
        environ = Path(f"/proc/{child.pid}/environ").read_bytes()
        assert b"ambient-secret" not in environ and b"ambient-model-secret" not in environ
        assert child.poll() is None
        output, errors = child.communicate(b"{}\n", timeout=10)
        assert json.loads(output) == ERROR
        assert errors == b""
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()


def test_shared_preparation_and_private_expected_receipt(ready):
    module = importlib.import_module(
        "isaaclab_arena_examples.agentic_environment_generation.web_api.publication_payload"
    )
    intent, spec, projection = module.prepare_publication(ready.store, ready.auth, "effect")
    assert (intent, projection) == (executor(ready)._prepare("effect")[0], executor(ready)._prepare("effect")[2])
    private, expected = module.build_private_envelope(
        intent, spec, projection, ready.profiles["graph"]["connection"], "graph_write"
    )
    assert b"fake-private-publication-password" in private
    assert "fake-private-publication-password" not in str(expected)
    assert expected["transport"]["scope_id"] == projection["scope_id"]
    assert not ready.drivers
    assert ready.auth._records == {}


# This entrypoint injects a fake physical SDK driver in CODE, never through JSON.
FAKE_CODE = """
import socket, sys, os, json

def denied(*args, **kwargs):
    raise AssertionError('network forbidden')
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
import runpy
main = runpy.run_path("isaaclab_arena_examples/agentic_environment_generation/web_api/publication_worker.py")["main"]

def factory(**kwargs):
    from isaaclab_arena.tests.test_workbench_research_graph_transport import ready_driver
    assert kwargs['max_transaction_retry_time'] == 0
    assert kwargs['connection_timeout'] == 3
    driver = ready_driver()
    def close():
        assert len(driver.sessions) == 1
        assert all(s.closed for s in driver.sessions)
        print(kwargs['password'])
        os.write(2, kwargs['password'].encode())
        if CLOSE_FAIL:
            raise RuntimeError(kwargs['password'])
        assert driver.commits == EXPECT_COMMITS
    driver.close = close
    return driver
raise SystemExit(main(driver_factory=factory))
"""


def private_input(ready, capability="graph_write"):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_payload import (
        build_private_envelope,
    )

    return build_private_envelope(
        *executor(ready)._prepare("effect"), ready.profiles["graph"]["connection"], capability
    )


@pytest.mark.parametrize("capability", ["graph_write", "graph_read"])
@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_one_physical_call_closed_before_secret_free_result(ready, capability, cleanup_failure):
    private, expected = private_input(ready, capability)
    code = FAKE_CODE.replace("CLOSE_FAIL", repr(cleanup_failure)).replace(
        "EXPECT_COMMITS", str(int(capability == "graph_write"))
    )
    child = spawn(code)
    read_ready(child)
    output, errors = child.communicate(private, timeout=15)
    assert errors == b""
    assert b"fake-private-publication-password" not in output
    result = json.loads(output)
    assert result == (
        {"schema_version": 1, "receipt": expected} if capability == "graph_write" and not cleanup_failure else ERROR
    )
    assert child.returncode == (0 if "receipt" in result else 1)


@pytest.mark.parametrize(
    "attack",
    [
        "duplicate",
        "trailing",
        "oversized",
        "depth",
        "missing-newline",
        "nan",
        "scope",
        "capability",
        "attestation",
        "profile",
        "projection",
        "source",
    ],
)
def test_invalid_input_never_constructs_driver(ready, attack):
    private, _ = private_input(ready)
    obj = json.loads(private)
    if attack == "duplicate":
        private = private.replace(b"{", b'{"schema_version":1,', 1)
    elif attack == "trailing":
        private += b"{}\n"
    elif attack == "oversized":
        private = b" " * (2 * 1024 * 1024) + private
    elif attack == "depth":
        private = b"[" * 40 + b"0" + b"]" * 40 + b"\n"
    elif attack == "missing-newline":
        private = private.rstrip()
    elif attack == "nan":
        private = b'{"a":NaN}\n'
    else:
        if attack == "attestation":
            obj["immutable_scope_attested"] = 1
        elif attack == "profile":
            obj["config"]["database"] = "wrong"
        elif attack == "projection":
            obj["projection"]["scope_id"] = "wrong"
        elif attack == "source":
            obj["source"] = {}
        else:
            obj[attack] = "wrong"
        private = json.dumps(obj).encode() + b"\n"
    code = FAKE_CODE.replace(
        "    from isaaclab_arena.tests.test_workbench_research_graph_transport import ready_driver",
        "    os.write(3, b'FORBIDDEN')\n    from isaaclab_arena.tests.test_workbench_research_graph_transport import"
        " ready_driver",
    )
    child = spawn(code)
    read_ready(child)
    output, errors = child.communicate(private, timeout=15)
    assert json.loads(output) == ERROR
    assert errors == b""


def test_parent_result_screening_is_independent_and_bounded(ready):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_payload import screen_worker_result

    _, expected = private_input(ready)
    raw = json.dumps({"schema_version": 1, "receipt": expected}).encode() + b"\n"
    assert screen_worker_result(raw, expected, ("captured-old-password",)) == expected
    with pytest.raises(ValueError):
        screen_worker_result(raw, expected, (expected["effect_id"],))
    with pytest.raises(ValueError):
        screen_worker_result(raw + raw, expected, ())
    changed = json.loads(raw)
    changed["receipt"]["transport"]["database"] = "wrong"
    with pytest.raises(ValueError):
        screen_worker_result(json.dumps(changed).encode() + b"\n", expected, ())


def test_verified_read_uses_no_write(ready):
    from isaaclab_arena.agentic_environment_generation.workbench import research_graph_transport
    from isaaclab_arena.tests.test_workbench_research_graph_transport import ready_driver

    intent, spec, projection = executor(ready)._prepare("effect")
    driver = ready_driver()
    research_graph_transport.publish_once(
        driver, "research", projection, spec=spec, effect_id="effect", immutable_scope_attested=True
    )
    code = FAKE_CODE.replace("CLOSE_FAIL", "False").replace("EXPECT_COMMITS", "0")
    code = code.replace(
        "    def close():",
        f"    driver.nodes = {driver.nodes!r}\n    driver.edges = {driver.edges!r}\n    def close():",
    )
    private, expected = private_input(ready, "graph_read")
    child = spawn(code)
    read_ready(child)
    output, errors = child.communicate(private, timeout=15)
    assert errors == b""
    assert json.loads(output) == {"schema_version": 1, "receipt": expected}
    assert child.returncode == 0


def test_default_worker_never_loads_model_or_opens_journal(ready):
    code = """
import sys, socket
class Forbidden:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'openai' or fullname.endswith('.journal') or fullname.endswith('.generation'):
            raise AssertionError('forbidden import')
sys.meta_path.insert(0, Forbidden())
def audit(event, args):
    if event in {'sqlite3.connect', 'socket.connect'}:
        raise AssertionError('forbidden IO')
sys.addaudithook(audit)
import runpy
main = runpy.run_path("isaaclab_arena_examples/agentic_environment_generation/web_api/publication_worker.py")["main"]
raise SystemExit(main())
"""
    child = spawn(code)
    read_ready(child)
    output, errors = child.communicate(b"{}\n", timeout=15)
    assert json.loads(output) == ERROR
    assert errors == b""


def test_parent_pid_mismatch_emits_nothing():
    child = spawn(parent_pid=os.getpid() + 100000)
    output, errors = child.communicate(b"{}\n", timeout=10)
    assert output == errors == b""
    assert child.returncode == 1


def test_parent_death_kills_worker_blocked_on_private_pipe():
    import time
    from pathlib import Path

    read_fd, write_fd = os.pipe()
    code = f"""
import os, subprocess, sys, time
child = subprocess.Popen([sys.executable, {WORKER!r}, '--parent-pid', str(os.getpid())], stdin={read_fd}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
assert child.stdout.readline()
print(child.pid, flush=True)
time.sleep(30)
"""
    parent = subprocess.Popen([sys.executable, "-c", code], pass_fds=(read_fd,), stdout=subprocess.PIPE)
    os.close(read_fd)
    try:
        assert select.select([parent.stdout], [], [], 10)[0]
        pid = int(parent.stdout.readline())
        parent.kill()
        parent.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            path = Path(f"/proc/{pid}/stat")
            if not path.exists() or path.read_text().split(") ", 1)[1].split()[0] == "Z":
                break
            time.sleep(0.02)
        else:
            pytest.fail("worker survived parent death")
    finally:
        os.close(write_fd)
        if parent.poll() is None:
            parent.kill()
        parent.wait()


def test_default_sdk_factory_without_models_or_journal(ready):
    private, expected = private_input(ready)
    code = FAKE_CODE.replace("CLOSE_FAIL", "False").replace("EXPECT_COMMITS", "1")
    code = code.replace(
        "raise SystemExit(main(driver_factory=factory))",
        """
from types import SimpleNamespace
def sdk(uri, *, auth, **kwargs):
    return factory(uri=uri, user=auth[0], password=auth[1], **kwargs)
from neo4j import Query
sys.modules['neo4j'] = SimpleNamespace(Query=Query, GraphDatabase=SimpleNamespace(driver=sdk))
def audit(event, args):
    if event == 'sqlite3.connect':
        raise AssertionError('journal forbidden')
sys.addaudithook(audit)
class Forbidden:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'openai' or fullname.endswith('.journal'):
            raise AssertionError('model/simulation/journal forbidden')
sys.meta_path.insert(0, Forbidden())
raise SystemExit(main())
""",
    )
    child = spawn(code)
    read_ready(child)
    output, errors = child.communicate(private, timeout=15)
    assert errors == b""
    assert json.loads(output) == {"schema_version": 1, "receipt": expected}
