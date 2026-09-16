#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Static, bounded real-core process-death worker; never launches workloads."""
import hashlib
import json
import os
import re
import signal
import sys
import time
import traceback
from pathlib import Path

CASES = ("partial-payload", "before-promotion", "after-promotion", "race-same", "race-different")
MODES = ("serve", "kill", "read", "retry", "race-a", "race-b", "snapshot", "resync-failure")
OUT = Path("/evidence")
PRIVATE = Path("/private")


def publish(name, value):
    """Persist non-replacing evidence before a failpoint can terminate Python."""
    raw = json.dumps(value, indent=2, sort_keys=True).encode()
    assert len(raw) < 8 * 1024 * 1024
    with (OUT / (name + ".json")).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(OUT, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def oom():
    """Require cgroup-v2 OOM evidence, not just Docker's PID1 flag."""
    values = dict(line.split() for line in Path("/sys/fs/cgroup/memory.events").read_text().splitlines())
    assert {"oom", "oom_kill", "oom_group_kill"} <= set(values)
    return {name: int(values[name]) for name in ("oom", "oom_kill", "oom_group_kill")}


def identity():
    return {"pid": os.getpid(), "start_ticks": Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19],
            "pid_namespace": os.readlink("/proc/self/ns/pid")}


def preimport(token, fresh):
    """Reuse the initial preflight; recheck kernel isolation on every exec."""
    from api import preflight, probe_egress
    if fresh:
        proof = preflight()
    else:
        assert not any(name.startswith("isaaclab_arena") for name in sys.modules)
        assert os.getuid() == 1000
        status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
        assert int(status["CapEff"].strip(), 16) == 0 and status["NoNewPrivs"].strip() == "1"
        assert not list(Path("/dev").glob("nvidia*")) and not Path("/dev/dri").exists()
        assert {p.name for p in Path("/sys/class/net").iterdir()} == {"lo"}
        assert all(os.statvfs(p).f_flag & os.ST_RDONLY for p in ("/", "/source", "/isaac-sim"))
        assert (PRIVATE / "owner").read_text() == token
        proof = {"uid": 1000, "egress_denied": True, "errno": probe_egress(),
                 "before_repository_imports": True, "readonly_source_root_deps": True,
                 "caps": status["CapEff"].strip(), "no_new_privileges": True, "gpu_devices": []}
    proof["oom"] = oom()
    return proof


def preserve(case, invocation):
    """Copy exact private fixture/bundle bytes before destroying owned tmpfs."""
    from confined_io import ConfinedRoot, new_destination
    root = PRIVATE / case
    if not root.exists():
        return {}
    files = {}
    total = 0
    with ConfinedRoot(root) as source, new_destination(OUT / (invocation + "-state")) as target:
        names = source.files(Path(), {".json", ".yaml"}, recursive=True)
        assert len(names) <= 40
        for name in names:
            raw = source.read(name)
            total += len(raw)
            assert total <= 8 * 1024 * 1024
            target.write_new(name, raw)
            files[str(name)] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return files


def bootstrap(counts):
    """Import the genuine core only after denial and genuine metadata capture."""
    import platform
    import subprocess
    from api import MetadataReplay, capture_git_metadata, make_audit, make_profile, metadata_popen
    from backend_checks import CoreImportBoundary
    platform.processor = lambda: os.uname().machine
    metadata = capture_git_metadata()
    replay = MetadataReplay(metadata, counts)
    sys.addaudithook(make_audit(counts))
    sys.setprofile(make_profile(counts))
    sys.meta_path.insert(0, CoreImportBoundary(counts))
    sys.path.insert(0, "/source")
    native = subprocess.Popen
    subprocess.Popen = metadata_popen(replay)
    try:
        import git  # noqa: F401 -- genuine immutable-image GitPython
    finally:
        subprocess.Popen = native
    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    from isaaclab_arena.agentic_environment_generation.workbench import editor_revision_storage as storage
    return Documents, storage, {"stdout": metadata["stdout"].decode("ascii"), "returncode": metadata["returncode"],
                                "replays": replay.reads}


def main(token, mode, case, invocation):
    assert re.fullmatch(r"arena-revproc-[a-f0-9]{12}", token)
    assert mode in MODES and case in CASES
    assert re.fullmatch(r"[a-z][a-z0-9-]{0,63}", invocation)
    os.umask(0o077)
    signal.alarm(300 if mode == "serve" else 45)
    counts = dict.fromkeys(("network", "provider", "graph", "render", "workload", "subprocess"), 0)
    proof = {"schema_version": 1, "run": token, "mode": mode, "case": case, "invocation": invocation,
             "identity": identity(), "status": "failed", "forbidden": counts, "power_loss_test": False}
    armed = False

    def signals(event, args):
        if event == "os.kill":
            assert armed and args == (os.getpid(), signal.SIGKILL), "Only armed worker self-SIGKILL is authorized"
        if event == "os.killpg":
            raise RuntimeError("Process-group signalling denied")
    sys.addaudithook(signals)
    try:
        proof["preimport"] = preimport(token, mode == "serve")
        publish(invocation + "-preimport", proof)
        if mode == "serve":
            (PRIVATE / "owner").write_text(token)
            from confined_io import read_confined
            from stage import BACKEND_FIXTURE
            fixture = read_confined(Path("/source"), BACKEND_FIXTURE)
            for name in CASES:
                root = PRIVATE / name
                (root / "root/generated_envs").mkdir(parents=True)
                (root / "state").mkdir()
                (root / "root/generated_envs/scene.yaml").write_bytes(fixture)
            proof["fixture_sha256"] = hashlib.sha256(fixture).hexdigest()
            executable = str(Path(sys.executable).resolve(strict=True))
            assert executable.startswith("/isaac-sim/") and os.statvfs(executable).f_flag & os.ST_RDONLY
            runtime_env = {}
            for name in ("PYTHONPATH", "LD_LIBRARY_PATH", "CARB_APP_PATH", "ISAAC_PATH", "EXP_PATH"):
                if name in os.environ:
                    paths = [p for p in os.environ[name].split(":") if p]
                    assert all(p.startswith(("/isaac-sim/", "/usr/lib/", "/lib/")) or p == "/isaac-sim" for p in paths)
                    runtime_env[name] = ":".join(paths)
            proof["interpreter"] = {"executable": executable, "environment": runtime_env}
            proof["status"] = "ready"
            publish("ready", proof)
            time.sleep(290)
            raise TimeoutError("Owned keeper walltime expired")
        if mode == "snapshot":
            proof["files"] = {name: preserve(name, invocation + "-" + name) for name in CASES}
            proof["status"] = "passed"
            return 0
        Documents, storage, proof["metadata"] = bootstrap(counts)
        root = PRIVATE / case
        state = root / "state"
        documents = Documents(state, root=root / "root")
        text = (root / "root/generated_envs/scene.yaml").read_text()
        if case == "race-different" and mode == "race-b":
            text += "# distinct request payload\n"
        key = token + ":" + case
        proof["key"] = key
        proof["revision_id"] = storage.key_id(key)
        proof["request_sha256"] = storage.request_hash(text, None, None)
        syncs = []
        native_sync = os.fsync

        def sync(fd):
            path = os.readlink(f"/proc/self/fd/{fd}")
            if path.startswith(str(state)):
                if mode == "resync-failure":
                    proof["injected_resync_failure"] = path
                    raise OSError("test-only retry resync unavailable")
                result = native_sync(fd)
                syncs.append(path)
                return result
            return native_sync(fd)
        os.fsync = sync
        proof["successful_fsync_paths"] = syncs

        def die(point):
            nonlocal armed
            assert mode == "kill" and point == case and point in CASES[:3]
            proof.update(status="failpoint-reached", failpoint=point, signal="SIGKILL", ack_emitted=False,
                         oom_before_kill=oom(), files=preserve(case, invocation))
            assert not any(counts.values())
            publish(invocation + "-witness", proof)
            armed = True
            os.kill(os.getpid(), signal.SIGKILL)
            raise AssertionError("SIGKILL returned")

        if mode == "kill":
            native_write = os.write
            native_promote = storage.artifacts._rename_noreplace

            def partial_write(fd, data):
                target = os.readlink(f"/proc/self/fd/{fd}")
                if case == "partial-payload" and target.endswith("/snapshot.json") and target.startswith(str(state)):
                    written = native_write(fd, data[:7])
                    proof["partial_write"] = {"written": written, "requested": len(data), "target": target}
                    assert written == 7 and len(data) > written
                    die("partial-payload")
                return native_write(fd, data)

            def promote(*args):
                assert args[3] == "manifest.json"
                if case == "before-promotion":
                    die(case)
                result = native_promote(*args)
                if case == "after-promotion":
                    die(case)
                return result
            os.write = partial_write
            storage.artifacts._rename_noreplace = promote

        protect = None
        if mode in {"race-a", "race-b"}:
            import fcntl
            entered, blocked = root / "lock-held", root / "contender-blocked"
            def wait(path):
                deadline = time.monotonic() + 12
                while not path.exists():
                    assert time.monotonic() < deadline, "Race rendezvous deadline"
                    time.sleep(0.01)
            if mode == "race-a":
                def protect(bundle):
                    if not entered.exists():
                        entered.write_text(str(os.getpid()))
                        publish(invocation + "-lock-held", proof)
                        wait(blocked)
            else:
                wait(entered)
                native_flock = fcntl.flock
                def flock(fd, operation):
                    try:
                        return native_flock(fd, operation)
                    except BlockingIOError:
                        if not blocked.exists():
                            blocked.write_text(str(os.getpid()))
                            proof["real_flock_contention"] = True
                            publish(invocation + "-contended", proof)
                        raise
                fcntl.flock = flock
        try:
            if mode in {"read", "resync-failure"}:
                receipt = documents.save_request(key)
            else:
                receipt = documents.save(text, None, None, idempotency_key=key, protect_snapshot=protect)
            assert receipt["idempotency_key"] == key and receipt["revision"]["revision_id"] == storage.key_id(key)
            proof.update(outcome="committed", receipt=receipt)
            if mode in {"read", "retry"}:
                opened = documents.load(receipt["revision"]["open_source"]["id"])
                proof["reopened"] = {"yaml_matches": opened["yaml_text"] == receipt["revision"]["yaml_text"],
                                     "source_hash": opened["source_hash"], "valid": opened["validation"]["valid"],
                                     "canonical_hash": opened["validation"]["canonical_hash"]}
                assert proof["reopened"]["yaml_matches"] and proof["reopened"]["valid"]
        except (storage.RevisionError, storage.RevisionUncertain, KeyError) as error:
            proof.update(outcome="not-success", error_type=type(error).__name__, error_message=str(error))
        assert mode != "kill", "Requested failpoint was not reached"
        proof["catalogue_ids"] = documents.revisions.ids()
        proof["files"] = preserve(case, invocation)
        assert not any(counts.values())
        proof["status"] = "passed"
        return 0
    except BaseException:
        proof["failure"] = traceback.format_exc()
        raise
    finally:
        proof["oom_after"] = oom()
        proof["imported_modules"] = sorted(name for name in sys.modules if name.startswith(("isaaclab_arena", "neo4j", "git")))
        publish(invocation + "-result", proof)


if __name__ == "__main__":
    assert len(sys.argv) == 5
    raise SystemExit(main(*sys.argv[1:]))
