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
import secrets
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
    value = decode(read_private(path, MAX_CONFIG), MAX_CONFIG)
    fields(
        value,
        "schema_version mode operator private_root credentials_file endpoint bolt_uri binding artifact_root"
        " required_profiles bootstrap_principal read_principal"
        + (" role_bindings" if type(value) is dict and value.get("schema_version") == 3 else "")
        + (" native_validation" if type(value) is dict and value.get("schema_version") == 4 else ""),
    )
    # Setup selection is never readiness or execution authority. V3 adds explicit
    # private roles, not a production mode or an exemption from the harness guard.
    if (
        type(value["schema_version"]) is not int
        or type(value["mode"]) is not str
        or (value["schema_version"], value["mode"])
        not in (
            (1, "query-only"),
            (2, "isolated-synthetic-execution-v1"),
            (3, "query-only"),
            (3, "isolated-synthetic-execution-v1"),
            (4, "retained-native-validation-v1"),
        )
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
    if value["schema_version"] == 3:
        validate_role_bindings(value["role_bindings"], profiles)
    elif value["schema_version"] == 4:
        from .installed_native import NativeSelection

        NativeSelection.model_validate_json(encode(value["native_validation"]))
        if profiles:
            raise PrivateFileError("Native-only setup cannot select model profiles")
    return Config(path, value, binding, profiles, hashlib.sha256(encode(value)).hexdigest())


def alias(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise PrivateFileError("Invalid credential alias")
    return value


def validate_role_bindings(value, profiles):
    """Validate explicit public pins without credentials, providers or database IO."""
    from ..profiles import ProfileRegistration, profile_revision
    from ..provider_configuration import ENDPOINTS

    fields(value, "generation assessment repair prior_read")
    for role in ("generation", "assessment", "repair"):
        row = fields(value[role], "credential_alias profile")
        alias(row["credential_alias"])
        profile = ProfileRegistration.model_validate_json(encode(row["profile"]))
        if (
            profile.kind != "model"
            or profile_revision(profile) not in profiles
            or profile.settings.endpoint not in ENDPOINTS.values()
            or ("generation_model" if role == "repair" else role + "_model") not in profile.roles
        ):
            raise PrivateFileError("Unsupported role profile")
    # The current workflow contract pins repair to its generation model. Require
    # explicit sharing rather than silently selecting a separate unbound model/key.
    if value["repair"] != value["generation"]:
        raise PrivateFileError("Repair requires explicit generation binding")
    prior = fields(value["prior_read"], "credential_alias endpoint database authentication")
    alias(prior["credential_alias"])
    endpoint(prior["endpoint"], bolt=True)
    text(prior["database"], 128)
    if prior["authentication"] != "basic":
        raise PrivateFileError("Unsupported prior authentication")


def credential_document(raw, *, input_document=False):
    value = decode(raw, MAX_CREDENTIALS)
    if type(value) is not dict or type(value.get("schema_version")) is not int or value["schema_version"] not in (1, 2):
        raise PrivateFileError("Unsupported credentials")
    fields(
        value,
        "schema_version databases"
        + (" models" + ("" if input_document else " generation") if value["schema_version"] == 2 else ""),
    )
    databases = value["databases"]
    if type(databases) is not dict or not {"operational"} <= set(databases) <= (
        {"operational", "prior_read"} if value["schema_version"] == 2 else {"operational"}
    ):
        raise PrivateFileError("Unsupported database credentials")
    operational = fields(databases["operational"], "scheme username password")
    if operational["scheme"] != "basic":
        raise PrivateFileError("Unsupported credentials")
    text(operational["username"], 256)
    text(operational["password"], 4096)
    if value["schema_version"] == 2:
        if not input_document and (
            type(value["generation"]) is not str or not re.fullmatch(r"[a-f0-9]{32}", value["generation"])
        ):
            raise PrivateFileError("Invalid credential generation")
        models = value["models"]
        if type(models) is not dict or not set(models) <= {"generation", "assessment", "repair"}:
            raise PrivateFileError("Unsupported model credentials")
        aliases = {}
        for item in models.values():
            fields(item, "alias api_key")
            alias(item["alias"])
            text(item["api_key"], 4096)
            if len(item["api_key"]) < 16 or any(ord(c) < 33 or ord(c) > 126 for c in item["api_key"]):
                raise PrivateFileError("Invalid private model credential")
            if aliases.setdefault(item["alias"], item["api_key"]) != item["api_key"]:
                raise PrivateFileError("Shared credential alias differs")
        if "prior_read" in databases:
            prior = fields(databases["prior_read"], "alias scheme username password")
            alias(prior["alias"])
            if prior["scheme"] != "basic" or prior["alias"] in aliases:
                raise PrivateFileError("Unsupported prior credentials")
            text(prior["username"], 256)
            text(prior["password"], 4096)
    return value


def prepare_credentials(config, value):
    """Bind supplied private roles and issue a nonsecret revision, never a grant."""
    from ..provider_configuration import reject_secret

    if config.value["schema_version"] == 3:
        if value["schema_version"] != 2:
            raise PrivateFileError("Versioned private roles required")
        selected = config.value["role_bindings"]
        for role, item in value["models"].items():
            if item["alias"] != selected[role]["credential_alias"]:
                raise PrivateFileError("Private role binding differs")
            reject_secret(config.value, item["api_key"])
        prior = value["databases"].get("prior_read")
        if prior is not None:
            if prior["alias"] != selected["prior_read"]["credential_alias"]:
                raise PrivateFileError("Private prior binding differs")
            reject_secret(config.value, prior["password"])
            reject_secret(config.value, prior["username"])
    elif config.value["schema_version"] == 4:
        if value["schema_version"] != 2 or value["models"] or set(value["databases"]) != {"operational"}:
            raise PrivateFileError("Native-only setup requires only the operational database binding")
    elif value["schema_version"] != 1:
        raise PrivateFileError("Explicit role configuration required")
    if value["schema_version"] == 2:
        value = {**value, "generation": secrets.token_hex(16)}
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
    return credential_document(bytes(data), input_document=True)


def change_credentials(config, *, remove, credential_fd=None):
    """Explicit serialized update/removal; failed directory sync stays unknown."""
    if type(remove) is not bool:
        raise ValueError("Explicit credential operation required")
    value = None if remove else prepare_credentials(config, input_credentials(credential_fd))
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
    return {
        "schema_version": 1,
        "code": "credentials_removed" if remove else "credentials_updated",
        **(
            {"execution_authorized": False, "credential_generation": value["generation"]}
            if value is not None and value["schema_version"] == 2
            else {}
        ),
    }


def setup(config, credential_fd):
    credential = prepare_credentials(config, input_credentials(credential_fd))
    target = Path(config.value["credentials_file"])
    with Directory(str(target.parent)) as directory, directory.lease("credentials.lock"):
        with Directory(config.value["private_root"], create=True):
            pass
        directory.write(target.name, encode(credential))
    return {
        "schema_version": 1,
        "code": "setup_complete",
        **(
            {"execution_authorized": False, "credential_generation": credential["generation"]}
            if credential["schema_version"] == 2
            else {}
        ),
    }
