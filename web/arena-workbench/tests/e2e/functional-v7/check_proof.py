# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Fail-closed v3 envelope/v2 wire checker; hashes are NOT authenticity."""
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath

VERSION = 3
WIRE_VERSION = 2
FIXTURE = "isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml"
COUNTERS = frozenset(("network", "provider", "graph", "render", "workload", "subprocess"))
LABEL = "arena.functional-v7"
REQUIRED_ARTIFACTS = frozenset(("ownership.json", "source-manifest.json", "dependency-manifest.json",
                                "evidence/api-proof.json", "evidence/api-final.json", "evidence/preimport-api.json"))
BROWSER_ARTIFACTS = frozenset(("evidence/browser-proof.json", "evidence/preimport-browser.json",
                               "evidence/browser.png", "evidence/browser-trace.zip", "evidence/build.log",
                               "evidence/dist/index.html"))
FRONTEND_FILES = frozenset((".package-lock.json", "@playwright/test/package.json", "vite/package.json"))
HARNESS_PREFIX = "web/arena-workbench/tests/e2e/functional-v7/"
REQUIRED_SOURCE = frozenset(HARNESS_PREFIX + name for name in ("api.py", "run.py", "stage.py", "check_proof.py"))
BROWSER_SOURCE = frozenset((HARNESS_PREFIX + "browser.mjs", *("web/arena-workbench/" + name for name in
                            ("src/main.tsx", "vite.config.ts", "package.json", "index.html"))))


def sha(value):
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def digest(value):
    assert isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "Invalid SHA-256"
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, f"Duplicate JSON key: {key}"
        result[key] = value
    return result


def parse(raw):
    return json.loads(raw, object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def confined(root, relative):
    assert isinstance(relative, str) and relative, "Empty artifact path"
    parts = PurePosixPath(relative)
    assert not parts.is_absolute() and ".." not in parts.parts and str(parts) == relative, "Unsafe artifact path"
    target = root
    for part in parts.parts:
        target = target / part
        assert not target.is_symlink(), f"Symlink denied: {relative}"
    assert target.is_file(), f"Missing artifact: {relative}"
    return target


def load(root, name):
    return parse(confined(root, name).read_text(encoding="utf-8"))


def passed(value, version=WIRE_VERSION):
    assert type(value) is dict and type(value["schema_version"]) is int and value["schema_version"] == version
    assert value["status"] == "passed", "Missing/failed success status"
    assert not value.get("error") and not value.get("failure"), "Contradictory success/error"


def counters(value):
    assert type(value) is dict and set(value) == COUNTERS, "Exact nonempty forbidden counter set required"
    assert all(type(count) is int and count == 0 for count in value.values()), "Forbidden activity or invalid counter"


def preimport(value, browser=False):
    passed(value)
    assert type(value["uid"]) is int and value["uid"] == 1000
    for field in ("egress_denied", "before_repository_imports", "no_new_privileges", "readonly_source_root_deps"):
        assert value[field] is True, field
    assert isinstance(value["caps"], str) and re.fullmatch(r"0+", value["caps"])
    assert value["gpu_devices"] == []
    if browser:
        assert value["code"] in {"ENETUNREACH", "EHOSTUNREACH", "EPERM", "EACCES"}
    else:
        assert type(value["errno"]) is int and value["errno"] in {101, 113, 1, 13}


def hashed_tree(root, manifest):
    assert type(manifest) is dict and manifest, "Nonempty byte manifest required"
    for name, expected in manifest.items():
        assert sha(confined(root, name).read_bytes()) == digest(expected), f"Byte hash mismatch: {name}"
    actual = set()
    for target in root.rglob("*"):
        assert not target.is_symlink(), f"Symlink denied: {target}"
        if target.is_file():
            actual.add(target.relative_to(root).as_posix())
    assert actual == set(manifest), "Unmanifested/missing staged bytes"


PROVISION_LABEL = "arena.functional-v7.provision-recipe"
PROVISION_PINS = {
    "neo4j": {"version": "6.2.0", "filename": "neo4j-6.2.0-py3-none-any.whl",
              "sha256": "b87abdd13a5cc2e3bd51026926c2f20ac38fa3febe98c340520dce19e97388d0"},
    "pytz": {"version": "2026.3.post1", "filename": "pytz-2026.3.post1-py2.py3-none-any.whl",
             "sha256": "dd95840dd199baea12d9cc096a1d452caa6596a1c1e4b5f3dbd1541855d5e815"},
}


def selected_runtime(discovery):
    """Keep live discovery immutable; accept only a separately bound test image."""
    base = discovery["runtime_image"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", base)
    if "selected_runtime_image" not in discovery:
        assert "provision" not in discovery, "Unbound provision record"
        return base
    image = discovery["selected_runtime_image"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image) and image != base, "Invalid test image override"
    provision = discovery["provision"]
    passed(provision, 1)
    assert provision["image"] == image
    recipe = provision["recipe"]
    assert type(recipe["schema_version"]) is int and recipe["schema_version"] == 1
    assert recipe["base_image"] == base and recipe["scope"] == "test-only declared neo4j plus pytz"
    assert recipe["pins"] == PROVISION_PINS
    assert recipe["build_policy"] == "COPY-only; network=none; no RUN; no package execution"
    assert recipe["python_version"][:2] == [3, 12] and all(type(x) is int for x in recipe["python_version"])
    root = recipe["purelib"]
    assert root.startswith("/isaac-sim/") and root.endswith("/site-packages")
    assert str(PurePosixPath(root)) == root and ".." not in PurePosixPath(root).parts
    digest(recipe["declaration_sha256"])
    digest(recipe["acquisition_sha256"])
    files = recipe["files"]
    assert type(files) is dict and 0 < len(files) <= 4096
    for name, value in files.items():
        parts = PurePosixPath(name).parts
        assert name == "/".join(parts) and len(parts) >= 2 and not any(x in ("", ".", "..") for x in name.split("/"))
        assert parts[0] in {"neo4j", "pytz", "neo4j-6.2.0.dist-info", "pytz-2026.3.post1.dist-info"}
        digest(value)
    assert "neo4j/__init__.py" in files and "pytz/__init__.py" in files
    recipe_hash = sha(json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode())
    assert provision["recipe_sha256"] == recipe_hash
    parent, child = provision["base_projection"], provision["image_projection"]
    assert parent["Id"] == base and child["Id"] == image
    assert not parent["Volumes"] and not child["Volumes"]
    assert child["Recipe"] == recipe_hash
    layers = parent["Layers"]
    assert type(layers) is list and layers and len(layers) <= 128
    assert child["Layers"][:-1] == layers, "Test image is not a single COPY layer over base"
    for layer in child["Layers"]:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", layer)
    readback = provision["readback"]
    passed(readback, 1)
    assert readback["recipe_sha256"] == recipe_hash
    assert type(readback["files_verified"]) is int and readback["files_verified"] == len(files)
    assert readback["uid"] == 1000 and type(readback["uid"]) is int
    assert readback["egress_denied"] is True and readback["before_package_imports"] is True
    assert type(readback["errno"]) is int and readback["errno"] in (101, 113, 1, 13)
    assert provision["cleanup_verified"] is True
    return image


def ownership(root, run, browser):
    record = load(root, "ownership.json")
    passed(record, VERSION)
    for field in ("run", "candidates", "created_ids", "verified_isolation", "containers", "cleanup",
                  "remaining_owned", "cleanup_errors", "cleanup_verification", "cleanup_verified",
                  "evidence_errors", "staged_source_hash_errors", "live_source_hash_errors"):
        assert json.dumps(record[field], sort_keys=True) == json.dumps(run[field], sort_keys=True), f"Ownership contradiction: {field}"
    token = run["run"]
    assert isinstance(token, str) and re.fullmatch(r"arena-f0-[a-z0-9-]+", token)
    roles = ("dependency", "api", "browser") if browser else ("dependency", "api")
    names = {token + "-" + role for role in roles}
    assert type(run["candidates"]) is list and len(run["candidates"]) == len(names) and set(run["candidates"]) == names
    for field in ("created_ids", "verified_isolation"):
        assert type(run[field]) is dict and set(run[field]) == names, f"Exact intended roles required: {field}"
    assert all(value is True for value in run["verified_isolation"].values()), "Unverified isolation"
    assert run["cleanup_verified"] is True, "Cleanup not verified"
    for field in ("remaining_owned", "cleanup_errors", "evidence_errors", "staged_source_hash_errors", "live_source_hash_errors"):
        assert run[field] == [], f"Contradictory successful finalization: {field}"
    listing = run["cleanup_verification"]
    assert listing["status"] == "passed" and listing["authoritative"] is True and listing["label_ids"] == []
    assert listing["candidate_ids"] == {name: [] for name in names}
    discovery = run["discovery"]
    digest(discovery["runtime_id"])
    host_output = run["host_output"]
    assert isinstance(host_output, str) and host_output.startswith("/") and host_output.endswith("/.runs/" + token)
    assert ".." not in PurePosixPath(host_output).parts
    assert len(run["containers"]) == len(names) and len(run["cleanup"]) == len(names)
    by_name, identities = {}, set()
    for container in run["containers"]:
        name = container["name"]
        assert name.startswith("/") and name[1:] in names and name not in by_name
        by_name[name] = container
        identity = digest(container["id"])
        assert digest(run["created_ids"][name[1:]]) == identity, "Create ACK/container identity contradiction"
        assert identity not in identities
        identities.add(identity)
        role = name.removeprefix("/" + token + "-")
        image = discovery["browser_image"] if role == "browser" else selected_runtime(discovery)
        assert identity != discovery["runtime_id"], "Owned identity cannot be the live runtime"
        assert isinstance(image, str) and image.startswith("sha256:")
        digest(image[7:])
        assert container["image"] == image and container["labels"][LABEL] == token and container["user"] == "1000:1000"
        host = container["host_config"]
        assert host["NetworkMode"] == "none" and host["ReadonlyRootfs"] is True
        assert host["CapDrop"] == ["ALL"] and "no-new-privileges" in host["SecurityOpt"]
        assert host["CapAdd"] in ([], None), "Added capabilities invalidate isolation"
        assert host["Privileged"] is False and host["Devices"] in ([], None) and host["DeviceRequests"] in ([], None)
        assert host["PortBindings"] in ({}, None) and host["Binds"] in ([], None)
        assert host["PidMode"] in ("", None) and host["IpcMode"] == "private", "Unsafe PID/IPC namespace"
        assert host["UsernsMode"] in ("", None), "Unsafe user namespace"
        assert host["VolumesFrom"] in ([], None), "Inherited volumes invalidate isolation"
        assert type(host["PidsLimit"]) is int and 0 < host["PidsLimit"] <= 256
        assert type(host["Memory"]) is int and 0 < host["Memory"] <= 4294967296
        assert set(host["Tmpfs"]) == {"/tmp", "/private"}
        assert all({"rw", "nosuid", "nodev"} <= set(options.split(",")) for options in host["Tmpfs"].values())
        expected = {"/source": ("source", False), "/evidence": ("evidence", True), "/bridge": ("bridge", role == "api")}
        expected.update({"/pydeps": ("pydeps", False)} if role == "api" else
                        {"/app": ("source/web/arena-workbench", False), "/app/node_modules": (None, False)})
        if role == "dependency":
            expected = {}  # Immutable donor has no source, state or dependency mounts.
        mounts = {mount["Destination"]: mount for mount in container["mounts"]}
        assert len(mounts) == len(container["mounts"]) and set(mounts) == set(expected), "Unexpected mount coverage"
        for destination, (folder, writable) in expected.items():
            mount = mounts[destination]
            assert mount["RW"] is writable
            if folder is None:
                assert mount["Type"] == "volume" and mount["Name"] == discovery["deps"] and mount["Name"]
            else:
                assert mount["Type"] == "bind" and mount["Source"] == host_output + "/" + folder
    cleaned = set()
    for cleanup in run["cleanup"]:
        assert cleanup["name"] in names and cleanup["name"] not in cleaned
        cleaned.add(cleanup["name"])
        assert cleanup["id"] == by_name["/" + cleanup["name"]]["id"]
        assert cleanup["removed"] is True and cleanup["ownership_verified"] is True


def dependency_contract(run, dependency):
    """Bind distinct immutable donor and API identities, never the live runtime."""
    assert dependency["source_role"] == "dependency"
    donor = run["created_ids"][run["run"] + "-dependency"]
    assert digest(dependency["source_container"]) == donor
    assert donor != run["created_ids"][run["run"] + "-api"] != run["discovery"]["runtime_id"]
    assert donor != run["discovery"]["runtime_id"]
    assert dependency["discovered_runtime_id"] == run["discovery"]["runtime_id"]
    assert dependency["source_image"] == selected_runtime(run["discovery"])
    if "provision" in run["discovery"]:
        recipe = run["discovery"]["provision"]["recipe"]
        assert dependency["path"] == recipe["purelib"] + "/neo4j", "Provision/donor path mismatch"
        expected = {name: value for name, value in recipe["files"].items() if name.startswith("neo4j/")}
        assert dependency["files"] == expected, "Provision/donor bytes mismatch"
    assert dependency["trust"] == "installed immutable image; bounded descriptor-confined source-only archive"
    probe = dependency["probe"]
    passed(probe, 1)
    assert type(probe["uid"]) is int and probe["uid"] == 1000
    assert probe["egress_denied"] is True and probe["before_package_imports"] is True
    assert type(probe["errno"]) is int and probe["errno"] in (101, 113, 1, 13)
    roots = probe["roots"]
    assert type(roots) is list and roots and len(roots) == len(set(roots)) and len(roots) <= 32
    for root in roots:
        assert isinstance(root, str) and root.startswith("/isaac-sim/")
        assert ".." not in PurePosixPath(root).parts and str(PurePosixPath(root)) == root
        assert root.endswith("/site-packages")
    path = dependency["path"]
    assert probe["packages"] == [path] and path in [root + "/neo4j" for root in roots]


def browser_proof(root, run, api, text):
    web = load(root, "evidence/browser-proof.json")
    passed(web)
    standalone = load(root, "evidence/preimport-browser.json")
    preimport(standalone, browser=True)
    assert web["preimport"] == standalone
    for field in ("source", "source_id", "view_id", "source_hash"):
        assert web[field] == api[field], f"Browser document identity: {field}"
    assert web["layout"] == run["layout"] and web["layout_verified"] is True
    assert web["schema_valid_visible"] is True
    assert web["final_editor_visible"] is True
    assert web["final_editor_yaml"] == text and web["final_editor_sha256"] == sha(text)
    assert web["final_editor_readback"] == "visible-codemirror-select-all-clipboard"
    assert isinstance(web["browser_version"], str) and web["browser_version"]
    assert web["external"] == [] and web["errors"] == [] and web["forbidden"] == []
    assert any(row == {"method": "GET", "path": "/api/editor/documents/" + api["source_id"], "status": 200}
               for row in web["http"])
    frontend = web["frontend_dependencies"]
    assert frontend == run["frontend_dependencies"]
    assert frontend["playwright_version"] == "1.58.2" and set(frontend["files"]) == FRONTEND_FILES
    for value in frontend["files"].values():
        digest(value)
    exchanges = web["validation_exchanges"]
    assert isinstance(exchanges, list) and len(exchanges) >= 2
    by_sequence = {}
    for index, exchange in enumerate(exchanges, 1):
        assert type(exchange["sequence"]) is int and exchange["sequence"] == index, "Distinct monotonic request sequence required"
        assert parse(exchange["request_body"]) == exchange["request"], "Exact outbound body mismatch"
        assert set(exchange["request"]) == {"yaml_text", "document_id"}
        by_sequence[index] = exchange
    phases = web["validation_phases"]
    assert isinstance(phases, list) and [phase["phase"] for phase in phases] == ["edit", "restore"]
    previous = 0
    for phase, expected in zip(phases, (text + "\n", text)):
        after, sequence = phase["after_sequence"], phase["request_sequence"]
        assert type(after) is int and type(sequence) is int and previous <= after < sequence
        exchange = by_sequence[sequence]
        assert exchange["request"] == {"yaml_text": expected, "document_id": api["view_id"]}
        assert exchange["response_request_sequence"] == sequence and exchange["status"] == 200
        assert not exchange.get("error")
        result = exchange["response"]
        assert result["valid"] is True and result["source_hash"] == sha(expected)
        assert result["canonical_hash"] == api["validation"]["canonical_hash"]
        previous = sequence
    restored = by_sequence[previous]
    assert web["validation_request"] == restored["request"] == api["validation_request"]
    assert web["validation"] == restored["response"] == api["validation"]
    for kind in ("schema", "catalogues", "jobs"):
        readback = web["readbacks"][kind]
        assert readback["status"] == 200
        if kind == "jobs":
            assert readback["body"]["jobs"] == []
        else:
            assert readback["body"] == api[kind], f"Browser {kind} contradiction"


AUTHORING_CHECKS = frozenset(('supported_table_actual_schema', 'invalid_schema_save_disabled',
    'candidate_transport_error_disables_apply',
    'stale_option_aba_consent_retired', 'same_editor_through_apply', 'dirty_cancel_zero_document_reads',
    'same_editor_navigation_prompt', 'save_does_not_open', 'library_exact_revision_before_open',
    'explicit_open_same_editor', 'reload_exact_root_hash_origin_theme', 'zero_jobs', 'exact_blob_bytes',
    'consent_and_fresh_validation_each_xyz'))


def authoring_contract(a, validations, api, final):
    """Check additive authoring evidence without replacing the original F0 baseline."""
    from urllib.parse import unquote
    passed(a, 1)
    assert a['profile'] == final['profile'] == 'authoring-v1'
    assert a['remaining'] == []
    assert set(a['checks']) == AUTHORING_CHECKS and all(value is True for value in a['checks'].values())
    original, draft = a['initial_draft'], a['final_draft']
    assert sha(draft) == a['final_sha256'] and original != draft
    proposals = a['proposals']
    assert len(proposals) == 3
    prior = original
    for axis, proposal in enumerate(proposals):
        assert type(proposal['axis']) is int and proposal['axis'] == axis
        assert proposal['original'] == prior
        # Independent byte-preservation check, not the editor's CST helper.
        match = re.search(r'position_xyz: \[([^\]]+)\]', prior)
        assert match and prior.count('position_xyz:') == 1
        coordinates = match[1].split(', ')
        assert len(coordinates) == 3
        coordinates[axis] = ('1.25', '-0.25', '0.125')[axis]
        candidate = prior[:match.start(1)] + ', '.join(coordinates) + prior[match.end(1):]
        assert proposal['candidate'] == candidate and candidate != prior
        digest(proposal['canonical_hash'])
        prior = candidate
    assert prior == draft
    wanted = [('raw-supported-table', original), ('invalid-raw', 'unknown_field: true\n'),
              ('recover-valid-raw', original), ('candidate-0', proposals[0]['candidate']),
              ('candidate-0-after-aba', proposals[0]['candidate']), ('fresh-applied-0', proposals[0]['candidate']),
              ('candidate-1', proposals[1]['candidate']), ('fresh-applied-1', proposals[1]['candidate']),
              ('candidate-2', draft), ('fresh-applied-2', draft)]
    assert [(p['phase'], p['yaml']) for p in a['phases']] == wanted
    by_sequence = {row['sequence']: row for row in validations}
    previous = 0
    results = {}
    for phase in a['phases']:
        after, sequence = phase['after_sequence'], phase['request_sequence']
        assert type(after) is int and type(sequence) is int and previous <= after < sequence
        row = by_sequence[sequence]
        assert row['status'] == 200 and row['response_request_sequence'] == sequence
        assert parse(row['request_body']) == row['request'] == {'yaml_text': phase['yaml'], 'document_id': api['view_id']}
        response = row['response']
        assert response['valid'] is (phase['phase'] != 'invalid-raw')
        assert response['source_hash'] == sha(phase['yaml'])
        if phase['phase'] != 'invalid-raw': digest(response['canonical_hash'])
        results[phase['phase']] = response
        previous = sequence
    for axis, proposal in enumerate(proposals):
        assert results[f'candidate-{axis}']['canonical_hash'] == results[f'fresh-applied-{axis}']['canonical_hash'] == proposal['canonical_hash']
    wire = a['exchanges']
    assert [r['sequence'] for r in wire] == list(range(1, len(wire) + 1))
    def exchange(field, method, path):
        sequence = a[field]
        assert type(sequence) is int and sequence > 0
        row = wire[sequence - 1]
        assert row['sequence'] == row['response_request_sequence'] == sequence and row['status'] == 200
        assert row['method'] == method and unquote(row['path']) == path
        return row
    saved = exchange('save_sequence', 'POST', '/api/editor/save')
    request = saved['request']
    assert set(request) == {'yaml_text', 'document_id', 'expected_source_hash', 'idempotency_key'}
    assert re.fullmatch(r'[A-Za-z0-9_-]{1,128}', request['idempotency_key'])
    assert request['yaml_text'] == draft and request['document_id'] == api['view_id']
    assert request['expected_source_hash'] == api['source_hash']
    receipt = saved['response']
    assert receipt['schema_version'] == 1 and type(receipt['schema_version']) is int and receipt['state'] == 'committed'
    assert receipt['idempotency_key'] == request['idempotency_key']
    assert receipt['request_sha256'] == sha(json.dumps(['editor-save/v1', draft, api['view_id'], api['source_hash']], separators=(',', ':'), ensure_ascii=False))
    revision = receipt['revision']
    rid = revision['revision_id']
    assert re.fullmatch(r'[a-f0-9]{32}', rid)
    source = 'editor-revision:' + rid
    assert revision['open_source'] == {'kind': 'editor_revision', 'id': source}
    assert revision['download_url'] == f'/api/editor/revisions/{rid}/download'
    assert revision['yaml_text'] == draft and revision['source_hash'] == sha(draft)
    assert revision['canonical_hash'] == proposals[-1]['canonical_hash']
    readback = exchange('receipt_get_sequence', 'GET', '/api/editor/save-requests/' + request['idempotency_key'])
    assert readback['response'] == receipt
    index = exchange('library_index_sequence', 'GET', '/api/editor')
    rows = [r for r in index['response']['documents'] if r['id'] == source]
    assert len(rows) == 1
    assert {k: rows[0][k] for k in ('kind', 'revision_id', 'source_hash', 'canonical_hash')} == {
        'kind': 'editor_revision', 'revision_id': rid, 'source_hash': sha(draft), 'canonical_hash': revision['canonical_hash']}
    opened = exchange('open_sequence', 'GET', '/api/editor/documents/' + source)
    reloaded = exchange('reload_sequence', 'GET', '/api/editor/documents/' + source)
    assert a['save_sequence'] < a['receipt_get_sequence'] <= a['library_index_sequence'] < a['open_sequence'] < a['reload_sequence']
    assert re.fullmatch(r'[a-f0-9]{32}', reloaded['response']['document_id'])
    assert {k: v for k, v in opened['response'].items() if k != 'document_id'} == {k: v for k, v in reloaded['response'].items() if k != 'document_id'}
    document = opened['response']
    assert re.fullmatch(r'[a-f0-9]{32}', document['document_id'])
    assert document['source_origin'] == revision['open_source'] and document['source'] == source
    assert document['yaml_text'] == draft and document['source_hash'] == sha(draft)
    assert document['validation']['valid'] is True and document['validation']['source_hash'] == sha(draft)
    assert document['validation']['canonical_hash'] == revision['canonical_hash']
    writes = [r for r in wire if r['method'] == 'POST' and r['path'] == '/api/editor/save']
    assert writes == [saved], 'Exactly one durable Save, never implicit replay'
    assert final['allowed_authoring_writes'] == [{'method': 'POST', 'path': '/api/editor/save', 'request': request, 'status': 200}]
    recreated = final['recreated_documents']
    assert len(recreated) == 1 and recreated[0]['receipt'] == receipt
    assert recreated[0]['scope'] == 'fresh Documents service over same private durable state; not API process restart'
    fresh = recreated[0]['document']
    assert re.fullmatch(r'[a-f0-9]{32}', fresh['document_id'])
    assert {k: v for k, v in fresh.items() if k != 'document_id'} == {k: v for k, v in document.items() if k != 'document_id'}
    assert a['jobs']['status'] == 200 and a['jobs']['body']['jobs'] == []
    geometry = a['geometry']
    assert [(r['width'], r['theme']) for r in geometry] == [(w, t) for w in (1440, 390) for t in ('dark', 'light')]
    for row in geometry:
        assert type(row['scrollWidth']) is int and row['scrollWidth'] <= row['width'] + 1
        assert type(row['editorWidth']) in (int, float) and 0 < row['editorWidth'] <= row['width']
        assert type(row['background']) is str and row['background']
    return a


def authoring_proof(root, run, api, final, web):
    assert run['layout'] == 'v7' and run['browser'] is True
    assert run['allowed_mutations'] == ['keyed-editor-save-fresh-private-state']
    assert api['profile'] == web['profile'] == run['profile'] == 'authoring-v1'
    a = authoring_contract(web['authoring'], web['validation_exchanges'], api, final)
    assert HARNESS_PREFIX + 'browser-authoring.mjs' in run['source_sha256']
    for field, expected in [('download_before_apply', a['initial_draft']), ('download_after_apply', a['final_draft'])]:
        download = a[field]
        name = 'evidence/' + download['artifact']
        assert name in run['artifacts']
        raw = confined(root, name).read_bytes()
        assert raw == expected.encode('utf-8') and len(raw) == download['bytes']
        assert sha(raw) == download['sha256'] and download['url_scheme'] == 'blob:'
        assert isinstance(download['suggested_filename'], str) and download['suggested_filename']
    assert a['revision_download']['status'] == 200
    assert confined(root, 'evidence/authoring-revision-export.yaml').read_text() == a['revision_download']['text']
    assert sha(a['revision_download']['text']) == a['revision_download']['sha256']
    names = ['authoring-reviewed-diff.png', 'authoring-library-before-open.png',
             *[f'authoring-{w}-{t}.png' for w in (1440, 390) for t in ('dark', 'light')], 'authoring-reloaded.png']
    assert a['screenshots'] == names
    for name in names:
        assert 'evidence/' + name in run['artifacts']
        raw = confined(root, 'evidence/' + name).read_bytes()
        assert len(raw) > 100 and raw.startswith(b'\x89PNG\r\n\x1a\n')


def check(directory, browser=False):
    # Assertions are validation logic; never silently accept with python -O.
    if not __debug__:
        raise RuntimeError("Proof checking requires assertions enabled")
    root = Path(directory).resolve()
    run = load(root, "run-proof.json")
    passed(run, VERSION)
    assert type(run["browser"]) is bool and (not browser or run["browser"]), "Browser evidence required"
    browser = run["browser"]  # A CLI omission cannot downgrade an asserted browser run.
    profile = run.get("profile", "readonly")
    assert profile in {"readonly", "authoring-v1", "manual-research-v1"}
    if profile in {"authoring-v1", "manual-research-v1"}:
        assert browser and run["layout"] == "v7"
    else:
        assert not run.get("allowed_mutations")
    assert run["layout"] in {"legacy", "v7"}
    assert run["mutations_enabled"] is (profile != "readonly")
    artifacts = run["artifacts"]
    required = REQUIRED_ARTIFACTS | (BROWSER_ARTIFACTS if browser else frozenset())
    assert type(artifacts) is dict and required <= set(artifacts), "Required hashed artifact coverage missing"
    for name in required:
        assert confined(root, name).stat().st_size > 0, f"Empty required artifact: {name}"
    for name, expected in artifacts.items():
        assert sha(confined(root, name).read_bytes()) == digest(expected), f"Artifact hash mismatch: {name}"
    for target in (root / "evidence").rglob("*"):
        assert not target.is_symlink()
        if target.is_file():
            assert target.relative_to(root).as_posix() in artifacts, "Unhashed evidence artifact"
    ownership(root, run, browser)
    manifest = load(root, "source-manifest.json")
    assert manifest == run["source_sha256"]
    hashed_tree(root / "source", manifest)
    assert REQUIRED_SOURCE | (BROWSER_SOURCE if browser else frozenset()) <= set(manifest), "Required staged sources missing"
    assert FIXTURE in manifest and [name for name in manifest if name.endswith((".yaml", ".yml"))] == [FIXTURE]
    staging = run["staging"]
    assert staging["policy_version"] == 2 and staging["approved_fixture"] == FIXTURE
    assert staging["manifest_sha256"] == artifacts["source-manifest.json"]
    assert run["staged_source_unchanged"] is True and type(run["live_source_changed_since_capture"]) is list
    assert set(run["live_source_changed_since_capture"]) <= set(manifest)
    if "selected_runtime_image" in run["discovery"]:
        assert "provision-manifest.json" in run["artifacts"], "Provision artifact absent"
        assert json.dumps(load(root, "provision-manifest.json"), sort_keys=True) == json.dumps(run["discovery"]["provision"], sort_keys=True)
    dependency = load(root, "dependency-manifest.json")
    assert json.dumps(dependency, sort_keys=True) == json.dumps(run["dependency"], sort_keys=True)
    dependency_contract(run, dependency)
    assert all(name.startswith("neo4j/") for name in dependency["files"])
    hashed_tree(root / "pydeps", dependency["files"])
    api, final = load(root, "evidence/api-proof.json"), load(root, "evidence/api-final.json")
    passed(api); passed(final)
    counters(api["forbidden"]); counters(final["forbidden"])
    assert api["forbidden"] == final["forbidden"] and api["jobs"] == final["jobs"] == []
    assert final["lifespan_closed"] is True and final["socket_absent"] is True
    standalone = load(root, "evidence/preimport-api.json")
    preimport(standalone)
    assert api["preimport"] == standalone
    text = confined(root / "source", FIXTURE).read_bytes().decode("utf-8")
    assert api["source"] == FIXTURE and api["yaml_text"] == text and api["source_hash"] == sha(text)
    assert api["source_id"] == sha(FIXTURE)[:32]
    assert api["view_id"] == sha(json.dumps([FIXTURE, text, {}], sort_keys=True))[:32] != api["source_id"]
    document = api["document"]
    for field, expected in {"source": FIXTURE, "document_id": api["view_id"], "yaml_text": text,
                            "source_hash": sha(text), "validation": api["validation"]}.items():
        assert document[field] == expected, f"API loaded document contradiction: {field}"
    assert api["validation_request"] == {"yaml_text": text, "document_id": api["view_id"]}
    validation = api["validation"]
    assert validation["valid"] is True and validation["source_hash"] == sha(text)
    digest(validation["canonical_hash"])
    assert type(validation["assets"]) is list and validation["assets"]
    assert type(validation["graph"]["nodes"]) is list and validation["graph"]["nodes"]
    assert type(validation["graph"]["edges"]) is list
    assert api["invalid_validation"]["valid"] is False and api["invalid_validation"]["errors"]
    assert api["schema"]["read_only"] is True and api["schema"]["schema"]
    assert api["catalogues"]["read_only"] is True
    digest(api["schema"]["schema_sha256"]); digest(api["catalogues"]["catalogue_sha256"])
    # Production catalogue metadata uses compact, sorted stdlib JSON, not proof-file formatting.
    for kind, body_field, hash_field in (("schema", "schema", "schema_sha256"),
                                        ("catalogues", "catalogues", "catalogue_sha256")):
        metadata = api[kind]
        assert type(metadata["schema_version"]) is int and metadata["schema_version"] == 1
        assert type(metadata[body_field]) is dict and metadata[body_field]
        assert sha(json.dumps(metadata[body_field], sort_keys=True, separators=(",", ":"), allow_nan=False)) == metadata[hash_field]
    assert set(api["catalogues"]["catalogues"]) == {"assets", "relations", "tasks"}
    assert api["session_csrf_verified"] is True
    for capability in ("generation", "snapshots", "neo4j", "research_versions", "publication_execution"):
        assert api["capabilities"][capability] is (profile == 'manual-research-v1' and capability == 'research_versions')
    for expected in ({"method": "GET", "path": "/api/editor", "status": 401},
                     {"method": "POST", "path": "/api/editor/validate", "status": 403}):
        assert expected in api["http"]
    # Match api.capture_git_metadata/main, not the retired OS subprocess allowance.
    # These self-reported bytes are consistency evidence, not executable attestation.
    assert api["metadata_subprocesses"] == [], "Package-triggered OS subprocesses denied"
    capture = api["metadata_capture"]
    assert type(capture) is dict and set(capture) == {
        "argv", "cwd", "timeout_seconds", "before_repository_imports", "stdout", "returncode"}
    assert capture["argv"] == ["/usr/bin/git", "version"] and capture["cwd"] == "/"
    assert type(capture["timeout_seconds"]) is int and capture["timeout_seconds"] == 2
    assert capture["before_repository_imports"] is True
    assert type(capture["returncode"]) is int and capture["returncode"] == 0
    assert isinstance(capture["stdout"], str) and re.fullmatch(
        r"git version [0-9]+(?:\.[0-9]+)+(?:[.A-Za-z0-9+-]*)\n", capture["stdout"])
    # Fresh genuine GitPython import uses one or two reads; its adapter caps at two.
    assert type(api["metadata_replays"]) is int and api["metadata_replays"] in (1, 2)
    if browser:
        browser_proof(root, run, api, text)
    if profile == "authoring-v1":
        authoring_proof(root, run, api, final, load(root, "evidence/browser-proof.json"))
    elif profile == "manual-research-v1":
        from manual_research import proof as manual_proof
        manual_proof(root, run, api, final, load(root, "evidence/browser-proof.json"))
    else:
        assert api.get("profile", "readonly") == final.get("profile", "readonly") == "readonly"
        assert not final.get("allowed_authoring_writes")
        if browser:
            web = load(root, "evidence/browser-proof.json")
            assert web.get("profile", "readonly") == "readonly" and "authoring" not in web
            assert not any(r["method"] == "POST" and r["path"] == "/api/editor/save" for r in web["http"])
    result = {"verified": True, "schema_version": VERSION, "source_id": api["source_id"], "view_id": api["view_id"],
              "canonical_hash": validation["canonical_hash"], "browser": browser, "layout": run["layout"], "profile": profile,
              "scope": "artifact consistency only; self-authored hashes do not establish authenticity or full acceptance"}
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    check(sys.argv[1], "--browser" in sys.argv[2:])
