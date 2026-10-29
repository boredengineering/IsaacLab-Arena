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


class InitializationNativeAdmission(unittest.TestCase):
    """Real admission AST with inert physical/load ports, never native execution."""

    def setUp(self):
        from types import SimpleNamespace

        names = {"InitializationAdmission", "InitializationLoader", "InitializationPythonAPILoader"}
        tree = ast.parse(HARNESS.read_text())
        self.ns: dict = dict(Path=pathlib.Path, sys=SimpleNamespace(modules={}))
        exec(
            compile(
                ast.Module(
                    body=[n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in names], type_ignores=[]
                ),
                str(HARNESS),
                "exec",
            ),
            self.ns,
        )
        cls = self.ns["InitializationAdmission"]
        self.admission = cls.__new__(cls)
        self.admission.guard = SimpleNamespace(forbidden=dict(runtime=0, blocked_import=0))
        self.root = "/isaac-sim/kit/python/lib/python3.12/site-packages/torch"
        self.path = self.root + "/lib/libtorch_global_deps.so"
        self.admission.roots = {"torch": self.root}
        self.admission.libraries = {}
        self.admission.modules = []
        self.admission.budget = dict(bytes=0, files=0, deadline=100)
        self.reads = []
        self.row: dict = dict(path=self.path, sha256="UNITONLY", inode=1)

        def reader(path, budget, **kwargs):
            self.reads.append((path, kwargs))
            return dict(self.row, path=path)

        self.ns["initialization_physical_file"] = reader

    def caught(self, operation):
        # Torch's broad Exception handler can swallow the admission diagnostic.
        try:
            operation()
        except Exception as error:
            return error
        self.fail("admission unexpectedly succeeded")

    def assert_forbidden_proof(self):
        proof, junit = unitonly_proof()
        proof["forbidden"].update(self.admission.guard.forbidden)
        verify = isolated(HARNESS, {"initialization_verify_proof", "initialization_origin"})[
            "initialization_verify_proof"
        ]
        with self.assertRaises(AssertionError):
            verify(proof, junit, "positive")

    def test_caught_explicit_library_denials_latch_before_read(self):
        for path, reason in (
            (None, "S2 unnamed native load has no physical binding"),
            ("libtorch_global_deps.so", "S2 unnamed native load has no physical binding"),
            ("/unreviewed/lib.so", "S2 unreviewed explicit library origin"),
        ):
            with self.subTest(path=path):
                before = self.admission.guard.forbidden["runtime"]
                error = self.caught(
                    lambda: self.admission.audit("ctypes.dlopen", (path,))
                    if path is not None
                    else self.admission.library(path)
                )
                self.assertIs(type(error), AssertionError)
                self.assertEqual(str(error), reason)
                self.assertEqual(self.reads, [])
                self.assertEqual(self.admission.guard.forbidden["runtime"], before + 1)
                self.assert_forbidden_proof()

    def test_caught_physical_library_denial_preserves_original_exception(self):
        for error in (AssertionError("S2 physical read ceiling"), OSError("UNITONLY no-follow refusal")):
            with self.subTest(error=error):

                def refused(*args, **kwargs):
                    raise error

                self.ns["initialization_physical_file"] = refused
                self.admission.first_native_denial = None
                before = self.admission.guard.forbidden["runtime"]
                self.assertIs(self.caught(lambda: self.admission.library(self.path)), error)
                self.assertEqual(self.admission.first_native_denial,
                                 dict(path=self.path, failure_type=type(error).__name__, reason=str(error)))
                self.assertEqual(self.admission.guard.forbidden["runtime"], before + 1)
                self.assertEqual(self.admission.libraries, {})
                self.assert_forbidden_proof()

    def test_permitted_library_reverification_is_unchanged(self):
        self.assertEqual(self.admission.library(self.path), self.row)
        self.admission.audit("ctypes.dlopen", (self.path,))
        self.assertEqual(self.reads, [(self.path, {"binary": True}), (self.path, {"binary": False})])
        self.assertEqual(self.admission.libraries, {self.path: self.row})
        self.assertFalse(any(self.admission.guard.forbidden.values()))
        self.row["inode"] = 2
        error = self.caught(lambda: self.admission.library(self.path))
        self.assertIs(type(error), AssertionError)
        self.assertEqual(self.admission.guard.forbidden["runtime"], 1)
        self.assertEqual(self.admission.libraries[self.path]["inode"], 1)

    def test_native_preload_keeps_operator_approved_physical_root_boundary(self):
        base = "/isaac-sim/kit/python/lib/python3.12/site-packages/nvidia/"
        selected = base + "cublas/lib/libcublas.so.12"
        self.assertEqual(self.admission.library(selected)["path"], selected)
        self.assertEqual(len(self.reads), 1)
        for path in ("/tmp/unreviewed.so", "/isaac-sim-shadow/libcublas.so.12"):
            with self.assertRaises(AssertionError):
                self.admission.library(path)
        self.assertEqual(len(self.reads), 1)

    def loader(self, name="torch._C"):
        from types import SimpleNamespace

        self.load_calls = []
        original = SimpleNamespace(
            create_module=lambda spec: self.load_calls.append("create") or self.module,
            exec_module=lambda module: self.load_calls.append("exec"),
        )
        self.module = SimpleNamespace(
            __file__=self.path,
            __spec__=SimpleNamespace(origin=self.path, submodule_search_locations=None),
        )
        return self.ns["InitializationLoader"](self.admission, name, original, dict(self.row))

    def test_caught_extension_preload_identity_denials_are_sticky(self):
        loader = self.loader()
        self.row["inode"] = 2
        for operation in (lambda: loader.create_module(self.module.__spec__), lambda: loader.exec_module(self.module)):
            with self.subTest(operation=operation):
                before = self.admission.guard.forbidden["runtime"]
                error = self.caught(operation)
                self.assertEqual(str(error), "S2 loader identity drift")
                self.assertEqual(self.admission.guard.forbidden["runtime"], before + 1)
                self.assertEqual(self.load_calls, [])
                self.assert_forbidden_proof()

    def test_caught_extension_postload_identity_denials_are_sticky(self):
        for field in ("origin", "package_path", "witness_limit", "physical"):
            with self.subTest(field=field):
                loader = self.loader()
                self.admission.modules = []
                self.module.__spec__.submodule_search_locations = None

                def original(module):
                    self.load_calls.append("exec")
                    if field == "origin":
                        module.__file__ = "/UNITONLY/wrong.so"
                    elif field == "package_path":
                        module.__spec__.submodule_search_locations = [self.root]
                        module.__path__ = ["/UNITONLY/wrong"]
                    elif field == "witness_limit":
                        self.admission.modules = [{}] * 2048
                    else:
                        self.row["inode"] += 1

                loader.original.exec_module = original
                before = self.admission.guard.forbidden["runtime"]
                error = self.caught(lambda: loader.exec_module(self.module))
                self.assertIs(type(error), AssertionError)
                self.assertEqual(self.admission.guard.forbidden["runtime"], before + 1)
                self.assertEqual(self.load_calls, ["exec"])
                self.assert_forbidden_proof()

    def test_permitted_loader_and_ordinary_module_errors_do_not_poison_guard(self):
        loader = self.loader()
        self.assertIs(loader.create_module(self.module.__spec__), self.module)
        loader.exec_module(self.module)
        self.assertEqual(self.load_calls, ["create", "exec"])
        self.assertEqual(len(self.admission.modules), 1)
        error = ValueError("UNITONLY expected schema negative, not an admission denial")

        def original(module):
            raise error

        loader.original.exec_module = original
        self.assertIs(self.caught(lambda: loader.exec_module(self.module)), error)
        self.assertFalse(any(self.admission.guard.forbidden.values()))

    def test_caught_selected_origin_denials_before_physical_read_are_sticky(self):
        from types import SimpleNamespace

        self.admission.pathfinder = SimpleNamespace(find_spec=lambda *args: None)
        for name, path, reason in (
            ("torch", None, "S2 fixed package origin missing: torch"),
            ("torch._C", ["/UNITONLY/wrong"], "S2 changed package search path"),
        ):
            with self.subTest(name=name):
                before = self.admission.guard.forbidden["blocked_import"]
                error = self.caught(lambda: self.admission.find_spec(name, path))
                self.assertEqual(str(error), reason)
                self.assertEqual(self.reads, [])
                self.assertEqual(self.admission.guard.forbidden["blocked_import"], before + 1)
                self.assert_forbidden_proof()
        self.assertEqual(getattr(self.admission, "first_import_denial", None), dict(
            name="torch", failure_type="AssertionError", reason="S2 fixed package origin missing: torch"))

    def test_absent_admitted_submodule_is_import_error_without_fallback_or_violation(self):
        import importlib
        import sys
        import tempfile
        from importlib.machinery import PathFinder
        from types import ModuleType, SimpleNamespace
        from unittest.mock import patch

        with tempfile.TemporaryDirectory(prefix="s2-optional-import-") as directory:
            name = "s2_optional_unit"
            package = ModuleType(name)
            package.__path__ = [directory]
            self.admission.roots = {name: directory}
            self.admission.pathfinder = PathFinder
            self.ns["sys"] = sys
            fallback = SimpleNamespace(find_spec=lambda *args: self.fail("Unverified fallback finder invoked"))
            with patch.dict(sys.modules, {name: package}), patch.object(sys, "meta_path", [self.admission, fallback]):
                with self.assertRaises(ModuleNotFoundError) as missing:
                    importlib.import_module(name + ".optional")
                self.assertEqual(missing.exception.name, name + ".optional")
            self.assertFalse(any(self.admission.guard.forbidden.values()))
            self.assertEqual(self.reads, [])

    def pythonapi_loader(self, suffix=""):
        import sys
        from types import SimpleNamespace

        path = "/isaac-sim/kit/python/lib/python3.12/ctypes/__init__.py"
        row = dict(path=path, sha256="UNITONLY ctypes")
        raw = (
            "DEFAULT_MODE = 0\n"
            "class CDLL:\n"
            "    def __init__(self, name, mode=DEFAULT_MODE, handle=None,"
            " use_errno=False, use_last_error=False, winmode=None):\n"
            "        self._name = name\n"
            "        final_name = name\n"
            "        self._handle = _dlopen(final_name, mode)\n"
            "class PyDLL(CDLL):\n"
            "    pass\n"
            "pythonapi = PyDLL(None)\n" + suffix
        ).encode()
        module = SimpleNamespace(
            __name__="ctypes", __file__=path, __spec__=SimpleNamespace(origin=path, _initializing=True)
        )
        self.namespace_calls = []

        def dlopen(name, mode):
            self.admission.audit("ctypes.dlopen", (name,))
            self.namespace_calls.append((name, mode))
            return 123  # UNITONLY inert handle, never a host dlopen.

        module._dlopen = dlopen
        self.admission.pythonapi_bootstrap = []
        self.admission.pythonapi_active = None
        self.admission.pythonapi_dlopen = dlopen
        self.admission.guard.initialization_controls_ready = True
        self.admission.guard.initialization_role = "init-server"
        executable = "/isaac-sim/kit/python/bin/python3"
        self.ns.update(
            EXECUTABLE=executable,
            os=SimpleNamespace(getpid=lambda: 123),
            sys=SimpleNamespace(
                modules={"ctypes": module, "_ctypes": SimpleNamespace(dlopen=dlopen)},
                implementation=SimpleNamespace(name="cpython"),
                executable=executable,
                # Remove only this UNITONLY Python dlopen shim's extra frame;
                # a genuine C audit event supplies the CDLL frame directly.
                _getframe=lambda depth: sys._getframe(depth + 2),
            ),
            initialization_physical_file=lambda path, budget, **kw: (row, raw) if kw.get("source") else row,
            initialization_executable_binding=lambda budget: ({"path": executable}, {"UNITONLY": True}),
        )
        original = SimpleNamespace(
            exec_module=lambda module: self.fail("ctypes must execute unchanged captured source")
        )
        return self.ns["InitializationPythonAPILoader"](self.admission, "ctypes", original, row), module

    def test_caught_unnamed_audit_denial_is_sticky(self):
        import sys

        self.ns["sys"]._getframe = sys._getframe
        self.admission.pythonapi_active = None
        self.admission.pythonapi_bootstrap = []
        error = self.caught(lambda: self.admission.audit("ctypes.dlopen", (None,)))
        self.assertEqual(str(error), "S2 unnamed native load denied")
        self.assertEqual(self.admission.guard.forbidden["runtime"], 1)
        self.assertEqual(self.reads, [])
        self.assert_forbidden_proof()

    def test_pythonapi_bootstrap_success_and_replay_accounting(self):
        loader, module = self.pythonapi_loader()
        loader.exec_module(module)
        self.assertEqual(self.namespace_calls, [(None, 0)])
        self.assertEqual(self.admission.pythonapi_bootstrap[0]["status"], "completed")
        self.assertIsNone(self.admission.pythonapi_active)
        self.assertFalse(any(self.admission.guard.forbidden.values()))
        error = self.caught(lambda: loader.exec_module(module))
        self.assertIs(type(error), AssertionError)
        self.assertEqual(self.admission.guard.forbidden["runtime"], 1)
        self.assertEqual(self.namespace_calls, [(None, 0)])
        self.assert_forbidden_proof()

    def test_pythonapi_prevalidation_and_postvalidation_denials_are_sticky(self):
        for stage in ("pre", "post", "executable"):
            with self.subTest(stage=stage):
                loader, module = self.pythonapi_loader("__file__ = '/UNITONLY/wrong'\n" if stage == "post" else "")
                error = OSError("UNITONLY executable binding read refused")
                if stage == "pre":
                    module.__spec__._initializing = False
                if stage == "executable":

                    def refused(budget):
                        raise error

                    self.ns["initialization_executable_binding"] = refused
                before = self.admission.guard.forbidden["runtime"]
                caught = self.caught(lambda: loader.exec_module(module))
                if stage == "executable":
                    self.assertIs(caught, error)
                else:
                    self.assertIs(type(caught), AssertionError)
                self.assertEqual(self.admission.guard.forbidden["runtime"], before + 1)
                self.assertIsNone(self.admission.pythonapi_active)
                if stage == "post":
                    self.assertEqual(self.admission.pythonapi_bootstrap[0]["status"], "admitted")
                else:
                    self.assertEqual(self.namespace_calls, [])
                self.assert_forbidden_proof()


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
        self.trigger_origin = self.p + "/lazy_loader/__init__.py"
        self.paths = [
            "/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle/six.py",
            "/isaac-sim/kit/python/lib/python3.12/importlib/metadata/__init__.py",
            self.isaaclab_root + "/utils/array.py",
            self.p + "/farama_notifications/__init__.py",
            self.p + "/networkx/utils/backends.py",
            self.p + "/fsspec/registry.py",
            "/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/jinja2/__init__.py",
        ]
        names = {"registration_metadata_probe"} | {
            node.name for node in ast.parse(HARNESS.read_text()).body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("initialization_boundary_")
        }
        namespace = isolated(HARNESS, names)
        tree = ast.parse(HARNESS.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "InitializationAdmission")
        exec(compile(ast.Module(body=[cls], type_ignores=[]), str(HARNESS), "exec"), namespace)
        self.ns = namespace
        self.clock = time.monotonic()
        self.reads = []
        self.raw = b"import os\nfrom . import thing\n"
        self.admission = namespace["InitializationAdmission"].__new__(namespace["InitializationAdmission"])
        self.admission.guard = SimpleNamespace(
            initialization_case="positive",
            initialization_role="init-server",
            forbidden=dict(runtime=0, blocked_import=0),
        )
        self.admission.runner = SimpleNamespace(
            GRAPHQL_IMAGE="sha256:b94e17024f1e123ac5a42759ab56651a18823fda7c701e765cba31f200154cdd",
            GRAPHQL_MANIFEST_SHA256="03764536ed54c1f59cbf46305c5bc4ba618e2dc1deeeac7ffdfb21a0dffbf810",
        )
        self.admission.roots = {}
        self.admission.baseline = {"UNITONLY": self.p + "/already.py"}
        self.admission.modules = [{"name": "torch", "origin": self.p + "/torch/__init__.py"}]
        self.admission.budget = dict(bytes=123, files=2, entries=0, deadline=self.clock + 30, byte_limit=2 * 1024**3)
        self.admission.pathfinder = SimpleNamespace(find_spec=lambda *args: SimpleNamespace(origin=self.trigger_origin))
        self.admission.dependency_frontier = None
        self.admission.dependency_frontier_started = False
        self.admission.provider_state = None

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
        import re
        import stat

        def inventory(path, budget):
            raise FileNotFoundError(path)

        namespace.update(
            re=re, stat=stat, E1_YAML_ROOT="/isaac-sim/exts/omni.pip.compute/pip_prebundle/yaml",
            initialization_directory_inventory=inventory,
            json=json,
            hashlib=hashlib,
            os=os,
            sys=SimpleNamespace(path=[], meta_path=[], path_hooks=[], path_importer_cache={}, modules=sys.modules),
            Path=pathlib.Path,
            time=SimpleNamespace(monotonic=lambda: self.clock),
            initialization_physical_file=reader,
        )

        # Legacy collector tests keep their old finite source fixture explicitly;
        # production selects only the literal metadata page. The new page suite
        # replaces these source-isolated ports with the real page helpers.
        namespace.update(
            INITIALIZATION_METADATA_PAGE="EP-A",
            initialization_metadata_page_selection=lambda page: dict(sources=self.paths),
            initialization_metadata_page_state=lambda page, limit: namespace["initialization_boundary_state"](limit),
            initialization_metadata_page_capture=lambda *args, page: namespace["initialization_boundary_inventory"](
                *args, residual=True),
        )

    def legacy_inventory(self, source_rows=None):
        """Exercise the retained collector mode; runtime selects one fixed page."""
        inventory = self.ns["initialization_boundary_inventory"]

        def legacy(*args, **kwargs):
            kwargs["residual"] = False
            report = args[1]
            files = report["files"]
            try:
                if source_rows is not None:
                    report["files"] = source_rows
                return inventory(*args, **kwargs)
            finally:
                report["files"] = files

        self.ns["initialization_boundary_inventory"] = legacy

    def reconcile(self):
        """Test the legacy reconciliation helper without a runtime selection."""
        budget = dict(self.admission.budget, entries=0, entry_limit=4096)
        self.ns["initialization_boundary_reconcile"](
            self.admission, self.admission.dependency_frontier, budget,
            lambda rows, row: rows.append(row) is None,
            lambda row, key, value: row.__setitem__(key, value) is None)

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
        self.assertEqual(len(set(self.paths)), len(self.paths))
        self.assertEqual(self.reads, self.paths)
        self.assertEqual(report["baseline"], self.admission.baseline)
        self.assertEqual(report["module_origins"], self.admission.modules)
        self.assertEqual(report["status"], "partial")
        self.assertFalse(report["expanded_import_admitted"])
        for row in report["files"]:
            self.assertEqual(row["status"], "observed")
            self.assertEqual(row["source_evidence"]["text"].encode(), self.raw)
            self.assertTrue(row["imports_complete"])
            if row["path"].endswith(".kit"):
                self.assertEqual(row["imports"], [])
                self.assertEqual(row["source_evidence"]["format"], "complete_utf8_data")
            else:
                self.assertEqual(row["imports"][1]["line"], 2)
        self.assertLessEqual(len(json.dumps(report, sort_keys=True).encode()), 1048576)
        self.assertEqual(self.admission.budget, dict(original, bytes=123 + len(self.raw) * len(self.paths)))
        self.assertEqual(sys.path, before_path)
        self.assertEqual(dict(sys.modules), before_modules)
        self.trigger()
        self.assertEqual(self.reads, self.paths)

    def test_coherent_packet_reads_actual_path_metadata_under_same_budget(self):
        import hashlib
        import stat

        self.legacy_inventory()
        self.ns["sys"].path = ["/source/scripts", self.p]
        distribution = self.p + "/torch-2.10.0+cu128.dist-info"
        content = {
            distribution + "/METADATA": b"Name: torch\nVersion: 2.10.0+cu128\nRequires-Dist: sympy>=1.13\n",
            distribution + "/entry_points.txt": b"[torch.backends]\nunit = external_unit:activate\n[gymnasium.envs]\ntest = unit_env:register\n",
        }
        observations = []

        def inventory(path, budget):
            self.assertIs(budget, self.admission.budget)
            self.assertEqual(budget["file_limit"], 262144)
            self.assertLessEqual(budget["deadline"], self.clock + 5)
            observations.append(path)
            names = (["torch-2.10.0+cu128.dist-info", "external_unit.py"] if path == self.p else
                     ["METADATA", "entry_points.txt"] if path == distribution else [])
            budget["entries"] += len(names)
            return dict(path=path, device=1, inode=1, entries=[dict(
                name=name, scan_index=i, mode=(stat.S_IFDIR if name.endswith(".dist-info") else stat.S_IFREG),
                size=len(content.get(path + "/" + name, b"")), device=1, inode=i+2, links=1,
            ) for i, name in enumerate(names)])

        def reader(path, budget, **kwargs):
            if path in content:
                self.reads.append(path)
                raw = content[path]
                budget["bytes"] += len(raw)
                return dict(path=path, physical=path, size=len(raw), links=[],
                            sha256=hashlib.sha256(raw).hexdigest()), raw
            return self.reader(path, budget, **kwargs)

        self.ns.update(initialization_directory_inventory=inventory, initialization_physical_file=reader)
        self.trigger()
        report = self.admission.dependency_frontier
        self.assertIn("boundary", report, "missing integrated metadata/native boundary")
        boundary = report["boundary"]
        self.assertEqual(boundary["sys_path"], ["/source/scripts", self.p])
        self.assertTrue(boundary["metadata_complete"])
        self.assertEqual(boundary["torch_backends"][0]["value"], "external_unit:activate")
        self.assertEqual(boundary["torch_backends"][0]["effect_review"], "required_not_admitted")
        self.assertIsNotNone(boundary["torch_backends"][0]["target_origins"], "plugin target origin not inspected")
        self.assertEqual(boundary["torch_backends"][0]["target_origins"][0]["path"], self.p + "/external_unit.py")
        self.assertEqual(boundary["distributions"][0]["version"], "2.10.0+cu128")
        self.assertEqual(boundary["distributions"][0]["requires_dist"], ["sympy>=1.13"])
        self.assertEqual(boundary["metadata_files"], 2)
        self.assertEqual(set(self.reads), set(self.paths) | set(content))
        self.assertTrue(observations)
        self.assertFalse(report["expanded_import_admitted"])
        self.assertEqual(report["bytes_read"], len(self.raw) * len(self.paths) + sum(map(len, content.values())))
        self.assertEqual(self.admission.budget["bytes"], 123 + report["bytes_read"])

    def test_source_observed_mpmath_backend_metadata_is_not_auto_admitted(self):
        import hashlib
        import stat

        self.raw = b"try:\n    import gmpy2\nexcept ImportError:\n    pass\n"
        self.legacy_inventory([dict(path=self.p + "/mpmath/libmp/backend.py",
                                    source_evidence=dict(text=self.raw.decode()))])
        self.ns["sys"].path = [self.p]
        raw = b"Name: gmpy2\nVersion: 2.2.1\n"
        metadata_path = self.p + "/gmpy2-2.2.1.dist-info/METADATA"

        def inventory(path, budget):
            leaves = (["gmpy2-2.2.1.dist-info"] if path == self.p else
                      ["METADATA"] if path.endswith(".dist-info") else [])
            budget["entries"] += len(leaves)
            return dict(path=path, device=1, inode=1, entries=[dict(name=name, scan_index=i,
                mode=stat.S_IFDIR if name.endswith(".dist-info") else stat.S_IFREG,
                size=len(raw), links=1, device=1, inode=2+i) for i, name in enumerate(leaves)])

        def reader(path, budget, **kwargs):
            if path == metadata_path:
                self.reads.append(path)
                budget["bytes"] += len(raw)
                return dict(path=path, physical=path, links=[], size=len(raw), sha256=hashlib.sha256(raw).hexdigest()), raw
            return self.reader(path, budget, **kwargs)

        self.ns.update(initialization_directory_inventory=inventory, initialization_physical_file=reader)
        self.trigger()
        report = self.admission.dependency_frontier
        self.assertIn(metadata_path, self.reads, "source-selected backend metadata not included")
        report["files"][0]["path"] = self.p + "/mpmath/libmp/backend.py"  # UNITONLY legacy source selector.
        self.reconcile()
        backend = next(row for row in report["boundary"]["external_families"] if row["module"] == "gmpy2")
        self.assertEqual(backend["distributions"][0]["version"], "2.2.1")
        self.assertFalse(backend["admitted"])
        self.assertNotIn("sage", [row["module"] for row in report["boundary"]["external_families"]])

    def test_import_qualification_and_external_baseline_are_exact(self):
        self.raw = (b"import filelock\nif TYPE_CHECKING:\n    import sympy\n"
                    b"def deferred():\n    import networkx\ntry:\n    import gmpy2\nexcept ImportError:\n    pass\n")
        self.admission.baseline = {"filelock": self.p + "/filelock/__init__.py", "filelock.sub": "UNITONLY"}
        self.trigger()
        report = self.admission.dependency_frontier
        edges = {row["names"][0]: row for row in report["files"][0]["imports"]}
        self.assertIn("qualification", edges["filelock"], "imports lack eager/deferred/type-only qualification")
        self.assertEqual(edges["filelock"]["qualification"], "eager_syntax")
        self.assertEqual(edges["sympy"]["qualification"], "type_only")
        self.assertEqual(edges["networkx"]["qualification"], "deferred")
        self.assertEqual(edges["gmpy2"]["qualification"], "conditional")
        report["files"][0]["path"] = self.p + "/mpmath/libmp/backend.py"  # UNITONLY legacy source selector.
        self.reconcile()
        families = {row["module"]: row for row in report["boundary"]["external_families"]}
        self.assertEqual(families["filelock"]["baseline_full_names"], self.admission.baseline)
        self.assertTrue(families["filelock"]["source_edges"])
        self.assertFalse(families["filelock"]["admitted"])
        self.assertIn("gmpy2", families)
        self.assertEqual(families["sympy"]["effect_review"], "required_not_admitted")

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
            ("failure", "init-server", "lazy_loader", self.trigger_origin),
            ("positive", "init-generate", "lazy_loader", self.trigger_origin),
            ("positive", "init-server", "other", self.trigger_origin),
            ("positive", "init-server", "lazy_loader", self.paths[0]),
            ("positive", "init-server", "lazy_loader", self.p + "/lazy_loader/other.py"),
        ):
            self.admission.guard.initialization_case = case
            self.admission.guard.initialization_role = role
            self.admission.pathfinder.find_spec = lambda *args: type("Spec", (), {"origin": origin})()
            self.trigger(name)
            self.assertEqual(self.reads, [])
        self.admission.guard.initialization_case = "positive"
        self.admission.guard.initialization_role = "init-server"
        self.admission.pathfinder.find_spec = lambda *args: type("Spec", (), {"origin": self.trigger_origin})()

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
            ["observed", "not_read_missing", "not_read_refused", "observed"]
            + ["not_read_deadline"] * (len(self.paths) - 4),
        )
        self.assertEqual(report["bytes_read"], len(self.raw) * 2 + 7)
        self.assertEqual(self.admission.budget["deadline"], deadline)
        self.assertEqual(report["files"][0]["source_evidence"]["text"].encode(), self.raw)
        self.assertTrue({"metadata_files", "plugins", "distributions", "numpy_hook", "projection", "native", "limits"}
                        <= set(report["boundary"]), "terminal boundary fields must precede source I/O")

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
        self.assertEqual(self.admission.budget, dict(original, bytes=123 + len(self.raw) * len(self.paths)))
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
            if row["path"].endswith(".kit"):
                self.assertTrue(row["imports_complete"])
                self.assertNotIn("imports_error_type", row)
                continue
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
            files = [pathlib.Path(root, str(i) + ".py") for i in range(len(self.paths))]
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
        self.assertEqual(len(report["files"]), len(self.paths))
        self.admission.dependency_frontier_started = False
        self.admission.baseline = {"good": "origin", "unexpected": object()}
        self.trigger()
        report = self.admission.dependency_frontier
        self.assertEqual(report["baseline"], {"good": "origin"})
        self.assertNotIn("not_read_pending", [row["status"] for row in report["files"]])

    def test_residual_batch_retains_first_source_at_shorter_role_read_cap(self):
        import hashlib
        import json
        import os
        import stat
        import tempfile
        from types import SimpleNamespace

        fn = isolated(HARNESS, {"initialization_physical_file"})["initialization_physical_file"]
        projected = SimpleNamespace(**{k: getattr(os, k) for k in dir(os)})
        projected.fstatvfs = lambda fd: SimpleNamespace(f_flag=os.ST_RDONLY)
        fn.__globals__.update(os=projected, stat=stat, time=self.ns["time"], hashlib=hashlib)
        with tempfile.TemporaryDirectory() as root:
            small, large = pathlib.Path(root, "first.py"), pathlib.Path(root, "candidate.py")
            self.admission.budget["byte_limit"] = 123 + 524288
            small.write_bytes(self.raw)
            # Legal physical size but source escaping exceeds the report cap.
            large.write_bytes(b"#" + bytes([1]) * 262143)

            def reader(path, budget, **kwargs):
                self.reads.append(path)
                return fn(str(small if path == self.paths[0] else large), budget, **kwargs)

            self.ns["initialization_physical_file"] = reader
            self.trigger()
        report = self.admission.dependency_frontier
        self.assertEqual(self.reads, self.paths)
        self.assertEqual(report["files"][0]["source_evidence"]["text"].encode(), self.raw)
        self.assertIn("not_read_byte_limit", [row["status"] for row in report["files"]])
        self.assertEqual(report["bytes_read"], len(self.raw) + ((524288 - len(self.raw)) // 262144) * 262144)
        self.assertEqual(self.admission.budget["bytes"], 123 + report["bytes_read"])
        self.assertEqual(report["status"], "partial")
        self.assertEqual(
            report["limits"],
            dict(seconds=5, file_bytes=262144, total_bytes=4194304, report_bytes=1048576, imports=512),
        )
        self.assertLessEqual(len(json.dumps(report, sort_keys=True).encode()), 1048576)
        self.assertEqual(self.admission.guard.forbidden, dict(runtime=0, blocked_import=1))

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


class InitializationMetadataPages(unittest.TestCase):
    """UNITONLY frozen candidate pages; no runtime or discovery completeness."""

    def selection(self):
        names = {n.name for n in ast.parse(HARNESS.read_text()).body if isinstance(n, ast.FunctionDef)}
        self.assertIn("initialization_metadata_page_selection", names, "finite page selection missing")
        return isolated(HARNESS, {"initialization_metadata_page_selection"})["initialization_metadata_page_selection"]

    def port(self, page="EP-A"):
        port = InitializationDependencyFrontier()
        port.setUp()
        functions = {n.name for n in ast.parse(HARNESS.read_text()).body
                     if isinstance(n, ast.FunctionDef) and n.name.startswith("initialization_metadata_page_")}
        self.assertIn("initialization_metadata_page_capture", functions, "bounded page collector missing")
        exec(compile(ast.Module(body=[n for n in ast.parse(HARNESS.read_text()).body
            if isinstance(n, ast.FunctionDef) and n.name in functions], type_ignores=[]), str(HARNESS), "exec"), port.ns)
        port.ns["INITIALIZATION_METADATA_PAGE"] = page
        selection = port.ns["initialization_metadata_page_selection"](page)
        port.ns["sys"].path = list(selection["sys_path"])
        port.paths = selection["sources"]
        port.metadata_paths = selection["paths"]
        port.scans = []

        def inventory(path, budget):
            import stat
            port.scans.append(path)
            children = sorted({p[len(path)+1:].split("/")[0]
                               for p in selection["paths"] if p.startswith(path + "/")})
            budget["entries"] += len(children)
            assert budget["entries"] <= budget["entry_limit"]
            return dict(path=path, device=1, inode=1, mode=stat.S_IFDIR, entries=[dict(
                name=name, scan_index=i, mode=stat.S_IFDIR if name.endswith(".dist-info") else stat.S_IFREG,
                size=len(port.raw), links=1, device=1, inode=i+2) for i, name in enumerate(children)])

        port.ns["initialization_directory_inventory"] = inventory
        return port

    def test_selected_page_raw_capture_only_and_original_refusal(self):
        import hashlib
        import json

        for page in ("EP-A", "EP-B", "DIST"):
            with self.subTest(page=page):
                port = self.port(page)
                port.raw = b"malformed unparsed metadata\n[torch.backends]\na = never_execute:target\n"
                port.trigger()
                report = port.admission.dependency_frontier
                self.assertEqual(report["requested_manifest"], port.paths)
                boundary = report["boundary"]
                self.assertEqual(port.reads, port.metadata_paths + port.paths)
                self.assertEqual([r["path"] for r in boundary["metadata"]], port.metadata_paths)
                self.assertEqual(boundary["metadata_files"], len(port.metadata_paths))
                self.assertTrue(boundary["page"]["page_content_complete"])
                self.assertFalse(boundary["metadata_complete"])
                self.assertFalse(boundary["distributions_complete"])
                self.assertIsNone(boundary["torch_backends"])
                self.assertEqual(boundary["plugins"], [])
                self.assertEqual(boundary["native"], [])
                self.assertFalse(boundary["native_complete"])
                for row in boundary["metadata"]:
                    self.assertEqual(row["status"], "observed")
                    self.assertEqual(row["text"].encode(), port.raw)
                    self.assertEqual(row["witness"]["sha256"], hashlib.sha256(port.raw).hexdigest())
                    self.assertEqual(row["parse_status"], "not_parsed")
                self.assertEqual(report["bytes_read"], len(port.raw) * len(port.reads))
                self.assertEqual(port.admission.budget["bytes"], 123 + report["bytes_read"])
                self.assertLessEqual(len(json.dumps(report, sort_keys=True).encode()), 1048576)
                self.assertEqual(report["status"], "partial")
                prior = list(port.reads)
                port.trigger()
                self.assertEqual(port.reads, prior)
                self.assertEqual(port.admission.guard.forbidden["blocked_import"], 2)

    def test_metadata_dispositions_are_distinct_and_never_positive(self):
        import stat

        cases = {"missing": "not_read_missing", "empty": "empty_stat_only_unread",
                 "link": "not_read_link", "oversize": "not_read_oversize",
                 "bytes": "not_read_byte_limit", "permission": "not_read_permission",
                 "decode": "read_decode_error", "error": "not_read_error"}
        for case, expected in cases.items():
            with self.subTest(case=case):
                port = self.port()
                original = port.ns["initialization_directory_inventory"]
                target = port.metadata_paths[0]
                def inventory(path, budget):
                    result = original(path, budget)
                    if path == target.rpartition("/")[0]:
                        if case == "missing":
                            result["entries"] = []
                        elif case == "empty":
                            result["entries"][0]["size"] = 0
                        elif case == "link":
                            result["entries"][0]["mode"] = stat.S_IFLNK
                    return result
                def reader(path, budget, **kwargs):
                    if path == target:
                        if case == "oversize":
                            raise AssertionError("S2 physical per-file ceiling")
                        if case == "bytes":
                            raise AssertionError("S2 physical read ceiling")
                        if case == "permission":
                            raise PermissionError("UNITONLY")
                        if case == "error":
                            raise OSError("UNITONLY")
                        if case == "decode":
                            raw = port.raw
                            port.raw = b"\xff\xfe"
                            try:
                                return port.reader(path, budget, **kwargs)
                            finally:
                                port.raw = raw
                    return port.reader(path, budget, **kwargs)
                port.ns.update(initialization_directory_inventory=inventory, initialization_physical_file=reader)
                port.trigger()
                b = port.admission.dependency_frontier["boundary"]
                self.assertEqual(b["metadata"][0]["status"], expected)
                self.assertFalse(b["page"]["page_content_complete"])
                self.assertFalse(b["metadata_complete"])
                self.assertIsNone(b["torch_backends"])
                if case == "decode":
                    self.assertEqual(b["metadata"][0]["raw_hex"], "fffe")
                    self.assertIsNone(b["metadata"][0]["text"])

    def test_new_scan_charges_survive_limit_restoration(self):
        port = self.port()
        port.admission.budget.pop("entries")
        port.trigger()
        report = port.admission.dependency_frontier
        self.assertGreater(report["entries"], 0)
        self.assertEqual(port.admission.budget.get("entries"), report["entries"], "scan counters refunded")
        self.assertEqual(port.admission.budget["files"], 2)
        self.assertNotIn("file_limit", port.admission.budget)

    def test_actual_readers_share_source_metadata_role_and_output_ceilings(self):
        import hashlib
        import json
        import os
        import stat
        import tempfile
        from types import SimpleNamespace

        for case in ("all-pages", "role", "file", "total", "encoded", "entries", "deadline"):
            for page in (("EP-A", "EP-B", "DIST") if case == "all-pages" else ("EP-A",)):
                with self.subTest(case=case, page=page), tempfile.TemporaryDirectory() as tmp:
                    port = self.port(page)
                    raw = b"x" * (262145 if case == "file" else 262144 if case == "total" else 200000 if case == "encoded" else 29)
                    if case == "encoded":
                        raw = b"\x00" * len(raw)
                    for origin in port.metadata_paths + port.paths:
                        target = pathlib.Path(tmp, origin.lstrip("/"))
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(raw)
                    for origin in port.ns["sys"].path[:2]:
                        pathlib.Path(tmp, origin.lstrip("/")).mkdir(parents=True, exist_ok=True)
                    helpers = isolated(HARNESS, {"initialization_physical_file", "initialization_directory_inventory"})
                    projected = SimpleNamespace(**{k: getattr(os, k) for k in dir(os)})
                    projected.fstatvfs = lambda fd: SimpleNamespace(f_flag=os.ST_RDONLY)
                    helpers.update(os=projected, stat=stat, hashlib=hashlib, time=port.ns["time"])
                    def reader(path, budget, **kwargs):
                        self.assertIn(path, port.metadata_paths + port.paths, "unselected content read")
                        self.assertLessEqual(budget["byte_limit"], 123 + 4194304)
                        self.assertLessEqual(budget["file_limit"], 262144)
                        self.assertLessEqual(budget["deadline"], port.clock + 5)
                        port.reads.append(path)
                        return helpers["initialization_physical_file"](str(pathlib.Path(tmp, path.lstrip("/"))), budget, **kwargs)
                    def inventory(path, budget):
                        port.scans.append(path)
                        result = helpers["initialization_directory_inventory"](str(pathlib.Path(tmp, path.lstrip("/"))), budget)
                        if case == "deadline":
                            port.clock += 6
                        return result
                    port.ns.update(initialization_physical_file=reader, initialization_directory_inventory=inventory)
                    if case == "role":
                        port.admission.budget["byte_limit"] = 123 + len(raw) * (len(port.metadata_paths) + 1)
                    if case == "entries":
                        port.admission.budget.update(entries=4095, entry_limit=4096)
                    before = dict(port.admission.budget)
                    port.trigger()
                    report = port.admission.dependency_frontier
                    b = report["boundary"]
                    self.assertLessEqual(report["bytes_read"], 4194304)
                    self.assertLessEqual(port.admission.budget["bytes"], before["byte_limit"])
                    self.assertLessEqual(report["entries"], 4096)
                    self.assertLessEqual(len(b["directories"]), 512)
                    self.assertLessEqual(b["metadata_files"], 32)
                    self.assertLessEqual(len(json.dumps(report, sort_keys=True).encode()), 1048576)
                    self.assertEqual(port.admission.budget["bytes"], 123 + report["bytes_read"])
                    self.assertEqual(port.admission.budget["entries"], report["entries"])
                    self.assertEqual(port.admission.budget["byte_limit"], before["byte_limit"])
                    self.assertEqual(port.admission.budget["deadline"], before["deadline"])
                    self.assertFalse(b["metadata_complete"])
                    self.assertIsNone(b["torch_backends"])
                    if case == "all-pages":
                        self.assertTrue(b["page"]["page_content_complete"])
                        self.assertEqual(report["bytes_read"], len(raw) * (len(port.metadata_paths) + len(port.paths)))
                        self.assertTrue(report["source_capture_complete"])
                    elif case == "role":
                        self.assertTrue(b["page"]["page_content_complete"])
                        self.assertEqual(report["bytes_read"], len(raw) * (len(port.metadata_paths) + 1))
                        self.assertFalse(report["source_capture_complete"])
                    else:
                        self.assertFalse(b["page"]["page_content_complete"])

    def test_selector_tamper_misbound_context_and_reentry_read_nothing(self):
        select = self.selection()
        tree = ast.parse(HARNESS.read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == select.__name__)
        for node in ast.walk(fn):
            if isinstance(node, ast.Constant) and node.value == select("EP-A")["paths"][0]:
                node.value = "/etc/arbitrary/entry_points.txt"
        ns = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(HARNESS), "exec"), ns)
        with self.assertRaisesRegex(AssertionError, "membership changed"):
            ns[select.__name__]("EP-A")
        for drift in ("path", "path_object", "image", "provision", "page"):
            with self.subTest(drift=drift):
                port = self.port()
                if drift == "path":
                    port.ns["sys"].path.reverse()
                elif drift == "path_object":
                    port.ns["sys"].path[0] = object()
                elif drift == "image":
                    port.admission.runner.GRAPHQL_IMAGE = "sha256:wrong"
                elif drift == "provision":
                    port.admission.runner.GRAPHQL_MANIFEST_SHA256 = "wrong"
                else:
                    port.ns["INITIALIZATION_METADATA_PAGE"] = "ALL"
                port.trigger()
                self.assertEqual(port.reads, [])
                self.assertEqual(port.scans, [])
                self.assertTrue(port.admission.dependency_frontier_started)
        port = self.port()
        port.trigger()
        before = (list(port.reads), list(port.scans), dict(port.admission.budget))
        for page in ("EP-A", "EP-B", "DIST"):
            with self.assertRaisesRegex(AssertionError, "already consumed"):
                port.ns["initialization_metadata_page_capture"](port.admission,
                    port.admission.dependency_frontier, port.admission.budget, None, None, page=page)
        self.assertEqual((port.reads, port.scans, port.admission.budget), before)

    def test_opaque_providers_are_never_queried_and_drift_is_not_complete(self):
        for drift in (None, "path", "finder", "hook"):
            with self.subTest(drift=drift):
                port = self.port()
                calls = []
                class Opaque:
                    def __getattribute__(self, name):
                        calls.append(name)
                        raise AssertionError("provider attribute executed")
                    def __eq__(self, other):
                        calls.append("eq")
                        raise AssertionError("provider equality executed")
                    def __hash__(self):
                        calls.append("hash")
                        raise AssertionError("provider hash executed")
                finder, hook = Opaque(), Opaque()
                port.ns["sys"].meta_path = [finder]
                port.ns["sys"].path_hooks = [hook]
                original = port.reader
                def reader(path, budget, **kwargs):
                    if path == port.metadata_paths[-1]:
                        if drift == "path":
                            port.ns["sys"].path.reverse()
                        elif drift == "finder":
                            port.ns["sys"].meta_path[:] = [Opaque()]
                        elif drift == "hook":
                            port.ns["sys"].path_hooks[:] = [Opaque()]
                    return original(path, budget, **kwargs)
                port.ns["initialization_physical_file"] = reader
                port.trigger()
                b = port.admission.dependency_frontier["boundary"]
                self.assertEqual(calls, [])
                self.assertEqual(b["finders"][0]["object_id"], id(finder))
                self.assertEqual(b["page"]["page_content_complete"], drift is None)
                self.assertFalse(b["page"]["discovery_complete"])
                self.assertFalse(b["page"]["resolver_order_equivalent"])

    def test_production_seam_is_one_literal_page_without_legacy_or_write_calls(self):
        tree = ast.parse(HARNESS.read_text())
        selected = [n for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "INITIALIZATION_METADATA_PAGE" for t in n.targets)]
        self.assertEqual(len(selected), 1)
        self.assertEqual(ast.literal_eval(selected[0].value), "DIST")
        probe = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "registration_metadata_probe")
        frontier = next(n for n in probe.body if isinstance(n, ast.FunctionDef) and n.name == "dependency_frontier")
        helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("initialization_metadata_page_")]
        calls = [n for block in [frontier] + helpers for n in ast.walk(block) if isinstance(n, ast.Call)]
        names = [n.func.id for n in calls if isinstance(n.func, ast.Name)]
        self.assertEqual(names.count("initialization_metadata_page_capture"), 1)
        self.assertTrue({"initialization_boundary_inventory", "initialization_boundary_native", "open", "exec", "eval",
                         "__import__", "entry_points", "distribution"}.isdisjoint(names))
        attrs = {n.func.attr for n in calls if isinstance(n.func, ast.Attribute)}
        self.assertTrue({"find_distributions", "find_spec", "load", "write", "write_bytes", "write_text", "getenv"}.isdisjoint(attrs))
        select = self.selection()
        expected = ["/isaac-sim/kit/python/lib/python3.12/importlib/metadata/" + name
                    for name in ("_collections.py", "_itertools.py", "_functools.py", "_adapters.py")]
        self.assertEqual(select("EP-A")["sources"], expected)
        self.assertEqual(select("EP-B")["sources"], [])
        self.assertEqual(select("DIST")["sources"], [])

    def test_exact_frozen_table_and_strict_enum(self):
        import hashlib
        import json

        manifest = ROOT / "outputs/workflow/plan04-implementation/s2-initialization/autonomous-continuation/resumption/observed-boundary-packet/metadata-page-membership.json"
        raw = manifest.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "847811bdcb4f4bdfa10ad0051cd3c4b603a35f429c68fdaa9f2ff3f302fa0613")
        expected = json.loads(raw)
        select = self.selection()
        for page, count in zip(expected["pages"], (32, 23, 25)):
            actual = select(page["name"])
            self.assertEqual(actual["paths"], page["paths"])
            self.assertEqual(actual["membership_sha256"], page["membership_sha256"])
            self.assertEqual(len(actual["paths"]), count)
            self.assertEqual(actual["sys_path"], expected["sys_path"])
            for key in ("image", "provision_manifest_sha256", "role_leaf_sha256", "run"):
                self.assertEqual(actual[key], expected[key])
            self.assertEqual(len(actual["sources"]), 4 if page["name"] == "EP-A" else 0)
        for invalid in (None, [], {}, "EP-A/../EP-B", "ep-a", "", "ALL"):
            with self.subTest(invalid=invalid), self.assertRaises(AssertionError):
                select(invalid)


class InitializationResidualPacket(unittest.TestCase):
    """UNITONLY residual selection; retained observations are never recaptured."""

    def test_native_facts_survive_later_directory_entry_time_and_json_exhaustion(self):
        import json
        import stat

        for failure in ("directories", "entries", "deadline", "json", "gmp"):
            with self.subTest(failure=failure):
                port = InitializationDependencyFrontier()
                port.setUp()
                port.ns["sys"].path = [f"/root{i}" for i in range(20)] if failure == "directories" else [port.p]
                seen = []
                first = port.p + "/torch/lib"

                def inventory(path, budget):
                    seen.append(path)
                    if path == first:
                        budget["entries"] += 1
                        return dict(path=path, device=1, inode=1, entries=[dict(
                            name="libtorch_global_deps.so", scan_index=0, mode=stat.S_IFREG,
                            size=37, links=1, device=1, inode=2)])
                    if path.endswith("/nvidia/cublas/lib"):
                        if failure == "entries":
                            budget["entries"] = 4096
                            raise AssertionError("S2 inventory entry ceiling")
                        if failure == "deadline":
                            port.clock += 6
                            raise TimeoutError()
                        if failure == "json":
                            budget["entries"] = 4096
                            return dict(path=path, entries=[dict(name="x" * 255, scan_index=i,
                                mode=stat.S_IFREG, size=1, links=1, device=1, inode=i+3) for i in range(4095)])
                    if failure == "entries" and budget["entries"] == 4096:
                        raise AssertionError("S2 inventory entry ceiling")
                    if failure == "gmp" and path == port.p:
                        port.clock += 6
                        raise TimeoutError()
                    raise FileNotFoundError(path)

                port.ns["initialization_directory_inventory"] = inventory
                port.trigger()
                report = port.admission.dependency_frontier
                boundary = report["boundary"]
                self.assertEqual(boundary["native"][0]["status"], "observed")
                self.assertEqual(boundary["native"][0]["candidates"][0]["size"], 37)
                self.assertEqual(boundary["projection"]["identities"][0]["projected_minimum_read_bytes"], 37)
                self.assertEqual(boundary["native_complete"], failure == "gmp")
                self.assertFalse(boundary["projection"]["complete"])
                self.assertFalse(boundary["metadata_complete"])
                self.assertIsNone(boundary["torch_backends"])
                self.assertLessEqual(len(boundary["directories"]), 512)
                self.assertLessEqual(report["entries"], 4096)
                self.assertLessEqual(len(json.dumps(report, sort_keys=True).encode()), 1048576)
                self.assertEqual(boundary["metadata_files"], 0)
                self.assertEqual(report["limits"], dict(seconds=5, file_bytes=262144,
                    total_bytes=4194304, report_bytes=1048576, imports=512))
                self.assertEqual(boundary["limits"], dict(metadata_files=32, entries_per_directory=4096,
                    entries_total=4096, directories=512, paths=128))
                self.assertEqual(port.admission.guard.forbidden, dict(runtime=0, blocked_import=1))
                self.assertTrue(port.admission.dependency_frontier_started)
                if failure == "directories":
                    self.assertEqual(len(boundary["directories"]), 512)
                    self.assertEqual(len(seen), 512)

    def test_residual_native_refused_precedence_does_not_select_later_path(self):
        import stat

        port = InitializationDependencyFrontier()
        port.setUp()
        port.ns["sys"].path = ["/earlier", "/later"]

        def inventory(path, budget):
            if path == "/earlier/nvidia/cublas/lib":
                raise AssertionError("UNITONLY earlier symlink refused")
            if path == "/later/nvidia/cublas/lib":
                budget["entries"] += 1
                return dict(path=path, entries=[dict(name="libcublas.so.1", scan_index=0,
                    mode=stat.S_IFREG, size=10, links=1, device=1, inode=2)])
            raise FileNotFoundError(path)

        port.ns["initialization_directory_inventory"] = inventory
        port.trigger()
        boundary = port.admission.dependency_frontier["boundary"]
        cuda = boundary["native"][8]
        self.assertEqual(cuda["status"], "unresolved_precedence")
        self.assertIsNone(cuda["winner"])
        self.assertEqual(len(cuda["searches"]), 6, "exhaustive table semantics changed")
        self.assertEqual(cuda["candidates"][0]["path_index"], 1)
        self.assertFalse(boundary["native_complete"])

    def test_existing_entry_budget_is_charged_not_restored(self):
        port = InitializationDependencyFrontier()
        port.setUp()
        port.admission.budget.update(entries=11, entry_limit=100)

        def inventory(path, budget):
            if path == port.p + "/torch/lib":
                budget["entries"] += 3
            raise FileNotFoundError(path)

        port.ns["initialization_directory_inventory"] = inventory
        port.trigger()
        self.assertEqual(port.admission.dependency_frontier["entries"], 14)
        self.assertEqual(port.admission.budget["entries"], 14, "physical scan charges were reset")
        self.assertEqual(port.admission.budget["entry_limit"], 100)
        self.assertEqual(port.admission.budget["files"], 2)

    def test_fixed_gmp_origins_are_physical_and_not_global_availability(self):
        import stat

        port = InitializationDependencyFrontier()
        port.setUp()
        p = port.p
        seen = []
        roots = [p,
            "/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle",
            "/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle"]

        def inventory(path, budget):
            seen.append(path)
            leaves = (["gmpy2.cpython-312-x86_64-linux-gnu.so"] if path == p else
                      ["gmpy"] if path == roots[-1] else
                      ["__init__.py"] if path == roots[-1] + "/gmpy" else [])
            budget["entries"] += len(leaves)
            return dict(path=path, device=1, inode=1, entries=[dict(
                name=name, scan_index=i, mode=stat.S_IFDIR if name == "gmpy" else stat.S_IFREG,
                size=9, links=1, device=1, inode=i+2) for i, name in enumerate(leaves)])

        port.ns["initialization_directory_inventory"] = inventory
        port.trigger()
        boundary = port.admission.dependency_frontier["boundary"]
        self.assertEqual(len(boundary.get("gmp_backends", [])), 2, "fixed physical GMP origins not observed")
        for row in boundary["gmp_backends"]:
            self.assertEqual(row["roots"], roots)
            self.assertEqual(row["status"], "present_requires_review")
            self.assertIsNone(row["global_availability"])
            self.assertFalse(row["admitted"])
            self.assertEqual(len(row["origins"]), 1)
            self.assertNotIn("sha256", row["origins"][0])
        self.assertEqual(port.reads, port.paths)
        self.assertEqual([seen.count(root) for root in roots], [1, 1, 1])
        self.assertEqual(boundary["metadata_files"], 0)

    def test_residual_provider_snapshot_is_identity_based_and_rechecked(self):
        for drift in (None, "finder", "hook", "path"):
            with self.subTest(drift=drift):
                port = InitializationDependencyFrontier()
                port.setUp()
                calls = []

                class Opaque:
                    def __getattribute__(self, name):
                        calls.append(name)
                        raise AssertionError("provider attributes must not execute")

                    def __eq__(self, other):
                        calls.append("eq")
                        raise AssertionError("provider equality must not execute")

                finder, hook = Opaque(), Opaque()
                port.ns["sys"].meta_path = [port.admission, finder]
                port.ns["sys"].path_hooks = [hook]
                port.ns["sys"].path = [port.p]

                def inventory(path, budget):
                    if path.endswith("/nvtx/lib"):
                        if drift == "finder":
                            port.ns["sys"].meta_path[-1] = Opaque()
                        elif drift == "hook":
                            port.ns["sys"].path_hooks[-1] = Opaque()
                        elif drift == "path":
                            port.ns["sys"].path[:] = ["/changed"]
                    raise FileNotFoundError(path)

                port.ns["initialization_directory_inventory"] = inventory
                port.trigger()
                boundary = port.admission.dependency_frontier["boundary"]
                self.assertEqual(calls, [])
                self.assertEqual(boundary.get("finders_stable"), drift != "finder")
                self.assertEqual(boundary.get("path_hooks_stable"), drift != "hook")
                self.assertEqual(boundary["path_stable"], drift != "path")
                self.assertEqual(boundary["finders"][-1]["identity"], "opaque_unsupported")
                self.assertEqual(boundary["finders"][-1]["object_id"], id(finder))
                self.assertTrue(boundary["native_complete"])
                self.assertFalse(boundary["metadata_complete"])
                self.assertIsNone(boundary["torch_backends"])

    def test_context_survives_optional_ast_exhaustion(self):
        from unittest.mock import patch

        port = InitializationDependencyFrontier()
        port.setUp()
        walk = ast.walk

        def costly_walk(tree):
            for node in walk(tree):
                port.clock += 6
                yield node

        with patch.object(ast, "walk", costly_walk):
            port.trigger()
        report = port.admission.dependency_frontier
        self.assertTrue(report["baseline_complete"], "optional AST starved baseline context")
        self.assertEqual(report["baseline"], port.admission.baseline)
        self.assertTrue(report["module_origins_complete"])
        self.assertTrue(report["source_capture_complete"])
        self.assertTrue(report["boundary"]["native_complete"])
        self.assertFalse(report["imports_complete"])
        self.assertTrue(report["deadline_exhausted"])
        self.assertFalse(report["boundary"]["metadata_complete"])

    def test_exact_zip_entry_uses_nofollow_parent_witness(self):
        import os
        import stat
        import tempfile
        from types import SimpleNamespace

        for form in ("absent", "present", "link", "directory", "parent_link", "parent_missing"):
            with self.subTest(form=form), tempfile.TemporaryDirectory() as temporary:
                port = InitializationDependencyFrontier()
                port.setUp()
                exact = "/isaac-sim/kit/python/lib/python312.zip"
                parent = pathlib.Path(temporary, "lib")
                parent.mkdir()
                leaf = parent / "python312.zip"
                if form == "present":
                    leaf.write_bytes(b"UNITONLY-not-an-executable-archive")
                elif form == "link":
                    leaf.symlink_to("unknown")
                elif form == "directory":
                    leaf.mkdir()
                elif form == "parent_link":
                    parent.rmdir()
                    parent.symlink_to(temporary)
                elif form == "parent_missing":
                    parent.rmdir()
                fn = isolated(HARNESS, {"initialization_directory_inventory"})["initialization_directory_inventory"]
                projected = SimpleNamespace(**{k: getattr(os, k) for k in dir(os)})
                projected.fstatvfs = lambda fd: SimpleNamespace(f_flag=os.ST_RDONLY)
                fn.__globals__.update(os=projected, stat=stat, time=port.ns["time"])
                calls = []

                def inventory(path, budget):
                    calls.append(path)
                    if path == exact.rpartition("/")[0]:
                        return fn(str(parent), budget)
                    raise FileNotFoundError(path)

                port.ns["sys"].path = [exact]
                port.ns["initialization_directory_inventory"] = inventory
                port.trigger()
                boundary = port.admission.dependency_frontier["boundary"]
                self.assertIn("zip_path", boundary, "no exact physical zip observation")
                row = boundary["zip_path"]
                self.assertEqual(row["path"], exact)
                expected = {"absent": "absent", "present": "present_regular", "link": "link"}.get(form, "unresolved")
                self.assertEqual(row["status"], expected)
                self.assertIn(exact.rpartition("/")[0], calls)
                self.assertFalse(any(path == exact for path in calls))
                self.assertFalse(boundary["metadata_complete"])
                self.assertIsNone(boundary["torch_backends"])
                self.assertEqual(port.reads, port.paths)
                if form in {"present", "link", "directory"}:
                    self.assertEqual(row["entry"]["name"], "python312.zip")
                    self.assertIn("scan_index", row["entry"])

    def test_native_priority_excludes_exhausted_metadata_sweep(self):
        import stat

        port = InitializationDependencyFrontier()
        port.setUp()
        port.ns["sys"].path = [port.p]
        events = []

        def inventory(path, budget):
            events.append(("stat", path))
            self.assertIs(budget, port.admission.budget)
            self.assertEqual(budget["entry_limit"], 4096)
            self.assertLessEqual(budget["deadline"], port.clock + 5)
            self.assertFalse(path.endswith(".dist-info"), "repeated exhausted distribution sweep")
            leaves = ([f"old_{i}.dist-info" for i in range(334)] if path == port.p else
                      ["libtorch_global_deps.so"] if path == port.p + "/torch/lib" else [])
            budget["entries"] += len(leaves)
            return dict(path=path, device=1, inode=1, entries=[dict(
                name=name, scan_index=i, mode=stat.S_IFDIR if name.endswith(".dist-info") else stat.S_IFREG,
                size=10, device=1, inode=i+2, links=1) for i, name in enumerate(leaves)])

        def reader(path, budget, **kwargs):
            events.append(("read", path))
            self.assertIn(path, port.paths, "old source or metadata recaptured")
            return port.reader(path, budget, **kwargs)

        port.ns.update(initialization_directory_inventory=inventory, initialization_physical_file=reader)
        port.trigger()
        report = port.admission.dependency_frontier
        boundary = report["boundary"]
        self.assertEqual(boundary["metadata_files"], 0)
        self.assertEqual(boundary.get("metadata_selection"), "not_selected_residual_packet")
        self.assertFalse(boundary["metadata_complete"])
        self.assertIsNone(boundary["torch_backends"])
        self.assertIsNone(boundary["gymnasium_plugins"])
        self.assertTrue(boundary["native_complete"], "native completion cannot depend on metadata")
        self.assertEqual([row["kind"] for row in boundary["native"][:8]], [
            "torch_global_deps", "torch_C", "torch_shm_manager", "numpy_core", "numpy_wheel_libs",
            "warp_core", "warp_llvm", "yaml_extension"])
        self.assertTrue(all(row["kind"] == "torch_cuda_preload" for row in boundary["native"][8:]))
        self.assertEqual(len(boundary["native"]), 24)
        self.assertEqual(events[0], ("stat", port.p + "/torch/lib"), "fixed native facts have first I/O priority")
        self.assertLess(events.index(("stat", port.p + "/torch/lib")), events.index(("read", port.paths[0])))
        self.assertLess(events.index(("stat", port.p + "/numpy")),
                        events.index(("stat", port.p + "/nvidia/cublas/lib")))
        self.assertEqual(port.reads, port.paths)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["retained_evidence"]["status"], "retained-not-current")
        self.assertFalse(report["retained_evidence"]["coverage_joined"])
        self.assertTrue(all("retained-not-current" in row["rationale"] for row in boundary["native"]))


class InitializationProviderRecognition(unittest.TestCase):
    """UNITONLY bootstrap fixtures; never execute captured six/package source."""

    def setUp(self):
        import types

        self.port = InitializationDependencyFrontier()
        self.port.setUp()
        self.ns = self.port.ns
        self.six = types.ModuleType("six")
        self.origin = "/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle/six.py"
        self.digest = "c51c91f703d3d4b3696c923cb5fec213e05e75d9215393befac7f2fa6a3904df"
        # Synthetic shape only: none of these sentinel methods may be called.
        exec("""
class _SixMetaPathImporter(object):
    def __init__(self, name):
        self.name = name
        self.known_modules = {}
    def _add_module(self, *args): raise AssertionError('provider called')
    def _get_module(self, *args): raise AssertionError('provider called')
    def find_module(self, *args): raise AssertionError('provider called')
    def find_spec(self, *args): raise AssertionError('provider called')
    def __get_module(self, *args): raise AssertionError('provider called')
    def load_module(self, *args): raise AssertionError('provider called')
    def is_package(self, *args): raise AssertionError('provider called')
    def get_code(self, *args): raise AssertionError('provider called')
    get_source = get_code
    def create_module(self, *args): raise AssertionError('provider called')
    def exec_module(self, *args): raise AssertionError('provider called')
_importer = _SixMetaPathImporter('six')
""", self.six.__dict__)
        self.six.__file__ = self.origin
        self.finder = self.six._importer
        self.runner = types.ModuleType("joined_runner")
        installer = isolated(ROOT / "scripts/run-workflow-neo4j-checks.py", {"install_staged_import_guard"})
        self.runner.__dict__.update(installer)
        self.runner.__dict__.update(Path=pathlib.Path, sys=types.SimpleNamespace(modules={}, meta_path=[]))
        # Rebind the AST-isolated trusted installer to this exact bootstrap namespace.
        fn = installer["install_staged_import_guard"]
        self.runner.install_staged_import_guard = types.FunctionType(fn.__code__, self.runner.__dict__)
        row = dict(file=self.origin, path=self.origin, physical=self.origin, origin=self.origin,
                   sha256=self.digest, size=34703, links=[])
        self.runner._GRAPHQL_PROBE = {"result": {"status": "passed", "loaded_modules": {"six": row}}}
        self.sources = {"scripts/run-workflow-neo4j-checks.py":
                        "232790f2e4aae824c6e809fc1930965feed3baa47365db4a5c1ebd996fdbe20d",
                        "unit/__init__.py": "1" * 64, "unit/child.py": "2" * 64}
        import sys

        self.ns["sys"].modules = dict(sys.modules, six=self.six)

    def bootstrap(self):
        self.assertIn("initialization_boundary_provider_bootstrap", self.ns,
                      "source-bound bootstrap recognizer is missing")
        return self.ns["initialization_boundary_provider_bootstrap"](self.runner, self.sources)

    def recognize(self, state, finder=None):
        return self.ns["initialization_boundary_provider_recognize"](state, self.finder if finder is None else finder)

    def test_exact_preloaded_six_is_diagnostic_nonparticipant(self):
        state = self.bootstrap()
        self.assertEqual(self.recognize(state), "six._SixMetaPathImporter[metadata_nonparticipant]")
        self.assertIsNone(self.recognize(state, object()))


    def test_exact_staged_return_is_diagnostic_nonparticipant(self):
        state = self.bootstrap()
        closure = {"files": ["unit/__init__.py", "unit/child.py"], "namespaces": ["unit"]}
        finder = self.runner.install_staged_import_guard("/source", closure["files"], closure["namespaces"])
        self.assertIn("initialization_boundary_provider_staged", self.ns,
                      "installer-return anchor is missing")
        self.ns["initialization_boundary_provider_staged"](state, finder, closure)
        self.assertEqual(self.recognize(state, finder), "StagedFinder[metadata_nonparticipant]")
        # A second genuine factory product is not the retained installer return.
        other = self.runner.install_staged_import_guard("/source", closure["files"], closure["namespaces"])
        self.assertIsNone(self.recognize(state, other))


    def test_bootstrap_and_time_of_use_memberships_fail_closed(self):
        for mutation in ("witness_hash", "witness_link", "source", "known_modules", "method_defaults", "namespace"):
            with self.subTest(mutation=mutation):
                self.setUp()
                state = self.bootstrap()
                self.assertIsNotNone(self.recognize(state))
                if mutation == "witness_hash":
                    self.runner._GRAPHQL_PROBE["result"]["loaded_modules"]["six"]["sha256"] = "0" * 64
                elif mutation == "witness_link":
                    self.runner._GRAPHQL_PROBE["result"]["loaded_modules"]["six"]["links"].append("link")
                elif mutation == "source":
                    self.sources["scripts/run-workflow-neo4j-checks.py"] = "0" * 64
                elif mutation == "known_modules":
                    self.finder.known_modules["six.moves.new"] = object()
                elif mutation == "method_defaults":
                    type(self.finder).find_spec.__kwdefaults__ = {"find_distributions": object()}
                else:
                    self.six.__dict__["new_global"] = object()
                self.assertIsNone(self.recognize(state), mutation)

    def test_staged_closure_membership_and_installer_mutation_fail_closed(self):
        for mutation in ("modules", "namespaces", "packages", "closure_cell", "source_files", "installer_code"):
            with self.subTest(mutation=mutation):
                self.setUp()
                state = self.bootstrap()
                closure = {"files": ["unit/__init__.py"], "namespaces": ["unit"]}
                finder = self.runner.install_staged_import_guard("/source", closure["files"], closure["namespaces"])
                self.ns["initialization_boundary_provider_staged"](state, finder, closure)
                self.assertIsNotNone(self.recognize(state, finder))
                fn = type(finder).find_spec
                cells = dict(zip(fn.__code__.co_freevars, fn.__closure__))
                if mutation == "modules":
                    cells["modules"].cell_contents["extra"] = pathlib.Path("/source/extra.py")
                elif mutation == "namespaces":
                    closure["namespaces"].append("extra")
                elif mutation == "packages":
                    cells["packages"].cell_contents.add("extra")
                elif mutation == "closure_cell":
                    cells["root"].cell_contents = object()
                elif mutation == "source_files":
                    closure["files"].append("extra.py")
                else:
                    self.runner.install_staged_import_guard.__code__ = (lambda: None).__code__
                self.assertIsNone(self.recognize(state, finder), mutation)

    def test_safe_shape_rejects_injected_resolvers_hooks_descriptors(self):
        calls = []

        class Descriptor:
            def __get__(self, *args):
                calls.append("descriptor")
                raise AssertionError("descriptor executed")

        for key, value in (("find_distributions", Descriptor()), ("__getattr__", lambda *args: calls.append("getattr")),
                           ("__getattribute__", lambda *args: calls.append("getattribute")),
                           ("__dict__", Descriptor())):
            for early in (False, True):
                with self.subTest(key=key, early=early):
                    self.setUp()
                    state = None if early else self.bootstrap()
                    if key == "__dict__":
                        members = dict(type(self.finder).__dict__)
                        members.pop("__dict__")
                        members.pop("__weakref__")
                        members[key] = value
                        cls = type("_SixMetaPathImporter", (), members)
                        self.finder.__class__ = cls
                        self.six.__dict__["_SixMetaPathImporter"] = cls
                    else:
                        setattr(type(self.finder), key, value)
                    state = self.bootstrap() if early else state
                    self.assertIsNone(self.recognize(state))
        self.assertEqual(calls, [])

    def test_instance_resolver_and_poison_keys_are_never_looked_up(self):
        calls = []

        class Poison:
            def __hash__(self):
                return hash("find_distributions")

            def __eq__(self, other):
                calls.append("equality")
                raise AssertionError("poison key compared")

        for location in ("instance", "module", "known_modules"):
            with self.subTest(location=location):
                self.setUp()
                state = self.bootstrap()
                namespace = {"instance": self.finder.__dict__, "module": self.six.__dict__,
                             "known_modules": self.finder.known_modules}[location]
                namespace[Poison()] = object()
                self.assertIsNone(self.recognize(state))
        self.setUp()
        state = self.bootstrap()
        self.finder.__dict__["find_distributions"] = object()
        self.assertIsNone(self.recognize(state))
        self.assertEqual(calls, [])

    def test_unknown_metaclass_class_attribute_and_equality_traps_remain_opaque(self):
        calls = []

        class Meta(type):
            def __getattribute__(self, key):
                calls.append("meta attribute")
                raise AssertionError(key)

            @property
            def __dict__(self):
                calls.append("meta dictionary descriptor")
                raise AssertionError("meta dictionary descriptor")

            @property
            def __mro__(self):
                calls.append("meta MRO descriptor")
                raise AssertionError("meta MRO descriptor")

            def __eq__(self, other):
                calls.append("meta equality")
                raise AssertionError("meta equality")

            __hash__ = None

        class Unknown(metaclass=Meta):
            def __getattribute__(self, key):
                calls.append("instance attribute")
                raise AssertionError(key)

            def __eq__(self, other):
                calls.append("instance equality")
                raise AssertionError("instance equality")

        state = self.bootstrap()
        self.assertIsNone(self.recognize(state, Unknown()))
        self.assertIsNone(self.recognize(state, Unknown))
        self.six.__dict__["_SixMetaPathImporter"] = Unknown
        self.six.__dict__["_importer"] = Unknown()
        state = self.bootstrap()
        self.assertIsNone(self.recognize(state, self.six.__dict__["_importer"]))
        self.assertEqual(calls, [])

    def test_equal_code_labels_replacements_and_mro_changes_are_not_identity(self):
        import types

        for mutation in ("same_code", "equal_code", "class", "module", "base"):
            with self.subTest(mutation=mutation):
                self.setUp()
                state = self.bootstrap()
                cls = type(self.finder)
                if mutation == "same_code":
                    fn = cls.find_spec
                    cls.find_spec = types.FunctionType(fn.__code__, self.six.__dict__, fn.__name__)
                elif mutation == "equal_code":
                    cls.find_spec.__code__ = cls.find_spec.__code__.replace()
                elif mutation == "class":
                    self.finder.__class__ = type("_SixMetaPathImporter", (), {})
                elif mutation == "module":
                    self.ns["sys"].modules["six"] = types.ModuleType("six")
                else:
                    class Base:
                        pass

                    class Derived(Base):
                        pass

                    self.finder.__class__ = Derived
                self.assertIsNone(self.recognize(state), mutation)


    def test_inventory_recognizes_only_anchors_and_retains_unknown_coverage(self):
        state = self.bootstrap()
        self.port.admission.provider_state = state
        self.ns["sys"].meta_path = [self.finder, object()]
        self.port.trigger()
        boundary = self.port.admission.dependency_frontier["boundary"]
        self.assertEqual([row["object_id"] for row in boundary["finders"]],
                         [id(finder) for finder in self.ns["sys"].meta_path])
        self.assertEqual(boundary["finders"][0]["identity"], "six._SixMetaPathImporter[metadata_nonparticipant]")
        self.assertEqual(boundary["finders"][1]["identity"], "opaque_unsupported")
        self.assertTrue(boundary["provider_shapes_stable"])
        self.assertFalse(boundary["metadata_complete"])
        self.assertIsNone(boundary["torch_backends"])

    def test_inventory_detects_shape_mutation_with_unchanged_finder_vector(self):
        self.port.admission.provider_state = self.bootstrap()
        self.ns["sys"].meta_path = [self.finder]

        def inventory(path, budget):
            self.finder.__dict__["find_distributions"] = object()
            raise FileNotFoundError(path)

        self.ns["initialization_directory_inventory"] = inventory
        self.port.trigger()
        boundary = self.port.admission.dependency_frontier["boundary"]
        self.assertTrue(boundary["finders_stable"])
        self.assertFalse(boundary.get("provider_shapes_stable", True), "shape mutation was not reconciled")
        self.assertFalse(boundary["metadata_complete"])

    def test_only_positive_child_retains_return_and_post_query_anchors(self):
        tree = ast.parse(HARNESS.read_text())
        child = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == "initialization_child")
        calls = [node for node in ast.walk(child) if isinstance(node, ast.Call)]
        admission = next(node for node in calls if isinstance(node.func, ast.Name)
                         and node.func.id == "InitializationAdmission")
        self.assertTrue(any(item.arg == "provider_sources" and isinstance(item.value, ast.Name)
                            and item.value.id == "manifest" for item in admission.keywords))
        retained = [node for node in ast.walk(child) if isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "install_staged_import_guard"]
        self.assertEqual(len(retained), 1)
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                   and node.name == "InitializationAdmission")
        init = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
        self.assertIn("initialization_boundary_provider_bootstrap", ast.unparse(init))
        self.assertIn("initialization_boundary_provider_staged", ast.unparse(child))


    def test_staged_rejects_mutation_before_return_anchor(self):
        for mutation in ("source", "files", "modules", "module_spec", "importlib", "root", "module_value"):
            with self.subTest(mutation=mutation):
                self.setUp()
                state = self.bootstrap()
                closure = {"files": ["unit/__init__.py"], "namespaces": ["unit"]}
                finder = self.runner.install_staged_import_guard("/source", closure["files"], closure["namespaces"])
                cells = dict(zip(type(finder).find_spec.__code__.co_freevars, type(finder).find_spec.__closure__))
                if mutation == "source":
                    self.sources["scripts/run-workflow-neo4j-checks.py"] = "0" * 64
                elif mutation == "files":
                    closure["files"].append("unverified.py")
                elif mutation == "modules":
                    cells["modules"].cell_contents["unverified"] = pathlib.Path("/source/unverified.py")
                elif mutation == "module_spec":
                    cells["ModuleSpec"].cell_contents = object()
                elif mutation == "root":
                    cells["root"].cell_contents = object()
                elif mutation == "module_value":
                    cells["modules"].cell_contents["unit"] = object()
                else:
                    cells["importlib"].cell_contents = object()
                self.ns["initialization_boundary_provider_staged"](state, finder, closure)
                self.assertIsNone(self.recognize(state, finder), mutation)

    def test_constructor_state_and_unverified_source_are_not_anchors(self):
        for mutation in ("source", "name", "known_modules", "missing_witness", "wrong_witness"):
            with self.subTest(mutation=mutation):
                self.setUp()
                if mutation == "source":
                    self.sources["scripts/run-workflow-neo4j-checks.py"] = "0" * 64
                elif mutation == "name":
                    self.finder.name = object()
                elif mutation == "known_modules":
                    self.finder.known_modules = object()
                elif mutation == "missing_witness":
                    self.runner._GRAPHQL_PROBE["result"]["loaded_modules"].clear()
                else:
                    self.runner._GRAPHQL_PROBE["result"]["loaded_modules"]["six"]["sha256"] = "0" * 64
                self.assertIsNone(self.recognize(self.bootstrap()), mutation)


    def test_metadata_page_uses_safe_recognizers_without_discovery_promotion(self):
        calls = []

        class Hostile:
            def __getattribute__(self, name):
                calls.append(name)
                raise AssertionError("provider attribute executed")

        for mutate in (False, True):
            with self.subTest(mutate=mutate):
                self.setUp()
                state = self.bootstrap()
                closure = {"files": ["unit/__init__.py"], "namespaces": ["unit"]}
                staged = self.runner.install_staged_import_guard("/source", closure["files"], closure["namespaces"])
                self.ns["initialization_boundary_provider_staged"](state, staged, closure)
                page = InitializationMetadataPages().port()
                page.admission.provider_state = state
                page.ns["sys"].modules = self.ns["sys"].modules
                providers = [staged, self.finder, Hostile()]
                page.ns["sys"].meta_path = providers
                page.ns["sys"].path_hooks = [Hostile()]
                original = page.ns["initialization_directory_inventory"]

                def inventory(path, budget):
                    if mutate:
                        self.finder.__dict__["find_distributions"] = object()
                    return original(path, budget)

                page.ns["initialization_directory_inventory"] = inventory
                page.trigger()
                boundary = page.admission.dependency_frontier["boundary"]
                self.assertEqual([row["object_id"] for row in boundary["finders"]], [id(p) for p in providers])
                self.assertEqual([row["identity"] for row in boundary["finders"]], [
                    "StagedFinder[metadata_nonparticipant]", "six._SixMetaPathImporter[metadata_nonparticipant]",
                    "opaque_unsupported"])
                self.assertEqual(boundary["path_hooks"][0]["identity"], "opaque_unsupported")
                self.assertEqual(boundary["provider_shapes_stable"], not mutate)
                self.assertEqual(boundary["page"]["page_content_complete"], not mutate)
                self.assertFalse(boundary["metadata_complete"])
                self.assertFalse(boundary["distributions_complete"])
                self.assertIsNone(boundary["torch_backends"])
                self.assertEqual(page.reads, page.metadata_paths + page.paths)
        self.assertEqual(calls, [])


    def test_proxy_wrapped_custom_namespaces_are_not_builtin_dictionaries(self):
        import types

        calls = []

        class Mapping(dict):
            def items(self):
                calls.append("items")
                raise AssertionError("wrapped custom mapping executed")

        for location in ("sources", "probe", "witness"):
            with self.subTest(location=location):
                self.setUp()
                proxy = types.MappingProxyType(Mapping())
                if location == "sources":
                    self.sources = proxy
                elif location == "probe":
                    self.runner._GRAPHQL_PROBE = proxy
                else:
                    self.runner._GRAPHQL_PROBE["result"]["loaded_modules"]["six"] = proxy
                self.assertIsNone(self.recognize(self.bootstrap()))
        self.assertEqual(calls, [])


    def test_namespace_ceiling_precedes_snapshot_allocation(self):
        calls = []

        def snapshot_was_too_early(value):
            calls.append("tuple")
            raise AssertionError("oversize namespace was materialized")

        self.ns["tuple"] = snapshot_was_too_early
        with self.assertRaises(ValueError):
            self.ns["initialization_boundary_provider_items"]({str(index): None for index in range(4097)})
        self.assertEqual(calls, [])


class InitializationBoundaryInventory(unittest.TestCase):
    """UNITONLY bounded physical inventory; no image/package execution."""

    def test_missing_named_distribution_metadata_keeps_whole_packet_partial(self):
        import stat

        port = InitializationDependencyFrontier()
        port.setUp()
        port.legacy_inventory()
        port.ns["sys"].path = [port.p]

        def inventory(path, budget):
            leaves = ["torch-2.10.0.dist-info"] if path == port.p else []
            budget["entries"] += len(leaves)
            return dict(path=path, device=1, inode=1, entries=[dict(
                name=name, mode=stat.S_IFDIR, scan_index=0, size=0, links=1, device=1, inode=2,
            ) for name in leaves])

        port.ns["initialization_directory_inventory"] = inventory
        port.trigger()
        report = port.admission.dependency_frontier
        self.assertTrue(report["boundary"]["metadata_complete"])
        self.assertEqual(report["boundary"]["torch_backends"], [])
        self.assertFalse(report["boundary"]["distributions_complete"], "missing METADATA was silently complete")
        self.assertEqual(report["status"], "partial")

    def test_unversioned_egg_metadata_uses_real_readonly_nofollow_reader(self):
        import hashlib
        import os
        import stat
        import tempfile
        from types import SimpleNamespace

        port = InitializationDependencyFrontier()
        port.setUp()
        port.legacy_inventory()
        functions = isolated(HARNESS, {"initialization_physical_file", "initialization_directory_inventory"})
        projected = SimpleNamespace(**{key: getattr(os, key) for key in dir(os)})
        projected.fstatvfs = lambda fd: SimpleNamespace(f_flag=os.ST_RDONLY)
        functions.update(os=projected, stat=stat, time=port.ns["time"], hashlib=hashlib)
        with tempfile.TemporaryDirectory() as root:
            metadata = pathlib.Path(root, "filelock.egg-info")
            metadata.mkdir()
            raw = b"Name: filelock\nVersion: UNITONLY\n"
            (metadata / "PKG-INFO").write_bytes(raw)
            (metadata / "entry_points.txt").write_bytes(b"[torch.backends]\n")
            port.ns["sys"].path = [root]
            port.ns["initialization_directory_inventory"] = functions["initialization_directory_inventory"]

            def reader(path, budget, **kwargs):
                if path.startswith(root + "/"):
                    return functions["initialization_physical_file"](path, budget, **kwargs)
                return port.reader(path, budget, **kwargs)

            port.ns["initialization_physical_file"] = reader
            port.trigger()
            boundary = port.admission.dependency_frontier["boundary"]
            self.assertTrue(boundary["distributions"], "unversioned named egg-info metadata omitted")
            row = boundary["distributions"][0]
            self.assertEqual(row["version"], "UNITONLY")
            self.assertEqual(row["witness"]["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(row["witness"]["inode"], (metadata / "PKG-INFO").stat().st_ino)
            self.assertEqual(boundary["torch_backends"], [])
            self.assertTrue(boundary["metadata_complete"])
            self.assertEqual(port.admission.dependency_frontier["bytes_read"],
                             len(port.raw) * len(port.paths) + len(raw) + len(b"[torch.backends]\n"))

    def test_case_variant_distribution_suffixes_preserve_real_physical_names(self):
        import hashlib
        import os
        import stat
        import tempfile
        from types import SimpleNamespace

        for dirname, leaf, family in (("torch-1.DIST-INFO", "METADATA", "torch"),
                                      ("torch-1.DiSt-InFo", "METADATA", "torch"),
                                      ("filelock.EGG-INFO", "PKG-INFO", "filelock"),
                                      ("filelock.EgG-InFo", "PKG-INFO", "filelock")):
            with self.subTest(dirname=dirname):
                port = InitializationDependencyFrontier()
                port.setUp()
                port.legacy_inventory()
                functions = isolated(HARNESS, {"initialization_physical_file", "initialization_directory_inventory"})
                projected = SimpleNamespace(**{key: getattr(os, key) for key in dir(os)})
                projected.fstatvfs = lambda fd: SimpleNamespace(f_flag=os.ST_RDONLY)
                functions.update(os=projected, stat=stat, time=port.ns["time"], hashlib=hashlib)
                with tempfile.TemporaryDirectory() as root:
                    metadata = pathlib.Path(root, dirname)
                    metadata.mkdir()
                    raw = f"Name: {family}\nVersion: UNITONLY\n".encode()
                    points = b"[torch.backends]\nunit = forbidden_UNITONLY:activate\n"
                    (metadata / leaf).write_bytes(raw)
                    (metadata / "entry_points.txt").write_bytes(points)
                    port.ns["sys"].path = [root]
                    port.ns["initialization_directory_inventory"] = functions["initialization_directory_inventory"]

                    def reader(path, budget, **kwargs):
                        if path.startswith(root + "/"):
                            return functions["initialization_physical_file"](path, budget, **kwargs)
                        return port.reader(path, budget, **kwargs)

                    port.ns["initialization_physical_file"] = reader
                    port.trigger()
                    boundary = port.admission.dependency_frontier["boundary"]
                    self.assertEqual(len(boundary["plugins"]), 1, "case-variant physical metadata was silently omitted")
                    self.assertTrue(boundary["metadata_complete"])
                    self.assertTrue(boundary["distributions_complete"])
                    self.assertEqual(boundary["torch_backends"][0]["value"], "forbidden_UNITONLY:activate")
                    self.assertEqual(boundary["torch_backends"][0]["effect_review"], "required_not_admitted")
                    self.assertEqual(boundary["metadata_files"], 2)
                    self.assertEqual({row["path"] for row in boundary["metadata"]},
                                     {str(metadata / leaf), str(metadata / "entry_points.txt")})
                    row = boundary["distributions"][0]
                    self.assertEqual(row["name"], family)
                    self.assertEqual(row["metadata_path"], str(metadata / leaf))
                    self.assertEqual(row["witness"]["sha256"], hashlib.sha256(raw).hexdigest())
                    self.assertEqual(row["witness"]["inode"], (metadata / leaf).stat().st_ino)
                    self.assertEqual(port.admission.dependency_frontier["bytes_read"],
                                     len(port.raw) * len(port.paths) + len(raw) + len(points))

    def test_case_variant_egg_forms_are_explicitly_incomplete(self):
        import hashlib
        import os
        import stat
        import tempfile
        from types import SimpleNamespace

        for suffix in (".EGG", ".EgG"):
            for form in ("directory_entry", "file_entry", "path_root"):
                with self.subTest(suffix=suffix, form=form):
                    port = InitializationDependencyFrontier()
                    port.setUp()
                    port.legacy_inventory()
                    functions = isolated(HARNESS, {"initialization_physical_file", "initialization_directory_inventory"})
                    projected = SimpleNamespace(**{key: getattr(os, key) for key in dir(os)})
                    projected.fstatvfs = lambda fd: SimpleNamespace(f_flag=os.ST_RDONLY)
                    functions.update(os=projected, stat=stat, time=port.ns["time"], hashlib=hashlib)
                    with tempfile.TemporaryDirectory() as root:
                        egg = pathlib.Path(root, "unit-1" + suffix)
                        if form == "file_entry":
                            egg.write_bytes(b"UNITONLY_NOT_AN_ARCHIVE")
                        else:
                            egg.mkdir()
                        port.ns["sys"].path = [str(egg) if form == "path_root" else root]
                        port.ns["initialization_directory_inventory"] = functions["initialization_directory_inventory"]
                        port.trigger()
                        boundary = port.admission.dependency_frontier["boundary"]
                        self.assertFalse(boundary["metadata_complete"], "case-variant egg was silently unaccounted")
                        self.assertIsNone(boundary["torch_backends"])
                        self.assertEqual(boundary["metadata_files"], 0)
                        if form == "path_root":
                            self.assertEqual(boundary["path_coverage"][0]["path"], str(egg))
                            self.assertEqual(boundary["path_coverage"][0]["status"], "unsupported_archive_or_relative_path")
                        else:
                            self.assertIn(dict(path=str(egg), reason="unsupported_egg_or_metadata_form"),
                                          boundary["incomplete_reasons"])

    def test_provider_metaclass_descriptors_are_opaque_without_execution(self):
        for branch in ("finder", "hook", "cache"):
            for throwing in (False, True):
                for as_class in (False, True):
                    with self.subTest(branch=branch, throwing=throwing, as_class=as_class):
                        port = InitializationDependencyFrontier()
                        port.setUp()
                        port.legacy_inventory()
                        calls = []

                        class Meta(type):
                            @property
                            def __module__(cls):
                                calls.append("metaclass descriptor")
                                if throwing:
                                    raise RuntimeError("must not execute descriptor")
                                return "UNITONLY_CUSTOM"

                        class Provider(metaclass=Meta):
                            def __call__(self, *args, **kwargs):
                                calls.append("provider call")
                                raise RuntimeError("must not execute provider")

                        provider = Provider if as_class else Provider()
                        if branch == "finder":
                            port.ns["sys"].meta_path = [provider]
                        elif branch == "hook":
                            port.ns["sys"].path_hooks = [provider]
                        else:
                            port.ns["sys"].path = ["/UNITONLY"]
                            port.ns["sys"].path_importer_cache = {"/UNITONLY": provider}
                        port.trigger()
                        self.assertEqual(calls, [], "identity observation executed custom metaclass code")
                        boundary = port.admission.dependency_frontier["boundary"]
                        self.assertFalse(boundary["metadata_complete"])
                        self.assertIsNone(boundary["torch_backends"])
                        key = {"finder": "finders", "hook": "path_hooks", "cache": "importer_cache"}[branch]
                        self.assertEqual(len(boundary[key]), 1, "opaque provider observation was lost")
                        self.assertEqual(boundary[key][0]["identity"], "opaque_unsupported")
                        self.assertIsNone(boundary["error_type"], "opaque providers must not abort observation")

    def test_same_label_finders_and_cached_importers_are_not_trusted(self):
        labels = [("finder", "_frozen_importlib", "BuiltinImporter"),
                  ("finder", "_frozen_importlib", "FrozenImporter"),
                  ("finder", "_frozen_importlib_external", "PathFinder"),
                  ("cache", "_frozen_importlib_external", "FileFinder")]
        for branch, module, name in labels:
            for as_class in (False, True):
                with self.subTest(branch=branch, name=name, as_class=as_class):
                    port = InitializationDependencyFrontier()
                    port.setUp()
                    port.legacy_inventory()
                    calls = []

                    class Impostor:
                        def find_distributions(self, *args, **kwargs):
                            calls.append("find_distributions")
                            raise RuntimeError("must not execute provider")

                        def __eq__(self, other):
                            calls.append("equality")
                            raise RuntimeError("must compare identity only")

                    Impostor.__module__, Impostor.__qualname__ = module, name
                    provider = Impostor if as_class else Impostor()
                    if branch == "finder":
                        port.ns["sys"].meta_path = [provider]
                    else:
                        port.ns["sys"].path = ["/UNITONLY"]
                        port.ns["sys"].path_importer_cache = {"/UNITONLY": provider}
                    port.trigger()
                    boundary = port.admission.dependency_frontier["boundary"]
                    self.assertEqual(calls, [])
                    self.assertFalse(boundary["metadata_complete"], "trusted label was mistaken for identity")
                    self.assertIsNone(boundary["torch_backends"])
                    key = "finders" if branch == "finder" else "importer_cache"
                    self.assertEqual(boundary[key][0]["identity"], "opaque_unsupported")

    def test_canonical_stdlib_finders_and_cached_importer_remain_accounted(self):
        import importlib.machinery
        from unittest.mock import patch

        port = InitializationDependencyFrontier()
        port.setUp()
        port.legacy_inventory()
        machinery = importlib.machinery
        port.ns["sys"].meta_path = [port.admission, machinery.BuiltinImporter,
                                      machinery.FrozenImporter, machinery.PathFinder]
        port.ns["sys"].path = ["/UNITONLY"]
        port.ns["sys"].path_importer_cache = {"/UNITONLY": machinery.FileFinder("/UNITONLY")}
        with patch.object(machinery.PathFinder, "find_distributions", side_effect=AssertionError("no resolver calls")):
            port.trigger()
        boundary = port.admission.dependency_frontier["boundary"]
        self.assertTrue(boundary["metadata_complete"])
        self.assertEqual(boundary["torch_backends"], [])
        self.assertTrue(all(row["status"] == "accounted" for row in boundary["finders"]))
        self.assertTrue(boundary["importer_cache"][0]["supported"])

    def test_same_label_hooks_require_canonical_code_globals_and_closure(self):
        import sys
        from types import FunctionType

        canonical = next(hook for hook in sys.path_hooks if type(hook) is FunctionType)
        for variant in ("function", "zip_class", "wrong_class", "wrong_loaders", "wrong_globals", "copied_code", "toxic_label"):
            with self.subTest(variant=variant):
                port = InitializationDependencyFrontier()
                port.setUp()
                port.legacy_inventory()
                calls = []

                def custom_hook(*args, **kwargs):
                    calls.append("hook")
                    raise RuntimeError("must not execute hook")

                impostor = custom_hook

                class Custom:
                    def __call__(self, *args, **kwargs):
                        calls.append("loader")
                        raise RuntimeError("must not execute loader")

                    def __eq__(self, other):
                        calls.append("equality")
                        raise RuntimeError("identity comparison only")

                    def __add__(self, other):
                        calls.append("label addition")
                        raise RuntimeError("do not evaluate descriptive labels")

                if variant in {"wrong_class", "wrong_loaders", "wrong_globals", "copied_code"}:
                    def cell(value):
                        cells = (lambda: value).__closure__
                        assert cells is not None
                        return cells[0]

                    closure = canonical.__closure__
                    assert closure is not None
                    if variant == "wrong_class":
                        closure = tuple(cell(Custom()) if name == "cls" else item
                                        for name, item in zip(canonical.__code__.co_freevars, closure))
                    elif variant == "wrong_loaders":
                        closure = tuple(cell(((Custom(), [".py"]),)) if name == "loader_details" else item
                                        for name, item in zip(canonical.__code__.co_freevars, closure))
                    impostor = FunctionType(canonical.__code__.replace() if variant == "copied_code" else canonical.__code__,
                                            {} if variant == "wrong_globals" else canonical.__globals__, closure=closure)
                if variant == "zip_class":
                    Custom.__module__, Custom.__qualname__ = "zipimport", "zipimporter"
                    impostor = Custom
                else:
                    impostor.__module__ = Custom() if variant == "toxic_label" else "_frozen_importlib_external"
                    impostor.__qualname__ = "FileFinder.path_hook.<locals>.path_hook"
                port.ns["sys"].path_hooks = [impostor]
                port.trigger()
                boundary = port.admission.dependency_frontier["boundary"]
                self.assertEqual(calls, [], "hook identity observation executed custom code")
                self.assertFalse(boundary["metadata_complete"], "hook label or partial code evidence was trusted")
                self.assertIsNone(boundary["torch_backends"])
                self.assertEqual(len(boundary["path_hooks"]), 1, "unsupported hook observation was lost")
                self.assertEqual(boundary["path_hooks"][0]["identity"], "opaque_unsupported")
                self.assertEqual(boundary["path_hooks"][0]["status"], "unsupported_custom_hook")

    def test_canonical_stdlib_path_hooks_remain_accounted_without_calls(self):
        import builtins
        import sys
        from types import FunctionType

        port = InitializationDependencyFrontier()
        port.setUp()
        port.legacy_inventory()
        port.ns["sys"].path_hooks = list(sys.path_hooks)
        self.assertTrue(any(type(hook) is FunctionType for hook in sys.path_hooks))
        calls = []

        def guard(frame, event, arg):
            if event == "call" and any(type(hook) is FunctionType and frame.f_code is hook.__code__
                                        for hook in port.ns["sys"].path_hooks):
                calls.append("canonical hook call")
                raise AssertionError("collector must not call even canonical hooks")

        def guarded_import(name, *args, **kwargs):
            self.assertEqual(name, "ast", "collector must use already-loaded stdlib bindings")
            return builtins.__import__(name, *args, **kwargs)

        port.ns["__builtins__"] = dict(vars(builtins), __import__=guarded_import)
        # Rebind the extracted functions so their builtins use this guard.
        for name, value in list(port.ns.items()):
            if type(value) is FunctionType and name.startswith("initialization_boundary_"):
                port.ns[name] = FunctionType(value.__code__, port.ns, name, value.__defaults__, value.__closure__)
        previous = sys.getprofile()
        try:
            sys.setprofile(guard)
            port.trigger()
        finally:
            sys.setprofile(previous)
        boundary = port.admission.dependency_frontier["boundary"]
        self.assertEqual(calls, [])
        self.assertTrue(boundary["metadata_complete"], "genuine startup stdlib hooks were not accounted")
        self.assertEqual(boundary["torch_backends"], [])
        self.assertTrue(all(row["status"] == "accounted" for row in boundary["path_hooks"]))

    def test_hook_closure_type_checks_do_not_invoke_custom_metaclass_equality(self):
        import sys
        from types import FunctionType

        port = InitializationDependencyFrontier()
        port.setUp()
        port.legacy_inventory()
        calls = []

        class Meta(type):
            def __eq__(cls, other):
                calls.append("metaclass equality")
                raise RuntimeError("type checks must use identity")

        class Suffixes(list, metaclass=Meta):
            def __iter__(self):
                calls.append("suffix iteration")
                raise RuntimeError("unknown suffix collection must stay opaque")

        canonical = next(hook for hook in sys.path_hooks if type(hook) is FunctionType)
        assert canonical.__closure__ is not None
        cells = dict(zip(canonical.__code__.co_freevars, canonical.__closure__))
        loaders = cells["loader_details"].cell_contents
        replacement = ((loaders[0][0], Suffixes()), *loaders[1:])
        replacement_cells = (lambda: replacement).__closure__
        assert replacement_cells is not None
        closure = tuple(replacement_cells[0] if name == "loader_details" else value
                        for name, value in cells.items())
        port.ns["sys"].path_hooks = [FunctionType(canonical.__code__, canonical.__globals__, closure=closure)]
        port.trigger()
        boundary = port.admission.dependency_frontier["boundary"]
        self.assertEqual(calls, [], "type membership invoked custom metaclass equality")
        self.assertFalse(boundary["metadata_complete"])
        self.assertIsNone(boundary["torch_backends"])
        self.assertEqual(boundary["path_hooks"][0]["status"], "unsupported_custom_hook")

    def test_hook_identity_observation_never_executes_custom_attribute_code(self):
        port = InitializationDependencyFrontier()
        port.setUp()
        port.legacy_inventory()
        calls = []

        class CustomHook:
            def __getattribute__(self, name):
                calls.append(name)
                raise RuntimeError("custom metadata hook executed")

        port.ns["sys"].path_hooks = [CustomHook()]
        port.trigger()
        self.assertEqual(calls, [], "identity inspection must not execute custom hook attributes")
        boundary = port.admission.dependency_frontier["boundary"]
        self.assertFalse(boundary["metadata_complete"])
        self.assertIsNone(boundary["torch_backends"])
        self.assertEqual(boundary["path_hooks"][0]["status"], "unsupported_custom_hook")

    def test_metadata_stat_failures_and_json_escaping_share_encoded_ceiling(self):
        import json

        port = InitializationDependencyFrontier()
        port.setUp()
        port.legacy_inventory()
        port.ns["sys"].path = [f"/UNITONLY{i}" for i in range(10)]
        error = type("UNITONLY_" + "x" * 200, (Exception,), {})

        def refused(path, budget):
            raise error()

        port.ns["initialization_directory_inventory"] = refused
        port.admission.baseline = {f"UNITONLY_{i}": '\\"\\n\u2603' * 200 for i in range(1000)}
        port.trigger()
        report = port.admission.dependency_frontier
        actual = len(json.dumps(report, sort_keys=True).encode())
        self.assertLessEqual(actual, 1048576, "unaccounted stat error/status growth exceeded shared JSON ceiling")
        self.assertLessEqual(actual, report["encoded_bytes_upper_bound"])
        self.assertIsNone(report["boundary"]["torch_backends"])
        self.assertFalse(report["expanded_import_admitted"])

    def test_incomplete_metadata_never_publishes_an_empty_backend_set(self):
        import hashlib
        import stat

        for failure in ("metadata_limit", "archive", "custom_finder", "empty", "link", "invalid", "directory_limit"):
            with self.subTest(failure=failure):
                port = InitializationDependencyFrontier()
                port.setUp()
                port.legacy_inventory()
                port.ns["sys"].path = [port.p]
                raw = b"[torch.backends]\n" if failure != "invalid" else b"unit = missing_group\n"
                if failure == "archive":
                    port.ns["sys"].path.insert(0, "/actual/stdlib.zip")
                if failure == "custom_finder":
                    class NeverCall:
                        def find_distributions(self, *args, **kwargs):
                            raise RuntimeError("must not execute finder")
                    port.ns["sys"].meta_path = [NeverCall()]

                def inventory(path, budget):
                    if failure == "directory_limit":
                        budget["entries"] = 4096
                        raise AssertionError("S2 inventory entry ceiling")
                    if path == port.p:
                        leaves = [(f"unit_{i}-1.dist-info", stat.S_IFDIR) for i in range(33 if failure == "metadata_limit" else 1)]
                    elif path.endswith(".dist-info"):
                        leaves = [("entry_points.txt", stat.S_IFLNK if failure == "link" else stat.S_IFREG)]
                    else:
                        leaves = []
                    budget["entries"] += len(leaves)
                    return dict(path=path, device=1, inode=1, entries=[dict(
                        name=name, mode=mode, scan_index=i, size=0 if failure == "empty" else len(raw),
                        links=1, device=1, inode=i+2,
                    ) for i, (name, mode) in enumerate(leaves)])

                def reader(path, budget, **kwargs):
                    if path.endswith("entry_points.txt"):
                        port.reads.append(path)
                        budget["bytes"] += len(raw)
                        return dict(path=path, physical=path, links=[], size=len(raw),
                                    sha256=hashlib.sha256(raw).hexdigest()), raw
                    return port.reader(path, budget, **kwargs)

                port.ns.update(initialization_directory_inventory=inventory, initialization_physical_file=reader)
                port.trigger()
                report = port.admission.dependency_frontier
                boundary = report["boundary"]
                self.assertFalse(boundary["metadata_complete"])
                self.assertIsNone(boundary["torch_backends"])
                self.assertEqual(report["status"], "partial", "incomplete boundary cannot be an observed whole packet")
                self.assertLessEqual(boundary["metadata_files"], 32)
                self.assertLessEqual(report["entries"], 4096)
                self.assertFalse(report["expanded_import_admitted"])
                self.assertEqual(boundary["limits"]["metadata_files"], 32)

    def test_numpy_alternative_and_family_origins_are_physical_not_inferred(self):
        import stat

        port = InitializationDependencyFrontier()
        port.setUp()
        port.legacy_inventory()
        port.ns["sys"].path = [port.p]
        names = {
            port.p: [("filelock", stat.S_IFDIR)],
            port.p + "/filelock": [("__init__.py", stat.S_IFREG)],
            port.p + "/numpy": [("_distributor_init_local", stat.S_IFDIR),
                                  ("_distributor_init_local.cpython-312-x86_64-linux-gnu.so", stat.S_IFLNK)],
        }

        def inventory(path, budget):
            leaves = names.get(path, [])
            budget["entries"] += len(leaves)
            return dict(path=path, device=1, inode=1, entries=[dict(
                name=name, mode=mode, scan_index=i, size=12, links=1, device=1, inode=i+2,
            ) for i, (name, mode) in enumerate(leaves)])

        port.ns["initialization_directory_inventory"] = inventory
        port.trigger()
        boundary = port.admission.dependency_frontier["boundary"]
        self.assertIsNotNone(boundary["numpy_hook"], "missing optional-hook alternative inventory")
        self.assertEqual(boundary["numpy_hook"]["status"], "present_requires_review")
        self.assertEqual(len(boundary["numpy_hook"]["candidates"]), 2)
        port.reconcile()
        filelock = next(row for row in boundary["external_families"] if row["module"] == "filelock")
        self.assertEqual(filelock["origin_status"], "observed")
        self.assertEqual(filelock["origins"][0]["path"], port.p + "/filelock/__init__.py")
        self.assertFalse(filelock["admitted"])

    def test_native_selectors_preserve_path_layout_and_unsorted_winner(self):
        import stat

        port = InitializationDependencyFrontier()
        port.setUp()
        port.legacy_inventory()
        port.ns["sys"].path = ["/first", port.p]
        names = {
            "/first/nvidia/cublas/lib": ["libcublas.so.9", "libcublas.so.1"],
            "/first/nvidia/cu12/lib": ["libcublas.so.0"],
            port.p + "/torch/lib": ["libtorch_global_deps.so"],
            port.p + "/torch": ["_C.cpython-312-x86_64-linux-gnu.so"],
            port.p + "/torch/bin": ["torch_shm_manager"],
            port.p + "/numpy/_core": ["_multiarray_umath.cpython-312-x86_64-linux-gnu.so"],
            port.p + "/numpy.libs": ["libopenblas-unit.so"],
            port.p + "/warp/bin": ["warp.so", "warp-clang.so"],
            port.ns["E1_YAML_ROOT"]: ["_yaml.cpython-312-x86_64-linux-gnu.so"],
        }

        def inventory(path, budget):
            leaves = names.get(path, [])
            budget["entries"] += len(leaves)
            return dict(path=path, device=1, inode=1, entries=sorted([
                dict(name=name, scan_index=i, mode=stat.S_IFREG, size=(i+1)*10, device=1, inode=i+2, links=1)
                for i, name in enumerate(leaves)], key=lambda row: row["name"]))

        port.ns["initialization_directory_inventory"] = inventory
        port.trigger()
        boundary = port.admission.dependency_frontier["boundary"]
        self.assertTrue(boundary["native"], "native selector table is not integrated")
        cuda = [row for row in boundary["native"] if row["kind"] == "torch_cuda_preload"]
        self.assertEqual(len(cuda), 16)
        self.assertEqual(sum(row["required"] for row in cuda), 15)
        self.assertEqual(cuda[0]["winner"], "/first/nvidia/cublas/lib/libcublas.so.9")
        self.assertEqual([row["path"] for row in cuda[0]["candidates"]], [
            "/first/nvidia/cublas/lib/libcublas.so.9", "/first/nvidia/cublas/lib/libcublas.so.1",
            "/first/nvidia/cu12/lib/libcublas.so.0",
        ])
        self.assertEqual(boundary["projection"]["conditional_required_identities"], 17)
        self.assertEqual(boundary["projection"]["four_role_conditional_identities"], 68)
        self.assertEqual(boundary["projection"]["role_identity_limit"], 16)
        self.assertEqual(boundary["projection"]["role_read_limit"], 2 * 1024**3)
        self.assertFalse(boundary["projection"]["admission_enabled"])
        self.assertEqual(port.reads, port.paths, "native files must never be content-read")
        candidates = [candidate for row in boundary["native"] for candidate in row["candidates"]]
        self.assertTrue(any("numpy.libs" in row["path"] for row in candidates))
        self.assertTrue(any(row["path"].endswith("warp.so") for row in candidates))
        self.assertTrue(any("_yaml." in row["path"] for row in candidates))
        self.assertTrue(all("sha256" not in row for row in candidates))

    def test_sorted_evidence_retains_real_scandir_precedence(self):
        import os
        import stat
        import tempfile
        import time
        from types import SimpleNamespace

        fn = isolated(HARNESS, {"initialization_directory_inventory"})["initialization_directory_inventory"]
        projected = SimpleNamespace(**{k: getattr(os, k) for k in dir(os)})
        projected.fstatvfs = lambda fd: SimpleNamespace(f_flag=os.ST_RDONLY)
        fn.__globals__.update(os=projected, stat=stat, time=time)
        with tempfile.TemporaryDirectory() as root:
            for name in ("z.so.1", "a.so.1", "m.so.1"):
                pathlib.Path(root, name).write_bytes(b"UNITONLY")
            with os.scandir(root) as entries:
                actual = [entry.name for entry in entries]
            budget = dict(deadline=time.monotonic() + 5, entries=0, entry_limit=4096)
            result = fn(root, budget)
            self.assertEqual([r["name"] for r in result["entries"]], sorted(actual))
            self.assertTrue(all("scan_index" in row for row in result["entries"]), "missing native-order witness")
            self.assertEqual([r["name"] for r in sorted(result["entries"], key=lambda r: r["scan_index"])], actual)
            self.assertEqual(budget["entries"], 3)


class InitializationCaseReleaseGuards(unittest.TestCase):
    """UNITONLY C1/C2 release checks; no package imports or runtime effects."""

    def monitor_port(self, case):
        import builtins
        import signal
        from types import SimpleNamespace

        names = {"initialization_monitor_stall", "initialization_failure_witness"}
        tree = ast.parse(HARNESS.read_text())
        ns: dict = dict(__file__=str(HARNESS), SELF="scripts/workflow_graphql_execution_join_harness.py")
        marker = dict(pid=202, parent_pid=101, pgid=202, sid=202, start_ticks=7,
                      boot="UNITONLY", pid_namespace="UNITONLY", case=case,
                      before_owner_construction=True, after_real_initialization=True, observed_at=0.0)
        self.records = {
            "/evidence/initialization-pre-readiness.json": marker,
            "/evidence/join-launch-202.json": dict(marker, bootstrap_argv=[0] * 6 + ["api-serve"]),
            "/evidence/join-process-202-started.json": dict(marker, startup_exception_sites=[]),
        }
        self.now, self.signals, self.leaves = [0.0], [], {}
        identity = {key: marker[key] for key in ("pid", "parent_pid", "pgid", "sid", "start_ticks", "boot", "pid_namespace")}
        guard = SimpleNamespace(initialization_case=case, role="harness",
                                initialization_server_identity=copy.deepcopy(identity),
                                spawn_records=[dict(pid=101, bootstrap_argv=[0] * 6 + ["api-launch"])])
        class FakePath:
            def __init__(inner, value):
                inner.value = str(value)

            def exists(inner):
                return inner.value in self.records

            def read_text(inner):
                self.assertEqual(inner.value, str(HARNESS))
                return HARNESS.read_text()

        def imported(name, *args, **kwargs):
            if name == "workflow_graphql_execution_join_fixture":
                return SimpleNamespace(initialization_group_absent=lambda pid: bool(self.signals))
            return builtins.__import__(name, *args, **kwargs)

        ns.update(__builtins__=dict(vars(builtins), __import__=imported), ACTIVE=guard,
                  Path=FakePath, LAUNCH=["api-launch"], signal=signal,
                  time=SimpleNamespace(monotonic=lambda: self.now[0], sleep=lambda delay: self.now.__setitem__(0, self.now[0] + delay)),
                  os=SimpleNamespace(killpg=lambda pid, sig: self.signals.append((pid, sig, self.now[0]))),
                  read_json=lambda path: self.records[path.value], role_for=lambda argv: "server",
                  live_identity=lambda row: self.assertEqual({key: row[key] for key in identity}, identity),
                  write_evidence=lambda name, row: self.leaves.update({name: copy.deepcopy(row)}))
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names],
                                type_ignores=[]), str(HARNESS), "exec"), ns)
        return ns

    def injected_exception(self) -> dict:
        tree = ast.parse(HARNESS.read_text())
        hook = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "initialization_pre_readiness")
        fault = next(n for n in ast.walk(hook) if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
                     and isinstance(n.exc.func, ast.Name) and n.exc.func.id == "RuntimeError")
        return dict(exception_type="RuntimeError", sites=[
            dict(file="isaaclab_arena/agentic_environment_generation/workflow/api/installed_execution.py",
                 function="build", line=256),
            dict(file="scripts/workflow_graphql_execution_join_harness.py",
                 function="initialization_pre_readiness", line=fault.lineno),
        ])

    def test_failure_trace_triggers_external_containment_without_final_record(self):
        ns = self.monitor_port("failure")
        ns["initialization_monitor_stall"]()
        self.assertEqual(self.signals, [])
        original = self.injected_exception()
        self.records["/evidence/join-process-202-started.json"]["startup_exception_sites"] = [original]
        self.now[0] = 2.0
        ns["initialization_monitor_stall"]()
        self.assertEqual(self.signals, [(202, 9, 2.0)], "C1 parked startup must be externally contained")
        stop = self.leaves["initialization-stall-stop.json"]
        self.assertEqual(stop["original_failure"], original)
        self.assertEqual(stop["server_pid"], 202)
        self.assertNotIn("/evidence/join-process-202.json", self.records)
        ns["initialization_monitor_stall"]()
        self.assertEqual(len(self.signals), 1)

    def test_failure_evidence_uses_started_trace_and_external_stop_not_finally(self):
        from types import SimpleNamespace

        ns = isolated(HARNESS, {"initialization_evidence_names", "initialization_required_evidence",
                                "initialization_failure_witness"})
        ns.update(__file__=str(HARNESS), INITIALIZATION_ROLES=("init-server", "init-generate", "init-refine", "init-assess"))
        proof = dict(process_pids=list(range(90, 101)), initialization_roles=[dict(role="init-server", pid=100)])
        required = ns["initialization_required_evidence"]("failure", proof)
        self.assertNotIn("join-process-100.json", required, "SIGKILL cannot emit a normal finally record")
        self.assertIn("join-process-100-started.json", required)
        self.assertIn("initialization-stall-stop.json", required)
        original = self.injected_exception()
        marker = dict(case="failure", pid=100)
        stop = dict(server_pid=100, signal=9, original_failure=original, group_reap_seconds=0.1)
        started = dict(startup_exception_sites=[original])
        reads = []
        def read(path):
            reads.append(str(path))
            self.assertEqual(str(path), "/evidence/join-process-100-started.json")
            return started
        ns.update(checkpoint=marker, row=dict(pid=100), case="failure", Path=pathlib.Path, read_json=read,
                  ACTIVE=SimpleNamespace(initialization_stall_stop=stop))
        tree = ast.parse(HARNESS.read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "initialization_installed_case")
        index = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "witness" for t in n.targets))
        exec(compile(ast.Module(body=fn.body[index:], type_ignores=[]), str(HARNESS), "exec"), ns)
        witness = ns["ACTIVE"].initialization_result["pre_readiness_failure"]
        self.assertEqual(witness["original_failure"], original)
        self.assertEqual(witness["signal"], 9)
        self.assertEqual(reads, ["/evidence/join-process-100-started.json"])

    def case_archive(self, case, *, reader_only=False):
        import json

        proof, junit = unitonly_proof(case)
        proof["process_pids"] = list(range(90, 100)) + [100]
        proof["initialization_server_cleanup"]["launcher_pid"] = 97
        server = proof["initialization_roles"][0]
        server.update(parent_pid=97, boot="UNITONLY", pid_namespace="UNITONLY", status="completed",
                      forbidden=proof["forbidden"], sdk_calls=0, owner_constructions=0)
        identity = {k: server[k] for k in ("pid", "parent_pid", "pgid", "sid", "start_ticks", "boot", "pid_namespace")}
        witness = proof["pre_readiness_failure"]
        witness.update(identity, observed_at=0.0, signal=9, observed_stall_seconds=5.0)
        original = self.injected_exception()
        if case == "failure":
            witness.pop("stall_seconds")
            witness["original_failure"] = original
            witness["failure_site"] = copy.deepcopy(original["sites"][-1])
        marker = {k: v for k, v in witness.items() if k not in {
            "readiness_absent", "server_pid", "original_failure_retained", "stall_seconds",
            "group_reap_seconds", "signal", "observed_stall_seconds", "original_failure"}}
        stop = {k: witness[k] for k in ("server_pid", "signal", "observed_stall_seconds", "group_reap_seconds")}
        stop.update(original_failure=original) if case == "failure" else stop.update(stall_seconds=5)
        prefix = ["/isaac-sim/kit/python/bin/python3", "-I", "-S", "-B",
                  "/source/scripts/workflow_graphql_execution_join_harness.py", "--cli"]
        module = "isaaclab_arena.agentic_environment_generation.workflow.cli"
        server_argv = ["api-serve", "--config", "UNITONLY", "--instance", "d" * 32, "--lease-fd", "7", "--gate-fd", "8"]
        server_launch = dict(identity, bootstrap_argv=prefix + server_argv, production_argv=[prefix[0], "-m", module] + server_argv)
        objects = {"initialization-init-server.json": server, "initialization-pre-readiness.json": marker,
                   "initialization-stall-stop.json": stop, "join-launch-100.json": server_launch,
                   "join-process-100-started.json": dict(identity, source_sha256=proof["source_sha256"], role="server",
                       bootstrap_argv=prefix + server_argv, argv=[module] + server_argv,
                       startup_exception_sites=[original] if case == "failure" else [])}
        spawns, used = [], []
        commands = ["setup"] * 2 + ["admin"] * 5 + ["api-launch", "api-stop", "api-status"]
        for index, command in enumerate(commands):
            pid = 90 + index
            args = [command]
            spawn = dict(pid=pid, bootstrap_argv=prefix + args, production_argv=None)
            spawns.append(spawn)
            used.append(args)
            process = dict(pid=pid, parent_pid=50, pgid=pid, sid=pid, start_ticks=1, boot="UNITONLY",
                           pid_namespace="UNITONLY", bootstrap_argv=prefix + args, argv=[module] + args,
                           role=(["setup"] * 2 + ["admin"] * 5 + ["launcher", "client", "client"])[index],
                           status="completed", source_sha256=proof["source_sha256"], returncode=0 if index < 7 else 3,
                           forbidden=proof["forbidden"], sdk_calls=0, owner_constructions=0,
                           spawn_records=[server_launch] if index == 7 else [])
            result = (dict(code="setup_complete" if index < 2 else "admin_complete") if index < 7
                      else dict(state="launching", code="exited_unclean"))
            objects.update({f"join-launch-{pid}.json": dict(spawn, parent_pid=50), f"join-process-{pid}.json": process,
                            f"initialization-cli-{index}.json": dict(pid=pid, argv=args, returncode=process["returncode"],
                                                                     stdout=json.dumps(result), stderr="")})
        objects["initialization-harness.json"] = dict(spawn_records=spawns, used=used, forbidden=proof["forbidden"])
        objects["client-proof.json"] = proof
        ns = isolated(HARNESS, {"initialization_verify_evidence", "initialization_required_evidence",
                                "initialization_evidence_names", "initialization_verify_proof", "initialization_origin",
                                "initialization_failure_witness"})
        if reader_only:
            ns.pop("initialization_failure_witness")
            ns.pop("__file__", None)
        ns.update(INITIALIZATION_ROLES=("init-server", "init-generate", "init-refine", "init-assess"))
        if not reader_only:
            ns["__file__"] = str(HARNESS)
        def verify():
            files = {name: json.dumps(value).encode() for name, value in objects.items()}
            files.update({"pytest.xml": junit, "collection-ready": (case + "\n").encode()})
            return ns["initialization_verify_evidence"](files, case)
        return objects, verify

    def test_archive_reader_keeps_exporter_fixed_function_closure(self):
        _, verify = self.case_archive("failure", reader_only=True)
        try:
            result = verify()
        except NameError as error:
            self.fail(f"Exporter/host fixed reader closure is incomplete: {error}")
        self.assertEqual(result["status"], "passed")

    def test_archive_accepts_real_C_failure_shape_without_fabricated_finally(self):
        objects, verify = self.case_archive("failure")
        self.assertNotIn("join-process-100.json", objects)
        try:
            result = verify()
        except KeyError as error:
            self.fail(f"C1 archive demanded unavailable post-SIGKILL evidence: {error}")
        self.assertEqual(result["status"], "passed")

    def test_generic_nonready_or_success_receipts_cannot_certify_C_cases(self):
        import json

        for case in ("failure", "timeout"):
            objects, verify = self.case_archive(case)
            self.assertEqual(verify()["status"], "passed")
            for index in (7, 8, 9):
                output = objects[f"initialization-cli-{index}.json"]
                process = objects[f"join-process-{90 + index}.json"]
                original_output, original_process = copy.deepcopy(output), copy.deepcopy(process)
                mutations = [(0, {}), (3, {}), (3, dict(state="failed", code="startup_failed")),
                             (3, dict(state="launching", code="unknown")),
                             (0, dict(state="launching", code="exited_unclean")),
                             (3, dict(state="ready", code="exited_unclean")),
                             (3, dict(state="launching", code="exited_unclean", capabilities={"submit": True}))]
                for code, receipt in mutations:
                    with self.subTest(case=case, index=index, receipt=receipt, code=code):
                        output.update(returncode=code, stdout=json.dumps(receipt))
                        process["returncode"] = code
                        with self.assertRaises(AssertionError):
                            verify()
                    output.update(original_output)
                    process.update(original_process)

    def test_timeout_archive_requires_five_second_external_signal_and_bounded_reap(self):
        for case in ("failure", "timeout"):
            objects, verify = self.case_archive(case)
            self.assertEqual(verify()["status"], "passed")
            stop = objects["initialization-stall-stop.json"]
            witness = objects["client-proof.json"]["pre_readiness_failure"]
            for field, values in {
                "signal": (True, 15, "9"),
                "server_pid": (True, 101),
                "group_reap_seconds": (-1, 5.01, True, float("inf"), float("nan")),
                "observed_stall_seconds": ((-1, True, float("inf"), float("nan")) if case == "failure"
                                           else (4.99, 5.051, 40, True, float("inf"), float("nan"))),
            }.items():
                original = stop[field]
                for value in values:
                    with self.subTest(case=case, field=field, value=value):
                        stop[field] = witness[field] = value
                        with self.assertRaises((AssertionError, TypeError)):
                            verify()
                stop[field] = witness[field] = original

    def test_original_failure_rejects_unrelated_or_malformed_source_coordinates(self):
        objects, verify = self.case_archive("failure")
        started = objects["join-process-100-started.json"]
        original = self.injected_exception()
        mutations = [dict(exception_type="ValueError", sites=original["sites"]), dict(exception_type="RuntimeError", sites=[])]
        for key, value in (("file", "other.py"), ("function", "other"), ("line", True), ("line", 1)):
            wrong = copy.deepcopy(original)
            wrong["sites"][-1][key] = value
            mutations.append(wrong)
        for event in mutations:
            with self.subTest(event=event):
                started["startup_exception_sites"] = [event]
                objects["initialization-stall-stop.json"]["original_failure"] = event
                objects["client-proof.json"]["pre_readiness_failure"]["original_failure"] = event
                with self.assertRaises(AssertionError):
                    verify()

    def test_timeout_monitor_never_signals_before_five_seconds(self):
        ns = self.monitor_port("timeout")
        self.now[0] = 4.99
        ns["initialization_monitor_stall"]()
        self.assertEqual(self.signals, [])
        self.now[0] = 5.0
        ns["initialization_monitor_stall"]()
        self.assertEqual(self.signals, [(202, 9, 5.0)])
        self.assertEqual(self.leaves["initialization-stall-stop.json"]["observed_stall_seconds"], 5.0)

    def test_C_database_readiness_is_bounded_before_pytest(self):
        import builtins
        from types import SimpleNamespace

        tree = ast.parse(HARNESS.read_text())
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertIn("initialization_wait_database", functions, "C bootstrap bypassed legacy database readiness")
        inside = ast.unparse(functions["initialization_inside"])
        self.assertLess(inside.index("initialization_wait_database("), inside.index("pytest.main("))
        self.assertLess(inside.index("install_staged_import_guard("), inside.index("initialization_wait_database("))
        self.assertIn("if network is not None:", inside)
        for mode in ("retry", "deadline", "late-success"):
            now, calls, closes = [0.0], [], []
            class Unavailable(Exception):
                pass
            class Driver:
                def __enter__(inner):
                    return inner
                def __exit__(inner, *args):
                    closes.append(True)
                def verify_connectivity(inner):
                    now[0] += 1
                    if mode == "late-success":
                        now[0] = 6
                    elif mode == "deadline" or len(calls) == 1:
                        raise Unavailable()
            def driver(uri, **kwargs):
                calls.append((uri, kwargs))
                self.assertLessEqual(kwargs["connection_acquisition_timeout"], 5 - now[0])
                return Driver()
            module = SimpleNamespace(GraphDatabase=SimpleNamespace(driver=driver),
                                     exceptions=SimpleNamespace(ServiceUnavailable=Unavailable, SessionExpired=Unavailable))
            def imported(name, *args, **kwargs):
                return module if name == "neo4j" else builtins.__import__(name, *args, **kwargs)
            ns: dict = dict(__builtins__=dict(vars(builtins), __import__=imported),
                            time=SimpleNamespace(monotonic=lambda: now[0], sleep=lambda delay: now.__setitem__(0, now[0] + delay)))
            exec(compile(ast.Module(body=[functions["initialization_wait_database"]], type_ignores=[]), str(HARNESS), "exec"), ns)
            with self.subTest(mode=mode):
                if mode == "retry":
                    ns["initialization_wait_database"]("bolt://172.30.0.2:7687", 5)
                    self.assertEqual(len(calls), 2)
                else:
                    with self.assertRaises(AssertionError):
                        ns["initialization_wait_database"]("bolt://172.30.0.2:7687", 5)
                self.assertEqual(len(calls), len(closes))
                self.assertTrue(all(uri == "bolt://172.30.0.2:7687" and options["auth"] is None
                                    and options["max_transaction_retry_time"] == 0 for uri, options in calls))

    def test_failed_collection_retains_partial_output_and_separate_cleanup_error(self):
        import contextlib
        from types import SimpleNamespace

        for mode in ("deadline", "overflow", "monitor"):
            ns = isolated(HARNESS, {"initialization_collect"})
            class Stream:
                def fileno(inner):
                    return 1
                def close(inner):
                    pass
            proc = SimpleNamespace(pid=101, stdout=Stream(), stderr=Stream())
            now, visits = [0.0], [0]
            class Selector:
                def __enter__(inner):
                    return inner
                def __exit__(inner, *args):
                    pass
                def register(inner, *args):
                    pass
                def get_map(inner):
                    return {1: True}
                def select(inner, delay):
                    now[0] += 1
                    return [(SimpleNamespace(fileobj=proc.stderr), 1)]
            def monitor():
                visits[0] += 1
                if mode == "monitor" and visits[0] == 2:
                    raise RuntimeError("UNITONLY monitor failure")
            def contain(*args):
                raise OSError("UNITONLY cleanup failure")
            guard = SimpleNamespace(initialization_case="timeout", role="harness",
                                    spawn_records=[dict(pid=101, bootstrap_argv=[0] * 6 + ["api-launch"])])
            ns.update(ACTIVE=guard, LAUNCH=["api-launch"], selectors=SimpleNamespace(DefaultSelector=Selector, EVENT_READ=1),
                      os=SimpleNamespace(set_blocking=lambda *a: None, read=lambda *a: b"native stderr"),
                      time=SimpleNamespace(monotonic=lambda: now[0]), initialization_owned_server=lambda pid: None,
                      initialization_monitor_stall=monitor, initialization_contain_launcher=contain,
                      screen=lambda raw: None, contextlib=contextlib)
            with self.subTest(mode=mode):
                with self.assertRaises(OSError):
                    ns["initialization_collect"](proc, 1 if mode == "deadline" else 40,
                                                 stderr_limit=2 if mode == "overflow" else 65536)
                records = getattr(guard, "initialization_collection_errors", [])
                self.assertEqual(len(records), 1, "bounded collected bytes vanished on failure")
                self.assertEqual(records[0]["failure_type"], "RuntimeError" if mode == "monitor" else "AssertionError")
                self.assertEqual(records[0]["cleanup_failure_type"], "OSError")
                self.assertTrue(records[0]["stderr"].startswith("na"))
                self.assertLessEqual(len(records[0]["stderr"].encode()), 65536)
                self.assertEqual(records[0]["pid"], 101)
        inside = next(n for n in ast.parse(HARNESS.read_text()).body
                      if isinstance(n, ast.FunctionDef) and n.name == "initialization_inside")
        self.assertIn("initialization_collection_errors", ast.unparse(inside))

    def test_collection_errors_cannot_be_omitted_from_acceptance(self):
        objects, verify = self.case_archive("timeout")
        objects["initialization-harness.json"]["collection_errors"] = [dict(pid=97, failure_type="AssertionError")]
        with self.assertRaises(AssertionError):
            verify()

    def test_failure_monitor_rejects_other_process_trace_before_signalling(self):
        for field, value in (("pid", 203), ("parent_pid", 102), ("start_ticks", 8),
                             ("boot", "OTHER"), ("pid_namespace", "OTHER")):
            ns = self.monitor_port("failure")
            record = self.records["/evidence/join-process-202-started.json"]
            record["startup_exception_sites"] = [self.injected_exception()]
            record[field] = value
            with self.subTest(field=field):
                with self.assertRaises(AssertionError):
                    ns["initialization_monitor_stall"]()
                self.assertEqual(self.signals, [])

    def test_monitor_rejects_launch_identity_disagreement_before_any_signal(self):
        changes = (("pid", 303), ("parent_pid", 102), ("pgid", 303), ("sid", 303),
                   ("start_ticks", 6), ("boot", "OTHER-BOOT"), ("pid_namespace", "OTHER-NS"),
                   ("start_ticks", 7.0))
        for case in ("failure", "timeout"):
            for source in ("retained", "disk"):
                for field, value in changes:
                    ns = self.monitor_port(case)
                    self.now[0] = 5.0
                    self.records["/evidence/join-process-202-started.json"]["startup_exception_sites"] = [self.injected_exception()]
                    identity = (ns["ACTIVE"].initialization_server_identity if source == "retained"
                                else self.records["/evidence/join-launch-202.json"])
                    identity[field] = value
                    with self.subTest(case=case, source=source, field=field, value=value):
                        with self.assertRaises(AssertionError):
                            ns["initialization_monitor_stall"]()
                        self.assertEqual(self.signals, [])

    def test_timeout_witness_measures_signal_time_not_preverification_time(self):
        ns = self.monitor_port("timeout")
        self.now[0] = 5.0
        ns["live_identity"] = lambda row: self.now.__setitem__(0, 8.0)
        ns["initialization_monitor_stall"]()
        self.assertEqual(self.signals, [(202, 9, 8.0)])
        self.assertEqual(self.leaves["initialization-stall-stop.json"]["observed_stall_seconds"], 8.0,
                         "slow identity verification cannot masquerade as a five-second signal")

    def test_installed_network_environment_precedes_guard_and_fixture(self):
        from types import SimpleNamespace

        tree = ast.parse(HARNESS.read_text())
        inside = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "initialization_inside")
        body = next(n for n in inside.body if isinstance(n, ast.Try)).body
        end = next(i for i, n in enumerate(body) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "guard" for t in n.targets))
        prefix = compile(ast.Module(body=body[:end + 1], type_ignores=[]), str(HARNESS), "exec")
        for case in ("positive", "failure", "timeout"):
            reads, seen = [], []
            env = {"ARENA_WORKFLOW_NEO4J_URI": "UNITONLY-stale", "ARENA_WORKFLOW_NEO4J_DATABASE": "stale"}
            network = dict(ip="172.30.0.2", port=7687, container_id="a" * 64, network_id="b" * 64)
            ns = dict(case=case, initialization_preflight=lambda: {}, initialization_verify_sources=lambda: {},
                      Path=pathlib.Path, os=SimpleNamespace(environ=env),
                      read_json=lambda path, limit: reads.append(str(path)) or network,
                      JoinGuards=lambda *args: seen.append(dict(env)))
            exec(prefix, ns)
            with self.subTest(case=case):
                if case == "positive":
                    self.assertEqual(reads, [])
                    self.assertEqual(env["ARENA_WORKFLOW_NEO4J_URI"], "UNITONLY-stale")
                else:
                    self.assertEqual(reads, ["/network/manifest.json"])
                    self.assertEqual(seen[0]["ARENA_WORKFLOW_NEO4J_URI"], "bolt://172.30.0.2:7687")
                    self.assertEqual(seen[0]["ARENA_WORKFLOW_NEO4J_DATABASE"], "workflowtest")


class InitializationStaticGuards(unittest.TestCase):
    def test_directory_inventory_is_bounded_readonly_and_does_not_follow_links(self):
        import os
        import stat
        import tempfile
        import time
        from types import SimpleNamespace

        fn = isolated(HARNESS, {"initialization_directory_inventory"})["initialization_directory_inventory"]
        projected = SimpleNamespace(**{k: getattr(os, k) for k in dir(os)})
        projected.fstatvfs = lambda fd: SimpleNamespace(f_flag=os.ST_RDONLY)
        fn.__globals__.update(os=projected, stat=stat, time=time)
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root, "selected")
            path.mkdir()
            (path / "empty.py").write_bytes(b"")
            (path / "link.py").symlink_to(path / "empty.py")
            budget = dict(deadline=time.monotonic() + 5, entries=0, entry_limit=2)
            result = fn(str(path), budget)
            self.assertEqual(result["path"], str(path))
            self.assertEqual([row["name"] for row in result["entries"]], ["empty.py", "link.py"])
            self.assertTrue(stat.S_ISREG(result["entries"][0]["mode"]))
            self.assertEqual(result["entries"][0]["size"], 0)
            self.assertTrue(stat.S_ISLNK(result["entries"][1]["mode"]))
            self.assertEqual(budget["entries"], 2)
            with self.assertRaisesRegex(AssertionError, "entry ceiling"):
                fn(str(path), budget)
            alias = pathlib.Path(root, "alias")
            alias.symlink_to(path, target_is_directory=True)
            with self.assertRaises((AssertionError, OSError)):
                fn(str(alias), dict(budget, entries=0))
            with self.assertRaises(AssertionError):
                fn(str(path), dict(budget, entries=0, deadline=0))
            projected.fstatvfs = lambda fd: SimpleNamespace(f_flag=0)
            with self.assertRaises(AssertionError):
                fn(str(path), dict(budget, entries=0))

    def test_empty_python_source_has_real_identity_but_empty_native_is_refused(self):
        import hashlib
        import os
        import stat
        import tempfile
        import time
        from types import SimpleNamespace

        fn = isolated(HARNESS, {"initialization_physical_file"})["initialization_physical_file"]
        # UNITONLY readonly projection; descriptors, empty bytes and hashes are real.
        projected = SimpleNamespace(**{k: getattr(os, k) for k in dir(os)})
        projected.fstatvfs = lambda fd: SimpleNamespace(f_flag=os.ST_RDONLY)
        fn.__globals__.update(os=projected, stat=stat, time=time, hashlib=hashlib)
        with tempfile.TemporaryDirectory() as root:
            budget = dict(bytes=0, files=0, deadline=time.monotonic() + 5)
            for name in ("__init__.py", "__init__.pyi"):
                path = pathlib.Path(root, name)
                path.write_bytes(b"")
                with self.subTest(name=name):
                    row, raw = fn(str(path), budget, source=True)
                    self.assertEqual(raw, b"")
                    self.assertEqual(row["size"], 0)
                    self.assertEqual(row["sha256"], hashlib.sha256(b"").hexdigest())
                    self.assertEqual(fn(str(path), budget), row)
                    self.assertEqual(budget["bytes"], 0)
                    self.assertEqual(budget["files"], 0)
                    with self.assertRaises(AssertionError):
                        fn(str(path), budget, binary=True)
            for name in ("native.so", "python3", "data.json"):
                path = pathlib.Path(root, name)
                path.write_bytes(b"")
                for options in ({}, {"binary": True}, {"source": True}):
                    with self.subTest(name=name, options=options), self.assertRaises(AssertionError):
                        fn(str(path), budget, **options)

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
        self.assertEqual(fn("torchgen", pure + "torchgen/__init__.py", False), "torchgen")
        self.assertEqual(fn("matplotlib", pure + "matplotlib/__init__.py", False), "matplotlib")
        physx = "/workspaces/isaaclab_arena/submodules/IsaacLab/source/isaaclab_physx/isaaclab_physx"
        self.assertEqual(fn("isaaclab_physx.sim", physx + "/sim/__init__.py", False), "isaaclab_physx")
        with self.assertRaises(AssertionError):
            fn("torchgen", pure + "torchgen_shadow/__init__.py", False)
        for name, origin, preloaded in (
            ("openai", yaml + "openai/__init__.py", False),
            ("yaml", pure + "yaml/__init__.py", False),
            ("warp", pure + "warp/../other.py", False),
            ("warp", pure + "warp/__init__.py", True),
            ("warp", pure + "warp_shadow/__init__.py", False),
            ("unknown", "/unapproved/unknown/__init__.py", False),
            ("unknown", pure + "warp/__init__.py", False),
            ("warp", pure + "warp/__init__.py", 0),
        ):
            with self.assertRaises(AssertionError):
                fn(name, origin, preloaded)

    def test_observed_toml_root_is_admitted_by_both_maps_only(self):
        from types import SimpleNamespace

        root = "/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/toml"
        origin = isolated(HARNESS, {"initialization_origin"})["initialization_origin"]
        self.assertEqual(origin("toml.decoder", root + "/decoder.py", False), "toml")
        tree = ast.parse(HARNESS.read_text())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "InitializationAdmission")
        init = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
        nodes = [node for node in init.body if ast.unparse(node).startswith(("self.roots =", "self.roots.update("))]
        admission = SimpleNamespace()
        namespace = dict(self=admission, DEPENDENCY_ROOTS=["/isaac-sim/kit/python/lib/python3.12/site-packages"],
                         E1_YAML_ROOT="/isaac-sim/exts/omni.pip.compute/pip_prebundle/yaml")
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(HARNESS), "exec"), namespace)
        self.assertEqual(admission.roots["toml"], root)
        for path in (root + "_shadow/__init__.py", root + "/../other.py",
                     "/isaac-sim/kit/python/lib/python3.12/site-packages/toml/__init__.py"):
            with self.subTest(path=path), self.assertRaises(AssertionError):
                origin("toml", path, False)
        with self.assertRaises(AssertionError):
            origin("toml", root + "/__init__.py", True)

    def test_init_server_evidence_is_separate_from_four_role_proof(self):
        import hashlib

        ns = isolated(HARNESS, {"initialization_verify_proof", "initialization_origin",
                                "initialization_evidence_names", "initialization_required_evidence"})
        ns["INITIALIZATION_ROLES"] = ("init-server", "init-generate", "init-refine", "init-assess")
        proof, junit = unitonly_proof()
        proof["initialization_roles"] = proof["initialization_roles"][:1]
        proof.update(case="init-server", process_pids=[100], scope="init-server preparation only",
                     all_roles_complete=False)
        junit = junit.replace(b"test_initialization_positive", b"test_initialization_init_server")
        proof["junit_sha256"] = hashlib.sha256(junit).hexdigest()
        self.assertTrue(ns["initialization_verify_proof"](proof, junit, "init-server"))
        expected = {"client-proof.json", "pytest.xml", "collection-ready", "initialization-harness.json",
                    "initialization-init-server.json", "initialization-init-server-output.json", "join-launch-100.json"}
        self.assertEqual(ns["initialization_evidence_names"]("init-server", proof), expected)
        self.assertEqual(ns["initialization_required_evidence"]("init-server", proof), expected)
        with self.assertRaises(AssertionError):
            ns["initialization_verify_proof"](proof, junit, "positive")
        for changes in ({"all_roles_complete": True}, {"readiness_observed": True},
                        {"process_pids": [100, 101]}, {"scope": "full S2 suite"}):
            with self.subTest(changes=changes), self.assertRaises(AssertionError):
                ns["initialization_verify_proof"](dict(proof, **changes), junit, "init-server")

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
            start_ticks=123,
            boot="UNITONLY",
            pid_namespace="pid:[UNITONLY]",
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
            initialization_server_identity={key: server[key] for key in (
                "pid", "parent_pid", "pgid", "sid", "start_ticks", "boot", "pid_namespace")},
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
            initialization_owned_server=lambda pid: guard.initialization_server_identity,
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
        self.assertEqual(identities, [guard.initialization_server_identity],
                         "server signal must check the independently retained launch identity")
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


def test_initialization_init_server():
    """One cold server preparation only; no installed readiness or later roles."""
    import workflow_graphql_execution_join_harness as harness

    assert harness.ACTIVE.initialization_case == "init-server"
    row = harness.initialization_fresh("init-server")
    harness.ACTIVE.initialization_result = dict(initialization_roles=[row])


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
