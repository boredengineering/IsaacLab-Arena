# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Host-only control tests: fake Docker, private temporary files, owned UDS."""

import copy
import hashlib
import http.client
import importlib.util
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).parent


def load():
    path = HERE / "control.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("control", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def profile(root):
    services = {}
    for index, name in enumerate(("arena", "neo4j", "gr00t"), 1):
        services[name] = {
            "identity": {
                "Id": str(index) * 64,
                "Image": "sha256:" + "a" * 64,
                "User": "1000:1000",
                "Entrypoint": ["/approved-offline-start"],
                "Cmd": [],
                "WorkingDir": "/",
                "NetworkMode": "host",
                "Mounts": [],
                "Memory": 4096,
                "MemorySwap": 4096,
                "PidsLimit": 256,
                "Privileged": False,
                "ReadonlyRootfs": True,
                "EnvSha256": "e" * 64,
            },
            "startup_only": True,
            "offline": True,
            "cached_weights": True,
        }
    services["arena"]["identity"]["Mounts"] = [
        {
            "Type": "bind",
            "Source": str(root / "repo"),
            "Destination": "/repo",
            "RW": True,
        },
        {
            "Type": "bind",
            "Source": str(root / "eval"),
            "Destination": "/eval",
            "RW": True,
        },
    ]
    services["neo4j"]["identity"]["Mounts"] = [
        {
            "Type": "volume",
            "Source": "/approved/data",
            "Destination": "/data",
            "RW": True,
        },
    ]
    services["gr00t"]["identity"]["Mounts"] = [
        {
            "Type": "bind",
            "Source": "/approved/models",
            "Destination": "/models",
            "RW": False,
        },
    ]
    files = []
    for name in ("docker/workbench/runtime.py", "docker/workbench/workbench.py", "docker/resource_limits.py"):
        path = root / "repo" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("# synthetic reviewed startup code\n")
        files.append(reviewed_file("arena", "/repo/" + name, path))
    return {
        "schema_version": 1,
        "startup_review": {"mode": "image-baked-v1", "files": files},
        "origin": "http://127.0.0.1:3010",
        "expected_policy": "nvidia/GR00T-N1.6-DROID",
        "connections": {
            "neo4j_uri": "bolt://127.0.0.1:7687",
            "neo4j_database": "neo4j",
            "gr00t_host": "127.0.0.1",
            "gr00t_port": 5555,
        },
        "services": services,
        "api": {
            "uid": 1000,
            "gid": 1000,
            "repo": "/repo",
            "state": "/eval/.wb/test/state",
            "socket": "/eval/.wb/test/ipc/api.sock",
            "environment": {},
        },
        "storage": {
            "ipc_host": str(root / "eval/.wb/test/ipc"),
            "state_host": str(root / "eval/.wb/test/state"),
            "create": [
                str(root / "eval/.wb"),
                str(root / "eval/.wb/test"),
                str(root / "eval/.wb/test/ipc"),
                str(root / "eval/.wb/test/state"),
            ],
        },
        "resources": {
            "min_ram_available_bytes": 1024,
            "min_gpu_free_mib": 1024,
            "reviewed_until": 9999999999,
        },
        "limits": {"docker_seconds": 15, "startup_seconds": 600, "receipts": 32},
        "frontend": {
            "image": "sha256:" + "f" * 64,
            "uid": 1000,
            "gid": 1000,
            "memory_bytes": 104857600,
            "pids_limit": 256,
            "name": "approved-workbench",
        },
    }


def reviewed_file(service, container_path, path):
    info = path.stat()
    return {
        "service": service,
        "container_path": container_path,
        "host_path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "device": info.st_dev,
        "inode": info.st_ino,
    }


def observation_profile(root):
    value = profile(root)
    value["startup_review"] = {"mode": "observation-only-v1", "files": []}
    for service in value["services"].values():
        service.update(startup_only=False, offline=False, cached_weights=False)
        service["identity"].update(
            Entrypoint=None,
            Cmd=None,
            EnvSha256=None,
            Memory=0,
            MemorySwap=0,
            PidsLimit=None,
            ReadonlyRootfs=False,
        )
    return value


class ObservationTests(unittest.TestCase):
    def test_observation_opaque_mount_metadata_installs_without_source_reads_or_probes(self):
        from unittest import mock

        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = observation_profile(root)
            value["startup_review"]["mount_metadata"] = []
            for service, name, kind in (
                ("gr00t", "models", "bind"),
                ("neo4j", "data", "volume"),
                ("neo4j", "logs", "volume"),
            ):
                opaque = root / "opaque" / name
                opaque.mkdir(parents=True)
                info = opaque.stat()
                mount = {"Source": str(opaque), "Destination": "/" + name, "Type": kind, "RW": True}
                mounts = value["services"][service]["identity"]["Mounts"]
                if name == "logs":
                    mounts.append(mount)
                else:
                    mounts[0] = mount
                value["startup_review"]["mount_metadata"].append(
                    {"Source": str(opaque), "st_dev": info.st_dev, "st_ino": info.st_ino}
                )
            home = root / "installed"
            source = HERE / "control.py"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            real_stat = Path.stat

            def denied(path, *args, **kwargs):
                if path.is_relative_to(root / "opaque"):
                    raise PermissionError(13, "Permission denied", str(path))
                return real_stat(path, *args, **kwargs)

            with (
                mock.patch.object(Path, "stat", denied),
                mock.patch.object(tool, "open_reviewed_code", side_effect=AssertionError("source content read")),
                mock.patch.object(tool.Docker, "call", side_effect=AssertionError("Docker probe")),
            ):
                tool.install(home, value, source, digest)
                self.assertEqual(tool.load_installation(home)["profile"], value)
                docker = FakeDocker(value)
                controller = tool.Controller(value, home / "state", docker)
                self.assertIs(controller.observe()["startup_allowed"], False)
                self.assertTrue(all(call[0] == "inspect" for call in docker.calls))
                before = list(docker.calls)
                with self.assertRaises(tool.ControlError) as caught:
                    controller.start({"request_id": "a" * 32, "profile_revision": controller.revision})
                self.assertEqual((caught.exception.status, caught.exception.code), (403, "startup_disabled"))
                self.assertEqual(docker.calls, before)

    def test_observation_mount_metadata_rechecks_accessible_sources_before_observing(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = observation_profile(root)
            source = root / "models"
            source.mkdir()
            info = source.stat()
            value["services"]["gr00t"]["identity"]["Mounts"][0]["Source"] = str(source)
            value["startup_review"]["mount_metadata"] = [
                {"Source": str(source), "st_dev": info.st_dev, "st_ino": info.st_ino}
            ]
            controller = tool.Controller(value, root, FakeDocker(value))
            self.assertEqual(controller.observe()["services"][2]["status"], "stopped")
            source.rename(root / "previous-models")
            source.mkdir()
            before = list(controller.docker.calls)
            self.assertTrue(all(s["status"] == "unknown" for s in controller.observe()["services"]))
            self.assertEqual(controller.docker.calls, before)
            with self.assertRaisesRegex(ValueError, "mount_metadata_changed"):
                tool.validate_profile(value)

    def test_mount_metadata_cannot_be_used_with_a_different_identity_mode(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            source = root / "repo"
            info = source.stat()
            review = {
                "mode": "observation-only-v1",
                "files": [],
                "mount_metadata": [{"Source": str(source), "st_dev": info.st_dev, "st_ino": info.st_ino}],
            }
            with self.assertRaisesRegex(ValueError, "invalid_startup_review"):
                tool.validate_identity(value["services"]["arena"]["identity"], "image-baked-v1", review)

    def test_observation_mount_metadata_rejects_protected_aliases_with_real_inode_pairs(self):
        from unittest import mock

        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.mkdir()
            protected = root / "private"
            protected.mkdir()
            home = protected / "control"
            home.mkdir()
            target = home / "daemon.sock"
            target.touch()
            source = str(root / "opaque" / "leaf")
            real_stat = Path.stat

            def denied(path, *args, **kwargs):
                if path.is_relative_to(root / "opaque"):
                    raise PermissionError(13, "Permission denied", str(path))
                return real_stat(path, *args, **kwargs)

            for alias in (outside, target, home, protected, root):
                info = alias.stat()
                review = {
                    "mode": "observation-only-v1",
                    "files": [],
                    "mount_metadata": [{"Source": source, "st_dev": info.st_dev, "st_ino": info.st_ino}],
                }
                with self.subTest(alias=alias), mock.patch.object(Path, "stat", denied):
                    self.assertEqual(tool.mount_contains(source, target, review), alias != outside)
                    value = observation_profile(root)
                    value["startup_review"] = review
                    value["services"]["gr00t"]["identity"]["Mounts"][0]["Source"] = source
                    if alias in (home, protected, root):
                        with self.assertRaisesRegex(ValueError, "installation_inside_service_mount"):
                            tool.protect_installation(home, value)
                    elif alias == outside:
                        tool.protect_installation(home, value)

    def test_observation_mount_metadata_requires_exact_known_typed_entries(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = observation_profile(root)
            source = root / "repo"
            info = source.stat()
            entry = {"Source": str(source), "st_dev": info.st_dev, "st_ino": info.st_ino}
            value["startup_review"]["mount_metadata"] = [entry]
            self.assertEqual(tool.validate_profile(value), value)
            for entries in (
                None,
                {},
                [None],
                [entry, entry],
                [entry] * 129,
                [dict(entry, extra=True)],
                [{k: v for k, v in entry.items() if k != "st_dev"}],
                [dict(entry, Source=str(root / "foreign"))],
                [dict(entry, Source=str(source) + "/")],
                [dict(entry, Source=str(source) + "/../repo")],
                [dict(entry, Source=[])],
                *([dict(entry, st_dev=v)] for v in (False, None, "0", -1, 0.0, 2**64)),
                *([dict(entry, st_ino=v)] for v in (True, None, "1", 0, -1, 1.0, 2**64)),
            ):
                bad = copy.deepcopy(value)
                bad["startup_review"]["mount_metadata"] = entries
                with self.subTest(entries=entries), self.assertRaises(ValueError):
                    tool.validate_profile(bad)
            for mode in ("image-baked-v1", "operator-reviewed-existing-v1"):
                for entries in ([], [entry]):
                    bad = profile(root)
                    bad["startup_review"].update(mode=mode, mount_metadata=entries)
                    with self.subTest(mode=mode, entries=entries), self.assertRaises(ValueError):
                        tool.validate_profile(bad)
            for changes in ({"files": [entry]}, {"extra": True}):
                bad = copy.deepcopy(value)
                bad["startup_review"].update(changes)
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    tool.validate_profile(bad)
            for flag in ("startup_only", "offline", "cached_weights"):
                bad = copy.deepcopy(value)
                bad["services"]["arena"][flag] = True
                with self.subTest(flag=flag), self.assertRaises(ValueError):
                    tool.validate_profile(bad)

    def test_observation_mount_metadata_fallback_is_only_source_permission_error(self):
        from unittest import mock

        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = observation_profile(root)
            source = root / "models"
            source.mkdir()
            info = source.stat()
            value["services"]["gr00t"]["identity"]["Mounts"][0]["Source"] = str(source)
            entry = {"Source": str(source), "st_dev": info.st_dev, "st_ino": info.st_ino}
            real_stat = Path.stat
            for failure in (PermissionError(13, "denied"), FileNotFoundError(2, "missing"), OSError(5, "I/O")):

                def denied(path, *args, **kwargs):
                    if path == source:
                        raise failure
                    return real_stat(path, *args, **kwargs)

                with self.subTest(failure=failure), mock.patch.object(Path, "stat", denied):
                    if isinstance(failure, PermissionError):
                        with self.assertRaises(PermissionError):
                            tool.validate_profile(value)
                        normal = profile(root)
                        normal["services"]["gr00t"]["identity"]["Mounts"][0]["Source"] = str(source)
                        for mode in ("image-baked-v1", "operator-reviewed-existing-v1"):
                            normal["startup_review"]["mode"] = mode
                            with self.assertRaises(PermissionError):
                                tool.validate_profile(normal)
                    pinned = copy.deepcopy(value)
                    pinned["startup_review"]["mount_metadata"] = [entry]
                    if isinstance(failure, PermissionError):
                        self.assertEqual(tool.validate_profile(pinned), pinned)
                    else:
                        with self.assertRaises(type(failure)):
                            tool.validate_profile(pinned)
            review = dict(value["startup_review"], mount_metadata=[entry])
            target = root / "private"

            def target_denied(path, *args, **kwargs):
                if path in (source, target):
                    raise PermissionError(13, "denied", str(path))
                return real_stat(path, *args, **kwargs)

            with mock.patch.object(Path, "stat", target_denied), self.assertRaises(PermissionError):
                tool.mount_contains(str(source), target, review)
            real_resolve = Path.resolve

            def resolve_denied(path, *args, **kwargs):
                if path == source:
                    raise PermissionError(13, "denied", str(path))
                return real_resolve(path, *args, **kwargs)

            with mock.patch.object(Path, "resolve", resolve_denied), self.assertRaises(PermissionError):
                tool.mount_contains(str(source), target, review)

    def test_observation_mount_metadata_does_not_bypass_lexical_or_symlink_exclusions(self):
        from unittest import mock

        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = observation_profile(root)
            actual = root / "actual"
            actual.mkdir()
            info = actual.stat()
            alias = root / "alias"
            alias.symlink_to(actual, target_is_directory=True)
            for source in (alias, alias / "child"):
                (actual / "child").mkdir(exist_ok=True)
                metadata = source.stat()
                value["services"]["gr00t"]["identity"]["Mounts"][0]["Source"] = str(source)
                value["startup_review"]["mount_metadata"] = [
                    {"Source": str(source), "st_dev": metadata.st_dev, "st_ino": metadata.st_ino}
                ]
                with self.subTest(source=source), self.assertRaisesRegex(ValueError, "symlink_storage"):
                    tool.validate_profile(value)
            source = root / "opaque"
            review = {
                "mode": "observation-only-v1",
                "files": [],
                "mount_metadata": [{"Source": str(source), "st_dev": info.st_dev, "st_ino": info.st_ino}],
            }
            real_stat = Path.stat

            def denied(path, *args, **kwargs):
                if path == source:
                    raise PermissionError(13, "denied", str(path))
                return real_stat(path, *args, **kwargs)

            with mock.patch.object(Path, "stat", denied):
                self.assertTrue(tool.mount_contains(str(source), source / "private", review))
                self.assertTrue(tool.mount_contains(str(source), root, review, bidirectional=True))

    def test_observation_retains_unknown_receipts_without_reconcile_or_reissue(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = observation_profile(root)
            receipt = {
                "request_id": "a" * 32,
                "profile_revision": tool.profile_revision(value),
                "status": "unknown",
                "code": "start_unknown",
            }
            tool.atomic_private(root / "receipts.json", [receipt])
            docker = FakeDocker(value)
            for record in docker.records.values():
                record["status"] = "running"
            docker.healthy = True
            controller = tool.Controller(value, root, docker)
            self.assertEqual(controller.observe(receipt["request_id"])["operation"], receipt)
            before = list(docker.calls)
            with self.assertRaises(tool.ControlError):
                controller.start({k: receipt[k] for k in ("request_id", "profile_revision")})
            with self.assertRaises(tool.ControlError):
                controller._run(receipt)
            self.assertEqual(docker.calls, before)
            self.assertEqual(json.loads(tool.private_file(root / "receipts.json")), [receipt])
            self.assertTrue(all(c[0] == "inspect" for c in docker.calls))

    def test_observation_preserves_daemon_installation_and_ipc_exclusions(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = observation_profile(root)
            for source in ("/", "/var/run", "/var/run/docker.sock"):
                bad = copy.deepcopy(value)
                bad["services"]["arena"]["identity"]["Mounts"][0]["Source"] = source
                with self.subTest(source=source), self.assertRaisesRegex(ValueError, "docker_mount_forbidden"):
                    tool.validate_profile(bad)
            home = root / "installed"
            value["services"]["gr00t"]["identity"]["Mounts"][0]["Source"] = str(home)
            with self.assertRaisesRegex(ValueError, "installation_inside_service_mount"):
                tool.protect_installation(home, value)
            value = observation_profile(root)
            controller = tool.Controller(
                value, root, FakeDocker(value), guard=lambda: tool.prepare_api_storage(value, create=False)
            )
            self.assertTrue(all(s["status"] == "unknown" for s in controller.observe()["services"]))
            self.assertFalse(controller.docker.calls)
            self.assertFalse(Path(value["storage"]["ipc_host"]).exists())

    def test_observation_known_field_drift_including_boolean_zero_never_matches(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = observation_profile(root)
            for field, changed in (
                ("Memory", False),
                ("MemorySwap", 0.0),
                ("Privileged", 0),
                ("ReadonlyRootfs", 0),
                ("User", "root"),
                ("NetworkMode", "bridge"),
                ("Image", "sha256:" + "b" * 64),
                ("Mounts", []),
            ):
                docker = FakeDocker(value)
                docker.records["1" * 64]["identity"][field] = changed
                controller = tool.Controller(value, root, docker)
                with self.subTest(field=field):
                    self.assertEqual(controller.observe()["services"][0]["status"], "mismatch")
                    self.assertIs(controller.observe()["startup_allowed"], False)

    def test_installed_observation_pairs_and_rejects_http_escalation_without_research_writes(self):
        self._installed_observation_http()

    def test_installed_observation_mount_metadata_never_probes_or_escalates_over_http(self):
        self._installed_observation_http(opaque=True)

    def _installed_observation_http(self, *, opaque=False):
        tool = load()
        from unittest import mock

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = observation_profile(root)
            home = root / "installed"
            source = HERE / "control.py"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            (root / "eval").mkdir()
            if opaque:
                model = root / "opaque" / "models"
                model.mkdir(parents=True)
                info = model.stat()
                value["services"]["gr00t"]["identity"]["Mounts"][0]["Source"] = str(model)
                value["startup_review"]["mount_metadata"] = [
                    {"Source": str(model), "st_dev": info.st_dev, "st_ino": info.st_ino}
                ]
                real_stat = Path.stat

                def denied(path, *args, **kwargs):
                    if path.is_relative_to(root / "opaque"):
                        raise PermissionError(13, "Permission denied", str(path))
                    return real_stat(path, *args, **kwargs)

                patcher = mock.patch.object(Path, "stat", denied)
                patcher.start()
                self.addCleanup(patcher.stop)
            tool.prepare_api_storage(value, create=True)
            journal = Path(value["storage"]["state_host"]) / "journal.sqlite3"
            journal.write_bytes(b"synthetic retained research state")
            before = journal.stat()
            calls, forbidden = [], []

            def run(argv, timeout):
                calls.append(argv)
                self.assertEqual(argv[3], "inspect")
                for field in (".Config.Env", ".Config.Entrypoint", ".Config.Cmd"):
                    self.assertNotIn(field, argv[7])
                identity = next(
                    copy.deepcopy(s["identity"]) for s in value["services"].values() if s["identity"]["Id"] == argv[-1]
                )
                for field in ("EnvSha256", "Entrypoint", "Cmd"):
                    del identity[field]
                return json.dumps(dict(identity, State={"Status": "running" if argv[-1] == "1" * 64 else "exited"}))

            def prohibited(*args):
                forbidden.append(args)
                raise AssertionError("observation attempted execution or code/credential read")

            tool.open_reviewed_code = prohibited
            docker = tool.Docker(run=run)
            docker.api_status = docker.api_start = docker.resources = docker.start = prohibited
            with mock.patch.object(tool.hashlib, "sha256", side_effect=prohibited):
                record = docker.inspect("1" * 64, observation_only=True)
            for field in ("EnvSha256", "Entrypoint", "Cmd"):
                self.assertIsNone(record["identity"][field])
            tool.install(home, value, source, digest)
            self.assertEqual(tool.load_installation(home)["profile"], value)
            with tool.installed_server(home, docker=docker) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                cookie, csrf = None, None

                def request(method, path, body=None, **overrides):
                    connection = http.client.HTTPConnection("127.0.0.1:3010", timeout=2)
                    connection.sock = socket.socket(socket.AF_UNIX)
                    connection.sock.settimeout(2)
                    connection.sock.connect(str(home / "ipc/control.sock"))
                    headers = {"Origin": value["origin"], "Content-Type": "application/json"}
                    if cookie:
                        headers["Cookie"] = cookie
                    if csrf:
                        headers["X-CSRF-Token"] = csrf
                    headers.update(overrides)
                    connection.request(
                        method, path, body=json.dumps(body) if body is not None else None, headers=headers
                    )
                    response = connection.getresponse()
                    result = response.status, json.loads(response.read()), response.getheader("Set-Cookie")
                    connection.close()
                    return result

                try:
                    token = json.loads(tool.private_file(home / "pairing.json"))["pairing_token"]
                    status, session, cookie = request("POST", "/control/session", {"pairing_token": token})
                    self.assertEqual(status, 200)
                    cookie = cookie.split(";", 1)[0]
                    csrf = session["csrf_token"]
                    status, observed, _ = request("GET", "/control/research-services")
                    self.assertEqual(status, 200)
                    self.assertEqual([s["status"] for s in observed["services"]], ["running", "stopped", "stopped"])
                    self.assertEqual(observed["api"], "unknown")
                    self.assertIs(observed["startup_allowed"], False)
                    body = {"request_id": "a" * 32, "profile_revision": observed["profile_revision"]}
                    inspected = len(calls)
                    for revision in (body["profile_revision"], "f" * 64):
                        response = request(
                            "POST", "/control/research-services/start", dict(body, profile_revision=revision)
                        )
                        self.assertEqual(response[:2], (403, {"error": "startup_disabled"}))
                    for field in (
                        "mode",
                        "startup_review",
                        "mount_metadata",
                        "startup_allowed",
                        "startup_only",
                        "offline",
                        "cached_weights",
                    ):
                        self.assertEqual(
                            request("POST", "/control/research-services/start", dict(body, **{field: True}))[0], 400
                        )
                        self.assertEqual(request("GET", "/control/research-services?" + field + "=true")[0], 400)
                    for headers, error in (
                        ({"Host": "evil.test"}, "wrong_host"),
                        ({"Origin": "http://evil.test"}, "wrong_origin"),
                        ({"X-CSRF-Token": "wrong"}, "csrf_failed"),
                    ):
                        self.assertEqual(
                            request("POST", "/control/research-services/start", body, **headers)[:2],
                            (403, {"error": error}),
                        )
                    self.assertEqual(request("GET", "/control/research-services?request_id=" + "a" * 32)[0], 404)
                    # A changed installed profile cannot turn the pinned controller into a starter.
                    changed = copy.deepcopy(value)
                    if opaque:
                        changed["startup_review"]["mount_metadata"][0]["st_ino"] += 1
                    else:
                        changed["resources"]["reviewed_until"] += 1
                    self.assertNotEqual(tool.profile_revision(changed), tool.profile_revision(value))
                    tool.atomic_private(home / "profile.json", changed)
                    self.assertEqual(request("POST", "/control/research-services/start", body)[0], 403)
                    server.controller.observation_after = 0
                    observed = request("GET", "/control/research-services")[1]
                    self.assertIs(observed["startup_allowed"], False)
                    self.assertEqual(observed["api"], "unknown")
                    self.assertTrue(all(s["status"] == "unknown" for s in observed["services"]))
                    self.assertEqual(len(calls), inspected)
                    self.assertEqual(request("DELETE", "/control/session")[0], 200)
                    self.assertEqual(request("GET", "/control/research-services")[0], 401)
                    self.assertFalse((home / "state/receipts.json").exists())
                finally:
                    server.shutdown()
                    thread.join(3)
            self.assertFalse(forbidden)
            self.assertEqual(journal.read_bytes(), b"synthetic retained research state")
            self.assertEqual((journal.stat().st_mtime_ns, journal.stat().st_ino), (before.st_mtime_ns, before.st_ino))

    def test_observation_frontend_bootstrap_keeps_safe_projection_and_fixed_target(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = observation_profile(root)
            target = "f" * 64
            calls = []
            running = False

            def run(argv, timeout):
                nonlocal running
                calls.append(argv)
                action = argv[3]
                if action == "create":
                    self.assertEqual(argv[-1], value["frontend"]["image"])
                    self.assertIn("--pull=never", argv)
                    return target
                self.assertEqual(argv[-1], target)
                if action == "start":
                    running = True
                    return target
                self.assertEqual(action, "inspect")
                for forbidden in (".Config.Env", ".Config.Cmd", ".Config.Entrypoint"):
                    self.assertNotIn(forbidden, argv[7])
                identity = copy.deepcopy(value["services"]["arena"]["identity"])
                identity.update(Id=target, Image=value["frontend"]["image"])
                for field in ("EnvSha256", "Entrypoint", "Cmd"):
                    del identity[field]
                return json.dumps(dict(identity, State={"Status": "running" if running else "created"}))

            docker = tool.Docker(run=run)
            self.assertEqual(tool.bootstrap_frontend(root, value, docker), target)
            self.assertEqual(tool.bootstrap_frontend(root, value, docker), target)
            self.assertEqual([c[3] for c in calls if c[3] != "inspect"], ["create", "start"])

    def test_observation_projects_no_secrets_and_never_dispatches_start_or_probes(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = observation_profile(root)
            calls, tasks = [], []
            records = {s["identity"]["Id"]: copy.deepcopy(s["identity"]) for s in value["services"].values()}
            status = "exited"

            def run(argv, timeout):
                calls.append(argv)
                self.assertEqual(argv[:3], ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock"])
                self.assertEqual(argv[3:7], ["inspect", "--type", "container", "--format"])
                projection = argv[7]
                for forbidden in (".Config.Env", ".Config.Cmd", ".Config.Entrypoint", "json .Config}}", "json .}}"):
                    self.assertNotIn(forbidden, projection)
                self.assertNotIn("json .State}}", projection)
                identity = copy.deepcopy(records[argv[-1]])
                for field in ("EnvSha256", "Entrypoint", "Cmd"):
                    del identity[field]
                return json.dumps(dict(identity, State={"Status": status}))

            docker = tool.Docker(run=run)
            controller = tool.Controller(value, root, docker, submit=tasks.append)
            for status in ("exited", "running"):
                observed = controller.observe()
                self.assertEqual(
                    [s["status"] for s in observed["services"]], ["stopped" if status == "exited" else "running"] * 3
                )
                self.assertEqual(observed["api"], "unknown")
                self.assertIs(observed["startup_allowed"], False)
                self.assertEqual(
                    set(observed),
                    {
                        "schema_version",
                        "profile_revision",
                        "expected_policy",
                        "services",
                        "api",
                        "startup_allowed",
                        "operation",
                    },
                )
            before = list(calls)
            for revision in (controller.revision, "f" * 64):
                with self.assertRaises(tool.ControlError) as refused:
                    controller.start({"request_id": "a" * 32, "profile_revision": revision})
                self.assertEqual(refused.exception.code, "startup_disabled")
            self.assertEqual(calls, before)
            self.assertFalse(tasks)
            self.assertFalse(controller.path.exists())
            self.assertEqual(docker.api_status(value), "unknown")
            with self.assertRaises(tool.ControlError):
                docker.api_start(value)
            self.assertFalse(docker.resources(value))
            self.assertEqual(calls, before)
            # Fixed startup capability cannot be escalated by mutable current flags/mode.
            for service in controller.profile["services"].values():
                service.update(startup_only=True, offline=True, cached_weights=True)
            controller.profile["startup_review"]["mode"] = "operator-reviewed-existing-v1"
            with self.assertRaises(tool.ControlError):
                controller.start({"request_id": "b" * 32, "profile_revision": controller.revision})
            self.assertIs(controller.observe()["startup_allowed"], False)
            self.assertEqual(calls, before)

    def test_private_observation_contract_accepts_only_honest_known_identity(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            value = observation_profile(Path(directory))
            self.assertEqual(tool.validate_profile(value), value)
            tool.verify_reviewed_files(value)
            for field in ("startup_only", "offline", "cached_weights"):
                for flag in (True, 0, None, "false"):
                    bad = copy.deepcopy(value)
                    bad["services"]["arena"][field] = flag
                    with self.subTest(field=field, flag=flag), self.assertRaises(ValueError):
                        tool.validate_profile(bad)
            for field, invalid in (
                ("Id", "same-name"),
                ("Image", "latest"),
                ("User", None),
                ("NetworkMode", None),
                ("WorkingDir", None),
                ("Mounts", None),
                ("Memory", False),
                ("Memory", -1),
                ("MemorySwap", "0"),
                ("PidsLimit", False),
                ("Privileged", True),
                ("ReadonlyRootfs", 0),
                ("EnvSha256", "e" * 64),
                ("Entrypoint", []),
                ("Cmd", []),
            ):
                bad = copy.deepcopy(value)
                bad["services"]["arena"]["identity"][field] = invalid
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    tool.validate_profile(bad)
            for mode in ("image-baked-v1", "operator-reviewed-existing-v1", "observation", None):
                bad = copy.deepcopy(value)
                bad["startup_review"]["mode"] = mode
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    tool.validate_profile(bad)
            for mode in ("image-baked-v1", "operator-reviewed-existing-v1"):
                for field, invalid in (
                    ("EnvSha256", None),
                    ("Entrypoint", None),
                    ("Cmd", None),
                    ("Memory", 0),
                    ("MemorySwap", 0),
                    ("PidsLimit", None),
                ):
                    bad = profile(Path(directory))
                    bad["startup_review"]["mode"] = mode
                    bad["services"]["arena"]["identity"][field] = invalid
                    with self.subTest(mode=mode, field=field), self.assertRaises(ValueError):
                        tool.validate_profile(bad)
                bad = profile(Path(directory))
                bad["startup_review"] = {"mode": mode, "files": []}
                with self.subTest(mode=mode, field="files"), self.assertRaises(ValueError):
                    tool.validate_profile(bad)
            # Observation makes no startup-code attestation, even if sources are offered.
            value["startup_review"]["files"] = profile(Path(directory))["startup_review"]["files"]
            with self.assertRaises(ValueError):
                tool.validate_profile(value)


class MountProbeRun:
    """Synthetic daemon boundary; never invokes Docker or reads mounted data."""

    def __init__(self, tool):
        self.tool = tool
        self.calls = []
        self.target = "c" * 64
        self.image = "sha256:" + "b" * 64
        self.exists = False
        self.name = self.label = None
        self.volumes = None
        self.output = "42 73\n"
        self.failure = None

    def __call__(self, argv, timeout):
        self.calls.append((argv, timeout))
        args = argv[3:]
        action = args[0]
        if action == "image":
            return json.dumps({"Id": self.image, "Volumes": self.volumes})
        if action == "create":
            self.name = args[args.index("--name") + 1]
            self.label = args[args.index("--label") + 1]
            self.exists = True
            if self.failure == "create_ack":
                raise TimeoutError()
            return self.target
        if action == "inspect":
            key, value = self.label.split("=", 1)
            return json.dumps({"Id": self.target, "Name": "/" + self.name, "Labels": {key: value}})
        if action == "start":
            if self.failure == "start":
                raise TimeoutError()
            return self.output
        if action == "wait":
            return "0"
        if action == "rm":
            if self.failure == "cleanup":
                raise TimeoutError()
            self.exists = False
            return self.target
        if action == "ps":
            return self.target if self.exists else ""
        raise AssertionError("unexpected Docker operation: " + repr(args))


class MountProbeTests(unittest.TestCase):
    def test_probe_projects_only_owned_label_and_optional_image_volumes(self):
        tool = load()
        run = MountProbeRun(tool)
        self.assertEqual(tool.Docker(run=run).mount_source_metadata("/opaque/models", run.image), (42, 73))
        commands = [argv[3:] for argv, _ in run.calls]
        image = next(command for command in commands if command[0] == "image")
        self.assertIn('(index .Config "Volumes")', image[image.index("--format") + 1])
        for command in commands:
            if command[0] == "inspect":
                template = command[command.index("--format") + 1]
                self.assertNotIn("json .Config.Labels", template)
                self.assertIn('(index .Config.Labels "arena.control.mount-stat")', template)

    def test_probe_serializes_ownership_and_blocks_followers_after_unknown_cleanup(self):
        tool = load()
        entered, release = threading.Event(), threading.Event()
        first, second = MountProbeRun(tool), MountProbeRun(tool)
        first.failure = "cleanup"
        outcomes = []

        def boundary(argv, timeout):
            run = first if threading.current_thread().name == "first-probe" else second
            if run is first and argv[3] == "image":
                entered.set()
                if not release.wait(1):
                    raise AssertionError("test release missing")
            return run(argv, timeout)

        docker = tool.Docker(run=boundary)

        def probe():
            try:
                outcomes.append(docker.mount_source_metadata("/opaque/models", first.image))
            except (ValueError, TimeoutError) as error:
                outcomes.append(type(error).__name__)

        owner = threading.Thread(target=probe, name="first-probe")
        follower = threading.Thread(target=probe, name="second-probe")
        owner.start()
        self.assertTrue(entered.wait(1))
        follower.start()
        follower.join(0.05)
        release.set()
        owner.join(2)
        follower.join(2)
        self.assertFalse(owner.is_alive() or follower.is_alive())
        self.assertFalse(second.calls, "concurrent verifier bypassed unresolved ownership")
        self.assertEqual(sorted(outcomes), ["TimeoutError", "ValueError"])
        self.assertEqual(docker.probe_unresolved["id"], first.target)

    def test_probe_cleanup_and_ack_loss_never_authorize_and_retain_exact_ownership(self):
        tool = load()
        for failure in ("create_ack", "start", "cleanup"):
            with self.subTest(failure=failure):
                run = MountProbeRun(tool)
                run.failure = failure
                docker = tool.Docker(run=run)
                with self.assertRaises(TimeoutError):
                    docker.mount_source_metadata("/opaque/models", run.image)
                commands = [argv[3:] for argv, _ in run.calls]
                self.assertEqual([c for c in commands if c[0] == "rm"], [["rm", "--force", run.target]])
                if failure == "create_ack":
                    discovery = next(c for c in commands if c[0] == "ps")
                    self.assertIn("name=^/" + run.name + "$", discovery)
                    self.assertIn("label=" + run.label, discovery)
                    self.assertFalse(any(c[0] == "start" for c in commands))
                if failure == "cleanup":
                    self.assertEqual(docker.probe_unresolved, {"id": run.target, "name": run.name, "label": run.label})
                    before = len(run.calls)
                    with self.assertRaisesRegex(ValueError, "cleanup_unknown"):
                        docker.mount_source_metadata("/opaque/models", run.image)
                    self.assertEqual(len(run.calls), before)
                else:
                    self.assertFalse(run.exists)

    def test_probe_refuses_foreign_ownership_bad_results_and_unproved_absence(self):
        tool = load()
        for failure in ("owner_id", "owner_name", "owner_label", "absence", "bad_stat", "exit", "create_id", "lookup"):
            with self.subTest(failure=failure):
                run = MountProbeRun(tool)
                if failure in {"create_id", "lookup"}:
                    run.failure = "create_ack"

                def boundary(argv, timeout):
                    action = argv[3]
                    if failure == "create_id" and action == "create":
                        run.failure = None
                        run(argv, timeout)
                        return "short-id"
                    result = run(argv, timeout)
                    if action == "inspect" and failure.startswith("owner_"):
                        record = json.loads(result)
                        record[{"owner_id": "Id", "owner_name": "Name", "owner_label": "Labels"}[failure]] = "foreign"
                        return json.dumps(record)
                    if action == "ps" and failure == "absence":
                        return run.target
                    if action == "ps" and failure == "lookup":
                        return run.target + "\n" + "d" * 64
                    if action == "start" and failure == "bad_stat":
                        return "42 73\nsecret content"
                    if action == "wait" and failure == "exit":
                        return "1"
                    return result

                docker = tool.Docker(run=boundary)
                with self.assertRaises((ValueError, TimeoutError)):
                    docker.mount_source_metadata("/opaque/models", run.image)
                commands = [argv[3:] for argv, _ in run.calls]
                if failure.startswith("owner_") or failure == "lookup":
                    self.assertFalse(any(c[0] in {"start", "rm"} for c in commands))
                    self.assertIsNotNone(docker.probe_unresolved)
                else:
                    self.assertTrue(any(c == ["rm", "--force", run.target] for c in commands))

    def test_probe_image_and_mount_syntax_fail_before_create(self):
        tool = load()
        for source, image, volumes in (
            ("/opaque/models,src=/", "sha256:" + "b" * 64, None),
            ("/opaque/models", "latest", None),
            ("/opaque/models", "sha256:" + "b" * 64, {"/unapproved": {}}),
            ("/opaque/models", "sha256:" + "a" * 64, None),
        ):
            with self.subTest(source=source, image=image, volumes=volumes):
                run = MountProbeRun(tool)
                run.volumes = volumes
                docker = tool.Docker(run=run)
                with self.assertRaises(ValueError):
                    docker.mount_source_metadata(source, image)
                self.assertFalse(any(argv[3] == "create" for argv, _ in run.calls))

    def test_probe_cleanup_has_independent_bounded_budget_after_expiry(self):
        from unittest import mock

        tool = load()
        clock = [100.0]
        run = MountProbeRun(tool)

        def boundary(argv, timeout):
            if argv[3] == "start":
                clock[0] += 20
                raise TimeoutError()
            result = run(argv, timeout)
            if argv[3] == "rm":
                clock[0] += 3
            return result

        docker = tool.Docker(run=boundary)
        with mock.patch.object(tool.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(TimeoutError):
                docker.mount_source_metadata("/opaque/models", run.image)
        self.assertTrue(any(argv[3] == "rm" and 0 < timeout <= 2 for argv, timeout in run.calls))
        self.assertIsNotNone(docker.probe_unresolved, "expired absence check must retain unresolved ownership")
        self.assertIsNone(docker.local.deadline)

    def test_stat_only_probe_is_hardened_owned_and_removed_by_exact_id(self):
        tool = load()
        run = MountProbeRun(tool)
        docker = tool.Docker(run=run)
        self.assertEqual(docker.mount_source_metadata("/opaque/models", run.image), (42, 73))
        commands = [argv[3:] for argv, _ in run.calls]
        create = next(c for c in commands if c[0] == "create")
        for arg in (
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--restart=no",
            "--no-healthcheck",
        ):
            self.assertIn(arg, create)
        for option, value in (
            ("--user", "1000:1000"),
            ("--memory", "67108864"),
            ("--memory-swap", "67108864"),
            ("--pids-limit", "32"),
            ("--entrypoint", "/usr/bin/stat"),
            ("--workdir", "/"),
            ("--mount", "type=bind,src=/opaque/models,dst=/arena-mount-source,readonly"),
        ):
            self.assertEqual(create[create.index(option) + 1], value)
        self.assertEqual(create.count("--mount"), 1)
        self.assertEqual(create[create.index(run.image) + 1 :], ["--format=%d %i", "--", "/arena-mount-source"])
        self.assertEqual([c for c in commands if c[0] == "start"], [["start", "--attach", run.target]])
        self.assertEqual([c for c in commands if c[0] == "rm"], [["rm", "--force", run.target]])
        self.assertEqual(commands[-1], ["ps", "-aq", "--no-trunc", "--filter", "id=" + run.target])
        self.assertFalse(run.exists)
        self.assertTrue(all(0 < timeout <= 15 for _, timeout in run.calls))
        self.assertNotIn("--publish", create)
        self.assertNotIn("/var/run/docker.sock", create)
        self.assertFalse(any(c[0] in {"run", "exec", "logs", "pull", "build"} for c in commands))


class StartupV2Tests(unittest.TestCase):
    def fixture(self, root):
        value = profile(root)
        value["connections"]["gr00t_port"] = 5559
        value["api"]["environment"] = {"ARENA_WORKBENCH_GR00T_PORT": "5559"}
        value["startup_review"].update(
            mode="operator-reviewed-existing-v2", mount_metadata=[], mount_probe_image="sha256:" + "b" * 64
        )
        for service in ("neo4j", "gr00t"):
            source = root / "opaque" / service
            source.mkdir(parents=True)
            info = source.stat()
            value["services"][service]["identity"]["Mounts"][0]["Source"] = str(source)
            value["startup_review"]["mount_metadata"].append(
                {"Source": str(source), "st_dev": info.st_dev, "st_ino": info.st_ino}
            )
        value["services"]["gr00t"]["identity"].update(
            Entrypoint=["python"],
            Cmd=["-m", "approved.policy", "--model-path", "/models/local"],
            WorkingDir="/repo",
            ReadonlyRootfs=False,
        )
        return value

    def denied(self, root):
        from unittest import mock

        real_stat = Path.stat

        def stat(path, *args, **kwargs):
            if path.is_relative_to(root / "opaque"):
                raise PermissionError(13, "synthetic native UID1000 traversal denial")
            return real_stat(path, *args, **kwargs)

        return mock.patch.object(Path, "stat", stat)

    def docker(self, value):
        from unittest import mock

        docker = FakeDocker(value)
        pins = {p["Source"]: (p["st_dev"], p["st_ino"]) for p in value["startup_review"]["mount_metadata"]}
        docker.mount_source_metadata = mock.Mock(side_effect=lambda source, image: pins[source])
        return docker

    def test_v2_contract_rejections_precede_probes_and_never_read_data(self):
        from unittest import mock

        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            for change in (
                "missing_image",
                "tag",
                "image_type",
                "foreign",
                "duplicate",
                "bool_dev",
                "float_inode",
                "comma",
                "script",
            ):
                bad = copy.deepcopy(value)
                review = bad["startup_review"]
                if change == "missing_image":
                    del review["mount_probe_image"]
                elif change == "tag":
                    review["mount_probe_image"] = "cached:latest"
                elif change == "image_type":
                    review["mount_probe_image"] = True
                elif change == "foreign":
                    review["mount_metadata"][0]["Source"] = "/foreign/source"
                elif change == "duplicate":
                    review["mount_metadata"].append(copy.deepcopy(review["mount_metadata"][0]))
                elif change == "bool_dev":
                    review["mount_metadata"][0]["st_dev"] = True
                elif change == "float_inode":
                    review["mount_metadata"][0]["st_ino"] = 1.0
                elif change == "comma":
                    review["mount_metadata"][0]["Source"] += ",src=/"
                elif change == "script":
                    bad["services"]["arena"]["identity"].update(Entrypoint=["/repo/unlisted.sh"], ReadonlyRootfs=False)
                docker = self.docker(value)
                with self.denied(root), self.subTest(change=change), self.assertRaises(ValueError):
                    tool.verify_mount_sources(bad, docker)
                docker.mount_source_metadata.assert_not_called()
            docker = self.docker(value)
            real_open = tool.open_reviewed_code
            opened = []

            def code_only(path):
                opened.append(path)
                self.assertIn(path, {p["host_path"] for p in value["startup_review"]["files"]})
                return real_open(path)

            with self.denied(root), mock.patch.object(tool, "open_reviewed_code", side_effect=code_only):
                tool.verify_mount_sources(value, docker)
                self.assertEqual(docker.mount_source_metadata.call_count, 2, "not once per protected ancestor")
                self.assertTrue(opened)
            with self.denied(root), mock.patch.object(tool, "open_reviewed_code", side_effect=PermissionError()):
                docker.mount_source_metadata.reset_mock()
                with self.assertRaises(PermissionError):
                    tool.verify_mount_sources(value, docker)
                docker.mount_source_metadata.assert_not_called()

    def test_v2_requires_fresh_metadata_and_only_source_permission_falls_back(self):
        from unittest import mock

        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            docker = self.docker(value)
            with self.denied(root):
                with self.assertRaisesRegex(ValueError, "fresh_mount_verification_required"):
                    tool.validate_profile(value)
                tool.verify_mount_sources(value, docker)
                docker.mount_source_metadata.side_effect = lambda *_: (0, 1)
                with self.assertRaisesRegex(ValueError, "mount_metadata_changed"):
                    tool.verify_mount_sources(value, docker)
            for error in (FileNotFoundError(), OSError("other I/O")):
                real_stat = Path.stat

                def broken(path, *args, **kwargs):
                    if path.is_relative_to(root / "opaque"):
                        raise error
                    return real_stat(path, *args, **kwargs)

                docker.mount_source_metadata.reset_mock()
                with mock.patch.object(Path, "stat", broken), self.assertRaises(type(error)):
                    tool.verify_mount_sources(value, docker)
                docker.mount_source_metadata.assert_not_called()
            source = root / "opaque/gr00t"
            source.rename(root / "old")
            source.mkdir()
            with self.assertRaisesRegex(ValueError, "mount_metadata_changed"):
                tool.verify_mount_sources(value, docker)

    def test_v2_protected_aliases_and_visible_symlinks_are_refused_without_probes(self):
        from unittest import mock

        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            home = root / "private/control"
            home.mkdir(parents=True)
            for target in (Path("/run"), home, home.parent):
                bad = copy.deepcopy(value)
                info = target.stat()
                bad["startup_review"]["mount_metadata"][0].update(st_dev=info.st_dev, st_ino=info.st_ino)
                docker = self.docker(bad)
                with (
                    self.denied(root),
                    self.subTest(target=target),
                    self.assertRaisesRegex(ValueError, "forbidden|inside_service_mount"),
                ):
                    tool.verify_mount_sources(bad, docker, home=home)
                docker.mount_source_metadata.assert_not_called()
            # A visible parent symlink is rejected even though the leaf is opaque.
            (root / "opaque").rename(root / "actual")
            (root / "opaque").symlink_to(root / "actual", target_is_directory=True)
            real_stat = Path.stat

            def denied_leaf(path, *args, **kwargs):
                if str(path) in {p["Source"] for p in value["startup_review"]["mount_metadata"]}:
                    raise PermissionError()
                return real_stat(path, *args, **kwargs)

            docker = self.docker(value)
            with mock.patch.object(Path, "stat", denied_leaf), self.assertRaisesRegex(ValueError, "symlink"):
                tool.verify_mount_sources(value, docker)
            docker.mount_source_metadata.assert_not_called()

    def test_v2_final_inspection_drift_prevents_service_start_and_keeps_pins(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            docker = self.docker(value)
            tasks = []
            with self.denied(root):
                controller = tool.Controller(value, root, docker, submit=tasks.append)
                controller.start({"request_id": "a" * 32, "profile_revision": controller.revision})
                original = docker.inspect
                inspections = []

                def inspect(target):
                    inspections.append(target)
                    if len(inspections) == 4:
                        docker.mount_source_metadata.side_effect = lambda *_: (999, 999)
                    return original(target)

                docker.inspect = inspect
                tasks.pop()()
                self.assertEqual(controller.receipts[0]["status"], "failed")
                self.assertFalse(any(c[0] == "start" for c in docker.calls))
                self.assertEqual(controller.profile, value)

    def test_v2_unknown_probe_cleanup_blocks_even_now_accessible_sources(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            run = MountProbeRun(tool)
            run.failure = "cleanup"
            docker = tool.Docker(run=run)
            with self.assertRaises(TimeoutError):
                docker.mount_source_metadata("/opaque/models", run.image)
            before = len(run.calls)
            with self.assertRaisesRegex(ValueError, "cleanup_unknown"):
                tool.verify_mount_sources(value, docker)
            self.assertEqual(len(run.calls), before)

    def test_v2_observation_second_guard_shares_budget_and_never_caches_mount_authority(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            fake = self.docker(value)
            docker = tool.Docker(run=lambda *_: (_ for _ in ()).throw(AssertionError("unexpected subprocess")))
            docker.inspect, docker.api_status = fake.inspect, fake.api_status
            deadlines = []

            def metadata(source, image):
                deadlines.append(getattr(docker.local, "deadline", None))
                return fake.mount_source_metadata(source, image)

            docker.mount_source_metadata = metadata
            with self.denied(root):
                controller = tool.Controller(value, root, docker)
                deadlines.clear()
                controller.observe(reuse=True)
                self.assertTrue(deadlines)
                self.assertNotIn(None, deadlines, "second guard escaped the overall observation budget")
                self.assertEqual(len(set(deadlines)), 1)
                before = len(deadlines)
                controller.observe(reuse=True)
                self.assertGreater(len(deadlines), before, "cached labels must not cache metadata authority")
                self.assertIsNone(docker.local.deadline)

    def test_v2_observation_admits_realistic_fresh_probe_latency(self):
        from unittest import mock

        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            fake = self.docker(value)
            clock, advance = [100.0], [False]
            docker = tool.Docker(run=lambda *_: (_ for _ in ()).throw(AssertionError("unexpected subprocess")))
            docker.inspect, docker.api_status = fake.inspect, fake.api_status

            def metadata(source, image):
                docker.timeout()
                if advance[0]:
                    clock[0] += 0.55
                docker.timeout()
                return fake.mount_source_metadata(source, image)

            docker.mount_source_metadata = metadata
            with self.denied(root), mock.patch.object(tool.time, "monotonic", side_effect=lambda: clock[0]):
                controller = tool.Controller(value, root, docker)
                advance[0] = True
                self.assertTrue(controller.observe()["startup_allowed"])
                self.assertEqual(controller.observation_seconds, 8.0)
                self.assertEqual(tool.Controller.observation_seconds, 2.0)
                self.assertIsNone(docker.local.deadline)

    def test_v2_all_mounts_share_one_verification_deadline(self):
        from unittest import mock

        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            fake = self.docker(value)
            clock = [100.0]
            docker = tool.Docker(run=lambda *_: (_ for _ in ()).throw(AssertionError("unexpected subprocess")))

            def metadata(source, image):
                docker.timeout()
                clock[0] += 10
                docker.timeout()
                return fake.mount_source_metadata(source, image)

            docker.mount_source_metadata = metadata
            with self.denied(root), mock.patch.object(tool.time, "monotonic", side_effect=lambda: clock[0]):
                with self.assertRaises(TimeoutError):
                    tool.verify_mount_sources(value, docker)
                self.assertIsNone(getattr(docker.local, "deadline", None))

    def test_v2_api_exec_forwards_5559_and_reauthenticates_before_fresh_probes(self):
        from unittest import mock

        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            fake = self.docker(value)
            calls = []
            docker = tool.Docker(run=lambda argv, timeout: calls.append(argv) or "{}")
            target = value["services"]["arena"]["identity"]
            docker.inspect = mock.Mock(return_value={"identity": target, "status": "running"})
            docker.mount_source_metadata = fake.mount_source_metadata
            with self.denied(root):
                docker._api(value, "status")
                self.assertEqual(fake.mount_source_metadata.call_count, 2)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][3], "exec")
                self.assertIn("ARENA_WORKBENCH_GR00T_PORT=5559", calls[0])
                self.assertIn("--start-paused", calls[0])
                fake.mount_source_metadata.reset_mock()
                docker.guard = mock.Mock(side_effect=ValueError("installation_changed"))
                with self.assertRaisesRegex(ValueError, "installation_changed"):
                    docker._api(value, "ensure-paused")
                fake.mount_source_metadata.assert_not_called()
                self.assertEqual(len(calls), 1)

    def test_v2_adapter_rechecks_mounts_after_identity_inspection_before_exec_and_start(self):
        from unittest import mock

        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            for action in ("status", "ensure-paused", "start"):
                calls = []
                docker = tool.Docker(run=lambda argv, timeout: calls.append(argv) or "{}")
                target = value["services"]["arena"]["identity"]
                docker.inspect = mock.Mock(return_value={"identity": target, "status": "running"})
                docker.mount_source_metadata = mock.Mock(return_value=(999, 999))
                with (
                    self.denied(root),
                    self.subTest(action=action),
                    self.assertRaisesRegex(ValueError, "mount_metadata_changed"),
                ):
                    if action == "start":
                        docker.start(target["Id"], profile=value)
                    else:
                        docker._api(value, action)
                self.assertFalse(calls, "drift must block actual exec/start")
                self.assertEqual(docker.mount_source_metadata.call_count, 1)

    def test_v2_installed_server_injects_adapter_and_authenticates_before_probes(self):
        from unittest import mock

        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            docker = self.docker(value)
            source = HERE / "control.py"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            home = root / "installed"
            with (
                self.denied(root),
                mock.patch.object(tool, "prepare_api_storage"),
                mock.patch.object(tool.Docker, "call", side_effect=AssertionError("uninjected Docker")),
            ):
                tool.install(home, value, source, digest, docker=docker)
                with tool.installed_server(home, docker=docker) as server:
                    before = docker.mount_source_metadata.call_count
                    with self.assertRaisesRegex(ValueError, "helper_busy"), tool.installed_server(home, docker=docker):
                        self.fail("second helper acquired the singleton")
                    self.assertEqual(
                        docker.mount_source_metadata.call_count, before, "no probes before singleton ownership"
                    )
                    self.assertTrue(server.controller.observe()["startup_allowed"])
                    for marker in ("profile.json", "control.py"):
                        saved = (home / marker).read_bytes()
                        (home / marker).write_bytes(saved + (b" " if marker == "control.py" else b" "))
                        if marker == "profile.json":
                            changed = json.loads(saved)
                            changed["startup_review"]["mount_probe_image"] = "sha256:" + "f" * 64
                            (home / marker).write_bytes(tool.canonical(changed))
                        before = docker.mount_source_metadata.call_count
                        self.assertFalse(server.controller.observe()["startup_allowed"])
                        self.assertEqual(docker.mount_source_metadata.call_count, before)
                        with self.assertRaisesRegex(ValueError, "installation_changed"):
                            tool.load_installation(home, docker=docker)
                        self.assertEqual(docker.mount_source_metadata.call_count, before)
                        (home / marker).write_bytes(saved)

    @unittest.skipUnless(os.getuid() == 0 and hasattr(os, "fork"), "requires a disposable UID1000 child")
    def test_native_uid1000_opaque_roots_install_readback_and_start(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            source = root / "reviewed-control.py"
            source.write_bytes((HERE / "control.py").read_bytes())
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            # Only disposable fixture ownership changes. The opaque tree remains
            # root-owned 0700; no real Docker volume or model source is touched.
            (root / "opaque").chmod(0o700)
            for path in [root, source, root / "repo", *(root / "repo").rglob("*")]:
                os.chown(path, 1000, 1000)
            read_fd, write_fd = os.pipe()
            pid = os.fork()
            if pid == 0:
                os.close(read_fd)
                try:
                    os.setgroups([])
                    os.setgid(1000)
                    os.setuid(1000)
                    self.assertEqual((os.getuid(), os.getgid()), (1000, 1000))
                    with self.assertRaises(PermissionError):
                        (root / "opaque/gr00t").stat()
                    docker = self.docker(value)
                    home = root / "installed"
                    self.assertEqual(tool.install(home, value, source, digest, docker=docker)["profile"], value)
                    self.assertEqual(tool.load_installation(home, docker=docker)["manifest"]["uid"], 1000)
                    tasks = []
                    controller = tool.Controller(value, home / "state", docker, submit=tasks.append)
                    controller.start({"request_id": "a" * 32, "profile_revision": controller.revision})
                    tasks.pop()()
                    self.assertEqual(controller.receipts[0]["status"], "completed")
                    self.assertEqual(controller.profile["connections"]["gr00t_port"], 5559)
                    os.write(write_fd, b"uid1000 install/readback/start passed")
                    os._exit(0)
                except BaseException as error:
                    os.write(write_fd, (type(error).__name__ + ": " + str(error)).encode()[:4096])
                    os._exit(1)
            os.close(write_fd)
            output = os.read(read_fd, 4096)
            os.close(read_fd)
            _, status = os.waitpid(pid, 0)
            self.assertEqual(status, 0, output.decode())
            self.assertEqual(output, b"uid1000 install/readback/start passed")

    def test_v2_opaque_install_readback_and_fixed_start_with_private_5559(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            docker = self.docker(value)
            source = HERE / "control.py"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            with self.denied(root):
                self.assertEqual(
                    tool.install(root / "installed", value, source, digest, docker=docker)["profile"], value
                )
                before = docker.mount_source_metadata.call_count
                self.assertEqual(tool.load_installation(root / "installed", docker=docker)["profile"], value)
                self.assertGreater(docker.mount_source_metadata.call_count, before)
                tasks = []
                controller = tool.Controller(value, root / "installed/state", docker, submit=tasks.append)
                before = docker.mount_source_metadata.call_count
                controller.start({"request_id": "a" * 32, "profile_revision": controller.revision})
                tasks.pop()()
                self.assertEqual(controller.receipts[0]["status"], "completed")
                self.assertGreater(docker.mount_source_metadata.call_count, before)
                self.assertEqual([c[1] for c in docker.calls if c[0] == "start"], [str(i) * 64 for i in (1, 2, 3)])
                self.assertEqual(controller.profile, value, "verification must never repin")


class ProfileTests(unittest.TestCase):
    def test_private_gr00t_port_is_bounded_canonical_and_matches_api_environment(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            for port in (1, 5559, 65535):
                value["connections"]["gr00t_port"] = port
                value["api"]["environment"] = {"ARENA_WORKBENCH_GR00T_PORT": str(port)}
                self.assertEqual(tool.validate_profile(value), value)
            for port in (True, 0, 65536, 5559.0, "5559", None):
                value["connections"]["gr00t_port"] = port
                with self.subTest(port=port), self.assertRaises(ValueError):
                    tool.validate_profile(value)
            value["connections"]["gr00t_port"] = 5559
            for port in ("5555", "05559", "+5559", "65536", "0", "5559\n", 5559):
                value["api"]["environment"]["ARENA_WORKBENCH_GR00T_PORT"] = port
                with self.subTest(environment=port), self.assertRaises(ValueError):
                    tool.validate_profile(value)
            value["api"]["environment"] = {}
            self.assertEqual(tool.validate_profile(value), value)
            value["connections"]["gr00t_host"] = "0.0.0.0"
            with self.assertRaises(ValueError):
                tool.validate_profile(value)

    def test_required_review_tracks_actual_api_chain_files(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            value["startup_review"]["mode"] = "operator-reviewed-existing-v1"
            expected = {"docker/workbench/runtime.py", "docker/workbench/workbench.py", "docker/resource_limits.py"}
            entries = []
            for relative in sorted(expected):
                # Bind the fixture layout to existing source, not imagined neighbors.
                source = HERE.parent.parent / relative
                self.assertTrue(source.is_file(), relative)
                target = Path(directory) / "repo" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
                entries.append(reviewed_file("arena", "/repo/" + relative, target))
            value["startup_review"]["files"] = entries
            tool.validate_profile(value)

    def test_modes_and_boolean_review_are_explicit_with_no_downgrade(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            for review in (
                None,
                {},
                {"mode": "existing", "files": []},
                {"mode": None, "files": []},
                {"mode": "operator-reviewed-existing-v1"},
            ):
                bad = copy.deepcopy(value)
                if review is None:
                    del bad["startup_review"]
                else:
                    bad["startup_review"] = review
                with self.subTest(review=review), self.assertRaises(ValueError):
                    tool.validate_profile(bad)
            for mode in ("image-baked-v1", "operator-reviewed-existing-v1"):
                for field, invalid in (
                    ("ReadonlyRootfs", 0),
                    ("ReadonlyRootfs", 1),
                    ("ReadonlyRootfs", "false"),
                    ("ReadonlyRootfs", None),
                    ("Privileged", True),
                    ("Privileged", 0),
                ):
                    bad = copy.deepcopy(value)
                    bad["startup_review"]["mode"] = mode
                    bad["services"]["arena"]["identity"][field] = invalid
                    with self.subTest(mode=mode, field=field, invalid=invalid), self.assertRaises(ValueError):
                        tool.validate_profile(bad)
            for field in ("mode", "files"):
                bad = copy.deepcopy(value)
                bad["startup_review"][field] = "operator-reviewed-existing-v1" if field == "mode" else []
                self.assertNotEqual(tool.profile_revision(value), tool.profile_revision(bad))
            for field in ("service", "container_path", "host_path", "sha256", "device", "inode"):
                bad = copy.deepcopy(value)
                bad["startup_review"]["files"][0][field] = "different"
                self.assertNotEqual(tool.profile_revision(value), tool.profile_revision(bad))

    def test_code_evidence_rejects_model_secret_and_noncode_paths_without_opening(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            for relative in ("models/config.py", "data/start.py", "secrets/key.py", ".env", "weights.bin"):
                bad = copy.deepcopy(value)
                entry = copy.deepcopy(bad["startup_review"]["files"][0])
                entry.update(container_path="/repo/" + relative, host_path=str(Path(directory) / "repo" / relative))
                bad["startup_review"]["files"].append(entry)
                with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "startup"):
                    tool.validate_profile(bad)

    def test_reviewed_file_reads_refuse_missing_alias_special_oversize_and_pathswap(self):
        tool = load()
        for kind in ("missing", "symlink", "parent_symlink", "hardlink", "directory", "fifo", "oversize", "pathswap"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                value = profile(root)
                path = Path(value["startup_review"]["files"][0]["host_path"])
                tool.verify_reviewed_files(value)
                if kind == "parent_symlink":
                    path.parent.rename(root / "moved")
                    path.parent.symlink_to(root / "moved", target_is_directory=True)
                elif kind == "hardlink":
                    os.link(path, root / "alias.py")
                elif kind == "oversize":
                    path.write_bytes(b"x" * 262145)
                else:
                    # Keep the old inode alive, so replacement cannot reuse it.
                    path.rename(root / "old.py")
                    if kind == "symlink":
                        path.symlink_to(root / "old.py")
                    elif kind == "directory":
                        path.mkdir()
                    elif kind == "fifo":
                        os.mkfifo(path)
                    elif kind == "pathswap":
                        path.write_bytes((root / "old.py").read_bytes())
                with self.assertRaises((ValueError, OSError)):
                    tool.verify_reviewed_files(value)
                docker, tasks = FakeDocker(value), []
                controller = tool.Controller(value, root, docker, submit=tasks.append)
                self.assertFalse(controller.observe()["startup_allowed"])
                with self.assertRaises(tool.ControlError):
                    controller.start({"request_id": "a" * 32, "profile_revision": controller.revision})
                self.assertFalse(docker.calls)
                self.assertFalse(tasks)

    def test_operator_review_requires_listed_direct_mounted_startup_code(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            value["startup_review"]["mode"] = "operator-reviewed-existing-v1"
            script = root / "repo/startup.sh"
            script.write_bytes(b"#!/bin/sh\nexit 0\n")
            identity = value["services"]["arena"]["identity"]
            for entrypoint, command, cwd in (
                (["/repo/startup.sh"], [], "/"),
                (["/bin/sh"], ["startup.sh"], "/repo"),
                (["python"], ["--script=/repo/startup.sh"], "/"),
            ):
                identity.update(Entrypoint=entrypoint, Cmd=command, WorkingDir=cwd, ReadonlyRootfs=False)
                with self.subTest(command=command), self.assertRaisesRegex(ValueError, "missing_startup_review"):
                    tool.validate_profile(value)
            value["startup_review"]["files"].append(reviewed_file("arena", "/repo/startup.sh", script))
            self.assertEqual(tool.validate_profile(value), value)

    def test_review_requires_exact_mapped_api_chain_before_any_file_read(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            value["startup_review"]["mode"] = "operator-reviewed-existing-v1"
            for change in ("missing_chain", "wrong_source", "shadow_mount", "duplicate", "digest", "excess"):
                bad = copy.deepcopy(value)
                files = bad["startup_review"]["files"]
                if change == "missing_chain":
                    files.pop()
                elif change == "wrong_source":
                    files[0]["host_path"] = "/unapproved/runtime.py"
                elif change == "shadow_mount":
                    bad["services"]["arena"]["identity"]["Mounts"].append({
                        "Type": "bind",
                        "Source": "/unapproved",
                        "Destination": "/repo/docker",
                        "RW": True,
                    })
                elif change == "duplicate":
                    files.append(copy.deepcopy(files[0]))
                elif change == "digest":
                    files[0]["sha256"] = "A" * 64
                else:
                    files *= 11
                with self.subTest(change=change), self.assertRaisesRegex(ValueError, "startup"):
                    tool.validate_profile(bad)

    def test_explicit_operator_mode_accepts_reviewed_existing_stack(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            value["startup_review"]["mode"] = "operator-reviewed-existing-v1"
            for service in value["services"].values():
                service["identity"]["ReadonlyRootfs"] = False
            value["services"]["gr00t"]["identity"].update(
                Entrypoint=["python"],
                Cmd=["-m", "approved.policy", "--model-path", "/models/local"],
                WorkingDir="/repo",
            )
            self.assertEqual(tool.validate_profile(value), value)

    def test_image_startup_requires_readonly_container_root(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            self.assertEqual(tool.validate_profile(value), value)
            for service in tool.SERVICES:
                bad = copy.deepcopy(value)
                bad["services"][service]["identity"]["ReadonlyRootfs"] = False
                with self.subTest(service=service), self.assertRaisesRegex(ValueError, "unverifiable_startup"):
                    tool.validate_profile(bad)

    def test_mutable_startup_script_is_refused_before_and_after_content_edit(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "repo").mkdir(exist_ok=True)
            script = root / "repo/startup.sh"
            cases = (
                (["/repo/startup.sh"], [], "/"),
                (["/bin/sh"], ["/repo/startup.sh"], "/"),
                (["/bin/sh"], ["startup.sh"], "/repo"),
                (["/bin/sh", "-c", "exec /repo/startup.sh"], [], "/"),
                (["/usr/bin/python3"], ["-cexec(open('/repo/startup.sh').read())"], "/"),
                (["//repo/startup.sh"], [], "/"),
            )
            for entrypoint, command, cwd in cases:
                value = profile(root)
                identity = value["services"]["arena"]["identity"]
                identity.update(Entrypoint=entrypoint, Cmd=command, WorkingDir=cwd)
                revision = tool.profile_revision(value)
                for content in ("#!/bin/sh\nexit 0\n", "#!/bin/sh\nrun-unreviewed-work\n"):
                    script.write_text(content)
                    with self.subTest(entrypoint=entrypoint, command=command, content=content):
                        self.assertEqual(tool.profile_revision(value), revision)
                        with self.assertRaisesRegex(ValueError, "unverifiable_startup"):
                            tool.validate_profile(value)
            # Image-baked init/wrapper contracts remain usable; no host artifact reads.
            value = profile(root)
            value["services"]["arena"]["identity"]["Entrypoint"] = [
                "/usr/bin/tini",
                "--",
                "/usr/local/bin/arena-offline-start",
            ]
            self.assertEqual(tool.validate_profile(value), value)

    def test_daemon_parent_and_symlink_alias_mounts_are_refused(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alias = root / "innocent"
            alias.symlink_to("/var/run", target_is_directory=True)
            for source in ("/", "/var", "/var/run", "/run", str(alias)):
                with self.subTest(source=source):
                    value = profile(root)
                    value["services"]["arena"]["identity"]["Mounts"].append({
                        "Type": "bind",
                        "Source": source,
                        "Destination": "/host-run",
                        "RW": False,
                    })
                    with self.assertRaisesRegex(ValueError, "docker_mount_forbidden"):
                        tool.validate_profile(value)

    def test_explicit_profile_pins_all_targets_and_rejects_unreviewed_start(self):
        tool = load()
        self.assertIsNotNone(tool, "standalone installed control helper is missing")
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            approved = tool.validate_profile(value)
            self.assertEqual(len(tool.profile_revision(approved)), 64)
            for change in (
                "id",
                "image",
                "entrypoint",
                "offline",
                "root",
                "docker_mount",
            ):
                bad = copy.deepcopy(value)
                identity = bad["services"]["arena"]["identity"]
                if change == "id":
                    identity["Id"] = "same-name"
                elif change == "image":
                    identity["Image"] = "latest"
                elif change == "entrypoint":
                    identity["Entrypoint"] = None
                elif change == "offline":
                    bad["services"]["arena"]["offline"] = False
                elif change == "root":
                    bad["api"]["uid"] = 0
                else:
                    identity["Mounts"].append({
                        "Type": "bind",
                        "Source": "/var/run/docker.sock",
                        "Destination": "/docker.sock",
                        "RW": True,
                    })
                with self.subTest(change=change), self.assertRaises(ValueError):
                    tool.validate_profile(bad)


class FakeDocker:
    def __init__(self, value):
        self.records = {
            s["identity"]["Id"]: {
                "identity": copy.deepcopy(s["identity"]),
                "status": "stopped",
            }
            for s in value["services"].values()
        }
        self.calls = []
        self.healthy = False
        self.fail = None
        self.capacity = True

    def inspect(self, target, *, observation_only=False):
        self.calls.append(("inspect", target))
        return copy.deepcopy(self.records.get(target))

    def start(self, target, *, profile=None):
        self.calls.append(("start", target))
        if target == self.fail:
            raise TimeoutError("private daemon message with secrets")
        self.records[target]["status"] = "running"

    def resources(self, value):
        return self.capacity

    def api_status(self, value):
        self.calls.append(("api_status",))
        return "healthy" if self.healthy else "stopped"

    def api_start(self, value):
        self.calls.append(("api_start",))
        self.healthy = True


class MarkerRecoveryTests(unittest.TestCase):
    def test_every_marker_discards_only_private_torn_pending_not_committed_state(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("receipts.json", "pairing.json", "frontend.json", "profile.json", "installation.json"):
                with self.subTest(name=name):
                    path = root / name
                    tool.atomic_private(path, {"committed": True})
                    pending = root / (name + ".pending")
                    pending.write_bytes(b'{"torn":')
                    pending.chmod(0o600)
                    self.assertEqual(json.loads(tool.private_file(path)), {"committed": True})
                    tool.atomic_private(path, {"replacement": True})
                    self.assertEqual(json.loads(tool.private_file(path)), {"replacement": True})
                    self.assertFalse(pending.exists())
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_unsafe_pending_aliases_are_refused_without_touching_target(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, pending, other = root / "marker", root / "marker.pending", root / "other"
            other.write_bytes(b"private-retained-bytes")
            other.chmod(0o600)
            for kind in ("symlink", "hardlink", "directory", "public"):
                if kind == "symlink":
                    pending.symlink_to(other)
                elif kind == "hardlink":
                    os.link(other, pending)
                elif kind == "directory":
                    pending.mkdir()
                else:
                    pending.write_bytes(b"torn")
                    pending.chmod(0o644)
                with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "unsafe_pending_file"):
                    tool.atomic_private(path, {})
                self.assertEqual(other.read_bytes(), b"private-retained-bytes")
                self.assertFalse(path.exists())
                if pending.is_dir():
                    pending.rmdir()
                else:
                    pending.unlink()

    def test_socket_inode_alias_is_detected_without_opening_socket(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            daemon, alias = root / "daemon", root / "unrelated-name"
            with socket.socket(socket.AF_UNIX) as owned:
                owned.bind(str(daemon))
                os.link(daemon, alias)
                self.assertTrue(tool.path_contains(alias, daemon))
                self.assertTrue(tool.path_contains(root, daemon))
                self.assertFalse(tool.path_contains(root / "missing", daemon))


class StartupTests(unittest.TestCase):
    def test_final_identity_inspection_cannot_release_changed_code(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            docker, tasks = FakeDocker(value), []
            original = docker.inspect
            inspections = 0

            def inspect(target):
                nonlocal inspections
                inspections += 1
                if inspections == 4:
                    Path(value["startup_review"]["files"][0]["host_path"]).write_text("# drift\n")
                return original(target)

            docker.inspect = inspect
            controller = tool.Controller(value, root, docker, submit=tasks.append)
            controller.start({"request_id": "a" * 32, "profile_revision": controller.revision})
            tasks.pop()()
            self.assertEqual(controller.receipts[0]["status"], "failed")
            self.assertFalse(any(c[0] in {"start", "api_start", "api_status"} for c in docker.calls))

    def test_reviewed_module_start_completes_without_restarting_healthy_api(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            value["startup_review"]["mode"] = "operator-reviewed-existing-v1"
            for service in value["services"].values():
                service["identity"]["ReadonlyRootfs"] = False
            value["services"]["arena"]["identity"].update(
                Entrypoint=["python"],
                Cmd=["-m", "approved.startup"],
                WorkingDir="/repo",
            )
            value["services"]["gr00t"]["identity"].update(
                Entrypoint=["python"],
                Cmd=["-m", "approved.policy", "--model-path", "/models/local"],
            )
            docker, tasks = FakeDocker(value), []
            docker.healthy = True
            controller = tool.Controller(value, root, docker, submit=tasks.append)
            controller.start({"request_id": "a" * 32, "profile_revision": controller.revision})
            tasks.pop()()
            self.assertEqual(controller.observe()["operation"]["status"], "completed")
            self.assertEqual(
                [c[1] for c in docker.calls if c[0] == "start"],
                [s["identity"]["Id"] for s in value["services"].values()],
            )
            self.assertFalse(any(c[0] == "api_start" for c in docker.calls))
            self.assertTrue(all(c[0] in {"inspect", "start", "api_status"} for c in docker.calls))

    def test_reviewed_wrapper_drift_blocks_observation_and_start_before_effects(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            value["startup_review"]["mode"] = "operator-reviewed-existing-v1"
            wrapper = root / "repo/startup.sh"
            wrapper.write_bytes(b"#!/bin/sh\nexit 0\n")
            value["startup_review"]["files"].append(reviewed_file("arena", "/repo/startup.sh", wrapper))
            value["services"]["arena"]["identity"].update(
                ReadonlyRootfs=False,
                Entrypoint=["/bin/sh"],
                Cmd=["startup.sh"],
                WorkingDir="/repo",
            )
            docker, tasks = FakeDocker(value), []
            controller = tool.Controller(value, root, docker, submit=tasks.append)
            request = {"request_id": "a" * 32, "profile_revision": controller.revision}
            controller.start(request)
            before = wrapper.stat()
            wrapper.write_bytes(b"#!/bin/sh\nexit 1\n")
            os.utime(wrapper, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertEqual(wrapper.stat().st_size, before.st_size)
            self.assertEqual(wrapper.stat().st_ino, before.st_ino)
            self.assertEqual(tool.profile_revision(value), controller.revision)
            tasks.pop()()
            observed = controller.observe()
            self.assertEqual(observed["operation"]["status"], "failed")
            self.assertFalse(observed["startup_allowed"])
            self.assertFalse(any(c[0] in {"start", "api_start", "api_status"} for c in docker.calls))
            with self.assertRaises(tool.ControlError):
                controller.start(dict(request, request_id="b" * 32))

    def test_cached_observation_preserves_exact_receipt_and_never_reconciles_unknown(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            docker, tasks = FakeDocker(value), []
            for record in docker.records.values():
                record["status"] = "running"
            docker.healthy = True
            controller = tool.Controller(value, root, docker, submit=tasks.append)
            controller.observe(reuse=True)
            request = {"request_id": "a" * 32, "profile_revision": controller.revision}
            controller.start(request)
            controller._finish(controller.receipts[0], "unknown", "start_unknown")
            docker.records[value["services"]["arena"]["identity"]["Id"]]["status"] = "stopped"
            before = list(docker.calls)
            response = controller.observe(request["request_id"], reuse=True)
            self.assertEqual(response["operation"]["status"], "unknown")
            self.assertEqual(docker.calls, before)
            self.assertFalse(response["startup_allowed"])
            with self.assertRaises(tool.ControlError) as missing:
                controller.observe("f" * 32, reuse=True)
            self.assertEqual(missing.exception.status, 404)
            controller.observation_after = 0
            response = controller.observe(request["request_id"], reuse=True)
            self.assertEqual(response["services"][0]["status"], "stopped")
            self.assertEqual(response["operation"]["status"], "unknown")

    def test_crashed_receipt_replacement_recovers_unknown_without_reissue(self):
        tool = load()
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            docker, tasks = FakeDocker(value), []
            controller = tool.Controller(value, root, docker, submit=tasks.append)
            request = {"request_id": "b" * 32, "profile_revision": controller.revision}
            controller.start(request)
            # Kill a real writer after its pending file is fsynced, before replace.
            child = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    (
                        "import importlib.util,os,pathlib,sys;"
                        "s=importlib.util.spec_from_file_location('control',sys.argv[1]);"
                        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                        "m.os.replace=lambda *args:os._exit(73);"
                        "m.atomic_private(pathlib.Path(sys.argv[2]),[])"
                    ),
                    str(HERE / "control.py"),
                    str(controller.path),
                ],
                check=False,
            )
            self.assertEqual(child.returncode, 73)
            self.assertTrue(controller.path.with_suffix(".json.pending").exists())
            restarted = tool.Controller(value, root, docker, submit=tasks.append)
            self.assertEqual(restarted.start(request)["status"], "unknown")
            self.assertEqual(len(tasks), 1)
            self.assertFalse(docker.calls)
            self.assertFalse(controller.path.with_suffix(".json.pending").exists())
            self.assertEqual(json.loads(controller.path.read_text())[0]["status"], "unknown")

    def test_driver_failure_after_possible_start_and_restart_never_reissues(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            docker, tasks = FakeDocker(value), []
            request = {
                "request_id": "b" * 32,
                "profile_revision": tool.profile_revision(value),
            }
            controller = tool.Controller(value, Path(directory), docker, submit=tasks.append)
            controller.start(request)

            def ambiguous(target):
                docker.calls.append(("start", target))
                docker.records[target]["status"] = "running"
                raise tool.DockerFailure()

            docker.start = ambiguous
            tasks.pop()()
            self.assertEqual(controller.observe()["operation"]["status"], "unknown")
            restarted = tool.Controller(value, Path(directory), docker, submit=tasks.append)
            self.assertEqual(restarted.start(request)["status"], "unknown")
            with self.assertRaises(tool.ControlError) as conflict:
                restarted.start(dict(request, profile_revision="f" * 64))
            self.assertEqual(conflict.exception.status, 409)
            self.assertFalse(tasks)

    def test_missing_ipc_guard_disables_start_without_creating_directories(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            docker = FakeDocker(value)

            def guard():
                raise ValueError("approved_directory_missing")

            controller = tool.Controller(value, Path(directory), docker, guard=guard)
            self.assertFalse(controller.observe()["startup_allowed"])
            with self.assertRaises(tool.ControlError) as refused:
                controller.start({"request_id": "a" * 32, "profile_revision": tool.profile_revision(value)})
            self.assertEqual(refused.exception.status, 503)
            self.assertFalse(any(c[0] == "start" for c in docker.calls))

    def test_retained_receipt_extra_fields_are_refused_not_echoed(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            tool.atomic_private(
                Path(directory) / "receipts.json",
                [{
                    "request_id": "a" * 32,
                    "profile_revision": tool.profile_revision(value),
                    "status": "starting",
                    "code": "starting",
                    "secret": "never-public",
                }],
            )
            with self.assertRaises(ValueError):
                tool.Controller(value, Path(directory), FakeDocker(value))

    def test_partial_unknown_is_reconciled_read_only_and_blocks_other_requests(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            docker, tasks = FakeDocker(value), []
            docker.fail = value["services"]["neo4j"]["identity"]["Id"]
            controller = tool.Controller(value, Path(directory), docker, submit=tasks.append)
            request = {
                "request_id": "b" * 32,
                "profile_revision": tool.profile_revision(value),
            }
            controller.start(request)
            with self.assertRaises(tool.ControlError) as busy:
                controller.start(dict(request, request_id="c" * 32))
            self.assertEqual(busy.exception.status, 429)
            tasks.pop()()
            self.assertEqual(
                controller.observe(request["request_id"])["operation"]["status"],
                "unknown",
            )
            before = [c for c in docker.calls if c[0] == "start"]
            for record in docker.records.values():
                record["status"] = "running"
            docker.healthy = True
            self.assertEqual(
                controller.observe(request["request_id"])["operation"]["status"],
                "completed",
            )
            self.assertEqual([c for c in docker.calls if c[0] == "start"], before)

    def test_same_name_replacement_and_changed_mount_never_start_any_target(self):
        tool = load()
        for kind in ("missing", "mount", "entrypoint", "image", "resource"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                value = profile(Path(directory))
                docker, tasks = FakeDocker(value), []
                target = value["services"]["gr00t"]["identity"]["Id"]
                if kind == "missing":
                    replacement = docker.records.pop(target)
                    replacement["identity"]["Id"] = "9" * 64
                    docker.records["9" * 64] = replacement
                elif kind == "resource":
                    docker.capacity = False
                else:
                    key = {
                        "mount": "Mounts",
                        "entrypoint": "Entrypoint",
                        "image": "Image",
                    }[kind]
                    docker.records[target]["identity"][key] = []
                controller = tool.Controller(value, Path(directory), docker, submit=tasks.append)
                controller.start({
                    "request_id": "a" * 32,
                    "profile_revision": tool.profile_revision(value),
                })
                tasks.pop()()
                self.assertEqual(controller.observe()["operation"]["status"], "failed")
                self.assertFalse(any(c[0] in {"start", "api_start"} for c in docker.calls))
                with self.assertRaises(tool.ControlError) as missing:
                    controller.observe("f" * 32)
                self.assertEqual(missing.exception.status, 404)

    def test_start_is_reserved_observable_and_exact_replay_never_restarts(self):
        tool = load()
        self.assertTrue(
            hasattr(tool, "Controller"),
            "retained bounded startup controller is missing",
        )
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            docker = FakeDocker(value)
            tasks = []
            controller = tool.Controller(value, Path(directory), docker, submit=tasks.append)
            request = {
                "request_id": "a" * 32,
                "profile_revision": tool.profile_revision(value),
            }
            accepted = controller.start(request)
            self.assertEqual(accepted["status"], "starting")
            self.assertFalse(any(call[0] == "start" for call in docker.calls))
            self.assertEqual(controller.start(request), accepted)
            tasks.pop()()
            observed = controller.observe(request["request_id"])
            self.assertEqual(observed["operation"]["status"], "completed")
            self.assertEqual(observed["operation"]["code"], "services_started")
            self.assertEqual([s["id"] for s in observed["services"]], ["arena", "neo4j", "gr00t"])
            self.assertEqual(
                set(observed),
                {
                    "schema_version",
                    "profile_revision",
                    "expected_policy",
                    "services",
                    "api",
                    "startup_allowed",
                    "operation",
                },
            )
            before = list(docker.calls)
            restarted = tool.Controller(value, Path(directory), docker, submit=tasks.append)
            self.assertEqual(restarted.start(request)["status"], "completed")
            self.assertEqual(docker.calls, before)
            self.assertFalse(tasks)


class BootstrapTests(unittest.TestCase):
    def test_changed_private_profile_is_rejected_before_reading_new_sources(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            source = HERE / "control.py"
            home = root / "operator"
            tool.install(home, value, source, hashlib.sha256(source.read_bytes()).hexdigest())
            value["startup_review"]["files"][0]["sha256"] = "f" * 64
            tool.atomic_private(home / "profile.json", value)
            opened = []
            original = tool.open_reviewed_code

            def tracking(path):
                opened.append(path)
                return original(path)

            tool.open_reviewed_code = tracking
            with self.assertRaisesRegex(ValueError, "installation_changed"):
                tool.load_installation(home)
            self.assertFalse(opened)

    def test_install_and_readback_refuse_stale_code_before_bootstrap(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            source = HERE / "control.py"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            home = root / "operator"
            tool.install(home, value, source, digest)
            Path(value["startup_review"]["files"][0]["host_path"]).write_text("# drift\n")
            with self.assertRaisesRegex(ValueError, "startup_file_changed"):
                tool.load_installation(home)
            other = root / "other"
            with self.assertRaisesRegex(ValueError, "startup_file_changed"):
                tool.install(other, value, source, digest)
            self.assertFalse(other.exists())
            docker = FakeDocker(value)
            with self.assertRaisesRegex(ValueError, "startup_file_changed"):
                with tool.installed_server(home, docker=docker, bootstrap=True):
                    self.fail("stale code admitted")
            self.assertFalse(docker.calls)
            self.assertFalse(Path(value["storage"]["ipc_host"]).exists())

    def test_hardlinked_pairing_secret_is_refused_on_installed_readback(self):
        tool = load()
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "operator"
            value = profile(root)
            source = HERE / "control.py"
            (root / "repo").mkdir(exist_ok=True)
            tool.install(home, value, source, hashlib.sha256(source.read_bytes()).hexdigest())
            tool.atomic_private(home / "pairing.json", {"pairing_token": "private-test-token"})
            os.link(home / "pairing.json", root / "repo/innocent.json")
            with self.assertRaisesRegex(ValueError, "installation_secret_alias"):
                tool.load_installation(home)

    def test_install_under_private_umask_establishes_exact_modes(self):
        tool = load()
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "operator"
            source = HERE / "control.py"
            previous = os.umask(0o077)
            try:
                tool.install(home, profile(root), source, hashlib.sha256(source.read_bytes()).hexdigest())
            finally:
                os.umask(previous)
            for path, mode in ((home, 0o700), (home / "state", 0o700), (home / "ipc", 0o750)):
                self.assertEqual(path.stat().st_mode & 0o777, mode)
            tool.load_installation(home)

    def test_control_secrets_cannot_be_exposed_through_mount_alias(self):
        tool = load()
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = HERE / "control.py"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            home = root / "operator"
            alias = root / "alias"
            alias.symlink_to(home, target_is_directory=True)
            value = profile(root)
            value["services"]["arena"]["identity"]["Mounts"].append({
                "Type": "bind",
                "Source": str(alias),
                "Destination": "/innocent",
                "RW": False,
            })
            with self.assertRaisesRegex(ValueError, "installation_inside_service_mount"):
                tool.install(home, value, source, digest)
            self.assertFalse(home.exists())

            alias.unlink()
            alias.mkdir()
            tool.install(home, value, source, digest)
            alias.rmdir()
            alias.symlink_to(home / "state", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "installation_inside_service_mount"):
                tool.load_installation(home)

    def test_install_copies_reviewed_bytes_outside_arena_mounts_and_refuses_tampering(
        self,
    ):
        tool = load()
        self.assertTrue(hasattr(tool, "install"), "safe installed helper entrypoint missing")
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            source = HERE / "control.py"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            home = root / "operator"
            tool.install(home, value, source, digest)
            self.assertEqual((home / "control.py").read_bytes(), source.read_bytes())
            self.assertEqual(tool.load_installation(home)["profile"], value)
            (home / "profile.json").write_text("{}")
            with self.assertRaises(ValueError):
                tool.load_installation(home)
            with self.assertRaises(ValueError):
                tool.install(root / "eval/helper", value, source, digest)
            with self.assertRaises(ValueError):
                tool.install(root / "other", value, source, "0" * 64)

    def test_frontend_bootstrap_creates_only_explicit_image_and_reuses_exact_id(self):
        tool = load()
        self.assertTrue(hasattr(tool, "bootstrap_frontend"), "cold frontend bootstrap missing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, calls = profile(root), []
            target = "f" * 64
            expected = {"Id": target, "Image": value["frontend"]["image"]}

            class FrontendDocker:
                def call(self, *argv):
                    calls.append(argv)
                    return target

                def inspect(self, container):
                    self_test.assertEqual(container, target)
                    return {
                        "identity": expected,
                        "status": "running" if any(c[0] == "start" for c in calls) else "stopped",
                    }

                def start(self, container):
                    calls.append(("start", container))

            self_test = self
            docker = FrontendDocker()
            tool.bootstrap_frontend(root, value, docker)
            create = next(c for c in calls if c[0] == "create")
            self.assertEqual(create[-1], value["frontend"]["image"])
            self.assertIn("--pull=never", create)
            self.assertIn("127.0.0.1:3010:3000", create)
            self.assertIn("--read-only", create)
            self.assertFalse(any("docker.sock" in part for part in create))
            self.assertFalse(any(c[0] in {"stop", "rm", "pull", "build", "restart"} for c in calls))
            count = len(calls)
            tool.bootstrap_frontend(root, value, docker)
            self.assertEqual(len(calls), count)
            expected["Id"] = "e" * 64
            with self.assertRaises(ValueError):
                tool.bootstrap_frontend(root, value, docker)

    def test_ambiguous_frontend_start_is_never_resent(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            calls = []
            target = "f" * 64

            class FrontendDocker:
                def call(self, *argv):
                    return target

                def inspect(self, container):
                    return {"identity": {"Id": target, "Image": value["frontend"]["image"]}, "status": "stopped"}

                def start(self, container):
                    calls.append(container)
                    raise TimeoutError()

            docker = FrontendDocker()
            with self.assertRaises(TimeoutError):
                tool.bootstrap_frontend(root, value, docker)
            with self.assertRaisesRegex(ValueError, "unknown|unresolved"):
                tool.bootstrap_frontend(root, value, docker)
            self.assertEqual(calls, [target])

    def test_cold_api_ipc_creation_is_explicit_and_preserves_existing_state(self):
        tool = load()
        self.assertTrue(
            hasattr(tool, "prepare_api_storage"),
            "cold bootstrap IPC preparation missing",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            value["api"].update(uid=os.getuid(), gid=os.getgid())
            (root / "eval").mkdir()
            tool.prepare_api_storage(value, create=True)
            state = Path(value["storage"]["state_host"])
            journal = state / "journal.sqlite3"
            journal.write_bytes(b"retained-existing-journal")
            tool.prepare_api_storage(value, create=False)
            self.assertEqual(journal.read_bytes(), b"retained-existing-journal")
            self.assertEqual(state.stat().st_mode & 0o777, 0o700)
            self.assertEqual(Path(value["storage"]["ipc_host"]).stat().st_mode & 0o777, 0o750)
            state.chmod(0o755)
            with self.assertRaisesRegex(ValueError, "ownership|mode"):
                tool.prepare_api_storage(value, create=True)
            state.chmod(0o700)
            value["api"]["uid"] += 1
            with self.assertRaisesRegex(ValueError, "ownership"):
                tool.prepare_api_storage(value, create=True)
            self.assertEqual(journal.read_bytes(), b"retained-existing-journal")

    def test_missing_unapproved_or_symlink_ipc_is_refused_without_mkdir(self):
        tool = load()
        self.assertTrue(
            hasattr(tool, "prepare_api_storage"),
            "cold bootstrap IPC preparation missing",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            (root / "eval").mkdir()
            with self.assertRaisesRegex(ValueError, "missing"):
                tool.prepare_api_storage(value, create=False)
            self.assertFalse((root / "eval/.wb").exists())
            (root / "eval/.wb").symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                tool.prepare_api_storage(value, create=True)


class DockerBoundaryTests(unittest.TestCase):
    def test_api_chain_drift_blocks_fixed_status_and_paused_exec(self):
        tool = load()
        for name in ("docker/workbench/runtime.py", "docker/workbench/workbench.py", "docker/resource_limits.py"):
            for action in ("api_status", "api_start"):
                for stage in ("before", "during_inspect"):
                    with (
                        self.subTest(name=name, action=action, stage=stage),
                        tempfile.TemporaryDirectory() as directory,
                    ):
                        value = profile(Path(directory))
                        path = Path(directory) / "repo" / name
                        identity = value["services"]["arena"]["identity"]
                        identity["EnvSha256"] = hashlib.sha256(tool.canonical([])).hexdigest()
                        calls = []

                        def run(argv, timeout):
                            calls.append(argv)
                            if "inspect" in argv:
                                if stage == "during_inspect":
                                    path.write_bytes(b"# changed code\n")
                                return json.dumps(dict(identity, Env=[], State={"Status": "running"}))
                            return '{"owned":false,"healthy":false}'

                        if stage == "before":
                            path.write_bytes(b"# changed code\n")
                        with self.assertRaises(ValueError):
                            getattr(tool.Docker(run=run), action)(value)
                        self.assertFalse(any("exec" in command for command in calls))

    def test_observation_has_one_overall_budget_and_clears_worker_deadline(self):
        tool = load()
        import time

        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            calls = []

            def unavailable(argv, timeout):
                calls.append(timeout)
                time.sleep(min(timeout, 0.04))
                raise TimeoutError()

            docker = tool.Docker(run=unavailable)
            controller = tool.Controller(value, Path(directory), docker)
            controller.observation_seconds = 0.06
            started = time.monotonic()
            observed = controller.observe()
            elapsed = time.monotonic() - started
            self.assertLessEqual(sum(calls), 0.1, "per-call timeouts did not share an observation deadline")
            self.assertLess(elapsed, 0.11)
            self.assertFalse(observed["startup_allowed"])
            self.assertTrue(all(s["status"] == "unknown" for s in observed["services"]))
            self.assertEqual(docker.timeout(), 15)

    def test_docker_deadline_caps_every_call_and_output_is_bounded(self):
        tool = load()
        self.assertTrue(
            hasattr(tool.Docker, "set_deadline"),
            "startup total deadline is not enforced at Docker boundary",
        )
        import sys
        import time

        calls = []
        docker = tool.Docker(run=lambda argv, timeout: calls.append(timeout) or "")
        docker.set_deadline(time.monotonic() + 0.1)
        docker.call("ps")
        self.assertLessEqual(calls[0], 0.1)
        docker.set_deadline(time.monotonic() - 1)
        with self.assertRaises(TimeoutError):
            docker.call("ps")
        self.assertEqual(len(calls), 1)
        with self.assertRaises(tool.DockerFailure):
            tool.bounded_run([sys.executable, "-c", "import sys;sys.stdout.write('x'*300000)"], 2)
        with self.assertRaises(TimeoutError):
            tool.bounded_run([sys.executable, "-c", "import time;time.sleep(10)"], 0.05)

    def test_fixed_nonroot_api_only_exec_and_inspect_hide_environment(self):
        tool = load()
        self.assertTrue(hasattr(tool, "Docker"), "bounded Docker adapter missing")
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            value["api"]["environment"] = {
                "ARENA_GR00T_CHECKPOINT_SHA256": "c" * 64,
                "ARENA_WORKBENCH_GPU_MIN_FREE_MIB": "4096",
                "ARENA_WORKBENCH_GPU_UUID": "GPU-12345678-1234-1234-1234-123456789abc",
            }
            tool.validate_profile(value)
            identity = value["services"]["arena"]["identity"]
            calls = []

            def run(argv, timeout):
                calls.append((argv, timeout))
                if "inspect" in argv:
                    return json.dumps(
                        dict(
                            identity,
                            Env=["PRIVATE_TOKEN=secret-never-public"],
                            State={"Status": "running"},
                        )
                    )
                return '{"owned":false,"healthy":false}'

            docker = tool.Docker(run=run)
            record = docker.inspect(identity["Id"])
            self.assertNotIn("secret-never-public", json.dumps(record))
            identity["EnvSha256"] = record["identity"]["EnvSha256"]
            docker.api_start(value)
            argv = calls[-1][0]
            self.assertIn("ensure-paused", argv)
            self.assertIn("--start-paused", argv)
            self.assertEqual(argv[argv.index("--user") + 1], "1000:1000")
            self.assertIn("ARENA_GR00T_CHECKPOINT_SHA256=" + "c" * 64, argv)
            self.assertIn("ARENA_WORKBENCH_GPU_MIN_FREE_MIB=4096", argv)
            self.assertIn("ARENA_WORKBENCH_GPU_UUID=GPU-12345678-1234-1234-1234-123456789abc", argv)
            self.assertNotIn("workbench.py", " ".join(argv))
            self.assertTrue(all(timeout <= 15 for _, timeout in calls))
            for forbidden in ("pull", "build", "restart", "stop", "rm", "create"):
                self.assertFalse(any(forbidden in command for command, _ in calls))

    def test_api_environment_rejects_malformed_resource_and_hash_values(self):
        tool = load()
        with tempfile.TemporaryDirectory() as directory:
            for key, invalid in (
                ("ARENA_WORKBENCH_GPU_MIN_FREE_MIB", "0"),
                ("ARENA_WORKBENCH_GPU_MIN_FREE_MIB", "4096;start"),
                ("ARENA_WORKBENCH_GPU_MIN_FREE_MIB", "01"),
                ("ARENA_WORKBENCH_GPU_MIN_FREE_MIB", 4096),
                ("ARENA_WORKBENCH_GPU_UUID", "0"),
                ("ARENA_WORKBENCH_GPU_UUID", "GPU-12345678-1234-1234-1234-123456789abc\n"),
                ("ARENA_GR00T_CHECKPOINT_SHA256", "4096"),
                ("ARENA_GR00T_CONFIG_SHA256", None),
                ("PYTHONPATH", "/untrusted"),
            ):
                with self.subTest(key=key, invalid=invalid):
                    value = profile(Path(directory))
                    value["api"]["environment"] = {key: invalid}
                    with self.assertRaisesRegex(ValueError, "invalid_environment"):
                        tool.validate_profile(value)


class EntryPointTests(unittest.TestCase):
    def test_installed_server_recovers_receipt_and_pairing_pending_under_singleton(self):
        tool = load()
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            home = root / "installed"
            source = HERE / "control.py"
            tool.install(home, value, source, hashlib.sha256(source.read_bytes()).hexdigest())
            request = {
                "request_id": "a" * 32,
                "profile_revision": tool.profile_revision(value),
                "status": "starting",
                "code": "starting",
            }
            tool.atomic_private(home / "state/receipts.json", [request])
            for name in ("state/receipts.json.pending", "pairing.json.pending"):
                (home / name).write_bytes(b'{"torn":')
                (home / name).chmod(0o600)
            docker = FakeDocker(value)
            with tool.installed_server(home, docker=docker) as server:
                self.assertTrue((home / "ipc/control.sock").is_socket())
                self.assertEqual(server.controller.receipts[0]["status"], "unknown")
                self.assertIn("pairing_token", json.loads(tool.private_file(home / "pairing.json")))
                self.assertFalse((home / "state/receipts.json.pending").exists())
                self.assertFalse((home / "pairing.json.pending").exists())
            self.assertFalse(docker.calls)

    def test_executable_launcher_installs_and_inspects_without_pythonpath_hooks(self):
        import hashlib
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "control.py"
            source.write_bytes((HERE / "control.py").read_bytes())
            source.chmod(0o700)
            marker = root / "hook-executed"
            poison = f"open({str(marker)!r}, 'w').write('executed')\n"
            (root / "sitecustomize.py").write_text(poison)
            (root / "argparse.py").write_text(poison)
            config = root / "profile.json"
            config.write_text(json.dumps(profile(root)))
            config.chmod(0o600)
            environment = dict(os.environ, PYTHONPATH=str(root))
            home = root / "installed"
            result = subprocess.run(
                [
                    str(source),
                    "install",
                    "--home",
                    str(home),
                    "--profile",
                    str(config),
                    "--source-sha256",
                    hashlib.sha256(source.read_bytes()).hexdigest(),
                ],
                env=environment,
                capture_output=True,
                text=True,
                timeout=3,
            )
            self.assertFalse(marker.exists(), "launcher allowed interpreter startup hook execution")
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(
                [
                    str(home / "control.py"),
                    "inspect",
                    "--home",
                    str(home),
                ],
                env=environment,
                capture_output=True,
                text=True,
                timeout=3,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["schema_version"], 1)
            self.assertFalse(marker.exists())
            self.assertEqual((home / "control.py").stat().st_mode & 0o777, 0o700)

    def test_nonisolated_cli_refuses_before_shadow_imports_for_every_action(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "shadow-executed"
            (root / "argparse.py").write_text(f"open({str(marker)!r}, 'w').write('executed')\n")
            environment = dict(os.environ, PYTHONPATH=str(root))
            for action in ("install", "inspect", "bootstrap", "serve"):
                result = subprocess.run(
                    [sys.executable, "-S", str(HERE / "control.py"), action, "--home", str(root / "home")],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                with self.subTest(action=action):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(marker.exists(), "shadow module executed before isolation refusal")
                    self.assertIn("isolated", result.stderr)
            self.assertFalse((root / "home").exists())

    def test_install_cli_isolated_serve_has_singleton_and_owned_socket_cleanup(self):
        tool = load()
        self.assertTrue(hasattr(tool, "installed_server"), "installed serve entrypoint missing")
        import hashlib
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            source = HERE / "control.py"
            config = root / "operator-profile.json"
            config.write_text(json.dumps(value))
            config.chmod(0o600)
            home = root / "installed"
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    str(source),
                    "install",
                    "--home",
                    str(home),
                    "--profile",
                    str(config),
                    "--source-sha256",
                    hashlib.sha256(source.read_bytes()).hexdigest(),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((home / "control.py").exists())
            with tool.installed_server(home, docker=FakeDocker(value)) as server:
                self.assertTrue((home / "ipc/control.sock").is_socket())
                with self.assertRaisesRegex(ValueError, "busy"):
                    with tool.installed_server(home, docker=FakeDocker(value)):
                        self.fail("second helper took singleton")
                self.assertEqual(server.controller.revision, tool.profile_revision(value))
                self.assertEqual((home / "pairing.json").stat().st_mode & 0o777, 0o600)
            self.assertFalse((home / "ipc/control.sock").exists())


class WireTests(unittest.TestCase):
    def test_queued_observations_do_not_repeat_budget_ahead_of_start_and_revoke(self):
        tool = load()
        import time

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = profile(root)
            entered, release = threading.Event(), threading.Event()
            calls, tasks = [], []

            def unavailable(argv, timeout):
                calls.append(timeout)
                entered.set()
                self.assertTrue(release.wait(2))
                time.sleep(timeout)
                raise TimeoutError()

            controller = tool.Controller(value, root, tool.Docker(run=unavailable), submit=tasks.append)
            controller.observation_seconds = 0.12
            path = str(root / "control.sock")
            with tool.ControlServer(path, controller, "unused") as server:
                server.session = {"cookie": "test-cookie", "csrf_token": "test-csrf", "expires_at": time.time() + 60}
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                connections = []

                def enqueue(method, target, body=None):
                    connection = http.client.HTTPConnection("127.0.0.1:3010", timeout=3)
                    connection.sock = socket.socket(socket.AF_UNIX)
                    connection.sock.settimeout(3)
                    connection.sock.connect(path)
                    connection.request(
                        method,
                        target,
                        body=json.dumps(body) if body is not None else None,
                        headers={
                            "Origin": value["origin"],
                            "Content-Type": "application/json",
                            "Cookie": "arena_control=test-cookie",
                            "X-CSRF-Token": "test-csrf",
                        },
                    )
                    connections.append(connection)

                try:
                    started = time.monotonic()
                    enqueue("GET", "/control/research-services")
                    if not entered.wait(2):
                        response = connections[0].getresponse()
                        self.fail(f"observation did not enter driver: {response.status} {response.read()!r}")
                    enqueue("GET", "/control/research-services")
                    enqueue("GET", "/control/research-services")
                    request = {"request_id": "c" * 32, "profile_revision": controller.revision}
                    enqueue("POST", "/control/research-services/start", request)
                    enqueue("DELETE", "/control/session")
                    release.set()
                    responses = []
                    for connection in connections:
                        response = connection.getresponse()
                        responses.append((response.status, json.loads(response.read())))
                    self.assertEqual([r[0] for r in responses], [200, 200, 200, 202, 200])
                    self.assertEqual(len(calls), 1, "queued polls repeatedly spent the observation budget")
                    self.assertLess(time.monotonic() - started, 0.3)
                    self.assertEqual(responses[3][1]["request_id"], request["request_id"])
                    self.assertIsNone(server.session)
                    self.assertEqual(len(tasks), 1)
                finally:
                    release.set()
                    for connection in connections:
                        connection.close()
                    server.shutdown()
                    thread.join(3)

    def test_owned_uds_pairing_csrf_origin_and_exact_start_wire(self):
        tool = load()
        self.assertTrue(hasattr(tool, "ControlServer"), "control HTTP server is missing")
        with tempfile.TemporaryDirectory() as directory:
            value = profile(Path(directory))
            docker, tasks = FakeDocker(value), []
            controller = tool.Controller(value, Path(directory), docker, submit=tasks.append)
            path = str(Path(directory) / "control.sock")
            with tool.ControlServer(path, controller, "one-time-token") as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                def request(
                    method,
                    target,
                    body=None,
                    cookie=None,
                    csrf=None,
                    origin=value["origin"],
                ):
                    connection = http.client.HTTPConnection("127.0.0.1:3010", timeout=2)
                    connection.sock = socket.socket(socket.AF_UNIX)
                    connection.sock.settimeout(2)
                    connection.sock.connect(path)
                    headers = {"Origin": origin, "Content-Type": "application/json"}
                    if cookie:
                        headers["Cookie"] = cookie
                    if csrf:
                        headers["X-CSRF-Token"] = csrf
                    connection.request(
                        method,
                        target,
                        body=json.dumps(body) if body is not None else None,
                        headers=headers,
                    )
                    response = connection.getresponse()
                    result = (
                        response.status,
                        json.loads(response.read()),
                        response.getheader("Set-Cookie"),
                    )
                    connection.close()
                    return result

                try:
                    self.assertEqual(request("GET", "/control/research-services")[0], 401)
                    self.assertEqual(
                        request(
                            "POST",
                            "/control/session",
                            {"pairing_token": "one-time-token"},
                            origin="http://evil.test",
                        )[0],
                        403,
                    )
                    status, session, cookie = request("POST", "/control/session", {"pairing_token": "one-time-token"})
                    self.assertEqual(status, 200)
                    self.assertEqual(set(session), {"schema_version", "csrf_token", "expires_at"})
                    for flag in ("HttpOnly", "SameSite=Strict", "Path=/control"):
                        self.assertIn(flag, cookie)
                    self.assertNotIn("Domain=", cookie)
                    cookie = cookie.split(";", 1)[0]
                    csrf = session["csrf_token"]
                    self.assertEqual(request("POST", "/control/session", {}, cookie)[1], session)
                    body = {
                        "request_id": "d" * 32,
                        "profile_revision": tool.profile_revision(value),
                    }
                    self.assertEqual(
                        request("POST", "/control/research-services/start", body, cookie)[0],
                        403,
                    )
                    for key in ("mode", "startup_review", "files", "ReadonlyRootfs", "host_path", "sha256"):
                        with self.subTest(injected=key):
                            injected = dict(body, **{key: "operator-reviewed-existing-v1"})
                            self.assertEqual(
                                request("POST", "/control/research-services/start", injected, cookie, csrf)[0], 400
                            )
                            self.assertEqual(
                                request("GET", "/control/research-services?" + key + "=x", cookie=cookie)[0], 400
                            )
                    self.assertFalse(tasks)
                    status, operation, _ = request("POST", "/control/research-services/start", body, cookie, csrf)
                    self.assertEqual(status, 202)
                    self.assertEqual(
                        set(operation),
                        {"request_id", "profile_revision", "status", "code"},
                    )
                    self.assertEqual(
                        request(
                            "POST",
                            "/control/research-services/start",
                            dict(body, target="evil"),
                            cookie,
                            csrf,
                        )[0],
                        400,
                    )
                    self.assertEqual(
                        request(
                            "GET",
                            "/control/research-services?request_id=" + "f" * 32,
                            cookie=cookie,
                        )[0],
                        404,
                    )
                    self.assertEqual(
                        request("PUT", "/control/session", {}, cookie, csrf)[1], {"error": "method_not_allowed"}
                    )
                    self.assertEqual(
                        request(
                            "POST", "/control/research-services/start", body, cookie, csrf, origin="http://evil.test"
                        )[0],
                        403,
                    )
                    self.assertEqual(
                        request("DELETE", "/control/session", None, cookie, csrf)[1],
                        {"schema_version": 1, "revoked": True},
                    )
                    self.assertEqual(
                        request("GET", "/control/research-services", cookie=cookie)[0],
                        401,
                    )
                    self.assertFalse(any(c[0] == "start" for c in docker.calls))
                finally:
                    server.shutdown()
                    thread.join(3)


if __name__ == "__main__":
    unittest.main()
