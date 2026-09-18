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
                with self.subTest(resource=resource, error=type(error).__name__), tempfile.TemporaryDirectory() as tmp:
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
                self.assertEqual(guard.find_spec("local_app.safe").origin, str(root / "local_app/safe.py"))
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
            "server": {"agent": "Neo4j/5.26.30", "protocol_version": [5, 8], "address": "172.22.0.2:7687"},
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
        for bad in (b"<testsuite/>", b"<testsuite><testcase><skipped/></testcase></testsuite>"):
            with self.assertRaises(AssertionError):
                runner.validate_client_proof(proof, "workflow", bad)
        runner.validate_client_proof(proof, "workflow", xml)


if __name__ == "__main__":
    unittest.main()
