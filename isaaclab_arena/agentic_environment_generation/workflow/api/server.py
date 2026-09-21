# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Gated, single-process query server; control outlives bearer/DB availability."""

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
            except socket.timeout:
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
                        "code": "stop_requested" if self.stop.is_set() else self.known["code"],
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


async def supervise(config, selected, known):
    import httpx
    import uvicorn

    from .application import Composition, Settings, create_app
    from .installed_composition import Resources
    from .installed_config import endpoint
    from .security import TokenRegistry

    registry = TokenRegistry(binding=config.binding, instance=selected, generation=1, clock=time.time)
    token = registry.issue(principal=config.value["read_principal"], lifetime=3600)
    auth = registry.authenticate(("Bearer " + token).encode())
    resources = Resources(config)
    app = create_app(
        settings=Settings(config.binding, Path(config.value["artifact_root"]), config.profiles),
        composition=Composition(
            resources.driver,
            resources.store,
            resources.authority,
            resources.authority.admin,
            resources.authority.reader,
            resources.protect,
            registry,
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
        timeout_graceful_shutdown=None,
    )
    server = uvicorn.Server(settings)
    control = Control(config, selected, known, registry.rotate)
    failed = False

    async def serving():
        nonlocal failed
        try:
            await server.serve()
        except BaseException:
            failed = True

    task = asyncio.create_task(serving())
    try:
        while not server.started and not task.done():
            if control.stop.is_set():
                server.should_exit = True
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
        known.update(state="ready", code="ready")
        save_state(config, selected, known)
        while not task.done() and not control.stop.is_set():
            await asyncio.sleep(0.05)
        if control.stop.is_set():
            known.update(state="stopping", code="stop_requested")
            save_state(config, selected, known)
            server.should_exit = True
        await task
        lifespan = server.lifespan
        if failed or lifespan.error_occurred or lifespan.shutdown_failed or not control.stop.is_set():
            raise ValueError("Server cleanup unconfirmed")
        control.close()
        known.update(state="stopped", code="drained")
        save_state(config, selected, known)
    except BaseException:
        registry.rotate()
        server.should_exit = True
        await task
        control.close()
        known.update(state="failed", code="startup_failed")
        save_state(config, selected, known)
        return 2
    return 0


def serve(config, selected, lifetime, gate):
    """No operational effects until inherited lease, intent and startup gate agree."""
    known = validate_gate(config, selected, lifetime, gate)
    logging.disable(logging.CRITICAL)
    try:
        return asyncio.run(supervise(config, selected, known))
    finally:
        os.close(lifetime)
