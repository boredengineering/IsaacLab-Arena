# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Trusted F0 shim: real API, with all execution adapters denied before use."""
import asyncio
import errno
import hashlib
import http.client
import io
import json
import os
import re
import socket
import stat
import subprocess
import sys
import threading
import traceback
from pathlib import Path

ROOT = Path("/source")
OUT = Path("/evidence")
ORIGIN = "http://127.0.0.1:31847"
SOCKET = "/bridge/api.sock"


def write(name, value):
    temporary = OUT / (name + ".pending")
    temporary.write_text(json.dumps(value, indent=2))
    temporary.replace(OUT / name)


def probe_egress():
    """Require explicit kernel egress denial, never success, refusal or timeout."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(2)
        try:
            probe.connect(("1.1.1.1", 443))
        except OSError as error:
            assert error.errno in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EPERM, errno.EACCES}, repr(error)
            return error.errno
        raise AssertionError("Egress unexpectedly possible")


def verify_metadata_executable():
    """Require the image's immutable, root-owned absolute Git binary."""
    path = Path("/usr/bin/git")
    assert path.resolve(strict=True) == path, "Metadata executable must not be redirected"
    metadata = path.stat()
    assert stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0
    assert not metadata.st_mode & 0o022 and metadata.st_mode & 0o111
    assert os.statvfs(path).f_flag & os.ST_RDONLY, "Metadata executable must be read-only"


def capture_git_metadata():
    """Read actual Git version once, before package imports, with fixed bounds."""
    verify_metadata_executable()
    result = subprocess.run(
        ["/usr/bin/git", "version"], executable="/usr/bin/git", cwd="/",
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "LANGUAGE": "C", "LC_ALL": "C"},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False, close_fds=True, timeout=2, check=True,
    )
    assert result.returncode == 0 and result.stderr == b""
    assert re.fullmatch(rb"git version [0-9]+(?:\.[0-9]+)+(?:[.A-Za-z0-9+-]*)\n", result.stdout)
    return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}


class MetadataReplay:
    """Serve captured bytes to the exact GitPython import probe, never spawn.

    This is a metadata-only compatibility adapter, not a replacement GitPython
    module or a synthetic version. Unknown calls and real OS spawns are denied.
    """

    def __init__(self, metadata, counters):
        self.metadata = dict(metadata)
        self.counters = counters
        self.expected_env = dict(os.environ, LANGUAGE="C", LC_ALL="C")
        self.expected_cwd = os.getcwd()
        self.reads = 0
        self.lock = threading.Lock()

    def expected_kwargs(self):
        return dict(env=dict(self.expected_env), cwd=self.expected_cwd, bufsize=-1,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    shell=False, universal_newlines=False)

    def deny(self):
        self.counters["subprocess"] += 1
        raise RuntimeError("F0 denies subprocess work (metadata-only adapter)")

    def __call__(self, args, *positional, **kwargs):
        with self.lock:
            # GitPython versions differ only in whether encoding=None is explicit.
            expected = self.expected_kwargs()
            if "encoding" in kwargs:
                expected["encoding"] = None
            if (type(args) is not list or args != ["git", "version"] or positional
                    or kwargs != expected or self.reads >= 2):
                self.deny()
            self.reads += 1
        return CapturedMetadataProcess(self.metadata, self.deny)


class CapturedMetadataProcess:
    """Expose actual captured metadata bytes without claiming an OS PID."""

    def __init__(self, metadata, deny):
        self.args = ["git", "version"]
        self.returncode = metadata["returncode"]
        self.stdin = None
        self.stdout = io.BytesIO(metadata["stdout"])
        self.stderr = io.BytesIO(metadata["stderr"])
        self.output = (metadata["stdout"], metadata["stderr"])
        self.deny = deny

    def communicate(self, input=None, timeout=None):
        if input is not None:
            self.deny()
        return self.output

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stdout.close()
        self.stderr.close()


def metadata_popen(replay):
    """Keep Popen a subscriptable type for dependency annotations, without spawn."""
    class MetadataPopen(CapturedMetadataProcess):
        def __new__(cls, args, *positional, **kwargs):
            return replay(args, *positional, **kwargs)

        @classmethod
        def __class_getitem__(cls, item):
            return cls
    return MetadataPopen


def make_audit(counters):
    """Deny every actual OS process and IP connection after trusted capture."""
    def audit(event, args):
        if event == "socket.connect" and args[0].family != socket.AF_UNIX:
            counters["network"] += 1
            raise RuntimeError("F0 denies IP connections")
        if event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.fork", "os.forkpty"}:
            counters["subprocess"] += 1
            raise RuntimeError("F0 denies subprocess work")
    return audit


def make_profile(counters):
    """Deny construction/execution adapters without importing their packages."""
    def profile(frame, event, arg):
        if event != "call":
            return
        module = frame.f_globals.get("__name__", "")
        name = frame.f_code.co_name
        owner = type(frame.f_locals.get("self")).__name__
        category = None
        if name == "__init__" and owner in {"InferenceBackend", "EnvironmentGenerationAgent", "OpenAI", "AsyncOpenAI"}:
            category = "provider"
        elif module.startswith("neo4j") and name in {"driver", "__init__"} and (name == "driver" or owner.endswith("Driver")):
            category = "graph"
        elif module.endswith("snapshot_service") and (name == "render" or owner == "SnapshotService"):
            category = "render"
        elif module.endswith("graph_access") and name == "retrieve_snapshot":
            category = "graph"
        if category:
            counters[category] += 1
            raise RuntimeError(f"F0 denies {category} construction/execution")
    return profile


def workload_allowed(method, path, counters, profile="readonly", body=None):
    assert profile in {"readonly", "authoring-v1", "manual-research-v1"}
    if profile == "manual-research-v1" and method not in {"GET", "HEAD"} and path not in {
            "/api/sessions", "/api/session/activity", "/api/editor/validate", "/api/session"}:
        from manual_research import manual_mutation
        allowed = manual_mutation(method, path, body)
        if not allowed:
            counters["workload"] += 1
        return allowed
    keyed_save = (profile == "authoring-v1" and method == "POST" and path == "/api/editor/save"
                  and type(body) is dict and type(body.get("idempotency_key")) is str
                  and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", body["idempotency_key"]) is not None)
    allowed = keyed_save or method in {"GET", "HEAD"} or (method == "POST" and path in
              {"/api/sessions", "/api/session/activity", "/api/editor/validate"}) or (
              method == "DELETE" and path == "/api/session")
    if not allowed:
        counters["workload"] += 1
    return allowed


async def manual_request_body(request):
    """Bound raw bytes and reject duplicate keys before dispatch or reservation."""
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 2 * 1024 * 1024:
            raise ValueError("Manual request exceeds bounds")
        chunks.append(chunk)
    raw = b"".join(chunks)
    def unique(pairs):
        value = {}
        for key, child in pairs:
            if key in value:
                raise ValueError("Duplicate manual request key")
            value[key] = child
        return value
    body = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    # Reject nonfinite values, invalid Unicode and excessive encoder nesting.
    json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    # Starlette's cached request forwards these exact bytes after stream parsing.
    request._body = raw
    return body


def preflight():
    assert not any(name.startswith("isaaclab_arena") for name in sys.modules)
    assert os.getuid() == 1000
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    assert int(status["CapEff"].strip(), 16) == 0 and status["NoNewPrivs"].strip() == "1"
    assert not list(Path("/dev").glob("nvidia*")) and not Path("/dev/dri").exists()
    assert {p.name for p in Path("/sys/class/net").iterdir()} == {"lo"}
    for mount in ("/", "/source", "/isaac-sim", *(["/pydeps"] if Path("/pydeps").exists() else [])):
        assert os.statvfs(mount).f_flag & os.ST_RDONLY, mount
    assert not list(Path("/private").iterdir()), "Fresh state required"
    denial = probe_egress()
    evidence = {"schema_version": 2, "status": "passed", "egress_denied": True, "errno": denial, "uid": os.getuid(),
                "before_repository_imports": True, "caps": status["CapEff"].strip(),
                "no_new_privileges": True, "readonly_source_root_deps": True, "gpu_devices": []}
    write("preimport-api.json", evidence)
    assert os.environ.get("F0_FAULT") != "preimport-denial", "Injected preimport denial"
    return evidence


def final_record(counters, jobs, lifespan_closed, socket_absent):
    """Publish success only after the genuine lifespan and socket observations."""
    assert set(counters) == {"network", "provider", "graph", "render", "workload", "subprocess"}
    assert all(type(value) is int and value == 0 for value in counters.values())
    assert jobs == [] and lifespan_closed is True and socket_absent is True
    return {"schema_version": 2, "status": "passed", "forbidden": dict(counters), "jobs": jobs,
            "lifespan_closed": lifespan_closed, "socket_absent": socket_absent}


def bootstrap_manual_store(app, store_class):
    """Initialize one fresh store on the existing lifespan Journal; never open another."""
    from manual_research import STORE
    assert set(app.state.research_roots) == {STORE}
    root = Path(app.state.research_roots[STORE])
    assert not root.exists() and not root.is_symlink(), "Fresh manual store required"
    store = store_class.create(app.state.journal, root, STORE,
                               protect_public=app.state.model_settings.protect_public)
    try:
        observed = manual_store_identity(app, store)
    finally:
        store.close()  # Owns artifact descriptors, not the app Journal.
    return {**observed, "root": str(root), "fresh": True, "closed": True}


def manual_store_identity(app, store):
    """Observe the actual registry and its caller-owned Journal, not a chosen ID."""
    from manual_research import STORE, matches
    assert store.store_id == STORE and store.registry.journal is app.state.journal
    registry_id = store.registry.registry_id
    assert matches(registry_id, r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
    return {"store_id": STORE, "registry_id": registry_id, "existing_app_journal": True}


async def main():
    proof = {"schema_version": 2, "status": "failed", "forbidden": {"network": 0, "provider": 0, "graph": 0, "render": 0,
                                               "workload": 0, "subprocess": 0}, "http": []}
    profile_name = os.environ.get("F0_PROFILE", "readonly")
    assert profile_name in {"readonly", "authoring-v1", "manual-research-v1"}
    authoring_writes = []
    manual_writes = []
    manual = profile_name == "manual-research-v1"
    if manual:
        from manual_research import MutationBudget
        manual_budget = MutationBudget()
    proof["profile"] = profile_name
    try:
        proof["preimport"] = preflight()
        os.umask(0o077)
        # Warp's metadata lookup otherwise spawns `uname -p` during registry import.
        # Resolve real CPU architecture through the equivalent stdlib syscall instead.
        import platform
        platform.processor = lambda: os.uname().machine
        counters = proof["forbidden"]
        # Capture from the immutable image with trusted fixed arguments, not from
        # package code. Subsequent GitPython import probes replay these exact bytes;
        # no package-triggered OS subprocess (even `git version`) is permitted.
        metadata = capture_git_metadata()
        proof["metadata_capture"] = {"argv": ["/usr/bin/git", "version"], "cwd": "/",
                                     "timeout_seconds": 2, "before_repository_imports": True,
                                     "stdout": metadata["stdout"].decode("ascii"),
                                     "returncode": metadata["returncode"]}
        # No package-triggered subprocess is permitted. The one trusted OS capture
        # is recorded separately above; replay reads are not OS processes.
        proof["metadata_subprocesses"] = []
        replay = MetadataReplay(metadata, counters)
        sys.addaudithook(make_audit(counters))
        profile = make_profile(counters)
        sys.setprofile(profile)
        threading.setprofile(profile)
        sys.path.insert(0, str(ROOT))
        if Path("/pydeps").exists():
            sys.path.insert(0, "/pydeps")
        # Only GitPython retains the metadata adapter. Other dependencies retain
        # the real Popen type, whose every execution is denied by the audit hook.
        native_popen = subprocess.Popen
        subprocess.Popen = metadata_popen(replay)
        try:
            import git  # noqa: F401 -- genuine import-time version/flag initialization
        finally:
            subprocess.Popen = native_popen
        from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, editor_execution
        from fastapi.responses import JSONResponse
        import uvicorn
        def unavailable(*args, **kwargs):
            # Deliberately unavailable adapter, not a fake snapshot result.
            raise ImportError("F0 excludes the snapshot adapter")
        editor_execution.make_snapshot_service = unavailable
        app = create_app("/private/state", origin=ORIGIN, diagnostics=False, start_paused=True,
                         research_roots={"manual-browser": Path("/private/manual-research")} if manual else {},
                         publication_profiles={}, publication_enabled=False,
                         managed_retrieval_enabled=False)
        app.state.neo4j_available = False
        @app.middleware("http")
        async def workload_boundary(request, next_handler):
            mutation_path = request.url.path == "/api/editor/save" or (manual and request.url.path == "/api/research/stores/manual-browser/versions")
            try:
                body = None
                if request.method == "POST" and mutation_path:
                    body = await manual_request_body(request) if manual else await request.json()
            except (ValueError, UnicodeError, RecursionError):
                body = None
            boundary_path = request.url.path + ('?' + request.url.query if manual and mutation_path and request.url.query else '')
            if not workload_allowed(request.method, boundary_path, counters, profile_name, body):
                return JSONResponse({"detail": "F0 denies workload mutation"}, status_code=403)
            if manual and mutation_path and request.method == "POST":
                writes = authoring_writes if request.url.path == "/api/editor/save" else manual_writes
                if not manual_budget.admit(request.url.path):
                    counters["workload"] += 1
                    return JSONResponse({"detail": "F0 mutation budget exhausted"}, status_code=403)
                record = {"method": "POST", "path": request.url.path, "request": body, "status": None}
                writes.append(record)
                response = await next_handler(request)
                record["status"] = response.status_code
                return response
            response = await next_handler(request)
            if request.method == "POST" and request.url.path == "/api/editor/save":
                authoring_writes.append({"method": "POST", "path": request.url.path, "request": body, "status": response.status_code})
            return response
        server = uvicorn.Server(uvicorn.Config(app, uds=SOCKET, log_level="warning", lifespan="on", access_log=False))
        serving = asyncio.create_task(server.serve())
        for _ in range(400):
            if server.started:
                break
            if serving.done():
                await serving
                raise AssertionError("API failed to start")
            await asyncio.sleep(0.025)
        assert server.started
        try:
            if manual:
                from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
                proof["manual_store"] = bootstrap_manual_store(app, ResearchStore)
            proof.update(await asyncio.to_thread(acceptance, proof))
            proof["metadata_replays"] = replay.reads
            assert not any(counters.values()), counters
            proof["status"] = "passed"
            write("api-proof.json", proof)
            for _ in range(2400):
                if Path("/bridge/stop").exists():
                    break
                await asyncio.sleep(0.1)
            else:
                raise TimeoutError("Bounded F0 lifespan expired")
            jobs = app.state.journal.snapshot()["jobs"]
            recreated_documents = []
            if manual:
                manual_versions = []
                with ResearchStore.open(app.state.journal, Path('/private/manual-research'), 'manual-browser',
                                        protect_public=app.state.model_settings.protect_public) as store:
                    final_manual_store = {**manual_store_identity(app, store), 'root': '/private/manual-research', 'fresh': True, 'closed': True}
                    assert final_manual_store == proof['manual_store'], 'Observed registry lineage mismatch'
                    for record in manual_writes:
                        assert record['status'] == 201
                        reservation = store.registry.get_reservation_for_workflow('manual-browser', record['request']['idempotency_key'])
                        assert reservation is not None
                        commit = store.registry.get_commit(reservation['reservation_id'])
                        files = store.read_version(reservation['reservation_id'])
                        folder = OUT / ('manual-version-' + str(reservation['version']))
                        folder.mkdir()
                        for name, data in files.items():
                            assert '/' not in name and name not in {'.', '..'}
                            (folder / name).write_bytes(data)
                        manual_versions.append(commit)
                assert not app.state.publication_authorization._records
                assert not app.state.workflow_authorization.grants._records
            if profile_name == "authoring-v1" and authoring_writes:
                from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
                recreated = Documents(app.state.documents.state_dir, root=ROOT)
                assert recreated.views == {} and recreated.frozen == {}
                for write_record in authoring_writes:
                    if write_record["status"] != 200:
                        continue
                    receipt = recreated.save_request(write_record["request"]["idempotency_key"])
                    loaded = recreated.load(receipt["revision"]["open_source"]["id"])
                    assert loaded["yaml_text"] == receipt["revision"]["yaml_text"]
                    assert loaded["source_hash"] == receipt["revision"]["source_hash"]
                    assert loaded["source_origin"] == receipt["revision"]["open_source"]
                    recreated_documents.append({"receipt": receipt, "document": loaded,
                        "scope": "fresh Documents service over same private durable state; not API process restart"})
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, timeout=15)
            Path(SOCKET).unlink(missing_ok=True)
        final = final_record(counters, jobs, app.state._cleanup.closed, not Path(SOCKET).exists())
        final.update(profile=profile_name, allowed_authoring_writes=authoring_writes)
        if manual:
            final.update(allowed_manual_writes=manual_writes, manual_versions=manual_versions,
                         manual_store=final_manual_store)
        if profile_name == "authoring-v1":
            final["recreated_documents"] = recreated_documents
        write("api-final.json", final)
    except BaseException:
        proof["status"] = "failed"
        proof["error"] = traceback.format_exc()
        write("api-proof.json", proof)
        raise


def acceptance(proof):
    cookie = ""
    csrf = ""
    def request(method, path, body=None, expected=200, authenticated=True, with_csrf=True):
        connection = http.client.HTTPConnection("127.0.0.1", 31847, timeout=20)
        connection.sock = socket.socket(socket.AF_UNIX)
        connection.sock.settimeout(20)
        connection.sock.connect(SOCKET)
        headers = {"Host": "127.0.0.1:31847", "Origin": ORIGIN, "Content-Type": "application/json"}
        if authenticated:
            headers["Cookie"] = cookie
        if with_csrf:
            headers["X-CSRF-Token"] = csrf
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        raw = response.read()
        new_cookie = response.getheader("set-cookie", "").split(";", 1)[0]
        proof["http"].append({"method": method, "path": path, "status": response.status})
        assert response.status == expected, (path, response.status, raw[:1000])
        connection.close()
        return json.loads(raw), new_cookie
    request("GET", "/api/editor", expected=401, authenticated=False)
    session, cookie = request("POST", "/api/sessions", {})
    csrf = session["csrf_token"]
    index, _ = request("GET", "/api/editor")
    assert len(index["documents"]) == 1, index["documents"]
    assert not any(index["capabilities"][name] for name in
                   ("generation", "snapshots", "neo4j", "publication_execution"))
    assert index['capabilities']['research_versions'] is (proof.get('profile', 'readonly') == 'manual-research-v1')
    source_id = index["default_document_id"]
    loaded, _ = request("GET", f"/api/editor/documents/{source_id}")
    source = "isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml"
    text = (ROOT / source).read_bytes().decode("utf-8")
    digest = lambda value: hashlib.sha256(value.encode()).hexdigest()
    assert source_id == digest(source)[:32]
    assert loaded["source"] == source and loaded["yaml_text"] == text and loaded["source_hash"] == digest(text)
    view_id = digest(json.dumps([source, text, {}], sort_keys=True))[:32]
    assert loaded["document_id"] == view_id and source_id != view_id
    draft = {"yaml_text": text, "document_id": view_id}
    request("POST", "/api/editor/validate", draft, expected=403, with_csrf=False)
    validation, _ = request("POST", "/api/editor/validate", draft)
    assert validation["valid"] is True and validation == loaded["validation"]
    invalid, _ = request("POST", "/api/editor/validate", {"yaml_text": "unknown_field: true", "document_id": view_id})
    assert invalid["valid"] is False and invalid["errors"]
    schema, _ = request("GET", "/api/editor/schema")
    catalogues, _ = request("GET", "/api/editor/catalogues")
    assert schema["read_only"] and schema["schema"] and catalogues["read_only"]
    jobs, _ = request("GET", "/api/jobs")
    assert jobs["jobs"] == []
    return {"source": source, "yaml_text": text, "document": loaded, "validation_request": draft,
            "source_id": source_id, "view_id": view_id, "source_hash": digest(text), "validation": validation,
            "invalid_validation": invalid, "schema": schema, "catalogues": catalogues, "jobs": jobs["jobs"],
            "session_csrf_verified": True, "capabilities": index["capabilities"]}


if __name__ == "__main__":
    asyncio.run(main())
