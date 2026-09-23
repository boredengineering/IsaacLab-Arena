# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""S2 source-isolated guard checks; host checks are NOT Arena runtime proof."""

import ast
import copy
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts/workflow_graphql_execution_join_harness.py"
FIXTURE = ROOT / "scripts/workflow_graphql_execution_join_fixture.py"


def isolated(path, names):
    """Compile named pure functions only, never import a harness/package closure."""
    tree = ast.parse(path.read_text())
    selected: list[ast.stmt] = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in selected if isinstance(node, ast.FunctionDef)} == set(names), "missing S2 pure guard"
    namespace = {}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class InitializationStaticGuards(unittest.TestCase):
    def test_fixed_environment_and_argv(self):
        fn = isolated(HARNESS, {"initialization_environment"})["initialization_environment"]
        for role in ("init-server", "init-generate", "init-refine", "init-assess"):
            env = fn("positive", role)
            root = "/tmp/s2-init/positive/" + role
            self.assertEqual(env["HOME"], root + "/home")
            self.assertEqual(env["WARP_CACHE_PATH"], root + "/cache/warp")
            self.assertEqual(env["XDG_CACHE_HOME"], root + "/cache")
            self.assertEqual(env["TMPDIR"], root + "/tmp")
            self.assertEqual(env["PATH"], "/usr/bin:/bin")
            self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "")
            self.assertEqual(env["NVIDIA_VISIBLE_DEVICES"], "void")
        for case, role in (("unknown", "init-server"), ("positive", "../escape"), (True, "init-server")):
            with self.assertRaises(AssertionError):
                fn(case, role)

    def test_exact_package_origins_no_fallback(self):
        fn = isolated(HARNESS, {"initialization_origin"})["initialization_origin"]
        pure = "/isaac-sim/kit/python/lib/python3.12/site-packages/"
        yaml = "/isaac-sim/exts/omni.pip.compute/pip_prebundle/yaml/"
        self.assertEqual(fn("warp._src.context", pure + "warp/_src/context.py", False), "warp")
        self.assertEqual(fn("yaml", yaml + "__init__.py", False), "yaml")
        for name, origin, preloaded in (
            ("openai", yaml + "openai/__init__.py", False),
            ("yaml", pure + "yaml/__init__.py", False),
            ("warp", pure + "warp/../other.py", False),
            ("warp", pure + "warp/__init__.py", True),
            ("warp", pure + "warp_shadow/__init__.py", False),
            ("unknown", pure + "unknown/__init__.py", False),
            ("warp", pure + "warp/__init__.py", 0),
        ):
            with self.assertRaises(AssertionError):
                fn(name, origin, preloaded)

    def test_incomplete_proofs_cannot_pass(self):
        fn = isolated(HARNESS, {"initialization_verify_proof"})["initialization_verify_proof"]
        junit = (
            b'<testsuites><testsuite tests="1"><testcase name="test_initialization_positive"/></testsuite></testsuites>'
        )
        incomplete = dict(status="passed", mode="workflow-graphql-initialization", case="positive", tests=1)
        for patch in ({}, {"status": "failed"}, {"tests": 0}, {"case": "failure"}):
            value = copy.deepcopy(incomplete)
            value.update(patch)
            with self.assertRaises((AssertionError, KeyError)):
                fn(value, junit, "positive")
        with self.assertRaises(AssertionError):
            fn(incomplete, junit, "arbitrary")

    def test_unfinished_dispatch_is_explicit_nonpass(self):
        fn = isolated(HARNESS, {"initialization_inside"})["initialization_inside"]
        written = []
        fn.__globals__["write_evidence"] = lambda name, value: written.append((name, value))
        for case in ("positive", "failure", "timeout"):
            proof = fn(case)
            self.assertEqual(proof["status"], "failed")
            self.assertEqual(proof["case"], case)
            self.assertEqual(proof["tests"], 0)
            self.assertFalse(proof["execution_attempted"])
            self.assertTrue(proof["release_blockers"])
            self.assertEqual(written[-1], ("client-proof.json", proof))
        with self.assertRaises(AssertionError):
            fn("arbitrary")

    def test_fault_hook_is_at_real_owner_entry_before_admission(self):
        tree = ast.parse(HARNESS.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "JoinGuards")
        profile = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "profile")
        # Raising from a profile callback disables that callback in CPython.
        # The fault must be a direct real build call with the effect guard intact.
        self.assertNotIn("initialization_pre_readiness", ast.unparse(profile))
        path = ROOT / "isaaclab_arena/agentic_environment_generation/workflow/api/installed_execution.py"
        text = ast.unparse(ast.parse(path.read_text()))
        self.assertIn("initialization_pre_readiness", text)
        self.assertLess(
            text.index("catalogue_digest = execution_catalogue_sha256()"), text.index("checkpoint(catalogue_digest)")
        )
        self.assertLess(text.index("checkpoint(catalogue_digest)"), text.index("app = ForegroundWorkflow("))
        hook = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "initialization_pre_readiness")
        hook_text = ast.unparse(hook)
        self.assertIn("before_owner_construction", hook_text)
        self.assertIn("initialization_case", hook_text)
        self.assertNotIn("ready = True", hook_text)
        fn = isolated(HARNESS, {"initialization_pre_readiness"})["initialization_pre_readiness"]
        fn.__globals__["ACTIVE"] = object()
        self.assertIsNone(fn("legacy-digest"))

    def test_worker_catalogue_preparation_is_shared(self):
        path = ROOT / "isaaclab_arena_examples/agentic_environment_generation/web_api/scene_worker.py"
        tree = ast.parse(path.read_text())
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertIn("prepare_catalogues", functions)
        self.assertIn("prepare_catalogues(inputs['execution_catalogue_sha256'])", ast.unparse(functions["execute"]))
        text = ast.unparse(functions["prepare_catalogues"])
        for required in (
            "build_asset_catalogue()",
            "build_relation_catalogue()",
            "build_task_catalogue()",
            "execution_catalogue_sha256",
            "Catalogue mismatch",
        ):
            self.assertIn(required, text)

    def test_real_preparation_not_initializer_substitution(self):
        tree = ast.parse(FIXTURE.read_text())
        fn = next(
            (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "initialization_preparation"), None
        )
        self.assertIsNotNone(fn, "missing real schema preparation")
        assert fn is not None
        text = ast.unparse(fn)
        for required in (
            "install_synthetic_sdk(scene=True)",
            "ArenaEnvGraphSpec.model_validate",
            "minimal_spec_dict",
            "reject_unknown_fields",
            "execution_catalogue_sha256",
        ):
            self.assertIn(required, text)
        self.assertNotIn("platform.processor =", text)
        self.assertNotIn("warp.init =", text)
        self.assertNotIn("sys.modules[", text)


def unitonly_proof(case="positive") -> tuple[dict, bytes]:
    """UNITONLY synthetic full-schema vector; never actual runtime evidence."""
    import hashlib

    junit = (
        '<testsuites><testsuite tests="1"><testcase name="test_initialization_' + case + '"/></testsuite></testsuites>'
    ).encode()
    source = {"UNITONLY.py": "a" * 64}
    physical = dict(
        path="/isaac-sim/kit/python/lib/python3.12/site-packages/warp/bin/warp.so", links=[], size=1024, sha256="b" * 64
    )
    physical["physical"] = physical["path"]
    module_path = "/isaac-sim/kit/python/lib/python3.12/site-packages/warp/__init__.py"
    module = dict(physical, name="warp", path=module_path, physical=module_path, origin=module_path, preloaded=False)
    roles = ["init-server", "init-generate", "init-refine", "init-assess"] if case == "positive" else ["init-server"]
    rows = [
        dict(
            role=role,
            pid=100 + index,
            pgid=100 + index,
            sid=100 + index,
            start_ticks=1,
            source_sha256=source,
            preimport={"before_package_imports": True},
            real_preparation_complete=True,
            cache_verified=True,
            native_bindings_verified=True,
            module_origins_verified=True,
            platform_processor_unmodified=True,
            usable_gpu=False,
            native_libraries=[copy.deepcopy(physical)],
            module_origins=[copy.deepcopy(module)],
            cache_before=[],
            cache_after=[],
            catalogue_sha256="c" * 64,
            schema_checks=[
                "supported_normalization",
                "unknown_asset",
                "unknown_relation",
                "dangling_reference",
                "unknown_yaml_field",
                "catalogue_agreement",
                "catalogue_disagreement",
            ],
        )
        for index, role in enumerate(roles)
    ]
    proof = dict(
        evidence_label="UNITONLY synthetic; not runtime evidence",
        mode="workflow-graphql-initialization",
        case=case,
        status="passed",
        tests=1,
        junit_sha256=hashlib.sha256(junit).hexdigest(),
        image="sha256:b94e17024f1e123ac5a42759ab56651a18823fda7c701e765cba31f200154cdd",
        provision_manifest_sha256="03764536ed54c1f59cbf46305c5bc4ba618e2dc1deeeac7ffdfb21a0dffbf810",
        source_sha256=source,
        release_blockers=[],
        missing_process_witnesses=[],
        children_verified=True,
        owned_groups_absent=True,
        sdk_calls=0,
        provider_constructions=0,
        readiness_observed=False,
        owner_admitted=False,
        forbidden=dict.fromkeys(
            ("network", "subprocess", "provider", "runtime", "graph", "legacy", "blocked_import"), 0
        ),
        initialization_roles=rows,
    )
    if case != "positive":
        proof["pre_readiness_failure"] = dict(
            after_real_initialization=True,
            before_owner_construction=True,
            case=case,
            readiness_absent=True,
            server_pid=100,
            original_failure_retained=True,
            catalogue_sha256="c" * 64,
            kind="fixed-initialization-failure" if case == "failure" else "supervisor-stall-not-native-hang",
            stall_seconds=5,
            group_reap_seconds=1,
        )
    return proof, junit


class InitializationFullProofGuards(unittest.TestCase):
    """UNITONLY full-reader regressions, not native-execution negatives."""

    def setUp(self):
        self.verify = isolated(HARNESS, {"initialization_verify_proof", "initialization_origin"})[
            "initialization_verify_proof"
        ]

    def test_unitonly_full_schema_controls(self):
        for case in ("positive", "failure", "timeout"):
            for digest in ("c" * 64, "d" * 64):
                proof, junit = unitonly_proof(case)
                for row in proof["initialization_roles"]:
                    row["catalogue_sha256"] = digest
                if case != "positive":
                    proof["pre_readiness_failure"]["catalogue_sha256"] = digest
                self.assertTrue(self.verify(proof, junit, case))

    def test_exact_effect_categories(self):
        proof, junit = unitonly_proof()
        self.assertTrue(self.verify(proof, junit, "positive"))
        mutations = [{"unrelated": 0}, {}, [], dict(proof["forbidden"], extra=0)]
        for key in proof["forbidden"]:
            missing = dict(proof["forbidden"])
            del missing[key]
            mutations.append(missing)
            mutations.extend(dict(proof["forbidden"], **{key: value}) for value in (False, "0", 1))
        for value in mutations:
            with self.subTest(value=value):
                bad = copy.deepcopy(proof)
                bad["forbidden"] = value
                with self.assertRaises((AssertionError, KeyError)):
                    self.verify(bad, junit, "positive")

    def test_concrete_native_and_origin_witnesses(self):
        proof, junit = unitonly_proof()
        self.assertTrue(self.verify(proof, junit, "positive"))
        for field in ("native_libraries", "module_origins"):
            witness = proof["initialization_roles"][0][field][0]
            mutations = [None, [], [None], "not-a-list"]
            for key in ("path", "physical", "links", "size", "sha256"):
                missing = dict(witness)
                del missing[key]
                mutations.append([missing])
            for key, values in {
                "path": (None, "relative.so", "/isaac-sim/../escape.so", "/bad\x00.so"),
                "physical": (None, "relative.so", "/elsewhere.so"),
                "links": (None, [None]),
                "size": (True, "1", -1, 0, 2 * 1024**3 + 1),
                "sha256": (None, "b" * 63, "B" * 64, "g" * 64),
            }.items():
                mutations.extend([dict(witness, **{key: value})] for value in values)
            if field == "native_libraries":
                mutations.append([dict(witness) for _ in range(65)])
                mutations.append([dict(witness, size=2 * 1024**3) for _ in range(5)])
            else:
                for key in ("name", "origin", "preloaded"):
                    missing = dict(witness)
                    del missing[key]
                    mutations.append([missing])
                for key, value in (
                    ("name", None),
                    ("name", "unknown"),
                    ("origin", "/shadow/warp.so"),
                    ("preloaded", True),
                    ("preloaded", 0),
                ):
                    mutations.append([dict(witness, **{key: value})])
            for value in mutations:
                with self.subTest(field=field, value=value):
                    bad = copy.deepcopy(proof)
                    bad["initialization_roles"][0][field] = value
                    with self.assertRaises((AssertionError, KeyError)):
                        self.verify(bad, junit, "positive")

    def test_unitonly_packet_identity_bounds(self):
        proof, junit = unitonly_proof()
        for row in proof["initialization_roles"]:
            row["native_libraries"] *= 16
        self.assertTrue(self.verify(proof, junit, "positive"))
        proof["initialization_roles"][0]["native_libraries"].append(
            copy.deepcopy(proof["initialization_roles"][0]["native_libraries"][0])
        )
        with self.assertRaises(AssertionError):
            self.verify(proof, junit, "positive")
        proof, junit = unitonly_proof()
        for row in proof["initialization_roles"]:
            row["native_libraries"][0]["size"] = 2 * 1024**3 - 1024
        self.assertTrue(self.verify(proof, junit, "positive"))
        proof["initialization_roles"][0]["native_libraries"][0]["size"] += 1
        with self.assertRaises(AssertionError):
            self.verify(proof, junit, "positive")
        proof, junit = unitonly_proof()
        proof["initialization_roles"][0]["native_libraries"][0]["size"] = 2 * 1024**3
        self.assertTrue(self.verify(proof, junit, "positive"))

    def test_catalogue_identity_agreement_and_checkpoint_binding(self):
        for case in ("positive", "failure", "timeout"):
            proof, junit = unitonly_proof(case)
            self.assertTrue(self.verify(proof, junit, case))
            targets = [("role", i) for i in range(len(proof["initialization_roles"]))]
            if case != "positive":
                targets.append(("checkpoint", 0))
            for kind, index in targets:
                for value in (None, 1, "c" * 63, "C" * 64, "g" * 64, "d" * 64, "MISSING"):
                    # A single server catalogue is free to differ from UNITONLY's literal,
                    # but must still bind its checkpoint (or its positive peers).
                    with self.subTest(case=case, target=(kind, index), value=value):
                        bad = copy.deepcopy(proof)
                        target = bad["initialization_roles"][index] if kind == "role" else bad["pre_readiness_failure"]
                        if value == "MISSING":
                            del target["catalogue_sha256"]
                        else:
                            target["catalogue_sha256"] = value
                        with self.assertRaises((AssertionError, KeyError)):
                            self.verify(bad, junit, case)


if __name__ == "__main__":
    unittest.main()
