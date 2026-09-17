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

    def test_normal_launcher_can_explicitly_forward_paused_start(self):
        tool = load("workbench")
        config = {
            "api_user": "1000:1000",
            "runtime_repo": "/repo",
            "runtime": "a" * 64,
            "state": "/eval/.wb/test/state",
            "socket": "/eval/.wb/test/ipc/api.sock",
            "origin": "http://127.0.0.1:3010",
            "diagnostics": False,
            "start_paused": True,
        }
        with patch.object(tool, "run", return_value="") as execute:
            tool.runtime_call(config, "serve", detached=True)
        self.assertIn("--start-paused", execute.call_args.args[0])

    def test_socket_paths_and_port_range_are_validated(self):
        tool = load("workbench")
        with self.assertRaisesRegex(RuntimeError, "port"):
            tool.validate_port(0)
        with self.assertRaisesRegex(RuntimeError, "port"):
            tool.validate_port(65536)
        self.assertEqual(tool.validate_port(3000), 3000)


class RuntimeTests(unittest.TestCase):
    def test_api_only_start_preserves_healthy_api_and_spawns_only_paused_supervisor(
        self,
    ):
        runtime = load("runtime")
        self.assertTrue(hasattr(runtime, "ensure_paused"), "API-only admission is missing")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            args = Namespace(
                state_dir=str(state),
                socket=str(state / "api.sock"),
                origin="http://127.0.0.1:3010",
                diagnostics=False,
                start_paused=True,
            )
            with (
                patch.object(runtime, "prepare"),
                patch.object(runtime, "health", return_value=True),
                patch.object(runtime, "owned_process", return_value={"pid": 1}),
                patch.object(runtime.subprocess, "Popen") as spawn,
            ):
                self.assertEqual(runtime.ensure_paused(args), "healthy")
                spawn.assert_not_called()
            with (
                patch.object(runtime, "prepare"),
                patch.object(runtime, "health", return_value=False),
                patch.object(runtime, "owned_process", return_value=None),
                patch.object(runtime, "preflight") as preflight,
                patch.object(runtime.subprocess, "Popen") as spawn,
            ):
                self.assertEqual(runtime.ensure_paused(args), "starting")
                argv = spawn.call_args.args[0]
                self.assertIn("--start-paused", argv)
                self.assertIn("serve", argv)
                self.assertNotIn("stop", argv)
                preflight.assert_called_once()

    def test_paused_start_reaches_api_child_and_cli_factory_without_queue_resume(self):
        tool, runtime = load("workbench"), load("runtime")
        self.assertIn(
            "--start-paused",
            tool.api_command(
                "/state",
                "/ipc/api.sock",
                "http://127.0.0.1:3010",
                False,
                start_paused=True,
            ),
        )
        self.assertIn(
            "--start-paused",
            runtime.inherited_api_command(
                "/state",
                "/ipc/api.sock",
                "http://127.0.0.1:3010",
                False,
                start_paused=True,
            ),
        )
        # Parse package CLI as source only: host tests never import Arena modules.
        import ast

        source = ROOT.parents[1] / "isaaclab_arena_examples/agentic_environment_generation/web_api/__main__.py"
        tree = ast.parse(source.read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        self.assertTrue(
            any(any(isinstance(a, ast.Constant) and a.value == "--start-paused" for a in c.args) for c in calls)
        )
        factory = next(c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "create_app")
        self.assertTrue(
            any(
                k.arg == "start_paused" and isinstance(k.value, ast.Attribute) and k.value.attr == "start_paused"
                for k in factory.keywords
            )
        )

    def test_preflight_allows_time_wait_but_refuses_live_listener(self):
        runtime = load("runtime")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with socket.socket() as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                port = listener.getsockname()[1]
                with patch.object(runtime, "prepare"):
                    with self.assertRaisesRegex(RuntimeError, "unavailable"):
                        runtime.preflight(state, state / "api.sock", port)
                with socket.create_connection(("127.0.0.1", port), timeout=2) as peer:
                    connection, _ = listener.accept()
                    connection.close()
                    self.assertEqual(peer.recv(1), b"")
            with socket.socket() as plain:
                with self.assertRaises(OSError):
                    plain.bind(("127.0.0.1", port))
            with patch.object(runtime, "prepare"):
                runtime.preflight(state, state / "api.sock", port)

    def test_api_child_uses_runtime_interpreter_not_an_early_exiting_shell_wrapper(self):
        runtime = load("runtime")
        command = runtime.inherited_api_command("/state", "/ipc/api.sock", "http://127.0.0.1:3001", True)
        self.assertEqual(command[0], runtime.sys.executable)
        self.assertEqual(
            command[1:], load("workbench").api_command("/state", "/ipc/api.sock", "http://127.0.0.1:3001", True)[1:]
        )

    def test_health_read_is_bounded_even_for_an_unrelated_listener(self):
        runtime = load("runtime")
        from unittest.mock import MagicMock

        connection = MagicMock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = b'{"status":"ok"}'
        with (
            patch.object(runtime.http.client, "HTTPConnection", return_value=connection),
            patch.object(runtime.socket, "socket"),
        ):
            self.assertTrue(runtime.health("/unused/api.sock", "http://127.0.0.1:3010"))
        connection.getresponse.return_value.read.assert_called_once_with(4096)

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
    def test_control_overlay_resolves_without_arena_or_docker_mount(self):
        env = dict(
            os.environ,
            FRONTEND_UID="2001",
            FRONTEND_GID="2002",
            API_GID="1234",
            CONTROL_GID="2003",
            WORKBENCH_IPC_HOST="/host/api-ipc",
            WORKBENCH_CONTROL_IPC_HOST="/host/operator/ipc",
            FRONTEND_MEMORY_BYTES="4294967296",
            COMPOSE_DISABLE_ENV_FILE="true",
        )
        command = [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(ROOT / "compose.yaml"),
            "-f",
            str(ROOT / "compose.control.yaml"),
            "config",
            "--format",
            "json",
        ]
        config = json.loads(subprocess.check_output(command, env=env, text=True))
        self.assertEqual(set(config["services"]), {"frontend"})
        service = config["services"]["frontend"]
        mounts = {m["target"]: m for m in service["volumes"]}
        self.assertEqual(set(mounts), {"/run/arena-api", "/run/arena-control"})
        self.assertTrue(mounts["/run/arena-control"]["read_only"])
        self.assertFalse(mounts["/run/arena-control"]["bind"]["create_host_path"])
        self.assertEqual(set(service["group_add"]), {"1234", "2003"})

    def test_control_proxy_keeps_same_origin_and_only_narrow_socket_mount(self):
        for mode in ("dev", "prod"):
            text = (ROOT / f"nginx.{mode}.conf").read_text()
            self.assertIn(
                "upstream arena_control { server unix:/run/arena-control/control.sock; }",
                text,
            )
            self.assertIn("location ^~ /control/", text)
            block = text.split("location ^~ /control/", 1)[1].split("}", 1)[0]
            self.assertIn("proxy_set_header Host $http_host", block)
            self.assertIn('proxy_set_header X-Forwarded-Host ""', block)
            self.assertIn("proxy_cache off", block)
            self.assertIn("access_log off", block)
        text = (ROOT / "compose.control.yaml").read_text()
        self.assertIn("/run/arena-control", text)
        self.assertIn("create_host_path: false", text)
        self.assertIn("read_only: true", text)
        self.assertNotIn("docker.sock", text)

    def test_observation_and_stop_do_not_require_capacity_discovery(self):
        tool = load("workbench")
        config = dict(
            host_root="/host/clone",
            ipc_host="/host/ipc",
            port=3010,
            frontend_uid=1000,
            frontend_gid=1234,
            api_gid=1234,
            project="arena-test",
            dev=True,
        )
        for command in ("ps", "stop"):
            with (
                self.subTest(command=command),
                patch.object(
                    tool, "resource_environment", side_effect=RuntimeError("capacity unavailable")
                ) as capacity,
                patch.object(tool, "run", return_value="ok") as execute,
            ):
                self.assertEqual(tool.compose(config, command), "ok")
                capacity.assert_not_called()
                self.assertEqual(execute.call_args.kwargs["env"]["FRONTEND_MEMORY_BYTES"], "6291456")

    def test_explicit_stop_attempts_api_cleanup_when_frontend_stop_fails(self):
        tool = load("workbench")
        with (
            patch.object(tool, "compose", side_effect=RuntimeError("frontend stop failed")),
            patch.object(tool, "runtime_call", return_value="stopped") as runtime,
        ):
            with self.assertRaisesRegex(RuntimeError, "frontend stop failed"):
                tool.lifecycle({}, "stop")
            runtime.assert_called_once_with({}, "stop")

    def test_start_rollback_attempts_api_cleanup_when_frontend_stop_fails(self):
        tool = load("workbench")

        def compose(config, command, *args):
            if command in ("up", "stop"):
                raise RuntimeError(f"{command} failed")
            return ""

        def runtime(config, command, **kwargs):
            if command == "status":
                return json.dumps({"owned": runtime_calls.call_count > 1, "healthy": True})
            return ""

        with (
            patch.object(tool, "compose", side_effect=compose),
            patch.object(tool, "runtime_call", side_effect=runtime) as runtime_calls,
        ):
            with self.assertRaisesRegex(RuntimeError, "stop failed"):
                tool.lifecycle({}, "start")
            self.assertEqual(runtime_calls.call_args.args, ({}, "stop"))
            self.assertTrue(any(call.args == ({}, "serve") for call in runtime_calls.call_args_list))

    def test_launcher_overwrites_inherited_limits_with_fresh_daemon_budget(self):
        tool = load("workbench")
        config = dict(
            host_root="/host/clone",
            ipc_host="/host/ipc",
            port=3010,
            frontend_uid=1000,
            frontend_gid=1234,
            api_gid=1234,
            project="arena-test",
            dev=True,
        )
        budget = {"FRONTEND_MEMORY_BYTES": "4294967296", "FRONTEND_PIDS_LIMIT": "256"}
        with (
            patch.dict(os.environ, FRONTEND_MEMORY_BYTES="999999999999"),
            patch.object(tool, "resource_environment", create=True, return_value=budget) as discover,
            patch.object(tool, "run", return_value="configured") as execute,
        ):
            self.assertEqual(tool.compose(config, "config", "--quiet"), "configured")
        discover.assert_called_once_with()
        for key, value in budget.items():
            self.assertEqual(execute.call_args.kwargs["env"][key], value)
        with (
            patch.object(tool, "resource_environment", create=True, side_effect=RuntimeError("no capacity")),
            patch.object(tool, "run") as execute,
        ):
            with self.assertRaisesRegex(RuntimeError, "no capacity"):
                tool.compose(config, "config")
            execute.assert_not_called()

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
            FRONTEND_MEMORY_BYTES="4294967296",
            FRONTEND_PIDS_LIMIT="256",
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
            self.assertEqual(int(service["mem_limit"]), 4294967296)
            self.assertEqual(int(service["memswap_limit"]), 4294967296)
            self.assertEqual(int(service["pids_limit"]), 256)
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
