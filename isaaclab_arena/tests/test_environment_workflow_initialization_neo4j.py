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
        self.assertLess(text.index("initialization_cache_create"), text.index("initialization_preparation"))
        self.assertLess(text.index("InitializationAdmission("), text.index("initialization_preparation"))
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
        names.__globals__["INITIALIZATION_ROLES"] = ("init-server", "init-generate", "init-refine", "init-assess")
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
            {"test_initialization_positive", "test_initialization_failure", "test_initialization_timeout"} <= tests
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
            pid=202, parent_pid=101, pgid=202, sid=202, start_ticks=123, boot="UNITONLY", pid_namespace="pid:[UNITONLY]"
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
            time=SimpleNamespace(monotonic=lambda: now[0], sleep=lambda delay: now.__setitem__(0, now[0] + delay)),
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
        self.assertIn(202, [row[0] for row in signals], "separate installed server survived cold-role deadline")
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
            ("positive", "harness", ns["initialization_collect"], "S2 cold role deadline"),
            ("timeout", "server", ns["initialization_collect"], "S2 cold role deadline"),
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

        ns = isolated(HARNESS, {
            "initialization_collect", "initialization_monitor_stall", "initialization_contain_launcher"
        })
        now, signals, waits, closed = [10.0], [], [], []
        server = dict(pid=202, pgid=202, sid=202, parent_pid=101,
                      case="timeout", before_owner_construction=True, observed_at=0.0)
        launch = ["api-launch"]
        guard = SimpleNamespace(initialization_case="timeout", role="harness",
                                spawn_records=[dict(pid=101, bootstrap_argv=[0] * 6 + launch)],
                                initialization_group_absent=lambda pid: False)

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
        exec(compile(ast.Module(body=[node for node in ast.parse(HARNESS.read_text()).body
                                     if isinstance(node, ast.FunctionDef) and node.name in ns],
                                type_ignores=[]), str(HARNESS), "exec"), ns)
        ns.update(ACTIVE=guard, LAUNCH=launch, Path=FakePath, contextlib=contextlib, signal=signal,
                  selectors=SimpleNamespace(DefaultSelector=Selector, EVENT_READ=1),
                  os=SimpleNamespace(set_blocking=lambda *args: None,
                                     killpg=lambda pid, sig: signals.append((pid, sig, now[0]))),
                  time=SimpleNamespace(monotonic=lambda: now[0],
                                       sleep=lambda delay: now.__setitem__(0, now[0] + delay)),
                  read_json=lambda path: (server if "pre-readiness" in path.value else
                                          dict(server, bootstrap_argv=[0] * 6 + ["api-serve"])),
                  role_for=lambda argv: "server", live_identity=lambda row: row,
                  initialization_owned_server=lambda pid: server,
                  write_evidence=lambda *args: self.fail("unreaped checkpoint cannot produce success evidence"))
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
            physical_read_budget=dict(bytes=2048, files=1, deadline=1),
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
        proof["host_containment_required"] = False
        proof["initialization_server_cleanup"] = dict(
            status="contained", host_containment_required=False, launcher_pid=99, server_pid=100, group_reap_seconds=1
        )
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
