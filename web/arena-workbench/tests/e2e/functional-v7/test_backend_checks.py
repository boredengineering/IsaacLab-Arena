# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Core runner contracts; stdlib tests run only in an owned isolated sandbox."""
import json
import os
import signal
import sys
import tempfile
import unittest
import uuid
from itertools import combinations
from pathlib import Path
from unittest import mock

import backend_checks

CORE = "isaaclab_arena/tests/test_workbench_editor_revisions.py"
API = "isaaclab_arena_examples/tests/test_workbench_editor_revision_api.py"
WORKFLOW = (
    "isaaclab_arena/tests/test_environment_workflow_contracts.py",
    "isaaclab_arena/tests/test_environment_workflow_readiness.py",
    "isaaclab_arena/tests/test_environment_workflow_decisions.py",
    "isaaclab_arena/tests/test_environment_workflow_store.py",
    "isaaclab_arena/tests/test_environment_workflow_repairs.py",
    "isaaclab_arena/tests/test_environment_workflow_evidence.py",
    "isaaclab_arena/tests/test_environment_workflow_import_boundaries.py",
    "isaaclab_arena/tests/test_environment_workflow_service.py",
)


class CoreRunnerTests(unittest.TestCase):
    def test_workflow_nonempty_unique_subsets_are_explicit_core_only(self):
        import stage

        self.assertTrue(set(WORKFLOW) <= set(stage.EXPLICIT_BACKEND_TESTS))
        self.assertEqual(backend_checks.selection([]), [CORE, API])
        self.assertFalse(backend_checks.core_only([]))
        for size in range(1, len(WORKFLOW) + 1):
            for subset in combinations(WORKFLOW, size):
                for names in (list(subset), list(reversed(subset))):
                    with self.subTest(names=names):
                        self.assertEqual(backend_checks.selection(names), names)
                        self.assertTrue(backend_checks.core_only(names))

    def test_workflow_admission_keeps_exact_path_and_duplicate_rejection(self):
        import stage

        for selected in WORKFLOW:
            for names in (
                [selected, selected],
                [*WORKFLOW, selected],
                [selected + "::test_x"],
                [selected, "--live"],
                [selected.replace(".py", "_unapproved.py")],
                ["/" + selected],
                ["./" + selected],
                ["isaaclab_arena/tests/../tests/" + Path(selected).name],
                ["isaaclab_arena/tests/test_environment_workflow_*.py"],
            ):
                with self.subTest(names=names):
                    for check in (backend_checks.selection, backend_checks.core_only):
                        with self.assertRaisesRegex(ValueError, "approved backend"):
                            check(names)
                    with mock.patch.object(stage, "ConfinedRoot") as source:
                        with self.assertRaisesRegex(ValueError, "approved backend"):
                            stage.stage("/unused", "/unused-destination", False, backend_tests=names)
                        source.assert_not_called()

    def test_workflow_admission_preserves_old_singletons_and_mixed_profiles(self):
        import stage

        self.assertTrue(set(WORKFLOW) <= set(stage.EXPLICIT_BACKEND_TESTS))
        old = [name for name in (*stage.BACKEND_TESTS, *stage.EXPLICIT_BACKEND_TESTS) if name not in WORKFLOW]
        old_core = {CORE, "isaaclab_arena/tests/test_trajectory_assessment.py"}
        self.assertEqual(stage.BACKEND_TESTS, (CORE, API))
        for name in old:
            self.assertEqual(backend_checks.selection([name]), [name])
            self.assertEqual(backend_checks.core_only([name]), name in old_core)
            for workflow in WORKFLOW:
                for names in ([name, workflow], [workflow, name], [*WORKFLOW, name]):
                    self.assertEqual(backend_checks.selection(names), names)
                    self.assertFalse(backend_checks.core_only(names))
        for pair in combinations(old, 2):
            for names in (list(pair), list(reversed(pair))):
                self.assertEqual(backend_checks.selection(names), names)
                self.assertFalse(backend_checks.core_only(names))

    def test_workflow_staging_captures_only_selected_inert_test_closure(self):
        import stage
        from test_confined_io import StagingTests

        self.assertTrue(set(WORKFLOW) <= set(stage.EXPLICIT_BACKEND_TESTS))
        fixture = StagingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.put(stage.BACKEND_FIXTURE, b"approved: fixture\n")
        helper = "isaaclab_arena/workflow_helper.py"
        fixture.put(helper, b"VALUE = 1\n")
        unapproved = "isaaclab_arena/tests/test_environment_workflow_unapproved.py"
        conftest = "isaaclab_arena/tests/conftest.py"
        for name in (*WORKFLOW, unapproved, conftest):
            fixture.put(name, b"from isaaclab_arena.workflow_helper import VALUE\n")
        for index, names in enumerate(([], list(WORKFLOW), list(WORKFLOW[::2]))):
            manifest = stage.stage(fixture.root, fixture.base / f"workflow-{index}", False, backend_tests=names)
            self.assertEqual(set(manifest) & set(WORKFLOW), set(names))
            self.assertEqual(helper in manifest, bool(names))
            self.assertNotIn(unapproved, manifest)
            self.assertNotIn(conftest, manifest)
        with mock.patch.object(stage, "ConfinedRoot") as source:
            with self.assertRaisesRegex(ValueError, "approved backend"):
                stage.stage(fixture.root, fixture.destination, True, backend_tests=list(WORKFLOW))
            source.assert_not_called()
        leaf = fixture.root / WORKFLOW[0]
        leaf.unlink()
        leaf.symlink_to(fixture.root / helper)
        with self.assertRaises((OSError, ValueError)):
            stage.stage(fixture.root, fixture.destination, False, backend_tests=[WORKFLOW[0]])
        self.assertFalse(fixture.destination.exists())

    def test_trajectory_assessment_is_explicit_core_only(self):
        selected = "isaaclab_arena/tests/test_trajectory_assessment.py"
        self.assertEqual(backend_checks.selection([selected]), [selected])
        self.assertTrue(backend_checks.core_only([selected]))
        self.assertEqual(backend_checks.selection([]), [CORE, API])
        self.assertFalse(backend_checks.core_only([selected, CORE]))
        for names in ([selected, selected], [selected + "::test_x"], [selected, "--live"]):
            with self.assertRaises(ValueError):
                backend_checks.selection(names)

    def test_native_policy_data_is_an_explicit_inert_fixture_closure(self):
        import stage

        selected = "isaaclab_arena_gr00t/tests/test_gr00t_remote_closedloop_policy.py"
        required = {
            stage.BACKEND_FIXTURE,
            "isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml",
            "isaaclab_arena_gr00t/embodiments/droid/gr00t_8dof_joint_space.yaml",
            "isaaclab_arena_gr00t/embodiments/droid/8dof_joint_space.yaml",
            "isaaclab_arena_gr00t/embodiments/droid/13dof_joint_space.yaml",
            "isaaclab_arena_gr00t/tests/test_data/test_g1_locomanip_lerobot/test_g1_locomanip_gr00t_closedloop_config.yaml",
            "isaaclab_arena_gr00t/embodiments/g1/gr00t_43dof_joint_space.yaml",
            "isaaclab_arena_gr00t/embodiments/g1/43dof_joint_space.yaml",
        }
        self.assertEqual(set(stage.backend_fixture_paths([selected])), required)
        self.assertEqual(stage.backend_fixture_paths([]), ())
        self.assertEqual(stage.backend_fixture_paths([CORE]), (stage.BACKEND_FIXTURE,))
        self.assertEqual(set(stage.backend_fixture_paths(["isaaclab_arena/tests/test_spec_wire_adapter.py"])), {
            stage.BACKEND_FIXTURE,
            "isaaclab_arena_environments/robolab/tasks/banana_on_plate.yaml",
            "isaaclab_arena_environments/robolab/scenes/bagel_plate_banana_bowl.yaml",
        })

    def test_stack_readiness_units_are_explicit_only(self):
        for selected in (
            "isaaclab_arena_examples/tests/test_workbench_readiness.py",
            "isaaclab_arena_examples/tests/test_workbench_paused_start.py",
            "isaaclab_arena_examples/tests/test_workbench_policy_readiness.py",
            "isaaclab_arena_examples/tests/test_workbench_policy_wire.py",
            "isaaclab_arena/tests/test_policy_contract.py",
            "isaaclab_arena_gr00t/tests/test_serving_metadata.py",
            "isaaclab_arena_gr00t/tests/test_gr00t_remote_closedloop_policy.py",
        ):
            with self.subTest(selected=selected):
                self.assertEqual(backend_checks.selection([selected]), [selected])
                self.assertEqual(backend_checks.selection([]), [CORE, API])
                self.assertFalse(backend_checks.core_only([selected]))
                for names in (
                    [selected, selected],
                    [selected + "::test_x"],
                    [selected, "--live"],
                    [selected.replace(".py", "_unapproved.py")],
                ):
                    with self.assertRaises(ValueError):
                        backend_checks.selection(names)

    def test_generation_diagnostics_are_explicit_only(self):
        selected = "isaaclab_arena_examples/tests/test_workbench_generation_diagnostics.py"
        self.assertEqual(backend_checks.selection([selected]), [selected])
        self.assertEqual(backend_checks.selection([]), [CORE, API])
        self.assertFalse(backend_checks.core_only([selected]))
        self.assertFalse(backend_checks.core_only([CORE, selected]))
        for names in (
            [selected, selected],
            [selected + "::test_x"],
            [selected, "--live"],
            [selected.replace("generation_diagnostics", "generation_diagnostics_unapproved")],
        ):
            with self.assertRaises(ValueError):
                backend_checks.selection(names)

    def test_model_profiles_are_explicit_only(self):
        for selected in (
            "isaaclab_arena/tests/test_inference_profiles.py",
            "isaaclab_arena_examples/tests/test_workbench_model_settings.py",
            "isaaclab_arena_examples/tests/test_workbench_workflow_authorization.py",
            "isaaclab_arena_examples/tests/test_workbench_execution_grants.py",
            "isaaclab_arena_examples/tests/test_workbench_reauthorization.py",
        ):
            self.assertEqual(backend_checks.selection([selected]), [selected])
            self.assertEqual(backend_checks.selection([]), [CORE, API])
            self.assertFalse(backend_checks.core_only([selected]))
            for names in (
                [selected, selected],
                [selected + "::test_x"],
                [selected, "--live"],
                ["isaaclab_arena/tests/test_inference_profiles_unapproved.py"],
            ):
                with self.assertRaises(ValueError):
                    backend_checks.selection(names)

    def test_inference_units_are_explicit_only_and_keep_other_boundaries(self):
        selected = "isaaclab_arena/tests/test_inference_backend.py"
        self.assertEqual(backend_checks.selection([selected]), [selected])
        self.assertEqual(backend_checks.selection([]), [CORE, API])
        self.assertFalse(backend_checks.core_only([selected]))
        for names in (
            [selected, selected],
            [selected + "::test_x"],
            [selected, "--live"],
            [selected.replace("inference_backend", "environment_generation_agent")],
        ):
            with self.assertRaises(ValueError):
                backend_checks.selection(names)

    def test_inference_unit_profile_only_allows_mockable_constructors(self):
        from types import SimpleNamespace

        from api import make_profile

        counts = dict.fromkeys(("network", "provider", "graph", "render", "workload", "subprocess"), 0)
        profile = backend_checks.inference_unit_profile(make_profile(counts))

        def frame(owner, module="synthetic", name="__init__"):
            return SimpleNamespace(
                f_globals={"__name__": module},
                f_code=SimpleNamespace(co_name=name),
                f_locals={"self": type(owner, (), {})()},
            )

        for owner in ("InferenceBackend", "OpenAI"):
            profile(frame(owner), "call", None)
        for owner in ("EnvironmentGenerationAgent", "AsyncOpenAI"):
            with self.assertRaisesRegex(RuntimeError, "provider"):
                profile(frame(owner), "call", None)
        with self.assertRaisesRegex(RuntimeError, "graph"):
            profile(frame("Driver", "neo4j"), "call", None)
        self.assertEqual(counts["provider"], 2)
        self.assertEqual(counts["graph"], 1)

    def test_explicit_research_and_graph_queries_keep_all_selection_guards(self):
        for name, sibling in (("manual_research_versions", "research_store"), ("graph_queries", "graph_access")):
            selected = f"isaaclab_arena_examples/tests/test_workbench_{name}.py"
            with self.subTest(selected=selected):
                self.assertEqual(backend_checks.selection([selected]), [selected])
                self.assertEqual(backend_checks.selection([]), [CORE, API])
                self.assertFalse(backend_checks.core_only([selected]))
                self.assertFalse(backend_checks.core_only([CORE, selected]))
                for names in (
                    [selected, selected],
                    [selected + "::test_x"],
                    [selected, "--live"],
                    [selected.replace(name, sibling)],
                ):
                    with self.assertRaises(ValueError):
                        backend_checks.selection(names)

    def test_core_import_boundary_blocks_api_but_does_not_fake_drivers(self):
        counts = dict.fromkeys(("network", "provider", "graph", "render", "workload", "subprocess"), 0)
        guard = backend_checks.CoreImportBoundary(counts)
        for name in (
            "isaaclab_arena_examples.agentic_environment_generation.web_api",
            "isaaclab_arena_examples.agentic_environment_generation.web_api.app",
        ):
            with self.assertRaisesRegex(ImportError, "core-only"):
                guard.find_spec(name, None)
        self.assertEqual(counts["workload"], 2)
        for name in ("neo4j", "neo4j.driver", "isaaclab_arena.agentic_environment_generation.workbench.documents"):
            self.assertIsNone(guard.find_spec(name, None))

    def test_core_main_never_acquires_driver_and_preserves_failed_test_cleanup(self):
        import run
        import stage

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "web/arena-workbench/tests/e2e/functional-v7/backend_checks.py"
            runs = []
            created = []
            owned_class = run.OwnedRun

            def owned(output, token):
                def command(*args):
                    if args[0] == "create":
                        created.append(args)
                        return "a" * 64
                    return ""

                value = owned_class(output, token, command)
                runs.append(value)
                return value

            def stage_bytes(repo, destination, browser, backend_tests):
                self.assertEqual(backend_tests, [CORE])
                destination.mkdir()
                (destination / "synthetic.py").write_bytes(b"# stdlib orchestration fixture only\n")
                import hashlib

                return {"synthetic.py": hashlib.sha256((destination / "synthetic.py").read_bytes()).hexdigest()}

            def wait(value, cid, path, timeout):
                path.write_text(
                    json.dumps({
                        "status": "failed",
                        "test_exit": 1,
                        "scope": "synthetic orchestration unit, not pytest evidence",
                    })
                )

            def verified(value, cid, mounts):
                value.proof["containers"].append({"id": cid, "image": "sha256:" + "b" * 64})

            with (
                mock.patch.object(backend_checks, "__file__", str(script)),
                mock.patch.object(run, "OwnedRun", side_effect=owned),
                mock.patch.object(
                    run, "discover", return_value={"host_root": "/synthetic", "runtime_image": "sha256:" + "b" * 64}
                ),
                mock.patch.object(stage, "stage", side_effect=stage_bytes),
                mock.patch.object(
                    run, "obtain_dependency", side_effect=AssertionError("core must not acquire drivers")
                ) as acquire,
                mock.patch.object(run, "verify_container", side_effect=verified),
                mock.patch.object(run, "docker", return_value="1"),
                mock.patch.object(run, "wait_file", side_effect=wait),
                mock.patch.object(backend_checks.os, "chown"),
            ):
                self.assertEqual(backend_checks.main([CORE]), 1)
            acquire.assert_not_called()
            self.assertEqual(len(created), 1)
            self.assertFalse(any("/pydeps" in part for part in created[0]))
            self.assertIn("PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", created[0])
            self.assertIn("-i", created[0])
            proof = json.loads((runs[0].output / "run-proof.json").read_text())
            self.assertEqual(proof["mode"], "core")
            self.assertEqual(proof["status"], "failed")
            self.assertEqual(proof["backend"]["test_exit"], 1)
            self.assertTrue(proof["cleanup_verified"])
            self.assertEqual(proof["remaining_owned"], [])
            self.assertTrue(proof["staged_source_unchanged"])

    def test_only_exact_core_selection_avoids_api_dependencies(self):
        self.assertTrue(backend_checks.core_only([CORE]))
        self.assertFalse(backend_checks.core_only([API]))
        self.assertFalse(backend_checks.core_only([]))
        self.assertFalse(backend_checks.core_only([CORE, API]))
        for names in ([CORE, CORE], ["--collect-only"], [CORE + "::test_x"]):
            with self.assertRaises(ValueError):
                backend_checks.core_only(names)


class RuntimeRunnerTests(unittest.TestCase):
    """Real selection/provenance validation with synthetic daemon boundaries."""

    def setUp(self):
        from test_check_proof import ProofTests

        fixture = ProofTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.provision = fixture.install_synthetic_provision()
        self.manifest = fixture.root / "provision-manifest.json"
        self.discovery = {
            "host_root": "/synthetic",
            "runtime_id": "c" * 64,
            "runtime_image": self.provision["recipe"]["base_image"],
        }
        self.image = self.provision["image"]

    def invoke(self, names, image, manifest, *, projection=None, dependency=None, container_image=None):
        import hashlib
        import inspect

        import run
        import stage

        self.assertIn(
            "runtime_image",
            inspect.signature(backend_checks.main).parameters,
            "backend main must accept a verified runtime override",
        )
        self.assertIn("provision_manifest", inspect.signature(backend_checks.main).parameters)
        if dependency is None:
            dependency = {
                "source_image": self.image,
                "files": {
                    name: value
                    for name, value in self.provision["recipe"]["files"].items()
                    if name.startswith("neo4j/")
                },
            }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "web/arena-workbench/tests/e2e/functional-v7/backend_checks.py"
            runs, created = [], []
            owned_class = run.OwnedRun

            def owned(output, token):
                def command(*args):
                    if args[0] == "create":
                        created.append(args)
                        return "a" * 64
                    return ""

                value = owned_class(output, token, command)
                runs.append(value)
                return value

            def stage_bytes(repo, destination, browser, backend_tests):
                self.assertEqual(backend_tests, names)
                destination.mkdir()
                data = b"# synthetic orchestration only, not backend evidence\n"
                (destination / "synthetic.py").write_bytes(data)
                return {"synthetic.py": hashlib.sha256(data).hexdigest()}

            def wait(value, cid, path, timeout):
                path.write_text(
                    json.dumps({"status": "failed", "test_exit": 1, "scope": "synthetic orchestration only"})
                )

            def metadata(value):
                key = "image_projection" if value == self.image else "base_projection"
                return self.provision[key]

            def verified(value, cid, mounts):
                value.proof["containers"].append({"id": cid, "image": container_image or self.image})

            with (
                mock.patch.object(backend_checks, "__file__", str(script)),
                mock.patch.object(run, "OwnedRun", side_effect=owned),
                mock.patch.object(run, "discover", return_value=self.discovery),
                mock.patch.object(run, "provision_image_metadata", side_effect=projection or metadata) as readback,
                mock.patch.object(stage, "stage", side_effect=stage_bytes) as staging,
                mock.patch.object(run, "obtain_dependency", return_value=dependency) as acquire,
                mock.patch.object(run, "verify_container", side_effect=verified),
                mock.patch.object(run, "docker", return_value="1") as daemon,
                mock.patch.object(run, "wait_file", side_effect=wait),
                mock.patch.object(backend_checks.os, "chown"),
            ):
                self.assertEqual(backend_checks.main(names, runtime_image=image, provision_manifest=manifest), 1)
            if container_image is not None:
                self.assertNotIn(
                    mock.call("start", "a" * 64),
                    daemon.call_args_list,
                    "Do not start a pytest container with mismatched image readback",
                )
            proof = json.loads((runs[0].output / "run-proof.json").read_text())
            if "provision" in proof.get("discovery", {}):
                saved = runs[0].output / "provision-manifest.json"
                self.assertEqual(json.loads(saved.read_text()), self.provision)
                self.assertEqual(
                    proof["artifacts"]["provision-manifest.json"], hashlib.sha256(saved.read_bytes()).hexdigest()
                )
            self.assertTrue(proof["cleanup_verified"])
            self.assertEqual(proof["remaining_owned"], [])
            self.assertNotIn("selected_runtime_image", self.discovery)
            return proof, created, acquire, staging, readback

    def test_unpaired_or_mutable_override_fails_before_staging_or_acquisition(self):
        for image, manifest in (
            (self.image, None),
            (None, self.manifest),
            ("latest", self.manifest),
            ("", self.manifest),
            (self.image, ""),
        ):
            with self.subTest(image=image, manifest=str(manifest)):
                proof, created, acquire, staging, readback = self.invoke([API], image, manifest)
                self.assertIn("override", proof["failure"])
                self.assertEqual(created, [])
                acquire.assert_not_called()
                staging.assert_not_called()
                readback.assert_not_called()

    def test_invalid_manifest_fails_before_staging_or_acquisition(self):
        for content in ("not json", "{}", json.dumps(dict(self.provision, status="failed"))):
            with self.subTest(content=content[:30]):
                self.manifest.write_text(content)
                proof, created, acquire, staging, readback = self.invoke([API], self.image, self.manifest)
                self.assertIn("failure", proof)
                self.assertEqual(created, [])
                acquire.assert_not_called()
                staging.assert_not_called()
                readback.assert_not_called()

    def test_mismatched_manifest_image_fails_before_image_readback(self):
        proof, created, acquire, staging, readback = self.invoke([API], "sha256:" + "f" * 64, self.manifest)
        self.assertIn("AssertionError", proof["failure"])
        self.assertEqual(created, [])
        acquire.assert_not_called()
        staging.assert_not_called()
        readback.assert_not_called()

    def test_mismatched_image_or_base_readback_fails_before_staging(self):
        for key in ("image_projection", "base_projection"):

            def metadata(image):
                actual = "image_projection" if image == self.image else "base_projection"
                value = self.provision[actual]
                return dict(value, Layers=[]) if actual == key else value

            with self.subTest(key=key):
                proof, created, acquire, staging, readback = self.invoke(
                    [API], self.image, self.manifest, projection=metadata
                )
                self.assertIn("readback mismatch", proof["failure"])
                self.assertEqual(created, [])
                acquire.assert_not_called()
                staging.assert_not_called()

    def test_verified_override_preserves_discovery_and_selects_exact_pytest_image(self):
        proof, created, acquire, staging, readback = self.invoke([API], self.image, self.manifest)
        self.assertEqual(
            proof["discovery"], dict(self.discovery, selected_runtime_image=self.image, provision=self.provision)
        )
        self.assertEqual(acquire.call_args.args[1], proof["discovery"])
        self.assertEqual(readback.call_args_list, [mock.call(self.image), mock.call(self.discovery["runtime_image"])])
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0][created[0].index("-i") - 1], self.image)
        self.assertTrue(any("dst=/pydeps,readonly" in part for part in created[0]))
        self.assertEqual(proof["backend"]["test_exit"], 1)

    def test_core_explicit_override_is_verified_without_driver_acquisition(self):
        proof, created, acquire, staging, readback = self.invoke([CORE], self.image, self.manifest)
        acquire.assert_not_called()
        self.assertEqual(proof["mode"], "core")
        self.assertEqual(proof["discovery"]["selected_runtime_image"], self.image)
        self.assertEqual(created[0][created[0].index("-i") - 1], self.image)
        self.assertFalse(any("/pydeps" in part for part in created[0]))
        self.assertEqual(readback.call_count, 2)

    def test_workflow_batch_uses_existing_core_runtime_without_driver_acquisition(self):
        import stage

        self.assertTrue(set(WORKFLOW) <= set(stage.EXPLICIT_BACKEND_TESTS))
        for names in (list(WORKFLOW), list(WORKFLOW[::2]), [WORKFLOW[-1]]):
            with self.subTest(names=names):
                proof, created, acquire, staging, readback = self.invoke(names, self.image, self.manifest)
                acquire.assert_not_called()
                self.assertEqual(proof["mode"], "core")
                self.assertEqual(proof["tests"], names)
                self.assertEqual(proof["dependency"]["packages_acquired"], [])
                self.assertEqual(created[0][created[0].index("-i") - 1], self.image)
                self.assertFalse(any("/pydeps" in part for part in created[0]))
                self.assertEqual(proof["backend"]["test_exit"], 1)
                self.assertEqual(proof["status"], "failed")
                self.assertTrue(proof["staged_source_unchanged"])
                self.assertEqual(readback.call_count, 2)

    def test_mismatched_donor_image_or_bytes_fails_before_pytest_creation(self):
        files = {name: value for name, value in self.provision["recipe"]["files"].items() if name.startswith("neo4j/")}
        for dependency in (
            {"source_image": self.discovery["runtime_image"], "files": files},
            {"source_image": self.image, "files": dict(files, **{"neo4j/__init__.py": "f" * 64})},
        ):
            with self.subTest(dependency=dependency):
                proof, created, acquire, staging, readback = self.invoke(
                    [API], self.image, self.manifest, dependency=dependency
                )
                self.assertIn("Provision/donor", proof["failure"])
                self.assertEqual(created, [])
                acquire.assert_called_once()

    def test_mismatched_pytest_image_readback_never_starts(self):
        for names in ([CORE], [API]):
            with self.subTest(names=names):
                proof, created, acquire, staging, readback = self.invoke(
                    names, self.image, self.manifest, container_image=self.discovery["runtime_image"]
                )
                self.assertIn("Pytest image readback mismatch", proof["failure"])


class SharedCliTests(unittest.TestCase):
    def setUp(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "functional_checks_cli", Path(__file__).with_name("run-functional-checks.py")
        )
        assert spec is not None and spec.loader is not None
        self.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cli)
        self.addCleanup(setattr, sys, "path", sys.path[:])
        self.image = "sha256:" + "a" * 64

    def test_backend_forwards_exact_override_and_selection(self):
        flags = ["--runtime-image", self.image, "--provision-manifest", "/synthetic/provision.json"]
        for args in (["backend", API, *flags], ["backend", *flags, API]):
            with self.subTest(args=args), mock.patch.object(backend_checks, "main", return_value=17) as main:
                self.assertEqual(self.cli.main(args), 17)
                main.assert_called_once_with(
                    [API], runtime_image=self.image, provision_manifest="/synthetic/provision.json"
                )

    def test_frontend_dependency_id_forwarding_and_scope(self):
        import frontend_checks
        import run

        cid = "d" * 64
        for mode in ("typecheck", "build"):
            with self.subTest(mode=mode), mock.patch.object(frontend_checks, "main", return_value=23) as main:
                self.assertEqual(
                    self.cli.main([mode, "--allow-frontend-verification", "--frontend-dependency-container", cid]), 23
                )
            main.assert_called_once_with(mode, True, frontend_dependency_container=cid)
        with mock.patch.object(run, "main", return_value=19) as main:
            self.assertEqual(self.cli.main(["api", "--browser", "--frontend-dependency-container", cid]), 19)
        main.assert_called_once_with(["--browser", "--frontend-dependency-container", cid])
        for mode in ("backend", "api", "security-units"):
            with self.subTest(mode=mode), self.assertRaises(SystemExit) as error:
                self.cli.main([mode, "--frontend-dependency-container", cid])
            self.assertEqual(error.exception.code, 2)

    def test_backend_without_override_preserves_core_selection(self):
        with mock.patch.object(backend_checks, "main", return_value=0) as main:
            self.assertEqual(self.cli.main(["backend", CORE]), 0)
        main.assert_called_once_with([CORE], runtime_image=None, provision_manifest=None)

    def test_api_override_forwarding_is_unchanged(self):
        import run

        with mock.patch.object(run, "main", return_value=19) as main:
            self.assertEqual(
                self.cli.main(
                    ["api", "--runtime-image", self.image, "--provision-manifest", "/synthetic/provision.json"]
                ),
                19,
            )
        main.assert_called_once_with(
            ["--runtime-image", self.image, "--provision-manifest", "/synthetic/provision.json"]
        )

    def test_unpaired_overrides_fail_before_dispatch(self):
        import run

        for mode in ("backend", "api"):
            for args in (["--runtime-image", self.image], ["--provision-manifest", "/synthetic/provision.json"]):
                with (
                    self.subTest(mode=mode, args=args),
                    mock.patch.object(backend_checks, "main") as backend,
                    mock.patch.object(run, "main") as api,
                ):
                    with self.assertRaises(SystemExit) as error:
                        self.cli.main([mode, *args])
                    self.assertEqual(error.exception.code, 2)
                    backend.assert_not_called()
                    api.assert_not_called()

    def test_non_runtime_modes_reject_overrides(self):
        for mode in ("security-units", "typecheck", "build"):
            with self.subTest(mode=mode), self.assertRaises(SystemExit) as error:
                self.cli.main(
                    [mode, "--runtime-image", self.image, "--provision-manifest", "/synthetic/provision.json"]
                )
            self.assertEqual(error.exception.code, 2)


def sandbox():
    """Run this suite and existing lifecycle guards without host test execution."""
    from confined_io import ConfinedRoot, new_destination, read_confined
    from run import OwnedRun, compare_source, discover, docker, hash_evidence, verify_container, wait_file
    from self_test import UNIT_SOURCES

    here = Path(__file__).resolve().parent
    root = here.parents[4]
    output = here / ".runs" / ("arena-core-units-" + uuid.uuid4().hex[:12])
    output.mkdir(parents=True)
    owned = OwnedRun(output, output.name)
    owned.proof.update(status="failed", scope="stdlib core-runner/lifecycle units, not backend acceptance")
    previous = {}

    def interrupted(signum, frame):
        raise InterruptedError(f"signal {signum}")

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, interrupted)
    try:
        discovery = discover(root, False)
        owned.proof["discovery"] = discovery
        import hashlib

        with ConfinedRoot(here) as source:
            captured = {name: source.read(name) for name in (*UNIT_SOURCES, "test_backend_checks.py")}
        with ConfinedRoot(root) as source:
            captured["run-functional-checks.py"] = source.read("scripts/run-functional-checks.py")
        with new_destination(output / "source") as destination:
            for name, data in captured.items():
                destination.write_new(name, data)
        owned.proof["source_sha256"] = {name: hashlib.sha256(data).hexdigest() for name, data in captured.items()}
        (output / "evidence").mkdir(mode=0o700)
        os.chown(output / "evidence", 1000, 1000)
        host = discovery["host_root"] + "/" + output.relative_to(root).as_posix()
        mounts = [f"type=bind,src={host}/source,dst=/source,readonly", f"type=bind,src={host}/evidence,dst=/evidence"]
        cid = owned.create(
            "tests",
            discovery["runtime_image"],
            "/usr/bin/env",
            [
                "-i",
                "HOME=/tmp",
                "PATH=/usr/bin:/bin",
                "PYTHONDONTWRITEBYTECODE=1",
                "PYTHONNOUSERSITE=1",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
                "NVIDIA_VISIBLE_DEVICES=void",
                "CUDA_VISIBLE_DEVICES=",
                "/isaac-sim/python.sh",
                "/source/test_backend_checks.py",
                "--inside",
            ],
            mounts,
        )
        verify_container(owned, cid, mounts)
        docker("start", cid)
        wait_file(owned, cid, output / "evidence/core-units.json", timeout=60)
        owned.proof["units"] = json.loads(read_confined(output, "evidence/core-units.json"))
        exit_code = docker("wait", cid)
        (output / "evidence/units.log").write_text(docker("logs", cid))
        assert exit_code == "0" and owned.proof["units"]["passed"]
        owned.proof["status"] = "passed"
    except BaseException:
        import traceback

        owned.proof["failure"] = traceback.format_exc()
    finally:
        for signum in previous:
            signal.signal(signum, signal.SIG_IGN)
        owned.proof["cleanup_verified"] = owned.cleanup()
        changed, rejected = compare_source(output / "source", owned.proof.get("source_sha256", {}))
        errors = changed + rejected
        owned.proof["staged_source_unchanged"] = bool(owned.proof.get("source_sha256")) and not errors
        owned.proof["artifacts"] = {}
        hash_evidence(output, owned.proof["artifacts"], errors)
        owned.proof["evidence_errors"] = errors
        if errors or not owned.proof["cleanup_verified"] or not owned.proof["staged_source_unchanged"]:
            owned.proof["status"] = "failed"
        owned.save()
        (output / "run-proof.json").write_text(json.dumps(owned.proof, indent=2))
        print(
            json.dumps({
                "output": str(output),
                "status": owned.proof["status"],
                "remaining_owned": owned.proof.get("remaining_owned"),
            })
        )
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return 0 if owned.proof["status"] == "passed" else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--sandbox"]:
        raise SystemExit(sandbox())
    if sys.argv[1:] != ["--inside"]:
        raise SystemExit("Use --sandbox; never run these tests on the host")
    from api import preflight, write

    preflight()
    suites = [
        unittest.defaultTestLoader.loadTestsFromTestCase(case)
        for case in (CoreRunnerTests, RuntimeRunnerTests, SharedCliTests)
    ]
    suites.extend(
        unittest.defaultTestLoader.discover(str(Path(__file__).parent), pattern=name)
        for name in ("test_run.py", "test_confined_io.py", "test_api.py")
    )
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(suites))
    passed = result.wasSuccessful() and result.testsRun > 0 and not result.skipped
    write(
        "core-units.json",
        {"passed": passed, "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)},
    )
    raise SystemExit(0 if passed else 1)
