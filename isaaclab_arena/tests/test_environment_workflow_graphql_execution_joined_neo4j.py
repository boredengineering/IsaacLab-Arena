# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""One installed HTTP admission/owner/SDK/readback witness; never a fake owner."""

import json
import os
import time
from pathlib import Path


def _detachment_proof_negatives():
    """Pure checker regressions; no clocks, children, SDK or transport effects."""
    from copy import deepcopy

    from workflow_graphql_execution_join_fixture import check_detachment_proof

    identity = dict(pid=41, parent_pid=40, pgid=41, sid=41, boot="boot", pid_namespace="pid:[1]", start_ticks=7)
    server = dict(identity, pid=40, parent_pid=38, pgid=40, sid=40, start_ticks=6)
    detached = dict(
        submit_pid=39,
        server_identity=server,
        worker_identity=identity,
        server_live=dict(server, parent_pid=1, state="S"),
        worker_live=dict(identity, state="S"),
        submit_reaped_before_release=True,
        observed_at=12.0,
        release_requested_at=13.0,
    )
    release = dict(
        identity=identity, calls=2, phase="released", outcome="marker_removed",
        waiting_at=10.0, deadline=30.0, released_at=14.0,
        response_ready=True, response_returning=True,
    )
    check_detachment_proof(detached, release)
    mutations = (
        ("timeout_after_descheduling", "release", {"outcome": "timeout", "released_at": 31.0}, "explicit removal"),
        ("late_removal", "release", {"released_at": 31.0}, "release ordering"),
        ("missing_response", "release", {"response_returning": False}, "transport response"),
        ("submit_not_reaped", "detached", {"submit_reaped_before_release": False}, "submit reap"),
        ("zombie_worker", "worker_live", {"state": "Z"}, "live identity"),
        ("dead_server", "server_live", {"state": "X"}, "live identity"),
        ("reused_worker_pid", "worker_live", {"start_ticks": 8}, "live identity"),
        ("reused_server_pid", "server_live", {"start_ticks": 8}, "live identity"),
        ("foreign_namespace", "worker_live", {"pid_namespace": "pid:[2]"}, "live identity"),
        ("foreign_release", "release_identity", {"start_ticks": 8}, "release identity"),
    )
    checked = []
    for name, target, update, message in mutations:
        observed, returned = deepcopy(detached), deepcopy(release)
        destination = {
            "release": returned, "detached": observed,
            "worker_live": observed["worker_live"], "server_live": observed["server_live"],
            "release_identity": returned["identity"],
        }[target]
        destination.update(update)
        try:
            check_detachment_proof(observed, returned)
        except AssertionError as error:
            assert message in str(error), (name, str(error))
            checked.append(name)
        else:
            raise AssertionError(f"detachment checker accepted {name}")
    return checked


def test_installed_execution_survives_submit_exit():
    """Reach production composition first, then require the whole retained join."""
    import workflow_graphql_execution_join_harness as h
    from workflow_graphql_execution_join_fixture import (
        IDENTITY_FIELDS,
        PAUSE,
        PAUSE_BYTES,
        configuration,
        contract,
        registrations,
    )

    records = []
    proof_negative_checks = []
    launched = False
    pause = PAUSE

    def invoke(arguments, *, private_fd=None):
        result = h.fresh(arguments, private_fd=private_fd)
        h.screen(result.stdout + result.stderr)
        records.append({
            "argv": arguments,
            "pid": result.pid,
            "returncode": result.returncode,
            "stdout": result.stdout.decode(),
            "stderr": result.stderr.decode(),
        })
        return result

    try:
        proof_negative_checks = _detachment_proof_negatives()
        profiles = registrations()
        for kind, config_path in zip(("query", "execution"), h.CONFIGS, strict=True):
            configuration(kind, profiles if kind == "execution" else ())
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
                result = invoke(
                    ["setup", "--config", config_path, "--create", "--credentials-fd", str(read_fd)],
                    private_fd=read_fd,
                )
            finally:
                os.close(read_fd)
            assert result.returncode == 0, "E1 prerequisite setup failed; not joined application RED"
            assert json.loads(result.stdout)["code"] == "setup_complete"
        raw_contract = contract(profiles)
        path = Path(h.CONTRACT)
        path.write_text(raw_contract)
        path.chmod(0o600)
        for arguments in h.ADMIN:
            result = invoke(arguments)
            assert result.returncode == 0, "E1 explicit administration failed; not joined application RED"
            assert json.loads(result.stdout)["code"] == "admin_complete"

        result = invoke(h.LAUNCH)
        # First application acceptance assertion. This is an actual installed
        # api-launch -> api-serve attempt, not a source-inspection placeholder.
        assert result.returncode == 0, "Production installed synthetic owner composition is missing or refused"
        launched = True
        ready = json.loads(result.stdout)
        assert ready["state"] == "ready"
        # Proposed execution capability projection. Query-only readiness is not
        # accepted as an execution witness, even if a descriptor exists.
        capabilities = ready.get("capabilities", {})
        assert (
            capabilities.get("mode") == "isolated-synthetic-execution-v1"
        ), "Production installed execution composition/capabilities are absent; query readiness is not execution"
        assert capabilities.get("submit") is True
        assert capabilities.get("required_policy") is False
        server_pid = h.server_pid()
        pause.parent.mkdir(mode=0o700)
        pause.write_bytes(PAUSE_BYTES)
        pause.chmod(0o600)
        result = invoke(h.SUBMIT)
        assert result.returncode == 0, "Production installed submit command/transport is missing or refused"
        admitted = json.loads(result.stdout)
        assert admitted["data"]["submitWorkflow"]["runId"] == h.RUN_ID
        assert admitted["data"]["submitWorkflow"]["operationId"] == h.OPERATION
        assert not Path(f"/proc/{result.pid}").exists(), "submit was not reaped"
        deadline = min(h.ACTIVE.deadline, time.monotonic() + 15)
        while not list(Path("/evidence").glob("generation-child-*-active.json")):
            assert time.monotonic() < deadline, "actual generation SDK barrier not reached"
            time.sleep(0.02)
        active_paths = list(Path("/evidence").glob("generation-child-*-active.json"))
        assert len(active_paths) == 1
        active = h.read_json(active_paths[0])
        worker_pid = active["identity"]["pid"]
        assert active["calls"] == 2 and active["phase"] == "waiting" and active["outcome"] is None
        assert active["response_ready"] is True and active["response_returning"] is False
        witness = h.read_json(Path(f"/evidence/join-process-{worker_pid}-started.json"))
        assert witness["parent_pid"] == server_pid and witness["role"] == "model"
        assert witness["preimport"]["before_package_imports"] is True
        worker_identity = {key: witness[key] for key in IDENTITY_FIELDS}
        assert active["identity"] == worker_identity
        server = h.read_json(Path(f"/evidence/join-process-{server_pid}-started.json"))
        assert server["role"] == "server"
        server_identity = {key: server[key] for key in IDENTITY_FIELDS}
        worker_live = h.live_identity(worker_identity)
        server_live = h.live_identity(server_identity)
        observed_at = time.monotonic()
        assert pause.read_bytes() == PAUSE_BYTES
        h.write_evidence(
            "join-detached.json",
            {
                "submit_pid": result.pid,
                "server_identity": server_identity,
                "worker_identity": worker_identity,
                "worker_live": worker_live,
                "server_live": server_live,
                "submit_reaped_before_release": True,
                "observed_at": observed_at,
                "release_requested_at": time.monotonic(),
            },
        )
        pause.unlink()
        result = invoke(h.RESULT)
        assert result.returncode == 0, "Production exact-result HTTP reader missing or incomplete"
        h.verify_result(json.loads(result.stdout), raw_contract)
        result = invoke(h.STOP)
        assert result.returncode == 0 and json.loads(result.stdout)["state"] == "stopped"
        launched = False
        result = invoke(h.STATUS)
        assert result.returncode == 0 and json.loads(result.stdout)["state"] == "stopped"
        h.verify_positive()
    finally:
        if pause.exists():
            pause.unlink()
        # Only the fixed stop/status roles; never restart, retry submit or create
        # authority from a receipt. Cleanup failure must remain visible.
        if launched:
            for arguments in (h.STOP, h.STATUS):
                if h.unused(arguments):
                    invoke(arguments)
        h.write_evidence("join-case.json", {
            "processes": records,
            "positive_complete": h.ACTIVE.positive_complete,
            "proof_negative_checks": proof_negative_checks,
        })
