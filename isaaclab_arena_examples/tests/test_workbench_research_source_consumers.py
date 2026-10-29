# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Frozen consumer verification only; no graph, provider, or runtime acceptance."""
import hashlib
import json
import shutil

import pytest

from isaaclab_arena.agentic_environment_generation.workbench.research_registry import canonical_json, digest

from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
from isaaclab_arena.agentic_environment_generation.workbench import research_source
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena_examples.tests.test_workbench_manual_research_versions import manual  # noqa: F401
from isaaclab_arena.tests.test_workbench_editor_revisions import source_bundle  # noqa: F401


def test_frozen_spec_uses_copied_bundle_after_originals_removed(manual, source_bundle):
    store, args, bundle = manual
    commit = store.persist_editor_revision("family", "save", **args)
    reservation = commit["reservation"]
    expected = ArenaEnvGraphSpec.from_dict(Documents(".").validate(bundle["export_yaml"])["spec"])
    shutil.rmtree(source_bundle[4])
    shutil.rmtree(source_bundle[5])
    files = store.read_version(reservation["reservation_id"])
    before = dict(files)
    assert "candidate.json" not in files
    assert "job_id" not in reservation["source"]
    actual = research_source.verify_frozen_spec(reservation["source"], files)
    assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
    assert files == before
    assert files["environment.yaml"] == bundle["snapshot"]["yaml_text"].encode()
    assert files["environment.yaml"] != files["export.yaml"]
    assert store.registry.journal.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def legacy_files(text, *, source_hash=None):
    """Receipt-only fixture, not a job, attempt, or publication acceptance."""
    receipt = {"yaml_text": text, "validation": {"valid": True,
               "source_hash": source_hash or hashlib.sha256(text.encode()).hexdigest()},
               "publication": "not_published"}
    source = dict(job_id="job", attempt_id="attempt", generation=1,
                  receipt_sha256=digest(receipt), request_sha256="1" * 64)
    return source, {"candidate.json": canonical_json(receipt).encode(), "environment.yaml": text.encode()}


def test_legacy_candidate_raw_digest_conflict_is_rejected(source_bundle):
    source, files = legacy_files(source_bundle[3].read_text(), source_hash="0" * 64)
    with pytest.raises(ValueError, match="source"):
        research_source.verify_frozen_spec(source, files)


def test_legacy_candidate_codec_and_normalized_projection_are_unchanged(source_bundle):
    from isaaclab_arena.agentic_environment_generation.workbench.research_projection import project_scene
    text = source_bundle[3].read_text()
    source, files = legacy_files(text)
    before = canonical_json(source), dict(files)
    spec = research_source.verify_frozen_spec(source, files)
    old_spec = ArenaEnvGraphSpec.from_dict(Documents(".").validate(text)["spec"])
    scope = dict(store_id="store", revision_id="revision", family="family", version="v1")
    assert canonical_json(project_scene(spec, **scope)) == canonical_json(project_scene(old_spec, **scope))
    assert (canonical_json(source), files) == before
    assert "kind" not in source
    assert research_source.verify_source_artifacts(source, files) == json.loads(files["candidate.json"])


def test_legacy_candidate_missing_includes_remains_unsupported(source_bundle):
    source, files = legacy_files(source_bundle[2].read_text())
    with pytest.raises(ValueError, match="Invalid frozen research source"):
        research_source.verify_frozen_spec(source, files)


@pytest.mark.parametrize("artifact", ["environment.yaml", "editor-snapshot.json", "editor-receipt.json", "export.yaml"])
@pytest.mark.parametrize("damage", ["missing", "corrupt", "recoded"])
def test_manual_source_artifact_corruption_is_rejected(manual, artifact, damage):
    store, args, bundle = manual
    commit = store.persist_editor_revision("family", "save", **args)
    files = store.read_version(commit["reservation"]["reservation_id"])
    if damage == "missing":
        files.pop(artifact)
    elif damage == "corrupt":
        files[artifact] = b"{}"
    else:
        files[artifact] += b" "
    with pytest.raises(ValueError, match="Invalid research source artifacts"):
        research_source.verify_frozen_spec(args["source"], files)


@pytest.mark.parametrize("field", ["canonical_hash", "source_hash", "bundle_sha256", "receipt_sha256"])
def test_manual_source_digest_conflicts_are_rejected(manual, field):
    store, args, bundle = manual
    commit = store.persist_editor_revision("family", "save", **args)
    files = store.read_version(commit["reservation"]["reservation_id"])
    with pytest.raises(ValueError, match="Invalid research source artifacts"):
        research_source.verify_frozen_spec({**args["source"], field: "0" * 64}, files)


def test_manual_same_scene_different_include_bytes_cannot_replace_bundle(manual):
    from isaaclab_arena.agentic_environment_generation.workbench.editor_revision_storage import encode
    store, args, bundle = manual
    changed = json.loads(json.dumps(bundle))
    changed["snapshot"]["includes"]["scene-assets.yaml"] += "# same canonical scene\n"
    changed["bundle_sha256"] = hashlib.sha256(encode([
        changed["codec"], changed["receipt"], changed["snapshot"], changed["export_yaml"]])).hexdigest()
    new_source = research_source.editor_revision_source(changed)
    assert new_source["canonical_hash"] == args["source"]["canonical_hash"]
    assert new_source["source_hash"] == args["source"]["source_hash"]
    assert new_source["bundle_sha256"] != args["source"]["bundle_sha256"]
    files = research_source.editor_source_artifacts(new_source, changed)
    with pytest.raises(ValueError, match="Invalid research source artifacts"):
        research_source.verify_frozen_spec(args["source"], files)


def test_current_protection_sees_decoded_unused_includes_and_propagates(source_bundle):
    import yaml
    documents, source_id, source, include, state, root = source_bundle
    spec = yaml.safe_load(include.read_text())
    spec["env_name"] = "current-secret"
    include.write_text(yaml.safe_dump(spec).replace("current-secret", '"current-\\u0073ecret"'))
    loaded = documents.load(source_id)
    spec["env_name"] = "clean"
    receipt = documents.save(yaml.safe_dump(spec), loaded["document_id"], loaded["source_hash"],
                             idempotency_key="unused-frozen")
    bundle = documents.load_revision_bundle(receipt["revision"]["revision_id"])
    source = research_source.editor_revision_source(bundle)
    files = research_source.editor_source_artifacts(source, bundle)
    shutil.rmtree(state)
    shutil.rmtree(root)
    class CurrentPolicyRejected(Exception):
        pass
    rejection = CurrentPolicyRejected("current protection")
    def protect(value):
        assert value["decoded"]["includes"]["scene-assets.yaml"]["env_name"] == "current-secret"
        raise rejection
    with pytest.raises(CurrentPolicyRejected) as error:
        research_source.verify_frozen_spec(source, files, protect_snapshot=protect)
    assert error.value is rejection
    before = dict(files)
    def mutate(value):
        value["snapshot"]["includes"].clear()
    with pytest.raises(ValueError, match="protection callback changed bundle"):
        research_source.verify_frozen_spec(source, files, protect_snapshot=mutate)
    assert files == before


def publication_reader_fixture(commit, files, spec):
    """Read-only hypothetical intent: never persist it or claim graph acceptance."""
    from copy import deepcopy
    from types import SimpleNamespace
    from isaaclab_arena.agentic_environment_generation.workbench.research_projection import project_scene
    commit, files = deepcopy(commit), dict(files)
    reservation = commit["reservation"]
    target = dict(profile_id="graph", revision="frozen", scope_ownership="cooperative_immutable")
    request = dict(effect_id="effect", target_profile=target)
    reservation["publication_request"] = request
    commit["publication_intent_id"] = "effect"
    files["source.json"] = canonical_json(reservation).encode()
    projection = project_scene(spec, store_id=reservation["store_id"], revision_id=reservation["revision_id"],
                               family=reservation["family"], version=f"v{reservation['version']}")
    files["projection.json"] = canonical_json(projection).encode()
    descriptor = dict(artifact="projection.json", artifact_sha256=hashlib.sha256(files["projection.json"]).hexdigest(),
                      projection_digest=projection["digest"], scope_id=projection["scope_id"])
    commit["manifest"]["files"] = {name: dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                                     for name, raw in files.items()}
    intent = dict(**request, payload=descriptor, payload_sha256=digest(descriptor), schema_version=1,
                  registry_id="registry", reservation_id=reservation["reservation_id"], state="pending")
    registry = SimpleNamespace(registry_id="registry", get_publication_intent=lambda _: intent,
                               get_commit=lambda _: commit)
    store = SimpleNamespace(registry=registry, store_id=reservation["store_id"],
                            get_reservation=lambda _: reservation, read_version=lambda _: files)
    authorization = SimpleNamespace(profile_metadata=lambda _: target)
    return store, authorization, intent, projection, files, commit


def test_publication_preparation_reads_manual_frozen_spec_without_job(manual, source_bundle):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_payload import prepare_publication
    real_store, args, bundle = manual
    commit = real_store.persist_editor_revision("family", "save", **args)
    files = real_store.read_version(commit["reservation"]["reservation_id"])
    spec = research_source.verify_frozen_spec(args["source"], files)
    fixture = publication_reader_fixture(commit, files, spec)
    shutil.rmtree(source_bundle[4])
    shutil.rmtree(source_bundle[5])
    store, authorization, intent, projection, files, _ = fixture
    actual_intent, actual_spec, actual_projection = prepare_publication(store, authorization, "effect")
    assert actual_intent == intent
    assert actual_spec.model_dump(mode="json") == spec.model_dump(mode="json")
    assert actual_projection == projection
    assert "candidate.json" not in files
    # The fixture above grants nothing and is not installed in the real registry.
    assert real_store.registry.get_publication_intent("effect") is None
    with pytest.raises(ValueError, match="publication is unsupported"):
        real_store.persist_editor_revision("family", "publish", **args,
                                          publication_request={"effect_id": "effect", "target_profile": "graph"})


def retrieval_reader_fixture(store, intent, projection):
    """Fixture receipt equality only: not actual graph readback or durable acceptance."""
    import sqlite3
    from contextlib import nullcontext
    from types import SimpleNamespace
    from isaaclab_arena.agentic_environment_generation.workbench.research_graph_transport import IMMUTABLE_SCOPE_DECLARATION
    from isaaclab_arena.agentic_environment_generation.workbench.research_retrieval import ManagedSelectionProvider
    transport = dict(status="verified", database="neo4j", effect_id="effect", scope_id=projection["scope_id"],
                     projection_digest=projection["digest"], canonical_identity=projection["canonical_identity"],
                     verification_boundary=dict(method="operator_attested_immutable_scope_v1", operator_attested=True,
                                                declaration=IMMUTABLE_SCOPE_DECLARATION, database_snapshot=False))
    receipt = dict(schema_version=1, status="verified", effect_id="effect", target_profile=intent["target_profile"],
                   payload_sha256=intent["payload_sha256"], transport=transport)
    state = dict(state="verified", attempt_id="fixture-only", generation=1, receipt=receipt, effect_id="effect",
                 target_profile=intent["target_profile"], payload_sha256=intent["payload_sha256"])
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE publication_receipts (effect_id TEXT, body TEXT)")
    db.execute("INSERT INTO publication_receipts VALUES (?,?)", ("effect", canonical_json(dict(
        receipt=receipt, attempt_id=state["attempt_id"], generation=state["generation"]))))
    journal = SimpleNamespace(db=db, _lock=nullcontext())
    store.registry.journal = journal
    attempts = SimpleNamespace(journal=journal, registry=store.registry, get_state=lambda _: state)
    provider = ManagedSelectionProvider([(store, attempts)], database="neo4j",
                                        authorized_targets={"graph": intent["target_profile"]})
    return provider, attempts, state, db


def test_retrieval_preparation_reads_copied_manual_source_without_candidate(manual, source_bundle):
    real_store, args, bundle = manual
    commit = real_store.persist_editor_revision("family", "save", **args)
    files = real_store.read_version(commit["reservation"]["reservation_id"])
    spec = research_source.verify_frozen_spec(args["source"], files)
    store, _, intent, projection, _, _ = publication_reader_fixture(commit, files, spec)
    provider, attempts, state, db = retrieval_reader_fixture(store, intent, projection)
    shutil.rmtree(source_bundle[4])
    shutil.rmtree(source_bundle[5])
    try:
        result = provider._prepare(store, attempts, intent["reservation_id"])
        assert result["spec"].model_dump(mode="json") == spec.model_dump(mode="json")
        assert result["projection"] == projection
        assert result["evidence"] == state["receipt"]["transport"]
    finally:
        db.close()
    assert real_store.registry.get_publication_intent("effect") is None


def test_publication_state_save_does_not_require_manual_job_events(manual, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench.research_publication import PublicationAttempts
    store, args, _ = manual
    commit = store.persist_editor_revision("family", "save", **args)
    journal = store.registry.journal
    attempts = PublicationAttempts(journal, store.registry, initialize=True, protect_public=lambda _: None)
    # Exercise only the state serialization/event helper, not claim/release/acceptance.
    monkeypatch.setattr(attempts, "_intent", lambda _: {"reservation_id": commit["reservation"]["reservation_id"]})
    monkeypatch.setattr(journal, "get_job", lambda _: pytest.fail("Manual source must not look up a candidate job"))
    monkeypatch.setattr(journal, "_event", lambda *args: pytest.fail("Manual source must not emit a candidate job event"))
    state = dict(effect_id="fixture-only", state="pending")
    with journal._transaction() as db:
        assert attempts._save(db, state, "fixture_only") == state
    row = journal.db.execute("SELECT body FROM publication_states WHERE effect_id=?", ("fixture-only",)).fetchone()
    assert json.loads(row[0]) == state
    assert journal.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    assert store.registry.get_publication_intent("fixture-only") is None


def test_publication_state_save_keeps_legacy_job_event(manual):
    from isaaclab_arena.agentic_environment_generation.workbench.research_publication import PublicationAttempts
    from isaaclab_arena_examples.tests.test_workbench_research_store import candidate
    store, _, _ = manual
    journal = store.registry.journal
    args, receipt = candidate(journal)
    commit = store.persist_candidate("legacy", "save", **args,
                                     publication_request={"effect_id": "effect", "target_profile": "graph"})
    attempts = PublicationAttempts(journal, store.registry, initialize=True, protect_public=lambda _: None)
    before = journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    state = dict(effect_id="effect", state="pending")
    with journal._transaction() as db:
        assert attempts._save(db, state, "fixture_only") == state
    assert journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == before + 1
    assert "kind" not in commit["reservation"]["source"]


@pytest.fixture(params=["editor_revision", "accepted_candidate"])
def consumer_fixture(manual, request):
    store, args, _ = manual
    if request.param == "editor_revision":
        commit = store.persist_editor_revision("family", "consumer", **args)
    else:
        from isaaclab_arena_examples.tests.test_workbench_research_store import candidate
        args, _ = candidate(store.registry.journal)
        commit = store.persist_candidate("family", "consumer", **args)
    files = store.read_version(commit["reservation"]["reservation_id"])
    spec = research_source.verify_frozen_spec(commit["reservation"]["source"], files)
    return publication_reader_fixture(commit, files, spec), spec, store


@pytest.mark.parametrize("consumer", ["publication", "retrieval"])
@pytest.mark.parametrize("damage", [None, "source", "projection", "descriptor", "raw"])
def test_consumers_preserve_source_projection_descriptor_contracts(consumer_fixture, consumer, damage):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_payload import prepare_publication
    fixture, spec, _ = consumer_fixture
    store, authorization, intent, projection, files, commit = fixture
    if damage == "source":
        source = json.loads(files["source.json"])
        source["family"] = "different"
        files["source.json"] = canonical_json(source).encode()
    elif damage == "projection":
        changed = json.loads(files["projection.json"])
        changed["scope"]["family"] = "different"
        files["projection.json"] = canonical_json(changed).encode()
    elif damage == "descriptor":
        intent["payload"]["artifact_sha256"] = "0" * 64
        intent["payload_sha256"] = digest(intent["payload"])
    elif damage == "raw":
        files["environment.yaml"] += b"# canonical-equivalent raw replacement\n"
    # Reseal fixture manifest so a superficial checksum cannot mask the deeper guard.
    commit["manifest"]["files"] = {name: dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                                     for name, raw in files.items()}
    if consumer == "publication":
        run = lambda: prepare_publication(store, authorization, "effect")
        db = None
    else:
        provider, attempts, _, db = retrieval_reader_fixture(store, intent, projection)
        run = lambda: provider._prepare(store, attempts, intent["reservation_id"])
    try:
        if damage:
            with pytest.raises(ValueError):
                run()
        elif consumer == "publication":
            result = run()
            assert result[0] == intent
            assert result[1].model_dump(mode="json") == spec.model_dump(mode="json")
            assert canonical_json(result[2]) == canonical_json(projection)
        else:
            result = run()
            assert result["spec"].model_dump(mode="json") == spec.model_dump(mode="json")
            assert canonical_json(result["projection"]) == canonical_json(projection)
    finally:
        if db is not None:
            db.close()


@pytest.mark.parametrize("artifact", ["environment.yaml", "source.json", "projection.json",
                                       "editor-snapshot.json", "editor-receipt.json", "export.yaml"])
def test_publication_checks_every_manual_artifact_manifest_entry(manual, artifact):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_payload import prepare_publication
    real_store, args, _ = manual
    commit = real_store.persist_editor_revision("family", "manifest", **args)
    files = real_store.read_version(commit["reservation"]["reservation_id"])
    spec = research_source.verify_frozen_spec(args["source"], files)
    store, authorization, _, _, _, commit = publication_reader_fixture(commit, files, spec)
    commit["manifest"]["files"][artifact]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="artifact manifest conflict"):
        prepare_publication(store, authorization, "effect")


@pytest.mark.parametrize("damage", ["state", "durable", "target", "unverified"])
def test_retrieval_keeps_existing_receipt_and_eligibility_guards(consumer_fixture, damage):
    fixture, _, _ = consumer_fixture
    store, _, intent, projection, _, _ = fixture
    provider, attempts, state, db = retrieval_reader_fixture(store, intent, projection)
    try:
        if damage == "target":
            intent["target_profile"] = {**intent["target_profile"], "revision": "not-authorized"}
        elif damage == "unverified":
            state["state"] = "unknown"
        elif damage == "state":
            state["generation"] = 2
        else:
            db.execute("UPDATE publication_receipts SET body='{}'")
        if damage in {"target", "unverified"}:
            assert provider._prepare(store, attempts, intent["reservation_id"]) is None
        else:
            with pytest.raises(ValueError, match="Durable verified receipt conflict"):
                provider._prepare(store, attempts, intent["reservation_id"])
    finally:
        db.close()


@pytest.mark.parametrize("consumer", ["publication", "retrieval"])
def test_consumers_preserve_current_store_protection_errors(manual, consumer):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_payload import prepare_publication
    real_store, args, _ = manual
    commit = real_store.persist_editor_revision("family", "protect", **args)
    files = real_store.read_version(commit["reservation"]["reservation_id"])
    spec = research_source.verify_frozen_spec(args["source"], files)
    store, authorization, intent, projection, _, _ = publication_reader_fixture(commit, files, spec)
    rejection = RuntimeError("Current store protection rejects copied source")
    def protect(value):
        if "snapshot" in value:
            raise rejection
    real_store.protect_public = protect
    store.read_version = real_store.read_version
    if consumer == "publication":
        run = lambda: prepare_publication(store, authorization, "effect")
        db = None
    else:
        provider, attempts, _, db = retrieval_reader_fixture(store, intent, projection)
        run = lambda: provider._prepare(store, attempts, intent["reservation_id"])
    try:
        with pytest.raises(RuntimeError) as error:
            run()
        assert error.value is rejection
    finally:
        if db is not None:
            db.close()


def test_resealed_wrong_canonical_export_is_rejected(manual):
    from isaaclab_arena.agentic_environment_generation.workbench.editor_revision_storage import encode
    _, args, bundle = manual
    changed = json.loads(json.dumps(bundle))
    changed["export_yaml"] = changed["export_yaml"].replace("env_name:", "env_name: different #", 1)
    assert changed["export_yaml"] != bundle["export_yaml"]
    changed["bundle_sha256"] = hashlib.sha256(encode([
        changed["codec"], changed["receipt"], changed["snapshot"], changed["export_yaml"]])).hexdigest()
    source = {**args["source"], "bundle_sha256": changed["bundle_sha256"]}
    files = {"environment.yaml": changed["snapshot"]["yaml_text"].encode(),
             "editor-snapshot.json": encode(changed["snapshot"]), "editor-receipt.json": encode(changed["receipt"]),
             "export.yaml": changed["export_yaml"].encode()}
    with pytest.raises(ValueError, match="Invalid research source artifacts"):
        research_source.verify_frozen_spec(source, files)
