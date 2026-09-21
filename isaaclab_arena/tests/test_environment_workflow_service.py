# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Application composition contracts; every external port is synthetic here."""

import json

import pytest

from isaaclab_arena.agentic_environment_generation.workflow.contracts import parse_contract
from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate, DependencyResult


@pytest.mark.parametrize("operation", ["initialize_scope", "initialize_artifacts", "verify_current_resources"])
@pytest.mark.parametrize("denial", ["admin", "read_only", "missing_protect", "mutating_protect", "veto"])
def test_scope_admin_authorization_and_public_screen_before_io(operation, denial, tmp_path):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.admin import WorkflowScopeAdmin
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding
    from isaaclab_arena.tests.test_environment_workflow_store import scope_binding_body

    calls = []

    class NoIO:
        def __getattr__(self, name):
            pytest.fail("admin denial reached IO: " + name)

    def authorize(principal):
        calls.append(("admin", principal))
        if denial == "admin":
            raise PermissionError("admin denied")

    def protect(body):
        calls.append("protect")
        if denial == "mutating_protect":
            body["authority_id"] = "changed"
        elif denial == "veto":
            raise PermissionError("public veto")

    authority = (
        SimpleNamespace(require_read=lambda _: None)
        if denial == "read_only"
        else SimpleNamespace(require_admin=authorize)
    )
    admin = WorkflowScopeAdmin(NoIO(), authority)
    kwargs = dict(protect=None if denial == "missing_protect" else protect)
    if operation != "initialize_scope":
        kwargs["root"] = tmp_path / "untouched"
        if operation == "initialize_artifacts":
            kwargs["create"] = True
        else:
            kwargs["required_profiles"] = ()
    error = AttributeError if denial == "read_only" else PermissionError if denial in ("admin", "veto") else ValueError
    with pytest.raises(error):
        getattr(admin, operation)("operator", ScopeBinding.model_validate(scope_binding_body()), **kwargs)
    assert not (tmp_path / "untouched").exists()
    assert calls == (
        []
        if denial == "read_only"
        else [("admin", "operator")] + ([] if denial in ("admin", "missing_protect") else ["protect"])
    )


@pytest.mark.parametrize("case", ["denied", "invalid_id", "missing_protection", "invalid_permission", "missing"])
def test_joined_inspection_service_denial_precedes_store_and_effects(case):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []

    def authorize(principal):
        calls.append("read")
        if case == "denied":
            raise PermissionError("private-read-authority-sentinel")

    def lookup(run_id):
        calls.append("lookup")
        return None

    service = WorkflowService(
        SimpleNamespace(get_run_inspection=lookup), SimpleNamespace(require_read=authorize), None, validate_support=None
    )
    kwargs = dict(
        protect=None if case == "missing_protection" else lambda v: calls.append(("protect", v)),
        check_action_permission=1 if case == "invalid_permission" else None,
    )
    if case == "missing":
        assert service.read_run_inspection("reader", "missing", **kwargs) is None
        assert calls == ["read", "lookup", ("protect", None)]
    else:
        with pytest.raises(PermissionError if case == "denied" else ValueError) as caught:
            service.read_run_inspection("reader", "bad id" if case == "invalid_id" else "missing", **kwargs)
        import traceback

        assert "private-read-authority-sentinel" not in "".join(
            traceback.format_exception(caught.type, caught.value, caught.tb)
        )
        assert calls == ["read"]


@pytest.mark.parametrize(
    "case",
    [
        "read_denied",
        "missing_permission",
        "permission_denied",
        "absent_eligibility",
        "malformed",
        "unknown_read",
        "query_read",
    ],
)
def test_resume_service_fails_closed_before_callbacks_or_admission(case):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []

    def read(principal):
        calls.append("read")
        if case == "read_denied":
            raise PermissionError("read denied")

    def lookup(key):
        calls.append("lookup")
        if case == "unknown_read":
            raise OutcomeUnknown("unknown")
        if case == "query_read":
            raise ValueError("query error")

    def permission(*args):
        calls.append("permission")
        if case == "permission_denied":
            raise PermissionError("resume denied")

    def preview(run_id):
        calls.append("preview")
        return SimpleNamespace(
            selection=SimpleNamespace(branch="generation"),
            run=SimpleNamespace(version=1, contract_json=contract().model_dump_json()),
        )

    service = WorkflowService(
        SimpleNamespace(get_resume_receipt=lookup, preview_resume=preview),
        SimpleNamespace(require_read=read),
        None,
        validate_support=None,
    )
    with pytest.raises(
        OutcomeUnknown
        if case == "unknown_read"
        else PermissionError if case in {"read_denied", "permission_denied"} else ValueError
    ):
        service.admit_resume(
            "reader",
            "key",
            dict(runId="run", expectedVersion=True if case == "malformed" else 1, renewAuthorization=False),
            check_resume=None if case == "missing_permission" else permission,
            check_eligibility=None,
            protect=lambda v: None,
        )
    expected = ["read"]
    if case not in {"read_denied", "malformed"}:
        expected.append("lookup")
    if case in {"permission_denied", "absent_eligibility"}:
        expected.extend(["preview", "permission"])
    assert calls == expected


@pytest.mark.parametrize("raw", ['"private-contract-sentinel"', '{"private-contract-sentinel":', 17])
def test_resume_service_retained_contract_decode_is_static(raw):
    import traceback
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []
    service = WorkflowService(
        SimpleNamespace(
            get_resume_receipt=lambda key: None,
            preview_resume=lambda run: SimpleNamespace(
                run=SimpleNamespace(version=1, contract_json=raw),
                selection=SimpleNamespace(branch="generation"),
            ),
        ),
        SimpleNamespace(require_read=lambda p: None),
        None,
        validate_support=None,
    )
    with pytest.raises(ValueError) as caught:
        service.admit_resume(
            "reader",
            "resume",
            dict(runId="run", expectedVersion=1, renewAuthorization=False),
            check_resume=lambda *a: calls.append("permission"),
            check_eligibility=lambda *a, **kw: calls.append("eligibility"),
            protect=lambda v: None,
        )
    assert str(caught.value) == "Invalid retained resume selection"
    assert "private-contract-sentinel" not in "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert calls == []


@pytest.mark.parametrize(
    "damage", ["false_codec", "float_version", "missing_event", "wrong_source", "refusal_event", "version_jump"]
)
def test_cancel_receipt_rejects_rehashed_structural_damage(damage):
    from isaaclab_arena.agentic_environment_generation.workflow.commands import (
        CancelReceipt,
        command_digest,
        command_json,
        make_cancel_receipt,
    )

    payload = command_json({"runId": "run"})
    valid = make_cancel_receipt(
        scope=dict(database="db", deployment_id="d", workspace_id="w"),
        operation_id="key",
        run_id="run",
        payload_json=payload,
        payload_digest=command_digest(payload),
        before_version=2**40,
        after_version=2**40 + 1,
        disposition="cancellation_requested",
        reason=None,
        first_local_stop=dict(delivery="delivered", remote_effects="unknown", durable_cancellation="unconfirmed"),
        events=[dict(sequence=2**40, kind="CancellationRequested", source_id="run")],
    )
    body = valid.model_dump(mode="json")
    if damage == "false_codec":
        body["codec_version"] = True
    elif damage == "float_version":
        body["receipt_version"] = 1.0
    elif damage == "missing_event":
        body["events"] = []
    elif damage == "wrong_source":
        body["events"][0]["source_id"] = "other"
    elif damage == "refusal_event":
        body.update(disposition="refused", reason="inactive_run")
    else:
        body["after_version"] += 1
    body["receipt_digest"] = command_digest(command_json({k: v for k, v in body.items() if k != "receipt_digest"}))
    with pytest.raises(ValueError):
        CancelReceipt.model_validate(body)


@pytest.mark.parametrize("kind", ["submission", "run_intent"])
@pytest.mark.parametrize("case", ["missing", "denied", "bad_id", "absent", "replace", "transport", "unknown", "query_error"])
def test_admission_intent_service_authenticates_before_io_and_screens_none(kind, case):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []
    failure = {"transport": OSError("transport"), "unknown": OutcomeUnknown("unknown"),
               "query_error": ValueError("query error")}.get(case)

    def auth(principal):
        assert principal == "reader"
        calls.append("auth")
        if case == "denied":
            raise PermissionError("denied")

    def read(identity):
        assert identity == "literal.Id:1"
        calls.append("io")
        if failure is not None:
            raise failure

    def protect(value):
        assert value is None
        calls.append("screen")
        return {} if case == "replace" else None

    store = SimpleNamespace(get_submission_inspection=read, get_run_intent=read)
    service = WorkflowService(store, SimpleNamespace(require_read=auth), None, validate_support=None)
    method = getattr(service, "read_" + kind)
    if case == "missing":
        assert method("reader", "literal.Id:1", protect=protect) is None
        assert calls == ["auth", "io", "screen"]
    else:
        error = PermissionError if case == "denied" else type(failure) if failure is not None else ValueError
        with pytest.raises(error) as caught:
            method("reader", " literal.Id:1" if case == "bad_id" else "literal.Id:1",
                   protect=None if case == "absent" else protect)
        if failure is not None:
            assert caught.value is failure
        assert calls == (["auth"] if case in {"denied", "bad_id", "absent"} else
                         ["auth", "io", "screen"] if case == "replace" else ["auth", "io"])


@pytest.mark.parametrize("kind", ["submission", "run_intent"])
@pytest.mark.parametrize("screen", ["allow", "mutate", "replace", "deny", "oversize"])
def test_admission_intent_service_detaches_freezes_and_screens_whole_view(kind, screen):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.queries import FrozenRunIntentView, FrozenSubmissionInspection, SceneReadScope
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    scope = SceneReadScope(database="db", deployment_id="d", workspace_id="w")
    admission = FrozenSubmissionInspection(
        scope=scope, kind="SUBMIT", operation_id="key", run_id="a" * 64,
        request_digest="b" * 64, accepted_contract_digest="c" * 64,
        digest_codec="sha256-canonical-json-utf8-v1", admitted_at=0.0,
        disposition="retained_admission", provenance="legacy_run_record", receipt_version=None, cause_id=None,
    )
    retained = admission if kind == "submission" else FrozenRunIntentView(
        scope=scope, run_id=admission.run_id, submission=admission, contract=contract(),
        state="pending", phase="dependency_readiness", run_version=1, event_cursor=0,
        intent_projection_revision="d" * 64,
    )
    if screen == "oversize":
        retained = retained.model_copy(update={"scope": SceneReadScope(database="界" * 800000, deployment_id="d", workspace_id="w")})
    calls = []

    def protect(value):
        calls.append(value)
        assert value == retained.model_dump(mode="json")
        if screen == "mutate":
            value["scope"]["workspace_id"] = "foreign"
        if screen == "replace":
            return {"redacted": True}
        if screen == "deny":
            raise PermissionError("denied")

    service = WorkflowService(SimpleNamespace(get_submission_inspection=lambda i: retained, get_run_intent=lambda i: retained),
                              SimpleNamespace(require_read=lambda p: None), None, validate_support=None)
    method = getattr(service, "read_" + kind)
    if screen == "allow":
        result = method("reader", "key", protect=protect)
        assert result == retained and result is not retained and result.scope is not retained.scope
        with pytest.raises(ValueError):
            result.scope.workspace_id = "foreign"
    else:
        with pytest.raises(PermissionError if screen == "deny" else ValueError):
            method("reader", "key", protect=protect)
    assert retained.scope.workspace_id == "w"
    assert len(calls) == (0 if screen == "oversize" else 1)


@pytest.mark.parametrize("case", ["missing", "denied", "absent", "replace", "unavailable"])
def test_cleanup_read_authorizes_and_screens_absence(case):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import StoreUnavailable
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []

    def authorize(p):
        calls.append("authorize")
        if case == "denied":
            raise PermissionError("denied")

    def read(run_id):
        calls.append("io")
        if case == "unavailable":
            raise StoreUnavailable("unavailable")

    def protect(value):
        assert value is None
        calls.append("screen")
        if case == "replace":
            return {}
        return None

    service = WorkflowService(
        SimpleNamespace(get_run_cleanup=read), SimpleNamespace(require_read=authorize), None, validate_support=None
    )
    assert hasattr(service, "read_run_cleanup"), "authenticated cleanup read missing"
    if case == "missing":
        assert service.read_run_cleanup("reader", "run", protect=protect) is None
        assert calls == ["authorize", "io", "screen"]
    else:
        error = PermissionError if case == "denied" else StoreUnavailable if case == "unavailable" else ValueError
        with pytest.raises(error):
            service.read_run_cleanup("reader", "run", protect=None if case == "absent" else protect)
        assert calls[0] == "authorize"
        if case in ("denied", "absent"):
            assert calls == ["authorize"]


@pytest.mark.parametrize("screen", ["allow", "mutate", "replace", "deny"])
def test_cleanup_read_screens_detached_whole_frozen_view(screen):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.queries import RunCleanupView, SceneReadScope
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    retained = RunCleanupView(
        scope=SceneReadScope(database="db", deployment_id="d", workspace_id="w"),
        run_id="run",
        run_version=1,
        current_scope_owner=None,
        intents=(),
        projection_revision="a" * 64,
    )
    calls = []

    def read(run_id):
        assert run_id == "run" and calls == ["auth"]
        calls.append("io")
        return retained

    def protect(value):
        calls.append("screen")
        assert value == retained.model_dump(mode="json")
        if screen == "mutate":
            value["scope"]["workspace_id"] = "foreign"
        elif screen == "replace":
            return {"redacted": True}
        elif screen == "deny":
            raise PermissionError("denied public data")

    service = WorkflowService(
        SimpleNamespace(get_run_cleanup=read),
        SimpleNamespace(require_read=lambda p: calls.append("auth")),
        None,
        validate_support=None,
    )
    if screen == "allow":
        value = service.read_run_cleanup("reader", "run", protect=protect)
        assert value == retained and value is not retained
        with pytest.raises(ValueError):
            value.scope.workspace_id = "foreign"
    else:
        with pytest.raises(PermissionError if screen == "deny" else ValueError):
            service.read_run_cleanup("reader", "run", protect=protect)
    assert retained.scope.workspace_id == "w" and calls == ["auth", "io", "screen"]


@pytest.mark.parametrize("operation", ["register", "get", "list"])
@pytest.mark.parametrize("denied", [False, True])
def test_profile_admin_and_reads_authorize_before_io_and_screen(operation, denied):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow import service as api
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import (
        ProfileRegistration, profile_revision,
    )
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    assert hasattr(api, "WorkflowProfileAdmin"), "explicit profile administration is missing"
    calls = []
    registration = ProfileRegistration.model_validate(profile_registration())
    retained = profile_revision(registration)

    def authorize(principal):
        assert principal == "operator"
        calls.append("authorize")
        if denied:
            raise PermissionError("denied")

    def protect(value):
        calls.append("screen")

    def register(value, *, protect):
        calls.append("io")
        assert value == registration
        protect(retained.model_dump(mode="json"))
        return retained

    def read(*args):
        calls.append("io")
        return (retained,) if operation == "list" else retained

    def forbidden(*args, **kwargs):
        pytest.fail("profile metadata cannot resolve credentials, probe, or release")

    store = SimpleNamespace(register_profile=register, get_profile=read, list_profiles=read)
    authority = SimpleNamespace(require_admin=authorize, require_read=authorize, require_execute=forbidden)
    admin = api.WorkflowProfileAdmin(store, authority)
    service = api.WorkflowService(store, authority, SimpleNamespace(check=forbidden), validate_support=forbidden)
    assert calls == []

    def invoke():
        if operation == "register":
            return admin.register_profile("operator", registration, protect=protect)
        if operation == "get":
            return service.read_profile("operator", registration.profile_id, registration.revision, protect=protect)
        return service.list_profiles("operator", protect=protect)

    if denied:
        with pytest.raises(PermissionError):
            invoke()
        assert calls == ["authorize"]
    else:
        result = invoke()
        assert result == ((retained,) if operation == "list" else retained)
        assert calls[0:2] == ["authorize", "io"] and "screen" in calls[2:]
        with pytest.raises(ValueError):
            retained.registration.revision = 3


@pytest.mark.parametrize("operation", ["get", "list"])
@pytest.mark.parametrize("screen", ["absent", "mutate", "replace", "deny"])
def test_profile_read_protection_is_mandatory_reject_only(operation, screen):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration, profile_revision
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    retained = profile_revision(ProfileRegistration.model_validate(profile_registration()))
    calls = []

    def read(*args):
        calls.append("io")
        return (retained,) if operation == "list" else retained

    def protect(value):
        if screen == "mutate":
            (value[0] if operation == "list" else value)["schema_version"] = 2
        if screen == "replace":
            return {"redacted": True}
        if screen == "deny":
            raise ValueError("private-data rejected")

    service = WorkflowService(SimpleNamespace(get_profile=read, list_profiles=read),
                              SimpleNamespace(require_read=lambda p: None), None, validate_support=None)
    with pytest.raises(ValueError):
        if operation == "get":
            service.read_profile("reader", "public-model", 2, protect=None if screen == "absent" else protect)
        else:
            service.list_profiles("reader", protect=None if screen == "absent" else protect)
    if screen == "absent":
        assert calls == []
    assert retained.schema_version == 1


@pytest.mark.parametrize(
    "case", ["valid", "denied", "missing_attempt", "foreign_run", "foreign_principal", "changed_contract"]
)
def test_recovery_read_is_authenticated_and_never_resolves_execution(case):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []
    run = SimpleNamespace(run_id="run", contract_json="retained frozen contract")
    attempt = SimpleNamespace(
        fence=SimpleNamespace(run_id="other" if case == "foreign_run" else "run"),
        authorization=SimpleNamespace(principal="other" if case == "foreign_principal" else "creator"),
        contract_json="different" if case == "changed_contract" else run.contract_json,
    )
    owner = SimpleNamespace(owner_id="original", owner_epoch=1, dirty=True)

    def require_read(principal):
        calls.append("read_authority")
        assert principal == "creator"
        if case == "denied":
            raise PermissionError("read denied")

    def forbidden(*args, **kwargs):
        pytest.fail("recovery read must not probe, resolve grants, or execute")

    store = SimpleNamespace(
        get_run=lambda run_id: calls.append("run") or run,
        get_generation_attempt=lambda run_id: calls.append("attempt")
        or (None if case == "missing_attempt" else attempt),
        get_owner=lambda: calls.append("owner") or owner,
    )
    authority = SimpleNamespace(
        require_read=require_read, require_submit=forbidden, require_execute=forbidden, private_envelope=forbidden
    )
    service = WorkflowService(store, authority, SimpleNamespace(check=forbidden), validate_support=forbidden)
    if case == "valid":
        assert service.read_generation_recovery("creator", "run") == (run, attempt, owner)
        assert calls == ["read_authority", "run", "attempt", "owner"]
    else:
        with pytest.raises(PermissionError if case == "denied" else ValueError):
            service.read_generation_recovery("creator", "run")
        assert calls == (["read_authority"] if case == "denied" else ["read_authority", "run", "attempt"])


@pytest.mark.parametrize("kind", ["candidate", "decision", "assessment", "evidence"])
def test_historical_scene_query_denial_precedes_store_io(kind):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []

    def deny(principal):
        calls.append("read")
        raise PermissionError("read denied")

    def forbidden(*args, **kwargs):
        pytest.fail("denied query performed IO or public projection")

    service = WorkflowService(
        SimpleNamespace(**{"get_scene_" + kind: forbidden}),
        SimpleNamespace(require_read=deny, require_execute=forbidden),
        SimpleNamespace(check=forbidden),
        validate_support=forbidden,
    )
    with pytest.raises(PermissionError, match="read denied"):
        getattr(service, "read_scene_" + kind)("reader", "a" * 64, protect=forbidden)
    assert calls == ["read"]


def historical_scene_views():
    from isaaclab_arena.agentic_environment_generation.workflow.evidence import EvidenceCohort, SceneEvidenceAssessment
    from isaaclab_arena.agentic_environment_generation.workflow.queries import (
        SceneAssessmentView,
        SceneCandidateView,
        SceneDecisionView,
        SceneEvidenceView,
        SceneReadScope,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        Observation,
        SceneDecision,
        candidate_record,
    )

    common = dict(scope=SceneReadScope(database="db", deployment_id="dep", workspace_id="ws"), run_id="run")
    candidate = candidate_record("run", {"text": "private-sentinel"}, source_id="source")
    assessment = SceneEvidenceAssessment(status="not_established", failed_ids=("visible",))
    observation = Observation(
        cohort=EvidenceCohort(
            realization_id="r",
            reset_id="reset",
            environment_id="env",
            window_id="w",
            frame_id="f",
            contract_digest="c" * 64,
            profile_digest="d" * 64,
        ),
        evidence=(),
        verified_manifest_digests=(),
    )
    return {
        "candidate": (candidate.candidate_id, SceneCandidateView(**common, candidate=candidate)),
        "decision": (
            "a" * 64,
            SceneDecisionView(
                **common,
                decision_id="a" * 64,
                candidate_id=candidate.candidate_id,
                decision=SceneDecision(action="stop", reason="private-sentinel", assessment=assessment),
                next_intent_id=None,
                evidence_id="b" * 64,
                selected_assessment_id="e" * 64,
            ),
        ),
        "assessment": (
            "e" * 64,
            SceneAssessmentView(
                **common,
                assessment_id="e" * 64,
                evidence_id="b" * 64,
                candidate_id=candidate.candidate_id,
                assessment=assessment,
            ),
        ),
        "evidence": (
            "b" * 64,
            SceneEvidenceView(
                **common, evidence_id="b" * 64, candidate_id=candidate.candidate_id, observation=observation
            ),
        ),
    }


@pytest.mark.parametrize("kind", ["candidate", "decision", "assessment", "evidence"])
@pytest.mark.parametrize("policy", ["allow", "deny", "mutate", "replace", "missing", "unavailable", "absent"])
def test_historical_query_public_protection_is_distinct_from_read_authority(kind, policy):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    record_id, view = historical_scene_views()[kind]
    calls = []

    def read(principal):
        assert principal == "reader"
        calls.append("read")

    def retained(identity):
        assert identity == record_id
        calls.append("store")
        if policy == "unavailable":
            raise OSError("store unavailable")
        return None if policy == "absent" else view

    def protect(value):
        calls.append("protect")
        if policy == "absent":
            assert value is None
        else:
            assert value == view.model_dump(mode="json")
        if policy == "deny":
            raise PermissionError("public data denied")
        if policy == "mutate":
            value["run_id"] = "changed"
        if policy == "replace":
            return {"redacted": True}
        return None

    def forbidden(*args, **kwargs):
        pytest.fail("query resolved execution authority/readiness")

    service = WorkflowService(
        SimpleNamespace(**{"get_scene_" + kind: retained}),
        SimpleNamespace(require_read=read, require_execute=forbidden, require_submit=forbidden),
        SimpleNamespace(check=forbidden),
        validate_support=forbidden,
    )
    query = getattr(service, "read_scene_" + kind)
    if policy in ("allow", "absent"):
        assert query("reader", record_id, protect=protect) == (None if policy == "absent" else view)
    else:
        error = PermissionError if policy == "deny" else OSError if policy == "unavailable" else ValueError
        with pytest.raises(error):
            query("reader", record_id, protect=None if policy == "missing" else protect)
    expected = ["read"] if policy == "missing" else ["read", "store"]
    if policy not in ("missing", "unavailable"):
        expected.append("protect")
    assert calls == expected
    assert view.run_id == "run"


@pytest.mark.parametrize("policy", ["allow", "deny", "mutate", "replace"])
def test_escape_heavy_candidate_screens_one_complete_typed_response(policy):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import candidate_record
    from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import _protected, canonical
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    _, small = historical_scene_views()["candidate"]
    candidate = candidate_record("run", {"x": "\\" * ((1048576 - 8) // 2)}, source_id="source")
    view = small.model_copy(update={"candidate": candidate})
    calls = []

    def protect(value):
        calls.append(value)
        assert value == view.model_dump(mode="json")  # Full envelope, not chunks.
        if policy == "deny":
            raise PermissionError("denied")
        if policy == "mutate":
            value["candidate"]["source_id"] = "changed"
        if policy == "replace":
            return {"redacted": True}

    service = WorkflowService(
        SimpleNamespace(get_scene_candidate=lambda _: view),
        SimpleNamespace(require_read=lambda _: None), None, validate_support=None,
    )
    # Legacy artifact/default protection ceiling is unchanged and precedes policy.
    for screen in (lambda: canonical(view.model_dump(mode="json")),
                   lambda: _protected(view.model_dump(mode="json"), calls.append)):
        with pytest.raises(ValueError, match="byte bound"):
            screen()
    assert calls == []
    if policy == "allow":
        assert service.read_scene_candidate("reader", candidate.candidate_id, protect=protect) == view
    else:
        with pytest.raises(PermissionError if policy == "deny" else ValueError):
            service.read_scene_candidate("reader", candidate.candidate_id, protect=protect)
    assert len(calls) == 1
    assert view.candidate.source_id == "source"


def test_query_size_extension_is_finite_and_legacy_default_is_unchanged():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.queries import HISTORICAL_CANDIDATE_VIEW_BYTES
    from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import _protected
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []
    boundary = "x" * (2 * 1024 * 1024 - 2)  # JSON string adds two quote bytes.
    assert len(_protected(boundary, lambda _: None)) == 2 * 1024 * 1024
    with pytest.raises(ValueError, match="byte bound"):
        _protected(boundary + "x", calls.append)
    record_id, view = historical_scene_views()["candidate"]
    oversized = view.model_copy(update={
        "scope": view.scope.model_copy(update={"database": "x" * HISTORICAL_CANDIDATE_VIEW_BYTES})
    })
    service = WorkflowService(
        SimpleNamespace(get_scene_candidate=lambda _: oversized),
        SimpleNamespace(require_read=lambda _: None), None, validate_support=None,
    )
    with pytest.raises(ValueError, match="byte bound"):
        service.read_scene_candidate("reader", record_id, protect=calls.append)
    assert not calls


def contract(*, policy=False, existing=False):
    profile = {"profile_id": "synthetic", "settings_sha256": "a" * 64}
    criterion = {
        "criterion_id": "visible",
        "kind": "visual",
        "evidence_producer": "visual-v1",
        "requirement": "required",
        "evaluator_version": "1",
        "required_modalities": ["rgb"],
        "coordinate_frames": ["external_camera"],
        "observation_window": {"start_step": 0, "end_step": 1},
        "rubric": "Target is visible",
        "subjects": ["banana"],
        "limit": {"operator": "eq", "value": 1.0, "unit": "boolean"},
    }
    criteria = [criterion]
    if policy:
        criteria.append({
            **criterion,
            "criterion_id": "policy",
            "kind": "policy",
            "required_modalities": ["policy_rollout"],
            "evidence_producer": "policy-v1",
        })
    return parse_contract(
        json.dumps({
            "schema_version": "1",
            "source": (
                {"kind": "existing", "identity": "candidate-1", "content": "opaque-yaml"}
                if existing
                else {"kind": "new", "prompt": "Banana on maple table"}
            ),
            "criteria": criteria,
            "preserved": [],
            "allowed_interventions": [],
            "execution": {
                "generation_model": {**profile, "billing": "free"},
                "assessment_model": {**profile, "billing": "free"},
                "runtime": profile,
                "database": profile,
                "policy": profile if policy else None,
                "capture": profile,
                "seed": 1,
                "timestep_seconds": 0.01,
                "decimation": 1,
                "dcrg": None,
            },
            "budget": {
                "max_candidates": 2,
                "max_revisions": 1,
                "max_runtime_seconds": 60.0,
                "max_model_calls": 8,
                "max_model_tokens": 10000,
                "max_cost_usd": 1.0,
                "max_realizations": 2,
                "max_steps": 100,
                "max_observations": 2,
                "max_policy_episodes": 2 if policy else 0,
                "max_policy_steps": 100 if policy else 0,
                "per_operation_timeout_seconds": 10.0,
                "total_deadline_seconds": 60.0,
            },
            "effects": {
                "allow_paid_models": False,
                "allow_runtime": True,
                "allow_database_reads": False,
                "allow_operational_writes": True,
                "allow_publication": False,
            },
        })
    )


def test_full_policy_request_checks_policy_before_generation_factory():
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import required_dependencies

    calls = []

    def probe(required, timeout):
        calls.append(required.dependency_id)
        return DependencyResult(
            required.dependency_id,
            "unavailable" if required.dependency_id == "policy" else "passed",
            required.profile_sha256,
            profile_id=required.profile_id,
        )

    gate = DependencyGate(probe)
    report, _ = gate.execute(
        required_dependencies(contract(policy=True)), lambda: calls.append("initialization_ping"), timeout_s=5
    )
    assert report.blockers == ("policy",)
    assert "initialization_ping" not in calls
    assert {"runtime", "neo4j", "generation_model", "assessment_model", "capture", "gpu", "policy"} == set(calls)


def test_scene_only_positive_control_does_not_require_policy():
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import required_dependencies

    calls = []

    def probe(required, timeout):
        calls.append(required.dependency_id)
        return DependencyResult(
            required.dependency_id, "passed", required.profile_sha256, profile_id=required.profile_id
        )

    report, _ = DependencyGate(probe).execute(
        required_dependencies(contract()), lambda: calls.append("initialization_ping"), timeout_s=5
    )
    assert report.ready
    assert "policy" not in calls
    assert calls[-1] == "initialization_ping" and calls.count("initialization_ping") == 1


def test_existing_verification_without_repair_does_not_require_generation():
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import required_dependencies

    names = {item.dependency_id for item in required_dependencies(contract(existing=True))}
    assert "generation_model" not in names and "assessment_model" in names


@pytest.mark.parametrize("unavailable", ["runtime", "neo4j", "generation_model", "assessment_model", "capture", "gpu"])
def test_each_required_scene_dependency_blocks_all_model_construction(unavailable):
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import required_dependencies

    calls = []

    def probe(required, timeout):
        return DependencyResult(
            required.dependency_id,
            "unavailable" if required.dependency_id == unavailable else "passed",
            required.profile_sha256,
            profile_id=required.profile_id,
        )

    report, _ = DependencyGate(probe).execute(
        required_dependencies(contract()), lambda: calls.append("initialization_ping"), timeout_s=5
    )
    assert report.blockers == (unavailable,) and calls == []


def test_probe_timeout_blocks_construction_without_exception_leakage():
    def probe(required, timeout):
        raise TimeoutError("synthetic-private-detail")

    from isaaclab_arena.agentic_environment_generation.workflow.readiness import required_dependencies

    calls = []
    report, _ = DependencyGate(probe).execute(
        required_dependencies(contract()), lambda: calls.append("initialization_ping"), timeout_s=5
    )
    assert not report.ready and calls == []
    assert all(item.code == "probe_timeout" for item in report.results)
    assert "synthetic-private-detail" not in repr(report)


@pytest.mark.parametrize("allow_writes", [False, True])
def test_exact_submission_replay_skips_resolution_probes_and_execution_authority(allow_writes):
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []
    retained = object()

    class Store:
        def lookup_submission(self, operation_id, request_json):
            calls.append("lookup")
            return retained

    class Authority:
        def require_read(self, principal):
            calls.append("read_authority")

        def require_submit(self, principal, operation_id, request):
            raise AssertionError("replay must not capture execution authority")

    def forbidden(*args):
        raise AssertionError("replay must not resolve profiles, probe or dispatch")

    service = WorkflowService(Store(), Authority(), DependencyGate(forbidden), validate_support=forbidden)
    raw = contract().model_dump(mode="json")
    raw["effects"]["allow_operational_writes"] = allow_writes
    result = service.submit("local-principal", "operation-1", json.dumps(raw))
    assert result.run is retained and result.disposition == "retained"
    assert calls == ["read_authority", "lookup"]


@pytest.mark.parametrize("ready", [False, True])
def test_fresh_admission_checks_support_authority_and_whole_readiness_before_store(ready):
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []
    accepted = object()

    class Store:
        def lookup_submission(self, operation_id, request_json):
            calls.append("lookup")

        def admit(self, operation_id, request_json, contract_json, max_pending):
            calls.append("admit")
            assert operation_id == "operation-1" and request_json == contract_json and max_pending == 1
            return accepted

    class Authority:
        def require_read(self, principal):
            calls.append("read_authority")

        def require_submit(self, principal, operation_id, request):
            calls.append("submit_authority")

    def supported(request):
        calls.append("supported")

    def probe(required, timeout):
        calls.append("probe:" + required.dependency_id)
        return DependencyResult(
            required.dependency_id,
            "passed" if ready else "unavailable",
            required.profile_sha256,
            profile_id=required.profile_id,
        )

    service = WorkflowService(Store(), Authority(), DependencyGate(probe), validate_support=supported)
    result = service.submit("local-principal", "operation-1", json.dumps(contract().model_dump(mode="json")))
    assert calls[:4] == ["read_authority", "lookup", "supported", "submit_authority"]
    assert result.disposition == ("accepted" if ready else "dependencies_not_ready")
    assert result.run is (accepted if ready else None)
    assert result.readiness.ready is ready
    assert ("admit" in calls) is ready
    if ready:
        assert calls[-2:] == ["submit_authority", "admit"]


def test_fresh_submission_without_operational_write_permission_stops_before_probes():
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []

    class Store:
        def lookup_submission(self, *args):
            return None

        def admit(self, *args):
            calls.append("write")

    class Authority:
        def require_read(self, principal):
            pass

        def require_submit(self, principal, operation_id, request):
            calls.append("submit_authority")

    def probe(*args):
        calls.append("probe")

    raw = contract().model_dump(mode="json")
    raw["effects"]["allow_operational_writes"] = False
    service = WorkflowService(Store(), Authority(), DependencyGate(probe), validate_support=lambda request: None)
    with pytest.raises(ValueError, match="operational_writes_not_permitted"):
        service.submit("principal", "operation-1", json.dumps(raw))
    assert calls == []


@pytest.mark.parametrize("operation_id", [None, "", True, [], "a" * 129, "a/b", " a", "a\n", "é", "-a"])
def test_invalid_operation_id_stops_after_read_auth_before_any_io(operation_id):
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []

    class Authority:
        def require_read(self, principal):
            calls.append("read")

    class Store:
        def lookup_submission(self, *args):
            calls.append("lookup")
            raise AssertionError("invalid operation must not reach store")

    service = WorkflowService(Store(), Authority(), None, validate_support=None)
    with pytest.raises(ValueError, match="operation"):
        service.submit("principal", operation_id, json.dumps(contract().model_dump(mode="json")))
    assert calls == ["read"]


def test_frozen_profile_ids_propagate_separately_from_instance_ids():
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import required_dependencies

    requests = required_dependencies(contract(policy=True))
    assert all(item.profile_id == "synthetic" and item.instance_id is None for item in requests)


def test_revoke_during_probe_blocks_admission():
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    revoked = []

    class Authority:
        def require_read(self, principal):
            pass

        def require_submit(self, principal, operation_id, request):
            if revoked:
                raise PermissionError("revoked")

    class Store:
        def lookup_submission(self, *args):
            return None

        def admit(self, *args):
            pytest.fail("revoked request admitted")

    def probe(required, timeout):
        revoked.append(True)
        return DependencyResult(
            required.dependency_id, "passed", required.profile_sha256, profile_id=required.profile_id
        )

    service = WorkflowService(Store(), Authority(), DependencyGate(probe), validate_support=lambda _: None)
    with pytest.raises(PermissionError, match="revoked"):
        service.submit("principal", "op", json.dumps(contract().model_dump(mode="json")))


@pytest.mark.parametrize(
    "error_name",
    ["StoreUnavailable", "SubmissionConflict", "OutcomeUnknown", "SchemaMissing", "OSError", "TypeError", "ValueError"],
)
def test_lookup_catches_only_classified_store_unavailable(error_name):
    from isaaclab_arena.agentic_environment_generation.workflow import neo4j_store
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    errors = {"OSError": OSError, "TypeError": TypeError, "ValueError": ValueError}
    error_type = errors[error_name] if error_name in errors else getattr(neo4j_store, error_name)
    error = error_type("private detail")
    calls = []

    class Authority:
        def require_read(self, principal):
            calls.append("read")

    class Store:
        def lookup_submission(self, *args):
            calls.append("lookup")
            raise error

        def admit(self, *args):
            pytest.fail("outage must not admit")

    def forbidden(*args):
        pytest.fail("lookup failure must not resolve or probe")

    service = WorkflowService(Store(), Authority(), DependencyGate(forbidden), validate_support=forbidden)
    raw = json.dumps(contract().model_dump(mode="json"))
    if error_name == "StoreUnavailable":
        result = service.submit("principal", "op", raw)
        assert result.disposition == "dependencies_not_ready" and result.run is None
        assert result.readiness.blockers == ("neo4j",)
        observation = result.readiness.results[0]
        assert observation.profile_id == "synthetic" and observation.profile_sha256 == "a" * 64
        assert observation.status == "unavailable" and observation.code == "probe_failed"
        assert "private detail" not in repr(result)
    else:
        with pytest.raises(type(error)) as caught:
            service.submit("principal", "op", raw)
        assert caught.value is error
    assert calls == ["read", "lookup"]


def test_admit_outcome_unknown_is_not_relabelled_or_retried():
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []

    class Authority:
        def require_read(self, principal):
            pass

        def require_submit(self, principal, operation_id, request):
            pass

    class Store:
        def lookup_submission(self, *args):
            return None

        def admit(self, *args):
            calls.append("admit")
            raise OutcomeUnknown("unknown")

    def probe(required, timeout):
        return DependencyResult(
            required.dependency_id, "passed", required.profile_sha256, profile_id=required.profile_id
        )

    service = WorkflowService(Store(), Authority(), DependencyGate(probe), validate_support=lambda _: None)
    with pytest.raises(OutcomeUnknown):
        service.submit("principal", "op", json.dumps(contract().model_dump(mode="json")))
    assert calls == ["admit"]


@pytest.mark.parametrize("kind", ["other_store", "fake_service", "subclass"])
def test_completion_constructor_rejects_untrusted_or_cross_store_adopter(kind):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import GenerationCoordinator
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    f = coordinator_fixture()
    coordinator = f.coordinator

    class FakeService:
        bound_store = coordinator._store

        def adopt_generation(self, *args, **kwargs):
            pytest.fail("untrusted adopter must never run")

    class Subclass(WorkflowService):
        pass

    service = FakeService()
    if kind != "fake_service":
        cls = Subclass if kind == "subclass" else WorkflowService
        service = cls(
            object() if kind == "other_store" else coordinator._store,
            coordinator._authority,
            None,
            validate_support=lambda _: None,
        )
    with pytest.raises(ValueError, match="same-store"):
        GenerationCoordinator(
            coordinator._store,
            coordinator._authority,
            coordinator._gate,
            coordinator._worker,
            run_id="run",
            principal="creator",
            lease=coordinator._lease,
            readiness_clock=coordinator._clock,
            workflow_service=service,
        )
    assert "prepare" not in f.calls and "send" not in f.calls and "stop" not in f.calls


def coordinator_fixture():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        AttemptFence,
        AuthorizationSnapshot,
        GenerationReservation,
        ReadinessReceipt,
        WorkerRegistration,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json, contract_digest
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import GenerationCoordinator, PreparedWorker
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import ReadinessClock
    from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence

    calls = []
    request = contract()
    state = SimpleNamespace(revoked=False, absent=False, db_down=False, prepare_hook=None, send_error=False)
    fence = AttemptFence(
        run_id="run",
        intent_id="intent",
        attempt_id="attempt",
        generation=1,
        owner_id="owner",
        owner_epoch=1,
    )
    registration = WorkerRegistration(
        registration_id="worker",
        fence=fence,
        host="host",
        boot="boot",
        pid=10,
        pgid=10,
        sid=10,
        start_ticks=10,
    )
    prepared = PreparedWorker(registration, object())
    authorization = AuthorizationSnapshot(
        database="neo4j",
        deployment_id="dep",
        workspace_id="ws",
        principal="creator",
        grant_ref="grant",
        contract_digest=contract_digest(request),
        expires_at=1000.0,
        capabilities=("generation_model", "operational_writes"),
    )

    class Store:
        dependency_instances = {}

        def get_run(self, run_id):
            calls.append("get_run")
            if state.db_down:
                raise OSError("private outage")
            return SimpleNamespace(
                run_id=run_id,
                contract_json=canonical_json(request),
                version=1,
                state="pending",
                phase="generation",
            )

        def reserve_generation(self, run_id, version, decision, auth, reservation, *, readiness):
            assert type(readiness) is ReadinessReceipt
            assert readiness.contract_digest == contract_digest(request) and auth == authorization
            calls.append("reserve")
            return "intent"

        def begin_owner(self, owner_id):
            calls.append("owner")
            return 1

        def claim_intent(self, intent, owner_id, epoch):
            calls.append("claim")
            return fence

        def register_worker(self, actual_fence, actual_registration):
            assert actual_fence == fence and actual_registration == registration
            calls.append("register")
            return registration

        def release_attempt(self, actual_fence, registration_id, auth, *, readiness):
            assert actual_fence == fence and registration_id == registration.registration_id
            assert type(readiness) is ReadinessReceipt and auth == authorization
            calls.append("release")
            return True

        def request_cancel(self, run_id, version):
            calls.append("cancel_db")
            if state.db_down:
                raise OSError("private outage")
            return SimpleNamespace(state="cancel_requested")

        def acknowledge_cleanup(self, actual_fence, evidence):
            assert actual_fence == fence and evidence.registration == registration
            calls.append("ack")

    class Authority:
        def require_read(self, principal):
            assert principal == "creator"
            calls.append("read_auth")

        def require_execute(self, principal, request, *, run_id, fence=None):
            assert run_id == "run"
            assert fence == (None if "claim" not in calls else registration.fence)
            assert principal == "creator" and request == contract()
            calls.append("execute_auth")
            if state.revoked:
                raise PermissionError("private revoked")
            return authorization

        def release_guard(self, principal, request, fence, registration):
            from contextlib import nullcontext

            return nullcontext()

        def private_envelope(self, principal, request, actual_fence, actual_registration):
            assert actual_fence == fence and actual_registration == registration
            calls.append("envelope")
            return b"secret"

    class Lease:
        owner_id = "owner"

        def mark_prepared(self, fence):
            assert fence.owner_id == self.owner_id

        def require_held(self, run_id, principal):
            assert (run_id, principal) == ("run", "creator")
            calls.append("lease")

    class Worker:
        def prepare(self, actual_fence, request, *, timeout_s):
            calls.append("prepare")
            assert actual_fence == fence and 0 < timeout_s <= 10
            if state.prepare_hook:
                state.prepare_hook()
            return prepared

        def send(self, actual, envelope, *, timeout_s):
            assert actual is prepared and envelope == b"secret"
            assert calls[-4:] == ["release", "envelope", "execute_auth", "lease"]
            calls.append("send")
            if state.send_error:
                raise OSError("secret")

        def stop_owned(self, actual, *, timeout_s):
            assert actual is prepared
            calls.append("stop")
            return CleanupEvidence(
                registration=registration,
                evidence_ref="stopped",
                observation="owned_process_group_stopped",
                remote_effects="unknown",
            )

    def probe(required, timeout):
        calls.append("probe:" + required.dependency_id)
        return DependencyResult(
            required.dependency_id,
            "unavailable" if state.absent else "passed",
            required.profile_sha256,
            profile_id=required.profile_id,
        )

    def clock():
        return 100.0

    store, worker = Store(), Worker()
    coordinator = GenerationCoordinator(
        store,
        Authority(),
        DependencyGate(probe, clock=clock),
        worker,
        run_id="run",
        principal="creator",
        lease=Lease(),
        readiness_clock=ReadinessClock.capture(monotonic=clock, wall_clock=clock),
    )
    reservation = GenerationReservation(
        model_calls=2,
        model_tokens=100,
        cost_ceiling_usd=0.0,
        runtime_allowance_seconds=5.0,
    )

    def dispatch():
        return coordinator.dispatch("creator", expected_version=1, decision_id="decision", reservation=reservation)

    return SimpleNamespace(
        coordinator=coordinator,
        dispatch=dispatch,
        calls=calls,
        state=state,
        prepared=prepared,
        store=store,
        worker=worker,
    )


@pytest.mark.parametrize("claim_changed", [False, True])
def test_keyed_generation_dispatch_pins_actual_first_claim(claim_changed):
    import inspect

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import GenerationReservation
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete

    f = coordinator_fixture()
    assert "resume_operation_id" in inspect.signature(f.coordinator.dispatch).parameters
    reservation = GenerationReservation(
        model_calls=2, model_tokens=100, cost_ceiling_usd=0, runtime_allowance_seconds=5
    )
    f.store.pending_generation = lambda run: dict(intent_id="intent", reservation=reservation)
    claims, marks = [], []

    def claim(intent, owner, epoch, *, resume_operation_id=None):
        claims.append((intent, owner, epoch, resume_operation_id))
        if claim_changed:
            raise ValueError("Resume selection changed")
        f.calls.append("claim")
        return f.prepared.registration.fence

    f.store.claim_intent = claim
    f.coordinator._lease.mark_prepared = marks.append
    kwargs = dict(
        expected_version=1,
        decision_id="decision",
        reservation=reservation,
        pending_intent="intent",
        resume_operation_id="resume-key",
    )
    if claim_changed:
        with pytest.raises(DispatchIncomplete):
            f.coordinator.dispatch("creator", **kwargs)
        assert marks == [] and "prepare" not in f.calls and "send" not in f.calls
    else:
        handle = f.coordinator.dispatch("creator", **kwargs)
        assert f.coordinator.dispatch("creator", **kwargs) is handle
        assert f.calls.count("prepare") == f.calls.count("send") == 1
        with pytest.raises(ValueError, match="conflicting local dispatch"):
            f.coordinator.dispatch("creator", **(kwargs | {"resume_operation_id": None}))
    assert claims == [("intent", "owner", 1, "resume-key")]
    assert "reserve" not in f.calls


def test_keyed_dispatch_without_existing_intent_never_reserves_or_prepares():
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import GenerationReservation

    f = coordinator_fixture()
    with pytest.raises(ValueError, match="Keyed dispatch requires an existing intent"):
        f.coordinator.dispatch(
            "creator",
            expected_version=1,
            decision_id="decision",
            reservation=GenerationReservation(
                model_calls=2, model_tokens=100, cost_ceiling_usd=0, runtime_allowance_seconds=5
            ),
            resume_operation_id="resume",
        )
    assert "reserve" not in f.calls and "prepare" not in f.calls and "owner" not in f.calls


def keyed_scene_fixture():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.commands import (
        ResumeSelection,
        command_digest,
        command_json,
        make_resume_receipt,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
    from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import SceneIntent, ScenePortProfile
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    f = coordinator_fixture()
    calls, claims = [], []
    reservation = dict(model_calls=1, model_tokens=1, cost_ceiling_usd=0, runtime_allowance_seconds=1)
    profile = ScenePortProfile(
        port_id="synthetic",
        assurance="synthetic",
        owned_worker=True,
        producer_ids=("scene.visible",),
        observe=reservation,
        repair=reservation,
    )
    run = f.store.get_run("run")
    run.version, run.state = 2, "running"
    intent = SceneIntent(
        intent_id="a" * 64, candidate_id="c" * 64, action="repair", status="reserved", reservation=reservation
    )
    snapshot = SimpleNamespace(run=run, profile=profile, intent=intent, candidate=None, original=None)
    state = SimpleNamespace(claim_error=False, replace=False)
    selection = ResumeSelection(
        run_id="run", version=1, contract_digest=contract_digest(contract()), branch="scene", intent_id=intent.intent_id
    )
    text = command_json(dict(runId="run", expectedVersion=1, renewAuthorization=False))
    receipt = make_resume_receipt(
        scope=dict(database="neo4j", deployment_id="dep", workspace_id="ws"),
        operation_id="scene-resume",
        run_id="run",
        payload_json=text,
        payload_digest=command_digest(text),
        before_version=1,
        after_version=2,
        selection=selection.model_dump(mode="json"),
        contract_digest=selection.contract_digest,
        disposition="continuation_admitted",
        reason=None,
        authorization_action="none",
        events=[dict(sequence=2, kind="ResumeAdmitted", source_id=intent.intent_id)],
    )

    def claim(run_id, intent_id, owner, epoch, *, resume_operation_id=None):
        claims.append((intent_id, resume_operation_id))
        if state.replace:
            snapshot.intent = intent.model_copy(update={"intent_id": "b" * 64})
            raise ValueError("Resume selection changed")
        fence = f.prepared.registration.fence.model_copy(update={"intent_id": intent_id})
        snapshot.intent = snapshot.intent.model_copy(update={"worker_fence": fence})
        if state.claim_error:
            from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown

            raise OutcomeUnknown("claim ACK unknown")
        return fence

    def prepare(intent, *args):
        calls.append("prepare")
        return f.prepared.registration.model_copy(update={"fence": intent.worker_fence})

    def register(fence, registration):
        snapshot.intent = snapshot.intent.model_copy(update={"worker_registration": registration})

    def release(*args, **kwargs):
        snapshot.intent = snapshot.intent.model_copy(update={"status": "released"})
        return True

    def finish(*args):
        calls.append("finish")
        run.version += 1
        if len(claims) == 2:
            run.state = "stopped"
        else:
            snapshot.intent = intent.model_copy(update={"intent_id": "b" * 64})

    def cleanup(intent):
        calls.append("cleanup")
        return CleanupEvidence(
            registration=intent.worker_registration,
            evidence_ref="stopped",
            observation="owned_process_group_stopped",
            remote_effects="unknown",
        )

    ports = SimpleNamespace(
        profile=profile,
        authorize=lambda *a: calls.append("authorize"),
        ready=lambda *a: calls.append("ready"),
        require_bounded_capability=lambda *a: True,
        require_held_owner=lambda: SimpleNamespace(owner_id="owner", owner_epoch=1),
        prepare_worker=prepare,
        cleanup_worker=cleanup,
        execute=lambda *a: {"synthetic": True},
        validate_candidate=lambda *a: None,
    )
    store = SimpleNamespace(
        scene_snapshot=lambda r: snapshot,
        claim_scene_worker=claim,
        register_scene_worker=register,
        release_scene=release,
        check_scene_release=lambda *a, **kw: snapshot.intent,
        get_run=lambda r: run,
        finish_scene=finish,
        acknowledge_scene_cleanup=lambda *a: None,
        mark_scene_unknown=lambda *a: calls.append("unknown"),
    )
    service = WorkflowService(store, f.coordinator._authority, None, validate_support=None)
    return SimpleNamespace(
        service=service,
        store=store,
        ports=ports,
        receipt=receipt,
        snapshot=snapshot,
        state=state,
        calls=calls,
        claims=claims,
    )


@pytest.mark.parametrize("fault", [None, "stale", "replacement", "claim_unknown"])
def test_keyed_scene_first_claim_only_and_stale_pin_never_marks_replacement_unknown(fault):
    import inspect

    t = keyed_scene_fixture()
    assert "resume_receipt" in inspect.signature(t.service.run_scene).parameters
    if fault == "stale":
        t.snapshot.run.version += 1
    t.state.replace = fault == "replacement"
    t.state.claim_error = fault == "claim_unknown"
    if fault:
        with pytest.raises(Exception):
            t.service.run_scene("creator", "run", ports=t.ports, resume_receipt=t.receipt)
        assert "prepare" not in t.calls and "unknown" not in t.calls
        if fault == "stale":
            assert t.claims == [] and t.calls == []
        if fault == "claim_unknown":
            assert t.snapshot.intent.worker_fence is not None, "ambiguous claimed ACK retains the fence obligation"
        if fault == "replacement":
            assert t.snapshot.intent.intent_id == "b" * 64 and t.snapshot.intent.worker_fence is None
    else:
        result = t.service.run_scene("creator", "run", ports=t.ports, resume_receipt=t.receipt)
        assert result.run.state == "stopped"
        assert t.claims == [("a" * 64, "scene-resume"), ("b" * 64, None)]
        assert t.calls.count("prepare") == t.calls.count("cleanup") == 2


@pytest.mark.parametrize("changed", [False, True])
def test_generation_recovery_read_pins_full_fence_without_execution(changed):
    import inspect
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    f = coordinator_fixture()
    fence = f.prepared.registration.fence
    requested = fence.model_copy(update={"owner_epoch": 2}) if changed else fence
    calls = []
    run = f.store.get_run("run")
    attempt = SimpleNamespace(
        fence=fence,
        authorization=SimpleNamespace(principal="creator"),
        registration=f.prepared.registration,
        contract_json=run.contract_json,
    )

    def exact(expected):
        calls.append(expected)
        return attempt

    f.store.get_attempt = exact
    f.store.get_generation_attempt = lambda *a: pytest.fail("must not reselect by run")
    f.store.get_owner = lambda: None
    service = WorkflowService(f.store, f.coordinator._authority, None, validate_support=None)
    assert "expected_fence" in inspect.signature(service.read_generation_recovery).parameters
    if changed:
        with pytest.raises(ValueError, match="Original generation recovery binding required"):
            service.read_generation_recovery("creator", "run", expected_fence=requested)
    else:
        assert service.read_generation_recovery("creator", "run", expected_fence=requested)[1] is attempt
    assert calls == [requested]
    assert "execute_auth" not in f.calls


def test_owned_receiver_failure_does_not_require_read_or_cancel_user():
    f = coordinator_fixture()
    handle = f.dispatch()
    f.state.db_down = True

    def expired(principal):
        raise PermissionError("expired")

    f.coordinator._authority.require_read = expired
    with pytest.raises(PermissionError):
        f.coordinator.fail_owned(object())
    outcome = f.coordinator.fail_owned(handle.prepared)
    assert outcome.durable_reconciliation_pending and not outcome.cleanup_pending
    assert handle.reconciliation_required and handle.cleanup is not None
    assert "cancel_db" not in f.calls and f.calls.count("stop") == 1
    with pytest.raises(PermissionError):
        f.coordinator.cancel("creator")


def test_coordinator_preparation_latch_and_release_guard_boundaries():
    from contextlib import contextmanager

    f = coordinator_fixture()
    active = []
    marked = []

    @contextmanager
    def guard(principal, request, fence, registration):
        assert "release" in f.calls
        active.append(True)
        try:
            yield
        finally:
            active.pop()

    f.coordinator._authority.release_guard = guard
    f.coordinator._lease.mark_prepared = lambda fence: marked.append(fence)
    prepare = f.worker.prepare
    send = f.worker.send

    def checked_prepare(fence, request, **kwargs):
        assert marked == [fence]
        return prepare(fence, request, **kwargs)

    def checked_send(*args, **kwargs):
        assert active == [True]
        return send(*args, **kwargs)

    f.worker.prepare, f.worker.send = checked_prepare, checked_send
    f.dispatch()
    assert not active


@pytest.mark.parametrize("revoke_before_guard", [False, True])
def test_coordinator_threaded_guard_and_cancellation_lock_order(revoke_before_guard):
    from contextlib import contextmanager
    from threading import Event, RLock, Thread

    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete

    f = coordinator_fixture()
    authority_lock = RLock()
    entered, resume, cancelling, cancelled = Event(), Event(), Event(), Event()
    errors = []

    @contextmanager
    def guard(*args):
        with authority_lock:
            if revoke_before_guard:
                raise PermissionError("revoked before final guard")
            yield

    read = f.coordinator._authority.require_read

    def locked_read(principal):
        with authority_lock:
            read(principal)

    f.coordinator._authority.require_read = locked_read
    f.coordinator._authority.release_guard = guard
    send = f.worker.send

    def waiting_send(*args, **kwargs):
        entered.set()
        assert resume.wait(2)
        send(*args, **kwargs)

    f.worker.send = waiting_send

    def dispatch():
        try:
            f.dispatch()
        except DispatchIncomplete:
            errors.append("denied")

    def cancel():
        cancelling.set()
        f.coordinator.cancel("creator")
        cancelled.set()

    thread = Thread(target=dispatch)
    thread.start()
    if revoke_before_guard:
        thread.join(2)
        assert not thread.is_alive() and errors == ["denied"] and "send" not in f.calls
        return
    assert entered.wait(2)
    stopper = Thread(target=cancel)
    stopper.start()
    assert cancelling.wait(2) and not cancelled.wait(0.1)
    resume.set()
    thread.join(2)
    stopper.join(2)
    assert not thread.is_alive() and not stopper.is_alive() and not errors
    assert cancelled.is_set() and f.calls.index("send") < f.calls.index("stop")


def test_coordinator_missing_guard_never_sends():
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete

    f = coordinator_fixture()
    f.coordinator._authority.release_guard = None
    with pytest.raises(DispatchIncomplete):
        f.dispatch()
    assert "release" in f.calls and "send" not in f.calls and "stop" in f.calls


def test_generation_coordinator_releases_then_sends_once_and_retains_exact_retry():
    f = coordinator_fixture()
    handle = f.dispatch()
    assert handle.prepared is f.prepared
    before = list(f.calls)
    f.state.revoked = True
    assert f.dispatch() is handle
    assert f.calls == before + ["read_auth"]
    assert f.calls.count("execute_auth") == 3
    assert f.calls.count("envelope") == 2
    lifecycle = [c for c in f.calls if c in {"reserve", "owner", "claim", "prepare", "register", "release", "send"}]
    assert lifecycle == [
        "reserve",
        "owner",
        "claim",
        "prepare",
        "register",
        "release",
        "send",
    ]
    assert f.calls.count("probe:gpu") == 2
    assert b"secret" not in repr(handle).encode()


@pytest.mark.parametrize("context", ["run", "fence"])
def test_execution_authority_rejects_wrong_run_or_attempt_context(context):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete

    f = coordinator_fixture()
    original = f.coordinator._authority.require_execute

    def bound_elsewhere(principal, request, *, run_id, fence=None):
        auth = original(principal, request, run_id=run_id, fence=fence)
        if context == "run":
            assert run_id == "run"
            raise PermissionError("grant belongs to another run")
        if fence is not None:
            assert fence == f.prepared.registration.fence
            raise PermissionError("grant belongs to another attempt")
        return auth

    f.coordinator._authority.require_execute = bound_elsewhere
    with pytest.raises(DispatchIncomplete):
        f.dispatch()
    assert "send" not in f.calls and "release" not in f.calls
    assert ("reserve" in f.calls) is (context == "fence")
    assert ("stop" in f.calls) is (context == "fence")


@pytest.mark.parametrize(
    "field,value",
    [
        ("grant_ref", "other"),
        ("principal", "other"),
        ("database", "other"),
        ("workspace_id", "other"),
        ("deployment_id", "other"),
        ("contract_digest", "f" * 64),
        ("capabilities", ("generation_model",)),
        ("expires_at", 2000.0),
    ],
)
def test_final_authorization_must_equal_durable_release_snapshot(field, value):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete

    f = coordinator_fixture()
    original = f.coordinator._authority.require_execute

    def changed(principal, request, *, run_id, fence=None):
        auth = original(principal, request, run_id=run_id, fence=fence)
        return auth.model_copy(update={field: value}) if "release" in f.calls else auth

    f.coordinator._authority.require_execute = changed
    with pytest.raises(DispatchIncomplete) as caught:
        f.dispatch()
    assert "release" in f.calls and "send" not in f.calls
    assert f.calls.count("stop") == 1 and caught.value.handle.reconciliation_required
    assert f.dispatch() is caught.value.handle


@pytest.mark.parametrize("failure", ["dependency", "revoked", "send", "prepare"])
def test_generation_coordinator_failure_fences_retry_and_stops_exact_worker(failure):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete, PrepareFailed

    f = coordinator_fixture()
    if failure == "dependency":
        f.state.absent = True
    elif failure == "revoked":
        f.state.prepare_hook = lambda: setattr(f.state, "revoked", True)
    elif failure == "send":
        f.state.send_error = True
    else:

        def fail():
            raise PrepareFailed(f.prepared)

        f.state.prepare_hook = fail
    with pytest.raises(DispatchIncomplete) as caught:
        f.dispatch()
    retained = caught.value.handle
    assert f.dispatch() is retained
    assert f.calls.count("send") == (1 if failure == "send" else 0)
    assert f.calls.count("prepare") == (0 if failure == "dependency" else 1)
    assert f.calls.count("stop") == (0 if failure == "dependency" else 1)
    assert retained.incomplete
    if failure == "send":
        assert retained.reconciliation_required and retained.prepared is f.prepared
    assert "secret" not in str(caught.value)


def test_generation_coordinator_local_cancel_stops_before_database_outage():
    f = coordinator_fixture()
    handle = f.dispatch()
    f.state.db_down = True
    result = f.coordinator.cancel("creator")
    assert result.durable_cancellation_pending and not result.cleanup_pending
    assert handle.cleanup.registration == f.prepared.registration
    assert f.calls.index("stop") < f.calls.index("get_run", f.calls.index("send"))
    assert f.dispatch() is handle and f.calls.count("send") == 1


def test_generation_coordinator_cancel_during_prepare_never_sends():
    f = coordinator_fixture()
    f.state.prepare_hook = lambda: f.coordinator.cancel("creator")
    handle = f.dispatch()
    assert handle.cleanup.registration == f.prepared.registration
    assert "send" not in f.calls and "release" not in f.calls
    assert f.calls.count("stop") == 1


@pytest.mark.parametrize("release", [False, "unknown", "send_error"])
def test_generation_release_ambiguity_never_resends_and_records_reconciliation(release):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete
    from isaaclab_arena.agentic_environment_generation.workflow.results import ReconciliationReason

    f = coordinator_fixture()

    def release_attempt(*args, **kwargs):
        f.calls.append("release")
        if release == "unknown":
            raise OSError("unknown private commit")
        return release == "send_error"

    def reconcile(fence, reason):
        assert fence == f.prepared.registration.fence
        assert reason is ReconciliationReason.OWNER_OUTCOME_UNCERTAIN
        f.calls.append("reconcile")
        raise OSError("database offline")

    f.store.release_attempt = release_attempt
    f.store.mark_reconciliation_required = reconcile
    f.state.send_error = True
    with pytest.raises(DispatchIncomplete) as caught:
        f.dispatch()
    assert f.dispatch() is caught.value.handle
    assert f.calls.count("send") == (1 if release == "send_error" else 0)
    assert f.calls.index("stop") < f.calls.index("reconcile")
    assert caught.value.handle.durable_reconciliation_pending


def test_generation_cancel_serializes_with_release_send_and_is_creator_only():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    f = coordinator_fixture()
    entered, proceed, cancelling = Event(), Event(), Event()
    original = f.store.release_attempt

    def release(*args, **kwargs):
        entered.set()
        assert proceed.wait(2)
        return original(*args, **kwargs)

    f.store.release_attempt = release

    def cancel():
        cancelling.set()
        return f.coordinator.cancel("creator")

    with ThreadPoolExecutor(max_workers=2) as pool:
        dispatched = pool.submit(f.dispatch)
        assert entered.wait(2)
        cancelled = pool.submit(cancel)
        assert cancelling.wait(2)
        assert "stop" not in f.calls
        proceed.set()
        dispatched.result(3)
        cancelled.result(3)
    assert f.calls.index("release") < f.calls.index("send") < f.calls.index("stop")
    before = list(f.calls)
    with pytest.raises((PermissionError, AssertionError)):
        f.coordinator.cancel("other")
    assert f.calls == before


def test_generation_cancel_retries_cleanup_ack_without_reissuing_versioned_cancel():
    from types import SimpleNamespace

    f = coordinator_fixture()
    f.dispatch()
    f.store.get_run = lambda _: SimpleNamespace(version=8, state="cancel_requested")

    def forbidden(*args):
        pytest.fail("cancel_requested must not be issued with a new version")

    f.store.request_cancel = forbidden
    result = f.coordinator.cancel("creator")
    assert result.durable_cancellation_pending
    assert "ack" in f.calls


def test_generation_stop_failure_retains_exact_cleanup_obligation():
    f = coordinator_fixture()
    handle = f.dispatch()

    def failed_stop(prepared, *, timeout_s):
        assert prepared is f.prepared
        raise OSError("private stop error")

    f.worker.stop_owned = failed_stop
    result = f.coordinator.cancel("creator")
    assert result.cleanup_pending and result.durable_cancellation_pending
    assert handle.cleanup_pending and handle.prepared is f.prepared
    assert "cancel_db" not in f.calls
    assert f.dispatch() is handle and f.calls.count("send") == 1


@pytest.mark.parametrize("case", ["denied", "malformed", "missing", "transport", "unknown", "query", "none", "mutate"])
def test_command_lookup_auth_validation_and_transport_separation(case):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []
    errors = dict(transport=OSError("transport"), unknown=OutcomeUnknown("unknown"), query=ValueError("query"))

    def read(principal):
        calls.append("auth")
        if case == "denied":
            raise PermissionError("denied")

    def lookup(key):
        calls.append("io")
        if case in errors:
            raise errors[case]

    service = WorkflowService(
        SimpleNamespace(get_cancel_receipt=lookup), SimpleNamespace(require_read=read), None, validate_support=None
    )
    protect = None if case == "missing" else lambda value: {} if case == "mutate" else None
    if case == "none":
        assert service.read_command("reader", "CANCEL", "key", protect=protect) is None
    else:
        with pytest.raises((ValueError, PermissionError, OSError, OutcomeUnknown)) as caught:
            service.read_command("reader", "CANCEL", "bad key" if case == "malformed" else "key", protect=protect)
        if case in errors:
            assert caught.value is errors[case]
    assert calls == (["auth"] if case in {"denied", "malformed", "missing"} else ["auth", "io"])


@pytest.mark.parametrize("method", ["list_runs", "read_scope_events"])
@pytest.mark.parametrize("case", ["denied", "unbound", "protect", "zero", "large", "bool", "float", "string", "cursor"])
def test_page_auth_and_static_rejections_precede_all_io(method, case):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.tests.test_environment_workflow_store import scope_binding_body

    calls = []

    class NoIO:
        def __getattr__(self, name):
            pytest.fail("page reached IO: " + name)

    def read(principal):
        calls.append(principal)
        if case == "denied":
            raise PermissionError("revoked")

    service = WorkflowService(
        NoIO(),
        SimpleNamespace(require_read=read),
        NoIO(),
        validate_support=NoIO(),
        read_scope=None if case == "unbound" else ScopeBinding.model_validate(scope_binding_body()),
    )
    assert calls == []
    kwargs = dict(
        first={"zero": 0, "large": 1001, "bool": True, "float": 1.0, "string": "1"}.get(case, 1),
        after="" if case in ("denied", "cursor") else None,
        protect=None if case in ("denied", "protect") else lambda _: None,
    )
    with pytest.raises(PermissionError if case == "denied" else ValueError):
        getattr(service, method)("reader", **kwargs)
    assert calls == ["reader"]


def test_page_envelope_two_mib_rejects_instead_of_silently_dropping_rows():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.paging import MAX_PAGE_BYTES, RunSummary, RunWindow
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.tests.test_environment_workflow_store import scope_binding_body

    binding = ScopeBinding.model_validate(scope_binding_body())
    # Deliberately hostile trusted-port fixture, not accepted retained Neo4j data.
    row = RunSummary.model_construct(
        run_id="a" * 64,
        operation_id="x" * MAX_PAGE_BYTES,
        state="pending",
        phase="generation",
        run_version="1",
        event_cursor="1",
    )
    window = RunWindow.model_construct(binding=binding, floor="0", ceiling="1", runs=(row,))
    service = WorkflowService(
        SimpleNamespace(list_runs_window=lambda *a, **k: window),
        SimpleNamespace(require_read=lambda _: None),
        None,
        validate_support=None,
        read_scope=binding,
    )
    with pytest.raises(ValueError):
        service.list_runs("reader", protect=lambda _: pytest.fail("oversize escaped"))


def test_candidate_parent_query_and_scope_cursor_mismatches_precede_store_io():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        CandidatePosition,
        CursorBindingMismatch,
        CursorQueryMismatch,
        RunPosition,
        encode_cursor,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
        ScopeBinding,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )
    from isaaclab_arena.tests.test_environment_workflow_store import scope_binding_body

    binding = ScopeBinding.model_validate(scope_binding_body())
    called = []

    class NoIO:
        def __getattr__(self, name):
            pytest.fail("unexpected IO " + name)

    service = WorkflowService(
        NoIO(),
        SimpleNamespace(require_read=called.append),
        None,
        validate_support=None,
        read_scope=binding,
    )
    for token, error in (
        (
            encode_cursor(
                binding, CandidatePosition(run_id="b" * 64, position="c" * 64)
            ),
            CursorQueryMismatch,
        ),
        (encode_cursor(binding, RunPosition(position="c" * 64)), CursorQueryMismatch),
        (
            encode_cursor(
                binding.model_copy(update={"authority_id": "other"}),
                CandidatePosition(run_id="a" * 64, position="c" * 64),
            ),
            CursorBindingMismatch,
        ),
    ):
        with pytest.raises(error):
            service.list_scene_candidates(
                "reader", "a" * 64, after=token, protect=lambda _: None
            )
    assert called == ["reader"] * 3


@pytest.mark.parametrize(
    "case",
    [
        "denied",
        "unbound",
        "protect",
        "zero",
        "large",
        "bool",
        "float",
        "string",
        "cursor",
        "oversize_cursor",
        "run_id",
    ],
)
def test_candidate_auth_and_invalid_request_precede_all_io(case):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
        ScopeBinding,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )
    from isaaclab_arena.tests.test_environment_workflow_store import scope_binding_body

    calls = []

    class NoIO:
        def __getattr__(self, name):
            pytest.fail("candidate page reached IO: " + name)

    def read(principal):
        calls.append(principal)
        if case == "denied":
            raise PermissionError("revoked")

    service = WorkflowService(
        NoIO(),
        SimpleNamespace(require_read=read),
        NoIO(),
        validate_support=NoIO(),
        read_scope=(
            None
            if case == "unbound"
            else ScopeBinding.model_validate(scope_binding_body())
        ),
    )
    with pytest.raises(PermissionError if case == "denied" else ValueError):
        service.list_scene_candidates(
            "reader",
            True if case in ("denied", "run_id") else "a" * 64,
            first={
                "zero": 0,
                "large": 1001,
                "bool": True,
                "float": 1.0,
                "string": "1",
            }.get(case, 100),
            after=(
                ""
                if case in ("denied", "cursor")
                else "x" * 4097 if case == "oversize_cursor" else None
            ),
            protect=None if case in ("denied", "protect") else lambda _: None,
        )
    assert calls == ["reader"]


def test_candidate_page_envelope_size_is_reject_only():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        CandidateItem,
        CandidateWindow,
        MAX_PAGE_BYTES,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
        ScopeBinding,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )
    from isaaclab_arena.tests.test_environment_workflow_store import scope_binding_body

    binding = ScopeBinding.model_validate(scope_binding_body())
    row = CandidateItem.model_construct(
        candidate_id="b" * 64, run_id="x" * MAX_PAGE_BYTES
    )
    window = CandidateWindow.model_construct(
        binding=binding, run_id="a" * 64, floor="0", ceiling="1", candidates=(row,)
    )
    service = WorkflowService(
        SimpleNamespace(list_scene_candidates_window=lambda *a, **k: window),
        SimpleNamespace(require_read=lambda _: None),
        None,
        validate_support=None,
        read_scope=binding,
    )
    with pytest.raises(ValueError):
        service.list_scene_candidates(
            "reader", "a" * 64, protect=lambda _: pytest.fail("oversize escaped")
        )


def test_decision_parent_query_and_scope_cursor_mismatches_precede_store_io():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        DecisionPosition,
        CursorBindingMismatch,
        CursorQueryMismatch,
        RunPosition,
        encode_cursor,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
        ScopeBinding,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )
    from isaaclab_arena.tests.test_environment_workflow_store import scope_binding_body

    binding = ScopeBinding.model_validate(scope_binding_body())
    called = []

    class NoIO:
        def __getattr__(self, name):
            pytest.fail("unexpected IO " + name)

    service = WorkflowService(
        NoIO(),
        SimpleNamespace(require_read=called.append),
        None,
        validate_support=None,
        read_scope=binding,
    )
    for token, error in (
        (
            encode_cursor(binding, DecisionPosition(run_id="b" * 64, position="c" * 64)),
            CursorQueryMismatch,
        ),
        (encode_cursor(binding, RunPosition(position="c" * 64)), CursorQueryMismatch),
        (
            encode_cursor(
                binding.model_copy(update={"authority_id": "other"}),
                DecisionPosition(run_id="a" * 64, position="c" * 64),
            ),
            CursorBindingMismatch,
        ),
    ):
        with pytest.raises(error):
            service.list_decisions("reader", "a" * 64, after=token, protect=lambda _: None)
    assert called == ["reader"] * 3


@pytest.mark.parametrize(
    "case",
    [
        "denied",
        "unbound",
        "protect",
        "zero",
        "large",
        "bool",
        "float",
        "string",
        "cursor",
        "oversize_cursor",
        "run_id",
    ],
)
def test_decision_auth_and_invalid_request_precede_all_io(case):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
        ScopeBinding,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )
    from isaaclab_arena.tests.test_environment_workflow_store import scope_binding_body

    calls = []

    class NoIO:
        def __getattr__(self, name):
            pytest.fail("decision page reached IO: " + name)

    def read(principal):
        calls.append(principal)
        if case == "denied":
            raise PermissionError("revoked")

    service = WorkflowService(
        NoIO(),
        SimpleNamespace(require_read=read),
        NoIO(),
        validate_support=NoIO(),
        read_scope=(None if case == "unbound" else ScopeBinding.model_validate(scope_binding_body())),
    )
    with pytest.raises(PermissionError if case == "denied" else ValueError):
        service.list_decisions(
            "reader",
            True if case in ("denied", "run_id") else "a" * 64,
            first={
                "zero": 0,
                "large": 1001,
                "bool": True,
                "float": 1.0,
                "string": "1",
            }.get(case, 100),
            after=("" if case in ("denied", "cursor") else "x" * 4097 if case == "oversize_cursor" else None),
            protect=None if case in ("denied", "protect") else lambda _: None,
        )
    assert calls == ["reader"]


def test_decision_page_envelope_size_is_reject_only():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        DecisionItem,
        DecisionWindow,
        MAX_PAGE_BYTES,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
        ScopeBinding,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )
    from isaaclab_arena.tests.test_environment_workflow_store import scope_binding_body

    binding = ScopeBinding.model_validate(scope_binding_body())
    row = DecisionItem.model_construct(decision_id="b" * 64, run_id="x" * MAX_PAGE_BYTES, record_kind="scene_decision")
    window = DecisionWindow.model_construct(binding=binding, run_id="a" * 64, floor="0", ceiling="1", decisions=(row,))
    service = WorkflowService(
        SimpleNamespace(list_decisions_window=lambda *a, **k: window),
        SimpleNamespace(require_read=lambda _: None),
        None,
        validate_support=None,
        read_scope=binding,
    )
    with pytest.raises(ValueError):
        service.list_decisions("reader", "a" * 64, protect=lambda _: pytest.fail("oversize escaped"))
