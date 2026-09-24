# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Installed operator setup and explicit configuration handover contracts."""

import contextlib
import io
import json
import os
import pwd
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@contextlib.contextmanager
def operator_configuration():
    from workflow_graphql_execution_join_fixture import registrations

    from isaaclab_arena.agentic_environment_generation.workflow.profiles import profile_revision

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        profiles = registrations()
        value = {
            "schema_version": 3,
            "mode": "query-only",
            "operator": dict(
                uid=os.getuid(),
                gid=os.getgid(),
                groups=sorted(os.getgroups()),
                account=pwd.getpwuid(os.getuid()).pw_name,
                home=os.environ.get("HOME"),
                cwd=os.getcwd(),
            ),
            "private_root": str(root / "runtime"),
            "credentials_file": str(root / "credentials.json"),
            "endpoint": "http://127.0.0.1:18761/graphql",
            "bolt_uri": "bolt://127.0.0.1:17687",
            "binding": dict(
                schema_version=1,
                authority_id="operator-unit",
                operational_schema_version=1,
                artifact_marker_schema=1,
                database="neo4j",
                deployment_id="operator-unit",
                workspace_id="unit",
                store_id="operator-unit",
                registry_id="operator-unit",
            ),
            "artifact_root": str(root / "artifacts"),
            "required_profiles": [profile_revision(p).model_dump(mode="json") for p in profiles],
            "bootstrap_principal": "unit-admin",
            "read_principal": "unit-reader",
            "role_bindings": {
                role: dict(
                    credential_alias="cloud-" + ("generation" if role == "repair" else role),
                    profile=profiles[role == "assessment"].model_dump(mode="json"),
                )
                for role in ("generation", "assessment", "repair")
            },
        }
        value["role_bindings"]["prior_read"] = dict(
            credential_alias="prior-only", endpoint="bolt://127.0.0.1:17688", database="priors", authentication="basic"
        )
        credentials = dict(
            schema_version=2,
            databases=dict(
                operational=dict(scheme="basic", username="operational-unit", password="unit-db-sentinel"),
                prior_read=dict(
                    alias="prior-only", scheme="basic", username="prior-unit", password="unit-prior-sentinel"
                ),
            ),
            models={
                role: dict(
                    alias=value["role_bindings"][role]["credential_alias"],
                    api_key="unit-private-" + ("generation" if role == "repair" else role),
                )
                for role in ("generation", "assessment", "repair")
            },
        )
        path = root / "server.json"
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        yield path, value, credentials


def private_setup(path, credentials, command="setup"):
    from isaaclab_arena.agentic_environment_generation.workflow.cli import main

    read, write = os.pipe()
    os.fchmod(read, 0o600)
    os.write(write, json.dumps(credentials).encode())
    os.close(write)
    output, error = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            args = [command, "--config", str(path), "--credentials-fd", str(read)]
            code = main(args + (["--create"] if command == "setup" else []))
        return code, output.getvalue(), error.getvalue()
    finally:
        os.close(read)


class OperatorSetup(unittest.TestCase):
    def test_installed_handover_help_declares_both_exact_configuration_bindings(self):
        from isaaclab_arena.agentic_environment_generation.workflow.cli import main

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["api-handover", "--help"]), 0)
        for name in ("--previous-config", "--previous-instance", "--config", "--instance"):
            self.assertIn(name, output.getvalue())

    def test_resources_use_one_private_generation_for_database_and_roles(self):
        from isaaclab_arena.agentic_environment_generation.workflow.api import installed_composition
        from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load

        with operator_configuration() as (path, value, credentials):
            self.assertEqual(private_setup(path, credentials)[0], 0)
            original = Path(value["credentials_file"]).read_bytes()
            rotated = json.loads(original)
            rotated["generation"] = "c" * 32
            rotated["databases"]["operational"]["password"] += "-changed"
            with patch.object(
                installed_composition, "read_private", side_effect=[original, json.dumps(rotated).encode()]
            ):
                resource = installed_composition.Resources(load(str(path)))
            self.assertTrue(resource.roles.document["databases"]["operational"] == resource.credential)
            self.assertEqual(resource.roles.document["generation"], json.loads(original)["generation"])

    def test_missing_roles_do_not_fall_back_to_environment_credentials(self):
        from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
        from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load

        with operator_configuration() as (path, value, credentials):
            credentials["models"] = {}
            credentials["databases"].pop("prior_read")
            self.assertEqual(private_setup(path, credentials)[0], 0)
            with patch.dict(os.environ, {"OPENAI_API_KEY": "ambient-must-not-be-used", "NEO4J_PASSWORD": "ambient"}):
                resource = Resources(load(str(path)))
                for role in ("generation", "assessment", "repair"):
                    with self.subTest(role=role), self.assertRaisesRegex(ValueError, "unavailable"):
                        resource.private_roles().model_config(role)
                with self.assertRaisesRegex(ValueError, "unavailable"):
                    resource.private_roles().prior_read()

    def test_public_configuration_rejects_unbound_profile_transport_and_authentication(self):
        from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load

        with operator_configuration() as (path, value, credentials):
            for name in ("profile", "repair", "transport", "authentication"):
                changed = json.loads(json.dumps(value))
                if name == "profile":
                    changed["role_bindings"]["generation"]["profile"]["settings"]["model"] = "not-selected"
                elif name == "repair":
                    changed["role_bindings"]["repair"]["credential_alias"] = "different-private-binding"
                else:
                    changed["role_bindings"]["prior_read"]["endpoint" if name == "transport" else name] = (
                        "neo4j+s://example.invalid" if name == "transport" else "bearer"
                    )
                path.write_text(json.dumps(changed))
                with self.subTest(name=name), self.assertRaises(ValueError):
                    load(str(path))

    def test_handover_cannot_replace_unresolved_instance_or_change_scope(self):
        from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load
        from isaaclab_arena.agentic_environment_generation.workflow.api.instance import identity, launch
        from isaaclab_arena.agentic_environment_generation.workflow.api.private_files import Directory, encode

        with operator_configuration() as (path, value, credentials):
            self.assertEqual(private_setup(path, credentials)[0], 0)
            value["mode"] = "isolated-synthetic-execution-v1"
            path.write_text(json.dumps(value))
            old = load(str(path))
            selected, target = "a" * 32, "b" * 32
            captured = identity(os.getpid())
            captured.pop("state")
            location = Path(value["private_root"]) / "instances" / selected
            location.mkdir(parents=True, mode=0o700)
            location.parent.chmod(0o700)
            known = dict(
                schema_version=1,
                instance=selected,
                config_sha256=old.digest,
                binding_sha256=old.binding.body_sha256,
                endpoint=value["endpoint"],
                generation=1,
                state="ready",
                code="ready",
                identity=captured,
            )
            with Directory(str(location)) as directory:
                directory.write("state.json", encode(known))
                directory.write("configuration.json", encode(old.value))
            with Directory(value["private_root"]) as directory:
                directory.write(
                    "current.json", encode(dict(schema_version=1, instance=selected, config_sha256=old.digest))
                )
            value["endpoint"] = "http://127.0.0.1:18762/graphql"
            next_path = path.with_name("next.json")
            next_path.write_text(json.dumps(value))
            next_path.chmod(0o600)
            new = load(str(next_path))
            with patch("subprocess.Popen", side_effect=AssertionError("unresolved handover spawned")):
                with self.assertRaisesRegex(ValueError, "unresolved"):
                    launch(new, target, previous_config=old, previous_instance=selected)
            self.assertFalse((location.parent / target).exists())
            known.update(state="stopped", code="cleanup_unknown")
            with Directory(str(location)) as directory:
                directory.write("state.json", encode(known), replace=True)
            with patch(
                "isaaclab_arena.agentic_environment_generation.workflow.api.instance.same_process", return_value=False
            ):
                with self.assertRaisesRegex(ValueError, "cleanup unresolved"):
                    launch(new, target, previous_config=old, previous_instance=selected)
            value["private_root"] = str(path.parent / "different-runtime")
            next_path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "durable scope or private roots"):
                launch(load(str(next_path)), target, previous_config=old, previous_instance=selected)
            self.assertFalse(Path(value["private_root"]).exists())

    def test_config_report_precedes_private_setup_and_preserves_selected_roles(self):
        from isaaclab_arena.agentic_environment_generation.workflow.cli import main

        with operator_configuration() as (path, value, credentials):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["setup-readiness", "--config", str(path)]), 0)
            report = json.loads(output.getvalue())
            self.assertFalse(Path(value["credentials_file"]).exists())
            self.assertEqual(report["roles"]["generation"]["shared_alias_with"], ["repair"])
            for role in ("generation", "assessment", "repair"):
                selected = report["roles"][role]["selection"]
                self.assertEqual(selected["model"], value["role_bindings"][role]["profile"]["settings"]["model"])
                self.assertEqual(selected["credential"]["source_role"], "models." + role)
            self.assertEqual(report["installed_boundary"]["provider_bootstrap"], "private_roles_v2")
            self.assertEqual(
                report["database_compatibility"]["prior_read"]["installed_credential_slot"], "databases.prior_read"
            )
            self.assertNotIn(value["credentials_file"], output.getvalue())
            self.assertFalse(report["execution_authorized"])

    def test_rotation_invalidates_role_snapshot_but_not_current_read_authority(self):
        from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
        from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load

        with operator_configuration() as (path, value, credentials):
            code, original, _ = private_setup(path, credentials)
            self.assertEqual(code, 0)
            resource = Resources(load(str(path)))
            with resource.private_roles().release_guard():
                code, output, error = private_setup(path, credentials, "credentials-update")
                self.assertEqual(code, 2)
                self.assertNotIn("unit-private", output + error)
            credentials["models"] = {}
            credentials["databases"].pop("prior_read")
            code, rotated, error = private_setup(path, credentials, "credentials-update")
            self.assertEqual(code, 0, error)
            self.assertNotEqual(
                json.loads(original)["credential_generation"], json.loads(rotated)["credential_generation"]
            )
            resource.authority.require_read("unit-reader")
            with self.assertRaisesRegex(ValueError, "generation changed"):
                resource.private_roles().model_config("generation")
            replacement = Resources(load(str(path)))
            replacement.authority.require_read("unit-reader")
            with self.assertRaisesRegex(ValueError, "unavailable"):
                replacement.private_roles().model_config("generation")

    def test_private_roles_setup_uses_explicit_aliases_and_never_authorizes_execution(self):
        from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
        from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load

        with operator_configuration() as (path, value, credentials):
            load(str(path))
            code, output, error = private_setup(path, credentials)
            self.assertEqual(code, 0, error)
            result = json.loads(output)
            self.assertEqual(result["code"], "setup_complete")
            self.assertFalse(result["execution_authorized"])
            resources = Resources(load(str(path)))
            roles = resources.private_roles()
            for role in ("generation", "assessment", "repair"):
                private = roles.model_config(role)
                self.assertEqual(private["api_key"], credentials["models"][role]["api_key"])
                self.assertNotIn("databases", private)
                self.assertNotIn(credentials["databases"]["prior_read"]["password"], str(private))
                self.assertNotIn(private["api_key"], output + error)
            self.assertEqual(roles.prior_read()["username"], "prior-unit")
            self.assertEqual(resources.credential["username"], "operational-unit")
            for secret in ("unit-private-generation", "unit-private-assessment", "unit-prior-sentinel"):
                with self.assertRaises(ValueError):
                    roles.protect({"nested": [secret]})

    def test_offline_installed_cli_distinguishes_execution_modes_without_effects(self):
        from isaaclab_arena.agentic_environment_generation.workflow.cli import main

        output = io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            patch("builtins.open", side_effect=AssertionError("offline file access")),
            patch("socket.socket", side_effect=AssertionError("offline network access")),
            patch("subprocess.Popen", side_effect=AssertionError("offline process creation")),
        ):
            self.assertEqual(main(["setup-readiness"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(
            report["installed_boundary"]["execution_modes"],
            {"query-only": "supported", "isolated-synthetic-execution-v1": "harness_only", "production": "unsupported"},
        )
        self.assertFalse(report["execution_authorized"])
        self.assertEqual(report["credential_generation"], "not_observed")
        self.assertTrue(all(row["public_selection"] == "unresolved" for row in report["roles"].values()))
        blocker = next(row for row in report["blockers"] if row["code"] == "installed_execution")
        self.assertNotIn("remains query-only", blocker["next_action"])
        self.assertIn("production", blocker["next_action"])
