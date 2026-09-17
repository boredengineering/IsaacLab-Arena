# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Import-safe F0 isolated acceptance; stdlib host orchestration only."""
import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
import traceback
import uuid
from pathlib import Path

LABEL = "arena.functional-v7"


def projection(fields):
    """Build explicit Docker Go-template JSON, never serialize parent metadata."""
    return "{" + ",".join(json.dumps(key) + ":{{json " + value + "}}" for key, value in fields.items()) + "}"


IDENTITY_FORMAT = projection({"Id": ".Id", "Name": ".Name", "Label": '(index .Config.Labels "' + LABEL + '")'})
IMAGE_FORMAT = projection({"Id": ".Id", "Volumes": '(index .Config "Volumes")'})
HOST_FIELDS = (
    "NetworkMode",
    "ReadonlyRootfs",
    "CapDrop",
    "CapAdd",
    "SecurityOpt",
    "DeviceRequests",
    "Devices",
    "Privileged",
    "PidMode",
    "IpcMode",
    "UsernsMode",
    "Binds",
    "VolumesFrom",
    "Tmpfs",
    "PidsLimit",
    "Memory",
    "PortBindings",
)
MOUNT_FORMAT = projection({key: '(index $m "' + key + '")' for key in ("Type", "Source", "Destination", "Name", "RW")})
OWN_FORMAT = (
    '{"Id":{{json .Id}},"Name":{{json .Name}},"Image":{{json .Image}},'
    '"Config":{"User":{{json .Config.User}},"Labels":{"'
    + LABEL
    + '":{{json (index .Config.Labels "'
    + LABEL
    + '")}}}},"HostConfig":'
    + projection({key: '(index .HostConfig "' + key + '")' for key in HOST_FIELDS})
    + ',"Mounts":[{{range $i,$m := .Mounts}}{{if $i}},{{end}}'
    + MOUNT_FORMAT
    + "{{end}}]}"
)


def running_metadata(root, command=None):
    """Project only clone/frontend mount destinations at the CLI boundary."""
    command = command or docker
    ids = command("ps", "-q", "--no-trunc").splitlines()
    if not ids:
        return []
    import re

    assert all(re.fullmatch(r"[0-9a-f]{64}", cid) for cid in ids), "Invalid Docker identity"
    destinations = (str(root), "/workspaces/isaaclab_arena", "/app", "/app/node_modules")
    condition = "or " + " ".join("(eq $m.Destination " + json.dumps(path) + ")" for path in destinations)
    template = (
        '{"Id":{{json .Id}},"Image":{{json .Image}},"Mounts":[{{ $first := true }}{{range $m := .Mounts}}{{if '
        + condition
        + "}}{{if not $first}},{{end}}{{$first = false}}"
        + MOUNT_FORMAT
        + "{{end}}{{end}}]}"
    )
    records = [json.loads(line) for line in command("inspect", "--format", template, *ids).splitlines()]
    assert {r["Id"] for r in records} == set(ids) and len(records) == len(ids)
    return records


def image_metadata(image, command=None):
    command = command or docker
    info = json.loads(command("image", "inspect", "--format", IMAGE_FORMAT, image))
    import re

    assert re.fullmatch(r"sha256:[0-9a-f]{64}", info["Id"]), "Image identity is not immutable"
    assert not info["Volumes"], "Image declares implicit volumes"
    if image.startswith("sha256:"):
        assert info["Id"] == image, "Image identity mismatch"
    return info


def provision_image_metadata(image):
    from check_proof import PROVISION_LABEL

    template = projection({
        "Id": ".Id",
        "Volumes": '(index .Config "Volumes")',
        "Layers": ".RootFS.Layers",
        "Recipe": '(index .Config.Labels "' + PROVISION_LABEL + '")',
    })
    return json.loads(docker("image", "inspect", "--format", template, image))


def select_runtime(discovered, image=None, manifest=None):
    """Select a provisioned test image without relabelling live discovery."""
    import re

    from check_proof import parse, selected_runtime

    if image is None and manifest is None:
        return discovered
    assert (
        image and manifest and re.fullmatch(r"sha256:[0-9a-f]{64}", image)
    ), "Image override needs immutable ID and provision manifest"
    from confined_io import read_confined

    path = Path(manifest).absolute()
    value = parse(read_confined(path.parent, path.name))
    selected = dict(discovered, selected_runtime_image=image, provision=value)
    selected_runtime(selected)
    assert provision_image_metadata(image) == value["image_projection"], "Provisioned image readback mismatch"
    assert (
        provision_image_metadata(discovered["runtime_image"]) == value["base_projection"]
    ), "Provision base readback mismatch"
    return selected


def runtime_image(discovered):
    from check_proof import selected_runtime

    return selected_runtime(discovered)


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError(f"docker {args[0]}: {result.stderr[:2000]}")
    return (result.stdout + (result.stderr if args[0] == "logs" else "")).strip()


class OwnedRun:
    """Persist intended names before creation can become ambiguous."""

    def __init__(self, output, token, command=docker):
        self.output = Path(output)
        self.token = token
        self.command = command
        self.candidates = []
        self.proof = {
            "schema_version": 3,
            "status": "starting",
            "run": token,
            "candidates": self.candidates,
            "created_ids": {},
            "verified_isolation": {},
            "containers": [],
            "cleanup": [],
            "metadata_projection": "CLI allowlists; no Env, command, or arbitrary labels",
        }

    def save(self):
        temporary = self.output / "ownership.pending"
        with temporary.open("w") as stream:
            json.dump(self.proof, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.output / "ownership.json")
        descriptor = os.open(self.output, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def create(self, role, image, entrypoint, args, mounts):
        name = f"{self.token}-{role}"
        assert name not in self.candidates, "Duplicate intended container name"
        self.candidates.append(name)
        self.save()
        flags = [
            "create",
            "--pull=never",
            "--name",
            name,
            "--label",
            f"{LABEL}={self.token}",
            "--network=none",
            "--read-only",
            "--no-healthcheck",
            "--user=1000:1000",
            "--group-add=1234",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=256",
            "--memory=4g",
            "--shm-size=256m",
            "--workdir=/tmp",
            "--entrypoint",
            entrypoint,
            "--tmpfs=/tmp:rw,nosuid,nodev,uid=1000,gid=1000,mode=1777,size=1073741824",
            "--tmpfs=/private:rw,nosuid,nodev,uid=1000,gid=1000,mode=0700,size=134217728",
            "--env=NVIDIA_VISIBLE_DEVICES=void",
            "--env=CUDA_VISIBLE_DEVICES=",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            "--env=PYTHONNOUSERSITE=1",
            "--env=HOME=/tmp",
        ]
        for mount in mounts:
            flags.extend(["--mount", mount])
        identity = self.command(*flags, image, *args)
        # The immutable create ACK is ownership, not a successful isolation check.
        # Retain it in memory even if durable evidence writing now fails.
        self.proof["created_ids"][name] = identity
        self.proof["verified_isolation"][name] = False
        self.save()
        import re

        assert re.fullmatch(r"[0-9a-f]{64}", identity), "Malformed Docker create identity"
        return identity

    def cleanup(self):
        errors = []
        # Candidates are independent: a single daemon/ownership failure must not skip others.
        for name in reversed(self.candidates):
            try:
                ids = self.command("ps", "-aq", "--no-trunc", "--filter", f"name=^/{name}$").splitlines()
                for identity in ids:
                    info = json.loads(self.command("inspect", "--format", IDENTITY_FORMAT, identity))
                    assert info["Id"] == identity and info["Name"] == "/" + name
                    assert info["Label"] == self.token, "Ownership mismatch"
                    known = (
                        [self.proof["created_ids"][name]]
                        if name in self.proof["created_ids"]
                        else [record["id"] for record in self.proof["containers"] if record["name"] == "/" + name]
                    )
                    assert not known or known == [identity], "Known container identity was replaced"
                    # Never collect output from an unverified/unstarted replacement.
                    if self.proof["verified_isolation"].get(name):
                        try:
                            (self.output / f"{name}.log").write_text(self.command("logs", "--tail", "1000", identity))
                        except Exception as error:
                            errors.append(f"logs {name}: {error}")
                    self.command("rm", "-f", identity)
                    self.proof["cleanup"].append(
                        {"name": name, "id": identity, "removed": True, "ownership_verified": True}
                    )
            except Exception as error:
                errors.append(f"{name}: {error}")
        self.proof["cleanup_verification"] = {"status": "failed", "authoritative": False}
        try:
            label_ids = self.command("ps", "-aq", "--no-trunc", "--filter", f"label={LABEL}={self.token}").splitlines()
            candidate_ids = {}
            for name in self.candidates:
                candidate_ids[name] = self.command(
                    "ps", "-aq", "--no-trunc", "--filter", f"name=^/{name}$"
                ).splitlines()
            remaining = label_ids + [identity for identities in candidate_ids.values() for identity in identities]
            self.proof["remaining_owned"] = sorted(set(remaining))
            self.proof["cleanup_verification"] = {
                "status": "failed" if remaining else "passed",
                "authoritative": True,
                "label_ids": label_ids,
                "candidate_ids": candidate_ids,
            }
        except Exception as error:
            self.proof["remaining_owned"] = None
            errors.append(f"authoritative listing: {error}")
        self.proof["cleanup_errors"] = errors
        try:
            self.save()
        except Exception as error:
            errors.append(f"ownership evidence: {error}")
        return not errors and self.proof["remaining_owned"] == []


def discover_frontend(root, frontend_dependency_container=None, *, running=None):
    """Select installed mutable dependencies without runtime/browser image discovery."""
    import re

    if frontend_dependency_container is not None:
        assert re.fullmatch(
            r"[0-9a-f]{64}", frontend_dependency_container
        ), "Frontend dependency container requires exact lowercase 64-hex ID"
    running = running_metadata(root) if running is None else running
    host_roots = {
        m["Source"] for c in running for m in c["Mounts"] if m["Type"] == "bind" and m["Destination"] == str(root)
    }
    assert len(host_roots) == 1, "Cannot identify host clone bind"
    host_root = host_roots.pop()
    result = {"host_root": host_root}
    frontends = [
        c
        for c in running
        if any(m["Source"] == host_root + "/web/arena-workbench" and m["Destination"] == "/app" for m in c["Mounts"])
    ]
    if frontend_dependency_container is not None:
        template = (
            '{"Id":{{json .Id}},"Image":{{json .Image}},'
            '"Status":{{json .State.Status}},"Running":{{json .State.Running}},"Mounts":['
            "{{ $first := true }}{{range $m := .Mounts}}"
            '{{if or (eq $m.Destination "/app") (eq $m.Destination "/app/node_modules")}}'
            "{{if not $first}},{{end}}{{$first = false}}"
            + MOUNT_FORMAT
            + "{{end}}{{end}}]}"
        )
        origin = json.loads(docker("inspect", "--format", template, frontend_dependency_container))
        assert origin.get("Id") == frontend_dependency_container, "Frontend dependency identity mismatch"
        assert (
            origin.get("Status") == "exited" and origin.get("Running") is False
        ), "Frontend dependency container must be verified stopped (exited)"
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", origin.get("Image", "")), "Frontend dependency image ID malformed"
        app = [m for m in origin["Mounts"] if m["Destination"] == "/app"]
        assert (
            len(app) == 1 and app[0]["Type"] == "bind" and app[0]["Source"] == host_root + "/web/arena-workbench"
        ), "Frontend dependency clone bind mismatch"
        volumes = [m for m in origin["Mounts"] if m["Destination"] == "/app/node_modules"]
        assert len(volumes) == 1 and volumes[0]["Type"] == "volume", "Missing or ambiguous frontend dependency volume"
        assert isinstance(volumes[0].get("Name"), str) and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*", volumes[0]["Name"]
        ), "Invalid frontend dependency volume name"
        frontends = [origin]
        result["frontend_dependency_origin"] = origin
    assert frontends, "Cannot identify installed frontend dependencies"
    deps = {
        m.get("Name")
        for c in frontends
        for m in c["Mounts"]
        if m["Destination"] == "/app/node_modules" and m["Type"] == "volume"
    }
    assert len(deps) == 1, "Ambiguous installed dependency volumes"
    dependency_volume = deps.pop()
    result.update(
        deps=dependency_volume,
        frontend_dependency_trust="Trusted installed mutable volume; no immutable package provenance",
    )
    return result


def discover(root, browser, frontend_dependency_container=None):
    import re

    if frontend_dependency_container is not None:
        assert re.fullmatch(
            r"[0-9a-f]{64}", frontend_dependency_container
        ), "Frontend dependency container requires exact lowercase 64-hex ID"
        assert browser, "Frontend dependency selection requires browser discovery"
    running = running_metadata(root)
    host_roots = {
        m["Source"] for c in running for m in c["Mounts"] if m["Type"] == "bind" and m["Destination"] == str(root)
    }
    assert len(host_roots) == 1, "Cannot identify host clone bind"
    host_root = host_roots.pop()
    # Policy servers may share the clone read-only; the simulator contract
    # requires the exact writable bind. Ambiguous writable runtimes still fail.
    runtimes = [
        c
        for c in running
        if any(
            m["Type"] == "bind"
            and m["Source"] == host_root
            and m["Destination"] == "/workspaces/isaaclab_arena"
            and m.get("RW") is True
            for m in c["Mounts"]
        )
    ]
    assert len(runtimes) == 1, "Cannot uniquely identify runtime image"
    runtime = runtimes[0]
    result = {"host_root": host_root, "runtime_image": runtime["Image"], "runtime_id": runtime["Id"]}
    images = [runtime["Image"]]
    if browser:
        result.update(discover_frontend(root, frontend_dependency_container, running=running))
        # Browser version is pinned by the installed frontend dependency manifest at runtime.
        local = docker("image", "ls", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}").splitlines()
        candidates = [
            line.split()[0] for line in local if line.startswith("mcr.microsoft.com/playwright:v1.58.2-noble ")
        ]
        assert len(candidates) == 1, "Approved local Playwright image missing; no pull permitted"
        result.update(browser_image=image_metadata(candidates[0])["Id"])
        images.append(result["browser_image"])
    for image in images:
        image_metadata(image)
    return result


def verify_container(run, identity, mounts):
    info = json.loads(run.command("inspect", "--format", OWN_FORMAT, identity))
    host = info["HostConfig"]
    assert info["Id"] == identity
    assert info["Config"]["Labels"].get(LABEL) == run.token
    assert info["Name"].lstrip("/") in run.candidates
    assert run.proof["created_ids"].get(info["Name"].lstrip("/")) == identity
    assert host["NetworkMode"] == "none" and host["ReadonlyRootfs"]
    assert info["Config"]["User"] == "1000:1000" and host["CapDrop"] == ["ALL"]
    assert not host["CapAdd"]
    assert "no-new-privileges" in host["SecurityOpt"]
    assert not host.get("DeviceRequests") and not host.get("Devices") and not host["Privileged"]
    assert not host.get("Binds") and not host.get("VolumesFrom") and not host.get("PortBindings")
    assert host.get("PidMode") in ("", None) and host.get("IpcMode") == "private"
    assert host.get("UsernsMode") in ("", None)
    assert type(host["PidsLimit"]) is int and 0 < host["PidsLimit"] <= 256
    assert type(host["Memory"]) is int and 0 < host["Memory"] <= 4294967296
    assert set(host["Tmpfs"]) == {"/tmp", "/private"}
    assert all({"rw", "nosuid", "nodev"} <= set(value.split(",")) for value in host["Tmpfs"].values())
    expected_mounts = {}
    for spec in mounts:
        fields = dict(part.split("=", 1) if "=" in part else (part, True) for part in spec.split(","))
        assert set(fields) <= {"type", "src", "dst", "readonly"}
        assert fields["type"] in {"bind", "volume"} and fields["dst"] not in expected_mounts
        expected_mounts[fields["dst"]] = fields
    assert len(info["Mounts"]) == len(expected_mounts), "Implicit/unexpected mount"
    for mount in info["Mounts"]:
        expected = expected_mounts.pop(mount["Destination"])
        assert mount["Type"] == expected["type"]
        source = mount.get("Name") if mount["Type"] == "volume" else mount["Source"]
        assert source == expected["src"], "Unexpected mount source"
        assert mount["RW"] is (not expected.get("readonly", False)), "Unexpected mount write permission"
    run.proof["containers"].append({
        "id": identity,
        "name": info["Name"],
        "image": info["Image"],
        "host_config": host,
        "mounts": info["Mounts"],
        "user": info["Config"]["User"],
        "labels": info["Config"]["Labels"],
    })
    run.proof["verified_isolation"][info["Name"].lstrip("/")] = True
    run.save()


def wait_file(run, identity, path, timeout=120):
    deadline = time.monotonic() + timeout
    while not path.exists():
        state = json.loads(run.command("inspect", "--format", projection({"Running": ".State.Running"}), identity))
        assert state["Running"], "Container exited before expected evidence"
        assert time.monotonic() < deadline, f"Timed out waiting for {path.name}"
        time.sleep(0.25)


def extract_dependency(payload, destination):
    """Preflight the complete bounded archive before creating any output."""
    import io
    import re
    import tarfile

    assert len(payload) <= 32 * 1024 * 1024, "Dependency archive byte budget"
    files = {}
    directories = set()
    seen = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        for member in archive:
            name = member.name
            parts = name.split("/")
            assert len(seen) < 4096 and name not in seen, "Duplicate/excess dependency entries"
            seen.add(name)
            assert parts[0] == "neo4j" and all(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", p) for p in parts)
            assert not member.linkname and not member.pax_headers, "Dependency link/extended metadata denied"
            assert member.isdir() or member.isreg(), "Dependency special entry denied"
            if member.isdir():
                directories.add(name)
            else:
                assert name.endswith(".py") or name == "neo4j/py.typed", "Unexpected dependency file"
                assert 0 <= member.size <= 2 * 1024 * 1024
                total += member.size
                assert total <= 16 * 1024 * 1024, "Dependency size budget"
                files[name] = archive.extractfile(member).read()
        assert "neo4j" in directories and "neo4j/__init__.py" in files, "Missing package root"
        assert all(
            str(Path(name).parent) in directories for name in seen if name != "neo4j"
        ), "Missing parent directory"
    destination = Path(destination)
    destination.mkdir(mode=0o755)  # Must be a fresh, private harness-owned directory.
    for name in sorted(directories, key=lambda value: (value.count("/"), value)):
        (destination / name).mkdir(mode=0o755)
    for name, content in files.items():
        with (destination / name).open("xb") as stream:
            stream.write(content)
    return {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}


# Only immutable installed image bytes are eligible. No live Docker diff/cp fallback.
# The exporter verifies root ancestors and every entry via descriptors before reading
# any package bytes; .pyc, hidden files, links and non-package entries are refused.
DEPENDENCY_PROBE = r"""import os,sysconfig,socket,errno,json,stat
assert os.getuid()==1000
assert os.statvfs('/').f_flag & os.ST_RDONLY
assert set(os.listdir('/sys/class/net'))=={'lo'}
assert not any(n.startswith('nvidia') or n=='dri' for n in os.listdir('/dev'))
with open('/proc/self/status') as stream: status=dict(line.split(':',1) for line in stream if ':' in line)
assert int(status['CapEff'].strip(),16)==0 and status['NoNewPrivs'].strip()=='1'
with socket.socket() as probe:
 probe.settimeout(2)
 try: probe.connect(('198.18.0.1',9))
 except OSError as e:
  assert e.errno in {errno.ENETUNREACH,errno.EHOSTUNREACH,errno.EPERM,errno.EACCES}
  denial=e.errno
 else: raise AssertionError('egress possible')
roots=sorted(set(sysconfig.get_path(key) for key in ('purelib','platlib')))
packages=[]
for root in roots:
 assert root.startswith('/isaac-sim/') and root.endswith('/site-packages') and '..' not in root.split('/')
 fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:
  for part in root.strip('/').split('/'):
   nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
  try: info=os.stat('neo4j',dir_fd=fd,follow_symlinks=False)
  except FileNotFoundError: continue
  assert stat.S_ISDIR(info.st_mode), 'Immutable package must be a real directory'
  packages.append(root+'/neo4j')
 finally: os.close(fd)
print(json.dumps({'schema_version':1,'status':'passed','uid':os.getuid(),'errno':denial,
 'egress_denied':True,'before_package_imports':True,'roots':roots,'packages':packages}))
"""

DEPENDENCY_EXPORT = r"""import os,stat,sys,io,tarfile,socket,errno
assert os.getuid()==1000
assert os.statvfs('/').f_flag & os.ST_RDONLY
assert set(os.listdir('/sys/class/net'))=={'lo'}
with socket.socket() as probe:
 probe.settimeout(2)
 try: probe.connect(('198.18.0.1',9))
 except OSError as e: assert e.errno in {errno.ENETUNREACH,errno.EHOSTUNREACH}
 else: raise AssertionError('egress possible')
root=sys.argv[1]
assert root.startswith('/isaac-sim/') and root.endswith('/site-packages/neo4j') and '..' not in root.split('/')
fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
for part in root.strip('/').split('/'):
 nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
entries=[]
def scan(fd,name):
 entries.append((name,None)); assert len(entries)<=4096
 for child in sorted(os.listdir(fd)):
  assert not child.startswith('.') and child.replace('_','').replace('-','').replace('.','').isalnum()
  info=os.stat(child,dir_fd=fd,follow_symlinks=False)
  if stat.S_ISDIR(info.st_mode):
   assert child!='__pycache__', 'Image package caches are not approved source'
   sub=os.open(child,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
   try: scan(sub,name+'/'+child)
   finally: os.close(sub)
  else:
   assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and (child.endswith('.py') or child=='py.typed')
   assert info.st_size<=2097152
   entries.append((name+'/'+child,(os.dup(fd),child,info)))
scan(fd,'neo4j');os.close(fd)
assert sum(e[1][2].st_size for e in entries if e[1])<=16777216
output=io.BytesIO()
with tarfile.open(fileobj=output,mode='w',format=tarfile.USTAR_FORMAT) as archive:
 for name,entry in entries:
  info=tarfile.TarInfo(name)
  if entry is None: info.type=tarfile.DIRTYPE;info.mode=0o755;archive.addfile(info)
  else:
   parent,child,before=entry
   f=os.open(child,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent);os.close(parent)
   after=os.fstat(f)
   assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)
   with os.fdopen(f,'rb') as stream: data=stream.read(2097153)
   assert len(data)==before.st_size
   info.size=len(data);info.mode=0o644;archive.addfile(info,io.BytesIO(data))
sys.stdout.buffer.write(output.getvalue())
"""


def obtain_dependency(run, discovered, destination):
    image = image_metadata(runtime_image(discovered))["Id"]
    donor = run.create(
        "dependency", image, "/usr/bin/env", ["-i", "HOME=/tmp", "PATH=/usr/bin:/bin", "sh", "-c", "sleep 180"], []
    )
    verify_container(run, donor, [])
    docker("start", donor)
    command = [
        "docker",
        "exec",
        "--user",
        "1000:1000",
        donor,
        "/usr/bin/env",
        "-i",
        "HOME=/tmp",
        "PATH=/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE=1",
        "/isaac-sim/python.sh",
        "-I",
        "-S",
        "-c",
    ]
    observed = subprocess.run([*command, DEPENDENCY_PROBE], capture_output=True, timeout=30)
    (run.output / "dependency-probe-error.log").write_bytes(observed.stderr)
    assert observed.returncode == 0, "Immutable package metadata probe failed; see dependency-probe-error.log"
    from check_proof import parse, passed

    probe = parse(observed.stdout)
    passed(probe, 1)
    provenance = {
        "source_container": donor,
        "source_image": image,
        "source_role": "dependency",
        "discovered_runtime_id": discovered["runtime_id"],
        "probe": probe,
        "trust": "installed immutable image; bounded descriptor-confined source-only archive",
    }
    run.proof["dependency_probe"] = provenance
    (run.output / "dependency-probe.json").write_text(json.dumps(provenance, indent=2))
    run.save()
    assert (
        len(probe["packages"]) == 1
    ), "Immutable Neo4j package unavailable or ambiguous; no live mutable copy, install or API launch"
    path = probe["packages"][0]
    assert path in [root + "/neo4j" for root in probe["roots"]]
    result = subprocess.run([*command, DEPENDENCY_EXPORT, path], capture_output=True, timeout=30)
    (run.output / "dependency-export-error.log").write_bytes(result.stderr)
    assert (
        result.returncode == 0
    ), "Approved dependency unavailable in immutable image; live mutable dependency copy denied"
    files = extract_dependency(result.stdout, destination)
    return dict(provenance, path=path, files=files)


def wheel_entries(payload, package, version):
    """Preflight inert wheel contents completely before writing any member."""
    import base64
    import csv
    import io
    import stat
    import zipfile

    assert package in ("neo4j", "pytz"), "Wheel package is not approved"
    assert len(payload) <= 2 * 1024 * 1024, "Wheel archive byte budget"
    files = {}
    metadata = package + "-" + version + ".dist-info"
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        assert 0 < len(entries) <= 4096, "Wheel entry budget"
        assert sum(row.file_size for row in entries) <= 16 * 1024 * 1024, "Wheel expanded byte budget"
        for row in entries:
            name = row.filename
            parts = name.split("/")
            assert len(parts) >= 2 and all(p not in ("", ".", "..") for p in parts), "Wheel path denied"
            assert all(all(c.isalnum() or c in "_.+-" for c in part) for part in parts), "Wheel path characters"
            assert parts[0] in (package, metadata), "Wheel unexpected root"
            mode = row.external_attr >> 16
            assert stat.S_IFMT(mode) in (0, stat.S_IFREG) and not mode & 0o7000, "Wheel link/special entry denied"
            assert not row.flag_bits & 1 and row.file_size <= 2 * 1024 * 1024, "Wheel encrypted/oversize entry"
            assert name not in files, "Wheel duplicate path"
            if parts[0] == package:
                assert (
                    name.endswith(".py") or parts[-1] == "py.typed" or (package == "pytz" and parts[1] == "zoneinfo")
                ), "Wheel hook/unapproved data"
            content = archive.read(row)
            assert len(content) == row.file_size, "Wheel inconsistent length"
            files[name] = content
    record_name = metadata + "/RECORD"
    assert record_name in files and metadata + "/METADATA" in files, "Wheel metadata absent"
    seen = set()
    for name, digest, size in csv.reader(io.StringIO(files[record_name].decode("utf-8"))):
        assert name in files and name not in seen, "Wheel RECORD coverage"
        seen.add(name)
        if name == record_name:
            assert digest == size == "", "Wheel RECORD self entry"
        else:
            expected = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest()).decode().rstrip("=")
            assert digest == expected and size == str(len(files[name])), "Wheel RECORD mismatch"
    assert seen == set(files), "Wheel unrecorded file"
    return files


def compare_source(root, manifest):
    """Hash through descriptor confinement; rejected paths are changed and errors."""
    from confined_io import read_confined

    changed, errors = [], []
    for name, expected in manifest.items():
        try:
            actual = hashlib.sha256(read_confined(root, name)).hexdigest()
            if actual != expected:
                changed.append(name)
        except (OSError, ValueError, AssertionError):
            changed.append(name)
            errors.append(name)
    return changed, errors


def require_passed(value):
    """Require the current wire proof contract without upgrading old records."""
    from check_proof import passed

    passed(value)


def hash_evidence(output, artifacts, errors):
    """Hash every evidence leaf through pinned descriptors, never follow links."""
    import stat

    from confined_io import MAX_ENTRIES, ConfinedRoot

    with ConfinedRoot(output) as source:
        count = 0

        def visit(folder):
            nonlocal count
            with source._directory(folder) as (descriptor, chain):
                names = sorted(os.listdir(descriptor))
                count += len(names)
                assert count <= MAX_ENTRIES, "Evidence entry budget exceeded"
                for leaf in names:
                    relative = folder / leaf
                    name = relative.as_posix()
                    try:
                        info = os.stat(leaf, dir_fd=descriptor, follow_symlinks=False)
                        if stat.S_ISDIR(info.st_mode):
                            visit(relative)
                        else:
                            artifacts[name] = hashlib.sha256(source.read(relative)).hexdigest()
                    except Exception:
                        errors.append(name)
                source._check(chain)

        visit(Path("evidence"))


def finalize(run, root):
    """Always attempt cleanup and final proof, without following evidence links."""
    output = run.output
    errors = run.proof.setdefault("evidence_errors", [])
    try:
        clean = run.cleanup()
    except BaseException as error:
        clean = False
        run.proof["remaining_owned"] = None
        run.proof.setdefault("cleanup_errors", []).append(type(error).__name__)
    run.proof["cleanup_verified"] = clean
    if not clean:
        run.proof["status"] = "failed"
    run.proof["acceptance_scope"] = "Frozen staged source; not a live-tree stability acceptance"
    try:
        manifest = run.proof.get("source_sha256", {})
        changed, rejected = compare_source(output / "source", manifest)
        run.proof["staged_source_unchanged"] = not changed
        run.proof["staged_source_hash_errors"] = rejected
        changed_live, rejected_live = compare_source(root, manifest)
        run.proof["live_source_changed_since_capture"] = changed_live
        run.proof["live_source_hash_errors"] = rejected_live
        if changed or rejected_live:
            run.proof["status"] = "failed"
    except Exception as error:
        run.proof["status"] = "failed"
        run.proof["staged_source_unchanged"] = False
        errors.append("source hashing: " + type(error).__name__)
    run.proof["artifacts"] = {}
    try:
        from confined_io import read_confined

        hash_evidence(output, run.proof["artifacts"], errors)
        for name in ("source-manifest.json", "dependency-manifest.json"):
            try:
                run.proof["artifacts"][name] = hashlib.sha256(read_confined(output, name)).hexdigest()
            except Exception:
                errors.append(name)
        for name in (
            "dependency-probe.json",
            "dependency-probe-error.log",
            "dependency-export-error.log",
            "provision-manifest.json",
        ):
            if (output / name).exists():
                run.proof["artifacts"][name] = hashlib.sha256(read_confined(output, name)).hexdigest()
    except Exception as error:
        errors.append("evidence hashing: " + type(error).__name__)
    if errors:
        run.proof["status"] = "failed"
    # Retain failed bridges/proofs for diagnosis; only remove a successful fresh bridge.
    if clean and run.proof.get("status") == "passed" and (output / "bridge").exists():
        try:
            shutil.rmtree(output / "bridge")
        except Exception as error:
            errors.append("bridge cleanup: " + type(error).__name__)
            run.proof["status"] = "failed"
    try:
        run.save()
        run.proof["artifacts"]["ownership.json"] = hashlib.sha256(read_confined(output, "ownership.json")).hexdigest()
        (output / "run-proof.json").write_text(json.dumps(run.proof, indent=2))
        if run.proof.get("status") == "passed":
            from check_proof import check

            try:
                check(output, browser=run.proof.get("browser", False))
            except Exception as error:
                run.proof["status"] = "failed"
                errors.append("v3 consistency: " + type(error).__name__ + ": " + str(error))
                run.save()
                run.proof["artifacts"]["ownership.json"] = hashlib.sha256(
                    read_confined(output, "ownership.json")
                ).hexdigest()
                (output / "run-proof.json").write_text(json.dumps(run.proof, indent=2))
    except Exception as error:
        run.proof["status"] = "failed"
        errors.append("final proof write: " + type(error).__name__)
        print(json.dumps({"status": "failed", "evidence_errors": errors}), flush=True)
    return run.proof.get("status") == "passed"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-image", help="Immutable test-only image ID; requires --provision-manifest")
    parser.add_argument("--provision-manifest", help="Verified test-only provision manifest")
    parser.add_argument("--frontend-dependency-container", help="Exact 64-hex stopped frontend dependency container ID")
    parser.add_argument("--browser", action="store_true", help="Also build and exercise real Chromium")
    parser.add_argument("--layout", choices=("legacy", "v7"), default="legacy")
    parser.add_argument("--profile", choices=("readonly", "authoring-v1", "manual-research-v1"), default="readonly")
    parser.add_argument(
        "--manual-research-closure-approved",
        action="store_true",
        help="Operator acknowledges parent-approved API security AND UI closure; not a bypass",
    )
    parser.add_argument("--fault", choices=("after-create", "preimport-denial"))
    options = parser.parse_args(argv)
    if options.frontend_dependency_container is not None and not options.browser:
        parser.error("--frontend-dependency-container requires --browser")
    if options.profile == "authoring-v1" and not (options.browser and options.layout == "v7"):
        parser.error("authoring-v1 requires --browser --layout v7")
    if options.profile == "manual-research-v1" and not (
        options.browser and options.layout == "v7" and options.manual_research_closure_approved
    ):
        parser.error(
            "manual-research-v1 requires --browser --layout v7 and parent-approved API security AND UI closure"
            " acknowledgement"
        )
    if options.manual_research_closure_approved and options.profile != "manual-research-v1":
        parser.error("Closure acknowledgement applies only to manual-research-v1")
    root = Path(__file__).resolve().parents[5]
    here = Path(__file__).resolve().parent
    token = "arena-f0-" + uuid.uuid4().hex[:12]
    output = here / ".runs" / token
    output.mkdir(parents=True, mode=0o755)
    run = OwnedRun(output, token)
    run.proof.update(status="starting", mutations_enabled=False, layout=options.layout, browser=options.browser)
    if options.profile != "readonly":
        run.proof["profile"] = options.profile
        run.proof["mutations_enabled"] = True
        run.proof["allowed_mutations"] = ["keyed-editor-save-fresh-private-state"]
        if options.profile == "manual-research-v1":
            from manual_research import MUTATIONS

            run.proof["allowed_mutations"] = list(MUTATIONS)
            run.proof["manual_research_closure_approved"] = True
    print(json.dumps({"output": str(output), "run": token}), flush=True)
    previous = {}

    def interrupted(signum, frame):
        raise InterruptedError(f"signal {signum}")

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, interrupted)
    try:
        dependency_selection = (
            {"frontend_dependency_container": options.frontend_dependency_container}
            if options.frontend_dependency_container is not None
            else {}
        )
        discovered = select_runtime(
            discover(root, options.browser, **dependency_selection), options.runtime_image, options.provision_manifest
        )
        run.proof["discovery"] = discovered
        if "provision" in discovered:
            (output / "provision-manifest.json").write_text(json.dumps(discovered["provision"], indent=2))
        from stage import FIXTURE, stage

        manifest = stage(root, output / "source", options.browser)
        if options.browser:
            (output / "source/web/arena-workbench/node_modules").mkdir()
        run.proof["source_sha256"] = manifest
        (output / "source-manifest.json").write_text(json.dumps(manifest, indent=2))
        from confined_io import read_confined

        run.proof["staging"] = {
            "policy_version": 2,
            "approved_fixture": FIXTURE,
            "manifest_sha256": hashlib.sha256(read_confined(output, "source-manifest.json")).hexdigest(),
        }
        for name in ("evidence", "bridge"):
            directory = output / name
            directory.mkdir(mode=0o700)
            os.chown(directory, 1000, 1000)
        host_out = discovered["host_root"] + "/" + str(output.relative_to(root))
        run.proof["host_output"] = host_out

        def bind(name, target, readonly=False):
            return f"type=bind,src={host_out}/{name},dst={target}" + (",readonly" if readonly else "")

        pydeps = output / "pydeps"
        run.proof["dependency"] = obtain_dependency(run, discovered, pydeps)
        (output / "dependency-manifest.json").write_text(json.dumps(run.proof["dependency"], indent=2))

        common = [
            bind("source", "/source", True),
            bind("pydeps", "/pydeps", True),
            bind("evidence", "/evidence"),
            bind("bridge", "/bridge"),
        ]
        script = "/source/web/arena-workbench/tests/e2e/functional-v7/api.py"
        clean_env = [
            "-i",
            "HOME=/tmp",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE=1",
            "PYTHONNOUSERSITE=1",
            "NVIDIA_VISIBLE_DEVICES=void",
            "CUDA_VISIBLE_DEVICES=",
            "F0_FAULT=" + (options.fault or ""),
            "F0_PROFILE=" + options.profile,
            "/isaac-sim/python.sh",
            script,
        ]
        api = run.create("api", runtime_image(discovered), "/usr/bin/env", clean_env, common)
        verify_container(run, api, common)
        if options.fault == "after-create":
            raise RuntimeError("Injected after-create fault")
        docker("start", api)
        wait_file(run, api, output / "evidence/api-proof.json")
        api_proof = json.loads((output / "evidence/api-proof.json").read_text())
        require_passed(api_proof)
        if options.browser:
            browser_mounts = [
                bind("source", "/source", True),
                bind("source/web/arena-workbench", "/app", True),
                bind("evidence", "/evidence"),
                bind("bridge", "/bridge", True),
                f"type=volume,src={discovered['deps']},dst=/app/node_modules,readonly",
            ]
            web = run.create(
                "browser",
                discovered["browser_image"],
                "/usr/bin/env",
                [
                    "-i",
                    "HOME=/tmp",
                    "PATH=/usr/local/bin:/usr/bin:/bin",
                    "LAYOUT=" + options.layout,
                    "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright",
                    "F0_PROFILE=" + options.profile,
                    "node",
                    "/source/web/arena-workbench/tests/e2e/functional-v7/browser.mjs",
                ],
                browser_mounts,
            )
            verify_container(run, web, browser_mounts)
            docker("start", web)
            wait_file(run, web, output / "evidence/browser-proof.json", 220)
            result = json.loads((output / "evidence/browser-proof.json").read_text())
            # Preserve genuine API lifespan/counters even when a browser journey fails.
            run.proof["frontend_dependencies"] = result["frontend_dependencies"]
        # API watches only its fresh private bridge; shut down via its own control file.
        (output / "bridge/stop").touch()
        wait_file(run, api, output / "evidence/api-final.json", 30)
        final = json.loads((output / "evidence/api-final.json").read_text())
        require_passed(final)
        assert not any(final["forbidden"].values()) and final["jobs"] == []
        assert final["lifespan_closed"] and final["socket_absent"]
        if options.browser:
            require_passed(result)
        run.proof["status"] = "passed"
    except BaseException:
        run.proof["status"] = "failed"
        run.proof["failure"] = traceback.format_exc()
        print(run.proof["failure"], flush=True)
    finally:
        # A second interrupt must not abandon bounded cleanup or evidence writing.
        for signum in previous:
            signal.signal(signum, signal.SIG_IGN)
        try:
            finalize(run, root)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        print(
            json.dumps({
                "status": run.proof["status"],
                "output": str(output),
                "remaining_owned": run.proof.get("remaining_owned"),
            }),
            flush=True,
        )
    return 0 if run.proof["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
