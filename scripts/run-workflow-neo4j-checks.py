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
The explicit workflow-graphql-execution E0 slice admits only two installed
configuration setup interpreters; it deliberately grants no owner/SDK effects.
Read its captured installed-execution/admission.md before independent review
and first invocation. Configuration acceptance is not workflow execution.
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
GRAPHQL_TEST = "isaaclab_arena/tests/test_environment_workflow_graphql_neo4j.py"
GRAPHQL_NETWORK_TEST = "isaaclab_arena/tests/test_environment_workflow_graphql_network_neo4j.py"
GRAPHQL_MODES = ("workflow-graphql", "workflow-graphql-network")
EXECUTION_MODE = "workflow-graphql-execution"
EXECUTION_TEST = "isaaclab_arena/tests/test_environment_workflow_graphql_execution_neo4j.py"
EXECUTION_HELPER = "scripts/workflow_graphql_execution_harness.py"
EXECUTION_SPEC = "outputs/workflow/plan04-implementation/installed-execution/admission.md"
EXECUTION_SOURCE_LIMIT = 96
JOIN_MODE = "workflow-graphql-execution-joined"
JOIN_HELPER = "scripts/workflow_graphql_execution_join_harness.py"
JOIN_TEST = "isaaclab_arena/tests/test_environment_workflow_graphql_execution_joined_neo4j.py"
JOIN_INVENTORY = "outputs/workflow/plan04-implementation/installed-execution/join-source-files.json"
JOIN_SOURCE_LIMIT = 383
LIFECYCLE_MODE = "workflow-graphql-execution-lifecycle"
LIFECYCLE_HELPER = "scripts/workflow_graphql_execution_lifecycle_harness.py"
LIFECYCLE_TEST = "isaaclab_arena/tests/test_environment_workflow_execution_lifecycle.py"
LIFECYCLE_SPEC = "outputs/workflow/plan04-implementation/installed-execution/lifecycle-spec.md"
LIFECYCLE_INVENTORY = "outputs/workflow/plan04-implementation/installed-execution/lifecycle-source-files.json"
LIFECYCLE_ARCHIVE = "outputs/workflow/plan04-implementation/installed-execution/correction-round1-preimage/execution_owner.py"
LIFECYCLE_ARCHIVE_SHA256 = "3d1ff06c7ee5ff08df5430cee4784ba9f753375fc1fe17bb366929d98fa31e67"
LIFECYCLE_SOURCE_LIMIT = 339  # 335 measured repository leaves + four generated.
LIFECYCLE_ROOTS = (
    SELF, PROCESS_HELPER, LIFECYCLE_HELPER, LIFECYCLE_TEST, LIFECYCLE_SPEC,
    LIFECYCLE_INVENTORY, LIFECYCLE_ARCHIVE,
    "isaaclab_arena/agentic_environment_generation/workflow/api/execution_owner.py",
    "isaaclab_arena/agentic_environment_generation/workflow/api/execution_schema.py",
)
LIFECYCLE_CASES = (
    "test_execution_server_observation_does_not_cancel_unresolved_cleanup[timeout]",
    "test_execution_server_observation_does_not_cancel_unresolved_cleanup[cleanup_error]",
    "test_execution_stop_precedes_blocked_admission_drain",
    "test_historical_owner_fails_stop_before_blocked_admission_drain",
    "test_execution_cleanup_timeout_is_sticky_and_retains_area",
    "test_execution_stop_while_authenticated_body_and_query_are_pending",
    "test_execution_cleanup_error_is_observable_and_never_releases_area",
)
GRAPHQL_BOOTSTRAP_MODES = (*GRAPHQL_MODES, EXECUTION_MODE, JOIN_MODE, LIFECYCLE_MODE)
BOLT_MODES = (*PROCESS_MODES, *GRAPHQL_BOOTSTRAP_MODES)
GRAPHQL_SOURCE_LIMIT = 128
# Separately measured query network closure; no SDK/native imports.
GRAPHQL_NETWORK_SOURCE_LIMIT = 96
GRAPHQL_IMAGE = "sha256:b94e17024f1e123ac5a42759ab56651a18823fda7c701e765cba31f200154cdd"
GRAPHQL_MANIFEST_SHA256 = "03764536ed54c1f59cbf46305c5bc4ba618e2dc1deeeac7ffdfb21a0dffbf810"
PROCESS_SOURCE_LIMIT = 320
# Reviewed scene closure: 341 files / 3.1 MiB (SDK/schema/registry plus fixed fixture imports).
# Separate bound; ordinary and stdlib-child cohorts retain their existing limits.
SCENE_SOURCE_LIMIT = 384
FIXTURE = "isaaclab_arena/tests/test_data/minimal_maple_table_env_graph.yaml"


def select_graphql_runtime(discovered, image, manifest, *, command=None):
    """Validate the exact approved pair before any owned resource creation."""
    from run import select_runtime
    from confined_io import read_confined

    assert image and manifest, "Explicit paired GraphQL image/manifest required"
    assert image == GRAPHQL_IMAGE, "Unapproved query image"
    path = Path(manifest).absolute()
    raw = read_confined(path.parent, path.name)
    assert hashlib.sha256(raw).hexdigest() == GRAPHQL_MANIFEST_SHA256, "Unapproved query manifest"
    command_kwargs = {} if command is None else {"command": command}
    return select_runtime(discovered, image, path, profile="graphql-test-v1", **command_kwargs)


def validate_join_historical_metadata(root):
    """Bind E1's fixed replay to actual historical bytes, never a fresh probe."""
    from confined_io import read_confined

    fixture = "outputs/workflow/plan04-implementation/installed-execution/join-git-metadata.json"
    historical = "outputs/workflow/plan03-implementation/application-extraction/workflow-scene/client-proof.json"
    expected = "47c532a8fb9fad1b3c847432e8d5415d0b6a0a39632204bfc25c7065345aa2a0"
    raw = read_confined(root, fixture)
    assert len(raw) <= 4096
    value = json.loads(raw)
    assert set(value) == {"source", "source_sha256", "stdout", "returncode", "scope"}
    assert value["source"] == historical and value["source_sha256"] == expected
    assert value["scope"] == "historical actual immutable-image Git metadata replay, not a fresh E1 Git version probe"
    original = read_confined(root, historical)
    assert len(original) <= 4 * 1024 * 1024
    assert hashlib.sha256(original).hexdigest() == expected, "Historical Git evidence changed"
    metadata = json.loads(original)["metadata"]
    assert type(value["returncode"]) is type(metadata["returncode"]) is int
    assert value["returncode"] == metadata["returncode"] == 0
    assert type(value["stdout"]) is str and value["stdout"] == metadata["stdout"]
    assert value["stdout"] == "git version 2.43.0\n"
    return dict(fixture=fixture, fixture_sha256=hashlib.sha256(raw).hexdigest(),
                source=historical, source_sha256=expected, projection_verified=True,
                scope="historical metadata compatibility only; not fresh executable version attestation")


def graphql_probe_source(root):
    """Reuse the accepted verifier functions unchanged, with this cohort's preflight."""
    import importlib.util
    from check_proof import GRAPHQL_CLOSURE_SHA256
    from confined_io import read_confined

    spec = importlib.util.spec_from_file_location("query_provisioner", root / "scripts/provision-functional-runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw = read_confined(root, "outputs/workflow/plan03-implementation/graphql-provisioning/discovery/closure-input.json")
    assert hashlib.sha256(raw).hexdigest() == GRAPHQL_CLOSURE_SHA256
    code = module.graphql_import_code("/isaac-sim/kit/python/lib/python3.12/site-packages", json.loads(raw), GRAPHQL_IMAGE, "unused")
    tree = ast.parse(code)
    nodes = []
    constants = {"PATHS", "ALLOWED", "BINDINGS", "CLOSURE", "INCIDENTAL"}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {"physical_file", "check_imports"}:
            nodes.append(ast.get_source_segment(code, node))
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in node.targets):
            nodes.append(ast.get_source_segment(code, node))
    assert len(nodes) == 7
    return ("import os, sys, json, hashlib\n" + "\n".join(nodes)).encode()


_GRAPHQL_PROBE = None


def graphql_imports(preimport, guard):
    """Witness real framework imports before repository code under query denial."""
    global _GRAPHQL_PROBE
    namespace = {}
    exec(compile(Path("/source/graphql-import-check.py").read_bytes(), "/source/graphql-import-check.py", "exec"), namespace)
    paths = namespace["PATHS"]
    assert sys.flags.isolated == sys.flags.no_site == sys.flags.ignore_environment == 1
    assert sys.path == ["/source/scripts", *paths[:3]]
    sys.path[:] = paths
    sys.dont_write_bytecode = True
    profile = json.loads(Path("/source/graphql-profile.json").read_text())
    before = dict(guard.forbidden)
    result = dict(schema_version=1, status="failed", image=GRAPHQL_IMAGE,
                  scope="query cohort actual framework imports, not the application response",
                  recipe_sha256=profile["recipe_sha256"], interpreter="/isaac-sim/python.sh",
                  executable=sys.executable, python_version=list(sys.version_info[:3]),
                  sys_path=list(sys.path), uid=os.getuid(), errno=preimport["kernel_denial"]["2"],
                  egress_denied=True, before_package_imports=True, distributions={}, modules={}, loaded_modules={})
    namespace["result"] = result
    namespace["check_imports"]()
    assert before == guard.forbidden
    result["forbidden"] = {"network": guard.forbidden["network"], "subprocess": guard.forbidden["subprocess"],
                           "blocked_import": guard.forbidden.get("blocked_import", 0)}
    _GRAPHQL_PROBE = namespace
    return result


def graphql_runtime_modules():
    """Record additional executed immutable files separately from the closed probe."""
    rows = {}
    for name, module in sorted(list(sys.modules.items())):
        origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if not origin or origin in ("built-in", "frozen") or origin.startswith("/source/"):
            continue
        if any(origin.startswith(p + "/") for p in _GRAPHQL_PROBE["ALLOWED"]):
            _, row = _GRAPHQL_PROBE["physical_file"](origin, _GRAPHQL_PROBE["ALLOWED"])
            rows[name] = dict(row, origin=origin)
        else:
            assert any(origin.startswith(p + "/") for p in _GRAPHQL_PROBE["PATHS"][:3]), "Unrecorded runtime origin"
    return rows


def graphql_runtime_metadata(modules):
    """Additional observed test/driver dependencies, not a new metadata closure claim."""
    import importlib.metadata
    baseline = _GRAPHQL_PROBE["result"]["loaded_modules"]
    extras = sorted({n.split(".")[0] for n in modules} - {n.split(".")[0] for n in baseline})
    names = {"_pytest": "pytest", "py": "pytest"}
    result = {}
    for root in extras:
        name = names.get(root, root)
        distribution = importlib.metadata.distribution(name)
        _, witness = _GRAPHQL_PROBE["physical_file"](str(distribution._path) + "/METADATA", _GRAPHQL_PROBE["ALLOWED"])
        result[root] = dict(distribution=name, version=distribution.version, metadata=witness)
    return result


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
    expected_uri = ("bolt://" + network_manifest["ip"] + ":7687") if mode in BOLT_MODES else URI
    assert proof["uri"] == expected_uri
    assert proof["driver_version"] == "6.2.0"
    assert proof["driver_file"] == "/isaac-sim/kit/python/lib/python3.12/site-packages/neo4j/__init__.py"
    assert proof["server"]["agent"] == "Neo4j/5.26.30"
    assert proof["server"]["protocol_version"] == [5, 8]
    assert re.fullmatch(r"[0-9.]+:7687", proof["server"]["address"])
    assert proof["return_one"] == 1 and proof["driver_closed"] is True
    assert re.fullmatch(r"[a-f0-9]{32}", proof["marker"]["token"])
    assert proof["marker"]["created_read_deleted"] is True and proof["marker"]["remaining"] == 0
    assert proof["suite"] == (LIFECYCLE_TEST if mode == LIFECYCLE_MODE else JOIN_TEST if mode == JOIN_MODE else EXECUTION_TEST if mode == EXECUTION_MODE else GRAPHQL_NETWORK_TEST if mode == "workflow-graphql-network" else GRAPHQL_TEST if mode == "workflow-graphql" else (
        CLI_TEST
        if mode == "workflow-cli"
        else (
            SCENE_TEST
            if mode == "workflow-scene"
            else (PROCESS_TEST if mode == "workflow-process" else TEST if mode == "workflow" else None)
        )
    )
    )
    if mode == JOIN_MODE:
        assert proof["network_manifest"] == network_manifest
        assert proof["children_verified"] is True and not proof["missing_process_witnesses"]
        assert len(proof["joined_processes"]) == 17
        assert proof["allowed"]["child_launch"] == 12 and proof["allowed"]["bolt"] > 0
        assert not any(proof["forbidden"].values())
        assert proof["preimport"]["before_package_imports"] is True
    if mode in ("workflow-graphql", LIFECYCLE_MODE):
        assert proof["network_manifest"] == network_manifest
        assert proof["allowed"]["child_launch"] == 0 and proof["allowed"]["bolt"] > 0
        assert not any(proof["forbidden"].values())
        assert proof["preimport"]["before_package_imports"] is True
        assert proof["no_children"] is True
    if mode == LIFECYCLE_MODE:
        assert network_manifest is not None
        assert set(proof["preimport"]["kernel_denial"]) == {"2", "10"}
        assert proof["server"]["address"] == network_manifest["ip"] + ":7687"
        detail = proof["lifecycle"]
        assert detail["historical_owner_sha256"] == LIFECYCLE_ARCHIVE_SHA256
        assert detail["test_effects_denied"] is True
        assert detail["installed_active_worker_shutdown_proven"] is False
        assert set(detail["blocked_admission"]) == {"current", "historical"}
        for kind, observation in detail["blocked_admission"].items():
            assert set(observation) == {"admission_entered", "close_pending", "refused", "area_retained", "stop_before_release", "closed_after_release"}
            assert all(value is True for name, value in observation.items() if name != "stop_before_release")
            assert observation["stop_before_release"] is (kind == "current")
    if mode == EXECUTION_MODE:
        assert proof["network_manifest"] == network_manifest
        assert proof["children_verified"] is True
        assert len(proof["execution_admission_processes"]) == 2
        assert all(row["returncode"] == 0 for row in proof["execution_admission_processes"])
        assert all(row["loader_events"] == [{"event": "call"}, {"event": "return", "accepted": True}]
                   for row in proof["execution_admission_processes"])
        assert proof["allowed"]["child_launch"] == 2 and proof["allowed"]["bolt"] > 0
        assert not any(proof["forbidden"].values())
        assert proof["preimport"]["before_package_imports"] is True
    if mode == "workflow-graphql-network":
        assert proof["network_manifest"] == network_manifest
        assert proof["children_verified"] is True and len(proof["network_processes"]) == 23 and len(proof["network_servers"]) == 3
        assert not any(proof["forbidden"].values())
        assert proof["allowed"]["child_launch"] == 23 and proof["allowed"]["bolt"] > 0
        assert proof["preimport"]["before_package_imports"] is True
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
        if mode == LIFECYCLE_MODE:
            assert len(cases) == len(LIFECYCLE_CASES)
            assert {case.attrib["name"] for case in cases} == set(LIFECYCLE_CASES)
        if mode == JOIN_MODE:
            assert len(cases) == 1 and cases[0].attrib["name"] == "test_installed_execution_survives_submit_exit"
        if mode == EXECUTION_MODE:
            assert len(cases) == 1 and cases[0].attrib["name"] == "test_fresh_installed_execution_configuration_admission"
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
    process = mode in BOLT_MODES
    query_only = mode in GRAPHQL_BOOTSTRAP_MODES
    selected_test = (
        CLI_TEST
        if mode == "workflow-cli"
        else (SCENE_TEST if mode == "workflow-scene" else PROCESS_TEST if process else TEST)
    )
    if query_only:
        selected_test = GRAPHQL_NETWORK_TEST if mode == "workflow-graphql-network" else GRAPHQL_TEST
    if mode == EXECUTION_MODE:
        selected_test = EXECUTION_TEST
    if mode == JOIN_MODE:
        selected_test = JOIN_TEST
    if mode == LIFECYCLE_MODE:
        selected_test = LIFECYCLE_TEST
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
            if mode == LIFECYCLE_MODE:
                import workflow_graphql_execution_lifecycle_harness as lifecycle

                proof["source_sha256"] = lifecycle.verify_sources()
            elif mode == EXECUTION_MODE:
                import workflow_graphql_execution_harness as execution_harness

                proof["source_sha256"] = execution_harness.verify_sources()
            elif mode == JOIN_MODE:
                import workflow_graphql_execution_join_harness as joined

                proof["source_sha256"] = joined.verify_sources()
            else:
                proof["source_sha256"] = harness.verify_sources(scene=mode in SCENE_MODES, query_only=query_only, network=mode == "workflow-graphql-network")
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
                query_only=query_only,
            )
            if mode == "workflow-graphql-network":
                from workflow_graphql_network_harness import NetworkGuards

                guard = NetworkGuards("harness", network_manifest["ip"])
            if mode == EXECUTION_MODE:
                guard = execution_harness.ExecutionAdmissionGuards("harness", network_manifest["ip"])
            if mode == JOIN_MODE:
                guard = joined.JoinGuards("harness", network_manifest["ip"])
                joined.ACTIVE = guard
            harness.ACTIVE = guard
            guard.install()
            if query_only:
                proof["imports"] = graphql_imports(proof["preimport"], guard)
            if mode == JOIN_MODE:
                sys.path.insert(0, "/source/scripts")
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
        if mode == LIFECYCLE_MODE:
            lifecycle_before = lifecycle.begin_tests(guard)
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
            if mode == EXECUTION_MODE:
                # Retain completed interpreter evidence even on application assertion RED.
                proof.update(execution_harness.verify_children(guard, proof["source_sha256"]))
            if mode == JOIN_MODE:
                proof.update(joined.verify_children(guard, proof["source_sha256"], positive=result == 0))
            assert result == 0, "Workflow integration suite failed"
            if mode == LIFECYCLE_MODE:
                proof.update(lifecycle.finish_tests(guard, lifecycle_before, proof["source_sha256"]))
            import xml.etree.ElementTree as ET

            cases = list(ET.parse("/evidence/pytest.xml").getroot().iter("testcase"))
            assert cases and not any(list(case) for case in cases), "Empty/skipped/failed suite"
            proof.update(
                scope="exact workflow integration suite against disposable Neo4j",
                tests=len(cases),
            )
            if mode == LIFECYCLE_MODE:
                proof["scope"] = "in-process real-owner/ASGI lifecycle with inert external ports; Bolt self-check only"
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
        if query_only:
            assert guard.fixed_spec is None
            if mode == "workflow-graphql-network":
                from workflow_graphql_network_harness import verify_children

                proof.update(verify_children(guard, proof["source_sha256"]))
            elif mode not in (EXECUTION_MODE, JOIN_MODE):
                assert not guard.children
                proof["no_children"] = True
            proof["runtime_modules"] = graphql_runtime_modules()
            proof["additional_runtime_metadata"] = graphql_runtime_metadata(proof["runtime_modules"])
        proof["status"] = "passed"
    except BaseException:
        proof["error"] = traceback.format_exc()
        raise
    finally:
        if guard is not None:
            proof.update(forbidden=guard.forbidden, allowed=guard.allowed)
        Path("/evidence/client-proof.json").write_text(json.dumps(proof, indent=2))
    return 0


def stage_source(root, destination, mode, *, provision=None):
    """Capture only fixed entrypoints and their confined static Python closure."""
    from confined_io import ConfinedRoot

    captured = {}
    namespaces = sorted(
        {p.stem if p.suffix == ".py" else p.name for p in root.iterdir() if p.name.isidentifier() or p.suffix == ".py"}
        | {"isaaclab_arena"}
    )
    todo = [SELF] + ([TEST] if mode == "workflow" else [])
    if mode == INITIALIZATION_MODE:
        from confined_io import read_confined

        inventory = json.loads(read_confined(root, INITIALIZATION_INVENTORY))
        assert type(inventory) is list and len(inventory) == len(set(inventory)) == INITIALIZATION_SOURCE_LIMIT - 4
        assert SELF in inventory and JOIN_HELPER in inventory and INITIALIZATION_TEST in inventory
        todo += inventory
    if mode == LIFECYCLE_MODE:
        from confined_io import read_confined

        inventory = json.loads(read_confined(root, LIFECYCLE_INVENTORY))
        assert type(inventory) is list and len(inventory) == len(set(inventory)) == LIFECYCLE_SOURCE_LIMIT - 4
        todo += LIFECYCLE_ROOTS
    if mode == EXECUTION_MODE:
        todo += [EXECUTION_TEST, EXECUTION_HELPER, EXECUTION_SPEC, PROCESS_HELPER,
                 "isaaclab_arena/agentic_environment_generation/workflow/cli.py"]
    if mode == JOIN_MODE:
        inventory = json.loads((root / JOIN_INVENTORY).read_text())
        assert type(inventory) is list and len(inventory) == len(set(inventory)) == JOIN_SOURCE_LIMIT - 4
        todo += inventory
    if mode in GRAPHQL_MODES:
        todo += [GRAPHQL_NETWORK_TEST if mode == "workflow-graphql-network" else GRAPHQL_TEST, PROCESS_HELPER]
        if mode == "workflow-graphql-network":
            todo.append("scripts/workflow_graphql_network_harness.py")
        todo += sorted(str(p.relative_to(root)) for p in (root / "isaaclab_arena/tests/test_data/workflow_graphql").glob("*.graphql"))
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
                INITIALIZATION_SOURCE_LIMIT if mode == INITIALIZATION_MODE else LIFECYCLE_SOURCE_LIMIT if mode == LIFECYCLE_MODE else JOIN_SOURCE_LIMIT if mode == JOIN_MODE else EXECUTION_SOURCE_LIMIT if mode == EXECUTION_MODE else SCENE_SOURCE_LIMIT if mode in SCENE_MODES else PROCESS_SOURCE_LIMIT if mode in PROCESS_MODES else GRAPHQL_NETWORK_SOURCE_LIMIT if mode == "workflow-graphql-network" else GRAPHQL_SOURCE_LIMIT if mode == "workflow-graphql" else 128
            )
            assert sum(map(len, captured.values())) <= 8 * 1024 * 1024
            if name == SELF or not name.endswith(".py"):
                continue
            path = Path(name)
            package = list(path.parent.parts)
            if mode == LIFECYCLE_MODE and name == LIFECYCLE_ARCHIVE:
                assert hashlib.sha256(data).hexdigest() == LIFECYCLE_ARCHIVE_SHA256
                # Resolve the fixed loader's actual relative imports, not outputs/.
                package = "isaaclab_arena/agentic_environment_generation/workflow/api".split("/")
            for i in range(1, len(package) + 1):
                init = "/".join(package[:i]) + "/__init__.py"
                if source.is_file(init):
                    todo.append(init)
            tree = ast.parse(data)
            if mode in BOLT_MODES or mode == INITIALIZATION_MODE:
                # Runtime imports never execute TYPE_CHECKING branches. Keep the
                # old cohort's deliberately conservative closure unchanged.
                class RuntimeImports(ast.NodeTransformer):
                    def visit_FunctionDef(self, node):
                        if (mode in GRAPHQL_BOOTSTRAP_MODES or mode == INITIALIZATION_MODE) and name == PROCESS_HELPER and node.name in {
                            "child", "scene_child", "cli_child", "load_scene_metadata", "replay_scene_metadata",
                            "verify_scene_children", "verify_cli_children"
                        }:
                            return []
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

    if mode == EXECUTION_MODE:
        literals = [node.value for node in ast.parse(captured[EXECUTION_HELPER]).body
                    if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "SOURCE_FILES" for target in node.targets)]
        assert len(literals) == 1
        exact_files = ast.literal_eval(literals[0])
        assert type(exact_files) is tuple and all(type(name) is str for name in exact_files)
        assert len(exact_files) == len(set(exact_files))
        assert set(captured) == set(exact_files), "E0 source inventory changed; fresh admission review required"
    if mode == JOIN_MODE:
        assert set(captured) == set(inventory), "E1 source closure changed; fresh exact inventory review required"
    if mode == LIFECYCLE_MODE:
        assert set(captured) == set(inventory), "Lifecycle source closure changed; fresh exact inventory review required"
    if mode == INITIALIZATION_MODE:
        assert set(captured) == set(inventory), "S2 source closure changed; fresh exact inventory review required"
    if mode in GRAPHQL_BOOTSTRAP_MODES or mode == INITIALIZATION_MODE:
        assert provision is not None
        captured["graphql-import-check.py"] = graphql_probe_source(root)
        captured["graphql-profile.json"] = json.dumps({"recipe_sha256": provision["recipe_sha256"]}).encode()
    captured["closure.json"] = json.dumps({"files": sorted(captured), "namespaces": namespaces}).encode()
    if mode in BOLT_MODES or mode == INITIALIZATION_MODE:
        captured["source-manifest.json"] = json.dumps(
            {name: hashlib.sha256(data).hexdigest() for name, data in captured.items()}
        ).encode()
    if mode in PROCESS_MODES:
        assert len(captured) <= (SCENE_SOURCE_LIMIT if mode in SCENE_MODES else PROCESS_SOURCE_LIMIT)
        assert sum(map(len, captured.values())) <= 8 * 1024 * 1024
    if mode == EXECUTION_MODE:
        assert len(captured) <= EXECUTION_SOURCE_LIMIT
        assert sum(map(len, captured.values())) <= 8 * 1024 * 1024
    if mode == JOIN_MODE:
        assert len(captured) == JOIN_SOURCE_LIMIT
        assert len(captured["source-manifest.json"]) <= 65536
        assert sum(map(len, captured.values())) <= 8 * 1024 * 1024
    if mode == LIFECYCLE_MODE:
        assert len(captured) == LIFECYCLE_SOURCE_LIMIT
        assert len(captured["source-manifest.json"]) <= 65536
        assert sum(map(len, captured.values())) <= 8 * 1024 * 1024
    if mode == INITIALIZATION_MODE:
        assert len(captured) == INITIALIZATION_SOURCE_LIMIT
        assert len(captured["source-manifest.json"]) <= 65536
        assert sum(map(len, captured.values())) <= 8 * 1024 * 1024
    with new_destination(destination) as output:
        for name, data in captured.items():
            output.write_new(name, data)
    return {name: hashlib.sha256(data).hexdigest() for name, data in captured.items()}


INITIALIZATION_MODE = "workflow-graphql-initialization"
INITIALIZATION_CASES = ("positive", "failure", "timeout")
INITIALIZATION_TEST = "isaaclab_arena/tests/test_environment_workflow_initialization_neo4j.py"
INITIALIZATION_INVENTORY = "outputs/workflow/plan04-implementation/s2-initialization/source-files.json"
INITIALIZATION_SOURCE_LIMIT = 385  # 381 measured repository leaves plus four generated.


def initialization_validate_options(mode, case):
    """Reject misplaced or absent case selection before any discovery or writes."""
    if mode == INITIALIZATION_MODE:
        if case not in INITIALIZATION_CASES:
            raise ValueError("S2 requires an explicit positive|failure|timeout case")
    elif case is not None:
        raise ValueError("--initialization-case is exclusive to " + INITIALIZATION_MODE)


class InitializationClock:
    """Use one pre-discovery work deadline and one nonrenewable cleanup reserve."""

    def __init__(self, monotonic):
        self.monotonic = monotonic
        self.work_deadline = monotonic() + 300
        self.cleanup_deadline = None

    def begin_cleanup(self):
        if self.cleanup_deadline is None:
            self.cleanup_deadline = self.monotonic() + 120

    def timeout(self, ceiling=45):
        deadline = self.work_deadline if self.cleanup_deadline is None else self.cleanup_deadline
        remaining = deadline - self.monotonic()
        if remaining <= 0:
            raise TimeoutError("S2 aggregate deadline exhausted; cleanup may be unknown")
        return min(45, ceiling, remaining)


class InitializationCommand:
    """Stream Docker pipes under one clock, retaining no unbounded output."""

    def __init__(self, clock, *, popen=None, selector=None, read=None, set_blocking=None, killpg=None,
                 pidfd_open=None, pidfd_signal=None, close=None):
        import selectors
        import subprocess

        self.clock = clock
        self.popen = popen or subprocess.Popen
        self.selector = selector or selectors.DefaultSelector
        self.read = read or os.read
        self.set_blocking = set_blocking or os.set_blocking
        self.killpg = killpg or os.killpg
        self.pidfd_open = pidfd_open or os.pidfd_open
        self.pidfd_signal = pidfd_signal or signal.pidfd_send_signal
        self.close = close or os.close
        self.last = None
        self.reap_unknown = False

    def _stream(self, args, stdout_limit):
        import selectors
        import subprocess

        assert not self.reap_unknown or self.clock.cleanup_deadline is not None, "S2 command reap unknown; work closed"
        self.last = None
        budget = self.clock.timeout()
        if budget <= 5:
            raise TimeoutError("S2 command cannot reserve bounded group reap time")
        deadline = self.clock.monotonic() + budget - 5
        selected = self.selector()
        try:
            process = self.popen(["docker", *args], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        except BaseException:
            selected.close()
            raise
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        limits = {"stdout": stdout_limit, "stderr": 65536}
        group_fd = None
        try:
            # Linux retained group reference prevents signalling a recycled
            # numeric PGID after wait() has reaped the Docker CLI leader.
            group_fd = self.pidfd_open(process.pid, 0)
            for name in buffers:
                stream = getattr(process, name)
                self.set_blocking(stream.fileno(), False)
                selected.register(stream, selectors.EVENT_READ, name)
            while selected.get_map():
                remaining = deadline - self.clock.monotonic()
                if remaining <= 0:
                    raise TimeoutError("S2 Docker command deadline exceeded")
                for key, _ in selected.select(min(0.1, remaining)):
                    name = key.data
                    try:
                        chunk = self.read(key.fileobj.fileno(), min(65536, limits[name] - len(buffers[name]) + 1))
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selected.unregister(key.fileobj)
                    elif len(buffers[name]) + len(chunk) > limits[name]:
                        raise RuntimeError("S2 Docker " + name + " overflow")
                    else:
                        buffers[name].extend(chunk)
            remaining = deadline - self.clock.monotonic()
            if remaining <= 0:
                raise TimeoutError("S2 Docker command deadline exceeded")
            code = process.wait(timeout=min(5, remaining))
            if code:
                raise RuntimeError("S2 Docker command failed: " + str(code))
            try:
                self.pidfd_signal(group_fd, 0, None, 4)
            except ProcessLookupError:
                pass
            else:
                raise RuntimeError("S2 Docker CLI group survived its leader")
            return bytes(buffers["stdout"]), bytes(buffers["stderr"])
        except BaseException:
            # Kill the exact newly-owned session even when its leader has exited;
            # descendants can otherwise retain a pipe indefinitely.
            try:
                if group_fd is None:
                    # No wait/poll has occurred if acquiring the pidfd failed;
                    # our unreaped Popen child still reserves this numeric PID.
                    self.killpg(process.pid, signal.SIGKILL)
                else:
                    self.pidfd_signal(group_fd, signal.SIGKILL, None, 4)
            except ProcessLookupError:
                pass
            except BaseException:
                self.reap_unknown = True
            try:
                reap_timeout = 5
                if self.clock.cleanup_deadline is not None:
                    reap_timeout = min(5, max(0, self.clock.cleanup_deadline - self.clock.monotonic()))
                process.wait(timeout=reap_timeout)
                if group_fd is not None:
                    try:
                        self.pidfd_signal(group_fd, 0, None, 4)
                    except ProcessLookupError:
                        pass
                    else:
                        self.reap_unknown = True
                else:
                    self.reap_unknown = True
            except BaseException:
                self.reap_unknown = True
            raise
        finally:
            self.last = {"operation": args[0], "stdout": bytes(buffers["stdout"]),
                         "stderr": bytes(buffers["stderr"]), "returncode": process.returncode,
                         "reap_unknown": self.reap_unknown}
            selected.close()
            process.stdout.close()
            process.stderr.close()
            if group_fd is not None:
                self.close(group_fd)

    def __call__(self, *args):
        out, err = self._stream(args, 4 * 1024 * 1024 - (65536 if args[0] == "logs" else 0))
        return (out + (err if args[0] == "logs" else b"")).decode("utf-8").strip()

    def archive(self, identity, path):
        import re

        assert re.fullmatch(r"[a-f0-9]{64}", identity)
        assert path in ("/evidence", "/evidence/collection-ready")
        limit = 36 * 1024 * 1024 if path == "/evidence" else 65536
        return self._stream(("cp", identity + ":" + path, "-"), limit)[0]


def initialization_client_flags(host, network):
    """Build only the S2 client's fixed quota and read-only mount controls."""
    import re

    assert network == "none" or re.fullmatch(r"[a-f0-9]{64}", network)
    assert type(host) is str and host.startswith("/") and "," not in host
    assert ".." not in host.split("/")
    flags = [
        "--network=" + network, "--read-only", "--user=1000:1000", "--group-add=1234",
        "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=256",
        "--memory=4g", "--memory-swap=4g", "--cpus=1", "--ipc=private", "--shm-size=16m",
        "--no-healthcheck", "--log-opt=max-size=1m", "--log-opt=max-file=1", "--workdir=/tmp",
        "--env=NVIDIA_VISIBLE_DEVICES=void", "--env=CUDA_VISIBLE_DEVICES=",
        "--tmpfs=/tmp:rw,nosuid,nodev,uid=1000,gid=1000,mode=0700,size=134217728",
        "--tmpfs=/evidence:rw,nosuid,nodev,noexec,uid=1000,gid=1000,mode=0700,size=33554432",
        "--mount", f"type=bind,src={host}/source,dst=/source,readonly",
    ]
    if network != "none":
        flags += ["--mount", f"type=bind,src={host}/network,dst=/network,readonly"]
    return flags


def initialization_archive(payload, allowed):
    """Validate an already stream-bounded Docker tar without extracting paths."""
    import io
    import re
    import tarfile

    assert type(payload) is bytes and len(payload) <= 36 * 1024 * 1024, "S2 archive overflow"
    assert len(payload) >= 1024 and len(payload) % 512 == 0 and payload[-1024:] == bytes(1024), "Incomplete S2 tar"
    assert type(allowed) is frozenset and len(allowed) <= 55
    assert all(type(name) is str and re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,127}", name) for name in allowed)
    files = {}
    root_seen = False
    total = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        for entry in archive:
            assert not entry.linkname and not entry.pax_headers and entry.sparse is None
            if entry.name in ("evidence", "evidence/"):
                assert entry.isdir() and not root_seen and entry.size == 0
                root_seen = True
                continue
            parts = entry.name.split("/")
            assert len(parts) == 2 and parts[0] == "evidence", "Unsafe evidence archive path"
            name = parts[1]
            assert name in allowed and name not in files and len(files) < 55
            assert entry.isreg() and 0 <= entry.size <= 4 * 1024 * 1024
            total += entry.size
            assert total <= 32 * 1024 * 1024, "S2 evidence aggregate overflow"
            stream = archive.extractfile(entry)
            assert stream is not None
            with stream:
                raw = stream.read(entry.size + 1)
            assert len(raw) == entry.size
            files[name] = raw
        assert payload[archive.offset:] == bytes(len(payload) - archive.offset), "Trailing S2 archive data"
    return files


def initialization_archive_names(payload, case, evidence_names):
    """Derive PID leaves only from the actual bounded proof in this same archive."""
    import io
    import tarfile

    assert type(payload) is bytes and len(payload) <= 36 * 1024 * 1024
    proof = None
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        for index, entry in enumerate(archive):
            assert index < 56, "S2 evidence entry count"
            if entry.name == "evidence/client-proof.json":
                assert proof is None and entry.isreg() and not entry.linkname and not entry.pax_headers
                assert entry.sparse is None and 0 < entry.size <= 4 * 1024 * 1024
                raw = archive.extractfile(entry).read(entry.size + 1)
                assert len(raw) == entry.size
                proof = json.loads(raw)
                assert type(proof) is dict
    names = evidence_names(case, proof)
    assert type(names) in (set, frozenset)
    return frozenset(names) | {"initialization-error.json"}


def initialization_marker(payload, case):
    """Read only the bounded single regular marker member, never extract it."""
    import io
    import tarfile

    assert len(payload) <= 65536
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        entries = list(archive)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.name == "collection-ready" and entry.isreg() and entry.size <= 32
        assert not entry.linkname and not entry.pax_headers and entry.sparse is None
        assert archive.extractfile(entry).read(33) == (case + "\n").encode()


def initialization_collect(command, identity, case, allowed, clock, *, sleep=time.sleep):
    """Poll at most thirty times, then collect exactly one live tmpfs archive."""
    ready = False
    for attempt in range(30):
        clock.timeout()
        assert command("inspect", "--format", "{{.State.Running}}", identity) == "true", "S2 collector exited"
        try:
            payload = command.archive(identity, "/evidence/collection-ready")
        except RuntimeError:
            # A missing marker is the only retryable Docker error. Other failures
            # are retained by the command transport; no general command retry.
            last = getattr(command, "last", None)
            if last is not None:
                assert last["returncode"] not in (None, 0)
                assert b"Could not find the file" in last["stderr"], "S2 marker command failed"
        else:
            initialization_marker(payload, case)
            ready = True
            break
        if attempt < 29:
            assert clock.timeout(2) == 2, "S2 collection deadline exhausted"
            sleep(2)
    # Even missing-readiness failures get one bounded partial-evidence attempt.
    clock.timeout()
    assert command("inspect", "--format", "{{.State.Running}}", identity) == "true", "S2 tmpfs lost"
    payload = command.archive(identity, "/evidence")
    files = initialization_archive(payload, allowed(payload) if callable(allowed) else allowed)
    assert command("inspect", "--format", "{{.State.Running}}", identity) == "true", "S2 collector died during copy"
    if not ready:
        # The caller can retain actual partial leaves without certifying them.
        error = RuntimeError("S2 collection marker absent after thirty checks")
        error.evidence_files = files
        raise error
    return files


def initialization_verify_container(info, extra, identity, name, token, label, host, network, role):
    """Reject any difference from S2's actual inspected kernel resource profile."""
    assert role in {"client", "db"}
    cfg = info["HostConfig"]
    assert info["Id"] == identity and info["Name"] == "/" + name
    assert info["Image"] == (GRAPHQL_IMAGE if role == "client" else DB_IMAGE)
    assert info["Config"]["Labels"][label] == token
    assert info["Config"]["User"] == ("1000:1000" if role == "client" else "7474:7474")
    assert cfg["NetworkMode"] == network and cfg["ReadonlyRootfs"] is True
    assert not cfg["PortBindings"] and not cfg["Devices"] and not cfg["DeviceRequests"] and not cfg["Privileged"]
    assert cfg["CapDrop"] == ["ALL"] and not cfg["CapAdd"] and "no-new-privileges" in cfg["SecurityOpt"]
    assert not cfg["Binds"] and not cfg["VolumesFrom"] and cfg["IpcMode"] == "private"
    assert cfg["PidMode"] in ("", None) and cfg["UsernsMode"] in ("", None)
    assert cfg["PidsLimit"] == (256 if role == "client" else 128)
    assert cfg["Memory"] == (4294967296 if role == "client" else 1073741824)
    assert extra["MemorySwap"] == cfg["Memory"] and extra["NanoCpus"] == 1000000000
    assert extra["ShmSize"] == 16777216 and not extra["PublishAllPorts"]
    assert extra["GroupAdd"] == (["1234"] if role == "client" else None)
    assert extra["RestartPolicy"] == {"Name": "no", "MaximumRetryCount": 0}
    expected = ({"/tmp": (134217728, "1000", "1000"), "/evidence": (33554432, "1000", "1000")}
                if role == "client" else {"/tmp": (33554432, "7474", "7474"),
                    "/var/lib/neo4j/conf": (1048576, "7474", "7474"),
                    "/var/lib/neo4j/run": (1048576, "7474", "7474"),
                    "/data": (268435456, "7474", "7474"), "/logs": (33554432, "7474", "7474")})
    assert set(cfg["Tmpfs"]) == set(expected)
    for path, (size, uid, gid) in expected.items():
        options = cfg["Tmpfs"][path].split(",")
        assert {"rw", "nosuid", "nodev", "uid=" + uid, "gid=" + gid, "size=" + str(size)} <= set(options)
        assert len(options) == len(set(options))
        if role == "client":
            assert "mode=0700" in options
            assert set(options) == {"rw", "nosuid", "nodev", "uid=" + uid, "gid=" + gid,
                                   "size=" + str(size), "mode=0700"} | ({"noexec"} if path == "/evidence" else set())
        else:
            assert set(options) == {"rw", "nosuid", "nodev", "uid=" + uid, "gid=" + gid,
                                   "size=" + str(size)} | ({"exec"} if path == "/tmp" else set())
    mounts = info["Mounts"]
    paths = ({"/source"} | ({"/network"} if network != "none" else set())) if role == "client" else set()
    assert len(mounts) == len(paths)
    assert {row["Destination"] for row in mounts} == paths
    for row in mounts:
        assert row["Type"] == "bind" and row["RW"] is False
        assert row["Source"] == host + row["Destination"]
    expected_network = "none" if network == "none" else token
    assert set(extra["Networks"]) == {expected_network}
    for endpoint in extra["Networks"].values():
        assert not endpoint.get("Gateway") and not endpoint.get("IPv6Gateway") and not endpoint.get("GlobalIPv6Address")
        if network != "none":
            assert endpoint["NetworkID"] in ("", network)  # Empty only before Docker start.


def initialization_cleanup(run, clock, network, label):
    """Reuse OwnedRun transport within one separate aggregate cleanup reserve."""
    clock.begin_cleanup()
    clean = False
    try:
        clean = run.cleanup()
    except BaseException as error:
        run.proof["container_cleanup_error"] = str(error)[:4096]
    try:
        if network is not None:
            command = run.command
            found = command("network", "ls", "--no-trunc", "--format", "{{.ID}}",
                            "--filter", "name=^" + run.token + "$").splitlines()
            for identity in found:
                projection = ('{"Id":{{json .Id}},"Name":{{json .Name}},"Internal":{{json .Internal}},'
                              '"Label":{{json (index .Labels "' + label + '")}},"Containers":{{json .Containers}}}')
                info = json.loads(command("network", "inspect", "--format", projection, identity))
                assert info["Id"] == identity and info["Name"] == run.token and info["Label"] == run.token
                assert info["Internal"] and not info["Containers"]
                assert run.proof.get("network_id") in (None, identity)
                command("network", "rm", identity)
            for selector in ("name=^" + run.token + "$", "label=" + label + "=" + run.token):
                assert not command("network", "ls", "--no-trunc", "--format", "{{.ID}}", "--filter", selector)
            run.proof["network_cleanup_verified"] = run.proof["create_attempts"].get(run.token) == "acknowledged"
            clean = clean and run.proof["network_cleanup_verified"]
        clock.timeout()
    except BaseException as error:
        clean = False
        run.proof["cleanup_error"] = str(error)[:4096]
    ambiguous = [name for name, state in run.proof["create_attempts"].items() if state != "acknowledged"]
    run.proof["ambiguous_creates"] = ambiguous
    if ambiguous or getattr(getattr(run, "command", None), "reap_unknown", False) or not clean:
        clean = False
        run.proof["cleanup_verification"] = dict(status="unknown", authoritative=False,
            recovery_obligation="Reconcile exact owned names/labels; timed out creates may appear after empty listings")
    run.proof["cleanup_verified"] = clean
    run.save()
    return clean


def initialization_inside_entry(case):
    """Dispatch S2 before legacy DB self-check and hold its live quotaed evidence."""
    assert case in INITIALIZATION_CASES
    deadline = time.monotonic() + 300
    assert os.getuid() == 1000 and os.statvfs("/").f_flag & os.ST_RDONLY
    assert not any(name.startswith("nvidia") or name == "dri" for name in os.listdir("/dev"))
    sys.path.insert(0, "/source/scripts")
    import workflow_graphql_execution_join_harness as helper

    os.umask(0o077)
    try:
        proof = helper.initialization_inside(case)
        raw = json.dumps(proof, sort_keys=True).encode()
        assert len(raw) <= 4 * 1024 * 1024
        # The producer owns client-proof.json; demand exact readback, never
        # overwrite actual failure evidence with a synthesized success record.
        with open("/evidence/client-proof.json", "rb") as stream:
            saved = stream.read(4 * 1024 * 1024 + 1)
        assert len(saved) <= 4 * 1024 * 1024 and json.loads(saved) == proof
    except BaseException as error:
        raw = json.dumps({"status": "failed", "case": case, "error_type": type(error).__name__,
                          "error": str(error)[:8192]}).encode()
        with open("/evidence/initialization-error.json", "xb") as stream:
            stream.write(raw)
    with open("/evidence/collection-ready", "xb") as stream:
        stream.write((case + "\n").encode())
    while time.monotonic() < deadline:
        time.sleep(max(0, min(1, deadline - time.monotonic())))
    return 1  # Expired collection is never a successful stopped-tmpfs result.


def initialization_host_contract(root):
    """Load only the fixed stdlib proof-reader definitions, never package code."""
    from confined_io import read_confined

    raw = read_confined(root, JOIN_HELPER)
    names = {"initialization_origin", "initialization_verify_proof", "initialization_evidence_names"}
    nodes = [node for node in ast.parse(raw).body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in nodes} == names, "S2 producer/reader contract incomplete"
    assert all(not node.decorator_list and not node.args.kw_defaults for node in nodes)
    assert all(all(isinstance(default, ast.Constant) and default.value is None for default in node.args.defaults) for node in nodes)
    namespace = {"__builtins__": __builtins__}
    constants = [node for node in ast.parse(raw).body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "INITIALIZATION_ROLES" for target in node.targets)]
    assert len(constants) == 1
    namespace["INITIALIZATION_ROLES"] = ast.literal_eval(constants[0].value)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), JOIN_HELPER, "exec"), namespace)
    namespace["_source_sha256"] = hashlib.sha256(raw).hexdigest()
    return namespace


def initialization_run(options):
    """Execute only S2's owned resources; admission remains in initialization_main."""
    import ipaddress
    import re

    clock = InitializationClock(time.monotonic)  # Starts before even discovery.
    command = InitializationCommand(clock)
    case = options.initialization_case
    initialization_validate_options(INITIALIZATION_MODE, case)
    root = Path(__file__).absolute().parents[1]
    sys.path.insert(0, str(root / "web/arena-workbench/tests/e2e/functional-v7"))
    from confined_io import ConfinedRoot, new_destination, read_confined
    from run import LABEL, OWN_FORMAT, OwnedRun, discover, projection

    contract = initialization_host_contract(root)
    fixed_names = contract["initialization_evidence_names"](case)
    assert type(fixed_names) in (set, frozenset) and len(fixed_names) <= 54
    assert {"client-proof.json", "pytest.xml", "collection-ready"} <= fixed_names

    def allowed(payload):
        return initialization_archive_names(payload, case, contract["initialization_evidence_names"])
    token = "arena-s2-init-" + uuid.uuid4().hex
    output = root / "outputs/workflow/plan04-implementation/s2-initialization/runs" / token
    with ConfinedRoot(output.parent.parent) as parent:
        try:
            parent.validate_directory("runs")
        except FileNotFoundError:
            with new_destination(output.parent):
                pass
    with new_destination(output):
        pass
    run = OwnedRun(output, token, command=command)
    run.proof.update(status="failed", mode=INITIALIZATION_MODE, case=case, create_attempts={},
                     network_id=None, work_deadline=clock.work_deadline,
                     graphql_provision_manifest_sha256=GRAPHQL_MANIFEST_SHA256)
    network = None
    files = None
    accepted = False
    previous = {}

    def interrupted(signum, frame):
        raise InterruptedError("S2 signal " + str(signum))

    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, interrupted)
    try:
        discovery = discover(root, False, command=command)
        discovery = select_graphql_runtime(discovery, options.runtime_image, options.provision_manifest, command=command)
        assert discovery["selected_runtime_image"] == GRAPHQL_IMAGE
        for image in (DB_IMAGE, GRAPHQL_IMAGE):
            assert command("image", "inspect", "--format", "{{.Id}}", image) == image
        clock.timeout()
        manifest = stage_source(root, output / "source", INITIALIZATION_MODE, provision=discovery["provision"])
        clock.timeout()
        assert manifest[JOIN_HELPER] == contract["_source_sha256"], "S2 proof-reader source changed during staging"
        run.proof["source_sha256"] = manifest
        host = discovery["host_root"] + "/" + output.relative_to(root).as_posix()
        run.proof["host_root"] = discovery["host_root"]
        run.save()
        if case != "positive":
            network = token  # Set before an ambiguous daemon create.
            run.proof["create_attempts"][token] = "attempted"
            run.save()
            nid = command("network", "create", "--internal", "--ipv6=false", "--opt",
                          "com.docker.network.bridge.gateway_mode_ipv4=isolated", "--label", LABEL + "=" + token, token)
            run.proof["network_id"] = nid
            assert re.fullmatch(r"[a-f0-9]{64}", nid)
            run.proof["create_attempts"][token] = "acknowledged"
            run.save()
            network = nid
            net = json.loads(command("network", "inspect", nid))[0]
            assert net["Id"] == nid and net["Name"] == token and net["Labels"][LABEL] == token
            assert not net["Containers"]
            validate_process_network(net)
            run.proof["isolated_network"] = net
        for role in (("client",) if case == "positive" else ("db", "client")):
            clock.timeout()
            name = token + "-" + role
            run.candidates.append(name)
            run.proof["create_attempts"][name] = "attempted"
            run.save()
            flags = ["create", "--pull=never", "--name", name, "--label", LABEL + "=" + token]
            if role == "client":
                flags += initialization_client_flags(host, network or "none")
                flags += ["--entrypoint=/usr/bin/env", GRAPHQL_IMAGE, "-i", "HOME=/tmp", "PATH=/usr/bin:/bin",
                          "PYTHONDONTWRITEBYTECODE=1", "PYTHONNOUSERSITE=1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
                          "NVIDIA_VISIBLE_DEVICES=void", "CUDA_VISIBLE_DEVICES=", "OPENBLAS_NUM_THREADS=1",
                          "OMP_NUM_THREADS=1", "MKL_NUM_THREADS=1", "/isaac-sim/python.sh", "-I", "-S", "-B",
                          "/source/" + SELF, "--inside", INITIALIZATION_MODE, case]
            else:
                flags += ["--network=" + network, "--read-only", "--user=7474:7474", "--cap-drop=ALL",
                          "--security-opt=no-new-privileges", "--pids-limit=128", "--memory=1g", "--memory-swap=1g",
                          "--cpus=1", "--ipc=private", "--shm-size=16m", "--no-healthcheck",
                          "--log-opt=max-size=1m", "--log-opt=max-file=1", "--network-alias=database",
                          "--env=NVIDIA_VISIBLE_DEVICES=void", "--env=CUDA_VISIBLE_DEVICES=",
                          "--tmpfs=/tmp:rw,nosuid,nodev,exec,uid=7474,gid=7474,size=33554432",
                          "--tmpfs=/var/lib/neo4j/conf:rw,nosuid,nodev,uid=7474,gid=7474,size=1048576",
                          "--tmpfs=/var/lib/neo4j/run:rw,nosuid,nodev,uid=7474,gid=7474,size=1048576",
                          "--tmpfs=/data:rw,nosuid,nodev,uid=7474,gid=7474,size=268435456",
                          "--tmpfs=/logs:rw,nosuid,nodev,uid=7474,gid=7474,size=33554432",
                          "--env=NEO4J_AUTH=none", "--env=NEO4J_initial_dbms_default__database=" + DATABASE,
                          "--env=NEO4J_server_memory_heap_initial__size=256m", "--env=NEO4J_server_memory_heap_max__size=256m",
                          "--env=NEO4J_server_memory_pagecache_size=128m", "--env=NEO4J_db_tx__log_preallocate=false",
                          "--env=NEO4J_db_tx__log_rotation_size=16m", "--env=NEO4J_db_tx__log_rotation_retention__policy=32M size",
                          "--env=NEO4J_server_http_enabled=false", "--env=NEO4J_server_https_enabled=false", DB_IMAGE]
            identity = command(*flags)
            run.proof["created_ids"][name] = identity
            assert re.fullmatch(r"[a-f0-9]{64}", identity)
            run.proof["create_attempts"][name] = "acknowledged"
            run.save()
            extra_format = projection({"NanoCpus": ".HostConfig.NanoCpus", "MemorySwap": ".HostConfig.MemorySwap",
                                       "ShmSize": ".HostConfig.ShmSize", "GroupAdd": ".HostConfig.GroupAdd",
                                       "PublishAllPorts": ".HostConfig.PublishAllPorts", "RestartPolicy": ".HostConfig.RestartPolicy",
                                       "Networks": ".NetworkSettings.Networks"})
            info = json.loads(command("inspect", "--format", OWN_FORMAT, identity))
            extra = json.loads(command("inspect", "--format", extra_format, identity))
            initialization_verify_container(info, extra, identity, name, token, LABEL, host, network or "none", role)
            run.proof["containers"].append(dict(id=identity, name="/" + name, image=info["Image"], isolation=info, limits=extra))
            run.proof["verified_isolation"][name] = True
            run.save()
            command("start", identity)
            extra = json.loads(command("inspect", "--format", extra_format, identity))
            initialization_verify_container(info, extra, identity, name, token, LABEL, host, network or "none", role)
            if network is not None:
                endpoint = extra["Networks"][token]
                assert endpoint["NetworkID"] == network
                assert not endpoint["Gateway"] and not endpoint["IPv6Gateway"]
                if role == "db":
                    binding = dict(container_id=identity, network_id=network,
                                   ip=str(ipaddress.IPv4Address(endpoint["IPAddress"])), port=7687)
                    with new_destination(output / "network") as destination:
                        destination.write_new("manifest.json", json.dumps(binding).encode())
                    run.proof["network_manifest"] = binding
                    run.save()
        try:
            files = initialization_collect(command, identity, case, allowed, clock)
        except BaseException as error:
            files = getattr(error, "evidence_files", None)
            raise
        finally:
            if files is not None:
                with new_destination(output / "evidence") as destination:
                    for name, raw in sorted(files.items()):
                        clock.timeout()
                        destination.write_new(name, raw)
                run.proof["evidence_sha256"] = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
        proof = json.loads(read_confined(output / "evidence", "client-proof.json"))
        junit = read_confined(output / "evidence", "pytest.xml")
        assert contract["initialization_verify_proof"](proof, junit, case) is True
        assert proof["source_sha256"] == {name: digest for name, digest in manifest.items() if name != "source-manifest.json"}
        assert read_confined(output / "evidence", "collection-ready") == (case + "\n").encode()
        for name, digest in manifest.items():
            clock.timeout()
            assert hashlib.sha256(read_confined(output / "source", name)).hexdigest() == digest
            if name not in {"closure.json", "source-manifest.json", "graphql-import-check.py", "graphql-profile.json"}:
                assert hashlib.sha256(read_confined(root, name)).hexdigest() == digest, "S2 source changed"
        clock.timeout()
        run.proof["client"] = proof
        accepted = True
    except BaseException as error:
        run.proof["error"] = {"type": type(error).__name__, "message": str(error)[:8192]}
        if command.last is not None:
            run.proof["last_command"] = {key: value for key, value in command.last.items() if key not in {"stdout", "stderr"}}
            run.proof["last_command"]["stdout_retained_bytes"] = min(len(command.last["stdout"]), 4 * 1024 * 1024)
            run.proof["last_command"]["stdout_observed_bytes"] = len(command.last["stdout"])
            with ConfinedRoot(output) as destination:
                destination.write_new("command-stdout.bin", command.last["stdout"][:4 * 1024 * 1024])
                destination.write_new("command-stderr.bin", command.last["stderr"])
    finally:
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        try:
            clean = initialization_cleanup(run, clock, network, LABEL)
            run.proof["status"] = "passed" if accepted and clean else "failed"
            run.proof["cleanup_deadline"] = clock.cleanup_deadline
            run.save()
            with ConfinedRoot(output) as destination:
                destination.write_new("run-proof.json", json.dumps(run.proof, indent=2).encode())
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    print(json.dumps({"output": str(output), "status": run.proof["status"], "cleanup_verified": run.proof["cleanup_verified"]}))
    return 0 if run.proof["status"] == "passed" else 1


def initialization_main(options):
    """Refuse further attempts until the tmpfs evidence transport is amended."""
    raise RuntimeError(
        "S2 execution closed: Docker cp does not support tmpfs evidence; "
        "a reviewed collection-protocol amendment is required before another attempt"
    )


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
            "workflow-graphql",
            "workflow-graphql-network",
            EXECUTION_MODE,
            JOIN_MODE,
            LIFECYCLE_MODE,
            INITIALIZATION_MODE,
        ),
        # Lifecycle is explicit; no default, legacy case or launch limit changes.
    )
    parser.add_argument("--runtime-image")
    parser.add_argument("--provision-manifest", type=Path)
    parser.add_argument("--initialization-case", choices=INITIALIZATION_CASES)
    options = parser.parse_args(argv)
    try:
        initialization_validate_options(options.mode, options.initialization_case)
    except ValueError as error:
        parser.error(str(error))
    if options.mode == INITIALIZATION_MODE:
        return initialization_main(options)
    if options.mode not in GRAPHQL_BOOTSTRAP_MODES:
        assert options.runtime_image is None and options.provision_manifest is None
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "web/arena-workbench/tests/e2e/functional-v7"))
    from confined_io import ConfinedRoot, new_destination, read_confined
    from run import LABEL, OWN_FORMAT, OwnedRun, discover, docker, projection

    token = "arena-neo4j-" + uuid.uuid4().hex
    output = (root / "outputs/workflow/plan03-implementation/graphql-query-launch/implementation/runs" if options.mode == "workflow-graphql-network" else root / "outputs/workflow/plan03-implementation/graphql-query-api/runs" if options.mode == "workflow-graphql"
              else root / "web/arena-workbench/tests/e2e/functional-v7/.runs") / token
    if options.mode == EXECUTION_MODE:
        output = root / "outputs/workflow/plan04-implementation/installed-execution/runs" / token
    if options.mode == JOIN_MODE:
        output = root / "outputs/workflow/plan04-implementation/installed-execution/joined-runs" / token
    if options.mode == LIFECYCLE_MODE:
        output = root / "outputs/workflow/plan04-implementation/installed-execution/lifecycle-runs" / token
    # Validate every ancestor before the first write; never resolve .runs links.
    with ConfinedRoot(output.parent.parent) as parent:
        try:
            parent.validate_directory(output.parent.name)
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
        client_image = CLIENT_IMAGE
        if options.mode in GRAPHQL_BOOTSTRAP_MODES:
            discovery = select_graphql_runtime(discovery, options.runtime_image, options.provision_manifest)
            client_image = discovery["selected_runtime_image"]
            run.proof["graphql_provision_manifest_sha256"] = GRAPHQL_MANIFEST_SHA256
            run.proof["invocation"] = [sys.executable, *sys.argv]
        run.proof["host_root"] = discovery["host_root"]
        for image in (DB_IMAGE, client_image):
            assert docker("image", "inspect", "--format", "{{.Id}}", image) == image
        if options.mode == JOIN_MODE:
            run.proof["historical_metadata"] = validate_join_historical_metadata(root)
        manifest = stage_source(root, output / "source", options.mode, provision=discovery.get("provision"))
        if options.mode == JOIN_MODE:
            historical = run.proof["historical_metadata"]
            assert manifest[historical["fixture"]] == historical["fixture_sha256"]
        run.proof["source_sha256"] = manifest
        host = discovery["host_root"] + "/" + output.relative_to(root).as_posix()
        run.save()
        network_created = True  # Recover ambiguous create by exact intended name + label.
        run.proof["create_attempts"][token] = "attempted"
        run.save()
        network_flags = (
            ["--opt", "com.docker.network.bridge.gateway_mode_ipv4=isolated"] if options.mode in BOLT_MODES else []
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
        if options.mode in BOLT_MODES:
            detailed = json.loads(docker("network", "inspect", nid))[0]
            validate_process_network(detailed)
            run.proof["isolated_network"] = detailed
        run.proof["network"] = net
        # Scene parent + SDK children reuse F0's 4 GiB / 256 PID resource cap.
        # The stdlib-child cap cannot hold two immutable Torch/SDK import trees.
        # CPU, egress, namespace, read-only, per-child alarm/deadlines stay pinned.
        # Approved ordinary extended-cohort experiment: DB 4 GiB; other modes stay 1 GiB.
        for role, image, user, memory, pids in (
            ("db", DB_IMAGE, "7474:7474", "4g" if options.mode == "workflow" else "1g", 128),
            (
                "client",
                client_image,
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
                if options.mode in BOLT_MODES:
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
                if options.mode in BOLT_MODES:
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
                    *(["OPENBLAS_NUM_THREADS=1", "OMP_NUM_THREADS=1", "MKL_NUM_THREADS=1"] if options.mode == JOIN_MODE else []),
                    "/isaac-sim/python.sh",
                    *(["-I", "-S"] if options.mode in GRAPHQL_BOOTSTRAP_MODES else []),
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
                (4294967296 if options.mode == "workflow" else 1073741824)
                if role == "db"
                else 4294967296 if options.mode in SCENE_MODES else 805306368
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
                assert cfg["ReadonlyRootfs"] and len(info["Mounts"]) == (3 if options.mode in BOLT_MODES else 2)
                assert set(cfg["Tmpfs"]) == {"/tmp"}
                binds = {m["Destination"]: m for m in info["Mounts"] if m["Type"] == "bind"}
                assert set(binds) == (
                    {"/source", "/evidence", "/network"} if options.mode in BOLT_MODES else {"/source", "/evidence"}
                )
                if options.mode in BOLT_MODES:
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
                    if options.mode in BOLT_MODES
                    else {"/data", "/logs"}
                )
                if options.mode in BOLT_MODES:
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
            if role == "db" and options.mode in BOLT_MODES:
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
        if options.mode == "workflow-graphql":
            from check_proof import graphql_import_contract
            graphql_import_contract(dict(discovery["provision"], imports=proof["imports"]))
            run.proof["evidence_sha256"] = {
                name: hashlib.sha256(read_confined(output / "evidence", name)).hexdigest()
                for name in ("client-proof.json", "pytest.xml", "schema.graphql", "operation-coverage.json", "graphql-joined.json", "graphql-full-join.json")
            }
            run.proof["captured_source_files"] = len(manifest)
            run.proof["captured_source_bytes"] = sum(len(read_confined(output / "source", name)) for name in manifest)
        if options.mode == "workflow-graphql-network":
            from check_proof import graphql_import_contract

            graphql_import_contract(dict(discovery["provision"], imports=proof["imports"]))
            run.proof["evidence_sha256"] = {}
            for row in [*proof["network_processes"], *proof["network_servers"]]:
                name = row["evidence_file"]
                assert name == f"graphql-process-{row['pid']}.json"
                raw = read_confined(output / "evidence", name)
                assert hashlib.sha256(raw).hexdigest() == row["evidence_sha256"]
                detail = json.loads(raw)
                graphql_import_contract(dict(discovery["provision"], imports=detail["imports"]))
                assert detail["source_sha256"] == proof["source_sha256"]
                run.proof["evidence_sha256"][name] = row["evidence_sha256"]
            for name in ("client-proof.json", "pytest.xml", "uvicorn-discovery.json", "network-retained-readback.json"):
                run.proof["evidence_sha256"][name] = hashlib.sha256(read_confined(output / "evidence", name)).hexdigest()
            run.proof["captured_source_files"] = len(manifest)
            run.proof["captured_source_bytes"] = sum(len(read_confined(output / "source", name)) for name in manifest)
        if options.mode == EXECUTION_MODE:
            from check_proof import graphql_import_contract

            graphql_import_contract(dict(discovery["provision"], imports=proof["imports"]))
            run.proof["evidence_sha256"] = {}
            for row in proof["execution_admission_processes"]:
                name = row["evidence_file"]
                assert name == f"graphql-execution-process-{row['pid']}.json"
                raw = read_confined(output / "evidence", name)
                assert hashlib.sha256(raw).hexdigest() == row["evidence_sha256"]
                detail = json.loads(raw)
                assert detail["source_sha256"] == proof["source_sha256"]
                assert detail["pid"] == row["pid"] and detail["returncode"] == row["returncode"]
                assert detail["loader_events"] == row["loader_events"]
                assert not any(detail["allowed"].values()) and not any(detail["forbidden"].values())
                graphql_import_contract(dict(discovery["provision"], imports=detail["imports"]))
                run.proof["evidence_sha256"][name] = row["evidence_sha256"]
            for name in ("client-proof.json", "pytest.xml", "execution-admission.json"):
                run.proof["evidence_sha256"][name] = hashlib.sha256(read_confined(output / "evidence", name)).hexdigest()
            run.proof["captured_source_files"] = len(manifest)
            run.proof["captured_source_bytes"] = sum(len(read_confined(output / "source", name)) for name in manifest)
        if options.mode == JOIN_MODE:
            from check_proof import graphql_import_contract

            graphql_import_contract(dict(discovery["provision"], imports=proof["imports"]))
            for row in proof["joined_processes"]:
                detail = json.loads(read_confined(output / "evidence", f"join-process-{row['pid']}.json"))
                assert detail["source_sha256"] == proof["source_sha256"]
                assert detail["status"] == "completed" and detail["returncode"] == 0
                assert not any(detail["forbidden"].values())
                graphql_import_contract(dict(discovery["provision"], imports=detail["imports"]))
            run.proof["captured_source_files"] = len(manifest)
            run.proof["captured_source_bytes"] = sum(len(read_confined(output / "source", name)) for name in manifest)
        if options.mode == LIFECYCLE_MODE:
            from check_proof import graphql_import_contract

            graphql_import_contract(dict(discovery["provision"], imports=proof["imports"]))
            assert proof["source_sha256"] == {name: digest for name, digest in manifest.items() if name != "source-manifest.json"}
            witness = json.loads(read_confined(output / "evidence", "lifecycle-blocked-admission.json"))
            assert witness["historical_path"] == LIFECYCLE_ARCHIVE
            assert witness["historical_sha256"] == LIFECYCLE_ARCHIVE_SHA256
            assert witness["observations"] == proof["lifecycle"]["blocked_admission"]
            run.proof["evidence_sha256"] = {
                name: hashlib.sha256(read_confined(output / "evidence", name)).hexdigest()
                for name in ("client-proof.json", "pytest.xml", "lifecycle-blocked-admission.json")
            }
            run.proof["captured_source_files"] = len(manifest)
            run.proof["captured_source_bytes"] = sum(len(read_confined(output / "source", name)) for name in manifest)
        run.proof.update(client=proof, status="passed")
    except BaseException:
        run.proof["error"] = traceback.format_exc()
        if options.mode in BOLT_MODES:
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
            if options.mode == EXECUTION_MODE:
                # Hash actual partial failure evidence after owned processes stop.
                # No success-only witness is invented when startup/pytest failed.
                import re

                try:
                    with ConfinedRoot(output / "evidence") as evidence:
                        names = sorted(os.listdir(evidence.fd))
                    assert len(names) <= 5
                    assert all(name in {"client-proof.json", "pytest.xml", "execution-admission.json"}
                               or re.fullmatch(r"graphql-execution-process-[1-9][0-9]*\.json", name) for name in names)
                    actual = {}
                    for name in names:
                        raw = read_confined(output / "evidence", name)
                        assert len(raw) <= 4 * 1024 * 1024
                        actual[name] = hashlib.sha256(raw).hexdigest()
                    for name, digest in run.proof.get("evidence_sha256", {}).items():
                        assert actual.get(name) == digest, "Execution admission evidence changed during cleanup"
                    run.proof["evidence_sha256"] = actual
                except BaseException:
                    clean = False
                    run.proof["evidence_collection_error"] = traceback.format_exc()
            if options.mode == JOIN_MODE:
                # Hash actual partial witnesses after owned resources stop. Keep
                # incomplete/failed records as evidence, never fabricate success.
                import re

                try:
                    with ConfinedRoot(output / "evidence") as evidence:
                        names = sorted(os.listdir(evidence.fd))
                    assert len(names) <= 55
                    fixed = {"client-proof.json", "pytest.xml", "join-case.json", "join-detached.json",
                             "join-http-result.json", "join-retained.json", "join-positive.json"}
                    fixed |= {name + ".pending" for name in fixed if name.startswith("join-")}
                    assert all(name in fixed or re.fullmatch(
                        r"(?:join-process-[1-9][0-9]*(?:-started)?|join-launch-[1-9][0-9]*|generation-child-[1-9][0-9]*-(?:sdk|active))\.json(?:\.pending)?",
                        name) for name in names)
                    actual = {}
                    for name in names:
                        raw = read_confined(output / "evidence", name)
                        assert len(raw) <= 4 * 1024 * 1024
                        actual[name] = hashlib.sha256(raw).hexdigest()
                    run.proof["evidence_sha256"] = actual
                except BaseException:
                    clean = False
                    run.proof["evidence_collection_error"] = traceback.format_exc()
            if options.mode == LIFECYCLE_MODE:
                # Preserve only actual partial evidence; collection is not RED.
                try:
                    with ConfinedRoot(output / "evidence") as evidence:
                        names = sorted(os.listdir(evidence.fd))
                    assert set(names) <= {"client-proof.json", "pytest.xml", "lifecycle-blocked-admission.json"}
                    actual = {}
                    for name in names:
                        raw = read_confined(output / "evidence", name)
                        assert len(raw) <= 4 * 1024 * 1024
                        actual[name] = hashlib.sha256(raw).hexdigest()
                    for name, digest in run.proof.get("evidence_sha256", {}).items():
                        assert actual.get(name) == digest, "Lifecycle evidence changed during cleanup"
                    run.proof["evidence_sha256"] = actual
                except BaseException:
                    clean = False
                    run.proof["evidence_collection_error"] = traceback.format_exc()
            for name, digest in run.proof.get("source_sha256", {}).items():
                assert hashlib.sha256(read_confined(output / "source", name)).hexdigest() == digest
                if options.mode in GRAPHQL_BOOTSTRAP_MODES and name not in {
                    "closure.json", "source-manifest.json", "graphql-import-check.py", "graphql-profile.json"
                }:
                    assert hashlib.sha256(read_confined(root, name)).hexdigest() == digest, "Live query cohort source changed"
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
    if sys.argv[1:3] == ["--inside", INITIALIZATION_MODE]:
        assert len(sys.argv) == 4 and sys.argv[3] in INITIALIZATION_CASES
        raise SystemExit(initialization_inside_entry(sys.argv[3]))
    if sys.argv[1:2] == ["--inside"]:
        assert len(sys.argv) == 3 and sys.argv[2] in (
            "self-check",
            "workflow",
            "workflow-process",
            "workflow-scene",
            "workflow-cli",
            "workflow-graphql",
            "workflow-graphql-network",
            EXECUTION_MODE,
            JOIN_MODE,
            LIFECYCLE_MODE,
        )
        raise SystemExit(inside(sys.argv[2]))
    raise SystemExit(main())
