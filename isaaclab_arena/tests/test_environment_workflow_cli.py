# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Stdlib-only adapter tests; load the CLI file without importing Arena packages."""

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "isaaclab_arena_examples/agentic_environment_generation/foreground_workflow_cli.py"


def entry():
    spec = importlib.util.spec_from_file_location("foreground_cli_under_test", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CLITests(unittest.TestCase):
    def test_outcome_exit_mapping(self):
        module = entry()
        for state, expected in (
            ("accepted", 0),
            ("stopped", 6),
            ("blocked", 3),
            ("cancelled", 7),
            ("failed", 5),
            ("unknown", 3),
        ):
            self.assertEqual(module.outcome_exit({"state": state}), expected)

    def test_all_commands_delegate_exact_ids_and_close(self):
        self.assertTrue(ENTRY.is_file(), "foreground entrypoint missing")
        module = entry()
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.json"
            profile.write_text(
                json.dumps({
                    "schema_version": 1,
                    "composition": "isolated-synthetic-v1",
                    "database": {
                        "uri": "bolt://127.0.0.1:7687",
                        "database": "workflowtest",
                        "username": "operator",
                    },
                    "deployment_id": "test-deployment",
                    "workspace_id": "test-workspace",
                    "artifact_root": directory + "/artifacts",
                    "lease_root": directory + "/leases",
                })
            )
            profile.chmod(0o600)
            contract = Path(directory) / "contract.json"
            contract.write_text('{"synthetic_request":true}')
            for command in ("run", "status", "cancel", "resume"):
                with self.subTest(command=command):
                    calls = []

                    class App:
                        def run(self, *args):
                            calls.append(("run", args))
                            return {"state": "accepted", "run_id": "Run.Exact:1"}

                        def status(self, *args):
                            calls.append(("status", args))
                            return {"state": "accepted"}

                        cancel = status
                        resume = status

                        def close(self):
                            calls.append(("close", ()))

                    def factory(config, credentials, *, allow_startup):
                        self.assertEqual(config["composition"], "isolated-synthetic-v1")
                        self.assertEqual(credentials, {})
                        self.assertFalse(allow_startup)
                        return App()

                    argv = [
                        command,
                        "--config",
                        str(profile),
                        "--principal",
                        "Principal.Exact:1",
                    ]
                    argv += ["--operation-id", "Op.Exact:1", str(contract)] if command == "run" else ["Run.Exact:1"]
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        result = module.main(argv, application_factory=factory)
                    self.assertEqual(result, 0)
                    self.assertEqual(calls[-1], ("close", ()))
                    self.assertEqual(calls[0][1][0], "Principal.Exact:1")
                    self.assertEqual(
                        calls[0][1][1],
                        "Op.Exact:1" if command == "run" else "Run.Exact:1",
                    )
                    if command == "run":
                        self.assertEqual(calls[0][1][2], contract.read_bytes())
                    self.assertEqual(json.loads(output.getvalue())["schema_version"], 1)


class BoundaryTests(unittest.TestCase):
    def test_admission_is_flushed_before_execution_and_final_is_separate(self):
        module = entry()
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(directory)
            contract = Path(directory) / "contract.json"
            contract.write_text("{}")

            class Output(io.StringIO):
                flushed = False

                def flush(self):
                    self.flushed = True

            output = Output()

            class App:
                def set_admission_listener(self, callback):
                    self.callback = callback

                def run(self, *args):
                    self.callback({"run_id": "Exact.Run", "state": "admitted"})
                    assert output.flushed
                    assert json.loads(output.getvalue())["event"] == "admitted"
                    return {"run_id": "Exact.Run", "state": "stopped"}

                def close(self):
                    pass

            with contextlib.redirect_stdout(output):
                code = module.main(
                    [
                        "run",
                        "--config",
                        str(profile),
                        "--principal",
                        "operator",
                        "--operation-id",
                        "op",
                        str(contract),
                    ],
                    application_factory=lambda *a, **k: App(),
                )
            self.assertEqual(code, 6)
            lines = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[-1]["result"]["state"], "stopped")

    def profile(self, directory, **changes):
        value = {
            "schema_version": 1,
            "composition": "isolated-synthetic-v1",
            "database": {
                "uri": "bolt://127.0.0.1:7687",
                "database": "workflowtest",
                "username": "operator",
            },
            "deployment_id": "deployment",
            "workspace_id": "workspace",
            "artifact_root": directory + "/artifacts",
            "lease_root": directory + "/leases",
        }
        value.update(changes)
        path = Path(directory) / "config.json"
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        return path

    def test_resume_renewal_requires_explicit_flag(self):
        module = entry()
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(directory)
            calls = []

            class App:
                def resume(self, principal, run_id, **kwargs):
                    calls.append((principal, run_id, kwargs))
                    return {"state": "accepted"}

                def close(self):
                    pass

            base = ["resume", "--config", str(profile), "--principal", "operator"]
            for extra, expected in (([], {}), (["--renew-authorization"], {"renew_authorization": True})):
                with contextlib.redirect_stdout(io.StringIO()):
                    code = module.main([*base, *extra, "run"], application_factory=lambda *a, **kw: App())
                self.assertEqual(code, 0)
                self.assertEqual(calls[-1], ("operator", "run", expected))
            for command in ("status", "cancel"):
                with contextlib.redirect_stdout(io.StringIO()):
                    code = module.main(
                        [command, *base[1:], "--renew-authorization", "run"],
                        application_factory=lambda *a, **kw: self.fail("renewal on read/cancel"),
                    )
                self.assertEqual(code, 2)

    def test_config_rejects_unknown_code_secret_and_native_before_factory(self):
        module = entry()
        with tempfile.TemporaryDirectory() as directory:
            for changes in (
                {"factory": "private.callback"},
                {"command": ["sh"]},
                {"api_key": "private-key"},
                {"composition": "native"},
                {"schema_version": True},
                {"workspace_id": " bad"},
            ):
                with self.subTest(changes=changes):
                    config = self.profile(directory, **changes)
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        result = module.main(
                            [
                                "status",
                                "--config",
                                str(config),
                                "--principal",
                                "operator",
                                "run",
                            ],
                            application_factory=lambda *a, **kw: self.fail("factory before validation"),
                        )
                    self.assertEqual(result, 2)
                    self.assertEqual(
                        json.loads(output.getvalue()),
                        {"schema_version": 1, "error": "invalid_input"},
                    )

    def test_private_fd_rejects_standard_and_oversized_descriptors(self):
        module = entry()
        self.assertTrue(hasattr(module, "_read_credentials"), "bounded private FD reader missing")
        for fd in (0, 1, 2, -1, True):
            with self.assertRaises(ValueError):
                module._read_credentials(fd)
        with tempfile.TemporaryFile() as stream:
            stream.write(b"x" * (module.MAX_INPUT_BYTES + 1))
            stream.seek(0)
            with self.assertRaises(ValueError):
                module._read_credentials(stream.fileno())

    def test_errors_are_static_and_failed_application_is_closed(self):
        from isaaclab_arena.agentic_environment_generation.inference_profiles import ModelProfileUnavailable

        module = entry()
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(directory)
            for error, expected in (
                (PermissionError("private-key"), (4, "denied")),
                (ConnectionError("private-key"), (3, "not_ready")),
                (ModelProfileUnavailable("private-key"), (3, "model_profile_not_ready")),
                (ValueError("private-key"), (5, "application_failed")),
                (RuntimeError("private-key"), (5, "application_failed")),
            ):
                calls = []

                class App:
                    def status(self, *args):
                        raise error

                    def close(self):
                        calls.append("closed")

                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = module.main(
                        [
                            "status",
                            "--config",
                            str(profile),
                            "--principal",
                            "operator",
                            "run",
                        ],
                        application_factory=lambda *a, **kw: App(),
                    )
                self.assertEqual((code, json.loads(out.getvalue())["error"]), expected)
                self.assertEqual(calls, ["closed"])
                self.assertNotIn("private-key", out.getvalue() + err.getvalue())

    def test_json_rejects_nonfinite_exponents(self):
        module = entry()
        with self.assertRaises(ValueError):
            module._json(b'{"limit":1e999}')

    def test_credentials_reject_persisted_files(self):
        module = entry()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-a-credential-source"
            path.write_bytes(b"{}")
            path.chmod(0o600)
            with path.open("rb") as stream, self.assertRaises(ValueError):
                module._read_credentials(stream.fileno())

    def test_close_failure_is_not_retried(self):
        module = entry()
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(directory)
            calls = []

            class App:
                def status(self, *args):
                    return {"state": "accepted"}

                def close(self):
                    calls.append("close")
                    raise RuntimeError("private-key")

            with contextlib.redirect_stdout(io.StringIO()):
                code = module.main(
                    [
                        "status",
                        "--config",
                        str(profile),
                        "--principal",
                        "operator",
                        "run",
                    ],
                    application_factory=lambda *a, **kw: App(),
                )
            self.assertEqual(code, 5)
            self.assertEqual(calls, ["close"])

    def test_duplicate_json_and_nonprivate_profile_are_rejected(self):
        module = entry()
        with self.assertRaises(ValueError):
            module._json(b'{"models":{},"models":{}}')
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(directory)
            profile.chmod(0o644)
            with self.assertRaises(ValueError):
                module._read_file(str(profile), private=True)

    def test_malformed_database_url_rejected_before_factory(self):
        module = entry()
        with tempfile.TemporaryDirectory() as directory:
            for uri in (
                "bolt://user:secret@localhost:7687",
                "bolt://localhost:bad",
                "bolt://localhost:7687?password=private",
                " bolt://localhost:7687",
            ):
                profile = self.profile(
                    directory,
                    database={
                        "uri": uri,
                        "database": "workflowtest",
                        "username": "operator",
                    },
                )
                with self.subTest(uri=uri), self.assertRaises(ValueError):
                    module._config(profile.read_bytes())

    def test_private_pipe_is_bounded_and_preserves_exact_credentials(self):
        module = entry()
        self.assertTrue(hasattr(module, "_read_credentials"), "bounded private FD reader missing")
        read, write = os.pipe()
        try:
            os.write(write, b'{"database_password":"private-EXACT","models":{}}')
            os.close(write)
            write = None
            self.assertEqual(
                module._read_credentials(read),
                {"database_password": "private-EXACT", "models": {}},
            )
        finally:
            os.close(read)
            if write is not None:
                os.close(write)


class BootstrapTests(unittest.TestCase):
    def test_observation_only_port_pins_reports_and_never_starts(self):
        from types import SimpleNamespace

        path = ROOT / "isaaclab_arena/agentic_environment_generation/workflow/bootstrap.py"
        spec = importlib.util.spec_from_file_location("bootstrap_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, "ObservationOnlyPort"), "shared observer bridge missing")
        required = SimpleNamespace(
            dependency_id="runtime", profile_id="offline", profile_sha256="a" * 64, instance_id=None
        )
        calls = []

        def observe(request, timeout):
            calls.append(request)
            return SimpleNamespace(**vars(request), status="passed")

        port = module.ObservationOnlyPort((required,), observe)
        gate = module.ScopedHostBootstrap(port, allow_startup=True)
        self.assertEqual(calls, [])
        self.assertEqual(gate.prepare((required,), timeout_s=5), ("passed",))
        self.assertFalse(port.capabilities()["runtime"]["start"])
        foreign = SimpleNamespace(**(vars(required) | {"profile_sha256": "b" * 64}))
        self.assertEqual(gate.prepare((foreign,), timeout_s=5), ("unavailable",))
        self.assertEqual(len(calls), 1)
        wrong = module.ObservationOnlyPort((required,), lambda r, t: SimpleNamespace(**vars(foreign), status="passed"))
        self.assertEqual(module.ScopedHostBootstrap(wrong).prepare((required,), timeout_s=5), ("unavailable",))

    def test_gate_binding_preserves_clock_and_exact_requirements(self):
        import sys
        from types import ModuleType, SimpleNamespace
        from unittest.mock import patch

        path = ROOT / "isaaclab_arena/agentic_environment_generation/workflow/bootstrap.py"
        spec = importlib.util.spec_from_file_location("bootstrap_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        adapter = module.ScopedHostBootstrap(clock=lambda: 10.0)
        self.assertTrue(hasattr(adapter, "check"), "readiness gate binding missing")
        required = (
            SimpleNamespace(
                dependency_id="runtime",
                profile_id="fixture",
                profile_sha256="a" * 64,
                instance_id=None,
            ),
        )
        readiness = ModuleType("isaaclab_arena.agentic_environment_generation.workflow.readiness")
        readiness.DependencyResult = lambda **kw: SimpleNamespace(**kw)
        readiness.ReadinessReport = lambda **kw: SimpleNamespace(**kw)
        with patch.dict(sys.modules, {readiness.__name__: readiness}):
            result = adapter.check(required, timeout_s=5)
        self.assertIs(result.clock, adapter._clock)
        self.assertIs(result.requirements, required)
        self.assertEqual(result.results[0].status, "unavailable")
        self.assertEqual(result.started_at, 10.0)

    def test_start_capabilities_are_frozen_before_observation(self):
        from types import SimpleNamespace

        path = ROOT / "isaaclab_arena/agentic_environment_generation/workflow/bootstrap.py"
        spec = importlib.util.spec_from_file_location("bootstrap_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        required = (
            SimpleNamespace(
                dependency_id="neo4j",
                profile_id="fixture",
                profile_sha256="a" * 64,
                instance_id="exact",
            ),
        )
        caps = {
            "neo4j": {
                "profile_id": "fixture",
                "profile_sha256": "a" * 64,
                "instance_id": "exact",
                "observe": True,
                "start": False,
            }
        }
        calls = []

        class SyntheticHelper:
            def capabilities(self):
                return caps

            def observe(self, request, timeout):
                caps["neo4j"]["start"] = True
                return "stopped"

            def start_scoped(self, request, timeout):
                calls.append("start")

        adapter = module.ScopedHostBootstrap(SyntheticHelper(), allow_startup=True)
        self.assertEqual(adapter.prepare(required, timeout_s=5), ("unavailable",))
        self.assertEqual(calls, [])

    def test_full_closure_preflight_and_scoped_start(self):
        from types import SimpleNamespace

        path = ROOT / "isaaclab_arena/agentic_environment_generation/workflow/bootstrap.py"
        self.assertTrue(path.is_file(), "scoped bootstrap adapter missing")
        spec = importlib.util.spec_from_file_location("bootstrap_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        required = tuple(
            SimpleNamespace(
                dependency_id=role,
                profile_id="fixture",
                profile_sha256="a" * 64,
                instance_id="exact-" + role,
            )
            for role in (
                "runtime",
                "neo4j",
                "generation_model",
                "assessment_model",
                "capture",
                "gpu",
            )
        )
        for missing, allow in (("assessment_model", True), (None, False), (None, True)):
            with self.subTest(missing=missing, allow=allow):
                calls = []
                capabilities = {
                    r.dependency_id: {
                        "profile_id": r.profile_id,
                        "profile_sha256": r.profile_sha256,
                        "instance_id": r.instance_id,
                        "observe": True,
                        "start": r.dependency_id == "neo4j",
                    }
                    for r in required
                    if r.dependency_id != missing
                }

                class SyntheticInstalledHelper:
                    def capabilities(self):
                        calls.append("capabilities")
                        return capabilities

                    def observe(self, request, timeout_s):
                        calls.append("observe:" + request.dependency_id)
                        return (
                            "stopped" if request.dependency_id == "neo4j" and "start:neo4j" not in calls else "passed"
                        )

                    def start_scoped(self, request, timeout_s):
                        calls.append("start:" + request.dependency_id)

                adapter = module.ScopedHostBootstrap(SyntheticInstalledHelper(), allow_startup=allow)
                self.assertEqual(calls, [])
                result = adapter.prepare(required, timeout_s=5)
                if missing:
                    self.assertEqual(calls, ["capabilities"])
                    self.assertFalse(all(r == "passed" for r in result))
                elif allow:
                    self.assertTrue(all(r == "passed" for r in result))
                    self.assertEqual(calls.count("start:neo4j"), 1)
                    self.assertLess(
                        calls.index("observe:assessment_model"),
                        calls.index("start:neo4j"),
                    )
                    self.assertEqual(calls[-1], "observe:neo4j")
                else:
                    self.assertNotIn("start:neo4j", calls)
                    self.assertIn("unavailable", result)


class OfflineSetupReportTests(unittest.TestCase):
    def test_installed_cli_reports_unresolved_roles_without_setup(self):
        from isaaclab_arena.agentic_environment_generation.workflow.cli import main

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["setup-readiness"])
        self.assertEqual(code, 0, err.getvalue())
        report = json.loads(out.getvalue())
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["outcome"], "scene-only")
        self.assertEqual(
            set(report["roles"]),
            {"generation", "assessment", "repair", "local_policy", "prior_read", "operational_db"},
        )
        for row in report["roles"].values():
            self.assertEqual(row["public_selection"], "unresolved")
            self.assertEqual(row["access"], "not_checked")
            self.assertEqual(row["capability"], "not_checked")
            self.assertEqual(row["execution"], "not_authorized")
            self.assertIsNone(row["checked_at"])
        self.assertFalse(report["execution_authorized"])
        self.assertEqual(len(report["selection_sha256"]), 64)
        self.assertTrue(report["blockers"])
        self.assertTrue(all(b["next_action"] for b in report["blockers"]))
        self.assertTrue(all("scene-only" in b["outcomes"] for b in report["blockers"]))
        self.assertTrue(all("local_policy" not in b["roles"] for b in report["blockers"]))
        if Path("/evidence").is_dir():
            (Path("/evidence") / "setup-readiness-unresolved.json").write_text(out.getvalue())

    def test_explicit_selection_file_is_the_only_data_read(self):
        from unittest.mock import patch

        from isaaclab_arena.agentic_environment_generation.workflow import cli

        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory) / "public.json"
            selected.write_text(
                json.dumps({
                    "schema_version": 1,
                    "outcome": "required-policy",
                    "roles": {
                        "generation": {
                            "provider": "openai",
                            "model": "Literal.Model-1",
                            "endpoint": "https://api.openai.com/v1",
                        },
                    },
                })
            )
            opened = []
            real_open = os.open

            def only_selected(path, *args, **kwargs):
                self.assertEqual(path, str(selected))
                opened.append(path)
                return real_open(path, *args, **kwargs)

            out, err = io.StringIO(), io.StringIO()
            with (
                patch.object(os, "open", only_selected),
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
            ):
                code = cli.main(["setup-readiness", "--selection", str(selected)])
            self.assertEqual(code, 0, err.getvalue())
            report = json.loads(out.getvalue())
            self.assertEqual(opened, [str(selected)])
            self.assertEqual(report["outcome"], "required-policy")
            self.assertEqual(report["roles"]["generation"]["selection"]["model"], "Literal.Model-1")

    def test_bad_selection_files_have_exact_static_errors(self):
        from isaaclab_arena.agentic_environment_generation.workflow.cli import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sentinel-secret-path.json"
            for raw in (
                b"{sentinel-secret",
                b"{}",
                b"x" * 65537,
                b"\xff",
                b'{"schema_version":1,"schema_version":1}',
                b"[" * 1000,
            ):
                path.write_bytes(raw)
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = main(["setup-readiness", "--selection", str(path)])
                self.assertEqual(
                    (code, out.getvalue(), err.getvalue()), (2, "", "setup-readiness: invalid selection file\n")
                )
            path.unlink()
            for kind in ("missing", "directory", "symlink", "fifo"):
                if kind == "directory":
                    path.mkdir()
                elif kind == "symlink":
                    path.symlink_to(Path(directory))
                elif kind == "fifo":
                    os.mkfifo(path)
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = main(["setup-readiness", "--selection", str(path)])
                self.assertEqual(
                    (code, out.getvalue(), err.getvalue()), (2, "", "setup-readiness: invalid selection file\n")
                )
                if kind == "directory":
                    path.rmdir()
                elif kind != "missing":
                    path.unlink()

    def test_documented_selection_example_through_installed_cli(self):
        from isaaclab_arena.agentic_environment_generation.workflow.cli import main

        # Kept byte-equivalent as JSON to setup_selection.example.json; checked
        # statically outside the sandbox without widening its source closure.
        example = {
            "schema_version": 1,
            "outcome": "scene-only",
            "roles": {
                "generation": {
                    "provider": "openai",
                    "model": "gpt-4.1",
                    "endpoint": "https://api.openai.com/v1",
                    "inference_profile": None,
                    "credential": {
                        "alias": "cloud-example",
                        "source": "private_file",
                        "source_role": "models.generation",
                        "public_id": "public-project-example",
                    },
                },
                "assessment": {
                    "provider": "openai",
                    "model": "gpt-4.1",
                    "endpoint": "https://api.openai.com/v1",
                    "inference_profile": None,
                    "credential": {
                        "alias": "cloud-example",
                        "source": "private_file",
                        "source_role": "models.assessment",
                        "public_id": "public-project-example",
                    },
                },
                "repair": None,
                "local_policy": None,
                "prior_read": {
                    "provider": "neo4j",
                    "endpoint": "neo4j+s://research.example.invalid:7687",
                    "database": "research-example",
                    "authentication": "basic",
                    "tls": "system_ca",
                    "credential": {
                        "alias": "prior-reader-example",
                        "source": "private_file",
                        "source_role": "databases.prior_read",
                    },
                },
                "operational_db": {
                    "provider": "neo4j",
                    "endpoint": "bolt://192.0.2.10:7687",
                    "database": "pilot-example",
                    "authentication": "basic",
                    "tls": "none",
                    "credential": {
                        "alias": "operational-example",
                        "source": "private_file",
                        "source_role": "databases.operational",
                    },
                },
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "public-selection.json"
            path.write_text(json.dumps(example))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["setup-readiness", "--selection", str(path)])
            self.assertEqual(code, 0, err.getvalue())
            report = json.loads(out.getvalue())
        self.assertEqual(report["selection"], example)
        self.assertEqual(report["roles"]["generation"]["shared_alias_with"], ["assessment"])
        self.assertEqual(report["database_compatibility"]["prior_read"]["transport"], "incompatible")
        self.assertEqual(report["roles"]["repair"]["public_selection"], "unresolved")
        self.assertFalse(report["execution_authorized"])

    def test_query_only_dispatch_and_exact_error_screening_remain_unchanged(self):
        import sys
        from types import ModuleType
        from unittest.mock import patch

        from isaaclab_arena.agentic_environment_generation.workflow import cli

        calls = []
        client = ModuleType("isaaclab_arena.agentic_environment_generation.workflow.api.client")

        def query(path, command, **kwargs):
            calls.append((path, command, kwargs))
            return {"retained": "Run.Exact"}

        client.query = query
        with patch.dict(sys.modules, {client.__name__: client}):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(cli.main(["status", "--client", "/explicit/client", "Run.Exact"]), 0)
            self.assertEqual(json.loads(out.getvalue()), {"retained": "Run.Exact"})
            self.assertEqual(calls[0][:2], ("/explicit/client", "status"))
            self.assertEqual(calls[0][2]["identifier"], "Run.Exact")

            def denied(*args, **kwargs):
                raise RuntimeError("SENTINEL-PRIVATE")

            client.query = denied
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["status", "--client", "/explicit/client", "Run.Exact"])
            self.assertEqual((code, out.getvalue(), err.getvalue()), (2, "", "workflow: query unavailable\n"))
        for argv in (
            ["setup-readiness", "--execution-authorized", "SENTINEL-PRIVATE"],
            ["setup-readiness", "--sel", "SENTINEL-PRIVATE"],
            ["run", "SENTINEL-PRIVATE"],
        ):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(argv)
            self.assertEqual((code, out.getvalue(), err.getvalue()), (2, "", "inspect-contract: invalid arguments\n"))


class CoreDispatchTests(unittest.TestCase):
    def test_core_parser_dispatches_without_loading_domain_or_application(self):
        import argparse
        import ast
        import sys
        from types import ModuleType
        from unittest.mock import patch

        source = ROOT / "isaaclab_arena/agentic_environment_generation/workflow/cli.py"
        tree = ast.parse(source.read_text())
        subset = ast.Module(
            body=[
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                and node.name in {"main", "_StaticArgumentParser", "_add_installed_arguments"}
            ],
            type_ignores=[],
        )
        namespace = {"argparse": argparse, "sys": sys, "__doc__": "parser test"}
        exec(compile(subset, str(source), "exec"), namespace)
        calls = []
        module = ModuleType("isaaclab_arena_examples.agentic_environment_generation.foreground_workflow_cli")
        module.main = lambda argv: calls.append(argv) or 0
        argv = [
            "status",
            "--config",
            "/explicit/profile",
            "--principal",
            "operator",
            "Run.Exact",
        ]
        output = io.StringIO()
        with (
            patch.dict(sys.modules, {module.__name__: module}),
            contextlib.redirect_stderr(output),
        ):
            result = namespace["main"](argv)
        self.assertEqual(result, 2, output.getvalue())
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
