#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Stdlib runner regressions; no application imports or live Docker calls."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT / "web/arena-workbench/tests/e2e/functional-v7"))
spec = importlib.util.spec_from_file_location("runner", ROOT / "scripts/run-workflow-neo4j-checks.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def test_cli_profile_is_additive_fixed_and_staged(self):
        self.assertEqual(
            runner.CLI_TEST,
            "isaaclab_arena/tests/test_environment_workflow_cli_process_neo4j.py",
        )
        self.assertEqual(runner.PROCESS_SOURCE_LIMIT, 320)
        self.assertEqual(runner.SCENE_SOURCE_LIMIT, 384)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = runner.stage_source(ROOT, Path(tmp) / "source", "workflow-cli")
            self.assertIn(runner.CLI_TEST, manifest)
            self.assertIn(
                "isaaclab_arena_examples/agentic_environment_generation/foreground_workflow_cli.py",
                manifest,
            )
            self.assertLessEqual(len(manifest), 384)
        spec = importlib.util.spec_from_file_location("harness_cli", ROOT / "scripts/workflow_process_harness.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        args = [
            "/immutable/python",
            "-s",
            "-B",
            "/source/scripts/workflow_process_harness.py",
            "--scene-child",
        ]
        kwargs = {"env": {"HOME": "/tmp"}}
        with patch.object(helper, "scene_spawn_spec", return_value=(args, kwargs)):
            actual, options = helper.cli_spawn_spec()
        self.assertEqual(actual[-1], "--cli-child")
        self.assertIs(options, kwargs)
        import socket

        for scene in (False, True):
            guard = helper.Guards("172.30.0.2", scene=scene)
            with socket.socket(socket.AF_UNIX) as sock:
                self.assertFalse(guard.control_allowed(sock, "/proc/self/fd/3/stop-" + "a" * 40 + ".sock"))

    def test_scene_launch_budget_is_exact_and_does_not_change_ordinary_guard(self):
        from types import SimpleNamespace

        spec = importlib.util.spec_from_file_location("process_harness", ROOT / "scripts/workflow_process_harness.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        args = [
            "/immutable/python",
            "-s",
            "-B",
            "/source/scripts/workflow_process_harness.py",
            "--scene-child",
        ]
        kwargs = dict(
            executable=args[0],
            env={"HOME": "/tmp"},
            cwd="/source",
            stdin=-1,
            stdout=-1,
            stderr=-1,
            shell=False,
            close_fds=True,
            pass_fds=(),
            start_new_session=True,
            text=False,
        )
        for scene, cli, limit in (
            (False, False, 1),
            (True, False, 12),
            (True, True, 31),
        ):
            guard = helper.Guards("172.30.0.2", scene=scene, cli=cli)
            guard.fixed_spec = (args, kwargs)
            guard.native = lambda *a, **k: SimpleNamespace(pid=100 + guard.allowed["child_launch"])
            with patch.object(helper, "verify_sources") as verify:
                for _ in range(limit):
                    guard.popen(args, **kwargs)
                self.assertEqual(guard.allowed["child_launch"], limit)
                verify.assert_called_with(scene=scene)
                with self.assertRaises(RuntimeError):
                    guard.popen(args, **kwargs)
                self.assertEqual(guard.allowed["child_launch"], limit)
        child = helper.Guards(scene=True)
        child.fixed_spec = (args, kwargs)
        with self.assertRaises(RuntimeError):
            child.popen(args, **kwargs)
        self.assertEqual(child.allowed["child_launch"], 0)

    def test_scene_mode_has_exact_entry_and_ordinary_bounds_unchanged(self):
        self.assertEqual(
            runner.SCENE_TEST,
            "isaaclab_arena/tests/test_environment_workflow_scene_worker_neo4j.py",
        )
        self.assertEqual(runner.PROCESS_SOURCE_LIMIT, 320)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = runner.stage_source(ROOT, Path(tmp) / "source", "workflow-scene")
            self.assertIn(runner.SCENE_TEST, manifest)
            self.assertIn(runner.SCENE_FIXTURE, manifest)
            self.assertIn(
                "isaaclab_arena_examples/agentic_environment_generation/web_api/scene_worker.py",
                manifest,
            )
            self.assertLessEqual(len(manifest), runner.SCENE_SOURCE_LIMIT)

    def test_process_guard_rejects_non_bolt_dns_listen_and_process(self):
        spec = importlib.util.spec_from_file_location("process_harness", ROOT / "scripts/workflow_process_harness.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        guard = helper.Guards("172.30.0.2")
        import socket

        with socket.socket() as sock:
            for event, args in (
                ("socket.connect", (sock, ("172.30.0.3", 7687))),
                ("socket.connect", (sock, ("172.30.0.2", 80))),
                ("socket.getaddrinfo", ("database", 7687, 0, 0, 0)),
                ("socket.bind", (sock, ("127.0.0.1", 0))),
                ("subprocess.Popen", ("python", [], None, {})),
            ):
                with self.subTest(event=event), self.assertRaises(RuntimeError):
                    guard.audit(event, args)
        self.assertEqual(guard.allowed, {"bolt": 0, "child_launch": 0})
        self.assertEqual(sum(guard.forbidden.values()), 5)

    def test_process_spawn_gate_pins_every_launch_field(self):
        spec = importlib.util.spec_from_file_location("process_harness", ROOT / "scripts/workflow_process_harness.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        args = ["/immutable/python", "-I", "-S", "fixture.py"]
        kwargs = dict(
            executable=args[0],
            env={"HOME": "/tmp"},
            cwd="/source",
            stdin=-1,
            stdout=-1,
            stderr=-1,
            shell=False,
            close_fds=True,
            pass_fds=(),
            start_new_session=True,
            text=False,
        )
        guard = helper.Guards("172.30.0.2")
        with (
            patch.object(helper, "spawn_spec", return_value=(args, kwargs)),
            patch.object(helper, "verify_sources"),
        ):
            for key, value in (
                ("env", {"HOME": "/evil"}),
                ("cwd", "/tmp"),
                ("stdin", None),
                ("stdout", None),
                ("stderr", None),
                ("pass_fds", (4,)),
                ("shell", True),
                ("start_new_session", 1),
                ("close_fds", False),
                ("text", True),
            ):
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    guard.popen(args, **dict(kwargs, **{key: value}))
            self.assertEqual(guard.allowed["child_launch"], 0)
            with self.assertRaises(RuntimeError):
                guard.popen(["alternate", *args[1:]], **kwargs)

    def test_profile_skips_data_inspection_for_non_policy_names(self):
        from types import SimpleNamespace

        spec = importlib.util.spec_from_file_location("process_harness", ROOT / "scripts/workflow_process_harness.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        guard = helper.Guards()

        class NoGlobals:
            def get(self, *args):
                raise AssertionError("Non-policy call must not inspect globals or class hierarchy")

        frame = SimpleNamespace(f_code=SimpleNamespace(co_name="ordinary_parse"), f_globals=NoGlobals())
        guard.profile(frame, "call", None)
        self.assertFalse(any(guard.forbidden.values()))

    def test_process_profile_denies_provider_subclasses_and_runtime(self):
        from types import SimpleNamespace

        spec = importlib.util.spec_from_file_location("process_harness", ROOT / "scripts/workflow_process_harness.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        for name, category in (
            ("OpenAI", "provider"),
            ("EnvironmentGenerationAgent", "provider"),
            ("SimulationApp", "runtime"),
            ("SnapshotService", "runtime"),
        ):
            guard = helper.Guards("172.30.0.2")
            base = type(name, (), {})
            child = type("Subclass", (base,), {})
            frame = SimpleNamespace(
                f_globals={"__name__": "synthetic"},
                f_code=SimpleNamespace(co_name="__init__"),
                f_locals={"self": child()},
            )
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                guard.profile(frame, "call", None)
            self.assertEqual(guard.forbidden[category], 1)
        for module, name, category in (
            ("isaacsim.runtime", "launch", "runtime"),
            ("owned.snapshot_service", "render", "runtime"),
            ("owned.graph_access", "retrieve_snapshot", "graph"),
            ("neo4j._sync.driver", "driver", "graph"),
        ):
            guard = helper.Guards()
            frame = SimpleNamespace(
                f_code=SimpleNamespace(co_name=name, co_filename="/untrusted"),
                f_globals={"__name__": module},
                f_locals={},
            )
            with (
                self.subTest(module=module, name=name),
                self.assertRaises(RuntimeError),
            ):
                guard.profile(frame, "call", None)
            self.assertEqual(guard.forbidden[category], 1)

    def test_process_closure_is_manifest_bound_and_old_limit_unchanged(self):
        import hashlib

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "isaaclab_arena/tests/test_data").mkdir(parents=True)
            (root / runner.SELF).write_text("# runner\n")
            (root / runner.PROCESS_HELPER).write_text("# fixed\n")
            (root / runner.FIXTURE).write_text("fixture: true\n")
            for i in range(257):
                (root / f"isaaclab_arena/m{i}.py").write_text("# module\n")
            imports = "\n".join(f"import isaaclab_arena.m{i}" for i in range(257))
            (root / runner.TEST).write_text(imports)
            (root / runner.PROCESS_TEST).write_text(imports)
            with self.assertRaises(AssertionError):
                runner.stage_source(root, root / "old", "workflow")
            hashes = runner.stage_source(root, root / "new", "workflow-process")
            captured = json.loads((root / "new/source-manifest.json").read_text())
            self.assertEqual(set(hashes) - {"source-manifest.json"}, set(captured))
            for name, digest in captured.items():
                self.assertEqual(
                    hashlib.sha256((root / "new" / name).read_bytes()).hexdigest(),
                    digest,
                )
            import workflow_process_harness as helper

            self.assertEqual(helper.MAX_CAPTURE_FILES, runner.PROCESS_SOURCE_LIMIT)
            self.assertLessEqual(len(hashes), runner.PROCESS_SOURCE_LIMIT)
            extra = "\n".join(f"import isaaclab_arena.n{i}" for i in range(64))
            for i in range(64):
                (root / f"isaaclab_arena/n{i}.py").write_text("# module\n")
            (root / runner.PROCESS_TEST).write_text(imports + "\n" + extra)
            with self.assertRaises(AssertionError):
                runner.stage_source(root, root / "oversized", "workflow-process")

    def test_process_network_requires_isolated_gateway_and_no_ipv6(self):
        good = dict(
            Internal=True,
            EnableIPv6=False,
            Options={"com.docker.network.bridge.gateway_mode_ipv4": "isolated"},
            IPAM={"Config": [{"Subnet": "172.30.0.0/16"}]},
        )
        runner.validate_process_network(good)
        for bad in (
            dict(good, Internal=False),
            dict(good, EnableIPv6=True),
            dict(good, Options={}),
            dict(good, IPAM={"Config": [{"Gateway": "172.30.0.1"}]}),
        ):
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                runner.validate_process_network(bad)

    def test_symlink_output_rejected_before_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "web/arena-workbench/tests/e2e/functional-v7"
            parent.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            (parent / ".runs").symlink_to(outside, target_is_directory=True)
            with (
                patch.object(runner, "__file__", str(root / "scripts/runner.py")),
                patch("run.discover", side_effect=AssertionError("Docker reached")),
                patch("run.OwnedRun", side_effect=AssertionError("Ownership reached")),
                patch.object(runner.os, "fchown") as chown,
            ):
                with self.assertRaises(OSError):
                    runner.main(["self-check"])
            self.assertEqual(list(outside.iterdir()), [])
            chown.assert_not_called()

    def test_ambiguous_creates_remain_unknown_after_empty_listings(self):
        import run

        owned = run.OwnedRun
        for resource in ("network", "container"):
            for error in (subprocess.TimeoutExpired("docker", 45), KeyboardInterrupt()):
                with (
                    self.subTest(resource=resource, error=type(error).__name__),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    root = Path(tmp)
                    base = root / "web/arena-workbench/tests/e2e/functional-v7"
                    base.mkdir(parents=True)
                    listings = []
                    delayed = []

                    def docker(*args):
                        if delayed:
                            return delayed[0]
                        if args[:2] == ("image", "inspect"):
                            return args[-1]
                        if args[:2] == ("network", "create"):
                            if resource == "network":
                                raise error
                            return "a" * 64
                        if args[:2] == ("network", "inspect"):
                            return json.dumps({
                                "Id": "a" * 64,
                                "Name": token[0],
                                "Internal": True,
                                "Labels": {run.LABEL: token[0]},
                                "Containers": {},
                            })
                        if args[0] == "create":
                            raise error
                        listings.append(args)
                        return ""

                    token = []

                    def owner(output, name):
                        token.append(name)
                        return owned(output, name, command=docker)

                    with (
                        patch.object(runner, "__file__", str(root / "scripts/runner.py")),
                        patch.object(runner.os, "fchown"),
                        patch("run.OwnedRun", side_effect=owner),
                        patch("run.docker", side_effect=docker),
                        patch("run.discover", return_value={"host_root": str(root)}),
                        patch.object(runner, "stage_source", return_value={}),
                    ):
                        self.assertEqual(runner.main(["self-check"]), 1)
                    proof = json.loads((base / ".runs" / token[0] / "run-proof.json").read_text())
                    # The daemon can accept the pending request AFTER these empty snapshots.
                    self.assertTrue(listings)
                    delayed.append("b" * 64)  # Request lands after all cleanup snapshots.
                    self.assertEqual(docker("ps", "-aq"), "b" * 64)
                    self.assertFalse(proof["cleanup_verified"])
                    self.assertEqual(proof["cleanup_verification"]["status"], "unknown")
                    self.assertTrue(proof["ambiguous_creates"])

    def test_staged_guard_rejects_dynamic_namespace_and_installed_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "local_app").mkdir()
            (root / "local_app/safe.py").write_text("VALUE = 1\n")
            manifest = {"local_app/safe.py": ""}
            fallback = root / "installed"
            (fallback / "local_app").mkdir(parents=True)
            (fallback / "local_app/__init__.py").write_text('raise AssertionError("Installed fallback executed")\n')
            (fallback / "local_app/unstaged.py").write_text('raise AssertionError("Installed fallback executed")\n')
            sys.path.insert(0, str(fallback))
            guard = runner.install_staged_import_guard(root, manifest, ["local_app"])
            try:
                self.assertEqual(
                    guard.find_spec("local_app.safe").origin,
                    str(root / "local_app/safe.py"),
                )
                with self.assertRaises(ImportError):
                    __import__("local_app.unstaged", fromlist=["value"])
                (root / "local_app/unstaged.py").write_text("VALUE = 2\n")
                with self.assertRaises(ImportError):
                    __import__("local_app.unstaged", fromlist=["value"])
            finally:
                sys.meta_path.remove(guard)
                sys.path.remove(str(fallback))
                sys.modules.pop("local_app", None)

    def test_parent_proof_rejects_wrong_contract_and_empty_junit(self):
        proof = {
            "status": "passed",
            "mode": "workflow",
            "database": runner.DATABASE,
            "uri": runner.URI,
            "driver_version": "6.2.0",
            "driver_file": "/isaac-sim/kit/python/lib/python3.12/site-packages/neo4j/__init__.py",
            "server": {
                "agent": "Neo4j/5.26.30",
                "protocol_version": [5, 8],
                "address": "172.22.0.2:7687",
            },
            "return_one": 1,
            "driver_closed": True,
            "marker": {"token": "a" * 32, "created_read_deleted": True, "remaining": 0},
            "suite": runner.TEST,
            "tests": 1,
        }
        xml = b'<testsuite><testcase name="test_real"/></testsuite>'
        for field, bad in [
            ("mode", "self-check"),
            ("database", "neo4j"),
            ("uri", "bolt://other:7687"),
            ("driver_file", "/source/neo4j.py"),
            ("driver_version", "fake"),
            ("suite", "other.py"),
        ]:
            with self.subTest(field=field), self.assertRaises(AssertionError):
                runner.validate_client_proof(dict(proof, **{field: bad}), "workflow", xml)
        for bad in (
            b"<testsuite/>",
            b"<testsuite><testcase><skipped/></testcase></testsuite>",
        ):
            with self.assertRaises(AssertionError):
                runner.validate_client_proof(proof, "workflow", bad)
        runner.validate_client_proof(proof, "workflow", xml)


if __name__ == "__main__":
    unittest.main()
