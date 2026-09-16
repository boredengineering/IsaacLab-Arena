# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Manual research persistence: real private files/SQLite, no generation runtime."""
import hashlib
import json
from contextlib import closing
import shutil

import pytest

from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
from isaaclab_arena.tests.test_workbench_editor_revisions import source_bundle  # noqa: F401


def saved(source_bundle):
    documents, source_id, source, include, state, root = source_bundle
    loaded = documents.load(source_id)
    receipt = documents.save(loaded["yaml_text"], loaded["document_id"], loaded["source_hash"],
                             idempotency_key="manual-source")
    return documents, receipt


def test_public_verified_bundle_is_detached_exact_and_versioned(source_bundle):
    documents, receipt = saved(source_bundle)
    revision_id = receipt["revision"]["revision_id"]
    bundle = documents.load_revision_bundle(revision_id)
    assert set(bundle) == {"schema_version", "codec", "receipt", "snapshot", "export_yaml", "bundle_sha256"}
    assert bundle["schema_version"] == 1
    assert bundle["codec"] == "arena-editor-bundle/v1"
    assert bundle["receipt"] == receipt
    assert bundle["snapshot"]["includes"] == {"scene-assets.yaml": source_bundle[3].read_text()}
    exact = [bundle["codec"], bundle["receipt"], bundle["snapshot"], bundle["export_yaml"]]
    encoded = json.dumps(exact, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    assert bundle["bundle_sha256"] == hashlib.sha256(encoded).hexdigest()
    assert Documents.verify_revision_bundle(revision_id, bundle) == bundle
    bundle["snapshot"]["includes"].clear()
    assert documents.load_revision_bundle(revision_id)["snapshot"]["includes"]


@pytest.fixture
def manual(source_bundle, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
    from isaaclab_arena.agentic_environment_generation.workbench.research_source import editor_revision_source
    documents, receipt = saved(source_bundle)
    bundle = documents.load_revision_bundle(receipt["revision"]["revision_id"])
    args = {"source": editor_revision_source(bundle), "bundle_loader": documents.load_revision_bundle,
            "approval": {"scope": "persist_editor_revision", "principal": "owner"}, "parent_revision_id": None}
    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        with ResearchStore.create(journal, tmp_path / "managed", "store", protect_public=lambda value: None) as store:
            yield store, args, bundle


def test_committed_replay_restart_does_not_need_original_storage(manual, source_bundle, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
    store, args, bundle = manual
    commit = store.persist_editor_revision("family", "save", **args)
    files = store.read_version(commit["reservation"]["reservation_id"])
    shutil.rmtree(source_bundle[4])
    shutil.rmtree(source_bundle[5])
    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        with ResearchStore.open(journal, tmp_path / "managed", "store", protect_public=lambda value: None) as restarted:
            before = list(journal.db.iterdump())
            assert restarted.read_version(commit["reservation"]["reservation_id"]) == files
            def unavailable(revision_id):
                pytest.fail("Committed replay must not access original editor storage")
            assert restarted.persist_editor_revision("family", "save", **{**args, "bundle_loader": unavailable}) == commit
            assert restarted.persist_editor_revision("family", "save", **{**args, "bundle_loader": None}) == commit
            assert list(journal.db.iterdump()) == before


@pytest.mark.parametrize("phase", ["fresh", "reserved", "committed"])
@pytest.mark.parametrize("boundary", ["binding", "bundle"])
@pytest.mark.parametrize("mutation", ["nested", "cycle", "object", "tuple"])
def test_manual_protection_is_detached_reject_only(manual, phase, boundary, mutation):
    store, args, bundle = manual
    if phase == "reserved":
        store.registry.reserve_editor_revision("store", "family", "save", source=args["source"], bundle=bundle,
            approval=args["approval"], parent_revision_id=None)
    elif phase == "committed":
        store.persist_editor_revision("family", "save", **args)
    journal = store.registry.journal
    before = list(journal.db.iterdump())
    original = json.dumps(bundle, sort_keys=True)
    observed = []
    def mutate(value):
        if (boundary == "bundle" and "snapshot" in value) or (boundary == "binding" and "approval" in value):
            observed.append(True)
            if mutation == "nested":
                value["changed"] = True
            elif mutation == "cycle":
                value["cycle"] = value
            elif mutation == "object":
                value["object"] = object()
            else:
                value["tuple"] = ()
    store.protect_public = mutate
    with pytest.raises(ValueError):
        store.persist_editor_revision("family", "save", **args)
    assert observed
    assert json.dumps(bundle, sort_keys=True) == original
    assert list(journal.db.iterdump()) == before


def test_public_loader_protects_decoded_unused_frozen_includes(source_bundle):
    import yaml
    documents, source_id, source, include, state, root = source_bundle
    spec = yaml.safe_load(include.read_text())
    spec["env_name"] = "x05-secret"
    include.write_text(yaml.safe_dump(spec).replace("x05-secret", '\"x05-\\u0073ecret\"'))
    loaded = documents.load(source_id)
    assert loaded["validation"]["valid"]
    spec["env_name"] = "clean"
    receipt = documents.save(yaml.safe_dump(spec), loaded["document_id"], loaded["source_hash"],
                             idempotency_key="unused-includes")
    def protect(value):
        if "x05-secret" in json.dumps(value):
            raise ValueError("secret rejected")
    with pytest.raises(ValueError, match="secret rejected"):
        documents.load_revision_bundle(receipt["revision"]["revision_id"], protect_snapshot=protect)


@pytest.mark.parametrize("phase", ["reserved", "committed"])
@pytest.mark.parametrize("field", ["family", "parent", "approval", "source"])
def test_manual_same_key_binds_explicit_source_lineage_and_approval(manual, phase, field):
    store, args, bundle = manual
    if phase == "reserved":
        store.registry.reserve_editor_revision("store", "family", "save", source=args["source"], bundle=bundle,
            approval=args["approval"], parent_revision_id=None)
    else:
        store.persist_editor_revision("family", "save", **args)
    journal = store.registry.journal
    before = list(journal.db.iterdump())
    changed, family = dict(args), "family"
    if field == "family":
        family = "other"
    elif field == "parent":
        changed["parent_revision_id"] = "not-inferred"
    elif field == "approval":
        changed["approval"] = {"scope": "persist_editor_revision", "principal": "other"}
    else:
        changed["source"] = {**args["source"], "bundle_sha256": "0" * 64}
    with pytest.raises(ValueError, match="conflict"):
        store.persist_editor_revision(family, "save", **changed)
    assert list(journal.db.iterdump()) == before


def test_manual_explicit_parent_is_committed_same_family_not_latest(manual):
    store, args, bundle = manual
    first = store.persist_editor_revision("family", "first", **args)
    root = first["reservation"]["revision_id"]
    second = store.persist_editor_revision("family", "second", **args)
    third = store.persist_editor_revision("family", "third", **{**args, "parent_revision_id": root})
    assert second["reservation"]["parent_revision_id"] is None
    assert third["reservation"]["parent_revision_id"] == root
    assert third["reservation"]["version"] == 3
    with pytest.raises(ValueError, match="same store and family"):
        store.persist_editor_revision("other", "bad-parent", **{**args, "parent_revision_id": root})
    omitted = {key: value for key, value in args.items() if key != "parent_revision_id"}
    with pytest.raises(TypeError):
        store.persist_editor_revision("family", "omitted-parent", **omitted)
    assert [row["version"] for row in store.lineage("family")] == [1, 2, 3]


@pytest.mark.parametrize("phase", ["fresh", "reserved", "promoted"])
@pytest.mark.parametrize("attack", ["missing", "corrupt", "symlink", "wrong-bundle"])
def test_manual_incomplete_retry_requires_same_verified_original(manual, source_bundle, tmp_path, monkeypatch, phase, attack):
    store, args, bundle = manual
    if phase == "reserved":
        store.registry.reserve_editor_revision("store", "family", "save", source=args["source"], bundle=bundle,
            approval=args["approval"], parent_revision_id=None)
    elif phase == "promoted":
        with monkeypatch.context() as guard:
            def fail(*a, **kw):
                raise RuntimeError("injected pre-commit exception, not process death")
            guard.setattr(store.registry, "record_commit", fail)
            with pytest.raises(RuntimeError):
                store.persist_editor_revision("family", "save", **args)
    journal = store.registry.journal
    before = list(journal.db.iterdump())
    target = source_bundle[4] / "editor-revision-bundles" / args["source"]["editor_revision_id"] / "snapshot.json"
    if attack == "missing":
        target.unlink()
    elif attack == "corrupt":
        target.write_bytes(b"{}")
    elif attack == "symlink":
        original = target.read_bytes()
        target.unlink()
        other = tmp_path / "outside.json"
        other.write_bytes(original)
        target.symlink_to(other)
    else:
        changed = json.loads(json.dumps(bundle))
        changed["snapshot"]["includes"]["scene-assets.yaml"] += "# same scene, different exact bytes\n"
        changed["bundle_sha256"] = hashlib.sha256(json.dumps(
            [changed["codec"], changed["receipt"], changed["snapshot"], changed["export_yaml"]],
            ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert Documents.verify_revision_bundle(args["source"]["editor_revision_id"], changed) == changed
        args = {**args, "bundle_loader": lambda revision_id: changed}
    monkeypatch.setattr(store.area, "stage", lambda *a, **kw: pytest.fail("Rejected source staged"))
    with pytest.raises((ValueError, KeyError)):
        store.persist_editor_revision("family", "save", **args)
    assert list(journal.db.iterdump()) == before
    assert journal.db.execute("SELECT COUNT(*) FROM research_commits").fetchone()[0] == 0


def test_manual_promoted_retry_reuses_exact_files_after_restart(manual, tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
    store, args, bundle = manual
    with monkeypatch.context() as guard:
        def fail(*a, **kw):
            raise RuntimeError("injected pre-commit exception, not process death")
        guard.setattr(store.registry, "record_commit", fail)
        with pytest.raises(RuntimeError):
            store.persist_editor_revision("family", "save", **args)
    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        with ResearchStore.open(journal, tmp_path / "managed", "store", protect_public=lambda value: None) as restarted:
            monkeypatch.setattr(restarted.area, "stage", lambda *a, **kw: pytest.fail("Second artifact copy"))
            commit = restarted.persist_editor_revision("family", "save", **args)
            assert commit["reservation"]["version"] == 1
            assert journal.db.execute("SELECT COUNT(*) FROM research_commits").fetchone()[0] == 1


def test_legacy_five_field_candidate_bytes_digests_wrappers_and_mixed_lineage(manual):
    from isaaclab_arena_examples.tests.test_workbench_research_store import candidate
    from isaaclab_arena.agentic_environment_generation.workbench.research_source import source_kind, verify_source_artifacts
    store, manual_args, bundle = manual
    journal = store.registry.journal
    journal.begin_run()
    args, receipt = candidate(journal)  # synthetic SQLite storage fixture, never a provider
    encode = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    sha = lambda value: hashlib.sha256(encode(value)).hexdigest()
    reference = store.candidate_reference(args["job_id"])
    expected = {key: args[key] for key in ("job_id", "attempt_id", "generation")}
    expected.update(receipt_sha256=sha(receipt), request_sha256=sha(journal.get_job(args["job_id"])["inputs"]))
    assert reference == expected
    assert set(reference) == {"job_id", "attempt_id", "generation", "receipt_sha256", "request_sha256"}
    assert source_kind(reference) == "accepted_candidate"
    commit = store.persist_candidate("family", "candidate-save", **args)
    reservation = commit["reservation"]
    assert reservation["source"] == expected
    request = {key: reservation[key] for key in ("store_id", "family", "source", "parent_revision_id", "publication_request")}
    assert reservation["request_digest"] == sha(request)
    assert commit["manifest"]["digest"] == sha({key: value for key, value in commit["manifest"].items() if key != "digest"})
    files = store.read_version(reservation["reservation_id"])
    assert files == {"environment.yaml": receipt["yaml_text"].encode(), "candidate.json": encode(receipt),
                     "source.json": encode(reservation)}
    assert verify_source_artifacts(reference, files) == receipt
    child = store.persist_editor_revision("family", "manual-child", **{
        **manual_args, "parent_revision_id": reservation["revision_id"]})
    assert child["reservation"]["version"] == 2
    assert store.persist_candidate("family", "candidate-save", **args) == commit
    assert store.read_version(reservation["reservation_id"]) == files
    assert journal.get_candidate_receipt(args["job_id"], args["attempt_id"], args["generation"]) == receipt


@pytest.mark.parametrize("phase", ["fresh", "committed", "read"])
def test_manual_secret_rejection_preserves_callback_exception(manual, tmp_path, phase):
    store, args, bundle = manual
    if phase != "fresh":
        commit = store.persist_editor_revision("family", "save", **args)
    journal = store.registry.journal
    before = list(journal.db.iterdump())
    files = {str(p): p.read_bytes() for p in (tmp_path / "managed").rglob("*") if p.is_file()}
    rejected = ValueError("secret rejected without reflection")
    def protect(value):
        if "snapshot" in value:
            raise rejected
    store.protect_public = protect
    with pytest.raises(ValueError) as error:
        if phase == "read":
            store.read_version(commit["reservation"]["reservation_id"])
        else:
            store.persist_editor_revision("family", "save", **args)
    assert error.value is rejected
    assert list(journal.db.iterdump()) == before
    assert {str(p): p.read_bytes() for p in (tmp_path / "managed").rglob("*") if p.is_file()} == files


@pytest.mark.parametrize("publication", [{}, {"effect_id": "effect", "target_profile": "graph"}, False])
def test_manual_publication_is_rejected_before_reservation_or_source_loading(manual, tmp_path, publication):
    store, args, bundle = manual
    journal = store.registry.journal
    before = list(journal.db.iterdump())
    def unavailable(*a):
        pytest.fail("Publication must reject before loading")
    with pytest.raises(ValueError, match="unsupported"):
        store.persist_editor_revision("family", "save", **{**args, "bundle_loader": unavailable},
                                      publication_request=publication)
    with pytest.raises(ValueError, match="unsupported"):
        store.registry.reserve_editor_revision("store", "family", "save", source=args["source"], bundle=bundle,
            approval=args["approval"], parent_revision_id=None, publication_request=publication)
    assert list(journal.db.iterdump()) == before
    assert list((tmp_path / "managed/staging").iterdir()) == []
    assert list((tmp_path / "managed/final").iterdir()) == []


@pytest.mark.parametrize("artifact", ["environment.yaml", "editor-snapshot.json", "editor-receipt.json", "export.yaml", "source.json"])
@pytest.mark.parametrize("attack", ["missing", "corrupt", "symlink"])
def test_manual_committed_copy_corruption_is_not_repaired_from_original(manual, tmp_path, artifact, attack):
    store, args, bundle = manual
    commit = store.persist_editor_revision("family", "save", **args)
    target = tmp_path / "managed" / commit["relative_directory"] / artifact
    if attack == "corrupt":
        target.write_bytes(b"{}")
    else:
        original = target.read_bytes()
        target.unlink()
        if attack == "symlink":
            other = tmp_path / "outside-copy"
            other.write_bytes(original)
            target.symlink_to(other)
    before = list(store.registry.journal.db.iterdump())
    with pytest.raises(ValueError):
        store.read_version(commit["reservation"]["reservation_id"])
    with pytest.raises(ValueError):
        store.persist_editor_revision("family", "save", **args)
    assert list(store.registry.journal.db.iterdump()) == before


@pytest.mark.parametrize("approval", [None, {"scope": "persist_candidate", "principal": "owner"},
    {"scope": "persist_editor_revision", "principal": "owner", "extra": True}])
def test_manual_fresh_approval_rejected_without_reservation(manual, approval):
    store, args, bundle = manual
    before = list(store.registry.journal.db.iterdump())
    with pytest.raises(ValueError, match="approval"):
        store.persist_editor_revision("family", "save", **{**args, "approval": approval})
    assert list(store.registry.journal.db.iterdump()) == before


@pytest.mark.parametrize("attack", ["unknown-kind", "extra", "missing", "boolean-version", "codec", "digest", "revision-id"])
def test_manual_source_union_rejects_malformed_identifiers_before_loading(manual, attack):
    store, args, bundle = manual
    source = dict(args["source"])
    if attack == "unknown-kind":
        source["kind"] = "accepted_candidate"
    elif attack == "extra":
        source["job_id"] = "not-a-job"
    elif attack == "missing":
        del source["receipt_sha256"]
    elif attack == "boolean-version":
        source["schema_version"] = True
    elif attack == "codec":
        source["bundle_codec"] = "arena-editor-bundle/v2"
    elif attack == "digest":
        source["bundle_sha256"] = "A" * 64
    else:
        source["editor_revision_id"] = "../" + source["editor_revision_id"]
    def unavailable(*a):
        pytest.fail("Malformed source reached bundle loader")
    before = list(store.registry.journal.db.iterdump())
    with pytest.raises(ValueError):
        store.persist_editor_revision("family", "save", **{**args, "source": source, "bundle_loader": unavailable})
    assert list(store.registry.journal.db.iterdump()) == before


def test_manual_partial_stage_is_retained_not_repaired(manual, tmp_path):
    store, args, bundle = manual
    reservation = store.registry.reserve_editor_revision("store", "family", "save", source=args["source"], bundle=bundle,
        approval=args["approval"], parent_revision_id=None)
    staged = tmp_path / "managed/staging" / reservation["reservation_id"]
    staged.mkdir(mode=0o700)
    (staged / "environment.yaml").write_bytes(bundle["snapshot"]["yaml_text"].encode())
    before = list(store.registry.journal.db.iterdump())
    with pytest.raises(ValueError):
        store.persist_editor_revision("family", "save", **args)
    assert list(store.registry.journal.db.iterdump()) == before
    assert [p.name for p in staged.iterdir()] == ["environment.yaml"]
    assert store.latest_version("family") is None


def test_manual_save_readback_uses_same_journal_without_candidate_records(source_bundle, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
    from isaaclab_arena.agentic_environment_generation.workbench import research_source

    documents, receipt = saved(source_bundle)
    revision_id = receipt["revision"]["revision_id"]
    bundle = documents.load_revision_bundle(revision_id)
    source = research_source.editor_revision_source(bundle)
    assert set(source) == {"kind", "schema_version", "editor_revision_id", "source_hash", "canonical_hash",
                           "bundle_codec", "bundle_sha256", "receipt_sha256"}
    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        with ResearchStore.create(journal, tmp_path / "managed", "store", protect_public=lambda value: None) as store:
            commit = store.persist_editor_revision("family", "manual-save", source=source,
                bundle_loader=documents.load_revision_bundle,
                approval={"scope": "persist_editor_revision", "principal": "owner"}, parent_revision_id=None)
            reservation = commit["reservation"]
            assert reservation["source"] == source
            assert reservation["parent_revision_id"] is None
            assert reservation["version"] == 1
            assert commit["publication_intent_id"] is None
            files = store.read_version(reservation["reservation_id"])
            assert set(files) == {"environment.yaml", "editor-snapshot.json", "editor-receipt.json", "export.yaml", "source.json"}
            assert files["environment.yaml"] == bundle["snapshot"]["yaml_text"].encode()
            assert files["export.yaml"] == bundle["export_yaml"].encode()
            assert json.loads(files["editor-receipt.json"]) == receipt
            assert json.loads(files["editor-snapshot.json"]) == bundle["snapshot"]
            assert research_source.verify_source_artifacts(source, files) == bundle
            assert store.latest_version("family") == 1
            for table in ("jobs", "attempts", "candidate_receipts", "modern_candidate_receipts", "events"):
                assert journal.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            assert journal.db.execute("SELECT COUNT(*) FROM research_publication_intents").fetchone()[0] == 0
