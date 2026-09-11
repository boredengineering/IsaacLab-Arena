#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Discover and manage the clone-local workbench without managing dependencies."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
LOCAL_ROOT = HERE.parent.parent


def run(command, **kwargs):
    """Run an argv command without a shell or implicit credential-file loading."""
    return subprocess.run(command, check=True, text=True, capture_output=True, **kwargs).stdout.strip()


def docker_records():
    """Read only Docker identity, mount and state metadata; never Config.Env."""
    ids = run(["docker", "ps", "-aq"]).split()
    if not ids:
        raise RuntimeError("No existing containers; start the approved Arena runtime separately")
    template = (
        '{"Id":{{json .Id}},"Name":{{json .Name}},"Running":{{json .State.Running}},'
        '"User":{{json .Config.User}},"Mounts":{{json .Mounts}},'
        '"NetworkMode":{{json .HostConfig.NetworkMode}}}'
    )
    return [json.loads(line) for line in run(["docker", "inspect", "--format", template, *ids]).splitlines()]


def resolve_host_root(local_root, containers):
    """Resolve a host clone or a uniquely mapped nested editor clone."""
    local = PurePosixPath(local_root)
    candidates = set()
    for container in containers:
        if not container.get("Running", True):
            continue
        for mount in container["Mounts"]:
            if mount["Type"] != "bind":
                continue
            source = PurePosixPath(mount["Source"])
            destination = PurePosixPath(mount["Destination"])
            if local == source:
                candidates.add(str(source))
            if local.is_relative_to(destination):
                candidates.add(str(source / local.relative_to(destination)))
    if len(candidates) != 1:
        raise RuntimeError("Host clone mapping absent or ambiguous; supply --host-root explicitly")
    return candidates.pop()


def resolve_identity(passwd, sim_gid, requested_user, requested_gid):
    """Select one normal non-root account and the simulator's access group."""
    accounts = [line.split(":") for line in passwd.splitlines() if len(line.split(":")) == 7]
    if requested_user is not None:
        candidates = [a for a in accounts if requested_user in (a[0], a[2])]
    else:
        candidates = [
            a
            for a in accounts
            if 1000 <= int(a[2]) < 60000 and a[5].startswith("/home/") and a[6].endswith(("/sh", "/bash", "/zsh"))
        ]
    if len(candidates) != 1:
        raise RuntimeError("API account absent or ambiguous; supply --api-user")
    account = candidates[0]
    uid, gid = int(account[2]), int(requested_gid if requested_gid is not None else sim_gid)
    if uid <= 0 or gid <= 0:
        raise RuntimeError("API must use a non-root UID and GID")
    return account[0], uid, gid


def api_command(state, socket_path, origin, diagnostics):
    """Return the explicitly approved, UDS-only API entry point."""
    command = [
        "/isaac-sim/python.sh",
        "-m",
        "isaaclab_arena_examples.agentic_environment_generation.web_api",
        "--state-dir",
        state,
        "--socket",
        socket_path,
        "--origin",
        origin,
    ]
    if diagnostics:
        command.append("--diagnostics")
    return command


def validate_port(port):
    """Reject invalid published port values before any state change."""
    if not 1 <= port <= 65535:
        raise RuntimeError("HTTP port must be between 1 and 65535")
    return port


def discover(args):
    """Resolve the actual clone, existing runtime, access identity and narrow mounts."""
    records = docker_records()
    host_root = args.host_root or resolve_host_root(str(LOCAL_ROOT), records)
    if not host_root.startswith("/") or ".." in PurePosixPath(host_root).parts:
        raise RuntimeError("--host-root must be an absolute canonical host path")
    candidates = []
    for record in records:
        mounts = [m for m in record["Mounts"] if m["Type"] == "bind" and m["Source"] == host_root]
        if not mounts:
            continue
        if args.runtime:
            if args.runtime not in (record["Name"].lstrip("/"), record["Id"]):
                continue
            if not record["Running"]:
                raise RuntimeError("Selected Arena runtime is stopped; start it explicitly outside this launcher")
        elif not record["Running"]:
            continue
        try:
            run(["docker", "exec", "--user", "65534:65534", record["Id"], "test", "-e", "/isaac-sim/python.sh"])
        except subprocess.CalledProcessError:
            continue
        if len(mounts) != 1:
            raise RuntimeError("Clone has multiple destinations in the runtime; ambiguous workdir")
        candidates.append((record, mounts[0]["Destination"]))
    if len(candidates) != 1:
        raise RuntimeError(
            "No unique running Arena runtime for this clone; use --runtime with an exact name/ID. "
            "Stopped dependencies are never started automatically"
        )
    runtime, repo = candidates[0]
    eval_mounts = [m for m in runtime["Mounts"] if m["Destination"] == "/eval" and m["Type"] == "bind" and m.get("RW")]
    if len(eval_mounts) != 1:
        raise RuntimeError("Runtime requires a writable host bind at /eval; configure it separately")
    probe = ["docker", "exec", "--user", "65534:65534", runtime["Id"]]
    passwd = run([*probe, "getent", "passwd"])
    sim_gid = run([*probe, "stat", "-c", "%g", "/isaac-sim"])
    user, uid, gid = resolve_identity(passwd, sim_gid, args.api_user, args.api_gid)
    identity = f"{user}:{gid}"
    run(["docker", "exec", "--user", identity, runtime["Id"], "test", "-x", "/isaac-sim/python.sh"])
    frontend_uid = args.frontend_uid if args.frontend_uid is not None else uid
    frontend_gid = args.frontend_gid if args.frontend_gid is not None else gid
    if frontend_uid <= 0 or frontend_gid <= 0:
        raise RuntimeError("Frontend must use a non-root numeric UID and GID")
    clone_id = hashlib.sha256(host_root.encode()).hexdigest()[:12]
    relative = f".wb/{clone_id}"
    base = f"/eval/{relative}"
    socket_path = f"{base}/ipc/api.sock"
    if len(socket_path.encode()) >= 104:
        raise RuntimeError("Unix socket path is too long")
    port = validate_port(args.port)
    origin = f"http://127.0.0.1:{port}"
    return {
        "host_root": host_root,
        "local_root": str(LOCAL_ROOT),
        "runtime": runtime["Id"],
        "runtime_name": runtime["Name"].lstrip("/"),
        "runtime_repo": repo,
        "runtime_network": runtime["NetworkMode"],
        "api_user": identity,
        "api_uid": uid,
        "api_gid": gid,
        "frontend_uid": frontend_uid,
        "frontend_gid": frontend_gid,
        "port": port,
        "origin": origin,
        "project": f"arena-wb-{clone_id}",
        "state": f"{base}/state",
        "socket": socket_path,
        "ipc_host": str(PurePosixPath(eval_mounts[0]["Source"]) / relative / "ipc"),
        "state_host": str(PurePosixPath(eval_mounts[0]["Source"]) / relative / "state"),
        "diagnostics": args.diagnostics,
        "dev": args.dev,
        "api_command": api_command(f"{base}/state", socket_path, origin, args.diagnostics),
    }


def compose(config, *command):
    """Run only this clone's frontend project; disable implicit .env reads."""
    env = dict(os.environ)
    env.update({
        "COMPOSE_DISABLE_ENV_FILE": "true",
        "WORKBENCH_BUILD_CONTEXT": str(LOCAL_ROOT),
        "WORKBENCH_SOURCE_HOST": config["host_root"] + "/web/arena-workbench",
        "WORKBENCH_IPC_HOST": config["ipc_host"],
        "WORKBENCH_HTTP_PORT": str(config["port"]),
        "FRONTEND_UID": str(config["frontend_uid"]),
        "FRONTEND_GID": str(config["frontend_gid"]),
        "API_GID": str(config["api_gid"]),
    })
    argv = ["docker", "compose", "--env-file", "/dev/null", "-p", config["project"], "-f", str(HERE / "compose.yaml")]
    if config["dev"]:
        argv += ["-f", str(HERE / "compose.dev.yaml")]
    return run([*argv, *command], env=env)


def runtime_call(config, action, detached=False):
    """Execute the small stdlib supervisor as the discovered non-root API user."""
    argv = ["docker", "exec"]
    if detached:
        argv.append("--detach")
    argv += [
        "--user",
        config["api_user"],
        "-w",
        config["runtime_repo"],
        config["runtime"],
        "/isaac-sim/python.sh",
        config["runtime_repo"] + "/docker/workbench/runtime.py",
        action,
        "--state-dir",
        config["state"],
        "--socket",
        config["socket"],
        "--origin",
        config["origin"],
    ]
    if config["diagnostics"]:
        argv.append("--diagnostics")
    if action == "preflight" and config["runtime_network"] == "host":
        argv += ["--port", str(config["port"])]
    return run(argv)


@contextmanager
def operation_lock(config):
    """Hold the runtime's filesystem lock until the host operation finishes."""
    argv = [
        "docker",
        "exec",
        "-i",
        "--user",
        config["api_user"],
        "-w",
        config["runtime_repo"],
        config["runtime"],
        "/isaac-sim/python.sh",
        config["runtime_repo"] + "/docker/workbench/runtime.py",
        "lock",
        "--state-dir",
        config["state"],
        "--socket",
        config["socket"],
        "--origin",
        config["origin"],
    ]
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    finished = threading.Event()

    def keepalive():
        while not finished.wait(2):
            try:
                process.stdin.write("KEEPALIVE\n")
                process.stdin.flush()
            except (BrokenPipeError, ValueError):
                return

    thread = threading.Thread(target=keepalive, daemon=True)
    try:
        if process.stdout.readline().strip() != "READY":
            raise RuntimeError(process.stderr.read().strip() or "Could not acquire workbench operation lock")
        thread.start()
        yield
    finally:
        finished.set()
        if thread.ident:
            thread.join(timeout=3)
        if process.poll() is None:
            try:
                process.stdin.write("RELEASE\n")
                process.stdin.flush()
            except BrokenPipeError:
                pass
        process.stdin.close()
        process.wait(timeout=10)
        process.stdout.close()
        process.stderr.close()


def main():
    """Expose read-only inspect/config/status and explicit start/stop lifecycle."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "inspect/config/status do not launch services. start launches only the frontend and UDS API; "
            "stop stops this clone's frontend and verified workbench-owned API supervisor, never Arena/Neo4j/GR00T. "
            "Run with the same identity/port/dev options for each lifecycle command. No .env files are read."
        ),
    )
    parser.add_argument("action", choices=["inspect", "config", "start", "status", "stop"])
    parser.add_argument("--runtime", help="Exact existing Arena container name or full ID")
    parser.add_argument("--host-root", help="Canonical host clone path if mount discovery is ambiguous")
    parser.add_argument("--api-user", help="Existing non-root account name or UID (default: unique /home account)")
    parser.add_argument("--api-gid", type=int, help="Simulator access/socket group (default: /isaac-sim group)")
    parser.add_argument("--frontend-uid", type=int)
    parser.add_argument("--frontend-gid", type=int)
    parser.add_argument("--port", type=int, default=int(os.environ.get("WORKBENCH_HTTP_PORT", "3000")))
    parser.add_argument("--dev", action="store_true")
    parser.add_argument(
        "--diagnostics", action="store_true", help="Explicitly enable bounded test-only diagnostic jobs"
    )
    args = parser.parse_args()
    config = discover(args)
    if args.action == "inspect":
        print(json.dumps(config, indent=2))
    elif args.action == "config":
        print(compose(config, "config"))
    elif args.action == "status":
        print(runtime_call(config, "status"))
        print(compose(config, "ps", "--all"))
    else:
        with operation_lock(config):
            lifecycle(config, args.action)


def lifecycle(config, action):
    """Start or stop only this workbench while its operation lock is held."""
    if action == "stop":
        print(compose(config, "stop", "frontend"))
        print(runtime_call(config, "stop"))
        print(runtime_call(config, "status"))
    else:
        # Check ownership/collisions before building or launching. No automatic dependency start.
        current = json.loads(runtime_call(config, "status"))
        if current["owned"]:
            raise RuntimeError("Workbench API already running; use status or stop before changing configuration")
        if compose(config, "ps", "--status", "running", "-q"):
            raise RuntimeError("Workbench frontend already running; stop it before changing configuration")
        print(runtime_call(config, "preflight"))
        print(compose(config, "config", "--quiet"))
        print(compose(config, "build", "frontend"))
        runtime_call(config, "serve", detached=True)
        try:
            for _ in range(60):
                status = json.loads(runtime_call(config, "status"))
                if status["owned"] and status["healthy"]:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("API failed to become healthy; inspect private state/launcher.log in Arena")
            print(compose(config, "up", "-d", "--no-deps", "--wait", "--wait-timeout", "90", "frontend"))
        except BaseException:
            # Never touch external services; leave durable job state and logs intact.
            compose(config, "stop", "frontend")
            runtime_call(config, "stop")
            raise
        print(runtime_call(config, "status"))
        print(compose(config, "ps"))
        print(config["origin"])


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"workbench: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        sys.exit(1)
