# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Immutable artifact tests on real local filesystems, without simulation."""

import hashlib
import json
import os
import stat

import pytest


def test_stage_promote_verified_read_retry(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea, ArtifactError

    binding = {"source_candidate_id": "candidate-1", "attempt_id": "attempt-1"}
    files = {"environment.yaml": b"scene: {}\n", "result.json": b"{}"}
    with ArtifactArea.create(tmp_path / "area", store_id="store", registry_id="registry") as area:
        manifest = area.stage("reservation-1", files, binding)
        digest = manifest.pop("digest")
        assert (
            digest
            == hashlib.sha256(
                json.dumps(
                    manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
                ).encode()
            ).hexdigest()
        )
        manifest["digest"] = digest
        assert manifest["binding"] == binding
        assert manifest["store_id"] == "store"
        assert manifest["registry_id"] == "registry"
        assert manifest["reservation_id"] == "reservation-1"
        assert area.stage("reservation-1", files, binding) == manifest
        relative = area.promote("reservation-1", "Family", "v1", manifest)
        assert relative == "final/Family/v1"
        assert area.verify(relative, manifest) == files
        assert area.read_file(relative, manifest, "environment.yaml") == files["environment.yaml"]
        assert area.promote("reservation-1", "Family", "v1", manifest) == relative
        other = area.stage("reservation-2", files, {**binding, "attempt_id": "attempt-2"})
        with pytest.raises(ArtifactError):
            area.promote("reservation-2", "Family", "v1", other)
        assert area.verify(relative, manifest) == files


@pytest.mark.parametrize(
    "files,binding",
    [
        ({"../escape.json": b"{}"}, {}),
        ({".env": b"secret"}, {}),
        ({"credentials.json": b"{}"}, {}),
        ({"private.yaml": b"{}"}, {}),
        ({"manifest.json": b"{}"}, {}),
        ({"a.txt": b"x"}, {}),
        ({"a.json": b"x" * (2 * 1024 * 1024 + 1)}, {}),
        ({f"f{i}.json": b"x" for i in range(17)}, {}),
        ({f"f{i}.json": b"x" * (2 * 1024 * 1024) for i in range(5)}, {}),
        ({"a.json": b"{}"}, {"value": float("nan")}),
        ({"a.json": b"{}"}, {"value": "x" * 65536}),
        ({"a.json": b"{}"}, {"value": (1, 2)}),
    ],
)
def test_stage_bounds_before_any_write(tmp_path, files, binding):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea, ArtifactError

    with ArtifactArea.create(tmp_path / "area", store_id="s", registry_id="r") as area:
        with pytest.raises(ArtifactError):
            area.stage("reservation", files, binding)
        assert list((tmp_path / "area" / "staging").iterdir()) == []


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "writable", "fifo", "tamper", "truncate"])
def test_open_and_verify_reject_hostile_managed_tree(tmp_path, attack):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea, ArtifactError

    root = tmp_path / "area"
    with ArtifactArea.create(root, store_id="s", registry_id="r") as area:
        manifest = area.stage("reservation", {"a.json": b"{}"}, {})
        relative = area.promote("reservation", "family", "v1", manifest)
        target = root / relative / "a.json"
        if attack in ("symlink", "hardlink", "fifo"):
            target.unlink()
            outside = tmp_path / "outside"
            outside.write_bytes(b"{}")
            if attack == "symlink":
                target.symlink_to(outside)
            elif attack == "hardlink":
                os.link(outside, target)
            else:
                os.mkfifo(target)
        elif attack == "writable":
            target.chmod(0o666)
        else:
            target.write_bytes(b"xx" if attack == "tamper" else b"")
        with pytest.raises(ArtifactError):
            area.verify(relative, manifest)
        with pytest.raises(ArtifactError):
            ArtifactArea.open(root, store_id="s", registry_id="r")


def test_manifest_paths_validated_before_filesystem_read(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea, ArtifactError

    with ArtifactArea.create(tmp_path / "area", store_id="s", registry_id="r") as area:
        manifest = area.stage("res", {"a.json": b"{}"}, {})
        manifest["files"] = {"../outside.json": {"size": 0, "sha256": "0" * 64}}
        manifest["digest"] = hashlib.sha256(
            json.dumps(
                {k: v for k, v in manifest.items() if k != "digest"}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        with pytest.raises(ArtifactError):
            area._validate_manifest(manifest)


def test_closed_area_rejects_use(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea, ArtifactError

    area = ArtifactArea.create(tmp_path / "area", store_id="s", registry_id="r")
    area.close()
    monkeypatch.chdir(tmp_path / "area")
    with pytest.raises(ArtifactError):
        area.stage("res", {"a.json": b"{}"}, {})


@pytest.mark.parametrize("location", ["root", "parent", "staging", "family"])
def test_symlink_directories_are_never_followed(tmp_path, location):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea, ArtifactError

    root = tmp_path / "area"
    outside = tmp_path / "outside"
    outside.mkdir()
    if location in ("root", "parent"):
        root.symlink_to(outside, target_is_directory=True)
        with pytest.raises(ArtifactError):
            ArtifactArea.create(root if location == "root" else root / "child", store_id="s", registry_id="r")
        assert list(outside.iterdir()) == []
        return
    with ArtifactArea.create(root, store_id="s", registry_id="r") as area:
        if location == "staging":
            (root / "staging").rmdir()
            (root / "staging").symlink_to(outside, target_is_directory=True)
            with pytest.raises(ArtifactError):
                area.stage("res", {"a.json": b"{}"}, {})
        else:
            manifest = area.stage("res", {"a.json": b"{}"}, {})
            (root / "final" / "family").symlink_to(outside, target_is_directory=True)
            with pytest.raises(ArtifactError):
                area.promote("res", "family", "v1", manifest)
        assert list(outside.iterdir()) == []


@pytest.mark.parametrize("identifier", ["../x", "a/b", " a", "a.", "", "ß", "a\\\\b"])
def test_literal_ids_rejected_without_folding(tmp_path, identifier):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea, ArtifactError

    with ArtifactArea.create(tmp_path / "area", store_id="s", registry_id="r") as area:
        with pytest.raises(ArtifactError):
            area.stage(identifier, {"a.json": b"{}"}, {})
        manifest = area.stage("res", {"a.json": b"{}"}, {})
        with pytest.raises(ArtifactError):
            area.promote("res", identifier, "v1", manifest)


def test_incomplete_stage_fsync_failure_cannot_commit_after_restart(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench import research_artifacts as artifacts

    root = tmp_path / "area"
    with artifacts.ArtifactArea.create(root, store_id="s", registry_id="r") as area:
        real_fsync = os.fsync

        def fail_file(fd):
            if stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("private fault details")
            real_fsync(fd)

        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", fail_file)
            with pytest.raises(artifacts.ArtifactError, match="^Artifact staging failed$"):
                area.stage("res", {"a.json": b"{}"}, {})
    with artifacts.ArtifactArea.open(root, store_id="s", registry_id="r") as area:
        with pytest.raises(artifacts.ArtifactError):
            area.stage("res", {"a.json": b"{}"}, {})
        assert list((root / "final").iterdir()) == []


def test_atomic_no_clobber_race_and_unavailable_fail_closed(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench import research_artifacts as artifacts

    root = tmp_path / "area"
    with artifacts.ArtifactArea.create(root, store_id="s", registry_id="r") as area:
        manifest = area.stage("res", {"a.json": b"{}"}, {})
        real_rename = artifacts._rename_noreplace

        def racing_rename(source_fd, source, target_fd, target):
            os.mkdir(target, dir_fd=target_fd)
            real_rename(source_fd, source, target_fd, target)

        with monkeypatch.context() as patch:
            patch.setattr(artifacts, "_rename_noreplace", racing_rename)
            with pytest.raises(artifacts.ArtifactError):
                area.promote("res", "family", "v1", manifest)
        assert list((root / "final" / "family" / "v1").iterdir()) == []
        assert (root / "staging" / "res" / "a.json").read_bytes() == b"{}"
        with monkeypatch.context() as patch:
            patch.setattr(artifacts.ctypes, "CDLL", lambda *a, **kw: object())
            with pytest.raises(artifacts.ArtifactError):
                area.promote("res", "family", "v2", manifest)
        assert not (root / "final" / "family" / "v2").exists()


def test_invalid_staging_manifest_is_safe_and_does_not_leak_fds(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea, ArtifactError

    root = tmp_path / "area"
    with ArtifactArea.create(root, store_id="s", registry_id="r") as area:
        area.stage("res", {"a.json": b"{}"}, {})
    (root / "staging" / "res" / "manifest.json").write_bytes(b"[]")
    count = len(os.listdir("/proc/self/fd"))
    for _ in range(10):
        with pytest.raises(ArtifactError):
            ArtifactArea.open(root, store_id="s", registry_id="r")
    assert len(os.listdir("/proc/self/fd")) == count


def test_promotion_parent_fsync_failure_reports_ambiguity_then_verifies_retry(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench import research_artifacts as artifacts

    root = tmp_path / "area"
    with artifacts.ArtifactArea.create(root, store_id="s", registry_id="r") as area:
        manifest = area.stage("res", {"a.json": b"{}"}, {})
        real_fsync = os.fsync

        def fail_after_rename(fd):
            if (root / "final" / "family" / "v1").exists():
                raise OSError("fault")
            real_fsync(fd)

        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", fail_after_rename)
            with pytest.raises(artifacts.ArtifactError):
                area.promote("res", "family", "v1", manifest)
        assert area.promote("res", "family", "v1", manifest) == "final/family/v1"
        assert area.verify("final/family/v1", manifest) == {"a.json": b"{}"}


def test_retry_syncs_manifest_after_ambiguous_file_fsync(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench import research_artifacts as artifacts

    with artifacts.ArtifactArea.create(tmp_path / "area", store_id="s", registry_id="r") as area:
        real_fsync = os.fsync

        def fail_manifest(fd):
            if os.readlink(f"/proc/self/fd/{fd}").endswith("manifest.json"):
                raise OSError("fault")
            real_fsync(fd)

        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", fail_manifest)
            with pytest.raises(artifacts.ArtifactError):
                area.stage("res", {"a.json": b"{}"}, {})
            # A matching retry must still fail until the unsynced file can sync.
            with pytest.raises(artifacts.ArtifactError):
                area.stage("res", {"a.json": b"{}"}, {})
        manifest = area.stage("res", {"a.json": b"{}"}, {})
        assert area.promote("res", "family", "v1", manifest) == "final/family/v1"


def test_explicit_bound_initialization(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea, ArtifactError

    root = tmp_path / "artifacts"
    with pytest.raises(ArtifactError):
        ArtifactArea.open(root, store_id="store", registry_id="registry")
    assert not root.exists()
    area = ArtifactArea.create(root, store_id="store", registry_id="registry")
    area.close()
    ArtifactArea.open(root, store_id="store", registry_id="registry").close()
    for store, registry in [("other", "registry"), ("store", "other")]:
        with pytest.raises(ArtifactError):
            ArtifactArea.open(root, store_id=store, registry_id=registry)
    with pytest.raises(ArtifactError):
        ArtifactArea.create(root, store_id="store", registry_id="registry")
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "old.json").write_bytes(b"{}")
    with pytest.raises(ArtifactError):
        ArtifactArea.create(legacy, store_id="store", registry_id="registry")
