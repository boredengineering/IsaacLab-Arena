#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Disposable real Neo4j checks; self-check is NOT workflow-store acceptance.

Run `python3 scripts/run-workflow-neo4j-checks.py self-check`, `workflow`,
or exact `workflow-process` (real DB + fixed stdlib child; no SDK/runtime),
or `workflow-scene` (real DB + fixed scene SDK children; synthetic HTTP/capture),
or `workflow-cli` (31 fresh public-module CLI interpreters sharing one disposable
DB/artifact scope: run/status/cancel/resume and required-profile denial checks).
CLI mode is an additive reviewed role: 384-source bound, 31 CLI children, 28
SDK grandchildren (original cohort, active cancellation and unclaimed continuation),
780-second outer collection deadline (600 baseline plus 180 for B1). Every
interpreter repeats kernel/source/preimport checks. No inherited ACTIVE singleton,
application factory injection, native/GPU/live-provider/research-DB access. The
owner-private artifact scope exists until all commands finish, then owned Docker
resources are removed and their exact absence is verified.
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
PROCESS_TEST = "isaaclab_arena/tests/test_environment_workflow_recovery_neo4j.py"
PROCESS_HELPER = "scripts/workflow_process_harness.py"
SCENE_TEST = "isaaclab_arena/tests/test_environment_workflow_scene_worker_neo4j.py"
SCENE_FIXTURE = "web/arena-workbench/tests/e2e/functional-v7/generation_worker_fixture.py"
CLI_TEST = "isaaclab_arena/tests/test_environment_workflow_cli_process_neo4j.py"
PROCESS_MODES = ("workflow-process", "workflow-scene", "workflow-cli")
SCENE_MODES = ("workflow-scene", "workflow-cli")
PROCESS_SOURCE_LIMIT = 320
# Reviewed scene closure: 341 files / 3.1 MiB (SDK/schema/registry plus fixed fixture imports).
# Separate bound; ordinary and stdlib-child cohorts retain their existing limits.
SCENE_SOURCE_LIMIT = 384
FIXTURE = "isaaclab_arena/tests/test_data/minimal_maple_table_env_graph.yaml"


def validate_process_network(net):
    """Require isolated gateway mode: plain internal bridges can reach the host."""
    assert net["Internal"] is True and net["EnableIPv6"] is False
    assert net["Options"].get("com.docker.network.bridge.gateway_mode_ipv4") == "isolated"
    assert not any(item.get("Gateway") for item in net["IPAM"]["Config"])


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
                    submodule_search_locations=([str(modules[fullname].parent)] if fullname in packages else None),
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


def validate_client_proof(proof, mode, junit=None, network_manifest=None):
    """Validate this runner's contract independently of the unrelated F0 checker."""
    import re
    import xml.etree.ElementTree as ET

    assert proof["status"] == "passed" and proof["mode"] == mode
    assert proof["database"] == DATABASE
    expected_uri = ("bolt://" + network_manifest["ip"] + ":7687") if mode in PROCESS_MODES else URI
    assert proof["uri"] == expected_uri
    assert proof["driver_version"] == "6.2.0"
    assert proof["driver_file"] == "/isaac-sim/kit/python/lib/python3.12/site-packages/neo4j/__init__.py"
    assert proof["server"]["agent"] == "Neo4j/5.26.30"
    assert proof["server"]["protocol_version"] == [5, 8]
    assert re.fullmatch(r"[0-9.]+:7687", proof["server"]["address"])
    assert proof["return_one"] == 1 and proof["driver_closed"] is True
    assert re.fullmatch(r"[a-f0-9]{32}", proof["marker"]["token"])
    assert proof["marker"]["created_read_deleted"] is True and proof["marker"]["remaining"] == 0
    assert proof["suite"] == (
        CLI_TEST
        if mode == "workflow-cli"
        else (
            SCENE_TEST
            if mode == "workflow-scene"
            else (PROCESS_TEST if mode == "workflow-process" else TEST if mode == "workflow" else None)
        )
    )
    if mode in PROCESS_MODES:
        assert proof["network_manifest"] == network_manifest
        assert proof["server"]["address"] == network_manifest["ip"] + ":7687"
        assert proof["preimport"]["before_package_imports"] is True
        assert set(proof["preimport"]["kernel_denial"]) == {"2", "10"}
        assert not any(proof["forbidden"].values())
        assert proof["allowed"]["bolt"] > 0 and proof["allowed"]["child_launch"] == (
            31 if mode == "workflow-cli" else 12 if mode == "workflow-scene" else 1
        )
        assert proof["children_verified"] is True
    if mode != "self-check":
        assert junit, "Missing workflow JUnit"
        tree = ET.fromstring(junit)
        cases = list(tree.iter("testcase"))
        assert cases and len(cases) == proof["tests"], "Empty or inconsistent workflow JUnit"
        assert not any(list(case) for case in cases), "Skipped/failed workflow JUnit"
        assert not any(node.tag in ("error", "failure", "skipped") for node in tree.iter())
        if mode == "workflow-cli":
            assert {case.attrib["name"] for case in cases} == {
                "test_fresh_default_module_run_status_and_dependency_denials"
            }
            assert len(cases) == 1 and proof["cli"]["state"] == "accepted"
            assert proof["cli"]["same_database"] and proof["cli"]["owner_retired"]
            assert len(proof["cli"]["commands"]) == 31
        if mode == "workflow-scene":
            assert {case.attrib["name"] for case in cases} == {
                "test_real_scene_refine_committed_fences_and_proposal_guard",
                "test_real_neo4j_foreground_scene_ports_three_stage_trace",
                "test_foreground_application_api_exists",
                *{
                    "test_foreground_application_full_outcome[" + role + "]"
                    for role in (
                        "runtime",
                        "neo4j",
                        "generation_model",
                        "assessment_model",
                        "capture",
                        "gpu",
                        "None",
                        "resume-preflight",
                    )
                },
            }
            assert len(cases) == 11
            assert proof["scene"]["proposal_guarded"] is True
            assert proof["scene_ports"]["state"] == "accepted"
            assert proof["scene_ports"]["owner_retired"] is True
            assert proof["scene_ports"]["stages"] == ["observe", "repair", "observe"]


def inside(mode):
    """Exercise genuine Bolt transport before optionally running the fixed suite."""
    process = mode in PROCESS_MODES
    selected_test = (
        CLI_TEST
        if mode == "workflow-cli"
        else (SCENE_TEST if mode == "workflow-scene" else PROCESS_TEST if process else TEST)
    )
    uri = URI
    guard = None
    proof = {
        "status": "failed",
        "mode": mode,
        "uri": URI,
        "suite": selected_test if mode != "self-check" else None,
        "scope": "real transport self-check, not store acceptance",
    }
    try:
        assert os.getuid() == 1000 and os.statvfs("/").f_flag & os.ST_RDONLY
        assert not any(n.startswith("nvidia") or n == "dri" for n in os.listdir("/dev"))
        if process:
            os.chmod("/tmp", 0o700)
            os.umask(0o077)
            sys.path.insert(0, "/source/scripts")
            import workflow_process_harness as harness

            proof["preimport"] = harness.preflight()
            proof["source_sha256"] = harness.verify_sources(scene=mode in SCENE_MODES)
            assert os.statvfs("/network/manifest.json").f_flag & os.ST_RDONLY
            network_manifest = json.loads(Path("/network/manifest.json").read_text())
            assert set(network_manifest) == {"container_id", "network_id", "ip", "port"}
            assert network_manifest["port"] == 7687
            proof["network_manifest"] = network_manifest
            uri = "bolt://" + network_manifest["ip"] + ":7687"
            proof["uri"] = uri
            if mode in SCENE_MODES:
                metadata = harness.load_scene_metadata()
            guard = harness.Guards(
                network_manifest["ip"],
                scene=mode in SCENE_MODES,
                cli=mode == "workflow-cli",
            )
            harness.ACTIVE = guard
            guard.install()
            if mode in SCENE_MODES:
                proof["metadata"] = harness.replay_scene_metadata(metadata, guard)
            import platform

            platform.processor = lambda: os.uname().machine
            closure = json.loads(Path("/source/closure.json").read_text())
            install_staged_import_guard("/source", closure["files"], closure["namespaces"])
        import neo4j

        proof.update(
            driver_version=neo4j.__version__,
            driver_file=neo4j.__file__,
            database=DATABASE,
        )
        marker = uuid.uuid4().hex
        with neo4j.GraphDatabase.driver(
            uri,
            auth=None,
            connection_timeout=2,
            connection_acquisition_timeout=3,
            max_transaction_retry_time=0,
        ) as driver:
            deadline = time.monotonic() + (45 if process else 100)
            while True:
                try:
                    driver.verify_connectivity()
                    break
                except (
                    neo4j.exceptions.ServiceUnavailable,
                    neo4j.exceptions.SessionExpired,
                ):
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
                            "MATCH (n:ArenaDisposableMarker {token: $token}) RETURN n.token AS token",
                            token=marker,
                        ).single(strict=True)["token"]
                        == marker
                    )
                    tx.run(
                        "MATCH (n:ArenaDisposableMarker {token: $token}) DELETE n",
                        token=marker,
                    ).consume()
                    tx.commit()
                assert session.run("MATCH (n:ArenaDisposableMarker) RETURN count(n) AS n").single()["n"] == 0
                proof["marker"] = {
                    "token": marker,
                    "created_read_deleted": True,
                    "remaining": 0,
                }
        proof["driver_closed"] = True
        if mode != "self-check":
            os.environ["ARENA_WORKFLOW_NEO4J_URI"] = uri
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
                "/source/" + selected_test,
            ])
            assert result == 0, "Workflow integration suite failed"
            import xml.etree.ElementTree as ET

            cases = list(ET.parse("/evidence/pytest.xml").getroot().iter("testcase"))
            assert cases and not any(list(case) for case in cases), "Empty/skipped/failed suite"
            proof.update(
                scope="exact workflow integration suite against disposable Neo4j",
                tests=len(cases),
            )
            if mode == "workflow-cli":
                proof.update(harness.verify_cli_children(guard, proof["source_sha256"]))
            if mode == "workflow-scene":
                proof.update(harness.verify_scene_children(guard, proof["source_sha256"]))
            if mode == "workflow-process":
                recovery = json.loads(Path("/evidence/workflow-recovery.json").read_text())
                assert recovery["fresh_object"] is True and recovery["resend_count"] == 0
                assert recovery["owner_retired"] is True
                for pid in guard.children:
                    child = json.loads(Path(f"/evidence/workflow-child-{pid}.json").read_text())
                    assert child["pid"] == child["pgid"] == child["sid"] == pid
                    assert child["parent_pid"] == os.getpid()
                    assert child["pid"] == recovery["registration"]["pid"]
                    assert child["start_ticks"] == recovery["registration"]["start_ticks"]
                    assert child["pid_namespace"] == os.readlink("/proc/self/ns/pid")
                    assert child["source_sha256"] == proof["source_sha256"]
                    assert not any(child["forbidden"].values()) and not any(child["allowed"].values())
                    assert child["preimport"]["before_package_imports"] is True
                    assert not Path(f"/proc/{pid}").exists(), "Owned child not reaped"
                assert len(guard.children) == 1 and not any(guard.forbidden.values())
                assert "openai" not in sys.modules, "SDK not admitted in this fixture cohort"
                proof.update(
                    children_verified=True,
                    scope=(
                        "real Neo4j + owned stdlib fixture producer + actual schema with fixture registry + fresh"
                        " recovery object; no SDK/generation/runtime"
                    ),
                )
        proof["status"] = "passed"
    except BaseException:
        proof["error"] = traceback.format_exc()
        raise
    finally:
        if guard is not None:
            proof.update(forbidden=guard.forbidden, allowed=guard.allowed)
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
    if mode in PROCESS_MODES:
        todo += [
            (CLI_TEST if mode == "workflow-cli" else SCENE_TEST if mode == "workflow-scene" else PROCESS_TEST),
            PROCESS_HELPER,
            FIXTURE,
        ]
        if mode in SCENE_MODES:
            todo += [
                SCENE_TEST,
                SCENE_FIXTURE,
                "web/arena-workbench/tests/e2e/functional-v7/api.py",
                "web/arena-workbench/tests/e2e/functional-v7/confined_io.py",
                "isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml",
            ]
    with ConfinedRoot(root) as source:
        while todo:
            name = todo.pop()
            if name in captured:
                continue
            data = source.read(name)
            captured[name] = data
            assert len(captured) <= (
                SCENE_SOURCE_LIMIT if mode in SCENE_MODES else PROCESS_SOURCE_LIMIT if mode in PROCESS_MODES else 128
            )
            assert sum(map(len, captured.values())) <= 8 * 1024 * 1024
            if name == SELF or not name.endswith(".py"):
                continue
            path = Path(name)
            package = list(path.parent.parts)
            for i in range(1, len(package) + 1):
                init = "/".join(package[:i]) + "/__init__.py"
                if source.is_file(init):
                    todo.append(init)
            tree = ast.parse(data)
            if mode in PROCESS_MODES:
                # Runtime imports never execute TYPE_CHECKING branches. Keep the
                # old cohort's deliberately conservative closure unchanged.
                class RuntimeImports(ast.NodeTransformer):
                    def visit_FunctionDef(self, node):
                        omitted = {
                            PROCESS_HELPER: {"scene_child"},
                            "isaaclab_arena/assets/registries.py": {"ensure_assets_registered"},
                            "isaaclab_arena_examples/agentic_environment_generation/web_api/generation_worker.py": {
                                "main"
                            },
                        }
                        # This cohort uses a fixed registry and stdlib producer,
                        # never these runtime entrypoints. Missing imports fail
                        # closed through the staged finder (no ambient fallback).
                        if mode == "workflow-process" and node.name in omitted.get(name, set()):
                            return []
                        return self.generic_visit(node)

                    def visit_If(self, node):
                        if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                            return []
                        return self.generic_visit(node)

                tree = RuntimeImports().visit(tree)
            for node in ast.walk(tree):
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
    if mode in PROCESS_MODES:
        captured["source-manifest.json"] = json.dumps(
            {name: hashlib.sha256(data).hexdigest() for name, data in captured.items()}
        ).encode()
    if mode in PROCESS_MODES:
        assert len(captured) <= (SCENE_SOURCE_LIMIT if mode in SCENE_MODES else PROCESS_SOURCE_LIMIT)
        assert sum(map(len, captured.values())) <= 8 * 1024 * 1024
    with new_destination(destination) as output:
        for name, data in captured.items():
            output.write_new(name, data)
    return {name: hashlib.sha256(data).hexdigest() for name, data in captured.items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=(
            "self-check",
            "workflow",
            "workflow-process",
            "workflow-scene",
            "workflow-cli",
        ),
    )
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
    net_format = projection({
        "Id": ".Id",
        "Name": ".Name",
        "Internal": ".Internal",
        "Labels": ".Labels",
        "Containers": ".Containers",
    })
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
        network_flags = (
            ["--opt", "com.docker.network.bridge.gateway_mode_ipv4=isolated"] if options.mode in PROCESS_MODES else []
        )
        nid = docker(
            "network",
            "create",
            "--internal",
            *network_flags,
            "--label",
            f"{LABEL}={token}",
            token,
        )
        run.proof["network_id"] = nid
        run.proof["create_attempts"][token] = "acknowledged"
        run.save()
        net = json.loads(docker("network", "inspect", "--format", net_format, nid))
        assert net["Id"] == nid and net["Internal"] and net["Labels"][LABEL] == token
        if options.mode in PROCESS_MODES:
            detailed = json.loads(docker("network", "inspect", nid))[0]
            validate_process_network(detailed)
            run.proof["isolated_network"] = detailed
        run.proof["network"] = net
        # Scene parent + SDK children reuse F0's 4 GiB / 256 PID resource cap.
        # The stdlib-child cap cannot hold two immutable Torch/SDK import trees.
        # CPU, egress, namespace, read-only, per-child alarm/deadlines stay pinned.
        for role, image, user, memory, pids in (
            ("db", DB_IMAGE, "7474:7474", "1g", 128),
            (
                "client",
                CLIENT_IMAGE,
                "1000:1000",
                "4g" if options.mode in SCENE_MODES else "768m",
                256 if options.mode in SCENE_MODES else 128,
            ),
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
                if options.mode in PROCESS_MODES:
                    flags += [
                        "--read-only",
                        "--tmpfs=/tmp:rw,nosuid,nodev,exec,uid=7474,gid=7474,size=33554432",
                        "--tmpfs=/var/lib/neo4j/conf:rw,nosuid,nodev,uid=7474,gid=7474,size=1048576",
                        "--tmpfs=/var/lib/neo4j/run:rw,nosuid,nodev,uid=7474,gid=7474,size=1048576",
                    ]
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
                if options.mode in PROCESS_MODES:
                    mounts.append(f"type=bind,src={host}/network,dst=/network,readonly")
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
            assert cfg["Memory"] == (
                1073741824 if role == "db" else 4294967296 if options.mode in SCENE_MODES else 805306368
            )
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
                assert cfg["ReadonlyRootfs"] and len(info["Mounts"]) == (3 if options.mode in PROCESS_MODES else 2)
                assert set(cfg["Tmpfs"]) == {"/tmp"}
                binds = {m["Destination"]: m for m in info["Mounts"] if m["Type"] == "bind"}
                assert set(binds) == (
                    {"/source", "/evidence", "/network"} if options.mode in PROCESS_MODES else {"/source", "/evidence"}
                )
                if options.mode in PROCESS_MODES:
                    assert binds["/network"]["Source"] == host + "/network" and not binds["/network"]["RW"]
                assert binds["/source"]["Source"] == host + "/source" and not binds["/source"]["RW"]
                assert binds["/evidence"]["Source"] == host + "/evidence" and binds["/evidence"]["RW"]
            else:
                assert not info["Mounts"], "No implicit volumes or host mounts for DB"
                assert set(cfg["Tmpfs"]) == (
                    {
                        "/data",
                        "/logs",
                        "/tmp",
                        "/var/lib/neo4j/conf",
                        "/var/lib/neo4j/run",
                    }
                    if options.mode in PROCESS_MODES
                    else {"/data", "/logs"}
                )
                if options.mode in PROCESS_MODES:
                    assert cfg["ReadonlyRootfs"]
            run.proof["containers"].append({
                "id": cid,
                "name": "/" + name,
                "image": image,
                "isolation": info,
                "limits": extra,
            })
            run.proof["verified_isolation"][name] = True
            run.save()
            docker("start", cid)
            if role == "db" and options.mode in PROCESS_MODES:
                import ipaddress

                owned_net = json.loads(docker("inspect", "--format", "{{json .NetworkSettings.Networks}}", cid))
                assert set(owned_net) == {token}
                endpoint = owned_net[token]
                assert endpoint["NetworkID"] == nid and not endpoint["Gateway"] and not endpoint["IPv6Gateway"]
                db_ip = str(ipaddress.IPv4Address(endpoint["IPAddress"]))
                network_manifest = dict(container_id=cid, network_id=nid, ip=db_ip, port=7687)
                with new_destination(output / "network") as destination:
                    destination.write_new("manifest.json", json.dumps(network_manifest).encode())
                run.proof["network_manifest"] = network_manifest
                run.save()
        deadline = time.monotonic() + (
            780 if options.mode == "workflow-cli" else 240 if options.mode == "workflow-scene" else 150
        )
        while docker("inspect", "--format", "{{.State.Running}}", cid) == "true":
            assert time.monotonic() < deadline, "Client deadline exceeded"
            time.sleep(0.5)
        assert docker("inspect", "--format", "{{.State.ExitCode}}", cid) == "0", "Client failed; inspect bounded logs"
        proof = json.loads(read_confined(output, "evidence/client-proof.json"))
        validate_client_proof(
            proof,
            options.mode,
            (read_confined(output, "evidence/pytest.xml") if options.mode != "self-check" else None),
            network_manifest=run.proof.get("network_manifest"),
        )
        run.proof.update(client=proof, status="passed")
    except BaseException:
        run.proof["error"] = traceback.format_exc()
        if options.mode in PROCESS_MODES:
            run.proof["owned_logs"] = {}
            for name, identity in run.proof["created_ids"].items():
                try:
                    run.proof["owned_logs"][name] = docker("logs", "--tail=60", identity)
                except Exception:
                    run.proof["owned_logs"][name] = "log capture unavailable"
        print(run.proof["error"], flush=True)
    finally:
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        try:
            clean = run.cleanup()
            if network_created:
                try:
                    found = docker(
                        "network",
                        "ls",
                        "--no-trunc",
                        "--format",
                        "{{.ID}}",
                        "--filter",
                        "name=^" + token + "$",
                    ).splitlines()
                    for identity in found:
                        net = json.loads(docker("network", "inspect", "--format", net_format, identity))
                        assert net["Name"] == token and net["Labels"][LABEL] == token
                        assert run.proof["network_id"] in (None, identity) and not net["Containers"]
                        run.proof["network_id"] = identity
                        docker("network", "rm", identity)
                    assert not docker(
                        "network",
                        "ls",
                        "--no-trunc",
                        "--format",
                        "{{.ID}}",
                        "--filter",
                        "label=" + LABEL + "=" + token,
                    )
                    run.proof["network_cleanup_verified"] = run.proof["create_attempts"].get(token) == "acknowledged"
                except BaseException:
                    clean = False
                    run.proof["network_cleanup_error"] = traceback.format_exc()
            for name, digest in run.proof.get("source_sha256", {}).items():
                assert hashlib.sha256(read_confined(output / "source", name)).hexdigest() == digest
            if "network_manifest" in run.proof:
                assert json.loads(read_confined(output, "network/manifest.json")) == run.proof["network_manifest"]
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
        assert len(sys.argv) == 3 and sys.argv[2] in (
            "self-check",
            "workflow",
            "workflow-process",
            "workflow-scene",
            "workflow-cli",
        )
        raise SystemExit(inside(sys.argv[2]))
    raise SystemExit(main())
