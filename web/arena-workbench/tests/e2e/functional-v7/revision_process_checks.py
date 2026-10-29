#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Bounded host orchestration; never imports Arena or executes live containers."""
import hashlib
import json
import os
import signal
import subprocess
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

COUNTERS = {"network", "provider", "graph", "render", "workload", "subprocess"}
CASES = ("partial-payload", "before-promotion", "after-promotion", "race-same", "race-different")
WORKER = "/source/web/arena-workbench/tests/e2e/functional-v7/revision_process_worker.py"


def validate_death(record, witness, following):
    """A 137 exit needs exact pre-kill identity, armed witness and stable OOM."""
    assert record["exit"] == 137 and isinstance(witness, dict) and isinstance(following, dict)
    assert witness["status"] == "failpoint-reached" and witness["signal"] == "SIGKILL"
    assert witness["ack_emitted"] is False
    for field in ("run", "case", "invocation"):
        assert witness[field] == record[field]
    assert witness["failpoint"] == record["case"] and record["case"] in CASES[:3]
    assert following["identity"] == witness["identity"]
    assert following["docker_oom_killed"] is False
    assert set(witness["oom_before_kill"]) == {"oom", "oom_kill", "oom_group_kill"}
    assert witness["oom_before_kill"] == following["oom"]
    assert set(witness["forbidden"]) == COUNTERS and not any(witness["forbidden"].values())
    return True


def assert_resync(proof):
    state = "/private/" + proof["case"] + "/state"
    area = state + "/editor-revision-bundles"
    bundle = area + "/" + proof["revision_id"]
    expected = {state, area, bundle, *(bundle + "/" + name for name in ("manifest.json", "snapshot.json", "export.yaml"))}
    assert expected <= set(proof["successful_fsync_paths"]), "Replay did not genuinely fsync all bundle files and ancestors"


def main():
    from confined_io import read_confined
    from run import OwnedRun, compare_source, discover, docker, hash_evidence, projection, verify_container
    from stage import stage
    here = Path(__file__).resolve().parent
    root = here.parents[4]
    assert str(root) == "/workspaces/IsaacLab-Arena"
    token = "arena-revproc-" + uuid.uuid4().hex[:12]
    output = here / ".runs" / token
    output.mkdir(parents=True)
    (output / "evidence").mkdir(mode=0o700)
    os.chown(output / "evidence", 1000, 1000)
    run = OwnedRun(output, token)
    run.proof.update(status="failed", scope="real Documents/keyed RevisionStorage, OS process death and flock concurrency",
                     power_loss_test=False, executions=[], cases={}, bounds={"wall_seconds": 300,
                     "worker_seconds": 45, "exec_seconds": 55, "max_execs": 20, "max_parallel_writers": 2,
                     "source_bytes": 134217728, "private_bytes": 134217728, "snapshot_bytes": 8388608})
    print(json.dumps({"output": str(output)}), flush=True)
    started = time.monotonic()
    cid = None
    mounts = []
    calls = 0
    export_ok = False
    previous = {}

    def interrupt(signum, frame):
        raise TimeoutError(f"Bounded host interruption: {signum}")
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        previous[sig] = signal.signal(sig, interrupt)
    signal.alarm(300)

    def read(name):
        return json.loads(read_confined(output, "evidence/" + name + ".json"))

    def exact_owned():
        from run import IDENTITY_FORMAT
        info = json.loads(docker("inspect", "--format", IDENTITY_FORMAT, cid))
        assert info == {"Id": cid, "Name": "/" + token + "-workers", "Label": token}
        assert run.proof["created_ids"][token + "-workers"] == cid
        assert run.proof["verified_isolation"][token + "-workers"] is True

    def environment(mode, case, invocation):
        env = ["-i", "HOME=/tmp", "PATH=/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE=1", "PYTHONNOUSERSITE=1",
               "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", "NVIDIA_VISIBLE_DEVICES=void", "CUDA_VISIBLE_DEVICES="]
        executable = "/isaac-sim/python.sh"
        if mode != "serve":
            interpreter = run.proof["keeper"]["interpreter"]
            executable = interpreter["executable"]
            assert executable.startswith("/isaac-sim/") and ".." not in Path(executable).parts
            assert set(interpreter["environment"]) <= {"PYTHONPATH", "LD_LIBRARY_PATH", "CARB_APP_PATH", "ISAAC_PATH", "EXP_PATH"}
            env.extend(name + "=" + value for name, value in interpreter["environment"].items())
        return [*env, executable, WORKER, token, mode, case, invocation]

    def execute(mode, case, invocation):
        nonlocal calls
        exact_owned()
        calls += 1
        assert calls <= 20
        record = {"run": token, "case": case, "mode": mode, "invocation": invocation, "container_id": cid}
        begin = time.monotonic()
        try:
            result = subprocess.run(["docker", "exec", "--user=1000:1000", cid, "/usr/bin/env",
                                     *environment(mode, case, invocation)], capture_output=True, timeout=55)
            record.update(exit=result.returncode, seconds=time.monotonic() - begin)
            assert len(result.stdout) + len(result.stderr) <= 1024 * 1024
            (output / "evidence" / (invocation + ".stdout")).write_bytes(result.stdout)
            (output / "evidence" / (invocation + ".stderr")).write_bytes(result.stderr)
            record["preimport"] = read(invocation + "-preimport")
            if mode == "kill":
                record["witness"] = read(invocation + "-witness")
                assert not (output / "evidence" / (invocation + "-result.json")).exists(), "Killed worker ran a finalizer/ACK"
            else:
                record["result"] = read(invocation + "-result")
                assert record["exit"] == 0 and record["result"]["status"] == "passed", record
                assert set(record["result"]["forbidden"]) == COUNTERS and not any(record["result"]["forbidden"].values())
                assert record["preimport"]["preimport"]["oom"] == record["result"]["oom_after"]
            exact_owned()
            return record
        except BaseException:
            record["failure"] = traceback.format_exc()
            raise
        finally:
            run.proof["executions"].append(record)
            (output / (invocation + "-exec.json")).write_text(json.dumps(record, indent=2))

    try:
        discovery = discover(root, False)
        run.proof["discovery"] = discovery
        source = stage(root, output / "source", False,
                       backend_tests=["isaaclab_arena/tests/test_workbench_editor_revisions.py"])
        run.proof["source_sha256"] = source
        (output / "source-manifest.json").write_text(json.dumps(source, indent=2))
        run.proof["dependency"] = {"policy": "original immutable image only; no Neo4j dependency acquisition", "packages_acquired": []}
        host = discovery["host_root"] + "/" + output.relative_to(root).as_posix()
        mounts = [f"type=bind,src={host}/source,dst=/source,readonly", f"type=bind,src={host}/evidence,dst=/evidence"]
        cid = run.create("workers", discovery["runtime_image"], "/usr/bin/env",
                         environment("serve", CASES[0], "keeper"), mounts)
        verify_container(run, cid, mounts)
        assert run.proof["containers"][-1]["image"] == discovery["runtime_image"]
        docker("start", cid)
        deadline = time.monotonic() + 20
        while not (output / "evidence/ready.json").exists():
            assert time.monotonic() < deadline, "Keeper preflight deadline (20 seconds)"
            state = json.loads(docker("inspect", "--format", projection({"Running": ".State.Running"}), cid))
            assert state["Running"], "Keeper exited before preimport proof"
            time.sleep(0.1)
        run.proof["keeper"] = read("ready")
        for case in CASES[:3]:
            death = execute("kill", case, case + "-kill")
            observed = execute("read", case, case + "-read")
            retry = execute("retry", case, case + "-retry")
            after = observed["result"]
            state = json.loads(docker("inspect", "--format", projection({"OOMKilled": ".State.OOMKilled"}), cid))
            validate_death(death, death["witness"], {"identity": death["preimport"]["identity"],
                           "oom": observed["preimport"]["preimport"]["oom"], "docker_oom_killed": state["OOMKilled"]})
            assert death["preimport"]["preimport"]["oom"] == death["witness"]["oom_before_kill"]
            assert death["witness"]["files"] == after["files"] == retry["result"]["files"], "Retry changed crash evidence"
            expected = 1 if case == "after-promotion" else 0
            for result in (after, retry["result"]):
                assert len(result["catalogue_ids"]) == expected
                assert sum(name.endswith("/manifest.json") for name in result["files"]) == expected
                if expected:
                    assert result["outcome"] == "committed"
                    assert_resync(result)
                else:
                    assert result["outcome"] == "not-success"
                    assert result["error_type"] == "RevisionError" and result["error_message"] == "Incomplete or corrupt editor revision"
            if expected:
                assert after["receipt"] == retry["result"]["receipt"]
            if case == "partial-payload":
                assert death["witness"]["partial_write"]["written"] == 7
                assert any(name.endswith("/snapshot.json") and entry["bytes"] == 7 for name, entry in after["files"].items())
            run.proof["cases"][case] = {"status": "passed", "commits": expected, "classification":
                                       "committed after fresh-process resync" if expected else "uncommitted; incomplete evidence retained; no success",
                                       "exit": death["exit"], "intentional_sigkill_verified": True,
                                       "retry_same_bytes": True, "receipt": after.get("receipt")}
        failed_sync = execute("resync-failure", "after-promotion", "after-promotion-resync-failure")["result"]
        assert failed_sync["outcome"] == "not-success" and failed_sync["error_type"] == "RevisionUncertain"
        assert failed_sync["injected_resync_failure"] and not failed_sync["successful_fsync_paths"]
        recovered = execute("read", "after-promotion", "after-promotion-resync-recovered")["result"]
        assert_resync(recovered)
        assert recovered["files"] == failed_sync["files"]
        assert recovered["receipt"] == run.proof["cases"]["after-promotion"]["receipt"]
        run.proof["retry_resync_failure"] = {"status": "passed", "classification": "RevisionUncertain, not success", "recovered_same_receipt": True}
        for case in CASES[3:]:
            # These are host Docker CLI waiters, not forked/threaded Arena writers.
            with ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(execute, "race-a", case, case + "-a")
                b = pool.submit(execute, "race-b", case, case + "-b")
                first, second = a.result(timeout=60)["result"], b.result(timeout=60)["result"]
            assert first["identity"] != second["identity"]
            assert second["real_flock_contention"] is True
            assert first["outcome"] == "committed"
            if case == "race-same":
                assert second["receipt"] == first["receipt"] and second["request_sha256"] == first["request_sha256"]
            else:
                assert second["outcome"] == "not-success" and second["error_type"] == "RevisionError"
                assert second["error_message"] == "Editor idempotency key conflict"
                assert second["request_sha256"] != first["request_sha256"]
            observed = execute("retry", case, case + "-verify")["result"]
            assert observed["receipt"] == first["receipt"]
            assert observed["catalogue_ids"] == [first["revision_id"]]
            assert sum(name.endswith("/manifest.json") for name in observed["files"]) == 1
            assert observed["files"] == first["files"] == second["files"]
            assert_resync(observed)
            run.proof["cases"][case] = {"status": "passed", "commits": 1, "real_flock_contention": True,
                                       "writer_identities": [first["identity"], second["identity"]],
                                       "outcomes": [first["outcome"], second["outcome"]], "receipt": observed["receipt"]}
        identities = [entry["preimport"]["identity"] for entry in run.proof["executions"]]
        assert len({(i["pid_namespace"], i["pid"], i["start_ticks"]) for i in identities}) == len(identities)
        assert len(run.proof["cases"]) == len(CASES)
        run.proof["total_commits"] = sum(case["commits"] for case in run.proof["cases"].values())
        run.proof["status"] = "passed"
    except BaseException:
        run.proof["failure"] = traceback.format_exc()
        print(run.proof["failure"], flush=True)
    finally:
        signal.alarm(0)
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        try:
            if cid and run.proof["verified_isolation"].get(token + "-workers"):
                try:
                    exported = execute("snapshot", CASES[0], "final-export")
                    export_ok = exported["result"]["status"] == "passed"
                except BaseException:
                    run.proof["export_failure"] = traceback.format_exc()
            run.proof["all_private_evidence_exported"] = export_ok
            run.proof["cleanup_verified"] = run.cleanup()
            manifest = run.proof.get("source_sha256", {})
            changed, errors = compare_source(output / "source", manifest)
            run.proof["staged_source_unchanged"] = bool(manifest) and not changed
            errors.extend(changed)
            run.proof["artifacts"] = {}
            hash_evidence(output, run.proof["artifacts"], errors)
            if manifest:
                run.proof["artifacts"]["source-manifest.json"] = hashlib.sha256(read_confined(output, "source-manifest.json")).hexdigest()
            run.proof["evidence_errors"] = errors
            run.proof["wall_seconds"] = time.monotonic() - started
            run.proof["exec_count"] = calls
            if errors or not manifest or not run.proof["cleanup_verified"] or not export_ok:
                run.proof["status"] = "failed"
            run.save()
            (output / "run-proof.json").write_text(json.dumps(run.proof, indent=2))
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        print(json.dumps({"status": run.proof["status"], "output": str(output), "exec_count": calls,
                          "commits": run.proof.get("total_commits"), "cleanup": run.proof.get("cleanup_verified"),
                          "remaining_owned": run.proof.get("remaining_owned")}), flush=True)
    return 0 if run.proof["status"] == "passed" else 1


if __name__ == "__main__":
    assert len(__import__("sys").argv) == 1, "No arbitrary worker/command inputs"
    raise SystemExit(main())
