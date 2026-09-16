# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Pure host resource-policy tests; never start or modify containers."""

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
GIB = 1024**3


class ResourceLimitsTest(unittest.TestCase):
    def helper(self):
        path = HERE / "resource_limits.py"
        self.assertTrue(path.exists(), "shared resource policy is missing")
        spec = importlib.util.spec_from_file_location("resource_limits", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_editor_caps_are_persistent_and_checked_before_directory_fallback(self):
        config = json.loads((HERE.parent / ".devcontainer/devcontainer.json").read_text())
        for argument in ("--memory=8589934592", "--memory-swap=8589934592", "--pids-limit=512"):
            self.assertIn(argument, config["runArgs"])
        command = config["initializeCommand"]
        self.assertTrue(command.startswith("python3 docker/resource_limits.py --check-editor && ("))
        self.assertTrue(command.endswith(")"))

    def test_editor_preflight_validates_actual_flags_and_rejects_small_hosts(self):
        helper = self.helper()
        self.assertTrue(hasattr(helper, "validate_editor"), "editor preflight is missing")
        flags = ["--memory=8589934592", "--memory-swap=8589934592", "--pids-limit=512"]
        helper.validate_editor(flags, 80 * GIB)
        with self.assertRaises(ValueError):
            helper.validate_editor(flags, 80 * GIB - 1)
        for bad in (
            flags[:2],
            flags + ["--memory=1"],
            flags + ["--memory", "0"],
            flags + ["-m", "0"],
            flags + ["--memory-swap", "-1"],
            flags + ["--pids-limit", "-1"],
            ["--memory=0", "--memory-swap=0", "--pids-limit=512"],
            [flags[0], "--memory-swap=-1", flags[2]],
            [flags[0], flags[1], "--pids-limit=0"],
            [flags[0], flags[1], "--pids-limit=513"],
        ):
            with self.subTest(flags=bad), self.assertRaises(ValueError):
                helper.validate_editor(bad, 80 * GIB)
        helper.validate_editor(["--memory=1073741824", "--memory-swap=1073741824", "--pids-limit=256"], 16 * GIB)

    def test_cli_emits_only_validated_numeric_exports_or_checks_actual_editor(self):
        helper = self.helper()
        self.assertTrue(hasattr(helper, "main"), "host CLI is missing")
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["resource_limits.py"]),
            patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "98143846400")),
            redirect_stdout(output),
        ):
            helper.main()
        expected = helper.resource_environment(98143846400)
        self.assertEqual(output.getvalue(), "".join(f"export {key}={value}\n" for key, value in expected.items()))
        for capacity, passes in ((98143846400, True), (16 * GIB, False)):
            with (
                patch.object(sys, "argv", ["resource_limits.py", "--check-editor"]),
                patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, str(capacity))),
            ):
                if passes:
                    helper.main()
                else:
                    with self.assertRaises(ValueError):
                        helper.main()

    def test_arena_launcher_computes_caps_before_any_build_or_removal(self):
        script = (HERE / "run_docker.sh").read_text()
        assignment = 'RESOURCE_ENV=$(python3 "$SCRIPT_DIR/resource_limits.py")'
        self.assertIn(assignment, script)
        self.assertLess(script.index(assignment), script.index("docker build"))
        self.assertLess(script.index(assignment), script.index("docker rm"))
        self.assertIn('eval "$RESOURCE_ENV"', script)
        for flag, variable in (
            ("memory", "ARENA_MEMORY_BYTES"),
            ("memory-swap", "ARENA_MEMORY_BYTES"),
            ("pids-limit", "ARENA_PIDS_LIMIT"),
        ):
            self.assertIn(f'"--{flag}" "${variable}"', script)

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI is required for config-only checks")
    def test_compose_effective_limits_in_simulator_and_both_frontend_modes(self):
        helper = self.helper()
        budgets = helper.resource_environment(98143846400)
        env = {
            "PATH": os.environ["PATH"],
            "HOME": "/tmp",
            "DOCKER_HOST": "unix:///nonexistent-resource-test.sock",
            "COMPOSE_DISABLE_ENV_FILE": "true",
            "DISPLAY": "",
            "FRONTEND_UID": "1000",
            "FRONTEND_GID": "1000",
            "API_GID": "1000",
            "WORKBENCH_IPC_HOST": "/tmp/test-ipc",
            "WORKBENCH_SOURCE_HOST": "/tmp/test-source",
            **budgets,
        }
        for files, service, role in (
            ([HERE / "docker-compose.sim.yml"], "isaaclab-arena", "ARENA"),
            ([HERE / "workbench/compose.yaml"], "frontend", "FRONTEND"),
            ([HERE / "workbench/compose.yaml", HERE / "workbench/compose.dev.yaml"], "frontend", "FRONTEND"),
        ):
            with self.subTest(role=role, files=files):
                command = ["docker", "compose", "--env-file", "/dev/null", "-p", "resource-policy-test"]
                for path in files:
                    command += ["-f", str(path)]
                command += ["config", "--format", "json"]
                result = subprocess.run(command, env=env, check=True, text=True, capture_output=True, timeout=15)
                config = json.loads(result.stdout)["services"][service]
                memory = int(budgets[f"{role}_MEMORY_BYTES"])
                self.assertEqual(int(config.get("mem_limit", 0)), memory)
                self.assertEqual(int(config.get("memswap_limit", 0)), memory)
                self.assertEqual(int(config.get("pids_limit", 0)), int(budgets[f"{role}_PIDS_LIMIT"]))
                missing = dict(env)
                del missing[f"{role}_MEMORY_BYTES"]
                rejected = subprocess.run(command, env=missing, text=True, capture_output=True, timeout=15)
                self.assertNotEqual(rejected.returncode, 0, "missing budgets must not become unlimited")

    def test_invalid_and_too_small_capacities_fail_closed(self):
        helper = self.helper()
        for value in (-1, 0, True, 1.5, "98143846400", 120 * 1024**2 - 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                helper.resource_environment(value)
        for output in ("", "0", "-1", "unknown"):
            with (
                self.subTest(output=output),
                patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output)),
                self.assertRaises(ValueError),
            ):
                helper.resource_environment()
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("docker", 15)):
            with self.assertRaises(subprocess.TimeoutExpired):
                helper.resource_environment()

    def test_daemon_capacity_not_editor_cgroup_drives_default_budgets(self):
        helper = self.helper()
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "98143846400\n")) as run:
            self.assertEqual(helper.resource_environment()["ARENA_MEMORY_BYTES"], "58886307840")
        run.assert_called_once_with(
            ["docker", "info", "--format", "{{.MemTotal}}"],
            check=True,
            text=True,
            capture_output=True,
            timeout=15,
        )

    def test_budgets_reserve_host_headroom_at_all_machine_sizes(self):
        helper = self.helper()
        for capacity in (GIB, 16 * GIB, 98143846400, 1024 * GIB):
            with self.subTest(capacity=capacity):
                budgets = helper.resource_environment(capacity)
                limits = []
                for role, maximum, percentage, pids in (
                    ("EDITOR", 8, 10, 512),
                    ("ARENA", 56, 60, 2048),
                    ("FRONTEND", 4, 5, 256),
                ):
                    memory = int(budgets[f"{role}_MEMORY_BYTES"])
                    self.assertEqual(memory, min(maximum * GIB, capacity * percentage // 100))
                    self.assertEqual(budgets[f"{role}_PIDS_LIMIT"], str(pids))
                    self.assertGreater(memory, 0)
                    limits.append(memory)
                self.assertLessEqual(sum(limits), capacity * 75 // 100)


if __name__ == "__main__":
    unittest.main()
