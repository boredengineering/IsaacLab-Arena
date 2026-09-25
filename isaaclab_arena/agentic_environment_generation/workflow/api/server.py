# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Gated installed server; control outlives bearer/DB availability."""

import asyncio
import logging
import os
import socket
import struct
import threading
import time
from pathlib import Path

from .instance import _frame, instance_path, save_state, validate_gate
from .private_files import Directory, encode, fields

READINESS = (
    "query Readiness { workflowProfiles { __typename ... on WorkflowProfileList { profiles { id revision } } ... on"
    " QueryFailure { code } } }"
)
EXECUTION_SHUTDOWN_SECONDS = 20.0


async def observe_execution_shutdown(task, app):
    """Bound observation only; never cancel owned cleanup or infer drain on timeout."""
    deadline = asyncio.get_running_loop().time() + EXECUTION_SHUTDOWN_SECONDS
    while not task.done():
        if app.state.cleanup_unknown:
            return False
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False
        await asyncio.wait({task}, timeout=min(0.05, remaining))
    return not app.state.cleanup_unknown


class Control:
    def __init__(self, config, selected, known, revoke):
        self.config, self.selected, self.known, self.revoke = config, selected, known, revoke
        self.stop = threading.Event()
        self.closed = threading.Event()
        self.directory = Directory(instance_path(config, selected))
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(f"/proc/self/fd/{self.directory.fd}/control.sock")
        os.chmod("control.sock", 0o600, dir_fd=self.directory.fd, follow_symlinks=False)
        self.socket.listen(4)
        self.socket.settimeout(0.1)
        self.thread = threading.Thread(target=self.run, name="query-instance-control", daemon=False)
        self.thread.start()

    def run(self):
        while not self.closed.is_set():
            try:
                peer, _ = self.socket.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with peer:
                try:
                    _, uid, _ = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    if uid != os.getuid():
                        raise PermissionError("Control peer rejected")
                    packet = fields(_frame(peer, time.monotonic() + 5), "v op instance config_sha256")
                    if (
                        type(packet["v"]) is not int
                        or packet["v"] != 1
                        or packet["instance"] != self.selected
                        or packet["config_sha256"] != self.config.digest
                        or packet["op"] not in {"status", "stop"}
                    ):
                        raise ValueError("Control request rejected")
                    if packet["op"] == "stop":
                        self.stop.set()
                        self.revoke()
                    response = {
                        "v": 1,
                        "instance": self.selected,
                        "state": "stopping" if self.stop.is_set() else self.known["state"],
                        "code": (
                            "cleanup_unknown"
                            if self.known["code"] == "cleanup_unknown"
                            else "stop_requested" if self.stop.is_set() else self.known["code"]
                        ),
                    }
                    peer.sendall(encode(response) + b"\n")
                except Exception:
                    pass

    def close(self):
        self.closed.set()
        self.socket.close()
        self.thread.join(6)
        if self.thread.is_alive():
            raise ValueError("Control close incomplete")
        self.directory.__exit__()
        # Consumed instance socket is a tombstone; never unlink another instance.


async def retain_unknown(app, config, selected, known, *, pending=None):
    """Report uncertainty while retaining resources and the lifetime lease."""
    from contextlib import suppress

    known.update(state="stopping", code="cleanup_unknown")
    # Metadata failure cannot authorize lease release; live local control still
    # reports cleanup_unknown without depending on DB/HTTP.
    with suppress(Exception):
        save_state(config, selected, known)
    if pending is not None:
        while not pending.done():
            try:
                await asyncio.shield(pending)
            except asyncio.CancelledError:
                if pending.cancelled():
                    break
            except Exception:
                break
        owner = getattr(app.state, "execution_owner", None)
        if (
            not pending.cancelled()
            and pending.exception() is None
            and app.state.cleanup_complete
            and not app.state.cleanup_unknown
            and owner is not None
            and owner._closed
        ):
            return
    app.state.cleanup_unknown = True
    while True:
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            continue


async def supervise(config, selected, known, *, native_authorized=False, assessment_authorized=False):
    import httpx
    import uvicorn

    from .application import Composition, Settings, create_app
    from .installed_composition import Resources
    from .installed_config import endpoint
    from .security import TokenRegistry

    registry = TokenRegistry(binding=config.binding, instance=selected, generation=1, clock=time.time)
    token = registry.issue(principal=config.value["read_principal"], lifetime=3600)
    auth = registry.authenticate(("Bearer " + token).encode())
    execution_factory = None
    if config.value["mode"] == "isolated-synthetic-execution-v1":
        import importlib

        # This literal is an explicit execution root, not a discoverable plugin.
        execution = importlib.import_module(
            "isaaclab_arena.agentic_environment_generation.workflow.api.installed_execution"
        )
        execution_factory = execution.compose(config, tokens=registry, auth=auth)
    elif config.value["mode"] == "retained-native-validation-v1":
        import importlib

        execution = importlib.import_module(
            "isaaclab_arena.agentic_environment_generation.workflow.api.installed_native"
        )
        execution_factory = execution.compose(config, tokens=registry, auth=auth, native_authorized=native_authorized)
    elif config.value["mode"] == "retained-visual-assessment-v1":
        from . import installed_assessment as execution

        execution_factory = execution.compose(
            config,
            tokens=registry,
            auth=auth,
            assessment_authorized=assessment_authorized,
            private_roles=lambda: resources.private_roles(),
        )
    resources = Resources(config)

    def protect(value):
        resources.protect(value)
        if execution_factory is not None:
            execution.protect(value)

    app = create_app(
        settings=Settings(config.binding, Path(config.value["artifact_root"]), config.profiles),
        composition=Composition(
            resources.driver,
            resources.store,
            resources.authority,
            resources.authority.admin,
            resources.authority.reader,
            protect,
            registry,
            execution_factory,
        ),
    )
    host, port = endpoint(config.value["endpoint"])
    settings = uvicorn.Config(
        app,
        host=host,
        port=port,
        loop="asyncio",
        http="h11",
        lifespan="on",
        ws="none",
        workers=1,
        reload=False,
        proxy_headers=False,
        access_log=False,
        log_config=None,
        server_header=False,
        date_header=False,
        backlog=16,
        timeout_keep_alive=2,
        timeout_graceful_shutdown=2 if execution_factory is not None else None,
    )
    server = uvicorn.Server(settings)
    control = Control(
        config,
        selected,
        known,
        app.state.request_execution_stop if execution_factory is not None else registry.rotate,
    )
    failed = False

    async def serving():
        nonlocal failed
        try:
            await server.serve()
        except BaseException:
            failed = True

    task = asyncio.create_task(serving())

    async def drain_server():
        if execution_factory is not None:
            app.state.request_execution_stop()
        server.should_exit = True
        if execution_factory is not None and not await observe_execution_shutdown(task, app):
            await retain_unknown(app, config, selected, known, pending=task)
        await task

    try:
        while not server.started and not task.done():
            if control.stop.is_set():
                server.should_exit = True
                if execution_factory is not None:
                    break
            await asyncio.sleep(0.05)
        if not server.started or control.stop.is_set():
            raise ValueError("Server startup incomplete")
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=5, cookies=None) as client:
            async with client.stream(
                "POST",
                config.value["endpoint"],
                headers={"Authorization": "Bearer " + token},
                json={"query": READINESS},
            ) as response:
                raw = bytearray()
                async for part in response.aiter_bytes():
                    raw.extend(part)
                    if len(raw) > 65536:
                        raise ValueError("Readiness response rejected")
                from .private_files import decode

                result = decode(bytes(raw), 65536)
                if (
                    response.status_code != 200
                    or result.get("data", {}).get("workflowProfiles", {}).get("__typename") != "WorkflowProfileList"
                ):
                    raise ValueError("Network readiness rejected")
        descriptor = {
            "schema_version": 1,
            "endpoint": config.value["endpoint"],
            "instance": selected,
            "generation": auth.generation,
            "binding": auth.binding.model_dump(mode="json"),
            "principal": auth.principal,
            "expires_at": auth.expires_at,
            "bearer": token,
        }
        with Directory(config.value["private_root"]) as root, root.lease("metadata.lock"):
            with Directory(instance_path(config, selected)) as directory:
                directory.write("client.json", encode(descriptor))
        if execution_factory is not None:
            if app.state.execution_owner is None:
                raise ValueError("Execution composition unavailable")
            known["capabilities"] = dict(execution.CAPABILITIES)
        known.update(state="ready", code="ready")
        save_state(config, selected, known)
        while not task.done() and not control.stop.is_set():
            if execution_factory is not None and (app.state.cleanup_unknown or server.should_exit):
                break
            await asyncio.sleep(0.05)
        if control.stop.is_set():
            known.update(state="stopping", code="stop_requested")
            save_state(config, selected, known)
            server.should_exit = True
        await drain_server()
        lifespan = server.lifespan
        if failed or lifespan.error_occurred or lifespan.shutdown_failed or not control.stop.is_set():
            if execution_factory is not None:
                await retain_unknown(app, config, selected, known)
            raise ValueError("Server cleanup unconfirmed")
        control.close()
        known.update(state="stopped", code="drained")
        save_state(config, selected, known)
    except BaseException:
        registry.rotate()
        await drain_server()
        if execution_factory is not None and (
            failed or server.lifespan.error_occurred or server.lifespan.shutdown_failed
        ):
            await retain_unknown(app, config, selected, known)
        control.close()
        known.update(state="failed", code="startup_failed")
        save_state(config, selected, known)
        return 2
    return 0


def serve(config, selected, lifetime, gate, *, native_authorized=False, assessment_authorized=False):
    """No operational effects until inherited lease, intent and startup gate agree."""
    known = validate_gate(config, selected, lifetime, gate)
    logging.disable(logging.CRITICAL)
    try:
        return asyncio.run(
            supervise(
                config,
                selected,
                known,
                native_authorized=native_authorized,
                assessment_authorized=assessment_authorized,
            )
        )
    finally:
        os.close(lifetime)
