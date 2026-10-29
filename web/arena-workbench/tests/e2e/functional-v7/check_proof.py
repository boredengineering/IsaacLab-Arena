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


GRAPHQL_PINS = {'cross-web': {'version': '0.6.0', 'filename': 'cross_web-0.6.0-py3-none-any.whl', 'sha256': 'bdebf0c08d02f3a48cf67b6904d3a6d8fd8cab2cd905592ab96ab00b259cd582'}, 'graphql-core': {'version': '3.2.6', 'filename': 'graphql_core-3.2.6-py3-none-any.whl', 'sha256': '78b016718c161a6fb20a7d97bbf107f331cd1afe53e45566c59f776ed7f0b45f'}, 'strawberry-graphql': {'version': '0.327.7', 'filename': 'strawberry_graphql-0.327.7-py3-none-any.whl', 'sha256': '0c653f16fe2a35b5a672fb5492cee5243a2f44f209247a946eddc1a6399b2284'}}
GRAPHQL_FILES_SHA256 = '9d37bef3c9b7d9ad84de543401b6da1d65474efb4dc77c8236ffa9f5e39454e8'
GRAPHQL_LABEL = 'arena.functional-v7.graphql-test-v1-recipe'
GRAPHQL_RECIPE = '/opt/arena-f0/graphql-test-v1-recipe.json'
GRAPHQL_PARENT = 'sha256:e20b3cc8258b793aaf1fe47c130f54e677fa9c0a6427991cfc1045b743162da5'
GRAPHQL_ROOTS = frozenset(('strawberry', 'graphql', 'cross_web', 'strawberry_graphql-0.327.7.dist-info',
                           'graphql_core-3.2.6.dist-info', 'cross_web-0.6.0.dist-info'))


GRAPHQL_ARCHIVE = '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle'
GRAPHQL_URDF = '/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle'
GRAPHQL_CIP = '/isaac-sim/extscache/omni.cip.pip-2.0.5+lx64.cp312/pip_prebundle'
GRAPHQL_LANGCHAIN = '/isaac-sim/extscache/omni.ai.langchain.core-2.3.1+109.0.0.lx64.cp312/pip_core_prebundle'
GRAPHQL_CLOSURE_SHA256 = '0b360d1a033cde87a76984848f6cfa57e6bf2c7abf61aa1f2b60e32f1463253d'
# Observed fixed-parent module bytes plus independently verified metadata. No path search.
GRAPHQL_IMPORT_BINDINGS = {'annotated-doc': ('annotated_doc',
                   '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/annotated_doc/__init__.py',
                   '/isaac-sim/extscache/omni.ai.langchain.core-2.3.1+109.0.0.lx64.cp312/pip_core_prebundle/annotated_doc/__init__.py',
                   '56ecb1c547bcd247c4c969ceac2c7f064f21c9ba3768aa3a4580659010585bc9',
                   '0.0.4',
                   '/isaac-sim/extscache/omni.ai.langchain.core-2.3.1+109.0.0.lx64.cp312/pip_core_prebundle/annotated_doc-0.0.4.dist-info/METADATA',
                   '22b9b9289b9adf7758daa28a02327e3a129a5415487f01467a3fdd49edd9d535'),
 'annotated-types': ('annotated_types',
                     '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/annotated_types/__init__.py',
                     '/isaac-sim/extscache/omni.ai.langchain.core-2.3.1+109.0.0.lx64.cp312/pip_core_prebundle/annotated_types/__init__.py',
                     '4729cbb112941062342a2997c9d943d5f6447c4cd6c03a345289f7cce2a11b54',
                     '0.7.0',
                     '/isaac-sim/extscache/omni.ai.langchain.core-2.3.1+109.0.0.lx64.cp312/pip_core_prebundle/annotated_types-0.7.0.dist-info/METADATA',
                     'ee5b6ac64b09274c026051813484025939564067801f485115d9cadc207cf791'),
 'anyio': ('anyio',
           '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/anyio/__init__.py',
           '/isaac-sim/extscache/omni.ai.langchain.core-2.3.1+109.0.0.lx64.cp312/pip_core_prebundle/anyio/__init__.py',
           'ee20d5a8c529ad4b8a358f7516ea0aa9ac80851f8e635dfa6033c8e8fefc1c79',
           '4.13.0',
           '/isaac-sim/extscache/omni.ai.langchain.core-2.3.1+109.0.0.lx64.cp312/pip_core_prebundle/anyio-4.13.0.dist-info/METADATA',
           '1741187e23e5993470989376264b4dc4983518d9e5d301e1cce5a6cfba45be33'),
 'certifi': ('certifi',
             '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/certifi/__init__.py',
             '/isaac-sim/extscache/omni.ai.langchain.core-2.3.1+109.0.0.lx64.cp312/pip_core_prebundle/certifi/__init__.py',
             '8812585adc5118731a3b54bbde9598a459fdeb6590e257687f61a47cc4911093',
             '2026.4.22',
             '/isaac-sim/extscache/omni.ai.langchain.core-2.3.1+109.0.0.lx64.cp312/pip_core_prebundle/certifi-2026.4.22.dist-info/METADATA',
             '4ed6ffe9ccbed05046ab7bff2024cd3ca717295b368bed1fe20a73e365bc415a'),
 'click': ('click',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/click/__init__.py',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/click/__init__.py',
           '1487767d7092241df27960fe7b6b8e37e9818456b661cf4cbd71a61eef0e5c6d',
           '8.4.2',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/click-8.4.2.dist-info/METADATA',
           '194c9dd81d567f9081f026c7e401060fbafa7bc147c8e0a58b3668b40a64c031'),
 'cross-web': ('cross_web',
               '/isaac-sim/kit/python/lib/python3.12/site-packages/cross_web/__init__.py',
               '/isaac-sim/kit/python/lib/python3.12/site-packages/cross_web/__init__.py',
               '2ea83dc27100c94d4a93aedd17b76553f666c90bcc26de4f8ac4c509e5c11b66',
               '0.6.0',
               '/isaac-sim/kit/python/lib/python3.12/site-packages/cross_web-0.6.0.dist-info/METADATA',
               '01b2065fab9296a63400e07fbda77a30504ea77e7aa9bec831df3f7edeec1ba5'),
 'fastapi': ('fastapi',
             '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/fastapi/__init__.py',
             '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/fastapi/__init__.py',
             'ca12fe54331fb6134c68bbdb23e41814668b8278c1bc4384f6bd1b5d6ec712b4',
             '0.120.4',
             '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/fastapi-0.120.4.dist-info/METADATA',
             'a1dd127a7eb392206aabd1c193aba2762f833e0624323bd1c19106b670036e8c'),
 'graphql-core': ('graphql',
                  '/isaac-sim/kit/python/lib/python3.12/site-packages/graphql/__init__.py',
                  '/isaac-sim/kit/python/lib/python3.12/site-packages/graphql/__init__.py',
                  '76310514cd898a782af162dbf9b9f8cc7ace58e25c774e553c3b42389ba09896',
                  '3.2.6',
                  '/isaac-sim/kit/python/lib/python3.12/site-packages/graphql_core-3.2.6.dist-info/METADATA',
                  '8facd74087696305b3eb65824752359fa05a2b4abdc3a4900a06d20f85abfa26'),
 'h11': ('h11',
         '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/h11/__init__.py',
         '/isaac-sim/extscache/omni.ai.langchain.core-2.3.1+109.0.0.lx64.cp312/pip_core_prebundle/h11/__init__.py',
         '88ed4ace448ee36c99e9f7e0f953206f1fd9553586518d349d16045a7facde46',
         '0.16.0',
         '/isaac-sim/extscache/omni.ai.langchain.core-2.3.1+109.0.0.lx64.cp312/pip_core_prebundle/h11-0.16.0.dist-info/METADATA',
         '28f326098ac09fcba79b8f180f96087c841fe2456215cb7b872a9c7d5cd19d64'),
 'httpcore': ('httpcore',
              '/isaac-sim/kit/python/lib/python3.12/site-packages/httpcore/__init__.py',
              '/isaac-sim/kit/python/lib/python3.12/site-packages/httpcore/__init__.py',
              'f644ff92a0a10822544c7c30db866647f7b371d6e94585a4b03fa060dce464ff',
              '1.0.9',
              '/isaac-sim/kit/python/lib/python3.12/site-packages/httpcore-1.0.9.dist-info/METADATA',
              'fe2d4fda6199128978779e0cf27f3c045c531863fcdd987eacc74f3a18d41c21'),
 'httpx': ('httpx',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/httpx/__init__.py',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/httpx/__init__.py',
           '0ac6997bac998f4ac783adf6d8058a587193315afdb718047c3e4fdff46bcfad',
           '0.28.1',
           '/isaac-sim/kit/python/lib/python3.12/site-packages/httpx-0.28.1.dist-info/METADATA',
           'febb9b0f8f3e80d57c8199c304f35c4336e8581d1d18d7983c92766b82793b25'),
 'idna': ('idna',
          '/isaac-sim/kit/python/lib/python3.12/site-packages/idna/__init__.py',
          '/isaac-sim/kit/python/lib/python3.12/site-packages/idna/__init__.py',
          '8514c3ed53136a3596ebdf512fa487bbdd7da5a99adcaed82e0363d2c306d3af',
          '3.19',
          '/isaac-sim/kit/python/lib/python3.12/site-packages/idna-3.19.dist-info/METADATA',
          '4d113161aca8582e8d28fddf3ea50f19b607209c2b3e4364379a163454680084'),
 'packaging': ('packaging',
               '/isaac-sim/kit/python/lib/python3.12/site-packages/packaging/__init__.py',
               '/isaac-sim/kit/python/lib/python3.12/site-packages/packaging/__init__.py',
               '12108cb824b3eb4220409f776ffe302720281e953d27eb9d746e1068c4f43eee',
               '23.2',
               '/isaac-sim/kit/python/lib/python3.12/site-packages/packaging-23.2.dist-info/METADATA',
               'b3574943ce848d906e97f50291034674771b2edb3a660e3f9b10aa93ad17eb1b'),
 'pydantic': ('pydantic',
              '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/pydantic/__init__.py',
              '/isaac-sim/extscache/omni.cip.pip-2.0.5+lx64.cp312/pip_prebundle/pydantic/__init__.py',
              '0f7ffed1a44fa00179107e13e093d53982cd11cf8379a09c0ede94cc88cffc3d',
              '2.11.10',
              '/isaac-sim/extscache/omni.cip.pip-2.0.5+lx64.cp312/pip_prebundle/pydantic-2.11.10.dist-info/METADATA',
              'c817ba01e7d4ae7d0996e833d0722eaaeb3b26c69755631eccb80ca3be041128'),
 'pydantic-core': ('pydantic_core',
                   '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/pydantic_core/__init__.py',
                   '/isaac-sim/extscache/omni.cip.pip-2.0.5+lx64.cp312/pip_prebundle/pydantic_core/__init__.py',
                   '4f3396b89320a5769970f892d988ddf0e52a8cf6ca3aea5dcd7a777598d60867',
                   '2.33.2',
                   '/isaac-sim/extscache/omni.cip.pip-2.0.5+lx64.cp312/pip_prebundle/pydantic_core-2.33.2.dist-info/METADATA',
                   'efc941a0e673e0acdfcf3ff2308fea147305b36484dd58275a97863ed8f270ab'),
 'python-dateutil': ('dateutil',
                     '/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle/dateutil/__init__.py',
                     '/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle/dateutil/__init__.py',
                     '32a6a6ebb58ef4891399417223aeaf4ba2284974e9f46dfcf0369d1f62c230b6',
                     '2.9.0.post0',
                     '/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle/python_dateutil-2.9.0.post0.dist-info/METADATA',
                     'a9d436da322be808332f98d88325998e87cb693a678a9969feb4cfad729a6e93'),
 'python-multipart': ('python_multipart',
                      '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/python_multipart/__init__.py',
                      '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/python_multipart/__init__.py',
                      '1c3e9769e00baf386ed2b9826c3094e6ff94fbbe848eb82b1dda241af25bb762',
                      '0.0.26',
                      '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/python_multipart-0.0.26.dist-info/METADATA',
                      'da2329774c7ec8d6739383843bb91c5d60e1e518f23a54350799dd12624b9d5d'),
 'six': ('six',
         '/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle/six.py',
         '/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle/six.py',
         'c51c91f703d3d4b3696c923cb5fec213e05e75d9215393befac7f2fa6a3904df',
         '1.17.0',
         '/isaac-sim/exts/isaacsim.asset.importer.urdf/pip_prebundle/six-1.17.0.dist-info/METADATA',
         '562042078c2752549f6d8a7c86dbc5dd708088a7be6d80672ec7b07100b72468'),
 'starlette': ('starlette',
               '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/starlette/__init__.py',
               '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/starlette/__init__.py',
               'ba9d47533e35c4b11c34f124d9b06cdc188647c62658b929f5557653f47681d9',
               '0.49.3',
               '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/starlette-0.49.3.dist-info/METADATA',
               '8f6f4e61ccf8e9510544010c954dfb0520d04aff39ab8af8fd3c43f8500213bd'),
 'strawberry-graphql': ('strawberry',
                        '/isaac-sim/kit/python/lib/python3.12/site-packages/strawberry/__init__.py',
                        '/isaac-sim/kit/python/lib/python3.12/site-packages/strawberry/__init__.py',
                        '609c5a0ae4f5ea569ea3894a1fa5c610c5f02c651c7e4a9375649a86b1228346',
                        '0.327.7',
                        '/isaac-sim/kit/python/lib/python3.12/site-packages/strawberry_graphql-0.327.7.dist-info/METADATA',
                        'f52830292aa3c0e63f449b541b7ada85b07880667332bb3afb2619009c2d354b'),
 'typing-extensions': ('typing_extensions',
                       '/isaac-sim/kit/python/lib/python3.12/site-packages/typing_extensions.py',
                       '/isaac-sim/kit/python/lib/python3.12/site-packages/typing_extensions.py',
                       '4040ca1a1ecbee00d1385c12a93084d1c5bd46f0b774f07e5ae7e91c4f55e696',
                       '4.16.0',
                       '/isaac-sim/kit/python/lib/python3.12/site-packages/typing_extensions-4.16.0.dist-info/METADATA',
                       'b05084ca1d50879865178d9fff9fabeab61bdfb1f361bfbde95421ffc8f9be46'),
 'typing-inspection': ('typing_inspection',
                       '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/typing_inspection/__init__.py',
                       '/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+f9bf0dda.lx64.cp312/pip_prebundle/typing_inspection/__init__.py',
                       'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
                       '0.4.2',
                       '/isaac-sim/extscache/omni.ai.langchain.core-2.3.1+109.0.0.lx64.cp312/pip_core_prebundle/typing_inspection-0.4.2.dist-info/METADATA',
                       '61096cd0bfe3c7040b6f98c22b02d190fe01936d0ff7616c5134fed02891953a'),
 'uvicorn': ('uvicorn',
             '/isaac-sim/kit/python/lib/python3.12/site-packages/uvicorn/__init__.py',
             '/isaac-sim/kit/python/lib/python3.12/site-packages/uvicorn/__init__.py',
             'd47fc9857b620dc0302aa3d4fdb29639cdf52e7de836ad3143386fded24574cc',
             '0.52.4',
             '/isaac-sim/kit/python/lib/python3.12/site-packages/uvicorn-0.52.4.dist-info/METADATA',
             '6cea83c70e4f2746374ca19af72a52406aa706ad8735b11d72fbd5fd82f7cbff')}


# Observed opportunistic parent imports, NOT added wheels or enabled extras.
GRAPHQL_INCIDENTAL = {'orjson': {'license': None,
            'license_expression': 'MPL-2.0 AND (Apache-2.0 OR MIT)',
            'name': 'orjson',
            'path': '/isaac-sim/kit/python/lib/python3.12/site-packages/orjson-3.12.0.dist-info/METADATA',
            'requires_dist': [],
            'requires_python': '>=3.10',
            'sha256': '3a04b81906c2ac8f535b0a4fb8371eea786718fbca08a75ff13f6c734f43b778',
            'version': '3.12.0'},
 'pygments': {'license': None,
              'license_expression': 'BSD-2-Clause',
              'name': 'Pygments',
              'path': '/isaac-sim/kit/python/lib/python3.12/site-packages/pygments-2.21.0.dist-info/METADATA',
              'requires_dist': ["colorama>=0.4.6; extra == 'windows-terminal'"],
              'requires_python': '>=3.9',
              'sha256': '1dde075570136774c706bf0009183a793fe0ee262e4a5590cc6eff8453eedd43',
              'version': '2.21.0'},
 'rich': {'license': 'MIT',
          'license_expression': None,
          'name': 'rich',
          'path': '/isaac-sim/kit/python/lib/python3.12/site-packages/rich-14.3.4.dist-info/METADATA',
          'requires_dist': ['ipywidgets (>=7.5.1,<9) ; extra == "jupyter"',
                            'markdown-it-py (>=2.2.0)',
                            'pygments (>=2.13.0,<3.0.0)'],
          'requires_python': '>=3.8.0',
          'sha256': 'efb5f04704b438de828e9e44d88b9f5ab91f6006acf55a7b40911ea43c230a41',
          'version': '14.3.4'},
 'sniffio': {'license': 'MIT OR Apache-2.0',
             'license_expression': None,
             'name': 'sniffio',
             'path': '/isaac-sim/kit/python/lib/python3.12/site-packages/sniffio-1.3.1.dist-info/METADATA',
             'requires_dist': [],
             'requires_python': '>=3.7',
             'sha256': '0b318b57098edeccf585e60a889a6b6a7b5c4086f3a9aa62eff76a1d3cee12d9',
             'version': '1.3.1'},
 'zstandard': {'license': None,
               'license_expression': 'BSD-3-Clause',
               'name': 'zstandard',
               'path': '/isaac-sim/kit/python/lib/python3.12/site-packages/zstandard-0.25.0.dist-info/METADATA',
               'requires_dist': ['cffi~=1.17; (platform_python_implementation != "PyPy" and python_version < "3.14") '
                                 'and extra == "cffi"',
                                 'cffi>=2.0.0b; (platform_python_implementation != "PyPy" and python_version >= '
                                 '"3.14") and extra == "cffi"'],
               'requires_python': '>=3.9',
               'sha256': '03d37736b26b9ae48451dd17026d93dffbd252fb708c1a2a9ae1be0c0966de92',
               'version': '0.25.0'}}
GRAPHQL_INCIDENTAL_MODULES_SHA256 = 'd616d4c4b33c0e29a23a7ba0371991d8b9dba06c5f3f59201dcf71e76d15fa83'
GRAPHQL_METADATA_FIELDS_SHA256 = '38db8b4ff7eee254ac05852c9a693adf0048f3cfbe8b8ed825b0cac1443d7a59'


GRAPHQL_CORE_EXTENSION_SHA256 = '2711a346eff384909098ae5a1d1db8a8f741f2300c59c1fc651f39c370b8d0b4'


def graphql_sys_path(purelib):
    """The reviewed isolated interpreter order, with only two existing bundle roots."""
    stdlib = str(PurePosixPath(purelib).parent)
    return [str(PurePosixPath(stdlib).parent)+'/python312.zip', stdlib, stdlib+'/lib-dynload',
            purelib, GRAPHQL_ARCHIVE, GRAPHQL_URDF]


def graphql_import_contract(provision):
    """Require actual imports, selected metadata and physical immutable origins."""
    proof = provision['imports']
    passed(proof, 1)
    assert proof['image'] == provision['image'] and proof['recipe_sha256'] == provision['recipe_sha256']
    assert proof['interpreter'] == '/isaac-sim/python.sh' and proof['executable'] == '/isaac-sim/kit/python/bin/python3'
    assert proof['python_version'] == [3,12,13] and all(type(x) is int for x in proof['python_version'])
    root = provision['recipe']['purelib']
    paths = graphql_sys_path(root)
    assert proof['sys_path'] == paths, 'GraphQL path binding'
    assert type(proof['uid']) is int and proof['uid'] == 1000
    assert type(proof['errno']) is int and proof['errno'] in (101,113,1,13)
    assert proof['egress_denied'] is True and proof['before_package_imports'] is True
    assert set(proof['forbidden']) == {'network','subprocess','blocked_import'}
    assert all(type(n) is int and n == 0 for n in proof['forbidden'].values())
    assert proof['constraints_passed'] is True
    allowed = (root, GRAPHQL_ARCHIVE, GRAPHQL_URDF, GRAPHQL_CIP, GRAPHQL_LANGCHAIN)
    def witness(value):
        import posixpath
        path = value['path']
        for field in ('path','physical'):
            assert any(value[field].startswith(r+'/') for r in allowed), 'Physical origin root'
            assert posixpath.normpath(value[field]) == value[field]
        digest(value['sha256'])
        assert type(value['size']) is int and 0 <= value['size'] <= 33554432
        assert type(value['links']) is list and len(value['links']) <= 16
        for link in value['links']:
            assert path == link['path'] or path.startswith(link['path']+'/'), 'Physical link chain'
            target = link['target']
            assert type(target) is str and target and len(target) <= 4096
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(link['path']),target))
            path = resolved + path[len(link['path']):]
            assert any(path.startswith(r+'/') for r in allowed), 'Physical link target root'
        assert path == value['physical'], 'Physical chain endpoint'
    expected_modules = {b[0] for b in GRAPHQL_IMPORT_BINDINGS.values()} | {'strawberry.fastapi','pydantic_core._pydantic_core'}
    assert set(proof['modules']) == expected_modules and set(proof['distributions']) == set(GRAPHQL_IMPORT_BINDINGS)
    for name, binding in GRAPHQL_IMPORT_BINDINGS.items():
        module, origin, physical, file_hash, version, meta_path, meta_hash = binding
        row = proof['modules'][module]
        assert row['origin'] == row['file'] == row['path'] == origin, 'Selected module origin'
        assert row['physical'] == physical and row['sha256'] == file_hash, 'Immutable module bytes'
        witness(row)
        dist = proof['distributions'][name]
        assert dist['version'] == version, 'Selected distribution version'
        assert dist['metadata']['physical'] == meta_path and dist['metadata']['sha256'] == meta_hash, 'Selected metadata bytes'
        witness(dist['metadata'])
        assert dist['requires_python'] is None or type(dist['requires_python']) is str
        assert type(dist['requires_dist']) is list and all(type(r) is str for r in dist['requires_dist'])
    for module in expected_modules - {b[0] for b in GRAPHQL_IMPORT_BINDINGS.values()}:
        row = proof['modules'][module]
        origin = (root+'/strawberry/fastapi/__init__.py' if module == 'strawberry.fastapi' else
                  GRAPHQL_ARCHIVE+'/pydantic_core/_pydantic_core.cpython-312-x86_64-linux-gnu.so')
        assert row['origin'] == row['file'] == row['path'] == origin
        if module == 'strawberry.fastapi':
            assert row['sha256'] == 'a79aa0f4096462334e58a713e2e46279b22947aa486f51ea0cc8837c5e4eded8'
        else:
            assert row['physical'] == GRAPHQL_CIP+'/pydantic_core/_pydantic_core.cpython-312-x86_64-linux-gnu.so'
            assert row['sha256'] == GRAPHQL_CORE_EXTENSION_SHA256, 'Immutable native core bytes'
        witness(row)
    canonical = lambda value: json.dumps(value,sort_keys=True,separators=(',',':'))
    assert sha(canonical({n:{k:r[k] for k in ('version','requires_python','requires_dist')}
                          for n,r in proof['distributions'].items()})) == GRAPHQL_METADATA_FIELDS_SHA256, 'Metadata fields'
    incidental = proof['incidental_distributions']
    assert set(incidental) == set(GRAPHQL_INCIDENTAL)
    for name,expected in GRAPHQL_INCIDENTAL.items():
        row = incidental[name]
        assert all(row[k] == expected[k] for k in ('version','requires_python','requires_dist')), 'Incidental metadata fields'
        assert row['metadata']['path'] == row['metadata']['physical'] == expected['path']
        assert row['metadata']['sha256'] == expected['sha256']
        witness(row['metadata'])
    loaded = proof['loaded_modules']
    extras = {n:r for n,r in loaded.items() if n.split('.')[0] not in {m.split('.')[0] for m in expected_modules}}
    assert sha(canonical(extras)) == GRAPHQL_INCIDENTAL_MODULES_SHA256, 'Exact incidental import bytes'
    assert expected_modules <= loaded.keys() and len(loaded) <= 1024
    for name,row in loaded.items():
        assert name.split('.')[0] in {n.split('.')[0] for n in expected_modules} | set(GRAPHQL_INCIDENTAL), 'Undeclared loaded dependency'
        assert row['origin'] == row['file'] == row['path']
        assert any(row['path'].startswith(r+'/') for r in (root,GRAPHQL_ARCHIVE,GRAPHQL_URDF))
        witness(row)
    assert all(loaded[n] == proof['modules'][n] for n in expected_modules)


def graphql_runtime(discovery):
    """Compose the fixed GraphQL child with an unchanged legacy parent proof."""
    provision = discovery['provision']
    passed(provision, 1)
    assert provision['profile'] == 'graphql-test-v1'
    parent_raw = provision['parent_manifest']
    assert type(parent_raw) is str and len(parent_raw.encode()) <= 1048576
    parent = parse(parent_raw)
    selected_runtime(dict(runtime_image=discovery['runtime_image'], selected_runtime_image=GRAPHQL_PARENT, provision=parent))
    recipe = provision['recipe']
    assert type(recipe['schema_version']) is int and recipe['schema_version'] == 1
    assert recipe['profile'] == 'graphql-test-v1' and recipe['pins'] == GRAPHQL_PINS, 'GraphQL pins'
    assert recipe['closure_sha256'] == GRAPHQL_CLOSURE_SHA256
    assert recipe['path_binding'] == 'isolated-sysconfig-kit-archive-urdf-v1'
    assert recipe['parent_manifest_sha256'] == sha(parent_raw), 'Parent manifest hash'
    assert recipe['parent_recipe_sha256'] == parent['recipe_sha256'], 'Parent recipe hash'
    assert recipe['base_image'] == GRAPHQL_PARENT and recipe['recipe_path'] == GRAPHQL_RECIPE
    assert recipe['build_policy'] == 'COPY-only; network=none; no RUN; no package execution'
    assert recipe['purelib'] == parent['recipe']['purelib']
    assert recipe['python_version'] == [3,12,13] and all(type(x) is int for x in recipe['python_version'])
    digest(recipe['acquisition_sha256'])
    files = recipe['files']
    canonical = lambda x: json.dumps(x, sort_keys=True, separators=(',', ':'))
    assert sha(canonical(files)) == GRAPHQL_FILES_SHA256, 'Exact reviewed wheel file map'
    assert {n.split('/')[0] for n in files} == GRAPHQL_ROOTS
    recipe_hash = sha(canonical(recipe))
    assert provision['recipe_sha256'] == recipe_hash
    image = discovery['selected_runtime_image']
    assert re.fullmatch(r'sha256:[0-9a-f]{64}', image) and image not in (GRAPHQL_PARENT, discovery['runtime_image'])
    assert provision['image'] == image
    assert provision['base_projection'] == parent['image_projection']
    child = provision['image_projection']
    assert child['Id'] == image and not child['Volumes']
    assert child['Recipe'] == parent['recipe_sha256'] and child['GraphQLRecipe'] == recipe_hash
    config = provision['parent_config_projection']
    assert {k:config[k] for k in parent['image_projection']} == parent['image_projection']
    assert config['GraphQLRecipe'] is None and GRAPHQL_LABEL not in config['Labels']
    assert child['Labels'] == {**config['Labels'],GRAPHQL_LABEL:recipe_hash}, 'Exact inherited and child labels'
    assert child['User'] == '1000:1000', 'GraphQL image user'

    assert child['Layers'][:-1] == parent['image_projection']['Layers'], 'GraphQL single COPY layer'
    assert all(re.fullmatch(r'sha256:[0-9a-f]{64}', layer) for layer in child['Layers'])
    absent = sorted([recipe['purelib']+'/'+r for r in GRAPHQL_ROOTS] + [GRAPHQL_RECIPE])
    for key in ('no_overwrite', 'readback'):
        value = provision[key]
        passed(value, 1)
        assert type(value['uid']) is int and value['uid'] == 1000
        assert type(value['errno']) is int and value['errno'] in (101,113,1,13)
        assert value['egress_denied'] is True and value['before_package_imports'] is True
        assert value['parent_recipe_sha256'] == parent['recipe_sha256']
    assert provision['no_overwrite']['absent'] == absent, 'No-overwrite targets'
    readback = provision['readback']
    assert readback['recipe_sha256'] == recipe_hash
    assert type(readback['files_verified']) is int and readback['files_verified'] == len(files)
    assert provision['cleanup_verified'] is True
    assert not provision.get('evidence_errors') and not provision.get('cleanup_errors')
    graphql_import_contract(provision)
    return image


def selected_runtime(discovery, *, profile=None):
    """Keep live discovery immutable; accept only a separately bound test image."""
    assert profile in (None, 'graphql-test-v1'), 'Unknown provision profile'
    if profile == 'graphql-test-v1':
        return graphql_runtime(discovery)
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
