#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Disposable real Neo4j checks; self-check is NOT workflow-store acceptance.

Run `python3 scripts/run-workflow-neo4j-checks.py self-check` or `workflow`.
Workflow mode admits only tests/test_environment_workflow_neo4j.py and its
statically discovered local Python imports. No installs, credentials or shell args.
Tests receive ARENA_WORKFLOW_NEO4J_URI and ARENA_WORKFLOW_NEO4J_DATABASE;
auth is None, exclusively inside this ephemeral internal/no-published-port scope.
"""
import argparse
import ast
import hashlib
import json
import os
import signal
import sys
import time
import traceback
import uuid
from pathlib import Path

DB_IMAGE = "sha256:037cf5756f0135cbfd66b739b6df7c7c4bb100f9ce11602f6f9538e17e02c74d"
CLIENT_IMAGE = "sha256:e20b3cc8258b793aaf1fe47c130f54e677fa9c0a6427991cfc1045b743162da5"
TEST = "isaaclab_arena/tests/test_environment_workflow_neo4j.py"
DATABASE = "workflowtest"
URI = "bolt://database:7687"
SELF = "scripts/run-workflow-neo4j-checks.py"


def install_staged_import_guard(root, manifest, namespaces):
    """Resolve repository imports only from the captured closure, including namespaces."""
    import importlib.util
    from importlib.machinery import ModuleSpec

    root = Path(root)
    modules = {}
    packages = set()
    for name in manifest:
        if not name.endswith(".py"):
            continue
        parts = list(Path(name).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
            packages.add(".".join(parts))
        modules[".".join(parts)] = root / name
        packages.update(".".join(parts[:i]) for i in range(1, len(parts)))

    class StagedFinder:
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] not in namespaces:
                return None
            if fullname in modules:
                return importlib.util.spec_from_file_location(
                    fullname,
                    modules[fullname],
                    submodule_search_locations=[str(modules[fullname].parent)] if fullname in packages else None,
                )
            if fullname in packages:
                spec = ModuleSpec(fullname, loader=None, is_package=True)
                spec.submodule_search_locations = [str(root / fullname.replace(".", "/"))]
                return spec
            raise ImportError("Unstaged repository import: " + fullname)

    for name, module in list(sys.modules.items()):
        if name.split(".")[0] in namespaces:
            assert name in modules and getattr(module, "__file__", None) == str(modules[name]), (
                "Preloaded application fallback: " + name
            )
    guard = StagedFinder()
    sys.meta_path.insert(0, guard)
    return guard


def validate_client_proof(proof, mode, junit=None):
    """Validate this runner's contract independently of the unrelated F0 checker."""
    import re
    import xml.etree.ElementTree as ET

    assert proof["status"] == "passed" and proof["mode"] == mode
    assert proof["database"] == DATABASE and proof["uri"] == URI
    assert proof["driver_version"] == "6.2.0"
    assert proof["driver_file"] == "/isaac-sim/kit/python/lib/python3.12/site-packages/neo4j/__init__.py"
    assert proof["server"]["agent"] == "Neo4j/5.26.30"
    assert proof["server"]["protocol_version"] == [5, 8]
    assert re.fullmatch(r"[0-9.]+:7687", proof["server"]["address"])
    assert proof["return_one"] == 1 and proof["driver_closed"] is True
    assert re.fullmatch(r"[a-f0-9]{32}", proof["marker"]["token"])
    assert proof["marker"]["created_read_deleted"] is True and proof["marker"]["remaining"] == 0
    assert proof["suite"] == (TEST if mode == "workflow" else None)
    if mode == "workflow":
        assert junit, "Missing workflow JUnit"
        tree = ET.fromstring(junit)
        cases = list(tree.iter("testcase"))
        assert cases and len(cases) == proof["tests"], "Empty or inconsistent workflow JUnit"
        assert not any(list(case) for case in cases), "Skipped/failed workflow JUnit"
        assert not any(node.tag in ("error", "failure", "skipped") for node in tree.iter())


def inside(mode):
    """Exercise genuine Bolt transport before optionally running the fixed suite."""
    proof = {
        "status": "failed",
        "mode": mode,
        "uri": URI,
        "suite": TEST if mode == "workflow" else None,
        "scope": "real transport self-check, not store acceptance",
    }
    try:
        assert os.getuid() == 1000 and os.statvfs("/").f_flag & os.ST_RDONLY
        assert not any(n.startswith("nvidia") or n == "dri" for n in os.listdir("/dev"))
        import neo4j

        proof.update(driver_version=neo4j.__version__, driver_file=neo4j.__file__, database=DATABASE)
        marker = uuid.uuid4().hex
        with neo4j.GraphDatabase.driver(
            URI, auth=None, connection_timeout=2, connection_acquisition_timeout=3, max_transaction_retry_time=0
        ) as driver:
            deadline = time.monotonic() + 100
            while True:
                try:
                    driver.verify_connectivity()
                    break
                except (neo4j.exceptions.ServiceUnavailable, neo4j.exceptions.SessionExpired):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(1)
            info = driver.get_server_info()
            proof["server"] = {
                "address": str(info.address),
                "agent": info.agent,
                "protocol_version": list(info.protocol_version),
            }
            with driver.session(database=DATABASE) as session:
                proof["return_one"] = session.run("RETURN 1 AS value").single(strict=True)["value"]
                assert proof["return_one"] == 1
                with session.begin_transaction(timeout=15) as tx:
                    tx.run("CREATE (:ArenaDisposableMarker {token: $token})", token=marker).consume()
                    assert (
                        tx.run(
                            "MATCH (n:ArenaDisposableMarker {token: $token}) RETURN n.token AS token", token=marker
                        ).single(strict=True)["token"]
                        == marker
                    )
                    tx.run("MATCH (n:ArenaDisposableMarker {token: $token}) DELETE n", token=marker).consume()
                    tx.commit()
                assert session.run("MATCH (n:ArenaDisposableMarker) RETURN count(n) AS n").single()["n"] == 0
                proof["marker"] = {"token": marker, "created_read_deleted": True, "remaining": 0}
        proof["driver_closed"] = True
        if mode == "workflow":
            os.environ["ARENA_WORKFLOW_NEO4J_URI"] = URI
            os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"] = DATABASE
            sys.path.insert(0, "/source")
            closure = json.loads(Path("/source/closure.json").read_text())
            install_staged_import_guard("/source", closure["files"], closure["namespaces"])
            import pytest

            result = pytest.main([
                "-q",
                "--noconftest",
                "--import-mode=importlib",
                "--rootdir=/source",
                "-p",
                "no:cacheprovider",
                "-o",
                "addopts=",
                "--basetemp=/tmp/pytest",
                "--junitxml=/evidence/pytest.xml",
                "/source/" + TEST,
            ])
            assert result == 0, "Workflow integration suite failed"
            import xml.etree.ElementTree as ET

            cases = list(ET.parse("/evidence/pytest.xml").getroot().iter("testcase"))
            assert cases and not any(list(case) for case in cases), "Empty/skipped/failed suite"
            proof.update(scope="exact workflow integration suite against disposable Neo4j", tests=len(cases))
        proof["status"] = "passed"
    except BaseException:
        proof["error"] = traceback.format_exc()
        raise
    finally:
        Path("/evidence/client-proof.json").write_text(json.dumps(proof, indent=2))
    return 0


def stage_source(root, destination, mode):
    """Capture only fixed entrypoints and their confined static Python closure."""
    from confined_io import ConfinedRoot

    captured = {}
    namespaces = sorted(
        {p.stem if p.suffix == ".py" else p.name for p in root.iterdir() if p.name.isidentifier() or p.suffix == ".py"}
        | {"isaaclab_arena"}
    )
    todo = [SELF] + ([TEST] if mode == "workflow" else [])
    with ConfinedRoot(root) as source:
        while todo:
            name = todo.pop()
            if name in captured:
                continue
            data = source.read(name)
            captured[name] = data
            assert len(captured) <= 128 and sum(map(len, captured.values())) <= 8 * 1024 * 1024
            if name == SELF:
                continue
            path = Path(name)
            package = list(path.parent.parts)
            for i in range(1, len(package) + 1):
                init = "/".join(package[:i]) + "/__init__.py"
                if source.is_file(init):
                    todo.append(init)
            for node in ast.walk(ast.parse(data)):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    base = package[: len(package) - node.level + 1] if node.level else []
                    base += (node.module or "").split(".") if node.module else []
                    modules = [".".join(base)] + [".".join(base + [alias.name]) for alias in node.names]
                for module in modules:
                    if module.split(".")[0] not in namespaces:
                        continue
                    stem = module.replace(".", "/")
                    for candidate in (stem + ".py", stem + "/__init__.py"):
                        if source.is_file(candidate):
                            todo.append(candidate)
    from confined_io import new_destination

    captured["closure.json"] = json.dumps({"files": sorted(captured), "namespaces": namespaces}).encode()
    with new_destination(destination) as output:
        for name, data in captured.items():
            output.write_new(name, data)
    return {name: hashlib.sha256(data).hexdigest() for name, data in captured.items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("self-check", "workflow"))
    options = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "web/arena-workbench/tests/e2e/functional-v7"))
    from confined_io import ConfinedRoot, new_destination, read_confined
    from run import LABEL, OWN_FORMAT, OwnedRun, discover, docker, projection

    token = "arena-neo4j-" + uuid.uuid4().hex
    output = root / "web/arena-workbench/tests/e2e/functional-v7/.runs" / token
    # Validate every ancestor before the first write; never resolve .runs links.
    with ConfinedRoot(output.parent.parent) as parent:
        try:
            parent.validate_directory(".runs")
        except FileNotFoundError:
            with new_destination(output.parent):
                pass
    with new_destination(output) as destination:
        os.mkdir("evidence", mode=0o700, dir_fd=destination.fd)
        with ConfinedRoot(output / "evidence") as evidence:
            os.fchown(evidence.fd, 1000, 1000)
    run = OwnedRun(output, token)
    run.proof.update(
        status="failed",
        mode=options.mode,
        scope="disposable integration only",
        network_name=token,
        network_id=None,
        create_attempts={},
    )
    print(json.dumps({"output": str(output)}), flush=True)
    network_created = False
    previous = {}

    def interrupted(signum, frame):
        raise InterruptedError(f"signal {signum}")

    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, interrupted)
    net_format = projection(
        {"Id": ".Id", "Name": ".Name", "Internal": ".Internal", "Labels": ".Labels", "Containers": ".Containers"}
    )
    try:
        discovery = discover(root, False)
        run.proof["host_root"] = discovery["host_root"]
        for image in (DB_IMAGE, CLIENT_IMAGE):
            assert docker("image", "inspect", "--format", "{{.Id}}", image) == image
        manifest = stage_source(root, output / "source", options.mode)
        run.proof["source_sha256"] = manifest
        host = discovery["host_root"] + "/" + output.relative_to(root).as_posix()
        run.save()
        network_created = True  # Recover ambiguous create by exact intended name + label.
        run.proof["create_attempts"][token] = "attempted"
        run.save()
        nid = docker("network", "create", "--internal", "--label", f"{LABEL}={token}", token)
        run.proof["network_id"] = nid
        run.proof["create_attempts"][token] = "acknowledged"
        run.save()
        net = json.loads(docker("network", "inspect", "--format", net_format, nid))
        assert net["Id"] == nid and net["Internal"] and net["Labels"][LABEL] == token
        run.proof["network"] = net
        for role, image, user, memory, pids in (
            ("db", DB_IMAGE, "7474:7474", "1g", 128),
            ("client", CLIENT_IMAGE, "1000:1000", "768m", 128),
        ):
            name = token + "-" + role
            run.candidates.append(name)
            run.save()
            flags = [
                "create",
                "--pull=never",
                "--name",
                name,
                "--label",
                f"{LABEL}={token}",
                "--network",
                nid,
                "--user",
                user,
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=" + str(pids),
                "--memory=" + memory,
                "--memory-swap=" + memory,
                "--cpus=1",
                "--ipc=private",
                "--shm-size=16m",
                "--no-healthcheck",
                "--log-opt=max-size=1m",
                "--log-opt=max-file=1",
                "--env=NVIDIA_VISIBLE_DEVICES=void",
                "--env=CUDA_VISIBLE_DEVICES=",
            ]
            if role == "db":
                flags += [
                    "--network-alias=database",
                    "--tmpfs=/data:rw,nosuid,nodev,uid=7474,gid=7474,size=268435456",
                    "--tmpfs=/logs:rw,nosuid,nodev,uid=7474,gid=7474,size=33554432",
                    "--env=NEO4J_AUTH=none",
                    "--env=NEO4J_initial_dbms_default__database=" + DATABASE,
                    "--env=NEO4J_server_memory_heap_initial__size=256m",
                    "--env=NEO4J_server_memory_heap_max__size=256m",
                    "--env=NEO4J_server_memory_pagecache_size=128m",
                    "--env=NEO4J_db_tx__log_preallocate=false",
                    "--env=NEO4J_db_tx__log_rotation_size=16m",
                    "--env=NEO4J_db_tx__log_rotation_retention__policy=32M size",
                    "--env=NEO4J_server_http_enabled=false",
                    "--env=NEO4J_server_https_enabled=false",
                ]
                command = [image]
                mounts = []
            else:
                mounts = [
                    f"type=bind,src={host}/source,dst=/source,readonly",
                    f"type=bind,src={host}/evidence,dst=/evidence",
                ]
                flags += [
                    "--read-only",
                    "--group-add=1234",
                    "--workdir=/tmp",
                    "--tmpfs=/tmp:rw,nosuid,nodev,uid=1000,gid=1000,size=134217728",
                    "--entrypoint=/usr/bin/env",
                ]
                for mount in mounts:
                    flags += ["--mount", mount]
                command = [
                    image,
                    "-i",
                    "HOME=/tmp",
                    "PATH=/usr/bin:/bin",
                    "PYTHONDONTWRITEBYTECODE=1",
                    "PYTHONNOUSERSITE=1",
                    "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
                    "NVIDIA_VISIBLE_DEVICES=void",
                    "CUDA_VISIBLE_DEVICES=",
                    "/isaac-sim/python.sh",
                    "/source/" + SELF,
                    "--inside",
                    options.mode,
                ]
            run.proof["create_attempts"][name] = "attempted"
            run.save()
            cid = docker(*flags, *command)
            run.proof["created_ids"][name] = cid
            run.proof["create_attempts"][name] = "acknowledged"
            run.save()
            info = json.loads(docker("inspect", "--format", OWN_FORMAT, cid))
            cfg = info["HostConfig"]
            assert info["Id"] == cid and info["Image"] == image and info["Config"]["User"] == user
            assert info["Config"]["Labels"][LABEL] == token
            assert cfg["NetworkMode"] == nid and not cfg["PortBindings"]
            assert not cfg["Devices"] and not cfg["DeviceRequests"] and not cfg["Privileged"]
            assert cfg["CapDrop"] == ["ALL"] and not cfg["CapAdd"]
            assert "no-new-privileges" in cfg["SecurityOpt"] and cfg["PidsLimit"] == pids
            assert cfg["Memory"] == (1073741824 if role == "db" else 805306368)
            extra = json.loads(
                docker(
                    "inspect",
                    "--format",
                    projection({
                        "NanoCpus": ".HostConfig.NanoCpus",
                        "MemorySwap": ".HostConfig.MemorySwap",
                        "Networks": ".NetworkSettings.Networks",
                    }),
                    cid,
                )
            )
            assert extra["NanoCpus"] == 1000000000 and extra["MemorySwap"] == cfg["Memory"]
            assert set(extra["Networks"]) == {token}
            if role == "client":
                assert cfg["ReadonlyRootfs"] and len(info["Mounts"]) == 2
                assert set(cfg["Tmpfs"]) == {"/tmp"}
                binds = {m["Destination"]: m for m in info["Mounts"] if m["Type"] == "bind"}
                assert set(binds) == {"/source", "/evidence"}
                assert binds["/source"]["Source"] == host + "/source" and not binds["/source"]["RW"]
                assert binds["/evidence"]["Source"] == host + "/evidence" and binds["/evidence"]["RW"]
            else:
                assert not info["Mounts"], "No implicit volumes or host mounts for DB"
                assert set(cfg["Tmpfs"]) == {"/data", "/logs"}
            run.proof["containers"].append(
                {"id": cid, "name": "/" + name, "image": image, "isolation": info, "limits": extra}
            )
            run.proof["verified_isolation"][name] = True
            run.save()
            docker("start", cid)
        deadline = time.monotonic() + 150
        while docker("inspect", "--format", "{{.State.Running}}", cid) == "true":
            assert time.monotonic() < deadline, "Client deadline exceeded"
            time.sleep(0.5)
        assert docker("inspect", "--format", "{{.State.ExitCode}}", cid) == "0", "Client failed; inspect bounded logs"
        proof = json.loads(read_confined(output, "evidence/client-proof.json"))
        validate_client_proof(
            proof, options.mode, read_confined(output, "evidence/pytest.xml") if options.mode == "workflow" else None
        )
        run.proof.update(client=proof, status="passed")
    except BaseException:
        run.proof["error"] = traceback.format_exc()
        print(run.proof["error"], flush=True)
    finally:
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        try:
            clean = run.cleanup()
            if network_created:
                try:
                    found = docker(
                        "network", "ls", "--no-trunc", "--format", "{{.ID}}", "--filter", "name=^" + token + "$"
                    ).splitlines()
                    for identity in found:
                        net = json.loads(docker("network", "inspect", "--format", net_format, identity))
                        assert net["Name"] == token and net["Labels"][LABEL] == token
                        assert run.proof["network_id"] in (None, identity) and not net["Containers"]
                        run.proof["network_id"] = identity
                        docker("network", "rm", identity)
                    assert not docker(
                        "network", "ls", "--no-trunc", "--format", "{{.ID}}", "--filter", "label=" + LABEL + "=" + token
                    )
                    run.proof["network_cleanup_verified"] = run.proof["create_attempts"].get(token) == "acknowledged"
                except BaseException:
                    clean = False
                    run.proof["network_cleanup_error"] = traceback.format_exc()
            for name, digest in run.proof.get("source_sha256", {}).items():
                assert hashlib.sha256(read_confined(output / "source", name)).hexdigest() == digest
            ambiguous = [name for name, state in run.proof["create_attempts"].items() if state != "acknowledged"]
            run.proof["ambiguous_creates"] = ambiguous
            if ambiguous:
                clean = False
                run.proof["cleanup_verification"].update(
                    status="unknown",
                    authoritative=False,
                    recovery_obligation=(
                        "Pending create may complete after empty listings; reconcile exact names and labels"
                    ),
                )
            run.proof["cleanup_verified"] = clean
            if not clean:
                run.proof["status"] = "failed"
            run.save()
            (output / "run-proof.json").write_text(json.dumps(run.proof, indent=2))
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        print(
            json.dumps({
                "status": run.proof["status"],
                "output": str(output),
                "cleanup_verified": run.proof.get("cleanup_verified"),
            }),
            flush=True,
        )
    return 0 if run.proof["status"] == "passed" else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--inside"]:
        assert len(sys.argv) == 3 and sys.argv[2] in ("self-check", "workflow")
        raise SystemExit(inside(sys.argv[2]))
    raise SystemExit(main())
