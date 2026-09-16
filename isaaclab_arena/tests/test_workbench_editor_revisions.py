# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Durable editor revision contracts; run only in the isolated CPU test sandbox."""

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
from isaaclab_arena.agentic_environment_generation.workbench import editor_revision_storage as storage


@pytest.fixture
def source_bundle(tmp_path):
    """Copy only approved YAML into a fresh source tree and keep state separate."""
    fixture = Path(__file__).parent / "test_data/minimal_maple_table_env_graph.yaml"
    spec = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    root = tmp_path / "source"
    directory = root / "generated_envs"
    directory.mkdir(parents=True)
    source = directory / "scene.yaml"
    include = directory / "scene-assets.yaml"
    source.write_text("# authored café 🌍\nexternal_yaml: scene-assets.yaml\n", encoding="utf-8")
    include.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    documents = Documents(state, root=root)
    source_id = next(row["id"] for row in documents.index() if row["source"] == "generated_envs/scene.yaml")
    return documents, source_id, source, include, state, root


def test_exact_save_retry_survives_restart_and_mutable_include_changes(source_bundle):
    documents, source_id, source, include, state, root = source_bundle
    original_source = source.read_bytes()
    original_include = include.read_bytes()
    loaded = documents.load(source_id)
    assert loaded["validation"]["valid"]
    args = (loaded["yaml_text"], loaded["document_id"], loaded["source_hash"])
    first = documents.save(*args, idempotency_key="save:test-1")
    expected_request = hashlib.sha256(
        json.dumps(["editor-save/v1", *args], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert set(first) == {"schema_version", "idempotency_key", "request_sha256", "state", "revision"}
    assert first["schema_version"] == 1
    assert first["idempotency_key"] == "save:test-1"
    assert first["request_sha256"] == expected_request
    assert first["state"] == "committed"
    revision = first["revision"]
    assert revision["open_source"] == {
        "kind": "editor_revision", "id": "editor-revision:" + revision["revision_id"]
    }
    assert source.read_bytes() == original_source
    assert include.read_bytes() == original_include
    before = {str(path.relative_to(state)): path.read_bytes() for path in state.rglob("*") if path.is_file()}

    source.write_text("not: the original source\n", encoding="utf-8")
    include.write_text("not: the original include\n", encoding="utf-8")
    restarted = Documents(state, root=root)
    assert restarted.save(*args, idempotency_key="save:test-1") == first
    assert restarted.save_request("save:test-1") == first
    after = {str(path.relative_to(state)): path.read_bytes() for path in state.rglob("*") if path.is_file()}
    assert after == before

    opened = restarted.load(revision["open_source"]["id"])
    assert opened["yaml_text"] == loaded["yaml_text"]
    assert opened["source_hash"] == revision["source_hash"]
    assert opened["validation"]["canonical_hash"] == revision["canonical_hash"]
    assert opened["validation"]["valid"]
    assert restarted.frozen[opened["document_id"]] == {"scene-assets.yaml": original_include.decode("utf-8")}
    assert restarted.validate(opened["yaml_text"], opened["document_id"])["valid"]
    assert len(opened["document_id"]) == 32
    again = restarted.load(revision["open_source"]["id"])
    assert again["document_id"] != opened["document_id"]
    rows = [row for row in restarted.index() if row.get("kind") == "editor_revision"]
    assert [row["id"] for row in rows] == [revision["open_source"]["id"]]
    assert restarted.download(revision["revision_id"]).startswith("# Flattened immutable Arena editor export")


@pytest.mark.parametrize("mutation", ["nested", "object", "cycle", "deep", "tuple", "unicode"])
@pytest.mark.parametrize("replay", [False, True])
def test_protection_is_reject_only_and_never_changes_durable_bytes(source_bundle, mutation, replay):
    documents, source_id, _, _, state, _ = source_bundle
    loaded = documents.load(source_id)
    args = (loaded["yaml_text"], loaded["document_id"], loaded["source_hash"])
    if replay:
        documents.save(*args, idempotency_key="protected")
    before = {str(p): p.read_bytes() for p in state.rglob("*") if p.is_file()}

    def protect(bundle):
        if mutation == "nested":
            bundle["snapshot"]["includes"]["scene-assets.yaml"] += "# changed\n"
        elif mutation == "object":
            bundle["receipt"]["revision"]["open_source"] = object()
        elif mutation == "cycle":
            bundle["snapshot"]["includes"]["cycle"] = bundle
        elif mutation == "deep":
            nested = {}
            bundle["extra"] = nested
            for _ in range(10000):
                child = {}
                nested["next"] = child
                nested = child
        elif mutation == "tuple":
            bundle["snapshot"]["includes"] = ()
        else:
            bundle["snapshot"]["yaml_text"] = "\ud800"

    with pytest.raises(ValueError, match="^Editor protection callback changed bundle$"):
        documents.save(*args, idempotency_key="protected", protect_snapshot=protect)
    assert {str(p): p.read_bytes() for p in state.rglob("*") if p.is_file()} == before


def test_all_committed_response_paths_recheck_current_full_bundle_protection(source_bundle):
    documents, source_id, source, include, state, root = source_bundle
    loaded = documents.load(source_id)
    args = (loaded["yaml_text"], loaded["document_id"], loaded["source_hash"])
    receipt = documents.save(*args, idempotency_key="current-protection")
    revision = receipt["revision"]
    source.unlink()
    include.unlink()
    documents = Documents(state, root=root)
    seen = []
    rejection = RuntimeError("secret rejected")

    def reject(bundle):
        assert set(bundle) == {"receipt", "snapshot", "export_yaml"}
        assert bundle["snapshot"]["includes"]["scene-assets.yaml"]
        assert bundle["receipt"] == receipt
        seen.append(True)
        raise rejection

    operations = [
        lambda: documents.save(*args, idempotency_key="current-protection", protect_snapshot=reject),
        lambda: documents.save_request("current-protection", protect_snapshot=reject),
        lambda: documents.load(revision["open_source"]["id"], protect_snapshot=reject),
        lambda: documents.download(revision["revision_id"], protect_snapshot=reject),
        lambda: documents.index(protect_snapshot=reject),
    ]
    for operation in operations:
        with pytest.raises(RuntimeError) as caught:
            operation()
        assert caught.value is rejection
    assert len(seen) == len(operations)


@pytest.mark.parametrize("different", [False, True])
def test_concurrent_same_key_has_one_commit_and_exact_duplicate_or_conflict(source_bundle, different):
    documents, source_id, _, _, state, root = source_bundle
    first = documents.load(source_id)
    other = Documents(state, root=root)
    second = other.load(source_id)
    entered, contender = threading.Event(), threading.Event()

    def pause(bundle):
        entered.set()
        assert contender.wait(3)
        time.sleep(0.05)

    def compete():
        assert entered.wait(3)
        contender.set()
        try:
            return other.save(second["yaml_text"] + ("# different\n" if different else ""),
                              second["document_id"], second["source_hash"], idempotency_key="race")
        except ValueError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(documents.save, first["yaml_text"], first["document_id"], first["source_hash"],
                        idempotency_key="race", protect_snapshot=pause)
        b = pool.submit(compete)
        receipt, duplicate = a.result(timeout=10), b.result(timeout=10)
    if different:
        assert isinstance(duplicate, ValueError)
        assert str(duplicate) == "Editor idempotency key conflict"
    else:
        assert duplicate == receipt
    assert documents.save_request("race") == receipt
    assert len(list(state.rglob("manifest.json"))) == 1


@pytest.mark.parametrize("change", ["root", "include"])
@pytest.mark.parametrize("with_expected", [False, True])
def test_fresh_save_checks_all_frozen_source_bytes_even_unused_in_draft(source_bundle, change, with_expected):
    documents, source_id, source, include, state, _ = source_bundle
    loaded = documents.load(source_id)
    flattened = include.read_text(encoding="utf-8")
    target = source if change == "root" else include
    target.write_text(target.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        documents.save(flattened, loaded["document_id"], loaded["source_hash"] if with_expected else None,
                       idempotency_key="fresh-cas")
    assert not list(state.rglob("manifest.json"))


def test_catalogue_uses_discovered_file_kind_and_source_origin(source_bundle):
    documents, source_id, _, _, _, _ = source_bundle
    assert all(row["kind"] == "discovered_file" for row in documents.index())
    assert documents.load(source_id)["source_origin"] == {"kind": "discovered_file", "id": source_id}


def test_callback_cannot_race_source_cas_before_commit(source_bundle):
    documents, source_id, _, include, state, _ = source_bundle
    loaded = documents.load(source_id)

    def change_source(bundle):
        include.write_text("# changed during protection\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed"):
        documents.save(loaded["yaml_text"], loaded["document_id"], loaded["source_hash"],
                       idempotency_key="cas-race", protect_snapshot=change_source)
    assert not list(state.rglob("manifest.json"))


def test_immutable_reopened_children_and_old_views_survive_restart_without_source_paths(source_bundle):
    documents, source_id, source, include, state, root = source_bundle
    loaded = documents.load(source_id)
    receipt = documents.save(loaded["yaml_text"], loaded["document_id"], loaded["source_hash"], idempotency_key="parent")
    source.unlink()
    include.unlink()
    restarted = Documents(state, root=root)
    opened = restarted.load(receipt["revision"]["open_source"]["id"])
    another = restarted.load(receipt["revision"]["open_source"]["id"])
    assert opened["document_id"] != another["document_id"]
    assert restarted.has_document(opened["document_id"])
    assert opened["document_id"] not in restarted.paths
    assert restarted.resolve_view(opened["document_id"])["origin"] == receipt["revision"]["open_source"]
    protected = []
    def protect(bundle):
        protected.append(bundle)
    reloaded = restarted.load(opened["document_id"], protect_snapshot=protect)
    assert reloaded == opened  # Reloading an issued capability retains that UUID, not a new origin/view.
    assert protected[0]["receipt"] == receipt
    assert protected[0]["snapshot"]["includes"] == restarted.frozen[opened["document_id"]]
    assert opened["document_id"] not in restarted.paths
    child = restarted.save(opened["yaml_text"] + "# child\n", opened["document_id"], opened["source_hash"],
                           idempotency_key="child")
    assert restarted.validate(opened["yaml_text"], opened["document_id"])["valid"]
    assert child["revision"]["revision_id"] != receipt["revision"]["revision_id"]
    final = Documents(state, root=root)
    assert not final.has_document(opened["document_id"])
    assert final.load(child["revision"]["open_source"]["id"])["validation"]["valid"]
    assert final.save_request("parent") == receipt
    assert final.save_request("child") == child


@pytest.mark.parametrize("changed", ["root", "unused_include"])
def test_issued_view_reload_rejects_resealed_changed_bytes_without_rebinding(source_bundle, changed):
    documents, source_id, _, include, state, _ = source_bundle
    loaded = documents.load(source_id)
    # Retain an unused include, so both root and include identities are independently fenced.
    receipt = documents.save(include.read_text(), loaded["document_id"], loaded["source_hash"], idempotency_key="view-binding")
    opened = documents.load(receipt["revision"]["open_source"]["id"])
    view_id = opened["document_id"]
    old_view = dict(documents.views[view_id])
    old_includes = dict(documents.frozen[view_id])
    directory = state / "editor-revision-bundles" / receipt["revision"]["revision_id"]
    manifest = json.loads((directory / "manifest.json").read_bytes())
    snapshot = json.loads((directory / "snapshot.json").read_bytes())
    if changed == "root":
        snapshot["yaml_text"] += "# resealed change\n"
        snapshot["source_hash"] = hashlib.sha256(snapshot["yaml_text"].encode()).hexdigest()
        manifest["receipt"]["revision"].update(yaml_text=snapshot["yaml_text"], source_hash=snapshot["source_hash"])
        manifest["receipt"]["request_sha256"] = storage.request_hash(
            snapshot["yaml_text"], snapshot["document_id"], snapshot["expected_source_hash"])
    else:
        snapshot["includes"]["scene-assets.yaml"] += "# resealed include change\n"
    raw = storage.encode(snapshot)
    (directory / "snapshot.json").write_bytes(raw)
    manifest["files"]["snapshot.json"] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    (directory / "manifest.json").write_bytes(storage.encode(manifest))
    with pytest.raises(storage.RevisionError, match="Issued editor revision view changed"):
        documents.load(view_id)
    assert documents.views[view_id] == old_view
    assert documents.frozen[view_id] == old_includes
    assert documents.validate(opened["yaml_text"], view_id)["canonical_hash"] == opened["validation"]["canonical_hash"]


@pytest.mark.parametrize("file", ["manifest.json", "snapshot.json", "export.yaml"])
@pytest.mark.parametrize("damage", ["truncate", "symlink", "oversize", "remove", "hardlink", "fifo"])
def test_corrupt_committed_bundle_is_never_a_receipt_or_download(source_bundle, file, damage):
    documents, source_id, _, _, state, _ = source_bundle
    loaded = documents.load(source_id)
    args = (loaded["yaml_text"], loaded["document_id"], loaded["source_hash"])
    receipt = documents.save(*args, idempotency_key="corrupt")
    revision = receipt["revision"]
    target = state / "editor-revision-bundles" / revision["revision_id"] / file
    if damage == "truncate":
        target.write_bytes(b"{")
    elif damage == "oversize":
        with target.open("wb") as handle:
            handle.truncate(storage.MAX_BUNDLE_FILE + 1)
    elif damage == "remove":
        target.unlink()
    elif damage == "fifo":
        target.unlink()
        os.mkfifo(target, mode=0o600)
    else:
        external = state / "external"
        external.write_bytes(target.read_bytes())
        target.unlink()
        if damage == "symlink":
            target.symlink_to(external)
        else:
            os.link(external, target)
    before = {str(p): p.read_bytes() for p in state.rglob("*") if p.is_file()}
    for operation in (
        lambda: documents.save_request("corrupt"),
        lambda: documents.save(*args, idempotency_key="corrupt"),
        lambda: documents.load(revision["open_source"]["id"]),
        lambda: documents.download(revision["revision_id"]),
    ):
        with pytest.raises(storage.RevisionError):
            operation()
    assert {str(p): p.read_bytes() for p in state.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("phase", ["snapshot", "export", "manifest-file", "promoted-directory"])
def test_fsync_faults_leave_partial_or_reconcilable_commits_without_overwrite(source_bundle, monkeypatch, phase):
    documents, source_id, _, _, state, root = source_bundle
    loaded = documents.load(source_id)
    args = (loaded["yaml_text"], loaded["document_id"], loaded["source_hash"])
    real_sync = os.fsync
    failed = []

    def fail_sync(fd):
        name = os.readlink(f"/proc/self/fd/{fd}")
        match = ((phase == "snapshot" and name.endswith("/snapshot.json"))
                 or (phase == "export" and name.endswith("/export.yaml"))
                 or (phase == "manifest-file" and "/commit-" in name)
                 or (phase == "promoted-directory" and name.endswith(storage.key_id("sync"))
                     and (Path(name) / "manifest.json").exists()))
        if match and not failed:
            failed.append(name)
            raise OSError("injected fsync fault")
        return real_sync(fd)

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "fsync", fail_sync)
        with pytest.raises(storage.RevisionUncertain):
            documents.save(*args, idempotency_key="sync")
    assert failed
    before = {str(p): p.read_bytes() for p in state.rglob("*") if p.is_file()}
    restarted = Documents(state, root=root)
    if phase == "promoted-directory":
        synced = []
        def record_sync(fd):
            synced.append(os.readlink(f"/proc/self/fd/{fd}"))
            return real_sync(fd)
        with monkeypatch.context() as patcher:
            patcher.setattr(os, "fsync", record_sync)
            receipt = restarted.save(*args, idempotency_key="sync")
        assert receipt["state"] == "committed"
        for filename in ("snapshot.json", "export.yaml", "manifest.json"):
            assert any(path.endswith("/" + filename) for path in synced)
        assert str(state) in synced
    else:
        with pytest.raises(storage.RevisionError, match="Incomplete or corrupt"):
            restarted.save(*args, idempotency_key="sync")
        assert not list(state.rglob("manifest.json"))
    assert {str(p): p.read_bytes() for p in state.rglob("*") if p.is_file()} == before


def test_failed_retry_resync_is_uncertain_not_success_or_corruption(source_bundle, monkeypatch):
    documents, source_id, _, _, _, _ = source_bundle
    loaded = documents.load(source_id)
    documents.save(loaded["yaml_text"], loaded["document_id"], loaded["source_hash"], idempotency_key="retry-sync")
    def fail(fd):
        raise OSError("sync unavailable")
    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(storage.RevisionUncertain):
        documents.save_request("retry-sync")


@pytest.mark.parametrize("phase", ["payload-partial", "manifest-partial", "before-promotion", "after-promotion"])
def test_abrupt_interruption_retains_partial_evidence_or_exact_committed_replay(source_bundle, monkeypatch, phase):
    documents, source_id, _, _, state, root = source_bundle
    loaded = documents.load(source_id)
    args = (loaded["yaml_text"], loaded["document_id"], loaded["source_hash"])
    real_write, real_promote = storage.artifacts._write, storage.artifacts._rename_noreplace
    interrupted = []

    def write(fd, name, data):
        if ((phase == "payload-partial" and name == "snapshot.json")
                or (phase == "manifest-partial" and name.startswith("commit-"))):
            real_write(fd, name, data[:7])
            interrupted.append(True)
            raise SystemExit("simulated abrupt stop")
        return real_write(fd, name, data)

    def promote(*args):
        if phase == "before-promotion":
            interrupted.append(True)
            raise SystemExit("simulated abrupt stop")
        result = real_promote(*args)
        if phase == "after-promotion":
            interrupted.append(True)
            raise SystemExit("simulated abrupt stop")
        return result

    with monkeypatch.context() as patcher:
        patcher.setattr(storage.artifacts, "_write", write)
        patcher.setattr(storage.artifacts, "_rename_noreplace", promote)
        with pytest.raises(SystemExit):
            documents.save(*args, idempotency_key="interrupted")
    assert interrupted
    before = {str(p): p.read_bytes() for p in state.rglob("*") if p.is_file()}
    assert before
    restarted = Documents(state, root=root)
    if phase == "after-promotion":
        receipt = restarted.save(*args, idempotency_key="interrupted")
        assert receipt == restarted.save_request("interrupted")
    else:
        with pytest.raises(storage.RevisionError):
            restarted.save_request("interrupted")
        with pytest.raises(storage.RevisionError):
            restarted.save(*args, idempotency_key="interrupted")
        assert not [row for row in restarted.index() if row["kind"] == "editor_revision"]
    assert {str(p): p.read_bytes() for p in state.rglob("*") if p.is_file()} == before


def test_catalogue_capacity_is_checked_before_commit(source_bundle, monkeypatch):
    documents, source_id, _, _, state, _ = source_bundle
    loaded = documents.load(source_id)
    args = (loaded["yaml_text"], loaded["document_id"], loaded["source_hash"])
    monkeypatch.setattr(storage, "MAX_REVISIONS", 1)
    first = documents.save(*args, idempotency_key="capacity-1")
    before = {str(p): p.read_bytes() for p in state.rglob("*") if p.is_file()}
    with pytest.raises(storage.RevisionError, match="bounds"):
        documents.save(*args, idempotency_key="capacity-2")
    assert documents.save_request("capacity-1") == first
    assert {str(p): p.read_bytes() for p in state.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("location", ["area", "revision", "state"])
def test_symlinked_bundle_ancestors_fail_closed(source_bundle, location):
    documents, source_id, _, _, state, root = source_bundle
    loaded = documents.load(source_id)
    receipt = documents.save(loaded["yaml_text"], loaded["document_id"], loaded["source_hash"], idempotency_key="ancestors")
    area = state / "editor-revision-bundles"
    target = {"area": area, "revision": area / receipt["revision"]["revision_id"], "state": state}[location]
    moved = target.with_name(target.name + "-real")
    target.rename(moved)
    target.symlink_to(moved, target_is_directory=True)
    with pytest.raises(storage.RevisionError):
        Documents(state, root=root).save_request("ancestors")


@pytest.mark.parametrize("key", ["", "../escape", "has space", "a" * 129, True, 3, "café"])
def test_invalid_keys_never_write(source_bundle, key):
    documents, _, _, include, state, _ = source_bundle
    with pytest.raises(storage.RevisionError):
        documents.save(include.read_text(encoding="utf-8"), idempotency_key=key)
    assert not list(state.iterdir())


def test_invalid_unicode_and_oversize_yaml_are_bounded(source_bundle):
    documents, _, _, _, state, _ = source_bundle
    for text in ("\ud800", "#" + "x" * (256 * 1024)):
        with pytest.raises(storage.RevisionError):
            documents.save(text, idempotency_key="invalid-text")
    assert not list(state.rglob("manifest.json"))


def test_protection_retained_copies_and_return_values_cannot_rewrite_replay(source_bundle):
    documents, source_id, _, _, _, _ = source_bundle
    loaded = documents.load(source_id)
    retained = []
    def protect(bundle):
        bundle["snapshot"]["yaml_text"] = bundle["snapshot"]["yaml_text"]
        retained.append(bundle)
    receipt = documents.save(loaded["yaml_text"], loaded["document_id"], loaded["source_hash"],
                             idempotency_key="detached", protect_snapshot=protect)
    original = json.loads(json.dumps(receipt))
    for bundle in retained:
        bundle["receipt"]["revision"]["yaml_text"] = "tampered"
    assert receipt == original
    receipt["revision"]["yaml_text"] = "tampered response"
    assert documents.save_request("detached") == original


@pytest.mark.parametrize("damage", ["schema-bool", "receipt-schema-float", "request-hash", "receipt-extra",
                                    "descriptor-bool", "descriptor-size", "filename", "snapshot-hash", "export-content"])
def test_self_consistent_manifest_edits_still_require_strict_bundle_bindings(source_bundle, damage):
    documents, source_id, _, _, state, _ = source_bundle
    loaded = documents.load(source_id)
    receipt = documents.save(loaded["yaml_text"], loaded["document_id"], loaded["source_hash"], idempotency_key="strict")
    directory = state / "editor-revision-bundles" / receipt["revision"]["revision_id"]
    manifest = json.loads((directory / "manifest.json").read_bytes())
    if damage == "schema-bool":
        manifest["schema_version"] = True
    elif damage == "receipt-schema-float":
        manifest["receipt"]["schema_version"] = 1.0
    elif damage == "request-hash":
        manifest["receipt"]["request_sha256"] = "0" * 64
    elif damage == "receipt-extra":
        manifest["receipt"]["extra"] = "unexpected"
    elif damage == "descriptor-bool":
        manifest["files"]["snapshot.json"]["bytes"] = True
    elif damage == "descriptor-size":
        manifest["files"]["snapshot.json"]["bytes"] = storage.MAX_BUNDLE_FILE + 1
    elif damage == "filename":
        manifest["files"]["../snapshot.json"] = manifest["files"].pop("snapshot.json")
    else:
        filename = "snapshot.json" if damage == "snapshot-hash" else "export.yaml"
        if damage == "snapshot-hash":
            snapshot = json.loads((directory / filename).read_bytes())
            snapshot["source_hash"] = "0" * 64
            raw = storage.encode(snapshot)
        else:
            raw = b"# bogus flattened export\n"
        (directory / filename).write_bytes(raw)
        manifest["files"][filename] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    (directory / "manifest.json").write_bytes(storage.encode(manifest))
    with pytest.raises(storage.RevisionError):
        documents.save_request("strict")


def test_manifest_promotion_cannot_replace_a_competing_empty_file(source_bundle, monkeypatch):
    documents, source_id, _, _, state, _ = source_bundle
    loaded = documents.load(source_id)
    real_promote = storage.artifacts._rename_noreplace
    def compete(source_fd, source, target_fd, target):
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=target_fd)
        os.close(fd)
        return real_promote(source_fd, source, target_fd, target)
    monkeypatch.setattr(storage.artifacts, "_rename_noreplace", compete)
    with pytest.raises(storage.RevisionUncertain):
        documents.save(loaded["yaml_text"], loaded["document_id"], loaded["source_hash"], idempotency_key="no-replace")
    manifest = next(state.rglob("manifest.json"))
    assert manifest.read_bytes() == b""
    with pytest.raises(storage.RevisionError):
        documents.save_request("no-replace")
    assert manifest.read_bytes() == b""


def test_legacy_exports_remain_distinct_from_receipts_and_obey_protection(source_bundle):
    documents, source_id, _, _, state, root = source_bundle
    loaded = documents.load(source_id)
    args = (loaded["yaml_text"], loaded["document_id"], loaded["source_hash"])
    rejected = RuntimeError("secret rejected")
    def reject(bundle):
        assert bundle["receipt"] is None
        assert bundle["snapshot"]["includes"]
        raise rejected
    with pytest.raises(RuntimeError) as caught:
        documents.save(*args, protect_snapshot=reject)
    assert caught.value is rejected
    assert not list(state.rglob("snapshot.json"))
    legacy = documents.save(*args)
    assert set(legacy) == {"revision_id", "yaml_text", "source_hash", "canonical_hash", "download_url"}
    restarted = Documents(state, root=root)
    assert restarted.download(legacy["revision_id"])
    with pytest.raises(RuntimeError) as caught:
        restarted.download(legacy["revision_id"], protect_snapshot=reject)
    assert caught.value is rejected
    with pytest.raises(KeyError):
        restarted.save_request(legacy["revision_id"])
    with pytest.raises(KeyError):
        restarted.load("editor-revision:" + legacy["revision_id"])
    assert not [row for row in restarted.index() if row["kind"] == "editor_revision"]


def test_area_creation_fsync_failure_is_uncertain_and_exact_retry_reconciles(source_bundle, monkeypatch):
    documents, source_id, _, _, state, _ = source_bundle
    loaded = documents.load(source_id)
    args = (loaded["yaml_text"], loaded["document_id"], loaded["source_hash"])
    real_sync = os.fsync
    def fail(fd):
        if os.readlink(f"/proc/self/fd/{fd}") == str(state):
            raise OSError("injected state directory sync fault")
        return real_sync(fd)
    with monkeypatch.context() as patcher:
        patcher.setattr(os, "fsync", fail)
        with pytest.raises(storage.RevisionUncertain):
            documents.save(*args, idempotency_key="area-sync")
    assert not list(state.rglob("manifest.json"))
    assert documents.save(*args, idempotency_key="area-sync") == documents.save_request("area-sync")


def test_lock_wait_is_bounded_and_does_not_damage_committed_receipt(source_bundle, monkeypatch):
    documents, source_id, _, _, _, _ = source_bundle
    loaded = documents.load(source_id)
    first = documents.save(loaded["yaml_text"], loaded["document_id"], loaded["source_hash"], idempotency_key="busy")
    monkeypatch.setattr(storage, "LOCK_SECONDS", 0.02)
    with documents.revisions.area(lock=True):
        with pytest.raises(storage.RevisionBusy):
            documents.save_request("busy")
    assert documents.save_request("busy") == first


def test_request_bounds_are_rejected_before_storage_is_created(source_bundle):
    documents, _, _, include, state, _ = source_bundle
    text = include.read_text(encoding="utf-8")
    requests = [("#" + "x" * (256 * 1024), None, None), (text, "bad-view", None),
                (text, "0" * 32, "ABC"), ("\ud800", None, None)]
    for args in requests:
        with pytest.raises(storage.RevisionError):
            documents.save(*args, idempotency_key="invalid-request")
    assert not list(state.iterdir())
