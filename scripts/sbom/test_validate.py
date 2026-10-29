# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Standalone tooling tests; scanner fixture outputs are never synthesized."""

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOLING = ROOT / "outputs/sbom/tooling"


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.snapshot = Path(self.temp.name)
        shutil.copytree(TOOLING / "fixture", self.snapshot / "inputs")
        (self.snapshot / "source").mkdir()
        for suffix in ("syft", "cdx"):
            shutil.copyfile(TOOLING / f"fixture.{suffix}.json", self.snapshot / f"source/repository.{suffix}.json")
        self.manifest()

    def manifest(self):
        files = []
        for p in sorted((self.snapshot / "inputs").rglob("*")):
            if p.is_file():
                files.append(
                    dict(
                        path=str(p.relative_to(self.snapshot / "inputs")),
                        sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                        bytes=p.stat().st_size,
                        scan=True,
                        kind="lock",
                        scope="source-union",
                    )
                )
        self.write("input-manifest.json", {"files": files})
        self.bind_collection()

    def bind_collection(self):
        """Create a test-only collection envelope around actual scanner fixture bytes."""
        native = self.read("source/repository.syft.json")
        self.write("scope.json", self.read("input-manifest.json"))
        self.write(
            "collection.json",
            {
                "test_fixture": True,
                "scan_completed": True,
                "original_inputs_unchanged": True,
                "source_name": native["source"]["name"],
                "root_commit": native["source"]["version"],
                "commands": [{"name": "scan", "exit": 0}],
                "scope_sha256": hashlib.sha256((self.snapshot / "scope.json").read_bytes()).hexdigest(),
                "input_manifest_sha256": hashlib.sha256(
                    (self.snapshot / "input-manifest.json").read_bytes()
                ).hexdigest(),
                "output_sha256": {
                    f"source/repository.{s}.json": hashlib.sha256(
                        (self.snapshot / f"source/repository.{s}.json").read_bytes()
                    ).hexdigest()
                    for s in ("syft", "cdx")
                },
            },
        )

    def write(self, path, data):
        (self.snapshot / path).write_text(json.dumps(data))

    def read(self, path):
        return json.loads((self.snapshot / path).read_text())

    def run_cli(self):
        for name in ("validation.json", "coverage.json"):
            (self.snapshot / name).unlink(missing_ok=True)
        result = subprocess.run(
            [
                sys.executable,
                str(HERE / "validate.py"),
                "--snapshot",
                str(self.snapshot),
                "--schemas",
                str(TOOLING / "schemas"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertTrue((self.snapshot / "validation.json").exists(), result.stderr)
        return result, self.read("validation.json"), self.read("coverage.json")

    def test_invalid_evidence(self):
        for case in ("schema", "schema-type", "root", "target", "empty", "duplicate", "native"):
            with self.subTest(case=case):
                data = json.loads((TOOLING / "fixture.cdx.json").read_text())
                if case == "schema":
                    data["specVersion"] = "9.9"
                elif case == "schema-type":
                    data["components"][0]["type"] = "not-a-component-type"
                elif case == "root":
                    del data["metadata"]["component"]
                elif case == "target":
                    data["dependencies"][0]["dependsOn"].append("missing-target")
                elif case == "empty":
                    data["components"] = []
                elif case == "duplicate":
                    data["components"].append(copy.deepcopy(data["components"][0]))
                else:
                    data["components"][0]["version"] = "999"
                self.write("source/repository.cdx.json", data)
                result, validation, _ = self.run_cli()
                self.assertNotEqual(result.returncode, 0, case)
                self.assertTrue(validation["failures"])

    def test_hash_and_lock_reconciliation(self):
        lock = self.snapshot / "inputs/uv.lock"
        lock.write_text(
            lock.read_text()
            + '\n[[package]]\nname="missing"\nversion="1"\nsource={registry="https://pypi.org/simple"}\n'
        )
        result, report, _ = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any("hash" in f for f in report["failures"]))
        self.manifest()
        _, report, coverage = self.run_cli()
        self.assertFalse(report["ok"])
        self.assertEqual(coverage["missing"][0]["name"], "missing")
        lock.unlink()
        self.manifest()
        _, report, _ = self.run_cli()
        self.assertTrue(any("uv.lock" in f for f in report["failures"]))

    def test_source_variants_locations_and_limits(self):
        lock = self.snapshot / "inputs/uv.lock"
        lock.write_text(
            lock.read_text()
            + '\n[[package]]\nname="fixture-leaf"\nversion="1.2.3"\nsource={git="https://example.org/fork"}\n'
        )
        (self.snapshot / "inputs/requirements.txt").write_text("fixture-leaf>=1\n")
        (self.snapshot / "inputs/LICENSE").write_text("License evidence\n")
        nested = self.snapshot / "inputs/nested"
        nested.mkdir()
        shutil.copyfile(TOOLING / "fixture/uv.lock", nested / "uv.lock")
        self.manifest()
        _, _, coverage = self.run_cli()
        self.assertEqual(len(coverage["missing"]), 2)
        self.assertTrue(coverage["ambiguities"])
        dispositions = {p["path"]: p["disposition"] for p in coverage["inputs"]}
        self.assertEqual(dispositions["requirements.txt"], "partial")
        self.assertEqual(dispositions["LICENSE"], "not-package-metadata")
        self.assertEqual(len(coverage["inputs"][0]["limitations"]) > 0, True)

    def test_normalized_inventory(self):
        spec = importlib.util.spec_from_file_location("validator", HERE / "validate.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, "normalized_inventory"))
        original = self.read("source/repository.syft.json")
        changed = copy.deepcopy(original)
        changed["source"]["id"] = "other-root"
        changed["descriptor"]["timestamp"] = "other-time"
        self.assertEqual(module.normalized_inventory(original), module.normalized_inventory(changed))
        changed["artifacts"][0]["metadata"]["index"] = "other-origin"
        self.assertNotEqual(module.normalized_inventory(original), module.normalized_inventory(changed))
        changed = copy.deepcopy(original)
        changed["artifactRelationships"] = [e for e in changed["artifactRelationships"] if e["type"] != "dependency-of"]
        self.assertNotEqual(module.normalized_inventory(original), module.normalized_inventory(changed))
        changed = copy.deepcopy(original)
        changed["artifacts"][0]["locations"][0]["path"] = "/other/uv.lock"
        self.assertNotEqual(module.normalized_inventory(original), module.normalized_inventory(changed))

    def test_missing_files_and_npm_namespace_aliases(self):
        npm = self.read("inputs/package-lock.json")
        npm["packages"]["node_modules/@other/fixture-npm"] = {"version": "1.2.3"}
        npm["packages"]["node_modules/alias"] = {"name": "fixture-npm", "version": "1.2.3"}
        npm["packages"]["node_modules/workspace"] = {"link": True, "resolved": "packages/local"}
        self.write("inputs/package-lock.json", npm)
        self.manifest()
        _, _, coverage = self.run_cli()
        self.assertEqual(coverage["missing"][0]["name"], "@other/fixture-npm")
        self.assertEqual(len(coverage["unsupported"]), 2)
        (self.snapshot / "source/repository.syft.json").unlink()
        _, validation, _ = self.run_cli()
        self.assertFalse(validation["ok"])
        (self.snapshot / "input-manifest.json").unlink()
        _, validation, _ = self.run_cli()
        self.assertTrue(any("manifest" in f for f in validation["failures"]))

    def test_malformed_manifest_still_writes_failure(self):
        self.write("input-manifest.json", {"files": [None]})
        result, validation, _ = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(validation["failures"])

    def test_nested_components_are_reconciled(self):
        cdx = self.read("source/repository.cdx.json")
        child = cdx["components"].pop(1)
        cdx["components"][0]["components"] = [child]
        self.write("source/repository.cdx.json", cdx)
        self.bind_collection()
        result, validation, _ = self.run_cli()
        self.assertEqual(result.returncode, 0, validation)

    def test_positive_real_fixture(self):
        originals = [(p, p.read_bytes()) for p in (self.snapshot / "source").iterdir()]
        result, validation, coverage = self.run_cli()
        self.assertEqual(result.returncode, 0, validation)
        self.assertTrue(validation["ok"])
        self.assertEqual(len(coverage["inputs"]), 2)
        for path, content in originals:
            self.assertEqual(path.read_bytes(), content)

    def test_declared_dependency_missing_from_lock_and_inventory(self):
        (self.snapshot / "inputs/pyproject.toml").write_text(
            '[project]\nname="fixture-root"\nversion="0.0.0"\ndependencies=["fixture-leaf>=1", "missing-runtime>=2"]\n'
        )
        self.manifest()
        _, validation, coverage = self.run_cli()
        self.assertFalse(validation["source_coverage_complete"])
        missing = {r["name"]: r for r in coverage["declaration_gaps"]}
        self.assertEqual(set(missing), {"missing-runtime"})
        self.assertFalse(missing["missing-runtime"]["lock_candidates"])
        self.assertFalse(missing["missing-runtime"]["inventory_candidates"])
        self.assertEqual(len(coverage["root_declarations"]), 2)

    def test_dropped_approved_context_rejected_even_with_new_manifest_hash(self):
        (self.snapshot / "context").mkdir()
        (self.snapshot / "context/context.txt").write_bytes(b"context")
        manifest = self.read("input-manifest.json")
        manifest["files"].append(
            {"path": "context.txt", "scan": False, "bytes": 7, "sha256": hashlib.sha256(b"context").hexdigest()}
        )
        self.write("input-manifest.json", manifest)
        self.bind_collection()
        self.assertTrue(self.run_cli()[1]["ok"])
        manifest["files"].pop()
        self.write("input-manifest.json", manifest)
        collection = self.read("collection.json")
        collection["input_manifest_sha256"] = hashlib.sha256(
            (self.snapshot / "input-manifest.json").read_bytes()
        ).hexdigest()
        self.write("collection.json", collection)
        _, validation, _ = self.run_cli()
        self.assertFalse(validation["ok"])
        self.assertTrue(any("scope membership" in f for f in validation["failures"]))

    def test_wrong_source_identity_rejected_with_updated_output_hash(self):
        cdx = self.read("source/repository.cdx.json")
        cdx["metadata"]["component"]["version"] = "wrong-source-commit"
        self.write("source/repository.cdx.json", cdx)
        self.bind_collection()
        _, validation, _ = self.run_cli()
        self.assertFalse(validation["ok"])
        self.assertTrue(any("source identity" in f for f in validation["failures"]))

    def test_incomplete_collection_rejected(self):
        collection = self.read("collection.json")
        collection["scan_completed"] = False
        self.write("collection.json", collection)
        self.assertFalse(self.run_cli()[1]["ok"])


if __name__ == "__main__":
    unittest.main()
