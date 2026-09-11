# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Host-tool tests; no Arena imports, simulator, or Docker daemon required."""

import fcntl
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent


def load(name):
    path = ROOT / f"{name}.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DiscoveryTests(unittest.TestCase):
    def test_nested_clone_mapping_is_unique_and_uses_host_source(self):
        tool = load("workbench")
        self.assertIsNotNone(tool, "workbench discovery helper is missing")
        containers = [{"Mounts": [{"Type": "bind", "Source": "/host/clone", "Destination": "/editor/clone"}]}]
        self.assertEqual(tool.resolve_host_root("/editor/clone", containers), "/host/clone")
        self.assertEqual(tool.resolve_host_root("/host/clone", containers), "/host/clone")
        stale = {"Running": False, "Mounts": [{"Type": "bind", "Source": "/editor/clone", "Destination": "/old/repo"}]}
        self.assertEqual(tool.resolve_host_root("/editor/clone", [*containers, stale]), "/host/clone")
        containers.append({"Mounts": [{"Type": "bind", "Source": "/other/clone", "Destination": "/editor/clone"}]})
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            tool.resolve_host_root("/editor/clone", containers)

    def test_identity_requires_unambiguous_nonroot_account(self):
        tool = load("workbench")
        passwd = "root:x:0:0:root:/root:/bin/sh\nubuntu:x:1000:1000::/home/ubuntu:/bin/bash\nisaac-sim:x:1234:1234::/isaac-sim:/bin/bash"
        self.assertEqual(tool.resolve_identity(passwd, "1234", None, None), ("ubuntu", 1000, 1234))
        with self.assertRaisesRegex(RuntimeError, "non-root"):
            tool.resolve_identity(passwd, "1234", "root", None)
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            tool.resolve_identity(passwd + "\nalice:x:1001:1001::/home/alice:/bin/sh", "1234", None, None)
        self.assertEqual(tool.resolve_identity(passwd, "1234", "1000", "2000"), ("ubuntu", 1000, 2000))

    def test_api_command_is_exact_and_diagnostics_opt_in(self):
        tool = load("workbench")
        self.assertEqual(
            tool.api_command("/state", "/ipc/api.sock", "http://127.0.0.1:3000", False),
            [
                "/isaac-sim/python.sh",
                "-m",
                "isaaclab_arena_examples.agentic_environment_generation.web_api",
                "--state-dir",
                "/state",
                "--socket",
                "/ipc/api.sock",
                "--origin",
                "http://127.0.0.1:3000",
            ],
        )
        self.assertEqual(tool.api_command("/s", "/i", "http://127.0.0.1:3000", True)[-1], "--diagnostics")

    def test_discovery_rejects_stopped_runtime_and_never_starts_it(self):
        tool = load("workbench")
        records = [{
            "Id": "abc",
            "Name": "runtime",
            "Running": False,
            "User": "root",
            "NetworkMode": "host",
            "Mounts": [
                {"Type": "bind", "Source": "/host/clone", "Destination": "/repo"},
                {"Type": "bind", "Source": "/host/eval", "Destination": "/eval", "RW": True},
            ],
        }]
        args = Namespace(
            host_root="/host/clone",
            runtime="runtime",
            api_user=None,
            api_gid=None,
            frontend_uid=None,
            frontend_gid=None,
            port=3000,
            diagnostics=False,
            dev=False,
        )
        with patch.object(tool, "docker_records", return_value=records):
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                tool.discover(args)

    def test_socket_paths_and_port_range_are_validated(self):
        tool = load("workbench")
        with self.assertRaisesRegex(RuntimeError, "port"):
            tool.validate_port(0)
        with self.assertRaisesRegex(RuntimeError, "port"):
            tool.validate_port(65536)
        self.assertEqual(tool.validate_port(3000), 3000)


class RuntimeTests(unittest.TestCase):
    def test_api_child_uses_runtime_interpreter_not_an_early_exiting_shell_wrapper(self):
        runtime = load("runtime")
        command = runtime.inherited_api_command("/state", "/ipc/api.sock", "http://127.0.0.1:3001", True)
        self.assertEqual(command[0], runtime.sys.executable)
        self.assertEqual(
            command[1:], load("workbench").api_command("/state", "/ipc/api.sock", "http://127.0.0.1:3001", True)[1:]
        )

    def test_health_probe_preserves_configured_origin_authority(self):
        runtime = load("runtime")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api.sock"
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(path))
                listener.listen(1)
                listener.settimeout(2)
                received = []

                def respond():
                    try:
                        connection, _ = listener.accept()
                    except (OSError, TimeoutError):
                        return
                    with connection:
                        request = connection.recv(4096)
                        received.append(request)
                        status = b"200 OK" if b"Host: 127.0.0.1:33002\r\n" in request else b"403 Forbidden"
                        body = b'{"status":"ok"}'
                        connection.sendall(
                            b"HTTP/1.1 "
                            + status
                            + b"\r\nContent-Length: "
                            + str(len(body)).encode()
                            + b"\r\nConnection: close\r\n\r\n"
                            + body
                        )

                thread = threading.Thread(target=respond, daemon=True)
                thread.start()
                try:
                    self.assertTrue(runtime.health(path, "http://127.0.0.1:33002"))
                finally:
                    thread.join(timeout=3)
                self.assertEqual(len(received), 1)

    def test_lock_protocol_releases_without_waiting_for_docker_stdin_eof(self):
        runtime = load("runtime")
        reader, writer = os.pipe()
        with os.fdopen(reader, "r") as stream, os.fdopen(writer, "w") as sender:
            sender.write("KEEPALIVE\nRELEASE\n")
            sender.flush()
            self.assertTrue(runtime.wait_for_release(stream, timeout=0.1))
        reader, writer = os.pipe()
        with os.fdopen(reader, "r") as stream, os.fdopen(writer, "w"):
            self.assertFalse(runtime.wait_for_release(stream, timeout=0.01))

    def test_supervisor_lock_does_not_conflict_with_backend_state_lease(self):
        runtime = load("runtime")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with (state / "launcher.lock").open("w") as backend_lock:
                fcntl.flock(backend_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with runtime.supervisor_lock(state):
                    self.assertTrue((state / "process-supervisor.lock").exists())

    def test_operation_lock_excludes_a_second_launcher(self):
        runtime = load("runtime")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with runtime.control_lock(state):
                with self.assertRaisesRegex(RuntimeError, "operation"):
                    with runtime.control_lock(state):
                        self.fail("second launcher acquired lock")

    def test_status_never_adopts_an_unowned_process(self):
        runtime = load("runtime")
        self.assertIsNotNone(runtime, "runtime lifecycle helper missing")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / "launcher.json").write_text(json.dumps({"pid": os.getpid(), "start": "0"}))
            self.assertFalse(runtime.owned_process(state))
            self.assertEqual(runtime.stop(state), False)


class ConfigurationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI required")
    def test_compose_resolves_only_frontend_loopback_and_narrow_mounts(self):
        env = dict(
            os.environ,
            FRONTEND_UID="2001",
            FRONTEND_GID="2002",
            API_GID="1234",
            WORKBENCH_IPC_HOST="/host/eval/.wb/test/ipc",
            WORKBENCH_SOURCE_HOST="/host/clone/web/arena-workbench",
            WORKBENCH_HTTP_PORT="3333",
            COMPOSE_DISABLE_ENV_FILE="true",
        )
        base = ["docker", "compose", "--env-file", "/dev/null", "-p", "arena-wb-test", "-f", str(ROOT / "compose.yaml")]
        for dev in (False, True):
            command = base + (["-f", str(ROOT / "compose.dev.yaml")] if dev else [])
            config = json.loads(subprocess.check_output([*command, "config", "--format", "json"], env=env, text=True))
            self.assertEqual(list(config["services"]), ["frontend"])
            service = config["services"]["frontend"]
            self.assertEqual(
                service["ports"],
                [{"mode": "ingress", "host_ip": "127.0.0.1", "target": 3000, "published": "3333", "protocol": "tcp"}],
            )
            self.assertEqual(service["user"], "2001:2002")
            self.assertEqual(service["group_add"], ["1234"])
            self.assertTrue(service["read_only"])
            mounts = {m["target"]: m for m in service["volumes"]}
            self.assertEqual(
                set(mounts), {"/run/arena-api", "/app", "/app/node_modules"} if dev else {"/run/arena-api"}
            )
            self.assertTrue(mounts["/run/arena-api"]["read_only"])
            self.assertFalse(mounts["/run/arena-api"]["bind"]["create_host_path"])
            self.assertNotIn("depends_on", service)
            self.assertEqual(config["networks"]["workbench"]["driver"], "bridge")

    def test_configurations_are_narrow_nonroot_and_preserve_api(self):
        for name in (
            "Dockerfile.frontend",
            "Dockerfile.frontend.dockerignore",
            "compose.yaml",
            "compose.dev.yaml",
            "nginx.prod.conf",
            "nginx.dev.conf",
        ):
            self.assertTrue((ROOT / name).is_file(), name)
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("127.0.0.1:${WORKBENCH_HTTP_PORT:-3000}:3000", compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("API_GID", compose)
        self.assertNotIn("network_mode: host", compose)
        self.assertNotIn("docker.sock", compose)
        for mode in ("prod", "dev"):
            config = (ROOT / f"nginx.{mode}.conf").read_text()
            self.assertIn("unix:/run/arena-api/api.sock", config)
            self.assertIn("location = /api", config)
            self.assertIn("location ^~ /api/", config)
            self.assertIn("proxy_buffering off", config)
            self.assertIn("gzip off", config)
        dockerfile = (ROOT / "Dockerfile.frontend").read_text()
        self.assertIn("@sha256:", dockerfile)
        self.assertIn("npm ci", dockerfile)
        self.assertIn("AS development", dockerfile)
        self.assertIn("AS production", dockerfile)


if __name__ == "__main__":
    unittest.main()
