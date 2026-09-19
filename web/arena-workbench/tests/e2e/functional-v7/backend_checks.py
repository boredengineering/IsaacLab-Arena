# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Focused Documents/revision pytest, never the live runtime or full test tree."""
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import traceback
import uuid
from pathlib import Path


def selection(names):
    from stage import BACKEND_TESTS, EXPLICIT_BACKEND_TESTS, PROCESS_TESTS, SCENE_ENGINES_TEST
    names = list(names) or list(BACKEND_TESTS)
    if len(names) != len(set(names)) or not set(names) <= set(BACKEND_TESTS + EXPLICIT_BACKEND_TESTS):
        raise ValueError("Only unique approved backend test files are permitted; no pytest flags")
    if any(name in PROCESS_TESTS for name in names) and names not in [[name] for name in PROCESS_TESTS]:
        raise ValueError("Generation process approved backend profile requires exact singleton")
    if SCENE_ENGINES_TEST in names and names != [SCENE_ENGINES_TEST]:
        raise ValueError("Scene engine profile requires exact singleton")
    return names


def collector_timeout(names):
    """Bound host collection only; child alarms and operation deadlines are unchanged."""
    from stage import PROCESS_TESTS
    return 300 if selection(names) in [[name] for name in PROCESS_TESTS] else 180


def core_only(names):
    """Exact core suites use image dependencies without API dependency acquisition."""
    from stage import WORKFLOW_BACKEND_TESTS

    names = selection(names)
    return names in (
        ["isaaclab_arena/tests/test_workbench_editor_revisions.py"],
        ["isaaclab_arena/tests/test_trajectory_assessment.py"],
    ) or (bool(names) and set(names) <= set(WORKFLOW_BACKEND_TESTS))


class CoreImportBoundary:
    """Reject production API imports without substituting any dependency module."""

    def __init__(self, counts):
        self.counts = counts

    def find_spec(self, fullname, path, target=None):
        prefix = "isaaclab_arena_examples.agentic_environment_generation.web_api"
        if fullname == prefix or fullname.startswith(prefix + "."):
            self.counts["workload"] += 1
            raise ImportError("core-only pytest denies production API imports")
        return None


def inference_unit_profile(profile):
    """Allow only sync SDK/backend units; retain every other execution guard."""
    def guarded(frame, event, arg):
        if (event == "call" and frame.f_code.co_name == "__init__"
                and type(frame.f_locals.get("self")).__name__ in {"InferenceBackend", "OpenAI"}):
            return
        return profile(frame, event, arg)
    return guarded


def inside(names):
    # This shim imports only stdlib + trusted harness before kernel denial.
    from api import (MetadataReplay, capture_git_metadata, make_audit, make_profile,
                     metadata_popen, preflight, write)
    proof = {"schema_version": 1, "status": "failed", "scope": "isolated focused pytest; not F0 API acceptance"}
    counts = dict.fromkeys(("network", "provider", "graph", "render", "workload", "subprocess"), 0)
    try:
        assert "pytest" not in sys.modules, "Denial must precede pytest imports"
        proof["preimport"] = preflight()
        names = selection(names)
        core = core_only(names)
        proof["mode"] = "core" if core else "api"
        if core:
            sys.meta_path.insert(0, CoreImportBoundary(counts))
        os.umask(0o077)
        os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        import platform
        platform.processor = lambda: os.uname().machine
        # Documents validation lazily registers policies, which import GitPython.
        # Retain the bounded genuine metadata capture even without API drivers.
        metadata = capture_git_metadata()
        proof["metadata_capture"] = {"stdout": metadata["stdout"].decode("ascii"), "returncode": metadata["returncode"]}
        replay = MetadataReplay(metadata, counts)
        from stage import PROCESS_TESTS
        process_profile = names in [[name] for name in PROCESS_TESTS]
        gate = None
        if process_profile:
            from generation_worker_fixture import OWNER, SpawnGate
            Path("/private/owner").write_text(OWNER)
            gate = SpawnGate(counts)
        sys.addaudithook(gate.audit if gate else make_audit(counts))
        profile = make_profile(counts)
        from stage import SCENE_ENGINES_TEST
        if names in (["isaaclab_arena/tests/test_inference_backend.py"], [SCENE_ENGINES_TEST]):
            # Network/process audit remains installed. A missed test mock fails
            # before HTTP dispatch, including in an initializer.
            from openai import DefaultHttpxClient
            with DefaultHttpxClient(trust_env=False) as client:
                transport_type = type(client._transport)
            def denied_transport(*args, **kwargs):
                counts["provider"] += 1
                raise RuntimeError("Inference units require a synthetic SDK transport")
            transport_type.handle_request = denied_transport
            if names == [SCENE_ENGINES_TEST]:
                from generation_worker_fixture import production_sdk_profile
                profile = production_sdk_profile(profile)
            else:
                profile = inference_unit_profile(profile)
            proof["scope"] = "synthetic SDK transport units; no live model execution"
        sys.setprofile(profile)
        threading.setprofile(profile)
        sys.path[:0] = ["/source"] if core else ["/source", "/pydeps"]
        native = subprocess.Popen
        subprocess.Popen = metadata_popen(replay)
        try:
            import git  # noqa: F401 -- genuine immutable-image metadata import
        finally:
            subprocess.Popen = native
        if gate:
            subprocess.Popen = gate.popen_type()
            proof["mode"] = "generation-process"
        if not core:
            # No module replacement: API tests require a real immutable package.
            import neo4j
            assert Path(neo4j.__file__).is_relative_to("/pydeps/neo4j")
        import pytest
        args = ["-q", "--noconftest", "--import-mode=importlib", "--rootdir=/source",
                "-p", "no:cacheprovider", "-o", "addopts=", "--basetemp=/private/pytest",
                "--junitxml=/evidence/pytest.xml", *["/source/" + name for name in names]]
        proof["pytest_argv"] = args
        proof["test_exit"] = int(pytest.main(args))
        if gate:
            proof["permitted_launches"] = gate.launches
            proof["permitted_launch_count"] = len(gate.launches)
            proof["launch_rejections"] = gate.rejections
            proof["child_witnesses"] = gate.verify_children()
            proof["permitted_total_processes"] = len(proof["child_witnesses"])
            assert not list(Path("/evidence").glob("generation-child-*-forbidden.json"))
        proof["metadata_replays"] = replay.reads
        proof["forbidden"] = counts
        assert proof["test_exit"] == 0 and not any(counts.values())
        import xml.etree.ElementTree as ET
        report = ET.parse("/evidence/pytest.xml").getroot()
        cases = list(report.iter("testcase"))
        assert cases and not any(list(case) for case in cases), "Failures, skips or empty collection are not success"
        proof["tests"] = len(cases)
        proof["status"] = "passed"
    except BaseException:
        proof["error"] = traceback.format_exc()
        proof["forbidden"] = counts
        raise
    finally:
        proof["imported_modules"] = sorted(name for name in sys.modules if
            name.startswith(("isaaclab_arena", "neo4j", "git")))
        write("backend-proof.json", proof)
    return 0


def main(names=(), *, runtime_image=None, provision_manifest=None):
    names = selection(names)  # Reject options/paths before discovery or side effects.
    core = core_only(names)
    from confined_io import read_confined
    from run import OwnedRun, compare_source, discover, docker, hash_evidence, obtain_dependency, verify_container, wait_file
    from run import runtime_image as selected_image, select_runtime
    from stage import stage
    here = Path(__file__).resolve().parent
    root = here.parents[4]
    token = "arena-f0-backend-" + uuid.uuid4().hex[:12]
    output = here / ".runs" / token
    output.mkdir(parents=True)
    (output / "evidence").mkdir(mode=0o700)
    run = OwnedRun(output, token)
    run.proof.update(status="failed", scope="isolated focused pytest; not F0 API acceptance", tests=names,
                     mode="core" if core else "api")
    print(json.dumps({"output": str(output), "tests": names}), flush=True)
    previous = {}
    def interrupted(signum, frame):
        raise InterruptedError(f"signal {signum}")
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, interrupted)
    try:
        discovery = select_runtime(discover(root, False), runtime_image, provision_manifest)
        run.proof["discovery"] = discovery
        if "provision" in discovery:
            (output / "provision-manifest.json").write_text(json.dumps(discovery["provision"], indent=2))
        source = stage(root, output / "source", False, backend_tests=names)
        run.proof["source_sha256"] = source
        (output / "source-manifest.json").write_text(json.dumps(source, indent=2))
        os.chown(output / "evidence", 1000, 1000)
        dependency = ({"policy": "immutable runtime image only; no dependency acquisition", "packages_acquired": []}
                      if core else obtain_dependency(run, discovery, output / "pydeps"))
        run.proof["dependency"] = dependency
        (output / "dependency-manifest.json").write_text(json.dumps(dependency, indent=2))
        if not core and "provision" in discovery:
            expected = {name: value for name, value in discovery["provision"]["recipe"]["files"].items()
                        if name.startswith("neo4j/")}
            assert dependency["source_image"] == selected_image(discovery), "Provision/donor image mismatch"
            assert dependency["files"] == expected, "Provision/donor bytes mismatch"
        host = discovery["host_root"] + "/" + output.relative_to(root).as_posix()
        run.proof["host_output"] = host
        mounts = [f"type=bind,src={host}/source,dst=/source,readonly",
                  f"type=bind,src={host}/evidence,dst=/evidence"]
        from stage import PROCESS_TESTS
        if names in [[name] for name in PROCESS_TESTS]:
            mounts.append(f"type=bind,src={host}/source-manifest.json,dst=/generation-source-manifest.json,readonly")
        if not core:
            mounts.append(f"type=bind,src={host}/pydeps,dst=/pydeps,readonly")
        argv = ["-i", "HOME=/tmp", "PATH=/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE=1",
                "PYTHONNOUSERSITE=1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", "NVIDIA_VISIBLE_DEVICES=void",
                "CUDA_VISIBLE_DEVICES=", "/isaac-sim/python.sh",
                "/source/web/arena-workbench/tests/e2e/functional-v7/backend_checks.py", "--inside", *names]
        cid = run.create("pytest", selected_image(discovery), "/usr/bin/env", argv, mounts)
        verify_container(run, cid, mounts)
        images = [record["image"] for record in run.proof["containers"] if record["id"] == cid]
        assert images == [selected_image(discovery)], "Pytest image readback mismatch"
        docker("start", cid)
        run.proof["collector_timeout_seconds"] = collector_timeout(names)
        run.save()
        wait_file(run, cid, output / "evidence/backend-proof.json", timeout=collector_timeout(names))
        observed = json.loads(read_confined(output, "evidence/backend-proof.json"))
        run.proof["backend"] = observed
        assert docker("wait", cid) == "0" and observed["status"] == "passed"
        run.proof["status"] = "passed"
    except BaseException:
        run.proof["failure"] = traceback.format_exc()
        print(run.proof["failure"], flush=True)
    finally:
        for signum in previous:
            signal.signal(signum, signal.SIG_IGN)
        try:
            run.proof["cleanup_verified"] = run.cleanup()
            errors = []
            manifest = run.proof.get("source_sha256", {})
            changed, rejected = compare_source(output / "source", manifest)
            run.proof["staged_source_unchanged"] = bool(manifest) and not changed
            errors.extend(changed + rejected)
            run.proof["artifacts"] = {}
            hash_evidence(output, run.proof["artifacts"], errors)
            for name in ("source-manifest.json", "dependency-manifest.json", "dependency-probe.json", "provision-manifest.json"):
                if (output / name).exists():
                    run.proof["artifacts"][name] = hashlib.sha256(read_confined(output, name)).hexdigest()
            run.proof["evidence_errors"] = errors
            if errors or not run.proof["cleanup_verified"] or not manifest:
                run.proof["status"] = "failed"
            run.save()
            run.proof["artifacts"]["ownership.json"] = hashlib.sha256(read_confined(output, "ownership.json")).hexdigest()
            (output / "run-proof.json").write_text(json.dumps(run.proof, indent=2))
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        print(json.dumps({"status": run.proof["status"], "output": str(output),
                          "remaining_owned": run.proof.get("remaining_owned")}), flush=True)
    return 0 if run.proof["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(inside(sys.argv[2:]) if sys.argv[1:2] == ["--inside"] else main(sys.argv[1:]))
