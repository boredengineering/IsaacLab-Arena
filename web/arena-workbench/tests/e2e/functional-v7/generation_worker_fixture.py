# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Exact test-only Python spawn seam; never a private-packet import selector."""
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

SHIM = "web/arena-workbench/tests/e2e/functional-v7/generation_worker_fixture.py"
WORKER = "isaaclab_arena_examples/agentic_environment_generation/web_api/generation_worker.py"
TEST = "isaaclab_arena_examples/tests/test_workbench_generation_worker_process.py"
MODES = (
    "scene-sdk",
    "result",
    "wait",
    "resistant",
    "descendant",
    "production",
    "production-result",
    "production-sdk",
    "production-wait",
    "production-resistant",
    "production-orphan",
    "restart-old-live",
    "restart-live-missing",
    "restart-live-cancel",
    "restart-old",
    "restart-new",
    "restart-locality",
    "restart-missing",
    "restart-cancel",
)
MANIFEST = Path("/generation-source-manifest.json")
OWNER = "generation-process-fixture-v1"
MAX_LAUNCHES = 48


def verify_sources(manifest=None):
    """Hash the entire captured closure, including dynamic entry and injected code."""
    from confined_io import read_confined

    assert os.statvfs(MANIFEST).f_flag & os.ST_RDONLY, "source manifest must be read-only"
    expected = json.loads(MANIFEST.read_text())
    manifest = expected if manifest is None else manifest
    assert manifest == expected and {SHIM, WORKER, TEST} <= set(manifest), "source manifest binding missing"
    for name, digest in manifest.items():
        assert hashlib.sha256(read_confined(Path("/source"), name)).hexdigest() == digest, "source manifest mismatch"
    return manifest


def interpreter():
    executable = str(Path(sys.executable).resolve(strict=True))
    info = Path(executable).stat()
    assert executable.startswith("/isaac-sim/") and stat.S_ISREG(info.st_mode)
    # Match revision_process_worker: trust immutable image bytes, not image UID.
    assert os.statvfs(executable).f_flag & os.ST_RDONLY
    return executable


def clean_environment():
    env = {
        "HOME": "/tmp",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "NVIDIA_VISIBLE_DEVICES": "void",
        "CUDA_VISIBLE_DEVICES": "",
    }
    for name in ("PYTHONPATH", "LD_LIBRARY_PATH", "CARB_APP_PATH", "ISAAC_PATH", "EXP_PATH"):
        if name in os.environ:
            paths = [p for p in os.environ[name].split(":") if p]
            assert all(p.startswith(("/isaac-sim/", "/usr/lib/", "/lib/")) or p == "/isaac-sim" for p in paths)
            env[name] = ":".join(paths)
    return env


def spawn_spec(mode="production"):
    """Return exact (argv, kwargs) for the adapter's actual subprocess.Popen."""
    if mode not in MODES:
        raise ValueError("Only fixed generation fixture modes are allowed")
    return [interpreter(), "-s", "-B", "/source/" + SHIM, mode], {
        "executable": interpreter(),
        "env": clean_environment(),
        "cwd": "/source",
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
        "close_fds": True,
        "pass_fds": (),
        "start_new_session": mode != "descendant",
        "text": False,
    }


class SpawnGate:
    """Permit one audit event only while the fully checked native Popen runs."""

    def __init__(self, counts, *, descendant_only=False, restart_owner=False):
        from api import make_audit

        self.fallback = make_audit(counts)
        self.local = threading.local()
        self.lock = threading.Lock()
        self.native = subprocess.Popen
        self.launches = []
        self.rejections = 0
        self.descendant_only = descendant_only
        self.restart_owner = restart_owner
        self.environment = clean_environment()
        self.executable = interpreter()
        self.manifest = verify_sources()

    def audit(self, event, args):
        if event == "subprocess.Popen" and getattr(self.local, "expected", None) == args:
            self.local.expected = None
            return None
        return self.fallback(event, args)

    def popen(self, args, *positional, **kwargs):
        mode = args[-1] if isinstance(args, list) and args else None
        valid = mode in (("descendant",) if self.descendant_only else tuple(m for m in MODES if m != "descendant"))
        if self.restart_owner:
            valid = mode == ("production-orphan" if self.restart_owner == "live" else "production-sdk")
        expected_args, expected_kwargs = spawn_spec(mode) if valid else (None, None)
        valid = valid and not positional and args == expected_args and kwargs == expected_kwargs
        valid = valid and type(args) is list and all(type(value) is str for value in args)
        valid = valid and all(type(kwargs[key]) is type(value) for key, value in expected_kwargs.items())
        valid = valid and all(type(key) is str and type(value) is str for key, value in kwargs["env"].items())
        valid = valid and kwargs.get("env") == self.environment and args[0] == self.executable
        with self.lock:
            if not valid or len(self.launches) >= (1 if self.descendant_only or self.restart_owner else MAX_LAUNCHES):
                self.rejections += 1
                raise ValueError("Only bounded fixed generation Popen is permitted")
            verify_sources(self.manifest)
            self.local.expected = (self.executable, args, "/source", self.environment)
            record = {"mode": mode, "argv": args, "pid": None}
            self.launches.append(record)
            try:
                proc = self.native(args, **kwargs)
                record["pid"] = proc.pid
                return proc
            finally:
                self.local.expected = None

    def verify_children(self, *, records=None, parent_pid=None):
        """Read every launched child's independent preimport witness and liveness."""
        from confined_io import read_confined

        from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import group_members

        children = []
        for record in self.launches if records is None else records:
            pid = record["pid"]
            observed = json.loads(read_confined(Path("/evidence"), f"generation-child-{pid}-preimport.json"))
            assert observed["identity"]["pid"] == pid and observed["parent_pid"] == (
                os.getpid() if parent_pid is None else parent_pid
            )
            assert observed["pgid"] == observed["sid"] == pid
            assert observed["identity"]["pid_namespace"] == os.readlink("/proc/self/ns/pid")
            assert observed["source_sha256"] == self.manifest
            assert observed["preimport"]["before_repository_imports"] is True
            assert not any(observed["forbidden"].values())
            if record["mode"] == "restart-old-live":
                nested = json.loads(read_confined(Path("/evidence"), f"generation-child-{pid}-nested.json"))
                assert len(nested["launches"]) == 1 and nested["launches"][0]["mode"] == "production-orphan"
                children.extend(self.verify_children(records=nested["launches"], parent_pid=pid))
            if record["mode"] in {"resistant", "production-resistant", "production-orphan"}:
                branch = json.loads(read_confined(Path("/evidence"), f"generation-child-{pid}-descendant.json"))
                descendant = branch["descendant"]
                assert branch["permitted_launches"] == [
                    {"mode": "descendant", "argv": spawn_spec("descendant")[0], "pid": descendant}
                ]
                child = json.loads(read_confined(Path("/evidence"), f"generation-child-{descendant}-preimport.json"))
                assert child["parent_pid"] == pid and child["pgid"] == child["sid"] == pid
                assert child["identity"]["pid"] == descendant and child["source_sha256"] == self.manifest
                assert child["identity"]["pid_namespace"] == observed["identity"]["pid_namespace"]
                assert not any(child["forbidden"].values())
                children.append(
                    {
                        "identity": child["identity"],
                        "pgid": pid,
                        "sid": pid,
                        "mode": "descendant",
                        "no_live_group_members": True,
                    }
                )
            assert not any(s["state"] not in {"Z", "X"} for s in group_members(pid).values())
            children.append(
                {
                    "identity": observed["identity"],
                    "pgid": pid,
                    "sid": pid,
                    "mode": observed["mode"],
                    "no_live_group_members": True,
                }
            )
        return children

    def popen_type(self):
        gate = self

        class FixedPopen:
            def __new__(cls, args, *positional, **kwargs):
                return gate.popen(args, *positional, **kwargs)

            @classmethod
            def __class_getitem__(cls, item):
                return cls

        return FixedPopen


def production_sdk_profile(fallback):
    """Exact source/code-bound exceptions; never allow configured graph reads."""
    constructors = {
        "isaaclab_arena.agentic_environment_generation.environment_generation_agent": "EnvironmentGenerationAgent",
        "isaaclab_arena.agentic_environment_generation.inference_backend": "InferenceBackend",
        "openai._client": "OpenAI",
    }
    graph = "isaaclab_arena_examples.agentic_environment_generation.web_api.graph_access"

    def guarded(frame, event, arg):
        if event == "call":
            module = frame.f_globals.get("__name__", "")
            loaded = sys.modules.get(module)
            name = frame.f_code.co_name
            if module in constructors and name == "__init__":
                cls = getattr(loaded, constructors[module], None)
                code = getattr(getattr(cls, "__init__", None), "__code__", None)
                filename = frame.f_code.co_filename
                source = (
                    filename.startswith("/isaac-sim/") and os.statvfs(filename).f_flag & os.ST_RDONLY
                    if module == "openai._client"
                    else filename == "/source/" + module.replace(".", "/") + ".py"
                )
                if source and frame.f_code is code and type(frame.f_locals.get("self")) is cls:
                    return None
            if module == "openai._base_client" and name == "__init__":
                cls = getattr(sys.modules.get("openai._client"), "OpenAI", None)
                bases = [getattr(loaded, key, None) for key in ("SyncAPIClient", "BaseClient")]
                codes = {
                    getattr(getattr(base, "__init__", None), "__code__", None)
                    for base in bases
                    if base is not None and base in getattr(cls, "__mro__", ())
                }
                filename = frame.f_code.co_filename
                if (
                    type(frame.f_locals.get("self")) is cls
                    and any(frame.f_code is code for code in codes)
                    and filename.startswith("/isaac-sim/")
                    and os.statvfs(filename).f_flag & os.ST_RDONLY
                ):
                    return None
            if module == graph and name == "retrieve_snapshot":
                function = getattr(loaded, name, None)
                if (
                    frame.f_code is getattr(function, "__code__", None)
                    and frame.f_code.co_filename == "/source/" + graph.replace(".", "/") + ".py"
                    and all(frame.f_locals.get(key) is None for key in ("config", "driver_factory", "managed_context"))
                ):
                    return None
        return fallback(frame, event, arg)

    return guarded


def production_packet(*, model_calls=2, runtime_seconds=15):
    """Bootstrap real models/catalogue only in the isolated parent; not an OS authority proof."""
    verify_sources()
    assert os.getuid() == 1000 and Path("/private/owner").read_text() == OWNER
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        AttemptFence,
        GenerationReservation,
        WorkerRegistration,
    )
    from isaaclab_arena_examples.agentic_environment_generation.web_api.catalogues import execution_catalogue_sha256

    fence = AttemptFence(
        run_id="fixture-run",
        intent_id="fixture-intent",
        attempt_id="fixture-attempt",
        generation=1,
        owner_id="fixture-owner",
        owner_epoch=1,
    )
    registration = WorkerRegistration(
        registration_id="fixture-registration",
        fence=fence,
        host="fixture-host",
        boot="fixture-boot",
        pid=os.getpid(),
        pgid=os.getpgrp(),
        sid=os.getsid(0),
        start_ticks=1,
    )
    reservation = GenerationReservation(
        model_calls=model_calls, model_tokens=4096, cost_ceiling_usd=1, runtime_allowance_seconds=runtime_seconds
    )
    now = time.time()
    return {
        "inputs": {
            "operation": "new",
            "prompt": "Fixed synthetic fixture only",
            "retrieval_policy": "allow_fallback",
            "execution_catalogue_sha256": execution_catalogue_sha256(),
        },
        "config": {
            "api_key": "synthetic-unit-key-only",
            "model": "gpt-6-astra",
            "base_url": "https://api.openai.com/v1",
        },
        "graph_config": None,
        "workflow_execution": {
            "version": 1,
            "fence": fence.model_dump(mode="json"),
            "registration": registration.model_dump(mode="json"),
            "reservation": reservation.model_dump(mode="json"),
            "admitted_at": now,
            "released_at": now,
            "deadline": now + runtime_seconds,
        },
    }


def install_synthetic_sdk(*, scene=False):
    """Keep real SDK serialization/backend; replace HTTP and only generate_spec."""
    import importlib

    import openai._base_client
    from api import write
    from openai import DefaultHttpxClient

    openai._base_client.get_platform = lambda: "Linux"
    with DefaultHttpxClient(trust_env=False) as client:
        transport_type = type(client._transport)
    httpx = importlib.import_module(transport_type.__module__.split(".")[0])
    evidence = {
        "schema_version": 1,
        "pid": os.getpid(),
        "calls": 0,
        "responses": [],
        "scope": "synthetic HTTP; real constructors, ping, catalogue and schema; fixed generate_spec",
    }
    if scene:
        from isaaclab_arena.agentic_environment_generation.spec_wire_adapter import SpecWireAdapter
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
        from isaaclab_arena.tests.utils.agentic_environment_generation import minimal_spec_dict

        wire = SpecWireAdapter().encode(ArenaEnvGraphSpec.model_validate(minimal_spec_dict()).model_dump(mode="json"))
        evidence["scope"] = "synthetic HTTP; real scene model methods, SDK and schema; no native acceptance"

    def synthetic_response(transport, request):
        body = json.loads(request.content)
        evidence["calls"] += 1
        evidence["responses"].append(
            {"ordinal": evidence["calls"], "kind": "ping" if evidence["calls"] == 1 else "completion"}
        )
        write(f"generation-child-{os.getpid()}-sdk.json", evidence)
        content = json.dumps(wire) if scene else '{"unit_evidence": true}'
        if scene and evidence["calls"] > 1:
            # Only synthetic HTTP responses change. Real agent/backend/model
            # constructors, refinement, request serialization and images remain.
            import yaml

            from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import candidate_record

            fixture_scene = yaml.safe_load(
                Path("/source/isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml").read_text()
            )
            fixture_scene["relations"].append(
                dict(kind="on", subject="mug_ycb_robolab", reference="maple_table_robolab_table", params={})
            )
            fixture_scene = ArenaEnvGraphSpec.model_validate(fixture_scene).model_dump(mode="json")
            texts = []
            for message in body.get("messages", []):
                value = message.get("content", "")
                if isinstance(value, str):
                    texts.append(value)
                elif isinstance(value, list):
                    texts.extend(part["text"] for part in value if part.get("type") == "text")
            visual = next((text.split("Request:\n", 1)[1] for text in texts if "Request:\n" in text), None)
            if visual is not None:
                pause = Path("/tmp/workflow-cli/pause-visual")
                if pause.exists():
                    import signal
                    import time

                    def terminate(signum, frame):
                        raise SystemExit(0)

                    signal.signal(signal.SIGTERM, terminate)
                    write(f"generation-child-{os.getpid()}-active.json", dict(pid=os.getpid(), calls=evidence["calls"]))
                    deadline = time.monotonic() + 20
                    while pause.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                requested = json.loads(visual)
                visible = (
                    requested["candidate"]["candidate_digest"]
                    != candidate_record("run", fixture_scene, source_id="generation").digest
                )
                content = json.dumps(
                    dict(
                        requested,
                        answers=[dict(frame_digest=f["sha256"], visible=visible) for f in requested["frames"]],
                    )
                )
            elif any("Initial foreground workflow scene fixture" in text for text in texts):
                pause = Path("/tmp/workflow-cli/pause-generation")
                if pause.exists():
                    import signal
                    import time

                    def terminate_generation(signum, frame):
                        raise SystemExit(0)

                    signal.signal(signal.SIGTERM, terminate_generation)
                    write(f"generation-child-{os.getpid()}-active.json", dict(pid=os.getpid(), calls=evidence["calls"]))
                    deadline = time.monotonic() + 20
                    while pause.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                content = json.dumps(SpecWireAdapter().encode(fixture_scene))
            elif any("supported_visual_failure" in text for text in texts):
                fixture_scene["relations"][5]["params"]["x"] += 0.03
                content = json.dumps(SpecWireAdapter().encode(fixture_scene))
        return httpx.Response(
            200,
            json={
                "id": "synthetic-unit-only",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
            request=request,
        )

    transport_type.handle_request = synthetic_response
    write(f"generation-child-{os.getpid()}-sdk.json", evidence)
    if scene:
        return
    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import EnvironmentGenerationAgent

    EnvironmentGenerationAgent.generate_spec = fixed_generate_spec


def fixed_generate_spec(self, prompt, **kwargs):
    """Deliberately exclude USD/grounding/repair/physical validity from this fixture."""
    import yaml

    from stage import FIXTURE

    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import ActiveInferenceTelemetry
    from isaaclab_arena.agentic_environment_generation.inference_backend import StructuredOutputRequest
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    assert kwargs["publish_to_graph"] is False and kwargs["prior_context"] == ""
    assert kwargs["asset_catalog"].objects and kwargs["task_catalog"].tasks
    kwargs["progress"]("spec_inference")
    self.inference_backend.run_json(
        StructuredOutputRequest(
            schema_name="FixtureEvidence",
            schema={
                "type": "object",
                "properties": {"unit_evidence": {"type": "boolean"}},
                "required": ["unit_evidence"],
                "additionalProperties": False,
            },
            system="Fixed synthetic fixture",
            user="Return fixture evidence",
            retry_label="fixture",
        )
    )
    self._telemetry = ActiveInferenceTelemetry(converged=False, shacl_passed=False, geometry_passed=False)
    return ArenaEnvGraphSpec.from_dict(yaml.safe_load(Path("/source", FIXTURE).read_text())), None


def child(mode):
    """Recheck inherited kernel isolation before importing any Arena package."""
    from api import make_audit, make_profile, write
    from revision_process_worker import identity, preimport

    assert mode in MODES
    signal.alarm(30)
    manifest = verify_sources()
    proof = {
        "identity": identity(),
        "parent_pid": os.getppid(),
        "pgid": os.getpgrp(),
        "sid": os.getsid(0),
        "source_sha256": manifest,
        "preimport": preimport(OWNER, False),
        "mode": mode,
    }
    assert os.statvfs("/pydeps").f_flag & os.ST_RDONLY
    counts = dict.fromkeys(("network", "provider", "graph", "render", "workload", "subprocess"), 0)
    metadata = None
    if mode in {"production-sdk", "scene-sdk", "restart-old", "restart-old-live"}:
        from api import capture_git_metadata

        metadata = capture_git_metadata()
    gate = (
        SpawnGate(counts, descendant_only=True)
        if mode in {"resistant", "production-resistant", "production-orphan"}
        else None
    )
    if mode in {"restart-old", "restart-old-live"}:
        gate = SpawnGate(counts, restart_owner="live" if mode == "restart-old-live" else True)
    audit = gate.audit if gate else make_audit(counts)

    def child_audit(event, args):
        try:
            audit(event, args)
        except BaseException:
            # The legacy profile can encounter cleared module globals during
            # interpreter teardown; only actual charged denials are effects.
            if any(counts.values()):
                write(f"generation-child-{os.getpid()}-forbidden.json", counts)
            raise

    sys.addaudithook(child_audit)
    profile = make_profile(counts)
    if mode in {"production-sdk", "scene-sdk"}:
        profile = production_sdk_profile(profile)

    def child_profile(frame, event, arg):
        try:
            return profile(frame, event, arg)
        except BaseException:
            # The legacy profile can encounter cleared module globals during
            # interpreter teardown; only actual charged denials are effects.
            if any(counts.values()):
                write(f"generation-child-{os.getpid()}-forbidden.json", counts)
                write(
                    f"generation-child-{os.getpid()}-denial-site.json",
                    {
                        "module": frame.f_globals.get("__name__"),
                        "function": frame.f_code.co_name,
                        "qualified_name": frame.f_code.co_qualname,
                        "filename": frame.f_code.co_filename,
                        "owner_type": type(frame.f_locals.get("self")).__name__,
                    },
                )
            raise

    sys.setprofile(child_profile)
    threading.setprofile(child_profile)
    proof["forbidden"] = counts.copy()
    proof["interpreter"] = interpreter()
    proof["environment"] = clean_environment()
    write(f"generation-child-{os.getpid()}-preimport.json", proof)
    if gate:
        subprocess.Popen = gate.popen_type()
    sys.path[:0] = ["/source", "/pydeps"]
    if metadata is not None:
        import platform

        platform.processor = lambda: os.uname().machine
        from api import MetadataReplay, metadata_popen

        replay = MetadataReplay(metadata, counts)
        native = subprocess.Popen
        subprocess.Popen = metadata_popen(replay)
        try:
            import git  # noqa: F401 — force bounded metadata replay before application imports.
        finally:
            subprocess.Popen = native
        write(
            f"generation-child-{os.getpid()}-metadata.json",
            {
                "stdout": metadata["stdout"].decode("ascii"),
                "returncode": metadata["returncode"],
                "replays": replay.reads,
            },
        )
        import contextlib

        if mode in {"production-sdk", "scene-sdk"}:
            with contextlib.redirect_stdout(sys.stderr):
                install_synthetic_sdk(scene=mode == "scene-sdk")
    if mode.startswith("restart-"):
        import contextlib

        from isaaclab_arena_examples.tests.test_workbench_generation_worker_process import _restart_owner

        with contextlib.redirect_stdout(sys.stderr):
            result = _restart_owner(mode)
        if gate:
            nested = {"launches": gate.launches} if mode == "restart-old-live" else {"children": gate.verify_children()}
            write(f"generation-child-{os.getpid()}-nested.json", nested)
        assert not any(counts.values())
        assert not Path(f"/evidence/generation-child-{os.getpid()}-sdk.json").exists()
        write(f"generation-child-{os.getpid()}-restart.json", {"result": result, "forbidden": counts.copy()})
        print(json.dumps(result), flush=True)
        return 0
    if mode == "descendant":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print(json.dumps({"ready": os.getpid()}), flush=True)
        time.sleep(25)
        return 0
    if mode == "resistant":
        args, kwargs = spawn_spec("descendant")
        descendant = subprocess.Popen(args, **kwargs)
        ready = descendant.stdout.readline()
        assert json.loads(ready)["ready"] == descendant.pid
        proof["descendant"] = descendant.pid
        proof["permitted_launches"] = gate.launches
        write(f"generation-child-{os.getpid()}-descendant.json", proof)
        print(json.dumps({"ready": os.getpid(), "descendant": descendant.pid}), flush=True)
        time.sleep(25)
        return 0
    if mode == "wait":
        print(json.dumps({"ready": os.getpid()}), flush=True)
        time.sleep(25)
        return 0
    if mode == "result":
        assert sys.stdin.buffer.readline(64) == b"release\n"
        print(json.dumps({"result": {"fixture": "fixed-result"}}), flush=True)
        return 0
    if mode == "scene-sdk":
        from isaaclab_arena_examples.agentic_environment_generation.web_api import scene_worker as generation_worker
    else:
        from isaaclab_arena_examples.agentic_environment_generation.web_api import generation_worker

    if mode in {"production-wait", "production-resistant", "production-orphan"}:
        from isaaclab_arena_examples.agentic_environment_generation.web_api import generation

        def fixed_wait(inputs, progress, **kwargs):
            if mode == "production-orphan":
                # Test-only fault injection AFTER the actual entry armed PDEATHSIG.
                # Retain entry/envelope/protocol and release watchdog unchanged.
                assert generation_worker.ctypes.CDLL(None, use_errno=True).prctl(1, 0, 0, 0, 0) == 0
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
            progress("spec_inference")
            if mode in {"production-resistant", "production-orphan"}:
                args, options = spawn_spec("descendant")
                descendant = subprocess.Popen(args, **options)
                assert json.loads(descendant.stdout.readline())["ready"] == descendant.pid
                proof["descendant"] = descendant.pid
                proof["permitted_launches"] = gate.launches
                write(f"generation-child-{os.getpid()}-descendant.json", proof)
            time.sleep(25)
            raise RuntimeError("Fixed fixture wait expired")

        generation.generate = fixed_wait
    if mode == "production-result":
        from isaaclab_arena_examples.agentic_environment_generation.web_api import generation

        def fixed_generate(inputs, progress, **kwargs):
            return {"fixture": "fixed-result"}

        generation.generate = fixed_generate
    sys.argv = ["generation_worker", "--parent-pid", str(os.getppid())]
    try:
        return generation_worker.main()
    finally:
        write(f"generation-child-{os.getpid()}-final.json", {"forbidden": counts.copy(), "mode": mode})


if __name__ == "__main__":
    assert len(sys.argv) == 2 and sys.argv[1] in MODES
    raise SystemExit(child(sys.argv[1]))
