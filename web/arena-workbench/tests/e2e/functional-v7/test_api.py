# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Sandbox-only metadata and firewall regressions; no Arena/provider imports."""
import errno
import socket
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

import api


def counts():
    return dict.fromkeys(("network", "provider", "graph", "render", "workload", "subprocess"), 0)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.counters = counts()
        self.evidence = {"stdout": b"git version 2.43.0\n", "stderr": b"", "returncode": 0}
        self.replay = api.MetadataReplay(self.evidence, self.counters)

    def test_substituted_executable_context_and_unbounded_kwargs_are_denied_once(self):
        overrides = [
            {"executable": "/tmp/git"}, {"executable": "/usr/bin/git"},
            {"shell": True}, {"cwd": "/private"}, {"cwd": None},
            {"env": {"PATH": "/tmp"}}, {"env": None},
            {"env": dict(self.replay.expected_env, PATH="/tmp")},
            {"env": dict(self.replay.expected_env, LD_PRELOAD="/tmp/library.so")},
            {"preexec_fn": lambda: None}, {"pass_fds": (3,)}, {"close_fds": False},
            {"start_new_session": True}, {"creationflags": 1}, {"timeout": None},
            {"text": True}, {"universal_newlines": True}, {"encoding": "utf-8"},
            {"stdin": subprocess.PIPE}, {"stdout": None}, {"stderr": None},
            {"bufsize": 0}, {"unknown_option": True},
        ]
        for index, override in enumerate(overrides, 1):
            with self.subTest(override=override):
                kwargs = self.replay.expected_kwargs()
                kwargs.update(override)
                with self.assertRaisesRegex(RuntimeError, "subprocess"):
                    self.replay(["git", "version"], **kwargs)
                self.assertEqual(self.counters["subprocess"], index)
        self.assertEqual(self.replay.reads, 0)

    def test_path_argument_shape_and_positional_overrides_denied(self):
        arguments = ["git version", ["/tmp/git", "version"], ["/usr/bin/git", "version"],
                     ["git", "--version"], ["git", "version", "--build-options"],
                     ["git", "status"], [b"git", b"version"]]
        for index, argv in enumerate(arguments, 1):
            with self.subTest(argv=argv):
                with self.assertRaisesRegex(RuntimeError, "subprocess"):
                    self.replay(argv, **self.replay.expected_kwargs())
                self.assertEqual(self.counters["subprocess"], index)
        with self.assertRaisesRegex(RuntimeError, "subprocess"):
            self.replay(["git", "version"], 0, **self.replay.expected_kwargs())
        self.assertEqual(self.counters["subprocess"], len(arguments) + 1)

    def test_exact_gitpython_metadata_replays_real_bytes_with_a_read_budget(self):
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("OS process forbidden")):
            for _ in range(2):
                process = self.replay(["git", "version"], **self.replay.expected_kwargs())
                self.assertEqual(process.communicate(), (self.evidence["stdout"], self.evidence["stderr"]))
                self.assertEqual(process.wait(), 0)
                self.assertEqual(process.poll(), 0)
                process.stdout.close()
                process.stderr.close()
            with self.assertRaisesRegex(RuntimeError, "subprocess"):
                self.replay(["git", "version"], **self.replay.expected_kwargs())
        self.assertEqual(self.replay.reads, 2)
        self.assertEqual(self.counters["subprocess"], 1)

    def test_encoding_none_compatibility_and_bytes_streams(self):
        kwargs = self.replay.expected_kwargs()
        kwargs["encoding"] = None
        process = self.replay(["git", "version"], **kwargs)
        self.assertEqual(process.stdout.read(), self.evidence["stdout"])
        self.assertEqual(process.stderr.read(), b"")

    def test_replay_rejects_missing_bounds_and_never_claims_a_pid(self):
        for index, missing in enumerate(self.replay.expected_kwargs(), 1):
            kwargs = self.replay.expected_kwargs()
            kwargs.pop(missing)
            with self.subTest(missing=missing), self.assertRaisesRegex(RuntimeError, "subprocess"):
                self.replay(["git", "version"], **kwargs)
            self.assertEqual(self.counters["subprocess"], index)
        process = self.replay(["git", "version"], **self.replay.expected_kwargs())
        self.assertFalse(hasattr(process, "pid"))
        with process:
            self.assertEqual(process.communicate(timeout=0), (self.evidence["stdout"], b""))
        self.assertTrue(process.stdout.closed and process.stderr.closed)

    def test_popen_adapter_remains_a_type_for_gitpython_annotations(self):
        from typing import Optional
        popen = api.metadata_popen(self.replay)
        self.assertIsInstance(popen, type)
        self.assertIs(popen[bytes], popen)
        self.assertIsNotNone(Optional[popen])
        process = popen(["git", "version"], **self.replay.expected_kwargs())
        self.assertEqual(process.communicate(), (self.evidence["stdout"], b""))
        with self.assertRaisesRegex(RuntimeError, "subprocess"):
            process.communicate(input=b"not a metadata read")
        self.assertEqual(self.counters["subprocess"], 1)

    def test_capture_has_fixed_executable_environment_and_timeout(self):
        result = subprocess.CompletedProcess(["/usr/bin/git", "version"], 0, b"git version 2.43.0\n", b"")
        with mock.patch.object(api, "verify_metadata_executable"), mock.patch.object(api.subprocess, "run", return_value=result) as run:
            metadata = api.capture_git_metadata()
        self.assertEqual(metadata, self.evidence)
        run.assert_called_once_with(
            ["/usr/bin/git", "version"], executable="/usr/bin/git", cwd="/",
            env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "LANGUAGE": "C", "LC_ALL": "C"},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, close_fds=True, timeout=2, check=True,
        )

    def test_capture_failure_never_invents_a_version(self):
        for error in (subprocess.TimeoutExpired(["/usr/bin/git", "version"], 2),
                      subprocess.CalledProcessError(1, ["/usr/bin/git", "version"]), FileNotFoundError()):
            with self.subTest(error=type(error).__name__), mock.patch.object(api, "verify_metadata_executable"), \
                    mock.patch.object(api.subprocess, "run", side_effect=error):
                with self.assertRaises(type(error)):
                    api.capture_git_metadata()
        for stdout in (b"", b"invented version\n", b"git version 2.43.0\nextra\n"):
            result = subprocess.CompletedProcess([], 0, stdout, b"")
            with self.subTest(stdout=stdout), mock.patch.object(api, "verify_metadata_executable"), \
                    mock.patch.object(api.subprocess, "run", return_value=result):
                with self.assertRaises(AssertionError):
                    api.capture_git_metadata()


class FirewallTests(unittest.TestCase):
    def test_real_subprocess_audit_never_has_a_metadata_exception(self):
        counters = counts()
        audit = api.make_audit(counters)
        attempts = [
            ("subprocess.Popen", ("git", ["git", "version"], "/tmp", None)),
            ("subprocess.Popen", ("/tmp/evil", ["git", "version"], "/tmp", {})),
            ("subprocess.Popen", ("/bin/sh", ["git", "version"], "/private", {"PATH": "/tmp"})),
            ("os.system", (b"git version",)), ("os.exec", ()), ("os.posix_spawn", ()),
            ("os.fork", ()), ("os.forkpty", ()),
        ]
        for index, (event, args) in enumerate(attempts, 1):
            with self.assertRaisesRegex(RuntimeError, "subprocess"):
                audit(event, args)
            self.assertEqual(counters["subprocess"], index)

    def test_ip_connections_denied_uds_allowed(self):
        counters = counts()
        audit = api.make_audit(counters)
        for family in (socket.AF_INET, socket.AF_INET6):
            with self.assertRaisesRegex(RuntimeError, "IP"):
                audit("socket.connect", (SimpleNamespace(family=family), ("unused", 443)))
        audit("socket.connect", (SimpleNamespace(family=socket.AF_UNIX), "/unused.sock"))
        self.assertEqual(counters["network"], 2)

    def test_provider_graph_and_render_construction_denied_once(self):
        counters = counts()
        profile = api.make_profile(counters)
        paths = [
            ("example", "__init__", "InferenceBackend", "provider"),
            ("example", "__init__", "EnvironmentGenerationAgent", "provider"),
            ("openai", "__init__", "OpenAI", "provider"),
            ("openai", "__init__", "AsyncOpenAI", "provider"),
            ("neo4j", "driver", "GraphDatabase", "graph"),
            ("neo4j._sync.driver", "__init__", "BoltDriver", "graph"),
            ("example.snapshot_service", "render", "SnapshotService", "render"),
            ("example.snapshot_service", "__init__", "SnapshotService", "render"),
            ("example.graph_access", "retrieve_snapshot", "GraphAccess", "graph"),
        ]
        expected = counts()
        for module, name, owner, category in paths:
            frame = SimpleNamespace(f_globals={"__name__": module}, f_code=SimpleNamespace(co_name=name),
                                    f_locals={"self": type(owner, (), {})()})
            with self.subTest(module=module, name=name):
                with self.assertRaisesRegex(RuntimeError, category):
                    profile(frame, "call", None)
                expected[category] += 1
                self.assertEqual(counters, expected)
                profile(frame, "return", None)
                self.assertEqual(counters, expected)

    def test_authoring_profile_allows_only_explicit_keyed_save(self):
        for profile, body, expected in (
            ('readonly', {'idempotency_key': 'acceptance-save'}, False),
            ('authoring-v1', {}, False),
            ('authoring-v1', {'idempotency_key': ''}, False),
            ('authoring-v1', {'idempotency_key': 'acceptance-save'}, True),
        ):
            self.assertEqual(api.workload_allowed('POST', '/api/editor/save', counts(), profile, body), expected)
        for path in ('/api/jobs', '/api/editor/generate', '/api/editor/snapshots', '/api/editor/save/'):
            self.assertFalse(api.workload_allowed('POST', path, counts(), 'authoring-v1', {'idempotency_key': 'test'}))

    def test_only_validation_and_session_mutations_allowed(self):
        allowed = [("GET", "/api/editor"), ("HEAD", "/api/jobs"), ("POST", "/api/sessions"),
                   ("POST", "/api/session/activity"), ("POST", "/api/editor/validate"),
                   ("DELETE", "/api/session")]
        denied = [("POST", "/api/jobs"), ("POST", "/api/editor/generate"),
                  ("POST", "/api/editor/snapshots"), ("POST", "/api/editor/publications"),
                  ("POST", "/api/editor/validate/"), ("PUT", "/api/editor/validate"),
                  ("DELETE", "/api/jobs/job"), ("PATCH", "/api/settings")]
        counters = counts()
        for method, path in allowed:
            self.assertTrue(api.workload_allowed(method, path, counters))
        for index, (method, path) in enumerate(denied, 1):
            self.assertFalse(api.workload_allowed(method, path, counters))
            self.assertEqual(counters["workload"], index)


class ProbeTests(unittest.TestCase):
    def test_only_explicit_kernel_denial_is_evidence(self):
        for number in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EPERM, errno.EACCES):
            with self.subTest(errno=number), mock.patch.object(api.socket, "socket") as factory:
                probe = factory.return_value.__enter__.return_value
                probe.connect.side_effect = OSError(number, "unit-test denial")
                self.assertEqual(api.probe_egress(), number)
                probe.settimeout.assert_called_once_with(2)
                probe.connect.assert_called_once_with(("1.1.1.1", 443))
                factory.return_value.__exit__.assert_called_once()

    def test_success_timeout_refusal_and_unknown_error_are_not_denial(self):
        for error in (None, TimeoutError(), OSError(errno.ETIMEDOUT, "timeout"),
                      OSError(errno.ECONNREFUSED, "refused"), OSError(errno.EIO, "unknown")):
            with self.subTest(error=error), mock.patch.object(api.socket, "socket") as factory:
                probe = factory.return_value.__enter__.return_value
                probe.connect.side_effect = error
                with self.assertRaises(AssertionError):
                    api.probe_egress()
                factory.return_value.__exit__.assert_called_once()


if __name__ == "__main__":
    api.preflight()
    unittest.main()
