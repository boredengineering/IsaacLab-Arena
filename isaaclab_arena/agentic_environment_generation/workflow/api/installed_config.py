# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Explicit installed configuration admission; no ambient credential discovery."""

import fcntl
import hashlib
import ipaddress
import os
import pwd
import re
import select
import stat
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .private_files import Directory, PrivateFileError, canonical_path, decode, encode, fields, read_private

MAX_CONFIG = 256 * 1024
MAX_CREDENTIALS = 128 * 1024


def text(value, limit):
    if (
        type(value) is not str
        or not 1 <= len(value.encode("utf-8")) <= limit
        or any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in value)
    ):
        raise PrivateFileError("Invalid configuration value")
    return value


def endpoint(value, *, bolt=False):
    text(value, 256)
    url = urlsplit(value)
    host = str(ipaddress.IPv4Address(url.hostname))
    scheme, path = ("bolt", "") if bolt else ("http", "/graphql")
    if (
        url.scheme != scheme
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or url.path != path
        or type(url.port) is not int
        or not 1 <= url.port <= 65535
        or value != f"{scheme}://{host}:{url.port}{path}"
        or not bolt
        and not ipaddress.IPv4Address(host).is_loopback
    ):
        raise PrivateFileError("Invalid numeric endpoint")
    return host, url.port


@dataclass(frozen=True)
class Config:
    path: str
    value: dict
    binding: object
    profiles: tuple
    digest: str


def load(path):
    """Validate explicit config without reading credentials or opening a database."""
    from ..profiles import MAX_PROFILE_REVISIONS, ProfileRevision
    from ..scope_binding import ScopeBinding

    canonical_path(path)
    value = fields(
        decode(read_private(path, MAX_CONFIG), MAX_CONFIG),
        "schema_version mode operator private_root credentials_file endpoint bolt_uri binding artifact_root"
        " required_profiles bootstrap_principal read_principal",
    )
    # Setup selection only, not execution authority or readiness. The installed
    # server still composes query-only resources; no synthetic owner is enabled.
    if (
        type(value["schema_version"]) is not int
        or type(value["mode"]) is not str
        or (value["schema_version"], value["mode"]) not in ((1, "query-only"), (2, "isolated-synthetic-execution-v1"))
    ):
        raise PrivateFileError("Unsupported configuration")
    operator = fields(value["operator"], "uid gid groups account home cwd")
    if (
        type(operator["uid"]) is not int
        or type(operator["gid"]) is not int
        or operator["uid"] != os.getuid()
        or operator["uid"] == 0
        or operator["gid"] != os.getgid()
        or type(operator["groups"]) is not list
        or len(operator["groups"]) > 64
        or any(type(g) is not int or g < 0 for g in operator["groups"])
        or operator["groups"] != sorted(set(os.getgroups()))
        or operator["account"] != pwd.getpwuid(os.getuid()).pw_name
        or operator["home"] != os.environ.get("HOME")
        or operator["cwd"] != os.getcwd()
    ):
        raise PrivateFileError("Operator configuration differs")
    for key in ("home", "cwd"):
        canonical_path(operator[key])
    checkout = Path(__file__).parents[3]
    for key in ("private_root", "credentials_file", "artifact_root"):
        canonical_path(value[key])
        if Path(value[key]).is_relative_to(checkout):
            raise PrivateFileError("Private path inside checkout")
    if Path(value["credentials_file"]) != Path(path).with_name("credentials.json"):
        raise PrivateFileError("Explicit sibling credential file required")
    endpoint(value["endpoint"])
    endpoint(value["bolt_uri"], bolt=True)
    text(value["bootstrap_principal"], 128)
    text(value["read_principal"], 128)
    if value["bootstrap_principal"] == value["read_principal"]:
        raise PrivateFileError("Distinct principals required")
    binding = ScopeBinding.model_validate_json(encode(value["binding"]))
    if type(value["required_profiles"]) is not list or len(value["required_profiles"]) > MAX_PROFILE_REVISIONS:
        raise PrivateFileError("Invalid required profiles")
    profiles = tuple(ProfileRevision.model_validate_json(encode(p)) for p in value["required_profiles"])
    if len({(p.profile_id, p.revision) for p in profiles}) != len(profiles):
        raise PrivateFileError("Duplicate profile identity")
    return Config(path, value, binding, profiles, hashlib.sha256(encode(value)).hexdigest())


def credential_document(raw):
    value = fields(decode(raw, MAX_CREDENTIALS), "schema_version databases")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise PrivateFileError("Unsupported credentials")
    databases = fields(value["databases"], "operational")
    operational = fields(databases["operational"], "scheme username password")
    if operational["scheme"] != "basic":
        raise PrivateFileError("Unsupported credentials")
    text(operational["username"], 256)
    text(operational["password"], 4096)
    return value


def input_credentials(fd):
    """Read only an explicitly supplied private anonymous pipe through EOF."""
    if type(fd) is not int or fd < 3:
        raise PrivateFileError("Private credential pipe required")
    info = os.fstat(fd)
    if (
        not stat.S_ISFIFO(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.getuid()
        or info.st_gid != os.getgid()
        or fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
        or not re.fullmatch(r"pipe:\[[0-9]+\]", os.readlink(f"/proc/self/fd/{fd}"))
    ):
        raise PrivateFileError("Private credential pipe required")
    data = bytearray()
    deadline = time.monotonic() + 5
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise PrivateFileError("Credential input incomplete")
        chunk = os.read(fd, min(65536, MAX_CREDENTIALS + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_CREDENTIALS:
            raise PrivateFileError("Credential input too large")
    return credential_document(bytes(data))


def change_credentials(config, *, remove, credential_fd=None):
    """Explicit serialized update/removal; failed directory sync stays unknown."""
    if type(remove) is not bool:
        raise ValueError("Explicit credential operation required")
    value = None if remove else input_credentials(credential_fd)
    target = Path(config.value["credentials_file"])
    with Directory(str(target.parent)) as directory, directory.lease("credentials.lock"):
        fd = directory.open_file(target.name)
        os.close(fd)
        if remove:
            directory.check()
            os.unlink(target.name, dir_fd=directory.fd)
            os.fsync(directory.fd)
        else:
            directory.write(target.name, encode(value), replace=True)
    return {"schema_version": 1, "code": "credentials_removed" if remove else "credentials_updated"}


def setup(config, credential_fd):
    credential = input_credentials(credential_fd)
    target = Path(config.value["credentials_file"])
    with Directory(str(target.parent)) as directory, directory.lease("credentials.lock"):
        with Directory(config.value["private_root"], create=True):
            pass
        directory.write(target.name, encode(credential))
    return {"schema_version": 1, "code": "setup_complete"}
