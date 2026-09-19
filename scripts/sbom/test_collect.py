# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Tooling-only collection checks; never import or execute Arena."""
import importlib.util
import tempfile
import unittest
from pathlib import Path


class CollectionTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).with_name("collect.py")
        self.assertTrue(path.exists(), "SBOM collector not implemented")
        spec = importlib.util.spec_from_file_location("sbom_collect", path)
        assert spec is not None and spec.loader is not None
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "pyproject.toml").write_text('[project]\nname="example"\nversion="1.0"\n')

    def test_capture_exact_bytes_and_hash(self):
        output = self.root / "snapshot"
        result = self.module.capture(
            self.root, [{"path": "pyproject.toml", "scan": True, "kind": "manifest", "scope": "root"}], output
        )
        self.assertEqual((output / "inputs/pyproject.toml").read_bytes(), (self.root / "pyproject.toml").read_bytes())
        self.assertEqual(result["files"][0]["sha256"], self.module.sha256((self.root / "pyproject.toml").read_bytes()))

    def test_private_and_traversal_paths_rejected(self):
        for name in ["../outside", "/etc/passwd", ".env", "nested/.npmrc", ".git/config", "outputs/secret.json"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.module.read_input(self.root, name)

    def test_symlink_leaf_and_parent_rejected(self):
        (self.root / "alias.toml").symlink_to(self.root / "pyproject.toml")
        (self.root / "alias").symlink_to(self.root, target_is_directory=True)
        for name in ["alias.toml", "alias/pyproject.toml"]:
            with self.subTest(name=name), self.assertRaises((ValueError, OSError)):
                self.module.read_input(self.root, name)

    def test_bound_and_embedded_credentials_rejected(self):
        (self.root / "requirements.txt").write_text("https://operator:private-marker@example.invalid/pkg\n")
        with self.assertRaisesRegex(ValueError, "sensitive"):
            self.module.read_input(self.root, "requirements.txt")
        with self.assertRaises(ValueError):
            self.module.read_input(self.root, "pyproject.toml", max_bytes=2)

    def test_context_not_scanned_and_no_overwrite(self):
        output = self.root / "snapshot"
        entries = [{"path": "pyproject.toml", "scan": False, "kind": "context", "scope": "root"}]
        self.module.capture(self.root, entries, output)
        self.assertTrue((output / "context/pyproject.toml").is_file())
        self.assertFalse((output / "inputs/pyproject.toml").exists())
        with self.assertRaises(FileExistsError):
            self.module.capture(self.root, entries, output)

    def test_duplicate_scope_entry_rejected(self):
        item = {"path": "pyproject.toml", "scan": True, "kind": "manifest", "scope": "root"}
        with self.assertRaises(ValueError):
            self.module.capture(self.root, [item, item], self.root / "snapshot")


if __name__ == "__main__":
    unittest.main()
