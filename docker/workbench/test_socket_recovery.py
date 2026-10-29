# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Stdlib socket recovery regressions; run non-root in Arena, using temporary state only."""

import errno
import fcntl
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime
import workbench


class RecoveryCommandTests(unittest.TestCase):
    def test_host_recovery_delegates_without_outer_lock_or_service_actions(self):
        config = {"synthetic": "discovered clone"}
        with (
            patch.object(sys, "argv", ["workbench.py", "recover"]),
            patch.object(workbench, "discover", return_value=config),
            patch.object(workbench, "runtime_call", return_value='{"recovered":true}') as call,
            patch.object(workbench, "operation_lock", side_effect=AssertionError("runtime must own all four locks")),
            patch.object(workbench, "compose", side_effect=AssertionError("no frontend lifecycle")),
        ):
            workbench.main()
        call.assert_called_once_with(config, "recover")


class SocketRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertNotEqual(os.getuid(), 0, "Run socket recovery tests as the non-root API user")
        self.temporary = tempfile.TemporaryDirectory(prefix="wb-recover-")
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        root.chmod(0o750)
        self.state = root / "clone" / "state"
        self.path = root / "clone" / "ipc" / "api.sock"
        runtime.prepare(self.state, self.path)
        self.journal = self.state / "journal.sqlite3"
        self.journal.write_bytes(b"synthetic sentinel: never open as a journal")
        self.marker = self.state / "launcher.json"
        self.marker.write_bytes(b'{"pid":-1,"start":"synthetic"}')

    def stale_socket(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(self.path))

    def recover_command(self):
        return [
            sys.executable,
            str(Path(runtime.__file__).resolve()),
            "recover",
            "--state-dir",
            str(self.state),
            "--socket",
            str(self.path),
            "--origin",
            "http://127.0.0.1:3000",
        ]

    def test_explicit_recover_removes_only_stale_owned_socket(self):
        self.stale_socket()
        before = {path: path.read_bytes() for path in (self.journal, self.marker)}
        result = subprocess.run(self.recover_command(), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"recovered": True})
        self.assertFalse(self.path.exists())
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertEqual(
            {path.name for path in self.state.iterdir()},
            {"journal.sqlite3", "launcher.json", "control.lock", "process-supervisor.lock", "launcher.lock"},
        )
        self.assertEqual({path.name for path in self.path.parent.iterdir()}, {"api.sock.lock"})

    def test_recovery_syncs_ipc_directory_before_releasing_all_leases(self):
        self.stale_socket()
        synced = []
        real_fsync = os.fsync

        def sync(fd):
            self.assertEqual(os.fstat(fd).st_ino, self.path.parent.stat().st_ino)
            self.assertFalse(self.path.exists())
            for path in self.lock_paths():
                with path.open("r+b") as other:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            real_fsync(fd)
            synced.append(fd)

        with patch.object(os, "fsync", side_effect=sync):
            self.assertTrue(runtime.recover(self.state, self.path))
        self.assertEqual(len(synced), 1)

    def lock_paths(self):
        return (
            self.state / "control.lock",
            self.state / "process-supervisor.lock",
            self.state / "launcher.lock",
            self.path.with_name("api.sock.lock"),
        )

    def assert_recovery_refused(self, message):
        before = self.path.lstat()
        with self.assertRaisesRegex((RuntimeError, OSError), message):
            runtime.recover(self.state, self.path)
        after = self.path.lstat()
        self.assertEqual((before.st_dev, before.st_ino, before.st_mode), (after.st_dev, after.st_ino, after.st_mode))

    def test_live_socket_is_refused_and_keeps_listening(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(self.path))
            listener.listen(4)
            listener.settimeout(1)
            self.assert_recovery_refused("live server")
            connection, _ = listener.accept()
            connection.close()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.connect(str(self.path))
                connection, _ = listener.accept()
                connection.close()

    def test_foreign_socket_uid_is_refused_before_connect(self):
        self.stale_socket()
        real_lstat = Path.lstat

        def foreign_lstat(path, *args, **kwargs):
            info = real_lstat(path, *args, **kwargs)
            if path == self.path:
                # Real UDS, injected foreign UID: non-root tests cannot chown to another user.
                fields = list(info)
                fields[4] = os.geteuid() + 1
                return os.stat_result(fields)
            return info

        with (
            patch.object(Path, "lstat", foreign_lstat),
            patch.object(socket.socket, "connect", side_effect=AssertionError("foreign socket must not be probed")),
        ):
            self.assert_recovery_refused("foreign or non-socket")

    def test_symlink_and_dangling_symlink_are_refused(self):
        for target in (self.journal, self.path.parent / "absent"):
            with self.subTest(target=target):
                self.path.symlink_to(target)
                self.assert_recovery_refused("foreign or non-socket")
                self.assertTrue(self.path.is_symlink())
                self.path.unlink()
        self.assertEqual(self.journal.read_bytes(), b"synthetic sentinel: never open as a journal")

    def test_regular_file_and_directory_are_refused(self):
        self.path.write_bytes(b"not a socket")
        self.assert_recovery_refused("foreign or non-socket")
        self.assertEqual(self.path.read_bytes(), b"not a socket")
        self.path.unlink()
        self.path.mkdir()
        self.assert_recovery_refused("foreign or non-socket")

    def test_each_busy_lease_blocks_subprocess_recovery_and_releases_partial_leases(self):
        self.stale_socket()
        for path in self.lock_paths():
            with self.subTest(lock=path.name):
                inode = self.path.lstat().st_ino
                with path.open("a+b") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    result = subprocess.run(self.recover_command(), capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("already owns this lock", result.stderr)
                    self.assertEqual(self.path.lstat().st_ino, inode)
                for released in self.lock_paths():
                    with released.open("a+b") as lock:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertTrue(runtime.recover(self.state, self.path))

    def test_symlink_and_hardlinked_leases_are_refused(self):
        self.stale_socket()
        for path in self.lock_paths():
            for symlink in (True, False):
                with self.subTest(lock=path.name, symlink=symlink):
                    path.unlink(missing_ok=True)
                    if symlink:
                        path.symlink_to(self.journal)
                    else:
                        os.link(self.journal, path)
                    self.assert_recovery_refused("symbolic links|owned regular file")
                    path.unlink()
        self.assertEqual(self.journal.read_bytes(), b"synthetic sentinel: never open as a journal")

    def test_uncertain_connect_error_is_not_stale_evidence(self):
        self.stale_socket()
        with patch.object(socket.socket, "connect", side_effect=PermissionError(errno.EACCES, "synthetic denial")):
            self.assert_recovery_refused("Cannot prove")

    def test_replaced_inode_during_probe_is_preserved(self):
        self.stale_socket()
        real_connect = socket.socket.connect
        replaced = []

        def replace(probe, address):
            try:
                return real_connect(probe, address)
            except ConnectionRefusedError:
                self.path.rename(self.path.with_name("retired.sock"))
                self.stale_socket()
                replaced.append(self.path.lstat().st_ino)
                raise

        with patch.object(socket.socket, "connect", replace):
            with self.assertRaisesRegex(RuntimeError, "changed during stale check"):
                runtime.recover(self.state, self.path)
        self.assertEqual([self.path.lstat().st_ino], replaced)

    def test_missing_socket_is_noop_without_application_import_or_workload(self):
        before = set(sys.modules)
        with (
            patch.object(subprocess, "Popen", side_effect=AssertionError("no workloads")),
            patch.object(runtime.sqlite3, "connect", side_effect=AssertionError("no journal")),
        ):
            self.assertFalse(runtime.recover(self.state, self.path))
            self.stale_socket()
            self.assertTrue(runtime.recover(self.state, self.path))
        self.assertFalse(
            any(name.startswith(("isaaclab_arena", "isaaclab_arena_examples")) for name in set(sys.modules) - before)
        )

    def test_start_preflight_and_serve_do_not_automatically_recover(self):
        self.stale_socket()
        inode = self.path.lstat().st_ino
        with self.assertRaisesRegex(RuntimeError, "socket already exists") as preflight:
            runtime.preflight(self.state, self.path, None)
        self.assertIn("recover", str(preflight.exception))
        from argparse import Namespace

        with self.assertRaisesRegex(RuntimeError, "Socket already exists") as serve:
            runtime.serve(Namespace(state_dir=str(self.state), socket=str(self.path)))
        self.assertIn("recover", str(serve.exception))
        self.assertEqual(self.path.lstat().st_ino, inode)

    def test_fsync_failure_reports_failure_without_leaking_leases(self):
        self.stale_socket()
        with patch.object(os, "fsync", side_effect=OSError("synthetic fsync failure")):
            with self.assertRaisesRegex(OSError, "fsync failure"):
                runtime.recover(self.state, self.path)
        self.assertFalse(self.path.exists())
        for path in self.lock_paths():
            with path.open("r+b") as lock:
                self.assertTrue(stat.S_ISREG(os.fstat(lock.fileno()).st_mode))
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


if __name__ == "__main__":
    unittest.main()
