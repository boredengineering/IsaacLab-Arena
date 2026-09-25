# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Exact local instance lifetime, not workflow ownership or a process supervisor."""

import fcntl
import os
import re
import select
import socket
import stat
import struct
import subprocess
import sys
import time
from pathlib import Path

from .private_files import Directory, decode, encode, fields

PUBLIC = ["schema_version", "instance", "config_sha256", "binding_sha256", "endpoint", "generation", "state", "code"]
STATES = {"launching", "ready", "stopping", "stopped", "failed", "exited_unclean"}
MODULE = "isaaclab_arena.agentic_environment_generation.workflow.cli"
EXECUTION_MODES = {"isolated-synthetic-execution-v1", "retained-native-validation-v1"}


def instance_id(value):
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{32}", value) is None:
        raise ValueError("Invalid instance")
    return value


def identity(pid):
    if type(pid) is not int or not 1 <= pid <= 2147483647:
        raise ValueError("Invalid process")
    with open(f"/proc/{pid}/stat", "rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("Unknown process identity")
    parts = raw.decode().rsplit(")", 1)[1].split()
    return {
        "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "pid": pid,
        "start_ticks": int(parts[19]),
        "pgid": int(parts[2]),
        "sid": int(parts[3]),
        "namespace": os.readlink(f"/proc/{pid}/ns/pid"),
        "state": parts[0],
    }


def same_process(expected):
    fields(expected, "boot pid start_ticks pgid sid namespace")
    if any(type(expected[key]) is not int or expected[key] <= 0 for key in ("pid", "start_ticks", "pgid", "sid")):
        raise ValueError("Unknown process identity")
    try:
        current = identity(expected["pid"])
    except FileNotFoundError:
        return False
    state = current.pop("state")
    return current == expected and state not in {"Z", "X"}


def instance_path(config, selected):
    instance_id(selected)
    return config.value["private_root"] + "/instances/" + selected


def state(config, selected):
    with Directory(instance_path(config, selected)) as directory:
        value = decode(directory.read("state.json", 16384), 16384)
        extra = " capabilities" if config.value["mode"] in EXECUTION_MODES and "capabilities" in value else ""
        result = fields(value, " ".join(PUBLIC) + " identity" + extra)
        if extra:
            legacy = {"mode": "isolated-synthetic-execution-v1", "submit": True, "required_policy": False}
            allowed = (
                legacy,
                {**legacy, "cancel": True},
                {**legacy, "cancel": True, "resume": True},
            )
            if config.value["mode"] == "retained-native-validation-v1":
                from .installed_native import CAPABILITIES

                allowed = (CAPABILITIES,)
            if result["capabilities"] not in allowed:
                raise ValueError("Execution capability binding differs")
    if (
        type(result["schema_version"]) is not int
        or result["schema_version"] != 1
        or result["instance"] != selected
        or result["config_sha256"] != config.digest
        or result["binding_sha256"] != config.binding.body_sha256
        or result["endpoint"] != config.value["endpoint"]
        or type(result["generation"]) is not int
        or result["generation"] != 1
        or result["state"] not in STATES
        or result["code"]
        not in (
            {"launch_pending", "ready", "stop_requested", "drained", "startup_failed", "exited_unclean"}
            | ({"cleanup_unknown"} if config.value["mode"] in EXECUTION_MODES else set())
        )
    ):
        raise ValueError("Instance binding differs")
    return result


def save_state(config, selected, value):
    with Directory(config.value["private_root"]) as root, root.lease("metadata.lock"):
        current = decode(root.read("current.json", 4096), 4096)
        if current != {"schema_version": 1, "instance": selected, "config_sha256": config.digest}:
            raise ValueError("Instance replaced")
        with Directory(instance_path(config, selected)) as directory:
            prior = state(config, selected)
            if prior["identity"] != value["identity"]:
                raise ValueError("Instance identity differs")
            directory.write("state.json", encode(value), replace=True)


def receipt(value, *, code=None):
    result = {key: value[key] for key in PUBLIC}
    if "capabilities" in value:
        result["capabilities"] = dict(value["capabilities"])
    if code is not None:
        result["code"] = code
    return result


def released(config):
    with Directory(config.value["private_root"]) as root:
        try:
            with root.lease("lifetime.lock"):
                return True
        except BlockingIOError:
            return False


def _frame(sock, deadline):
    data = bytearray()
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Control observation incomplete")
        sock.settimeout(remaining)
        part = sock.recv(4097 - len(data))
        if not part:
            raise ValueError("Control observation incomplete")
        data.extend(part)
        if len(data) > 4096:
            raise ValueError("Control frame rejected")
    if data[-1:] != b"\n" or data.count(b"\n") != 1:
        raise ValueError("Control frame rejected")
    return decode(bytes(data), 4096)


def control(config, selected, operation, known):
    if operation not in {"status", "stop"} or known["identity"] is None or not same_process(known["identity"]):
        raise ValueError("Unknown control identity")
    with Directory(instance_path(config, selected)) as directory:
        info = os.stat("control.sock", dir_fd=directory.fd, follow_symlinks=False)
        if (
            not stat.S_ISSOCK(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or info.st_gid != os.getgid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise ValueError("Untrusted control endpoint")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            deadline = time.monotonic() + 5
            sock.settimeout(5)
            sock.connect(f"/proc/self/fd/{directory.fd}/control.sock")
            pid, uid, _ = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != os.getuid() or pid != known["identity"]["pid"] or not same_process(known["identity"]):
                raise PermissionError("Control peer differs")
            directory.check()
            after = os.stat("control.sock", dir_fd=directory.fd, follow_symlinks=False)
            if (info.st_dev, info.st_ino) != (after.st_dev, after.st_ino):
                raise PermissionError("Control endpoint changed")
            request = {"v": 1, "op": operation, "instance": selected, "config_sha256": config.digest}
            sock.sendall(encode(request) + b"\n")
            answer = fields(_frame(sock, deadline), "v instance state code")
            if (
                type(answer["v"]) is not int
                or answer["v"] != 1
                or answer["instance"] != selected
                or answer["state"] not in STATES
                or answer["code"]
                not in (
                    {"ready", "launch_pending", "stop_requested"}
                    | ({"cleanup_unknown"} if config.value["mode"] in EXECUTION_MODES else set())
                )
            ):
                raise ValueError("Control response rejected")
            return answer


def observe(config, selected, *, stop=False, reconcile=False):
    instance_id(selected)
    known = state(config, selected)
    if known["identity"] is None:
        return receipt(known, code="unknown"), 3
    alive = same_process(known["identity"])
    if not alive:
        if not released(config):
            return receipt(known, code="unknown"), 3
        if known["state"] == "stopped" and known["code"] == "drained":
            return receipt(known), 0
        if known["state"] == "failed":
            return receipt(known), 2
        if reconcile:
            known.update(state="exited_unclean", code="exited_unclean")
            save_state(config, selected, known)
        return receipt(known, code="exited_unclean"), 3
    try:
        answer = control(config, selected, "stop" if stop else "status", known)
    except (OSError, ValueError):
        return receipt(known, code="unknown"), 3
    known.update(state=answer["state"], code=answer["code"])
    if known["code"] == "cleanup_unknown":
        return receipt(known), 3
    if not stop:
        return receipt(known), 0 if known["state"] == "ready" else 3
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        known = state(config, selected)
        if known["code"] == "cleanup_unknown":
            return receipt(known), 3
        if not same_process(known["identity"]) and released(config):
            return receipt(known), 0 if known["state"] == "stopped" and known["code"] == "drained" else 3
        time.sleep(0.05)
    return receipt(known, code="unknown"), 3


def launch(config, selected, *, previous_config=None, previous_instance=None, native_authorized=False):
    """Launch a fresh instance, or explicitly hand over an exactly drained configuration."""
    from .installed_config import MAX_CONFIG

    instance_id(selected)
    transition = None
    native = config.value["mode"] == "retained-native-validation-v1"
    if type(native_authorized) is not bool or native_authorized != native:
        raise ValueError("Separate native approval must match the selected mode")
    if previous_config is not None or previous_instance is not None:
        instance_id(previous_instance)
        if previous_config is None or selected == previous_instance or config.digest == previous_config.digest:
            raise ValueError("Distinct checked configurations and instances required")
        unchanged = (
            "private_root",
            "credentials_file",
            "bolt_uri",
            "binding",
            "artifact_root",
            "operator",
            "bootstrap_principal",
            "read_principal",
        )
        if any(config.value[key] != previous_config.value[key] for key in unchanged):
            raise ValueError("Handover cannot change durable scope or private roots")
        transition = dict(
            schema_version=1,
            previous_instance=previous_instance,
            previous_config_sha256=previous_config.digest,
            instance=selected,
            config_sha256=config.digest,
        )
        # A retry of the same consumed transition only observes its exact target.
        with Directory(config.value["private_root"]) as root, root.lease("metadata.lock"):
            current = decode(root.read("current.json", 4096), 4096)
            replay = current == dict(schema_version=1, instance=selected, config_sha256=config.digest)
            if replay:
                with Directory(instance_path(config, selected)) as directory:
                    if decode(directory.read("handover.json", 4096), 4096) != transition:
                        raise ValueError("Handover replay differs")
        if replay:
            return observe(config, selected)
    with (
        Directory(config.value["private_root"]) as root,
        root.lease("metadata.lock"),
        root.lease("lifetime.lock") as lifetime,
    ):
        with Directory(root.path + "/instances", create=True):
            pass
        try:
            current = decode(root.read("current.json", 4096), 4096)
        except FileNotFoundError:
            current = None
        if current is not None:
            fields(current, "schema_version instance config_sha256")
            if transition is not None and current != dict(
                schema_version=1, instance=previous_instance, config_sha256=previous_config.digest
            ):
                raise ValueError("Previous configuration intent differs")
            prior_config = config if transition is None else previous_config
            prior = state(prior_config, instance_id(current["instance"]))
            if (
                prior["identity"] is None
                or same_process(prior["identity"])
                or prior["state"] not in {"stopped", "failed", "exited_unclean"}
            ):
                raise ValueError("Prior instance unresolved")
            if transition is not None:
                if prior["state"] != "stopped" or prior["code"] != "drained":
                    raise ValueError("Prior cleanup unresolved; recover using the previous configuration")
                with Directory(instance_path(previous_config, previous_instance)) as directory:
                    if decode(directory.read("configuration.json", MAX_CONFIG), MAX_CONFIG) != previous_config.value:
                        raise ValueError("Retained previous configuration differs")
        elif transition is not None:
            raise ValueError("Previous instance required")
        location = instance_path(config, selected)
        # A consumed directory is a permanent tombstone, including failed launches.
        with Directory(root.path + "/instances") as instances:
            previous = os.umask(0o077)
            try:
                os.mkdir(selected, 0o700, dir_fd=instances.fd)
            finally:
                os.umask(previous)
            with Directory(location) as new:
                os.fchmod(new.fd, 0o700)
                os.fsync(new.fd)
            os.fsync(instances.fd)
        initial = dict(
            schema_version=1,
            instance=selected,
            config_sha256=config.digest,
            binding_sha256=config.binding.body_sha256,
            endpoint=config.value["endpoint"],
            generation=1,
            state="launching",
            code="launch_pending",
            identity=None,
        )
        with Directory(location) as directory:
            directory.write("configuration.json", encode(config.value))
            if transition is not None:
                directory.write("handover.json", encode(transition))
            directory.write("state.json", encode(initial))
        root.write(
            "current.json",
            encode({"schema_version": 1, "instance": selected, "config_sha256": config.digest}),
            replace=current is not None,
        )
        gate, release = os.pipe2(os.O_CLOEXEC)
        os.fchmod(gate, 0o600)
        pidfd = None
        try:
            executable = sys.executable
            arguments = [
                executable,
                "-m",
                MODULE,
                "api-serve",
                "--config",
                config.path,
                "--instance",
                selected,
                "--lease-fd",
                str(lifetime),
                "--gate-fd",
                str(gate),
            ]
            operator = config.value["operator"]
            child_environment = {"HOME": operator["home"], "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
            if native:
                from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import (
                    worker_environment,
                )

                arguments.append("--authorize-native")
                child_environment.update(worker_environment(None))
                for key in ("EXP_PATH", "ISAAC_PATH", "CARB_APP_PATH"):
                    if key in os.environ:
                        child_environment[key] = os.environ[key]
                child_environment["OMNICLIENT_HUB_MODE"] = "disabled"
            child = subprocess.Popen(
                arguments,
                executable=executable,
                cwd=operator["cwd"],
                env=child_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                close_fds=True,
                pass_fds=(lifetime, gate),
                start_new_session=True,
                text=False,
            )
            captured = identity(child.pid)
            if (
                captured.pop("state") in {"Z", "X"}
                or captured["pid"] != captured["pgid"]
                or captured["pid"] != captured["sid"]
            ):
                raise ValueError("Detached process identity unavailable")
            pidfd = os.pidfd_open(child.pid)
            if not same_process(captured):
                raise ValueError("Detached process identity changed")
            initial["identity"] = captured
            with Directory(location) as directory:
                directory.write("state.json", encode(initial), replace=True)
            os.write(release, b"1")
        finally:
            os.close(gate)
            os.close(release)
            if pidfd is not None:
                os.close(pidfd)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        known = state(config, selected)
        if known["state"] == "ready":
            return observe(config, selected)
        if not same_process(initial["identity"]):
            return observe(config, selected)
        time.sleep(0.05)
    return receipt(known, code="unknown"), 3


def validate_gate(config, selected, lifetime, gate):
    """Reject ungated serve before credential/DB/listener effects."""
    if type(lifetime) is not int or type(gate) is not int or min(lifetime, gate) < 3 or lifetime == gate:
        raise ValueError("Inherited startup capabilities required")
    with Directory(config.value["private_root"]) as root:
        fd = root.open_file("lifetime.lock")
        try:
            expected, actual = os.fstat(fd), os.fstat(lifetime)
            if (expected.st_dev, expected.st_ino) != (actual.st_dev, actual.st_ino):
                raise ValueError("Inherited lease differs")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise ValueError("Lifetime lease is not held")
        finally:
            os.close(fd)
        info = os.fstat(gate)
        if (
            not stat.S_ISFIFO(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or not re.fullmatch(r"pipe:\[[0-9]+\]", os.readlink(f"/proc/self/fd/{gate}"))
        ):
            raise ValueError("Invalid startup gate")
        if not select.select([gate], [], [], 5)[0] or os.read(gate, 2) != b"1":
            raise ValueError("Startup gate closed")
        os.close(gate)
        current = decode(root.read("current.json", 4096), 4096)
        if current != {"schema_version": 1, "instance": selected, "config_sha256": config.digest}:
            raise ValueError("Launch intent differs")
        known = state(config, selected)
        own = identity(os.getpid())
        own.pop("state")
        if known["state"] != "launching" or known["identity"] != own:
            raise ValueError("Launch process differs")
        fcntl.flock(lifetime, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return known
