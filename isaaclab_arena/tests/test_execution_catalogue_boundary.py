# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Check explicit adapter vocabulary without loading the simulation registries."""

import asyncio
import copy
import hashlib
import json
import subprocess
import sys
import threading
import unittest
import yaml
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

CATALOGUE = {
    "assets": {
        "embodiments": [{"name": "franka_ik", "tags": []}],
        "backgrounds": [{"name": "maple_table_robolab", "tags": []}],
        "objects": [
            {"name": "rubiks_cube_hot3d_robolab", "tags": []},
            {"name": "bowl_ycb_robolab", "tags": []},
        ],
    },
    "relations": {
        "relations": [
            {"name": "is_anchor", "unary": True, "summary": "Test adapter anchor."},
            {"name": "on", "unary": False, "summary": "Test adapter support relation."},
        ]
    },
    "tasks": {
        "tasks": [{
            "name": "PickAndPlaceTask",
            "required_params": ["pick_up_object", "destination_location", "background_scene"],
            "summary": "Test adapter pick-and-place proposal.",
        }]
    },
}


class ExecutionCatalogueBoundary(unittest.TestCase):
    def test_bad_documents_remain_invalid_without_registry_fallback(self):
        from scripts.workflow_graphql_execution_join_fixture import synthetic_catalogue

        original = yaml.safe_load((Path(__file__).parent / "test_data/minimal_maple_table_env_graph.yaml").read_text())
        catalogue = synthetic_catalogue()
        documents = {}
        for name in ("asset", "task", "relation", "arity", "reference", "required_param", "unknown_field"):
            documents[name] = copy.deepcopy(original)
        documents["asset"]["embodiment"]["registry_name"] = "unavailable_asset"
        documents["task"]["task"]["subtasks"][0]["kind"] = "UnavailableTask"
        documents["relation"]["relations"][0]["kind"] = "unavailable_relation"
        documents["arity"]["relations"][0]["reference"] = original["objects"][0]["id"]
        documents["reference"]["relations"][0]["subject"] = "absent_node"
        documents["required_param"]["task"]["subtasks"][0]["params"].pop("pick_up_object")
        documents["unknown_field"]["unrecognized"] = True
        with patch("isaaclab_arena.assets.registries.ensure_assets_registered") as discovery:
            for name, document in documents.items():
                with self.subTest(invalid=name), self.assertRaises(ValueError):
                    catalogue.validate_document(yaml.safe_dump(document))
            discovery.assert_not_called()

    def test_catalogue_hash_and_context_are_bound_to_an_immutable_snapshot(self):
        from isaaclab_arena.environment_spec.execution_catalogue import ExecutionCatalogue, current_catalogue

        original = copy.deepcopy(CATALOGUE)
        catalogue = ExecutionCatalogue(original)
        expected = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        original["assets"]["objects"].clear()
        detached = catalogue.payload()
        detached["assets"]["objects"].clear()
        self.assertEqual(catalogue.sha256, expected)
        self.assertIsNone(current_catalogue())
        with catalogue.activate():
            self.assertIs(current_catalogue(), catalogue)
            with self.assertRaises(RuntimeError), ExecutionCatalogue(detached).activate():
                raise RuntimeError("leave inner scope")
            self.assertIs(current_catalogue(), catalogue)
        self.assertIsNone(current_catalogue())

    def test_server_json_codec_does_not_import_provider_or_simulator(self):
        code = """
import sys
sys.path[:] = PATHS
class NoExecutionImports:
    def find_spec(self, fullname, path=None, target=None):
        assert fullname.split('.')[0] not in {'openai', 'torch', 'isaaclab', 'isaacsim', 'pxr'}, fullname
sys.meta_path.insert(0, NoExecutionImports())
from isaaclab_arena.agentic_environment_generation.spec_wire_adapter import SpecWireAdapter
assert SpecWireAdapter.parse_json('{"value":true}') == {'value': True}
try:
    SpecWireAdapter.parse_json('{"value":1,"value":2}')
except ValueError:
    pass
else:
    raise AssertionError('Duplicate keys must remain invalid')
""".replace("PATHS", repr(sys.path))
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", code], capture_output=True, text=True, timeout=15
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_explicit_vocabulary_validates_real_schema_without_simulation_registration(self):
        data = yaml.safe_load((Path(__file__).parent / "test_data/minimal_maple_table_env_graph.yaml").read_text())
        with patch(
            "isaaclab_arena.assets.registries.ensure_assets_registered",
            side_effect=AssertionError("Simulation registration reached from orchestration validation"),
        ):
            spec = ArenaEnvGraphSpec.model_validate(data, context={"execution_catalogue": CATALOGUE})
        self.assertEqual(spec.embodiment.registry_name, "franka_ik")
        self.assertEqual(spec.task.subtasks[0].kind, "PickAndPlaceTask")

    def test_scoped_digest_and_worker_catalogues_use_actual_supplied_entries(self):
        from isaaclab_arena.environment_spec.execution_catalogue import ExecutionCatalogue
        from isaaclab_arena_examples.agentic_environment_generation.web_api.catalogues import execution_catalogue_sha256
        from isaaclab_arena_examples.agentic_environment_generation.web_api.scene_worker import prepare_catalogues

        catalogue = ExecutionCatalogue(CATALOGUE)
        with (
            catalogue.activate(),
            patch(
                "isaaclab_arena.assets.registries.ensure_assets_registered",
                side_effect=AssertionError("Full simulator catalogue was requested"),
            ),
        ):
            self.assertEqual(execution_catalogue_sha256(), catalogue.sha256)
            assets, relations, tasks = prepare_catalogues(catalogue.sha256)
            self.assertEqual(
                execution_catalogue_sha256(assets=assets, relations=relations, tasks=tasks), catalogue.sha256
            )
            self.assertEqual([entry.name for entry in tasks.tasks], ["PickAndPlaceTask"])
            with self.assertRaisesRegex(ValueError, "Catalogue mismatch"):
                prepare_catalogues("0" * 64)

    def test_deterministic_adapter_accepts_its_existing_documents(self):
        from scripts.workflow_graphql_execution_join_fixture import synthetic_catalogue

        catalogue = synthetic_catalogue()
        with patch(
            "isaaclab_arena.assets.registries.ensure_assets_registered",
            side_effect=AssertionError("Simulator discovery is not part of the adapter contract"),
        ):
            for name in ("minimal_maple_table_env_graph.yaml", "pick_and_place_maple_table_env_graph.yaml"):
                with self.subTest(document=name):
                    text = (Path(__file__).parent / "test_data" / name).read_text()
                    self.assertTrue(catalogue.validate_document(text)["valid"])

    def test_owner_drive_uses_adapter_vocabulary_after_submit_returns(self):
        from isaaclab_arena.agentic_environment_generation.workflow.api.execution_owner import ExecutionOwner
        from scripts.workflow_graphql_execution_join_fixture import contract, registrations, synthetic_catalogue

        catalogue = synthetic_catalogue()
        document = yaml.safe_load((Path(__file__).parent / "test_data/minimal_maple_table_env_graph.yaml").read_text())
        release = threading.Event()

        def drive():
            self.assertTrue(release.wait(3))
            return ArenaEnvGraphSpec.model_validate(document)

        receipt = SimpleNamespace(run_id="unit-run")
        root = SimpleNamespace(
            store=SimpleNamespace(lookup_submission=lambda *args: None),
            authority=SimpleNamespace(require_read=lambda *args: None),
            admit=lambda *args: (None, drive),
            service=SimpleNamespace(read_submission=lambda *args, **kwargs: receipt),
        )
        owner = ExecutionOwner(
            root,
            None,
            SimpleNamespace(recheck=lambda auth: None),
            lambda value: None,
            execution_context=catalogue.activate,
        )
        try:
            with patch(
                "isaaclab_arena.assets.registries.ensure_assets_registered",
                side_effect=AssertionError("Owner thread lost its adapter vocabulary"),
            ):
                result = asyncio.run(
                    owner.submit(SimpleNamespace(principal="unit-principal"), "unit-submit", contract(registrations()))
                )
                self.assertIs(result, receipt)
                release.set()
                assert owner._drive is not None
                self.assertEqual(owner._drive.result(timeout=3).embodiment.registry_name, "franka_ik")
        finally:
            release.set()
            owner._driver.shutdown(wait=True)
            owner._stopper.shutdown(wait=True)
            asyncio.run(owner.admissions.close(None))


if __name__ == "__main__":
    unittest.main()
