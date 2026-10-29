# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Stdlib-only synthetic-tree tests; run only via the approved isolated runner."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import confined_io
import stage as staging


class ConfinedReadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "source"
        self.root.mkdir()
        self.outside = self.base / "outside"
        self.outside.mkdir()
        (self.outside / "sentinel.py").write_bytes(b"OUTSIDE_SENTINEL")

    def assert_no_read(self, root, relative):
        with mock.patch.object(confined_io.os, "read", side_effect=AssertionError("unsafe bytes read")):
            with self.assertRaises((OSError, ValueError)):
                confined_io.read_confined(root, relative)

    def test_regular_capture(self):
        (self.root / "good.py").write_bytes(b"safe\x00bytes")
        self.assertEqual(confined_io.read_confined(self.root, "good.py"), b"safe\x00bytes")

    def test_leaf_and_ancestor_links_are_rejected_before_read(self):
        (self.root / "leaf.py").symlink_to(self.outside / "sentinel.py")
        (self.root / "nested").symlink_to(self.outside, target_is_directory=True)
        self.assert_no_read(self.root, "leaf.py")
        self.assert_no_read(self.root, "nested/sentinel.py")

    def test_root_and_root_ancestor_links_are_rejected(self):
        alias = self.base / "alias"
        alias.symlink_to(self.base, target_is_directory=True)
        self.assert_no_read(alias / "source", "anything.py")
        self.assert_no_read(alias, "outside/sentinel.py")

    def test_lexical_escapes_and_special_files_are_rejected(self):
        for relative in ("../outside/sentinel.py", str(self.outside / "sentinel.py"), "", "."):
            with self.subTest(relative=relative):
                self.assert_no_read(self.root, relative)
        os.mkfifo(self.root / "pipe")
        self.assert_no_read(self.root, "pipe")
        os.link(self.outside / "sentinel.py", self.root / "hard.py")
        self.assert_no_read(self.root, "hard.py")

    def test_leaf_replacement_between_stat_and_open_is_rejected(self):
        leaf = self.root / "safe.py"
        leaf.write_bytes(b"original")
        real_open = os.open
        def swapped(path, flags, *args, **kwargs):
            if str(path) == "safe.py":
                leaf.unlink()
                leaf.symlink_to(self.outside / "sentinel.py")
            return real_open(path, flags, *args, **kwargs)
        with mock.patch.object(confined_io.os, "open", side_effect=swapped):
            self.assert_no_read(self.root, "safe.py")

    def test_ancestor_replacement_between_stat_and_open_is_rejected(self):
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "sentinel.py").write_bytes(b"original")
        real_open = os.open
        def swapped(path, flags, *args, **kwargs):
            if str(path) == "nested":
                nested.rename(self.root / "old")
                nested.symlink_to(self.outside, target_is_directory=True)
            return real_open(path, flags, *args, **kwargs)
        with mock.patch.object(confined_io.os, "open", side_effect=swapped):
            self.assert_no_read(self.root, "nested/sentinel.py")

    def test_pinned_root_replacement_is_rejected(self):
        (self.root / "safe.py").write_bytes(b"original")
        with confined_io.ConfinedRoot(self.root) as source:
            self.root.rename(self.base / "old")
            self.root.mkdir()
            (self.root / "safe.py").write_bytes(b"replacement")
            with mock.patch.object(confined_io.os, "read", side_effect=AssertionError("replacement read")):
                with self.assertRaises(OSError):
                    source.read("safe.py")

    def test_regular_leaf_replacement_before_open_is_rejected(self):
        leaf = self.root / "safe.py"
        leaf.write_bytes(b"original")
        replacement = self.root / "replacement.py"
        replacement.write_bytes(b"replacement")
        real_open = os.open
        def swapped(path, flags, *args, **kwargs):
            if str(path) == "safe.py":
                replacement.replace(leaf)
            return real_open(path, flags, *args, **kwargs)
        with mock.patch.object(confined_io.os, "open", side_effect=swapped):
            self.assert_no_read(self.root, "safe.py")

    def test_destination_leaf_collision_and_root_replacement_are_rejected(self):
        destination = self.base / "destination"
        with confined_io.new_destination(destination) as output:
            (destination / "collision").symlink_to(self.outside / "sentinel.py")
            with self.assertRaises(OSError):
                output.write_new("collision", b"overwrite")
            (destination / "nested").symlink_to(self.outside, target_is_directory=True)
            with self.assertRaises(OSError):
                output.write_new("nested/sentinel.py", b"overwrite")
        output = confined_io.ConfinedRoot(destination)
        self.addCleanup(output.close)
        destination.rename(self.base / "old-destination")
        destination.symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(OSError):
            output.write_new("sentinel.py", b"overwrite")
        self.assertEqual((self.outside / "sentinel.py").read_bytes(), b"OUTSIDE_SENTINEL")

    def test_closed_capture_cannot_fall_back_to_cwd(self):
        source = confined_io.ConfinedRoot(self.root)
        source.close()
        with self.assertRaises(OSError):
            source.read("safe.py")

    def test_growing_file_is_not_read_until_eof(self):
        leaf = self.root / "safe.py"
        leaf.write_bytes(b"abc")
        real_read = os.read
        calls = []
        def growing(fd, count):
            calls.append(count)
            with leaf.open("ab") as stream:
                stream.write(b"more")
            return real_read(fd, count)
        with mock.patch.object(confined_io.os, "read", side_effect=growing):
            with self.assertRaises(OSError):
                confined_io.read_confined(self.root, "safe.py")
        self.assertLessEqual(sum(calls), 4)


class StagingTests(unittest.TestCase):
    def test_backend_selection_adds_only_exact_test_closure_and_approved_fixture(self):
        fixture = "isaaclab_arena/tests/test_data/minimal_maple_table_env_graph.yaml"
        self.put("isaaclab_arena/backend_helper.py", b"VALUE = 1\n")
        self.put("isaaclab_arena/tests/conftest.py", b"raise Exception('must not stage')\n")
        self.put("isaaclab_arena/tests/unapproved.py", b"raise Exception('must not stage')\n")
        self.put(fixture, b"env_name: synthetic\n")
        for index, selected in enumerate((
                "isaaclab_arena/tests/test_workbench_editor_revisions.py",
                "isaaclab_arena_examples/tests/test_workbench_graph_queries.py")):
            with self.subTest(selected=selected):
                self.put(selected, b"from isaaclab_arena.backend_helper import VALUE\n")
                destination = self.base / f"stage-{index}"
                manifest = staging.stage(self.root, destination, False, backend_tests=[selected])
                self.assertIn(selected, manifest)
                self.assertIn("isaaclab_arena/backend_helper.py", manifest)
                self.assertIn(fixture, manifest)
                self.assertNotIn("isaaclab_arena/tests/conftest.py", manifest)
                self.assertNotIn("isaaclab_arena/tests/unapproved.py", manifest)

    def test_backend_selection_rejects_unapproved_paths_before_capture(self):
        for selected in (["../outside.py"], ["isaaclab_arena/tests/unapproved.py"], ["-p", "plugin"],
                         ["isaaclab_arena/tests/test_workbench_editor_revisions.py"] * 2):
            with self.subTest(selected=selected), mock.patch.object(staging.ConfinedRoot, "read",
                                                                  side_effect=AssertionError("unsafe read")):
                with self.assertRaisesRegex(ValueError, "approved backend"):
                    staging.stage(self.root, self.destination, False, backend_tests=selected)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.destination = self.base / "stage"
        for folder in ("isaaclab_arena/assets", "isaaclab_arena/relations", "isaaclab_arena/tasks"):
            (self.root / folder).mkdir(parents=True)
        self.put("isaaclab_arena_examples/agentic_environment_generation/web_api/app.py", b"import isaaclab_arena.helper\n")
        self.put("isaaclab_arena/agentic_environment_generation/environment_generation_agent.py", b"# inert\n")
        self.put("isaaclab_arena/helper.py", b"VALUE = 'original'\n")
        self.put("isaaclab_arena/__init__.py", b"# package\n")
        self.put(staging.FIXTURE, b"approved: fixture\n")
        self.put(str(staging.HARNESS / "api.py"), b"# inert harness\n")

    def put(self, relative, data):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def test_capture_is_shared_by_parse_hash_and_copy(self):
        original = confined_io.ConfinedRoot.read
        reads = []
        def replacing(source, relative):
            data = original(source, relative)
            reads.append(str(relative))
            if str(relative) == "isaaclab_arena/helper.py":
                (self.root / relative).write_bytes(b"this is not valid python !!!\n")
            return data
        with mock.patch.object(confined_io.ConfinedRoot, "read", new=replacing):
            manifest = staging.stage(self.root, self.destination, False)
        frozen = b"VALUE = 'original'\n"
        self.assertEqual((self.destination / "isaaclab_arena/helper.py").read_bytes(), frozen)
        self.assertEqual(manifest["isaaclab_arena/helper.py"], hashlib.sha256(frozen).hexdigest())
        self.assertEqual(reads.count("isaaclab_arena/helper.py"), 1)
        self.assertEqual(len(reads), len(set(reads)))

    def test_frontend_imports_and_assets_have_positive_coverage(self):
        frontend = "web/arena-workbench/"
        sources = {
            "src/main.tsx": b"import './styles.css'; import View from './view'; import('./lazy');\n",
            "src/view/index.tsx": b"export default 1;\n",
            "src/lazy.ts": b"new URL('./icon.svg', import.meta.url);\n",
            "src/styles.css": b"body { background: url('./icon.svg'); }\n",
            "src/icon.svg": b"<svg/>\n",
            "vite.config.ts": b"import './config';\n",
            "config.ts": b"export default {};\n",
            "package.json": b"{}\n", "index.html": b"<html/>\n",
        }
        for name, data in sources.items():
            self.put(frontend + name, data)
        manifest = staging.stage(self.root, self.destination, True)
        for name, data in sources.items():
            with self.subTest(name=name):
                self.assertEqual((self.destination / (frontend + name)).read_bytes(), data)
                self.assertEqual(manifest[frontend + name], hashlib.sha256(data).hexdigest())

    def test_unsafe_discovery_directory_is_not_listed(self):
        assets = self.root / "isaaclab_arena/assets"
        assets.rmdir()
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "sentinel.py").write_bytes(b"SENTINEL")
        assets.symlink_to(outside, target_is_directory=True)
        with mock.patch.object(confined_io.os, "listdir", side_effect=AssertionError("unsafe traversal")):
            with self.assertRaises(OSError):
                staging.stage(self.root, self.destination, False)

    def test_fixture_harness_and_package_init_links_never_read_sentinel(self):
        for relative in (staging.FIXTURE, str(staging.HARNESS / "api.py"), "isaaclab_arena/__init__.py"):
            with self.subTest(relative=relative):
                source = self.root / relative
                old = source.read_bytes()
                sentinel = self.base / "sentinel"
                sentinel.write_bytes(b"SENTINEL")
                source.unlink()
                source.symlink_to(sentinel)
                with self.assertRaises(OSError):
                    staging.stage(self.root, self.destination, False)
                source.unlink()
                source.write_bytes(old)
                self.assertFalse(self.destination.exists())
                self.assertEqual(sentinel.read_bytes(), b"SENTINEL")

    def test_all_source_categories_reject_linked_ancestors(self):
        folders = (
            "isaaclab_arena", "isaaclab_arena/agentic_environment_generation",
            "isaaclab_arena/tests/test_data", str(staging.HARNESS),
            "isaaclab_arena_examples/agentic_environment_generation",
        )
        real_read = os.read
        for relative in folders:
            with self.subTest(relative=relative):
                original = self.root / relative
                parked = self.base / "parked"
                original.rename(parked)
                original.symlink_to(parked, target_is_directory=True)
                sentinel_ids = {
                    (info.st_dev, info.st_ino)
                    for path in parked.rglob("*") if path.is_file()
                    for info in [path.stat()]
                }
                def guarded(fd, count):
                    info = os.fstat(fd)
                    self.assertNotIn((info.st_dev, info.st_ino), sentinel_ids, "linked ancestor bytes read")
                    return real_read(fd, count)
                try:
                    with mock.patch.object(confined_io.os, "read", side_effect=guarded):
                        with self.assertRaises(OSError):
                            staging.stage(self.root, self.destination, False)
                    self.assertFalse(self.destination.exists())
                finally:
                    original.unlink()
                    parked.rename(original)

    def test_frontend_ancestor_link_and_lexical_escape_are_rejected(self):
        frontend = self.root / "web/arena-workbench"
        self.put("web/arena-workbench/vite.config.ts", b"// inert\n")
        self.put("web/arena-workbench/src/main.tsx", b"import './linked/sentinel';\n")
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "sentinel.ts").write_bytes(b"OUTSIDE_SENTINEL")
        (frontend / "src/linked").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            staging.stage(self.root, self.destination, True)
        self.put("web/arena-workbench/src/main.tsx", b"import '../../../outside/sentinel';\n")
        with self.assertRaises(ValueError):
            staging.stage(self.root, self.destination, True)
        self.assertFalse(self.destination.exists())

    def test_destination_collision_and_ancestor_link_cannot_escape(self):
        outside = self.base / "outside"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_bytes(b"unchanged")
        self.destination.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            staging.stage(self.root, self.destination, False)
        self.destination.unlink()
        self.destination.mkdir()
        (self.destination / "isaaclab_arena").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            staging.stage(self.root, self.destination, False)
        alias = self.base / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            staging.stage(self.root, alias / "new", False)
        self.assertFalse((outside / "new").exists())
        self.assertEqual(sentinel.read_bytes(), b"unchanged")


if __name__ == "__main__":
    unittest.main()
