#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Acquire two pinned public wheels, then COPY inert verified bytes offline into a test image.

Acquisition never imports repository/application code. Build has no RUN instruction,
no pip/setup execution and no network-enabled package execution. This is not a
project installer: only declared neo4j and its mandatory pytz requirement qualify.
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


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def acquire(destination):
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
        with opener.open(url, timeout=30) as response:
            assert response.status == 200 and response.url == url
            data = response.read(budget + 1)
            assert len(data) <= budget, "Public acquisition byte budget exceeded"
            return data

    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    records = {}
    for name, pin in PINS.items():
        metadata_url = f"https://pypi.org/pypi/{name}/{pin['version']}/json"
        raw = fetch(metadata_url, "pypi.org", 2 * 1024 * 1024)
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
    (destination / "acquisition.json").write_bytes(canonical(result))
    print(json.dumps({"acquisition": str(destination), "status": "passed"}), flush=True)


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("acquire", "build"))
    parser.add_argument("directory", type=Path, help="Fresh acquisition destination, or existing acquisition source for build")
    options = parser.parse_args()
    if options.mode == "acquire":
        acquire(options.directory.absolute())
    else:
        build(options.directory.absolute())


if __name__ == "__main__":
    main()
