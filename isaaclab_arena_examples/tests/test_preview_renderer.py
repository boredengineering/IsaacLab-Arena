# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""CPU regressions for renderer boundaries (not a claim about rendered pixels)."""

from types import SimpleNamespace

import pytest

from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp import asset_usd


class Prim:
    def __init__(self, path, valid=True):
        self.path, self.valid = path, valid

    def IsValid(self):
        return self.valid

    def __bool__(self):
        return self.valid

    def GetPath(self):
        return self.path


class Stage:
    def GetDefaultPrim(self):
        return Prim("/Root")

    def GetPrimAtPath(self, path):
        return Prim(path, path in {"/Root", "/Root/room/table"})


def test_runtime_reference_is_rebased_not_appended():
    assert (
        asset_usd.absolute_prim_path(Stage(), "{ENV_REGEX_NS}/kitchen/room/table", parent_name="kitchen")
        == "/Root/room/table"
    )
    assert asset_usd.absolute_prim_path(Stage(), "/Root/room/table") == "/Root/room/table"
    assert asset_usd.absolute_prim_path(Stage(), "room/table") == "/Root/room/table"
    with pytest.raises(ValueError):
        asset_usd.absolute_prim_path(Stage(), "{ENV_REGEX_NS}/other/room/table", parent_name="kitchen")
    with pytest.raises(ValueError):
        asset_usd.absolute_prim_path(Stage(), "missing")


def test_robot_usd_comes_from_scene_config_spawn():
    robot = SimpleNamespace(
        scene_config=SimpleNamespace(robot=SimpleNamespace(spawn=SimpleNamespace(usd_path="/robot.usd")))
    )
    assert asset_usd.resolve_node_usd_paths({"robot": robot}, ["robot"]) == {"robot": "/robot.usd"}


def test_options_are_strict_and_asset_views_are_scoped():
    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.render_identity import (
        normalize_options,
    )

    assert normalize_options(None, {"robot"}) == {"view": "isometric", "resolution": 1024, "asset_views": {}}
    assert normalize_options({"view": "front", "resolution": 512, "asset_views": {"robot": "top"}}, {"robot"})[
        "asset_views"
    ] == {"robot": "top"}
    for options in (
        {"view": "rear"},
        {"resolution": True},
        {"resolution": "512"},
        {"resolution": 2048},
        {"unknown": 1},
        {"asset_views": {"other": "top"}},
    ):
        with pytest.raises(ValueError):
            normalize_options(options, {"robot"})


def test_identity_reuses_asset_not_scene_and_changes_with_content(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.render_identity import (
        thumbnail_identity,
    )

    usd = tmp_path / "asset.usda"
    usd.write_text("first")
    kwargs = dict(
        registry_name="cup",
        params={"scale": [1, 1, 1]},
        dependencies=[usd],
        view="front",
        resolution=512,
        renderer_version="test",
    )
    first = thumbnail_identity(**kwargs)
    assert first == thumbnail_identity(**kwargs)
    assert first != thumbnail_identity(**{**kwargs, "view": "top"})
    assert first != thumbnail_identity(**{**kwargs, "params": {"scale": [2, 1, 1]}})
    assert first != thumbnail_identity(**{**kwargs, "renderer_version": "next"})
    usd.write_text("second")
    assert first != thumbnail_identity(**kwargs)
    assert thumbnail_identity(**{**kwargs, "dependencies": ["https://example.com/asset.usd"]}) is None


def test_worker_preserves_assets_when_scene_fails(tmp_path, monkeypatch):
    import sys

    from isaaclab_arena_examples.agentic_environment_generation.web_api import snapshot_service, snapshot_worker

    spec = SimpleNamespace(
        background=SimpleNamespace(id="bg"), embodiment=SimpleNamespace(id="robot"), objects=[], object_references=[]
    )
    monkeypatch.setattr(snapshot_service, "validated_spec", lambda _: spec)
    base = "isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp."

    def thumbnails(app, spec, **kwargs):
        path = kwargs["output_dir"] / "robot.png"
        path.write_bytes(b"transport-only")
        return {"robot": path}, {}

    def scene(*args, **kwargs):
        raise RuntimeError("scene failed")

    monkeypatch.setitem(sys.modules, base + "thumbnail_capture", SimpleNamespace(render_thumbnails_with_app=thumbnails))
    monkeypatch.setitem(sys.modules, base + "sim_preview", SimpleNamespace(run_sim_preview=scene))
    request = {"yaml_text": "fixture", "output_dir": str(tmp_path / "renders" / "one"), "num_envs": 1, "num_steps": 0}
    result = snapshot_worker._render(None, request, lambda _: None, tmp_path)
    assert result["ok"] and result["scene"] is None
    assert "robot" in result["paths"]
    assert result["errors"][0]["id"] == "scene"
    assert result["timings"]["scene_s"] >= 0


@pytest.mark.parametrize("view", ["isometric", "front", "side", "top"])
def test_camera_frames_real_usd_bounds_without_origin_assumption(view, monkeypatch):
    import sys

    from pxr import Gf, Usd, UsdGeom

    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp import kit_viewport

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    cube = UsdGeom.Cube.Define(stage, "/Target")
    UsdGeom.Xformable(cube).AddTranslateOp().Set(Gf.Vec3d(12, -7, 5))
    viewport = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "omni.kit.viewport.utility", SimpleNamespace(get_active_viewport=lambda: viewport))
    monkeypatch.setattr(kit_viewport, "pump_app", lambda *a, **kw: None)
    result = kit_viewport.frame_targets(None, stage, ["/Target"], view=view, resolution=512)
    assert result["lookat"] == [12, -7, 5]
    assert result["dimensions_m"] == [2, 2, 2]
    assert viewport.resolution == (512, 512)
    camera = UsdGeom.Camera(stage.GetPrimAtPath(viewport.camera_path)).GetCamera(Usd.TimeCode.Default())
    world_to_camera = camera.frustum.ComputeViewMatrix()
    projection = camera.frustum.ComputeProjectionMatrix()
    for x in (11, 13):
        for y in (-8, -6):
            for z in (4, 6):
                ndc = (world_to_camera * projection).Transform(Gf.Vec3d(x, y, z))
                assert all(abs(v) < 1 for v in ndc)
    with pytest.raises(ValueError, match="does not exist"):
        kit_viewport.frame_targets(None, stage, ["/Missing"])


def test_reference_isolation_hides_environment_not_target():
    from pxr import Usd, UsdGeom

    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.thumbnail_capture import (
        _isolate_subtree,
    )

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/Root")
    target = UsdGeom.Cube.Define(stage, "/Root/room/table")
    wall = UsdGeom.Cube.Define(stage, "/Root/room/wall")
    other_room = UsdGeom.Cube.Define(stage, "/Root/other/cube")
    stage.SetEditTarget(stage.GetSessionLayer())
    _isolate_subtree(stage, "/Root/room/table")
    assert target.ComputeVisibility() == UsdGeom.Tokens.inherited
    assert wall.ComputeVisibility() == UsdGeom.Tokens.invisible
    assert other_room.ComputeVisibility() == UsdGeom.Tokens.invisible
    assert not stage.GetRootLayer().GetPrimAtPath("/Root/room/wall").HasInfo("visibility")


def test_dependency_closure_tracks_texture_and_nested_usd(tmp_path):
    from pxr import Sdf, Usd, UsdGeom

    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.thumbnail_capture import _dependencies

    nested_path = tmp_path / "mesh.usda"
    nested = Usd.Stage.CreateNew(str(nested_path))
    cube = UsdGeom.Cube.Define(nested, "/Cube")
    nested.SetDefaultPrim(cube.GetPrim())
    nested.GetRootLayer().Save()
    texture = tmp_path / "albedo.png"
    texture.write_bytes(b"dependency-fingerprint-only")
    root_path = tmp_path / "root.usda"
    root = Usd.Stage.CreateNew(str(root_path))
    prim = root.DefinePrim("/Root")
    root.SetDefaultPrim(prim)
    prim.GetReferences().AddReference(str(nested_path))
    prim.CreateAttribute("texture", Sdf.ValueTypeNames.Asset).Set(str(texture))
    root.GetRootLayer().Save()
    assert set(map(str, _dependencies(str(root_path)))) == {str(root_path), str(nested_path), str(texture)}
    replacement = tmp_path / "replacement.png"
    replacement.write_bytes(b"updated-texture")
    root_path.write_text(root_path.read_text().replace(str(texture), str(replacement)))
    assert set(map(str, _dependencies(str(root_path)))) == {str(root_path), str(nested_path), str(replacement)}


def test_raw_cache_rejects_corruption_and_symlinks(tmp_path):
    import hashlib
    import json

    from PIL import Image

    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.thumbnail_capture import _cache_read

    # Transport/cache fixture, not renderer proof.
    image_path = tmp_path / "fixture.png"
    Image.new("RGB", (512, 512), "red").save(image_path)
    metadata_path = tmp_path / "fixture.json"
    metadata_path.write_text(
        json.dumps({"sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(), "capture": {"target": "/Fixture"}})
    )
    assert _cache_read(image_path, metadata_path, 512)[1]["target"] == "/Fixture"
    assert _cache_read(image_path, metadata_path, 1024) is None
    link = tmp_path / "link.png"
    link.symlink_to(image_path)
    assert _cache_read(link, metadata_path, 512) is None
    image_path.write_bytes(b"corrupt")
    assert _cache_read(image_path, metadata_path, 512) is None


def test_thumbnail_partial_success_and_cross_scene_raw_reuse(tmp_path, monkeypatch):
    import sys

    from PIL import Image
    from pxr import Usd, UsdGeom

    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp import thumbnail_capture as capture

    usd_path = tmp_path / "fixture.usda"
    stage = Usd.Stage.CreateNew(str(usd_path))
    cube = UsdGeom.Cube.Define(stage, "/Root")
    stage.SetDefaultPrim(cube.GetPrim())
    stage.GetRootLayer().Save()
    selection = SimpleNamespace(clear_selected_prim_paths=lambda: None)
    ctx = SimpleNamespace(open_stage=lambda _: True, get_stage=lambda: stage, get_selection=lambda: selection)
    fake_usd = SimpleNamespace(get_context=lambda: ctx)
    monkeypatch.setitem(sys.modules, "omni", SimpleNamespace(usd=fake_usd))
    monkeypatch.setitem(sys.modules, "omni.usd", fake_usd)

    def node(name):
        return SimpleNamespace(id=name, registry_name=name, params={})

    spec = SimpleNamespace(
        background=node("bg"), embodiment=node("robot"), objects=[node("broken")], object_references=[]
    )

    def construct(node, *args, **kwargs):
        if node.id == "broken":
            raise ValueError("constructor failed")
        return SimpleNamespace(usd_path=str(usd_path), name=node.id)

    monkeypatch.setattr(capture, "_construct_asset", construct)
    monkeypatch.setattr(capture, "wait_for_stage_load", lambda *a: None)
    monkeypatch.setattr(capture, "_ensure_default_lighting", lambda *a: None)
    monkeypatch.setattr(capture, "frame_targets", lambda *a, **kw: {"dimensions_m": [2, 2, 2], "view": kw["view"]})
    calls = []

    def png(app, path, **kwargs):
        calls.append(path)
        Image.new("RGB", (512, 512), "red").save(path)  # Cache fixture, never actual render evidence.
        return path.read_bytes()

    monkeypatch.setattr(capture, "capture_viewport_png", png)
    errors, timings, manifest = [], {}, {}
    options = {"resolution": 512}
    paths, _ = capture.render_thumbnails_with_app(
        None,
        spec,
        options=options,
        output_dir=tmp_path / "one",
        cache_dir=tmp_path / "cache",
        errors=errors,
        timings=timings,
        manifest=manifest,
    )
    assert set(paths) == {"bg", "robot"}
    assert errors[0]["id"] == "broken" and errors[0]["stage"] == "constructor"
    assert len(calls) == 2
    assert all(value >= 0 for value in timings.values())
    spec.relations = ["changed scene placement, not isolated geometry"]
    second, _ = capture.render_thumbnails_with_app(
        None,
        spec,
        options=options,
        output_dir=tmp_path / "two",
        cache_dir=tmp_path / "cache",
        manifest=manifest,
        asset_revision="different-whole-scene-bundle",
    )
    assert len(calls) == 2
    assert all(path.parent == tmp_path / "two" and not path.is_symlink() for path in second.values())
    assert all(manifest[node]["cache_hit"] for node in second)
    capture.render_thumbnails_with_app(
        None,
        spec,
        options={**options, "asset_views": {"robot": "side"}},
        output_dir=tmp_path / "three",
        cache_dir=tmp_path / "cache",
    )
    assert len(calls) == 3
    blocked = tmp_path / "cache" / (manifest["bg"]["cache_key"] + ".png")
    blocked.unlink()
    blocked.mkdir()
    errors = []
    fourth, _ = capture.render_thumbnails_with_app(
        None, spec, options=options, output_dir=tmp_path / "four", cache_dir=tmp_path / "cache", errors=errors
    )
    assert set(fourth) == {"bg", "robot"}
    assert any(error["id"] == "bg" and error["stage"] == "cache" for error in errors)


def test_stage_load_uses_completed_file_count_not_zero(monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp import kit_viewport

    monkeypatch.setattr(kit_viewport, "pump_app", lambda *a: None)
    status = iter([("loading", 3, 5), ("done", 5, 5), ("done", 5, 5), ("done", 5, 5)])
    context = SimpleNamespace(get_stage_loading_status=lambda: next(status))
    kit_viewport.wait_for_stage_load(None, context, max_updates=4)
    with pytest.raises(TimeoutError):
        kit_viewport.wait_for_stage_load(
            None, SimpleNamespace(get_stage_loading_status=lambda: ("loading", 2, 5)), max_updates=4
        )


def test_raw_cache_retention_is_bounded_and_does_not_follow_links(tmp_path):
    import os

    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.render_identity import prune_raw_cache

    for i in range(4):
        path = tmp_path / (format(i, "064x") + ".png")
        path.write_bytes(b"0123456789")
        path.with_suffix(".json").write_text("{}")
        os.utime(path, (i + 1, i + 1))
    other = tmp_path / "unrelated.png"
    other.write_bytes(b"owned elsewhere")
    link = tmp_path / ("a" * 64 + ".png")
    link.symlink_to(other)
    prune_raw_cache(tmp_path, max_entries=2, max_bytes=100)
    assert not (tmp_path / ("0" * 64 + ".png")).exists()
    assert not (tmp_path / ("0" * 64 + ".json")).exists()
    assert len([p for p in tmp_path.glob("*.png") if len(p.stem) == 64 and not p.is_symlink()]) == 2
    assert other.read_bytes() == b"owned elsewhere" and link.is_symlink()
