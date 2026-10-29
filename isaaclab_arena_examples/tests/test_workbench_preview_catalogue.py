# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Durable preview cache tests with explicit, synthetic transport-only revisions."""

import base64
from pathlib import Path

import pytest

from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_service import SnapshotService

FIXTURE = Path(__file__).parents[2] / "isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC")


def peer(calls):
    def rpc(request, deadline, emit):
        calls.append(request)
        output = Path(request["output_dir"])
        output.mkdir(parents=True)
        scene = output / "scene.png"
        scene.write_bytes(PNG)
        return {"ok": True, "paths": {}, "scene": str(scene)}

    return rpc


def test_catalogue_uses_the_same_canonical_hash_as_document_validation(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents

    text = FIXTURE.read_text()
    validation = Documents(tmp_path / "documents").validate(text)
    service = SnapshotService(tmp_path / "previews")
    monkeypatch.setattr(service, "_rpc", peer([]))
    result = service.render(text, "hash-contract", lambda _: None)
    assert result["canonical_hash"] == validation["canonical_hash"]
    recovered = service.lookup(validation["canonical_hash"], allow_historical=True)
    assert recovered is not None
    assert recovered["cache_key"] == result["cache_key"]
    service.close()


def test_missing_catalogue_is_a_read_only_miss(tmp_path):
    service = SnapshotService(tmp_path)
    service._db_path.unlink()
    assert service.lookup("a" * 64) is None
    assert not service._db_path.exists()
    with pytest.raises(KeyError):
        service.artifact_path("a" * 32)
    assert not service._db_path.exists()
    service.close()


def test_startup_removes_expired_owned_outputs_without_gpu(tmp_path):
    import os

    service = SnapshotService(tmp_path)
    service.close()
    output = service.root / "renders" / ("e" * 32)
    output.mkdir(parents=True)
    (output / "crashed.png").write_bytes(PNG)
    os.utime(output, (0, 0))
    restored = SnapshotService(tmp_path)
    assert not output.exists()
    assert restored._process.proc is None
    restored.close()


def test_invalid_or_oversized_options_never_reach_rpc(tmp_path, monkeypatch):
    service = SnapshotService(tmp_path)
    monkeypatch.setattr(service, "_rpc", lambda *args: pytest.fail("Invalid options reached renderer"))
    for options in ([], False, {"asset_views": {f"node{i}": "top" for i in range(129)}}):
        with pytest.raises(ValueError):
            service.render(FIXTURE.read_text(), "invalid-options", lambda _: None, options)
    service.close()


def test_failed_renderer_cleans_output_and_preserves_structured_diagnostics(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_service import SnapshotError

    service = SnapshotService(tmp_path)
    errors = [{"id": "scene", "stage": "capture", "code": "camera_failed", "message": "No camera"}]

    def rpc(request, deadline, emit):
        output = Path(request["output_dir"])
        output.mkdir(parents=True)
        (output / "leftover.png").write_bytes(b"broken")
        return {"ok": False, "error": "No valid preview", "errors": errors, "timings": {"scene_s": 2.0}}

    monkeypatch.setattr(service, "_rpc", rpc)
    with pytest.raises(SnapshotError) as caught:
        service.render(FIXTURE.read_text(), "failed", lambda _: None)
    assert caught.value.errors == errors
    assert caught.value.timings["scene_s"] == 2.0
    assert not list((service.root / "renders").iterdir())
    service.close()


def test_cleanup_failure_does_not_leak_catalogue_lock(tmp_path, monkeypatch):
    service = SnapshotService(tmp_path)
    monkeypatch.setattr(service, "_rpc", peer([]))

    def failed_cleanup(now):
        raise OSError("Controlled storage failure")

    monkeypatch.setattr(service, "_cleanup", failed_cleanup)
    with pytest.raises(OSError):
        service.render(FIXTURE.read_text(), "failed-cleanup", lambda _: None)
    assert not service._lock.locked()
    service.close()


def test_retention_bounds_isolated_thumbnail_cache_and_published_bytes(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_service import SnapshotError

    service = SnapshotService(tmp_path, max_bytes=32)
    monkeypatch.setattr(service, "_rpc", peer([]))
    with pytest.raises(SnapshotError, match="budget"):
        service.render(FIXTURE.read_text(), "oversized", lambda _: None)
    assert not list(service.root.glob("*.png"))
    cache = service.root / "isolated-thumbnails"
    cache.mkdir()
    (cache / ("a" * 64 + ".png")).write_bytes(PNG)
    (cache / ("a" * 64 + ".json")).write_text("{}")
    service.cleanup()
    assert not list(cache.iterdir())
    service.close()


def test_renderer_identity_tracks_simapp_implementation(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import preview_identity

    root = tmp_path / "isaaclab_arena_examples/agentic_environment_generation"
    api = root / "web_api"
    api.mkdir(parents=True)
    for name in ("snapshot_worker.py", "snapshot_service.py", "preview_options.py", "preview_identity.py"):
        (api / name).write_text("# test source\n")
    simapp = root / "review_gui/simapp"
    simapp.mkdir(parents=True)
    source = simapp / "kit_viewport.py"
    source.write_text("# first camera implementation\n")
    monkeypatch.setattr(preview_identity, "__file__", str(api / "preview_identity.py"))
    first = preview_identity.renderer_revision()
    source.write_text("# changed camera implementation\n")
    assert preview_identity.renderer_revision() != first


def test_explicit_local_dependency_closure_invalidates_changed_bytes_and_rejects_remote(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import preview_identity
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_service import validated_spec

    canonical = validated_spec(FIXTURE.read_text()).to_dict()
    dependency = tmp_path / "texture.bin"
    dependency.write_bytes(b"first texture bytes")
    assets = [canonical["embodiment"], canonical["background"], *canonical["objects"]]
    bundles = {asset["registry_name"]: [dependency] for asset in assets}
    resolver = preview_identity.LocalAssetRevisions(bundles)
    first = resolver(canonical)
    assert isinstance(first, str) and len(first) == 64
    dependency.write_bytes(b"other texture bytes")
    assert resolver(canonical) != first
    dependency.unlink()
    assert resolver(canonical) is None
    dependency.symlink_to(FIXTURE)
    assert resolver(canonical) is None
    assert preview_identity.LocalAssetRevisions({})(canonical) is None
    remote = {asset["registry_name"]: ["https://example.invalid/unversioned.usd"] for asset in assets}
    assert preview_identity.LocalAssetRevisions(remote)(canonical) is None
    assert preview_identity.registry_asset_revision(canonical) is None


def test_retention_evicts_old_receipts_and_owned_orphans_without_following_symlinks(tmp_path, monkeypatch):
    import os
    import time

    service = SnapshotService(
        tmp_path, asset_revision=lambda spec: "test-v1", max_receipts=1, max_bytes=1024 * 1024, max_age_s=60
    )
    monkeypatch.setattr(service, "_rpc", peer([]))
    first = service.render(FIXTURE.read_text(), "first", lambda _: None)
    second = service.render(FIXTURE.read_text(), "second", lambda _: None, {"view": "front"})
    assert service.lookup(first["canonical_hash"]) is None
    with pytest.raises(KeyError):
        service.artifact_path(first["scene"]["artifact_id"])
    assert service.lookup(second["canonical_hash"], second["options"]) == second
    assert not list((service.root / "renders").glob("*/scene.png"))
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "important.png"
    protected.write_bytes(PNG)
    (service.root / ("a" * 32 + ".png")).symlink_to(protected)
    (service.root / "renders" / ("b" * 32)).symlink_to(outside, target_is_directory=True)
    orphan = service.root / ("c" * 32 + ".png")
    orphan.write_bytes(PNG)
    os.utime(orphan, (0, 0))
    stale_output = service.root / "renders" / ("d" * 32)
    stale_output.mkdir()
    (stale_output / "leftover.png").write_bytes(PNG)
    os.utime(stale_output, (0, 0))
    service.cleanup(now=time.time() + 120)
    assert not orphan.exists() and not stale_output.exists()
    assert protected.read_bytes() == PNG
    assert service.lookup(second["canonical_hash"], second["options"]) is None
    service.close()


def test_catalogue_survives_restart_invalidates_revision_options_and_missing_files(tmp_path, monkeypatch):
    revision = ["immutable-test-bundle-v1"]
    calls = []
    service = SnapshotService(tmp_path, asset_revision=lambda spec: revision[0], renderer_version="test-v1")
    monkeypatch.setattr(service, "_rpc", peer(calls))
    result = service.render(FIXTURE.read_text(), "job", lambda _: None)
    canonical_hash = result["canonical_hash"]
    assert result["cache_key"] != canonical_hash
    assert service.lookup(canonical_hash) == result
    service.close()
    service = SnapshotService(tmp_path, asset_revision=lambda spec: revision[0], renderer_version="test-v1")
    monkeypatch.setattr(service, "_rpc", lambda *args: pytest.fail("Lookup launched renderer"))
    before = service._db_path.read_bytes()
    assert service.lookup(canonical_hash) == result
    assert service._db_path.read_bytes() == before
    assert service.lookup(canonical_hash, {"view": "top"}) is None
    revision[0] = "immutable-test-bundle-v2"
    assert service.lookup(canonical_hash) is None
    revision[0] = "immutable-test-bundle-v1"
    service.renderer_version = "test-v2"
    assert service.lookup(canonical_hash) is None
    service.renderer_version = "test-v1"
    service.artifact_path(result["scene"]["artifact_id"]).unlink()
    assert service.lookup(canonical_hash) is None
    assert len(calls) == 1
    service.close()


def test_unversioned_catalogue_restores_read_only_history_but_render_never_reuses_it(tmp_path, monkeypatch):
    calls = []
    service = SnapshotService(tmp_path)
    monkeypatch.setattr(service, "_rpc", peer(calls))
    result = service.render(FIXTURE.read_text(), "first", lambda _: None)
    canonical_hash = result["canonical_hash"]
    service.close()
    service = SnapshotService(tmp_path)
    monkeypatch.setattr(service, "_rpc", lambda *args: pytest.fail("Lookup launched renderer"))
    monkeypatch.setattr(service, "cleanup", lambda: pytest.fail("Lookup ran cleanup"))
    before = service._db_path.read_bytes()
    historical = service.lookup(canonical_hash, allow_historical=True)
    assert historical is not None
    assert historical["freshness"] == "unverified_assets"
    assert historical["scene"] == result["scene"]
    assert service._db_path.read_bytes() == before
    assert service._process.proc is None
    assert service.lookup(canonical_hash) is None
    monkeypatch.setattr(service, "_rpc", peer(calls))
    stages = []
    second = service.render(FIXTURE.read_text(), "second", stages.append)
    assert len(calls) == 2 and "cache_hit" not in stages
    assert second["scene"]["artifact_id"] != result["scene"]["artifact_id"]
    service.close()


@pytest.mark.parametrize("invalidation", ["options", "renderer", "missing", "corrupt", "expired", "canonical", "known"])
def test_historical_retrieval_cannot_bypass_identity_artifacts_or_retention(tmp_path, monkeypatch, invalidation):
    import json
    import sqlite3

    service = SnapshotService(tmp_path, renderer_version="test-v1")
    monkeypatch.setattr(service, "_rpc", peer([]))
    result = service.render(FIXTURE.read_text(), "history", lambda _: None)
    canonical_hash = result["canonical_hash"]
    assert service.lookup(canonical_hash, allow_historical=True) is not None
    options = None
    if invalidation == "options":
        options = {"view": "top"}
    elif invalidation == "renderer":
        service.renderer_version = "test-v2"
    elif invalidation == "missing":
        service.artifact_path(result["scene"]["artifact_id"]).unlink()
    elif invalidation == "corrupt":
        service.artifact_path(result["scene"]["variants"]["thumbnail"]["artifact_id"]).write_bytes(b"corrupt")
    elif invalidation == "expired":
        with sqlite3.connect(service._db_path) as db:
            db.execute("UPDATE previews SET created=0")
    elif invalidation == "canonical":
        with sqlite3.connect(service._db_path) as db:
            db.execute("UPDATE previews SET canonical=?", (json.dumps({"changed": True}),))
    elif invalidation == "known":
        service.asset_revision = lambda spec: "now-known-v1"
    before = service._db_path.read_bytes()
    monkeypatch.setattr(service, "_rpc", lambda *args: pytest.fail("Lookup launched renderer"))
    assert service.lookup(canonical_hash, options, allow_historical=True) is None
    assert service._db_path.read_bytes() == before
    service.close()


@pytest.mark.parametrize("invalidation", ["changed", "missing"])
def test_known_dependency_invalidation_never_falls_back_to_older_unversioned_receipt(
    tmp_path, monkeypatch, invalidation
):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.preview_identity import LocalAssetRevisions
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_service import validated_spec

    service = SnapshotService(tmp_path, renderer_version="test-v1")
    monkeypatch.setattr(service, "_rpc", peer([]))
    old = service.render(FIXTURE.read_text(), "unversioned", lambda _: None)
    canonical = validated_spec(FIXTURE.read_text()).to_dict()
    dependency = tmp_path / "trusted-complete-bundle.usd"
    dependency.write_bytes(b"first local dependency")
    assets = [canonical["embodiment"], canonical["background"], *canonical["objects"]]
    resolver = LocalAssetRevisions({asset["registry_name"]: [dependency] for asset in assets})
    service.asset_revision = resolver
    known = service.render(FIXTURE.read_text(), "known", lambda _: None)
    assert service.lookup(known["canonical_hash"], allow_historical=True) == known
    assert known["cache_key"] != old["cache_key"]
    if invalidation == "changed":
        dependency.write_bytes(b"changed local dependency")
    else:
        dependency.unlink()
    service.close()
    service = SnapshotService(tmp_path, asset_revision=resolver, renderer_version="test-v1")
    monkeypatch.setattr(service, "_rpc", lambda *args: pytest.fail("Lookup launched renderer"))
    assert service.lookup(known["canonical_hash"], allow_historical=True) is None
    assert service.lookup(known["canonical_hash"]) is None
    service.close()


def test_legacy_unversioned_receipt_is_readable_without_freshness_field_or_index_mutation(tmp_path, monkeypatch):
    import json
    import sqlite3

    service = SnapshotService(tmp_path, renderer_version="test-v1")
    monkeypatch.setattr(service, "_rpc", peer([]))
    result = service.render(FIXTURE.read_text(), "legacy", lambda _: None)
    result.pop("freshness")
    with sqlite3.connect(service._db_path) as db:
        db.execute("UPDATE previews SET result=?", (json.dumps(result),))
    service.close()
    service = SnapshotService(tmp_path, renderer_version="test-v1")
    before = service._db_path.read_bytes()
    assert service.lookup(result["canonical_hash"], allow_historical=True) == {
        **result,
        "freshness": "unverified_assets",
    }
    assert service.lookup(result["canonical_hash"]) is None
    assert service._db_path.read_bytes() == before
    assert service._process.proc is None
    service.close()


def test_partial_render_preserves_valid_png_variants_and_timings(tmp_path, monkeypatch):
    from PIL import Image

    service = SnapshotService(tmp_path, asset_revision=lambda spec: "test-v1")

    def rpc(request, deadline, emit):
        assert request["options"] == {"view": "side", "resolution": 512, "asset_views": {}}
        assert request["renderer_version"] == service.renderer_version
        output = Path(request["output_dir"])
        output.mkdir(parents=True)
        good = output / "good.png"
        Image.new("RGB", (512, 256), "red").save(good)
        bad = output / "bad.png"
        bad.write_bytes(b"not PNG")
        return {
            "ok": True,
            "paths": {"mug_ycb_robolab": str(good), "bowl_ycb_robolab": str(bad)},
            "scene": None,
            "errors": [{"id": "scene", "stage": "render", "code": "camera_failed", "message": "Camera failed"}],
            "timings": {"render_s": 1.25, "invalid": -1, "nan": float("nan")},
        }

    monkeypatch.setattr(service, "_rpc", rpc)
    result = service.render(FIXTURE.read_text(), "partial", lambda _: None, {"view": "side", "resolution": 512})
    assert result["scene"] is None and result["partial"] is True
    assert {asset["id"] for asset in result["assets"]} == {"mug_ycb_robolab"}
    entry = result["assets"][0]
    assert entry["artifact_id"] == entry["variants"]["full"]["artifact_id"]
    for name, size in [("full", (512, 256)), ("thumbnail", (256, 128))]:
        variant = entry["variants"][name]
        assert (variant["width"], variant["height"]) == size
        with Image.open(service.artifact_path(variant["artifact_id"])) as image:
            image.load()
            assert image.format == "PNG" and image.size == size
    assert any(error["id"] == "bowl_ycb_robolab" and error["stage"] == "publish" for error in result["errors"])
    assert any(error["code"] == "camera_failed" for error in result["errors"])
    assert result["timings"]["render_s"] == 1.25
    assert result["timings"]["total_s"] >= 0
    assert all(result["timings"][key] >= 0 for key in ("queue_s", "validation_s", "lookup_s", "rpc_s", "publish_s"))
    assert "invalid" not in result["timings"] and "nan" not in result["timings"]
    assert service.lookup(result["canonical_hash"], result["options"]) == result
    service.artifact_path(entry["variants"]["thumbnail"]["artifact_id"]).write_bytes(b"corrupt")
    assert service.lookup(result["canonical_hash"], result["options"]) is None
    service.close()
