#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Provision closed, explicit test images without installers or package acquisition execution.

The omitted profile remains declared Neo4j/pytz only. graphql-test-v1 adds exactly
three reviewed wheels over the preserved Neo4j image, with real denied import
compatibility proof. Acquisition is stdlib-only; builds are COPY-only/network-none.
Neither profile is a generic project installer or an API acceptance result.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys

# Deliberately local: the network-enabled acquisition process imports stdlib only.
PINS = {
    "neo4j": {"version": "6.2.0", "filename": "neo4j-6.2.0-py3-none-any.whl",
              "sha256": "b87abdd13a5cc2e3bd51026926c2f20ac38fa3febe98c340520dce19e97388d0"},
    "pytz": {"version": "2026.3.post1", "filename": "pytz-2026.3.post1-py2.py3-none-any.whl",
             "sha256": "dd95840dd199baea12d9cc096a1d452caa6596a1c1e4b5f3dbd1541855d5e815"},
}


GRAPHQL_PINS = {'cross-web': {'version': '0.6.0', 'filename': 'cross_web-0.6.0-py3-none-any.whl', 'sha256': 'bdebf0c08d02f3a48cf67b6904d3a6d8fd8cab2cd905592ab96ab00b259cd582'}, 'graphql-core': {'version': '3.2.6', 'filename': 'graphql_core-3.2.6-py3-none-any.whl', 'sha256': '78b016718c161a6fb20a7d97bbf107f331cd1afe53e45566c59f776ed7f0b45f'}, 'strawberry-graphql': {'version': '0.327.7', 'filename': 'strawberry_graphql-0.327.7-py3-none-any.whl', 'sha256': '0c653f16fe2a35b5a672fb5492cee5243a2f44f209247a946eddc1a6399b2284'}}


GRAPHQL_PYPI_METADATA = {'cross-web': 'dda3edd3c15abf8c33207d95204c2fb3bfbc1ad74bc77bfcf1d4a56105311991', 'graphql-core': 'ebf4736e597bb6bbbfdd81769d6af662254b7bceb42a7775ee9e5a74d378a17c', 'strawberry-graphql': 'd8ff16632ccf55c773287fc067288ae901154c6753519f7f241336e89b26ce91'}


def profile_pins(profile):
    """Keep acquisition stdlib-only with exactly two fixed profiles."""
    assert profile in (None, 'graphql-test-v1'), 'Unknown provision profile'
    return PINS if profile is None else GRAPHQL_PINS


def assert_destinations_absent(paths):
    """Reject existing destinations and every symlink/non-directory ancestor."""
    for path in paths:
        assert path.startswith('/') and all(p not in ('', '.', '..') for p in path[1:].split('/'))
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parts = path[1:].split('/')
            for part in parts[:-1]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
            try:
                os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise AssertionError('GraphQL destination overwrite denied: ' + path)
        finally:
            os.close(fd)
    return sorted(paths)


def physical_file(path, allowed_roots):
    """Read one bounded physical file through no-follow descriptors and record each link."""
    import stat
    import posixpath
    original, links = path, []
    while True:
        assert path == posixpath.normpath(path) and any(path.startswith(r+'/') for r in allowed_roots), 'Physical origin root'
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        restart = False
        try:
            parts = path[1:].split('/')
            for index, part in enumerate(parts):
                info = os.stat(part, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    target = os.readlink(part, dir_fd=fd)
                    prefix = '/'+'/'.join(parts[:index+1])
                    links.append({'path':prefix,'target':target})
                    assert len(links) <= 16, 'Physical symlink budget'
                    path = posixpath.normpath(posixpath.join(posixpath.dirname(prefix), target, *parts[index+1:]))
                    restart = True
                    break
                if index < len(parts)-1:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = nxt
                else:
                    f = os.open(part, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                    with os.fdopen(f, 'rb') as stream:
                        opened = os.fstat(stream.fileno())
                        assert (opened.st_dev,opened.st_ino) == (info.st_dev,info.st_ino)
                        assert stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1 and opened.st_size <= 33554432
                        data = stream.read(33554433)
                        assert len(data) == opened.st_size
                        return data, dict(path=original, physical=path, links=links, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        finally:
            os.close(fd)
        assert restart


def graphql_build_context(recipe, files):
    """Create one COPY layer with a distinct recipe, never replace the parent recipe."""
    import tarfile
    from check_proof import GRAPHQL_LABEL, GRAPHQL_RECIPE
    recipe_bytes = canonical(recipe)
    dockerfile = (f"FROM {recipe['base_image']}\nUSER 1000:1000\n"
                  f'LABEL {GRAPHQL_LABEL}="{sha(recipe_bytes)}"\n'
                  'COPY --chown=0:0 payload/ /\n').encode()
    context = {'Dockerfile':dockerfile, 'payload'+GRAPHQL_RECIPE:recipe_bytes,
               **{'payload'+recipe['purelib']+'/'+n:b for n,b in files.items()}}
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for name, data in sorted(context.items()):
            member = tarfile.TarInfo(name)
            member.mode, member.size = 0o644, len(data)
            tar.addfile(member, io.BytesIO(data))
    return dockerfile, out.getvalue()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def acquire(destination, *, profile=None):
    """Fetch exact official PyPI metadata/wheels, without importing acquired code."""
    import urllib.parse
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise AssertionError("Package acquisition redirects denied")

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def fetch(url, host, budget):
        parts = urllib.parse.urlsplit(url)
        assert parts.scheme == "https" and parts.netloc == host and not parts.query and not parts.fragment
        if profile == 'graphql-test-v1':
            import signal
            def deadline(signum, frame):
                raise TimeoutError('Public acquisition wall deadline')
            previous = signal.signal(signal.SIGALRM, deadline)
            signal.alarm(40)
        try:
            with opener.open(url, timeout=30) as response:
                assert response.status == 200 and response.url == url
                data = response.read(budget + 1)
                assert len(data) <= budget, "Public acquisition byte budget exceeded"
                return data
        finally:
            if profile == 'graphql-test-v1':
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous)

    pins = profile_pins(profile)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    records = {}
    for name, pin in pins.items():
        metadata_url = f"https://pypi.org/pypi/{name}/{pin['version']}/json"
        raw = fetch(metadata_url, "pypi.org", 2 * 1024 * 1024)
        if profile == 'graphql-test-v1':
            assert sha(raw) == GRAPHQL_PYPI_METADATA[name], 'Reviewed official metadata changed'
        metadata = json.loads(raw)
        assert metadata["info"]["name"] == name and metadata["info"]["version"] == pin["version"]
        wheels = [row for row in metadata["urls"] if row["filename"] == pin["filename"]]
        assert len(wheels) == 1
        wheel = wheels[0]
        assert wheel["packagetype"] == "bdist_wheel" and wheel["yanked"] is False
        assert wheel["digests"]["sha256"] == pin["sha256"]
        data = fetch(wheel["url"], "files.pythonhosted.org", 2 * 1024 * 1024)
        assert len(data) == wheel["size"] and sha(data) == pin["sha256"], "Official PyPI wheel hash mismatch"
        for filename, content in ((name + "-pypi.json", raw), (pin["filename"], data)):
            with (destination / filename).open("xb") as stream:
                stream.write(content)
        records[name] = {"metadata_url": metadata_url, "metadata_sha256": sha(raw),
                         "wheel_url": wheel["url"], "size": len(data), **pin}
    result = {"schema_version": 1, "status": "passed", "scope": "public acquisition only; no imports/install/test", "packages": records}
    if profile is not None:
        result["profile"] = profile
    (destination / "acquisition.json").write_bytes(canonical(result))
    print(json.dumps({"acquisition": str(destination), "status": "passed"}), flush=True)


def validate_graphql_acquisition(acquisition):
    """Revalidate retained official metadata, exact pins, RECORD and reviewed file map."""
    import urllib.parse
    from check_proof import parse, GRAPHQL_FILES_SHA256
    from confined_io import read_confined
    from run import graphql_wheel_entries
    raw = read_confined(acquisition, 'acquisition.json')
    acquired = parse(raw)
    assert type(acquired['schema_version']) is int and acquired['schema_version'] == 1
    assert acquired['status'] == 'passed' and set(acquired['packages']) == set(GRAPHQL_PINS), 'Exact GraphQL packages required'
    files = {}
    for name, pin in GRAPHQL_PINS.items():
        record = acquired['packages'][name]
        assert all(record[k] == v for k,v in pin.items()), 'Acquisition pin mismatch'
        meta_raw = read_confined(acquisition, name+'-pypi.json')
        assert sha(meta_raw) == record['metadata_sha256'] == GRAPHQL_PYPI_METADATA[name], 'Reviewed official metadata hash'
        meta = parse(meta_raw)
        assert record['metadata_url'] == f"https://pypi.org/pypi/{name}/{pin['version']}/json"
        assert meta['info']['name'] == name and meta['info']['version'] == pin['version']
        rows = [r for r in meta['urls'] if r['filename'] == pin['filename']]
        assert len(rows) == 1
        wheel = rows[0]
        assert wheel['packagetype'] == 'bdist_wheel' and wheel['yanked'] is False
        assert wheel['digests']['sha256'] == pin['sha256']
        url = urllib.parse.urlsplit(wheel['url'])
        assert url.scheme == 'https' and url.netloc == 'files.pythonhosted.org' and not url.query and not url.fragment
        assert url.path.startswith('/packages/') and url.path.endswith('/'+pin['filename'])
        assert record['wheel_url'] == wheel['url']
        payload = read_confined(acquisition, pin['filename'])
        assert type(record['size']) is int and type(wheel['size']) is int
        assert len(payload) == record['size'] == wheel['size'] and sha(payload) == pin['sha256'], 'Official wheel bytes'
        members = graphql_wheel_entries(payload, name, pin['version'])
        assert not files.keys() & members.keys()
        files.update(members)
    assert sha(canonical({n:sha(b) for n,b in files.items()})) == GRAPHQL_FILES_SHA256
    assert read_confined(acquisition, 'acquisition.json') == raw, 'Acquisition manifest changed'
    return raw, files


def build(acquisition):
    """Build a COPY-only test image and rehash its installed files under kernel denial."""
    import email.parser
    import signal
    import subprocess
    import tarfile
    import ast
    import re
    import uuid

    root = Path(__file__).absolute().parents[1]
    here = root / "web/arena-workbench/tests/e2e/functional-v7"
    sys.path.insert(0, str(here))
    import run
    from check_proof import PROVISION_LABEL, PROVISION_PINS, parse, selected_runtime
    from confined_io import read_confined
    assert PINS == PROVISION_PINS
    declaration = read_confined(root, "pyproject.toml")
    # Narrow fail-closed literal list, compatible with stdlib-only Python 3.10 hosts.
    projects = re.findall(r"(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)", declaration.decode())
    assert len(projects) == 1, "Unique project declaration required"
    dependency_lists = re.findall(r"(?ms)^dependencies = (\[\n.*?^\])", projects[0])
    assert len(dependency_lists) == 1 and "neo4j" in ast.literal_eval(dependency_lists[0]), "Only exact project-declared neo4j is authorized"
    acquisition_raw = read_confined(acquisition, "acquisition.json")
    acquired = parse(acquisition_raw)
    assert acquired["schema_version"] == 1 and acquired["status"] == "passed" and set(acquired["packages"]) == set(PINS)
    files = {}
    for name, pin in PINS.items():
        record = acquired["packages"][name]
        raw = read_confined(acquisition, name + "-pypi.json")
        assert sha(raw) == record["metadata_sha256"]
        metadata = parse(raw)
        assert record["metadata_url"] == f"https://pypi.org/pypi/{name}/{pin['version']}/json"
        assert all(record[key] == value for key, value in pin.items())
        assert metadata["info"]["name"] == name and metadata["info"]["version"] == pin["version"]
        wheel = [row for row in metadata["urls"] if row["filename"] == pin["filename"]]
        assert len(wheel) == 1 and wheel[0]["packagetype"] == "bdist_wheel" and wheel[0]["yanked"] is False
        assert wheel[0]["digests"]["sha256"] == pin["sha256"]
        assert record["wheel_url"] == wheel[0]["url"] and record["wheel_url"].startswith("https://files.pythonhosted.org/packages/")
        payload = read_confined(acquisition, pin["filename"])
        assert sha(payload) == pin["sha256"] and len(payload) == record["size"] == wheel[0]["size"]
        members = run.wheel_entries(payload, name, pin["version"])
        headers = email.parser.BytesParser().parsebytes(members[name + "-" + pin["version"] + ".dist-info/METADATA"])
        assert headers["Name"] == name and headers["Version"] == pin["version"]
        requirements = headers.get_all("Requires-Dist", [])
        assert requirements == (metadata["info"]["requires_dist"] or [])
        mandatory = [value for value in requirements if ";" not in value]
        assert mandatory == (["pytz"] if name == "neo4j" else [])
        assert headers["Requires-Python"] == (">=3.10" if name == "neo4j" else None)
        assert not set(files) & set(members)
        files.update(members)

    discovered = run.discover(root, False)
    base = discovered["runtime_image"]
    token = "arena-f0-provision-" + uuid.uuid4().hex[:12]
    output = here / ".runs" / token
    output.mkdir(mode=0o755)
    owned = run.OwnedRun(output, token)
    owned.proof["scope"] = "provision probes only; not API acceptance"
    print(json.dumps({"output": str(output)}), flush=True)
    previous = {}
    def interrupt(signum, frame):
        raise InterruptedError(f"signal {signum}")
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, interrupt)
    success = False
    provision = None
    try:
        preflight = run.DEPENDENCY_PROBE.split("roots=", 1)[0]
        def probe(role, image, code):
            cid = owned.create(role, image, "/usr/bin/env", ["-i", "HOME=/tmp", "PATH=/usr/bin:/bin",
                               "PYTHONDONTWRITEBYTECODE=1", "/isaac-sim/python.sh", "-I", "-S", "-c", code], [])
            run.verify_container(owned, cid, [])
            data = run.docker("start", "-a", cid)
            assert run.docker("wait", cid) == "0", "Provision probe failed"
            result = parse(data)
            (output / (role + ".json")).write_bytes(canonical(result))
            return result
        observed = probe("base-probe", base, preflight + "\nimport sys\nprint(json.dumps({'purelib':sysconfig.get_path('purelib'),'python_version':list(sys.version_info[:3]),'uid':os.getuid(),'errno':denial,'egress_denied':True}))")
        purelib = observed["purelib"]
        assert observed["python_version"][:2] == [3, 12]
        assert purelib.startswith("/isaac-sim/") and purelib.endswith("/site-packages")
        assert all(part not in (".", "..", "") for part in purelib[1:].split("/"))
        recipe = {"schema_version": 1, "scope": "test-only declared neo4j plus pytz", "base_image": base,
                  "purelib": purelib, "python_version": observed["python_version"], "pins": PINS,
                  "build_policy": "COPY-only; network=none; no RUN; no package execution",
                  "declaration_sha256": sha(declaration), "acquisition_sha256": sha(acquisition_raw),
                  "files": {name: sha(data) for name, data in files.items()}}
        recipe_bytes = canonical(recipe)
        recipe_hash = sha(recipe_bytes)
        # A single COPY makes the added rootfs diff independently recognizable.
        dockerfile = (f"FROM {base}\nUSER 1000:1000\nLABEL {PROVISION_LABEL}=\"{recipe_hash}\"\n"
                      "COPY --chown=0:0 payload/ /\n").encode()
        context = {"Dockerfile": dockerfile, "payload/opt/arena-f0/provision-recipe.json": recipe_bytes,
                   **{"payload" + purelib + "/" + name: data for name, data in files.items()}}
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w", format=tarfile.USTAR_FORMAT) as tar:
            for name, data in sorted(context.items()):
                info = tarfile.TarInfo(name)
                info.mode = 0o644
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        (output / "Dockerfile.test-only").write_bytes(dockerfile)
        (output / "recipe.json").write_bytes(recipe_bytes)
        (output / "build-context.tar").write_bytes(archive.getvalue())
        command = ["docker", "build", "--network=none", "--pull=false", "--no-cache", "--iidfile", str(output / "image.id"), "-"]
        built = subprocess.run(command, input=archive.getvalue(), capture_output=True, timeout=300,
                               env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "DOCKER_BUILDKIT": "0"})
        (output / "build.log").write_bytes(built.stdout + built.stderr)
        assert built.returncode == 0, "COPY-only Docker build failed; see build.log"
        image = read_confined(output, "image.id").decode().strip()
        run.image_metadata(image)
        readback_code = preflight + r'''
import hashlib
fd=os.open('/opt/arena-f0/provision-recipe.json',os.O_RDONLY|os.O_NOFOLLOW)
with os.fdopen(fd,'rb') as stream: raw=stream.read(1048577)
assert len(raw)<=1048576
recipe=json.loads(raw)
assert hashlib.sha256(raw).hexdigest()==EXPECTED
count=0
for name,expected in recipe['files'].items():
 path=recipe['purelib']+'/'+name
 fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:
  parts=path.strip('/').split('/')
  for part in parts[:-1]:
   nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
  f=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
  info=os.fstat(f)
  assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=2097152
  assert info.st_uid==0 and not info.st_mode & 0o022
  with os.fdopen(f,'rb') as stream: data=stream.read(2097153)
  assert len(data)==info.st_size and hashlib.sha256(data).hexdigest()==expected
  count+=1
 finally: os.close(fd)
print(json.dumps({'schema_version':1,'status':'passed','recipe_sha256':EXPECTED,'files_verified':count,
 'uid':os.getuid(),'errno':denial,'egress_denied':True,'before_package_imports':True}))
'''.replace("EXPECTED", repr(recipe_hash))
        readback = probe("image-readback", image, readback_code)
        provision = {"schema_version": 1, "status": "passed", "image": image, "recipe": recipe,
                     "recipe_sha256": recipe_hash, "base_projection": run.provision_image_metadata(base),
                     "image_projection": run.provision_image_metadata(image), "readback": readback}
        success = True
    finally:
        for signum in previous:
            signal.signal(signum, signal.SIG_IGN)
        clean = owned.cleanup()
        owned.proof.update(status="passed" if success and clean else "failed", cleanup_verified=clean)
        owned.save()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        assert clean, "Provision probe cleanup not verified"
    assert success and provision
    provision["cleanup_verified"] = True
    selected_runtime(dict(discovered, selected_runtime_image=provision["image"], provision=provision))
    (output / "provision-manifest.json").write_bytes(canonical(provision))
    # Actual external image/config readback is mandatory, not just a build ACK.
    run.select_runtime(discovered, provision["image"], output / "provision-manifest.json")
    print(json.dumps({"status": "passed", "image": provision["image"], "manifest": str(output / "provision-manifest.json"),
                      "remaining_owned": owned.proof["remaining_owned"]}), flush=True)


def graphql_import_code(purelib, closure, image, recipe_hash):
    """Generate the exact mount-free, preimport-denied real framework compatibility probe."""
    import inspect
    import run
    from check_proof import (GRAPHQL_IMPORT_BINDINGS, GRAPHQL_ARCHIVE, GRAPHQL_URDF,
                             GRAPHQL_CIP, GRAPHQL_LANGCHAIN, GRAPHQL_INCIDENTAL, graphql_sys_path)
    paths = graphql_sys_path(purelib)
    allowed = [purelib, GRAPHQL_ARCHIVE, GRAPHQL_URDF, GRAPHQL_CIP, GRAPHQL_LANGCHAIN]
    return (run.DEPENDENCY_PROBE.split('roots=',1)[0] + '\nimport hashlib, sys, signal\n' +
            inspect.getsource(physical_file) +
            f'\nPATHS={paths!r}\nALLOWED={allowed!r}\nBINDINGS={GRAPHQL_IMPORT_BINDINGS!r}\nCLOSURE={closure!r}\n' +
            f'IMAGE={image!r}\nRECIPE_HASH={recipe_hash!r}\nINCIDENTAL={GRAPHQL_INCIDENTAL!r}\n' + r'''
signal.alarm(35)
assert sys.flags.isolated == 1 and sys.flags.no_site == 1 and sys.flags.ignore_environment == 1
assert sys.path == PATHS[:3] and sysconfig.get_path('purelib') == PATHS[3]
sys.path[:] = PATHS
sys.dont_write_bytecode = True
forbidden={'network':0,'subprocess':0,'blocked_import':0}
def audit(event,args):
 category=None
 if event in ('socket.connect','socket.bind','socket.getaddrinfo','socket.gethostbyname'): category='network'
 if event in ('subprocess.Popen','os.system','os.fork','os.forkpty','os.posix_spawn','os.exec','os.spawn','pty.spawn'): category='subprocess'
 if event=='import' and args[0].split('.')[0] in {'isaaclab_arena','isaaclab_arena_examples','omni','carb','pxr','openai','anthropic','boto3','torch','sqlite3'}: category='blocked_import'
 if category:
  forbidden[category]+=1
  raise AssertionError('GraphQL import probe denies '+category)
sys.addaudithook(audit)
result={'schema_version':1,'status':'failed','scope':'real framework import compatibility; NOT ASGI/API/cohort acceptance',
 'image':IMAGE,'recipe_sha256':RECIPE_HASH,'interpreter':'/isaac-sim/python.sh','executable':sys.executable,
 'python_version':list(sys.version_info[:3]),'sys_path':list(sys.path),'uid':os.getuid(),'errno':denial,
 'egress_denied':True,'before_package_imports':True,'forbidden':forbidden,'distributions':{},'modules':{},'loaded_modules':{}}
def check_imports():
 import importlib, importlib.metadata, email.parser
 import packaging
 from packaging.requirements import Requirement
 from packaging.specifiers import SpecifierSet
 from packaging.markers import default_environment
 from packaging.utils import canonicalize_name
 assert packaging.__version__ == '23.2'
 env=default_environment()
 assert env['python_full_version']=='3.12.13'
 packages=CLOSURE['packages']
 requested=[r[0] for r in BINDINGS.values()]+['strawberry.fastapi','pydantic_core._pydantic_core']
 for name in requested:
  module=importlib.import_module(name)
  assert module.__spec__.origin == module.__file__
  _,witness=physical_file(module.__file__,ALLOWED)
  result['modules'][name]=dict(witness,origin=module.__spec__.origin,file=module.__file__)
 for name,binding in BINDINGS.items():
  module,origin,physical,file_hash,version,meta_path,meta_hash=binding
  selected=importlib.metadata.distribution(name)
  raw,witness=physical_file(str(selected._path)+'/METADATA',ALLOWED)
  headers=email.parser.BytesParser().parsebytes(raw)
  assert canonicalize_name(headers['Name'])==name and headers['Version']==version, ('metadata version',name)
  assert witness['physical']==meta_path and witness['sha256']==meta_hash, ('metadata origin',name,witness)
  requires=headers.get_all('Requires-Dist',[])
  row=packages[name]
  assert {Requirement(r) for r in requires} == {Requirement(r) for r in row['requires_dist']}
  assert {Requirement(r) for r in requires} == {Requirement(r) for r in row['pypi_requires_dist']}
  assert SpecifierSet(headers['Requires-Python'] or '') == SpecifierSet(row['pypi_requires_python'] or '')
  assert SpecifierSet(headers['Requires-Python'] or '').contains(env['python_full_version'])
  result['distributions'][name]=dict(version=headers['Version'],requires_dist=requires,
                                     requires_python=headers['Requires-Python'],metadata=witness)
 result['incidental_distributions']={}
 for name,expected in INCIDENTAL.items():
  selected=importlib.metadata.distribution(name)
  raw,witness=physical_file(str(selected._path)+'/METADATA',ALLOWED)
  headers=email.parser.BytesParser().parsebytes(raw)
  assert witness['path']==witness['physical']==expected['path'] and witness['sha256']==expected['sha256']
  assert headers['Version']==expected['version']
  assert SpecifierSet(headers['Requires-Python'] or '').contains(env['python_full_version'])
  result['incidental_distributions'][name]=dict(version=headers['Version'],requires_python=headers['Requires-Python'],
                                               requires_dist=headers.get_all('Requires-Dist',[]),metadata=witness)
 extras={};queue=[];processed={};edges=[]
 for text in CLOSURE['roots']:
  requirement=Requirement(text);name=canonicalize_name(requirement.name)
  assert requirement.specifier.contains(packages[name]['version'])
  extras.setdefault(name,set()).update(requirement.extras);queue.append(name)
 while queue:
  name=queue.pop(0);active=frozenset(extras.get(name,set()))
  if processed.get(name)==active:continue
  processed[name]=active
  for text in result['distributions'][name]['requires_dist']:
   req=Requirement(text);contexts=active or {''}
   enabled=any(req.marker is None or req.marker.evaluate(dict(env,extra=extra)) for extra in contexts)
   target=canonicalize_name(req.name)
   edges.append(dict(source=name,requirement=text,target=target,enabled=enabled))
   if not enabled:continue
   assert req.url is None and target in packages and req.specifier.contains(packages[target]['version']), (name,text)
   previous=set(extras.get(target,set()));extras.setdefault(target,set()).update(req.extras)
   if target not in processed or extras[target]!=previous:queue.append(target)
 assert set(processed)==set(packages)
 for name,module in sorted(list(sys.modules.items())):
  spec=getattr(module,'__spec__',None);origin=getattr(spec,'origin',None)
  if not origin or origin in ('built-in','frozen') or not any(origin.startswith(r+'/') for r in ALLOWED):continue
  assert getattr(module,'__file__',None)==origin
  _,witness=physical_file(origin,ALLOWED)
  result['loaded_modules'][name]=dict(witness,origin=origin,file=origin)
  assert len(result['loaded_modules'])<=1024
 result.update(status='passed',constraints_passed=True,constraint_edges=edges,
               marker_environment=env,packaging_version=packaging.__version__)
try:
 check_imports()
except BaseException as error:
 result.update(status='failed',error=type(error).__name__+': '+str(error))
 print(json.dumps(result))
 raise
print(json.dumps(result))
''')


def build_graphql(acquisition, parent_manifest):
    """Build the fixed COPY-only child and prove its parent and no-overwrite contract."""
    import inspect
    import signal
    import subprocess
    import uuid
    root = Path(__file__).absolute().parents[1]
    here = root / 'web/arena-workbench/tests/e2e/functional-v7'
    sys.path.insert(0, str(here))
    import run
    from check_proof import GRAPHQL_PARENT, GRAPHQL_RECIPE, GRAPHQL_ROOTS, GRAPHQL_CLOSURE_SHA256, parse, graphql_import_contract
    from confined_io import read_confined
    raw, files = validate_graphql_acquisition(acquisition)
    closure_raw = read_confined(root, 'outputs/workflow/plan03-implementation/graphql-provisioning/discovery/closure-input.json')
    assert sha(closure_raw) == GRAPHQL_CLOSURE_SHA256, 'Reviewed metadata closure changed'
    closure = parse(closure_raw)
    parent_raw = read_confined(parent_manifest.parent, parent_manifest.name)
    parent = parse(parent_raw)
    discovered = run.discover(root, False)
    run.select_runtime(discovered, GRAPHQL_PARENT, parent_manifest)
    token = 'arena-f0-graphql-provision-' + uuid.uuid4().hex[:12]
    output = root / 'outputs/workflow/plan03-implementation/graphql-provisioning/implementation' / token
    output.mkdir(parents=True, mode=0o700)
    owned = run.OwnedRun(output, token)
    owned.proof['scope'] = 'GraphQL test-image admission and actual framework import compatibility; NOT ASGI/API acceptance'
    owned.proof['source_sha256'] = {str(p.relative_to(root)):sha(p.read_bytes()) for p in
                                  (Path(__file__).absolute(), here/'run.py', here/'check_proof.py')}
    print(json.dumps({'output':str(output)}), flush=True)
    success = False
    previous = {}
    def interrupted(signum, frame):
        raise InterruptedError(f'signal {signum}')
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, interrupted)
    preflight = run.DEPENDENCY_PROBE.split('roots=', 1)[0]
    common = preflight + r'''
import hashlib, sys, signal
signal.alarm(35)
def read_file(path):
 fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:
  parts=path.strip('/').split('/')
  assert all(p not in ('','.','..') for p in parts)
  for part in parts[:-1]:
   nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
  f=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
  with os.fdopen(f,'rb') as stream:
   s=os.fstat(stream.fileno())
   assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=2097152
   assert s.st_uid==0 and not s.st_mode & 0o022
   data=stream.read(2097153);assert len(data)==s.st_size
   return data
 finally:os.close(fd)
parent_hash=hashlib.sha256(read_file('/opt/arena-f0/provision-recipe.json')).hexdigest()
assert parent_hash==PARENT_HASH
result={'schema_version':1,'status':'passed','uid':os.getuid(),'errno':denial,'egress_denied':True,
        'before_package_imports':True,'parent_recipe_sha256':parent_hash}
'''.replace('PARENT_HASH', repr(parent['recipe_sha256']))
    def probe(role, image, code):
        (output/(role+'.py')).write_text(code)
        cid = owned.create(role, image, '/usr/bin/env', ['-i','HOME=/tmp','PATH=/usr/bin:/bin',
                           'PYTHONDONTWRITEBYTECODE=1','/isaac-sim/python.sh','-I','-S','-c',code], [])
        run.verify_container(owned, cid, [])
        try:
            text = run.docker('start','-a',cid)
            (output/(role+'.stdout')).write_text(text)
            assert run.docker('wait',cid) == '0', 'GraphQL probe failed: '+role
            assert len(text.encode()) <= 2*1024*1024
            result = parse(text)
            (output/(role+'.json')).write_bytes(canonical(result))
            return result
        finally:
            (output/(role+'.log')).write_text(run.docker('logs', cid))
    try:
        code = common + inspect.getsource(assert_destinations_absent) + '\n' + (
            "purelib=sysconfig.get_path('purelib')\n"
            "assert purelib.startswith('/isaac-sim/') and purelib.endswith('/site-packages')\n"
            "result.update(purelib=purelib,python_version=list(sys.version_info[:3]),sys_path=list(sys.path))\n"
            f"result['absent']=assert_destinations_absent([purelib+'/'+r for r in {sorted(GRAPHQL_ROOTS)!r}]+[{GRAPHQL_RECIPE!r}])\n"
            "print(json.dumps(result))\n")
        observed = probe('no-overwrite', GRAPHQL_PARENT, code)
        assert observed['purelib'] == parent['recipe']['purelib'] and observed['python_version'] == [3,12,13]
        recipe = dict(schema_version=1, profile='graphql-test-v1', base_image=GRAPHQL_PARENT,
                      recipe_path=GRAPHQL_RECIPE, purelib=observed['purelib'], python_version=observed['python_version'],
                      pins=GRAPHQL_PINS, parent_manifest_sha256=sha(parent_raw), parent_recipe_sha256=parent['recipe_sha256'],
                      acquisition_sha256=sha(raw), files={n:sha(b) for n,b in files.items()},
                      closure_sha256=sha(closure_raw), path_binding='isolated-sysconfig-kit-archive-urdf-v1',
                      build_policy='COPY-only; network=none; no RUN; no package execution')
        recipe_bytes = canonical(recipe)
        recipe_hash = sha(recipe_bytes)
        dockerfile, archive = graphql_build_context(recipe, files)
        (output/'Dockerfile.test-only').write_bytes(dockerfile)
        (output/'recipe.json').write_bytes(recipe_bytes)
        (output/'build-context.tar').write_bytes(archive)
        tag = 'arena-f0-graphql-test:' + token.removeprefix('arena-f0-graphql-provision-')
        command = ['docker','build','--network=none','--pull=false','--no-cache','--tag',tag,'--iidfile',str(output/'image.id'),'-']
        (output/'build-command.json').write_bytes(canonical(command))
        built = subprocess.run(command, input=archive, capture_output=True, timeout=300,
                               env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','DOCKER_BUILDKIT':'0'})
        (output/'build.log').write_bytes(built.stdout+built.stderr)
        assert built.returncode == 0, 'GraphQL COPY build failed'
        image = read_confined(output,'image.id').decode().strip()
        assert run.image_metadata(tag)['Id'] == image
        readback = probe('image-readback', image, common +
            f"\nraw=read_file({GRAPHQL_RECIPE!r})\nassert hashlib.sha256(raw).hexdigest()=={recipe_hash!r}\n" +
            "recipe=json.loads(raw)\nfor name, expected in recipe['files'].items():\n" +
            " assert hashlib.sha256(read_file(recipe['purelib']+'/'+name)).hexdigest()==expected\n" +
            f"result.update(recipe_sha256={recipe_hash!r},files_verified=len(recipe['files']))\nprint(json.dumps(result))\n")
        provision = dict(schema_version=1, status='passed', profile='graphql-test-v1', image=image,
                         recipe=recipe, recipe_sha256=recipe_hash, parent_manifest=parent_raw.decode(),
                         base_projection=run.provision_image_metadata(GRAPHQL_PARENT),
                         parent_config_projection=run.provision_image_metadata(GRAPHQL_PARENT, profile='graphql-test-v1'),
                         image_projection=run.provision_image_metadata(image, profile='graphql-test-v1'),
                         no_overwrite=observed, readback=readback)
        provision['imports'] = probe('real-imports', image, graphql_import_code(recipe['purelib'], closure, image, recipe_hash))
        graphql_import_contract(provision)
        success = True
    finally:
        for signum in previous:
            signal.signal(signum, signal.SIG_IGN)
        try:
            clean = owned.cleanup()
            owned.proof.update(status='passed' if success and clean else 'failed', cleanup_verified=clean)
            owned.save()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        assert clean, 'GraphQL probe cleanup not verified'
    provision['cleanup_verified'] = True
    manifest = output/'provision-manifest.json'
    manifest.write_bytes(canonical(provision))
    run.select_runtime(discovered, image, manifest, profile='graphql-test-v1')
    print(json.dumps({'status':'passed','image':image,'manifest':str(manifest),
                      'scope':owned.proof['scope'],'remaining_owned':owned.proof['remaining_owned']}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("acquire", "build"))
    parser.add_argument("directory", type=Path, help="Fresh acquisition destination, or existing acquisition source for build")
    parser.add_argument('--profile', choices=('graphql-test-v1',), default=None)
    parser.add_argument('--parent-manifest', type=Path)
    options = parser.parse_args()
    if options.profile == 'graphql-test-v1':
        if options.mode == 'acquire':
            assert options.parent_manifest is None
            acquire(options.directory.absolute(), profile=options.profile)
        else:
            assert options.parent_manifest is not None, 'GraphQL parent manifest required'
            build_graphql(options.directory.absolute(), options.parent_manifest.absolute())
    else:
        assert options.parent_manifest is None, 'Parent manifest is GraphQL-only'
        if options.mode == "acquire":
            acquire(options.directory.absolute())
        else:
            build(options.directory.absolute())


if __name__ == "__main__":
    main()
