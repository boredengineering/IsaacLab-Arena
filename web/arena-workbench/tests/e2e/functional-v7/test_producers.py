# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Synthetic wire/daemon producer contracts, never live API/browser acceptance."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import api
import check_proof
import run
import test_check_proof


class ProducerTests(unittest.TestCase):
    def fixture(self):
        fixture = test_check_proof.ProofTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_preimport_emits_v2_from_actual_sandbox_observations(self):
        record = api.preflight()
        check_proof.preimport(record)
        self.assertEqual(json.loads((api.OUT / "preimport-api.json").read_text()), record)

    def test_api_preserves_exact_loaded_wire_fields_and_request(self):
        fixture = self.fixture()
        expected = fixture.get("evidence/api-proof.json")
        expected["document"]["additional_wire_field"] = {"keep": True}
        replies = [
            (401, {}), (200, {"csrf_token": "synthetic-unit-token"}),
            (200, {"documents": [expected["source_id"]], "default_document_id": expected["source_id"],
                   "capabilities": expected["capabilities"]}),
            (200, expected["document"]), (403, {}), (200, expected["validation"]),
            (200, expected["invalid_validation"]), (200, expected["schema"]),
            (200, expected["catalogues"]), (200, {"jobs": []}),
        ]
        sent = []
        class Connection:
            def __init__(self, *args, **kwargs):
                pass
            def request(self, method, path, body, headers):
                sent.append((method, path, json.loads(body) if body else None))
            def getresponse(self):
                status, body = replies.pop(0)
                response = mock.Mock(status=status)
                response.read.return_value = json.dumps(body).encode()
                response.getheader.return_value = "unit=cookie"
                return response
            def close(self):
                pass
        with mock.patch.object(api, "ROOT", fixture.root / "source"), \
                mock.patch.object(api.http.client, "HTTPConnection", Connection), \
                mock.patch.object(api.socket, "socket"):
            result = api.acceptance({"http": []})
        for field in ("source", "yaml_text", "document", "validation_request", "schema", "catalogues"):
            self.assertEqual(result[field], expected[field])
        self.assertEqual(sent[5][2], result["validation_request"])
        self.assertEqual(result["schema"]["schema_version"], 1)
        self.assertEqual(result["catalogues"]["schema_version"], 1)

    def test_final_record_requires_observed_closed_lifecycle_and_no_activity(self):
        counts = dict.fromkeys(check_proof.COUNTERS, 0)
        result = api.final_record(counts, [], True, True)
        check_proof.passed(result)
        check_proof.counters(result["forbidden"])
        for arguments in ((counts, [], False, True), (counts, [], True, False),
                          (counts, [{"id": "unit-job"}], True, True),
                          ({**counts, "subprocess": 1}, [], True, True), ({}, [], True, True)):
            with self.subTest(arguments=arguments), self.assertRaises(AssertionError):
                api.final_record(*arguments)

    def test_owned_producer_finalize_satisfies_unchanged_checker_on_synthetic_inputs(self):
        fixture = self.fixture()
        original = fixture.get("run-proof.json")
        owned = run.OwnedRun(fixture.root, original["run"])
        for key in ("browser", "layout", "mutations_enabled", "host_output", "source_sha256",
                    "staging", "dependency", "frontend_dependencies", "discovery"):
            owned.proof[key] = original[key]
        owned.proof["status"] = "passed"
        owned.candidates.extend(original["candidates"])
        containers = copy.deepcopy(original["containers"])
        removed = set()
        def command(*args):
            if args[0] == "ps":
                filter_value = args[-1]
                return "\n".join(c["id"] for c in containers if c["id"] not in removed and
                                 (filter_value.startswith("label=") or filter_value == "name=^" + c["name"] + "$"))
            if args[0] == "inspect":
                c = next(c for c in containers if c["id"] == args[-1])
                if args[2] == run.IDENTITY_FORMAT:
                    return json.dumps({"Id": c["id"], "Name": c["name"], "Label": owned.token})
                host = dict(c["host_config"], PidMode="", IpcMode="private", UsernsMode="", VolumesFrom=None)
                return json.dumps({"Id": c["id"], "Name": c["name"], "Image": c["image"],
                                   "Config": {"User": c["user"], "Labels": c["labels"]},
                                   "HostConfig": host, "Mounts": c["mounts"]})
            if args[0] == "rm":
                removed.add(args[-1]); return ""
            if args[0] == "logs":
                return "synthetic daemon unit output"
            raise AssertionError(args)
        owned.command = command
        for c in containers:
            owned.proof["created_ids"][c["name"][1:]] = c["id"]
            mounts = ["type=" + m["Type"] + ",src=" + (m["Name"] if m["Type"] == "volume" else m["Source"]) +
                      ",dst=" + m["Destination"] + ("" if m["RW"] else ",readonly") for m in c["mounts"]]
            run.verify_container(owned, c["id"], mounts)
        self.assertTrue(run.finalize(owned, fixture.root / "source"))
        check_proof.check(fixture.root, browser=True)
        self.assertIn("evidence/dist/index.html", owned.proof["artifacts"])
        self.assertEqual(owned.proof["artifacts"]["ownership.json"],
                         hashlib.sha256((fixture.root / "ownership.json").read_bytes()).hexdigest())

    def test_main_emits_manifests_and_mirrors_only_observed_v2_proofs(self):
        import shutil
        import stage
        fixture = self.fixture()
        expected = fixture.get("run-proof.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "web/arena-workbench/tests/e2e/functional-v7/run.py"
            owned_runs = []
            owned_class = run.OwnedRun
            def owned(output, token):
                value = owned_class(output, token, lambda *args: "a" * 64 if args[0] == "create" else "")
                owned_runs.append(value)
                return value
            def stage_bytes(repo, destination, browser):
                self.assertTrue(browser)
                shutil.copytree(fixture.root / "source", destination)
                return expected["source_sha256"]
            def dependency(value, discovery, destination):
                shutil.copytree(fixture.root / "pydeps", destination)
                shutil.copytree(fixture.root / "evidence", value.output / "evidence", dirs_exist_ok=True)
                return expected["dependency"]
            with mock.patch.object(run, "__file__", str(script)), \
                    mock.patch.object(run, "OwnedRun", side_effect=owned), \
                    mock.patch.object(run, "discover", return_value=dict(expected["discovery"], host_root="/synthetic-host")), \
                    mock.patch.object(stage, "stage", side_effect=stage_bytes), \
                    mock.patch.object(run, "obtain_dependency", side_effect=dependency), \
                    mock.patch.object(run, "verify_container"), mock.patch.object(run, "docker", return_value=""), \
                    mock.patch.object(run, "wait_file"), mock.patch.object(run, "finalize", return_value=True), \
                    mock.patch.object(run.os, "chown"):
                self.assertEqual(run.main(["--browser"]), 0)
            value = owned_runs[0]
            self.assertEqual(value.proof["frontend_dependencies"], expected["frontend_dependencies"])
            self.assertEqual(value.proof["dependency"], json.loads((value.output / "dependency-manifest.json").read_text()))
            self.assertEqual(value.proof["source_sha256"], json.loads((value.output / "source-manifest.json").read_text()))
            self.assertEqual(value.proof["staging"], {"policy_version": 2, "approved_fixture": check_proof.FIXTURE,
                             "manifest_sha256": hashlib.sha256((value.output / "source-manifest.json").read_bytes()).hexdigest()})
            self.assertEqual(value.proof["host_output"], "/synthetic-host/" + str(value.output.relative_to(root)))

    def test_missing_required_artifacts_cannot_finish_passed(self):
        with tempfile.TemporaryDirectory() as directory:
            owned = run.OwnedRun(directory, "arena-f0-unit", lambda *args: "")
            owned.proof.update(status="passed", source_sha256={}, browser=False)
            (Path(directory) / "evidence").mkdir()
            self.assertFalse(run.finalize(owned, Path(directory)))

    def test_failed_authoritative_listing_never_emits_success(self):
        with tempfile.TemporaryDirectory() as directory:
            owned = run.OwnedRun(directory, "arena-f0-unit", lambda *args: (_ for _ in ()).throw(TimeoutError()))
            self.assertFalse(owned.cleanup())
            self.assertEqual(owned.proof["cleanup_verification"]["status"], "failed")
            self.assertFalse(owned.proof["cleanup_verification"]["authoritative"])

    def test_legacy_proof_is_rejected_not_upgraded(self):
        with self.assertRaises((AssertionError, KeyError)):
            run.require_passed({"proof_version": 2, "status": "passed"})
        with self.assertRaises(AssertionError):
            run.require_passed({"schema_version": 1, "status": "passed"})
        run.require_passed({"schema_version": 2, "status": "passed"})


if __name__ == "__main__":
    api.preflight()
    unittest.main()
