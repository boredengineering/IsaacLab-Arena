# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Synthetic Docker lifecycle regressions; no daemon access from tests."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run-preview.py"


def load_launcher():
    spec = importlib.util.spec_from_file_location("preview_launcher", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LauncherTests(unittest.TestCase):
    def test_creation_timeout_keeps_intended_owner(self):
        launcher = load_launcher()
        launcher.RUN = "test-run"
        launcher.PROOF = {"containers": []}
        with patch.object(launcher, "docker", side_effect=subprocess.TimeoutExpired("docker run", 1)):
            with self.assertRaises(subprocess.TimeoutExpired):
                launcher.start("build", "image", "/source", "deps")
        self.assertEqual(launcher.OWNED, [{"name": "test-run-build", "label": "test-run", "id": None}])

    def test_cleanup_recovers_creation_timeout_orphan(self):
        launcher = load_launcher()
        launcher.RUN = "test-run"
        launcher.OWNED = [{"name": "test-run-build", "label": "test-run", "id": None}]
        launcher.PROOF = {"cleanup": []}
        present = {"test-run-build": "a" * 64}

        def docker(*args, **kwargs):
            if args[0] == "ps":
                if "--filter" in args:
                    return "\n".join(present.values())
                return "\n".join(f"{cid} {name}" for name, cid in present.items())
            if args[0] == "inspect":
                return json.dumps([{
                    "Id": "a" * 64,
                    "Name": "/test-run-build",
                    "Config": {"Labels": {"arena.ui-preview": "test-run"}},
                }])
            if args[0] == "rm":
                self.assertEqual(args[-1], "a" * 64)
                present.clear()
                return ""
            raise AssertionError(f"Unexpected Docker call: {args}")

        self.assertTrue(callable(getattr(launcher, "cleanup", None)), "Missing verified cleanup")
        with patch.object(launcher, "docker", side_effect=docker):
            self.assertTrue(launcher.cleanup())
        self.assertEqual(present, {})
        self.assertEqual(launcher.PROOF["owned_remaining"], [])
        self.assertTrue(launcher.PROOF["cleanup_verified"])

    def test_main_always_writes_cleanup_failure_proof(self):
        launcher = load_launcher()
        with tempfile.TemporaryDirectory() as output:

            def cleanup():
                self.assertNotEqual(launcher.PROOF["status"], "passed")
                launcher.PROOF["cleanup_verified"] = False
                launcher.PROOF["owned_remaining"] = None
                return False

            with (
                patch.object(launcher.tempfile, "mkdtemp", return_value=output),
                patch.object(launcher, "docker", side_effect=RuntimeError("daemon unavailable")),
                patch.object(launcher, "cleanup", side_effect=cleanup) as clean,
            ):
                self.assertEqual(launcher.main(), 1)
            proof = json.loads((Path(output) / "run-proof.json").read_text())
            self.assertEqual(clean.call_count, 1)
            self.assertEqual(proof["status"], "failed")
            self.assertFalse(proof["cleanup_verified"])
            self.assertIsNone(proof["owned_remaining"])

    def run_scenario(self, mode):
        launcher = load_launcher()
        present = {}
        removed = []
        inspected = []

        def acceptance():
            for role, cid in [("build", "a" * 64), ("browser", "b" * 64)]:
                name = f"{launcher.RUN}-{role}"
                launcher.OWNED.append({"name": name, "label": launcher.RUN, "id": cid})
                present[name] = cid

        def docker(*args, **kwargs):
            if mode == "daemon":
                raise RuntimeError("daemon unavailable")
            if args[0] == "ps":
                if "--filter" in args:
                    return "\n".join(
                        cid for name, cid in present.items() if not (mode == "foreign" and name.endswith("browser"))
                    )
                return "\n".join(f"{cid} {name}" for name, cid in present.items())
            if args[0] == "inspect":
                self.assertLessEqual(kwargs.get("timeout", 180), 30, "Cleanup inspection must be bounded")
                cid = args[-1]
                inspected.append(cid)
                if mode == "inspect-timeout" and cid.startswith("b"):
                    raise subprocess.TimeoutExpired("inspect", 30)
                name = next(name for name, value in present.items() if value == cid)
                label = "foreign-run" if mode == "foreign" and cid.startswith("b") else launcher.RUN
                return json.dumps([{"Id": cid, "Name": "/" + name, "Config": {"Labels": {"arena.ui-preview": label}}}])
            if args[0] == "rm":
                self.assertNotEqual(launcher.PROOF["status"], "passed")
                cid = args[-1]
                removed.append(cid)
                if cid.startswith("b") and mode == "rm-timeout":
                    raise subprocess.TimeoutExpired("rm", 30)
                if cid.startswith("b") and mode == "rm-failed":
                    raise RuntimeError("rm failed")
                if mode != "lying-rm":
                    del present[next(name for name, value in present.items() if value == cid)]
                return ""
            raise AssertionError(f"Unexpected Docker call: {args}")

        with tempfile.TemporaryDirectory() as output:
            with (
                patch.object(launcher.tempfile, "mkdtemp", return_value=output),
                patch.object(launcher, "run_acceptance", side_effect=acceptance),
                patch.object(launcher, "docker", side_effect=docker),
            ):
                code = launcher.main()
            proof = json.loads((Path(output) / "run-proof.json").read_text())
        return code, proof, present, removed, inspected

    def test_failed_rm_still_present_fails_acceptance(self):
        code, proof, present, removed, _ = self.run_scenario("rm-failed")
        self.assertEqual(code, 1)
        self.assertEqual(proof["status"], "failed")
        self.assertFalse(proof["cleanup_verified"])
        self.assertEqual(proof["owned_remaining"], ["b" * 64])
        self.assertEqual(removed, ["b" * 64, "a" * 64])
        self.assertEqual(len(present), 1)

    def test_rm_timeout_attempts_next_cleanup_and_writes_proof(self):
        code, proof, _, removed, _ = self.run_scenario("rm-timeout")
        self.assertEqual(code, 1)
        self.assertEqual(removed, ["b" * 64, "a" * 64])
        self.assertIn("TimeoutExpired", proof["cleanup"][0]["error"])
        self.assertEqual(len(proof["cleanup"]), 2)

    def test_inspect_timeout_attempts_next_cleanup(self):
        code, proof, _, removed, inspected = self.run_scenario("inspect-timeout")
        self.assertEqual(code, 1)
        self.assertEqual(inspected, ["b" * 64, "a" * 64])
        self.assertEqual(removed, ["a" * 64])
        self.assertFalse(proof["cleanup_verified"])

    def test_unavailable_daemon_is_not_absence(self):
        code, proof, _, removed, _ = self.run_scenario("daemon")
        self.assertEqual(code, 1)
        self.assertIsNone(proof["owned_remaining"])
        self.assertFalse(proof["cleanup_verified"])
        self.assertEqual(len(proof["cleanup"]), 2)
        self.assertTrue(all("error" in row for row in proof["cleanup"]))
        self.assertEqual(removed, [])

    def test_foreign_same_name_is_never_removed(self):
        code, proof, present, removed, _ = self.run_scenario("foreign")
        self.assertEqual(code, 1)
        self.assertEqual(removed, ["a" * 64])
        self.assertEqual(list(present.values()), ["b" * 64])
        self.assertIn("refused", proof["cleanup"][0])
        self.assertFalse(proof["cleanup_verified"])

    def test_successful_rm_without_absence_is_failure(self):
        code, proof, _, _, _ = self.run_scenario("lying-rm")
        self.assertEqual(code, 1)
        self.assertFalse(proof["cleanup_verified"])
        self.assertEqual(len(proof["owned_remaining"]), 2)

    def test_success_requires_zero_owned_left(self):
        code, proof, present, removed, _ = self.run_scenario("success")
        self.assertEqual(code, 0)
        self.assertEqual(proof["status"], "passed")
        self.assertTrue(proof["cleanup_verified"])
        self.assertEqual(proof["owned_remaining"], [])
        self.assertEqual(present, {})
        self.assertEqual(len(removed), 2)
        self.assertTrue(all(row["absent"] for row in proof["cleanup"]))

    def test_import_has_no_side_effects(self):
        with patch("subprocess.run", side_effect=AssertionError("Docker on import")) as run:
            load_launcher()
        self.assertEqual(run.call_count, 0, "Import must not execute acceptance or Docker")


if __name__ == "__main__":
    unittest.main()
