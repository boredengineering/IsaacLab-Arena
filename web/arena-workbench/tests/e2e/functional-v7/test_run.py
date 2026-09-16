# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Bounded Docker lifecycle fault tests; never use the actual daemon."""
import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("f0_run", Path(__file__).with_name("run.py"))
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class FrontendDependencyTests(unittest.TestCase):
    cid = "d" * 64
    root = Path("/clone")
    image = "sha256:" + "e" * 64

    def setUp(self):
        self.live = [
            {"Id": "a" * 64, "Image": self.image, "Mounts": [
                {"Type": "bind", "Source": "/host/clone", "Destination": "/clone"}]},
            {"Id": "b" * 64, "Image": self.image, "Mounts": [
                {"Type": "bind", "Source": "/host/clone", "Destination": "/workspaces/isaaclab_arena"}]},
        ]
        self.frontend = {"Id": self.cid, "Image": self.image, "Status": "exited", "Running": False,
                         "Mounts": [
                             {"Type": "bind", "Source": "/host/clone/web/arena-workbench", "Destination": "/app"},
                             {"Type": "volume", "Source": "/volumes/installed_deps", "Name": "installed_deps", "Destination": "/app/node_modules"}]}
        self.calls = []

    def daemon(self, *args):
        self.calls.append(args)
        if args[:2] == ("image", "ls"):
            return "mcr.microsoft.com/playwright:v1.58.2-noble ignored"
        if args[0] == "inspect":
            self.assertEqual(args[:2], ("inspect", "--format"))
            self.assertEqual(args[3:], (self.cid,))
            return json.dumps(self.frontend)
        raise AssertionError(args)

    def discover(self, browser=True, identity=None):
        import inspect
        self.assertIn("frontend_dependency_container", inspect.signature(runner.discover).parameters,
                      "Explicit stopped frontend dependency selection is missing")
        with mock.patch.object(runner, "running_metadata", return_value=self.live), \
                mock.patch.object(runner, "docker", side_effect=self.daemon), \
                mock.patch.object(runner, "image_metadata", return_value={"Id": self.image}):
            return runner.discover(self.root, browser, frontend_dependency_container=identity or self.cid)

    def test_explicit_selection_rejects_unverified_origin_without_fallback(self):
        import copy
        original = copy.deepcopy(self.frontend)
        cases = [
            ("replaced", {"Id": "f" * 64}, "identity"),
            ("running", {"Status": "running", "Running": True}, "stopped"),
            ("created", {"Status": "created"}, "stopped"),
            ("missing state", {"Running": None}, "stopped"),
            ("mutable image", {"Image": "node:latest"}, "image"),
            ("wrong clone", {"Mounts": [dict(original["Mounts"][0], Source="/other/web/arena-workbench"), original["Mounts"][1]]}, "clone"),
            ("wrong type", {"Mounts": [dict(original["Mounts"][0], Type="volume"), original["Mounts"][1]]}, "clone"),
            ("missing volume", {"Mounts": original["Mounts"][:1]}, "volume"),
            ("duplicate volume", {"Mounts": original["Mounts"] + [original["Mounts"][1]]}, "volume"),
            ("second volume", {"Mounts": original["Mounts"] + [dict(original["Mounts"][1], Name="other")]}, "volume"),
            ("invalid name", {"Mounts": [original["Mounts"][0], dict(original["Mounts"][1], Name="bad,inject")]}, "volume"),
        ]
        for name, changes, error in cases:
            with self.subTest(name=name):
                self.frontend = dict(original, **changes)
                with self.assertRaisesRegex(AssertionError, error):
                    self.discover()
        self.frontend = original
        with mock.patch.object(runner, "running_metadata", return_value=self.live), \
                mock.patch.object(runner, "docker", side_effect=RuntimeError("unknown exact ID")) as daemon:
            with self.assertRaisesRegex(RuntimeError, "unknown exact ID"):
                runner.discover(self.root, True, frontend_dependency_container=self.cid)
            self.assertEqual(daemon.call_count, 1)

    def test_explicit_id_format_and_nonfrontend_scope_fail_before_metadata(self):
        with mock.patch.object(runner, "running_metadata") as live, mock.patch.object(runner, "docker") as daemon:
            for identity in ("frontend-name", self.cid[:12], self.cid.upper(), " " + self.cid, ""):
                with self.subTest(identity=identity), self.assertRaisesRegex(AssertionError, "64"):
                    runner.discover(self.root, True, frontend_dependency_container=identity)
            with self.assertRaisesRegex(AssertionError, "browser"):
                runner.discover(self.root, False, frontend_dependency_container=self.cid)
            live.assert_not_called()
            daemon.assert_not_called()

    def test_explicit_projection_excludes_env_commands_and_arbitrary_mounts(self):
        self.discover()
        template = next(c[2] for c in self.calls if c[0] == "inspect")
        for forbidden in (".Config", ".Args", ".Path", "json .State}}", "json .Mounts", "json .}}"):
            self.assertNotIn(forbidden, template)
        self.assertIn('.State.Status', template)
        self.assertIn('.State.Running', template)
        self.assertIn('(eq $m.Destination "/app")', template)
        self.assertIn('(eq $m.Destination "/app/node_modules")', template)

    def test_default_runtime_and_legacy_browser_discovery_remain_unchanged(self):
        with mock.patch.object(runner, "running_metadata", return_value=self.live), \
                mock.patch.object(runner, "docker", side_effect=self.daemon), \
                mock.patch.object(runner, "image_metadata", return_value={"Id": self.image}):
            core = runner.discover(self.root, False)
            self.assertEqual(core, {"host_root": "/host/clone", "runtime_image": self.image, "runtime_id": "b" * 64})
            self.assertEqual(self.calls, [])
            with self.assertRaisesRegex(AssertionError, "Cannot identify installed"):
                runner.discover(self.root, True)
            self.live.append(self.frontend)
            legacy = runner.discover(self.root, True)
            self.assertEqual(legacy["deps"], "installed_deps")
            self.assertNotIn("frontend_dependency_origin", legacy)
            self.assertFalse(any(c[0] == "inspect" for c in self.calls))

    def test_frontend_only_discovery_needs_neither_runtime_nor_browser_image(self):
        self.assertTrue(hasattr(runner, "discover_frontend"), "Frontend-only discovery is missing")
        with mock.patch.object(runner, "running_metadata", return_value=self.live[:1]), \
                mock.patch.object(runner, "docker", side_effect=self.daemon), \
                mock.patch.object(runner, "image_metadata", side_effect=AssertionError("No image selection during dependency discovery")):
            result = runner.discover_frontend(self.root, frontend_dependency_container=self.cid)
        self.assertEqual(result["host_root"], "/host/clone")
        self.assertEqual(result["deps"], "installed_deps")
        self.assertEqual(result["frontend_dependency_origin"], self.frontend)
        self.assertNotIn("runtime_image", result)
        self.assertNotIn("browser_image", result)

    def test_typecheck_and_build_forward_explicit_dependency_without_browser_discovery(self):
        import frontend_checks
        import inspect
        import run
        self.assertIn("frontend_dependency_container", inspect.signature(frontend_checks.main).parameters)
        for mode in ("typecheck", "build"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                script = Path(directory) / "web/arena-workbench/tests/e2e/functional-v7/frontend_checks.py"
                original = run.OwnedRun
                records = []
                def owned(output, token):
                    value = original(output, token, lambda *args: "")
                    records.append(value)
                    return value
                with mock.patch.object(frontend_checks, "__file__", str(script)), \
                        mock.patch.object(run, "OwnedRun", side_effect=owned), \
                        mock.patch.object(run, "discover", side_effect=AssertionError("must not discover API/browser")) as broad, \
                        mock.patch.object(run, "discover_frontend", side_effect=RuntimeError("selection seam")) as selected:
                    self.assertEqual(frontend_checks.main(mode, True, frontend_dependency_container=self.cid), 1)
                selected.assert_called_once_with(Path(directory), frontend_dependency_container=self.cid)
                broad.assert_not_called()
                self.assertEqual(records[0].proof["failure"], "RuntimeError: selection seam")
                self.assertTrue(records[0].proof["cleanup_verified"])

    def test_browser_entry_forwards_explicit_id_before_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "web/arena-workbench/tests/e2e/functional-v7/run.py"
            with mock.patch.object(runner, "__file__", str(script)), \
                    mock.patch.object(runner, "discover", side_effect=RuntimeError("discovery seam")) as selected, \
                    mock.patch.object(runner, "finalize"), mock.patch.object(runner, "docker") as daemon:
                try:
                    self.assertEqual(runner.main(["--browser", "--frontend-dependency-container", self.cid]), 1)
                except SystemExit:
                    self.fail("Browser CLI is missing explicit frontend dependency selection")
                selected.assert_called_once_with(Path(directory), True, frontend_dependency_container=self.cid)
                daemon.assert_not_called()

    def test_explicit_stopped_frontend_is_bound_to_exact_clone_and_recorded(self):
        value = self.discover()
        self.assertEqual(value["deps"], "installed_deps")
        self.assertEqual(value["frontend_dependency_origin"], self.frontend)
        self.assertIn("mutable", value["frontend_dependency_trust"])
        self.assertEqual(value["runtime_id"], "b" * 64)
        self.assertEqual(len([c for c in self.calls if c[0] == "inspect"]), 1)


class LifecycleTests(unittest.TestCase):
    def test_authoring_requires_explicit_browser_and_v7_before_discovery(self):
        for arguments in (['--profile', 'authoring-v1'], ['--profile', 'authoring-v1', '--browser']):
            with self.subTest(arguments=arguments), mock.patch.object(runner, 'discover') as discover:
                with self.assertRaises(SystemExit) as raised:
                    runner.main(arguments)
                self.assertEqual(raised.exception.code, 2)
                discover.assert_not_called()

    def test_runtime_override_requires_immutable_identity_and_provenance_before_inspect(self):
        discovered = {"runtime_image": "sha256:" + "b" * 64, "runtime_id": "c" * 64}
        with mock.patch.object(runner, "docker", side_effect=AssertionError("unexpected inspect")):
            for image, manifest in (("latest", None), ("sha256:" + "a" * 64, None), (None, "/tmp/provision.json")):
                with self.subTest(image=image), self.assertRaisesRegex(AssertionError, "override"):
                    runner.select_runtime(discovered, image, manifest)
        self.assertEqual(discovered["runtime_image"], "sha256:" + "b" * 64)

    def test_wheel_preflight_is_bounded_and_rejects_links_and_hooks(self):
        import io
        import zipfile
        for name, mode in (("neo4j/../outside.py", 0o100644), ("neo4j/link.py", 0o120777),
                           ("neo4j/start.pth", 0o100644), ("other/start.py", 0o100644)):
            with self.subTest(name=name):
                data = io.BytesIO()
                with zipfile.ZipFile(data, "w") as archive:
                    entry = zipfile.ZipInfo(name)
                    entry.external_attr = mode << 16
                    archive.writestr(entry, "unsafe")
                with self.assertRaisesRegex(AssertionError, "Wheel"):
                    runner.wheel_entries(data.getvalue(), "neo4j", "6.2.0")

    def test_runtime_override_refuses_linked_manifest_before_daemon_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outside.json").write_text("{}")
            (root / "manifest.json").symlink_to(root / "outside.json")
            with mock.patch.object(runner, "docker") as daemon:
                with self.assertRaises((AssertionError, OSError, ValueError)):
                    runner.select_runtime({"runtime_image": "sha256:" + "b" * 64, "runtime_id": "c" * 64},
                                          "sha256:" + "a" * 64, root / "manifest.json")
                daemon.assert_not_called()

    def test_wheel_record_hash_coverage_and_archive_budget(self):
        import base64
        import hashlib
        import io
        import zipfile
        metadata = "neo4j-6.2.0.dist-info/"
        files = {"neo4j/__init__.py": b"# inert fixture", metadata + "METADATA": b"Name: neo4j\nVersion: 6.2.0\n"}
        record = "".join(name + ",sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=") + "," + str(len(data)) + "\n"
                         for name, data in files.items()) + metadata + "RECORD,,\n"
        files[metadata + "RECORD"] = record.encode()
        def archive(values):
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as zipped:
                for name, content in values.items():
                    zipped.writestr(name, content)
            return data.getvalue()
        self.assertEqual(runner.wheel_entries(archive(files), "neo4j", "6.2.0"), files)
        tampered = dict(files, **{"neo4j/__init__.py": b"# modified"})
        with self.assertRaisesRegex(AssertionError, "Wheel RECORD mismatch"):
            runner.wheel_entries(archive(tampered), "neo4j", "6.2.0")
        with self.assertRaisesRegex(AssertionError, "Wheel archive byte budget"):
            runner.wheel_entries(b"x" * (2 * 1024 * 1024 + 1), "neo4j", "6.2.0")

    def test_self_test_explicitly_covers_all_approved_python_suites(self):
        import self_test
        self.assertEqual(self_test.UNIT_SUITES, (
            "test_run.py", "test_confined_io.py", "test_api.py", "test_check_proof.py",
            "test_producers.py", "test_authoring_proof.py", "test_manual_research.py", "test_metadata_gitpython.py"))

    def test_missing_immutable_package_preserves_actual_probe_without_export(self):
        probe = {"schema_version": 1, "status": "passed", "uid": 1000, "egress_denied": True,
                 "before_package_imports": True, "errno": 101,
                 "roots": ["/isaac-sim/kit/python/lib/python3.12/site-packages"], "packages": []}
        with tempfile.TemporaryDirectory() as directory:
            owned = runner.OwnedRun(directory, "arena-f0-probe", lambda *args: "a" * 64)
            result = mock.Mock(returncode=0, stdout=json.dumps(probe).encode(), stderr=b"")
            with mock.patch.object(runner, "image_metadata", return_value={"Id": "sha256:" + "b" * 64}), \
                    mock.patch.object(runner, "verify_container"), mock.patch.object(runner, "docker"), \
                    mock.patch.object(runner.subprocess, "run", return_value=result) as calls:
                with self.assertRaisesRegex(AssertionError, "Immutable Neo4j package unavailable"):
                    runner.obtain_dependency(owned, {"runtime_image": "sha256:" + "b" * 64,
                                                     "runtime_id": "c" * 64}, Path(directory) / "deps")
            self.assertEqual(calls.call_count, 1, "Missing package must not invoke archive export")
            saved = json.loads((Path(directory) / "dependency-probe.json").read_text())
            self.assertEqual(saved["probe"], probe)
            self.assertEqual(saved["source_container"], "a" * 64)
            self.assertEqual(saved["discovered_runtime_id"], "c" * 64)
            self.assertFalse((Path(directory) / "deps").exists())

    def test_backend_cli_rejects_unapproved_selections_before_docker(self):
        import backend_checks
        with mock.patch.object(runner, "discover", side_effect=AssertionError("must not discover")):
            for names in (["--live"], ["/tmp/test.py"], ["isaaclab_arena/tests/test_workbench_editor_revisions.py"] * 2):
                with self.subTest(names=names), self.assertRaisesRegex(ValueError, "approved backend"):
                    backend_checks.selection(names)
        self.assertEqual(backend_checks.selection([]), list(__import__("stage").BACKEND_TESTS))

    def test_frontend_commands_require_explicit_gate_and_have_no_install(self):
        import frontend_checks
        for mode in ("typecheck", "build"):
            with self.assertRaisesRegex(ValueError, "explicit"):
                frontend_checks.command(mode, False)
        self.assertEqual(frontend_checks.command("typecheck", True), ["npm", "run", "typecheck"])
        self.assertEqual(frontend_checks.command("build", True),
                         ["npm", "run", "build", "--", "--outDir", "/evidence/dist", "--configLoader", "runner"])
        with self.assertRaises(ValueError):
            frontend_checks.command("install", True)

    def test_import_is_side_effect_free(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("Import executed subprocess")), \
                mock.patch.object(Path, "write_text", side_effect=AssertionError("Import wrote file")), \
                mock.patch.object(Path, "mkdir", side_effect=AssertionError("Import created directory")):
            loaded = importlib.util.module_from_spec(SPEC)
            SPEC.loader.exec_module(loaded)

    def test_create_id_persisted_before_verification_and_replacement_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            removed = []
            def command(*args):
                if args[0] == "create":
                    return "a" * 64
                if args[0] == "ps":
                    return "b" * 64
                if args[0] == "inspect":
                    info = {"Id": "b" * 64, "Name": "/test-api", "Label": "test"}
                    return json.dumps(info) if "--format" in args else json.dumps([info])
                if args[0] == "rm":
                    removed.append(args[-1])
                return ""
            run = runner.OwnedRun(directory, "test", command)
            cid = run.create("api", "sha256:test", "python3", [], [])
            record = json.loads((Path(directory) / "ownership.json").read_text())
            self.assertEqual(record.get("created_ids"), {"test-api": cid})
            self.assertEqual(record["containers"], [])
            self.assertFalse(run.cleanup())
            self.assertEqual(removed, [])

    def test_discovery_requests_only_projected_metadata(self):
        calls = []
        def command(*args):
            calls.append(args)
            if args[0] == "ps":
                return "a" * 64
            if args[0] == "inspect":
                self.assertIn("--format", args, "Full inspect requests credential metadata")
                template = args[args.index("--format") + 1]
                self.assertNotIn(".Config.Env", template)
                self.assertNotIn("json .Config", template)
                self.assertNotIn("json .HostConfig", template)
                raise RuntimeError("projection checked")
            raise AssertionError(args)
        with mock.patch.object(runner, "docker", command):
            with self.assertRaisesRegex(RuntimeError, "projection checked"):
                runner.discover(Path("/clone"), False)

    def test_dependency_archive_rejects_links_and_unexpected_entries_before_write(self):
        import io
        import tarfile
        for name, kind, error in (("neo4j/link.py", tarfile.SYMTYPE, "Dependency link/extended metadata denied"),
                                  ("neo4j/hard.py", tarfile.LNKTYPE, "Dependency link/extended metadata denied"),
                                  ("neo4j/.env", tarfile.REGTYPE, "^$"),
                                  ("neo4j/key.pem", tarfile.REGTYPE, "Unexpected dependency file"),
                                  ("other/file.py", tarfile.REGTYPE, "^$"),
                                  ("neo4j/../../outside.py", tarfile.REGTYPE, "^$"),
                                  ("neo4j/pipe.py", tarfile.FIFOTYPE, "Dependency special entry denied")):
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as directory:
                data = io.BytesIO()
                with tarfile.open(fileobj=data, mode="w") as archive:
                    root = tarfile.TarInfo("neo4j")
                    root.type = tarfile.DIRTYPE
                    archive.addfile(root)
                    # Otherwise valid package: no duplicate-root or missing-init guard
                    # may mask the individual path/type/suffix guard under test.
                    archive.addfile(tarfile.TarInfo("neo4j/__init__.py"))
                    entry = tarfile.TarInfo(name)
                    entry.type = kind
                    if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                        entry.linkname = "/outside"
                    archive.addfile(entry)
                target = Path(directory) / "deps"
                with self.assertRaisesRegex(AssertionError, error):
                    runner.extract_dependency(data.getvalue(), target)
                self.assertFalse(target.exists(), "Invalid archive wrote dependency bytes")

    def test_create_ack_survives_evidence_save_failure_in_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            run = runner.OwnedRun(directory, "test", lambda *args: "a" * 64)
            with mock.patch.object(run, "save", side_effect=[None, OSError("disk full")]):
                with self.assertRaises(OSError):
                    run.create("api", "sha256:test", "python3", [], [])
            self.assertEqual(run.proof["created_ids"], {"test-api": "a" * 64})
            self.assertFalse(run.proof["verified_isolation"]["test-api"])

    def test_final_hash_refuses_symlink_without_reading_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outside").write_text("secret marker")
            (root / "link.py").symlink_to(root / "outside")
            changed, errors = runner.compare_source(root, {"link.py": "irrelevant"})
            self.assertEqual(changed, ["link.py"])
            self.assertEqual(errors, ["link.py"])

    def test_finalization_preserves_failed_evidence_and_reports_hash_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = runner.OwnedRun(root, "test", lambda *args: "")
            run.proof.update(status="passed", source_sha256={"missing.py": "nope"})
            (root / "evidence").mkdir()
            (root / "outside").write_text("never hash through the evidence link")
            (root / "evidence/result.json").symlink_to(root / "outside")
            runner.finalize(run, root)
            self.assertEqual(run.proof["status"], "failed")
            self.assertTrue((root / "evidence/result.json").is_symlink())
            self.assertIn("evidence/result.json", run.proof["evidence_errors"])
            self.assertEqual(json.loads((root / "run-proof.json").read_text())["status"], "failed")

    def test_missing_evidence_wait_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def command(*args):
                calls.append(args)
                self.assertIn("--format", args)
                return '{"Running":true}'
            run = runner.OwnedRun(directory, "test", command)
            with self.assertRaisesRegex(AssertionError, "Timed out"):
                runner.wait_file(run, "a" * 64, Path(directory) / "missing", timeout=0)
            self.assertEqual(len(calls), 1)

    def test_signal_failure_cleans_and_preserves_failed_proof(self):
        import signal
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "web/arena-workbench/tests/e2e/functional-v7/run.py"
            records = []
            original_class = runner.OwnedRun
            original_handler = signal.getsignal(signal.SIGTERM)
            def owned(output, token):
                run = original_class(output, token, lambda *args: "")
                records.append(run)
                return run
            def interrupted(*args):
                signal.raise_signal(signal.SIGTERM)
            with mock.patch.object(runner, "__file__", str(script)), \
                    mock.patch.object(runner, "OwnedRun", side_effect=owned), \
                    mock.patch.object(runner, "discover", side_effect=interrupted):
                self.assertEqual(runner.main([]), 1)
            self.assertEqual(signal.getsignal(signal.SIGTERM), original_handler)
            proof = json.loads((records[0].output / "run-proof.json").read_text())
            self.assertEqual(proof["status"], "failed")
            self.assertEqual(proof["remaining_owned"], [])
            self.assertIn("InterruptedError", proof["failure"])

    def test_cleanup_continues_after_log_failure_and_evidence_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            removed = []
            def command(*args):
                if args[0] == "ps":
                    return "" if removed else "a" * 64
                if args[0] == "inspect":
                    return json.dumps({"Id": "a" * 64, "Name": "/test-api", "Label": "test"})
                if args[0] == "logs":
                    raise TimeoutError("log daemon unavailable")
                if args[0] == "rm":
                    removed.append(args[-1])
                    return ""
                raise AssertionError(args)
            run = runner.OwnedRun(directory, "test", command)
            run.candidates.append("test-api")
            run.proof["created_ids"]["test-api"] = "a" * 64
            run.proof["verified_isolation"]["test-api"] = True
            with mock.patch.object(run, "save", side_effect=OSError("disk full")):
                self.assertFalse(run.cleanup())
            self.assertEqual(removed, ["a" * 64])
            self.assertEqual(run.proof["remaining_owned"], [])
            self.assertEqual(len(run.proof["cleanup_errors"]), 2)

    def test_dependency_archive_accepts_source_only_package(self):
        import io
        import tarfile
        with tempfile.TemporaryDirectory() as directory:
            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode="w") as archive:
                entry = tarfile.TarInfo("neo4j")
                entry.type = tarfile.DIRTYPE
                archive.addfile(entry)
                entry = tarfile.TarInfo("neo4j/__init__.py")
                content = b"# inert test fixture\n"
                entry.size = len(content)
                archive.addfile(entry, io.BytesIO(content))
            target = Path(directory) / "deps"
            hashes = runner.extract_dependency(data.getvalue(), target)
            self.assertEqual((target / "neo4j/__init__.py").read_bytes(), content)
            self.assertEqual(set(hashes), {"neo4j/__init__.py"})

    def test_image_metadata_projection_excludes_credentials(self):
        def command(*args):
            self.assertEqual(args[:3], ("image", "inspect", "--format"))
            self.assertEqual(args[3], runner.IMAGE_FORMAT)
            self.assertNotIn(".Config.Env", args[3])
            self.assertNotIn("json .Config", args[3])
            return json.dumps({"Id": "sha256:" + "a" * 64, "Volumes": None})
        self.assertEqual(runner.image_metadata("approved", command)["Id"], "sha256:" + "a" * 64)

    def test_create_has_strict_isolation_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            run = runner.OwnedRun(directory, "test", lambda *args: calls.append(args) or "a" * 64)
            run.create("api", "sha256:test", "python3", [], [])
            command = calls[0]
            for flag in ("--pull=never", "--network=none", "--read-only", "--user=1000:1000",
                         "--cap-drop=ALL", "--security-opt=no-new-privileges"):
                self.assertIn(flag, command)
            self.assertNotIn("--gpus", command)
            self.assertNotIn("--privileged", command)

    def test_create_is_registered_before_ambiguous_timeout(self):
        self.assertTrue(hasattr(runner, "OwnedRun"), "Missing registered-before-create lifecycle")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            def docker(*args):
                if args[0] == "create":
                    record = json.loads((output / "ownership.json").read_text())
                    self.assertEqual(record["candidates"], ["test-api"])
                    self.assertIn("arena.functional-v7=test", args)
                    raise TimeoutError("accepted by daemon, CLI timed out")
                raise AssertionError(args)
            run = runner.OwnedRun(output, "test", docker)
            with self.assertRaises(TimeoutError):
                run.create("api", "sha256:test", "python3", [], [])
            self.assertEqual(run.candidates, ["test-api"])

    def test_cleanup_removes_only_exact_owned_identity_after_timeout(self):
        self.assertTrue(hasattr(runner.OwnedRun, "cleanup"), "Missing verified cleanup")
        with tempfile.TemporaryDirectory() as directory:
            removed = []
            info = {"Id": "immutable-id", "Name": "/test-api", "Label": "test"}
            def command(*args):
                if args[0] == "ps":
                    return "" if removed else "immutable-id"
                if args[0] == "inspect":
                    return json.dumps(info)
                if args[0] == "rm":
                    self.assertEqual(args, ("rm", "-f", "immutable-id"))
                    removed.append(args[-1])
                    return ""
                if args[0] == "logs":
                    return "bounded log"
                raise AssertionError(args)
            run = runner.OwnedRun(directory, "test", command)
            run.candidates = ["test-api"]
            self.assertTrue(run.cleanup())
            self.assertEqual(removed, ["immutable-id"])
            self.assertEqual(run.proof["remaining_owned"], [])

    def test_cleanup_refuses_same_label_replacement_of_known_id(self):
        with tempfile.TemporaryDirectory() as directory:
            removed = []
            def command(*args):
                if args[0] == "ps":
                    return "replacement"
                if args[0] == "inspect":
                    return json.dumps({"Id": "replacement", "Name": "/test-api", "Label": "test"})
                if args[0] == "rm":
                    removed.append(args[-1])
                return ""
            run = runner.OwnedRun(directory, "test", command)
            run.candidates = ["test-api"]
            run.proof["containers"] = [{"name": "/test-api", "id": "original"}]
            self.assertFalse(run.cleanup())
            self.assertEqual(removed, [])

    def test_cleanup_unknown_is_failure(self):
        self.assertTrue(hasattr(runner.OwnedRun, "cleanup"), "Missing verified cleanup")
        with tempfile.TemporaryDirectory() as directory:
            def denied(*args):
                raise TimeoutError("daemon unavailable")
            run = runner.OwnedRun(directory, "test", denied)
            run.candidates = ["test-api"]
            self.assertFalse(run.cleanup())
            self.assertIsNone(run.proof["remaining_owned"])

    def test_cleanup_refuses_foreign_ownership(self):
        self.assertTrue(hasattr(runner.OwnedRun, "cleanup"), "Missing verified cleanup")
        with tempfile.TemporaryDirectory() as directory:
            def command(*args):
                if args[0] == "ps":
                    return "foreign"
                if args[0] == "inspect":
                    return json.dumps({"Id": "foreign", "Name": "/test-api", "Label": "other"})
                raise AssertionError("Must not remove foreign identity")
            run = runner.OwnedRun(directory, "test", command)
            run.candidates = ["test-api"]
            self.assertFalse(run.cleanup())
            self.assertEqual(run.proof["remaining_owned"], ["foreign"])


if __name__ == "__main__":
    unittest.main()
