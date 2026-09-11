# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Snapshot contracts use a fake RPC peer, never pretend to verify Isaac pixels."""

import base64
import json
import os
import subprocess
import sys
import threading
import time
import yaml
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parents[2] / "isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml"
# Transport fixture ONLY; not a simulator artifact or a visual fidelity assertion.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC")


def test_contract_freezes_pngs_and_caches_canonical_input(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_service import SnapshotService

    service = SnapshotService(tmp_path)
    calls = []
    stages = []

    def rpc(request, deadline, emit):
        calls.append(request)
        output = Path(request["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        thumb = output / "thumb.png"
        scene = output / "scene.png"
        thumb.write_bytes(PNG)
        scene.write_bytes(PNG)
        return {
            "ok": True,
            "paths": {"mug_ycb_robolab": str(thumb)},
            "aabb_dimensions_m": {"mug_ycb_robolab": [0.1, 0.2, 0.3]},
            "scene": str(scene),
        }

    monkeypatch.setattr(service, "_rpc", rpc)
    yaml_text = FIXTURE.read_text()
    result = service.render(yaml_text, "job/../../not-a-path", stages.append)
    assert set(result) == {"input_hash", "assets", "scene", "warnings"}
    assert result["assets"][0]["id"] == "mug_ycb_robolab"
    assert result["assets"][0]["dimensions_m"] == [0.1, 0.2, 0.3]
    for entry in [*result["assets"], result["scene"]]:
        assert entry["url"] == f'/api/editor/artifacts/{entry["artifact_id"]}'
        path = service.artifact_path(entry["artifact_id"])
        assert path.is_relative_to(tmp_path / "editor-artifacts")
        assert path.read_bytes() == PNG
    assert result["warnings"]  # Missing robot and other thumbnails are not invented.
    cached = service.render(yaml_text + "\n# formatting only\n", "different-job", stages.append)
    assert cached == result
    assert len(calls) == 1
    assert "cache_hit" in stages
    assert calls[0]["num_envs"] == 1 and calls[0]["num_steps"] == 0
    service.close()
    restored = SnapshotService(tmp_path)
    monkeypatch.setattr(restored, "_rpc", rpc)
    assert restored.render(yaml_text, "after-restart", stages.append) == result
    assert len(calls) == 1
    changed = restored.render(yaml_text.replace("z: 0.85", "z: 0.95"), "edited", stages.append)
    assert changed["input_hash"] != result["input_hash"]
    assert changed["scene"]["artifact_id"] != result["scene"]["artifact_id"]
    assert len(calls) == 2
    restored.artifact_path(result["scene"]["artifact_id"]).write_bytes(b"corrupted cache")
    repaired = restored.render(yaml_text, "corrupt-receipt", stages.append)
    assert repaired["scene"]["artifact_id"] != result["scene"]["artifact_id"]
    assert len(calls) == 3
    restored.close()


def test_untrusted_paths_and_urls_rejected_before_rpc(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_service import (
        SnapshotError,
        SnapshotService,
    )

    service = SnapshotService(tmp_path)
    monkeypatch.setattr(service, "_rpc", lambda *args: pytest.fail("Unsafe spec reached renderer"))
    raw = yaml.safe_load(FIXTURE.read_text())
    for field, value in [("env_name", "../../outside"), ("includes", ["/etc/passwd"])]:
        with pytest.raises(SnapshotError):
            service.render(yaml.safe_dump({**raw, field: value}), "x", lambda _: None)
    for params in [
        {"usd_path": "https://evil.invalid/a.usd"},
        {"path": "/etc/passwd"},
        {"config": {"source": "omniverse://evil/a.usd"}},
    ]:
        unsafe = {**raw, "background": {**raw["background"], "params": params}}
        with pytest.raises(SnapshotError):
            service.render(yaml.safe_dump(unsafe), "x", lambda _: None)
    with pytest.raises(SnapshotError):
        service.render("a" * (256 * 1024 + 1), "x", lambda _: None)
    service.close()


def test_artifact_containment_png_validation_and_durable_index(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_service import (
        SnapshotError,
        SnapshotService,
    )

    service = SnapshotService(tmp_path)
    output = service.root / "renders" / "test"
    output.mkdir(parents=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    with pytest.raises(SnapshotError):
        service._publish(outside, output)
    (output / "symlink.png").symlink_to(outside)
    with pytest.raises(SnapshotError):
        service._publish(output / "symlink.png", output)
    source = output / "source.png"
    source.write_bytes(b"not a png")
    with pytest.raises(SnapshotError):
        service._publish(source, output)
    source.write_bytes(PNG)
    artifact = service._publish(source, output)
    service.close()
    restored = SnapshotService(tmp_path)
    path = restored.artifact_path(artifact["artifact_id"])
    assert path.read_bytes() == PNG
    for invalid in ["../outside.png", "/etc/passwd", "f" * 32]:
        with pytest.raises(KeyError):
            restored.artifact_path(invalid)
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(KeyError):
        restored.artifact_path(artifact["artifact_id"])
    restored.close()


def test_queue_wait_uses_snapshot_deadline(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_service import (
        SnapshotError,
        SnapshotService,
    )

    service = SnapshotService(tmp_path)
    service.timeout_s = 0.05

    def unexpected(*args):
        raise SnapshotError("Unexpected RPC after expired queue budget")

    monkeypatch.setattr(service, "_rpc", unexpected)
    service._lock.acquire()
    release = threading.Timer(0.3, service._lock.release)
    release.start()
    try:
        with pytest.raises(SnapshotError, match="queue deadline"):
            service.render(FIXTURE.read_text(), "queued", lambda _: None)
    finally:
        release.join()
        service.close()


def test_png_chunk_integrity_is_checked(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_service import (
        SnapshotError,
        SnapshotService,
    )

    service = SnapshotService(tmp_path)
    output = service.root / "renders" / "test"
    output.mkdir(parents=True)
    source = output / "broken.png"
    corrupt = bytearray(PNG)
    corrupt[29] ^= 1  # Invalid IHDR checksum, while preserving plausible framing.
    source.write_bytes(corrupt)
    with pytest.raises(SnapshotError, match="PNG"):
        service._publish(source, output)
    service.close()


@pytest.mark.parametrize(
    "reply,detail",
    [
        ({"ok": False, "error": "Missing registered USD"}, "Missing registered USD"),
        ({"ok": True, "paths": {}}, "scene PNG"),
    ],
)
def test_incomplete_render_is_an_error_not_a_receipt(tmp_path, monkeypatch, reply, detail):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_service import (
        SnapshotError,
        SnapshotService,
    )

    service = SnapshotService(tmp_path)
    monkeypatch.setattr(service, "_rpc", lambda *args: reply)
    with pytest.raises(SnapshotError, match=detail):
        service.render(FIXTURE.read_text(), "failed", lambda _: None)
    assert not list(service.root.glob("*.png"))
    service.close()


FAKE_PEER = """
import argparse, json, os, socket, subprocess, sys, time
from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_process import watch_parent
p=argparse.ArgumentParser()
p.add_argument('--socket'); p.add_argument('--root'); p.add_argument('--owner-fd', type=int)
a=p.parse_args(); watch_parent(a.owner_fd)
s=socket.socket(socket.AF_UNIX); s.bind(a.socket); s.listen()
while True:
 c,_=s.accept()
 with c:
  req=json.loads(c.makefile('rb').readline())
  if req.get('hang'): time.sleep(60)
  child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']) if req.get('child') else None
  c.sendall((json.dumps({'stage':'real_peer_stage'})+'\\n').encode())
  c.sendall((json.dumps({'ok':True, 'pid':os.getpid(), 'child':child.pid if child else None})+'\\n').encode())
"""


def test_owned_rpc_reuses_process_deadlines_and_cleans_socket(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_process import SnapshotProcess

    process = SnapshotProcess(tmp_path)
    assert process.proc is None
    monkeypatch.setattr(process, "_command", lambda: [sys.executable, "-c", FAKE_PEER])
    stages = []
    first = process.request({}, time.monotonic() + 5, stages.append)
    second = process.request({}, time.monotonic() + 5, stages.append)
    assert first["pid"] == second["pid"]
    owned = process.proc
    socket_path = process.socket_path
    assert len(str(socket_path).encode()) < 104
    assert "real_peer_stage" in stages
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="timeout|deadline|timed out"):
        process.request({"hang": True}, time.monotonic() + 0.2, stages.append)
    assert time.monotonic() - started < 5
    assert owned.poll() is not None
    assert not socket_path.exists()
    process.close()
    process.close()


def test_gpu_lease_blocks_another_owned_renderer(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_process import SnapshotProcess

    first = SnapshotProcess(tmp_path / "one")
    second = SnapshotProcess(tmp_path / "two")
    for process in [first, second]:
        monkeypatch.setattr(process, "_command", lambda: [sys.executable, "-c", FAKE_PEER])
    try:
        first.request({}, time.monotonic() + 5, lambda _: None)
        with pytest.raises(RuntimeError, match="GPU lease"):
            second.request({}, time.monotonic() + 0.1, lambda _: None)
        assert second.proc is None
        first.close()
        assert second.request({}, time.monotonic() + 5, lambda _: None)["ok"]
    finally:
        first.close()
        second.close()


def test_parent_death_releases_worker_and_descendant(tmp_path):
    script = tmp_path / "owner.py"
    receipt = tmp_path / "receipt.json"
    script.write_text(
        "import json, sys, time\nfrom pathlib import Path\n"
        "from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_process import SnapshotProcess\n"
        f"p=SnapshotProcess(Path({str(tmp_path / 'artifacts')!r}))\n"
        f"p._command=lambda: [sys.executable, '-c', {FAKE_PEER!r}]\n"
        "r=p.request({'child': True}, time.monotonic()+5, lambda _: None)\n"
        f"Path({str(receipt)!r}).write_text(json.dumps(r))\n"
        "time.sleep(60)\n"
    )
    with subprocess.Popen([sys.executable, str(script)]) as owner:
        try:
            deadline = time.monotonic() + 8
            while not receipt.exists() and time.monotonic() < deadline:
                assert owner.poll() is None
                time.sleep(0.05)
            assert receipt.exists()
            ids = json.loads(receipt.read_text())
            owner.kill()
            owner.wait(timeout=3)

            def running(pid):
                proc = Path(f"/proc/{pid}/stat")
                return proc.exists() and proc.read_text().rsplit(")", 1)[1].split()[0] != "Z"

            deadline = time.monotonic() + 3
            while any(running(ids[key]) for key in ("pid", "child")) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not running(ids["pid"]) and not running(ids["child"])
        finally:
            if owner.poll() is None:
                owner.kill()


@pytest.mark.skipif(os.environ.get("ARENA_REAL_SNAPSHOTS") != "1", reason="Explicit GPU render opt-in only")
def test_real_fixture_snapshot():
    from PIL import Image, ImageStat

    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_service import SnapshotService

    assert os.getuid() != 0 and os.getgid() != 0
    state = Path(os.environ["ARENA_REAL_SNAPSHOT_DIR"])
    service = SnapshotService(state)
    started = time.monotonic()
    try:
        result = service.render(
            FIXTURE.read_text(), "bounded-real-verification", lambda stage: print(stage, flush=True)
        )
        (state / "result.json").write_text(json.dumps(result, indent=2))
        assert result["scene"]
        expected = {
            "maple_table_robolab",
            "rubiks_cube_hot3d_robolab",
            "bowl_ycb_robolab",
            "mug_ycb_robolab",
            "maple_table_robolab_table",
        }
        assert {a["id"] for a in result["assets"]} == expected
        for entry in [*result["assets"], result["scene"]]:
            path = service.artifact_path(entry["artifact_id"])
            with Image.open(path) as image:
                image.load()
                assert image.format == "PNG" and min(image.size) >= 64
                assert max(ImageStat.Stat(image.convert("RGB")).stddev) > 1
        assert service.render(FIXTURE.read_text(), "same-input", print) == result
        print(json.dumps(result), flush=True)
    finally:
        service.close()
        print(f"bounded_render_seconds={time.monotonic() - started:.2f}", flush=True)
