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
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"),
        namespace,
    )
    return namespace


class InitializationProfilerGuards(unittest.TestCase):
    """Exercise the actual profiler AST without importing its runtime closure."""

    def setUp(self):
        from types import SimpleNamespace

        class BaseGuard:
            def __init__(self):
                self.base_events = []
                self.denials = []
                self.base_denial = None

            def profile(self, frame, event, arg):
                self.base_events.append((frame, event, arg))
                if self.base_denial:
                    self.deny(self.base_denial)

            def deny(self, category):
                self.denials.append(category)
                raise RuntimeError(category)

        tree = ast.parse(HARNESS.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "JoinGuards")
        cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "profile"]
        namespace = {}
        namespace.update(base=SimpleNamespace(Guards=BaseGuard), sys=SimpleNamespace(modules={}))
        exec(
            compile(ast.Module(body=[cls], type_ignores=[]), str(HARNESS), "exec"),
            namespace,
        )
        self.guard = namespace["JoinGuards"]()
        self.guard.role = "harness"
        self.guard.initialization_controls_ready = True
        self.frame = lambda metadata, name: SimpleNamespace(
            f_globals=metadata, f_code=SimpleNamespace(co_name=name), f_locals={}
        )

    def test_ordinary_teardown_metadata_reaches_base_unchanged(self):
        for metadata in ({"__name__": None}, {}, {"__name__": 7}):
            for event in ("call", "return", "c_call", "c_return", "c_exception"):
                with self.subTest(metadata=metadata, event=event):
                    frame = self.frame(metadata, "_removeHandlerRef")
                    arg = object()
                    self.guard.profile(frame, event, arg)
                    self.assertEqual(self.guard.base_events[-1], (frame, event, arg))
                    self.assertIs(frame.f_globals, metadata)
        self.assertEqual(self.guard.denials, [])

    def test_unknown_sensitive_modules_deny_runtime(self):
        for metadata in (
            {"__name__": None},
            {},
            {"__name__": 7},
            {"__name__": []},
            {"__name__": ""},
        ):
            for name in (
                "launch",
                "launch_tiled",
                "capture_launch",
                "Open",
                "OpenMasked",
            ):
                with self.subTest(metadata=metadata, name=name):
                    with self.assertRaisesRegex(RuntimeError, "^runtime$"):
                        self.guard.profile(self.frame(metadata, name), "call", None)
                    self.assertEqual(self.guard.denials[-1], "runtime")
        self.assertEqual(self.guard.base_events, [])

    def test_warp_and_pxr_sensitive_calls_remain_denied(self):
        for module, names in (
            ("warp", ("launch", "launch_tiled", "capture_launch")),
            ("warp._src.context", ("launch", "launch_tiled", "capture_launch")),
            ("pxr", ("Open", "OpenMasked")),
            ("pxr.Usd", ("Open", "OpenMasked")),
        ):
            for name in names:
                with self.subTest(module=module, name=name):
                    with self.assertRaisesRegex(RuntimeError, "^runtime$"):
                        self.guard.profile(self.frame({"__name__": module}, name), "call", None)
        self.assertEqual(self.guard.base_events, [])

    def test_known_unrelated_sensitive_names_reach_base(self):
        for name in ("launch", "launch_tiled", "capture_launch", "Open", "OpenMasked"):
            frame = self.frame({"__name__": "unrelated.module"}, name)
            self.guard.profile(frame, "call", None)
            self.assertEqual(self.guard.base_events[-1], (frame, "call", None))
        self.assertEqual(self.guard.denials, [])

    def test_none_metadata_does_not_bypass_base_denials(self):
        for category in ("legacy", "provider", "runtime", "graph"):
            self.guard.base_denial = category
            frame = self.frame({"__name__": None}, "__init__")
            with (
                self.subTest(category=category),
                self.assertRaisesRegex(RuntimeError, "^" + category + "$"),
            ):
                self.guard.profile(frame, "call", None)
            self.assertEqual(self.guard.base_events[-1], (frame, "call", None))

    def test_disabled_initialization_controls_preserve_base_dispatch(self):
        self.guard.initialization_controls_ready = False
        for module in (None, 7, "warp", "pxr"):
            for name in (
                "launch",
                "launch_tiled",
                "capture_launch",
                "Open",
                "OpenMasked",
            ):
                frame = self.frame({"__name__": module}, name)
                self.guard.profile(frame, "call", None)
                self.assertEqual(self.guard.base_events[-1], (frame, "call", None))
        self.assertEqual(self.guard.denials, [])


class InitializationDependencyFrontier(unittest.TestCase):
    """UNITONLY fixed-file ports; never import any selected image package."""

    def setUp(self):
        import hashlib
        import json
        import os
        import sys
        import time
        from types import SimpleNamespace

        self.p = "/isaac-sim/kit/python/lib/python3.12/site-packages"
        self.isaaclab_root = "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab/isaaclab"
        self.paths = [
            self.p + suffix
            for suffix in (
                "/lazy_loader/__init__.py",
                "/numpy/__init__.py",
                "/sympy/__init__.py",
                "/torch/__init__.py",
                "/torch/_utils.py",
                "/torch/_utils_internal.py",
                "/torch/torch_version.py",
                "/torch/version.py",
            )
        ] + [self.isaaclab_root + "/sim/__init__.py", self.isaaclab_root + "/sim/__init__.pyi"]
        namespace = isolated(HARNESS, {"registration_metadata_probe"})
        tree = ast.parse(HARNESS.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "InitializationAdmission")
        exec(compile(ast.Module(body=[cls], type_ignores=[]), str(HARNESS), "exec"), namespace)
        self.ns = namespace
        self.clock = time.monotonic()
        self.reads = []
        self.raw = b"import os\nfrom . import thing\n"
        self.admission = namespace["InitializationAdmission"].__new__(namespace["InitializationAdmission"])
        self.admission.guard = SimpleNamespace(initialization_case="positive", initialization_role="init-server")
        self.admission.runner = SimpleNamespace(
            GRAPHQL_IMAGE="sha256:b94e17024f1e123ac5a42759ab56651a18823fda7c701e765cba31f200154cdd",
            GRAPHQL_MANIFEST_SHA256="03764536ed54c1f59cbf46305c5bc4ba618e2dc1deeeac7ffdfb21a0dffbf810",
        )
        self.admission.roots = {}
        self.admission.baseline = {"UNITONLY": self.p + "/already.py"}
        self.admission.modules = [{"name": "torch", "origin": self.paths[3]}]
        self.admission.budget = dict(bytes=123, files=2, deadline=self.clock + 30, byte_limit=2 * 1024**3)
        self.admission.pathfinder = SimpleNamespace(find_spec=lambda *args: SimpleNamespace(origin=self.paths[0]))
        self.admission.dependency_frontier = None
        self.admission.dependency_frontier_started = False

        def reader(path, budget, *, source=False):
            self.assertTrue(source)
            self.assertEqual(budget["file_limit"], 262144)
            self.assertLessEqual(budget["deadline"], self.clock + 5)
            self.assertEqual(budget["byte_limit"], 123 + 4194304)
            self.reads.append(path)
            budget["bytes"] += len(self.raw)
            return (
                dict(
                    path=path, physical=path, links=[], size=len(self.raw), sha256=hashlib.sha256(self.raw).hexdigest()
                ),
                self.raw,
            )

        self.reader = reader
        namespace.update(
            json=json,
            hashlib=hashlib,
            os=os,
            sys=sys,
            Path=pathlib.Path,
            time=SimpleNamespace(monotonic=lambda: self.clock),
            initialization_physical_file=reader,
        )

    def trigger(self, name="lazy_loader"):
        with self.assertRaisesRegex(ImportError, "^Unadmitted S2 package origin: " + name + " at "):
            self.admission.find_spec(name)

    def test_fixed_grouped_capture_preserves_refusal_and_parent_budget(self):
        import json
        import sys

        before_path, before_modules = list(sys.path), dict(sys.modules)
        original = dict(self.admission.budget)
        self.trigger()
        report = self.admission.dependency_frontier
        self.assertIsInstance(report, dict)
        self.assertEqual(report["requested_manifest"], self.paths)
        self.assertEqual(self.reads, self.paths)
        self.assertEqual(report["baseline"], self.admission.baseline)
        self.assertEqual(report["module_origins"], self.admission.modules)
        self.assertEqual(report["status"], "observed")
        self.assertFalse(report["expanded_import_admitted"])
        for row in report["files"]:
            self.assertEqual(row["status"], "observed")
            self.assertEqual(row["source_evidence"]["text"].encode(), self.raw)
            self.assertTrue(row["imports_complete"])
            self.assertEqual(row["imports"][1]["line"], 2)
        self.assertLessEqual(len(json.dumps(report, sort_keys=True).encode()), 1048576)
        self.assertEqual(self.admission.budget, dict(original, bytes=123 + len(self.raw) * 10))
        self.assertEqual(sys.path, before_path)
        self.assertEqual(dict(sys.modules), before_modules)
        self.trigger()
        self.assertEqual(self.reads, self.paths)

    def test_failure_finally_exports_same_role_leaf_with_frontier(self):
        import io
        import json
        import tarfile
        from types import SimpleNamespace

        self.trigger()
        tree = ast.parse(HARNESS.read_text())
        child = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "initialization_child")
        final = next(n for n in child.body if isinstance(n, ast.Try)).finalbody
        leaves = {}
        record = dict(status="failed", failure_type="ImportError")
        self.admission.pythonapi_bootstrap = []
        scope = dict(
            record=record,
            admission=self.admission,
            role="init-server",
            guard=SimpleNamespace(forbidden={}, sdk_calls=0, owner_constructions=0),
            signal=SimpleNamespace(alarm=lambda n: None),
            write_evidence=lambda name, value: leaves.update({name: json.dumps(value).encode()}),
        )
        exec(compile(ast.Module(body=final, type_ignores=[]), str(HARNESS), "exec"), scope)
        name = "initialization-init-server.json"
        self.assertEqual(set(leaves), {name})
        self.assertEqual(json.loads(leaves[name])["dependency_frontier"], self.admission.dependency_frontier)
        fn = isolated(ROOT / "scripts/run-workflow-neo4j-checks.py", {"initialization_archive"})[
            "initialization_archive"
        ]
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as archive:
            info = tarfile.TarInfo("evidence/" + name)
            info.size = len(leaves[name])
            archive.addfile(info, io.BytesIO(leaves[name]))
        self.assertEqual(fn(buf.getvalue(), frozenset({name})), leaves)
        self.assertEqual(json.loads(leaves[name])["status"], "failed")

    def test_trigger_gates_and_reentry_no_second_inspection(self):
        for case, role, name, origin in (
            ("failure", "init-server", "lazy_loader", self.paths[0]),
            ("positive", "init-generate", "lazy_loader", self.paths[0]),
            ("positive", "init-server", "other", self.paths[0]),
            ("positive", "init-server", "lazy_loader", self.p + "/lazy_loader/other.py"),
        ):
            self.admission.guard.initialization_case = case
            self.admission.guard.initialization_role = role
            self.admission.pathfinder.find_spec = lambda *args: type("Spec", (), {"origin": origin})()
            self.trigger(name)
            self.assertEqual(self.reads, [])
        self.admission.guard.initialization_case = "positive"
        self.admission.guard.initialization_role = "init-server"
        self.admission.pathfinder.find_spec = lambda *args: type("Spec", (), {"origin": self.paths[0]})()

        def reader(path, budget, **kwargs):
            self.trigger()
            return self.reader(path, budget, **kwargs)

        self.ns["initialization_physical_file"] = reader
        self.trigger()
        self.assertEqual(self.reads, self.paths)

    def test_partial_observations_survive_missing_errors_and_deadline(self):
        def reader(path, budget, **kwargs):
            if path == self.paths[1]:
                raise FileNotFoundError(path)
            if path == self.paths[2]:
                raise SystemExit("UNITONLY unexpected inspection failure")
            if path == self.paths[4]:
                budget["bytes"] += 7  # Actual partial read must remain charged.
                self.clock += 6
                raise TimeoutError()
            return self.reader(path, budget, **kwargs)

        self.ns["initialization_physical_file"] = reader
        deadline = self.admission.budget["deadline"]
        self.trigger()
        report = self.admission.dependency_frontier
        self.assertEqual(
            [r["status"] for r in report["files"]],
            ["observed", "not_read_missing", "not_read_refused", "observed"] + ["not_read_deadline"] * 6,
        )
        self.assertEqual(report["bytes_read"], len(self.raw) * 2 + 7)
        self.assertEqual(self.admission.budget["deadline"], deadline)
        self.assertEqual(report["files"][0]["source_evidence"]["text"].encode(), self.raw)

    def test_metadata_encoder_visits_each_entry_once(self):
        import json
        from types import SimpleNamespace

        visits = []

        class CountingEncoder(json.JSONEncoder):
            def iterencode(self, value, *args, **kwargs):
                for chunk in super().iterencode(value, *args, **kwargs):
                    if "UNITONLY_ENTRY_" in chunk:
                        visits.append(chunk)
                    yield chunk

        self.admission.baseline = {f"UNITONLY_ENTRY_{i}": 'quote"\\\n\u2603' for i in range(663)}
        self.admission.modules = [{"name": f"UNITONLY_ENTRY_module_{i}"} for i in range(663)]
        self.ns["json"] = SimpleNamespace(JSONEncoder=CountingEncoder)
        self.trigger()
        report = self.admission.dependency_frontier
        self.assertTrue(report["baseline_complete"])
        self.assertTrue(report["module_origins_complete"])
        self.assertEqual(len(visits), 1326)
        self.assertEqual(report["baseline"], self.admission.baseline)
        self.assertEqual(report["module_origins"], self.admission.modules)
        self.assertLessEqual(len(json.dumps(report, sort_keys=True).encode()), 1048576)

    def test_known_663_baseline_cost_cannot_starve_source_capture(self):
        import json
        from types import SimpleNamespace

        case = self

        class CostEncoder(json.JSONEncoder):
            def iterencode(self, value, *args, **kwargs):
                for chunk in super().iterencode(value, *args, **kwargs):
                    if "UNITONLY_COST_" in chunk:
                        case.clock += 0.02  # Deterministic UNITONLY cost, not image timing.
                    yield chunk

        self.admission.baseline = {f"UNITONLY_COST_{i}": self.p + f"/m{i}.py" for i in range(663)}
        self.ns["json"] = SimpleNamespace(JSONEncoder=CostEncoder)
        original = dict(self.admission.budget)
        self.trigger()
        report = self.admission.dependency_frontier
        self.assertEqual(self.reads, self.paths)
        self.assertTrue(report["source_capture_complete"])
        self.assertFalse(report["baseline_complete"])
        self.assertLess(len(report["baseline"]), 663)
        self.assertEqual(report["limits"]["seconds"], 5)
        self.assertEqual(self.admission.budget, dict(original, bytes=123 + len(self.raw) * 10))
        self.assertLessEqual(len(json.dumps(report, sort_keys=True).encode()), 1048576)

    def test_large_valid_ast_cannot_starve_later_source_capture(self):
        from unittest.mock import patch

        large = b"x = 1\n" * 30000

        def reader(path, budget, **kwargs):
            self.raw = large if path == self.paths[0] else b"import os\n"
            return self.reader(path, budget, **kwargs)

        self.ns["initialization_physical_file"] = reader
        walk = ast.walk

        def costly_walk(tree):
            for node in walk(tree):
                self.clock += 6  # One optional walk exhausts the unchanged five seconds.
                yield node

        with patch.object(ast, "walk", costly_walk):
            self.trigger()
        report = self.admission.dependency_frontier
        self.assertEqual(self.reads, self.paths)
        self.assertTrue(report["source_capture_complete"])
        self.assertFalse(report["imports_complete"])
        self.assertTrue(report["files"][0]["source_evidence"]["complete_source"])
        self.assertFalse(report["files"][0]["imports_complete"])
        self.assertEqual(report["files"][0]["source_evidence"]["text"].encode(), large)
        self.assertTrue(all(not row.get("imports_complete", False) for row in report["files"]))

    def test_incremental_json_budget_exact_escaping_punctuation_and_reserve(self):
        import json

        tree = ast.parse(HARNESS.read_text())
        probe = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "registration_metadata_probe")
        frontier = next(n for n in probe.body if isinstance(n, ast.FunctionDef) and n.name == "dependency_frontier")
        helpers: list[ast.stmt] = [
            n for n in frontier.body if isinstance(n, ast.FunctionDef) and n.name in {"size", "add", "append"}
        ]
        # Convert closure mutation to globals in this UNITONLY extracted helper port.
        helpers = copy.deepcopy(helpers)
        for helper in helpers:
            assert isinstance(helper, ast.FunctionDef)
            helper.body = [ast.Global(names=n.names) if isinstance(n, ast.Nonlocal) else n for n in helper.body]
        report = {"baseline": {}, "module_origins": []}
        ns: dict = dict(
            encoder=json.JSONEncoder(sort_keys=True),
            encoding_deadline=None,
            used=len(json.dumps(report, sort_keys=True).encode()),
        )
        exec(compile(ast.fix_missing_locations(ast.Module(body=helpers, type_ignores=[])), str(HARNESS), "exec"), ns)
        for i in range(12):
            key = f'key"\\\n\u2603{i}'
            value = {"escaped": '\u0001\u00e9"\\\n', "values": [None, False, i]}
            self.assertTrue(ns["add"](report["baseline"], key, value))
            self.assertEqual(ns["used"], len(json.dumps(report, sort_keys=True).encode()))
            self.assertTrue(ns["append"](report["module_origins"], value))
            self.assertEqual(ns["used"], len(json.dumps(report, sort_keys=True).encode()))
        # Fill exactly to the variable-data ceiling; the terminal 8KiB remains.
        remaining = 1048576 - 8192 - ns["used"]
        self.assertTrue(ns["append"](report["module_origins"], "x" * (remaining - 4)))
        self.assertEqual(ns["used"], 1048576 - 8192)
        self.assertEqual(ns["used"], len(json.dumps(report, sort_keys=True).encode()))
        before = copy.deepcopy(report)
        self.assertFalse(ns["append"](report["module_origins"], ""))
        self.assertFalse(ns["add"](report["baseline"], "overflow", ""))
        self.assertEqual(report, before)

    def test_source_and_summary_errors_preserve_other_selected_files(self):
        def reader(path, budget, **kwargs):
            self.raw = bytes([255]) if path == self.paths[0] else b"def invalid(:\n"
            return self.reader(path, budget, **kwargs)

        self.ns["initialization_physical_file"] = reader
        self.trigger()
        report = self.admission.dependency_frontier
        self.assertEqual(self.reads, self.paths)
        self.assertEqual(report["files"][0]["status"], "read_error")
        self.assertEqual(report["files"][0]["error_type"], "UnicodeDecodeError")
        for row in report["files"][1:]:
            self.assertTrue(row["source_evidence"]["complete_source"])
            self.assertFalse(row["imports_complete"])
            self.assertEqual(row["imports_error_type"], "SyntaxError")
        self.assertFalse(report["source_capture_complete"])
        self.assertFalse(report["imports_complete"])

    def test_encoded_overflow_retains_prior_source_and_bounded_baseline(self):
        import json

        self.admission.baseline = {"m" + str(i): self.p + "/m" + str(i) + ".py" for i in range(663)}

        def reader(path, budget, **kwargs):
            if path == self.paths[1]:
                self.raw = b"#" + bytes([1]) * 262143  # Escapes exceed 1MiB despite legal physical size.
            elif path != self.paths[0]:
                self.raw = b"# small\n"
            return self.reader(path, budget, **kwargs)

        self.ns["initialization_physical_file"] = reader
        self.trigger()
        report = self.admission.dependency_frontier
        self.assertEqual(len(report["baseline"]), 663)
        self.assertEqual(report["files"][0]["status"], "observed")
        self.assertEqual(report["files"][1]["status"], "read_encoded_limit")
        self.assertIn("witness", report["files"][1])
        self.assertLessEqual(len(json.dumps(report, sort_keys=True).encode()), 1048576)

    def test_physical_refusal_statuses_and_ast_limit(self):
        import hashlib
        import os
        import stat
        import tempfile
        from types import SimpleNamespace

        fn = isolated(HARNESS, {"initialization_physical_file"})["initialization_physical_file"]
        projected = SimpleNamespace(**{k: getattr(os, k) for k in dir(os)})
        projected.fstatvfs = lambda fd: SimpleNamespace(f_flag=os.ST_RDONLY)
        fn.__globals__.update(os=projected, stat=stat, time=self.ns["time"], hashlib=hashlib)
        with tempfile.TemporaryDirectory() as root:
            files = [pathlib.Path(root, str(i) + ".py") for i in range(10)]
            for file in files:
                file.write_bytes(b"import os\n" * 513)
            files[1].unlink()
            files[2].unlink()
            files[2].symlink_to(files[0])
            files[3].write_bytes(b"#" * 262145)

            def reader(path, budget, **kwargs):
                return fn(str(files[self.paths.index(path)]), budget, **kwargs)

            self.ns["initialization_physical_file"] = reader
            self.trigger()
        rows = self.admission.dependency_frontier["files"]
        self.assertEqual(rows[1]["status"], "not_read_missing")
        self.assertEqual(rows[2]["status"], "not_read_link")
        self.assertEqual(rows[3]["status"], "not_read_oversize")
        self.assertEqual(len(rows[0]["imports"]), 512)
        self.assertFalse(rows[0]["imports_complete"])
        self.assertEqual(rows[0]["source_evidence"]["bytes"], len(b"import os\n") * 513)

    def test_unexpected_metadata_retains_partial_and_terminal_statuses(self):
        self.admission.baseline["oversized"] = "x" * 1048576
        self.trigger()
        report = self.admission.dependency_frontier
        self.assertEqual(report["baseline"], {"UNITONLY": self.p + "/already.py"})
        self.assertFalse(report["baseline_complete"])
        self.assertEqual(len(report["files"]), 10)
        self.admission.dependency_frontier_started = False
        self.admission.baseline = {"good": "origin", "unexpected": object()}
        self.trigger()
        report = self.admission.dependency_frontier
        self.assertEqual(report["baseline"], {"good": "origin"})
        self.assertNotIn("not_read_pending", [row["status"] for row in report["files"]])

    def test_no_candidate_execution_or_resolution_in_probe(self):
        import builtins

        def guarded_import(name, *args, **kwargs):
            self.assertEqual(name, "ast")
            return builtins.__import__(name, *args, **kwargs)

        tree = ast.parse(HARNESS.read_text())
        probe = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "registration_metadata_probe")
        scope = dict(self.ns, __builtins__=dict(vars(builtins), __import__=guarded_import))
        exec(compile(ast.Module(body=[probe], type_ignores=[]), str(HARNESS), "exec"), scope)
        self.ns["registration_metadata_probe"] = scope["registration_metadata_probe"]
        self.raw = b"raise RuntimeError('must never execute')\nimport forbidden_UNITONLY\n"
        self.trigger()
        self.assertEqual(self.reads, self.paths)
        self.assertEqual(self.admission.dependency_frontier["files"][0]["status"], "observed")
        nested = next(n for n in probe.body if isinstance(n, ast.FunctionDef) and n.name == "dependency_frontier")
        forbidden = {"exec", "eval", "compile", "find_spec", "walk", "listdir", "glob", "rglob"}
        for node in ast.walk(nested):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, forbidden)
                elif isinstance(node.func, ast.Attribute) and not (
                    isinstance(node.func.value, ast.Name) and node.func.value.id == "ast"
                ):
                    self.assertNotIn(node.func.attr, forbidden)

    def test_parent_shorter_limits_and_unexpected_probe_error_preserve_refusal(self):
        original = dict(self.admission.budget, deadline=self.clock + 1, byte_limit=124, file_limit=8)
        self.admission.budget = dict(original)

        def reader(path, budget, **kwargs):
            self.assertEqual(budget["deadline"], original["deadline"])
            self.assertEqual(budget["byte_limit"], 124)
            self.assertEqual(budget["file_limit"], 8)
            raise AssertionError("S2 physical read ceiling")

        self.ns["initialization_physical_file"] = reader
        self.trigger()
        self.assertEqual(self.admission.budget, original)
        self.admission.dependency_frontier_started = False

        def broken(*args, **kwargs):
            args[3]["partial_UNITONLY"] = True
            raise KeyboardInterrupt()

        self.ns["registration_metadata_probe"] = broken
        self.trigger()
        self.assertTrue(self.admission.dependency_frontier["partial_UNITONLY"])
        self.assertEqual(self.admission.dependency_frontier["inspection_error"], "KeyboardInterrupt")


class InitializationStaticGuards(unittest.TestCase):
    def test_physical_per_file_cap_precedes_any_read(self):
        import hashlib
        import os
        import stat
        import tempfile
        import time
        from types import SimpleNamespace

        fn = isolated(HARNESS, {"initialization_physical_file"})["initialization_physical_file"]
        reads = []
        projected = SimpleNamespace(**{k: getattr(os, k) for k in dir(os)})
        projected.fstatvfs = lambda fd: SimpleNamespace(f_flag=os.ST_RDONLY)
        projected.read = lambda *args: (reads.append(args), os.read(*args))[1]
        fn.__globals__.update(os=projected, stat=stat, time=time, hashlib=hashlib)
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root, "large.py")
            path.write_bytes(b"#" * 262145)
            budget = dict(bytes=0, files=0, deadline=time.monotonic() + 5, file_limit=262144)
            with self.assertRaises(AssertionError):
                fn(str(path), budget, source=True)
            self.assertEqual(reads, [])
            self.assertEqual(budget["bytes"], 0)
            budget.pop("file_limit")
            self.assertEqual(len(fn(str(path), budget, source=True)[1]), 262145)

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
        for case, role in (
            ("unknown", "init-server"),
            ("positive", "../escape"),
            (True, "init-server"),
        ):
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
        incomplete = dict(
            status="passed",
            mode="workflow-graphql-initialization",
            case="positive",
            tests=1,
        )
        for patch in ({}, {"status": "failed"}, {"tests": 0}, {"case": "failure"}):
            value = copy.deepcopy(incomplete)
            value.update(patch)
            with self.assertRaises((AssertionError, KeyError)):
                fn(value, junit, "positive")
        with self.assertRaises(AssertionError):
            fn(incomplete, junit, "arbitrary")

    def test_physical_native_reader_is_bounded_and_no_follow(self):
        import hashlib
        import os
        import stat
        import tempfile
        import time
        from types import SimpleNamespace

        fn = isolated(HARNESS, {"initialization_physical_file"})["initialization_physical_file"]
        # UNITONLY kernel-readonly projection; actual reads/links remain real.
        projected = SimpleNamespace(**{k: getattr(os, k) for k in dir(os)})
        projected.fstatvfs = lambda fd: SimpleNamespace(f_flag=os.ST_RDONLY)
        fn.__globals__.update(os=projected, stat=stat, time=time, hashlib=hashlib)
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root, "native.so")
            path.write_bytes(b"UNITONLY-not-a-native-library")
            budget = dict(bytes=0, files=0, deadline=time.monotonic() + 10)
            row = fn(str(path), budget, binary=True)
            self.assertEqual(row["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(budget["files"], 1)
            self.assertEqual(budget["bytes"], path.stat().st_size)
            source_row, raw = fn(str(path), budget, source=True)
            self.assertEqual(source_row, row)
            self.assertEqual(raw, b"UNITONLY-not-a-native-library")
            self.assertEqual(budget["bytes"], 2 * path.stat().st_size)
            link = pathlib.Path(root, "link.so")
            link.symlink_to(path)
            with self.assertRaises((AssertionError, OSError)):
                fn(str(link), budget, binary=True)
            parent = pathlib.Path(root, "parent")
            parent.symlink_to(root, target_is_directory=True)
            with self.assertRaises((AssertionError, OSError)):
                fn(str(parent / "native.so"), budget, binary=True)
            for patch in ({"files": 64}, {"bytes": 8 * 1024**3}, {"deadline": 0}):
                with self.assertRaises(AssertionError):
                    fn(str(path), dict(budget, **patch), binary=True)
            projected.fstatvfs = lambda fd: SimpleNamespace(f_flag=0)
            with self.assertRaises(AssertionError):
                fn(str(path), budget, binary=True)

    def test_cache_tree_rejects_symlink_and_owner_conflicts(self):
        import hashlib
        import os
        import stat
        import tempfile
        import time
        from types import SimpleNamespace

        fn = isolated(HARNESS, {"initialization_cache_manifest"})["initialization_cache_manifest"]
        projected = SimpleNamespace(**{k: getattr(os, k) for k in dir(os)})
        projected.getuid = lambda: 1000
        projected.getgid = lambda: 1000
        # UNITONLY uid projection; path traversal and hashing are real.
        original = os.fstat

        def owned(fd):
            value = original(fd)
            return SimpleNamespace(
                **{k: getattr(value, k) for k in dir(value) if k.startswith("st_")},
            )

        def owned_stat(fd):
            value = owned(fd)
            value.st_uid = value.st_gid = 1000
            return value

        projected.fstat = owned_stat
        fn.__globals__.update(os=projected, stat=stat, time=time, hashlib=hashlib)
        with tempfile.TemporaryDirectory() as root:
            pathlib.Path(root, "cache").mkdir(mode=0o700)
            pathlib.Path(root, "cache", "entry").write_bytes(b"cache UNITONLY")
            rows = fn(root, time.monotonic() + 5)
            self.assertEqual({r["path"] for r in rows}, {".", "cache", "cache/entry"})
            pathlib.Path(root, "cache", "link").symlink_to("entry")
            with self.assertRaises((AssertionError, OSError)):
                fn(root, time.monotonic() + 5)
            pathlib.Path(root, "cache", "link").unlink()
            with self.assertRaises(AssertionError):
                fn(root, 0)
            projected.fstat = original
            with self.assertRaises(AssertionError):
                fn(root, time.monotonic() + 5)

    def test_cold_role_bootstrap_controls_precede_fixture(self):
        tree = ast.parse(HARNESS.read_text())
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertIn("initialization_child", functions)
        text = ast.unparse(functions["initialization_child"])
        self.assertLess(
            text.index("initialization_cache_create"),
            text.index("initialization_preparation"),
        )
        self.assertLess(
            text.index("InitializationAdmission("),
            text.index("initialization_preparation"),
        )
        self.assertNotIn("platform.processor =", text)
        self.assertNotIn("/network/manifest.json", text)
        self.assertIn("initialization_verify_sources()", text)
        classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        self.assertIn("InitializationAdmission", classes)
        self.assertIn("InitializationLoader", classes)
        loader = ast.unparse(classes["InitializationLoader"])
        self.assertLess(loader.index("self.verify()"), loader.index("self.original.create_module"))
        self.assertIn("initialization_physical_file", loader)
        admission = ast.unparse(classes["InitializationAdmission"])
        self.assertIn("Unadmitted S2 package origin", admission)
        self.assertIn("ctypes.dlopen", admission)
        self.assertNotIn("startswith('omni')", admission)

    def test_evidence_allowlist_and_cold_role_schema_are_finite(self):
        names = isolated(HARNESS, {"initialization_evidence_names"})["initialization_evidence_names"]
        names.__globals__["INITIALIZATION_ROLES"] = (
            "init-server",
            "init-generate",
            "init-refine",
            "init-assess",
        )
        for case, count in (("positive", 4), ("failure", 11), ("timeout", 11)):
            leaves = names(case, {"process_pids": list(range(100, 100 + count))})
            self.assertLessEqual(len(leaves), 55)
            self.assertTrue({"client-proof.json", "pytest.xml", "collection-ready"} <= leaves)
            self.assertTrue(all("/" not in leaf for leaf in leaves))
            with self.assertRaises(AssertionError):
                names(case, {"process_pids": list(range(100, 101 + count))})
        text = ast.unparse(ast.parse(FIXTURE.read_text()))
        self.assertIn("role == 'init-assess'", text)
        self.assertIn("role == 'init-generate'", text)

    def test_installed_case_operator_home_matches_sanitized_spawn(self):
        tree = ast.parse(FIXTURE.read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "configuration")
        self.assertIn("home", [arg.arg for arg in fn.args.kwonlyargs])
        text = ast.unparse(ast.parse(HARNESS.read_text()))
        self.assertIn("configuration(kind, profiles if kind == 'execution' else (), home=", text)

    def test_real_fixed_dispatch_has_no_fabricated_junit(self):
        tree = ast.parse(HARNESS.read_text())
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        text = ast.unparse(functions["initialization_inside"])
        self.assertIn("pytest.main", text)
        self.assertIn("::test_initialization_", text)
        self.assertNotIn("<testsuite", text)
        self.assertIn("initialization_verify_proof", text)
        self.assertIn("client-proof.json", text)
        test_tree = ast.parse(pathlib.Path(__file__).read_text())
        tests = {n.name for n in test_tree.body if isinstance(n, ast.FunctionDef)}
        self.assertTrue(
            {
                "test_initialization_positive",
                "test_initialization_failure",
                "test_initialization_timeout",
            }
            <= tests
        )
        self.assertIn("initialization_fresh", functions)
        self.assertIn("initialization_installed_case", functions)

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
            text.index("catalogue_digest = execution_catalogue_sha256()"),
            text.index("checkpoint(catalogue_digest)"),
        )
        self.assertLess(
            text.index("checkpoint(catalogue_digest)"),
            text.index("app = ForegroundWorkflow("),
        )
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
        self.assertIn(
            "prepare_catalogues(inputs['execution_catalogue_sha256'])",
            ast.unparse(functions["execute"]),
        )
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
            (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "initialization_preparation"),
            None,
        )
        self.assertIsNotNone(fn, "missing real schema preparation")
        assert fn is not None
        text = ast.unparse(fn)
        for required in (
            "install_synthetic_sdk(scene=True)",
            "ArenaEnvGraphSpec.model_validate",
            "load_env_graph_spec_dict",
            "isaaclab_arena/tests/test_data/minimal_maple_table_env_graph.yaml",
            "reject_unknown_fields",
            "execution_catalogue_sha256",
        ):
            self.assertIn(required, text)
        self.assertNotIn("platform.processor =", text)
        self.assertNotIn("warp.init =", text)
        self.assertNotIn("sys.modules[", text)


class InitializationContainmentGuards(unittest.TestCase):
    def test_precheckpoint_deadline_contains_separate_server_group(self):
        import contextlib
        import signal
        from types import SimpleNamespace

        names = {"initialization_collect"}
        tree = ast.parse(HARNESS.read_text())
        names.update(
            n.name
            for n in tree.body
            if isinstance(n, ast.FunctionDef)
            and n.name in {"initialization_owned_server", "initialization_contain_launcher"}
        )
        ns = isolated(HARNESS, names)
        now, signals, evidence = [0.0], [], {}
        server = dict(
            pid=202,
            parent_pid=101,
            pgid=202,
            sid=202,
            start_ticks=123,
            boot="UNITONLY",
            pid_namespace="pid:[UNITONLY]",
        )
        launch = ["api-launch"]
        records = {"/evidence/join-launch-202.json": dict(server, bootstrap_argv=[0] * 6 + ["api-serve"])}

        class Stream:
            def fileno(self):
                return 1

            def close(self):
                pass

        class Selector:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def register(self, *args):
                pass

            def get_map(self):
                return {1: True}

            def select(self, delay):
                now[0] += delay
                return []

        class FakePath:
            def __init__(self, value):
                self.value = str(value)

            def glob(self, pattern):
                return [FakePath(key) for key in records]

            def __str__(self):
                return self.value

        class Process:
            pid = 101
            stdout, stderr = Stream(), Stream()
            returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout):
                self.returncode = -9
                return -9

        guard = SimpleNamespace(
            initialization_case="timeout",
            role="harness",
            spawn_records=[dict(pid=101, bootstrap_argv=[0] * 6 + launch)],
        )

        def killpg(pid, sig):
            signals.append((pid, sig, now[0]))

        identity_check = isolated(FIXTURE, {"check_live_identity"})["check_live_identity"]
        identity_check.__globals__["LIVE_IDENTITY_FIELDS"] = (
            "pid",
            "pgid",
            "sid",
            "boot",
            "pid_namespace",
            "start_ticks",
        )

        def live(expected):
            observed = dict(server, state="S")
            identity_check(expected, observed)
            return observed

        # No imports, real process creation, OS signals or checkpoint fixture.
        ns.update(
            ACTIVE=guard,
            LAUNCH=launch,
            Path=FakePath,
            contextlib=contextlib,
            signal=signal,
            selectors=SimpleNamespace(DefaultSelector=Selector, EVENT_READ=1),
            os=SimpleNamespace(set_blocking=lambda *a: None, killpg=killpg),
            time=SimpleNamespace(
                monotonic=lambda: now[0],
                sleep=lambda delay: now.__setitem__(0, now[0] + delay),
            ),
            read_json=lambda path: records[str(path)],
            role_for=lambda argv: "server",
            live_identity=live,
            initialization_monitor_stall=lambda: None,
            initialization_group_absent=lambda pid: any(row[0] == pid for row in signals),
            write_evidence=lambda name, row: evidence.update({name: row}),
        )
        guard.initialization_group_absent = ns["initialization_group_absent"]
        with self.assertRaisesRegex(AssertionError, "S2 cold role deadline"):
            ns["initialization_collect"](Process(), 40)
        self.assertIn(
            202,
            [row[0] for row in signals],
            "separate installed server survived cold-role deadline",
        )
        self.assertTrue(all(row[1] == signal.SIGKILL and row[2] <= 40.05 for row in signals))
        self.assertLessEqual(now[0], 45)
        self.assertEqual(guard.initialization_server_cleanup["status"], "contained")

        # Reuse and missing ownership refuse server signals, even after a
        # previously valid record was observed. The launcher is still reaped.
        for change in (
            {"start_ticks": 999},
            {"pgid": 303},
            {"sid": 303},
            {"boot": "OTHER"},
            {"pid_namespace": "pid:[OTHER]"},
            None,
        ):
            with self.subTest(identity_change=change):
                now[0] = 0
                signals.clear()
                guard.__dict__.pop("initialization_server_identity", None)
                if change is None:
                    records.clear()
                else:
                    records["/evidence/join-launch-202.json"] = dict(
                        server, **change, bootstrap_argv=[0] * 6 + ["api-serve"]
                    )
                with self.assertRaises(AssertionError):
                    ns["initialization_collect"](Process(), 40)
                self.assertNotIn(202, [row[0] for row in signals])
                self.assertIn(101, [row[0] for row in signals])
                self.assertEqual(guard.initialization_server_cleanup["status"], "unknown")
                self.assertTrue(guard.initialization_server_cleanup["host_containment_required"])

        records["/evidence/join-launch-202.json"] = dict(server, bootstrap_argv=[0] * 6 + ["api-serve"])
        guard.__dict__.pop("initialization_server_identity", None)
        guard.initialization_case = "failure"
        now[0] = 0
        signals.clear()

        def launcher_error(delay):
            now[0] += delay
            raise RuntimeError("UNITONLY launcher read error")

        selector = Selector()
        selector.select = launcher_error
        ns["selectors"].DefaultSelector = lambda: selector
        with self.assertRaisesRegex(RuntimeError, "UNITONLY launcher read error"):
            ns["initialization_collect"](Process(), 40)
        self.assertEqual({row[0] for row in signals}, {101, 202})
        self.assertLessEqual(now[0], 5.05)
        self.assertEqual(guard.initialization_server_cleanup["status"], "contained")

        # Unreapable group consumes one shared reserve, never a fresh five seconds
        # per process. Cleanup uncertainty cannot be reported as success.
        now[0] = 0
        signals.clear()
        guard.initialization_group_absent = lambda pid: False
        with self.assertRaisesRegex(AssertionError, "server group reap deadline"):
            ns["initialization_collect"](Process(), 40)
        self.assertLessEqual(now[0], 5.05)
        self.assertEqual(guard.initialization_server_cleanup["status"], "unknown")
        self.assertTrue(guard.initialization_server_cleanup["host_containment_required"])

        # Legacy collection and positive/native metadata roles never discover or
        # signal an installed server, even with the same fake launcher PID.
        ns.update(isolated(HARNESS, {"collect"}))
        legacy = ns["collect"]
        legacy.__globals__.update(ns)
        for case, role, collector, message in (
            (None, "harness", legacy, "E1 role collection deadline"),
            (
                "positive",
                "harness",
                ns["initialization_collect"],
                "S2 cold role deadline",
            ),
            (
                "timeout",
                "server",
                ns["initialization_collect"],
                "S2 cold role deadline",
            ),
        ):
            with self.subTest(case=case, role=role):
                now[0] = 0
                signals.clear()
                guard.initialization_case, guard.role = case, role
                ns["selectors"].DefaultSelector = Selector
                with self.assertRaisesRegex(AssertionError, message):
                    collector(Process(), 40)
                self.assertEqual([row[0] for row in signals], [101])

    def test_checkpoint_cleanup_deadline_survives_monitor_exception(self):
        import builtins
        import contextlib
        import signal
        from types import SimpleNamespace

        ns = isolated(
            HARNESS,
            {
                "initialization_collect",
                "initialization_monitor_stall",
                "initialization_contain_launcher",
            },
        )
        now, signals, waits, closed = [10.0], [], [], []
        server = dict(
            pid=202,
            pgid=202,
            sid=202,
            parent_pid=101,
            case="timeout",
            before_owner_construction=True,
            observed_at=0.0,
        )
        launch = ["api-launch"]
        guard = SimpleNamespace(
            initialization_case="timeout",
            role="harness",
            spawn_records=[dict(pid=101, bootstrap_argv=[0] * 6 + launch)],
            initialization_group_absent=lambda pid: False,
        )

        class Stream:
            def fileno(self):
                return 1

            def close(self):
                closed.append(self)

        class Process:
            pid = 101
            stdout, stderr = Stream(), Stream()

            def poll(self):
                return None

            def wait(self, timeout):
                waits.append(timeout)
                now[0] += timeout
                raise TimeoutError("UNITONLY unreaped launcher")

        class Selector:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def register(self, *args):
                pass

            def get_map(self):
                return {1: True}

            def select(self, delay):
                raise AssertionError("monitor must fail before select")

        class FakePath:
            def __init__(self, value):
                self.value = value

            def exists(self):
                return True

        def fake_import(name, *args, **kwargs):
            self.assertEqual(name, "workflow_graphql_execution_join_fixture")
            return SimpleNamespace(initialization_group_absent=lambda pid: False)

        # Execute the real monitor/collector/finally chain with fake clock and
        # syscalls only; no fixture/package imports or real process activity.
        ns["__builtins__"] = dict(vars(builtins), __import__=fake_import)
        # Functions retain their builtins at construction, so recompile them.
        exec(
            compile(
                ast.Module(
                    body=[
                        node
                        for node in ast.parse(HARNESS.read_text()).body
                        if isinstance(node, ast.FunctionDef) and node.name in ns
                    ],
                    type_ignores=[],
                ),
                str(HARNESS),
                "exec",
            ),
            ns,
        )
        ns.update(
            ACTIVE=guard,
            LAUNCH=launch,
            Path=FakePath,
            contextlib=contextlib,
            signal=signal,
            selectors=SimpleNamespace(DefaultSelector=Selector, EVENT_READ=1),
            os=SimpleNamespace(
                set_blocking=lambda *args: None,
                killpg=lambda pid, sig: signals.append((pid, sig, now[0])),
            ),
            time=SimpleNamespace(
                monotonic=lambda: now[0],
                sleep=lambda delay: now.__setitem__(0, now[0] + delay),
            ),
            read_json=lambda path: (
                server if "pre-readiness" in path.value else dict(server, bootstrap_argv=[0] * 6 + ["api-serve"])
            ),
            role_for=lambda argv: "server",
            live_identity=lambda row: row,
            initialization_owned_server=lambda pid: server,
            write_evidence=lambda *args: self.fail("unreaped checkpoint cannot produce success evidence"),
        )
        with self.assertRaises(TimeoutError) as caught:
            ns["initialization_collect"](Process(), 40)
        self.assertIsInstance(caught.exception.__context__, AssertionError)
        self.assertIn("server group reap deadline", str(caught.exception.__context__))
        self.assertEqual(signals[0], (202, signal.SIGKILL, 10.0))
        self.assertIn(101, [row[0] for row in signals])
        self.assertEqual(len(closed), 2)
        self.assertEqual(guard.initialization_server_cleanup["status"], "unknown")
        self.assertTrue(guard.initialization_server_cleanup["host_containment_required"])
        self.assertFalse(getattr(guard, "initialization_stall_stop", None))
        self.assertLessEqual(now[0], 15.0, "collector finally restarted checkpoint cleanup allowance")
        self.assertEqual(guard.initialization_cleanup_deadline, 15.0)
        self.assertTrue(all(timeout == 0 for timeout in waits))

    def test_monitor_success_open_pipes_share_containment_deadline(self):
        for reap_seconds in (0.0, 5.0):
            with self.subTest(reap_seconds=reap_seconds):
                self._monitor_success_launcher_alive(eof=False, reap_seconds=reap_seconds)

    def test_monitor_success_eof_shares_containment_deadline(self):
        for reap_seconds in (0.0, 5.0):
            with self.subTest(reap_seconds=reap_seconds):
                self._monitor_success_launcher_alive(eof=True, reap_seconds=reap_seconds)

    def _monitor_success_launcher_alive(self, *, eof, reap_seconds):
        import builtins
        import contextlib
        import signal
        from types import SimpleNamespace

        names = {
            "initialization_collect",
            "initialization_monitor_stall",
            "initialization_contain_launcher",
            "initialization_owned_server",
        }
        now, signals, waits, selects, closed, evidence, identities = (
            [10.0],
            [],
            [],
            [],
            [],
            {},
            [],
        )
        launch = ["api-launch"]
        server = dict(
            pid=202,
            pgid=202,
            sid=202,
            parent_pid=101,
            start_ticks=123,
            boot="UNITONLY",
            pid_namespace="pid:[UNITONLY]",
            case="timeout",
            before_owner_construction=True,
            observed_at=0.0,
        )

        def group_absent(pid):
            return pid == 202 and any(row[0] == pid for row in signals) and now[0] >= 10.0 + reap_seconds

        guard = SimpleNamespace(
            initialization_case="timeout",
            role="harness",
            spawn_records=[dict(pid=101, bootstrap_argv=[0] * 6 + launch)],
            initialization_group_absent=group_absent,
        )

        class Stream:
            def fileno(self):
                return 1

            def close(self):
                closed.append(self)

        class Process:
            pid = 101
            stdout, stderr = Stream(), Stream()

            def poll(self):
                return None

            def wait(self, timeout):
                waits.append((now[0], timeout))
                now[0] += timeout
                raise TimeoutError("UNITONLY launcher remains alive")

        class Selector:
            def __init__(self):
                self.streams = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def register(self, stream, event):
                self.streams[stream] = SimpleNamespace(fileobj=stream)

            def unregister(self, stream):
                del self.streams[stream]

            def get_map(self):
                return self.streams

            def select(self, delay):
                selects.append((now[0], delay))
                now[0] += delay
                return [(key, 1) for key in self.streams.values()] if eof else []

        class FakePath:
            def __init__(self, value):
                self.value = value

            def exists(self):
                return True

            def glob(self, pattern):
                return [FakePath("/evidence/join-launch-202.json")]

        def fake_import(name, *args, **kwargs):
            self.assertEqual(name, "workflow_graphql_execution_join_fixture")
            return SimpleNamespace(initialization_group_absent=group_absent)

        # Compile real monitor, ownership, collector and containment functions;
        # replace only clock, process, filesystem and fixture-import boundaries.
        ns: dict = {"__builtins__": dict(vars(builtins), __import__=fake_import)}
        exec(
            compile(
                ast.Module(
                    body=[
                        node
                        for node in ast.parse(HARNESS.read_text()).body
                        if isinstance(node, ast.FunctionDef) and node.name in names
                    ],
                    type_ignores=[],
                ),
                str(HARNESS),
                "exec",
            ),
            ns,
        )
        ns.update(
            ACTIVE=guard,
            LAUNCH=launch,
            Path=FakePath,
            contextlib=contextlib,
            signal=signal,
            selectors=SimpleNamespace(DefaultSelector=Selector, EVENT_READ=1),
            os=SimpleNamespace(
                set_blocking=lambda *args: None,
                read=lambda *args: b"",
                killpg=lambda pid, sig: signals.append((pid, sig, now[0])),
            ),
            time=SimpleNamespace(
                monotonic=lambda: now[0],
                sleep=lambda delay: now.__setitem__(0, now[0] + delay),
            ),
            read_json=lambda path: (
                server if "pre-readiness" in path.value else dict(server, bootstrap_argv=[0] * 6 + ["api-serve"])
            ),
            role_for=lambda argv: "server",
            live_identity=lambda row: identities.append(dict(row)),
            write_evidence=lambda name, row: evidence.update({name: dict(row)}),
        )
        with self.assertRaisesRegex(TimeoutError, "UNITONLY launcher remains alive"):
            ns["initialization_collect"](Process(), 40)
        self.assertEqual(guard.initialization_cleanup_deadline, 15.0)
        self.assertEqual(evidence["initialization-stall-stop.json"]["server_pid"], 202)
        self.assertTrue(
            group_absent(202),
            "real monitor must successfully observe server disappearance",
        )
        self.assertEqual(identities, [server], "server signal must retain the identity check")
        self.assertEqual(signals[0], (202, signal.SIGKILL, 10.0))
        self.assertEqual({row[0] for row in signals}, {101, 202})
        self.assertEqual(len(closed), 2)
        self.assertEqual(guard.initialization_server_cleanup["status"], "unknown")
        self.assertTrue(guard.initialization_server_cleanup["host_containment_required"])
        self.assertLessEqual(
            now[0],
            15.0,
            "successful monitor leaked containment deadline into role deadline 40",
        )
        self.assertTrue(all(start + timeout <= 15.0 for start, timeout in waits))
        self.assertTrue(all(start < 15.0 and start + delay <= 15.0 for start, delay in selects))
        self.assertTrue(all(timeout == 0 for start, timeout in waits if start >= 15.0))

    def test_unknown_cleanup_blocks_followup_launches_and_is_in_proof(self):
        functions = {
            node.name: ast.unparse(node)
            for node in ast.parse(HARNESS.read_text()).body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("initialization_server_cleanup", functions["initialization_inside"])
        self.assertIn("host_containment_required", functions["initialization_inside"])
        case = functions["initialization_installed_case"]
        self.assertLess(case.index("cleanup['status']"), case.index("invoke(STOP)"))


def unitonly_proof(case="positive") -> tuple[dict, bytes]:
    """UNITONLY synthetic full-schema vector; never actual runtime evidence."""
    import hashlib

    junit = (
        '<testsuites><testsuite tests="1"><testcase name="test_initialization_' + case + '"/></testsuite></testsuites>'
    ).encode()
    source = {"UNITONLY.py": "a" * 64}
    physical = dict(
        path="/isaac-sim/kit/python/lib/python3.12/site-packages/warp/bin/warp.so",
        links=[],
        size=1024,
        sha256="b" * 64,
    )
    physical["physical"] = physical["path"]
    module_path = "/isaac-sim/kit/python/lib/python3.12/site-packages/warp/__init__.py"
    module = dict(
        physical,
        name="warp",
        path=module_path,
        physical=module_path,
        origin=module_path,
        preloaded=False,
    )
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
            pythonapi_bootstrap=[
                dict(
                    kind="ctypes-pythonapi-process-namespace",
                    argument=None,
                    status="completed",
                    role=role,
                    pid=100 + index,
                    source=dict(
                        physical,
                        path="/isaac-sim/kit/python/lib/python3.12/ctypes/__init__.py",
                        physical="/isaac-sim/kit/python/lib/python3.12/ctypes/__init__.py",
                    ),
                    executable=dict(
                        physical,
                        path="/isaac-sim/kit/python/bin/python3",
                        physical="/isaac-sim/kit/python/bin/python3",
                        device=1,
                        inode=2,
                    ),
                    executable_binding=dict(
                        invocation="/isaac-sim/kit/python/bin/python3",
                        implementation="cpython",
                        version=[3, 12],
                        alias=None,
                        kernel=dict(
                            path="/proc/self/exe",
                            target="/isaac-sim/kit/python/bin/python3",
                            device=1,
                            inode=2,
                            pid=100 + index,
                        ),
                    ),
                    callsite=dict(module_line=475, init_line=382, module_code="<module>", init_code="CDLL.__init__"),
                )
            ],
            module_origins=[copy.deepcopy(module)],
            mapped_libraries=[
                dict(
                    address="1000-2000",
                    permissions="r-xp",
                    offset="00000000",
                    device="00:01",
                    inode="1",
                    path=physical["path"],
                )
            ],
            cpu_metadata=[],
            physical_read_budget=dict(bytes=16384, files=1, deadline=1),
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
            (
                "network",
                "subprocess",
                "provider",
                "runtime",
                "graph",
                "legacy",
                "blocked_import",
            ),
            0,
        ),
        initialization_roles=rows,
    )
    if case != "positive":
        proof["host_containment_required"] = False
        proof["initialization_server_cleanup"] = dict(
            status="contained",
            host_containment_required=False,
            launcher_pid=99,
            server_pid=100,
            group_reap_seconds=1,
        )
        proof["pre_readiness_failure"] = dict(
            after_real_initialization=True,
            before_owner_construction=True,
            case=case,
            readiness_absent=True,
            server_pid=100,
            original_failure_retained=True,
            catalogue_sha256="c" * 64,
            kind=("fixed-initialization-failure" if case == "failure" else "supervisor-stall-not-native-hang"),
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

    def test_executable_kernel_binding_required(self):
        proof, junit = unitonly_proof()
        proof["initialization_roles"][0]["pythonapi_bootstrap"][0].pop("executable_binding", None)
        with self.assertRaises((AssertionError, KeyError, TypeError)):
            self.verify(proof, junit, "positive")

    def test_kernel_binding_malformed_mismatched_and_role_drift(self):
        proof, junit = unitonly_proof()
        original = proof["initialization_roles"][0]["pythonapi_bootstrap"][0]["executable_binding"]
        mutations = [None, [], {}, dict(original, extra=True)]
        for key in original:
            missing = copy.deepcopy(original)
            del missing[key]
            mutations.append(missing)
        for key, value in (
            ("invocation", "/other"),
            ("implementation", "pypy"),
            ("version", [3, 11]),
            ("version", [True, 12]),
            ("alias", []),
            ("kernel", {}),
        ):
            mutations.append(dict(original, **{key: value}))
        for key, value in (("target", "/other"), ("path", "/proc/1/exe"), ("pid", 101), ("device", True), ("inode", 3)):
            mutations.append(dict(original, kernel=dict(original["kernel"], **{key: value})))
        for binding in mutations:
            with self.subTest(binding=binding):
                bad = copy.deepcopy(proof)
                bad["initialization_roles"][0]["pythonapi_bootstrap"][0]["executable_binding"] = binding
                with self.assertRaises((AssertionError, KeyError, TypeError)):
                    self.verify(bad, junit, "positive")
        # An internally consistent but different physical inode in another role refuses.
        changed = proof["initialization_roles"][1]["pythonapi_bootstrap"][0]
        changed["executable"]["inode"] = 3
        changed["executable_binding"]["kernel"]["inode"] = 3
        with self.assertRaises(AssertionError):
            self.verify(proof, junit, "positive")

    def test_terminal_alias_proof_is_separate_from_physical_file(self):
        proof, junit = unitonly_proof()
        for row in proof["initialization_roles"]:
            witness = row["pythonapi_bootstrap"][0]
            target = "/isaac-sim/kit/python/bin/python3.12"
            witness["executable"].update(path=target, physical=target)
            witness["executable_binding"]["kernel"]["target"] = target
            witness["executable_binding"]["alias"] = dict(
                target="python3.12", device=1, inode=3, mode=0o120777, size=len("python3.12"), mtime_ns=1, ctime_ns=1
            )
        self.assertTrue(self.verify(proof, junit, "positive"))
        for field, value in (("target", "../python3.12"), ("mode", 0o100755), ("size", 0), ("inode", True)):
            bad = copy.deepcopy(proof)
            bad["initialization_roles"][0]["pythonapi_bootstrap"][0]["executable_binding"]["alias"][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.verify(bad, junit, "positive")
        bad = copy.deepcopy(proof)
        bad["initialization_roles"][0]["pythonapi_bootstrap"][0]["executable"]["links"] = ["python3"]
        with self.assertRaises(AssertionError):
            self.verify(bad, junit, "positive")
        proof["initialization_roles"][1]["pythonapi_bootstrap"][0]["executable_binding"]["alias"]["ctime_ns"] = 2
        with self.assertRaises(AssertionError):
            self.verify(proof, junit, "positive")

    def test_context_reads_cannot_be_omitted_from_budget(self):
        proof, junit = unitonly_proof()
        proof["initialization_roles"][0]["physical_read_budget"]["bytes"] = 2048
        with self.assertRaises(AssertionError):
            self.verify(proof, junit, "positive")

    def test_context_budget_aggregate_keeps_existing_ceiling(self):
        proof, junit = unitonly_proof()
        for row in proof["initialization_roles"]:
            row["physical_read_budget"]["bytes"] = 2 * 1024**3
        self.assertTrue(self.verify(proof, junit, "positive"))
        proof["initialization_roles"][0]["physical_read_budget"]["bytes"] += 1
        with self.assertRaises(AssertionError):
            self.verify(proof, junit, "positive")

    def test_unitonly_full_schema_controls(self):
        for case in ("positive", "failure", "timeout"):
            for digest in ("c" * 64, "d" * 64):
                proof, junit = unitonly_proof(case)
                for row in proof["initialization_roles"]:
                    row["catalogue_sha256"] = digest
                if case != "positive":
                    proof["pre_readiness_failure"]["catalogue_sha256"] = digest
                self.assertTrue(self.verify(proof, junit, case))

    def test_pythonapi_bootstrap_missing_duplicate_and_mismatch_refuse(self):
        for case in ("positive", "failure", "timeout"):
            proof, junit = unitonly_proof(case)
            self.assertTrue(self.verify(proof, junit, case))
            bad = copy.deepcopy(proof)
            bad["initialization_roles"][0].pop("pythonapi_bootstrap", None)
            with self.assertRaises((AssertionError, KeyError)):
                self.verify(bad, junit, case)
            witness = proof["initialization_roles"][0]["pythonapi_bootstrap"][0]
            mutations = [[], [witness, witness]]
            for key, value in (
                ("status", "admitted"),
                ("role", "init-refine"),
                ("pid", 999),
                ("argument", "None"),
                ("kind", "native-library"),
            ):
                mutations.append([dict(witness, **{key: value})])
            for field, path in (("source", "/shadow/ctypes.py"), ("executable", "/usr/bin/python")):
                mutations.append([dict(witness, **{field: dict(witness[field], path=path, physical=path)})])
            mutations.append([dict(witness, callsite=dict(witness["callsite"], module_line=0))])
            if case == "positive":
                mutations.append([dict(witness, source=dict(witness["source"], sha256="e" * 64))])
            for value in mutations:
                with self.subTest(case=case, value=value):
                    bad = copy.deepcopy(proof)
                    bad["initialization_roles"][0]["pythonapi_bootstrap"] = value
                    with self.assertRaises((AssertionError, KeyError)):
                        self.verify(bad, junit, case)

    def test_unknown_or_unbounded_server_cleanup_cannot_pass(self):
        for case in ("failure", "timeout"):
            proof, junit = unitonly_proof(case)
            self.assertTrue(self.verify(proof, junit, case))
            for patch in (
                {"status": "unknown"},
                {"host_containment_required": True},
                {"server_pid": 999},
                {"group_reap_seconds": 5.01},
                {"group_reap_seconds": -1},
            ):
                with self.subTest(case=case, patch=patch):
                    bad = copy.deepcopy(proof)
                    bad["initialization_server_cleanup"].update(patch)
                    with self.assertRaises(AssertionError):
                        self.verify(bad, junit, case)
            bad = copy.deepcopy(proof)
            del bad["initialization_server_cleanup"]
            with self.assertRaises((AssertionError, KeyError)):
                self.verify(bad, junit, case)

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
            row["physical_read_budget"].update(bytes=32768, files=16)
        self.assertTrue(self.verify(proof, junit, "positive"))
        proof["initialization_roles"][0]["native_libraries"].append(
            copy.deepcopy(proof["initialization_roles"][0]["native_libraries"][0])
        )
        with self.assertRaises(AssertionError):
            self.verify(proof, junit, "positive")
        proof, junit = unitonly_proof()
        for row in proof["initialization_roles"]:
            # Seven context reads plus the module identity share the old cap.
            row["native_libraries"][0]["size"] = 2 * 1024**3 - 8 * 1024
            row["physical_read_budget"]["bytes"] = 2 * 1024**3
        self.assertTrue(self.verify(proof, junit, "positive"))
        proof["initialization_roles"][0]["native_libraries"][0]["size"] += 1
        with self.assertRaises(AssertionError):
            self.verify(proof, junit, "positive")
        proof, junit = unitonly_proof()
        proof["initialization_roles"][0]["native_libraries"][0]["size"] = 2 * 1024**3
        proof["initialization_roles"][0]["physical_read_budget"]["bytes"] = 2 * 1024**3 + 8 * 1024
        self.assertTrue(self.verify(proof, junit, "positive"))

    def test_native_observations_are_required_not_boolean_claims(self):
        proof, junit = unitonly_proof()
        for key in ("mapped_libraries", "cpu_metadata", "physical_read_budget"):
            bad = copy.deepcopy(proof)
            del bad["initialization_roles"][0][key]
            with self.assertRaises((AssertionError, KeyError)):
                self.verify(bad, junit, "positive")
        bad = copy.deepcopy(proof)
        bad["initialization_roles"][0]["mapped_libraries"] *= 257
        with self.assertRaises(AssertionError):
            self.verify(bad, junit, "positive")
        bad = copy.deepcopy(proof)
        bad["initialization_roles"][0]["cpu_metadata"] = [{}, {}]
        with self.assertRaises((AssertionError, KeyError)):
            self.verify(bad, junit, "positive")

    def test_catalogue_identity_agreement_and_checkpoint_binding(self):
        for case in ("positive", "failure", "timeout"):
            proof, junit = unitonly_proof(case)
            self.assertTrue(self.verify(proof, junit, case))
            targets = [("role", i) for i in range(len(proof["initialization_roles"]))]
            if case != "positive":
                targets.append(("checkpoint", 0))
            for kind, index in targets:
                for value in (
                    None,
                    1,
                    "c" * 63,
                    "C" * 64,
                    "g" * 64,
                    "d" * 64,
                    "MISSING",
                ):
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


def test_initialization_positive():
    """IF-B only inside the fixed harness: four real cold preparation roles."""
    import workflow_graphql_execution_join_harness as harness

    assert harness.ACTIVE.initialization_case == "positive"
    rows = [harness.initialization_fresh(role) for role in harness.INITIALIZATION_ROLES]
    harness.ACTIVE.initialization_result = dict(initialization_roles=rows)


def test_initialization_failure():
    """IF-C fixed post-initialization failure through the installed launcher."""
    import workflow_graphql_execution_join_harness as harness

    harness.initialization_installed_case("failure")


def test_initialization_timeout():
    """IF-C externally stopped pre-readiness stall, not a native-hang simulation."""
    import workflow_graphql_execution_join_harness as harness

    harness.initialization_installed_case("timeout")


if __name__ == "__main__":
    unittest.main()
