# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit foreground CLI; no ambient credentials, dynamic plugins or native startup.

Wire v1: run --config PROFILE --principal ID --operation-id ID CONTRACT;
status|cancel|resume --config PROFILE --principal ID RUN_ID. Optional private
--credentials-fd N supplies bounded JSON, never credentials on argv. The fixed
composition is isolated-synthetic-v1: capture is synthetic, NOT physical success.

Trusted factory contract: application_from_cli(config, credentials, *,
allow_startup=False) returns an application implementing run(principal,
operation_id, raw_contract), status/cancel/resume(principal, run_id), and close().
It must not resolve model grants, probe or start services in its constructor.
The application owns replay checks BEFORE execution readiness. Python callers
may inject a trusted factory for tests; JSON can never select Python code.
The default binding is the fixed sibling foreground_workflow module.

Profile JSON has exactly schema_version=1, composition='isolated-synthetic-v1',
database={uri,database,username}, deployment_id, workspace_id, artifact_root and
lease_root. Paths are explicit absolute paths; the profile is a singly-linked
owner-private regular file. It contains no passwords or model keys. Optional
credential input is a same-UID private pipe descriptor >=3, at most
128 KiB with a one-second read deadline. Persisted credential files are not read.
A descriptor is not a sandbox against
the same OS user, ptrace or a privileged host. The trusted single operator owns
the process and profile; --principal names that operator's workflow identity,
not an HTTP authentication mechanism. No ambient dotenv or credential discovery.

Inside the explicitly authorized isolated profile, use the installed interpreter:
  python -m isaaclab_arena_examples.agentic_environment_generation.foreground_workflow_cli run \\
    --config /private/profile.json --principal operator \\
    --operation-id exact-op /private/contract.json
  python -m isaaclab_arena_examples.agentic_environment_generation.foreground_workflow_cli status \\
    --config /private/profile.json --principal operator EXACT_RUN_ID
Replace status with cancel or resume for fresh application instances. Copy the
literal run_id from result, never normalize it. When credentials are necessary,
pass only --credentials-fd 3 and inherit a private pipe from the trusted launcher;
never put credential JSON in argv, shell history, environment or a config file.
The isolated fixture requires no real provider credentials. Production native
capture and broad installed-host startup remain unavailable at this milestone.

Supported isolated launcher: python3 scripts/run-workflow-neo4j-checks.py workflow-cli
It owns one bounded disposable DB/artifact scope and executes this module in fresh
interpreters for run/status/cancel/resume. Direct host execution has no admitted
bootstrap and honestly returns not_ready. No installed/native helper exists.

Public stdout is JSONL: a flushed {schema_version:1,event:"admitted",result:handle}
before execution effects, then {schema_version:1,result:publicdict}; errors use
{schema_version:1,error:STATIC_CODE}. No input or credentials appear in errors.
Exit mapping for ALL commands: accepted=0, invalid input=2, blocked/unknown/not
ready=3, denied=4, failed=5, stopped=6, cancelled=7. Nonterminal outcomes are 3.
This deliberately replaces the earlier command-handled=0 convention: clients
must parse each JSONL line and take the last result, not json.load(all_stdout).
Acceptance in this composition is synthetic, not native physical success.
The default prior receipt explicitly records unavailable/unconfigured fallback;
this launcher neither accesses nor claims retrieval from a research database.
Core workflow.cli remains only inspect-contract; execution imports flow from
this examples composition into core, never core into examples.
"""

import argparse
import contextlib
import json
import os
import re
import select
import stat
import time
from urllib.parse import urlsplit

from isaaclab_arena.agentic_environment_generation.inference_profiles import ModelProfileUnavailable

MAX_INPUT_BYTES = 131072
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid arguments")


def _read_file(path, *, private=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_INPUT_BYTES:
            raise ValueError("invalid file")
        if private and (metadata.st_uid != os.getuid() or metadata.st_mode & 0o077 or metadata.st_nlink != 1):
            raise ValueError("invalid private file")
        return os.read(fd, MAX_INPUT_BYTES + 1)
    finally:
        os.close(fd)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("oversized input")
    value = json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
    )
    if type(value) is not dict:
        raise ValueError("invalid object")
    # json.loads accepts exponent overflow as infinity despite parse_constant.
    json.dumps(value, allow_nan=False)
    return value


def _config(raw):
    value = _json(raw)
    expected = {
        "schema_version",
        "composition",
        "database",
        "deployment_id",
        "workspace_id",
        "artifact_root",
        "lease_root",
    }
    if set(value) != expected or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("invalid profile")
    if value["composition"] != "isolated-synthetic-v1":
        raise ValueError("unsupported composition")
    for key in ("deployment_id", "workspace_id"):
        if type(value[key]) is not str or not IDENTIFIER.fullmatch(value[key]):
            raise ValueError("invalid scope")
    for key in ("artifact_root", "lease_root"):
        if (
            type(value[key]) is not str
            or not os.path.isabs(value[key])
            or len(value[key]) > 4096
            or "\x00" in value[key]
        ):
            raise ValueError("invalid root")
    database = value["database"]
    if type(database) is not dict or set(database) != {"uri", "database", "username"}:
        raise ValueError("invalid database")
    for key in ("database", "username"):
        if type(database[key]) is not str or not IDENTIFIER.fullmatch(database[key]):
            raise ValueError("invalid database")
    if type(database["uri"]) is not str or len(database["uri"]) > 2048:
        raise ValueError("invalid database")
    uri = urlsplit(database["uri"])
    if (
        uri.scheme not in {"bolt", "bolt+s", "bolt+ssc"}
        or not uri.hostname
        or uri.username is not None
        or uri.password is not None
        or uri.path
        or uri.query
        or uri.fragment
        or uri.port is None
        or any(character.isspace() or ord(character) < 32 for character in database["uri"])
    ):
        raise ValueError("invalid database")
    return value


def _read_credentials(fd):
    if type(fd) is not int or fd < 3:
        raise ValueError("invalid descriptor")
    metadata = os.fstat(fd)
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise ValueError("descriptor not private")
    if not stat.S_ISFIFO(metadata.st_mode):
        raise ValueError("private pipe required")
    deadline, raw = time.monotonic() + 1.0, bytearray()
    while len(raw) <= MAX_INPUT_BYTES:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise ValueError("descriptor timeout")
        chunk = os.read(fd, min(8192, MAX_INPUT_BYTES + 1 - len(raw)))
        if not chunk:
            return _json(raw)
        raw.extend(chunk)
    raise ValueError("oversized input")


def _factory(config, credentials, *, allow_startup):
    from .foreground_workflow import application_from_cli

    return application_from_cli(config, credentials, allow_startup=allow_startup)


def outcome_exit(result):
    """Map workflow outcomes, not merely successful command dispatch."""
    return {
        "accepted": 0,
        "stopped": 6,
        "blocked": 3,
        "cancelled": 7,
        "failed": 5,
        "unknown": 3,
    }.get(result.get("state"), 3)


def _emit(value):
    print(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ),
        flush=True,
    )


def main(argv=None, *, application_factory=None):
    """Dispatch once through the shared application; errors never echo input."""
    parser = _Parser(prog="foreground-workflow", description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "status", "cancel", "resume"):
        sub = commands.add_parser(command, allow_abbrev=False)
        sub.add_argument("--config", required=True)
        sub.add_argument("--principal", required=True)
        sub.add_argument("--credentials-fd", type=int)
        if command == "run":
            sub.add_argument("--operation-id", required=True)
            sub.add_argument("--allow-startup", action="store_true", default=False)
            sub.add_argument("contract")
        else:
            sub.add_argument("run_id")
            if command == "resume":
                sub.add_argument("--renew-authorization", action="store_true", default=False)
    app = None
    try:
        options = parser.parse_args(argv)
        for value in (
            options.principal,
            options.operation_id if options.command == "run" else options.run_id,
        ):
            if not IDENTIFIER.fullmatch(value):
                raise ValueError("invalid identifier")
        config = _config(_read_file(options.config, private=True))
        credentials = {} if options.credentials_fd is None else _read_credentials(options.credentials_fd)
        raw = _read_file(options.contract) if options.command == "run" else None
    except SystemExit as error:
        return error.code
    except (OSError, ValueError, TypeError, RecursionError):
        _emit({"schema_version": 1, "error": "invalid_input"})
        return 2
    try:
        app = (application_factory or _factory)(
            config, credentials, allow_startup=getattr(options, "allow_startup", False)
        )
        if options.command in {"run", "resume"} and hasattr(app, "set_admission_listener"):
            app.set_admission_listener(
                lambda handle: _emit({"schema_version": 1, "event": "admitted", "result": handle})
            )
        if options.command == "run":
            result = app.run(options.principal, options.operation_id, raw)
        elif options.command == "resume" and options.renew_authorization:
            result = app.resume(options.principal, options.run_id, renew_authorization=True)
        else:
            result = getattr(app, options.command)(options.principal, options.run_id)
        if type(result) is not dict:
            raise RuntimeError("invalid application response")
        closing, app = app, None
        closing.close()
        _emit({"schema_version": 1, "result": result})
        return outcome_exit(result)
    except ModelProfileUnavailable:
        code, status = "model_profile_not_ready", 3
    except PermissionError:
        code, status = "denied", 4
    except (ConnectionError, TimeoutError, NotImplementedError):
        code, status = "not_ready", 3
    except Exception:
        code, status = "application_failed", 5
    finally:
        if app is not None:
            with contextlib.suppress(Exception):
                app.close()
        credentials.clear()
    _emit({"schema_version": 1, "error": code})
    return status


if __name__ == "__main__":
    raise SystemExit(main())
