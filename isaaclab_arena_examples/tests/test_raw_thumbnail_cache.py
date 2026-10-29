# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""CPU cache regressions; PNG fixtures are transport data, not rendered pixels."""

from types import SimpleNamespace

import pytest


@pytest.fixture
def thumbnail_renderer(tmp_path, monkeypatch):
    import sys

    from PIL import Image
    from pxr import Sdf, Usd, UsdGeom

    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp import thumbnail_capture as capture

    usd_path = tmp_path / "fixture.usda"
    stage = Usd.Stage.CreateNew(str(usd_path))
    root = UsdGeom.Xform.Define(stage, "/Root")
    UsdGeom.Cube.Define(stage, "/Root/Cube")
    stage.SetDefaultPrim(root.GetPrim())
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    stage.GetRootLayer().Save()
    state = SimpleNamespace(stage=None, calls=0)

    def open_stage(path):
        state.stage = Usd.Stage.Open(Sdf.Layer.FindOrOpen(path), Sdf.Layer.CreateAnonymous())
        return True

    ctx = SimpleNamespace(
        open_stage=open_stage,
        get_stage=lambda: state.stage,
        get_selection=lambda: SimpleNamespace(clear_selected_prim_paths=lambda: None),
    )
    fake_usd = SimpleNamespace(get_context=lambda: ctx)
    monkeypatch.setitem(sys.modules, "omni", SimpleNamespace(usd=fake_usd))
    monkeypatch.setitem(sys.modules, "omni.usd", fake_usd)
    background = SimpleNamespace(id="bg", registry_name="bg", params={})
    robot = SimpleNamespace(id="robot", registry_name="robot", params={})
    reference = SimpleNamespace(id="ref", parent_id="bg", prim_path="Cube", params={})
    spec = SimpleNamespace(background=background, embodiment=robot, objects=[], object_references=[reference])
    scales = {"bg": [1, 1, 1], "robot": [1, 1, 1]}

    def construct(node, *args, **kwargs):
        if node.id == "robot":
            return SimpleNamespace(
                name=node.id,
                scene_config=SimpleNamespace(
                    robot=SimpleNamespace(spawn=SimpleNamespace(usd_path=str(usd_path), scale=scales[node.id]))
                ),
            )
        return SimpleNamespace(name=node.id, usd_path=str(usd_path), scale=scales[node.id])

    def frame(app, stage, targets, **kwargs):
        bounds = (
            UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
            .ComputeWorldBound(stage.GetPrimAtPath(targets[0]))
            .ComputeAlignedRange()
        )
        return {"dimensions_m": list(bounds.GetSize())}

    def png(app, path, **kwargs):
        state.calls += 1
        Image.new("RGB", (512, 512), "red").save(path)
        return path.read_bytes()

    monkeypatch.setattr(capture, "_construct_asset", construct)
    monkeypatch.setattr(capture, "wait_for_stage_load", lambda *a: None)
    monkeypatch.setattr(capture, "_ensure_default_lighting", lambda *a: None)
    monkeypatch.setattr(capture, "frame_targets", frame)
    monkeypatch.setattr(capture, "capture_viewport_png", png)

    def render():
        manifest, errors = {}, []
        paths, dimensions = capture.render_thumbnails_with_app(
            None,
            spec,
            options={"resolution": 512},
            output_dir=tmp_path / "output",
            cache_dir=tmp_path / "isolated-thumbnails",
            manifest=manifest,
            errors=errors,
        )
        assert not errors
        assert set(paths) == {"bg", "robot", "ref"}
        return manifest, dimensions

    return SimpleNamespace(render=render, scales=scales, spec=spec, state=state, usd_path=usd_path, capture=capture)


@pytest.mark.parametrize("parent,affected", [("bg", {"bg", "ref"}), ("robot", {"robot"})])
def test_registry_default_scale_invalidates_only_affected_raw_thumbnails(thumbnail_renderer, parent, affected):
    renderer = thumbnail_renderer
    usd_bytes = renderer.usd_path.read_bytes()
    first, _ = renderer.render()
    warm, _ = renderer.render()
    assert all(entry["cache_hit"] for entry in warm.values())
    renderer.scales[parent][:] = [2, 3, 4]
    renderer.spec.relations = ["unrelated scene placement"]
    changed, dimensions = renderer.render()
    assert renderer.usd_path.read_bytes() == usd_bytes
    for node_id, entry in changed.items():
        assert entry["cache_hit"] == (node_id not in affected)
        assert (entry["cache_key"] != first[node_id]["cache_key"]) == (node_id in affected)
        assert dimensions[node_id] == ((4, 6, 8) if node_id in affected else (2, 2, 2))
    repeated, _ = renderer.render()
    assert all(entry["cache_hit"] for entry in repeated.values())


def test_scale_is_frozen_before_cache_lookup(thumbnail_renderer, monkeypatch):
    renderer = thumbnail_renderer
    original = renderer.capture._cache_read

    def read(*args):
        renderer.scales["robot"][:] = [9, 9, 9]
        return original(*args)

    # The robot is processed after bg, so change its scale only at its own lookup.
    calls = 0

    def lookup(*args):
        nonlocal calls
        calls += 1
        return read(*args) if calls == 2 else original(*args)

    monkeypatch.setattr(renderer.capture, "_cache_read", lookup)
    first, dimensions = renderer.render()
    assert dimensions["robot"] == (2, 2, 2)
    monkeypatch.setattr(renderer.capture, "_cache_read", original)
    renderer.scales["robot"][:] = [1, 1, 1]
    again, _ = renderer.render()
    assert again["robot"]["cache_hit"]
    assert first["robot"]["cache_key"] == again["robot"]["cache_key"]


def test_thumbnail_writer_uses_owned_temporary_names(thumbnail_renderer, monkeypatch):
    import re
    from pathlib import Path

    original = Path.replace
    temporary_names = []

    def replace(path, target):
        temporary_names.append(path.name)
        return original(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    thumbnail_renderer.render()
    assert temporary_names
    assert all(re.fullmatch(r"[a-f0-9]{64}\.tmp\.(png|json)", name) for name in temporary_names)


@pytest.fixture(params=["raw", "web"])
def cache_pruner(request, tmp_path):
    import sqlite3

    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.render_identity import prune_raw_cache
    from isaaclab_arena_examples.agentic_environment_generation.web_api.preview_retention import cleanup

    cache = tmp_path / "isolated-thumbnails"
    cache.mkdir()
    db_path = tmp_path / "catalogue.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE previews(cache_key TEXT, result TEXT, created REAL)")
        db.execute("CREATE TABLE artifacts(id TEXT)")
        db.execute("CREATE TABLE receipts(id TEXT)")

    def prune(*, max_entries=128, max_bytes=4096, max_age_s=None, now=1000):
        if request.param == "raw":
            age = {"max_age_s": max_age_s, "now": now} if max_age_s is not None else {}
            prune_raw_cache(cache, max_entries=max_entries, max_bytes=max_bytes, **age)
        else:
            cleanup(
                tmp_path,
                db_path,
                max_receipts=max_entries,
                max_bytes=max_bytes * 4,
                max_age_s=max_age_s if max_age_s is not None else 10**12,
                now=now,
            )

    return cache, prune


@pytest.mark.parametrize("budget", ["bytes", "count"])
def test_orphan_temporaries_are_budgeted(cache_pruner, budget):
    cache, prune = cache_pruner
    names = ["a" * 32 + ".tmp", "b" * 64 + ".tmp.png", "c" * 64 + ".tmp.json", "d" * 64 + ".json"]
    for name in names:
        (cache / name).write_bytes(b"0123456789")
    prune(**({"max_bytes": 0} if budget == "bytes" else {"max_entries": 0}))
    assert not any((cache / name).exists() for name in names)


@pytest.mark.parametrize("name", ["a" * 32 + ".tmp", "a" * 64 + ".tmp.png", "a" * 64 + ".tmp.json"])
def test_orphan_temporaries_expire_by_age(cache_pruner, name):
    import os

    cache, prune = cache_pruner
    stale = cache / name
    stale.write_bytes(b"expired")
    os.utime(stale, (1, 1))
    fresh = cache / ("b" * 64 + ".tmp.json")
    fresh.write_bytes(b"fresh")
    os.utime(fresh, (995, 995))
    prune(max_age_s=10, now=1000)
    assert not stale.exists()
    assert fresh.read_bytes() == b"fresh"


def test_retention_preserves_in_progress_thumbnail_writes(thumbnail_renderer, cache_pruner, monkeypatch):
    from pathlib import Path

    cache, prune = cache_pruner
    original = Path.replace
    observed = []

    def replace(path, target):
        if path.parent == cache:
            prune(max_entries=0, max_bytes=0)
            assert path.is_file(), "retention deleted an active temporary"
            if path.name.endswith(".json"):
                assert target.with_suffix(".png").is_file(), "retention split an active receipt"
            observed.append(path)
        return original(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    thumbnail_renderer.render()
    assert len(observed) == 6
    prune(max_entries=0, max_bytes=0)
    assert not list(cache.glob("*.png"))
    assert not list(cache.glob("*.json"))


def test_retention_preserves_unowned_paths_and_symlinks(cache_pruner, monkeypatch):
    import os
    from pathlib import Path

    cache, prune = cache_pruner
    outside = cache.parent / "outside.png"
    outside.write_bytes(b"untouched")
    names = ["a" * 64 + ".png", "b" * 64 + ".tmp.png", "c" * 32 + ".tmp"]
    for name in names:
        (cache / name).symlink_to(outside)
    unrelated = cache / "unrelated.tmp"
    unrelated.write_bytes(b"not ours")
    unowned = cache / ("d" * 64 + ".tmp.json")
    unowned.write_bytes(b"another uid")
    original = Path.lstat

    def lstat(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == unowned:
            fields = list(info)
            fields[4] = os.getuid() + 1
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(Path, "lstat", lstat)
    prune(max_entries=0, max_bytes=0)
    assert all((cache / name).is_symlink() for name in names)
    assert outside.read_bytes() == b"untouched"
    assert unrelated.read_bytes() == b"not ours"
    assert unowned.read_bytes() == b"another uid"


def test_crashed_writer_releases_lease_for_orphan_cleanup(cache_pruner):
    import selectors
    import subprocess
    import sys

    cache, prune = cache_pruner
    orphan = cache / ("a" * 64 + ".tmp.png")
    script = """
import os
import sys
from pathlib import Path
from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.render_identity import raw_cache_write_lease
cache = Path(sys.argv[1])
with raw_cache_write_lease(cache):
    (cache / ('a' * 64 + '.tmp.png')).write_bytes(b'partial capture')
    print('ready', flush=True)
    sys.stdin.readline()
    os._exit(0)  # Crash simulation: no finally/context-manager cleanup.
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(cache)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=10), "CPU writer did not become ready"
        assert child.stdout.readline().strip() == "ready"
        prune(max_bytes=0, max_entries=0)
        assert orphan.read_bytes() == b"partial capture"
        child.communicate("crash\n", timeout=10)
        assert child.returncode == 0
        prune(max_bytes=0, max_entries=0)
        assert not orphan.exists()
        assert not list(cache.iterdir())  # Leases do not leave unbudgeted files.
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)


def test_retention_does_not_traverse_symlink_cache_directory(cache_pruner):
    cache, prune = cache_pruner
    outside = cache.parent / "outside"
    outside.mkdir()
    receipt = outside / ("a" * 64 + ".png")
    receipt.write_bytes(b"not a cache")
    cache.rmdir()
    cache.symlink_to(outside, target_is_directory=True)
    prune(max_entries=0, max_bytes=0)
    assert receipt.read_bytes() == b"not a cache"
    assert cache.is_symlink()


def test_writer_lease_releases_on_exception_and_rejects_symlink_root(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.render_identity import (
        raw_cache_write_lease,
    )

    with pytest.raises(RuntimeError, match="failed write"):
        with raw_cache_write_lease(tmp_path):
            raise RuntimeError("failed write")
    with raw_cache_write_lease(tmp_path, blocking=False) as acquired:
        assert acquired
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError, match="real owned directory"):
        with raw_cache_write_lease(link):
            pytest.fail("Writer followed a cache symlink")
