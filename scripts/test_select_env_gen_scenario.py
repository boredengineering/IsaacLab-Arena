# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0


"""Stdlib-only checks for scenario selection; no Arena imports or execution."""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/select_env_gen_scenario.py"
CATALOGUE = ROOT / ".agents/references/agentic_env_generation/env_gen_test.md"


class SelectionTests(unittest.TestCase):
    def test_embedded_catalogue_preserves_every_original_prompt(self):
        module = self.module()
        selected = module.select(None, 42)
        _, original = module.read_catalogue(CATALOGUE)
        self.assertEqual(len(module.SCENARIOS), 10)
        keys = ("scenario_id", "test_name", "source_object", "target_container", "prompt")
        self.assertEqual(
            [{key: row[key] for key in keys} for row in selected["catalogue"]],
            [{key: row[key] for key in keys} for row in original],
        )
        self.assertEqual(selected["source"]["kind"], "embedded_catalogue")

    def module(self):
        spec = importlib.util.spec_from_file_location("scenario_selector", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_invalid_seed_is_not_coerced(self):
        module = self.module()
        for seed in (True, -1, 1.5, "42", 2**128):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                module.select(CATALOGUE, seed)

    def test_previous_is_excluded_without_rerolling_or_changing_seed(self):
        module = self.module()
        for previous in module.EXPECTED_IDS:
            result = module.select(None, 42, previous=previous)
            self.assertNotEqual(result["selected"]["scenario_id"], previous)
            self.assertEqual(result["selection"]["previous_scenario_id"], previous)
            self.assertEqual(result["selection"]["eligible_count"], 9)
            self.assertEqual(result, module.select(None, 42, previous=previous))
        with self.assertRaises(ValueError):
            module.select(None, 42, previous="A6")

    def test_replay_refuses_changed_source_before_drawing(self):
        module = self.module()
        original = module.select(CATALOGUE, 42)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "catalogue.md"
            source.write_bytes(CATALOGUE.read_bytes() + b"\nchanged\n")
            with patch.object(module.random, "Random", side_effect=AssertionError("Unexpected draw")):
                with self.assertRaisesRegex(ValueError, "digest"):
                    module.select(source, 42, expected_source_sha256=original["source"]["sha256"])

    def test_seed_replay_and_pool_reachability(self):
        module = self.module()
        first = module.select(CATALOGUE, 42)
        replay = module.select(CATALOGUE, 42, expected_source_sha256=first["source"]["sha256"])
        self.assertEqual(first, replay)
        reached = {module.select(CATALOGUE, seed)["selected"]["scenario_id"] for seed in range(100)}
        self.assertEqual(reached, set(module.EXPECTED_IDS))

    def test_invalid_pool_never_shrinks_silently(self):
        module = self.module()
        text = CATALOGUE.read_text()
        row = next(line for line in text.splitlines() if line.startswith("| **A1** |"))
        variants = (text.replace(row, ""), text.replace(row, row + "\n" + row), text.replace("**A1**", "**A6**"))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "catalogue.md"
            for variant in variants:
                with self.subTest(variant=variants.index(variant)):
                    source.write_text(variant)
                    with self.assertRaises(ValueError):
                        module.select(source, 42)

    def test_embedded_pool_cannot_silently_lose_or_duplicate_entries(self):
        module = self.module()
        original = module.SCENARIOS
        for invalid in (original[:-1], original + (original[0],)):
            with self.subTest(size=len(invalid)), patch.object(module, "SCENARIOS", invalid):
                with self.assertRaises(ValueError):
                    module.select(None, 42)

    def test_auto_seed_replay_and_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "selection.json"
            state = Path(directory) / "state.json"
            argv = [
                sys.executable,
                str(SCRIPT),
                "--catalogue",
                str(CATALOGUE),
                "--state",
                str(state),
                "--output",
                str(output),
            ]
            first = subprocess.run(argv, capture_output=True, text=True, timeout=10)
            self.assertEqual(first.returncode, 0, first.stderr)
            original = output.read_bytes()
            saved_state = state.read_bytes()
            selection = json.loads(original)
            retry = subprocess.run(argv, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(retry.returncode, 0)
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(state.read_bytes(), saved_state)
            replay = self.module().select(
                CATALOGUE, selection["selection"]["seed"], expected_source_sha256=selection["source"]["sha256"]
            )
            self.assertEqual(replay, selection)

    def test_cli_retains_exact_ten_scenarios_and_does_not_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "selection.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--seed",
                    "42",
                    "--catalogue",
                    str(CATALOGUE),
                    "--state",
                    str(Path(directory) / "state.json"),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            selection = json.loads(output.read_text())
            self.assertEqual(selection["execution"]["status"], "not_started")
            self.assertIsNone(selection["execution"]["run_id"])
            expected = [f"{category}{number}" for category in "AB" for number in range(1, 6)]
            self.assertEqual([row["scenario_id"] for row in selection["catalogue"]], expected)
            self.assertEqual(selection["selection"]["pool_size"], 10)
            self.assertEqual(selection["selected"], selection["catalogue"][selection["selection"]["index"]])
            mustard = next(row for row in selection["catalogue"] if row["scenario_id"] == "B2")
            self.assertEqual(mustard["target_container"], "purple_crate")
            self.assertEqual(
                mustard["prompt"],
                "Grasp the yellow mustard bottle from the right side and place it upright inside the purple storage"
                " crate.",
            )
            self.assertEqual(CATALOGUE.read_text().splitlines()[mustard["source_line"] - 1], mustard["source_row"])
            self.assertEqual(json.loads(result.stdout)["execution_status"], "not_started")

    def test_standalone_cli_print_and_persistent_no_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            standalone = directory / "selector.py"
            shutil.copyfile(SCRIPT, standalone)
            state = directory / "state.json"
            argv = [sys.executable, str(standalone), "--seed", "42", "--state", str(state), "--print"]
            results = []
            for _ in range(3):
                proc = subprocess.run(argv, capture_output=True, text=True, timeout=10)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                printed = json.loads(proc.stdout)
                saved = json.loads(Path(printed["output"]).read_text())
                self.assertEqual(printed["scenario"], saved["selected"])
                self.assertIn("prompt", printed["scenario"])
                self.assertIn("embodiment", printed["scenario"])
                if results:
                    self.assertNotEqual(printed["scenario"]["scenario_id"], results[-1])
                    self.assertEqual(printed["selection"]["previous_scenario_id"], results[-1])
                results.append(printed["scenario"]["scenario_id"])
            self.assertEqual(json.loads(state.read_text())["previous_scenario_id"], results[-1])

    def test_bootstrap_previous_and_corrupt_history_do_not_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            argv = [sys.executable, str(SCRIPT), "--state", str(state), "--previous", "B1", "--print"]
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=10)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertNotEqual(result["scenario_id"], "B1")
            self.assertEqual(result["selection"]["previous_scenario_id"], "B1")
            saved = state.read_bytes()
            conflict = subprocess.run(argv, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(conflict.returncode, 0)
            self.assertEqual(state.read_bytes(), saved)
            for corrupt in (
                "{",
                '{"schema_version":true,"previous_scenario_id":"A1"}',
                '{"schema_version":1,"previous_scenario_id":"A6"}',
            ):
                with self.subTest(corrupt=corrupt):
                    state.write_text(corrupt)
                    failed = subprocess.run(argv, capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(failed.returncode, 0)
                    self.assertEqual(failed.stdout, "")
                    self.assertEqual(state.read_text(), corrupt)


if __name__ == "__main__":
    unittest.main()
