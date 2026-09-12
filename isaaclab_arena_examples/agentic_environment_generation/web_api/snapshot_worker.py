# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Private SimApp worker using the existing Streamlit capture and preview code."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import socket
import sys
import time
import traceback
from pathlib import Path

from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_process import watch_parent


def _render(app, request: dict, send, root: Path) -> dict:
    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.render_identity import (
        normalize_options,
    )
    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.sim_preview import run_sim_preview
    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.thumbnail_capture import (
        render_thumbnails_with_app,
    )
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_service import validated_spec

    started = time.monotonic()
    spec = validated_spec(request["yaml_text"])
    if request.get("num_envs") != 1 or request.get("num_steps") != 0:
        raise ValueError("Editor snapshots permit only num_envs=1, num_steps=0")
    nodes = [spec.background, spec.embodiment, *spec.objects, *(spec.object_references or [])]
    options = normalize_options(request.get("options"), {node.id for node in nodes})
    output = Path(request["output_dir"])
    root = root.resolve()
    if not output.is_relative_to(root / "renders") or output.resolve() != output:
        raise ValueError("Snapshot output is not in the owned render directory")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    cache = root / "isolated-thumbnails"
    if cache.resolve() != cache:
        raise ValueError("Thumbnail cache must not contain symlinks")
    cache.mkdir(mode=0o700, exist_ok=True)
    errors, timings, manifest = [], {}, {}
    paths, dimensions, scene_path = {}, {}, None
    send({"stage": "rendering_asset_thumbnails"})
    asset_start = time.monotonic()
    try:
        paths, dimensions = render_thumbnails_with_app(
            app,
            spec,
            options=options,
            output_dir=output,
            cache_dir=cache,
            renderer_version=request.get("renderer_version", "legacy"),
            asset_revision=request.get("asset_revision"),
            errors=errors,
            timings=timings,
            manifest=manifest,
        )
    except Exception as exc:
        errors.append({"id": "assets", "stage": "thumbnails", "code": type(exc).__name__, "message": str(exc)})
    timings["assets_s"] = time.monotonic() - asset_start
    send({"stage": "solving_scene_and_capturing_overview"})
    scene_start = time.monotonic()
    try:
        scene = run_sim_preview(
            app, request["yaml_text"], num_envs=1, num_steps=0, env_spacing=3.0, options=options, output_dir=output
        )
        if not scene.get("ok"):
            raise RuntimeError(scene.get("error", "Scene capture failed"))
        scene_path = scene["first_frame"]
        timings.update(scene.get("timings", {}))
        manifest["scene"] = scene.get("camera", {})
    except Exception as exc:
        errors.append({"id": "scene", "stage": "scene", "code": type(exc).__name__, "message": str(exc)})
    timings["scene_s"] = time.monotonic() - scene_start
    timings["total_s"] = time.monotonic() - started
    return {
        "ok": bool(paths or scene_path),
        "paths": {node: str(path) for node, path in paths.items()},
        "aabb_dimensions_m": {node: list(dims) for node, dims in dimensions.items()},
        "scene": scene_path,
        "errors": errors,
        "timings": timings,
        "asset_manifest": manifest,
        **({"error": "No snapshot artifacts produced"} if not paths and not scene_path else {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--owner-fd", type=int, required=True)
    args = parser.parse_args()
    if os.getuid() == 0 or os.getgid() == 0:
        raise RuntimeError("Snapshot worker must run non-root in Arena (ubuntu:1234)")
    watch_parent(args.owner_fd)
    socket_path = Path(args.socket)
    root = Path(args.root)
    # Do not leak the private worker CLI into Kit's unknown-argument forwarding.
    sys.argv = [sys.argv[0]]
    from isaaclab_arena.utils.isaaclab_utils.simulation_app import get_app_launcher
    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.boot import launch_args

    launch = launch_args()
    launch.livestream = 0
    launch.video = True  # Preserve the active viewport if HEADLESS is configured.
    launch.kit_args = f"--portable --portable-root {socket_path.parent / 'kit'}"
    print(f"[editor-snapshot] boot args={vars(launch)}", flush=True)
    app = get_app_launcher(launch).app

    def terminate(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        # The service creates a private short directory. Never unlink an existing socket.
        server.bind(str(socket_path))
        os.chmod(socket_path, 0o600)
        server.listen(1)
        inode = socket_path.stat().st_ino
        print(f"[editor-snapshot] ready socket={socket_path}", flush=True)
        try:
            while True:
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(10)
                    with connection.makefile("rb") as reader:
                        line = reader.readline(512 * 1024 + 1)
                        if not line or len(line) > 512 * 1024 or not line.endswith(b"\n"):
                            continue

                        def send(payload):
                            connection.sendall((json.dumps(payload) + "\n").encode())

                        try:
                            result = _render(app, json.loads(line), send, root)
                        except Exception as exc:
                            traceback.print_exc()
                            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                        send(result)
        finally:
            if socket_path.exists() and socket_path.stat().st_ino == inode:
                socket_path.unlink()
            with contextlib.suppress(Exception):
                app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
