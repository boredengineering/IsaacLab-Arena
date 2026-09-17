#!/usr/bin/env -S /usr/bin/python3 -I -S
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Operator-installed, stdlib-only fixed-target research-service control."""

import sys

# sys is built in. This guard must precede every non-builtin import, including
# install. It cannot undo interpreter startup hooks: use the isolated launcher.
if __name__ == "__main__" and (not sys.flags.isolated or not sys.flags.no_site):
    raise SystemExit("control: python_isolated_mode_required_use_python3_-I_-S")

import argparse
import fcntl
import hashlib
import http.server
import json
import os
import re
import secrets
import selectors
import signal
import socket
import socketserver
import stat
import subprocess
import threading
import time
from contextlib import contextmanager, nullcontext, suppress
from http.cookies import SimpleCookie
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit

SERVICES = ("arena", "neo4j", "gr00t")
STARTUP_V2 = "operator-reviewed-existing-v2"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
API_ENVIRONMENT = {
    "ARENA_WORKBENCH_GR00T_PORT": re.compile(r"[1-9][0-9]{0,4}\Z"),
    "ARENA_GR00T_CHECKPOINT_SHA256": HEX64,
    "ARENA_GR00T_CONFIG_SHA256": HEX64,
    "ARENA_WORKBENCH_GPU_MIN_FREE_MIB": re.compile(r"[1-9][0-9]{0,9}\Z"),
    "ARENA_WORKBENCH_GPU_UUID": re.compile(r"GPU-[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}\Z"),
}
IDENTITY_KEYS = {
    "Id",
    "Image",
    "User",
    "Entrypoint",
    "Cmd",
    "WorkingDir",
    "NetworkMode",
    "Mounts",
    "Memory",
    "MemorySwap",
    "PidsLimit",
    "Privileged",
    "ReadonlyRootfs",
    "EnvSha256",
}


def exact(value, keys):
    """Reject missing and extra fields at a private/public contract boundary."""
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("invalid_contract")


def canonical(value):
    """Return canonical private contract bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def profile_revision(value):
    """Bind every operator expectation to a single immutable public revision."""
    return hashlib.sha256(canonical(value)).hexdigest()


def absolute(value):
    """Require an absolute normalized path, not a shell fragment or alias."""
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or str(PurePosixPath(value)) != value
        or ".." in PurePosixPath(value).parts
        or "\x00" in value
    ):
        raise ValueError("invalid_path")
    return value


def path_contains(source, target):
    """Compare lexical, symlink and inode aliases without reading host file bytes."""
    source, target = Path(source), Path(target)
    if target.is_relative_to(source) or target.resolve().is_relative_to(source.resolve()):
        return True
    # samefile also detects hardlinks and bind aliases of existing ancestors.
    for ancestor in (target, *target.parents, target.resolve(), *target.resolve().parents):
        try:
            if source.samefile(ancestor):
                return True
        except FileNotFoundError:
            continue
    return False


def positive(value, maximum=2**63 - 1):
    """Require a bounded positive integer, excluding booleans."""
    if type(value) is not int or not 0 < value <= maximum:
        raise ValueError("invalid_limit")


def validate_startup(identity, mode):
    """Apply only the explicitly selected private startup review contract."""
    if type(identity["ReadonlyRootfs"]) is not bool:
        raise ValueError("invalid_identity")
    absolute(identity["WorkingDir"] or "/")
    if mode in {"operator-reviewed-existing-v1", STARTUP_V2, "observation-only-v1"}:
        return
    if identity["ReadonlyRootfs"] is not True:
        raise ValueError("unverifiable_startup")
    cwd = PurePosixPath(absolute(identity["WorkingDir"] or "/"))
    argv = identity["Entrypoint"] + identity["Cmd"]
    if not argv[0].startswith("/"):
        raise ValueError("unverifiable_startup")
    candidates = [cwd]
    for arg in argv:
        if not re.fullmatch(r"[A-Za-z0-9_./:=,+@%-]+", arg) or arg.startswith(
            ("//", "-c", "-lc", "-ec", "-xc", "-m", "-e", "--command", "--eval")
        ):
            raise ValueError("unverifiable_startup")
        # Also inspect --script=/mount/path, not just standalone script arguments.
        path = PurePosixPath(arg.split("=", 1)[-1])
        if ".." in path.parts:
            raise ValueError("unverifiable_startup")
        candidates.append(path if path.is_absolute() else cwd / path)
    for mount in identity["Mounts"]:
        if any(path.is_relative_to(mount["Destination"]) for path in candidates):
            # Even a read-only bind can be changed by its host writer. Do not read
            # arbitrary host script paths or pretend the argv hash pins its bytes.
            raise ValueError("unverifiable_startup")


def validate_review_contract(review):
    """Require an explicit private mode and a bounded evidence list."""
    keys = {"mode", "files"}
    if isinstance(review, dict) and review.get("mode") == "observation-only-v1" and "mount_metadata" in review:
        keys.add("mount_metadata")
    if isinstance(review, dict) and review.get("mode") == STARTUP_V2:
        keys.update({"mount_metadata", "mount_probe_image"})
    exact(review, keys)
    if review["mode"] not in ("image-baked-v1", "operator-reviewed-existing-v1", STARTUP_V2, "observation-only-v1"):
        raise ValueError("invalid_startup_review")
    if review["mode"] == STARTUP_V2 and (
        not isinstance(review["mount_probe_image"], str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", review["mount_probe_image"])
    ):
        raise ValueError("invalid_mount_probe_image")
    if not isinstance(review["files"], list) or len(review["files"]) > 32:
        raise ValueError("invalid_startup_review")
    if review["mode"] == "observation-only-v1" and review["files"]:
        raise ValueError("invalid_startup_review")
    entries = review.get("mount_metadata", [])
    if not isinstance(entries, list) or len(entries) > 128:
        raise ValueError("invalid_mount_metadata")
    seen = set()
    for entry in entries:
        exact(entry, {"Source", "st_dev", "st_ino"})
        source = absolute(entry["Source"])
        if (
            (review["mode"] == STARTUP_V2 and "," in source)
            or source in seen
            or type(entry["st_dev"]) is not int
            or not 0 <= entry["st_dev"] < 2**64
            or type(entry["st_ino"]) is not int
            or not 0 < entry["st_ino"] < 2**64
        ):
            raise ValueError("invalid_mount_metadata")
        seen.add(source)


def mount_contains(source, target, review, *, bidirectional=False, verified_mounts=None):
    """Admit opaque v2 metadata only from this verification pass, never repin."""
    validate_review_contract(review)
    pin = next((entry for entry in review.get("mount_metadata", []) if entry["Source"] == source), None)
    if pin is None:
        return path_contains(source, target) or (bidirectional and path_contains(target, source))
    source, target = Path(source), Path(target)
    expected = (pin["st_dev"], pin["st_ino"])
    try:
        info = source.stat()
    except PermissionError:
        # Only this source stat failure admits pinned metadata. Target failures
        # below still fail closed, and missing/changed accessible sources fail.
        if review["mode"] == STARTUP_V2 and (verified_mounts or {}).get(str(source)) != expected:
            raise ValueError("fresh_mount_verification_required") from None
    else:
        if (info.st_dev, info.st_ino) != expected:
            raise ValueError("mount_metadata_changed")
        no_symlinks(source)
        return path_contains(source, target) or (bidirectional and path_contains(target, source))
    # Visible symlinks are refused; opaque ancestry is operator-reviewed.
    with suppress(PermissionError):
        no_symlinks(source)
    resolved_target = target.resolve()
    if any(t.is_relative_to(source) or (bidirectional and source.is_relative_to(t)) for t in (target, resolved_target)):
        return True
    for ancestor in (target, *target.parents, resolved_target, *resolved_target.parents):
        try:
            info = ancestor.stat()
        except FileNotFoundError:
            continue
        if (info.st_dev, info.st_ino) == expected:
            return True
    if bidirectional:
        try:
            info = target.stat()
        except FileNotFoundError:
            return False
        # Retain the reverse ancestor exclusion wherever host metadata is visible.
        for ancestor in source.parents:
            try:
                parent = ancestor.stat()
            except (FileNotFoundError, PermissionError):
                continue
            if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino):
                return True
    return False


def validate_reviewed_files(profile):
    """Validate explicit code-only source mappings without opening their bytes."""
    validate_review_contract(profile["startup_review"])
    if profile["startup_review"]["mode"] == "observation-only-v1":
        return
    seen = set()
    for entry in profile["startup_review"]["files"]:
        exact(entry, {"service", "container_path", "host_path", "sha256", "device", "inode"})
        if entry["service"] not in SERVICES:
            raise ValueError("invalid_startup_file")
        target = PurePosixPath(absolute(entry["container_path"]))
        source = PurePosixPath(absolute(entry["host_path"]))
        if (
            target.suffix not in {".py", ".sh"}
            or source.suffix not in {".py", ".sh"}
            or any(
                p.startswith(".") or p.lower() in {"models", "model", "data", "secrets", "weights", "cache"}
                for path in (target, source)
                for p in path.parts[1:]
            )
            or not isinstance(entry["sha256"], str)
            or not HEX64.fullmatch(entry["sha256"])
            or type(entry["device"]) is not int
            or entry["device"] < 0
            or type(entry["inode"]) is not int
            or entry["inode"] <= 0
        ):
            raise ValueError("invalid_startup_file")
        key = (entry["service"], str(target))
        if key in seen:
            raise ValueError("duplicate_startup_file")
        seen.add(key)
        mounts = [
            m
            for m in profile["services"][entry["service"]]["identity"]["Mounts"]
            if target.is_relative_to(m["Destination"])
        ]
        if (
            len(mounts) != 1
            or mounts[0]["Type"] != "bind"
            or source != PurePosixPath(mounts[0]["Source"]) / target.relative_to(mounts[0]["Destination"])
        ):
            raise ValueError("invalid_startup_mapping")
    required = {
        ("arena", profile["api"]["repo"] + "/" + name)
        for name in ("docker/workbench/runtime.py", "docker/workbench/workbench.py", "docker/resource_limits.py")
    }
    if not required <= seen:
        raise ValueError("missing_api_startup_review")
    if profile["startup_review"]["mode"] in {"operator-reviewed-existing-v1", STARTUP_V2}:
        for name, service in profile["services"].items():
            identity = service["identity"]
            cwd = PurePosixPath(identity["WorkingDir"] or "/")
            for index, arg in enumerate(identity["Entrypoint"] + identity["Cmd"]):
                path = PurePosixPath(arg.split("=", 1)[-1])
                if path.suffix not in {".sh", ".py"} and (index != 0 or "/" not in arg):
                    continue
                path = path if path.is_absolute() else cwd / path
                if any(path.is_relative_to(m["Destination"]) for m in identity["Mounts"]):
                    if (name, str(path)) not in seen:
                        raise ValueError("missing_startup_review")


def validate_identity(identity, mode, review=None, *, verified_mounts=None):
    """Validate known fields without treating unobserved metadata as startup evidence."""
    if review is not None:
        validate_review_contract(review)
        if review["mode"] != mode:
            raise ValueError("invalid_startup_review")
    observation_only = mode == "observation-only-v1"
    exact(identity, IDENTITY_KEYS)
    if (
        not isinstance(identity["Id"], str)
        or not HEX64.fullmatch(identity["Id"])
        or not isinstance(identity["Image"], str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", identity["Image"])
    ):
        raise ValueError("invalid_identity")
    if identity["Privileged"] is not False or not isinstance(identity["Mounts"], list):
        raise ValueError("invalid_identity")
    for key in ("User", "NetworkMode", "WorkingDir"):
        if not isinstance(identity[key], str) or "\x00" in identity[key]:
            raise ValueError("invalid_identity")
    if not identity["NetworkMode"]:
        raise ValueError("invalid_identity")
    if observation_only:
        if any(identity[key] is not None for key in ("EnvSha256", "Entrypoint", "Cmd")):
            raise ValueError("unobserved_metadata_required")
    else:
        if not isinstance(identity["EnvSha256"], str) or not HEX64.fullmatch(identity["EnvSha256"]):
            raise ValueError("invalid_identity")
        for key in ("Entrypoint", "Cmd"):
            if not isinstance(identity[key], list) or any(
                not isinstance(arg, str) or "\x00" in arg for arg in identity[key]
            ):
                raise ValueError("invalid_entrypoint")
        if not identity["Entrypoint"]:
            raise ValueError("unreviewed_entrypoint")
    for key in ("Memory", "MemorySwap", "PidsLimit"):
        if observation_only and (
            (key == "PidsLimit" and identity[key] is None)
            or (key != "PidsLimit" and type(identity[key]) is int and identity[key] == 0)
        ):
            continue
        positive(identity[key])
    if identity["MemorySwap"] != identity["Memory"]:
        raise ValueError("unreviewed_swap")
    for mount in identity["Mounts"]:
        exact(mount, {"Type", "Source", "Destination", "RW"})
        if mount["Type"] not in {"bind", "volume"} or type(mount["RW"]) is not bool:
            raise ValueError("invalid_mount")
        absolute(mount["Source"])
        absolute(mount["Destination"])
        if (
            "docker.sock" in mount["Source"]
            or "docker.sock" in mount["Destination"]
            or (
                mount_contains(mount["Source"], "/var/run/docker.sock", review, verified_mounts=verified_mounts)
                if review is not None
                else path_contains(mount["Source"], "/var/run/docker.sock")
            )
        ):
            raise ValueError("docker_mount_forbidden")
    validate_startup(identity, mode)


def validate_profile(value, *, verified_mounts=None):
    """Validate explicit operator-only admission; never infer startup safety."""
    exact(
        value,
        {
            "schema_version",
            "origin",
            "expected_policy",
            "connections",
            "services",
            "api",
            "storage",
            "resources",
            "limits",
            "frontend",
            "startup_review",
        },
    )
    if value["schema_version"] != 1 or value["expected_policy"] != "nvidia/GR00T-N1.6-DROID":
        raise ValueError("invalid_profile")
    origin = urlsplit(value["origin"])
    if (
        origin.scheme not in {"http", "https"}
        or origin.hostname != "127.0.0.1"
        or not origin.port
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("invalid_origin")
    connections = value["connections"]
    exact(connections, {"neo4j_uri", "neo4j_database", "gr00t_host", "gr00t_port"})
    graph = urlsplit(connections["neo4j_uri"])
    if (
        graph.scheme not in {"bolt", "neo4j"}
        or graph.hostname != "127.0.0.1"
        or not graph.port
        or graph.username
        or graph.password
        or graph.path
        or graph.query
        or graph.fragment
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,62}", connections["neo4j_database"])
        or connections["gr00t_host"] != "127.0.0.1"
        or type(connections["gr00t_port"]) is not int
        or not 1 <= connections["gr00t_port"] <= 65535
    ):
        raise ValueError("invalid_connections")
    review = value["startup_review"]
    validate_review_contract(review)
    observation_only = review["mode"] == "observation-only-v1"
    exact(value["services"], SERVICES)
    for service in value["services"].values():
        exact(service, {"identity", "startup_only", "offline", "cached_weights"})
        if any(service[key] is not (not observation_only) for key in ("startup_only", "offline", "cached_weights")):
            raise ValueError("unreviewed_entrypoint")
        exact(service["identity"], IDENTITY_KEYS)
        if not isinstance(service["identity"]["Mounts"], list):
            raise ValueError("invalid_mount")
        for mount in service["identity"]["Mounts"]:
            exact(mount, {"Type", "Source", "Destination", "RW"})
            absolute(mount["Source"])
    known_sources = {m["Source"] for s in value["services"].values() for m in s["identity"]["Mounts"]}
    if any(entry["Source"] not in known_sources for entry in review.get("mount_metadata", [])):
        raise ValueError("unknown_mount_metadata")
    for service in value["services"].values():
        validate_identity(service["identity"], review["mode"], review, verified_mounts=verified_mounts)
    api = value["api"]
    exact(api, {"uid", "gid", "repo", "state", "socket", "environment"})
    positive(api["uid"], 2**31 - 1)
    positive(api["gid"], 2**31 - 1)
    for key in ("repo", "state", "socket"):
        absolute(api[key])
    if (
        not isinstance(api["environment"], dict)
        or set(api["environment"]) - API_ENVIRONMENT.keys()
        or any(type(v) is not str or not API_ENVIRONMENT[k].fullmatch(v) for k, v in api["environment"].items())
    ):
        raise ValueError("invalid_environment")
    port = api["environment"].get("ARENA_WORKBENCH_GR00T_PORT")
    if port is not None and int(port) != connections["gr00t_port"]:
        raise ValueError("invalid_environment")
    state, socket = PurePosixPath(api["state"]), PurePosixPath(api["socket"])
    if (
        state.name != "state"
        or socket.name != "api.sock"
        or socket.parent.name != "ipc"
        or state.parent != socket.parent.parent
        or len(str(socket).encode()) >= 104
    ):
        raise ValueError("invalid_storage")
    storage = value["storage"]
    exact(storage, {"ipc_host", "state_host", "create"})
    for path in [storage["ipc_host"], storage["state_host"], *storage["create"]]:
        absolute(path)
    arena_mounts = value["services"]["arena"]["identity"]["Mounts"]
    for destination, path in ((api["repo"], None), ("/eval", storage["state_host"])):
        mounts = [m for m in arena_mounts if m["Destination"] == destination and m["Type"] == "bind" and m["RW"]]
        if len(mounts) != 1:
            raise ValueError("invalid_arena_mount")
        if path and (
            not state.is_relative_to("/eval")
            or str(PurePosixPath(mounts[0]["Source"]) / state.relative_to("/eval")) != path
            or str(PurePosixPath(mounts[0]["Source"]) / socket.parent.relative_to("/eval")) != storage["ipc_host"]
        ):
            raise ValueError("invalid_storage_mapping")
    if not any(m["Destination"] == "/data" and m["RW"] for m in value["services"]["neo4j"]["identity"]["Mounts"]):
        raise ValueError("missing_database_mount")
    if not value["services"]["gr00t"]["identity"]["Mounts"]:
        raise ValueError("missing_model_mount")
    exact(value["limits"], {"docker_seconds", "startup_seconds", "receipts"})
    for key, bound in (
        ("docker_seconds", 15),
        ("startup_seconds", 600),
        ("receipts", 128),
    ):
        positive(value["limits"][key], bound)
    exact(
        value["resources"],
        {"min_ram_available_bytes", "min_gpu_free_mib", "reviewed_until"},
    )
    for number in value["resources"].values():
        positive(number)
    frontend = value["frontend"]
    exact(frontend, {"image", "uid", "gid", "memory_bytes", "pids_limit", "name"})
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", frontend["image"]) or not re.fullmatch(
        r"[a-z][a-z0-9-]{0,62}", frontend["name"]
    ):
        raise ValueError("invalid_frontend")
    for key in ("uid", "gid", "memory_bytes", "pids_limit"):
        positive(frontend[key])
    validate_reviewed_files(value)
    return json.loads(canonical(value))


def verify_mount_sources(profile, docker=None, *, home=None):
    """Verify exact v2 Source pins freshly, with no authority retained across calls."""
    review = profile["startup_review"]
    validate_review_contract(review)
    if review["mode"] != STARTUP_V2:
        return None
    pins = {p["Source"]: (p["st_dev"], p["st_ino"]) for p in review["mount_metadata"]}
    # Preliminary shape/exclusion checking is NOT startup authorization. Candidate
    # pairs may reject protected aliases but cannot admit any effect until fresh
    # stat results below match. Do not spawn once per ancestor comparison.
    validate_profile(profile, verified_mounts=pins)
    if home is not None:
        protect_installation(home, profile, verified_mounts=pins)
    verify_reviewed_files(profile)
    docker = docker or Docker(seconds=profile["limits"]["docker_seconds"])
    if getattr(docker, "probe_unresolved", None) is not None:
        raise ValueError("mount_probe_cleanup_unknown")
    verified = {}
    with docker.budget(profile["limits"]["docker_seconds"]) if hasattr(docker, "budget") else nullcontext():
        for source, expected in pins.items():
            try:
                info = Path(source).stat()
            except PermissionError:
                observed = docker.mount_source_metadata(source, review["mount_probe_image"])
            else:
                no_symlinks(Path(source))
                observed = (info.st_dev, info.st_ino)
            if (
                not isinstance(observed, tuple)
                or len(observed) != 2
                or any(type(number) is not int for number in observed)
                or observed != expected
            ):
                raise ValueError("mount_metadata_changed")
            verified[source] = observed
    if getattr(docker, "probe_unresolved", None) is not None:
        raise ValueError("mount_probe_cleanup_unknown")
    validate_profile(profile, verified_mounts=verified)
    if home is not None:
        protect_installation(home, profile, verified_mounts=verified)
    return verified


def open_reviewed_code(path):
    """Open one exact host path with no-follow directory-relative traversal."""
    parts = PurePosixPath(absolute(path)).parts
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)


def verify_reviewed_files(profile):
    """Re-read only listed bounded regular code files; never learn replacement pins."""
    validate_reviewed_files(profile)
    if profile["startup_review"]["mode"] == "observation-only-v1":
        # Recheck metadata even on cached observations; never read source bytes.
        validate_profile(profile)
        return
    for entry in profile["startup_review"]["files"]:
        with os.fdopen(open_reviewed_code(entry["host_path"]), "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size > 262144
                or (before.st_dev, before.st_ino) != (entry["device"], entry["inode"])
            ):
                raise ValueError("startup_file_changed")
            data = stream.read(262145)
            after = os.fstat(stream.fileno())
            if (
                len(data) > 262144
                or hashlib.sha256(data).hexdigest() != entry["sha256"]
                or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            ):
                raise ValueError("startup_file_changed")
        # Detect replacement during the read as well as replacement since review.
        fd = open_reviewed_code(entry["host_path"])
        try:
            if os.fstat(fd) != after:
                raise ValueError("startup_file_changed")
        finally:
            os.close(fd)


class ControlError(Exception):
    """Carry only a static public code and HTTP disposition."""

    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def no_symlinks(path):
    """Reject every symlink component, including a dangling final component."""
    for component in [*reversed(path.parents), path]:
        if component.is_symlink():
            raise ValueError("symlink_storage")


def check_directory(path, uid, gid, mode):
    """Verify an existing directory without repairing ownership or mode."""
    no_symlinks(path)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_gid != gid:
        raise ValueError(f"directory_ownership_required:{uid}:{gid}:{path}")
    if stat.S_IMODE(info.st_mode) != mode:
        raise ValueError(f"directory_mode_required:{mode:o}:{path}")


def prepare_api_storage(profile, create=False):
    """Bootstrap only explicitly approved IPC parents, never modify old state."""
    api, storage = profile["api"], profile["storage"]
    state, ipc = Path(storage["state_host"]), Path(storage["ipc_host"])
    if state.parent != ipc.parent or state.name != "state" or ipc.name != "ipc":
        raise ValueError("invalid_storage")
    directories = [
        (state.parent.parent, 0o750),
        (state.parent, 0o750),
        (state, 0o700),
        (ipc, 0o750),
    ]
    approved = set(storage["create"])
    if approved - {str(path) for path, _ in directories}:
        raise ValueError("unapproved_directory")
    # Inspect every existing path before creating anything. Existing journals are untouched.
    for path, mode in directories:
        no_symlinks(path)
        if path.exists():
            check_directory(path, api["uid"], api["gid"], mode)
            continue
        if not create or str(path) not in approved:
            raise ValueError(f"approved_directory_missing:{path}")
        if os.getuid() != 0 and (api["uid"] != os.getuid() or api["gid"] not in {os.getgid(), *os.getgroups()}):
            raise ValueError(f'directory_ownership_required:{api["uid"]}:{api["gid"]}:{path}')
    for path, mode in directories:
        if not path.exists():
            path.mkdir(mode=mode)
            os.chown(path, api["uid"], api["gid"], follow_symlinks=False)
            os.chmod(path, mode, follow_symlinks=False)
        check_directory(path, api["uid"], api["gid"], mode)


def private_file(path, mode=0o600):
    """Read bounded, non-symlink operator-private bytes."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != mode
            or info.st_nlink != 1
        ):
            raise ValueError("private_file_ownership")
        data = stream.read(262145)
        if len(data) > 262144:
            raise ValueError("private_file_too_large")
        return data


def atomic_private(path, value):
    """Fsync a private replacement under the caller's exclusive writer lease."""
    temporary = path.with_name(path.name + ".pending")
    try:
        info = temporary.lstat()
    except FileNotFoundError:
        pass
    else:
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise ValueError("unsafe_pending_file")
        # A pre-replace crash cannot have released the following effect. The
        # committed marker alone is authoritative; never promote torn pending bytes.
        temporary.unlink()
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


class Controller:
    """Own startup receipts, never research jobs or dependency shutdown."""

    observation_seconds = 2.0
    observation_cooldown = 2.0

    def __init__(self, profile, state, docker, submit=None, guard=None, home=None):
        self.guard = guard or (lambda: None)
        if profile["startup_review"]["mode"] == STARTUP_V2:
            self.guard()
        self.home = home
        verified = verify_mount_sources(profile, docker, home=home)
        self.profile = validate_profile(profile, verified_mounts=verified)
        self.revision = profile_revision(self.profile)
        self.observation_only = self.profile["startup_review"]["mode"] == "observation-only-v1"
        if self.profile["startup_review"]["mode"] == STARTUP_V2:
            # Fresh mount passes plus API status exceed the legacy two seconds.
            # Keep one bounded deadline below the control client's 15 seconds.
            self.observation_seconds = 8.0
        self.state, self.docker = Path(state), docker
        self.lock = threading.RLock()
        self.observation_lock = threading.Lock()
        self.observation = None
        self.observation_after = 0.0
        self.submit = submit or (lambda task: threading.Thread(target=task, daemon=True).start())
        self.receipts = []
        self.path = self.state / "receipts.json"
        if self.path.exists():
            self.receipts = json.loads(private_file(self.path))
            if not isinstance(self.receipts, list) or len(self.receipts) > self.profile["limits"]["receipts"]:
                raise ValueError("invalid_receipts")
            seen = set()
            for operation in self.receipts:
                exact(operation, {"request_id", "profile_revision", "status", "code"})
                if (
                    not HEX32.fullmatch(operation["request_id"])
                    or not HEX64.fullmatch(operation["profile_revision"])
                    or operation["request_id"] in seen
                ):
                    raise ValueError("invalid_receipt")
                seen.add(operation["request_id"])
                codes = {
                    "starting": {"starting"},
                    "completed": {"services_started"},
                    "unknown": {"start_unknown"},
                    "failed": {
                        "start_failed",
                        "profile_mismatch",
                        "resource_unavailable",
                        "api_unavailable",
                    },
                }
                if operation["status"] not in codes or operation["code"] not in codes[operation["status"]]:
                    raise ValueError("invalid_receipt")
                if operation["status"] == "starting":
                    operation.update(status="unknown", code="start_unknown")
            self._save()

    def _save(self):
        atomic_private(self.path, self.receipts)

    def _guard(self):
        self.guard()
        if profile_revision(self.profile) != self.revision:
            raise ValueError("profile_mismatch")
        verify_reviewed_files(self.profile)
        verified = verify_mount_sources(self.profile, self.docker, home=self.home)
        if self.profile["startup_review"]["mode"] == STARTUP_V2:
            validate_profile(self.profile, verified_mounts=verified)

    def _states(self):
        try:
            self._guard()
        except Exception:
            return [{"id": name, "status": "unknown"} for name in SERVICES], (
                "unknown" if self.observation_only else "unavailable"
            )
        services = []
        for name in SERVICES:
            identity = self.profile["services"][name]["identity"]
            try:
                record = self.docker.inspect(
                    identity["Id"], **({"observation_only": True} if self.observation_only else {})
                )
                status = (
                    "missing"
                    if record is None
                    else (record["status"] if canonical(record["identity"]) == canonical(identity) else "mismatch")
                )
                if status not in {"running", "stopped", "missing", "mismatch"}:
                    status = "unknown"
            except Exception:
                status = "unknown"
            services.append({"id": name, "status": status})
        api = "unknown" if self.observation_only else "unavailable"
        if not self.observation_only and services[0]["status"] == "running":
            try:
                api = self.docker.api_status(self.profile)
                if api not in {"healthy", "stopped", "unavailable", "unknown"}:
                    api = "unknown"
            except Exception:
                api = "unknown"
        return services, api

    def observe(self, request_id=None, *, reuse=False):
        """Read exact retained disposition and current identities without starting."""
        with self.lock:
            operation = None
            if request_id is not None:
                if not isinstance(request_id, str) or not HEX32.fullmatch(request_id):
                    raise ControlError(400, "invalid_request")
                operation = next((r for r in self.receipts if r["request_id"] == request_id), None)
                if operation is None:
                    raise ControlError(404, "request_not_found")
            elif self.receipts:
                operation = self.receipts[-1]
        with self.observation_lock:
            fresh = not reuse or self.observation is None or time.monotonic() >= self.observation_after
            if hasattr(self.docker, "set_deadline"):
                self.docker.set_deadline(time.monotonic() + self.observation_seconds)
            try:
                if fresh:
                    services, api = self._states()
                    if reuse:
                        # Cache labels only, never mount verification authority.
                        self.observation = services, api
                        self.observation_after = time.monotonic() + self.observation_cooldown
                else:
                    services, api = self.observation
                try:
                    self._guard()
                    admitted = True
                except Exception:
                    admitted = False
            finally:
                if hasattr(self.docker, "set_deadline"):
                    self.docker.set_deadline(None)
        with self.lock:
            if (
                admitted
                and fresh
                and operation
                and operation["status"] == "unknown"
                and operation["profile_revision"] == self.revision
                and all(s["status"] == "running" for s in services)
                and api == "healthy"
            ):
                self._finish(operation, "completed", "services_started")
        return {
            "schema_version": 1,
            "profile_revision": self.revision,
            "expected_policy": self.profile["expected_policy"],
            "services": services,
            "api": api,
            "startup_allowed": (
                not self.observation_only
                and admitted
                and all(s["status"] in {"running", "stopped"} for s in services)
                and not any(r["status"] in {"starting", "unknown"} for r in self.receipts)
            ),
            "operation": dict(operation) if operation else None,
        }

    def start(self, request):
        """Reserve exact request before dispatching a bounded background startup."""
        try:
            exact(request, {"request_id", "profile_revision"})
            if not HEX32.fullmatch(request["request_id"]) or not HEX64.fullmatch(request["profile_revision"]):
                raise ValueError()
        except (ValueError, TypeError):
            raise ControlError(400, "invalid_request") from None
        if self.observation_only:
            raise ControlError(403, "startup_disabled")
        with self.lock:
            old = next(
                (r for r in self.receipts if r["request_id"] == request["request_id"]),
                None,
            )
            if old:
                if old["profile_revision"] != request["profile_revision"]:
                    raise ControlError(409, "request_conflict")
                return dict(old)
            if request["profile_revision"] != self.revision:
                raise ControlError(409, "profile_mismatch")
            if any(r["status"] in {"starting", "unknown"} for r in self.receipts):
                raise ControlError(429, "startup_busy")
            if len(self.receipts) >= self.profile["limits"]["receipts"]:
                # Never forget an accepted ID and accidentally execute its replay again.
                raise ControlError(429, "receipt_capacity")
            try:
                self._guard()
            except Exception:
                raise ControlError(503, "profile_unavailable") from None
            operation = dict(request, status="starting", code="starting")
            self.receipts.append(operation)
            self._save()
            result = dict(operation)
            self.submit(lambda: self._run(operation))
            return result

    def _finish(self, operation, status, code):
        with self.lock:
            operation.update(status=status, code=code)
            self._save()

    def _run(self, operation):
        if self.observation_only:
            raise ControlError(403, "startup_disabled")
        deadline = time.monotonic() + self.profile["limits"]["startup_seconds"]
        effect_attempted = False
        if hasattr(self.docker, "set_deadline"):
            self.docker.set_deadline(deadline)
        try:
            self._guard()
            services, api = self._states()
            if any(s["status"] not in {"running", "stopped"} for s in services):
                self._finish(operation, "failed", "profile_mismatch")
                return
            if not self.docker.resources(self.profile):
                self._finish(operation, "failed", "resource_unavailable")
                return
            for name in SERVICES:
                self._guard()
                if time.monotonic() >= deadline:
                    raise TimeoutError()
                identity = self.profile["services"][name]["identity"]
                record = self.docker.inspect(identity["Id"])
                if not record or record["identity"] != identity or record["status"] not in {"running", "stopped"}:
                    self._finish(operation, "failed", "profile_mismatch")
                    return
                if record["status"] == "stopped":
                    self._guard()
                    effect_attempted = True
                    self.docker.start(
                        identity["Id"],
                        **({"profile": self.profile} if self.profile["startup_review"]["mode"] == STARTUP_V2 else {}),
                    )
                record = self.docker.inspect(identity["Id"])
                if not record or record["identity"] != identity or record["status"] != "running":
                    raise TimeoutError()
                if name == "neo4j":
                    api = self.docker.api_status(self.profile)
                    if api == "stopped":
                        effect_attempted = True
                        self._guard()
                        self.docker.api_start(self.profile)
                    elif api != "healthy":
                        self._finish(operation, "failed", "api_unavailable")
                        return
            while time.monotonic() < deadline:
                services, api = self._states()
                if all(s["status"] == "running" for s in services) and api == "healthy":
                    self._finish(operation, "completed", "services_started")
                    return
                if any(s["status"] in {"missing", "mismatch"} for s in services):
                    self._finish(operation, "failed", "profile_mismatch")
                    return
                time.sleep(min(0.2, max(0, deadline - time.monotonic())))
            raise TimeoutError()
        except TimeoutError:
            self._finish(operation, "unknown", "start_unknown")
        except Exception:
            self._finish(
                operation,
                "unknown" if effect_attempted else "failed",
                "start_unknown" if effect_attempted else "start_failed",
            )
        finally:
            if hasattr(self.docker, "set_deadline"):
                self.docker.set_deadline(None)


def protect_installation(home, profile, *, verified_mounts=None):
    """Keep every service mount separate from installed code and private markers."""
    home = Path(home)
    # A hardlink inside an otherwise unrelated service directory also exposes a
    # secret. Inspect only our fixed marker inodes, never walk/read arbitrary mounts.
    for name in (
        "control.py",
        "profile.json",
        "installation.json",
        "pairing.json",
        "frontend.json",
        "state/receipts.json",
        "state/helper.lock",
    ):
        for suffix in ("", ".pending"):
            try:
                info = (home / (name + suffix)).lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("installation_secret_alias")
    for service in profile["services"].values():
        for mount in service["identity"]["Mounts"]:
            if mount_contains(
                mount["Source"], home, profile["startup_review"], bidirectional=True, verified_mounts=verified_mounts
            ):
                raise ValueError("installation_inside_service_mount")


def install(home, profile, source, source_sha256, docker=None):
    """Copy explicitly reviewed stdlib helper bytes outside all Arena mounts."""
    home, source = Path(absolute(str(home))), Path(source)
    no_symlinks(home)
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        data = stream.read(262145)
    if not HEX64.fullmatch(source_sha256) or len(data) > 262144 or hashlib.sha256(data).hexdigest() != source_sha256:
        raise ValueError("reviewed_helper_hash_mismatch")
    verified = verify_mount_sources(profile, docker, home=home)
    profile = validate_profile(profile, verified_mounts=verified)
    protect_installation(home, profile, verified_mounts=verified)
    verify_reviewed_files(profile)
    # Require an existing owner-private parent; never recursively create/chown it.
    check_directory(home.parent, os.getuid(), os.getgid(), 0o700)
    home.mkdir(mode=0o700)
    home.chmod(0o700)
    for name in ("state", "ipc"):
        mode = 0o700 if name == "state" else 0o750
        (home / name).mkdir(mode=mode)
        (home / name).chmod(mode)
    with os.fdopen(
        os.open(
            home / "control.py",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o700,
        ),
        "wb",
    ) as stream:
        os.fchmod(stream.fileno(), 0o700)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    atomic_private(home / "profile.json", profile)
    ipc = (home / "ipc").stat()
    atomic_private(
        home / "installation.json",
        {
            "schema_version": 1,
            "helper_sha256": source_sha256,
            "profile_revision": profile_revision(profile),
            "uid": os.getuid(),
            "gid": os.getgid(),
            "ipc_device": ipc.st_dev,
            "ipc_inode": ipc.st_ino,
        },
    )
    return load_installation(home, docker=docker)


def load_installation(home, docker=None, *, authenticate_only=False):
    """Verify installed bytes/profile and the unchanged owner-controlled socket directory."""
    home = Path(home)
    manifest = json.loads(private_file(home / "installation.json"))
    for directory, mode in (
        (home, 0o700),
        (home / "state", 0o700),
        (home / "ipc", 0o750),
    ):
        check_directory(directory, manifest["uid"], manifest["gid"], mode)
    if manifest["uid"] != os.getuid() or manifest["gid"] != os.getgid():
        raise ValueError("installation_owner_mismatch")
    profile = json.loads(private_file(home / "profile.json"))
    ipc = (home / "ipc").stat()
    if (
        hashlib.sha256(private_file(home / "control.py", mode=0o700)).hexdigest() != manifest["helper_sha256"]
        or profile_revision(profile) != manifest["profile_revision"]
        or (ipc.st_dev, ipc.st_ino) != (manifest["ipc_device"], manifest["ipc_inode"])
    ):
        raise ValueError("installation_changed")
    if authenticate_only:
        return {"profile": profile, "manifest": manifest}
    verified = verify_mount_sources(profile, docker, home=home)
    profile = validate_profile(profile, verified_mounts=verified)
    protect_installation(home, profile, verified_mounts=verified)
    verify_reviewed_files(profile)
    return {"profile": profile, "manifest": manifest}


def bootstrap_frontend(home, profile, docker):
    """Explicit host bootstrap: create once from cached image, pin ID, never recreate."""
    home = Path(home)
    inspection = {"observation_only": True} if profile["startup_review"]["mode"] == "observation-only-v1" else {}
    marker = home / "frontend.json"
    if marker.exists():
        receipt = json.loads(private_file(marker))
        if receipt["status"] not in {"created", "starting"} or receipt["profile_revision"] != profile_revision(profile):
            raise ValueError("frontend_bootstrap_unresolved")
        target = receipt["identity"]["Id"]
        record = docker.inspect(target, **inspection)
        if not record or record["identity"] != receipt["identity"]:
            raise ValueError("frontend_identity_mismatch")
        if receipt["status"] == "starting" and record["status"] != "running":
            raise ValueError("frontend_start_unknown")
    else:
        frontend = profile["frontend"]
        # Reserve before creation: ambiguous create is never resent by bootstrap.
        atomic_private(
            marker,
            {"status": "creating", "profile_revision": profile_revision(profile)},
        )
        argv = [
            "create",
            "--pull=never",
            "--name",
            frontend["name"],
            "--user",
            f'{frontend["uid"]}:{frontend["gid"]}',
            "--group-add",
            str(profile["api"]["gid"]),
            "--group-add",
            str(os.getgid()),
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--init",
            "--restart=no",
            "--memory",
            str(frontend["memory_bytes"]),
            "--memory-swap",
            str(frontend["memory_bytes"]),
            "--pids-limit",
            str(frontend["pids_limit"]),
            "--publish",
            f'127.0.0.1:{urlsplit(profile["origin"]).port}:3000',
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,mode=1777",
            "--mount",
            f'type=bind,src={profile["storage"]["ipc_host"]},dst=/run/arena-api,readonly',
            "--mount",
            f'type=bind,src={home / "ipc"},dst=/run/arena-control,readonly',
            frontend["image"],
        ]
        target = docker.call(*argv)
        if not HEX64.fullmatch(target):
            raise ValueError("frontend_bootstrap_unresolved")
        record = docker.inspect(target, **inspection)
        if not record or record["identity"]["Id"] != target or record["identity"]["Image"] != frontend["image"]:
            raise ValueError("frontend_identity_mismatch")
        atomic_private(
            marker,
            {
                "status": "created",
                "profile_revision": profile_revision(profile),
                "identity": record["identity"],
            },
        )
    if record["status"] == "stopped":
        atomic_private(
            marker,
            {"status": "starting", "profile_revision": profile_revision(profile), "identity": record["identity"]},
        )
        docker.start(target)
    elif record["status"] != "running":
        raise ValueError("frontend_state_unknown")
    after = docker.inspect(target, **inspection)
    if not after or after["identity"] != record["identity"] or after["status"] != "running":
        raise ValueError("frontend_start_unknown")
    atomic_private(
        marker, {"status": "created", "profile_revision": profile_revision(profile), "identity": record["identity"]}
    )
    return target


class DockerFailure(Exception):
    """A Docker call failed without exposing driver diagnostics."""


def bounded_run(argv, timeout):
    """Bound subprocess time and output; discard raw driver errors."""
    environment = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C.UTF-8"}
    with subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=environment,
        close_fds=True,
    ) as process:
        deadline, output = time.monotonic() + timeout, bytearray()
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError()
                    data = os.read(process.stdout.fileno(), 8192)
                    if not data:
                        break
                    output.extend(data)
                    if len(output) > 262144:
                        raise DockerFailure()
                if process.wait(timeout=max(0.001, deadline - time.monotonic())):
                    raise DockerFailure()
            return output.decode()
        except subprocess.TimeoutExpired:
            raise TimeoutError() from None
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


class Docker:
    """Fixed local-daemon inspection/start and non-root API supervisor adapter."""

    def __init__(self, run=bounded_run, seconds=15, guard=None):
        self.run, self.seconds = run, seconds
        self.guard = guard or (lambda profile: None)
        self.home = None
        self.local = threading.local()
        self.probe_lock = threading.Lock()
        self.prefix = ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock"]

    def set_deadline(self, deadline):
        """Apply a startup deadline only to this worker, never concurrent observation."""
        self.local.deadline = deadline

    def timeout(self):
        deadline = getattr(self.local, "deadline", None)
        remaining = self.seconds if deadline is None else min(self.seconds, deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError()
        return remaining

    def call(self, *argv):
        return self.run([*self.prefix, *argv], self.timeout()).strip()

    @contextmanager
    def budget(self, seconds):
        """Share the earliest deadline across nested calls and all mount sources."""
        previous = getattr(self.local, "deadline", None)
        deadline = time.monotonic() + seconds
        self.set_deadline(deadline if previous is None else min(previous, deadline))
        try:
            yield
        finally:
            self.set_deadline(previous)

    def _probe_owner(self, target, name, label):
        """Read only exact probe ownership metadata, never container contents."""
        template = (
            '{"Id":{{json .Id}},"Name":{{json .Name}},"Labels":'
            '{"arena.control.mount-stat":{{json (index .Config.Labels "arena.control.mount-stat")}}}}'
        )
        record = json.loads(self.call("inspect", "--type", "container", "--format", template, target))
        exact(record, {"Id", "Name", "Labels"})
        key, value = label.split("=", 1)
        if (
            record["Id"] != target
            or record["Name"] != "/" + name
            or not isinstance(record["Labels"], dict)
            or record["Labels"].get(key) != value
        ):
            raise ValueError("mount_probe_ownership_unknown")

    def _cleanup_probe(self, ownership):
        """Use an independent total cleanup budget, exact IDs and verified ownership."""
        previous = getattr(self.local, "deadline", None)
        self.set_deadline(time.monotonic() + 2.0)
        try:
            target, name, label = ownership["id"], ownership["name"], ownership["label"]
            if target is None:
                # A lost create ACK is not absence. Resolve only this unpredictable
                # ownership pair; never a service name or an arbitrary container.
                ids = self.call(
                    "ps", "-aq", "--no-trunc", "--filter", "name=^/" + name + "$", "--filter", "label=" + label
                ).splitlines()
                if not ids:
                    return
                if len(ids) != 1 or not HEX64.fullmatch(ids[0]):
                    raise ValueError("mount_probe_ownership_unknown")
                target = ownership["id"] = ids[0]
            self._probe_owner(target, name, label)
            self.call("rm", "--force", target)
            if self.call("ps", "-aq", "--no-trunc", "--filter", "id=" + target):
                raise ValueError("mount_probe_cleanup_unknown")
        finally:
            self.set_deadline(previous)

    def mount_source_metadata(self, source, image):
        """Serialize probe ownership within the caller's existing total deadline."""
        with self.budget(self.seconds):
            if not self.probe_lock.acquire(timeout=self.timeout()):
                raise TimeoutError()
            try:
                return self._mount_source_metadata(source, image)
            finally:
                self.probe_lock.release()

    def _mount_source_metadata(self, source, image):
        """Stat one approved read-only bind using a trusted cached image, then prove cleanup."""
        absolute(source)
        if "," in source or not isinstance(image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise ValueError("invalid_mount_probe")
        if getattr(self, "probe_unresolved", None) is not None:
            raise ValueError("mount_probe_cleanup_unknown")
        previous = getattr(self.local, "deadline", None)
        deadline = time.monotonic() + self.seconds
        self.set_deadline(deadline if previous is None else min(previous, deadline))
        try:
            template = '{"Id":{{json .Id}},"Volumes":{{json (index .Config "Volumes")}}}'
            record = json.loads(self.call("image", "inspect", "--format", template, image))
            exact(record, {"Id", "Volumes"})
            if record["Id"] != image or record["Volumes"] not in (None, {}):
                raise ValueError("invalid_mount_probe_image")
            token = secrets.token_hex(16)
            ownership = {"id": None, "name": "arena-mount-stat-" + token, "label": "arena.control.mount-stat=" + token}
            self.probe_unresolved = ownership
            try:
                target = self.call(
                    "create",
                    "--pull=never",
                    "--name",
                    ownership["name"],
                    "--label",
                    ownership["label"],
                    "--user",
                    "1000:1000",
                    "--network=none",
                    "--read-only",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges:true",
                    "--restart=no",
                    "--no-healthcheck",
                    "--memory",
                    "67108864",
                    "--memory-swap",
                    "67108864",
                    "--pids-limit",
                    "32",
                    "--workdir",
                    "/",
                    "--entrypoint",
                    "/usr/bin/stat",
                    "--mount",
                    f"type=bind,src={source},dst=/arena-mount-source,readonly",
                    image,
                    "--format=%d %i",
                    "--",
                    "/arena-mount-source",
                )
                if not HEX64.fullmatch(target):
                    raise ValueError("mount_probe_create_unknown")
                ownership["id"] = target
                self._probe_owner(target, ownership["name"], ownership["label"])
                output = self.call("start", "--attach", target)
                if self.call("wait", target) != "0" or not re.fullmatch(r"[0-9]{1,20} [0-9]{1,20}", output):
                    raise ValueError("invalid_mount_probe_result")
                pair = tuple(int(value) for value in output.split(" "))
                if not 0 <= pair[0] < 2**64 or not 0 < pair[1] < 2**64:
                    raise ValueError("invalid_mount_probe_result")
                return pair
            finally:
                # Cleanup failure overrides a successful stat and retains known
                # ownership, poisoning this adapter against subsequent probes.
                self._cleanup_probe(ownership)
                self.probe_unresolved = None
        finally:
            self.set_deadline(previous)

    def inspect(self, target, *, observation_only=False):
        if not HEX64.fullmatch(target):
            raise ValueError("invalid_identity")
        # Observation never requests environment/argv, even for private hashing.
        # Approved startup modes retain the saved-environment review digest.
        fields = {
            "Id": ".Id",
            "Image": ".Image",
            "User": ".Config.User",
            "WorkingDir": ".Config.WorkingDir",
            "NetworkMode": ".HostConfig.NetworkMode",
            "Mounts": ".Mounts",
            "Memory": ".HostConfig.Memory",
            "MemorySwap": ".HostConfig.MemorySwap",
            "PidsLimit": ".HostConfig.PidsLimit",
            "Privileged": ".HostConfig.Privileged",
            "ReadonlyRootfs": ".HostConfig.ReadonlyRootfs",
        }
        if not observation_only:
            fields.update(Entrypoint=".Config.Entrypoint", Cmd=".Config.Cmd", Env=".Config.Env")
        template = (
            "{"
            + ",".join('"' + name + '":{{json ' + field + "}}" for name, field in fields.items())
            + ',"State":{"Status":{{json .State.Status}}}}'
        )
        try:
            record = json.loads(self.call("inspect", "--type", "container", "--format", template, target))
        except DockerFailure:
            # A failed daemon call does not prove absence. Query exact retained ID.
            ids = self.call("ps", "-aq", "--no-trunc", "--filter", "id=" + target).splitlines()
            if target not in ids:
                return None
            raise
        if observation_only:
            exact(record, {*fields, "State"})
            record.update(EnvSha256=None, Entrypoint=None, Cmd=None)
        else:
            record["EnvSha256"] = hashlib.sha256(canonical(record.pop("Env"))).hexdigest()
            record["Cmd"] = record["Cmd"] or []
        record["Mounts"] = [
            {key: mount[key] for key in ("Type", "Source", "Destination", "RW")} for mount in record["Mounts"]
        ]
        status = {"running": "running", "exited": "stopped", "created": "stopped"}.get(
            record.pop("State")["Status"], "unknown"
        )
        return {"identity": record, "status": status}

    def start(self, target, *, profile=None):
        if not HEX64.fullmatch(target):
            raise ValueError("invalid_identity")
        if profile is not None:
            if target not in {s["identity"]["Id"] for s in profile["services"].values()}:
                raise ValueError("invalid_identity")
            self.guard(profile)
            verify_reviewed_files(profile)
            verify_mount_sources(profile, self, home=self.home)
        self.call("start", target)

    def _api(self, profile, action):
        if profile["startup_review"]["mode"] == "observation-only-v1":
            raise ControlError(403, "startup_disabled")
        api = profile["api"]
        target = profile["services"]["arena"]["identity"]
        record = self.inspect(target["Id"])
        if not record or record["identity"] != target or record["status"] != "running":
            raise DockerFailure()
        argv = [
            "exec",
            "--user",
            f'{api["uid"]}:{api["gid"]}',
            "--workdir",
            api["repo"],
        ]
        for name, value in sorted(api["environment"].items()):
            argv += ["--env", name + "=" + value]
        argv += [
            target["Id"],
            "/isaac-sim/python.sh",
            api["repo"] + "/docker/workbench/runtime.py",
            action,
            "--state-dir",
            api["state"],
            "--socket",
            api["socket"],
            "--origin",
            profile["origin"],
            "--start-paused",
        ]
        self.guard(profile)
        verify_reviewed_files(profile)
        verify_mount_sources(profile, self, home=self.home)
        return self.call(*argv)

    def api_status(self, profile):
        if profile["startup_review"]["mode"] == "observation-only-v1":
            return "unknown"
        status = json.loads(self._api(profile, "status"))
        if status["owned"] and status["healthy"]:
            return "healthy"
        return "stopped" if not status["owned"] and not status["healthy"] else "unavailable"

    def api_start(self, profile):
        self._api(profile, "ensure-paused")

    def resources(self, profile):
        if profile["startup_review"]["mode"] == "observation-only-v1":
            return False
        expected = profile["resources"]
        if time.time() >= expected["reviewed_until"]:
            return False
        memory = next(
            int(line.split()[1]) * 1024
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith("MemAvailable:")
        )
        try:
            gpu = self.run(
                [
                    "/usr/bin/nvidia-smi",
                    "--query-gpu=memory.free",
                    "--format=csv,noheader,nounits",
                ],
                self.timeout(),
            )
            # Multi-GPU target selection is deliberately unsupported, not guessed.
            values = gpu.splitlines()
            return (
                memory >= expected["min_ram_available_bytes"]
                and len(values) == 1
                and int(values[0]) >= expected["min_gpu_free_mib"]
            )
        except (OSError, ValueError, DockerFailure, TimeoutError):
            return False


class ControlServer(socketserver.UnixStreamServer):
    """Serve bounded same-origin control requests on a separately owned UDS."""

    def __init__(self, path, controller, pairing_token):
        self.controller = controller
        self.pairing_token = pairing_token
        self.pairing_expires = time.time() + 300
        self.pairing_attempts = 0
        self.session = None
        super().__init__(path, ControlHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address

    def handle_error(self, request, client_address):
        # Never print request bodies, cookies, Docker output or pairing material.
        pass


class ControlHandler(http.server.BaseHTTPRequestHandler):
    """Expose only the frozen control wire, with no generic Docker proxy."""

    def log_message(self, format, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self._reply(405 if code == 501 else code, {"error": "method_not_allowed" if code == 501 else "invalid_request"})

    def _reply(self, status, body, cookie=None):
        data = canonical(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def _session(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except Exception:
            raise ControlError(401, "unauthorized") from None
        session = self.server.session
        cookie = cookies.get("arena_control")
        if (
            not session
            or session["expires_at"] <= time.time()
            or not cookie
            or not secrets.compare_digest(cookie.value, session["cookie"])
        ):
            raise ControlError(401, "unauthorized")
        return session

    def _body(self):
        if hasattr(self, "body"):
            return self.body
        if self.headers.get("Content-Type", "").lower() != "application/json" or self.headers.get("Transfer-Encoding"):
            raise ControlError(400, "invalid_request")
        lengths = self.headers.get_all("Content-Length", [])
        if self.command == "DELETE" and lengths in ([], ["0"]):
            return {}
        if len(lengths) != 1 or not lengths[0].isdigit() or not 0 < int(lengths[0]) <= 2048:
            raise ControlError(400, "invalid_request")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result

        try:
            body = json.loads(
                self.rfile.read(int(lengths[0])),
                object_pairs_hook=unique,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
            if not isinstance(body, dict):
                raise ValueError()
            return body
        except (ValueError, UnicodeError):
            raise ControlError(400, "invalid_request") from None

    def _dispatch(self):
        if self.command not in {"POST", "GET", "DELETE"}:
            raise ControlError(405, "method_not_allowed")
        origin = self.server.controller.profile["origin"]
        if self.headers.get_all("Host", []) != [urlsplit(origin).netloc]:
            raise ControlError(403, "wrong_host")
        origins = self.headers.get_all("Origin", [])
        if origins != [origin] and (self.command != "GET" or origins):
            raise ControlError(403, "wrong_origin")
        if self.headers.get("Sec-Fetch-Site") not in {None, "same-origin", "none"}:
            raise ControlError(403, "wrong_origin")
        target = urlsplit(self.path)
        if target.scheme or target.netloc or target.fragment:
            raise ControlError(400, "invalid_request")
        if target.path == "/control/session" and not target.query and self.command == "POST":
            body = self._body()
            if not body:
                session = self._session()
                cookie = None
            else:
                exact(body, {"pairing_token"})
                token = body["pairing_token"]
                self.server.pairing_attempts += 1
                if (
                    not isinstance(token, str)
                    or self.server.pairing_attempts > 5
                    or time.time() >= self.server.pairing_expires
                    or not self.server.pairing_token
                    or not secrets.compare_digest(token, self.server.pairing_token)
                ):
                    raise ControlError(401, "pairing_failed")
                self.server.pairing_token = None
                session = {
                    "cookie": secrets.token_hex(32),
                    "csrf_token": secrets.token_hex(32),
                    "expires_at": time.time() + 1800,
                }
                self.server.session = session
                cookie = (
                    "arena_control=" + session["cookie"] + "; HttpOnly; SameSite=Strict; Path=/control; Max-Age=1800"
                )
                if origin.startswith("https:"):
                    cookie += "; Secure"
            self._reply(
                200,
                {
                    "schema_version": 1,
                    "csrf_token": session["csrf_token"],
                    "expires_at": session["expires_at"],
                },
                cookie,
            )
            return
        session = self._session()
        if self.command != "GET":
            if self.headers.get_all("X-CSRF-Token", []) != [session["csrf_token"]]:
                raise ControlError(403, "csrf_failed")
        if target.path == "/control/session" and not target.query and self.command == "DELETE":
            exact(self._body(), set())
            self.server.session = None
            self._reply(
                200,
                {"schema_version": 1, "revoked": True},
                "arena_control=; HttpOnly; SameSite=Strict; Path=/control; Max-Age=0",
            )
        elif target.path == "/control/research-services" and self.command == "GET":
            query = parse_qs(target.query, keep_blank_values=True, strict_parsing=True) if target.query else {}
            if set(query) - {"request_id"} or ("request_id" in query and len(query["request_id"]) != 1):
                raise ControlError(400, "invalid_request")
            self._reply(200, self.server.controller.observe(query.get("request_id", [None])[0], reuse=True))
        elif target.path == "/control/research-services/start" and not target.query and self.command == "POST":
            self._reply(202, self.server.controller.start(self._body()))
        else:
            raise ControlError(404, "not_found")

    def _handle(self):
        try:
            if self.command in {"POST", "DELETE", "PUT", "PATCH"}:
                # Drain a bounded valid body before rejecting credentials; otherwise
                # a header-first client can get EPIPE instead of the static error.
                self.body = self._body()
            self._dispatch()
        except ControlError as error:
            self._reply(error.status, {"error": error.code})
        except (ValueError, TypeError):
            self._reply(400, {"error": "invalid_request"})
        except Exception:
            self._reply(503, {"error": "control_unavailable"})

    do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = do_OPTIONS = do_HEAD = _handle


@contextmanager
def installed_server(home, docker=None, bootstrap=False):
    """Lease one installed helper, optionally bootstrap frontend, preserve unknown starts."""
    home = Path(home)
    installation = load_installation(home, authenticate_only=True)
    profile = installation["profile"]
    docker = docker or Docker(seconds=profile["limits"]["docker_seconds"])
    fd = os.open(home / "state/helper.lock", os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("helper_busy") from None
        load_installation(home, docker=docker)
        if bootstrap:
            prepare_api_storage(profile, create=True)
            bootstrap_frontend(home, profile, docker)

        def guard():
            current = load_installation(
                home, docker=docker, authenticate_only=profile["startup_review"]["mode"] == STARTUP_V2
            )
            if current != installation:
                raise ValueError("installation_changed")
            prepare_api_storage(profile, create=False)

        def adapter_guard(candidate):
            guard()
            if profile_revision(candidate) != installation["manifest"]["profile_revision"]:
                raise ValueError("installation_changed")

        docker.guard, docker.home = adapter_guard, home
        controller = Controller(profile, home / "state", docker, guard=guard, home=home)
        path = home / "ipc/control.sock"
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise ValueError("control_socket_ownership")
            with socket.socket(socket.AF_UNIX) as probe:
                probe.settimeout(1)
                try:
                    probe.connect(str(path))
                except ConnectionRefusedError:
                    pass
                else:
                    raise ValueError("control_socket_busy")
            if path.lstat() != info:
                raise ValueError("control_socket_changed")
            path.unlink()
        token = secrets.token_urlsafe(32)
        atomic_private(
            home / "pairing.json",
            {"pairing_token": token, "expires_at": time.time() + 300},
        )
        with ControlServer(str(path), controller, token) as server:
            path.chmod(0o660)
            inode = path.lstat()
            try:
                yield server
            finally:
                if path.exists() and path.lstat().st_ino == inode.st_ino and path.lstat().st_dev == inode.st_dev:
                    path.unlink()
                (home / "pairing.json").unlink(missing_ok=True)


def main(argv=None):
    """Install reviewed bytes, bootstrap cold frontend, or serve without starting services."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "bootstrap", "serve", "inspect"))
    parser.add_argument(
        "--home",
        type=Path,
        required=True,
        help="Operator-owned installation outside repository/eval mounts",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        help="Reviewed private mode-0600 operator profile (install only)",
    )
    parser.add_argument("--source-sha256", help="Independently reviewed control.py hash (install only)")
    args = parser.parse_args(argv)
    if args.action == "install":
        if not args.profile or not args.source_sha256:
            parser.error("install requires --profile and --source-sha256")
        installation = install(
            args.home,
            json.loads(private_file(args.profile)),
            Path(__file__),
            args.source_sha256,
        )
        print(
            json.dumps({
                "installed": True,
                "profile_revision": installation["manifest"]["profile_revision"],
            })
        )
        return
    if Path(__file__).resolve() != (args.home / "control.py").resolve():
        raise ValueError("run_installed_helper_with_python_isolated_mode")

    if args.action == "inspect":
        installation = load_installation(args.home)
        print(
            json.dumps({
                "schema_version": 1,
                "profile_revision": installation["manifest"]["profile_revision"],
                "expected_policy": installation["profile"]["expected_policy"],
            })
        )
        return
    with installed_server(args.home, bootstrap=args.action == "bootstrap") as server:
        stopping = threading.Event()
        previous = {sig: signal.signal(sig, lambda *_: stopping.set()) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            print(
                "Control ready; read the owner-private pairing.json within five minutes",
                flush=True,
            )
            server.timeout = 0.2
            while not stopping.is_set():
                server.handle_request()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, DockerFailure, TimeoutError) as error:
        # Directory prerequisite paths are operator-only; driver output is never printed.
        print(
            f"control: {error if isinstance(error, ValueError) else 'operation_unavailable'}",
            file=sys.stderr,
        )
        sys.exit(1)
