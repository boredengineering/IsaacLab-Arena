# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Real Cypher and bounded races against the separately owned disposable database.

Schema provisioning and initialize_scope are administrative, quiescent gates:
finish them before starting cooperative readers/writers. Concurrent initialization
is not an acceptance claim of this suite. No admission/unknown-outcome retries.
"""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from neo4j import GraphDatabase

from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
    CapacityExceeded,
    Neo4jWorkflowStore,
    ReplayGap,
    SubmissionConflict,
)


@pytest.fixture
def driver():
    with GraphDatabase.driver(
        os.environ["ARENA_WORKFLOW_NEO4J_URI"],
        auth=None,
        max_transaction_retry_time=0,
        connection_timeout=3,
        connection_acquisition_timeout=5,
    ) as d:
        with d.session(database=os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"]) as session:
            for ddl in Neo4jWorkflowStore.schema_requirements():
                with session.begin_transaction(timeout=5) as tx:
                    tx.run(ddl).consume()
                    tx.commit()
            session.run("CALL db.awaitIndexes(30)").consume()
        yield d


def test_explicit_scope_binding_retains_exact_replay(driver):
    s = Neo4jWorkflowStore(
        driver,
        database=os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"],
        deployment_id="binding-tests",
        workspace_id=uuid.uuid4().hex,
    )
    assert hasattr(s, "initialize_bound_scope"), "explicit immutable scope initialization missing"
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

    binding = ScopeBinding(
        authority_id="synthetic-authority",
        database=s.database,
        **s.scope,
        schema_version=1,
        operational_schema_version=1,
        artifact_marker_schema=1,
        store_id="synthetic-store",
        registry_id="synthetic-registry",
    )
    screened = []
    assert s.initialize_bound_scope(binding, protect=screened.append) == binding
    with driver.session(database=s.database) as session:
        before = session.run(
            "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "RETURN properties(c) AS value",
            **s.scope,
        ).single()["value"]
    assert s.initialize_bound_scope(binding, protect=screened.append) == binding
    assert s.verify_scope_binding(binding) == binding
    with driver.session(database=s.database) as session:
        after = session.run(
            "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "RETURN properties(c) AS value",
            **s.scope,
        ).single()["value"]
    assert before == after
    assert before["revision"] == before["sequence"] == before["floor"] == 0
    assert screened == [binding.model_dump(mode="json")] * 4


def binding_fixture(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

    s = Neo4jWorkflowStore(
        driver,
        database=os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"],
        deployment_id="binding-tests",
        workspace_id=uuid.uuid4().hex,
    )
    binding = ScopeBinding(
        authority_id="synthetic-authority",
        database=s.database,
        **s.scope,
        schema_version=1,
        operational_schema_version=1,
        artifact_marker_schema=1,
        store_id="synthetic-store",
        registry_id="synthetic-registry",
    )
    return s, binding


@pytest.mark.parametrize("existing_empty", [False, True])
def test_scope_admin_artifacts_and_fresh_current_resources(driver, tmp_path, monkeypatch, existing_empty):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowProfileAdmin
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    assert hasattr(WorkflowProfileAdmin, "initialize_scope"), "Explicit scope administration missing"
    from isaaclab_arena.agentic_environment_generation.workflow.admin import WorkflowScopeAdmin

    s, binding = binding_fixture(driver)
    checks = []
    authority = SimpleNamespace(require_admin=lambda p: checks.append(p))
    admin = WorkflowScopeAdmin(s, authority)
    assert admin.initialize_scope("operator", binding, protect=lambda _: None) == binding
    root = tmp_path / "artifacts"
    if existing_empty:
        root.mkdir(mode=0o700)
    created = admin.initialize_artifacts("operator", binding, root=root, create=True, protect=lambda _: None)
    assert created.db_binding_retained is True
    assert created.artifact_state == "artifact_created"
    assert created.durability == "creation_acknowledged"
    registered = WorkflowProfileAdmin(s, authority).register_profile(
        "operator",
        ProfileRegistration.model_validate(profile_registration()),
        protect=lambda _: None,
    )
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    queries = []

    def read_only(query, params):
        if query != "SESSION_CLOSED":
            queries.append(query)
            assert query.startswith(("MATCH ", "SHOW "))
            assert not any(word in query for word in ("SET ", "CREATE ", "MERGE ", "DELETE ", "CALL "))

    fresh = Neo4jWorkflowStore(inspection_driver(driver, read_only, fetch_size=None), database=s.database, **s.scope)
    verifier = WorkflowScopeAdmin(fresh, authority)
    monkeypatch.setattr(ArtifactArea, "create", lambda *a, **k: pytest.fail("read path created artifacts"))
    screens = []
    result = verifier.verify_current_resources(
        "operator", binding, root=root, required_profiles=(registered,), protect=screens.append
    )
    assert result.binding == binding and result.profiles == (registered,)
    assert result.artifact_state == "existing_layout_verified"
    assert result.durability == "not_established"
    assert screens[-1] == result.model_dump(mode="json")
    replay = verifier.initialize_artifacts("operator", binding, root=root, create=False, protect=lambda _: None)
    assert replay.artifact_state == "existing_layout_verified" and replay.durability == "not_established"
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert checks == ["operator"] * 5
    assert any("ArenaWorkflowProfileRevision" in q and q.startswith("MATCH ") for q in queries)


@pytest.mark.parametrize("failure_at", [1, 3, 4])
def test_scope_artifact_failed_fsync_is_incomplete_not_certified(driver, tmp_path, monkeypatch, failure_at):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workbench import research_artifacts
    from isaaclab_arena.agentic_environment_generation.workflow.admin import WorkflowScopeAdmin

    s, binding = binding_fixture(driver)
    admin = WorkflowScopeAdmin(s, SimpleNamespace(require_admin=lambda _: None))
    admin.initialize_scope("operator", binding, protect=lambda _: None)
    root = tmp_path / "area"
    root.mkdir(mode=0o700)
    fsync = os.fsync
    calls = []

    def fail(fd):
        calls.append(fd)
        if len(calls) == failure_at:
            raise OSError("synthetic fsync failure")
        return fsync(fd)

    with monkeypatch.context() as m:
        m.setattr(research_artifacts.os, "fsync", fail)
        with pytest.raises(ValueError) as caught:
            admin.initialize_artifacts("operator", binding, root=root, create=True, protect=lambda _: None)
    assert getattr(caught.value, "db_binding_retained", None) is True, "retained DB phase missing on artifact failure"
    assert caught.value.artifact_state == "incomplete_or_unknown"
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert s.verify_scope_binding(binding) == binding
    if failure_at == 1:
        with pytest.raises(ValueError):
            admin.initialize_artifacts("operator", binding, root=root, create=False, protect=lambda _: None)
    else:
        reopened = admin.initialize_artifacts("operator", binding, root=root, create=False, protect=lambda _: None)
        assert reopened.artifact_state == "existing_layout_verified"
        assert reopened.durability == "not_established"
        verified = admin.verify_current_resources(
            "operator", binding, root=root, required_profiles=(), protect=lambda _: None
        )
        assert verified.durability == "not_established"
    with pytest.raises(ValueError):
        admin.initialize_artifacts("operator", binding, root=root, create=True, protect=lambda _: None)
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    "field", ["authority_id", "database", "deployment_id", "workspace_id", "store_id", "registry_id"]
)
def test_scope_binding_each_identity_conflicts_without_mutation(driver, field):
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

    s, binding = binding_fixture(driver)
    s.initialize_bound_scope(binding, protect=lambda _: None)
    changed = ScopeBinding.model_validate(binding.model_dump() | {field: "different"})
    before = binding_control(driver, s)
    for action in (
        lambda: s.initialize_bound_scope(changed, protect=lambda _: None),
        lambda: s.verify_scope_binding(changed),
    ):
        with pytest.raises(SubmissionConflict):
            action()
    assert binding_control(driver, s) == before
    assert s.verify_scope_binding(binding) == binding


def binding_control(driver, store):
    with driver.session(database=store.database) as session:
        return session.run(
            "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "RETURN properties(c) AS value",
            **store.scope,
        ).data()


@pytest.mark.parametrize("legacy", ["empty", "run", "orphan"])
def test_scope_binding_never_adopts_legacy_or_orphan(driver, legacy):
    s, binding = binding_fixture(driver)
    if legacy != "orphan":
        s.initialize_scope()
        if legacy == "run":
            s.admit("legacy", "{}", "{}", 1)
    else:
        with driver.session(database=s.database) as session:
            session.run(
                "CREATE (:ArenaWorkflowProfile {deployment_id:$deployment_id, workspace_id:$workspace_id, "
                "profile_id:'orphan', kind:'model'})",
                **s.scope,
            ).consume()
    before = binding_control(driver, s)
    with pytest.raises((ValueError, RuntimeError), match="migration"):
        s.initialize_bound_scope(binding, protect=lambda _: None)
    assert binding_control(driver, s) == before
    if legacy != "orphan":
        with pytest.raises(ValueError, match="migration"):
            s.verify_scope_binding(binding)


@pytest.mark.parametrize(
    "damage",
    [
        "truncated",
        "private",
        "bool",
        "float",
        "future",
        "extra",
        "duplicate_json",
        "digest",
        "large",
        "array",
        "cross_scope",
        "missing_half",
    ],
)
def test_scope_binding_corruption_is_static_and_never_repaired(driver, damage):
    import hashlib
    import json
    import traceback

    s, binding = binding_fixture(driver)
    s.initialize_bound_scope(binding, protect=lambda _: None)
    raw = binding.model_dump(mode="json")
    if damage in ("bool", "float", "future"):
        raw["schema_version"] = {"bool": True, "float": 1.0, "future": 2}[damage]
    elif damage == "extra":
        raw["executable"] = "private-sentinel"
    elif damage == "private":
        raw["authority_id"] = {"password": "private-sentinel"}
    elif damage == "cross_scope":
        raw["workspace_id"] = "foreign"
    body = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    if damage == "truncated":
        body = '{"private-sentinel":'
    elif damage == "duplicate_json":
        body = body[:-1] + ',"schema_version":1}'
    elif damage == "large":
        body = "private-sentinel" * 1000
    digest = hashlib.sha256(body.encode()).hexdigest()
    if damage == "digest":
        digest = "a" * 64
    elif damage == "array":
        body = ["private-sentinel" * 5000]
    elif damage == "missing_half":
        digest = None
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "SET c.scope_binding_json=$body, c.scope_binding_sha256=$digest",
            **s.scope,
            body=body,
            digest=digest,
        ).consume()
    before = binding_control(driver, s)
    for action in (
        lambda: s.initialize_bound_scope(binding, protect=lambda _: None),
        lambda: s.verify_scope_binding(binding),
    ):
        with pytest.raises(ValueError, match="[Rr]etained scope binding") as caught:
            action()
        assert "private-sentinel" not in "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert binding_control(driver, s) == before


def test_scope_binding_missing_schema_duplicate_control_and_foreign_scope(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import SchemaMissing, ScopeMissing

    s, binding = binding_fixture(driver)
    with pytest.raises(ScopeMissing):
        s.verify_scope_binding(binding)
    ddl = next(q for q in Neo4jWorkflowStore.schema_requirements() if "(n:ArenaWorkflowControl)" in q)
    with driver.session(database=s.database) as session:
        constraints = session.run("SHOW CONSTRAINTS YIELD name, labelsOrTypes RETURN *").data()
        name = next(r["name"] for r in constraints if r["labelsOrTypes"] == ["ArenaWorkflowControl"])
        session.run("DROP CONSTRAINT `" + name + "`").consume()
        try:
            with pytest.raises(SchemaMissing):
                s.initialize_bound_scope(binding, protect=lambda _: None)
            assert binding_control(driver, s) == []
        finally:
            session.run(ddl).consume()
            session.run("CALL db.awaitIndexes(30)").consume()
    s.initialize_bound_scope(binding, protect=lambda _: None)
    foreign = Neo4jWorkflowStore(
        driver, database=s.database, deployment_id="other", workspace_id=s.scope["workspace_id"]
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

    other = ScopeBinding.model_validate(binding.model_dump() | {"deployment_id": "other"})
    with pytest.raises(ScopeMissing):
        foreign.verify_scope_binding(other)
    with driver.session(database=s.database) as session:
        session.run("DROP CONSTRAINT `" + name + "`").consume()
        try:
            session.run(
                "CREATE (c:ArenaWorkflowControl) SET c=$properties", properties=binding_control(driver, s)[0]["value"]
            ).consume()
            with s._transaction() as tx:
                with pytest.raises(ValueError, match="Ambiguous"):
                    s._scope_binding(tx)
            # Public reads reject missing required uniqueness rather than choosing a duplicate.
            with pytest.raises(SchemaMissing):
                s.verify_scope_binding(binding)
        finally:
            session.run(
                "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) DELETE c",
                **s.scope,
            ).consume()
            session.run(ddl).consume()
            session.run("CALL db.awaitIndexes(30)").consume()


@pytest.mark.parametrize("operation", ["initialize", "artifact", "verify"])
@pytest.mark.parametrize("fault", ["commit", "cleanup", "rollback", "query"])
def test_scope_binding_db_ack_and_transport_never_reach_filesystem(driver, tmp_path, monkeypatch, operation, fault):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.admin import WorkflowScopeAdmin
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown, ScopeMissing

    s, binding = binding_fixture(driver)
    if operation != "initialize":
        s.initialize_bound_scope(binding, protect=lambda _: None)
    error = OSError("synthetic local transport error")
    target = (
        "CREATE (c:ArenaWorkflowControl" if operation == "initialize" and fault == "rollback" else " AS present LIMIT 2"
    )
    injected = (target, True, error, False) if fault in ("rollback", "query") else fault
    faulty = Neo4jWorkflowStore(
        inspection_driver(driver, lambda *a: None, fault=injected, fetch_size=None), database=s.database, **s.scope
    )
    admin = WorkflowScopeAdmin(faulty, SimpleNamespace(require_admin=lambda _: None))
    monkeypatch.setattr(ArtifactArea, "create", lambda *a, **k: pytest.fail("filesystem after unknown DB outcome"))
    monkeypatch.setattr(ArtifactArea, "open", lambda *a, **k: pytest.fail("filesystem after unknown DB outcome"))
    with pytest.raises(OSError if fault in ("rollback", "query") else OutcomeUnknown):
        if operation == "initialize":
            admin.initialize_scope("operator", binding, protect=lambda _: None)
        elif operation == "artifact":
            admin.initialize_artifacts("operator", binding, root=tmp_path / "area", create=True, protect=lambda _: None)
        else:
            admin.verify_current_resources(
                "operator", binding, root=tmp_path / "area", required_profiles=(), protect=lambda _: None
            )
    assert not (tmp_path / "area").exists()
    if operation == "initialize" and fault in ("rollback", "query"):
        with pytest.raises(ScopeMissing):
            s.verify_scope_binding(binding)
    else:
        assert s.verify_scope_binding(binding) == binding


def test_scope_verification_is_readonly_and_callbacks_outside_transactions(driver, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.admin import WorkflowScopeAdmin

    s, binding = binding_fixture(driver)
    queries, closed = [], [True]

    def visit(query, params):
        if query == "SESSION_CLOSED":
            closed[0] = True
        else:
            closed[0] = False
            queries.append(query)

    observed = Neo4jWorkflowStore(inspection_driver(driver, visit, fetch_size=None), database=s.database, **s.scope)
    admin = WorkflowScopeAdmin(observed, SimpleNamespace(require_admin=lambda _: None))

    def protect(body):
        assert closed[0], "public callback entered an open DB transaction"
        # Independent cooperative control-lock read completes: no callback lock inversion.
        if binding_control(driver, s):
            with ThreadPoolExecutor() as pool:
                pool.submit(s.snapshot).result(timeout=3)

    admin.initialize_scope("operator", binding, protect=protect)
    root = tmp_path / "area"
    admin.initialize_artifacts("operator", binding, root=root, create=True, protect=protect)
    queries.clear()
    monkeypatch.setattr(ArtifactArea, "create", lambda *a, **k: pytest.fail("unexpected create"))
    before = binding_control(driver, s)
    admin.verify_current_resources("operator", binding, root=root, required_profiles=(), protect=lambda _: None)
    assert binding_control(driver, s) == before
    assert queries and all(q.startswith(("MATCH ", "SHOW ")) for q in queries)
    assert all(not any(word in q for word in ("SET ", "CREATE ", "MERGE ", "DELETE ", "CALL ")) for q in queries)


@pytest.mark.parametrize(
    "damage", ["missing", "empty", "partial", "truncated", "foreign", "symlink", "world_writable", "marker_symlink"]
)
def test_scope_admin_rejects_damaged_artifacts_without_repair(driver, tmp_path, damage):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.admin import WorkflowScopeAdmin

    s, binding = binding_fixture(driver)
    admin = WorkflowScopeAdmin(s, SimpleNamespace(require_admin=lambda _: None))
    admin.initialize_scope("operator", binding, protect=lambda _: None)
    root = tmp_path / "area"
    if damage != "missing":
        root.mkdir(mode=0o700)
    if damage == "partial":
        (root / "staging").mkdir(mode=0o700)
    elif damage not in ("missing", "empty"):
        with ArtifactArea.create(root, store_id=binding.store_id, registry_id=binding.registry_id):
            pass
        if damage == "truncated":
            (root / ArtifactArea.MARKER).write_bytes(b'{"schema":')
        elif damage == "foreign":
            (root / ArtifactArea.MARKER).write_bytes(b'{"schema":1,"store_id":"foreign","registry_id":"foreign"}')
        elif damage == "world_writable":
            root.chmod(0o777)
        elif damage == "symlink":
            target = tmp_path / "owned-target"
            root.rename(target)
            root.symlink_to(target, target_is_directory=True)
        elif damage == "marker_symlink":
            marker = root / ArtifactArea.MARKER
            target = tmp_path / "owned-marker"
            marker.rename(target)
            marker.symlink_to(target)
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    for action in (
        lambda: admin.initialize_artifacts("operator", binding, root=root, create=False, protect=lambda _: None),
        lambda: admin.verify_current_resources(
            "operator", binding, root=root, required_profiles=(), protect=lambda _: None
        ),
    ):
        with pytest.raises(ValueError):
            action()
    assert before == {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert root.exists() == (damage != "missing")
    if damage == "world_writable":
        assert root.stat().st_mode & 0o777 == 0o777


@pytest.mark.parametrize("profile_case", ["missing", "different", "duplicate"])
def test_scope_boot_exact_required_profiles_block_before_artifact_open(driver, tmp_path, monkeypatch, profile_case):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.admin import WorkflowScopeAdmin
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration, profile_revision
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    s, binding = binding_fixture(driver)
    s.initialize_bound_scope(binding, protect=lambda _: None)
    expected = profile_revision(ProfileRegistration.model_validate(profile_registration()))
    if profile_case != "missing":
        raw = profile_registration()
        if profile_case == "different":
            raw["roles"] = ["assessment_model"]
        s.register_profile(ProfileRegistration.model_validate(raw), protect=lambda _: None)
    admin = WorkflowScopeAdmin(s, SimpleNamespace(require_admin=lambda _: None))
    monkeypatch.setattr(ArtifactArea, "open", lambda *a, **k: pytest.fail("artifact open before required profiles"))
    before = binding_control(driver, s)
    with pytest.raises(ValueError, match="[Pp]rofile"):
        admin.verify_current_resources(
            "operator",
            binding,
            root=tmp_path / "absent",
            required_profiles=(expected,) * (2 if profile_case == "duplicate" else 1),
            protect=lambda _: None,
        )
    assert not (tmp_path / "absent").exists()
    assert binding_control(driver, s) == before


@pytest.mark.parametrize("operation", ["artifact", "verify"])
def test_scope_admin_closes_area_before_failed_return_protection(driver, tmp_path, monkeypatch, operation):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea, SafeBusy
    from isaaclab_arena.agentic_environment_generation.workflow.admin import WorkflowScopeAdmin

    s, binding = binding_fixture(driver)
    s.initialize_bound_scope(binding, protect=lambda _: None)
    root = tmp_path / "area"
    with ArtifactArea.create(root, store_id=binding.store_id, registry_id=binding.registry_id) as caller_owned:
        admin = WorkflowScopeAdmin(s, SimpleNamespace(require_admin=lambda _: None))
        with caller_owned.writer_lock():
            with pytest.raises(SafeBusy):
                admin.verify_current_resources(
                    "operator", binding, root=root, required_profiles=(), protect=lambda _: None
                )
        opened = []
        original = ArtifactArea.open

        def record(*args, **kwargs):
            area = original(*args, **kwargs)
            opened.append(area)
            return area

        monkeypatch.setattr(ArtifactArea, "open", record)

        def protect(value):
            if isinstance(value, dict) and "artifact_state" in value:
                assert opened[-1]._fd is None
                raise PermissionError("synthetic protection veto")

        with pytest.raises(PermissionError, match="synthetic protection veto"):
            if operation == "artifact":
                admin.initialize_artifacts("operator", binding, root=root, create=False, protect=protect)
            else:
                admin.verify_current_resources("operator", binding, root=root, required_profiles=(), protect=protect)
        assert opened and all(a._fd is None for a in opened)
        assert caller_owned._fd is not None


def test_joined_inspection_empty_pending_and_service(driver):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.tests.test_environment_workflow_service import contract

    s = scoped(driver)
    assert hasattr(s, "get_run_inspection"), "atomic joined point-read missing"
    assert s.get_run_inspection("missing") is None
    raw = canonical_json(contract())
    run = s.admit("inspection-pending", raw, raw, 1)
    view = s.get_run_inspection(run.run_id)
    assert view.intent == s.get_run_intent(run.run_id)
    assert view.cleanup == s.get_run_cleanup(run.run_id)
    assert view.retained_revision == s.get_run_inspection(run.run_id).retained_revision
    screened = []
    service = WorkflowService(s, SimpleNamespace(require_read=lambda p: None), None, validate_support=None)
    assert service.read_run_inspection("reader", run.run_id, protect=screened.append) == view
    assert screened == [view.model_dump(mode="json")]
    assert service.read_run_inspection("reader", "missing", protect=screened.append) is None
    assert screened[-1] is None
    assert scoped(driver).get_run_inspection(run.run_id) is None


def test_joined_inspection_reservations_readiness_and_full_width(driver):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    value = s.get_run_inspection(run.run_id)
    assert value.budget.reserved.model_calls == reservation.model_calls
    assert value.budget.reserved.candidates == 1
    assert value.budget.actual_consumption == "unknown"
    assert value.budget.deadline == 100.0 + contract.budget.total_deadline_seconds
    assert value.readiness[0].source == "intent.readiness_json"
    assert value.readiness[0].receipt.checked_at == 100.0
    assert value.readiness[0].current_readiness == "unknown"
    assert value.readiness[0].ttl_seconds is None
    assert value.actions.resume_branch == s.preview_resume(run.run_id).selection.branch
    assert value.actions.resume_intent_id == intent
    assert value.actions.permission_observation is None
    assert value.policy_outcome == "not_requested"
    assert value.publication_outcome == "not_permitted"
    assert value.experiment_outcome == "unknown"
    high = 2**63 - 2
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "SET r.version=$n, r.event_cursor=$n",
            **s.scope,
            n=high,
        ).consume()
    assert s.get_run_cleanup(run.run_id).run_version == high
    assert s.get_run_inspection(run.run_id).intent.run_version == high
    s.request_cancel(run.run_id, high)
    cancelled = s.get_run_inspection(run.run_id)
    assert cancelled.budget == value.budget  # Cancellation never refunds reservations.
    assert cancelled.retained_revision != value.retained_revision


def test_joined_inspection_permissions_are_after_snapshot_reject_only(driver):
    import traceback
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow import queries
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, _, _, _, _ = reserved(s)
    service = WorkflowService(s, SimpleNamespace(require_read=lambda p: None), None, validate_support=None)
    before = s.get_run_inspection(run.run_id)
    assert hasattr(queries, "ActionPermissionObservation"), "typed check-only observation missing"

    def check(principal, retained):
        assert principal == "reader" and retained == before
        # A real separate writer can acquire the lock before this callback returns.
        with ThreadPoolExecutor() as pool:
            pool.submit(s.request_cancel, run.run_id, retained.intent.run_version).result(timeout=3)
        return queries.ActionPermissionObservation(cancel="allowed", resume="denied", observed_at=101.0)

    result = service.read_run_inspection("reader", run.run_id, protect=lambda _: None, check_action_permission=check)
    assert result.retained_revision == before.retained_revision
    assert result.response_revision != before.response_revision
    assert result.intent.state == "running" and s.get_run(run.run_id).state == "cancel_requested"
    assert result.actions.permission_observation.resume == "denied"
    assert before.actions.permission_observation is None

    def bad(*args):
        raise RuntimeError("private-callback-sentinel")

    for kwargs in ({"protect": bad}, {"protect": lambda _: None, "check_action_permission": bad}):
        with pytest.raises(ValueError) as caught:
            service.read_run_inspection("reader", run.run_id, **kwargs)
        assert "private-callback-sentinel" not in "".join(
            traceback.format_exception(caught.type, caught.value, caught.tb)
        )
    with pytest.raises(ValueError):
        service.read_run_inspection("reader", run.run_id, protect=lambda body: body.clear())
    with pytest.raises(ValueError):
        service.read_run_inspection("reader", "missing", protect=bad)


def test_joined_inspection_atomic_old_new_and_hidden_dependency_revision(driver):
    from threading import Event

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, _, _ = reserved(s)
    old = s.get_run_inspection(run.run_id)
    locked, writer_attempted, release = Event(), Event(), Event()

    def read_visit(query, params):
        if "AS retained" in query:
            locked.set()
            assert writer_attempted.wait(3)
            assert release.wait(3)

    def write_visit(query, params):
        if "lock_anchor" in query:
            writer_attempted.set()

    reader = Neo4jWorkflowStore(inspection_driver(driver, read_visit, fetch_size=1), database=s.database, **s.scope)
    writer = Neo4jWorkflowStore(
        inspection_driver(driver, write_visit, fetch_size=None, before=True), database=s.database, **s.scope
    )
    with ThreadPoolExecutor() as pool:
        reading = pool.submit(reader.get_run_inspection, run.run_id)
        assert locked.wait(3)
        writing = pool.submit(writer.request_cancel, run.run_id, old.intent.run_version)
        assert writer_attempted.wait(3) and not writing.done()
        release.set()
        assert reading.result(timeout=4) == old
        writing.result(timeout=4)
    new = s.get_run_inspection(run.run_id)
    assert new.intent.state == "cancel_requested" and new.retained_revision != old.retained_revision
    assert new == s.get_run_inspection(run.run_id)  # control-lock increments excluded
    # Retained dependency variation that does not change aggregate allowances.
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "SET i.reservation_json=$raw",
            **s.scope,
            raw='{"model_calls":1,"model_tokens":100,"cost_ceiling_usd":1.00,"runtime_allowance_seconds":5.0}',
        ).consume()
    changed = s.get_run_inspection(run.run_id)
    assert changed.budget == new.budget
    assert changed.retained_revision != new.retained_revision


@pytest.mark.parametrize("field", ["run_id", "kind", "payload"])
def test_joined_history_metadata_is_bounded_before_bolt(driver, field):
    s = scoped(driver)
    with driver.session(database=s.database) as session:
        session.run(
            "CREATE (n:ArenaWorkflowEvidence {deployment_id:$deployment_id, workspace_id:$workspace_id, "
            "record_id:'bounded'}) SET n."
            + field
            + "=$value",
            **s.scope,
            value="x" * (2097153 if field == "payload" else 65537),
        ).consume()
    with s._transaction(fetch_size=1) as tx:
        row = s._historical_node(tx, "ArenaWorkflowEvidence", "bounded")
        assert len(str(row["node"][field])) < 100, "oversized retained metadata crossed Bolt"


def test_joined_inspection_whole_envelope_bound_and_retained_readiness(driver, monkeypatch):
    import json

    from isaaclab_arena.agentic_environment_generation.workflow import queries
    from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import canonical

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, _, _, _, _ = reserved(s)
    value = s.get_run_inspection(run.run_id)
    size = len(canonical(value.model_dump(mode="json"), max_bytes=queries.RUN_INSPECTION_BYTES))
    monkeypatch.setattr(queries, "RUN_INSPECTION_BYTES", size)
    assert s.get_run_inspection(run.run_id) == value
    monkeypatch.setattr(queries, "RUN_INSPECTION_BYTES", size - 1)
    with pytest.raises(queries.CorruptRunInspection):
        s.get_run_inspection(run.run_id)
    monkeypatch.undo()
    with driver.session(database=s.database) as session:
        query = "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
        raw = session.run(query + "RETURN i.readiness_json AS raw", **s.scope).single()["raw"]
        broken = json.loads(raw)
        broken["profiles"][0]["settings_sha256"] = "f" * 64
        session.run(query + "SET i.readiness_json=$raw", **s.scope, raw=json.dumps(broken)).consume()
    with pytest.raises(queries.CorruptRunInspection):
        s.get_run_inspection(run.run_id)


@pytest.mark.parametrize("policy", [False, True])
def test_joined_inspection_intent_ceilings_are_not_results_and_legacy_is_unchanged(driver, policy):
    import json

    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json, parse_contract
    from isaaclab_arena.agentic_environment_generation.workflow.read_model import workflow_result
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import scene_contract

    s = scoped(driver)
    body = scene_contract().model_dump(mode="json")
    body["effects"]["allow_publication"] = True
    with pytest.raises(ValueError, match="publication is unsupported"):
        parse_contract(json.dumps(body))
    body["effects"]["allow_publication"] = False
    if policy:
        body["execution"]["policy"] = body["execution"]["runtime"]
        body["criteria"][0].update(kind="policy", required_modalities=["policy_rollout"])
        body["budget"].update(max_policy_episodes=1, max_policy_steps=10)
    raw = canonical_json(parse_contract(json.dumps(body)))
    run = s.admit("intent-not-outcome", raw, raw, 1)
    legacy = workflow_result(s, run.run_id, protect=lambda _: None)
    value = s.get_run_inspection(run.run_id)
    assert value.policy_outcome == ("unsupported_or_unretained" if policy else "not_requested")
    assert value.publication_outcome == "not_permitted" and value.experiment_outcome == "unknown"
    assert value.scene is None and value.generation_outputs == () and value.readiness == ()
    assert value.actions.resume_branch is None and value.actions.permission_observation is None
    assert workflow_result(s, run.run_id, protect=lambda _: None) == legacy
    assert legacy["schema_version"] == 1


def scoped(driver, workspace=None, deployment="disposable-tests"):
    s = Neo4jWorkflowStore(
        driver,
        database=os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"],
        deployment_id=deployment,
        workspace_id=workspace or uuid.uuid4().hex,
    )
    assert s.verify_schema()
    s.initialize_scope()
    return s


@pytest.mark.parametrize("damage", ["fence", "registration", "contract", "fence_scalar"])
def test_resume_retained_decode_errors_are_static_before_callbacks(driver, damage):
    import json
    import traceback
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, _, _ = reserved(s)
    if damage != "contract":
        fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
        s.register_worker(fence, registration(fence))
    secret = "private-retained-selection-sentinel"
    raw = json.dumps({"generation": secret}) if damage == "fence" else json.dumps(secret)
    label, field = (
        ("ArenaWorkflowRun", "contract_json")
        if damage == "contract"
        else (
            ("ArenaExecutionAttempt", "registration_json")
            if damage == "registration"
            else ("ArenaExecutionIntent", "fence_json")
        )
    )
    query = "MATCH (n:" + label + " {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
    with driver.session(database=s.database) as session:
        session.run(query + "SET n." + field + "=$raw", **s.scope, raw=raw).consume()
    before = s.snapshot()
    calls = []
    service = WorkflowService(s, SimpleNamespace(require_read=lambda p: None), None, validate_support=None)
    payload = dict(runId=run.run_id, expectedVersion=s.get_run(run.run_id).version, renewAuthorization=False)
    operations = [
        lambda: s.preview_resume(run.run_id),
        lambda: service.admit_resume(
            "reader",
            "private-error",
            payload,
            check_resume=lambda *a: calls.append("permission"),
            check_eligibility=lambda *a, **kw: calls.append("eligibility"),
            protect=lambda v: None,
        ),
        lambda: s.admit_resume("direct-error", payload, selection=None, eligibility="current", protect=lambda v: None),
    ]
    if damage == "contract":
        operations[0], operations[1] = operations[1], operations[0]
    for operation in operations:
        with pytest.raises(ValueError) as caught:
            operation()
        assert str(caught.value) == "Invalid retained resume selection"
        assert secret not in "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert calls == []
    assert s.snapshot() == before
    assert s.get_resume_receipt("private-error") is None
    with driver.session(database=s.database) as session:
        assert session.run(query + "RETURN n." + field + " AS raw", **s.scope).single()["raw"] == raw


@pytest.mark.parametrize("field", ["registration_json", "cleanup_json", "released_at"])
def test_resume_generation_unclaimed_contradictions_do_not_promote(driver, field):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, _, _ = reserved(s)
    selection = s.preview_resume(run.run_id).selection
    admitted = s.admit_resume(
        "before-damage",
        dict(runId=run.run_id, expectedVersion=2, renewAuthorization=False),
        selection=selection,
        eligibility="current",
        protect=lambda v: None,
    )
    epoch = s.begin_owner("owner")
    query = (
        "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
        "WHERE i.intent_id=$id "
    )
    with driver.session(database=s.database) as session:
        session.run(
            query + "SET i." + field + "=$raw", **s.scope, id=intent, raw=100.0 if field == "released_at" else "{}"
        ).consume()
    before = s.snapshot()
    favorable = []
    try:
        preview = s.preview_resume(run.run_id)
        favorable.append(preview.selection is not None)
        result = s.admit_resume(
            "after-damage",
            dict(runId=run.run_id, expectedVersion=admitted.receipt.after_version, renewAuthorization=False),
            selection=preview.selection,
            eligibility="current",
            protect=lambda v: None,
        )
        favorable.append(result.receipt.disposition == "continuation_admitted")
    except ValueError:
        pass
    with pytest.raises(ValueError):
        s.claim_intent(intent, "owner", epoch, resume_operation_id="before-damage")
    assert not any(favorable), favorable
    assert s.snapshot() == before
    with driver.session(database=s.database) as session:
        assert session.run(query + "RETURN i." + field + " AS raw", **s.scope, id=intent).single()["raw"] == (
            100.0 if field == "released_at" else "{}"
        )


def test_resume_generation_admission_is_pinned_immutable_and_effect_free(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.commands import command_digest

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, reservation, contract = reserved(s)
    assert hasattr(s, "admit_resume"), "internal RESUME admission is missing"
    payload = dict(runId=run.run_id, expectedVersion=2, renewAuthorization=False)
    preview = s.preview_resume(run.run_id)
    result = s.admit_resume(
        "literal.Resume:1", payload, selection=preview.selection, eligibility="current", protect=lambda v: None
    )
    receipt = result.receipt
    assert result.fresh is True
    assert receipt.kind == "RESUME" and receipt.disposition == "continuation_admitted"
    assert receipt.before_version == 2 and receipt.after_version == 3
    assert receipt.selection.intent_id == intent and receipt.selection.branch == "generation"
    assert receipt.selection.contract_digest == command_digest(run.contract_json)
    assert receipt.authorization_action == "none"
    assert s.pending_generation(run.run_id)["reservation"] == reservation
    assert s.get_generation_attempt(run.run_id) is None
    event = s.events_after(2).events[0]
    assert (event.kind, event.command_kind, event.command_operation_id, event.source_id, event.operation_id) == (
        "ResumeAdmitted",
        "RESUME",
        "literal.Resume:1",
        intent,
        "generate",
    )
    assert s.get_resume_receipt("literal.Resume:1") == receipt
    s.request_cancel(run.run_id, 3)
    replay = s.admit_resume("literal.Resume:1", payload, selection=None, eligibility=None, protect=lambda v: None)
    assert replay.fresh is False and replay.receipt == receipt
    assert s.get_resume_receipt("literal.Resume:1") == receipt


@pytest.mark.parametrize(
    "case,reason",
    [
        ("missing", "target_not_found"),
        ("foreign", "target_not_found"),
        ("stale", "stale_version"),
        ("terminal", "inactive_run"),
        ("pending", "unsupported_branch"),
        ("not_ready", "private_eligibility_not_ready"),
        ("missing_grant", "private_eligibility_not_ready"),
        ("selection_changed", "selection_changed"),
    ],
)
def test_resume_authorized_refusals_are_retained_without_transition(driver, case, reason):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, _, _ = reserved(s)
    payload = dict(runId=run.run_id, expectedVersion=2, renewAuthorization=False)
    preview = s.preview_resume(run.run_id)
    eligibility = "current"
    if case in {"missing", "foreign"}:
        payload["runId"] = "absent" if case == "missing" else scoped(driver).admit("foreign", "{}", "{}", 1).run_id
    elif case == "stale":
        payload["expectedVersion"] = 1
    elif case == "terminal":
        s.request_cancel(run.run_id, 2)
        payload["expectedVersion"] = 3
    elif case == "pending":
        other = s.admit("pending", "{}", "{}", 1)
        payload.update(runId=other.run_id, expectedVersion=1)
    elif case in {"not_ready", "missing_grant"}:
        eligibility = "not_ready" if case == "not_ready" else "bind"
    else:
        preview.selection = preview.selection.model_copy(update={"intent_id": "different"})
    before = s.snapshot()
    result = s.admit_resume(
        "refused", payload, selection=preview.selection, eligibility=eligibility, protect=lambda v: None
    )
    assert result.fresh and result.receipt.disposition == "refused" and result.receipt.reason == reason
    assert not result.receipt.events and result.receipt.before_version == result.receipt.after_version
    assert s.snapshot() == before
    replay = s.admit_resume("refused", payload, selection=None, eligibility="current", protect=lambda v: None)
    assert not replay.fresh and replay.receipt == result.receipt


def test_resume_service_replay_precedes_permission_eligibility_and_config(driver):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.commands import CommandConflict
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, _, contract = reserved(s)
    calls = []
    authority = SimpleNamespace(require_read=lambda p: calls.append("read"))
    service = WorkflowService(s, authority, None, validate_support=None)
    assert hasattr(service, "admit_resume"), "shared RESUME admission missing"
    payload = dict(runId=run.run_id, expectedVersion=2, renewAuthorization=True)

    def permission(principal, operation_id, request):
        assert principal == "reader" and operation_id == "resume"
        assert request.model_dump() == payload
        calls.append("permission")

    def eligibility(principal, frozen, selection, *, renew_authorization):
        assert frozen == contract and selection.intent_id == intent and renew_authorization is True
        # A separate store transaction in this callback proves there is no held control lock.
        assert s.snapshot().runs[0].version == 2
        calls.append("eligibility")
        return "bind"

    result = service.admit_resume(
        "reader", "resume", payload, check_resume=permission, check_eligibility=eligibility, protect=lambda v: None
    )
    assert result.fresh and result.receipt.authorization_action == "bind"
    assert calls == ["read", "permission", "eligibility"]
    calls.clear()
    service._gate = service._validate_support = None
    replay = service.admit_resume(
        "second-reader", "resume", payload, check_resume=None, check_eligibility=None, protect=lambda v: None
    )
    assert not replay.fresh and replay.receipt == result.receipt and calls == ["read"]
    assert service.read_command("reader", "RESUME", "resume", protect=lambda v: None) == result.receipt
    for update in [dict(expectedVersion=3), dict(renewAuthorization=False), dict(runId="other")]:
        with pytest.raises(CommandConflict):
            service.admit_resume(
                "reader",
                "resume",
                dict(payload, **update),
                check_resume=None,
                check_eligibility=None,
                protect=lambda v: None,
            )
    assert calls == ["read"] * 5


@pytest.mark.parametrize("change", ["none", "version", "intent", "cancel", "wrong_key"])
def test_resume_generation_claim_rechecks_pin_in_actual_claim_transaction(driver, change):
    import inspect

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, reservation, _ = reserved(s)
    epoch = s.begin_owner("owner")
    preview = s.preview_resume(run.run_id)
    result = s.admit_resume(
        "pin",
        dict(runId=run.run_id, expectedVersion=2, renewAuthorization=False),
        selection=preview.selection,
        eligibility="current",
        protect=lambda v: None,
    )
    assert (
        "resume_operation_id" in inspect.signature(s.claim_intent).parameters
    ), "claim must enforce retained RESUME pin"
    if change in {"version", "intent"}:
        with driver.session(database=s.database) as session:
            if change == "version":
                session.run(
                    "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                    "SET r.version=r.version+1",
                    **s.scope,
                ).consume()
            else:
                session.run(
                    "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                    "SET i.status='superseded'",
                    **s.scope,
                ).consume()
    elif change == "cancel":
        s.request_cancel(run.run_id, 3)
    before = s.snapshot()
    if change == "none":
        fence = s.claim_intent(intent, "owner", epoch, resume_operation_id="pin")
        assert fence.intent_id == intent
        assert s.get_attempt(fence).reservation == reservation
        after_claim = s.snapshot()
        with pytest.raises(ValueError, match="Resume"):
            s.claim_intent(intent, "owner", epoch, resume_operation_id="pin")
        assert s.snapshot() == after_claim
    else:
        with pytest.raises(ValueError, match="[Rr]esume"):
            s.claim_intent(intent, "owner", epoch, resume_operation_id="absent" if change == "wrong_key" else "pin")
        assert s.get_generation_attempt(run.run_id) is None and s.snapshot() == before
    assert s.get_resume_receipt("pin") == result.receipt


@pytest.mark.parametrize("renew", [False, True])
def test_resume_registered_generation_reconciliation_is_read_only_not_new_work(driver, renew):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, _, _ = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    before = s.get_attempt(fence)
    version = s.get_run(run.run_id).version
    selection = s.preview_resume(run.run_id).selection
    assert selection is not None and selection.branch == "reconciliation", "registered attempt reconciliation missing"
    assert selection.fence == fence
    calls = []
    service = WorkflowService(
        s, SimpleNamespace(require_read=lambda p: calls.append("read")), None, validate_support=None
    )
    payload = dict(runId=run.run_id, expectedVersion=version, renewAuthorization=renew)
    result = service.admit_resume(
        "reader",
        "reconcile",
        payload,
        check_resume=lambda *a: calls.append("permission"),
        check_eligibility=None,
        protect=lambda v: None,
    )
    assert calls == ["read", "permission"]
    assert result.receipt.disposition == ("refused" if renew else "reconciliation_admitted")
    assert result.receipt.reason == ("renewal_not_applicable" if renew else None)
    assert result.receipt.selection.fence == fence
    assert result.receipt.authorization_action is None
    assert s.get_attempt(fence) == before and s.get_attempt(fence).registration == reg
    assert s.scene_snapshot(run.run_id) is None
    replay = service.admit_resume(
        "reader", "reconcile", payload, check_resume=None, check_eligibility=None, protect=lambda v: None
    )
    assert not replay.fresh and replay.receipt == result.receipt
    with pytest.raises(ValueError, match="Resume"):
        s.claim_intent(intent, "owner", fence.owner_epoch, resume_operation_id="reconcile")


@pytest.mark.parametrize("mode", ["same", "conflict_version", "conflict_bool", "different_keys"])
def test_resume_real_key_and_version_races_have_one_admission(driver, mode):
    from isaaclab_arena.agentic_environment_generation.workflow.commands import CommandConflict

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, reservation, _ = reserved(s)
    selection = s.preview_resume(run.run_id).selection
    barrier = Barrier(2)

    def admit(index):
        store = Neo4jWorkflowStore(driver, database=s.database, **s.scope)
        payload = dict(
            runId=run.run_id,
            expectedVersion=3 if mode == "conflict_version" and index else 2,
            renewAuthorization=bool(index) if mode == "conflict_bool" else False,
        )
        barrier.wait(timeout=10)
        try:
            return store.admit_resume(
                "key" + (str(index) if mode == "different_keys" else ""),
                payload,
                selection=selection,
                eligibility="current",
                protect=lambda v: None,
            )
        except CommandConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(admit, range(2)))
    if mode.startswith("conflict"):
        assert results.count("conflict") == 1
    else:
        assert sum(r.fresh and r.receipt.disposition == "continuation_admitted" for r in results) == 1
        if mode == "same":
            assert results[0].receipt == results[1].receipt and sum(r.fresh for r in results) == 1
        else:
            assert sorted(r.receipt.disposition for r in results) == ["continuation_admitted", "refused"]
            assert next(r.receipt for r in results if r.receipt.disposition == "refused").reason == "stale_version"
    admitted = [r for r in results if r != "conflict" and r.receipt.disposition == "continuation_admitted"]
    assert s.get_run(run.run_id).version == (3 if admitted else 2)
    assert s.get_generation_attempt(run.run_id) is None
    assert s.pending_generation(run.run_id)["reservation"] == reservation


@pytest.mark.parametrize("fault", ["rollback", "committed", "uncommitted", "close", "session_close"])
def test_resume_real_atomic_admission_unknown_ack_never_returns_fresh(driver, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, _, _, _, _ = reserved(s)
    selected = s.preview_resume(run.run_id).selection
    payload = dict(runId=run.run_id, expectedVersion=2, renewAuthorization=False)
    witnessed = []

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Tx(Proxy):
        def run(self, query, **params):
            result = self.real.run(query, **params)
            if fault == "rollback" and query.startswith("CREATE (c:ArenaResumeReceipt"):
                result.consume()
                row = self.real.run(
                    "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                    "RETURN r.version AS version",
                    **s.scope,
                ).single()
                assert row["version"] == 3
                assert (
                    self.real.run(
                        "MATCH (c:ArenaResumeReceipt {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                        "RETURN count(c) AS n",
                        **s.scope,
                    ).single()["n"]
                    == 1
                )
                witnessed.append("receipt_and_transition_before_rollback")
                raise ValueError("rollback injection")
            return result

        def commit(self):
            if fault != "uncommitted":
                self.real.commit()
            if fault in {"committed", "uncommitted"}:
                raise OSError("lost ACK")

        def close(self):
            self.real.close()
            witnessed.append("tx_closed")
            if fault == "close":
                raise OSError("close ACK lost")

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Tx(self.real.begin_transaction(**kwargs))

        def close(self):
            self.real.close()
            witnessed.append("session_closed")
            if fault == "session_close":
                raise OSError("session close ACK lost")

    class Driver(Proxy):
        def session(self, **kwargs):
            return Session(self.real.session(**kwargs))

    broken = Neo4jWorkflowStore(Driver(driver), database=s.database, **s.scope)
    with pytest.raises(ValueError if fault == "rollback" else OutcomeUnknown):
        broken.admit_resume("atomic", payload, selection=selected, eligibility="current", protect=lambda v: None)
    assert witnessed[-2:] == ["tx_closed", "session_closed"]
    committed = fault in {"committed", "close", "session_close"}
    receipt = s.get_resume_receipt("atomic")
    assert (receipt is not None) == committed
    assert s.get_run(run.run_id).version == (3 if committed else 2)
    assert len(s.events_after(0).events) == (3 if committed else 2)
    assert s.get_generation_attempt(run.run_id) is None
    if committed:
        replay = s.admit_resume("atomic", payload, selection=None, eligibility=None, protect=lambda v: None)
        assert not replay.fresh and replay.receipt == receipt
    # No automatic retry of an uncommitted/unknown command.


@pytest.mark.parametrize("fault", ["query", "transport", "commit", "cleanup"])
def test_resume_preview_preserves_query_transport_and_close_uncertainty(driver, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, _, _, _, _ = reserved(s)

    def visit(query, params):
        if query.startswith("MATCH (i:ArenaExecutionIntent") and fault in {"query", "transport"}:
            raise ValueError("query") if fault == "query" else OSError("transport")

    observed = Neo4jWorkflowStore(inspection_driver(driver, visit, fault=fault), database=s.database, **s.scope)
    expected = ValueError if fault == "query" else OSError if fault == "transport" else OutcomeUnknown
    with pytest.raises(expected) as caught:
        observed.preview_resume(run.run_id)
    if fault in {"query", "transport"}:
        assert str(caught.value) == fault
    assert s.preview_resume(run.run_id).selection.branch == "generation"


@pytest.mark.parametrize("fault", ["query", "transport", "commit", "cleanup"])
def test_resume_lookup_preserves_transport_and_unknown_priority(driver, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, _, _, _, _ = reserved(s)
    result = s.admit_resume(
        "read-fault",
        dict(runId=run.run_id, expectedVersion=2, renewAuthorization=False),
        selection=s.preview_resume(run.run_id).selection,
        eligibility="current",
        protect=lambda v: None,
    )

    def visit(query, params):
        if query.startswith("MATCH (c:ArenaResumeReceipt") and fault in {"query", "transport"}:
            raise ValueError("query") if fault == "query" else OSError("transport")

    observed = Neo4jWorkflowStore(inspection_driver(driver, visit, fault=fault), database=s.database, **s.scope)
    with pytest.raises(ValueError if fault == "query" else OSError if fault == "transport" else OutcomeUnknown):
        observed.get_resume_receipt("read-fault")
    assert s.get_resume_receipt("read-fault") == result.receipt


def test_resume_validation_to_first_scene_is_explicitly_unsupported(driver):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, _, _ = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    s.register_worker(fence, registration(fence))
    # Synthetic lifecycle fixture; no artifact or cleanup is invented by admission.
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "SET r.phase='validation'",
            **s.scope,
        ).consume()
    payload = dict(runId=run.run_id, expectedVersion=s.get_run(run.run_id).version, renewAuthorization=False)
    preview = s.preview_resume(run.run_id)
    result = s.admit_resume(
        "validation", payload, selection=preview.selection, eligibility=None, protect=lambda v: None
    )
    assert result.receipt.disposition == "refused" and result.receipt.reason == "unsupported_branch"
    assert result.receipt.contract_digest is not None


@pytest.mark.parametrize(
    "damage",
    [
        "json",
        "array",
        "oversize",
        "codec",
        "foreign_selection",
        "future_selection",
        "contract_selection",
        "wrong_refusal_reason",
    ],
)
def test_resume_refusal_corruption_is_static_bounded_and_never_repaired(driver, damage):
    import traceback

    from isaaclab_arena.agentic_environment_generation.workflow.commands import (
        CorruptResumeReceipt,
        command_digest,
        command_json,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, _, _, _, _ = reserved(s)
    payload = dict(runId=run.run_id, expectedVersion=2, renewAuthorization=False)
    result = s.admit_resume(
        "corrupt",
        payload,
        selection=s.preview_resume(run.run_id).selection,
        eligibility="not_ready",
        protect=lambda v: None,
    )
    body = result.receipt.model_dump(mode="json")
    if damage == "codec":
        body["codec_version"] = True
    elif damage == "foreign_selection":
        body["selection"]["run_id"] = "private-marker"
    elif damage == "future_selection":
        body["selection"]["version"] = 3
    elif damage == "contract_selection":
        body["selection"]["contract_digest"] = "f" * 64
    elif damage == "wrong_refusal_reason":
        body["reason"] = "renewal_not_applicable"
    body["receipt_digest"] = command_digest(command_json({k: v for k, v in body.items() if k != "receipt_digest"}))
    raw = {"json": '{"private-marker":', "array": ["private-marker" * 2000], "oversize": "private-marker" * 2000}.get(
        damage, command_json(body)
    )
    query = "MATCH (c:ArenaResumeReceipt {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
    with driver.session(database=s.database) as session:
        session.run(query + "SET c.receipt_json=$raw", **s.scope, raw=raw).consume()
    for action in (
        lambda: s.get_resume_receipt("corrupt"),
        lambda: s.admit_resume("corrupt", payload, selection=None, eligibility=None, protect=lambda v: None),
    ):
        with pytest.raises(CorruptResumeReceipt) as caught:
            action()
        assert "private-marker" not in "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    with driver.session(database=s.database) as session:
        assert session.run(query + "RETURN c.receipt_json AS raw", **s.scope).single()["raw"] == raw


def test_resume_lookup_and_cause_queries_are_indexed_scoped_bounded_and_readonly(driver):
    import json
    from pathlib import Path
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, _, _, _, _ = reserved(s)
    foreign = scoped(driver)
    for index in range(8):
        s.admit("history-" + str(index), "{}", "{}", 16)
        foreign.admit("foreign-" + str(index), "{}", "{}", 16)
    payload = dict(runId=run.run_id, expectedVersion=2, renewAuthorization=False)
    selected = s.preview_resume(run.run_id).selection
    queries = []
    observed = Neo4jWorkflowStore(
        inspection_driver(driver, lambda q, p: queries.append((q, p))), database=s.database, **s.scope
    )
    result = observed.admit_resume(
        "literal.Resume:1", payload, selection=selected, eligibility="current", protect=lambda v: None
    )
    causes = [(q, p) for q, p in queries if "e.sequence=$sequence" in q]
    assert len(causes) == 2
    assert all("command_kind='RESUME'" in q and p["source"] == selected.intent_id for q, p in causes)
    queries.clear()
    observed.admit_resume("stale", payload, selection=selected, eligibility="current", protect=lambda v: None)
    assert not any("ArenaWorkflowEvent" in q for q, _ in queries)

    def graph():
        with driver.session(database=s.database) as session:
            return [
                dict(r)
                for r in session.run(
                    "MATCH (n {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                    "RETURN elementId(n) AS id, properties(n) AS props ORDER BY id",
                    **s.scope,
                )
            ]

    before = graph()
    queries.clear()
    service = WorkflowService(observed, SimpleNamespace(require_read=lambda p: None), None, validate_support=None)
    assert service.read_command("reader", "RESUME", "literal.Resume:1", protect=lambda v: None) == result.receipt
    assert service.read_command("reader", "RESUME", "absent", protect=lambda v: None) is None
    assert foreign.get_resume_receipt("literal.Resume:1") is None
    assert before == graph()
    lookup = [(q, p) for q, p in queries if q != "SESSION_CLOSED"]
    assert len(lookup) == 2
    assert all(q.startswith("MATCH ") and "LIMIT 2" in q and "toStringOrNull" in q for q, _ in lookup)
    assert all(
        not any(token in q for token in ("SET ", "CREATE ", "MERGE ", "CALL ", "DELETE ", "properties("))
        for q, _ in lookup
    )
    plans = []

    def operators(plan):
        return [plan["operatorType"], *(op for child in plan.get("children", []) for op in operators(child))]

    with driver.session(database=s.database) as session:
        indexes = [dict(r) for r in session.run("SHOW INDEXES YIELD state, labelsOrTypes, properties RETURN *")]
        assert any(
            r["state"] == "ONLINE"
            and r["labelsOrTypes"] == ["ArenaResumeReceipt"]
            and r["properties"] == ["deployment_id", "workspace_id", "kind", "operation_id"]
            for r in indexes
        )
        for query, params in lookup + causes:
            plan = session.run("EXPLAIN " + query, **params).consume().plan
            ops = operators(plan)
            assert any("IndexSeek" in op for op in ops) and not any(
                "LabelScan" in op or "AllNodesScan" in op for op in ops
            ), ops
            plans.append(dict(query=query, operators=ops, plan=plan))
    Path("/evidence/resume-query-plans.json").write_text(json.dumps(plans))


@pytest.mark.parametrize("change", ["version", "contract"])
def test_resume_service_atomic_recheck_retains_callback_observation_race(driver, change):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, _, _, _, _ = reserved(s)
    calls = []
    service = WorkflowService(
        s, SimpleNamespace(require_read=lambda p: calls.append("read")), None, validate_support=None
    )

    def check(principal, contract, selection, *, renew_authorization):
        # Executes before admission; a driver transaction, not a fabricated preview.
        with driver.session(database=s.database) as session:
            update = "SET r.version=r.version+1" if change == "version" else "SET r.contract_json=$changed"
            session.run(
                "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) " + update,
                **s.scope,
                changed=run.contract_json + " ",
            ).consume()
        calls.append("eligibility")
        return "current"

    result = service.admit_resume(
        "reader",
        "race",
        dict(runId=run.run_id, expectedVersion=2, renewAuthorization=False),
        check_resume=lambda *a: calls.append("permission"),
        check_eligibility=check,
        protect=lambda v: None,
    )
    assert result.receipt.disposition == "refused"
    assert result.receipt.reason == ("stale_version" if change == "version" else "selection_changed")
    assert not result.receipt.events and s.get_generation_attempt(run.run_id) is None
    assert calls == ["read", "permission", "eligibility"]


@pytest.mark.parametrize("eligibility", ["current", "bind", "renew", "not_ready"])
def test_resume_requested_renewal_requires_explicit_future_action_eligibility(driver, eligibility):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, _, _, _, _ = reserved(s)
    result = s.admit_resume(
        "renewal",
        dict(runId=run.run_id, expectedVersion=2, renewAuthorization=True),
        selection=s.preview_resume(run.run_id).selection,
        eligibility=eligibility,
        protect=lambda v: None,
    )
    if eligibility in {"bind", "renew"}:
        assert result.receipt.disposition == "continuation_admitted"
        assert result.receipt.authorization_action == eligibility
    else:
        assert result.receipt.disposition == "refused" and result.receipt.reason == "private_eligibility_not_ready"
        assert result.receipt.authorization_action is None
    assert s.get_generation_attempt(run.run_id) is None


def test_resume_public_protection_never_holds_database_control_lock(driver):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, _, _, _, _ = reserved(s)
    selected = s.preview_resume(run.run_id).selection
    holding = False
    calls = []

    def visit(query, params):
        nonlocal holding
        if "SET c.lock_anchor=true" in query:
            holding = True
        elif query == "SESSION_CLOSED":
            holding = False

    def protect(value):
        assert not holding, "private public-screening callback invoked under store lock"
        # A real independent control-lock transaction must remain possible here.
        s.snapshot()
        calls.append(value)

    observed = Neo4jWorkflowStore(inspection_driver(driver, visit), database=s.database, **s.scope)
    payload = dict(runId=run.run_id, expectedVersion=2, renewAuthorization=False)
    result = observed.admit_resume("screen-lock", payload, selection=selected, eligibility="current", protect=protect)
    assert result.fresh and calls
    replay = observed.admit_resume("screen-lock", payload, selection=None, eligibility=None, protect=protect)
    assert not replay.fresh and replay.receipt == result.receipt


@pytest.mark.parametrize("phase", ["input", "response"])
def test_resume_screening_denial_never_returns_fresh_ticket(driver, phase):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, _, _, _, _ = reserved(s)

    def deny(value):
        if (phase == "input" and "payload" in value) or (phase == "response" and "receipt" in value):
            raise PermissionError("screening denied")

    with pytest.raises(PermissionError):
        s.admit_resume(
            "denied",
            dict(runId=run.run_id, expectedVersion=2, renewAuthorization=False),
            selection=s.preview_resume(run.run_id).selection,
            eligibility="current",
            protect=deny,
        )
    receipt = s.get_resume_receipt("denied")
    assert (receipt is not None) == (phase == "response")
    assert s.get_run(run.run_id).version == (3 if phase == "response" else 2)
    assert s.get_generation_attempt(run.run_id) is None


def test_resume_corrupt_lookup_cleanup_unknown_has_priority(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown

    s = scoped(driver)
    with driver.session(database=s.database) as session:
        session.run(
            "CREATE (c:ArenaResumeReceipt {deployment_id:$deployment_id, workspace_id:$workspace_id, "
            "kind:'RESUME', operation_id:'corrupt', receipt_json:'not-json'})",
            **s.scope,
        ).consume()
    observed = Neo4jWorkflowStore(
        inspection_driver(driver, lambda *a: None, fault="corrupt_cleanup"), database=s.database, **s.scope
    )
    with pytest.raises(OutcomeUnknown):
        observed.get_resume_receipt("corrupt")


def test_keyed_cancel_event_queries_use_exact_scoped_sequence(driver):
    import json
    from pathlib import Path

    from isaaclab_arena.agentic_environment_generation.workflow.commands import LocalStopObservation

    s, foreign = scoped(driver), scoped(driver)
    run = s.admit("indexed-cancel", "{}", "{}", 1)
    # Populate unrelated retained history in both scopes without changing the run.
    with driver.session(database=s.database) as session:
        for scope in (s.scope, foreign.scope):
            session.run(
                "UNWIND range(10000, 11000) AS sequence "
                "CREATE (e:ArenaWorkflowEvent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "SET e.sequence=sequence, e.run_id='other', e.kind='CancellationRequested', "
                "e.command_kind='CANCEL', e.command_operation_id='other', e.source_id='other'",
                **scope,
            ).consume()
    queries = []
    observed = Neo4jWorkflowStore(
        inspection_driver(driver, lambda q, p: queries.append((q, p))), database=s.database, **s.scope
    )
    receipt = observed.cancel_command(
        "indexed-cancel", run.run_id, LocalStopObservation(delivery="delivered"), protect=lambda v: None
    )
    event_queries = [(q, p) for q, p in queries if "MATCH (e:ArenaWorkflowEvent" in q]
    assert len(event_queries) == 2
    plans = []
    with driver.session(database=s.database) as session:
        for query, params in event_queries:
            plan = session.run("EXPLAIN " + query, **params).consume().plan
            plans.append(dict(query=query, params=params, plan=plan))
        Path("/evidence/cancel-event-plans.json").write_text(json.dumps(plans))
    for entry in plans:
        raw = json.dumps(entry["plan"])
        assert "IndexSeek" in raw and "NodeByLabelScan" not in raw, raw
        assert "e.sequence=" in entry["query"]
        assert receipt.events[0].sequence in entry["params"].values()
    for key, target in (("already", run.run_id), ("missing", "missing")):
        queries.clear()
        nontransition = observed.cancel_command(
            key, target, LocalStopObservation(delivery="no_owner"), protect=lambda v: None
        )
        assert nontransition.events == ()
        assert not any("ArenaWorkflowEvent" in q for q, _ in queries)
    assert s.get_cancel_receipt("indexed-cancel") == receipt


def test_keyed_cancel_atomic_receipt_replay_and_event_cause(driver):
    import hashlib
    import json

    s = scoped(driver)
    run = s.admit("same-key", "{}", "{}", 1)
    assert hasattr(s, "cancel_command"), "atomic keyed cancellation is missing"
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import LocalStopObservation

    first = LocalStopObservation(delivery="delivered")
    receipt = s.cancel_command("same-key", run.run_id, first, protect=lambda value: None)
    assert receipt.kind == "CANCEL" and receipt.operation_id == "same-key"
    assert receipt.run_id == run.run_id and receipt.disposition == "cancellation_requested"
    assert receipt.before_version == 1 and receipt.after_version == 2
    assert receipt.reason is None and receipt.first_local_stop == first
    assert receipt.codec_version == receipt.receipt_version == 1
    assert receipt.payload_json == json.dumps({"runId": run.run_id}, sort_keys=True, separators=(",", ":"))
    assert receipt.payload_digest == hashlib.sha256(receipt.payload_json.encode()).hexdigest()
    assert s.get_run(run.run_id).state == "cancelled"
    assert s.get_cancel_receipt("same-key") == receipt
    replay = s.cancel_command("same-key", run.run_id, LocalStopObservation(delivery="no_owner"), protect=lambda v: None)
    assert replay == receipt and len(s.events_after(0).events) == 2
    event = s.events_after(0).events[-1]
    assert event.operation_id == run.operation_id and event.source_id == run.run_id
    assert event.command_kind == "CANCEL" and event.command_operation_id == "same-key"
    assert receipt.events[0].sequence == event.sequence and receipt.events[0].source_id == run.run_id
    with driver.session(database=s.database) as session:
        row = session.run(
            "MATCH (c:ArenaCancelReceipt {deployment_id:$deployment_id, workspace_id:$workspace_id})"
            "-[:CAUSED]->(e:ArenaWorkflowEvent) RETURN count(e) AS count",
            **s.scope,
        ).single()
        assert row["count"] == 1


@pytest.mark.parametrize(
    "state, disposition, reason",
    [
        (None, "refused", "target_not_found"),
        ("accepted", "refused", "inactive_run"),
        ("cancel_requested", "already_requested", None),
        ("cancelled", "already_cancelled", None),
    ],
)
def test_keyed_cancel_retains_nontransition_dispositions(driver, state, disposition, reason):
    from isaaclab_arena.agentic_environment_generation.workflow.commands import LocalStopObservation

    s = scoped(driver)
    other = scoped(driver)
    run = other.admit("later", "{}", "{}", 1) if state is None else s.admit("later", "{}", "{}", 1)
    if state is not None:
        with driver.session(database=s.database) as session:
            session.run(
                "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "SET r.state=$state",
                **s.scope,
                state=state,
            ).consume()
    receipt = s.cancel_command("refusal", run.run_id, LocalStopObservation(delivery="no_owner"), protect=lambda v: None)
    assert (receipt.disposition, receipt.reason) == (disposition, reason)
    assert receipt.events == () and receipt.before_version == receipt.after_version
    if state is None:
        assert receipt.before_version is None
        # A target appearing later cannot change the bound refusal.
        with driver.session(database=s.database) as session:
            session.run(
                "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "SET r.workspace_id=$target",
                **other.scope,
                target=s.scope["workspace_id"],
            ).consume()
    assert (
        s.cancel_command("refusal", run.run_id, LocalStopObservation(delivery="delivered"), protect=lambda v: None)
        == receipt
    )
    assert len(s.events_after(0).events) == (0 if state is None else 1)


def test_read_command_kind_scope_and_readonly_lookup(driver):
    import json
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.commands import LocalStopObservation
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    assert hasattr(WorkflowService, "read_command"), "read-only command facade missing"
    s = scoped(driver)
    run = s.admit("shared-key", "{}", "{}", 1)
    receipt = s.cancel_command(
        "shared-key", run.run_id, LocalStopObservation(delivery="delivered"), protect=lambda v: None
    )
    calls = []
    service = WorkflowService(
        s, SimpleNamespace(require_read=lambda p: calls.append("read")), None, validate_support=None
    )

    def graph():
        with driver.session(database=s.database) as session:
            return [
                dict(row)
                for row in session.run(
                    "MATCH (n {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                    "RETURN elementId(n) AS id, properties(n) AS props ORDER BY id",
                    **s.scope,
                )
            ]

    before = graph()
    assert service.read_command("reader", "CANCEL", "shared-key", protect=lambda v: None) == receipt
    submit = service.read_command("reader", "SUBMIT", "shared-key", protect=lambda v: None)
    assert submit.kind == "SUBMIT" and submit.run_id == receipt.run_id
    assert service.read_command("reader", "CANCEL", "absent", protect=lambda v: None) is None
    assert service.read_command("reader", "RESUME", "shared-key", protect=lambda v: None) is None
    with pytest.raises(ValueError):
        service.read_command("reader", "cancel", "shared-key", protect=lambda v: None)
    assert before == graph() and len(calls) == 5
    other = scoped(driver)
    assert other.get_cancel_receipt("shared-key") is None
    assert (
        other.cancel_command(
            "shared-key", run.run_id, LocalStopObservation(delivery="no_owner"), protect=lambda v: None
        ).reason
        == "target_not_found"
    )
    assert s.get_cancel_receipt("shared-key") == receipt
    queries = []
    wrapped = Neo4jWorkflowStore(
        inspection_driver(driver, lambda q, p: queries.append((q, p))), database=s.database, **s.scope
    )
    assert wrapped.get_cancel_receipt("shared-key") == receipt
    with driver.session(database=s.database) as session:
        plans = []
        for query, params in queries:
            if query == "SESSION_CLOSED":
                continue
            assert "LIMIT 2" in query and not any(word in query for word in ("SET ", "CREATE ", "MERGE ", "DELETE "))
            plan = session.run("EXPLAIN " + query, **params).consume().plan
            assert "ArenaCancelReceipt" in json.dumps(plan) and "IndexSeek" in json.dumps(plan)
            plans.append(plan)
        from pathlib import Path

        Path("/evidence/cancel-lookup-plans.json").write_text(json.dumps(plans))


@pytest.mark.parametrize("conflicting", [False, True])
def test_keyed_cancel_real_same_key_races(driver, conflicting):
    from isaaclab_arena.agentic_environment_generation.workflow.commands import CommandConflict, LocalStopObservation

    s = scoped(driver)
    runs = [s.admit("race-one", "{}", "{}", 2), s.admit("race-two", "{}", "{}", 2)]
    barrier = Barrier(2)

    def cancel(index):
        store = Neo4jWorkflowStore(driver, database=s.database, **s.scope)
        barrier.wait(timeout=10)
        try:
            return store.cancel_command(
                "race-key",
                runs[index if conflicting else 0].run_id,
                LocalStopObservation(delivery="delivered"),
                protect=lambda v: None,
            )
        except CommandConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(cancel, range(2)))
    receipts = [r for r in results if r != "conflict"]
    assert len(receipts) == (1 if conflicting else 2)
    assert all(r == receipts[0] for r in receipts)
    assert s.get_cancel_receipt("race-key") == receipts[0]
    assert len(s.events_after(0).events) == 3
    assert sum(s.get_run(run.run_id).state == "cancelled" for run in runs) == 1


@pytest.mark.parametrize("fault", ["rollback", "committed", "uncommitted", "close"])
def test_keyed_cancel_real_transition_atomicity_unknown_ack_and_cleanup(driver, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.commands import LocalStopObservation
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown

    s = scoped(driver)
    run = s.admit("atomic", "{}", "{}", 1)
    witnessed = []

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Tx(Proxy):
        def run(self, query, **params):
            if fault == "rollback" and query.startswith("CREATE (c:ArenaCancelReceipt"):
                row = self.real.run(
                    "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                    "RETURN r.state AS state, r.version AS version",
                    **s.scope,
                ).single()
                assert dict(row) == dict(state="cancelled", version=2)
                witnessed.append("transition_before_receipt")
                raise ValueError("rollback injection")
            return self.real.run(query, **params)

        def commit(self):
            if fault != "uncommitted":
                self.real.commit()
            if fault in {"committed", "uncommitted"}:
                raise OSError("lost ACK")

        def close(self):
            self.real.close()
            witnessed.append("tx_closed")
            if fault == "close":
                raise OSError("close ACK lost")

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Tx(self.real.begin_transaction(**kwargs))

        def close(self):
            self.real.close()
            witnessed.append("session_closed")

    class Driver(Proxy):
        def session(self, **kwargs):
            return Session(self.real.session(**kwargs))

    broken = Neo4jWorkflowStore(Driver(driver), database=s.database, **s.scope)
    with pytest.raises(ValueError if fault == "rollback" else OutcomeUnknown):
        broken.cancel_command(
            "atomic-key", run.run_id, LocalStopObservation(delivery="delivered"), protect=lambda v: None
        )
    assert witnessed[-2:] == ["tx_closed", "session_closed"]
    retained = s.get_cancel_receipt("atomic-key")
    committed = fault in {"committed", "close"}
    assert (retained is not None) == committed
    assert s.get_run(run.run_id).state == ("cancelled" if committed else "pending")
    assert len(s.events_after(0).events) == (2 if committed else 1)
    recovered = s.cancel_command(
        "atomic-key", run.run_id, LocalStopObservation(delivery="no_owner"), protect=lambda v: None
    )
    assert recovered == (retained if committed else s.get_cancel_receipt("atomic-key"))
    assert recovered.first_local_stop.delivery == ("delivered" if committed else "no_owner")
    assert len(s.events_after(0).events) == 2


def test_keyed_cancel_collision_refusal_screening_and_old_receipt(driver, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow import neo4j_store
    from isaaclab_arena.agentic_environment_generation.workflow.commands import CommandConflict, LocalStopObservation

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, _, _ = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    receipt = s.cancel_command(
        "immutable", run.run_id, LocalStopObservation(delivery="delivered"), protect=lambda v: None
    )
    assert receipt.disposition == "cancellation_requested" and s.get_run(run.run_id).state == "cancel_requested"
    from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence

    # Real metadata cleanup/owner transitions with explicitly synthetic physical evidence.
    s.acknowledge_cleanup(
        fence,
        CleanupEvidence(
            registration=reg,
            evidence_ref="synthetic-stop",
            remote_effects="unknown",
            observation="owned_process_group_stopped",
        ),
    )
    assert s.get_run(run.run_id).state == "cancelled"
    s.retire_owner("owner", 1)
    s.begin_owner("replacement")
    assert s.get_run_cleanup(run.run_id).intents[0].retired_owner.owner_id == "owner"
    assert s.get_cancel_receipt("immutable") == receipt
    monkeypatch.setattr(neo4j_store, "command_digest", lambda raw: receipt.payload_digest)
    with pytest.raises(CommandConflict):
        s.cancel_command("immutable", "different", LocalStopObservation(delivery="delivered"), protect=lambda v: None)
    monkeypatch.undo()
    fresh = scoped(driver)
    pending = fresh.admit("screen", "{}", "{}", 1)

    def reject(value):
        if "receipt_digest" in value:
            raise PermissionError("rejected")

    with pytest.raises(PermissionError):
        fresh.cancel_command("screen", pending.run_id, LocalStopObservation(delivery="delivered"), protect=reject)
    assert fresh.get_cancel_receipt("screen") is None
    assert fresh.get_run(pending.run_id).state == "pending" and len(fresh.events_after(0).events) == 1


@pytest.mark.parametrize("damage", ["json", "array", "oversize", "codec", "missing_stop", "wrong_scope"])
def test_cancel_retained_corruption_is_static_and_preserved(driver, damage):
    import json
    import traceback

    from isaaclab_arena.agentic_environment_generation.workflow.commands import (
        CorruptCancelReceipt,
        LocalStopObservation,
    )

    s = scoped(driver)
    run = s.admit("corrupt", "{}", "{}", 1)
    receipt = s.cancel_command(
        "corrupt", run.run_id, LocalStopObservation(delivery="delivered"), protect=lambda v: None
    )
    body = receipt.model_dump(mode="json")
    if damage == "codec":
        body["codec_version"] = True
    elif damage == "missing_stop":
        del body["first_local_stop"]
    elif damage == "wrong_scope":
        body["scope"]["database"] = "private-marker"
    raw = {"json": '{"private-marker":', "array": ["private-marker" * 2000], "oversize": "private-marker" * 2000}.get(
        damage, json.dumps(body)
    )
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (c:ArenaCancelReceipt {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "SET c.receipt_json=$raw",
            **s.scope,
            raw=raw,
        ).consume()
    for action in (
        lambda: s.get_cancel_receipt("corrupt"),
        lambda: s.cancel_command(
            "corrupt", run.run_id, LocalStopObservation(delivery="delivered"), protect=lambda v: None
        ),
    ):
        with pytest.raises(CorruptCancelReceipt) as caught:
            action()
        assert "private-marker" not in "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    with driver.session(database=s.database) as session:
        row = session.run(
            "MATCH (c:ArenaCancelReceipt {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "RETURN c.receipt_json AS raw",
            **s.scope,
        ).single()
        assert row["raw"] == raw


@pytest.mark.parametrize("fault", ["query", "transport", "commit", "cleanup"])
def test_cancel_lookup_retains_query_transport_unknown_separation(driver, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.commands import LocalStopObservation
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown

    s = scoped(driver)
    run = s.admit("read-fault", "{}", "{}", 1)
    receipt = s.cancel_command(
        "read-fault", run.run_id, LocalStopObservation(delivery="no_owner"), protect=lambda v: None
    )

    def visit(query, params):
        if query.startswith("MATCH (c:ArenaCancelReceipt") and fault in {"query", "transport"}:
            raise ValueError("query") if fault == "query" else OSError("transport")

    observed = Neo4jWorkflowStore(inspection_driver(driver, visit, fault=fault), database=s.database, **s.scope)
    with pytest.raises(ValueError if fault == "query" else OSError if fault == "transport" else OutcomeUnknown):
        observed.get_cancel_receipt("read-fault")
    assert s.get_cancel_receipt("read-fault") == receipt


def test_request_free_admission_survives_lifecycle_with_fresh_client(driver):
    import hashlib
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate, DependencyResult
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.tests.test_environment_workflow_service import contract

    s = scoped(driver)
    s.clock = lambda: 100.0
    authority = SimpleNamespace(require_read=lambda p: None, require_submit=lambda *a: None)
    gate = DependencyGate(lambda dep, timeout: DependencyResult(
        dep.dependency_id, "passed", dep.profile_sha256, profile_id=dep.profile_id,
    ))
    raw = canonical_json(contract())
    admitted = WorkflowService(s, authority, gate, validate_support=lambda c: None).submit("reader", "Literal.Key:1", raw)
    assert admitted.disposition == "accepted"
    assert hasattr(s, "get_submission_inspection"), "request-free admission inspection missing"

    def forbidden(*args, **kwargs):
        pytest.fail("historical read must not resolve grants, catalogues, probes or artifacts")

    def read():
        with GraphDatabase.driver(os.environ["ARENA_WORKFLOW_NEO4J_URI"], auth=None,
                                  max_transaction_retry_time=0) as fresh:
            store = Neo4jWorkflowStore(fresh, database=s.database, **s.scope)
            store.get_profile = store.list_profiles = forbidden
            service = WorkflowService(store, SimpleNamespace(require_read=lambda p: None, require_submit=forbidden),
                                      SimpleNamespace(check=forbidden), validate_support=forbidden)
            screens = []
            value = service.read_submission("reader", "Literal.Key:1", protect=lambda v: screens.append(v))
            assert screens == [value.model_dump(mode="json")]
            return value

    value = read()
    assert value.scope.database == s.database and value.scope.workspace_id == s.scope["workspace_id"]
    assert value.operation_id == "Literal.Key:1" and value.run_id == admitted.run.run_id
    assert value.kind == "SUBMIT" and value.disposition == "retained_admission"
    assert value.provenance == "legacy_run_record" and value.admitted_at == 100.0
    assert value.request_digest == value.accepted_contract_digest == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert value.digest_codec == "sha256-canonical-json-utf8-v1"
    assert value.receipt_version is None and value.cause_id is None
    assert "state" not in value.model_dump() and "request_json" not in value.model_dump()
    with pytest.raises(ValueError):
        value.operation_id = "changed"
    s.request_cancel(admitted.run.run_id, 1)
    assert s.get_run(admitted.run.run_id).state == "cancelled"
    with driver.session(database=s.database) as session:
        session.run("MATCH (e:ArenaWorkflowEvent {deployment_id:$deployment_id, workspace_id:$workspace_id}) DELETE e",
                    **s.scope).consume()
    assert read() == value
    assert s.get_submission_inspection("missing") is None
    assert scoped(driver).get_submission_inspection("Literal.Key:1") is None
    opaque = s.admit("opaque", '{"legacy":"界"}', '{"accepted":true}', 1)
    assert s.get_submission_inspection("opaque").run_id == opaque.run_id
    assert s.get_submission_inspection("opaque").request_digest == hashlib.sha256('{"legacy":"界"}'.encode()).hexdigest()


@pytest.mark.parametrize("boundary", [False, True])
def test_frozen_run_intent_reads_exact_contract_and_full_width_lifecycle(driver, boundary):
    import hashlib
    import json
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.contracts import MAX_CONTRACT_BYTES, canonical_json, parse_contract
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.tests.test_environment_workflow_service import contract

    s = scoped(driver)
    value = contract(existing=True)
    if boundary:
        body = value.model_dump(mode="json")
        body["source"]["content"] = ""
        empty_size = len(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
        remaining = MAX_CONTRACT_BYTES - empty_size
        body["source"]["content"] = "界" * (remaining // 3) + "x" * (remaining % 3)
        value = parse_contract(json.dumps(body, ensure_ascii=False, separators=(",", ":")))
    raw = canonical_json(value)
    if boundary:
        assert len(raw.encode()) == MAX_CONTRACT_BYTES
    run = s.admit("intent-exact", raw, raw, 1)
    assert hasattr(s, "get_run_intent"), "frozen retained intent reader missing"

    def forbidden(*a, **kw):
        pytest.fail("frozen intent cannot resolve current inputs")

    def read():
        with GraphDatabase.driver(os.environ["ARENA_WORKFLOW_NEO4J_URI"], auth=None,
                                  max_transaction_retry_time=0) as fresh:
            store = Neo4jWorkflowStore(fresh, database=s.database, **s.scope)
            store.get_profile = store.list_profiles = forbidden
            service = WorkflowService(store, SimpleNamespace(require_read=lambda p: None, require_submit=forbidden),
                                      SimpleNamespace(check=forbidden), validate_support=forbidden)
            return service.read_run_intent("reader", run.run_id, protect=lambda v: None)

    initial = read()
    assert initial.contract == value and canonical_json(initial.contract) == raw
    assert initial.state == "pending" and initial.phase == "dependency_readiness"
    assert initial.run_version == 1 and initial.event_cursor == run.event_cursor
    assert initial.submission == s.get_submission_inspection("intent-exact")
    assert "revision" not in initial.contract.execution.generation_model.model_dump()
    assert not {"cleanup", "available_actions", "outcomes", "budget_consumption", "projection_revision"} & initial.model_dump().keys()
    with pytest.raises(ValueError):
        initial.contract.source.content = "changed"
    s.request_cancel(run.run_id, 1)
    changed = read()
    assert changed.state == "cancelled" and changed.run_version == 2
    assert changed.submission == initial.submission and changed.contract == initial.contract
    assert changed.intent_projection_revision != initial.intent_projection_revision
    assert read() == changed
    expected = changed.model_dump(mode="json", exclude={"intent_projection_revision"})
    assert changed.intent_projection_revision == hashlib.sha256(json.dumps(
        expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode()).hexdigest()
    with driver.session(database=s.database) as session:
        session.run("MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$id}) "
                    "SET r.version=$wide, r.event_cursor=$wide", **s.scope, id=run.run_id, wide=2**63 - 1).consume()
    wide = read()
    assert wide.run_version == wide.event_cursor == 2**63 - 1
    assert wide.submission == initial.submission
    assert s.get_run_intent("missing") is None
    assert scoped(driver).get_run_intent(run.run_id) is None


@pytest.mark.parametrize("damage", [
    "request_json", "contract_json", "noncanonical", "missing", "sentinel", "utf8_overflow", "run_id",
    "operation_id", "admitted_at", "request_digest", "accepted_contract_digest", "digest_codec",
    "contract_codec", "contract_defaults", "version_bool", "version_float", "version_zero", "cursor_negative",
    "state", "phase",
])
def test_admission_intent_retained_corruption_is_static_and_not_repaired(driver, damage):
    import json
    import traceback
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptRunRecord
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.tests.test_environment_workflow_service import contract

    s = scoped(driver)
    raw = canonical_json(contract())
    run = s.admit("corrupt-admission", raw, raw, 1)
    marker = "PRIVATE-RETAINED-SENTINEL"
    field, bad = damage, marker
    if damage == "noncanonical":
        field, bad = "request_json", '{ "private": "' + marker + '" }'
    elif damage == "missing":
        field, bad = "request_json", None
    elif damage in ("sentinel", "utf8_overflow"):
        field, bad = "request_json", json.dumps({"private": marker + ("x" * 2097152 if damage == "sentinel" else "界" * 800000)}, ensure_ascii=False)
    elif damage == "admitted_at":
        bad = True
    elif damage == "contract_codec":
        body = json.loads(raw)
        body["schema_version"] = marker
        field, bad = "contract_json", json.dumps(body, sort_keys=True, separators=(",", ":"))
    elif damage == "contract_defaults":
        body = json.loads(raw)
        del body["effects"]["allow_dcrg"]
        field, bad = "contract_json", json.dumps(body, sort_keys=True, separators=(",", ":"))
    elif damage.startswith("version_"):
        field, bad = "version", {"version_bool": True, "version_float": 1.0, "version_zero": 0}[damage]
    elif damage == "cursor_negative":
        field, bad = "event_cursor", -1
    query = "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
    with driver.session(database=s.database) as session:
        session.run(query + "SET r[$field]=$bad", **s.scope, field=field, bad=bad).consume()
        before = dict(session.run(query + "RETURN properties(r) AS r", **s.scope).single()["r"])
        assert before.get(field) == bad
        screens = []
        service = WorkflowService(s, SimpleNamespace(require_read=lambda p: None), None, validate_support=None)
        # Opaque legacy contracts remain valid admission facts. Mutable lifecycle
        # damage likewise must not turn an admission into a terminal receipt.
        only_intent = damage in {"contract_codec", "contract_defaults", "version_bool", "version_float", "version_zero", "cursor_negative", "state", "phase"}
        methods = [(service.read_run_intent, run.run_id)] if only_intent else [
            (service.read_submission, "corrupt-admission"), (service.read_run_intent, run.run_id),
        ]
        if damage == "run_id":
            methods[1] = (service.read_run_intent, marker)
        if damage == "operation_id":
            methods[0] = (service.read_submission, marker)
        for method, identity in methods:
            with pytest.raises(CorruptRunRecord, match="^Invalid retained run record$") as caught:
                method("reader", identity, protect=lambda v: screens.append(v))
            assert marker not in str(caught.value)
            assert marker not in "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
        assert screens == []
        if only_intent:
            assert s.get_submission_inspection("corrupt-admission").run_id == run.run_id
        assert dict(session.run(query + "RETURN properties(r) AS r", **s.scope).single()["r"]) == before


@pytest.mark.parametrize("field", ["request_json", "contract_json", "admitted_at", "version", "event_cursor", "state", "phase"])
@pytest.mark.parametrize("value_kind", ["number", "array", "oversize"])
def test_inspection_corrupt_physical_properties_are_bounded_before_hydration(driver, field, value_kind):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptRunRecord
    from isaaclab_arena.tests.test_environment_workflow_service import contract

    s = scoped(driver)
    raw = canonical_json(contract())
    run = s.admit("physical-bound", raw, raw, 1)
    value = 12 if value_kind == "number" else ["private" * 100000] if value_kind == "array" else "private" * 400000
    with driver.session(database=s.database) as session:
        session.run("MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                    "SET r[$field]=$value", **s.scope, field=field, value=value).consume()
    # Capture the actual production projection, independently of the decoder.
    with s._transaction() as tx:
        row = s._inspection_rows(tx, "run_id", run.run_id)[0]["retained"]
    if value_kind != "number":
        assert row[field] is None, "unbounded corrupt physical value crossed the query projection"
    if value_kind == "number" and field in {"version", "event_cursor", "admitted_at"}:
        assert s.get_run_intent(run.run_id) is not None
    else:
        with pytest.raises(CorruptRunRecord, match="^Invalid retained run record$"):
            s.get_run_intent(run.run_id)


def check_joined_query_faults(driver, store, run_id, targets):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown

    mismatches = []
    for target in targets:
        for advance in (False, True):
            for error in (ValueError, TypeError):
                for close in (False, True):
                    failure = error("actual joined query wrapper error")
                    observed = Neo4jWorkflowStore(
                        inspection_driver(
                            driver, lambda *args: None, fetch_size=1,
                            fault=(target, advance, failure, close),
                        ), database=store.database, **store.scope,
                    )
                    with pytest.raises((OutcomeUnknown, ValueError, TypeError)) as caught:
                        observed.get_run_inspection(run_id)
                    if (close and type(caught.value) is not OutcomeUnknown) or (
                        not close and caught.value is not failure
                    ):
                        mismatches.append((target, advance, error.__name__, close, type(caught.value).__name__))
    assert not mismatches, mismatches


@pytest.mark.parametrize(
    "target", ["AS run, elementId(r)", "AS owner", "AS intent,", "AS receipt LIMIT", "AS ownership"]
)
def test_joined_query_failures_are_not_corrupt_data(driver, target):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, _, _, _, _ = reserved(s)
    check_joined_query_faults(driver, s, run.run_id, [target])


def inspection_driver(real_driver, visit, *, fault=None, fetch_size=2, before=False):
    """Thin real-driver observer/fault injector; never fabricate query results."""
    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Transaction(Proxy):
        def run(self, query, **params):
            if before:
                visit(query, params)
            result = self.real.run(query, **params)
            if not before:
                visit(query, params)
            if isinstance(fault, tuple) and fault[0] in query:
                if not fault[1]:
                    result.consume()
                    raise fault[2]

                class FailedAdvance(Proxy):
                    def __iter__(self):
                        yield from self.real
                        raise fault[2]

                    def single(self, **kwargs):
                        self.real.single(**kwargs)
                        raise fault[2]

                return FailedAdvance(result)
            if fault in {"query", "transport"} and "AS retained" in query:
                result.consume()
                if fault == "query":
                    raise ValueError("actual query wrapper error")
                raise OSError("actual transport wrapper error")
            return result

        def commit(self):
            self.real.commit()
            if fault == "commit":
                raise OSError("lost acknowledgement after real commit")

        def close(self):
            self.real.close()
            if fault in {"cleanup", "corrupt_cleanup"} or (isinstance(fault, tuple) and fault[3]):
                raise OSError("transaction close failed after actual close")

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            assert kwargs == {"timeout": 5}
            return Transaction(self.real.begin_transaction(**kwargs))

        def close(self):
            self.real.close()
            visit("SESSION_CLOSED", {})

    class Driver(Proxy):
        def session(self, **kwargs):
            assert kwargs.get("fetch_size") == fetch_size
            return Session(self.real.session(**kwargs))

    return Driver(real_driver)


def test_inspection_exact_queries_are_indexed_bounded_and_domain_read_only(driver):
    import json
    from pathlib import Path

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, _, auth, _, _ = reserved(s)
    s.clock = lambda: auth.expires_at + 1000
    queries = []
    observed = Neo4jWorkflowStore(inspection_driver(driver, lambda q, p: queries.append((q, p))),
                                 database=s.database, **s.scope)
    before = s.snapshot()
    admission = observed.get_submission_inspection(run.operation_id)
    intent = observed.get_run_intent(run.run_id)
    assert intent.state == "running" and intent.phase == "generation"
    assert intent.submission == admission
    assert observed.get_run_intent(run.run_id) == intent
    assert s.snapshot() == before
    plans = []
    with driver.session(database=s.database) as session:
        indexes = list(session.run("SHOW INDEXES YIELD state, labelsOrTypes, properties RETURN *"))
        for field in ("run_id", "operation_id"):
            assert any(i["state"] == "ONLINE" and i["labelsOrTypes"] == ["ArenaWorkflowRun"]
                       and i["properties"] == ["deployment_id", "workspace_id", field] for i in indexes)
        for query, params in queries:
            if query == "SESSION_CLOSED" or "SET c.lock_anchor=true" in query:
                continue
            assert "LIMIT 2" in query and "properties(" not in query and "toStringOrNull" in query
            assert not any(word in query for word in ("SET ", "CREATE ", "MERGE ", "DELETE ", "CALL "))
            plan = session.run("EXPLAIN " + query, **params).consume().plan
            nodes, seeks = [plan], []
            while nodes:
                node = nodes.pop()
                assert "LabelScan" not in node["operatorType"] and "AllNodesScan" not in node["operatorType"]
                if "IndexSeek" in node["operatorType"]:
                    seeks.append(node["args"]["Details"])
                nodes.extend(node.get("children", []))
            field = "operation_id" if "WHERE r.operation_id=" in query else "run_id"
            assert any("ArenaWorkflowRun(deployment_id, workspace_id, " + field + ")" in seek for seek in seeks)
            plans.append(dict(query=query, plan=plan, seeks=seeks))
    assert len(plans) == 3
    Path("/evidence/admission-intent-plans.json").write_text(json.dumps(plans, sort_keys=True))


@pytest.mark.parametrize("kind", ["submission", "run_intent", "run_inspection"])
@pytest.mark.parametrize("fault", ["query", "transport", "commit", "cleanup", "corrupt_cleanup"])
def test_inspection_transport_commit_and_cleanup_precedence(driver, kind, fault):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.tests.test_environment_workflow_service import contract

    s = scoped(driver)
    raw = canonical_json(contract())
    run = s.admit("read-fault", raw, raw, 1)
    if fault == "corrupt_cleanup":
        with driver.session(database=s.database) as session:
            session.run("MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                        "SET r.request_json='private-invalid'", **s.scope).consume()
    calls, screens = [], []
    observed = Neo4jWorkflowStore(
        inspection_driver(
            driver, lambda q, p: calls.append(q), fault=fault, fetch_size=1 if kind == "run_inspection" else 2
        ),
        database=s.database,
        **s.scope,
    )
    service = WorkflowService(observed, SimpleNamespace(require_read=lambda p: None), None, validate_support=None)
    error = ValueError if fault == "query" else OSError if fault == "transport" else OutcomeUnknown
    with pytest.raises(error) as caught:
        getattr(service, "read_" + kind)("reader", run.operation_id if kind == "submission" else run.run_id,
                                        protect=lambda v: screens.append(v))
    assert type(caught.value) is error
    assert "SESSION_CLOSED" in calls and screens == []
    assert s.get_run(run.run_id).version == 1
    if fault != "corrupt_cleanup":
        assert s.get_submission_inspection(run.operation_id).run_id == run.run_id
        assert s.get_run_intent(run.run_id).run_version == 1


@pytest.mark.parametrize("method", ["get_submission_inspection", "get_run_intent", "get_run_inspection"])
def test_inspection_missing_uninitialized_scope_is_absent(driver, method):
    s = Neo4jWorkflowStore(driver, database=os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"],
                           deployment_id="uninitialized-inspection", workspace_id=uuid.uuid4().hex)
    assert getattr(s, method)("missing") is None


@pytest.mark.parametrize("width", [500, 1500])
def test_inspection_scope_wrapper_has_finite_utf8_bound(driver, width):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptRunRecord
    from isaaclab_arena.tests.test_environment_workflow_service import contract

    s = scoped(driver, workspace="界" * width)
    raw = canonical_json(contract())
    run = s.admit("scope-bound", raw, raw, 1)
    for method, identity in ((s.get_submission_inspection, run.operation_id), (s.get_run_intent, run.run_id)):
        if width == 500:
            assert method(identity).scope.workspace_id == "界" * width
        else:
            with pytest.raises(CorruptRunRecord, match="^Invalid retained run record$"):
                method(identity)


def test_inspection_rejects_duplicate_identity_without_rekeying(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptRunRecord
    from isaaclab_arena.tests.test_environment_workflow_service import contract

    s = scoped(driver)
    raw = canonical_json(contract())
    run = s.admit("duplicate-inspection", raw, raw, 1)
    with driver.session(database=s.database) as session:
        for name in ("operation", "run"):
            session.run("DROP CONSTRAINT arena_workflow_" + name).consume()
        duplicate = None
        try:
            duplicate = session.run(
                "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "CREATE (copy:ArenaWorkflowRun) SET copy=properties(r) RETURN elementId(copy) AS id", **s.scope,
            ).single()["id"]
            for method, identity in ((s.get_submission_inspection, run.operation_id), (s.get_run_intent, run.run_id)):
                with pytest.raises(CorruptRunRecord, match="^Invalid retained run record$"):
                    method(identity)
            assert session.run("MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                               "RETURN count(r) AS n", **s.scope).single()["n"] == 2
        finally:
            if duplicate is not None:
                session.run("MATCH (n) WHERE elementId(n)=$id DELETE n", id=duplicate).consume()
            for ddl in Neo4jWorkflowStore.schema_requirements():
                session.run(ddl).consume()
            session.run("CALL db.awaitIndexes(30)").consume()
    assert s.get_submission_inspection(run.operation_id).run_id == run.run_id


def test_run_cleanup_empty_projection_is_stable_and_shared(driver):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    s = scoped(driver)
    run = s.admit("cleanup-empty", "{}", "{}", 1)
    assert hasattr(s, "get_run_cleanup"), "bounded retained cleanup query missing"
    calls = []
    service = WorkflowService(s, SimpleNamespace(require_read=lambda p: calls.append(p)), None, validate_support=None)
    before = s.snapshot()
    value = service.read_run_cleanup("reader", run.run_id, protect=lambda v: calls.append(v))
    assert value.run_id == run.run_id and value.intents == ()
    assert value.current_scope_owner is None and value.run_version == run.version
    assert value == service.read_run_cleanup("reader", run.run_id, protect=lambda v: None)
    assert s.snapshot() == before
    assert calls == ["reader", value.model_dump(mode="json"), "reader"]
    with pytest.raises(ValueError):
        value.run_version = 900
    assert s.get_run_cleanup("missing") is None
    assert scoped(driver).get_run_cleanup(run.run_id) is None


@pytest.mark.parametrize("release", [False, True])
def test_run_cleanup_generation_obligation_lifecycle(driver, release):
    from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence, ReconciliationReason

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, _, contract = reserved(s)
    before = s.snapshot()
    value = s.get_run_cleanup(run.run_id)
    (item,) = value.intents
    assert item.intent_id == intent and item.kind == "generation"
    assert item.cleanup_state == "not_started" and item.release_state == "known_unreleased"
    assert item.fence is None and item.registration_id is None
    assert s.snapshot() == before
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    claimed = s.get_run_cleanup(run.run_id)
    assert claimed.intents[0].cleanup_state == "unknown"
    assert claimed.intents[0].fence == fence
    reg = s.register_worker(fence, registration(fence))
    registered = s.get_run_cleanup(run.run_id)
    assert registered.intents[0].registration_id == reg.registration_id
    assert registered.intents[0].cleanup_state == "unknown"
    if release:
        assert s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
        s.mark_reconciliation_required(fence, ReconciliationReason.RELEASED_WITHOUT_RECEIPT)
        with driver.session(database=s.database) as session:
            session.run(
                "MATCH (a:ArenaExecutionAttempt {deployment_id:$deployment_id, workspace_id:$workspace_id, "
                "attempt_id:$id}) SET a.released_at=0.0", **s.scope, id=fence.attempt_id,
            ).consume()
        assert s.get_run_cleanup(run.run_id).intents[0].release_state == "released"
    evidence = CleanupEvidence(
        registration=reg,
        evidence_ref="synthetic-stop",
        remote_effects="unknown",
        observation="owned_process_group_stopped",
    )
    s.acknowledge_cleanup(fence, evidence)
    retained = s.get_run_cleanup(run.run_id)
    (item,) = retained.intents
    assert item.cleanup_state == "recorded" and item.cleanup_evidence_ref == evidence.evidence_ref
    assert item.cleanup_observation == evidence.observation and item.remote_effects == "unknown"
    assert item.release_state == ("released" if release else "known_unreleased")
    assert item.retired_owner is None and retained.current_scope_owner.dirty
    assert retained.projection_revision != registered.projection_revision
    assert "pid" not in item.model_dump_json() and "registration" not in item.model_dump()
    if release:
        assert s.get_run(run.run_id).state == "reconciliation_required"
    s.request_cancel(run.run_id, s.get_run(run.run_id).version)
    s.retire_owner("owner", 1)
    retired = s.get_run_cleanup(run.run_id)
    assert retired.intents[0].retired_owner == s.get_retired_owner("owner")
    s.begin_owner("replacement")
    historical = s.get_run_cleanup(run.run_id)
    assert historical.intents == retired.intents
    assert historical.current_scope_owner.owner_id == "replacement"
    assert historical.projection_revision != retired.projection_revision
    assert historical.run_version == retired.run_version
    assert historical == s.get_run_cleanup(run.run_id)
    next_run = s.admit("cleanup-next", "{}", run.contract_json, 1)
    next_intent = s.reserve_generation(
        next_run.run_id, 1, "next", auth, s.get_attempt(fence).reservation, readiness=readiness(contract, auth)
    )
    s.claim_intent(next_intent, "replacement", 2)
    assert s.get_run_cleanup(run.run_id) == historical
    assert s.get_run_cleanup(next_run.run_id).intents[0].cleanup_state == "unknown"
    # A retained retirement or B's activity must never substitute for A's own receipt.
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id, intent_id:$id})"
            "-[:HAS_ATTEMPT]->(a) REMOVE i.cleanup_json, a.cleanup_json",
            **s.scope,
            id=intent,
        ).consume()
    unresolved = s.get_run_cleanup(run.run_id)
    assert unresolved.intents[0].cleanup_state == "unknown"
    assert unresolved.intents[0].retired_owner == retired.intents[0].retired_owner
    assert unresolved.projection_revision != historical.projection_revision


@pytest.mark.parametrize("receipt_only", [False, True])
def test_cancelled_cleanup_rejects_erased_release_time(completion_input, driver, receipt_only):
    from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptCleanupRecord
    from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence

    f, handle, artifacts, receipt, _ = completion_input
    s, fence = f.store, handle.fence
    if receipt_only:
        assert s.commit_generation_receipt(fence, artifacts.verify(receipt, protect=lambda _: None))
    s.acknowledge_cleanup(fence, CleanupEvidence(
        registration=handle.prepared.registration, evidence_ref="stop", remote_effects="unknown",
        observation="owned_process_group_stopped",
    ))
    s.request_cancel(f.run.run_id, s.get_run(f.run.run_id).version)
    value = s.get_run_cleanup(f.run.run_id).intents[0]
    assert value.cleanup_state == "recorded" and value.release_state == "released"
    query = (
        "MATCH (a:ArenaExecutionAttempt {deployment_id:$deployment_id, workspace_id:$workspace_id, "
        "attempt_id:$id}) "
    )
    with driver.session(database=s.database) as session:
        remove = "REMOVE a.released_at" + (", a.release_authorization_json" if receipt_only else "")
        assert session.run(query + remove + " RETURN count(a) AS n",
                           **s.scope, id=fence.attempt_id).single()["n"] == 1
        before = dict(session.run(query + "RETURN properties(a) AS a", **s.scope,
                                  id=fence.attempt_id).single()["a"])
        assert before["status"] == "cancelled"
        assert ("receipt_json" in before) is receipt_only
        assert ("release_authorization_json" in before) is not receipt_only
        with pytest.raises(CorruptCleanupRecord, match="^Invalid retained cleanup record$"):
            s.get_run_cleanup(f.run.run_id)
        assert dict(session.run(query + "RETURN properties(a) AS a", **s.scope,
                                id=fence.attempt_id).single()["a"]) == before


@pytest.mark.parametrize("driver_fetch_size", [None, 1])
@pytest.mark.parametrize("overflow", [False, True])
def test_cleanup_checks_outer_stream_before_nested_driver_queries(driver, overflow, driver_fetch_size):
    import json
    from pathlib import Path

    import neo4j

    from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptCleanupRecord

    assert neo4j.__version__ == "6.2.0"
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, _, _ = reserved(s)
    with driver.session(database=s.database) as session:
        count = session.run(
            "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run})"
            "-[:HAS_INTENT]->(i {intent_id:$id}) UNWIND range(1,$n) AS n "
            "CREATE (r)-[:HAS_INTENT]->(j:ArenaExecutionIntent) "
            "SET j=properties(i), j.intent_id=$id+'-'+toString(n), j.scene_json=$padding RETURN count(j) AS n",
            **s.scope, run=run.run_id, id=intent, n=160 if overflow else 32,
            padding="x" * 65000 if overflow else None,
        ).single()["n"]
    stats = dict(driver=neo4j.__version__, rows=count + 1, yielded=0, selected_bytes=0,
                 max_buffered=0, nested_while_streaming=[], session_options=[], exhausted=False)
    outer = None

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Result(Proxy):
        def __iter__(self):
            for row in self.real:
                stats["yielded"] += 1
                stats["selected_bytes"] += len(json.dumps(dict(row), allow_nan=False).encode())
                stats["max_buffered"] = max(stats["max_buffered"], len(self.real._record_buffer))
                yield row
            stats["exhausted"] = True

    class Transaction(Proxy):
        def run(self, query, **params):
            nonlocal outer
            streaming = outer is not None and not stats["exhausted"]
            before = len(outer._record_buffer) if streaming else 0
            result = self.real.run(query, **params)
            if streaming:
                stats["nested_while_streaming"].append(dict(before=before, after=len(outer._record_buffer)))
            if "AS ityped" in query:
                import inspect

                stats["transaction_run_source"] = inspect.getsource(type(self.real).run)
                outer = result
                stats["fetch_size"] = result._fetch_size
                return Result(result)
            return result

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            assert kwargs == {"timeout": 5}
            return Transaction(self.real.begin_transaction(**kwargs))

    class Driver(Proxy):
        def session(self, **kwargs):
            stats["session_options"].append(dict(kwargs))
            # Characterize both production defaults and actual tiny batches.
            if driver_fetch_size is not None:
                kwargs.setdefault("fetch_size", driver_fetch_size)
            return Session(self.real.session(**kwargs))

    observed = Neo4jWorkflowStore(Driver(driver), database=s.database, **s.scope)
    from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptRunInspection

    for joined in (False, True):
        # Exercise both readers against the same bounded physical padding cohort;
        # never duplicate large fixture writes just to parameterize a read path.
        outer = None
        stats.update(
            yielded=0, selected_bytes=0, max_buffered=0, nested_while_streaming=[], session_options=[], exhausted=False
        )
        read = observed.get_run_inspection if joined else observed.get_run_cleanup
        try:
            if overflow:
                with pytest.raises(CorruptRunInspection if joined else CorruptCleanupRecord):
                    read(run.run_id)
                assert stats["selected_bytes"] > 8 * 1024 * 1024
                assert stats["yielded"] < stats["rows"]
            else:
                value = read(run.run_id)
                assert len(value.cleanup.intents if joined else value.intents) == stats["rows"]
            assert stats["nested_while_streaming"] == [], stats
            assert stats["max_buffered"] <= 1, stats
            assert stats["session_options"] == [dict(database=s.database, fetch_size=1)]
        finally:
            Path(f"/evidence/cleanup-buffer-{overflow}-{driver_fetch_size}-{joined}.json").write_text(
                json.dumps(stats, sort_keys=True)
            )


def test_cleanup_exact_queries_are_bounded_indexed_and_read_only(driver):
    import json
    from pathlib import Path

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, _, _ = reserved(s)
    s.claim_intent(intent, "owner", s.begin_owner("owner"))
    queries = []

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Transaction(Proxy):
        def run(self, query, **params):
            queries.append((query, params))
            return self.real.run(query, **params)

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Transaction(self.real.begin_transaction(**kwargs))

    class Driver(Proxy):
        def session(self, **kwargs):
            return Session(self.real.session(**kwargs))

    observed = Neo4jWorkflowStore(Driver(driver), database=s.database, **s.scope)
    assert observed.get_run_cleanup(run.run_id).intents[0].cleanup_state == "unknown"
    plans = []

    def operators(node):
        return [node["operatorType"], *(op for child in node.get("children", []) for op in operators(child))]

    with driver.session(database=s.database) as session:
        for query, params in queries:
            assert "properties(" not in query
            if "SET " in query:
                assert "SET c.lock_anchor=true SET c.revision=c.revision+1" in query
                continue
            assert not any(word in query for word in ("CREATE ", "MERGE ", "DELETE ", "CALL "))
            plan = session.run("EXPLAIN " + query, **params).consume().plan
            ops = operators(plan)
            assert any("IndexSeek" in op or "NodeByElementIdSeek" in op for op in ops), ops
            assert not any("LabelScan" in op or "AllNodesScan" in op for op in ops), ops
            if "ArenaRetiredWorkflowOwner" in query:
                assert "toStringOrNull" in query and "65536" in query
            plans.append(dict(query=query, operators=ops, plan=plan))
    assert any("count(i)" in p["query"] for p in plans)
    assert any("LIMIT 1001" in p["query"] for p in plans)
    Path("/evidence/cleanup-plans.json").write_text(json.dumps(plans, sort_keys=True))


@pytest.mark.parametrize(
    "damage",
    [
        "intent_scope",
        "attempt_scope",
        "duplicate_intent",
        "duplicate_attempt",
        "extra_parent",
        "missing_link",
        "wrong_link",
        "duplicate_link",
        "foreign_parent",
        "status",
        "release_time",
        "fence_mirror",
        "registration_mirror",
        "cleanup_mirror",
        "cleanup_binding",
        "fence_binding",
        "retired_epoch",
        "retired_duplicate",
        "current_epoch",
        "missing_owner",
        "owner_dirty",
        "oversize",
        "duplicate_json",
        "malformed",
        "overflow",
        "array",
        "missing_release",
        "unclaimed_status",
        "retired_active",
        "retired_wrong_current_epoch",
    ],
)
def test_run_cleanup_rejects_corruption_without_public_data(driver, damage):
    import traceback
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptCleanupRecord
    from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, _, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    assert s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    evidence = CleanupEvidence(
        registration=reg, evidence_ref="stop", remote_effects="unknown", observation="owned_process_group_stopped"
    )
    s.acknowledge_cleanup(fence, evidence)
    assert s.get_run_cleanup(run.run_id).intents[0].cleanup_state == "recorded"
    prefix = (
        "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run})"
        "-[link:HAS_INTENT]->(i)-[:HAS_ATTEMPT]->(a) "
    )
    queries = {
        "intent_scope": "SET i.workspace_id='foreign'",
        "attempt_scope": "SET a.workspace_id='foreign'",
        "duplicate_intent": "CREATE (copy:ArenaExecutionIntent) SET copy=properties(i)",
        "duplicate_attempt": "CREATE (copy:ArenaExecutionAttempt) SET copy=properties(a)",
        "extra_parent": (
            "CREATE (copy:ArenaExecutionIntent)-[:HAS_ATTEMPT]->(a) SET copy=properties(i), copy.intent_id='other'"
        ),
        "missing_link": "DELETE link",
        "wrong_link": "DELETE link CREATE (r)-[:HAS_SCENE_INTENT]->(i)",
        "duplicate_link": "CREATE (r)-[:HAS_INTENT]->(i)",
        "foreign_parent": "CREATE (x:ArenaWorkflowRun {run_id:'foreign'})-[:HAS_INTENT]->(i)",
        "status": "SET i.status='private-sentinel', a.status='private-sentinel'",
        "release_time": "SET a.released_at='private-sentinel'",
        "fence_mirror": "SET i.fence_json='private-sentinel'",
        "registration_mirror": "REMOVE i.registration_json",
        "cleanup_mirror": "REMOVE i.cleanup_json",
        "cleanup_binding": "SET i.cleanup_json=$bad, a.cleanup_json=$bad",
        "fence_binding": "SET i.fence_json=$bad, a.fence_json=$bad",
        "retired_epoch": "CREATE (o:ArenaRetiredWorkflowOwner) SET o=$owner, o.owner_epoch=2",
        "retired_duplicate": "FOREACH (_ IN [1,2] | CREATE (o:ArenaRetiredWorkflowOwner) SET o=$owner)",
        "current_epoch": (
            "WITH r MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) SET"
            " c.owner_epoch=2"
        ),
        "missing_owner": (
            "WITH r MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) REMOVE"
            " c.owner_id"
        ),
        "owner_dirty": (
            "WITH r MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) SET"
            " c.owner_dirty='true'"
        ),
        "oversize": "SET i.cleanup_json=$bad, a.cleanup_json=$bad",
        "duplicate_json": "SET i.cleanup_json=$bad, a.cleanup_json=$bad",
        "malformed": "SET i.cleanup_json=$bad, a.cleanup_json=$bad",
        "overflow": (
            "WITH r UNWIND range(1,1001) AS n CREATE (r)-[:HAS_INTENT]->(j:ArenaExecutionIntent) SET j=$extra,"
            " j.intent_id=toString(n)"
        ),
        "array": "SET i.cleanup_json=['private-sentinel'], a.cleanup_json=['private-sentinel']",
        "missing_release": "REMOVE a.released_at",
        "unclaimed_status": "SET i.status='reserved', a.status='reserved'",
        "retired_active": "CREATE (o:ArenaRetiredWorkflowOwner) SET o=$owner",
        "retired_wrong_current_epoch": (
            "CREATE (o:ArenaRetiredWorkflowOwner) SET o=$owner WITH r MATCH (c:ArenaWorkflowControl"
            " {deployment_id:$deployment_id, workspace_id:$workspace_id}) SET c.owner_epoch=2, c.owner_dirty=false"
        ),
    }
    bad = "private-sentinel"
    if damage == "cleanup_binding":
        bad = evidence.model_copy(update={"registration": reg.model_copy(update={"pid": 999})}).model_dump_json()
    elif damage == "fence_binding":
        bad = fence.model_copy(update={"owner_epoch": 2}).model_dump_json()
    elif damage == "oversize":
        bad = evidence.model_dump_json() + " " * 65537
    elif damage == "duplicate_json":
        bad = evidence.model_dump_json()[:-1] + ',"evidence_ref":"private-sentinel"}'
    with driver.session(database=s.database) as session:
        session.run(
            prefix + queries[damage],
            **s.scope,
            run=run.run_id,
            bad=bad,
            owner=dict(s.scope, owner_id="owner", owner_epoch=1),
            extra=dict(s.scope, run_id=run.run_id, status="reserved"),
        ).consume()
    screened = []
    service = WorkflowService(s, SimpleNamespace(require_read=lambda p: None), None, validate_support=None)
    with pytest.raises(CorruptCleanupRecord) as caught:
        service.read_run_cleanup("reader", run.run_id, protect=screened.append)
    assert str(caught.value) == "Invalid retained cleanup record"
    assert "private-sentinel" not in "".join(traceback.format_exception(caught.value))
    assert screened == []


def test_model_profile_register_get_list_immutable(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    s = scoped(driver)
    raw = profile_registration()
    profile = ProfileRegistration.model_validate(raw)
    registered = s.register_profile(profile, protect=lambda value: None)
    assert registered.profile_id == profile.profile_id
    assert registered.revision == 2 and registered.schema_version == 1
    assert registered.registration == profile
    assert s.get_profile(profile.profile_id, 2) == registered
    assert s.list_profiles() == (registered,)
    assert s.register_profile(profile, protect=lambda value: None) == registered
    assert scoped(driver).get_profile(profile.profile_id, 2) is None


@pytest.mark.parametrize("operation,index", [
    ("get", "composite"), ("get", "scope"), ("list", "scope"),
    ("replay", "composite"), ("replay", "scope"),
])
def test_profile_physical_float_rejected_independent_of_query_plan(driver, operation, index):
    import json
    from pathlib import Path

    from isaaclab_arena.agentic_environment_generation.workflow.profiles import CorruptProfileRecord, ProfileRegistration
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    s = scoped(driver)
    profile = ProfileRegistration.model_validate(profile_registration())
    s.register_profile(profile, protect=lambda _: None)
    match = "MATCH (p:ArenaWorkflowProfileRevision {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
    with driver.session(database=s.database) as session:
        assert session.run(match + "SET p.revision=$value RETURN count(p) AS n", **s.scope,
                           value=2.0).single()["n"] == 1
        direct = session.run(match + "RETURN properties(p) AS p", **s.scope).single()["p"]
        direct_type = type(direct["revision"]).__name__
        # Numeric-equal SET can be optimized away; force a physical type change
        # independently of the equality predicate used by the production read.
        if type(direct["revision"]) is not float:
            assert session.run(match + "REMOVE p.revision RETURN count(p) AS n", **s.scope).single()["n"] == 1
            assert session.run(match + "SET p.revision=$value RETURN count(p) AS n", **s.scope,
                               value=2.0).single()["n"] == 1
        before = session.run(match + "RETURN properties(p) AS p", **s.scope).single()["p"]
        assert type(before["revision"]) is float and before["revision"] == 2.0
    evidence = dict(operation=operation, index=index, direct_set_type=direct_type,
                    physical_revision_type=type(before["revision"]).__name__, queries=[])

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Transaction(Proxy):
        def run(self, query, **params):
            if query.startswith("MATCH (p:ArenaWorkflowProfileRevision ") and "AS profile" in query:
                fields = "deployment_id, workspace_id" + (", profile_id, revision" if index == "composite" else "")
                hinted = query.replace(") ", ") USING INDEX p:ArenaWorkflowProfileRevision(" + fields + ") ", 1)
                plan = self.real.run("EXPLAIN " + hinted, **params).consume().plan
                nodes = [plan]
                seeks = []
                while nodes:
                    node = nodes.pop()
                    nodes.extend(node.get("children", []))
                    if "IndexSeek" in node["operatorType"]:
                        seeks.append(node)
                    assert "Scan" not in node["operatorType"]
                assert len(seeks) == 1
                assert "ArenaWorkflowProfileRevision(" + fields + ")" in seeks[0]["args"]["Details"]
                assert ("Unique" in seeks[0]["operatorType"]) == (index == "composite")
                rows = self.real.run(hinted, **params).data()
                evidence["queries"].append(dict(production_query=query, hinted_query=hinted, plan=plan,
                                                rows=rows, revision_types=[type(r["profile"]["revision"]).__name__
                                                                          for r in rows]))
                return rows
            return self.real.run(query, **params)

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Transaction(self.real.begin_transaction(**kwargs))

    class Driver(Proxy):
        def session(self, **kwargs):
            assert kwargs == dict(database=s.database)  # Other reads retain driver defaults.
            return Session(self.real.session(**kwargs))

    observed = Neo4jWorkflowStore(Driver(driver), database=s.database, **s.scope)
    read = {"get": lambda: observed.get_profile(profile.profile_id, 2),
            "list": observed.list_profiles,
            "replay": lambda: observed.register_profile(profile, protect=lambda _: None)}[operation]
    try:
        with pytest.raises(CorruptProfileRecord, match="^Invalid retained profile record$"):
            read()
    finally:
        with driver.session(database=s.database) as session:
            after = session.run(match + "RETURN properties(p) AS p", **s.scope).single()["p"]
        evidence["physical_unchanged"] = before == after and type(after["revision"]) is float
        Path(f"/evidence/profile-scalar-{operation}-{index}.json").write_text(json.dumps(evidence, sort_keys=True))
        assert evidence["physical_unchanged"]


def test_model_profile_actual_queries_seek_with_foreign_scopes(driver):
    import json
    from pathlib import Path

    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    s = scoped(driver)
    profile = ProfileRegistration.model_validate(profile_registration())
    retained = s.register_profile(profile, protect=lambda value: None)
    # Valid immutable bodies/anchors, one revision per foreign initialized scope.
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (p:ArenaWorkflowProfileRevision {deployment_id:$deployment_id, workspace_id:$workspace_id}), "
            "(a:ArenaWorkflowProfile {deployment_id:$deployment_id, workspace_id:$workspace_id}), "
            "(c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "UNWIND range(1,256) AS i "
            "CREATE (q:ArenaWorkflowProfileRevision), (b:ArenaWorkflowProfile), (d:ArenaWorkflowControl) "
            "SET q=p {.*, workspace_id:$workspace_id+'-foreign-'+toString(i)}, "
            "b=a {.*, workspace_id:$workspace_id+'-foreign-'+toString(i)}, "
            "d=c {.*, workspace_id:$workspace_id+'-foreign-'+toString(i)}",
            **s.scope,
        ).consume()
    queries = {}

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Transaction(Proxy):
        def run(self, query, **params):
            if query.startswith("MATCH (p:ArenaWorkflowProfileRevision "):
                assert not any(word in query for word in ("SET ", "CREATE ", "MERGE ", "DELETE ", "CALL "))
                kind = "count" if "count(p)" in query else "exact" if params.get("profile_id") else "list"
                queries[kind] = (query, params)
            return self.real.run(query, **params)

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Transaction(self.real.begin_transaction(**kwargs))

    class Driver(Proxy):
        def session(self, **kwargs):
            return Session(self.real.session(**kwargs))

    observed = Neo4jWorkflowStore(Driver(driver), database=s.database, **s.scope)
    assert observed.get_profile(profile.profile_id, profile.revision) == retained
    assert observed.list_profiles() == (retained,)
    observed.register_profile(ProfileRegistration.model_validate(profile_registration() | {"revision": 3}),
                              protect=lambda value: None)
    plans = {}

    def operators(node):
        return [node["operatorType"], *(op for child in node.get("children", []) for op in operators(child))]

    with driver.session(database=s.database) as session:
        for kind, (query, params) in queries.items():
            plan = session.run("EXPLAIN " + query, **params).consume().plan
            plans[kind] = dict(query=query, parameters=params, operators=operators(plan), plan=plan)
        indexes = session.run("SHOW INDEXES YIELD entityType, type, state, labelsOrTypes, properties, "
                              "owningConstraint RETURN *").data()
    Path("/evidence/profile-plans.json").write_text(json.dumps(dict(plans=plans, indexes=indexes), sort_keys=True))
    assert set(plans) == {"exact", "list", "count"}
    assert all(any("IndexSeek" in op for op in value["operators"]) for value in plans.values()), plans
    assert all(not any("Scan" in op for op in value["operators"]) for value in plans.values()), plans
    assert any(row == dict(entityType="NODE", type="RANGE", state="ONLINE", owningConstraint=None,
                           labelsOrTypes=["ArenaWorkflowProfileRevision"],
                           properties=["deployment_id", "workspace_id"]) for row in indexes)
    assert "p.profile_id=$profile_id AND p.revision=$revision" in queries["exact"][0]
    assert all("IS NULL" not in query for query, _ in queries.values())
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import SchemaMissing

    with driver.session(database=s.database) as session:
        session.run("DROP INDEX arena_workflow_profile_revision_scope").consume()
        try:
            with pytest.raises(SchemaMissing):
                s.verify_schema()
            with pytest.raises(SchemaMissing):
                s.initialize_scope()
            assert not session.run("SHOW INDEXES YIELD name WHERE name='arena_workflow_profile_revision_scope' "
                                   "RETURN name").data()
        finally:
            for ddl in s.schema_requirements():
                session.run(ddl).consume()
            session.run("CALL db.awaitIndexes(30)").consume()
    assert s.verify_schema()


@pytest.mark.parametrize("damage", ["literal", "nested", "json"])
@pytest.mark.parametrize("operation", ["read", "list"])
def test_model_profile_retained_validation_error_is_static(driver, damage, operation):
    import json
    import traceback
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    s = scoped(driver)
    profile = ProfileRegistration.model_validate(profile_registration())
    s.register_profile(profile, protect=lambda value: None)
    query = ("MATCH (p:ArenaWorkflowProfileRevision {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
             "RETURN properties(p) AS p")
    with driver.session(database=s.database) as session:
        row = session.run(query, **s.scope).single()["p"]
        value = json.loads(row["body_json"])
        if damage == "literal":
            value["registration"]["kind"] = "private-sentinel"
        else:
            value["registration"]["settings"]["inference_policy"] = {"private-sentinel": ["private-sentinel"]}
        body = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if damage == "json":
            body = '{"private-sentinel":'
        session.run("MATCH (p:ArenaWorkflowProfileRevision {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                    "SET p.body_json=$body", body=body, **s.scope).consume()
        damaged = session.run(query, **s.scope).single()["p"]
    screens, reads = [], []
    service = WorkflowService(s, SimpleNamespace(require_read=reads.append), None, validate_support=None)
    with pytest.raises(ValueError) as caught:
        if operation == "read":
            service.read_profile("reader", profile.profile_id, profile.revision, protect=screens.append)
        else:
            service.list_profiles("reader", protect=screens.append)
    assert reads == ["reader"] and screens == []
    with driver.session(database=s.database) as session:
        assert session.run(query, **s.scope).single()["p"] == damaged
    assert "private-sentinel" not in str(caught.value)
    assert "private-sentinel" not in "".join(traceback.format_exception(caught.value))
    assert type(caught.value).__name__ == "CorruptProfileRecord"
    assert str(caught.value) == "Invalid retained profile record"
    assert caught.value.__suppress_context__ is True and caught.value.__cause__ is None


def test_model_profile_scope_constraints_anchor_and_capacity(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    s = scoped(driver)
    with driver.session(database=s.database) as session:
        constraints = session.run("SHOW CONSTRAINTS YIELD labelsOrTypes, properties RETURN *").data()
    assert any(r["labelsOrTypes"] == ["ArenaWorkflowProfile"] and
               r["properties"] == ["deployment_id", "workspace_id", "profile_id"] for r in constraints)
    assert any(r["labelsOrTypes"] == ["ArenaWorkflowProfileRevision"] and
               r["properties"] == ["deployment_id", "workspace_id", "profile_id", "revision"] for r in constraints)
    values = []
    for revision in range(1, 65):
        profile = ProfileRegistration.model_validate(profile_registration() | {"revision": revision})
        values.append(s.register_profile(profile, protect=lambda value: None))
    assert s.list_profiles() == tuple(values)
    assert s.register_profile(values[0].registration, protect=lambda value: None) == values[0]
    with pytest.raises(CapacityExceeded):
        s.register_profile(ProfileRegistration.model_validate(profile_registration() | {"revision": 65}),
                           protect=lambda value: None)
    changed = profile_registration() | {"revision": 1, "roles": ["generation_model"]}
    with pytest.raises(SubmissionConflict):
        s.register_profile(ProfileRegistration.model_validate(changed), protect=lambda value: None)
    with driver.session(database=s.database) as session:
        anchors = session.run("MATCH (p:ArenaWorkflowProfile {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                              "RETURN p.profile_id AS id, p.kind AS kind", **s.scope).data()
        assert anchors == [{"id": "public-model", "kind": "model"}]
        session.run("MATCH (p:ArenaWorkflowProfile {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                    "SET p.kind='runtime'", **s.scope).consume()
    with pytest.raises(ValueError):
        s.get_profile("public-model", 1)
    with pytest.raises(ValueError):
        s.register_profile(values[0].registration, protect=lambda value: None)


def test_model_profile_new_registration_checks_current_catalogue(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    s = scoped(driver)
    raw = profile_registration()
    raw["settings"]["inference_policy"]["documentation_urls"] = ["https://example.invalid/not-builtin"]
    with pytest.raises(ValueError):
        s.register_profile(ProfileRegistration.model_validate(raw), protect=lambda value: None)
    assert s.list_profiles() == ()


def test_model_profile_history_and_replay_ignore_changed_catalogue(driver, monkeypatch):
    from isaaclab_arena.agentic_environment_generation import inference_profiles
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    s = scoped(driver)
    original = ProfileRegistration.model_validate(profile_registration())
    registered = s.register_profile(original, protect=lambda value: None)
    monkeypatch.setattr(inference_profiles, "inference_profile_catalogue", lambda: [])
    monkeypatch.setitem(inference_profiles.FIXED_ENDPOINTS, "openai", "https://changed.invalid")
    assert s.get_profile(original.profile_id, original.revision) == registered
    assert s.list_profiles() == (registered,)
    assert s.register_profile(original, protect=lambda value: None) == registered
    new = ProfileRegistration.model_validate(profile_registration() | {"revision": 3})
    with pytest.raises(ValueError):
        s.register_profile(new, protect=lambda value: None)
    assert s.list_profiles() == (registered,)


@pytest.mark.parametrize("damage", ["body_hash", "settings_hash", "body", "noncanonical", "codec",
                                    "missing_codec", "scalar_codec_bool", "scalar_revision_float", "kind", "oversize"])
def test_model_profile_corrupt_readback_is_rejected(driver, damage):
    import json

    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    s = scoped(driver)
    profile = ProfileRegistration.model_validate(profile_registration())
    s.register_profile(profile, protect=lambda value: None)
    with driver.session(database=s.database) as session:
        row = session.run("MATCH (p:ArenaWorkflowProfileRevision {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                          "RETURN properties(p) AS p", **s.scope).single()["p"]
        changes = {}
        if damage == "body_hash":
            changes["body_sha256"] = "a" * 64
        elif damage == "settings_hash":
            changes["settings_sha256"] = "a" * 64
        elif damage == "body":
            changes["body_json"] = "{}"
        elif damage == "noncanonical":
            changes["body_json"] = row["body_json"] + " "
        elif damage == "oversize":
            changes["body_json"] = " " * 16385
        elif damage in ("codec", "missing_codec"):
            value = json.loads(row["body_json"])
            value["schema_version"] = 2
            if damage == "missing_codec":
                value.pop("schema_version")
            changes["body_json"] = json.dumps(value, sort_keys=True, separators=(",", ":"))
        elif damage == "scalar_codec_bool":
            changes["schema_version"] = True
        elif damage == "scalar_revision_float":
            changes["revision"] = 2.0
        else:
            changes["kind"] = "runtime"
        session.run("MATCH (p:ArenaWorkflowProfileRevision {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                    "SET p += $changes", **s.scope, changes=changes).consume()
    with pytest.raises(ValueError):
        s.get_profile(profile.profile_id, profile.revision)
    with pytest.raises(ValueError):
        s.list_profiles()
    with pytest.raises(ValueError):
        s.register_profile(profile, protect=lambda value: None)


def test_model_profile_missing_scope_and_schema_never_initialize(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import SchemaMissing, ScopeMissing
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    s = Neo4jWorkflowStore(driver, database=os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"],
                          deployment_id="missing", workspace_id=uuid.uuid4().hex)
    with pytest.raises(ScopeMissing):
        s.get_profile("public-model", 2)
    with pytest.raises(ScopeMissing):
        s.list_profiles()
    with pytest.raises(ScopeMissing):
        s.register_profile(ProfileRegistration.model_validate(profile_registration()), protect=lambda value: None)
    with driver.session(database=s.database) as session:
        assert session.run("MATCH (n {deployment_id:$deployment_id, workspace_id:$workspace_id}) RETURN count(n) AS n",
                           **s.scope).single()["n"] == 0
        session.run("DROP CONSTRAINT arena_workflow_profile_revision").consume()
        try:
            with pytest.raises(SchemaMissing):
                s.verify_schema()
            with pytest.raises(SchemaMissing):
                s.initialize_scope()
        finally:
            for ddl in s.schema_requirements():
                session.run(ddl).consume()
            session.run("CALL db.awaitIndexes(30)").consume()


@pytest.mark.parametrize("case", ["same", "conflict", "capacity"])
def test_model_profile_real_races_are_atomic_without_retry(driver, case):
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    s = scoped(driver)
    original = ProfileRegistration.model_validate(profile_registration())
    # Prime an already-true lock anchor, not just first-write contention.
    s.register_profile(original, protect=lambda value: None)
    if case == "capacity":
        for revision in range(3, 65):
            s.register_profile(ProfileRegistration.model_validate(profile_registration() | {"revision": revision}),
                               protect=lambda value: None)
    barrier = Barrier(4)

    def register(i):
        raw = profile_registration() | {"revision": 100 + i if case == "capacity" else 100}
        if case == "conflict":
            raw["roles"] = ["generation_model"] if i % 2 else ["assessment_model"]
        profile = ProfileRegistration.model_validate(raw)
        barrier.wait(timeout=10)
        try:
            return s.register_profile(profile, protect=lambda value: None)
        except (SubmissionConflict, CapacityExceeded) as exc:
            return type(exc).__name__

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(register, range(4)))
    rows = s.list_profiles()
    if case == "same":
        assert len(rows) == 2 and all(r == rows[-1] for r in results)
    elif case == "conflict":
        assert len(rows) == 2 and results.count("SubmissionConflict") == 2
        assert all(r == "SubmissionConflict" or r == rows[-1] for r in results)
    else:
        assert len(rows) == 64 and results.count("CapacityExceeded") == 3
    with driver.session(database=s.database) as session:
        assert session.run("MATCH (p:ArenaWorkflowProfile {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                           "RETURN count(p) AS n", **s.scope).single()["n"] == 1


@pytest.mark.parametrize("operation", ["register", "get", "list", "cleanup"])
@pytest.mark.parametrize("failure", ["before_commit", "after_commit", "tx_close", "session_close"])
def test_model_profile_real_unknown_commit_and_cleanup(driver, operation, failure):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    s = scoped(driver)
    profile = ProfileRegistration.model_validate(profile_registration())
    if operation != "register":
        s.register_profile(profile, protect=lambda value: None)
    if operation == "cleanup":
        run = s.admit("cleanup-fault", "{}", "{}", 1)
        cleanup_before = s.get_run_cleanup(run.run_id)
    calls = []

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Transaction(Proxy):
        def commit(self):
            calls.append("commit")
            if failure == "before_commit":
                raise OSError("synthetic precommit failure")
            self.real.commit()
            if failure == "after_commit":
                raise OSError("synthetic committed acknowledgement loss")

        def close(self):
            calls.append("tx_close")
            self.real.close()
            if failure == "tx_close":
                raise OSError("synthetic close acknowledgement loss")

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Transaction(self.real.begin_transaction(**kwargs))

        def close(self):
            calls.append("session_close")
            self.real.close()
            if failure == "session_close":
                raise OSError("synthetic session acknowledgement loss")

    class Driver(Proxy):
        def session(self, **kwargs):
            calls.append("session")
            return Session(self.real.session(**kwargs))

    failing = Neo4jWorkflowStore(Driver(driver), database=s.database, **s.scope)
    with pytest.raises(OutcomeUnknown):
        if operation == "register":
            failing.register_profile(profile, protect=lambda value: None)
        elif operation == "get":
            failing.get_profile(profile.profile_id, profile.revision)
        elif operation == "cleanup":
            failing.get_run_cleanup(run.run_id)
        else:
            failing.list_profiles()
    assert calls == ["session", "commit", "tx_close", "session_close"]
    # Fresh genuine transport, not the fault injector, observes exact persistence.
    with GraphDatabase.driver(os.environ["ARENA_WORKFLOW_NEO4J_URI"], auth=None,
                              max_transaction_retry_time=0) as fresh:
        reader = Neo4jWorkflowStore(fresh, database=s.database, **s.scope)
        values = reader.list_profiles()
        if operation == "cleanup":
            assert reader.get_run_cleanup(run.run_id) == cleanup_before
        if operation == "register" and failure == "before_commit":
            assert values == ()
            with fresh.session(database=s.database) as session:
                assert session.run("MATCH (p:ArenaWorkflowProfile {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                                   "RETURN count(p) AS n", **s.scope).single()["n"] == 0
        else:
            assert len(values) == 1 and values[0].registration == profile
            assert reader.register_profile(profile, protect=lambda value: None) == values[0]


def test_model_profile_admin_service_reads_are_effect_free_and_sqlite_denied(driver, monkeypatch):
    from types import SimpleNamespace
    import builtins

    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowProfileAdmin, WorkflowService
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    original_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert name.split(".")[0] not in ("sqlite3", "openai", "anthropic", "fastapi", "strawberry")
        assert "workbench.journal" not in name and "web_api" not in name
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    s = scoped(driver)
    calls = []
    authority = SimpleNamespace(require_admin=lambda p: calls.append(("admin", p)),
                                require_read=lambda p: calls.append(("read", p)))
    admin = WorkflowProfileAdmin(s, authority)
    # Explicit user-defined admission retains unverified rather than inventing readiness.
    raw = profile_registration()
    raw["settings"]["inference_policy"].update(id="operator-model", origin="user_defined",
                                             support="unverified", documentation_urls=[])
    registration = ProfileRegistration.model_validate(raw)
    result = admin.register_profile("operator", registration, protect=lambda v: None)
    assert result.registration.settings.inference_policy.support == "unverified"

    def graph():
        with driver.session(database=s.database) as session:
            return session.run("MATCH (n {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                               "RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS properties ORDER BY id",
                               **s.scope).data()

    before = graph()
    queries = []

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Transaction(Proxy):
        def run(self, query, **params):
            queries.append(query)
            assert query.startswith("MATCH ")
            assert not any(word in query for word in ("SET ", "CREATE ", "MERGE ", "DELETE ", "CALL "))
            return self.real.run(query, **params)

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Transaction(self.real.begin_transaction(**kwargs))

    class Driver(Proxy):
        def session(self, **kwargs):
            return Session(self.real.session(**kwargs))

    reader = Neo4jWorkflowStore(Driver(driver), database=s.database, **s.scope)
    service = WorkflowService(reader, authority, None, validate_support=None)
    screens = []
    assert service.read_profile("reader", result.profile_id, result.revision, protect=screens.append) == result
    assert service.list_profiles("reader", protect=screens.append) == (result,)
    assert service.read_profile("reader", "absent", 1, protect=screens.append) is None
    assert len(screens) == 3 and screens[-1] is None
    assert calls == [("admin", "operator"), ("read", "reader"), ("read", "reader"), ("read", "reader")]
    assert queries and graph() == before


def test_model_profile_duplicate_revision_corruption_never_lists_ambiguity(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    s = scoped(driver)
    profile = ProfileRegistration.model_validate(profile_registration())
    s.register_profile(profile, protect=lambda value: None)
    with driver.session(database=s.database) as session:
        session.run("DROP CONSTRAINT arena_workflow_profile_revision").consume()
        duplicate = session.run(
            "MATCH (p:ArenaWorkflowProfileRevision {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "CREATE (q:ArenaWorkflowProfileRevision) SET q=properties(p) RETURN elementId(q) AS id", **s.scope,
        ).single()["id"]
        try:
            with pytest.raises(ValueError):
                s.list_profiles()
            with pytest.raises(ValueError):
                s.get_profile(profile.profile_id, profile.revision)
        finally:
            session.run("MATCH (q) WHERE elementId(q)=$id DELETE q", id=duplicate).consume()
            for ddl in s.schema_requirements():
                session.run(ddl).consume()
            session.run("CALL db.awaitIndexes(30)").consume()


def test_model_profile_int64_revision_and_deployment_namespace(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    s = scoped(driver)
    profile = ProfileRegistration.model_validate(profile_registration() | {"revision": 2**63 - 1})
    result = s.register_profile(profile, protect=lambda value: None)
    assert s.get_profile(profile.profile_id, 2**63 - 1) == result
    foreign = scoped(driver, workspace=s.scope["workspace_id"], deployment="other-deployment")
    assert foreign.get_profile(profile.profile_id, profile.revision) is None
    assert foreign.list_profiles() == ()
    assert foreign.register_profile(profile, protect=lambda value: None) == result


def test_historical_point_queries_use_explicit_admin_indexes(driver):
    import json
    from pathlib import Path

    # Execute EXPLAIN on the exact production point-query strings, including
    # evidence selection; run identity already has a scoped unique index.
    s = scoped(driver)
    plans = []
    with driver.session(database=s.database) as session:
        session.run("CALL db.awaitIndexes(30)").consume()  # Explicit quiescent admin only.

        class Explain:
            def run(self, query, **params):
                plan = session.run("EXPLAIN " + query, **params).consume().plan

                def operators(node):
                    return [node["operatorType"], *(op for c in node.get("children", []) for op in operators(c))]

                plans.append(dict(query=query, operators=operators(plan), plan=plan))
                return []

        for label in (
            "ArenaWorkflowCandidate", "ArenaWorkflowEvidence", "ArenaCriterionAssessment",
            "ArenaWorkflowDecision", "ArenaExecutionIntent", "ArenaWorkflowRun",
        ):
            assert s._historical_node(Explain(), label, "a" * 64) is None
        assert s._historical_selection(Explain(), "a" * 64, "run", "b" * 64) is None
    Path("/evidence/history-plans.json").write_text(json.dumps(plans, sort_keys=True))
    assert len(plans) == 7
    assert all(any("IndexSeek" in op for op in p["operators"]) for p in plans), plans
    assert all(not any("LabelScan" in op or "AllNodesScan" in op for op in p["operators"]) for p in plans)
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import SchemaMissing

    with driver.session(database=s.database) as session:
        indexes = session.run(
            "SHOW INDEXES YIELD name, type, state, labelsOrTypes, properties, owningConstraint "
            "WHERE name STARTS WITH 'arena_workflow_history_' RETURN *"
        ).data()
        assert len(indexes) == 9
        assert all(i["state"] == "ONLINE" and i["type"] == "RANGE" and i["owningConstraint"] is None for i in indexes)
        Path("/evidence/history-indexes.json").write_text(json.dumps(indexes, sort_keys=True))
        session.run("DROP INDEX arena_workflow_history_candidate").consume()
        try:
            with pytest.raises(SchemaMissing):
                s.verify_schema()
            # A read neither provisions schema nor initializes a scope.
            assert s.get_scene_candidate("f" * 64) is None
            assert session.run(
                "SHOW INDEXES YIELD name WHERE name='arena_workflow_history_candidate' RETURN name"
            ).data() == []
        finally:
            for ddl in s.schema_requirements():
                session.run(ddl).consume()
            session.run("CALL db.awaitIndexes(30)").consume()
    assert s.verify_schema()


def test_result_read_model_conservative_pending_budget(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.read_model import (
        workflow_result,
    )
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import scene_contract

    store = scoped(driver)
    contract = scene_contract()
    run = store.admit("read-model", canonical_json(contract), canonical_json(contract), 1)
    result = workflow_result(store, run.run_id, protect=lambda value: None)
    assert result["schema_version"] == 1
    assert result["budget"]["reserved"]["model_calls"] == 0
    assert result["budget"]["remaining"]["model_calls"] == contract.budget.max_model_calls
    assert result["budget"]["actual_consumption"] == "unknown"
    assert result["publication"] == "not_requested"
    assert result["experiment"] == "not_requested"
    assert [c["criterion_id"] for c in result["criteria"]] == [c.criterion_id for c in contract.criteria]
    assert all(c["verdict"] == "not_run" for c in result["criteria"])
    assert result["evidence"] == []
    assert result["recovery"] == "known_unreleased"
    assert result["available_actions"] == ["cancel", "resume"]
    assert store.get_run(run.run_id) == run


def test_admit_readback_replay_conflict_capacity_scope_events(driver):
    s = scoped(driver)
    assert s.lookup_submission("op", "{}") is None
    accepted = s.admit("op", "{}", '{"resolved":1}', 1)
    assert (
        accepted.version == 1
        and accepted.state == "pending"
        and accepted.phase == "dependency_readiness"
        and accepted.event_cursor == 1
    )
    assert s.get_run(accepted.run_id) == accepted
    assert s.lookup_submission("op", "{}") == accepted
    assert s.admit("op", "{}", '{"resolved":2}', 0) == accepted
    with pytest.raises(SubmissionConflict):
        s.admit("op", '{"different":true}', "{}", 1)
    with pytest.raises(CapacityExceeded):
        s.admit("other", "{}", "{}", 1)
    snapshot = s.snapshot()
    assert snapshot.runs == (accepted,) and snapshot.cursor == 1
    page = s.events_after(0, 1)
    assert page.cursor == page.ceiling == 1 and page.floor == 0
    assert len(page.events) == 1 and page.events[0].run_id == accepted.run_id
    assert hasattr(page.events[0], "source_id"), "missing stored source must read as explicit None"
    assert page.events[0].source_id is None
    assert page.events[0].schema_version == 1
    assert s.events_after(1).events == ()
    with pytest.raises(ReplayGap):
        s.events_after(2)
    other = scoped(driver)
    assert other.get_run(accepted.run_id) is None
    assert other.admit("op", "{}", "{}", 1).run_id != accepted.run_id
    s.initialize_scope()
    assert s.snapshot() == snapshot


def race(s, operations, capacity):
    barrier = Barrier(len(operations))

    def submit(operation):
        barrier.wait(timeout=10)
        try:
            return s.admit(operation, "{}", "{}", capacity)
        except CapacityExceeded:
            return None

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        return list(pool.map(submit, operations))


def test_control_only_race(driver):
    s = scoped(driver)
    barrier = Barrier(6)

    def read(_):
        barrier.wait(timeout=10)
        return s.snapshot()

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert len(list(pool.map(read, range(6)))) == 6


def prime_lock(s):
    assert s.snapshot().cursor == 0
    with s.driver.session(database=s.database) as session:
        row = session.run(
            "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "RETURN c.lock_anchor AS anchor, c.sequence AS sequence",
            **s.scope,
        ).single(strict=True)
        assert row["anchor"] is True and row["sequence"] == 0


def assert_readback(s, expected):
    snapshot = s.snapshot()
    assert snapshot.runs == tuple(sorted(expected, key=lambda run: run.run_id))
    assert snapshot.cursor == len(expected) and snapshot.floor == 0
    page = s.events_after(0)
    assert page.cursor == page.ceiling == len(expected) and page.floor == 0
    assert [event.sequence for event in page.events] == list(range(1, len(expected) + 1))
    assert {(event.run_id, event.operation_id) for event in page.events} == {
        (run.run_id, run.operation_id) for run in expected
    }
    for run in expected:
        assert s.get_run(run.run_id) == s.lookup_submission(run.operation_id, run.request_json) == run


@pytest.mark.parametrize("round_index", range(3))
def test_duplicate_key_race_is_one_acceptance_and_one_event(driver, round_index):
    s = scoped(driver)
    prime_lock(s)
    results = race(s, ["same"] * 6, 1)
    assert all(result == results[0] and result is not None for result in results)
    assert len(s.snapshot().runs) == 1
    assert s.snapshot().cursor == 1
    assert len(s.events_after(0).events) == 1
    assert results[0].request_json == results[0].contract_json == "{}"
    assert_readback(s, [results[0]])


@pytest.mark.parametrize("round_index", range(3))
def test_distinct_keys_race_cannot_exceed_scoped_capacity(driver, round_index):
    s = scoped(driver)
    prime_lock(s)
    results = race(s, [str(i) for i in range(6)], 2)
    assert sum(result is not None for result in results) == 2
    snapshot = s.snapshot()
    assert len(snapshot.runs) == snapshot.cursor == 2
    first = s.events_after(0, 1)
    second = s.events_after(first.cursor, 1)
    assert [first.events[0].sequence, second.events[0].sequence] == [1, 2]
    accepted = [result for result in results if result is not None]
    assert all(run.request_json == run.contract_json == "{}" for run in accepted)
    assert_readback(s, accepted)
    for operation, result in zip(map(str, range(6)), results):
        assert s.lookup_submission(operation, "{}") == result


@pytest.mark.parametrize("different_requests", [True, False])
def test_same_key_competing_requests_or_contracts(driver, different_requests):
    s = scoped(driver)
    prime_lock(s)
    barrier = Barrier(6)
    requests = ['{"request":%d}' % (i if different_requests else 0) for i in range(6)]
    contracts = ['{"contract":%d}' % i for i in range(6)]

    def submit(i):
        barrier.wait(timeout=10)
        try:
            return s.admit("same", requests[i], contracts[i], 1)
        except SubmissionConflict as exc:
            return exc

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(submit, range(6)))
    accepted = [result for result in results if not isinstance(result, SubmissionConflict)]
    winner = accepted[0]
    assert len(accepted) == (1 if different_requests else 6)
    assert all(result == winner for result in accepted)
    winner_index = contracts.index(winner.contract_json)
    assert winner.request_json == requests[winner_index]
    if different_requests:
        assert results[winner_index] == winner
        assert sum(isinstance(result, SubmissionConflict) for result in results) == 5
    assert_readback(s, [winner])


def test_mixed_snapshots_and_admissions_have_exact_scoped_prefix(driver):
    s = scoped(driver)
    foreign = scoped(driver)
    foreign_runs = [foreign.admit(str(i), "{}", "{}", 3) for i in range(3)]
    prime_lock(s)
    barrier = Barrier(6)

    def work(i):
        barrier.wait(timeout=10)
        if i < 3:
            return s.admit(str(i), '{"member":%d}' % i, "{}", 3), []
        return None, [s.snapshot() for _ in range(3)]

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(work, range(6)))
    accepted = [run for run, _ in results if run is not None]
    assert len(accepted) == 3
    snapshots = [snapshot for _, batch in results for snapshot in batch]
    assert len(snapshots) == 9
    for snapshot in snapshots:
        assert len(snapshot.runs) == snapshot.cursor and snapshot.floor == 0
        assert snapshot.runs == tuple(
            sorted(
                (run for run in accepted if run.event_cursor <= snapshot.cursor),
                key=lambda run: run.run_id,
            )
        )
        assert not {run.run_id for run in snapshot.runs} & {run.run_id for run in foreign_runs}
    assert_readback(s, accepted)
    assert_readback(foreign, foreign_runs)


def test_post_create_result_failure_rolls_back_real_transaction(driver):
    s = scoped(driver)
    prime_lock(s)
    injected = []

    class ResultFailure(RuntimeError):
        pass

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Transaction(Proxy):
        def run(self, query, **parameters):
            result = self.real.run(query, **parameters)
            if "CREATE (e:ArenaWorkflowEvent" not in query:
                return result
            rows = list(result)
            assert result.consume().counters.nodes_created == 2
            assert len(rows) == 1 and rows[0]["run"]["event_cursor"] == 1
            evidence = self.real.run(
                "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "MATCH (e:ArenaWorkflowEvent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "RETURN c.sequence AS cursor, r.run_id AS run, e.run_id AS event",
                **s.scope,
            ).single(strict=True)
            assert evidence["cursor"] == 1 and evidence["run"] == evidence["event"] == rows[0]["run"]["run_id"]

            def failing_result():
                injected.append(dict(evidence))
                raise ResultFailure("after real create result, before commit")
                yield  # Deliberately fail while the store consumes the query result.

            return failing_result()

        def commit(self):
            pytest.fail("injected result failure must never reach commit")

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Transaction(self.real.begin_transaction(**kwargs))

    class Driver(Proxy):
        def session(self, **kwargs):
            return Session(self.real.session(**kwargs))

    failing = Neo4jWorkflowStore(Driver(driver), database=s.database, **s.scope)
    with pytest.raises(ResultFailure, match="after real create result"):
        failing.admit("rollback", "{}", '{"retained":true}', 1)
    assert len(injected) == 1
    with GraphDatabase.driver(
        os.environ["ARENA_WORKFLOW_NEO4J_URI"],
        auth=None,
        max_transaction_retry_time=0,
        connection_timeout=3,
        connection_acquisition_timeout=5,
    ) as independent_driver:
        independent = Neo4jWorkflowStore(independent_driver, database=s.database, **s.scope)
        assert_readback(independent, [])
        assert independent.get_run(injected[0]["run"]) is None
        assert independent.lookup_submission("rollback", "{}") is None
        accepted = independent.admit("rollback", "{}", '{"retained":true}', 1)
        assert accepted.event_cursor == 1
        assert_readback(independent, [accepted])


def test_owner_epoch_is_stable_and_dirty_owner_cannot_be_replaced(driver):
    s = scoped(driver)
    assert hasattr(s, "begin_owner"), "durable owner protocol missing"
    assert s.begin_owner("owner-a") == 1
    assert s.begin_owner("owner-a") == 1
    with pytest.raises(ValueError):
        s.begin_owner("owner-b")
    replacement = Neo4jWorkflowStore(driver, database=s.database, **s.scope)
    assert replacement.begin_owner("owner-a") == 1


def test_owner_handover_requires_retirement_record_not_only_clean_flag(driver):
    s = scoped(driver)
    assert s.begin_owner("owner-a") == 1
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "SET c.owner_dirty=false",
            **s.scope,
        ).consume()
    before = s.get_owner()
    with pytest.raises(ValueError, match="retirement"):
        s.begin_owner("owner-b")
    assert s.get_owner() == before


def reserved(s):
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        GenerationReservation,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )
    from isaaclab_arena.tests.test_environment_workflow_decisions import (
        authority,
        generation_contract,
    )

    contract = generation_contract()
    auth = authority(s, contract)
    reservation = GenerationReservation(
        model_calls=1,
        model_tokens=100,
        cost_ceiling_usd=1.0,
        runtime_allowance_seconds=5.0,
    )
    run = s.admit("generate", "{}", canonical_json(contract), 1)
    intent = s.reserve_generation(
        run.run_id,
        1,
        "decision-1",
        auth,
        reservation,
        readiness=readiness(contract, auth),
    )
    return run, intent, auth, reservation, contract


def test_reserve_exact_replay_and_transition_guards(driver):
    s = scoped(driver)
    assert hasattr(s, "reserve_generation"), "reservation transaction missing"
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    s.clock = lambda: 300.0
    assert s.reserve_generation(run.run_id, 1, "decision-1", auth, reservation, readiness=None) == intent
    assert s.get_run(run.run_id).version == 2
    assert s.get_run(run.run_id).phase == "generation"
    assert [e.kind for e in s.events_after(0).events] == [
        "WorkflowRequested",
        "GenerationReserved",
    ]
    with pytest.raises(ValueError):
        s.reserve_generation(run.run_id, 1, "different", auth, reservation, readiness=None)
    with pytest.raises(ValueError):
        s.reserve_generation(run.run_id, 2, "second", auth, reservation, readiness=None)


def test_event_sources_survive_later_transitions_paging_scope_and_replay(driver):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, reservation, _ = reserved(s)
    interleaved = s.admit("interleaved", "{}", "{}", 1)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    for foreign in (
        scoped(driver),
        scoped(driver, workspace=s.scope["workspace_id"], deployment="foreign-deployment"),
    ):
        foreign.clock = lambda: 100.0
        reserved(foreign)

    reader = Neo4jWorkflowStore(driver, database=s.database, **s.scope)
    before = reader.snapshot()
    expected = [
        (run.run_id, "generate", "WorkflowRequested", None),
        (run.run_id, "generate", "GenerationReserved", "decision-1"),
        (interleaved.run_id, "interleaved", "WorkflowRequested", None),
        (run.run_id, "generate", "IntentClaimed", fence.attempt_id),
        (run.run_id, "generate", "WorkerRegistered", reg.registration_id),
    ]
    events = []
    cursor = 0
    for _ in expected:
        page = reader.events_after(cursor, 1)
        assert len(page.events) == 1
        assert page.floor == 0 and page.ceiling == len(expected)
        assert page.cursor == cursor + 1
        events.extend(page.events)
        cursor = page.cursor
    assert all(hasattr(event, "source_id") for event in events), "stored historical sources must be returned"
    assert [(e.run_id, e.operation_id, e.kind, e.source_id) for e in events] == expected
    assert all(e.schema_version == 1 for e in events)
    assert reader.events_after(0).events == tuple(events)
    assert reader.events_after(cursor).events == ()
    with pytest.raises(ReplayGap):
        reader.events_after(cursor + 1)
    assert s.admit("generate", "{}", "{}", 0) == reader.get_run(run.run_id)
    assert s.reserve_generation(run.run_id, 1, "decision-1", auth, reservation, readiness=None) == intent
    assert s.claim_intent(intent, "owner", fence.owner_epoch) == fence
    assert s.register_worker(fence, reg) == reg
    assert reader.snapshot() == before
    assert reader.events_after(0).events == tuple(events)


def test_exact_generation_recovery_lookup_is_bounded_and_scoped(driver):
    s = scoped(driver)
    s.clock = lambda: 100.0
    assert s.get_generation_attempt("unknown") is None
    run, intent, _, _, _ = reserved(s)
    assert s.get_generation_attempt(run.run_id) is None
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    assert s.get_generation_attempt(run.run_id) == s.get_attempt(fence)
    assert scoped(driver).get_generation_attempt(run.run_id) is None
    with pytest.raises(ValueError):
        s.get_attempt(fence.model_copy(update={"owner_epoch": 2}))
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (i:ArenaExecutionIntent {intent_id:$id})-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
            "CREATE (i)-[:HAS_ATTEMPT]->(duplicate:ArenaExecutionAttempt) SET duplicate=properties(a)",
            id=intent,
        ).consume()
    with pytest.raises(ValueError, match="ambiguous"):
        s.get_generation_attempt(run.run_id)


@pytest.mark.parametrize("damage", ["missing_fence", "duplicate_intent", "foreign_attempt", "detached_run"])
def test_recovery_rejects_inexact_retained_paths(driver, damage):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, _, _ = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    suffix = {
        "missing_fence": "REMOVE a.fence_json",
        "duplicate_intent": (
            "CREATE (r)-[:HAS_INTENT]->(other:ArenaExecutionIntent) SET other=properties(i) "
            "CREATE (other)-[:HAS_ATTEMPT]->(a)"
        ),
        "foreign_attempt": "SET a.workspace_id='foreign'",
        "detached_run": "DELETE link",
    }[damage]
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (r:ArenaWorkflowRun)-[link:HAS_INTENT]->(i:ArenaExecutionIntent)"
            "-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) WHERE i.intent_id=$id " + suffix,
            id=intent,
        ).consume()
    if damage == "detached_run":
        assert s.get_generation_attempt(run.run_id) is None
    else:
        with pytest.raises(ValueError):
            s.get_generation_attempt(run.run_id)
    with pytest.raises(ValueError):
        s.get_attempt(fence)


def test_claim_is_stable_and_owner_fenced(driver):
    s = scoped(driver)
    assert hasattr(s, "claim_intent"), "claim missing"
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    epoch = s.begin_owner("owner")
    with pytest.raises(ValueError):
        s.claim_intent(intent, "other", epoch)
    with pytest.raises(ValueError):
        s.claim_intent(intent, "owner", epoch + 1)
    fence = s.claim_intent(intent, "owner", epoch)
    assert fence.run_id == run.run_id and fence.intent_id == intent and fence.generation == 1
    assert s.claim_intent(intent, "owner", epoch) == fence
    assert s.get_run(run.run_id).version == 3


def registration(fence):
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        WorkerRegistration,
    )

    return WorkerRegistration(
        registration_id="reg-1",
        fence=fence,
        host="host",
        boot="boot",
        pid=100,
        pgid=100,
        sid=100,
        start_ticks=1000,
    )


def test_attempt_reads_committed_reservation_and_original_timing(driver):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    before = s.get_attempt(fence)
    assert before.reservation == reservation
    assert before.admitted_at == 100.0 and before.released_at is None
    reg = registration(fence)
    s.register_worker(fence, reg)
    s.clock = lambda: 101.0
    assert s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    released = s.get_attempt(fence)
    assert released.reservation == reservation and released.admitted_at == 100.0
    assert released.released_at == 101.0
    s.clock = lambda: 300.0
    assert not s.release_attempt(fence, reg.registration_id, auth, readiness=None)
    assert s.get_attempt(fence) == released


def test_registration_is_exact_and_fenced(driver):
    s = scoped(driver)
    assert hasattr(s, "register_worker"), "registration missing"
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = registration(fence)
    assert s.register_worker(fence, reg) == reg
    assert s.register_worker(fence, reg) == reg
    with pytest.raises(ValueError):
        s.register_worker(fence, reg.model_copy(update={"pid": 101}))
    with pytest.raises(ValueError):
        s.register_worker(fence.model_copy(update={"generation": 2}), reg)
    assert s.get_run(run.run_id).version == 4


def readiness(contract, auth):
    from isaaclab_arena.tests.test_environment_workflow_decisions import gate_readiness

    return gate_readiness(contract)


def test_release_once_requires_fresh_exact_readiness_and_authority(driver):
    s = scoped(driver)
    assert hasattr(s, "release_attempt"), "release missing"
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    ready = readiness(contract, auth)
    with pytest.raises(ValueError):
        s.release_attempt(fence, "reg-1", auth, readiness=ready)
    reg = s.register_worker(fence, registration(fence))
    with pytest.raises(TypeError):
        s.release_attempt(fence, reg.registration_id, auth)
    for bad in [
        auth.model_copy(update={"expires_at": 100.0}),
        auth.model_copy(update={"contract_digest": "b" * 64}),
        auth.model_copy(update={"capabilities": ("operational_writes",)}),
        auth.model_copy(update={"workspace_id": "foreign"}),
    ]:
        with pytest.raises(ValueError):
            s.release_attempt(fence, reg.registration_id, bad, readiness=ready)
    for bad in [
        ready.model_copy(update={"checked_at": 69.0}),
        ready.model_copy(update={"checked_at": 101.0}),
        ready.model_copy(update={"profiles": ready.profiles[:-1]}),
        ready.model_copy(update={"contract_digest": "b" * 64}),
    ]:
        with pytest.raises(ValueError):
            s.release_attempt(fence, reg.registration_id, auth, readiness=bad)
    barrier = Barrier(6)

    def release(_):
        barrier.wait(timeout=10)
        return s.release_attempt(fence, reg.registration_id, auth, readiness=ready)

    with ThreadPoolExecutor(max_workers=6) as pool:
        winners = list(pool.map(release, range(6)))
    assert winners.count(True) == 1 and winners.count(False) == 5
    assert not s.release_attempt(fence, reg.registration_id, auth, readiness=ready)
    with pytest.raises(ValueError):
        s.claim_intent(intent, "owner", fence.owner_epoch)
    assert s.get_run(run.run_id).version == 5
    assert [e.kind for e in s.events_after(0).events].count("AttemptReleased") == 1
    with driver.session(database=s.database) as session:
        rows = list(
            session.run(
                "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id})"
                "-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) WHERE i.intent_id=$id "
                "RETURN properties(i) AS intent, properties(a) AS attempt",
                **s.scope,
                id=intent,
            )
        )
    assert len(rows) == 1
    assert rows[0]["attempt"]["fence_json"] == fence.model_dump_json()
    assert rows[0]["attempt"]["registration_json"] == reg.model_dump_json()
    assert rows[0]["attempt"]["readiness_json"] == ready.model_dump_json()
    assert rows[0]["attempt"]["release_authorization_json"] == auth.model_dump_json()
    assert rows[0]["attempt"]["status"] == rows[0]["intent"]["status"] == "released"


def test_cancel_fences_release_without_cleanup_or_refund(driver):
    s = scoped(driver)
    assert hasattr(s, "request_cancel"), "cancellation missing"
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    with pytest.raises(ValueError):
        s.request_cancel(run.run_id, 1)
    cancelled = s.request_cancel(run.run_id, 4)
    assert cancelled.state == "cancel_requested" and cancelled.version == 5
    assert s.request_cancel(run.run_id, 4) == cancelled
    assert not s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    with pytest.raises(ValueError):
        s.claim_intent(intent, "owner", fence.owner_epoch)
    with pytest.raises(ValueError):
        s.begin_owner("replacement")
    assert s.get_run(run.run_id) == cancelled
    assert s.events_after(0).events[-1].kind == "CancellationRequested"


@pytest.mark.parametrize(
    "change",
    [
        "calls",
        "tokens",
        "cost",
        "runtime",
        "stale",
        "expired",
        "digest",
        "scope",
        "capability",
        "existing",
        "deadline",
    ],
)
def test_reservation_rejection_is_atomic(driver, change):
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        GenerationReservation,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        ExistingSource,
        canonical_json,
    )
    from isaaclab_arena.tests.test_environment_workflow_decisions import (
        authority,
        generation_contract,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    contract = generation_contract()
    if change == "existing":
        contract = contract.model_copy(
            update={"source": ExistingSource(kind="existing", identity="candidate", content="spec")}
        )
    auth = authority(s, contract)
    fields = dict(
        model_calls=1,
        model_tokens=100,
        cost_ceiling_usd=1.0,
        runtime_allowance_seconds=5.0,
    )
    if change in ("calls", "tokens", "cost", "runtime"):
        key, value = {
            "calls": ("model_calls", 3),
            "tokens": ("model_tokens", 1001),
            "cost": ("cost_ceiling_usd", 3.0),
            "runtime": ("runtime_allowance_seconds", 11.0),
        }[change]
        fields[key] = value
    updates = {
        "expired": {"expires_at": 100.0},
        "digest": {"contract_digest": "b" * 64},
        "scope": {"database": "foreign"},
        "capability": {"capabilities": ("operational_writes",)},
    }
    auth = auth.model_copy(update=updates.get(change, {}))
    run = s.admit("negative", "{}", canonical_json(contract), 1)
    if change == "deadline":
        s.clock = lambda: 160.0
    with pytest.raises(ValueError):
        s.reserve_generation(
            run.run_id,
            2 if change == "stale" else 1,
            "decision",
            auth,
            GenerationReservation(**fields),
            readiness=readiness(contract, auth),
        )
    assert s.get_run(run.run_id) == run
    assert s.snapshot().cursor == 1
    with driver.session(database=s.database) as session:
        row = session.run(
            "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "RETURN count(i) AS n",
            **s.scope,
        ).single()
        assert row["n"] == 0


def test_concurrent_reservations_validate_readiness_before_one_transition(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        GenerationReservation,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )
    from isaaclab_arena.tests.test_environment_workflow_decisions import (
        authority,
        generation_contract,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    contract = generation_contract()
    auth = authority(s, contract)
    allowance = GenerationReservation(
        model_calls=1,
        model_tokens=100,
        cost_ceiling_usd=1.0,
        runtime_allowance_seconds=5.0,
    )
    run = s.admit("race", "{}", canonical_json(contract), 1)
    ready = readiness(contract, auth)
    with pytest.raises(TypeError):
        s.reserve_generation(run.run_id, 1, "decision", auth, allowance)
    for bad in (
        None,
        ready.model_copy(update={"checked_at": 69.0}),
        ready.model_copy(update={"profiles": ready.profiles[:-1]}),
    ):
        with pytest.raises(ValueError):
            s.reserve_generation(run.run_id, 1, "decision", auth, allowance, readiness=bad)
        assert s.get_run(run.run_id) == run and s.snapshot().cursor == 1
    barrier = Barrier(4)

    def reserve(_):
        barrier.wait(timeout=10)
        return s.reserve_generation(run.run_id, 1, "decision", auth, allowance, readiness=ready)

    with ThreadPoolExecutor(max_workers=4) as pool:
        identities = list(pool.map(reserve, range(4)))
    assert len(set(identities)) == 1
    assert s.snapshot().cursor == 2
    with driver.session(database=s.database) as session:
        rows = list(
            session.run(
                "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "RETURN i.readiness_json AS readiness",
                **s.scope,
            )
        )
    assert len(rows) == 1 and rows[0]["readiness"] == ready.model_dump_json()


def test_cancel_vs_release_has_one_ordered_effect_and_no_retry_authority(driver):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, _, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    barrier = Barrier(2)

    def work(cancel):
        barrier.wait(timeout=10)
        if not cancel:
            return s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
        try:
            return s.request_cancel(run.run_id, 4)
        except ValueError:
            return "stale-cancel"

    with ThreadPoolExecutor(max_workers=2) as pool:
        released, cancelled = list(pool.map(work, (False, True)))
    events = s.events_after(0).events
    assert len(events) == 5
    assert events[-1].kind == ("AttemptReleased" if released else "CancellationRequested")
    assert (cancelled == "stale-cancel") is released
    s.clock = lambda: 300.0
    assert s.release_attempt(fence, reg.registration_id, auth, readiness=None) is False


def test_release_acknowledgement_loss_replay_returns_false(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
        OutcomeUnknown,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, _, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Transaction(Proxy):
        def commit(self):
            self.real.commit()
            raise OSError("lost acknowledgement after real release commit")

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Transaction(self.real.begin_transaction(**kwargs))

    class Driver(Proxy):
        def session(self, **kwargs):
            return Session(self.real.session(**kwargs))

    failing = Neo4jWorkflowStore(Driver(driver), database=s.database, **s.scope, clock=lambda: 100.0)
    with pytest.raises(OutcomeUnknown):
        failing.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    s.clock = lambda: 300.0
    assert s.release_attempt(fence, reg.registration_id, auth, readiness=None) is False
    assert [e.kind for e in s.events_after(0).events].count("AttemptReleased") == 1
    assert s.get_run(run.run_id).version == 5


def test_generation_result_requires_exact_cleanup(driver, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow import (
        artifacts,
        results,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    assert s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))

    class ReadAuthority:
        def require_read(self, principal):
            if principal != "local":
                raise ValueError("not authenticated")

    service = WorkflowService(s, ReadAuthority(), None, validate_support=lambda value: None)
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        adapter = artifacts.GenerationArtifacts(area)
        receipt = adapter.write(
            fence,
            reg,
            contract,
            b"scene: synthetic\n",
            {"scene": "synthetic"},
            protect=lambda value: None,
        )
        s.clock = lambda: 300.0  # expired execution grant must not erase released work
        assert service.adopt_generation("local", fence, receipt, artifacts=adapter, protect=lambda value: None)
        assert not service.adopt_generation("local", fence, receipt, artifacts=adapter, protect=lambda value: None)
        assert s.get_run(run.run_id).state == "running"
        view = s.get_attempt(fence)
        assert view.receipt == receipt and view.cleanup is None
        evidence = results.CleanupEvidence(
            registration=reg,
            evidence_ref="synthetic-stop-1",
            observation="owned_process_group_stopped",
            remote_effects="unknown",
        )
        assert s.acknowledge_cleanup(fence, evidence)
        assert s.get_run(run.run_id).state == "running"
        assert s.get_run(run.run_id).phase == "validation"
        assert s.get_attempt(fence).status == "produced"
        assert s.get_attempt(fence).usage_disposition == "fully_reserved_consumption_deferred"
        assert not s.acknowledge_cleanup(fence, evidence)
        with pytest.raises(ValueError):
            s.acknowledge_cleanup(
                fence,
                evidence.model_copy(update={"registration": reg.model_copy(update={"pid": 101})}),
            )
        with pytest.raises(ValueError):
            s.commit_generation_receipt(fence.model_copy(update={"generation": 2}), receipt)
        with pytest.raises(ValueError):
            s.commit_generation_receipt(fence, receipt.model_copy(update={"candidate_yaml_sha256": "b" * 64}))


@pytest.mark.parametrize("damage", ["bytes", "missing", "symlink", "manifest", "deny", "owner"])
def test_generation_adoption_rejects_artifact_damage_without_receipt(driver, tmp_path, damage):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))

    class ReadAuthority:
        def require_read(self, principal):
            pass  # synthetic authenticated principal; service must still owner-bind

    service = WorkflowService(s, ReadAuthority(), None, validate_support=lambda value: None)
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        adapter = GenerationArtifacts(area)
        receipt = adapter.write(
            fence,
            reg,
            contract,
            b"synthetic: true\n",
            {"synthetic": True},
            protect=lambda value: None,
        )
        path = tmp_path / "area" / receipt.artifact_directory / "candidate.yaml"
        if damage == "bytes":
            path.write_bytes(b"changed")
        elif damage == "missing":
            path.unlink()
        elif damage == "symlink":
            path.unlink()
            path.symlink_to(tmp_path / "outside")
        elif damage == "manifest":
            path.with_name("manifest.json").write_text("{}")

        def protect(value):
            if damage == "deny":
                raise ValueError("current policy rejects private data")

        before = s.get_run(run.run_id)
        with pytest.raises(ValueError):
            service.adopt_generation(
                "other" if damage == "owner" else "local",
                fence,
                receipt,
                artifacts=adapter,
                protect=protect,
            )
        assert s.get_attempt(fence).receipt is None
        assert s.get_run(run.run_id) == before


@pytest.mark.parametrize("cleanup_first", [False, True])
def test_cancelled_late_generation_is_diagnostic_only(driver, tmp_path, cleanup_first):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    evidence = CleanupEvidence(
        registration=reg,
        evidence_ref="synthetic-stop",
        observation="owned_process_group_stopped",
        remote_effects="unknown",
    )
    s.request_cancel(run.run_id, s.get_run(run.run_id).version)
    if cleanup_first:
        s.acknowledge_cleanup(fence, evidence)

    class ReadAuthority:
        def require_read(self, principal):
            assert principal == "local"

    service = WorkflowService(s, ReadAuthority(), None, validate_support=lambda value: None)
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        adapter = GenerationArtifacts(area)
        receipt = adapter.write(
            fence,
            reg,
            contract,
            b"synthetic: true\n",
            {"synthetic": True},
            protect=lambda value: None,
        )
        assert service.adopt_generation("local", fence, receipt, artifacts=adapter, protect=lambda value: None)
        assert s.get_run(run.run_id).state == ("cancelled" if cleanup_first else "cancel_requested")
        if not cleanup_first:
            s.acknowledge_cleanup(fence, evidence)
        assert s.get_run(run.run_id).state == "cancelled"
        assert s.get_attempt(fence).receipt == receipt
        with driver.session(database=s.database) as session:
            row = session.run(
                "MATCH (a:ArenaExecutionAttempt {attempt_id:$id}) RETURN a.receipt_disposition AS disposition",
                id=fence.attempt_id,
            ).single()
        assert row["disposition"] == "diagnostic"
        with pytest.raises(ValueError):
            s.begin_owner("replacement")


def test_cleanup_before_release_fences_future_execution(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    s.acknowledge_cleanup(
        fence,
        CleanupEvidence(
            registration=reg,
            evidence_ref="synthetic-stop",
            observation="owned_process_group_stopped",
            remote_effects="unknown",
        ),
    )
    assert not s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    cancelled = s.request_cancel(run.run_id, s.get_run(run.run_id).version)
    assert cancelled.state == "cancelled"


def test_receipt_retained_with_uncertain_cleanup_requires_reconciliation(driver, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
        ReconciliationReason,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    store = scoped(driver)
    store.clock = lambda: 100.0
    run, intent, auth, _, contract = reserved(store)
    fence = store.claim_intent(intent, "owner", store.begin_owner("owner"))
    reg = store.register_worker(fence, registration(fence))
    assert store.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))

    class Authority:
        def require_read(self, principal):
            assert principal == "local"

    service = WorkflowService(store, Authority(), None, validate_support=lambda value: None)
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        artifacts = GenerationArtifacts(area)
        receipt = artifacts.write(
            fence,
            reg,
            contract,
            b"synthetic: true\n",
            {"synthetic": True},
            protect=lambda value: None,
        )
        assert service.adopt_generation("local", fence, receipt, artifacts=artifacts, protect=lambda value: None)
        with pytest.raises(ValueError):
            store.mark_reconciliation_required(fence, ReconciliationReason.RELEASED_WITHOUT_RECEIPT)
        assert store.mark_reconciliation_required(fence, ReconciliationReason.OWNER_OUTCOME_UNCERTAIN)
        assert store.get_run(run.run_id).state == "reconciliation_required"
        assert store.get_attempt(fence).receipt == receipt
        assert not store.release_attempt(fence, reg.registration_id, auth, readiness=None)
        assert store.acknowledge_cleanup(
            fence,
            CleanupEvidence(
                registration=reg,
                evidence_ref="synthetic-stop",
                observation="owned_process_group_stopped",
                remote_effects="unknown",
            ),
        )
        final = store.get_run(run.run_id)
        assert (final.state, final.phase) == ("running", "validation")


@pytest.mark.parametrize("cancel_order", [None, "before_receipt", "after_receipt", "after_cleanup"])
@pytest.mark.parametrize("cleanup_first", [False, True])
def test_lost_released_attempt_reconciles_only_exact_output(driver, tmp_path, cancel_order, cleanup_first):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow import results
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    assert hasattr(s, "mark_reconciliation_required"), "lost attempt disposition missing"
    reason = results.ReconciliationReason.RELEASED_WITHOUT_RECEIPT
    before = s.get_run(run.run_id)
    with pytest.raises(ValueError):
        s.mark_reconciliation_required(fence, reason)
    assert s.get_run(run.run_id) == before
    assert s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    assert s.mark_reconciliation_required(fence, reason)
    retained = s.get_run(run.run_id)
    assert (retained.state, retained.phase) == ("reconciliation_required", "generation")
    assert not s.mark_reconciliation_required(fence, reason)
    with pytest.raises(ValueError):
        s.mark_reconciliation_required(fence, results.ReconciliationReason.OWNER_OUTCOME_UNCERTAIN)
    with pytest.raises(ValueError):
        s.mark_reconciliation_required(fence, "not-an-enum")
    assert s.get_run(run.run_id) == retained
    assert s.get_attempt(fence).reconciliation_reason == reason
    assert s.get_attempt(fence).status == "reconciliation_required"
    assert s.get_attempt(fence).released
    assert s.get_attempt(fence).receipt is None
    assert not s.release_attempt(fence, reg.registration_id, auth, readiness=None)
    with pytest.raises(ValueError):
        s.claim_intent(intent, "owner", fence.owner_epoch)
    with pytest.raises(ValueError):
        s.reserve_generation(
            run.run_id,
            retained.version,
            "retry",
            auth,
            reservation,
            readiness=readiness(contract, auth),
        )
    with pytest.raises(ValueError):
        s.begin_owner("replacement")
    assert s.snapshot().runs == (retained,)
    assert s.events_after(0).events[-1].kind == "ReconciliationRequired"
    evidence = results.CleanupEvidence(
        registration=reg,
        evidence_ref="synthetic-stop",
        observation="owned_process_group_stopped",
        remote_effects="unknown",
    )

    def cancel():
        s.request_cancel(run.run_id, s.get_run(run.run_id).version)

    if cancel_order == "before_receipt":
        cancel()
        assert s.get_run(run.run_id).state == "cancel_requested"
    if cleanup_first:
        s.acknowledge_cleanup(fence, evidence)

    class ReadAuthority:
        def require_read(self, principal):
            assert principal == "local"

    service = WorkflowService(s, ReadAuthority(), None, validate_support=lambda value: None)
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        adapter = GenerationArtifacts(area)
        receipt = adapter.write(
            fence,
            reg,
            contract,
            b"synthetic: true\n",
            {"synthetic": True},
            protect=lambda value: None,
        )
        s.clock = lambda: 300.0
        assert service.adopt_generation("local", fence, receipt, artifacts=adapter, protect=lambda value: None)
        if cancel_order == "after_receipt":
            cancel()
        if not cleanup_first:
            s.acknowledge_cleanup(fence, evidence)
        if cancel_order == "after_cleanup":
            cancel()
        final = s.get_run(run.run_id)
        assert final.state == ("cancelled" if cancel_order else "running")
        if not cancel_order:
            assert final.phase == "validation"
        assert not service.adopt_generation("local", fence, receipt, artifacts=adapter, protect=lambda value: None)
        assert not s.mark_reconciliation_required(fence, reason)
        assert s.get_run(run.run_id) == final
        view = s.get_attempt(fence)
        assert view.status == ("cancelled" if cancel_order else "produced")
        assert view.receipt == receipt and view.cleanup == evidence
        assert_receipt_storage(s, receipt, "diagnostic" if cancel_order else "produced")
        assert view.reconciliation_reason == reason
        assert view.usage_disposition == "fully_reserved_consumption_deferred"
        assert not s.release_attempt(fence, reg.registration_id, auth, readiness=None)
        assert [e.kind for e in s.events_after(0).events].count("AttemptReleased") == 1
        assert [e.kind for e in s.events_after(0).events].count("ReconciliationRequired") == 1
        with pytest.raises(ValueError):
            s.begin_owner("replacement")


def test_deployment_isolation_with_same_workspace_and_keys(driver):
    workspace = uuid.uuid4().hex
    left = scoped(driver, workspace, "deployment-left")
    right = scoped(driver, workspace, "deployment-right")
    first = left.admit("same", '{"side":"left"}', "{}", 1)
    assert_readback(right, [])
    assert right.lookup_submission("same", '{"side":"right"}') is None
    second = right.admit("same", '{"side":"right"}', "{}", 1)
    assert first.run_id != second.run_id
    assert left.get_run(second.run_id) is right.get_run(first.run_id) is None
    assert_readback(left, [first])
    assert_readback(right, [second])


def apply_release_authority_fault(f, fault):
    """Mutate only private fake authority after the real release commits."""
    if fault == "release_expiry":
        f.now[0] = f.auth.expires_at + 1
    elif fault == "release_revocation":
        f.revoked = True
    elif fault == "release_rotation":
        f.rotated = True
    elif fault == "release_grant_change":
        f.auth = f.auth.model_copy(update={"grant_ref": "replacement"})


def live_coordinator(driver, *, fault=None, completion=False):
    """Real store/gate/bridge; synthetic trusted lease, authority and worker (no processes)."""
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        GenerationReservation,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        GenerationCoordinator,
        PreparedWorker,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import (
        DependencyGate,
        DependencyResult,
        ReadinessClock,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )
    from isaaclab_arena.tests.test_environment_workflow_decisions import (
        authority,
        generation_contract,
    )

    store = scoped(driver)

    now = [100.0]

    def clock():
        return now[0]

    store.clock = clock
    contract = generation_contract()
    auth = authority(store, contract)
    run = store.admit("coordinator", "{}", canonical_json(contract), 1)
    f = SimpleNamespace(
        store=store,
        run=run,
        calls=[],
        prepared=None,
        intent=None,
        claimed=None,
        held=True,
        now=now,
        revoked=False,
        auth=auth,
        rotated=False,
    )

    class StoreProxy:
        """Fault only the selected boundary; every successful operation uses real Cypher."""

        def __getattr__(self, name):
            value = getattr(store, name)
            if not callable(value):
                return value

            def call(*args, **kwargs):
                f.calls.append("db:" + name)
                if name in ("begin_owner", "claim_intent"):
                    handle = f.coordinator._handle
                    assert handle.intent_id == f.intent and handle.decision_id == "decision"
                    assert handle.run_id == run.run_id and handle.expected_version == 1
                    assert handle.owner_id == f.coordinator._lease.owner_id
                    if name == "claim_intent":
                        assert handle.owner_epoch == args[2]
                if (name, fault) in {
                    ("register_worker", "registration_before"),
                    ("begin_owner", "pre_claim"),
                }:
                    raise OSError("synthetic boundary failure before commit")
                result = value(*args, **kwargs)
                if name == "release_attempt" and result is True:
                    apply_release_authority_fault(f, fault)
                if name == "reserve_generation":
                    f.intent = result
                    if fault == "reserve_ack_unknown":
                        raise OSError("synthetic reservation acknowledgement loss")
                if name == "claim_intent":
                    f.claimed = result
                if (name, fault) in {
                    ("register_worker", "registration_after"),
                    ("claim_intent", "claim_ack_unknown"),
                }:
                    raise OSError("synthetic acknowledgement loss after commit")
                return result

            return call

    class Authority:
        def require_read(self, principal):
            f.calls.append("authenticate")
            if principal != "local":
                raise PermissionError("creator required")

        def require_execute(self, principal, request, *, run_id, fence=None):
            assert principal == "local" and request == contract
            assert run_id == run.run_id and fence == f.claimed
            f.calls.append("execute_auth")
            if f.revoked or now[0] >= f.auth.expires_at:
                raise PermissionError("execution authority expired or revoked")
            return f.auth

        def release_guard(self, principal, request, fence, registration):
            from contextlib import nullcontext

            return nullcontext()

        def private_envelope(self, principal, request, fence, reg):
            assert principal == "local" and request == contract and reg.fence == fence
            f.calls.append("envelope")
            if f.rotated:
                raise PermissionError("frozen configuration changed")
            return b"synthetic-no-provider-envelope"

    class Lease:
        owner_id = "synthetic-owner-" + uuid.uuid4().hex

        def mark_prepared(self, fence):
            assert fence.owner_id == self.owner_id

        def require_held(self, run_id, principal):
            assert (run_id, principal) == (run.run_id, "local")
            if not f.held:
                raise RuntimeError("synthetic lease lost")

    class Worker:
        def prepare(self, fence, request, *, timeout_s):
            assert request == contract and 0 < timeout_s <= 120
            f.calls.append("prepare")
            f.prepared = PreparedWorker(registration(fence), object())
            if fault == "lease_lost":
                f.held = False
            return f.prepared

        def send(self, prepared, envelope, *, timeout_s):
            assert prepared is f.prepared and envelope == b"synthetic-no-provider-envelope"
            assert store.get_attempt(prepared.registration.fence).released
            f.calls.append("send")
            if fault == "send_failure":
                raise OSError("synthetic send outcome unknown")

        def stop_owned(self, prepared, *, timeout_s):
            assert prepared is f.prepared
            f.calls.append("localstop")
            return CleanupEvidence(
                registration=prepared.registration,
                evidence_ref="synthetic-owned-stop",
                observation="owned_process_group_stopped",
                remote_effects="unknown",
            )

    gate = DependencyGate(
        lambda req, timeout: DependencyResult(
            req.dependency_id,
            "passed",
            req.profile_sha256,
            profile_id=req.profile_id,
            instance_id=req.instance_id,
        ),
        clock=clock,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    proxy, authority_port = StoreProxy(), Authority()
    options = {}
    if completion:
        options["workflow_service"] = WorkflowService(proxy, authority_port, gate, validate_support=lambda _: None)
    f.coordinator = GenerationCoordinator(
        proxy,
        authority_port,
        gate,
        Worker(),
        run_id=run.run_id,
        principal="local",
        lease=Lease(),
        readiness_clock=ReadinessClock.capture(monotonic=clock, wall_clock=clock),
        **options,
    )
    f.reservation = GenerationReservation(
        model_calls=1,
        model_tokens=100,
        cost_ceiling_usd=1.0,
        runtime_allowance_seconds=5.0,
    )
    f.dispatch = lambda: f.coordinator.dispatch(
        "local",
        expected_version=1,
        decision_id="decision",
        reservation=f.reservation,
    )
    return f


@pytest.mark.parametrize(
    "fault",
    [
        "release_expiry",
        "release_revocation",
        "release_rotation",
        "release_grant_change",
    ],
)
def test_committed_release_rechecks_private_authority_before_send(driver, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        DispatchIncomplete,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        ReconciliationReason,
    )

    f = live_coordinator(driver, fault=fault)
    with pytest.raises(DispatchIncomplete) as caught:
        f.dispatch()
    handle = caught.value.handle
    retained = f.store.get_attempt(handle.fence)
    assert retained.released and retained.receipt is None
    assert retained.authorization.grant_ref != "replacement"
    assert retained.reconciliation_reason is ReconciliationReason.OWNER_OUTCOME_UNCERTAIN
    assert handle.cleanup.registration == f.prepared.registration
    assert not handle.cleanup_pending and not handle.durable_reconciliation_pending
    assert f.calls.count("send") == 0 and f.calls.count("localstop") == 1
    before = list(f.calls)
    assert f.dispatch() is handle
    assert f.calls == before + ["authenticate"]
    assert f.store.get_run(f.run.run_id).state == "reconciliation_required"


@pytest.fixture
def completion_input(driver, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        parse_contract,
    )

    f = live_coordinator(driver, completion=True)
    handle = f.dispatch()
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        artifacts = GenerationArtifacts(area)
        receipt = artifacts.write(
            handle.fence,
            handle.prepared.registration,
            parse_contract(f.run.contract_json),
            b"scene: synthetic\n",
            {"scene": "synthetic"},
            protect=lambda _: None,
        )
        yield f, handle, artifacts, receipt, tmp_path / "area"


def test_retired_owner_read_survives_replacement_without_changing_authority(
    completion_input,
):
    f, handle, artifacts, receipt, _ = completion_input
    store, fence = f.store, handle.fence
    lookup = getattr(store, "get_retired_owner", None)
    assert callable(lookup), "read-only retained retirement lookup is missing"
    assert lookup(fence.owner_id) is None
    f.coordinator.complete("local", receipt, artifacts, protect=lambda value: None)
    assert store.retire_owner(fence.owner_id, fence.owner_epoch)
    retired = lookup(fence.owner_id)
    assert retired.model_dump() == {
        "owner_id": fence.owner_id,
        "owner_epoch": fence.owner_epoch,
        "dirty": False,
    }
    store.begin_owner("replacement")
    owner, snapshot = store.get_owner(), store.snapshot()
    assert lookup(fence.owner_id) == retired
    assert lookup("replacement") is None
    assert lookup("unknown") is None
    assert store.get_owner() == owner and store.snapshot() == snapshot


def test_clean_owner_handover_preserves_historical_reads_and_fences_mutations(
    completion_input,
):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        parse_contract,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        ReconciliationReason,
    )

    f, handle, artifacts, receipt, _ = completion_input
    s, fence = f.store, handle.fence
    owner = s.get_owner()
    assert owner.model_dump() == {
        "owner_id": fence.owner_id,
        "owner_epoch": 1,
        "dirty": True,
    }
    with pytest.raises(ValueError, match="unresolved"):
        s.retire_owner(fence.owner_id, 1)
    assert s.get_owner() == owner
    assert s.commit_generation_receipt(fence, artifacts.verify(receipt, protect=lambda _: None))
    with pytest.raises(ValueError, match="unresolved"):
        s.retire_owner(fence.owner_id, 1)
    result = f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    before = s.snapshot()
    retained = s.get_attempt(fence)
    assert result.attempt == retained and retained.status == "produced"
    assert s.retire_owner(fence.owner_id, 1) is True
    assert s.get_owner().model_dump() == {
        "owner_id": fence.owner_id,
        "owner_epoch": 1,
        "dirty": False,
    }
    assert s.retire_owner(fence.owner_id, 1) is False
    assert s.get_attempt(fence) == retained
    with pytest.raises(ValueError, match="retired"):
        s.begin_owner(fence.owner_id)
    assert s.begin_owner("owner-b") == 2
    assert s.begin_owner("owner-b") == 2
    replacement = s.get_owner()
    assert replacement.owner_id == "owner-b" and replacement.owner_epoch == 2 and replacement.dirty
    assert s.get_attempt(fence) == s.get_generation_attempt(fence.run_id) == retained
    assert s.snapshot() == before
    next_run = s.admit("next-run", "{}", f.run.contract_json, 1)
    next_intent = s.reserve_generation(
        next_run.run_id,
        1,
        "next-decision",
        f.auth,
        f.reservation,
        readiness=readiness(parse_contract(f.run.contract_json), f.auth),
    )
    next_fence = s.claim_intent(next_intent, "owner-b", 2)
    s.register_worker(next_fence, registration(next_fence))
    next_view, next_run = s.get_attempt(next_fence), s.get_run(next_run.run_id)
    before = s.snapshot()
    for mutation in (
        lambda: s.claim_intent(fence.intent_id, fence.owner_id, 1),
        lambda: s.register_worker(fence, retained.registration),
        lambda: s.release_attempt(fence, retained.registration.registration_id, f.auth, readiness=None),
        lambda: s.commit_generation_receipt(fence, receipt),
        lambda: s.acknowledge_cleanup(fence, retained.cleanup),
        lambda: s.mark_reconciliation_required(fence, ReconciliationReason.OWNER_OUTCOME_UNCERTAIN),
    ):
        with pytest.raises(ValueError, match="owner"):
            mutation()
        assert s.get_owner() == replacement and s.snapshot() == before
    cancelled = s.request_cancel(fence.run_id, result.run.version)
    assert cancelled.state == "cancelled"
    historical = s.get_generation_attempt(fence.run_id)
    assert historical.status == "cancelled" and historical.receipt == receipt
    assert historical.cleanup == retained.cleanup and historical.reservation == retained.reservation
    assert s.request_cancel(fence.run_id, result.run.version) == cancelled
    assert s.get_owner() == replacement
    assert s.get_attempt(next_fence) == next_view and s.get_run(next_run.run_id) == next_run
    assert_receipt_storage(s, receipt, "diagnostic")


@pytest.mark.parametrize(
    "stage",
    [
        "reserved",
        "claimed",
        "prepared_unregistered",
        "registered",
        "released",
        "cleaned_no_outcome",
        "cancelled_no_cleanup",
    ],
)
def test_retirement_never_treats_unresolved_or_missing_registration_as_no_process(driver, stage):
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, _, contract = reserved(s)
    epoch = s.begin_owner("owner")
    if stage != "reserved":
        fence = s.claim_intent(intent, "owner", epoch)
        reg = registration(fence)  # Synthetic prepared process even if registration was not committed.
        if stage not in ("claimed", "prepared_unregistered"):
            s.register_worker(fence, reg)
            if stage in ("released", "cleaned_no_outcome"):
                s.release_attempt(
                    fence,
                    reg.registration_id,
                    auth,
                    readiness=readiness(contract, auth),
                )
            if stage == "cleaned_no_outcome":
                s.acknowledge_cleanup(
                    fence,
                    CleanupEvidence(
                        registration=reg,
                        evidence_ref="synthetic-stop",
                        observation="owned_process_group_stopped",
                        remote_effects="unknown",
                    ),
                )
        if stage == "cancelled_no_cleanup":
            assert s.request_cancel(run.run_id, s.get_run(run.run_id).version).state == "cancel_requested"
    before, owner = s.snapshot(), s.get_owner()
    with pytest.raises(ValueError, match="unresolved"):
        s.retire_owner("owner", epoch)
    with pytest.raises(ValueError, match="dirty"):
        s.begin_owner("replacement")
    assert s.snapshot() == before and s.get_owner() == owner


def test_cancelled_clean_registration_can_retire_without_refund(driver):
    f = live_coordinator(driver)
    handle = f.dispatch()
    f.coordinator.cancel("local")
    s, fence = f.store, handle.fence
    retained = s.get_attempt(fence)
    assert retained.status == "cancelled" and retained.receipt is None and retained.cleanup
    assert s.retire_owner(fence.owner_id, fence.owner_epoch)
    assert s.get_owner().dirty is False
    assert s.begin_owner("next") == 2
    assert s.get_generation_attempt(fence.run_id) == retained
    assert retained.reservation == f.reservation
    assert retained.usage_disposition == "fully_reserved_consumption_deferred"


def test_owner_absence_and_unavailable_readback_grant_no_retirement(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
        ScopeMissing,
    )

    s = scoped(driver)
    assert s.get_owner() is None
    with pytest.raises(ValueError, match="owner"):
        s.retire_owner("unknown", 1)
    assert s.get_owner() is None
    uninitialized = Neo4jWorkflowStore(driver, database=s.database, **{**s.scope, "workspace_id": "uninitialized"})
    with pytest.raises(ScopeMissing):
        uninitialized.get_owner()

    class Offline:
        def session(self, **kwargs):
            raise OSError("database unavailable")

    offline = Neo4jWorkflowStore(Offline(), database=s.database, **s.scope)
    with pytest.raises(OSError):
        offline.get_owner()
    assert s.begin_owner("empty-owner") == 1
    for wrong in (True, 0, -1, 2, "1"):
        with pytest.raises(ValueError):
            s.retire_owner("empty-owner", wrong)
    assert s.retire_owner("empty-owner", 1)
    assert s.get_owner().dirty is False


def test_retirement_commit_ack_loss_replays_exact_identity_even_after_later_epochs(
    completion_input,
):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
        OutcomeUnknown,
    )

    f, handle, artifacts, receipt, _ = completion_input
    f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    s, fence = f.store, handle.fence

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Transaction(Proxy):
        def commit(self):
            self.real.commit()
            raise OSError("lost retirement acknowledgement after real commit")

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Transaction(self.real.begin_transaction(**kwargs))

    class Driver(Proxy):
        def session(self, **kwargs):
            return Session(self.real.session(**kwargs))

    failing = Neo4jWorkflowStore(Driver(s.driver), database=s.database, **s.scope)
    with pytest.raises(OutcomeUnknown):
        failing.retire_owner(fence.owner_id, 1)
    independent = Neo4jWorkflowStore(s.driver, database=s.database, **s.scope)
    retired = independent.get_owner()
    assert (retired.owner_id, retired.owner_epoch, retired.dirty) == (
        fence.owner_id,
        1,
        False,
    )
    assert independent.retire_owner(fence.owner_id, 1) is False
    for epoch, name in enumerate(("owner-b", "owner-c", "owner-d"), 2):
        assert independent.begin_owner(name) == epoch
        assert independent.begin_owner(name) == epoch
        active = independent.get_owner()
        assert independent.retire_owner(fence.owner_id, 1) is False
        assert independent.get_owner() == active
        with pytest.raises(ValueError):
            independent.retire_owner(fence.owner_id, epoch)
        with pytest.raises(ValueError, match="retired"):
            independent.begin_owner(fence.owner_id)
        assert independent.retire_owner(name, epoch)
        assert independent.get_owner().dirty is False
    assert independent.get_generation_attempt(fence.run_id).receipt == receipt


@pytest.mark.parametrize("round_index", range(3))
def test_retirement_races_have_one_commit_and_never_clear_replacement(driver, round_index):
    s = scoped(driver)
    assert s.begin_owner("owner-a") == 1
    barrier = Barrier(6)

    def retire(_):
        barrier.wait(timeout=10)
        return s.retire_owner("owner-a", 1)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(retire, range(6)))
    assert results.count(True) == 1 and results.count(False) == 5
    assert s.get_owner().dirty is False
    barrier = Barrier(6)

    def begin_or_replay(index):
        barrier.wait(timeout=10)
        if index < 3:
            return s.retire_owner("owner-a", 1)
        try:
            return s.begin_owner("owner-" + str(index))
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(begin_or_replay, range(6)))
    assert results[:3] == [False] * 3
    assert results[3:].count(2) == 1 and results[3:].count(None) == 2
    owner = s.get_owner()
    assert owner.dirty and owner.owner_epoch == 2
    assert s.retire_owner("owner-a", 1) is False
    assert s.get_owner() == owner


@pytest.mark.parametrize("failure", ["bytes", "database", "cleanup", "acknowledgement"])
def test_real_completion_failure_stops_locally_and_retains_obligations(completion_input, monkeypatch, failure):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        CompletionIncomplete,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        ReconciliationReason,
    )

    f, handle, artifacts, receipt, root = completion_input

    def unavailable(*args, **kwargs):
        raise OSError("private failure detail")

    if failure == "bytes":
        (root / receipt.artifact_directory / "candidate.yaml").write_bytes(b"corrupt")
    elif failure == "database":
        monkeypatch.setattr(f.store, "get_attempt", unavailable)
        monkeypatch.setattr(f.store, "acknowledge_cleanup", unavailable)
        monkeypatch.setattr(f.store, "mark_reconciliation_required", unavailable)
    elif failure == "cleanup":
        monkeypatch.setattr(f.coordinator._worker, "stop_owned", unavailable)
    else:
        monkeypatch.setattr(f.store, "acknowledge_cleanup", unavailable)
    with pytest.raises(CompletionIncomplete) as caught:
        f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert "private" not in str(caught.value)
    assert caught.value.handle is handle and f.coordinator._handle is handle
    assert handle.incomplete and handle.reconciliation_required
    assert handle.fence == receipt.fence and handle.prepared is f.prepared
    if failure != "cleanup":
        assert handle.cleanup is not None and f.calls.count("localstop") == 1
    else:
        assert handle.cleanup is None and handle.cleanup_pending
    if failure == "database":
        assert handle.durable_reconciliation_pending
    else:
        view = f.store.get_attempt(handle.fence)
        assert view.reconciliation_reason == ReconciliationReason.OWNER_OUTCOME_UNCERTAIN
        assert view.receipt == (None if failure == "bytes" else receipt)
        assert f.store.get_run(f.run.run_id).phase != "validation"
    assert f.dispatch() is handle
    assert f.calls.count("send") == f.calls.count("prepare") == 1


@pytest.mark.parametrize("when", ["before", "callback", "concurrent", "offline_before"])
def test_real_completion_cancellation_wins_and_late_receipt_is_diagnostic(completion_input, monkeypatch, when):
    from threading import Thread

    f, handle, artifacts, receipt, _ = completion_input
    threads = []
    if when == "before":
        f.coordinator.cancel("local")
    if when == "offline_before":
        original = f.store.get_run

        def unavailable(*args):
            raise OSError("private offline")

        monkeypatch.setattr(f.store, "get_run", unavailable)
        assert f.coordinator.cancel("local").durable_cancellation_pending
        monkeypatch.setattr(f.store, "get_run", original)

    def protect(_):
        if when == "callback":
            f.coordinator.cancel("local")
        if when == "concurrent":
            thread = Thread(target=lambda: f.coordinator.cancel("local"))
            threads.append(thread)
            thread.start()
            thread.join(2)
            assert not thread.is_alive(), "adoption must not block cancellation"

    try:
        result = f.coordinator.complete("local", receipt, artifacts, protect=protect)
    finally:
        for thread in threads:
            thread.join(5)
    assert result.disposition == "cancelled" and result.run.state == "cancelled"
    assert result.attempt.receipt == receipt and result.attempt.cleanup == handle.cleanup
    assert f.calls.count("localstop") == f.calls.count("send") == 1
    assert f.store.get_run(f.run.run_id).state == "cancelled"
    assert_receipt_storage(f.store, receipt, "diagnostic")


def assert_receipt_storage(store, receipt, disposition):
    with store.driver.session(database=store.database) as session:
        row = session.run(
            "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) WHERE a.attempt_id=$attempt "
            "RETURN a.receipt_json AS receipt, a.receipt_disposition AS disposition",
            **store.scope,
            attempt=receipt.fence.attempt_id,
        ).single(strict=True)
    assert row["receipt"] == receipt.model_dump_json()
    assert row["disposition"] == disposition


@pytest.mark.parametrize("change", ["principal", "fence", "registration"])
def test_real_completion_wrong_local_identity_has_zero_stops(completion_input, change):
    f, handle, artifacts, receipt, _ = completion_input
    principal = "stranger" if change == "principal" else "local"
    if change == "fence":
        receipt = receipt.model_copy(update={"fence": receipt.fence.model_copy(update={"generation": 2})})
    if change == "registration":
        receipt = receipt.model_copy(update={"registration": receipt.registration.model_copy(update={"pid": 101})})
    with pytest.raises((ValueError, PermissionError)):
        f.coordinator.complete(principal, receipt, artifacts, protect=lambda _: None)
    assert "localstop" not in f.calls and handle.cleanup is None
    assert f.store.get_attempt(handle.fence).receipt is None


def test_real_completion_invalid_first_receipt_recovers_original_attempt(
    completion_input,
):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        CompletionIncomplete,
    )

    f, handle, artifacts, receipt, _ = completion_input
    malformed = receipt.model_copy(update={"candidate_yaml_sha256": "b" * 64})
    with pytest.raises(CompletionIncomplete):
        f.coordinator.complete("local", malformed, artifacts, protect=lambda _: None)
    assert f.store.get_attempt(handle.fence).receipt is None
    assert f.store.get_run(f.run.run_id).state == "reconciliation_required"
    assert handle.cleanup is not None and handle.reconciliation_required
    result = f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert result.disposition == "validation" and result.attempt.receipt == receipt
    assert not handle.incomplete and not handle.reconciliation_required
    assert not handle.durable_reconciliation_pending and not handle.cleanup_pending
    assert f.dispatch() is handle
    assert f.calls.count("localstop") == f.calls.count("send") == f.calls.count("prepare") == 1
    assert_receipt_storage(f.store, receipt, "produced")


@pytest.mark.parametrize("committed", [False, True])
def test_real_completion_verified_pin_survives_unknown_commit(completion_input, monkeypatch, tmp_path, committed):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        parse_contract,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        CompletionIncomplete,
    )

    f, handle, artifacts, receipt, _ = completion_input
    original = f.store.commit_generation_receipt

    def unknown(*args):
        assert handle.completion_receipt == receipt, "verified receipt must pin before possible commit"
        if committed:
            original(*args)
        raise OSError("private commit acknowledgement lost")

    monkeypatch.setattr(f.store, "commit_generation_receipt", unknown)
    with pytest.raises(CompletionIncomplete) as caught:
        f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert "private" not in str(caught.value)
    assert f.store.get_attempt(handle.fence).receipt == (receipt if committed else None)
    monkeypatch.setattr(f.store, "commit_generation_receipt", original)
    with ArtifactArea.create(tmp_path / "conflict", store_id="test", registry_id="scope") as area:
        other_artifacts = GenerationArtifacts(area)
        other = other_artifacts.write(
            handle.fence,
            handle.prepared.registration,
            parse_contract(f.run.contract_json),
            b"scene: other\n",
            {"scene": "other"},
            protect=lambda _: None,
        )
        assert other_artifacts.verify(other, protect=lambda _: None) == other
        with pytest.raises(ValueError, match="conflicting"):
            f.coordinator.complete("local", other, other_artifacts, protect=lambda _: None)
    result = f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert result.disposition == "validation"
    assert not handle.incomplete and not handle.reconciliation_required
    assert not handle.durable_reconciliation_pending and not handle.cleanup_pending
    assert f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None) == result
    assert f.calls.count("localstop") == f.calls.count("send") == f.calls.count("prepare") == 1
    assert_receipt_storage(f.store, receipt, "produced")


def test_expired_execution_still_allows_authenticated_completion_and_exact_retry(
    completion_input,
):
    f, handle, artifacts, receipt, _ = completion_input
    f.now[0] = f.auth.expires_at + 1
    calls = f.calls.count("execute_auth")
    result = f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert result.disposition == "validation"
    assert f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None) == result
    assert f.dispatch() is handle
    assert f.calls.count("execute_auth") == calls
    assert f.calls.count("send") == f.calls.count("localstop") == 1


def test_real_completion_conflict_rejected_locally_and_duplicate_rechecks_bytes(
    completion_input,
):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        CompletionIncomplete,
    )

    f, handle, artifacts, receipt, root = completion_input
    f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    count = len(f.calls)
    changed = receipt.model_copy(update={"candidate_yaml_sha256": "b" * 64})
    with pytest.raises(ValueError, match="conflicting"):
        f.coordinator.complete("local", changed, artifacts, protect=lambda _: None)
    assert f.calls[count:] == ["authenticate"]
    (root / receipt.artifact_directory / "candidate.yaml").write_bytes(b"corrupt")
    with pytest.raises(CompletionIncomplete):
        f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert f.calls.count("localstop") == f.calls.count("send") == 1
    assert handle.incomplete


@pytest.mark.parametrize("bypass", ["fake_artifacts", "instance_adopter"])
def test_real_completion_cannot_bypass_concrete_artifact_verification(completion_input, monkeypatch, bypass):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        CompletionIncomplete,
    )

    f, handle, artifacts, receipt, root = completion_input

    class FakeArtifacts:
        def verify(self, value, **kwargs):
            return value

    if bypass == "fake_artifacts":
        artifacts = FakeArtifacts()
    else:
        monkeypatch.setattr(f.coordinator._service, "adopt_generation", lambda *args, **kwargs: True)
        (root / receipt.artifact_directory / "candidate.yaml").write_bytes(b"corrupt")
    with pytest.raises(CompletionIncomplete):
        f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert f.store.get_attempt(handle.fence).receipt is None
    assert handle.incomplete and f.calls.count("localstop") == 1
    with pytest.raises(ValueError):
        f.store.begin_owner("replacement-owner")
    assert f.store.get_attempt(handle.fence).usage_disposition == "fully_reserved_consumption_deferred"


def test_real_completion_retry_reconciles_ack_loss_without_stopping_twice(completion_input, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        CompletionIncomplete,
    )

    f, handle, artifacts, receipt, _ = completion_input
    original = f.store.acknowledge_cleanup

    def unavailable(*args):
        assert original(*args) is True
        raise OSError("private ack loss after actual cleanup commit")

    monkeypatch.setattr(f.store, "acknowledge_cleanup", unavailable)
    with pytest.raises(CompletionIncomplete):
        f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    retained = f.store.get_attempt(handle.fence)
    assert retained.cleanup == handle.cleanup and retained.receipt == receipt
    assert f.store.get_run(f.run.run_id).phase == "validation"
    assert handle.incomplete and handle.reconciliation_required and handle.durable_reconciliation_pending
    assert_receipt_storage(f.store, receipt, "produced")
    monkeypatch.setattr(f.store, "acknowledge_cleanup", original)
    result = f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert result.disposition == "validation"
    assert f.store.get_attempt(handle.fence) == result.attempt == retained
    assert f.store.get_run(f.run.run_id) == result.run
    assert not handle.cleanup_pending
    assert not handle.incomplete and not handle.reconciliation_required
    assert not handle.durable_reconciliation_pending
    assert f.calls.count("localstop") == f.calls.count("send") == f.calls.count("prepare") == 1


def test_real_coordinator_completion_observes_validation_and_exact_cleanup(driver, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        parse_contract,
    )

    f = live_coordinator(driver, completion=True)
    handle = f.dispatch()
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        artifacts = GenerationArtifacts(area)
        receipt = artifacts.write(
            handle.fence,
            handle.prepared.registration,
            parse_contract(f.run.contract_json),
            b"scene: synthetic\n",
            {"scene": "synthetic"},
            protect=lambda _: None,
        )
        checked = []
        result = f.coordinator.complete("local", receipt, artifacts, protect=checked.append)
        assert result.disposition == "validation"
        assert (result.run.state, result.run.phase) == ("running", "validation")
        assert result.attempt.receipt == receipt and result.attempt.cleanup == handle.cleanup
        assert f.store.get_attempt(handle.fence) == result.attempt
        assert f.calls.count("send") == f.calls.count("prepare") == f.calls.count("localstop") == 1
        assert f.calls.index("db:commit_generation_receipt") < f.calls.index("localstop")
        assert f.calls.index("localstop") < f.calls.index("db:acknowledge_cleanup")
        again = f.coordinator.complete("local", receipt, artifacts, protect=checked.append)
        assert again == result and len(checked) == 2
        assert f.calls.count("localstop") == f.calls.count("send") == f.calls.count("prepare") == 1


def test_real_coordinator_dispatch_retry_authenticated_cancel_exact_cleanup(driver):
    f = live_coordinator(driver)
    handle = f.dispatch()
    retained = f.store.get_attempt(handle.fence)
    assert retained.registration == handle.prepared.registration and retained.released
    before = f.store.snapshot()
    assert f.dispatch() is handle
    assert f.store.snapshot() == before
    for decision, allowance in [
        ("changed", f.reservation),
        ("decision", f.reservation.model_copy(update={"model_tokens": 101})),
    ]:
        with pytest.raises(ValueError, match="conflicting local dispatch"):
            f.coordinator.dispatch("local", expected_version=1, decision_id=decision, reservation=allowance)
    assert f.calls.count("prepare") == f.calls.count("send") == 1
    with pytest.raises(PermissionError):
        f.coordinator.cancel("stranger")
    assert "localstop" not in f.calls and f.store.snapshot() == before
    f.calls.clear()
    result = f.coordinator.cancel("local")
    assert f.calls[:3] == ["authenticate", "localstop", "db:get_run"]
    assert not result.durable_cancellation_pending and not result.cleanup_pending
    assert f.store.get_run(f.run.run_id).state == "cancelled"
    retained = f.store.get_attempt(handle.fence)
    assert retained.status == "cancelled" and retained.cleanup == handle.cleanup
    assert retained.cleanup.registration == retained.registration == handle.prepared.registration
    assert retained.released and retained.receipt is None
    assert retained.usage_disposition == "fully_reserved_consumption_deferred"
    snapshot = f.store.snapshot()
    assert not f.coordinator.cancel("local").durable_cancellation_pending
    assert f.store.snapshot() == snapshot and f.calls.count("localstop") == 1
    assert [e.kind for e in f.store.events_after(0).events].count("AttemptReleased") == 1


def test_real_coordinator_lease_lost_before_release_never_sends(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        DispatchIncomplete,
    )

    f = live_coordinator(driver, fault="lease_lost")
    with pytest.raises(DispatchIncomplete) as failure:
        f.dispatch()
    handle = failure.value.handle
    retained = f.store.get_attempt(handle.fence)
    assert retained.registration == handle.prepared.registration and not retained.released
    assert "send" not in f.calls and "db:release_attempt" not in f.calls
    assert f.calls.count("localstop") == 1 and handle.cleanup is not None
    assert f.dispatch() is handle and f.calls.count("prepare") == 1
    assert not f.coordinator.cancel("local").durable_cancellation_pending
    assert f.store.get_run(f.run.run_id).state == "cancelled"


@pytest.mark.parametrize("committed", [False, True])
def test_real_coordinator_registration_unknown_preserves_exact_cleanup_obligation(driver, committed):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        DispatchIncomplete,
    )

    f = live_coordinator(driver, fault="registration_after" if committed else "registration_before")
    with pytest.raises(DispatchIncomplete) as failure:
        f.dispatch()
    handle = failure.value.handle
    retained = f.store.get_attempt(handle.fence)
    assert retained.registration == (handle.prepared.registration if committed else None)
    assert not retained.released and retained.cleanup is None
    assert "send" not in f.calls and f.calls.count("localstop") == 1
    assert handle.cleanup.registration == handle.prepared.registration
    assert f.dispatch() is handle and f.calls.count("prepare") == 1
    for _ in range(2):
        result = f.coordinator.cancel("local")
        assert result.durable_cancellation_pending is not committed
        assert not result.cleanup_pending
        retained = f.store.get_attempt(handle.fence)
        assert retained.cleanup == (handle.cleanup if committed else None)
        assert retained.registration == (handle.prepared.registration if committed else None)
        assert f.store.get_run(f.run.run_id).state == ("cancelled" if committed else "cancel_requested")
    assert f.calls.count("db:register_worker") == 1, "must not launder absent registration during cancellation"
    assert f.calls.count("localstop") == 1 and "send" not in f.calls


def test_real_coordinator_send_failure_persists_reconciliation_and_never_resends(
    driver,
):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        DispatchIncomplete,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        ReconciliationReason,
    )

    f = live_coordinator(driver, fault="send_failure")
    with pytest.raises(DispatchIncomplete) as failure:
        f.dispatch()
    handle = failure.value.handle
    assert handle.incomplete and handle.reconciliation_required
    assert not handle.durable_reconciliation_pending
    assert handle.cleanup is not None and not handle.cleanup_pending
    retained = f.store.get_attempt(handle.fence)
    assert retained.released and retained.reconciliation_reason == ReconciliationReason.OWNER_OUTCOME_UNCERTAIN
    assert retained.registration == handle.prepared.registration and retained.receipt is None
    assert f.store.get_run(f.run.run_id).state == "reconciliation_required"
    snapshot = f.store.snapshot()
    assert f.dispatch() is handle and f.store.snapshot() == snapshot
    assert f.calls.count("send") == f.calls.count("prepare") == f.calls.count("localstop") == 1
    assert [e.kind for e in f.store.events_after(0).events].count("ReconciliationRequired") == 1


@pytest.mark.parametrize("fault", ["pre_claim", "claim_ack_unknown"])
def test_real_coordinator_early_failure_retains_recovery_identifiers(driver, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        DispatchIncomplete,
    )

    f = live_coordinator(driver, fault=fault)
    with pytest.raises(DispatchIncomplete) as failure:
        f.dispatch()
    handle = failure.value.handle
    assert handle.incomplete and handle.prepared is None
    assert handle.fence is None and handle.cleanup is None
    assert handle.owner_id == f.coordinator._lease.owner_id
    assert handle.owner_epoch == (f.claimed.owner_epoch if f.claimed else None)
    before = f.store.snapshot()
    calls = list(f.calls)
    assert f.dispatch() is handle
    assert f.calls == calls + ["authenticate"] and f.store.snapshot() == before
    assert "prepare" not in f.calls and "send" not in f.calls
    with driver.session(database=f.store.database) as session:
        rows = list(
            session.run(
                "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "OPTIONAL MATCH (i)-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
                "RETURN i.intent_id AS intent, a.fence_json AS fence",
                **f.store.scope,
            )
        )
    assert len(rows) == 1 and rows[0]["intent"] == f.intent
    assert rows[0]["fence"] == (f.claimed.model_dump_json() if f.claimed else None)
    # A committed claim with lost ACK cannot provide an acknowledged fence, but
    # the known intent/run/owner recovery identifiers must survive the exception.
    retained_intent = handle.fence.intent_id if handle.fence else getattr(handle, "intent_id", None)
    assert retained_intent == f.intent, (
        f"PRODUCT GAP {fault}: durable intent {f.intent!r}, claimed={f.claimed!r}; "
        f"local diagnostic handle loses recovery identifiers: {handle!r}"
    )


def test_real_coordinator_cancel_before_dispatch_is_terminal_without_attempt(driver):
    f = live_coordinator(driver)
    first = f.coordinator.cancel("local")
    second = f.coordinator.cancel("local")
    with pytest.raises(ValueError, match="locally stopped"):
        f.dispatch()
    assert "prepare" not in f.calls and "send" not in f.calls
    with driver.session(database=f.store.database) as session:
        row = session.run(
            "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "RETURN count(i) AS n",
            **f.store.scope,
        ).single(strict=True)
    assert row["n"] == 0
    observed = f.store.get_run(f.run.run_id)
    assert (
        observed.state == "cancelled"
    ), f"PRODUCT GAP: no-attempt cancellation remains {observed.state!r}; first={first!r}, retry={second!r}"
    assert not first.durable_cancellation_pending and not first.cleanup_pending
    assert not second.durable_cancellation_pending and not second.cleanup_pending
    assert observed.phase == "dependency_readiness" and observed.version == 2
    assert f.store.request_cancel(f.run.run_id, 1) == observed
    assert [e.kind for e in f.store.events_after(0).events] == [
        "WorkflowRequested",
        "CancellationRequested",
    ]


def test_real_coordinator_reservation_ack_unknown_retains_command_identity(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        DispatchIncomplete,
    )

    f = live_coordinator(driver, fault="reserve_ack_unknown")
    with pytest.raises(DispatchIncomplete) as failure:
        f.dispatch()
    handle = failure.value.handle
    assert handle.run_id == f.run.run_id and handle.decision_id == "decision"
    assert handle.expected_version == 1 and handle.reservation == f.reservation
    assert handle.intent_id is None and handle.fence is None and handle.prepared is None
    calls = list(f.calls)
    assert f.dispatch() is handle and f.calls == calls + ["authenticate"]
    assert f.intent and f.store.get_run(f.run.run_id).state == "running"
    assert "prepare" not in f.calls and "send" not in f.calls


@pytest.mark.parametrize("round_index", range(3))
def test_pending_cancel_vs_reserve_never_fabricates_cleanup(driver, round_index):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        parse_contract,
    )
    from isaaclab_arena.tests.test_environment_workflow_decisions import authority

    f = live_coordinator(driver)
    s = f.store
    contract = parse_contract(f.run.contract_json)
    auth = authority(s, contract)
    barrier = Barrier(2)

    def work(cancel):
        barrier.wait(timeout=10)
        try:
            if cancel:
                return s.request_cancel(f.run.run_id, 1)
            return s.reserve_generation(
                f.run.run_id,
                1,
                "decision",
                auth,
                f.reservation,
                readiness=readiness(contract, auth),
            )
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancelled, intent = list(pool.map(work, (True, False)))
    observed = s.get_run(f.run.run_id)
    if cancelled is not None:
        assert intent is None and observed.state == "cancelled" and observed.phase == "dependency_readiness"
        assert s.request_cancel(f.run.run_id, 1) == observed
    else:
        assert intent and observed.state == "running"
        observed = s.request_cancel(f.run.run_id, observed.version)
        assert observed.state == "cancel_requested"
        with pytest.raises(ValueError, match="not claimable"):
            s.claim_intent(intent, "owner", s.begin_owner("owner"))
    with driver.session(database=s.database) as session:
        rows = list(
            session.run(
                "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "OPTIONAL MATCH (i)-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
                "RETURN i.intent_id AS intent, i.cleanup_json AS cleanup, a.attempt_id AS attempt",
                **s.scope,
            )
        )
    assert len(rows) == (0 if cancelled is not None else 1)
    assert all(r["cleanup"] is None and r["attempt"] is None for r in rows)
    kinds = [e.kind for e in s.events_after(0).events]
    assert kinds.count("CancellationRequested") == 1
    assert "AttemptCleanupAcknowledged" not in kinds


@pytest.mark.parametrize(
    "case",
    [
        "accept",
        "assessed_deadline",
        "unknown",
        "cancel_before",
        "cancel_during",
        "budget",
        "forbidden",
        "stale",
        "unsupported",
        "readiness",
        "deadline",
        "retire",
        "released_replay",
        "finish_replay",
        "corrupt_original",
        "escape_heavy_history",
        "observe_budget",
        "unbounded",
        "missing_bound_capability",
        "bound_revoked",
        "managed_accept",
        "managed_missing_worker_fence",
        "managed_missing_worker_registration",
        "managed_missing_worker_cleanup",
        "managed_missing_released_at",
        "managed_cancel_prepare",
        "managed_cancel_execute",
        "managed_prepare_unknown",
        "managed_release_ack",
        "managed_timeout",
        "managed_cleanup_failure",
        "managed_missing_ports",
        "managed_binding_cas",
        "managed_readiness_revoked",
        "managed_keyed_cancel_late_unknown",
        "managed_keyed_cancel_unresolved_unknown",
        "managed_resume_claim",
        "managed_resume_version",
        "managed_resume_selection",
        "managed_resume_unsafe",
        "managed_resume_damage_missing_fence",
        "managed_resume_damage_registration",
        "managed_resume_damage_cleanup",
        "managed_resume_damage_release",
        "managed_resume_error_intent",
        "managed_resume_error_profile",
        "managed_resume_error_scalar",
        "policy_pass",
        "policy_distinct_window",
        "policy_fail",
        "policy_empty",
        "policy_partial",
        "policy_unknown",
        "policy_profile_mismatch",
        "policy_candidate_mismatch",
        "policy_budget",
        "policy_cleanup_failure",
        "policy_slot_failure",
        "policy_cancel",
        "policy_deadline",
        "policy_foreign_binding",
        "policy_foreign_seed",
        "policy_duplicate_reset",
        "policy_zero_steps",
        "policy_second_task",
        "policy_v1_unsupported",
        "policy_foreign_intent",
        "policy_retained_tamper",
        "policy_intent_identity_tamper",
        "policy_producer_failure",
        "policy_atomic_rollback",
        "policy_contract_mismatch",
        "policy_seed_mismatch",
        "policy_foreign_candidate",
        "policy_foreign_contract",
        "policy_foreign_policy",
        "policy_foreign_instruction",
        "policy_foreign_task_digest",
        "policy_repair",
        "split_accept",
        "split_cleanup_unknown",
        "split_slot_unknown",
        "split_static_failure",
        "split_repair",
        "split_observe",
        "split_recover_assess",
        "split_tampered_assess",
        "split_cancel_capture",
    ],
)
def test_scene_durable_trace_readback_replay(driver, tmp_path, case):
    """Real Neo4j; synthetic ports/schema receipt, never native acceptance."""
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        GenerationReservation,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )
    from isaaclab_arena.tests.test_environment_workflow_decisions import authority
    from isaaclab_arena.tests.test_environment_workflow_repairs import scene
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import scene_contract

    scene_binding = None
    if case in ("accept", "escape_heavy_history", "forbidden"):
        from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
            ScopeBinding,
        )

        s = Neo4jWorkflowStore(
            driver,
            database=os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"],
            deployment_id="disposable-tests",
            workspace_id=uuid.uuid4().hex,
        )
        scene_binding = ScopeBinding(
            authority_id="synthetic-scene-authority",
            database=s.database,
            **s.scope,
            schema_version=1,
            operational_schema_version=1,
            artifact_marker_schema=1,
            store_id="scene",
            registry_id="scene",
        )
        s.initialize_bound_scope(scene_binding, protect=lambda _: None)
    else:
        s = scoped(driver)
    s.clock = lambda: 100.0
    contract = scene_contract()
    if case.startswith("policy_"):
        from isaaclab_arena.tests.test_environment_workflow_scene_loop import required_policy_contract

        contract = required_policy_contract()
        if case == "policy_distinct_window":
            raw = contract.model_dump(mode="python")
            raw["criteria"][-1]["observation_window"]["end_step"] = 20
            raw["budget"]["max_policy_steps"] = 20
            contract = type(contract).model_validate(raw)
    auth = authority(s, contract)
    run = s.admit("scene-trace", "{}", canonical_json(contract), 1)
    if scene_binding is not None:
        from types import SimpleNamespace

        discovery = WorkflowService(
            Neo4jWorkflowStore(driver, database=s.database, **s.scope),
            SimpleNamespace(require_read=lambda _: None),
            None,
            validate_support=None,
            read_scope=scene_binding,
        )
        bootstrap = discovery.list_runs("local", first=1, protect=lambda _: None)
        discovered_run = bootstrap.runs[0].run_id
        assert discovered_run == run.run_id
        first_watermark = bootstrap.event_watermark
        assert (
            discovery.list_scene_candidates(
                "local", discovered_run, protect=lambda _: None
            ).candidates
            == ()
        )
    intent = s.reserve_generation(
        run.run_id,
        1,
        "generation",
        auth,
        GenerationReservation(
            model_calls=1,
            model_tokens=100,
            cost_ceiling_usd=0.0,
            runtime_allowance_seconds=1.0,
        ),
        readiness=readiness(contract, auth),
    )
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    assert s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    with ArtifactArea.create(tmp_path / "scene", store_id="scene", registry_id="scene") as area:
        artifacts = GenerationArtifacts(area)
        import json

        candidate_source = {"x": "\\" * ((1048576 - 8) // 2)} if case == "escape_heavy_history" else scene()
        receipt = artifacts.write(
            fence,
            reg,
            contract,
            json.dumps(candidate_source).encode(),
            candidate_source,
            protect=lambda _: None,
        )
        s.commit_generation_receipt(fence, artifacts.verify(receipt, protect=lambda _: None))
        s.acknowledge_cleanup(
            fence,
            CleanupEvidence(
                registration=reg,
                evidence_ref="synthetic-stop",
                observation="owned_process_group_stopped",
                remote_effects="unknown",
            ),
        )
        produced = s.get_run_inspection(run.run_id)
        assert produced.scene is None
        assert len(produced.generation_outputs) == 1
        output = produced.generation_outputs[0]
        assert output.attempt_id == fence.attempt_id
        assert output.candidate_json_sha256 == receipt.candidate_json_sha256
        assert output.manifest_sha256 == receipt.manifest_sha256
        assert output.fresh_artifact_verification == "not_performed"
        assert output.disposition == "produced"
        validation = dict(
            disposition="schema_validated",
            fence=fence.model_dump(mode="json"),
            contract_digest=receipt.contract_digest,
            candidate_yaml_sha256=receipt.candidate_yaml_sha256,
            candidate_json_sha256=receipt.candidate_json_sha256,
            provenance_sha256=receipt.provenance_sha256,
            manifest_sha256=receipt.manifest_sha256,
            normalized_spec_sha256="a" * 64,
            validator_identity="explicitly-synthetic-schema-port",
        )
        if case == "escape_heavy_history":
            validation["disposition"] = "invalid_candidate"
        candidate = scene_loop.candidate_record(run.run_id, candidate_source, source_id=fence.attempt_id)
        profile = scene_loop.ScenePortProfile(
            port_id="synthetic-tracer",
            assurance="synthetic",
            producer_ids=tuple(c.evidence_producer for c in contract.criteria),
            observe=scene_loop.SceneReservation(
                model_calls=1,
                model_tokens=100,
                cost_ceiling_usd=0.0,
                runtime_allowance_seconds=1.0,
                realizations=1,
                observations=1,
                steps=10,
            ),
            repair=scene_loop.SceneReservation(
                model_calls=1,
                model_tokens=100,
                cost_ceiling_usd=0.0,
                runtime_allowance_seconds=1.0,
                candidates=1,
                revisions=1,
            ),
        )
        if case.startswith("managed_"):
            profile = scene_loop.ScenePortProfile.model_validate(dict(profile.model_dump(), owned_worker=True))
        if case.startswith(("split_", "policy_")):
            profile = scene_loop.ScenePortProfile(
                codec_version=2,
                port_id="split-native-contract-synthetic-effects",
                assurance="native-unverified",
                owned_worker=True,
                producer_ids=profile.producer_ids,
                capture=scene_loop.SceneReservation(
                    model_calls=0,
                    model_tokens=0,
                    cost_ceiling_usd=0.0,
                    runtime_allowance_seconds=1.0,
                    realizations=1,
                    observations=1,
                    steps=10,
                ),
                assess=scene_loop.SceneReservation(
                    model_calls=1,
                    model_tokens=100,
                    cost_ceiling_usd=0.0,
                    runtime_allowance_seconds=1.0,
                ),
                repair=profile.repair,
            )
        if case.startswith("policy_"):
            from isaaclab_arena.tests.test_environment_workflow_scene_loop import required_policy_profile

            if case == "policy_v1_unsupported":
                profile = scene_loop.ScenePortProfile(
                    port_id="v1-policy-denied",
                    assurance="synthetic",
                    producer_ids=profile.producer_ids,
                    observe=profile.capture,
                    repair=profile.repair,
                )
            else:
                profile = required_policy_profile(
                    profile, contract, candidate, task="navigation" if case == "policy_second_task" else "a2"
                )
                if case == "policy_profile_mismatch":
                    profile = profile.model_copy(update={"policy_criteria": ("0" * 64,)})
                if case in ("policy_contract_mismatch", "policy_seed_mismatch"):
                    update = (
                        {"contract_digest": "0" * 64}
                        if case == "policy_contract_mismatch"
                        else {"seed": contract.execution.seed + 1}
                    )
                    profile = profile.model_copy(
                        update={"policy_binding": profile.policy_binding.model_copy(update=update)}
                    )
                if case == "policy_candidate_mismatch":
                    profile = profile.model_copy(
                        update={
                            "policy_binding": profile.policy_binding.model_copy(update={"candidate_digest": "0" * 64})
                        }
                    )
                if case == "policy_budget":
                    profile = profile.model_copy(
                        update={"policy": profile.policy.model_copy(update={"policy_episodes": 3})}
                    )
        if case == "budget":
            profile = profile.model_copy(
                update={"observe": profile.observe.model_copy(update={"model_tokens": 10001})}
            )
        if case == "unsupported":
            profile = profile.model_copy(update={"producer_ids": ()})

        class ReadAuthority:
            def require_read(self, principal):
                assert principal == "local"

        service = WorkflowService(s, ReadAuthority(), None, validate_support=lambda _: None)
        if case == "corrupt_original":
            (tmp_path / "scene" / receipt.artifact_directory / "candidate.json").write_bytes(b"corrupt")
            with pytest.raises(ValueError):
                service.start_scene(
                    "local",
                    run.run_id,
                    artifacts=artifacts,
                    protect=lambda _: None,
                    validate_generation_candidate=lambda *a, **kw: validation,
                    profile=profile,
                )
            assert s.scene_snapshot(run.run_id) is None
            return
        version = s.get_run(run.run_id).version
        first = service.start_scene(
            "local",
            run.run_id,
            artifacts=artifacts,
            protect=lambda _: None,
            validate_generation_candidate=lambda *a, **kw: validation,
            profile=profile,
        )
        assert s.begin_scene(run.run_id, version, candidate, validation, profile) == first
        assert s.scene_snapshot(run.run_id).candidate == candidate
        if case.startswith("policy_"):
            exercise_policy_scene(case, s, service, run, auth, profile)
            return
        if case.startswith("split_"):
            exercise_split_scene(case, s, service, run, auth, profile)
            return
        if case == "escape_heavy_history":
            compact = service.read_run_inspection("local", run.run_id, protect=lambda _: None)
            assert compact.scene.candidate.candidate_id == candidate.candidate_id
            assert len(compact.model_dump_json()) < 65536
            from isaaclab_arena.agentic_environment_generation.workflow.queries import (
                SceneCandidateView,
                SceneReadScope,
            )

            assert len(candidate.scene_json.encode()) == 1048576
            assert len(candidate.model_dump_json().encode()) > 2 * 1024 * 1024
            expected = SceneCandidateView(
                scope=SceneReadScope(database=s.database, **s.scope), run_id=run.run_id, candidate=candidate
            )
            screened = []
            actual = service.read_scene_candidate("local", candidate.candidate_id, protect=screened.append)
            assert actual == expected
            assert screened == [expected.model_dump(mode="json")]
            page = discovery.list_scene_candidates(
                "local", discovered_run, protect=lambda _: None
            )
            assert [r.candidate_id for r in page.candidates] == [candidate.candidate_id]
            assert len(page.model_dump_json().encode()) < 4096
            assert (
                discovery.read_scene_candidate(
                    "local", page.candidates[0].candidate_id, protect=lambda _: None
                )
                == expected
            )
            assert s.scene_snapshot(run.run_id).decision.reason == "invalid_candidate"
            assert compact.intent.phase == "scene"
            assert compact.scene.evidence_id is None and compact.scene.next_intent_id is None
            from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptRunInspection

            # Keep the valid initial-stop writer fixture; erase only its two
            # selected payloads, not evidence/intent (which were already absent).
            with driver.session(database=s.database) as session:
                session.run(
                    "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, "
                    "run_id:$run}) REMOVE r.scene_candidate, r.scene_decision",
                    **s.scope, run=run.run_id,
                ).consume()
            with pytest.raises(CorruptRunInspection, match="^Invalid retained run inspection$"):
                service.read_run_inspection("local", run.run_id, protect=lambda _: None)
            return

        check_initial_scene_cleanup(service, run.run_id, profile)
        if case.startswith("managed_missing_") and case != "managed_missing_ports":
            from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptCleanupRecord

            scene_id = s.scene_snapshot(run.run_id).intent.intent_id
            claimed = s.claim_scene_worker(run.run_id, scene_id, "owner", fence.owner_epoch)
            view = s.get_run_cleanup(run.run_id)
            item = next(i for i in view.intents if i.intent_id == scene_id)
            assert item.fence == claimed and item.cleanup_state == "unknown"
            query = (
                "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id, "
                "intent_id:$id}) "
            )
            with driver.session(database=s.database) as session:
                original = session.run(query + "RETURN i.scene_json AS scene", **s.scope, id=scene_id).single()["scene"]
                damaged = json.loads(original)
                assert damaged["status"] == "reserved"
                del damaged[case.removeprefix("managed_missing_")]
                raw = json.dumps(damaged)
                assert session.run(query + "SET i.scene_json=$raw RETURN count(i) AS n",
                                   **s.scope, id=scene_id, raw=raw).single()["n"] == 1
                screened = []
                with pytest.raises(CorruptCleanupRecord, match="^Invalid retained cleanup record$"):
                    service.read_run_cleanup("local", run.run_id, protect=screened.append)
                assert screened == []
                assert session.run(query + "RETURN i.scene_json AS scene", **s.scope,
                                   id=scene_id).single()["scene"] == raw
            return
        ports = synthetic_scene_ports(case, s, run, auth)
        ports.profile = profile
        service = WorkflowService(s, ReadAuthority(), None, validate_support=lambda _: None)
        if check_resume_scene_claim(case, s, run, fence) or exercise_scene_worker_case(
            case, s, service, ports, run, fence, reg, auth, contract, receipt
        ):
            return
        if case == "cancel_before":
            s.request_cancel(run.run_id, s.get_run(run.run_id).version)
        if case == "deadline":
            s.clock = lambda: 159.5
        if case == "missing_bound_capability":
            ports.require_bounded_capability = None
        if case in ("readiness", "deadline", "unbounded", "missing_bound_capability"):
            with pytest.raises(ValueError, match="readiness|deadline|bounded"):
                service.run_scene("local", run.run_id, ports=ports)
            assert ports.calls == []
            return
        if case == "released_replay":
            pending = s.scene_snapshot(run.run_id)
            assert s.release_scene(
                run.run_id,
                pending.intent.intent_id,
                auth,
                readiness=readiness(contract, auth),
            )
            assert not s.release_scene(
                run.run_id,
                pending.intent.intent_id,
                auth,
                readiness=readiness(contract, auth),
            )
            final = service.run_scene("local", run.run_id, ports=ports)
            assert final.run.state == "reconciliation_required" and ports.calls == []
            return
        final, joined = run_inspected_scene(driver, s, service, run, ports, case)
        cleanup_view = check_final_scene_cleanup(s, service, run.run_id, profile, ports)
        if case in (
            "managed_timeout",
            "managed_release_ack",
            "managed_cancel_execute",
            "managed_readiness_revoked",
        ):
            assert final == s.scene_snapshot(run.run_id)
            assert final.intent.worker_cleanup is not None
            assert len(ports.prepared) == len(ports.cleaned) == 1
            assert ports.calls == ([] if case in ("managed_release_ack", "managed_readiness_revoked") else ["observe"])
            assert service.run_scene("local", run.run_id, ports=ports) == final
            if case == "managed_cancel_execute":
                assert final.run.state == "cancelled"
                assert s.retire_owner("owner", fence.owner_epoch)
            else:
                assert final.run.state == "reconciliation_required"
                with pytest.raises(ValueError, match="unresolved"):
                    s.retire_owner("owner", fence.owner_epoch)
            return
        if case == "bound_revoked":
            assert final.run.state == "reconciliation_required"
            assert final.intent.status == "reconciliation_required" and ports.calls == []
            return
        if case == "observe_budget":
            assert final.run.state == "stopped" and final.decision.reason == "budget_exhausted"
            assert ports.calls == ["observe"] * 4
            from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptSceneRecord

            events = [e for e in s.events_after(0).events if e.kind == "SceneDecisionRecorded"]
            earlier = service.read_scene_decision("local", events[0].source_id, protect=lambda _: None)
            later = service.read_scene_decision("local", events[1].source_id, protect=lambda _: None)
            assert earlier.candidate_id == later.candidate_id
            assert earlier.decision.action == later.decision.action == "observe"
            assert earlier.next_intent_id != later.next_intent_id
            screened = []
            with driver.session(database=s.database) as session:
                query = (
                    "MATCH (n:ArenaWorkflowDecision {deployment_id:$deployment_id, workspace_id:$workspace_id,"
                    " decision_id:$id}) SET n.intent_id=$intent"
                )
                session.run(query, **s.scope, id=earlier.decision_id, intent=later.next_intent_id).consume()
                try:
                    with pytest.raises(CorruptSceneRecord):
                        service.read_scene_decision("local", earlier.decision_id, protect=screened.append)
                    assert not screened
                finally:
                    session.run(query, **s.scope, id=earlier.decision_id, intent=earlier.next_intent_id).consume()
                session.run(query, **s.scope, id=earlier.decision_id, intent=None).consume()
                try:
                    assert service.read_scene_decision(
                        "local", earlier.decision_id, protect=lambda _: None
                    ).next_intent_id is None
                finally:
                    session.run(query, **s.scope, id=earlier.decision_id, intent=earlier.next_intent_id).consume()
            assert service.read_scene_decision("local", earlier.decision_id, protect=lambda _: None) == earlier
            return
        if case == "finish_replay":
            result = scene_loop.SceneResult(observation=ports.last_observation)
            assert not s.finish_scene(run.run_id, ports.last_intent.intent_id, 1, result)
            with pytest.raises(ValueError, match="conflicting"):
                s.finish_scene(
                    run.run_id,
                    ports.last_intent.intent_id,
                    1,
                    scene_loop.SceneResult(failure="invalid_candidate"),
                )
        if case in ("unknown", "cancel_during"):
            assert final.run.state == ("reconciliation_required" if case == "unknown" else "cancel_requested")
            assert final.intent.status == "reconciliation_required"
            assert ports.calls == ["observe"]
            assert service.run_scene("local", run.run_id, ports=ports) == final
            with pytest.raises(ValueError, match="unresolved"):
                s.retire_owner("owner", fence.owner_epoch)
            return
        if case == "cancel_before":
            assert final.run.state == "cancelled" and ports.calls == []
            return
        if case in ("budget", "forbidden", "stale", "unsupported", "assessed_deadline"):
            assert final.run.state == "stopped"
            assert (
                final.decision.reason
                == {
                    "budget": "budget_exhausted",
                    "assessed_deadline": "budget_exhausted",
                    "forbidden": "repair_rejected",
                    "stale": "stale_cohort",
                    "unsupported": "unsupported_criterion",
                }[case]
            )
            assert (
                len(ports.calls)
                == {"budget": 0, "unsupported": 0, "forbidden": 2, "stale": 3, "assessed_deadline": 3}[case]
            )
            if case == "forbidden":
                page = discovery.list_scene_candidates(
                    "local", discovered_run, protect=lambda _: None
                )
                assert [r.candidate_id for r in page.candidates] == [
                    candidate.candidate_id
                ]
                assert (
                    not page.has_more
                )  # Rejected, unadopted repair proposals are not candidates.
            if case == "stale":
                event = [e for e in s.events_after(0).events if e.kind == "SceneDecisionRecorded"][-1]
                decision = service.read_scene_decision("local", event.source_id, protect=lambda _: None)
                observation = service.read_scene_evidence("local", decision.evidence_id, protect=lambda _: None)
                assert decision.selected_assessment_id is None
                assert observation.candidate_id is None  # The writer retained no link for this diagnostic cohort.
                assert observation.observation == ports.last_observation
            return
        assert final.run.state == "accepted" and final.decision.action == "accept"
        if case == "managed_accept":
            assert len(ports.prepared) == len(ports.cleaned) == 3
            for scene_id in ports.prepared:
                retained_scene = s.get_scene_intent(run.run_id, scene_id)
                assert retained_scene.status == "produced"
                assert retained_scene.worker_cleanup.registration == retained_scene.worker_registration
            assert s.retire_owner("owner", fence.owner_epoch)
            s.begin_owner("replacement-scene-owner")
            assert s.get_scene_intent(run.run_id, ports.prepared[-1]) == retained_scene
            assert s.get_generation_attempt(run.run_id).receipt == receipt
            historical_cleanup = service.read_run_cleanup("local", run.run_id, protect=lambda _: None)
            assert len(historical_cleanup.intents) == 4
            assert all(i.cleanup_state == "recorded" and i.retired_owner.owner_epoch == 1
                       for i in historical_cleanup.intents)
            assert historical_cleanup.current_scope_owner.owner_id == "replacement-scene-owner"
            assert historical_cleanup.projection_revision != cleanup_view.projection_revision
            replacement = s.get_run_inspection(run.run_id)
            assert replacement.retained_revision != joined.retained_revision
            assert all(i.cleanup_state == "recorded" for i in replacement.cleanup.intents)
            assert replacement.cleanup.current_scope_owner.dirty
            check_cleanup_scene_corruption(driver, s, run.run_id, ports.prepared[0])
        if case == "retire":
            assert s.retire_owner("owner", fence.owner_epoch)
            assert s.get_owner().dirty is False
        assert ports.calls == ["observe", "repair", "observe"]
        assert final.candidate.parent_id == candidate.candidate_id
        assert final.candidate.original_id == candidate.candidate_id
        historical = [e for e in s.events_after(0).events if e.kind == "SceneDecisionRecorded"]
        assert all(hasattr(e, "source_id") for e in historical), "decision events must retain their own sources"
        assert len(historical) == len({e.source_id for e in historical}) == 4
        fresh = Neo4jWorkflowStore(driver, database=s.database, **s.scope)
        reader = WorkflowService(fresh, ReadAuthority(), None, validate_support=None)
        if case == "accept":
            reader = discovery
            check_joined_candidate_discovery(
                reader, discovered_run, first_watermark, candidate, final.candidate
            )
            page = reader.read_scope_events(
                "local", first=1000, after=first_watermark, protect=lambda _: None
            )
            historical = [
                e
                for e in page.events
                if e.run_id == discovered_run and e.kind == "SceneDecisionRecorded"
            ]
            assert len(historical) == 4
            check_joined_decision_discovery(reader, discovered_run, historical)
        before = (s.snapshot(), s.events_after(0), s.result_records(run.run_id))
        protected = []

        def protect(value):
            protected.append(value)

        decisions = [reader.read_scene_decision("local", e.source_id, protect=protect) for e in historical]
        assert [d.decision.action for d in decisions] == ["observe", "repair", "observe", "accept"]
        assert [d.candidate_id for d in decisions] == [
            candidate.candidate_id,
            candidate.candidate_id,
            final.candidate.candidate_id,
            final.candidate.candidate_id,
        ]
        assert decisions[0].selected_assessment_id is None and decisions[0].evidence_id is None
        assert decisions[1].next_intent_id is not None and decisions[-1].next_intent_id is None
        for decision in decisions[:-1]:
            assert decision.next_intent_id == scene_loop.identity(
                decision.decision_id, "intent"
            )
        assessments = [
            reader.read_scene_assessment("local", d.selected_assessment_id, protect=protect)
            for d in (decisions[1], decisions[-1])
        ]
        assert [a.assessment.status for a in assessments] == ["not_established", "established"]
        assert assessments[0].assessment_id != assessments[1].assessment_id
        observations = [reader.read_scene_evidence("local", a.evidence_id, protect=protect) for a in assessments]
        assert [e.evidence_id for e in observations] == [decisions[1].evidence_id, decisions[-1].evidence_id]
        assert observations[0].observation.cohort != observations[1].observation.cohort
        parents = [reader.read_scene_candidate("local", e.candidate_id, protect=protect) for e in observations]
        assert parents[0].candidate == candidate and parents[1].candidate == final.candidate
        child = parents[1].candidate
        assert reader.read_scene_candidate("local", child.parent_id, protect=protect) == parents[0]
        assert reader.read_scene_candidate("local", child.original_id, protect=protect) == parents[0]
        for view in [*decisions, *assessments, *observations, *parents]:
            assert view.run_id == run.run_id
            assert view.scope.database == s.database
            assert view.scope.deployment_id == s.scope["deployment_id"]
            assert view.scope.workspace_id == s.scope["workspace_id"]
        assert reader.read_scene_decision("local", "generation", protect=protect) is None
        foreign = WorkflowService(
            Neo4jWorkflowStore(driver, database=s.database, **dict(s.scope, workspace_id="foreign")),
            ReadAuthority(),
            None,
            validate_support=None,
        )
        for kind, record_id in (
            ("candidate", child.candidate_id),
            ("decision", decisions[1].decision_id),
            ("assessment", assessments[0].assessment_id),
            ("evidence", observations[0].evidence_id),
        ):
            assert getattr(reader, "read_scene_" + kind)("local", "f" * 64, protect=protect) is None
            assert getattr(foreign, "read_scene_" + kind)("local", record_id, protect=protect) is None
        assert protected
        assert (s.snapshot(), s.events_after(0), s.result_records(run.run_id)) == before
        if case == "accept":
            check_historical_scene_corruption(driver, s, reader, decisions, assessments, observations, parents)
        assert scoped(driver, workspace=s.scope["workspace_id"]).scene_snapshot(run.run_id) == final
        assert service.run_scene("local", run.run_id, ports=ports) == final
        assert ports.calls == ["observe", "repair", "observe"]
        assert s.get_generation_attempt(run.run_id).receipt == receipt
        assert (
            service.start_scene(
                "local",
                run.run_id,
                artifacts=artifacts,
                protect=lambda _: None,
                validate_generation_candidate=lambda *a, **kw: validation,
                profile=profile,
            )
            == first
        )
        if case == "accept":
            with driver.session(database=s.database) as session:
                query = "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run})-[:HAS_DECISION]->(d) "
                session.run(
                    query + "REMOVE r.decision_coverage, d.run_id, d.record_kind, d.membership_codec",
                    **s.scope,
                    run=run.run_id,
                ).consume()
                original_rows = session.run(
                    query + "RETURN properties(d) AS d ORDER BY d.decision_id", **s.scope, run=run.run_id
                ).data()
                assert (
                    service.start_scene(
                        "local",
                        run.run_id,
                        artifacts=artifacts,
                        protect=lambda _: None,
                        validate_generation_candidate=lambda *a, **kw: validation,
                        profile=profile,
                    )
                    == first
                )
                assert (
                    session.run(
                        query + "RETURN properties(d) AS d ORDER BY d.decision_id", **s.scope, run=run.run_id
                    ).data()
                    == original_rows
                )
                assert (
                    reader.list_decisions("local", run.run_id, protect=lambda _: None).reason
                    == "coverage_provenance_unavailable"
                )
                assert (
                    reader.read_scene_decision("local", decisions[-1].decision_id, protect=lambda _: None)
                    == decisions[-1]
                )
        with driver.session(database=s.database) as session:
            row = session.run(
                "MATCH (child:ArenaWorkflowCandidate {record_id:$child})-[:DERIVED_FROM]->"
                "(original:ArenaWorkflowCandidate {record_id:$original}) "
                "MATCH (e:ArenaWorkflowEvidence)-[:FOR_CANDIDATE]->(child) "
                "MATCH (a:ArenaCriterionAssessment)-[:ASSESSES]->(e) RETURN count(a) AS n",
                child=final.candidate.candidate_id,
                original=candidate.candidate_id,
            ).single()
            assert row["n"] == 1


def check_resume_scene_claim(case, s, run, fence):
    """Actual claim transaction; no selected worker is prepared or cleaned up."""
    if not case.startswith("managed_resume_"):
        return False
    import inspect

    snapshot = s.scene_snapshot(run.run_id)
    selected = snapshot.intent
    preview = s.preview_resume(run.run_id)
    assert preview.selection is not None and preview.selection.branch == "scene", "scene selection missing"
    if case.startswith("managed_resume_error_"):
        import json
        import traceback
        from types import SimpleNamespace

        from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

        admission = s.admit_resume(
            "before-error",
            dict(runId=run.run_id, expectedVersion=snapshot.run.version, renewAuthorization=False),
            selection=preview.selection,
            eligibility="current",
            protect=lambda v: None,
        )
        secret = "private-retained-scene-sentinel"
        profile_error = case.endswith("profile")
        label, field = (
            ("ArenaWorkflowRun", "scene_profile") if profile_error else ("ArenaExecutionIntent", "scene_json")
        )
        query = "MATCH (n:" + label + " {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
        if not profile_error:
            query += "WHERE n.intent_id=$id "
        with s.driver.session(database=s.database) as session:
            raw = session.run(query + "RETURN n." + field + " AS raw", **s.scope, id=selected.intent_id).single()["raw"]
            body = json.loads(raw)
            body["owned_worker" if profile_error else "status"] = secret
            raw = json.dumps(secret) if case.endswith("scalar") else json.dumps(body)
            session.run(query + "SET n." + field + "=$raw", **s.scope, id=selected.intent_id, raw=raw).consume()
        calls = []
        service = WorkflowService(s, SimpleNamespace(require_read=lambda p: None), None, validate_support=None)
        for operation in (
            lambda: s.preview_resume(run.run_id),
            lambda: service.admit_resume(
                "reader",
                "scene-error",
                dict(runId=run.run_id, expectedVersion=admission.receipt.after_version, renewAuthorization=False),
                check_resume=lambda *a: calls.append("permission"),
                check_eligibility=lambda *a, **kw: calls.append("eligibility"),
                protect=lambda v: None,
            ),
            lambda: s.claim_scene_worker(
                run.run_id, selected.intent_id, "owner", fence.owner_epoch, resume_operation_id="before-error"
            ),
        ):
            with pytest.raises(ValueError) as caught:
                operation()
            assert str(caught.value) == "Invalid retained resume selection"
            assert secret not in "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
        assert calls == []
        assert s.get_resume_receipt("before-error") == admission.receipt
        assert s.get_resume_receipt("scene-error") is None
        with s.driver.session(database=s.database) as session:
            assert (
                session.run(query + "RETURN n." + field + " AS raw", **s.scope, id=selected.intent_id).single()["raw"]
                == raw
            )
        return True
    if case.startswith("managed_resume_damage_"):
        import json

        damage = case.removeprefix("managed_resume_damage_")
        if damage == "missing_fence":
            claimed = s.claim_scene_worker(run.run_id, selected.intent_id, "owner", fence.owner_epoch)
            assert s.get_scene_intent(run.run_id, selected.intent_id).worker_fence == claimed
        else:
            # A valid admission followed by contradictory metadata must also fail
            # the pinned claim without depending on a changed version.
            admitted = s.admit_resume(
                "before-damage",
                dict(runId=run.run_id, expectedVersion=snapshot.run.version, renewAuthorization=False),
                selection=preview.selection,
                eligibility="current",
                protect=lambda v: None,
            )
            assert admitted.receipt.disposition == "continuation_admitted"
        query = (
            "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "WHERE i.intent_id=$id "
        )
        with s.driver.session(database=s.database) as session:
            original = session.run(query + "RETURN i.scene_json AS raw", **s.scope, id=selected.intent_id).single()[
                "raw"
            ]
            body = json.loads(original)
            assert body["status"] == "reserved"
            if damage == "missing_fence":
                del body["worker_fence"]
            else:
                body[
                    {"registration": "worker_registration", "cleanup": "worker_cleanup", "release": "released_at"}[
                        damage
                    ]
                ] = (
                    100.0
                    if damage == "release"
                    else (
                        registration(fence).model_dump(mode="json")
                        if damage == "registration"
                        else dict(
                            registration=registration(fence).model_dump(mode="json"),
                            evidence_ref="retained-stop",
                            observation="owned_process_group_stopped",
                            remote_effects="unknown",
                        )
                    )
                )
            raw = json.dumps(body)
            session.run(query + "SET i.scene_json=$raw", **s.scope, id=selected.intent_id, raw=raw).consume()
        before = s.snapshot()
        favorable = []
        try:
            damaged = s.preview_resume(run.run_id)
            favorable.append(damaged.selection is not None)
            result = s.admit_resume(
                "after-damage",
                dict(runId=run.run_id, expectedVersion=s.get_run(run.run_id).version, renewAuthorization=False),
                selection=damaged.selection,
                eligibility="current",
                protect=lambda v: None,
            )
            favorable.append(result.receipt.disposition == "continuation_admitted")
            if result.receipt.disposition == "continuation_admitted":
                s.claim_scene_worker(
                    run.run_id, selected.intent_id, "owner", fence.owner_epoch, resume_operation_id="after-damage"
                )
                favorable.append(True)
        except ValueError:
            pass
        if damage != "missing_fence":
            with pytest.raises(ValueError):
                s.claim_scene_worker(
                    run.run_id, selected.intent_id, "owner", fence.owner_epoch, resume_operation_id="before-damage"
                )
        assert not any(favorable), favorable
        assert s.snapshot() == before
        with s.driver.session(database=s.database) as session:
            assert (
                session.run(query + "RETURN i.scene_json AS raw", **s.scope, id=selected.intent_id).single()["raw"]
                == raw
            )
        return True
    if case == "managed_resume_unsafe":
        s.claim_scene_worker(run.run_id, selected.intent_id, "owner", fence.owner_epoch)
        preview = s.preview_resume(run.run_id)
        result = s.admit_resume(
            "scene-pin",
            dict(runId=run.run_id, expectedVersion=s.get_run(run.run_id).version, renewAuthorization=False),
            selection=preview.selection,
            eligibility="current",
            protect=lambda v: None,
        )
        assert result.receipt.disposition == "refused" and result.receipt.reason == "unsafe_scene"
        assert not result.receipt.events
        return True
    result = s.admit_resume(
        "scene-pin",
        dict(runId=run.run_id, expectedVersion=snapshot.run.version, renewAuthorization=False),
        selection=preview.selection,
        eligibility="current",
        protect=lambda v: None,
    )
    assert result.receipt.disposition == "continuation_admitted"
    assert result.receipt.selection.intent_id == selected.intent_id
    assert "resume_operation_id" in inspect.signature(s.claim_scene_worker).parameters
    if case != "managed_resume_claim":
        with s.driver.session(database=s.database) as session:
            # Adversarial next-selection change without version advancement must
            # still block the old admitted intent; this is not a new reservation.
            if case == "managed_resume_selection":
                replacement = selected.model_copy(update={"intent_id": "f" * 64})
                session.run(
                    "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                    "WHERE i.intent_id=$old CREATE (j:ArenaExecutionIntent) SET j=properties(i), "
                    "j.intent_id=$next, j.scene_json=$raw",
                    **s.scope,
                    old=selected.intent_id,
                    next=replacement.intent_id,
                    raw=replacement.model_dump_json(),
                ).consume()
            update = "SET r.version=r.version+1" if case == "managed_resume_version" else "SET r.scene_intent=$next"
            session.run(
                "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) " + update,
                **s.scope,
                next="f" * 64,
            ).consume()
        before = s.snapshot()
        with pytest.raises(ValueError, match="[Rr]esume"):
            s.claim_scene_worker(
                run.run_id, selected.intent_id, "owner", fence.owner_epoch, resume_operation_id="scene-pin"
            )
        assert s.snapshot() == before
        assert s.get_scene_intent(run.run_id, selected.intent_id).worker_fence is None
        if case == "managed_resume_selection":
            assert s.get_scene_intent(run.run_id, "f" * 64).worker_fence is None
    else:
        claimed = s.claim_scene_worker(
            run.run_id, selected.intent_id, "owner", fence.owner_epoch, resume_operation_id="scene-pin"
        )
        assert claimed.intent_id == selected.intent_id
        assert s.get_scene_intent(run.run_id, selected.intent_id).reservation == selected.reservation
    assert s.get_resume_receipt("scene-pin") == result.receipt
    # No synthetic cleanup of the selected worker: none was prepared.
    return True


def check_initial_scene_cleanup(service, run_id, profile):
    initial_cleanup = service.read_run_cleanup("local", run_id, protect=lambda _: None)
    assert [i.cleanup_state for i in initial_cleanup.intents if i.kind == "generation"] == ["recorded"]
    pending_cleanup = [i for i in initial_cleanup.intents if i.kind == "scene"]
    if pending_cleanup:
        assert len(pending_cleanup) == 1
        assert pending_cleanup[0].cleanup_state == ("not_started" if profile.owned_worker else "not_applicable")
        assert pending_cleanup[0].release_state == "known_unreleased"


def check_final_scene_cleanup(store, service, run_id, profile, ports):
    view = service.read_run_cleanup("local", run_id, protect=lambda _: None)
    scene_cleanup = [i for i in view.intents if i.kind == "scene"]
    if profile.owned_worker:
        assert {i.intent_id for i in scene_cleanup} == set(ports.prepared)
        assert all(i.cleanup_state == "recorded" for i in scene_cleanup)
        for item in scene_cleanup:
            retained = store.get_scene_intent(run_id, item.intent_id)
            assert item.fence == retained.worker_fence
            assert item.registration_id == retained.worker_registration.registration_id
            assert item.cleanup_evidence_ref == retained.worker_cleanup.evidence_ref
    else:
        assert all(i.cleanup_state == "not_applicable" for i in scene_cleanup)
    return view


def check_cleanup_scene_corruption(driver, store, run_id, intent_id):
    import json

    from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptCleanupRecord

    query = (
        "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run})"
        "-[:HAS_SCENE_INTENT]->(i {intent_id:$intent}) "
    )
    before = store.get_run_cleanup(run_id)
    with driver.session(database=store.database) as session:
        retained = session.run(
            query + "RETURN r.scene_profile AS profile, i.scene_json AS scene",
            **store.scope,
            run=run_id,
            intent=intent_id,
        ).single()
        for damage in (
            "profile_missing",
            "profile_implicit",
            "profile_bool",
            "profile_inline",
            "fence",
            "registration",
            "cleanup",
            "missing_worker",
            "released_at",
            "status",
            "mirror",
        ):
            profile, scene = json.loads(retained["profile"]), json.loads(retained["scene"])
            extra = None
            if damage == "profile_missing":
                profile = None
            elif damage == "profile_implicit":
                profile.pop("owned_worker")
            elif damage == "profile_bool":
                profile["owned_worker"] = "true"
            elif damage == "profile_inline":
                profile["owned_worker"] = False
            elif damage == "fence":
                scene["worker_fence"]["owner_epoch"] = 999
            elif damage == "registration":
                scene["worker_registration"]["pid"] = 999
            elif damage == "cleanup":
                scene["worker_cleanup"]["registration"]["fence"]["intent_id"] = "foreign"
            elif damage == "missing_worker":
                scene.update(worker_fence=None, worker_registration=None, worker_cleanup=None, released_at=None)
            elif damage == "released_at":
                scene["released_at"] = True
            elif damage == "status":
                scene["status"] = "reserved"
            else:
                extra = "private-sentinel"
            session.run(
                query + "SET r.scene_profile=$profile, i.scene_json=$scene, i.cleanup_json=$extra",
                **store.scope,
                run=run_id,
                intent=intent_id,
                profile=None if profile is None else json.dumps(profile),
                scene=json.dumps(scene),
                extra=extra,
            ).consume()
            try:
                with pytest.raises(CorruptCleanupRecord):
                    store.get_run_cleanup(run_id)
            finally:
                session.run(
                    query + "SET r.scene_profile=$profile, i.scene_json=$scene REMOVE i.cleanup_json",
                    **store.scope,
                    run=run_id,
                    intent=intent_id,
                    **dict(retained),
                ).consume()
        assert store.get_run_cleanup(run_id) == before


def check_historical_scene_corruption(driver, store, reader, decisions, assessments, evidence, candidates):
    """Inject damage only for negative setup; all historical reads use the application."""
    from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptSceneRecord

    labels = dict(
        candidate="ArenaWorkflowCandidate",
        decision="ArenaWorkflowDecision",
        assessment="ArenaCriterionAssessment",
        evidence="ArenaWorkflowEvidence",
    )
    ids = dict(
        candidate=candidates[1].candidate.candidate_id,
        decision=decisions[1].decision_id,
        assessment=assessments[0].assessment_id,
        evidence=evidence[0].evidence_id,
    )

    def write(query, **params):
        with driver.session(database=store.database) as session:
            session.run(query, **store.scope, **params).consume()

    def match(kind):
        field = "decision_id" if kind == "decision" else "record_id"
        return (
            "MATCH (n:"
            + labels[kind]
            + " {deployment_id:$deployment_id, workspace_id:$workspace_id}) WHERE n."
            + field
            + "=$id "
        )

    def read(kind):
        return getattr(reader, "read_scene_" + kind)("local", ids[kind], protect=lambda _: None)

    before = (store.snapshot(), store.events_after(0), store.result_records(decisions[0].run_id))
    # Root ambiguity, including duplicate equal payloads, must never pick a row.
    for kind in labels:
        write(
            match(kind) + "CREATE (copy:" + labels[kind] + ") SET copy=properties(n), copy.history_fault=true",
            id=ids[kind],
        )
        try:
            with pytest.raises(CorruptSceneRecord):
                read(kind)
        finally:
            write(
                "MATCH (n {deployment_id:$deployment_id, workspace_id:$workspace_id, history_fault:true}) DETACH"
                " DELETE n"
            )

    # Damaged retained codecs must not disclose raw keys or model inputs, even
    # through formatted exception chaining, before public protection is reached.
    import traceback

    run_query = (
        "MATCH (n:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id,"
        " run_id:$id}) "
    )
    original_contract = store.get_run(evidence[0].run_id).contract_json
    for damaged in ('{"private-sentinel":1,"private-sentinel":2}', '{"private-sentinel":1}'):
        write(run_query + "SET n.contract_json=$value", id=evidence[0].run_id, value=damaged)
        screened = []
        try:
            with pytest.raises(CorruptSceneRecord) as caught:
                reader.read_scene_evidence("local", ids["evidence"], protect=screened.append)
            assert "private-sentinel" not in str(caught.value)
            assert "private-sentinel" not in "".join(traceback.format_exception(caught.value))
            assert not screened
        finally:
            write(run_query + "SET n.contract_json=$value", id=evidence[0].run_id, value=original_contract)
    assert read("evidence") == evidence[0]

    # Scalar/payload inconsistencies and oversize retained bytes fail closed.
    faults = [
        ("decision", "run_id", "other-run", None),
        ("candidate", "run_id", "other-run", candidates[1].run_id),
        ("evidence", "run_id", "other-run", evidence[0].run_id),
        ("assessment", "run_id", "other-run", assessments[0].run_id),
        ("candidate", "payload", candidates[0].candidate.model_dump_json(), candidates[1].candidate.model_dump_json()),
        ("decision", "payload", decisions[-1].decision.model_dump_json(), decisions[1].decision.model_dump_json()),
        ("evidence", "payload", "x" * (2 * 1024 * 1024 + 1), evidence[0].observation.model_dump_json()),
        (
            "assessment",
            "payload",
            assessments[-1].assessment.model_dump_json(),
            assessments[0].assessment.model_dump_json(),
        ),
        ("decision", "evidence_id", "f" * 64, decisions[1].evidence_id),
        ("decision", "intent_id", "f" * 64, decisions[1].next_intent_id),
        ("decision", "candidate_id", "f" * 64, decisions[1].candidate_id),
    ]
    missed = []
    for kind, field, bad, original in faults:
        write(match(kind) + "SET n." + field + "=$value", id=ids[kind], value=bad)
        try:
            try:
                read(kind)
            except CorruptSceneRecord:
                pass
            else:
                missed.append((kind, field))
        finally:
            write(match(kind) + "SET n." + field + "=$value", id=ids[kind], value=original)
    assert not missed, missed

    # Do not hide extra same-endpoint, wrong-label or foreign-scope edges through
    # label/scope filters or DISTINCT. Removal restores the original graph.
    for kind, relation, incoming in (
        ("candidate", "DERIVED_FROM", False),
        ("candidate", "ORIGINAL", False),
        ("evidence", "FOR_CANDIDATE", False),
        ("assessment", "ASSESSES", False),
        ("decision", "HAS_DECISION", True),
        ("candidate", "HAS_SCENE_RECORD", True),
    ):
        pattern = "(n)<-[:" + relation + "]-(target)" if incoming else "(n)-[:" + relation + "]->(target)"
        duplicate = (
            "(n)<-[:" + relation + " {history_fault:true}]-(target)"
            if incoming
            else "(n)-[:" + relation + " {history_fault:true}]->(target)"
        )
        write(match(kind) + "MATCH " + pattern + " CREATE " + duplicate, id=ids[kind])
        try:
            with pytest.raises(CorruptSceneRecord):
                read(kind)
        finally:
            write("MATCH ()-[r {history_fault:true}]->() DELETE r")

    # Replace an edge with a valid same-run but wrong candidate. Matching scope
    # alone must not relabel failed-parent evidence as evidence of the child.
    for replacement in (None, candidates[1].candidate.candidate_id):
        write(match("evidence") + "MATCH (n)-[r:FOR_CANDIDATE]->() DELETE r", id=ids["evidence"])
        if replacement is not None:
            write(
                match("evidence")
                + "MATCH (c:ArenaWorkflowCandidate {deployment_id:$deployment_id, workspace_id:$workspace_id,"
                " record_id:$candidate}) CREATE (n)-[:FOR_CANDIDATE]->(c)",
                id=ids["evidence"],
                candidate=replacement,
            )
        try:
            with pytest.raises(CorruptSceneRecord):
                read("evidence")
        finally:
            write(match("evidence") + "OPTIONAL MATCH (n)-[r:FOR_CANDIDATE]->() DELETE r", id=ids["evidence"])
            write(
                match("evidence")
                + "MATCH (c:ArenaWorkflowCandidate {deployment_id:$deployment_id, workspace_id:$workspace_id,"
                " record_id:$candidate}) CREATE (n)-[:FOR_CANDIDATE]->(c)",
                id=ids["evidence"],
                candidate=candidates[0].candidate.candidate_id,
            )

    for damage in ("foreign_scope", "wrong_label"):
        write(
            match("evidence")
            + "MATCH (n)-[r:FOR_CANDIDATE]->(c) DELETE r "
            "CREATE (copy:ArenaWorkflowCandidate) SET copy=properties(c), copy.history_fault=true "
            "CREATE (n)-[:FOR_CANDIDATE]->(copy) "
            + (
                "SET copy.workspace_id='foreign'" if damage == "foreign_scope" else "REMOVE copy:ArenaWorkflowCandidate"
            ),
            id=ids["evidence"],
        )
        try:
            with pytest.raises(CorruptSceneRecord):
                read("evidence")
        finally:
            write("MATCH (n {deployment_id:$deployment_id, history_fault:true}) DETACH DELETE n")
            write(
                match("evidence")
                + "MATCH (c:ArenaWorkflowCandidate {deployment_id:$deployment_id, workspace_id:$workspace_id,"
                " record_id:$candidate}) CREATE (n)-[:FOR_CANDIDATE]->(c)",
                id=ids["evidence"],
                candidate=candidates[0].candidate.candidate_id,
            )

    # Losing a recorded assessment edge is corrupt, not a guessed replacement.
    query = match("assessment") + "MATCH (n)-[r:ASSESSES]->(e) "
    write(query + "DELETE r", id=ids["assessment"])
    try:
        with pytest.raises(CorruptSceneRecord):
            read("decision")
        with pytest.raises(CorruptSceneRecord):
            read("assessment")
    finally:
        write(
            match("assessment")
            + "MATCH (e:ArenaWorkflowEvidence {deployment_id:$deployment_id, workspace_id:$workspace_id,"
            " record_id:$evidence}) CREATE (n)-[:ASSESSES]->(e)",
            id=ids["assessment"],
            evidence=ids["evidence"],
        )

    # Legacy selection absence stays explicitly unavailable, even with a summary.
    write(match("decision") + "REMOVE n.evidence_id", id=ids["decision"])
    try:
        legacy = read("decision")
        assert legacy.evidence_id is None and legacy.selected_assessment_id is None
        assert legacy.decision.assessment == decisions[1].decision.assessment
    finally:
        write(match("decision") + "SET n.evidence_id=$evidence", id=ids["decision"], evidence=ids["evidence"])
    assert (store.snapshot(), store.events_after(0), store.result_records(decisions[0].run_id)) == before


def run_inspected_scene(driver, s, service, run, ports, case):
    if case == "accept":
        final, racing = joined_scene_writer_race(driver, s, service, run.run_id, ports)
    else:
        final = service.run_scene("local", run.run_id, ports=ports)
    joined = service.read_run_inspection("local", run.run_id, protect=lambda _: None)
    if case == "accept":
        assert racing == joined
    assert joined.scene.candidate.candidate_id == final.candidate.candidate_id
    assert joined.scene.candidate.source_id == final.candidate.source_id
    assert "scene_json" not in joined.scene.candidate.model_dump()
    assert joined.scene.action == final.decision.action
    assert joined.scene.reason == final.decision.reason
    latest = [e for e in s.events_after(0).events if e.kind == "SceneDecisionRecorded"][-1]
    assert joined.scene.decision_id == latest.source_id
    assert joined.scene.assessment == final.decision.assessment
    assert joined.scene.acceptance == ("accepted" if final.decision.action == "accept" else "not_established")
    assert joined.scene.assessment_status == (
        final.decision.assessment.status if final.decision.assessment is not None else "not_assessed"
    )
    if case == "stale":
        assert joined.scene.evidence_id is not None
        assert joined.scene.selected_assessed is False
        assert not any(c.verdict == "established" for c in joined.scene.criteria)
    if final.decision.action == "accept":
        assert joined.scene.selected_assessed
        assert all(c.verdict == "established" for c in joined.scene.criteria if c.requirement == "required")
    if case == "assessed_deadline":
        assert final.run.state == "stopped" and joined.scene.reason == "budget_exhausted"
        assert joined.scene.assessment_status == "established" and joined.scene.selected_assessed
        assert joined.scene.acceptance == "not_established"
        assert all(c.verdict == "established" for c in joined.scene.criteria)
    if case == "accept":
        check_joined_query_faults(
            driver, s, run.run_id, ["AS scene LIMIT", "AS source,", "WHERE n.record_id=", "MATCH (root)"]
        )
        check_joined_private_corruption(driver, s, run.run_id, joined)
        check_joined_causality(driver, s, run.run_id, joined)
    return final, joined


def check_joined_private_corruption(driver, store, run_id, expected):
    import json
    import traceback

    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown
    from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptRunInspection

    secret = "private-joined-retained-sentinel"
    targets = [
        ("ArenaWorkflowRun", "run_id", run_id, "scene_candidate"),
        ("ArenaWorkflowRun", "run_id", run_id, "scene_decision"),
        ("ArenaWorkflowEvidence", "record_id", expected.scene.evidence_id, "payload"),
        ("ArenaExecutionIntent", "intent_id", expected.cleanup.intents[0].intent_id, "reservation_json"),
        ("ArenaExecutionIntent", "intent_id", expected.cleanup.intents[0].intent_id, "readiness_json"),
        ("ArenaExecutionIntent", "intent_id", expected.cleanup.intents[0].intent_id, "fence_json"),
    ]
    with driver.session(database=store.database) as session:
        for label, identity, record_id, field in targets:
            query = (
                "MATCH (n:" + label + " {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "WHERE n." + identity + "=$id "
            )
            params = dict(store.scope, id=record_id)
            original = session.run(query + "RETURN n." + field + " AS raw", **params).single()["raw"]
            try:
                for broken in (json.dumps(secret), [secret]):
                    session.run(query + "SET n." + field + "=$raw", **params, raw=broken).consume()
                    with pytest.raises(CorruptRunInspection, match="^Invalid retained run inspection$") as caught:
                        store.get_run_inspection(run_id)
                    assert secret not in "".join(traceback.format_exception(caught.value))
                    observer = Neo4jWorkflowStore(
                        inspection_driver(driver, lambda *args: None, fault="cleanup", fetch_size=1),
                        database=store.database, **store.scope,
                    )
                    with pytest.raises(OutcomeUnknown):
                        observer.get_run_inspection(run_id)
            finally:
                session.run(query + "SET n." + field + "=$raw", **params, raw=original).consume()
    assert store.get_run_inspection(run_id) == expected


def joined_scene_writer_race(driver, store, service, run_id, ports):
    from threading import Event

    pending, reader_attempted, release = Event(), Event(), Event()
    original = store._scene_decide
    before = store.get_run_inspection(run_id)

    def decide(*args, **kwargs):
        value = original(*args, **kwargs)
        if args[3].action == "accept":
            pending.set()
            assert release.wait(4)
        return value

    def visit(query, params):
        if "lock_anchor" in query:
            reader_attempted.set()

    observer = Neo4jWorkflowStore(
        inspection_driver(driver, visit, fetch_size=1, before=True), database=store.database, **store.scope
    )
    store._scene_decide = decide
    try:
        with ThreadPoolExecutor() as pool:
            writing = pool.submit(service.run_scene, "local", run_id, ports=ports)
            assert pending.wait(4)
            reading = pool.submit(observer.get_run_inspection, run_id)
            assert reader_attempted.wait(3) and not reading.done()
            release.set()
            final, joined = writing.result(timeout=4), reading.result(timeout=4)
    finally:
        release.set()
        store._scene_decide = original
    assert before.scene.candidate.candidate_id != joined.scene.candidate.candidate_id
    assert before.scene.evidence_id is None and joined.scene.selected_assessed
    return final, joined


def check_joined_causality(driver, store, run_id, expected):
    import json
    from pathlib import Path

    from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptRunInspection

    queries = []
    observed = Neo4jWorkflowStore(
        inspection_driver(driver, lambda q, p: queries.append((q, p)), fetch_size=1),
        database=store.database,
        **store.scope,
    )
    assert observed.get_run_inspection(run_id) == expected
    query, params = next((q, p) for q, p in queries if "ORDER BY e.sequence DESC" in q)
    with driver.session(database=store.database) as session:
        session.run(
            "UNWIND range(0, 500) AS n CREATE (e:ArenaWorkflowEvent) "
            "SET e.deployment_id=$deployment_id, e.workspace_id=$foreign, e.run_id=$run, "
            "e.kind='SceneDecisionRecorded', e.sequence=n, e.source_id='foreign'",
            deployment_id=store.scope["deployment_id"],
            foreign=uuid.uuid4().hex,
            run=run_id,
        ).consume()
        plan = session.run("PROFILE " + query, **params).consume().profile
        Path("/evidence/joined-event-plan.json").write_text(json.dumps(plan, default=str))

        def flatten(node):
            return [node] + [child for c in node.get("children", []) for child in flatten(c)]

        nodes = flatten(plan)
        assert any("IndexSeek" in n["operatorType"] for n in nodes)
        assert not any("Scan" in n["operatorType"] or "Sort" in n["operatorType"] for n in nodes)
        assert sum(n.get("dbHits", 0) for n in nodes) < 20
        indices = list(session.run("SHOW INDEXES YIELD labelsOrTypes, properties, state, owningConstraint RETURN *"))
        assert any(
            i["labelsOrTypes"] == ["ArenaWorkflowEvent"]
            and i["properties"] == ["deployment_id", "workspace_id", "run_id", "kind", "sequence"]
            and i["state"] == "ONLINE"
            and i["owningConstraint"] is None
            for i in indices
        )
        base = (
            "MATCH (e:ArenaWorkflowEvent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "WHERE e.run_id=$run AND e.source_id=$source "
        )
        event = session.run(
            base + "RETURN e.sequence AS sequence", **store.scope, run=run_id, source=expected.scene.decision_id
        ).single(strict=True)
        exact = (
            "MATCH (e:ArenaWorkflowEvent {deployment_id:$deployment_id, workspace_id:$workspace_id, "
            "sequence:$sequence}) "
        )
        args = dict(store.scope, sequence=event["sequence"])
        for source in (None, "broken-retained-pointer"):
            session.run(exact + "SET e.source_id=$source", **args, source=source).consume()
            if source is None:
                legacy = store.get_run_inspection(run_id)
                assert legacy.scene.decision_id is None
                assert legacy.scene.assessment == expected.scene.assessment
                assert legacy.scene.decision_identity_provenance == "unavailable_retained_causality"
                root = (
                    "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, "
                    "run_id:$run}) SET r.scene_intent=$intent"
                )
                session.run(root, **store.scope, run=run_id, intent="broken-next-intent").consume()
                with pytest.raises(CorruptRunInspection):
                    store.get_run_inspection(run_id)
                session.run(root, **store.scope, run=run_id, intent=expected.scene.next_intent_id).consume()
            else:
                with pytest.raises(CorruptRunInspection, match="^Invalid retained run inspection$"):
                    store.get_run_inspection(run_id)
        session.run(exact + "SET e.source_id=$source", **args, source=expected.scene.decision_id).consume()
    assert store.get_run_inspection(run_id) == expected


def exercise_policy_scene(case, store, service, run, auth, profile):
    """Actual DB, explicitly synthetic task/evaluator/cleanup ports."""
    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.agentic_environment_generation.workflow.policy_contracts import (
        PolicyEpisode,
        PolicyTrialReceipt,
    )
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import observation

    base = synthetic_scene_ports("managed_accept", store, run, auth)
    events, captures, results = [], [], []
    from isaaclab_arena.agentic_environment_generation.workflow.read_model import workflow_result

    class PolicyPorts(type(base)):
        paused = True

        def ready(self, contract):
            return super().ready(contract).model_copy(update={"checked_at": store._now()})

        def authorize(self, principal, contract, action):
            if action == "policy" and self.paused:
                raise PermissionError("pause at durable policy handoff")
            return super().authorize(principal, contract, action)

        def prepare_worker(self, intent, candidate, original, contract, **kwargs):
            return super().prepare_worker(intent, candidate, original, contract)

        def execute(self, intent, candidate, original, contract, *, retained_observation=None):
            events.append(("execute", intent.action))
            if intent.action == "capture":
                complete = observation(contract, candidate, intent.intent_id, include_policy=True)
                capture = complete.model_copy(
                    update={"evidence": tuple(e for e in complete.evidence if e.modality != "visual")}
                )
                captures.append(capture)
                return capture
            if intent.action == "assess":
                result = observation(
                    contract,
                    candidate,
                    retained_observation.cohort.realization_id,
                    include_policy=True,
                    fail=case == "policy_repair" and len(captures) == 1,
                )
                self.assessment_result = (intent, result)
                return result
            if intent.action == "repair":
                return super().execute(intent, candidate, original, contract)
            assert intent.action == "policy"
            assert intent.policy_binding.candidate_digest == candidate.digest
            if case == "policy_repair":
                assert candidate.digest != profile.policy_binding.candidate_digest
                assert intent.policy_binding.task_definition_digest == profile.policy_binding.task_definition_digest
            assert store.get_run(run.run_id).state == "running"
            binding = intent.policy_binding
            episodes = tuple(
                PolicyEpisode(
                    binding_digest=binding.digest(),
                    episode_id=f"e{i}",
                    reset_id=binding.reset_id if i == 0 else f"next-reset-{i}",
                    seed=binding.seed,
                    success=False if case == "policy_fail" else None if case == "policy_unknown" else True,
                )
                for i in range(0 if case == "policy_empty" else 1 if case == "policy_partial" else binding.max_episodes)
            )
            assert "intent_id" in PolicyTrialReceipt.model_fields, "policy trial requires exact intent identity"
            receipt = PolicyTrialReceipt(
                intent_id=intent.intent_id,
                binding=binding,
                episodes=episodes,
                manifest_digest="e" * 64,
                episode_records_digest="f" * 64,
                policy_steps=10,
                prerequisite_steps=2,
            )
            corruptions = {
                "policy_foreign_binding": {"task_id": "foreign-task"},
                "policy_foreign_candidate": {"candidate_digest": "0" * 64},
                "policy_foreign_contract": {"contract_digest": "0" * 64},
                "policy_foreign_policy": {"policy_artifact_digest": "0" * 64},
                "policy_foreign_instruction": {"instruction": "different instruction"},
                "policy_foreign_task_digest": {"task_definition_digest": "0" * 64},
                "policy_foreign_seed": {"seed": binding.seed + 1},
            }
            if case in corruptions:
                foreign = binding.model_copy(update=corruptions[case])
                receipt = receipt.model_copy(
                    update={
                        "binding": foreign,
                        "episodes": tuple(
                            e.model_copy(update={"binding_digest": foreign.digest(), "seed": foreign.seed})
                            for e in episodes
                        ),
                    }
                )
            if case == "policy_duplicate_reset":
                receipt = receipt.model_copy(
                    update={
                        "episodes": (episodes[0], episodes[1].model_copy(update={"reset_id": episodes[0].reset_id}))
                    }
                )
            if case == "policy_zero_steps":
                receipt = receipt.model_copy(update={"policy_steps": 0})
            if case == "policy_foreign_intent":
                receipt = receipt.model_copy(update={"intent_id": "0" * 64})
            results.append((intent, receipt))
            if case == "policy_cancel":
                store.request_cancel(run.run_id, store.get_run(run.run_id).version)
            return receipt

        def cleanup_worker(self, intent):
            events.append(("cleanup", intent.action))
            if intent.action == "policy" and case == "policy_cleanup_failure":
                raise TimeoutError("policy cleanup unknown")
            return super().cleanup_worker(intent)

        def release_native_resource(self, intent, cleanup):
            events.append(("release", intent.action))
            if intent.action == "policy" and case == "policy_slot_failure":
                return False
            return True

        def verify_policy(self, output, contract, candidate, binding):
            assert events[-1] == ("release", "policy")
            assert output.binding == binding or case.startswith("policy_foreign_")
            return output

    ports = PolicyPorts()
    ports.profile = profile
    if case in (
        "policy_profile_mismatch",
        "policy_candidate_mismatch",
        "policy_contract_mismatch",
        "policy_seed_mismatch",
        "policy_v1_unsupported",
    ):
        final = service.run_scene("local", run.run_id, ports=ports)
        assert final.run.state == "stopped" and final.decision.reason == "unsupported_criterion"
        assert not events
        return
    if case == "policy_budget":
        final = service.run_scene("local", run.run_id, ports=ports)
        assert final.run.state == "stopped" and final.decision.reason == "budget_exhausted"
        assert [a for event, a in events if event == "execute"] == ["capture", "assess"]
        assert store.get_run_inspection(run.run_id).budget.reserved.policy_episodes == 0
        inspected = store.get_run_inspection(run.run_id)
        assert inspected.scene.acceptance == "accepted"
        assert all(c.verdict == "established" for c in inspected.scene.criteria if c.criterion_id != "task-success")
        assert workflow_result(store, run.run_id, protect=lambda _: None)["scene_acceptance"] == "accepted"
        return
    if case == "policy_atomic_rollback":
        original_event = store._event

        def fail_event(tx, run_id, kind, *args, **kwargs):
            current = store._scene_snapshot(tx, run_id)
            if kind == "SceneDecisionRecorded" and current.decision.action == "policy":
                assert current.run.state == "running" and current.intent.action == "policy"
                raise ValueError("injected policy transaction rollback")
            return original_event(tx, run_id, kind, *args, **kwargs)

        store._event = fail_event
        with pytest.raises(ValueError, match="transaction rollback"):
            service.run_scene("local", run.run_id, ports=ports)
        store._event = original_event
        rolled_back = store.scene_snapshot(run.run_id)
        assert rolled_back.run.state == "running" and rolled_back.intent.action == "assess"
        assert store.get_run_inspection(run.run_id).budget.reserved.policy_episodes == 0
        assessment_intent, assessed = ports.assessment_result
        assert store.finish_scene(
            run.run_id,
            assessment_intent.intent_id,
            rolled_back.run.version,
            scene_loop.SceneResult(codec_version=2, observation=assessed),
        )
    with pytest.raises(PermissionError, match="handoff"):
        service.run_scene("local", run.run_id, ports=ports)
    pending = store.scene_snapshot(run.run_id)
    assert pending.run.state == "running" and pending.decision.action == pending.intent.action == "policy"
    assert pending.decision.assessment.status == "established"
    assert pending.intent.worker_fence is None
    checked = store.get_run_inspection(run.run_id)
    assert checked.scene.acceptance == "accepted" and checked.policy_outcome == "ready_for_policy"
    assert checked.actions.resume_branch == "scene"
    assert checked.budget.reserved.policy_episodes == 2 and checked.budget.reserved.policy_steps == profile.policy.policy_steps
    assert store.get_scene_decision(checked.scene.decision_id).decision.action == "policy"
    assessment_intent, assessed = ports.assessment_result
    assert not store.finish_scene(
        run.run_id,
        assessment_intent.intent_id,
        pending.run.version,
        scene_loop.SceneResult(codec_version=2, observation=assessed),
    )
    assert store.scene_snapshot(run.run_id) == pending
    assert store.get_run_inspection(run.run_id).budget == checked.budget
    # Fresh service instance reconstructs the same unclaimed, durable policy work.
    service = type(service)(store, service._authority, None, validate_support=lambda _: None)
    ports.paused = False
    if case == "policy_producer_failure":
        from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence
        from isaaclab_arena.agentic_environment_generation.workflow.contracts import parse_contract

        owner = store.get_owner()
        fence = store.claim_scene_worker(run.run_id, pending.intent.intent_id, owner.owner_id, owner.owner_epoch)
        reg = registration(fence)
        store.register_scene_worker(fence, reg)
        contract = parse_contract(pending.run.contract_json)
        assert store.release_scene(
            run.run_id,
            pending.intent.intent_id,
            auth,
            readiness=readiness(contract, auth),
            fence=fence,
            registration_id=reg.registration_id,
        )
        store.acknowledge_scene_cleanup(
            fence,
            CleanupEvidence(
                registration=reg,
                evidence_ref="synthetic-policy-cleanup",
                observation="owned_process_group_stopped",
                remote_effects="unknown",
            ),
        )
        current = store.scene_snapshot(run.run_id)
        store.finish_scene(
            run.run_id,
            pending.intent.intent_id,
            current.run.version,
            scene_loop.SceneResult(codec_version=2, failure="evidence_verification_failed"),
        )
        inspected = store.get_run_inspection(run.run_id)
        assert inspected.intent.state == "stopped" and inspected.scene.acceptance == "accepted"
        assert inspected.scene.selected_assessed
        assert workflow_result(store, run.run_id, protect=lambda _: None)["scene_acceptance"] == "accepted"
        return
    if case == "policy_deadline":
        store.clock = lambda: 151.0
    if case in (
        "policy_cleanup_failure",
        "policy_slot_failure",
        "policy_foreign_binding",
        "policy_foreign_seed",
        "policy_duplicate_reset",
        "policy_zero_steps",
        "policy_foreign_intent",
        "policy_foreign_candidate",
        "policy_foreign_contract",
        "policy_foreign_policy",
        "policy_foreign_instruction",
        "policy_foreign_task_digest",
    ):
        with pytest.raises((TimeoutError, ValueError)):
            service.run_scene("local", run.run_id, ports=ports)
        final = store.scene_snapshot(run.run_id)
        assert final.run.state == "reconciliation_required"
        assert store.get_run_inspection(run.run_id).policy_outcome == "ready_for_policy"
        assert final.intent.intent_id == pending.intent.intent_id
        assert service.run_scene("local", run.run_id, ports=ports) == final
        return
    final = service.run_scene("local", run.run_id, ports=ports)
    if case in ("policy_cancel", "policy_deadline"):
        assert final.run.state == ("cancelled" if case == "policy_cancel" else "reconciliation_required")
        if case == "policy_deadline":
            assert not any(a == "policy" for event, a in events if event == "execute")
        assert service.run_scene("local", run.run_id, ports=ports) == final
        return
    expected = (
        "failed"
        if case == "policy_fail"
        else "unknown" if case in ("policy_empty", "policy_partial", "policy_unknown") else "passed"
    )
    assert final.run.state == ("accepted" if expected == "passed" else "stopped")
    assert final.decision.policy_trial.aggregate().outcome == expected
    assert (
        store.get_scene_decision(scene_loop.identity(run.run_id, final.run.version - 1, "scene-decision")).decision
        == final.decision
    )
    checked = store.get_run_inspection(run.run_id)
    assert checked.policy_outcome == expected
    assert checked.scene.acceptance == "accepted"  # Required policy failure does not erase scene prerequisites.
    assert checked.scene.selected_assessed
    legacy = workflow_result(store, run.run_id, protect=lambda _: None)
    assert legacy["scene_acceptance"] == "accepted"
    assert legacy["policy_outcome"] == expected
    assert (
        next(c["verdict"] for c in legacy["criteria"] if c["criterion_id"] == "task-success")
        == {"passed": "established", "failed": "violated", "unknown": "inconclusive"}[expected]
    )
    assert store.get_scene_decision(checked.scene.decision_id).decision == final.decision
    expected_actions = (
        ["capture", "assess"] + (["repair", "capture", "assess"] if case == "policy_repair" else []) + ["policy"]
    )
    assert [a for event, a in events if event == "execute"] == expected_actions
    assert service.run_scene("local", run.run_id, ports=ports) == final
    intent, receipt = results[0]
    assert not store.finish_scene(
        run.run_id, intent.intent_id, final.run.version, scene_loop.SceneResult(codec_version=2, policy_trial=receipt)
    )
    assert store.get_run_inspection(run.run_id).budget == checked.budget
    check_policy_history_tamper(case, store, run, receipt, final, checked)


def check_policy_history_tamper(case, store, run, receipt, final, checked):
    """Preserve exact producing identity checks independently of the happy trace."""
    if case == "policy_intent_identity_tamper":
        import json
        from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptSceneRecord

        changed = store.get_scene_intent(run.run_id, receipt.intent_id).model_dump(mode="json")
        changed["intent_id"] = "0" * 64
        with store._transaction() as tx:
            tx.run(
                "MATCH (i:ArenaExecutionIntent) WHERE i.intent_id=$id SET i.scene_json=$payload",
                id=receipt.intent_id,
                payload=json.dumps(changed),
            ).consume()
        with pytest.raises(CorruptSceneRecord):
            store.get_scene_decision(checked.scene.decision_id)
    if case == "policy_retained_tamper":
        import json
        from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptSceneRecord

        forged = final.decision.policy_trial.binding.model_copy(update={"instruction": "foreign instruction"})
        raw = final.decision.model_dump(mode="json")
        raw["policy_trial"]["binding"] = forged.model_dump(mode="json")
        for episode in raw["policy_trial"]["episodes"]:
            episode["binding_digest"] = forged.digest()
        with store._transaction() as tx:
            tx.run(
                "MATCH (d:ArenaWorkflowDecision) WHERE d.decision_id=$id SET d.payload=$payload",
                id=checked.scene.decision_id,
                payload=json.dumps(raw),
            ).consume()
        with pytest.raises(CorruptSceneRecord):
            store.get_scene_decision(checked.scene.decision_id)


def exercise_split_scene(case, store, service, run, auth, profile):
    """Real DB split lifecycle; synthetic capture/cleanup is NOT native proof."""
    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import observation

    base = synthetic_scene_ports("managed_accept", store, run, auth)
    events = []
    captured = []
    owner = store.get_owner()
    capture_ids = []

    class SplitPorts(type(base)):
        def prepare_worker(self, intent, candidate, original, contract, *, retained_observation=None):
            events.append(("prepare", intent.action))
            if intent.action == "assess":
                assert events[-2] == ("gpu_released", "capture")
                assert retained_observation == captured[-1]
                assert intent.observation_digest == scene_loop.identity(retained_observation.model_dump(mode="json"))
                inspected = store.get_run_inspection(run.run_id)
                assert inspected.scene.action == "assess" and not inspected.scene.selected_assessed
                assert inspected.scene.evidence_id == intent.observation_id
                assert inspected.budget.reserved.realizations == len(captured)
                assert inspected.budget.reserved.observations == len(captured)
                assert store.get_owner() == owner
            return super().prepare_worker(intent, candidate, original, contract)

        def execute(self, intent, candidate, original, contract, *, retained_observation=None):
            events.append(("execute", intent.action))
            if intent.action == "capture":
                assert intent.reservation.model_calls == intent.reservation.model_tokens == 0
                complete = observation(contract, candidate, intent.intent_id)
                value = complete.model_copy(
                    update={"evidence": tuple(e for e in complete.evidence if e.modality != "visual")}
                )
                if case == "split_static_failure":
                    value = value.model_copy(update={"static_failure": "ineffective_edit"})
                captured.append(value)
                capture_ids.append(intent.intent_id)
                if case == "split_cancel_capture":
                    store.request_cancel(run.run_id, store.get_run(run.run_id).version)
                return value
            if intent.action == "repair":
                import json

                child = json.loads(candidate.scene_json)
                child["relations"][2]["params"]["x"] = 0.03
                return child
            assert intent.action == "assess" and retained_observation == captured[-1]
            assert intent.reservation.realizations == intent.reservation.steps == 0
            result = observation(
                contract,
                candidate,
                retained_observation.cohort.realization_id,
                fail=case == "split_repair" and len(captured) == 1,
            )
            if case == "split_observe" and len(captured) == 1:
                result = result.model_copy(
                    update={"evidence": tuple(e for e in result.evidence if e.modality != "visual")}
                )
            if case == "split_tampered_assess":
                result = result.model_copy(update={"cohort": result.cohort.model_copy(update={"reset_id": "foreign"})})
            return result

        def cleanup_worker(self, intent):
            events.append(("cleanup", intent.action))
            if case == "split_cleanup_unknown":
                raise TimeoutError("cleanup unknown")
            return super().cleanup_worker(intent)

        def release_native_resource(self, intent, cleanup):
            assert events[-1] == ("cleanup", "capture")
            retained = store.get_scene_intent(run.run_id, intent.intent_id)
            assert retained.worker_cleanup == cleanup and retained.status in ("released", "reconciliation_required")
            assert store.scene_snapshot(run.run_id).intent.action == "capture"
            if case == "split_slot_unknown":
                raise TimeoutError("slot unknown")
            events.append(("gpu_released", "capture"))
            return True

        def authorize(self, principal, contract, action):
            if case == "split_recover_assess" and action == "assess" and not getattr(self, "resumed", False):
                raise PermissionError("pause before assessment preparation")
            return super().authorize(principal, contract, action)

    ports = SplitPorts()
    ports.profile = profile
    initial = store.scene_snapshot(run.run_id)
    assert initial.intent.action == "capture" and initial.intent.codec_version == 2
    if case in ("split_cleanup_unknown", "split_slot_unknown"):
        with pytest.raises(TimeoutError, match="unknown"):
            service.run_scene("local", run.run_id, ports=ports)
        pending = store.scene_snapshot(run.run_id)
        assert pending.run.state == "reconciliation_required"
        assert pending.intent.action == "capture" and pending.intent.status == "reconciliation_required"
        assert len(captured) == 1 and not any(action == "assess" for _, action in events)
        assert (
            pending.intent.worker_cleanup is None
            if case == "split_cleanup_unknown"
            else pending.intent.worker_cleanup is not None
        )
        assert store.get_run_inspection(run.run_id).scene.evidence_id is None
        assert service.run_scene("local", run.run_id, ports=ports) == pending
        return
    if case == "split_recover_assess":
        with pytest.raises(PermissionError, match="pause"):
            service.run_scene("local", run.run_id, ports=ports)
        pending = store.scene_snapshot(run.run_id)
        assert pending.intent.action == "assess" and pending.intent.worker_fence is None
        assert store.get_scene_capture(run.run_id, pending.intent.intent_id) == captured[-1]
        assert store.get_run_inspection(run.run_id).actions.resume_branch == "scene"
        # A fresh application service reads the same exact retained capture.
        service = type(service)(store, service._authority, None, validate_support=lambda _: None)
        ports.resumed = True
    if case == "split_tampered_assess":
        with pytest.raises(ValueError, match="assessment changed retained capture"):
            service.run_scene("local", run.run_id, ports=ports)
        pending = store.scene_snapshot(run.run_id)
        assert pending.run.state != "accepted" and pending.intent.action == "assess"
        assert store.get_scene_capture(run.run_id, pending.intent.intent_id) == captured[-1]
        return
    final = service.run_scene("local", run.run_id, ports=ports)
    if case in ("split_static_failure", "split_cancel_capture"):
        assert final.run.state == ("stopped" if case == "split_static_failure" else "cancelled")
        assert [action for stage, action in events if stage == "execute"] == ["capture"]
        assert store.get_owner() == owner
        return
    assert final.run.state == "accepted"
    expected = ["capture", "assess"]
    if case in ("split_repair", "split_observe"):
        expected += (["repair"] if case == "split_repair" else []) + ["capture", "assess"]
        assert len({value.cohort.realization_id for value in captured}) == 2
    assert [action for stage, action in events if stage == "execute"] == expected
    assert store.get_scene_intent(run.run_id, initial.intent.intent_id).status == "produced"
    checked = store.get_run_inspection(run.run_id)
    assert checked.scene.selected_assessed and checked.scene.acceptance == "accepted"
    assert checked.budget.reserved.realizations == checked.budget.reserved.observations == len(captured)
    assert checked.budget.reserved.steps == 10 * len(captured)
    assert service.run_scene("local", run.run_id, ports=ports) == final


def synthetic_scene_ports(case, s, run, auth):
    """Build controlled physical-port callbacks; no OS or native evidence."""
    import json

    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import observation

    class SyntheticPorts:
        calls = []
        bound_checks = 0
        prepared = []
        cleaned = []

        def require_held_owner(self):
            # Synthetic physical port: binding/order proof only, NO OS proof.
            return s.get_owner()

        def prepare_worker(self, intent, candidate, original, contract):
            assert intent.worker_fence is not None and intent.released_at is None
            assert len(self.prepared) == len(self.cleaned)
            self.prepared.append(intent.intent_id)
            if case == "managed_cancel_prepare":
                cancelled = s.request_cancel(run.run_id, s.get_run(run.run_id).version)
                assert cancelled.state == "cancel_requested"
            if case == "managed_prepare_unknown":
                raise TimeoutError("synthetic ambiguous prepare")
            return registration(intent.worker_fence)

        def cleanup_worker(self, intent):
            if case == "managed_cleanup_failure":
                raise TimeoutError("synthetic cleanup pending")
            if intent.worker_registration is None:
                raise ValueError("unregistered synthetic prepare remains unresolved")
            assert intent.worker_registration.fence == intent.worker_fence
            self.cleaned.append(intent.intent_id)
            return CleanupEvidence(
                registration=intent.worker_registration,
                evidence_ref="synthetic-scene-stop",
                observation="owned_process_group_stopped",
                remote_effects="unknown",
            )

        def require_bounded_capability(self, principal, contract, reservation):
            # Synthetic port has no provider effects; never provider attestation.
            assert principal == "local"
            self.bound_checks += 1
            return case != "unbounded" and not (case == "bound_revoked" and self.bound_checks > 1)

        def authorize(self, principal, contract, action):
            assert principal == "local"
            return auth

        ready_checks = 0

        def ready(self, contract):
            self.ready_checks += 1
            ready = readiness(contract, auth)
            revoked = case == "managed_readiness_revoked" and self.ready_checks >= 3
            return (
                ready.model_copy(update={"profiles": ready.profiles[:-1]}) if case == "readiness" or revoked else ready
            )

        def execute(self, released, candidate, original, contract):
            self.calls.append(released.action)
            if case in ("unknown", "managed_timeout"):
                raise TimeoutError("synthetic lost acknowledgement")
            if case in ("cancel_during", "managed_cancel_execute"):
                cancelled = s.request_cancel(run.run_id, s.get_run(run.run_id).version)
                assert cancelled.state == "cancel_requested"
            if released.action == "observe":
                if candidate.parent_id is not None:
                    child = s.get_run_inspection(run.run_id)
                    assert child.scene.candidate.candidate_id == candidate.candidate_id
                    assert child.scene.reason == "fresh_child_cohort_required"
                    assert child.scene.evidence_id is None and not child.scene.selected_assessed
                output = observation(
                    contract,
                    candidate,
                    "A" if candidate.parent_id is None or case == "stale" else "B",
                    fail=candidate.parent_id is None,
                )
                if case == "observe_budget":
                    output = output.model_copy(update={"evidence": ()})
                    output = output.model_copy(
                        update={"cohort": output.cohort.model_copy(update={"realization_id": str(len(self.calls))})}
                    )
                if case == "assessed_deadline" and candidate.parent_id is not None:
                    s.clock = lambda: 10000.0
                self.last_observation = output
                self.last_intent = released
                return output
            value = json.loads(candidate.scene_json)
            value["relations"][2]["params"]["x"] = 0.03
            if case == "forbidden":
                value["relations"][2]["params"]["z"] = 1.0
            return value

        def verify_observation(self, value, contract, candidate):
            return value  # Explicit synthetic evidence; production must read actual bytes.

        def validate_candidate(self, value):
            return None  # Explicit synthetic schema; native composition remains separate.

    return SyntheticPorts()


def exercise_scene_worker_case(case, s, service, ports, run, fence, reg, auth, contract, receipt):
    """Exercise synthetic physical-port failure/CAS cases, never OS cleanup proof."""
    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )

    if case in ("managed_keyed_cancel_late_unknown", "managed_keyed_cancel_unresolved_unknown"):
        from isaaclab_arena.agentic_environment_generation.workflow.commands import LocalStopObservation

        scene_id = s.scene_snapshot(run.run_id).intent.intent_id
        sf = s.claim_scene_worker(run.run_id, scene_id, "owner", fence.owner_epoch)
        sr = registration(sf)
        assert s.register_scene_worker(sf, sr)
        assert s.release_scene(
            run.run_id,
            scene_id,
            auth,
            readiness=readiness(contract, auth),
            fence=sf,
            registration_id=sr.registration_id,
        )
        retained = s.cancel_command(
            "late-unknown", run.run_id, LocalStopObservation(delivery="delivered"), protect=lambda v: None
        )
        assert s.get_run(run.run_id).state == "cancel_requested"
        cleanup = CleanupEvidence(
            registration=sr,
            evidence_ref="synthetic-scene-stop",
            observation="owned_process_group_stopped",
            remote_effects="unknown",
        )
        cleaned = case == "managed_keyed_cancel_late_unknown"
        if cleaned:
            assert s.acknowledge_scene_cleanup(sf, cleanup)
            assert s.get_run(run.run_id).state == "cancelled"
        # The receive failure writer arrives after the cancellation/cleanup writer.
        assert s.mark_scene_unknown(run.run_id, scene_id)
        assert s.get_run(run.run_id).state == ("cancelled" if cleaned else "cancel_requested")
        with s.driver.session(database=s.database) as session:
            reason = session.run(
                "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "WHERE r.run_id=$run RETURN r.stop_reason AS reason",
                **s.scope,
                run=run.run_id,
            ).single()["reason"]
        assert reason == "released_scene_outcome_unknown"
        assert s.get_scene_intent(run.run_id, scene_id).status == "reconciliation_required"
        assert s.get_cancel_receipt("late-unknown") == retained
        assert (
            s.cancel_command(
                "late-unknown", run.run_id, LocalStopObservation(delivery="no_owner"), protect=lambda v: None
            )
            == retained
        )
        if cleaned:
            assert not s.acknowledge_scene_cleanup(sf, cleanup)
            assert s.get_run(run.run_id).state == "cancelled"
            s.retire_owner("owner", fence.owner_epoch)
            assert s.get_owner().dirty is False
        else:
            with pytest.raises(ValueError, match="unresolved"):
                s.retire_owner("owner", fence.owner_epoch)
            assert s.get_scene_intent(run.run_id, scene_id).worker_cleanup is None
        assert not s.mark_scene_unknown(run.run_id, scene_id)
        assert s.get_cancel_receipt("late-unknown") == retained
        return True
    if case == "managed_missing_ports":
        ports.prepare_worker = None
        with pytest.raises(ValueError, match="managed scene worker ports"):
            service.run_scene("local", run.run_id, ports=ports)
        assert ports.calls == ports.prepared == []
        return True
    if case == "managed_binding_cas":
        pending = s.scene_snapshot(run.run_id)
        scene_id = pending.intent.intent_id
        with pytest.raises(ValueError, match="registration"):
            s.release_scene(run.run_id, scene_id, auth, readiness=readiness(contract, auth))
        sf = s.claim_scene_worker(run.run_id, scene_id, "owner", fence.owner_epoch)
        claimed = [i for i in s.get_run_cleanup(run.run_id).intents if i.kind == "scene"]
        assert claimed[0].cleanup_state == "unknown" and claimed[0].registration_id is None
        sr = registration(sf)
        with pytest.raises(ValueError, match="fence"):
            s.register_scene_worker(sf, registration(fence))
        assert s.register_scene_worker(sf, sr)
        assert not s.register_scene_worker(sf, sr)
        assert [i.cleanup_state for i in s.get_run_cleanup(run.run_id).intents if i.kind == "scene"] == ["unknown"]
        with pytest.raises(ValueError, match="conflicting"):
            s.register_scene_worker(sf, sr.model_copy(update={"pid": 999}))
        with ThreadPoolExecutor(max_workers=4) as pool:
            winners = list(
                pool.map(
                    lambda _: s.release_scene(
                        run.run_id,
                        scene_id,
                        auth,
                        readiness=readiness(contract, auth),
                        fence=sf,
                        registration_id=sr.registration_id,
                    ),
                    range(4),
                )
            )
        assert winners.count(True) == 1
        with pytest.raises(ValueError, match="cleanup"):
            s.finish_scene(
                run.run_id,
                scene_id,
                s.get_run(run.run_id).version,
                scene_loop.SceneResult(failure="invalid_candidate"),
            )
        with pytest.raises(ValueError, match="registration"):
            s.acknowledge_scene_cleanup(
                sf,
                CleanupEvidence(
                    registration=reg,
                    evidence_ref="wrong-scene-stop",
                    observation="owned_process_group_stopped",
                    remote_effects="unknown",
                ),
            )
        assert s.get_generation_attempt(run.run_id).receipt == receipt
        return True
    if case == "managed_release_ack":
        release = s.release_scene

        def lost_ack(*args, **kwargs):
            assert release(*args, **kwargs)
            raise OSError("synthetic committed release acknowledgement lost")

        s.release_scene = lost_ack
    if case in (
        "managed_prepare_unknown",
        "managed_cleanup_failure",
        "managed_cancel_prepare",
    ):
        with pytest.raises((ValueError, TimeoutError)):
            service.run_scene("local", run.run_id, ports=ports)
        retained = s.scene_snapshot(run.run_id)
        assert retained.intent.worker_fence is not None and retained.intent.worker_cleanup is None
        assert [i.cleanup_state for i in s.get_run_cleanup(run.run_id).intents if i.kind == "scene"] == ["unknown"]
        if case == "managed_cancel_prepare":
            assert retained.run.state == "cancel_requested"
        with pytest.raises(ValueError, match="unresolved"):
            s.retire_owner("owner", fence.owner_epoch)
        count = len(ports.prepared)
        service.run_scene("local", run.run_id, ports=ports)
        assert len(ports.prepared) == count == 1
        return True
    return False


def test_bound_run_first_page_is_compact_authenticated_and_live(driver):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.tests.test_environment_workflow_service import contract

    assert hasattr(WorkflowService, "list_runs"), "bounded authenticated run discovery missing"
    s, binding = binding_fixture(driver)
    s.initialize_bound_scope(binding, protect=lambda _: None)
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json

    runs = [s.admit(key, '{"request":1}', canonical_json(contract()), 10) for key in ("LiteralSyntheticId", "second")]
    calls = []
    service = WorkflowService(
        s, SimpleNamespace(require_read=lambda p: calls.append(p)), None, validate_support=None, read_scope=binding
    )
    screens = []
    page = service.list_runs("reader", first=1, protect=screens.append)
    assert calls == ["reader"]
    assert page.binding == binding and page.semantics == "live_keyset"
    assert len(page.runs) == 1 and page.has_more is True
    assert page.runs[0].run_id == min(r.run_id for r in runs)
    assert page.runs[0].run_version == "1"
    assert page.floor == "0" and page.ceiling == "2"
    assert page.event_watermark and page.end_cursor
    assert set(page.runs[0].model_dump()) == {"run_id", "operation_id", "state", "phase", "run_version", "event_cursor"}
    assert screens == [page.model_dump(mode="json")]


def paging_fixture(driver):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    s, binding = binding_fixture(driver)
    s.initialize_bound_scope(binding, protect=lambda _: None)
    service = WorkflowService(
        s, SimpleNamespace(require_read=lambda _: None), None, validate_support=None, read_scope=binding
    )
    return s, binding, service


def test_actual_run_event_page_profiles_are_scoped_ordered_range_and_bounded(driver):
    import json
    from pathlib import Path

    from isaaclab_arena.agentic_environment_generation.workflow.paging import EventPosition, RunPosition

    s, binding, service = paging_fixture(driver)
    runs = [s.admit(f"key-{n}", "{}", "{}", 100) for n in range(12)]
    with driver.session(database=s.database) as session:
        session.run(
            "UNWIND range(0, 500) AS n CREATE (r:ArenaWorkflowRun), (e:ArenaWorkflowEvent) "
            "SET r.deployment_id=$deployment_id, r.workspace_id=$foreign, r.run_id=toString(n), "
            "e.deployment_id=$deployment_id, e.workspace_id=$foreign, e.sequence=n",
            deployment_id=binding.deployment_id,
            foreign=uuid.uuid4().hex,
        ).consume()
    queries = []
    observed = Neo4jWorkflowStore(
        inspection_driver(driver, lambda q, p: queries.append((q, p)), fetch_size=2), database=s.database, **s.scope
    )
    observed.list_runs_window(binding, first=1)
    observed.list_runs_window(binding, first=1, after=RunPosition(position=sorted(r.run_id for r in runs)[0]))
    observed.read_scope_events_window(binding, first=1)
    observed.read_scope_events_window(binding, first=1, after=EventPosition(position="1", floor="0", ceiling="12"))
    selected = [(q, p) for q, p in queries if q.endswith(" AS row")]
    assert len(selected) == 4
    proofs = []

    def flatten(node):
        return [node] + [x for c in node.get("children", []) for x in flatten(c)]

    with driver.session(database=s.database) as session:
        for q, p in selected:
            result = session.run("PROFILE " + q, **p)
            rows = list(result)
            plan = result.consume().profile
            proofs.append(dict(query=q, parameters=p, plan=plan))
            Path("/evidence/paging-query-plans.json").write_text(json.dumps(proofs, default=str))
            nodes = flatten(plan)
            assert len(rows) == 2 and p["limit"] == 2
            assert any("IndexSeek" in n["operatorType"] for n in nodes)
            assert not any(any(word in n["operatorType"] for word in ("Scan", "Sort", "Top")) for n in nodes), plan
            assert max(n.get("rows", 0) for n in nodes) <= p["limit"], plan
            assert sum(n.get("dbHits", 0) for n in nodes) < 80, plan
    Path("/evidence/paging-query-plans.json").write_text(json.dumps(proofs, default=str))


@pytest.mark.parametrize(
    "target",
    [
        "run_version",
        "run_cursor",
        "run_identity",
        "state",
        "event_sequence",
        "event_schema",
        "event_source",
        "event_command",
        "floor",
        "ceiling",
    ],
)
def test_pages_reject_corrupt_physical_rows_including_lookahead(driver, target):
    from isaaclab_arena.agentic_environment_generation.workflow.paging import CorruptPage

    s, binding, service = paging_fixture(driver)
    runs = sorted([s.admit(k, "{}", "{}", 10) for k in ("one", "two")], key=lambda r: r.run_id)
    with s._transaction() as tx:
        s._lock(tx)
        if target in ("floor", "ceiling"):
            field = "floor" if target == "floor" else "sequence"
            tx.run(
                "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                f"SET c.{field}=1.0",
                **s.scope,
            ).consume()
        elif target.startswith("event"):
            field, value = {
                "event_sequence": ("sequence", 2.0),
                "event_schema": ("schema_version", True),
                "event_source": ("source_id", "x" * 129),
                "event_command": ("command_kind", "CANCEL"),
            }[target]
            tx.run(
                "MATCH (e:ArenaWorkflowEvent {deployment_id:$deployment_id, workspace_id:$workspace_id, sequence:2}) "
                f"SET e.{field}=$value",
                **s.scope,
                value=value,
            ).consume()
        else:
            field, value = {
                "run_version": ("version", 1.0),
                "run_cursor": ("event_cursor", True),
                "run_identity": ("operation_id", "another"),
                "state": ("state", "x" * 4096),
            }[target]
            tx.run(
                "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run}) "
                f"SET r.{field}=$value",
                **s.scope,
                run=runs[1].run_id,
                value=value,
            ).consume()
    method = service.read_scope_events if target.startswith("event") else service.list_runs
    with pytest.raises(CorruptPage):
        method("reader", first=1, protect=lambda _: pytest.fail("corruption reached public callback"))


def test_event_pages_preserve_interleaved_submission_sources_and_command_causes(driver):
    from dataclasses import asdict

    from isaaclab_arena.agentic_environment_generation.workflow.commands import LocalStopObservation

    s, binding, service = paging_fixture(driver)
    s.clock = lambda: 100.0
    run, _, _, _, _ = reserved(s)
    other = s.admit("other", "{}", "{}", 10)
    first = service.read_scope_events("reader", first=1, protect=lambda _: None)
    selection = s.preview_resume(run.run_id).selection
    resume = s.admit_resume(
        "Resume.Literal",
        dict(runId=run.run_id, expectedVersion=2, renewAuthorization=False),
        selection=selection,
        eligibility="current",
        protect=lambda _: None,
    )
    cancel = s.cancel_command(
        "Cancel.Literal", other.run_id, LocalStopObservation(delivery="no_owner"), protect=lambda _: None
    )
    delivered = list(first.events)
    page = first
    while page.has_more:
        page = service.read_scope_events("reader", first=1, after=page.resume_cursor, protect=lambda _: None)
        delivered.extend(page.events)
    original = s.events_after(0, 100).events
    assert [e.model_dump(mode="json") for e in delivered] == [
        asdict(e) | {"sequence": str(e.sequence)} for e in original
    ]
    assert {e.run_id for e in delivered} == {run.run_id, other.run_id}
    caused = {e.command_kind: e for e in delivered if e.command_kind is not None}
    assert caused["RESUME"].command_operation_id == resume.receipt.operation_id == "Resume.Literal"
    assert caused["CANCEL"].command_operation_id == cancel.operation_id == "Cancel.Literal"
    assert caused["RESUME"].operation_id == "generate" and caused["CANCEL"].operation_id == "other"
    assert delivered[0].source_id is None
    assert all("run_version" not in e.model_dump() for e in delivered)


def test_event_pages_retained_floor_expiry_future_and_empty_positions(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        EventPosition,
        FutureCursor,
        decode_cursor,
        encode_cursor,
    )

    s, binding, service = paging_fixture(driver)
    empty = service.list_runs("reader", protect=lambda _: None)
    assert empty.runs == () and empty.end_cursor is None and not empty.has_more
    empty_events = service.read_scope_events("reader", protect=lambda _: None)
    assert decode_cursor(empty_events.resume_cursor, binding, EventPosition).position == "0"
    for n in range(4):
        s.admit(f"key-{n}", "{}", "{}", 10)
    # Test-only simulated pruning. No production retention/reset operation exists.
    with s._transaction() as tx:
        s._lock(tx)
        tx.run(
            "MATCH (e:ArenaWorkflowEvent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "WHERE e.sequence<=2 DELETE e",
            **s.scope,
        ).consume()
        tx.run(
            "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) SET c.floor=2",
            **s.scope,
        ).consume()
    with pytest.raises(ReplayGap):
        service.read_scope_events("reader", after=empty.event_watermark, protect=lambda _: None)
    future = encode_cursor(binding, EventPosition(position="5", floor="0", ceiling="5"))
    with pytest.raises(FutureCursor):
        service.read_scope_events("reader", after=future, protect=lambda _: None)
    page = service.read_scope_events("reader", first=1, protect=lambda _: None)
    assert page.floor == "2" and page.ceiling == "4" and page.coverage == "retained"
    assert [e.sequence for e in page.events] == ["3"] and page.has_more
    second = service.read_scope_events("reader", first=1, after=page.resume_cursor, protect=lambda _: None)
    assert [e.sequence for e in second.events] == ["4"] and not second.has_more
    # Equality with the current floor is valid, not an expired cursor.
    at_floor = encode_cursor(binding, EventPosition(position="2", floor="0", ceiling="4"))
    assert service.read_scope_events("reader", first=1, after=at_floor, protect=lambda _: None).events == page.events
    s.begin_owner("owner-only")
    poll = service.read_scope_events("reader", after=second.resume_cursor, protect=lambda _: None)
    assert poll.events == () and poll.resume_cursor == second.resume_cursor


def test_page_fullwidth_counters_and_nonexistent_run_key(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        EventPosition,
        RunPosition,
        decode_cursor,
        encode_cursor,
    )

    s, binding, service = paging_fixture(driver)
    high = 2**53 + 1
    with s._transaction() as tx:
        s._lock(tx)
        tx.run(
            "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "SET c.floor=$high, c.sequence=$high",
            **s.scope,
            high=high,
        ).consume()
    run = s.admit("wide", "{}", "{}", 10)
    with s._transaction() as tx:
        s._lock(tx)
        tx.run(
            "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "SET r.version=$version",
            **s.scope,
            version=2**63 - 1,
        ).consume()
    page = service.list_runs("reader", protect=lambda _: None)
    assert page.runs[0].run_version == str(2**63 - 1)
    assert page.runs[0].event_cursor == str(high + 1) and page.ceiling == str(high + 1)
    assert type(page).model_validate_json(page.model_dump_json()) == page
    events = service.read_scope_events("reader", protect=lambda _: None)
    assert events.events[0].sequence == str(high + 1)
    assert decode_cursor(events.resume_cursor, binding, EventPosition).position == str(high + 1)
    missing = encode_cursor(binding, RunPosition(position="0" * 64))
    assert service.list_runs("reader", after=missing, protect=lambda _: None).runs[0].run_id == run.run_id
    beyond = encode_cursor(binding, RunPosition(position="f" * 64))
    final = service.list_runs("reader", after=beyond, protect=lambda _: None)
    assert not final.runs and not final.has_more and final.end_cursor == beyond


@pytest.mark.parametrize("method", ["list_runs", "read_scope_events"])
@pytest.mark.parametrize("damage", ["missing", "legacy", "corrupt", "changed"])
def test_each_page_rechecks_binding_inside_control_transaction(driver, method, damage):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import ScopeMissing
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
        CorruptScopeBinding,
        ScopeMigrationRequired,
    )

    s, binding, service = paging_fixture(driver)
    with s._transaction() as tx:
        s._lock(tx)
        query = "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
        if damage == "missing":
            tx.run(query + "DELETE c", **s.scope).consume()
        elif damage == "legacy":
            tx.run(query + "REMOVE c.scope_binding_json, c.scope_binding_sha256", **s.scope).consume()
        else:
            changed = binding.model_copy(update={"authority_id": "other-authority"})
            tx.run(
                query + "SET c.scope_binding_json=$body, c.scope_binding_sha256=$digest",
                **s.scope,
                body="{}" if damage == "corrupt" else changed.body_json,
                digest=changed.body_sha256,
            ).consume()
    with pytest.raises(
        {
            "missing": ScopeMissing,
            "legacy": ScopeMigrationRequired,
            "corrupt": CorruptScopeBinding,
            "changed": SubmissionConflict,
        }[damage]
    ):
        getattr(service, method)("reader", protect=lambda _: pytest.fail("unverified binding escaped"))


@pytest.mark.parametrize("method", ["list_runs_window", "read_scope_events_window"])
def test_page_query_execution_advancement_and_unknown_cleanup_are_not_empty_or_corrupt(driver, method):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown

    s, binding, _ = paging_fixture(driver)
    s.admit("one", "{}", "{}", 10)
    for target in ("scope_binding_json", "SHOW INDEXES", "AS row"):
        for advance in (False, True):
            for error in (ValueError, TypeError):
                for close in (False, True):
                    failure = error("actual page driver failure")
                    observed = Neo4jWorkflowStore(
                        inspection_driver(
                            driver, lambda *a: None, fetch_size=2, fault=(target, advance, failure, close)
                        ),
                        database=s.database,
                        **s.scope,
                    )
                    with pytest.raises((ValueError, TypeError, OutcomeUnknown)) as caught:
                        getattr(observed, method)(binding, first=1)
                    assert type(caught.value) is OutcomeUnknown if close else caught.value is failure
    for failure in ("commit", "cleanup"):
        observed = Neo4jWorkflowStore(
            inspection_driver(driver, lambda *a: None, fetch_size=2, fault=failure), database=s.database, **s.scope
        )
        with pytest.raises(OutcomeUnknown):
            getattr(observed, method)(binding, first=1)


@pytest.mark.parametrize("method", ["list_runs", "read_scope_events"])
@pytest.mark.parametrize("veto", [False, True])
def test_page_whole_public_envelope_reject_only_protection_is_after_close(driver, method, veto):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    s, binding, _ = paging_fixture(driver)
    s.admit("one", "{}", "{}", 10)
    closed = []
    observed = Neo4jWorkflowStore(
        inspection_driver(driver, lambda q, p: closed.append(q) if q == "SESSION_CLOSED" else None, fetch_size=101),
        database=s.database,
        **s.scope,
    )
    service = WorkflowService(
        observed, SimpleNamespace(require_read=lambda _: None), None, validate_support=None, read_scope=binding
    )

    def protect(body):
        assert closed == ["SESSION_CLOSED"]
        assert set(body) >= {"binding", "floor", "ceiling", "has_more", "semantics"}
        if veto:
            raise PermissionError("veto page")
        body["binding"]["authority_id"] = "mutation"

    with pytest.raises((ValueError, PermissionError)):
        getattr(service, method)("reader", protect=protect)


@pytest.mark.parametrize("method", ["list_runs", "read_scope_events"])
def test_one_page_control_lock_prevents_mixed_boundary_and_rows(driver, method):
    from threading import Event
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    s, binding, _ = paging_fixture(driver)
    original = s.admit("original", "{}", "{}", 10)
    held, attempted, release = Event(), Event(), Event()

    def hold(query, params):
        if "scope_binding_json" in query:
            held.set()
            assert release.wait(4)

    reader = Neo4jWorkflowStore(inspection_driver(driver, hold, fetch_size=101), database=s.database, **s.scope)
    writer = Neo4jWorkflowStore(
        inspection_driver(
            driver, lambda q, p: attempted.set() if "lock_anchor" in q else None, fetch_size=None, before=True
        ),
        database=s.database,
        **s.scope,
    )
    service = WorkflowService(
        reader, SimpleNamespace(require_read=lambda _: None), None, validate_support=None, read_scope=binding
    )
    try:
        with ThreadPoolExecutor() as pool:
            reading = pool.submit(getattr(service, method), "reader", protect=lambda _: None)
            assert held.wait(3)
            writing = pool.submit(writer.admit, "later", "{}", "{}", 10)
            assert attempted.wait(3) and not writing.done()
            release.set()
            page, added = reading.result(timeout=4), writing.result(timeout=4)
    finally:
        release.set()
    assert page.ceiling == "1"
    assert [r.run_id for r in getattr(page, "runs" if method == "list_runs" else "events")] == [original.run_id]
    assert added.event_cursor == 2


def test_page_requires_existing_online_unique_backing_index_without_ddl(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import SchemaMissing

    s, binding, service = paging_fixture(driver)
    with driver.session(database=s.database) as session:
        session.run("DROP CONSTRAINT arena_workflow_run").consume()
        try:
            with pytest.raises(SchemaMissing):
                service.list_runs("reader", protect=lambda _: None)
            with pytest.raises(SchemaMissing):
                service.read_scope_events("reader", protect=lambda _: None)
        finally:
            ddl = next(q for q in s.schema_requirements() if q.startswith("CREATE CONSTRAINT arena_workflow_run "))
            session.run(ddl).consume()
            session.run("CALL db.awaitIndexes(30)").consume()


def test_fresh_bound_client_bootstraps_live_runs_and_tails_first_watermark(driver):
    import hashlib
    import json
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowProfileAdmin, WorkflowService
    from isaaclab_arena.tests.test_environment_workflow_service import contract
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    assert hasattr(WorkflowService, "read_scope_events"), "bounded retained event pages missing"
    s, binding = binding_fixture(driver)
    authority = SimpleNamespace(require_read=lambda _: None, require_admin=lambda _: None)
    admin = WorkflowProfileAdmin(s, authority)
    admin.initialize_scope("operator", binding, protect=lambda _: None)
    admin.register_profile(
        "operator", ProfileRegistration.model_validate(profile_registration()), protect=lambda _: None
    )
    keys = sorted(
        ["LiteralSyntheticId"] + [f"synthetic-{n}" for n in range(20)],
        key=lambda key: hashlib.sha256(
            json.dumps(
                [binding.deployment_id, binding.workspace_id, key], ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest(),
    )
    request = canonical_json(contract())
    admitted = [s.admit(k, request, request, 100) for k in keys[1:]]
    # A distinct client knows no run IDs; discover only through authenticated pages.
    fresh = Neo4jWorkflowStore(driver, database=s.database, **s.scope)
    service = WorkflowService(fresh, authority, None, validate_support=None, read_scope=binding)
    first = service.list_runs("reader", first=1, protect=lambda _: None)
    watermark = first.event_watermark
    found = list(first.runs)
    page = first
    while page.has_more:
        page = service.list_runs("reader", first=3, after=page.end_cursor, protect=lambda _: None)
        found.extend(page.runs)
    assert [r.run_id for r in found] == sorted(r.run_id for r in admitted)
    for row in found:
        inspection = service.read_run_inspection("reader", row.run_id, protect=lambda _: None)
        assert inspection.intent.submission.operation_id == row.operation_id
    empty = service.list_runs("reader", after=page.end_cursor, protect=lambda _: None)
    assert empty.runs == () and not empty.has_more and empty.end_cursor == page.end_cursor
    late = s.admit(keys[0], request, request, 100)
    assert late.run_id < first.runs[0].run_id
    events = service.read_scope_events("reader", first=1, after=watermark, protect=lambda _: None)
    assert [e.run_id for e in events.events] == [late.run_id]
    assert events.events[0].operation_id == keys[0]
    assert events.events[0].source_id is None and events.events[0].command_kind is None
    assert events.events[0].sequence == str(len(admitted) + 1)
    assert events.coverage == "retained" and events.semantics == "live_keyset"
    poll = service.read_scope_events("reader", after=events.resume_cursor, protect=lambda _: None)
    assert poll.events == () and not poll.has_more and poll.resume_cursor == events.resume_cursor
    oldest = service.read_scope_events("reader", first=1, protect=lambda _: None)
    assert oldest.events[0].sequence == "1" and oldest.has_more
    second = service.read_scope_events("reader", first=1, after=oldest.resume_cursor, protect=lambda _: None)
    assert second.events[0].sequence == "2" and second.has_more


def candidate_page_fixture(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        candidate_record,
    )

    s, binding, service = paging_fixture(driver)
    run = s.admit("candidate-discovery", "{}", "{}", 10)
    candidates = [
        candidate_record(run.run_id, {"synthetic": n}, source_id=f"source-{n}")
        for n in range(3)
    ]
    with s._transaction() as tx:
        s._lock(tx)
        for c in candidates:
            s._scene_node(
                tx,
                "ArenaWorkflowCandidate",
                c.candidate_id,
                c.model_dump_json(),
                run.run_id,
            )
    return s, binding, service, run, sorted(candidates, key=lambda c: c.candidate_id)


def test_candidate_discovery_is_compact_parent_owned_live_and_empty(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    assert hasattr(
        WorkflowService, "list_scene_candidates"
    ), "candidate discovery missing"
    s, binding, service, run, candidates = candidate_page_fixture(driver)
    screens = []
    page = service.list_scene_candidates(
        "reader", run.run_id, first=1, protect=screens.append
    )
    assert page.binding == binding and page.run_id == run.run_id
    assert page.semantics == "live_keyset" and page.has_more
    assert page.floor == "0" and page.ceiling == "1"
    assert [r.model_dump() for r in page.candidates] == [
        dict(candidate_id=candidates[0].candidate_id, run_id=run.run_id)
    ]
    second = service.list_scene_candidates(
        "reader", run.run_id, first=2, after=page.end_cursor, protect=screens.append
    )
    assert [r.candidate_id for r in second.candidates] == [
        c.candidate_id for c in candidates[1:]
    ]
    assert not second.has_more
    empty = service.list_scene_candidates(
        "reader", run.run_id, after=second.end_cursor, protect=screens.append
    )
    assert (
        empty.candidates == ()
        and empty.end_cursor == second.end_cursor
        and not empty.has_more
    )
    parent = s.admit("no-candidates", "{}", "{}", 10)
    empty = service.list_scene_candidates(
        "reader", parent.run_id, protect=screens.append
    )
    assert empty.candidates == () and empty.end_cursor is None
    missing = service.list_scene_candidates("reader", "f" * 64, protect=screens.append)
    assert missing is None and screens[-1] is None
    assert screens[0] == page.model_dump(mode="json")


@pytest.mark.parametrize(
    "damage",
    [
        "missing_owner",
        "wrong_owner",
        "foreign_owner",
        "extra_owner",
        "wrong_owner_label",
        "duplicate",
        "duplicate_other_run",
        "repeated_owner",
        "foreign_extra_owner",
    ],
)
def test_candidate_window_validates_lookahead_identity_and_all_ownership_edges(
    driver, damage
):
    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        CorruptPage,
    )

    s, binding, service, run, candidates = candidate_page_fixture(driver)
    other = s.admit("other-parent", "{}", "{}", 10)
    target = candidates[
        1
    ].candidate_id  # Must validate the row not returned for first=1.
    with driver.session(database=s.database) as session:
        query = "MATCH (n:ArenaWorkflowCandidate {deployment_id:$deployment_id, workspace_id:$workspace_id, record_id:$id}) "
        if damage.startswith("duplicate"):
            session.run(
                query
                + "CREATE (copy:ArenaWorkflowCandidate) SET copy=properties(n), copy.run_id=$run",
                **s.scope,
                id=target,
                run=other.run_id if damage == "duplicate_other_run" else run.run_id,
            ).consume()
        else:
            if damage not in ("extra_owner", "repeated_owner", "foreign_extra_owner"):
                session.run(
                    query + "MATCH ()-[edge:HAS_SCENE_RECORD]->(n) DELETE edge",
                    **s.scope,
                    id=target,
                ).consume()
            if damage in ("wrong_owner", "extra_owner", "repeated_owner"):
                session.run(
                    query
                    + "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run}) "
                    "CREATE (r)-[:HAS_SCENE_RECORD]->(n)",
                    **s.scope,
                    id=target,
                    run=run.run_id if damage == "repeated_owner" else other.run_id,
                ).consume()
            elif damage in (
                "foreign_owner",
                "wrong_owner_label",
                "foreign_extra_owner",
            ):
                label = (
                    "NotAWorkflowRun"
                    if damage == "wrong_owner_label"
                    else "ArenaWorkflowRun"
                )
                session.run(
                    query + "CREATE (r:" + label + ")-[:HAS_SCENE_RECORD]->(n) "
                    "SET r.run_id=$run, r.deployment_id=$deployment_id, r.workspace_id=$owner_scope",
                    **s.scope,
                    id=target,
                    run=run.run_id,
                    owner_scope=(
                        s.scope["workspace_id"]
                        if damage == "wrong_owner_label"
                        else "foreign"
                    ),
                ).consume()
    screened = []
    with pytest.raises(CorruptPage, match="^Invalid retained page$"):
        service.list_scene_candidates(
            "reader", run.run_id, first=1, protect=screened.append
        )
    assert not screened


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation_id", "other-key"),
        ("operation_id", ["secret"]),
        ("operation_id", "s" * 129),
        ("version", 1.0),
        ("version", True),
        ("version", 0),
        ("event_cursor", 1.0),
        ("event_cursor", 999),
        ("state", "secret"),
        ("phase", None),
    ],
)
def test_candidate_discovery_rejects_corrupt_exact_parent_metadata(
    driver, field, value
):
    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        CorruptPage,
    )

    s, binding, service, run, candidates = candidate_page_fixture(driver)
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run}) "
            f"SET r.{field}=$value",
            **s.scope,
            run=run.run_id,
            value=value,
        ).consume()
    screened = []
    with pytest.raises(CorruptPage, match="^Invalid retained page$"):
        service.list_scene_candidates("reader", run.run_id, protect=screened.append)
    assert not screened


def test_candidate_profiles_bound_upstream_work_with_dense_same_scope_other_runs(
    driver,
):
    import json
    from pathlib import Path

    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        CandidatePosition,
    )

    s, binding, service, run, candidates = candidate_page_fixture(driver)
    other = s.admit("dense-other-parent", "{}", "{}", 10)
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run}) "
            "UNWIND range(0, 1500) AS i CREATE (n:ArenaWorkflowCandidate), (f:ArenaWorkflowCandidate), "
            "(r)-[:HAS_SCENE_RECORD]->(:ArenaWorkflowEvidence) "
            "SET n.deployment_id=$deployment_id, n.workspace_id=$workspace_id, n.run_id=$other, "
            "n.record_id=$between+toString(i), "
            "f.deployment_id=$deployment_id, f.workspace_id=$foreign, f.run_id=$run, f.record_id=n.record_id",
            **s.scope,
            run=run.run_id,
            other=other.run_id,
            foreign=uuid.uuid4().hex,
            between=candidates[0].candidate_id,
        ).consume()
    queries = []
    observed = Neo4jWorkflowStore(
        inspection_driver(driver, lambda q, p: queries.append((q, p)), fetch_size=2),
        database=s.database,
        **s.scope,
    )
    observed.list_scene_candidates_window(binding, run.run_id, first=1)
    observed.list_scene_candidates_window(
        binding,
        run.run_id,
        first=1,
        after=CandidatePosition(run_id=run.run_id, position=candidates[0].candidate_id),
    )
    selected = [
        (q, p)
        for q, p in queries
        if q.endswith(" AS row")
        or " AS parent LIMIT 2" in q
        or " AS key LIMIT 2" in q
        or " AS valid LIMIT 2" in q
    ]
    assert len(selected) == 12
    proofs = []

    def flatten(node):
        return [node] + [
            n for child in node.get("children", []) for n in flatten(child)
        ]

    with driver.session(database=s.database) as session:
        for q, p in selected:
            result = session.run("PROFILE " + q, **p)
            records = list(result)
            plan = result.consume().profile
            proofs.append(dict(query=q, parameters=p, plan=plan))
            Path("/evidence/candidate-query-plans.json").write_text(
                json.dumps(proofs, default=str)
            )
            assert 0 < len(records) <= 2
    for proof in proofs:
        plan = proof["plan"]
        nodes = flatten(plan)
        assert not any(
            any(word in n["operatorType"] for word in ("Scan", "Sort", "Top"))
            for n in nodes
        ), plan
        assert max(n.get("rows", 0) for n in nodes) <= 2, plan
        assert sum(n.get("dbHits", 0) for n in nodes) < 100, plan
        assert any(
            "IndexSeek" in n["operatorType"] or "ByElementIdSeek" in n["operatorType"]
            for n in nodes
        ), plan


@pytest.mark.parametrize(
    "index", ["arena_workflow_candidate_run_record", "arena_workflow_history_candidate"]
)
def test_candidate_read_requires_both_indexes_without_lazy_ddl(driver, index):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
        SchemaMissing,
    )

    s, binding, service, run, candidates = candidate_page_fixture(driver)
    with driver.session(database=s.database) as session:
        session.run("DROP INDEX " + index).consume()
        try:
            with pytest.raises(SchemaMissing):
                service.list_scene_candidates(
                    "reader",
                    run.run_id,
                    protect=lambda _: pytest.fail("unchecked page"),
                )
            assert not session.run(
                "SHOW INDEXES YIELD name WHERE name=$name RETURN name", name=index
            ).data()
        finally:
            for ddl in s.schema_requirements():
                session.run(ddl).consume()
            session.run("CALL db.awaitIndexes(30)").consume()


def check_joined_candidate_discovery(reader, run_id, first_watermark, original, child):
    before = reader.read_run_inspection("local", run_id, protect=lambda _: None)
    cursor, refs = None, []
    for _ in range(3):
        page = reader.list_scene_candidates(
            "local", run_id, first=1, after=cursor, protect=lambda _: None
        )
        refs.extend(page.candidates)
        cursor = page.end_cursor
        if not page.has_more:
            break
    assert len(refs) == 2 and {r.candidate_id for r in refs} == {
        original.candidate_id,
        child.candidate_id,
    }
    values = {
        r.candidate_id: reader.read_scene_candidate(
            "local", r.candidate_id, protect=lambda _: None
        )
        for r in refs
    }
    assert values[original.candidate_id].candidate == original
    assert values[child.candidate_id].candidate == child
    assert child.parent_id == child.original_id == original.candidate_id
    assert (
        reader.read_scene_candidate("local", child.parent_id, protect=lambda _: None)
        == values[original.candidate_id]
    )
    empty = reader.list_scene_candidates(
        "local", run_id, after=cursor, protect=lambda _: None
    )
    assert not empty.candidates and empty.end_cursor == cursor
    assert reader.read_run_inspection("local", run_id, protect=lambda _: None) == before
    assert reader.read_scope_events(
        "local", after=first_watermark, protect=lambda _: None
    ).events


@pytest.mark.parametrize(
    "payload",
    [None, "unknown retained codec", "x" * 2105345],
    ids=["missing", "unknown", "oversize"],
)
def test_candidate_discovery_does_not_hydrate_or_validate_payload(driver, payload):
    from isaaclab_arena.agentic_environment_generation.workflow.queries import (
        CorruptSceneRecord,
    )

    s, binding, service, run, candidates = candidate_page_fixture(driver)
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (n:ArenaWorkflowCandidate {deployment_id:$deployment_id, workspace_id:$workspace_id, record_id:$id}) "
            "SET n.payload=$payload",
            **s.scope,
            id=candidates[0].candidate_id,
            payload=payload,
        ).consume()
    page = service.list_scene_candidates(
        "reader", run.run_id, first=1, protect=lambda _: None
    )
    assert page.candidates[0].candidate_id == candidates[0].candidate_id
    with pytest.raises(CorruptSceneRecord):
        service.read_scene_candidate(
            "reader",
            page.candidates[0].candidate_id,
            protect=lambda _: pytest.fail("corrupt payload escaped"),
        )


def test_candidate_foreign_parent_is_identical_to_absent_parent(driver):
    s, binding, service, run, candidates = candidate_page_fixture(driver)
    other, _, _ = paging_fixture(driver)
    foreign = other.admit("foreign", "{}", "{}", 1)
    screened = []
    for key in (foreign.run_id, "f" * 64):
        assert (
            service.list_scene_candidates("reader", key, protect=screened.append)
            is None
        )
    assert screened == [None, None]


def test_candidate_invalid_string_lookahead_is_rejected_not_truncated(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        CorruptPage,
    )

    s, binding, service, run, candidates = candidate_page_fixture(driver)
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (n:ArenaWorkflowCandidate {deployment_id:$deployment_id, workspace_id:$workspace_id, record_id:$id}) "
            "SET n.record_id=$bad",
            **s.scope,
            id=candidates[1].candidate_id,
            bad=candidates[0].candidate_id + "x",
        ).consume()
    with pytest.raises(CorruptPage):
        service.list_scene_candidates(
            "reader",
            run.run_id,
            first=1,
            protect=lambda _: pytest.fail("bad lookahead escaped"),
        )


@pytest.mark.parametrize("veto", [False, True])
def test_candidate_protection_sees_only_whole_reference_page_after_close(driver, veto):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    s, binding, _, run, candidates = candidate_page_fixture(driver)
    closed, queries = [], []

    def visit(q, p):
        (closed if q == "SESSION_CLOSED" else queries).append(q)

    observed = Neo4jWorkflowStore(
        inspection_driver(driver, visit, fetch_size=101), database=s.database, **s.scope
    )
    service = WorkflowService(
        observed,
        SimpleNamespace(require_read=lambda _: None),
        None,
        validate_support=None,
        read_scope=binding,
    )

    def protect(body):
        assert closed == ["SESSION_CLOSED"]
        assert len(body["candidates"]) == 3
        assert all(set(r) == {"run_id", "candidate_id"} for r in body["candidates"])
        if veto:
            raise PermissionError("veto")
        body["candidates"][0]["candidate_id"] = "a" * 64

    with pytest.raises(PermissionError if veto else ValueError):
        service.list_scene_candidates("reader", run.run_id, protect=protect)
    assert all("properties(" not in q and "payload" not in q for q in queries)
    assert not any(
        word in q for q in queries for word in ("CREATE ", "MERGE ", "CALL ")
    )


def test_candidate_query_advancement_commit_and_close_faults_keep_original_classification(
    driver,
):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
        OutcomeUnknown,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    s, binding, _, run, candidates = candidate_page_fixture(driver)
    for target in (
        "scope_binding_json",
        "SHOW INDEXES",
        "AS parent",
        "AS row",
        "AS key LIMIT 2",
        "AS valid",
    ):
        for advance in (False, True):
            for error in (ValueError, TypeError):
                for close in (False, True):
                    failure = error("candidate driver failure")
                    observed = Neo4jWorkflowStore(
                        inspection_driver(
                            driver,
                            lambda *a: None,
                            fetch_size=2,
                            fault=(target, advance, failure, close),
                        ),
                        database=s.database,
                        **s.scope,
                    )
                    service = WorkflowService(
                        observed,
                        SimpleNamespace(require_read=lambda _: None),
                        None,
                        validate_support=None,
                        read_scope=binding,
                    )
                    with pytest.raises(
                        (ValueError, TypeError, OutcomeUnknown)
                    ) as caught:
                        service.list_scene_candidates(
                            "reader",
                            run.run_id,
                            first=1,
                            protect=lambda _: pytest.fail("fault escaped"),
                        )
                    assert (
                        type(caught.value) is OutcomeUnknown
                        if close
                        else caught.value is failure
                    )
    for failure in ("commit", "cleanup"):
        observed = Neo4jWorkflowStore(
            inspection_driver(driver, lambda *a: None, fetch_size=2, fault=failure),
            database=s.database,
            **s.scope,
        )
        service = WorkflowService(
            observed,
            SimpleNamespace(require_read=lambda _: None),
            None,
            validate_support=None,
            read_scope=binding,
        )
        with pytest.raises(OutcomeUnknown):
            service.list_scene_candidates(
                "reader",
                run.run_id,
                first=1,
                protect=lambda _: pytest.fail("unclosed page escaped"),
            )


def test_candidate_read_atomicity_blocks_cooperative_parent_and_candidate_writer(
    driver,
):
    from threading import Event

    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        candidate_record,
    )

    s, binding, service, run, candidates = candidate_page_fixture(driver)
    held, attempted, release = Event(), Event(), Event()

    def hold(q, p):
        if "AS parent" in q:
            held.set()
            assert release.wait(4)

    observed = Neo4jWorkflowStore(
        inspection_driver(driver, hold, fetch_size=101), database=s.database, **s.scope
    )
    writer = Neo4jWorkflowStore(
        inspection_driver(
            driver,
            lambda q, p: attempted.set() if "lock_anchor" in q else None,
            fetch_size=None,
            before=True,
        ),
        database=s.database,
        **s.scope,
    )
    new = candidate_record(run.run_id, {"synthetic": "later"}, source_id="later")

    def write():
        with writer._transaction() as tx:
            writer._lock(tx)
            writer._scene_node(
                tx,
                "ArenaWorkflowCandidate",
                new.candidate_id,
                new.model_dump_json(),
                run.run_id,
            )
            writer._event(tx, run.run_id, "CandidateRetained", new.candidate_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(
            observed.list_scene_candidates_window, binding, run.run_id
        )
        try:
            assert held.wait(4)
            writing = pool.submit(write)
            assert attempted.wait(4) and not writing.done()
        finally:
            release.set()
        before = reading.result(timeout=5)
        writing.result(timeout=5)
    assert len(before.candidates) == 3 and before.ceiling == "1"
    after = s.list_scene_candidates_window(binding, run.run_id)
    assert len(after.candidates) == 4 and after.ceiling == "2"


def test_candidate_selected_stream_is_drained_before_identity_queries(driver):
    import json
    from pathlib import Path

    s, binding, _, run, candidates = candidate_page_fixture(driver)
    stats = dict(yielded=0, exhausted=False, queued=0, checks=0)

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Result(Proxy):
        def __iter__(self):
            for record in self.real:
                stats["yielded"] += 1
                stats["queued"] = max(stats["queued"], len(self.real._record_buffer))
                assert len(json.dumps(dict(record)).encode()) < 512
                yield record
            stats["exhausted"] = True

    class Transaction(Proxy):
        def run(self, q, **params):
            if "AS key LIMIT 2" in q or "AS valid LIMIT 2" in q:
                assert stats["exhausted"] and stats["yielded"] == 2
                stats["checks"] += 1
            result = self.real.run(q, **params)
            return Result(result) if q.endswith(" AS row") else result

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Transaction(self.real.begin_transaction(**kwargs))

    class Driver(Proxy):
        def session(self, **kwargs):
            assert kwargs["fetch_size"] == 2
            return Session(self.real.session(**kwargs))

    observed = Neo4jWorkflowStore(Driver(driver), database=s.database, **s.scope)
    window = observed.list_scene_candidates_window(binding, run.run_id, first=1)
    assert len(window.candidates) == 2
    assert (
        stats["exhausted"]
        and stats["yielded"] == 2
        and stats["checks"] == 4
        and stats["queued"] <= 1
    )
    Path("/evidence/candidate-buffering.json").write_text(json.dumps(stats))


def test_decision_coverage_is_fresh_admission_only_not_exact_replay(driver):
    s, binding, service = paging_fixture(driver)
    run = s.admit("coverage", "{}", "{}", 2)
    query = "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run}) "
    with driver.session(database=s.database) as session:
        assert (
            session.run(query + "RETURN r.decision_coverage AS marker", **s.scope, run=run.run_id).single()["marker"]
            == 1
        )
        session.run(query + "REMOVE r.decision_coverage", **s.scope, run=run.run_id).consume()
        before = session.run(query + "RETURN properties(r) AS row", **s.scope, run=run.run_id).single()["row"]
        assert s.admit("coverage", "{}", "{}", 0) == run
        assert s.get_run(run.run_id) == run
        assert session.run(query + "RETURN properties(r) AS row", **s.scope, run=run.run_id).single()["row"] == before


def decision_writer_fixture(
    driver, *, legacy=False, operation="decision-writers", decision_id="foreground-initial-generation", fixture=None
):
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import GenerationReservation
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.tests.test_environment_workflow_decisions import authority, generation_contract

    s, binding, service = paging_fixture(driver) if fixture is None else fixture
    s.clock = lambda: 100.0
    contract = generation_contract()
    auth = authority(s, contract)
    reservation = GenerationReservation(
        model_calls=1, model_tokens=100, cost_ceiling_usd=1.0, runtime_allowance_seconds=5.0
    )
    run = s.admit(operation, "{}", canonical_json(contract), 10)
    if legacy:
        with driver.session(database=s.database) as session:
            session.run(
                "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run}) REMOVE r.decision_coverage",
                **s.scope,
                run=run.run_id,
            ).consume()
    intent = s.reserve_generation(run.run_id, 1, decision_id, auth, reservation, readiness=readiness(contract, auth))
    return s, binding, service, run, intent, auth, reservation


@pytest.mark.parametrize("legacy", [False, True])
def test_both_decision_writers_stamp_membership_without_changing_payload_or_legacy_run(driver, legacy):
    import hashlib
    import json
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        SceneDecision,
        candidate_record,
        identity,
    )

    s, binding, service, run, intent, auth, reservation = decision_writer_fixture(driver, legacy=legacy)
    candidate = candidate_record(run.run_id, {"synthetic": True}, source_id="source")
    decision = SceneDecision(action="stop", reason="budget_exhausted")
    current = s.get_run(run.run_id)
    with s._transaction() as tx:
        s._lock(tx)
        s._scene_decide(tx, current, candidate, decision, None)
    scene_id = identity(run.run_id, current.version, "scene-decision")
    query = "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run})-[:HAS_DECISION]->(d) "
    with driver.session(database=s.database) as session:
        rows = session.run(
            query + "RETURN properties(d) AS d, r.decision_coverage AS marker ORDER BY d.decision_id",
            **s.scope,
            run=run.run_id,
        ).data()
        values = {row["d"]["decision_id"]: row["d"] for row in rows}
        assert len(values) == 2
        for key, kind in ((scene_id, "scene_decision"), ("foreground-initial-generation", "generation_reservation")):
            value = values[key]
            assert value.get("run_id") == run.run_id, "atomic decision membership missing"
            assert value.get("record_kind") == kind
            assert type(value.get("membership_codec")) is int and value["membership_codec"] == 1
        assert all(row["marker"] == (None if legacy else 1) for row in rows)
        assert values[scene_id]["payload"] == decision.model_dump_json()
        payload = json.dumps(
            ["foreground-initial-generation", auth.model_dump(mode="json"), reservation.model_dump(mode="json")],
            sort_keys=True,
            separators=(",", ":"),
        )
        assert values["foreground-initial-generation"]["payload"] == payload
        assert (
            intent
            == hashlib.sha256(
                json.dumps([s.database, s.scope, run.run_id, 1, "generation"], sort_keys=True).encode()
            ).hexdigest()
        )
        # Markerless retained decision replay is observation, not a migration.
        session.run(query + "REMOVE d.run_id, d.record_kind, d.membership_codec", **s.scope, run=run.run_id).consume()
        before = session.run(
            query + "RETURN properties(d) AS d ORDER BY d.decision_id", **s.scope, run=run.run_id
        ).data()
        snapshot = s.snapshot()
        assert (
            s.reserve_generation(run.run_id, 1, "foreground-initial-generation", auth, reservation, readiness=None)
            == intent
        )
        assert (
            session.run(query + "RETURN properties(d) AS d ORDER BY d.decision_id", **s.scope, run=run.run_id).data()
            == before
        )
        assert s.snapshot() == snapshot


def test_decision_page_discovers_both_families_and_distinguishes_unknown_coverage(driver):
    from isaaclab_arena.agentic_environment_generation.workflow import paging
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import SceneDecision, candidate_record

    assert hasattr(WorkflowService, "list_decisions"), "run-owned decision discovery missing"
    s, binding, service, run, _, _, _ = decision_writer_fixture(driver)
    candidate = candidate_record(run.run_id, {"synthetic": True}, source_id="source")
    with s._transaction() as tx:
        s._lock(tx)
        s._scene_decide(
            tx,
            s._run(tx, "run_id", run.run_id),
            candidate,
            SceneDecision(action="stop", reason="budget_exhausted"),
            None,
        )
    page = service.list_decisions("reader", run.run_id, first=1, protect=lambda _: None)
    assert type(page) is paging.DecisionPage and page.has_more and len(page.decisions) == 1
    assert page.decisions[0].record_kind == "scene_decision"
    assert page.binding == binding and page.run_id == run.run_id
    second = service.list_decisions("reader", run.run_id, first=1, after=page.end_cursor, protect=lambda _: None)
    assert [r.model_dump() for r in second.decisions] == [
        dict(run_id=run.run_id, decision_id="foreground-initial-generation", record_kind="generation_reservation")
    ]
    assert not second.has_more
    empty = service.list_decisions("reader", run.run_id, after=second.end_cursor, protect=lambda _: None)
    assert empty.decisions == () and empty.end_cursor == second.end_cursor
    vacant = s.admit("vacant", "{}", "{}", 10)
    empty = service.list_decisions("reader", vacant.run_id, protect=lambda _: None)
    assert empty.decisions == () and empty.end_cursor is None
    assert service.list_decisions("reader", "f" * 64, protect=lambda _: None) is None
    other, _, _ = paging_fixture(driver)
    foreign = other.admit("foreign", "{}", "{}", 1)
    assert service.list_decisions("reader", foreign.run_id, protect=lambda _: None) is None
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) REMOVE r.decision_coverage",
            **s.scope,
        ).consume()
    for key in (run.run_id, vacant.run_id):
        value = service.list_decisions("reader", key, protect=lambda _: None)
        assert type(value) is paging.DecisionCoverageUnavailable
        assert value.reason == "coverage_provenance_unavailable" and value.run_id == key
        assert "decisions" not in value.model_dump()


def test_decision_coverage_rejects_malformed_and_unsupported_markers_distinctly(driver):
    import traceback

    s, binding, service = paging_fixture(driver)
    run = s.admit("invalid-coverage", "{}", "{}", 1)
    with driver.session(database=s.database) as session:
        for marker in (True, 1.0, [1], "secret-marker", "s" * 10000, 2, -1):
            session.run(
                "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run}) SET r.decision_coverage=$marker",
                **s.scope,
                run=run.run_id,
                marker=marker,
            ).consume()
            with pytest.raises(ValueError) as caught:
                service.list_decisions("reader", run.run_id, protect=lambda _: pytest.fail("invalid coverage escaped"))
            assert type(caught.value).__name__ == (
                "UnsupportedDecisionCoverage" if type(marker) is int else "CorruptPage"
            )
            assert str(caught.value) == (
                "Unsupported decision coverage version" if type(marker) is int else "Invalid retained page"
            )
            assert "secret-marker" not in "".join(traceback.format_exception(caught.value))


def decision_page_fixture(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        SceneDecision,
        candidate_record,
        identity,
    )

    s, binding, service, run, _, _, _ = decision_writer_fixture(driver)
    candidate = candidate_record(run.run_id, {"synthetic": True}, source_id="source")
    current = s.get_run(run.run_id)
    with s._transaction() as tx:
        s._lock(tx)
        s._scene_decide(tx, current, candidate, SceneDecision(action="stop", reason="budget_exhausted"), None)
    ids = sorted([identity(run.run_id, current.version, "scene-decision"), "foreground-initial-generation"])
    return s, binding, service, run, ids


def test_decision_membership_selected_and_lookahead_are_strict(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.paging import CorruptPage

    s, binding, service, run, ids = decision_page_fixture(driver)
    with driver.session(database=s.database) as session:
        for target in (0, 1):
            for field, value in (
                ("membership_codec", None),
                ("membership_codec", True),
                ("membership_codec", 1.0),
                ("membership_codec", 2),
                ("membership_codec", [1]),
                ("membership_codec", "s" * 10000),
                ("record_kind", None),
                ("record_kind", "other"),
                ("record_kind", ["scene_decision"]),
            ):
                query = "MATCH (n:ArenaWorkflowDecision {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run, decision_id:$id}) "
                params = dict(s.scope, run=run.run_id, id=ids[target])
                original = session.run(query + f"RETURN n.{field} AS value", **params).single()["value"]
                try:
                    session.run(query + f"SET n.{field}=$value", **params, value=value).consume()
                    with pytest.raises(CorruptPage, match="^Invalid retained page$"):
                        service.list_decisions(
                            "reader", run.run_id, first=1, protect=lambda _: pytest.fail("corrupt membership escaped")
                        )
                finally:
                    session.run(query + f"SET n.{field}=$value", **params, value=original).consume()
                assert len(service.list_decisions("reader", run.run_id, protect=lambda _: None).decisions) == 2


@pytest.mark.parametrize(
    "damage",
    [
        "missing_owner",
        "wrong_owner",
        "foreign_owner",
        "extra_owner",
        "wrong_owner_label",
        "duplicate",
        "duplicate_other_kind",
        "repeated_owner",
        "foreign_extra_owner",
    ],
)
def test_decision_window_validates_lookahead_identity_and_all_ownership_edges(driver, damage):
    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        CorruptPage,
    )

    s, binding, service, run, decisions = decision_page_fixture(driver)
    other = s.admit("other-parent", "{}", "{}", 10)
    target = decisions[1]  # Must validate the row not returned for first=1.
    with driver.session(database=s.database) as session:
        query = "MATCH (n:ArenaWorkflowDecision {deployment_id:$deployment_id, workspace_id:$workspace_id, decision_id:$id}) "
        if damage.startswith("duplicate"):
            session.run(
                query
                + "CREATE (copy:ArenaWorkflowDecision) SET copy=properties(n), copy.run_id=$run, copy.record_kind=$kind",
                **s.scope,
                id=target,
                kind="scene_decision" if damage == "duplicate_other_kind" else "generation_reservation",
                run=run.run_id,
            ).consume()
        else:
            if damage not in ("extra_owner", "repeated_owner", "foreign_extra_owner"):
                session.run(
                    query + "MATCH ()-[edge:HAS_DECISION]->(n) DELETE edge",
                    **s.scope,
                    id=target,
                ).consume()
            if damage in ("wrong_owner", "extra_owner", "repeated_owner"):
                session.run(
                    query
                    + "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run}) "
                    "CREATE (r)-[:HAS_DECISION]->(n)",
                    **s.scope,
                    id=target,
                    run=run.run_id if damage == "repeated_owner" else other.run_id,
                ).consume()
            elif damage in (
                "foreign_owner",
                "wrong_owner_label",
                "foreign_extra_owner",
            ):
                label = "NotAWorkflowRun" if damage == "wrong_owner_label" else "ArenaWorkflowRun"
                session.run(
                    query + "CREATE (r:" + label + ")-[:HAS_DECISION]->(n) "
                    "SET r.run_id=$run, r.deployment_id=$deployment_id, r.workspace_id=$owner_scope",
                    **s.scope,
                    id=target,
                    run=run.run_id,
                    owner_scope=(s.scope["workspace_id"] if damage == "wrong_owner_label" else "foreign"),
                ).consume()
    screened = []
    with pytest.raises(CorruptPage, match="^Invalid retained page$"):
        service.list_decisions("reader", run.run_id, first=1, protect=screened.append)
    assert not screened


def _decision_diagnostic_write(phase, **values):
    """Persist bounded synthetic diagnostics before the next hazardous step."""
    import json
    from pathlib import Path
    import time

    value = dict(phase=phase, observed_unix_ns=time.time_ns(), **values)
    raw = json.dumps(value, sort_keys=True)
    assert len(raw.encode()) <= 32768
    with Path(f"/evidence/decision-oom-{phase}.json").open("w") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _decision_diagnostic_snapshot(session, phase, *, retained=False):
    """Observe only the admitted disposable DB; never export property values."""
    _decision_diagnostic_write(phase, status="observation_started")
    values = {}
    try:
        if retained:
            # Five fixed whole-DB scalar scans, not production bounded-query proof.
            # size(toStringOrNull(...)) counts characters, NOT UTF-8/storage bytes;
            # arrays are excluded. Only payload/scene_json are size proxies.
            values["retained"] = dict(session.run(
                "MATCH (n) RETURN count(n) AS nodes, "
                "sum(CASE WHEN n:ArenaWorkflowDecision THEN 1 ELSE 0 END) AS decisions, "
                "sum(CASE WHEN n:ArenaWorkflowRun THEN 1 ELSE 0 END) AS runs, "
                "sum(CASE WHEN n:ArenaWorkflowCandidate THEN 1 ELSE 0 END) AS candidates, "
                "sum(CASE WHEN n:ArenaWorkflowEvidence THEN 1 ELSE 0 END) AS evidence, "
                "sum(CASE WHEN n:ArenaWorkflowEvidence AND n.workspace_id IS NULL "
                "THEN 1 ELSE 0 END) AS unscoped_evidence, "
                "sum(CASE WHEN n:ArenaExecutionIntent THEN 1 ELSE 0 END) AS intents, "
                "sum(coalesce(size(toStringOrNull(n.payload)),0)) AS payload_scalar_text_chars, "
                "sum(coalesce(size(toStringOrNull(n.scene_json)),0)) AS scene_json_scalar_text_chars, "
                "sum(CASE WHEN n:ArenaExecutionIntent AND size(toStringOrNull(n.scene_json))=65000 "
                "THEN 1 ELSE 0 END) AS intents_with_65000_scene_json_chars, "
                "sum(CASE WHEN n:ArenaWorkflowDecision THEN "
                "coalesce(size(toStringOrNull(n.payload)),0) ELSE 0 END) AS decision_payload_scalar_text_chars"
            ).single())
            _decision_diagnostic_write(phase, status="retained_observed", **values)
        values["index"] = session.run(
            "SHOW INDEXES YIELD name, state, populationPercent "
            "WHERE name='arena_workflow_decision_run_id' "
            "RETURN name, state, populationPercent LIMIT 1"
        ).data()
        _decision_diagnostic_write(phase, status="observation_complete", **values)
    except Exception as error:
        # Diagnostics must not preempt the existing index-restoration finally.
        _decision_diagnostic_write(phase, status="observation_failed", error_type=type(error).__name__, **values)


def _decision_oversize_diagnostic(session, s, run, decisions, payload):
    """Count the unchanged mutation MATCH and EXPLAIN, never PROFILE, its write."""
    query = (
        "MATCH (n:ArenaWorkflowDecision {deployment_id:$deployment_id, workspace_id:$workspace_id, decision_id:$id}) "
    )
    values: dict = dict(payload_chars=len(payload), payload_utf8_bytes=len(payload.encode("utf-8")),
                  expected_total_matches=1, expected_current_parent_matches=1)
    phase = "oversize-mutation-match"
    _decision_diagnostic_write(phase, status="match_observation_started", **values)
    try:
        values["matches"] = dict(session.run(
            query + "RETURN count(n) AS total_matches, "
            "sum(CASE WHEN n.run_id=$run THEN 1 ELSE 0 END) AS current_parent_matches",
            **s.scope, id=decisions[0], run=run.run_id,
        ).single())
        _decision_diagnostic_write(phase, status="match_observed_before_explain", **values)
        plan = session.run("EXPLAIN " + query + "SET n.payload=$payload",
                           **s.scope, id=decisions[0], payload=payload).consume().plan
        pending, operators = [plan], []
        while pending and len(operators) < 64:
            node = pending.pop()
            operators.append(dict(operator=node["operatorType"],
                                  estimated_rows=node.get("args", {}).get("EstimatedRows")))
            pending.extend(node.get("children", []))
        values["explain_operators"] = operators
        values["explain_truncated"] = bool(pending)
        _decision_diagnostic_write(phase, status="explain_complete_before_mutation", **values)
    except Exception as error:
        _decision_diagnostic_write(phase, status="observation_failed", error_type=type(error).__name__, **values)


def _decision_density_teardown(driver, s, run_id, foreign, primary_error):
    """Delete only this fresh fixture's scopes and parent-witnessed unscoped nodes."""
    values: dict = dict(local_scope=dict(s.scope), foreign_scope=dict(s.scope, workspace_id=foreign), run_id=run_id)
    try:
        _decision_diagnostic_write("density-teardown", status="cleanup_started", **values)
        with driver.session(database=s.database) as session:
            # Capture ownership before removing HAS_DECISION edges. These nodes
            # keep their original unscoped, property-free domain state throughout.
            ids = [
                row["id"]
                for row in session.run(
                    "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, "
                    "workspace_id:$workspace_id, run_id:$run})-[:HAS_DECISION]->(e:ArenaWorkflowEvidence) "
                    "WHERE e.deployment_id IS NULL AND e.workspace_id IS NULL "
                    "RETURN elementId(e) AS id LIMIT 1502",
                    **s.scope,
                    run=run_id,
                )
            ]
            assert len(ids) <= 1501 and len(set(ids)) == len(ids)
            values["unscoped_witness_count"] = len(ids)
            # Bounded metadata only, split to retain the diagnostic file bound.
            for start in range(0, len(ids), 250):
                _decision_diagnostic_write(
                    f"density-owned-ids-{start // 250}",
                    status="parent_edge_witness",
                    **values,
                    element_ids=ids[start : start + 250],
                )
            result = session.run(
                "MATCH (e) WHERE elementId(e) IN $ids DETACH DELETE e",
                ids=ids,
            ).consume()
            values["unscoped_deleted"] = result.counters.nodes_deleted
            values["unscoped_relationships_deleted"] = result.counters.relationships_deleted
            _decision_diagnostic_write("density-teardown", status="unscoped_delete_consumed", **values)
            result = session.run(
                "MATCH (n {deployment_id:$deployment_id}) WHERE n.workspace_id IN $workspaces "
                "DETACH DELETE n",
                deployment_id=s.scope["deployment_id"],
                workspaces=[s.scope["workspace_id"], foreign],
            ).consume()
            values["scoped_deleted"] = result.counters.nodes_deleted
            values["scoped_relationships_deleted"] = result.counters.relationships_deleted
            _decision_diagnostic_write("density-teardown", status="scoped_delete_consumed", **values)
            values["remaining_unscoped_ids"] = session.run(
                "MATCH (e) WHERE elementId(e) IN $ids RETURN elementId(e) AS id LIMIT 1", ids=ids
            ).data()
            values["remaining_scoped_ids"] = session.run(
                "MATCH (n {deployment_id:$deployment_id}) WHERE n.workspace_id IN $workspaces "
                "RETURN elementId(n) AS id LIMIT 1",
                deployment_id=s.scope["deployment_id"],
                workspaces=[s.scope["workspace_id"], foreign],
            ).data()
            _decision_diagnostic_write("density-teardown", status="absence_observed", **values)
            assert not values["remaining_unscoped_ids"] and not values["remaining_scoped_ids"]
            assert values["unscoped_deleted"] == len(ids)
            _decision_diagnostic_write("density-teardown", status="exact_targets_absent", **values)
    except Exception as error:
        # Preserve a primary assertion/transport failure; never claim DB cleanup
        # when unavailable. The runner still owns authoritative container cleanup.
        try:
            _decision_diagnostic_write(
                "density-teardown", status="cleanup_failed", error_type=type(error).__name__, **values
            )
        except Exception:
            # A failed evidence write must not replace the original test failure.
            if primary_error is None:
                raise
        if primary_error is None:
            raise
        primary_error.add_note(f"Exact-owned density teardown failed: {type(error).__name__}")


def test_decision_profiles_bound_upstream_work_with_dense_same_scope_other_runs(
    driver,
):
    import json
    from pathlib import Path
    import sys

    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        DecisionPosition,
    )

    s, binding, service, run, decisions = decision_page_fixture(driver)
    foreign = uuid.uuid4().hex
    try:
        other = s.admit("dense-other-parent", "{}", "{}", 10)
        with driver.session(database=s.database) as session:
            _decision_diagnostic_snapshot(session, "density-before-create", retained=True)
            session.run(
                "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run}) "
                "UNWIND range(0, 1500) AS i CREATE (n:ArenaWorkflowDecision), (f:ArenaWorkflowDecision), "
                "(r)-[:HAS_DECISION]->(:ArenaWorkflowEvidence), (g:ArenaWorkflowDecision) "
                "SET g.deployment_id=$deployment_id, g.workspace_id=$workspace_id, "
                "g.run_id='unrelated-'+toString(i), g.decision_id='foreground-initial-generation' "
                "SET n.deployment_id=$deployment_id, n.workspace_id=$workspace_id, n.run_id=$other, "
                "n.decision_id=$between+toString(i), "
                "f.deployment_id=$deployment_id, f.workspace_id=$foreign, f.run_id=$run, f.decision_id=n.decision_id",
                **s.scope,
                run=run.run_id,
                other=other.run_id,
                foreign=foreign,
                between=decisions[0],
            ).consume()
            _decision_diagnostic_snapshot(session, "density-after-create", retained=True)
        queries = []
        observed = Neo4jWorkflowStore(
            inspection_driver(driver, lambda q, p: queries.append((q, p)), fetch_size=2),
            database=s.database,
            **s.scope,
        )
        observed.list_decisions_window(binding, run.run_id, first=1)
        observed.list_decisions_window(
            binding,
            run.run_id,
            first=1,
            after=DecisionPosition(run_id=run.run_id, position=decisions[0]),
        )
        selected = [
            (q, p)
            for q, p in queries
            if q.endswith(" AS row") or " AS parent," in q or " AS key LIMIT 2" in q or " AS valid LIMIT 2" in q
        ]
        assert len(selected) == 10
        proofs = []

        def flatten(node):
            return [node] + [n for child in node.get("children", []) for n in flatten(child)]

        with driver.session(database=s.database) as session:
            _decision_diagnostic_write(
                "density-before-profile", status="original_profiles_starting", queries=len(selected)
            )
            for q, p in selected:
                result = session.run("PROFILE " + q, **p)
                records = list(result)
                plan = result.consume().profile
                proofs.append(dict(query=q, parameters=p, plan=plan))
                Path("/evidence/decision-query-plans.json").write_text(json.dumps(proofs, default=str))
                assert 0 < len(records) <= 2
            _decision_diagnostic_snapshot(session, "density-after-profile", retained=True)
        for proof in proofs:
            plan = proof["plan"]
            nodes = flatten(plan)
            assert not any(any(word in n["operatorType"] for word in ("Scan", "Sort", "Top")) for n in nodes), plan
            assert max(n.get("rows", 0) for n in nodes) <= 2, plan
            assert sum(n.get("dbHits", 0) for n in nodes) < 100, plan
            assert any("IndexSeek" in n["operatorType"] or "ByElementIdSeek" in n["operatorType"] for n in nodes), plan
    finally:
        _decision_density_teardown(driver, s, run.run_id, foreign, sys.exc_info()[1])


@pytest.mark.parametrize("index", ["arena_workflow_decision_run_id"])
def test_decision_read_requires_both_indexes_without_lazy_ddl(driver, index):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
        SchemaMissing,
    )

    s, binding, service, run, decisions = decision_page_fixture(driver)
    with driver.session(database=s.database) as session:
        _decision_diagnostic_snapshot(session, "index-before-drop")
        session.run("DROP INDEX " + index).consume()
        try:
            _decision_diagnostic_snapshot(session, "index-after-drop")
            with pytest.raises(SchemaMissing):
                service.list_decisions(
                    "reader",
                    run.run_id,
                    protect=lambda _: pytest.fail("unchecked page"),
                )
            assert not session.run("SHOW INDEXES YIELD name WHERE name=$name RETURN name", name=index).data()
        finally:
            _decision_diagnostic_snapshot(session, "index-before-recreate")
            for ddl in s.schema_requirements():
                session.run(ddl).consume()
            _decision_diagnostic_snapshot(session, "index-after-recreate")
            _decision_diagnostic_write("index-before-await", status="original_await_starting", timeout_seconds=30)
            session.run("CALL db.awaitIndexes(30)").consume()
            _decision_diagnostic_snapshot(session, "index-after-await", retained=True)


def test_decision_discovery_rejects_corrupt_exact_parent_metadata(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.paging import CorruptPage

    s, binding, service, run, decisions = decision_page_fixture(driver)
    with driver.session(database=s.database) as session:
        for field, value in (
            ("operation_id", "other-key"),
            ("operation_id", ["secret"]),
            ("operation_id", "s" * 129),
            ("version", 1.0),
            ("version", True),
            ("version", 0),
            ("event_cursor", 1.0),
            ("event_cursor", 999),
            ("state", "secret"),
            ("phase", None),
        ):
            query = (
                "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run}) "
            )
            params = dict(s.scope, run=run.run_id)
            original = session.run(query + f"RETURN r.{field} AS value", **params).single()["value"]
            try:
                session.run(query + f"SET r.{field}=$value", **params, value=value).consume()
                with pytest.raises(CorruptPage, match="^Invalid retained page$"):
                    service.list_decisions("reader", run.run_id, protect=lambda _: pytest.fail("bad parent escaped"))
            finally:
                session.run(query + f"SET r.{field}=$value", **params, value=original).consume()
            assert len(service.list_decisions("reader", run.run_id, protect=lambda _: None).decisions) == 2


@pytest.mark.parametrize(
    "payload",
    [None, "unknown retained codec", "x" * 2105345],
    ids=["missing", "unknown", "oversize"],
)
def test_decision_discovery_does_not_hydrate_or_validate_payload(driver, payload):
    from isaaclab_arena.agentic_environment_generation.workflow.queries import (
        CorruptSceneRecord,
    )

    s, binding, service, run, decisions = decision_page_fixture(driver)
    with driver.session(database=s.database) as session:
        if isinstance(payload, str) and len(payload) == 2105345:
            _decision_diagnostic_snapshot(session, "oversize-before-mutation", retained=True)
            _decision_oversize_diagnostic(session, s, run, decisions, payload)
        session.run(
            "MATCH (n:ArenaWorkflowDecision {deployment_id:$deployment_id, workspace_id:$workspace_id, decision_id:$id}) "
            "SET n.payload=$payload",
            **s.scope,
            id=decisions[0],
            payload=payload,
        ).consume()
        if isinstance(payload, str) and len(payload) == 2105345:
            _decision_diagnostic_write("oversize-after-mutation", status="original_write_consumed")
    page = service.list_decisions("reader", run.run_id, first=1, protect=lambda _: None)
    assert page.decisions[0].decision_id == decisions[0]
    with pytest.raises(CorruptSceneRecord):
        service.read_scene_decision(
            "reader",
            page.decisions[0].decision_id,
            protect=lambda _: pytest.fail("corrupt payload escaped"),
        )


def test_decision_query_advancement_commit_and_close_faults_keep_original_classification(
    driver,
):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
        OutcomeUnknown,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    s, binding, _, run, decisions = decision_page_fixture(driver)
    for target in (
        "scope_binding_json",
        "SHOW INDEXES",
        "AS parent",
        "AS row",
        "AS key LIMIT 2",
        "AS valid",
    ):
        for advance in (False, True):
            for error in (ValueError, TypeError):
                for close in (False, True):
                    failure = error("decision driver failure")
                    observed = Neo4jWorkflowStore(
                        inspection_driver(
                            driver,
                            lambda *a: None,
                            fetch_size=2,
                            fault=(target, advance, failure, close),
                        ),
                        database=s.database,
                        **s.scope,
                    )
                    service = WorkflowService(
                        observed,
                        SimpleNamespace(require_read=lambda _: None),
                        None,
                        validate_support=None,
                        read_scope=binding,
                    )
                    with pytest.raises((ValueError, TypeError, OutcomeUnknown)) as caught:
                        service.list_decisions(
                            "reader",
                            run.run_id,
                            first=1,
                            protect=lambda _: pytest.fail("fault escaped"),
                        )
                    assert type(caught.value) is OutcomeUnknown if close else caught.value is failure
    for failure in ("commit", "cleanup"):
        observed = Neo4jWorkflowStore(
            inspection_driver(driver, lambda *a: None, fetch_size=2, fault=failure),
            database=s.database,
            **s.scope,
        )
        service = WorkflowService(
            observed,
            SimpleNamespace(require_read=lambda _: None),
            None,
            validate_support=None,
            read_scope=binding,
        )
        with pytest.raises(OutcomeUnknown):
            service.list_decisions(
                "reader",
                run.run_id,
                first=1,
                protect=lambda _: pytest.fail("unclosed page escaped"),
            )


def test_decision_selected_stream_is_drained_before_identity_queries(driver):
    import json
    from pathlib import Path

    s, binding, _, run, decisions = decision_page_fixture(driver)
    stats = dict(yielded=0, exhausted=False, queued=0, checks=0)

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Result(Proxy):
        def __iter__(self):
            for record in self.real:
                stats["yielded"] += 1
                stats["queued"] = max(stats["queued"], len(self.real._record_buffer))
                assert len(json.dumps(dict(record)).encode()) < 512
                yield record
            stats["exhausted"] = True

    class Transaction(Proxy):
        def run(self, q, **params):
            if "AS key LIMIT 2" in q or "AS valid LIMIT 2" in q:
                assert stats["exhausted"] and stats["yielded"] == 2
                stats["checks"] += 1
            result = self.real.run(q, **params)
            return Result(result) if q.endswith(" AS row") else result

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Transaction(self.real.begin_transaction(**kwargs))

    class Driver(Proxy):
        def session(self, **kwargs):
            assert kwargs["fetch_size"] == 2
            return Session(self.real.session(**kwargs))

    observed = Neo4jWorkflowStore(Driver(driver), database=s.database, **s.scope)
    window = observed.list_decisions_window(binding, run.run_id, first=1)
    assert len(window.decisions) == 2
    assert stats["exhausted"] and stats["yielded"] == 2 and stats["checks"] == 4 and stats["queued"] <= 1
    Path("/evidence/decision-buffering.json").write_text(json.dumps(stats))


@pytest.mark.parametrize("veto", [False, True])
def test_decision_protection_sees_only_whole_reference_page_after_close(driver, veto):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    s, binding, _, run, decisions = decision_page_fixture(driver)
    closed, queries = [], []

    def visit(q, p):
        (closed if q == "SESSION_CLOSED" else queries).append(q)

    observed = Neo4jWorkflowStore(inspection_driver(driver, visit, fetch_size=101), database=s.database, **s.scope)
    service = WorkflowService(
        observed,
        SimpleNamespace(require_read=lambda _: None),
        None,
        validate_support=None,
        read_scope=binding,
    )

    def protect(body):
        assert closed == ["SESSION_CLOSED"]
        assert len(body["decisions"]) == 2
        assert all(set(r) == {"run_id", "decision_id", "record_kind"} for r in body["decisions"])
        if veto:
            raise PermissionError("veto")
        body["decisions"][0]["decision_id"] = "a" * 64

    with pytest.raises(PermissionError if veto else ValueError):
        service.list_decisions("reader", run.run_id, protect=protect)
    assert all("properties(" not in q and "payload" not in q for q in queries)
    assert not any(word in q for q in queries for word in ("CREATE ", "MERGE ", "CALL "))


def test_decision_identity_is_run_qualified_even_when_generation_collides_with_scene(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.queries import CorruptSceneRecord

    s, binding, service, first, ids = decision_page_fixture(driver)
    # Two real generation writers legitimately reuse a general Identifier.
    _, _, _, second, _, _, _ = decision_writer_fixture(driver, operation="second", fixture=(s, binding, service))
    # A hash-shaped generation Identifier can also collide with a different run's scene ID.
    _, _, _, third, _, _, _ = decision_writer_fixture(
        driver, operation="third", decision_id=ids[0], fixture=(s, binding, service)
    )
    for run, expected in ((first, ids), (second, [ids[1]]), (third, [ids[0]])):
        page = service.list_decisions("reader", run.run_id, protect=lambda _: None)
        assert [r.decision_id for r in page.decisions] == expected
        assert all(r.run_id == run.run_id for r in page.decisions)
    with pytest.raises(CorruptSceneRecord, match="ambiguous retained scene identity"):
        service.read_scene_decision("reader", ids[0], protect=lambda _: pytest.fail("ambiguous scene escaped"))
    # The repeated general Identifier is ambiguous before payload interpretation too.
    with pytest.raises(CorruptSceneRecord, match="ambiguous retained scene identity"):
        service.read_scene_decision("reader", ids[1], protect=lambda _: pytest.fail("ambiguous generation escaped"))


def check_joined_decision_discovery(reader, run_id, historical):
    cursor, refs = None, []
    for _ in range(6):
        page = reader.list_decisions("local", run_id, first=1, after=cursor, protect=lambda _: None)
        refs.extend(page.decisions)
        cursor = page.end_cursor
        if not page.has_more:
            break
    assert len(refs) == 5
    assert [r.decision_id for r in refs] == sorted(r.decision_id for r in refs)
    generations = [r for r in refs if r.record_kind == "generation_reservation"]
    assert len(generations) == 1 and generations[0].decision_id == "generation"
    assert reader.read_scene_decision("local", generations[0].decision_id, protect=lambda _: None) is None
    scene_ids = {r.decision_id for r in refs if r.record_kind == "scene_decision"}
    assert scene_ids == {e.source_id for e in historical}
    values = [reader.read_scene_decision("local", key, protect=lambda _: None) for key in scene_ids]
    selected = {d.decision.action: d for d in values if d.selected_assessment_id is not None}
    assert set(selected) == {"repair", "accept"}
    assessments = [
        reader.read_scene_assessment("local", selected[k].selected_assessment_id, protect=lambda _: None)
        for k in ("repair", "accept")
    ]
    assert [a.assessment.status for a in assessments] == ["not_established", "established"]
    evidence = [reader.read_scene_evidence("local", a.evidence_id, protect=lambda _: None) for a in assessments]
    assert evidence[0].observation.cohort != evidence[1].observation.cohort
    candidates = [
        reader.read_scene_candidate("local", e.candidate_id, protect=lambda _: None).candidate for e in evidence
    ]
    assert candidates[1].parent_id == candidates[0].candidate_id
    assert all(r.run_id == run_id for r in refs)


def test_decision_reader_holds_coverage_parent_and_selection_with_cooperative_writer(driver):
    from threading import Event
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import SceneDecision, candidate_record

    s, binding, service, run, ids = decision_page_fixture(driver)
    held, attempted, release = Event(), Event(), Event()

    def hold(q, p):
        if "AS parent" in q:
            held.set()
            assert release.wait(4)

    observed = Neo4jWorkflowStore(inspection_driver(driver, hold, fetch_size=101), database=s.database, **s.scope)
    writer = Neo4jWorkflowStore(
        inspection_driver(
            driver, lambda q, p: attempted.set() if "lock_anchor" in q else None, fetch_size=None, before=True
        ),
        database=s.database,
        **s.scope,
    )
    writer.clock = lambda: 100.0
    candidate = candidate_record(run.run_id, {"synthetic": "later"}, source_id="later")

    def write():
        with writer._transaction() as tx:
            writer._lock(tx)
            writer._scene_decide(
                tx,
                writer._run(tx, "run_id", run.run_id),
                candidate,
                SceneDecision(action="stop", reason="budget_exhausted"),
                None,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(observed.list_decisions_window, binding, run.run_id)
        try:
            assert held.wait(4)
            writing = pool.submit(write)
            assert attempted.wait(4) and not writing.done()
        finally:
            release.set()
        before = reading.result(timeout=5)
        writing.result(timeout=5)
    after = s.list_decisions_window(binding, run.run_id)
    assert len(before.decisions) == 2 and before.ceiling == "3"
    assert len(after.decisions) == 3 and after.ceiling == "4"


@pytest.mark.parametrize("result_kind", ["absent", "unavailable"])
@pytest.mark.parametrize("fault", [None, "commit", "cleanup"])
def test_decision_nonpage_envelopes_are_screened_only_after_close_and_ack(driver, result_kind, fault):
    from types import SimpleNamespace
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown

    s, binding, _, run, ids = decision_page_fixture(driver)
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run}) REMOVE r.decision_coverage",
            **s.scope,
            run=run.run_id,
        ).consume()
    closed = []
    observed = Neo4jWorkflowStore(
        inspection_driver(
            driver, lambda q, p: closed.append(q) if q == "SESSION_CLOSED" else None, fetch_size=101, fault=fault
        ),
        database=s.database,
        **s.scope,
    )
    service = WorkflowService(
        observed, SimpleNamespace(require_read=lambda _: None), None, validate_support=None, read_scope=binding
    )
    screened = []

    def protect(body):
        assert closed == ["SESSION_CLOSED"]
        screened.append(body)

    key = "f" * 64 if result_kind == "absent" else run.run_id
    if fault:
        with pytest.raises(OutcomeUnknown):
            service.list_decisions("reader", key, protect=protect)
        assert not screened
    else:
        value = service.list_decisions("reader", key, protect=protect)
        assert screened == [None if value is None else value.model_dump(mode="json")]


def test_decision_old_run_with_both_new_families_stays_unavailable(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import SceneDecision, candidate_record

    s, binding, service, run, _, _, _ = decision_writer_fixture(driver, legacy=True)
    candidate = candidate_record(run.run_id, {"synthetic": True}, source_id="source")
    with s._transaction() as tx:
        s._lock(tx)
        s._scene_decide(
            tx,
            s._run(tx, "run_id", run.run_id),
            candidate,
            SceneDecision(action="stop", reason="budget_exhausted"),
            None,
        )
    assert (
        service.list_decisions("reader", run.run_id, protect=lambda _: None).reason == "coverage_provenance_unavailable"
    )


def test_decision_page_retains_full_width_counters_and_identifier_bound(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.paging import MAX_COUNTER, CorruptPage

    s, binding, service, run, ids = decision_page_fixture(driver)
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) SET c.sequence=$value WITH c MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run}) SET r.version=$value, r.event_cursor=$value",
            **s.scope,
            run=run.run_id,
            value=MAX_COUNTER,
        ).consume()
        page = service.list_decisions("reader", run.run_id, protect=lambda _: None)
        assert page.ceiling == str(MAX_COUNTER)
        session.run(
            "MATCH (n:ArenaWorkflowDecision {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run, decision_id:$id}) SET n.decision_id=$value",
            **s.scope,
            run=run.run_id,
            id=ids[1],
            value="z" * 128,
        ).consume()
        assert (
            service.list_decisions("reader", run.run_id, protect=lambda _: None).decisions[-1].decision_id == "z" * 128
        )
        session.run(
            "MATCH (n:ArenaWorkflowDecision {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$run, decision_id:$id}) SET n.decision_id=$value",
            **s.scope,
            run=run.run_id,
            id="z" * 128,
            value="z" * 129,
        ).consume()
    with pytest.raises(CorruptPage):
        service.list_decisions("reader", run.run_id, first=1, protect=lambda _: pytest.fail("bad lookahead escaped"))
