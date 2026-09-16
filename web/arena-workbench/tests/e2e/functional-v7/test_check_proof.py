# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Synthetic checker-contract tests, never real API/browser acceptance evidence."""
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("checker", HERE / "check_proof.py")
assert spec is not None and spec.loader is not None
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
sha = lambda value: hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


class ProofTests(unittest.TestCase):
    def install_synthetic_provision(self):
        """Synthetic consistency fixture only, never evidence of an actual build."""
        run = self.get("run-proof.json")
        base = run["discovery"]["runtime_image"]
        image = "sha256:" + "7" * 64
        dependency = self.get("dependency-manifest.json")
        recipe = {"schema_version": 1, "scope": "test-only declared neo4j plus pytz", "base_image": base,
                  "purelib": "/isaac-sim/kit/python/lib/python3.12/site-packages", "python_version": [3, 12, 0],
                  "pins": copy.deepcopy(checker.PROVISION_PINS),
                  "build_policy": "COPY-only; network=none; no RUN; no package execution",
                  "declaration_sha256": "8" * 64, "acquisition_sha256": "9" * 64,
                  "files": {**dependency["files"], "pytz/__init__.py": "a" * 64}}
        digest = sha(json.dumps(recipe, sort_keys=True, separators=(",", ":")))
        provision = {"schema_version": 1, "status": "passed", "image": image, "recipe": recipe, "recipe_sha256": digest,
                     "base_projection": {"Id": base, "Volumes": None, "Layers": ["sha256:" + "a" * 64], "Recipe": None},
                     "image_projection": {"Id": image, "Volumes": None,
                                          "Layers": ["sha256:" + "a" * 64, "sha256:" + "b" * 64], "Recipe": digest},
                     "readback": {"schema_version": 1, "status": "passed", "recipe_sha256": digest,
                                  "files_verified": 2, "uid": 1000, "errno": 101,
                                  "egress_denied": True, "before_package_imports": True}, "cleanup_verified": True}
        run["discovery"].update(selected_runtime_image=image, provision=provision)
        for container in run["containers"]:
            if container["image"] == base:
                container["image"] = image
        dependency["source_image"] = image
        run["dependency"] = dependency
        self.put("dependency-manifest.json", dependency)
        self.put("provision-manifest.json", provision)
        self.put("run-proof.json", run)
        owner = self.get("ownership.json")
        owner["containers"] = run["containers"]
        self.put("ownership.json", owner)
        self.seal()
        return provision

    def test_provisioned_runtime_is_distinct_and_bound_to_actual_donor_bytes(self):
        self.install_synthetic_provision()
        checker.check(self.root)
        run = self.get("run-proof.json")
        provision = run["discovery"]["provision"]
        provision["recipe"]["files"]["neo4j/__init__.py"] = "e" * 64
        digest = sha(json.dumps(provision["recipe"], sort_keys=True, separators=(",", ":")))
        provision["recipe_sha256"] = provision["image_projection"]["Recipe"] = provision["readback"]["recipe_sha256"] = digest
        self.put("provision-manifest.json", provision)
        self.put("run-proof.json", run)
        self.seal()
        with self.assertRaisesRegex(AssertionError, "Provision/donor bytes"):
            checker.check(self.root)

    def test_provision_selection_rejects_resealed_identity_pin_layer_and_probe_tampering(self):
        provision = self.install_synthetic_provision()
        discovery = self.get("run-proof.json")["discovery"]
        self.assertEqual(checker.selected_runtime(discovery), provision["image"])
        mutations = (
            lambda d: d.update(selected_runtime_image="latest"),
            lambda d: d.update(selected_runtime_image=d["runtime_image"]),
            lambda d: d.pop("provision"),
            lambda d: d["provision"]["recipe"].update(base_image="sha256:" + "f" * 64),
            lambda d: d["provision"]["recipe"]["pins"]["neo4j"].update(sha256="f" * 64),
            lambda d: d["provision"]["image_projection"].update(Recipe="f" * 64),
            lambda d: d["provision"]["image_projection"].update(Layers=["sha256:" + "f" * 64]),
            lambda d: d["provision"]["readback"].update(files_verified=True),
            lambda d: d["provision"]["readback"].update(egress_denied=False),
            lambda d: d["provision"].update(cleanup_verified=False),
        )
        for index, mutate in enumerate(mutations):
            changed = copy.deepcopy(discovery)
            mutate(changed)
            with self.subTest(index=index), self.assertRaises((AssertionError, KeyError)):
                checker.selected_runtime(changed)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-proof-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.make_fixture()

    def put(self, name, body):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(body) if not isinstance(body, str) else body)

    def get(self, name):
        return json.loads((self.root / name).read_text())

    def seal(self):
        run = self.get("run-proof.json")
        run["artifacts"] = {str(p.relative_to(self.root)): sha(p.read_bytes())
                            for p in self.root.rglob("*") if p.is_file()
                            and (p.parts[-1] in {"ownership.json", "source-manifest.json", "dependency-manifest.json", "provision-manifest.json"}
                                 or p.is_relative_to(self.root / "evidence"))}
        self.put("run-proof.json", run)

    def change(self, name, mutate, reseal=True):
        value = self.get(name)
        mutate(value)
        self.put(name, value)
        if reseal:
            self.seal()

    def make_fixture(self):
        # Minimal synthetic data: this checks the checker, not Arena validity or execution.
        fixture = "env_name: synthetic\n"
        version = {"schema_version": 2, "status": "passed"}
        pre = dict(version, uid=1000, egress_denied=True, errno=101, before_repository_imports=True,
                   caps="0000000000000000", no_new_privileges=True, readonly_source_root_deps=True, gpu_devices=[])
        counts = dict.fromkeys(("network", "provider", "graph", "render", "workload", "subprocess"), 0)
        source = "isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml"
        view = sha(json.dumps([source, fixture, {}], sort_keys=True))[:32]
        validation = {"valid": True, "source_hash": sha(fixture), "canonical_hash": "a" * 64,
                      "assets": [{"id": "synthetic"}], "graph": {"nodes": [{"id": "synthetic"}], "edges": []}}
        schema_body = {"type": "object"}
        catalogue_body = {"assets": {"synthetic": True}, "relations": {"synthetic": True}, "tasks": {"synthetic": True}}
        metadata_sha = lambda value: sha(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))
        schema = {"schema_version": 1, "read_only": True, "schema": schema_body, "schema_sha256": metadata_sha(schema_body)}
        catalogues = {"schema_version": 1, "read_only": True, "catalogues": catalogue_body,
                      "catalogue_sha256": metadata_sha(catalogue_body)}
        api = dict(version, preimport=pre, source=source, source_id=sha(source)[:32], view_id=view,
                   source_hash=sha(fixture), yaml_text=fixture, document={"source": source, "document_id": view,
                   "source_hash": sha(fixture), "yaml_text": fixture, "validation": validation},
                   validation=validation, validation_request={"yaml_text": fixture, "document_id": view},
                   invalid_validation={"valid": False, "errors": ["synthetic error"]}, schema=schema,
                   catalogues=catalogues, jobs=[], forbidden=counts, session_csrf_verified=True,
                   metadata_subprocesses=[], metadata_replays=2,
                   metadata_capture={"argv": ["/usr/bin/git", "version"], "cwd": "/", "timeout_seconds": 2,
                                     "before_repository_imports": True, "stdout": "git version 2.43.0\n", "returncode": 0},
                   capabilities=dict.fromkeys(
                       ("generation", "snapshots", "neo4j", "research_versions", "publication_execution"), False),
                   http=[{"method": "GET", "path": "/api/editor", "status": 401},
                         {"method": "POST", "path": "/api/editor/validate", "status": 403}])
        self.put("evidence/api-proof.json", api)
        self.put("evidence/preimport-api.json", pre)
        self.put("evidence/preimport-browser.json", dict(pre, code="ENETUNREACH"))
        self.put("evidence/api-final.json", dict(version, forbidden=counts, jobs=[], lifespan_closed=True, socket_absent=True))
        exchanges = []
        for seq, text in enumerate((fixture + "\n", fixture), 1):
            payload = {"yaml_text": text, "document_id": view}
            exchanges.append({"sequence": seq, "request_body": json.dumps(payload), "request": payload,
                              "response_request_sequence": seq, "status": 200,
                              "response": dict(validation, source_hash=sha(text))})
        frontend = {"playwright_version": "1.58.2", "files": dict.fromkeys(
            (".package-lock.json", "@playwright/test/package.json", "vite/package.json"), "d" * 64)}
        web = dict(version, preimport=dict(pre, code="ENETUNREACH"), source=source, source_id=api["source_id"],
                   view_id=view, source_hash=sha(fixture), schema_valid_visible=True, layout="legacy", layout_verified=True,
                   validation_exchanges=exchanges, validation_phases=[
                       {"phase": "edit", "after_sequence": 0, "request_sequence": 1},
                       {"phase": "restore", "after_sequence": 1, "request_sequence": 2}],
                   validation_request=api["validation_request"], validation=validation,
                   final_editor_yaml=fixture, final_editor_sha256=sha(fixture), final_editor_visible=True,
                   final_editor_readback="visible-codemirror-select-all-clipboard", frontend_dependencies=frontend,
                   browser_version="synthetic", external=[], errors=[], forbidden=[],
                   http=[{"method": "GET", "path": "/api/editor/documents/" + str(api["source_id"]), "status": 200}],
                   readbacks={"schema": {"status": 200, "body": schema}, "catalogues": {"status": 200, "body": catalogues},
                              "jobs": {"status": 200, "body": {"jobs": []}}})
        self.put("evidence/browser-proof.json", web)
        for name in ("browser.png", "browser-trace.zip", "build.log", "dist/index.html"):
            self.put("evidence/" + name, "synthetic contract test artifact, not real pixels or trace")
        manifest = {source: sha(fixture)}
        self.put("source/" + source, fixture)
        for name in ("api.py", "run.py", "stage.py", "check_proof.py", "browser.mjs"):
            relative = "web/arena-workbench/tests/e2e/functional-v7/" + name
            self.put("source/" + relative, "synthetic source\n")
            manifest[relative] = sha("synthetic source\n")
        for name in ("src/main.tsx", "vite.config.ts", "package.json", "index.html"):
            relative = "web/arena-workbench/" + name
            self.put("source/" + relative, "synthetic frontend source\n")
            manifest[relative] = sha("synthetic frontend source\n")
        self.put("source-manifest.json", manifest)
        self.put("pydeps/neo4j/__init__.py", "# synthetic inert bytes\n")
        runtime_id, runtime_image, browser_image = "1" * 64, "sha256:" + "2" * 64, "sha256:" + "3" * 64
        dependency = {"source_container": "6" * 64, "source_image": runtime_image,
                      "source_role": "dependency", "discovered_runtime_id": runtime_id,
                      "path": "/isaac-sim/kit/python/lib/python3.12/site-packages/neo4j",
                      "probe": {"schema_version": 1, "status": "passed", "uid": 1000,
                                "egress_denied": True, "before_package_imports": True,
                                "errno": 101, "roots": ["/isaac-sim/kit/python/lib/python3.12/site-packages"],
                                "packages": ["/isaac-sim/kit/python/lib/python3.12/site-packages/neo4j"]},
                      "trust": "installed immutable image; bounded descriptor-confined source-only archive",
                      "files": {"neo4j/__init__.py": sha("# synthetic inert bytes\n")}}
        self.put("dependency-manifest.json", dependency)
        token, host_output = "arena-f0-synthetic", "/host/.runs/arena-f0-synthetic"
        containers, cleanup = [], []
        for role, digit, image in (("api", "4", runtime_image), ("browser", "5", browser_image), ("dependency", "6", runtime_image)):
            name, identity = token + "-" + role, digit * 64
            mounts = [{"Type": "bind", "Source": host_output + "/" + folder, "Destination": destination, "RW": rw}
                      for folder, destination, rw in (("source", "/source", False), ("evidence", "/evidence", True),
                                                       ("bridge", "/bridge", role == "api"))]
            if role == "api":
                mounts.append({"Type": "bind", "Source": host_output + "/pydeps", "Destination": "/pydeps", "RW": False})
            else:
                mounts.extend([{"Type": "bind", "Source": host_output + "/source/web/arena-workbench", "Destination": "/app", "RW": False},
                               {"Type": "volume", "Name": "synthetic-deps", "Source": "/volume", "Destination": "/app/node_modules", "RW": False}])
            if role == "dependency":
                mounts = []
            containers.append({"id": identity, "name": "/" + name, "image": image, "user": "1000:1000",
                               "labels": {"arena.functional-v7": token}, "mounts": mounts,
                               "host_config": {"NetworkMode": "none", "ReadonlyRootfs": True, "CapDrop": ["ALL"],
                               "SecurityOpt": ["no-new-privileges"], "CapAdd": [], "Devices": [], "DeviceRequests": [], "Privileged": False,
                               "PortBindings": {}, "Binds": [], "PidsLimit": 256, "Memory": 4294967296,
                               "PidMode": "", "IpcMode": "private", "UsernsMode": "", "VolumesFrom": None,
                               "Tmpfs": {"/tmp": "rw,nosuid,nodev", "/private": "rw,nosuid,nodev"}}})
            cleanup.append({"name": name, "id": identity, "removed": True, "ownership_verified": True})
        candidates = [row["name"].lstrip("/") for row in containers]
        ownership = dict(version, run=token, candidates=candidates, containers=containers, cleanup=cleanup,
                         created_ids={row["name"][1:]: row["id"] for row in containers},
                         verified_isolation=dict.fromkeys(candidates, True),
                         cleanup_verified=True, evidence_errors=[], staged_source_hash_errors=[], live_source_hash_errors=[],
                         remaining_owned=[], cleanup_errors=[], cleanup_verification={"status": "passed", "authoritative": True,
                         "label_ids": [], "candidate_ids": dict.fromkeys(candidates, [])})
        ownership["schema_version"] = 3
        self.put("ownership.json", ownership)
        run = dict(ownership, browser=True, layout="legacy", mutations_enabled=False, host_output=host_output,
                   source_sha256=manifest, staged_source_unchanged=True, live_source_changed_since_capture=[],
                   staging={"policy_version": 2, "approved_fixture": source,
                            "manifest_sha256": sha((self.root / "source-manifest.json").read_bytes())},
                   dependency=dependency, frontend_dependencies=frontend, discovery={"runtime_id": runtime_id,
                   "runtime_image": runtime_image, "browser_image": browser_image, "deps": "synthetic-deps"})
        self.put("run-proof.json", run)
        self.seal()

    def rejected(self):
        with self.assertRaises((AssertionError, KeyError, ValueError, OSError, TypeError)):
            checker.check(self.root, browser=True)

    def test_authoring_profile_cannot_borrow_or_downgrade_readonly_proof(self):
        self.mirrored_rejection(lambda p: p.update(profile='authoring-v1'))
        self.mirrored_rejection(lambda p: p.update(profile='unknown-profile'))
        self.mirrored_rejection(lambda p: p.update(allowed_mutations=['keyed-editor-save-fresh-private-state']))

    def test_complete_synthetic_contract(self):
        checker.check(self.root, browser=True)

    def mirrored_rejection(self, mutate):
        # Reseal BOTH records so only the semantic guard can reject this case.
        # Restore after each subtest: an earlier corruption must not mask another.
        originals = {name: self.get(name) for name in ("run-proof.json", "ownership.json")}
        try:
            for name in originals:
                self.change(name, mutate)
            self.rejected()
        finally:
            for name, value in originals.items():
                self.put(name, value)
            self.seal()

    def test_created_ack_and_true_isolation_required_for_each_role(self):
        for field in ("created_ids", "verified_isolation"):
            with self.subTest(field=field, case="missing"):
                self.mirrored_rejection(lambda p: p.pop(field))
            for replacement in ({}, [], {"arena-f0-synthetic-donor": "9" * 64}):
                with self.subTest(field=field, replacement=replacement):
                    self.mirrored_rejection(lambda p: p.update({field: replacement}))
            with self.subTest(field=field, case="extra role"):
                self.mirrored_rejection(lambda p: p[field].update({"arena-f0-synthetic-donor": True}))
            for name in self.get("run-proof.json")["candidates"]:
                with self.subTest(field=field, name=name, case="missing role"):
                    self.mirrored_rejection(lambda p: p[field].pop(name))
                values = ("9" * 64, "short", None) if field == "created_ids" else (False, 1, "true", None)
                for value in values:
                    with self.subTest(field=field, name=name, value=value):
                        self.mirrored_rejection(lambda p: p[field].update({name: value}))

    def test_created_ack_and_isolation_must_match_ownership_mirror(self):
        for field, value in (("created_ids", "9" * 64), ("verified_isolation", False), ("verified_isolation", 1)):
            original = self.get("ownership.json")
            with self.subTest(field=field):
                self.change("ownership.json", lambda p: p[field].update({p["candidates"][0]: value}))
                self.rejected()
                self.put("ownership.json", original); self.seal()

    def test_required_safe_namespaces_and_no_inherited_volumes_for_each_role(self):
        for index in range(3):
            for field, unsafe in {"PidMode": ("host", "container:other", False),
                                  "IpcMode": ("host", "container:other", "", None),
                                  "UsernsMode": ("host", "container:other", False),
                                  "VolumesFrom": (["other:rw"], {}, False)}.items():
                with self.subTest(role=index, field=field, case="missing"):
                    self.mirrored_rejection(lambda p: p["containers"][index]["host_config"].pop(field))
                for value in unsafe:
                    with self.subTest(role=index, field=field, value=value):
                        self.mirrored_rejection(lambda p: p["containers"][index]["host_config"].update({field: value}))

    def test_producer_safe_namespace_representations(self):
        for value in (None, ""):
            for name in ("run-proof.json", "ownership.json"):
                self.change(name, lambda p: [c["host_config"].update(PidMode=value, UsernsMode=value, VolumesFrom=[])
                                             for c in p["containers"]])
            checker.check(self.root, browser=True)

    def test_metadata_requires_trusted_capture_and_zero_package_processes(self):
        name = "evidence/api-proof.json"
        original = self.get(name)
        cases: list = [lambda p, field=field: p.pop(field)
                 for field in ("metadata_capture", "metadata_subprocesses", "metadata_replays")]
        for value in (None, {}, False, [["git", "version"]], [["git", "version"], ["git", "version"]]):
            cases.append(lambda p, value=value: p.update(metadata_subprocesses=value))
        for value in (None, False, True, 0, -1, 3, 2.0, "2"):
            cases.append(lambda p, value=value: p.update(metadata_replays=value))
        capture_cases = {"argv": (["git", "version"], ["/tmp/git", "version"], ["/usr/bin/git", "--version"]),
                         "cwd": ("/tmp", None), "timeout_seconds": (0, 3, 2.0, True),
                         "before_repository_imports": (False, 1), "returncode": (1, False, 0.0),
                         "stdout": (None, "", "git version 2.43.0", "git version synthetic\n",
                                    "git version 2\n", "git version 2.43.0\nextra\n", "git version ２.43.0\n")}
        for field, values in capture_cases.items():
            cases.append(lambda p, field=field: p["metadata_capture"].pop(field))
            for value in values:
                cases.append(lambda p, field=field, value=value: p["metadata_capture"].update({field: value}))
        cases.append(lambda p: p["metadata_capture"].update(executable="/tmp/git"))
        for index, mutate in enumerate(cases):
            with self.subTest(case=index):
                try:
                    self.change(name, mutate)
                    self.rejected()
                finally:
                    self.put(name, original); self.seal()

    def test_metadata_capture_preserves_supported_version_bytes_and_replay_budget(self):
        for reads, version in ((1, "git version 2.43.0\n"), (2, "git version 2.43.0.windows.1\n")):
            with self.subTest(reads=reads):
                self.change("evidence/api-proof.json", lambda p: p.update(metadata_replays=reads))
                self.change("evidence/api-proof.json", lambda p: p["metadata_capture"].update(stdout=version))
                checker.check(self.root, browser=True)

    def test_finalization_requires_true_cleanup_and_empty_error_arrays(self):
        for field, bad_values in {"cleanup_verified": (False, 1, None),
                                  "evidence_errors": (["evidence/result"], None, False, {}),
                                  "staged_source_hash_errors": ([checker.FIXTURE], None, False, {}),
                                  "live_source_hash_errors": ([checker.FIXTURE], None, False, {})}.items():
            with self.subTest(field=field, case="missing"):
                self.mirrored_rejection(lambda p: p.pop(field))
            for value in bad_values:
                with self.subTest(field=field, value=value):
                    self.mirrored_rejection(lambda p: p.update({field: value}))
            # A contradictory ownership snapshot cannot be hidden by a clean run record.
            original = self.get("ownership.json")
            with self.subTest(field=field, case="ownership only"):
                try:
                    self.change("ownership.json", lambda p: p.update({field: bad_values[0]}))
                    self.rejected()
                finally:
                    self.put("ownership.json", original); self.seal()

    def test_recorded_live_changes_are_allowed_under_frozen_source_scope(self):
        for name in ("ownership.json", "run-proof.json"):
            self.change(name, lambda p: p.update(live_source_changed_since_capture=[checker.FIXTURE],
                        acceptance_scope="Frozen staged source; not a live-tree stability acceptance"))
        result = checker.check(self.root, browser=True)
        self.assertIn("self-authored hashes do not establish authenticity", result["scope"])

    def test_complete_api_only_synthetic_contract(self):
        def api_only(p):
            name = p["run"] + "-browser"
            p["candidates"].remove(name)
            for field in ("created_ids", "verified_isolation"):
                p[field].pop(name)
            p["containers"] = [row for row in p["containers"] if row["name"] != "/" + name]
            p["cleanup"] = [row for row in p["cleanup"] if row["name"] != name]
            p["cleanup_verification"]["candidate_ids"].pop(name)
            p["browser"] = False
        for name in ("run-proof.json", "ownership.json"):
            self.change(name, api_only)
        self.assertFalse(checker.check(self.root)["browser"])

    def test_resealed_dependency_donor_identity_is_not_a_runtime_identity(self):
        for name in ("dependency-manifest.json", "run-proof.json"):
            self.change(name, lambda p: (p["dependency"] if "dependency" in p else p).update(source_container="9" * 64))
        self.rejected()

    def test_dependency_identity_and_probe_contradictions_resealed(self):
        originals = {name: self.get(name) for name in ("run-proof.json", "dependency-manifest.json")}
        cases = [("source_container", "1" * 64), ("source_container", "4" * 64),
                 ("source_image", "sha256:" + "9" * 64), ("source_role", "api"),
                 ("discovered_runtime_id", "9" * 64), ("path", "/tmp/site-packages/neo4j"),
                 ("trust", "live mutable copy")]
        cases += [("probe." + key, value) for key, values in {
            "egress_denied": [False, 1], "before_package_imports": [False, 1],
            "uid": [0, True], "errno": [111, True], "packages": [[], ["/unobserved/neo4j"]],
            "roots": [[], ["/tmp/site-packages"], ["/isaac-sim/../site-packages"]]
        }.items() for value in values]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                try:
                    for name in originals:
                        record = copy.deepcopy(originals[name])
                        dep = record["dependency"] if name == "run-proof.json" else record
                        target = dep["probe"] if field.startswith("probe.") else dep
                        target[field.split(".")[-1]] = value
                        self.put(name, record)
                    self.seal()
                    self.rejected()
                finally:
                    for name, record in originals.items():
                        self.put(name, record)
                    self.seal()
        checker.check(self.root, browser=True)

    def test_dependency_mirror_rejects_boolean_integer_alias(self):
        self.change("run-proof.json", lambda p: p["dependency"]["probe"].update(egress_denied=1))
        self.rejected()

    def test_old_envelope_rejected_without_upgrade(self):
        self.mirrored_rejection(lambda p: p.update(schema_version=2))

    def test_missing_required_schema_fields(self):
        for name, keys in {
            "run-proof.json": ["schema_version", "status", "artifacts", "staging", "dependency", "cleanup_verification"],
            "evidence/api-proof.json": ["status", "schema_version", "source", "document", "validation_request", "preimport"],
            "evidence/api-final.json": ["status", "forbidden"],
            "evidence/browser-proof.json": ["status", "preimport", "validation_phases", "final_editor_yaml", "layout_verified"],
        }.items():
            for key in keys:
                with self.subTest(name=name, key=key):
                    original = self.get(name)
                    self.change(name, lambda value: value.pop(key), reseal=key != "artifacts")
                    self.rejected()
                    self.put(name, original); self.seal()

    def test_empty_missing_extra_and_boolean_counters(self):
        for counts in ({}, {"network": 0}, dict.fromkeys(("network", "provider", "graph", "render", "workload", "subprocess"), False),
                       {**dict.fromkeys(("network", "provider", "graph", "render", "workload", "subprocess"), 0), "extra": 0}):
            with self.subTest(counts=counts):
                self.change("evidence/api-final.json", lambda value: value.update(forbidden=counts))
                self.rejected()

    def test_empty_artifact_manifest(self):
        self.change("run-proof.json", lambda value: value.update(artifacts={}), reseal=False)
        self.rejected()

    def test_missing_required_artifact_even_when_resealed(self):
        for name in ("evidence/preimport-api.json", "evidence/preimport-browser.json", "ownership.json", "evidence/browser.png"):
            with self.subTest(name=name):
                original = (self.root / name).read_bytes()
                (self.root / name).unlink(); self.seal(); self.rejected()
                (self.root / name).write_bytes(original); self.seal()

    def test_tampered_bytes(self):
        self.change("evidence/api-proof.json", lambda value: value.update(status="failed"), reseal=False)
        self.rejected()

    def test_rehashed_contradictions(self):
        cases = [("evidence/api-proof.json", lambda p: p.update(status="failed")),
                 ("evidence/api-proof.json", lambda p: p["document"].update(document_id="0" * 32)),
                 ("evidence/browser-proof.json", lambda p: p.update(source_id="0" * 32)),
                 ("evidence/browser-proof.json", lambda p: p.update(layout="v7")),
                 ("evidence/browser-proof.json", lambda p: p.update(final_editor_yaml="wrong\n")),
                 ("evidence/browser-proof.json", lambda p: p["validation_phases"][1].update(request_sequence=1)),
                 ("evidence/browser-proof.json", lambda p: p["validation_exchanges"][1].update(response_request_sequence=1)),
                 ("evidence/browser-proof.json", lambda p: p["validation_exchanges"][1].update(request_body='{}')),
                 ("evidence/browser-proof.json", lambda p: p["readbacks"]["schema"]["body"].update(schema_sha256="0" * 64)),
                 ("run-proof.json", lambda p: p["containers"][0].update(id="9" * 64)),
                 ("run-proof.json", lambda p: p["dependency"].update(source_container="9" * 64)),
                 ("evidence/preimport-browser.json", lambda p: p.update(egress_denied=False))]
        for name, mutate in cases:
            with self.subTest(name=name, mutate=mutate):
                original = copy.deepcopy(self.get(name))
                self.change(name, mutate); self.rejected()
                self.put(name, original); self.seal()

    def test_artifact_path_traversal_and_symlink(self):
        self.change("run-proof.json", lambda p: p["artifacts"].update({"../escape": "0" * 64}), reseal=False)
        self.rejected()
        self.seal()
        (self.root / "evidence/build.log").unlink()
        (self.root / "evidence/build.log").symlink_to(self.root / "evidence/browser.png")
        self.seal(); self.rejected()

    def test_duplicate_json_keys(self):
        self.put("evidence/api-final.json", '{"status":"failed","status":"passed"}')
        self.seal(); self.rejected()

    def test_resealed_source_cannot_omit_harness_or_entrypoints(self):
        relative = "web/arena-workbench/tests/e2e/functional-v7/browser.mjs"
        (self.root / "source" / relative).unlink()
        manifest = self.get("source-manifest.json")
        manifest.pop(relative)
        self.put("source-manifest.json", manifest)
        def mutate(run):
            run["source_sha256"] = manifest
            run["staging"]["manifest_sha256"] = sha((self.root / "source-manifest.json").read_bytes())
        self.change("run-proof.json", mutate)
        self.rejected()

    def test_matching_ownership_cannot_hide_added_capabilities(self):
        for name in ("run-proof.json", "ownership.json"):
            self.change(name, lambda p: p["containers"][0]["host_config"].update(CapAdd=["SYS_ADMIN"]))
        self.rejected()

    def test_matching_schema_bodies_must_match_their_content_hash(self):
        self.change("evidence/api-proof.json", lambda p: p["schema"]["schema"].update(type="array"))
        self.change("evidence/browser-proof.json", lambda p: p["readbacks"]["schema"]["body"]["schema"].update(type="array"))
        self.rejected()

    def test_empty_required_browser_artifact_even_when_resealed(self):
        self.put("evidence/browser.png", "")
        self.seal()
        self.rejected()

    def test_staged_source_and_dependency_byte_tampering(self):
        for relative in ("source/web/arena-workbench/tests/e2e/functional-v7/api.py", "pydeps/neo4j/__init__.py"):
            with self.subTest(relative=relative):
                old = (self.root / relative).read_bytes()
                (self.root / relative).write_bytes(old + b"tamper")
                self.rejected()
                (self.root / relative).write_bytes(old)

    def test_api_only_cannot_downgrade_a_browser_run(self):
        self.change("evidence/browser-proof.json", lambda p: p.update(status="failed"))
        with self.assertRaises((AssertionError, KeyError, ValueError)):
            checker.check(self.root, browser=False)


if __name__ == "__main__":
    unittest.main()
