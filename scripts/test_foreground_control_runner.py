# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Host-only stdlib fake-Docker regressions; never import application code."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).absolute().parents[1]
HELPERS = ROOT / "web/arena-workbench/tests/e2e/functional-v7"
sys.path.insert(0, str(HELPERS))
import run as f0

spec = importlib.util.spec_from_file_location(
    "foreground_fixture", ROOT / "isaaclab_arena_examples/tests/foreground_control_fixture.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class FakeDocker:
    """Model only public metadata, including a create accepted after lost ACK."""

    def __init__(self, root, mode="ok"):
        self.root, self.mode = root, mode
        self.calls = []
        self.cid = "a" * 64
        self.name = self.token = None
        self.present = False

    def __call__(self, argv, **kwargs):
        assert argv[0] == "docker", argv
        args = argv[1:]
        self.calls.append(args)
        out = ""
        if args[0] == "ps":
            if "--filter" not in args:
                out = "b" * 64
            elif self.present:
                out = self.cid
        elif "inspect" in args:
            assert "--format" in args, "Full Docker inspect fetched private metadata"
            fmt = args[args.index("--format") + 1]
            assert not any(key in fmt for key in (".Config.Env", ".Config.Cmd", ".Config.Entrypoint"))
            assert "{{json .Config}}" not in fmt and "{{json .}}" not in fmt
            if args[0] == "image":
                info = {"Id": fixture.IMAGE, "Volumes": None}
            elif args[-1] == "b" * 64:
                info = {"Id": "b" * 64, "Image": fixture.IMAGE, "Mounts": [
                    {"Type": "bind", "Source": str(self.root), "Destination": str(self.root), "RW": True},
                    {"Type": "bind", "Source": str(self.root), "Destination": "/workspaces/isaaclab_arena", "RW": True},
                ]}
            elif fmt == f0.IDENTITY_FORMAT:
                info = {"Id": self.cid, "Name": "/" + self.name,
                        "Label": "foreign" if self.mode == "foreign" else self.token}
                if self.mode == "replaced":
                    info["Id"] = "c" * 64
            elif fmt == f0.OWN_FORMAT:
                info = {"Id": self.cid, "Name": "/" + self.name, "Image": fixture.IMAGE,
                        "Config": {"User": "1000:1000", "Labels": {f0.LABEL: self.token}},
                        "HostConfig": {"NetworkMode": "host" if self.mode == "unsafe" else "none",
                                       "ReadonlyRootfs": True, "CapDrop": ["ALL"], "CapAdd": [],
                                       "SecurityOpt": ["no-new-privileges"], "Privileged": False,
                                       "IpcMode": "private", "PidsLimit": 64, "Memory": 1073741824,
                                       "Tmpfs": {"/tmp": "rw,nosuid,nodev", "/private": "rw,nosuid,nodev"}},
                        "Mounts": [{"Type": "bind", "Source": str(self.source), "Destination": "/source", "RW": False}]}
            else:
                info = {"Id": self.cid, "Image": fixture.IMAGE, "NanoCpus": 2000000000}
            out = json.dumps(info)
        elif args[0] == "create":
            self.name = args[args.index("--name") + 1]
            self.token = args[args.index("--label") + 1].split("=", 1)[1]
            self.source = self.root / "outputs/workflow" / self.token / "source"
            ownership = json.loads((self.source.parent / "ownership.json").read_text())
            assert self.name in ownership["candidates"], "Create intent not durable"
            assert "--pull=never" in args
            if self.mode in {"lost", "lost-visible"}:
                self.present = self.mode == "lost-visible"
                raise subprocess.TimeoutExpired(argv, 30)
            self.present = True
            out = self.cid
        elif args[0] == "start":
            assert any(c[0] == "inspect" and f0.OWN_FORMAT in c for c in self.calls)
        elif args[0] == "wait":
            out = "0"
        elif args[0] == "logs":
            manifest = json.loads((self.source / "manifest.json").read_text())
            junit = '<testsuites><testsuite tests="16" failures="0" errors="0" skipped="0">'
            junit += ''.join(f'<testcase name="case{i}"/>' for i in range(16))
            junit += '</testsuite></testsuites>'
            if self.mode == "failed-junit":
                junit = junit.replace('<testcase name="case0"/>', '<testcase name="case0"><failure/></testcase>')
            payload = dict(manifest=manifest, forbidden=[], result=0, junit=junit)
            out = "" if self.mode == "missing" else "CANCEL01_PROOF " + json.dumps(payload)
        elif args[0] == "rm":
            assert args == ["rm", "-f", self.cid], "Removal must use immutable ID"
            self.present = False
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(argv, 0, out if kwargs.get("text") else out.encode(),
                                           "" if kwargs.get("text") else b"")


class RunnerTests(unittest.TestCase):
    def exercise(self, mode="ok"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for rel in fixture.FILES:
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# inert captured fixture\n")
        (root / "outputs/workflow").mkdir(parents=True)
        fake = FakeDocker(root, mode)
        if mode == "symlink-source":
            (root / fixture.TEST).unlink()
            (root / fixture.TEST).symlink_to(root / fixture.CONTROL)
        from confined_io import ConfinedRoot

        original_read = ConfinedRoot.read
        original_save = f0.OwnedRun.save
        captured = []
        fake.snapshots = []

        def save(owned):
            original_save(owned)
            fake.snapshots.append(json.loads((owned.output / "ownership.json").read_text()))

        def read(source, rel):
            if source.root == root:
                captured.append(rel)
            return original_read(source, rel)

        with mock.patch.object(fixture, "__file__", str(root / fixture.SELF)), \
             mock.patch.object(ConfinedRoot, "read", read), \
             mock.patch.object(f0.OwnedRun, "save", save), \
             mock.patch.object(subprocess, "run", fake):
            result = fixture.sandbox()
        if mode != "symlink-source":
            self.assertEqual(captured, list(fixture.FILES), "Capture each live source exactly once")
        proofs = list((root / "outputs/workflow").glob("*/proof.json"))
        self.assertEqual(len(proofs), 1)
        return result, json.loads(proofs[0].read_text()), fake

    def test_source_symlink_rejected_before_create(self):
        result, proof, fake = self.exercise("symlink-source")
        self.assertEqual(result, 1)
        self.assertFalse(any(call[0] == "create" for call in fake.calls))
        self.assertFalse(proof["staged_source_unchanged"])

    def test_lost_create_ack_empty_listings_are_not_authoritative(self):
        result, proof, fake = self.exercise("lost")
        self.assertEqual(result, 1)
        self.assertFalse(proof["cleanup_verified"])
        self.assertFalse(proof["cleanup_verification"]["authoritative"])
        self.assertTrue(all(not snapshot.get("cleanup_verification", {}).get("authoritative", False)
                            for snapshot in fake.snapshots))
        # The daemon can accept after every cleanup listing has already returned.
        fake.present = True
        self.assertFalse(proof["cleanup_verification"]["authoritative"])

    def test_lost_ack_visible_container_removed_but_obligation_unresolved(self):
        result, proof, fake = self.exercise("lost-visible")
        self.assertEqual(result, 1)
        self.assertIn(["rm", "-f", fake.cid], fake.calls)
        self.assertFalse(proof["cleanup_verified"])
        self.assertFalse(proof["cleanup_verification"]["authoritative"])

    def test_foreign_label_or_replaced_id_never_removed(self):
        for mode in ("foreign", "replaced"):
            with self.subTest(mode=mode):
                result, proof, fake = self.exercise(mode)
                self.assertEqual(result, 1)
                self.assertFalse(proof["cleanup_verified"])
                self.assertFalse(any(call[0] == "rm" for call in fake.calls))

    def test_isolation_rejected_before_start(self):
        result, proof, fake = self.exercise("unsafe")
        self.assertEqual(result, 1)
        self.assertFalse(any(call[0] == "start" for call in fake.calls))
        self.assertTrue(proof["cleanup_verified"])

    def test_missing_or_failed_junit_never_passes(self):
        for mode in ("missing", "failed-junit"):
            with self.subTest(mode=mode):
                result, proof, fake = self.exercise(mode)
                self.assertEqual(result, 1)
                self.assertEqual(proof["status"], "failed")
                self.assertTrue(proof["cleanup_verified"])

    def test_metadata_only_owned_lifecycle(self):
        result, proof, fake = self.exercise()
        self.assertEqual(result, 0)
        self.assertTrue(proof["cleanup_verified"])
        self.assertFalse(fake.present)
        self.assertEqual(proof["tests"], 16)
        self.assertEqual(set(proof["source_sha256"]), set(fixture.FILES))
        self.assertTrue(proof["staged_source_unchanged"])
        self.assertIn(["rm", "-f", fake.cid], fake.calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
